"""Layar Swap (tahap 5): pilih pasangan token -> tinjau kutipan harga + password -> izin (bila perlu) -> swap -> status.

Alur tiga halaman dalam satu layar, mirip Kirim:
  0. Form    : token jual + jumlah, token terima, slippage. "Lihat harga" meminta kutipan dari kontrak DEX (thread).
  1. Tinjau  : kutipan, minimum diterima, biaya, dan master password.
  2. Status  : izin token (bila perlu) -> transaksi swap -> dipantau sampai masuk blok.

Penandatanganan memakai SQLite lewat Vault sehingga selalu di thread utama; jaringan (kutipan, estimasi gas,
kirim, tunggu blok) di thread terpisah. Password hanya disimpan di memori selama proses berjalan.
"""
from __future__ import annotations

import threading
import time
from decimal import Decimal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import swap, tx
from ..formatting import format_amount
from ..networks import NETWORKS
from ..portfolio import AssetRow, PortfolioService
from ..vault import InvalidPassword, SentTx, Vault, VaultError, WalletRecord
from . import theme
from .dialogs import ScreenBase, button
from .send_dialog import RECEIPT_POLL_ATTEMPTS, RECEIPT_POLL_SECONDS, plain
from .token_dialogs import open_url
from .widgets import PasswordField, copy_to_clipboard, label


class SwapScreen(ScreenBase):
    _prepared = Signal(int, object)          # (id, SwapPlan | Exception)
    _step = Signal(int, str, object)         # (id, nama langkah, hasil | Exception)
    _receipt = Signal(int, object)           # (id, Receipt | None)

    def __init__(
        self,
        vault: Vault,
        service: PortfolioService,
        wallet: WalletRecord,
        rows: list[AssetRow],
        parent: QWidget | None = None,
    ):
        super().__init__("Swap", parent)
        self.vault, self.service, self.wallet = vault, service, wallet
        self.run_in_thread = True                    # tes mematikannya
        self.sent_hash: str | None = None            # terisi setelah transaksi swap terkirim
        nets = swap.swap_networks(tuple(dict.fromkeys(r.token.network for r in rows)))
        self._rows = [r for r in rows if r.token.network in nets]
        self._sell_rows = [r for r in self._rows if r.has_balance]
        self._rid = 0
        self._plan: swap.SwapPlan | None = None
        self._busy = False
        self._closing = False
        self._max = False
        self._pw = ""
        self._tx_network = ""
        self._to_record: SentTx | None = None
        self._prepared.connect(self._on_prepared)
        self._step.connect(self._on_step)
        self._receipt.connect(self._on_receipt)

        self.pages = QStackedWidget()
        self.root.addWidget(self.pages)
        self.pages.addWidget(self._build_form())
        self.pages.addWidget(self._build_review())
        self.pages.addWidget(self._build_status())
        self._show_page(0)

    # ------------------------------------------------------------------
    def _show_page(self, index: int) -> None:
        for i in range(self.pages.count()):
            page = self.pages.widget(i)
            policy = page.sizePolicy()
            policy.setVerticalPolicy(QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored)
            page.setSizePolicy(policy)
        self.pages.setCurrentIndex(index)
        self.pages.updateGeometry()

    def go_back(self) -> None:
        if self.pages.currentIndex() == 1 and not self._busy:
            self._rid += 1
            self._show_page(0)
            return
        self.reject()

    def done(self, result: int) -> None:
        self._closing = True
        self._rid += 1
        self._pw = ""
        super().done(result)

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        return host, lay

    def _emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:   # layar sudah ditutup
            pass

    def _run(self, fn) -> None:
        if self.run_in_thread:
            threading.Thread(target=fn, daemon=True).start()
        else:
            fn()

    # ------------------------------------------------------------------
    # Halaman 0: form
    # ------------------------------------------------------------------
    def _build_form(self) -> QWidget:
        host, lay = self._page()
        lay.addWidget(label(f"Dari “{self.wallet.name}”  ·  {self.wallet.short_address}", "muted"))

        self.sell_combo = QComboBox()
        self.buy_combo = QComboBox()
        self.amount_edit = QLineEdit()
        self.max_btn = button("Maks")
        self.slip_edit = QLineEdit(str(swap.DEFAULT_SLIPPAGE_BPS / 100).rstrip("0").rstrip("."))
        self.form_err = self.error_label()
        self.next_btn = button("Lihat harga", "primary")
        cancel = button("Batal")

        if not self._sell_rows:
            lay.addWidget(
                label(
                    "Swap saat ini tersedia di jaringan Sepolia (uji coba) lewat Uniswap V3, dan kamu belum punya "
                    "aset bersaldo di sana. Isi saldo dulu lewat tombol Terima (faucet Sepolia).",
                    "warnbox",
                    wrap=True,
                )
            )
            cancel.setText("Tutup")
            cancel.clicked.connect(self.reject)
            lay.addLayout(self.button_row(cancel))
            return host

        names = ", ".join(sorted({f"{p.name} · {NETWORKS[n].name}" for n in
                                  {r.token.network for r in self._rows} for p in swap.providers_for(n)}))
        lay.addWidget(label(f"Lewat kontrak {names}", "small"))

        lay.addWidget(label("Tukar", "small"))
        for r in self._sell_rows:
            net = NETWORKS[r.token.network]
            self.sell_combo.addItem(f"{r.token.symbol} · {net.name}   —   saldo {format_amount(r.amount)}")
        lay.addWidget(self.sell_combo)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.amount_edit.setPlaceholderText("0.0")
        row.addWidget(self.amount_edit, 1)
        row.addWidget(self.max_btn)
        lay.addLayout(row)
        self.balance_lbl = label("", "small", wrap=True)
        lay.addWidget(self.balance_lbl)

        lay.addWidget(label("Menjadi", "small"))
        lay.addWidget(self.buy_combo)

        lay.addWidget(label("Toleransi slippage (%)", "small"))
        srow = QHBoxLayout()
        srow.setSpacing(8)
        self.slip_edit.setMaxLength(6)
        self.slip_edit.setFixedWidth(84)
        srow.addWidget(self.slip_edit)
        for bps in swap.SLIPPAGE_PRESETS_BPS:
            b = button(f"{bps / 100:g}%")
            b.clicked.connect(lambda _=False, v=bps: self.slip_edit.setText(f"{v / 100:g}"))
            srow.addWidget(b)
        srow.addStretch(1)
        lay.addLayout(srow)
        lay.addWidget(
            label(
                "Slippage adalah batas pergeseran harga yang kamu terima. Jika harga memburuk melebihi batas ini, "
                "transaksi dibatalkan oleh kontrak.",
                "small",
                wrap=True,
            )
        )

        lay.addWidget(self.form_err)
        lay.addLayout(self.button_row(cancel, self.next_btn))

        self.sell_combo.currentIndexChanged.connect(self._sell_changed)
        self.amount_edit.textEdited.connect(lambda *_: setattr(self, "_max", False))
        self.amount_edit.returnPressed.connect(self.next_btn.click)
        self.max_btn.clicked.connect(self._fill_max)
        cancel.clicked.connect(self.reject)
        self.next_btn.clicked.connect(self._on_next)
        self._sell_changed()
        return host

    def _current_sell(self) -> AssetRow:
        return self._sell_rows[self.sell_combo.currentIndex()]

    def _current_buy(self) -> AssetRow | None:
        i = self.buy_combo.currentIndex()
        opts = self._buy_options
        return opts[i] if 0 <= i < len(opts) else None

    def _sell_changed(self, *_args) -> None:
        sell = self._current_sell()
        net = NETWORKS[sell.token.network]
        self._max = False
        self.show_error(self.form_err, "")
        extra = " Sisakan sebagian untuk biaya gas." if sell.token.is_native else ""
        self.balance_lbl.setText(f"Saldo: {plain(sell.amount)} {sell.token.symbol} di {net.name}.{extra}")
        prov = swap.providers_for(sell.token.network)[0]
        weth = prov.weth.lower()
        keep = self._current_buy()
        opts = []
        for r in self._rows:
            t = r.token
            if t.network != sell.token.network or t.key == sell.token.key:
                continue
            # koin native <-> WETH bukan swap (tidak ada kolamnya): jangan ditawarkan
            if (sell.token.is_native and (t.address or "").lower() == weth) or (
                (sell.token.address or "").lower() == weth and t.is_native
            ):
                continue
            opts.append(r)
        self._buy_options = opts
        self.buy_combo.clear()
        for r in opts:
            self.buy_combo.addItem(f"{r.token.symbol}  —  {r.token.name}" + ("  (ditambah manual)" if r.token.custom else ""))
        if keep is not None:
            for i, r in enumerate(opts):
                if r.token.key == keep.token.key:
                    self.buy_combo.setCurrentIndex(i)

    _buy_options: list[AssetRow] = []

    def _fill_max(self) -> None:
        sell = self._current_sell()
        self.amount_edit.setText(plain(sell.amount))
        self._max = True

    def _on_next(self) -> None:
        if self._busy:
            return
        sell, buy = self._current_sell(), self._current_buy()
        try:
            if buy is None:
                raise swap.SwapError("Pilih token tujuan.")
            amount = tx.parse_amount(self.amount_edit.text(), sell.token.decimals)
            bps = swap.parse_slippage(self.slip_edit.text())
            balance = int(sell.amount.scaleb(sell.token.decimals))
            if amount > balance:
                raise swap.SwapError(f"Saldo {sell.token.symbol} tidak cukup.")
        except (swap.SwapError, tx.TransferError) as exc:
            self.show_error(self.form_err, str(exc))
            return
        self.show_error(self.form_err, "")
        if sell.token.is_native and (self._max or amount == balance):
            self.show_error(self.form_err, "Sisakan sebagian koin native untuk biaya gas (jangan swap seluruh saldo).")
            return
        self._start_prepare(sell.token, buy.token, amount, balance, bps)

    def _start_prepare(self, sell, buy, amount: int, balance: int, bps: int) -> None:
        self._busy = True
        self.next_btn.setEnabled(False)
        self.next_btn.setText("Mencari harga…")
        self._rid += 1
        rid = self._rid
        net = NETWORKS[sell.network]
        provider = swap.providers_for(net.key)[0]
        rpc = self.service.rpc_for(net.key)
        sender = self.wallet.address

        def work() -> None:
            try:
                result = swap.prepare_swap(rpc, net, provider, sell, buy, amount, sender, balance, bps)
            except Exception as exc:  # noqa: BLE001 - apa pun yang gagal ditampilkan sebagai pesan
                result = exc
            self._emit(self._prepared, rid, result)

        self._run(work)

    def _on_prepared(self, rid: int, result) -> None:
        if rid != self._rid:
            return
        self._busy = False
        self.next_btn.setEnabled(True)
        self.next_btn.setText("Lihat harga")
        if isinstance(result, Exception):
            msg = str(result) if isinstance(result, swap.SwapError) and str(result) else "Gagal menghubungi jaringan."
            if self.pages.currentIndex() == 1:
                self.review_err.setText(msg)
                self.review_err.show()
                self.swap_btn.setEnabled(False)
            else:
                self.show_error(self.form_err, msg)
            return
        refreshed = self.pages.currentIndex() == 1
        self._plan = result
        self.pw_field.clear()
        self._render_review()
        self._show_page(1)
        if refreshed:
            self.review_note.setText("Harga sudah diperbarui. Periksa lagi lalu tekan Tukar.")
            self.review_note.show()
        self.pw_field.setFocus()

    # ------------------------------------------------------------------
    # Halaman 1: tinjau
    # ------------------------------------------------------------------
    def _build_review(self) -> QWidget:
        host, lay = self._page()
        lay.addWidget(label("Tinjau swap", "heading"))
        self.summary_card = QWidget()
        self.summary_card.setObjectName("swapSummary")
        self.summary_card.setStyleSheet(
            f"QWidget#swapSummary {{ background: {theme.SURFACE}; border: 1px solid {theme.LINE}; border-radius: 12px; }}"
            "QWidget#swapSummary QLabel { background: transparent; }"
        )
        card = QVBoxLayout(self.summary_card)
        card.setContentsMargins(16, 12, 16, 12)
        card.setSpacing(2)
        self.summary_values: dict[str, QLabel] = {}
        keys = (("network", "Jaringan · DEX"), ("from", "Dari"), ("sell", "Kamu tukar"), ("buy", "Kamu terima (perkiraan)"),
                ("min", "Minimal diterima"), ("rate", "Harga"), ("route", "Kolam"), ("gas", "Biaya gas (perkiraan)"),
                ("approve", "Izin token"))
        for i, (key, title) in enumerate(keys):
            if i:
                card.addSpacing(8)
            head = label(title, "small")
            value = label("", wrap=True, selectable=True)
            value.setStyleSheet(f"color: {theme.TEXT_STRONG}; font-size: 14px; font-weight: 600;")
            card.addWidget(head)
            card.addWidget(value)
            self.summary_values[key] = value
            self.summary_values[key + "_head"] = head
        lay.addWidget(self.summary_card)

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
        self.swap_btn = button("Tukar sekarang", "primary")
        lay.addLayout(self.button_row(back, self.swap_btn))
        back.clicked.connect(self.go_back)
        self.swap_btn.clicked.connect(self._on_swap)
        self.pw_field.returnPressed.connect(self._on_swap)
        return host

    def summary_text(self) -> str:
        """Seluruh isi ringkasan sebagai satu teks (dipakai tes)."""
        return "\n".join(
            f"{self.summary_values[k + '_head'].text()}: {self.summary_values[k].text()}"
            for k in ("network", "from", "sell", "buy", "min", "rate", "route", "gas", "approve")
            if not self.summary_values[k].isHidden()
        )

    def _render_review(self) -> None:
        plan = self._plan
        if plan is None:
            return
        net = NETWORKS[plan.network]
        sell, buy = plan.sell, plan.buy
        sv = self.summary_values
        got = tx.to_units(plan.quote.amount_out, buy.decimals)
        least = tx.to_units(plan.min_out, buy.decimals)
        fee_native = tx.to_units(plan.est_fee_wei(), 18)
        sv["network"].setText(f"{net.name}{'  (testnet)' if net.is_testnet else ''}  ·  {plan.provider.name}")
        sv["from"].setText(f"{self.wallet.name}  ·  {self.wallet.short_address}")
        sv["sell"].setText(f"{plain(tx.to_units(plan.amount_in, sell.decimals))} {sell.symbol}")
        sv["buy"].setText(f"≈ {plain(got)} {buy.symbol}")
        sv["min"].setText(f"{plain(least)} {buy.symbol}   (slippage {plan.slippage_bps / 100:g}%)")
        sv["rate"].setText(f"1 {sell.symbol} ≈ {format_amount(plan.rate)} {buy.symbol}")
        sv["route"].setText(f"{sell.symbol} → {buy.symbol}, fee {plan.quote.fee / 10_000:g}%")
        sv["gas"].setText(f"{plain(fee_native.quantize(Decimal('0.00000001')))} {net.native_symbol}")
        needs = plan.needs_approval
        sv["approve"].setText(
            f"Perlu: 1 transaksi tambahan, hanya untuk {plain(tx.to_units(plan.amount_in, sell.decimals))} "
            f"{sell.symbol}" if needs else "Sudah ada"
        )
        for w in (sv["approve"], sv["approve_head"]):
            w.setVisible(not sell.is_native)
        warns = []
        if not net.is_testnet:
            warns.append("Ini jaringan utama: aset yang ditukar adalah aset sungguhan dan transaksinya tidak bisa dibatalkan.")
        else:
            warns.append("Likuiditas di jaringan uji sangat tipis dan harganya tidak mencerminkan pasar sungguhan.")
        if plan.slippage_bps > swap.WARN_SLIPPAGE_BPS:
            warns.append("Slippage di atas 5% membuka peluang kamu menerima jauh lebih sedikit dari kutipan.")
        if buy.custom:
            warns.append(f"{buy.symbol} adalah token yang kamu tambahkan sendiri. Pastikan contract address-nya benar; "
                         "token palsu bisa saja punya nama yang sama.")
        self.warn_box.setText("\n\n".join(warns))
        self.warn_box.setVisible(bool(warns))
        self.review_note.hide()
        try:
            plan.check_funds()
            self.review_err.hide()
            self.swap_btn.setEnabled(not self._busy)
        except swap.SwapError as exc:
            self.review_err.setText(str(exc))
            self.review_err.show()
            self.swap_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Eksekusi: [izin] -> swap
    # ------------------------------------------------------------------
    def _fail_review(self, msg: str) -> None:
        self.review_err.setText(msg)
        self.review_err.show()

    def _on_swap(self) -> None:
        plan = self._plan
        if plan is None or self._busy or not self.swap_btn.isEnabled():
            return
        pw = self.pw_field.text()
        if not pw:
            self._fail_review("Masukkan master password.")
            return
        try:
            valid = self.vault.verify_password(pw)
        except VaultError as exc:
            self._fail_review(str(exc) or "Gagal memeriksa password.")
            return
        if not valid:
            self.pw_field.clear()
            self._fail_review("Password salah.")
            self.pw_field.setFocus()
            return
        if time.time() - plan.created_at > swap.QUOTE_MAX_AGE:
            # Harga dan biaya sudah basi: ambil ulang, lalu minta pengguna menekan Tukar lagi.
            self._busy = True
            self.swap_btn.setEnabled(False)
            self._start_prepare(plan.sell, plan.buy, plan.amount_in, plan.balance, plan.slippage_bps)
            return
        self._pw = pw
        self.pw_field.clear()
        self._busy = True
        self._tx_network = plan.network
        self.status_title.setStyleSheet("")
        self.hash_lbl.hide()
        self._set_status_buttons(has_hash=False)
        self._show_page(2)
        self._rid += 1
        if plan.needs_approval:
            self._set_status(
                "Langkah 1 dari 2: memberi izin token…",
                f"Mengizinkan router {plan.provider.name} memakai {plain(tx.to_units(plan.amount_in, plan.sell.decimals))} "
                f"{plan.sell.symbol}, lalu menunggu konfirmasi blok. Jangan tutup layar ini sampai swap terkirim.",
            )
            self._prepare_call_step("approve_plan", plan.sell.address, plan.approve_calldata(), 0)
        else:
            self._start_swap_step()

    def _set_status(self, title: str, detail: str) -> None:
        self.status_title.setText(title)
        self.status_detail.setText(detail)

    def _start_swap_step(self) -> None:
        plan = self._plan
        self._set_status(
            "Mengirim swap…" if not plan.needs_approval else "Langkah 2 dari 2: mengirim swap…",
            "Menyiapkan dan menandatangani transaksi swap.",
        )
        self._prepare_call_step("swap_plan", plan.provider.router, plan.swap_calldata(), plan.swap_value())

    def _prepare_call_step(self, name: str, to: str, data: str, value: int) -> None:
        rid = self._rid
        plan = self._plan
        net = NETWORKS[plan.network]
        rpc = self.service.rpc_for(net.key)
        sender = self.wallet.address

        def work() -> None:
            try:
                result = swap.prepare_call(rpc, net, sender, to, data, value)
            except Exception as exc:  # noqa: BLE001
                result = exc
            self._emit(self._step, rid, name, result)

        self._run(work)

    def _abort(self, msg: str, detail_tail: str = "") -> None:
        self._busy = False
        self._pw = ""
        self.status_title.setStyleSheet(f"color: {theme.DANGER};")
        self.status_title.setText("Swap tidak jadi dikirim")
        self.status_detail.setText(f"{msg}\n\n{detail_tail or 'Tidak ada dana yang keluar dari wallet selain biaya gas yang mungkin sudah terpakai.'}")
        self._set_status_buttons(has_hash=False)

    def _msg(self, exc) -> str:
        return str(exc) if isinstance(exc, (swap.SwapError, tx.TransferError)) and str(exc) else "Gagal menghubungi jaringan."

    def _sign(self, call: swap.CallPlan) -> tuple[str, str] | None:
        try:
            return self.vault.sign_transfer(self.wallet.id, self._pw, call.tx_fields(tx.SPEED_NORMAL))
        except InvalidPassword:
            self._abort("Password salah.")
        except (VaultError, ValueError, TypeError) as exc:
            self._abort(str(exc) or "Gagal menandatangani transaksi.")
        return None

    def _on_step(self, rid: int, name: str, result) -> None:
        if rid != self._rid:
            return
        plan = self._plan
        if name in ("approve_plan", "swap_plan"):
            if isinstance(result, Exception):
                self._abort(self._msg(result))
                return
            signed = self._sign(result)
            if signed is None:
                return
            raw, tx_hash = signed
            net = NETWORKS[plan.network]
            rpc = self.service.rpc_for(net.key)
            if name == "approve_plan":
                def work_a() -> None:
                    try:
                        h = tx.broadcast(rpc, raw)
                        receipt = swap.wait_receipt(
                            rpc, h, attempts=swap.RECEIPT_WAIT_ATTEMPTS if self.run_in_thread else 1,
                            cancelled=lambda: self._closing,
                        )
                        out = (h, receipt)
                    except Exception as exc:  # noqa: BLE001
                        out = exc
                    self._emit(self._step, rid, "approve_done", out)

                self._run(work_a)
            else:
                self._to_record = SentTx(
                    network=plan.network, tx_hash=tx_hash, wallet_address=self.wallet.address,
                    to_address=plan.provider.router, symbol=plan.sell.symbol, decimals=plan.sell.decimals,
                    token_address=plan.sell.address, amount_raw=plan.amount_in, status="pending", block=None,
                    created_at=int(time.time()),
                )
                self._pw = ""                                   # penandatanganan terakhir selesai

                def work_s() -> None:
                    try:
                        out = tx.broadcast(rpc, raw)
                    except Exception as exc:  # noqa: BLE001
                        out = exc
                    self._emit(self._step, rid, "broadcasted", out)

                self._run(work_s)
            return
        if name == "approve_done":
            if isinstance(result, Exception):
                self._abort(self._msg(result))
                return
            _hash, receipt = result
            if receipt is None:
                self._abort(
                    "Izin token belum terkonfirmasi di jaringan dalam waktu wajar.",
                    "Swap belum dikirim. Izin yang terkirim hanya sebesar jumlah swap ini dan aman dibiarkan; "
                    "coba lagi nanti (izin yang sudah ada akan dipakai).",
                )
                return
            if not receipt.success:
                self._abort("Transaksi izin token gagal di blockchain.")
                return
            self._start_swap_step()
            return
        if name == "broadcasted":
            self._busy = False
            if isinstance(result, Exception):
                self._abort(self._msg(result))
                return
            self.sent_hash = result
            if self._to_record is not None:
                self.vault.record_sent_tx(self._to_record)
            self.status_title.setStyleSheet("")
            self._set_status(
                "Swap terkirim",
                "Menunggu masuk ke blok. Kamu boleh menutup layar ini; transaksi tetap berjalan.",
            )
            self.hash_lbl.setText(f"Hash transaksi\n{result[:34]}\n{result[34:]}")
            self.hash_lbl.show()
            self._set_status_buttons(has_hash=True)
            self._poll(rid, result)

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
        self.copy_hash_btn.clicked.connect(lambda: copy_to_clipboard(self.sent_hash or "", anchor=self.copy_hash_btn))
        self.explorer_btn.clicked.connect(lambda: open_url(tx.explorer_tx_url(self._tx_network, self.sent_hash or "")))
        self.close_btn.clicked.connect(self.accept)
        lay.addLayout(self.button_row(self.copy_hash_btn, self.explorer_btn, self.close_btn))
        self._set_status_buttons(has_hash=False)
        return host

    def _set_status_buttons(self, has_hash: bool = False) -> None:
        self.copy_hash_btn.setVisible(has_hash)
        self.explorer_btn.setVisible(has_hash)
        self.close_btn.setEnabled(True)

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
            self._set_status(
                "Masih menunggu konfirmasi",
                "Swap sudah dikirim tetapi belum masuk blok. Jaringan mungkin sedang padat. Cek statusnya di explorer; "
                "saldo di lobi akan menyesuaikan setelah selesai.",
            )
        elif receipt.success:
            self._set_status("Berhasil ✓", f"Swap masuk ke blok {receipt.block}. Saldo di lobi akan diperbarui.")
        else:
            self.status_title.setStyleSheet(f"color: {theme.DANGER};")
            self._set_status(
                "Swap gagal di blockchain",
                "Transaksi masuk blok tetapi dibatalkan kontrak (biasanya karena harga bergeser melebihi slippage). "
                "Biaya gas tetap terpotong; token yang kamu tukar tidak berkurang. Coba lagi dengan slippage lebih besar.",
            )
