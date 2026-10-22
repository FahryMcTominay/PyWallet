"""Dialog Kirim (tahap 4): isi form -> tinjau & konfirmasi dengan password -> status transaksi.

Alur tiga halaman dalam satu dialog:
  0. Form      : pilih aset, alamat tujuan, jumlah. "Lanjut" memeriksa input lalu bertanya ke jaringan
                 (nonce, biaya gas, estimasi gas) di thread terpisah.
  1. Tinjau    : ringkasan lengkap + pilihan kecepatan (Lambat/Normal/Cepat) + master password.
  2. Status    : hash transaksi, lalu dipantau sampai masuk blok.
"""
from __future__ import annotations

import threading
import time
from decimal import Decimal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import tx
from ..formatting import format_amount
from ..networks import NETWORKS
from ..portfolio import AssetRow, PortfolioService
from ..vault import InvalidPassword, SentTx, Vault, VaultError, WalletRecord
from . import theme
from .dialogs import ScreenBase, button
from .token_dialogs import open_url
from .widgets import PasswordField, copy_to_clipboard, label

RECEIPT_POLL_SECONDS = 4
RECEIPT_POLL_ATTEMPTS = 45          # ~3 menit


def plain(amount: Decimal) -> str:
    """Desimal tanpa notasi ilmiah (mis. 0.00001 bukan 1E-5)."""
    text = format(amount, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class SendDialog(ScreenBase):
    _prepared = Signal(int, object)      # (id permintaan, TransferPlan | Exception)
    _broadcasted = Signal(int, object)   # (id, tx_hash | Exception)
    _receipt = Signal(int, object)       # (id, Receipt | None)

    def __init__(
        self,
        vault: Vault,
        service: PortfolioService,
        wallet: WalletRecord,
        rows: list[AssetRow],
        parent: QWidget | None = None,
    ):
        super().__init__("Kirim", parent)
        self.vault, self.service, self.wallet = vault, service, wallet
        self.run_in_thread = True                    # tes mematikannya
        self.sent_hash: str | None = None            # terisi setelah transaksi berhasil dikirim ke jaringan
        self._rows = [r for r in rows if r.has_balance]
        self._rid = 0
        self._plan: tx.TransferPlan | None = None
        self._speed = tx.SPEED_NORMAL
        self._max = False
        self._busy = False
        self._closing = False
        self._tx_network = ""
        self._to_record: SentTx | None = None
        self._prepared.connect(self._on_prepared)
        self._broadcasted.connect(self._on_broadcasted)
        self._receipt.connect(self._on_receipt)

        self.pages = QStackedWidget()
        self.root.addWidget(self.pages)
        self.pages.addWidget(self._build_form())
        self.pages.addWidget(self._build_review())
        self.pages.addWidget(self._build_status())
        self._show_page(0)

    def _show_page(self, index: int) -> None:
        """Pindah halaman; halaman lain tidak ikut menentukan tinggi dialog."""
        for i in range(self.pages.count()):
            page = self.pages.widget(i)
            policy = page.sizePolicy()
            policy.setVerticalPolicy(QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored)
            page.setSizePolicy(policy)
        self.pages.setCurrentIndex(index)
        self.pages.updateGeometry()

    def go_back(self) -> None:
        """← pada halaman tinjau kembali ke form; selain itu keluar dari layar Kirim."""
        if self.pages.currentIndex() == 1 and not self._busy:
            self._show_page(0)
            return
        self.reject()

    # ------------------------------------------------------------------
    # Halaman 0: form
    # ------------------------------------------------------------------
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        return host, lay

    def _build_form(self) -> QWidget:
        host, lay = self._page()
        lay.addWidget(label(f"Dari “{self.wallet.name}”  ·  {self.wallet.short_address}", "muted"))

        self.asset_combo = QComboBox()
        self.addr_edit = QLineEdit()
        self.amount_edit = QLineEdit()
        self.max_btn = button("Maks")
        self.form_err = self.error_label()
        self.next_btn = button("Lanjut", "primary")
        cancel = button("Batal")

        if not self._rows:
            lay.addWidget(
                label(
                    "Belum ada aset dengan saldo di jaringan ini, jadi belum ada yang bisa dikirim. "
                    "Gunakan tombol Terima untuk mengisi saldo dulu (di Sepolia, lewat faucet).",
                    "warnbox",
                    wrap=True,
                )
            )
            cancel.setText("Tutup")
            cancel.clicked.connect(self.reject)
            lay.addLayout(self.button_row(cancel))
            return host

        lay.addWidget(label("Aset", "small"))
        for r in self._rows:
            net = NETWORKS[r.token.network]
            self.asset_combo.addItem(f"{r.token.symbol} · {net.name}   —   saldo {format_amount(r.amount)}")
        lay.addWidget(self.asset_combo)

        lay.addWidget(label("Alamat tujuan", "small"))
        self.addr_edit.setPlaceholderText("0x…")
        self.addr_edit.setMaxLength(66)
        lay.addWidget(self.addr_edit)

        lay.addWidget(label("Jumlah", "small"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.amount_edit.setPlaceholderText("0.0")
        row.addWidget(self.amount_edit, 1)
        row.addWidget(self.max_btn)
        lay.addLayout(row)
        self.balance_lbl = label("", "small")
        lay.addWidget(self.balance_lbl)

        lay.addWidget(self.form_err)
        lay.addWidget(
            label(
                "Pastikan alamat dan jaringan sudah benar. Transaksi blockchain tidak bisa dibatalkan atau "
                "ditarik kembali.",
                "small",
                wrap=True,
            )
        )
        lay.addLayout(self.button_row(cancel, self.next_btn))

        self.asset_combo.currentIndexChanged.connect(self._asset_changed)
        self.amount_edit.textEdited.connect(self._amount_edited)
        self.addr_edit.returnPressed.connect(self.next_btn.click)
        self.amount_edit.returnPressed.connect(self.next_btn.click)
        self.max_btn.clicked.connect(self._fill_max)
        cancel.clicked.connect(self.reject)
        self.next_btn.clicked.connect(self._on_next)
        self._asset_changed()
        return host

    def _current_row(self) -> AssetRow:
        return self._rows[self.asset_combo.currentIndex()]

    def _asset_changed(self, *_args) -> None:
        row = self._current_row()
        net = NETWORKS[row.token.network]
        self._max = False
        self.show_error(self.form_err, "")
        extra = " Sisakan sebagian untuk biaya gas." if row.token.is_native else ""
        self.balance_lbl.setText(f"Saldo: {plain(row.amount)} {row.token.symbol} di {net.name}.{extra}")

    def _amount_edited(self, *_args) -> None:
        self._max = False

    def _fill_max(self) -> None:
        row = self._current_row()
        self.amount_edit.setText(plain(row.amount))
        self._max = True

    def _raw_balance(self, row: AssetRow) -> int:
        return int(row.amount.scaleb(row.token.decimals))

    def _on_next(self) -> None:
        if self._busy:
            return
        row = self._current_row()
        try:
            to = tx.normalize_recipient(self.addr_edit.text())
            amount = tx.parse_amount(self.amount_edit.text(), row.token.decimals)
            balance = self._raw_balance(row)
            if amount > balance:
                raise tx.TransferError(f"Saldo {row.token.symbol} tidak cukup.")
            if to.lower() == self.wallet.address.lower():
                raise tx.TransferError("Alamat tujuan sama dengan alamat wallet kamu sendiri.")
        except tx.TransferError as exc:
            self.show_error(self.form_err, str(exc))
            return
        self.show_error(self.form_err, "")
        # Jika jumlah sama dengan seluruh saldo native, perlakukan sebagai "kirim maks" (biaya dikurangkan).
        send_max = row.token.is_native and (self._max or amount == balance)
        self._start_prepare(row, to, amount, balance, send_max)

    def _start_prepare(self, row: AssetRow, to: str, amount: int, balance: int, send_max: bool) -> None:
        self._busy = True
        self.next_btn.setEnabled(False)
        self.next_btn.setText("Memeriksa jaringan…")
        self._rid += 1
        rid = self._rid
        net = NETWORKS[row.token.network]
        rpc = self.service.rpc_for(net.key)
        sender = self.wallet.address

        def work() -> None:
            try:
                result = tx.prepare_transfer(rpc, net, row.token, sender, to, amount, balance, send_max)
            except Exception as exc:  # noqa: BLE001 - apa pun yang gagal ditampilkan sebagai pesan
                result = exc
            self._emit(self._prepared, rid, result)

        self._run(work)

    def _emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:   # dialog sudah ditutup
            pass

    def _run(self, fn) -> None:
        if self.run_in_thread:
            threading.Thread(target=fn, daemon=True).start()
        else:
            fn()

    def _on_prepared(self, rid: int, result) -> None:
        if rid != self._rid:
            return
        self._busy = False
        if self.next_btn is not None:
            self.next_btn.setEnabled(True)
            self.next_btn.setText("Lanjut")
        if isinstance(result, Exception):
            msg = str(result) if isinstance(result, tx.TransferError) and str(result) else "Gagal menghubungi jaringan."
            if self.pages.currentIndex() == 1:
                self.review_err.setText(msg)
                self.review_err.show()
                self.send_btn.setEnabled(False)
            else:
                self.show_error(self.form_err, msg)
            return
        stale_refresh = self.pages.currentIndex() == 1
        self._plan = result
        self.pw_field.clear()
        self._render_review()
        self._show_page(1)
        if stale_refresh:
            self.review_note.setText("Estimasi biaya sudah diperbarui. Periksa lagi lalu tekan Kirim.")
            self.review_note.show()
        self.pw_field.setFocus()

    # ------------------------------------------------------------------
    # Halaman 1: tinjau & konfirmasi
    # ------------------------------------------------------------------
    def _build_review(self) -> QWidget:
        host, lay = self._page()
        lay.addWidget(label("Tinjau transaksi", "heading"))
        self.summary_card = QWidget()
        self.summary_card.setObjectName("sendSummary")
        self.summary_card.setStyleSheet(
            f"QWidget#sendSummary {{ background: {theme.SURFACE}; border: 1px solid {theme.LINE}; border-radius: 12px; }}"
            "QWidget#sendSummary QLabel { background: transparent; }"
        )
        card_lay = QVBoxLayout(self.summary_card)
        card_lay.setContentsMargins(16, 12, 16, 12)
        card_lay.setSpacing(2)
        self.summary_values: dict[str, QLabel] = {}
        for key, title in (("network", "Jaringan"), ("from", "Dari"), ("to", "Ke"),
                           ("amount", "Jumlah"), ("fee", "Biaya gas (maks)"), ("total", "Total")):
            if key != "network":
                card_lay.addSpacing(8)
            head = label(title, "small")
            value = label("", selectable=True)
            value.setStyleSheet(f"color: {theme.TEXT_STRONG}; font-size: 14px; font-weight: 600;")
            card_lay.addWidget(head)
            card_lay.addWidget(value)
            self.summary_values[key] = value
            self.summary_values[key + "_head"] = head
        lay.addWidget(self.summary_card)

        lay.addWidget(label("Kecepatan (biaya gas)", "small"))
        seg = QHBoxLayout()
        seg.setSpacing(8)
        self.speed_group = QButtonGroup(self)
        self.speed_group.setExclusive(True)
        self.speed_buttons: dict[str, object] = {}
        for i, speed in enumerate(tx.SPEEDS):
            b = button(tx.SPEED_LABELS[speed], "segment")
            b.setCheckable(True)
            b.setChecked(speed == self._speed)
            self.speed_group.addButton(b, i)
            self.speed_buttons[speed] = b
            seg.addWidget(b)
        self.speed_group.idClicked.connect(lambda i: self._set_speed(tx.SPEEDS[i]))
        lay.addLayout(seg)

        self.warn_box = label("", "warnbox", wrap=True)
        self.warn_box.hide()
        lay.addWidget(self.warn_box)
        self.review_note = label("", "small", wrap=True)
        self.review_note.hide()
        lay.addWidget(self.review_note)

        lay.addWidget(label("Masukkan master password untuk menandatangani.", "small"))
        self.pw_field = PasswordField("Master password")
        lay.addWidget(self.pw_field)
        self.review_err = self.error_label()
        lay.addWidget(self.review_err)

        back = button("Kembali")
        self.send_btn = button("Kirim sekarang", "primary")
        lay.addLayout(self.button_row(back, self.send_btn))
        back.clicked.connect(self._back)
        self.send_btn.clicked.connect(self._on_send)
        self.pw_field.returnPressed.connect(self._on_send)
        return host

    def _back(self) -> None:
        if self._busy:
            return
        self._rid += 1
        self._show_page(0)

    def summary_text(self) -> str:
        """Seluruh isi ringkasan sebagai satu teks (dipakai tes)."""
        return "\n".join(
            f"{self.summary_values[k + '_head'].text()}: {self.summary_values[k].text()}"
            for k in ("network", "from", "to", "amount", "fee", "total")
            if not self.summary_values[k].isHidden()
        )

    def _set_speed(self, speed: str) -> None:
        self._speed = speed
        self._render_review()

    def _render_review(self) -> None:
        plan = self._plan
        if plan is None:
            return
        net = NETWORKS[plan.network]
        t = plan.token
        amount = tx.to_units(plan.final_amount(self._speed), t.decimals)
        fee_wei = plan.fee_wei(self._speed)
        fee = tx.to_units(fee_wei, 18)
        native = net.native_symbol
        sv = self.summary_values
        sv["network"].setText(net.name + ("  (testnet)" if net.is_testnet else ""))
        sv["from"].setText(f"{self.wallet.name}  ·  {self.wallet.short_address}")
        sv["to"].setText(plan.to)
        sv["amount"].setText(f"{plain(amount)} {t.symbol}")
        sv["fee"].setText(f"{plain(fee.quantize(Decimal('0.00000001')))} {native}")
        sv["total"].setText(f"{plain(amount + fee)} {t.symbol}" if t.is_native else "")
        for w in (sv["total"], sv["total_head"]):
            w.setVisible(t.is_native)
        warns = list(plan.warnings)
        if not net.is_testnet:
            warns.insert(0, "Ini jaringan utama: dana yang dikirim adalah aset sungguhan dan tidak bisa ditarik kembali.")
        self.warn_box.setText("\n\n".join(warns))
        self.warn_box.setVisible(bool(warns))
        self.review_note.hide()
        try:
            plan.check_funds(self._speed)
            self.review_err.hide()
            self.send_btn.setEnabled(not self._busy)
        except tx.TransferError as exc:
            self.review_err.setText(str(exc))
            self.review_err.show()
            self.send_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Kirim: tanda tangan -> broadcast
    # ------------------------------------------------------------------
    def _on_send(self) -> None:
        plan = self._plan
        if plan is None or self._busy or not self.send_btn.isEnabled():
            return
        pw = self.pw_field.text()
        if not pw:
            self.review_err.setText("Masukkan master password.")
            self.review_err.show()
            return
        if time.time() - plan.created_at > tx.PLAN_MAX_AGE:
            # Nonce dan biaya gas bisa sudah berubah: ambil ulang, lalu minta pengguna menekan Kirim lagi.
            row = next((r for r in self._rows if r.token.key == plan.token.key), None)
            if row is not None:
                self._busy = True
                self.send_btn.setEnabled(False)
                self._start_refresh(plan)
                return
        try:
            raw, tx_hash = self.vault.sign_transfer(self.wallet.id, pw, plan.tx_fields(self._speed))
        except InvalidPassword:
            self.pw_field.clear()
            self.review_err.setText("Password salah.")
            self.review_err.show()
            self.pw_field.setFocus()
            return
        except (VaultError, ValueError, TypeError) as exc:
            self.review_err.setText(str(exc) or "Gagal menandatangani transaksi.")
            self.review_err.show()
            return
        self.pw_field.clear()
        self._busy = True
        self._tx_network = plan.network
        self._to_record = SentTx(
            network=plan.network, tx_hash=tx_hash, wallet_address=self.wallet.address, to_address=plan.to,
            symbol=plan.token.symbol, decimals=plan.token.decimals, token_address=plan.token.address,
            amount_raw=plan.final_amount(self._speed), status="pending", block=None, created_at=int(time.time()),
        )
        self.send_btn.setEnabled(False)
        self.status_title.setText("Mengirim transaksi…")
        self.status_detail.setText("Menandatangani selesai. Mengirim ke jaringan.")
        self._set_status_buttons(done=False)
        self._show_page(2)
        self._rid += 1
        rid = self._rid
        rpc = self.service.rpc_for(plan.network)

        def work() -> None:
            try:
                result = tx.broadcast(rpc, raw)
            except Exception as exc:  # noqa: BLE001
                result = exc
            self._emit(self._broadcasted, rid, result)

        self._run(work)

    def _start_refresh(self, plan: tx.TransferPlan) -> None:
        self._rid += 1
        rid = self._rid
        net = NETWORKS[plan.network]
        rpc = self.service.rpc_for(net.key)

        def work() -> None:
            try:
                result = tx.prepare_transfer(
                    rpc, net, plan.token, plan.sender, plan.to, plan.amount, plan.balance, plan.send_max
                )
            except Exception as exc:  # noqa: BLE001
                result = exc
            self._emit(self._prepared, rid, result)

        self._run(work)

    # ------------------------------------------------------------------
    # Halaman 2: status
    # ------------------------------------------------------------------
    def _build_status(self) -> QWidget:
        host, lay = self._page()
        self.status_title = label("", "heading")
        self.status_detail = label("", "muted", wrap=True)
        self.hash_lbl = label("", "secret", wrap=True, selectable=True)
        self.hash_lbl.hide()
        lay.addWidget(self.status_title)
        lay.addWidget(self.status_detail)
        lay.addWidget(self.hash_lbl)
        lay.addStretch(1)
        self.copy_hash_btn = button("Salin hash")
        self.explorer_btn = button("Lihat di explorer")
        self.close_btn = button("Tutup", "primary")
        self.copy_hash_btn.clicked.connect(
            lambda: copy_to_clipboard(self.sent_hash or "", anchor=self.copy_hash_btn)
        )
        self.explorer_btn.clicked.connect(lambda: open_url(tx.explorer_tx_url(self._tx_network, self.sent_hash or "")))
        self.close_btn.clicked.connect(self.accept)
        lay.addLayout(self.button_row(self.copy_hash_btn, self.explorer_btn, self.close_btn))
        self._set_status_buttons(done=False)
        return host

    def _set_status_buttons(self, done: bool, has_hash: bool = False) -> None:
        self.copy_hash_btn.setVisible(has_hash)
        self.explorer_btn.setVisible(has_hash)
        self.close_btn.setEnabled(True)

    def _on_broadcasted(self, rid: int, result) -> None:
        if rid != self._rid:
            return
        self._busy = False
        if isinstance(result, Exception):
            msg = str(result) if isinstance(result, tx.TransferError) and str(result) else "Gagal mengirim transaksi."
            self.status_title.setText("Transaksi gagal dikirim")
            self.status_detail.setText(f"{msg}\n\nTidak ada dana yang keluar dari wallet.")
            self.status_title.setStyleSheet(f"color: {theme.DANGER};")
            self._set_status_buttons(done=True)
            return
        self.sent_hash = result
        if self._to_record is not None:                     # catat ke riwayat lokal (status: menunggu)
            self.vault.record_sent_tx(self._to_record)
        self.status_title.setStyleSheet("")
        self.status_title.setText("Transaksi terkirim")
        self.status_detail.setText("Menunggu masuk ke blok. Kamu boleh menutup jendela ini; transaksi tetap berjalan.")
        self.hash_lbl.setText(f"Hash transaksi\n{result[:34]}\n{result[34:]}")
        self.hash_lbl.show()
        self._set_status_buttons(done=False, has_hash=True)
        self._poll(rid, result)

    def _poll(self, rid: int, tx_hash: str) -> None:
        rpc = self.service.rpc_for(self._tx_network)
        attempts = RECEIPT_POLL_ATTEMPTS if self.run_in_thread else 1

        def work() -> None:
            receipt = None
            for i in range(attempts):
                if self._closing:
                    return
                receipt = tx.fetch_receipt(rpc, tx_hash)
                if receipt is not None:
                    break
                if i < attempts - 1:
                    time.sleep(RECEIPT_POLL_SECONDS)
            self._emit(self._receipt, rid, receipt)

        self._run(work)

    def _on_receipt(self, rid: int, receipt) -> None:
        if rid != self._rid:
            return
        if receipt is not None and self.sent_hash:
            self.vault.set_tx_status(self._tx_network, self.sent_hash, "success" if receipt.success else "failed", receipt.block)
        if receipt is None:
            self.status_title.setText("Masih menunggu konfirmasi")
            self.status_detail.setText(
                "Transaksi sudah dikirim tetapi belum masuk blok. Jaringan mungkin sedang padat. "
                "Cek statusnya di explorer; saldo di lobi akan menyesuaikan setelah selesai."
            )
        elif receipt.success:
            self.status_title.setText("Berhasil ✓")
            self.status_detail.setText(f"Transaksi masuk ke blok {receipt.block}. Saldo di lobi akan diperbarui.")
        else:
            self.status_title.setStyleSheet(f"color: {theme.DANGER};")
            self.status_title.setText("Transaksi gagal di blockchain")
            self.status_detail.setText(
                "Transaksi masuk blok tetapi dibatalkan oleh jaringan (status gagal). "
                "Biaya gas tetap terpotong. Lihat rinciannya di explorer."
            )

    # ------------------------------------------------------------------
    def done(self, result: int) -> None:
        self._closing = True
        self._rid += 1
        super().done(result)
