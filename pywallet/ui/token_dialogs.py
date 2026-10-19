"""Dialog token: tambah lewat contract address, dan lihat detail (termasuk contract address) sebuah token."""
from __future__ import annotations

import threading

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..formatting import format_amount
from ..networks import NETWORKS, networks_for_mode
from ..portfolio import AssetRow, PortfolioService
from ..rpc import RpcError, TokenInfo
from ..tokens import TOKENS, InvalidContractAddress, Token, find_builtin, normalize_contract_address
from ..vault import Vault
from . import theme
from .dialogs import USER_ERRORS, BaseDialog, button
from .widgets import TokenIcon, copy_to_clipboard, label, styled


def explorer_token_url(network: str, address: str) -> str:
    base = NETWORKS[network].explorer
    return f"{base}/token/{address}" if base else ""


def open_url(url: str) -> None:
    if url:
        QDesktopServices.openUrl(QUrl(url))


# ==========================================================================
# Tambah token
# ==========================================================================
class AddTokenDialog(BaseDialog):
    _fetched = Signal(int, object)   # (id permintaan, TokenInfo atau Exception)

    def __init__(self, vault: Vault, service: PortfolioService, mode: str, parent: QWidget | None = None):
        super().__init__("Tambah Token", parent, 500)
        self.vault = vault
        self.service = service
        self.added: Token | None = None
        self.run_in_thread = True            # tes mematikannya agar tidak perlu menunggu thread
        self._info: TokenInfo | None = None
        self._rid = 0
        self._networks = networks_for_mode(mode)
        self._network = self._networks[0].key
        self._fetched.connect(self._on_fetched)

        self.root.addWidget(label("Tambah token", "heading"))
        self.root.addWidget(
            label(
                "Masukkan contract address token. Nama, simbol, dan desimalnya dibaca langsung dari blockchain.",
                "muted",
                wrap=True,
            )
        )

        self.root.addWidget(label("Jaringan", "small"))
        self.net_buttons: dict[str, object] = {}
        if len(self._networks) > 1:
            seg = QHBoxLayout()
            seg.setSpacing(8)
            group = QButtonGroup(self)
            group.setExclusive(True)
            for i, net in enumerate(self._networks):
                b = button(net.name, "segment")
                b.setCheckable(True)
                b.setChecked(i == 0)
                group.addButton(b, i)
                seg.addWidget(b)
                self.net_buttons[net.key] = b
            group.idClicked.connect(lambda i: self._set_network(self._networks[i].key))
            self._group = group
            self.root.addLayout(seg)
        else:
            self.root.addWidget(styled(label(self._networks[0].name), theme.TEXT_STRONG, 14, 700))

        self.root.addWidget(label("Contract address", "small"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.addr_edit = QLineEdit()
        self.addr_edit.setPlaceholderText("0x…")
        self.addr_edit.setMaxLength(66)
        self.check_btn = button("Periksa", "primary")
        row.addWidget(self.addr_edit, 1)
        row.addWidget(self.check_btn)
        self.root.addLayout(row)

        self.err = self.error_label()
        self.root.addWidget(self.err)
        self.preview = label("", "secret", wrap=True)
        self.preview.hide()
        self.root.addWidget(self.preview)
        self.warn = label("", "warnbox", wrap=True)
        self.warn.hide()
        self.root.addWidget(self.warn)
        self.confirm = QCheckBox("Alamat ini sudah saya cocokkan dengan sumber resmi")
        self.confirm.hide()
        self.root.addWidget(self.confirm)
        self.root.addWidget(
            label(
                "Siapa pun bisa membuat token dengan nama dan logo apa saja. Ambil contract address dari situs "
                "resmi proyek atau dari explorer, bukan dari pesan atau iklan.",
                "small",
                wrap=True,
            )
        )

        self.explorer_btn = button("Buka di explorer")
        self.explorer_btn.setEnabled(False)
        cancel = button("Batal")
        self.add_btn = button("Tambahkan", "primary")
        self.add_btn.setEnabled(False)
        self.root.addLayout(self.button_row(self.explorer_btn, cancel, self.add_btn))

        self.check_btn.clicked.connect(self.check)
        self.addr_edit.returnPressed.connect(self.check)
        self.addr_edit.textChanged.connect(self._reset_preview)
        self.confirm.toggled.connect(self._refresh)
        self.explorer_btn.clicked.connect(lambda: open_url(self.explorer_url()))
        cancel.clicked.connect(self.reject)
        self.add_btn.clicked.connect(self._add)

    # --- helper ---------------------------------------------------------------------------------
    def explorer_url(self) -> str:
        try:
            return explorer_token_url(self._network, normalize_contract_address(self.addr_edit.text()))
        except InvalidContractAddress:
            return ""

    def _set_network(self, key: str) -> None:
        self._network = key
        self._reset_preview()

    def _reset_preview(self, *_args) -> None:
        self._rid += 1                      # hasil permintaan lama diabaikan
        self._info = None
        self.preview.hide()
        self.warn.hide()
        self.confirm.hide()
        self.confirm.setChecked(False)
        self.show_error(self.err, "")
        self.explorer_btn.setEnabled(bool(self.explorer_url()))
        self._refresh()

    def _refresh(self, *_args) -> None:
        self.add_btn.setEnabled(self._info is not None and self.confirm.isChecked())

    # --- langkah 1: periksa ---------------------------------------------------------------------
    def check(self) -> None:
        self._reset_preview()
        try:
            address = normalize_contract_address(self.addr_edit.text())
        except InvalidContractAddress as exc:
            self.show_error(self.err, str(exc))
            return
        builtin = find_builtin(self._network, address)
        if builtin is not None:
            self.show_error(self.err, f"{builtin.symbol} sudah ada di daftar bawaan jaringan ini.")
            return
        if any(t.network == self._network and t.address == address for t in self.vault.list_custom_tokens()):
            self.show_error(self.err, "Token ini sudah ada di daftarmu.")
            return
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Memeriksa…")
        rid, network = self._rid, self._network

        def work() -> None:
            try:
                result = self.service.token_info(network, address)
            except Exception as exc:  # noqa: BLE001 - apa pun yang gagal ditampilkan sebagai pesan
                result = exc
            try:
                self._fetched.emit(rid, result)
            except RuntimeError:   # dialog sudah ditutup
                pass

        if self.run_in_thread:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def _on_fetched(self, rid: int, result) -> None:
        if rid != self._rid:
            return
        self.check_btn.setEnabled(True)
        self.check_btn.setText("Periksa")
        if isinstance(result, Exception):
            msg = str(result) if isinstance(result, RpcError) and str(result) else "Gagal memeriksa token."
            self.show_error(self.err, msg)
            return
        self._info = result
        net = NETWORKS[self._network]
        self.preview.setText(
            f"Nama: {result.name}\nSimbol: {result.symbol}\nDesimal: {result.decimals}\n"
            f"Jaringan: {net.name}\nAlamat: {result.address}"
        )
        self.preview.show()
        lookalike = [
            t for t in TOKENS[self._network]
            if t.symbol.lower() == result.symbol.lower() and (t.address or "") != result.address
        ]
        if lookalike:
            self.warn.setText(
                f"Peringatan: simbol “{result.symbol}” sama dengan {lookalike[0].name} bawaan, tetapi alamatnya "
                f"berbeda. Ini bisa token palsu. Lanjutkan hanya jika kamu yakin."
            )
            self.warn.show()
        self.confirm.show()
        self._refresh()
        self.adjustSize()

    # --- langkah 2: tambahkan -------------------------------------------------------------------
    def _add(self) -> None:
        if not self.add_btn.isEnabled() or self._info is None:
            return
        info = self._info
        try:
            self.added = self.vault.add_custom_token(
                self._network, info.address, info.symbol, info.name, info.decimals
            )
        except USER_ERRORS as exc:
            self.show_error(self.err, str(exc))
            return
        self.accept()


# ==========================================================================
# Detail token (termasuk contract address)
# ==========================================================================
class TokenDetailDialog(BaseDialog):
    def __init__(self, row: AssetRow, parent: QWidget | None = None):
        super().__init__("Detail Token", parent, 480)
        self.token = row.token
        self.removed = False
        t = row.token
        net = NETWORKS[t.network]

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(TokenIcon(t, 48))
        names = QWidget()
        nl = QVBoxLayout(names)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        nl.addWidget(label(t.name, "heading"))
        nl.addWidget(styled(label(f"{t.symbol} · {net.name}"), theme.MUTED, 13))
        head.addWidget(names, 1)
        self.root.addLayout(head)

        bal = "—" if row.amount is None else f"{format_amount(row.amount)} {t.symbol}"
        for title, value in (("Saldo", bal), ("Desimal", str(t.decimals)), ("Jaringan", f"{net.name} (chain ID {net.chain_id})")):
            r = QHBoxLayout()
            r.addWidget(styled(label(title), theme.MUTED, 13))
            r.addStretch(1)
            r.addWidget(styled(label(value), theme.TEXT_STRONG, 13, 600))
            self.root.addLayout(r)

        self.addr_label = None
        close = button("Tutup")
        close.clicked.connect(self.accept)

        if t.is_native:
            self.root.addWidget(
                label(
                    f"{t.symbol} adalah koin bawaan jaringan {net.name}, jadi tidak punya contract address. "
                    f"Saldonya dibaca langsung dari jaringan lewat alamat wallet-mu.",
                    "infobox",
                    wrap=True,
                )
            )
            self.root.addLayout(self.button_row(close))
            return

        self.root.addWidget(label("Contract address", "small"))
        self.addr_label = label(t.address or "", "secret", wrap=True, selectable=True)
        self.root.addWidget(self.addr_label)
        origin = "Ditambahkan oleh kamu." if t.custom else "Token bawaan aplikasi."
        self.root.addWidget(
            label(
                f"{origin} Cocokkan alamat ini dengan sumber resmi proyek atau dengan halaman token di explorer "
                f"sebelum mengandalkannya.",
                "small",
                wrap=True,
            )
        )
        copy_btn = button("Salin alamat")
        copy_btn.clicked.connect(lambda: copy_to_clipboard(t.address or "", anchor=copy_btn))
        self.explorer_btn = button("Buka di explorer")
        self.explorer_btn.clicked.connect(lambda: open_url(explorer_token_url(t.network, t.address or "")))

        self.remove_btn = None
        self.confirm_box = None
        if t.custom:
            self.remove_btn = button("Hapus dari daftar", "danger")
            self.remove_btn.clicked.connect(self._ask_remove)
            self.root.addLayout(self.button_row(self.remove_btn, copy_btn, self.explorer_btn))
            self.confirm_box = QWidget()
            cl = QVBoxLayout(self.confirm_box)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(10)
            cl.addWidget(
                label(
                    "Hapus token ini dari daftar? Saldomu di blockchain tidak berubah; kamu bisa menambahkannya "
                    "lagi kapan saja dengan contract address yang sama.",
                    "warnbox",
                    wrap=True,
                )
            )
            no = button("Batal")
            self.yes_btn = button("Ya, hapus", "dangerSolid")
            no.clicked.connect(self._cancel_remove)
            self.yes_btn.clicked.connect(self._do_remove)
            cl.addLayout(self.button_row(no, self.yes_btn))
            self.confirm_box.hide()
            self.root.addWidget(self.confirm_box)
            self.root.addLayout(self.button_row(close))
        else:
            self.root.addLayout(self.button_row(close, copy_btn, self.explorer_btn))

    def _ask_remove(self) -> None:
        self.remove_btn.hide()
        self.confirm_box.show()
        self.adjustSize()

    def _cancel_remove(self) -> None:
        self.confirm_box.hide()
        self.remove_btn.show()
        self.adjustSize()

    def _do_remove(self) -> None:
        self.removed = True
        self.accept()
