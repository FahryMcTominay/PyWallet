"""Dialog Riwayat transaksi: daftar transaksi keluar dan masuk wallet aktif untuk mode yang sedang dipilih."""
from __future__ import annotations

import threading
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..formatting import format_amount
from ..history import (
    DIR_CALL,
    DIR_IN,
    DIR_OUT,
    DIR_SELF,
    ST_FAILED,
    ST_PENDING,
    HistoryItem,
    HistoryResult,
)
from ..networks import MODE_LABELS, MODES, NETWORKS
from ..portfolio import PortfolioService
from ..tokens import tokens_for_mode
from ..tx import explorer_tx_url
from ..vault import Vault, VaultError, WalletRecord
from . import theme
from .dialogs import ScreenBase, button
from .token_dialogs import open_url
from .widgets import PasswordField, label

_TITLES = {DIR_OUT: "Terkirim", DIR_IN: "Diterima", DIR_SELF: "Ke diri sendiri", DIR_CALL: "Panggilan kontrak"}
_ARROWS = {DIR_OUT: "↑", DIR_IN: "↓", DIR_SELF: "⇄", DIR_CALL: "⚙"}
_STATUS = {ST_PENDING: "Menunggu", ST_FAILED: "Gagal"}


def short(addr: str) -> str:
    return f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr


def format_time(ts: int) -> str:
    if ts <= 0:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M")


class HistoryRow(QFrame):
    clicked = Signal(object)

    def __init__(self, item: HistoryItem, multi_network: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("historyRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#historyRow {{ background: {theme.SURFACE}; border: 1px solid {theme.LINE}; border-radius: 12px; }}"
            f"QFrame#historyRow:hover {{ background: {theme.SURFACE_HI}; }}"
            "QFrame#historyRow QLabel { background: transparent; }"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        bad = item.status == ST_FAILED
        color = theme.DANGER if bad else (theme.ACCENT if item.direction == DIR_IN else theme.TEXT_STRONG)
        arrow = label(_ARROWS[item.direction])
        arrow.setFixedSize(34, 34)
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet(
            f"color: {color}; font-size: 16px; font-weight: 700; border: 1px solid {theme.LINE}; border-radius: 17px;"
        )
        row.addWidget(arrow)

        left = QVBoxLayout()
        left.setSpacing(1)
        title = label(_TITLES[item.direction])
        title.setStyleSheet(f"color: {theme.TEXT_STRONG}; font-size: 14px; font-weight: 600;")
        who = "dari" if item.direction == DIR_IN else "ke"
        sub = f"{who} {short(item.counterparty)}" if item.counterparty and item.direction != DIR_SELF else ""
        meta = " · ".join(p for p in (sub, NETWORKS[item.network].name if multi_network else "", format_time(item.timestamp)) if p)
        subtitle = label(meta, "small")
        left.addWidget(title)
        left.addWidget(subtitle)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(1)
        right.setAlignment(Qt.AlignmentFlag.AlignRight)
        if item.amount is not None:
            sign = "+" if item.direction == DIR_IN else "−" if item.direction == DIR_OUT else ""
            amt = label(f"{sign}{format_amount(item.amount)} {item.symbol}")
            amt.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 700;")
            amt.setAlignment(Qt.AlignmentFlag.AlignRight)
            right.addWidget(amt)
        notes = []
        if item.status in _STATUS:
            notes.append(_STATUS[item.status])
        if not item.known_token:
            notes.append("Token tidak dikenal")
        if notes:
            st = label(" · ".join(notes), "small")
            st.setAlignment(Qt.AlignmentFlag.AlignRight)
            if bad or not item.known_token:
                st.setStyleSheet(f"color: {theme.DANGER}; font-size: 12px;")
            right.addWidget(st)
        row.addLayout(right)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)
        super().mousePressEvent(event)


class HistoryDialog(ScreenBase):
    _loaded = Signal(int, object)

    def __init__(self, vault: Vault, service: PortfolioService, wallet: WalletRecord, mode: str,
                 parent: QWidget | None = None, run_in_thread: bool = True):
        super().__init__("Riwayat", parent, scroll=False)
        self.vault, self.service, self.wallet, self.mode = vault, service, wallet, mode
        self.run_in_thread = run_in_thread          # tes mematikannya
        self.result: HistoryResult | None = None
        self._rid = 0
        self._loaded.connect(self._on_loaded)

        self.root.addWidget(
            label(f"“{wallet.name}”  ·  {', '.join(NETWORKS[k].name for k in self._networks())} ({MODE_LABELS[mode]})", "muted")
        )

        self.status = label("", "small", wrap=True)
        self.root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 4, 0)
        self.body_lay.setSpacing(8)
        self.body_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        self.root.addWidget(self.scroll, 1)

        self.note = label("", "small", wrap=True)
        self.root.addWidget(self.note)
        self.refresh_btn = button("Muat ulang")
        close = button("Tutup", "primary")
        self.refresh_btn.clicked.connect(lambda: self.reload(force=True))
        close.clicked.connect(self.accept)
        self.root.addLayout(self.button_row(self.refresh_btn, close))
        self.reload()

    def _networks(self) -> tuple[str, ...]:
        return MODES[self.mode]

    # --- memuat ---------------------------------------------------------------------------------
    def reload(self, force: bool = False) -> None:
        """`force` = abaikan cache singkat (tombol Muat ulang)."""
        self._rid += 1
        rid = self._rid
        self.refresh_btn.setEnabled(False)
        self.status.setText("Memuat riwayat…")
        self.status.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        # SQLite hanya boleh dibaca di thread utama; datanya dibawa ke thread kerja.
        local = self.vault.list_sent_txs(self.wallet.address, self._networks())
        known = tokens_for_mode(self.mode, self.vault.list_custom_tokens())
        address, mode = self.wallet.address, self.mode
        api_key = self.vault.get_history_api_key()

        def work() -> None:
            try:
                result = self.service.history.load(address, mode, local, known, force, api_key)
            except Exception as exc:  # noqa: BLE001
                result = exc
            try:
                self._loaded.emit(rid, result)
            except RuntimeError:   # dialog sudah ditutup
                pass

        if self.run_in_thread:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def _on_loaded(self, rid: int, result) -> None:
        if rid != self._rid:
            return
        self.refresh_btn.setEnabled(True)
        if isinstance(result, Exception):
            self.status.setText("Gagal memuat riwayat.")
            self.status.setStyleSheet(f"color: {theme.DANGER}; font-size: 12px;")
            return
        self.result = result
        for net, tx_hash, status, block in result.updates:      # perbarui status transaksi yang tadinya menunggu
            self.vault.set_tx_status(net, tx_hash, status, block)
        self._render(result)

    def _render(self, result: HistoryResult) -> None:
        while self.body_lay.count() > 1:
            w = self.body_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        multi = len(self._networks()) > 1
        for it in result.items:
            row = HistoryRow(it, multi)
            row.clicked.connect(self._open)
            self.body_lay.insertWidget(self.body_lay.count() - 1, row)
        if result.errors:
            hint = ""
            if any("429" in e or "too many" in e.lower() for e in result.errors) and not self.vault.get_history_api_key():
                hint = " Batas permintaan API publik tercapai: pasang API key gratis di tab Profil agar lebih longgar."
            self.status.setText("; ".join(result.errors) + ". Data yang tampil mungkin belum lengkap." + hint)
            self.status.setStyleSheet(f"color: {theme.DANGER}; font-size: 12px;")
        else:
            self.status.setText("" if result.items else "Belum ada transaksi.")
            self.status.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        self.status.setVisible(bool(self.status.text()))
        notes = ["Menampilkan transaksi terbaru (maks. 50 per jenis per jaringan). Klik baris untuk membuka di explorer."]
        if result.hidden_zero:
            notes.append(
                f"{result.hidden_zero} transfer token bernilai nol disembunyikan. Itu sering modus “address poisoning”: "
                "alamat tiruan dimunculkan supaya kamu salah menyalinnya. Selalu cocokkan alamat tujuan secara penuh."
            )
        self.note.setText("\n".join(notes))

    def _open(self, item: HistoryItem) -> None:
        open_url(explorer_tx_url(item.network, item.tx_hash))


class ApiKeyDialog(ScreenBase):
    """Atur API key Blockscout PRO untuk riwayat transaksi (opsional; menghindari batas permintaan API publik)."""

    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__("API key riwayat", parent)
        self.vault = vault
        self.changed = False
        self.root.addWidget(
            label(
                "Tanpa key, riwayat memakai API publik yang batas permintaannya ketat (galat 429). Dengan key gratis "
                "dari Blockscout PRO (dev.blockscout.com, tanpa kartu kredit), satu key berlaku untuk Ethereum dan "
                "Sepolia. Base tidak masuk paket gratis, jadi riwayat Base tetap lewat API publik.",
                "muted",
                wrap=True,
            )
        )
        self.root.addWidget(
            label(
                "Key hanya dikirim ke api.blockscout.com dan disimpan di database lokal di komputermu, tanpa "
                "enkripsi. Ini bukan kunci wallet dan tidak bisa menggerakkan dana, tetapi jangan dibagikan.",
                "small",
                wrap=True,
            )
        )
        self.field = PasswordField("proapi_…")
        self.field.returnPressed.connect(self._save)
        self.root.addWidget(self.field)
        self.state = label("Key terpasang." if vault.get_history_api_key() else "Belum ada key.", "small")
        self.root.addWidget(self.state)
        self.err = self.error_label()
        self.root.addWidget(self.err)
        cancel = button("Batal")
        self.remove_btn = button("Hapus key", "danger")
        self.remove_btn.setVisible(bool(vault.get_history_api_key()))
        save = button("Simpan", "primary")
        cancel.clicked.connect(self.reject)
        self.remove_btn.clicked.connect(self._remove)
        save.clicked.connect(self._save)
        self.root.addLayout(self.button_row(cancel, self.remove_btn, save))

    def _save(self) -> None:
        try:
            self.vault.set_history_api_key(self.field.text())
        except VaultError as exc:
            self.show_error(self.err, str(exc))
            return
        self.changed = True
        self.accept()

    def _remove(self) -> None:
        self.vault.set_history_api_key(None)
        self.changed = True
        self.accept()
