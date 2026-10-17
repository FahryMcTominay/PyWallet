"""Layar utama: setup, unlock, onboarding kosong, dan tab Wallet / Swap / Profil."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_VERSION, MIN_PASSWORD_LENGTH, NETWORK_IS_TESTNET, NETWORK_NAME, db_path
from ..vault import SECRET_MNEMONIC, Vault, VaultError, WalletRecord, validate_new_password
from . import icons, theme
from .dialogs import button
from .widgets import (
    Avatar,
    Card,
    CircleAction,
    NavButton,
    PasswordField,
    copy_to_clipboard,
    divider,
    label,
)

NETWORK_LABEL = f"{NETWORK_NAME} · Testnet" if NETWORK_IS_TESTNET else NETWORK_NAME


def _column(max_width: int = 400) -> tuple[QVBoxLayout, QWidget]:
    """Kolom di tengah layar dengan lebar maksimum; mengembalikan (layout isi, widget induk)."""
    host = QWidget()
    host.setObjectName("root")
    host_lay = QHBoxLayout(host)
    host_lay.setContentsMargins(24, 24, 24, 24)
    inner = QWidget()
    inner.setMaximumWidth(max_width)
    inner_lay = QVBoxLayout(inner)
    inner_lay.setContentsMargins(0, 0, 0, 0)
    inner_lay.setSpacing(12)
    host_lay.addStretch(1)
    host_lay.addWidget(inner, 100)
    host_lay.addStretch(1)
    return inner_lay, host


# ==========================================================================
# Setup master password (pertama kali)
# ==========================================================================
class SetupPage(QWidget):
    completed = Signal()

    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__(parent)
        self.vault = vault
        lay, host = _column()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(host)

        lay.addStretch(2)
        lay.addWidget(label("PyWallet", "brand"), 0, Qt.AlignmentFlag.AlignHCenter)
        sub = label("Buat master password untuk melindungi wallet-mu.", "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(10)
        self.pw1 = PasswordField(f"Master password (min. {MIN_PASSWORD_LENGTH} karakter)")
        self.pw2 = PasswordField("Ulangi master password")
        self.pw2.returnPressed.connect(self._submit)
        lay.addWidget(self.pw1)
        lay.addWidget(self.pw2)
        lay.addWidget(
            label(
                "Password ini tidak bisa dipulihkan. Jika lupa, wallet hanya bisa dipulihkan dengan "
                "seed phrase atau private key-nya.",
                "infobox",
                wrap=True,
            )
        )
        self.err = label("", "error", wrap=True)
        self.err.hide()
        lay.addWidget(self.err)
        self.ok = button("Buat Password", "primary")
        self.ok.clicked.connect(self._submit)
        lay.addWidget(self.ok)
        lay.addStretch(3)

    def _submit(self) -> None:
        a, b = self.pw1.text(), self.pw2.text()
        try:
            validate_new_password(a)
            if a != b:
                raise VaultError("Kedua password tidak sama.")
            self.vault.setup_master_password(a)
        except VaultError as exc:
            self.err.setText(str(exc))
            self.err.show()
            return
        self.pw1.clear()
        self.pw2.clear()
        self.err.hide()
        self.completed.emit()


# ==========================================================================
# Unlock
# ==========================================================================
class UnlockPage(QWidget):
    unlocked = Signal()

    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__(parent)
        self.vault = vault
        self._fails = 0
        lay, host = _column()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(host)

        lay.addStretch(2)
        lay.addWidget(label("PyWallet", "brand"), 0, Qt.AlignmentFlag.AlignHCenter)
        sub = label("Masukkan master password untuk membuka wallet.", "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(10)
        self.pw = PasswordField("Master password")
        self.pw.returnPressed.connect(self._submit)
        lay.addWidget(self.pw)
        self.err = label("", "error", wrap=True)
        self.err.hide()
        lay.addWidget(self.err)
        self.ok = button("Buka", "primary")
        self.ok.clicked.connect(self._submit)
        lay.addWidget(self.ok)
        forgot = button("Lupa password?", "link")
        forgot.clicked.connect(self._forgot)
        lay.addWidget(forgot, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(3)

    def focus_input(self) -> None:
        self.pw.setFocus()

    def _submit(self) -> None:
        if not self.ok.isEnabled():
            return
        pw = self.pw.text()
        if not pw:
            return
        if self.vault.verify_password(pw):
            self._fails = 0
            self.pw.clear()
            self.err.hide()
            self.unlocked.emit()
            return
        self._fails += 1
        self.pw.clear()
        self.err.setText("Password salah.")
        self.err.show()
        if self._fails >= 3:  # jeda bertahap agar tebak-tebakan tidak nyaman
            delay = min(2 ** (self._fails - 2), 30)
            self.ok.setEnabled(False)
            self.err.setText(f"Password salah. Coba lagi dalam {delay} detik.")
            QTimer.singleShot(delay * 1000, lambda: self.ok.setEnabled(True))

    def _forgot(self) -> None:
        QMessageBox.information(
            self,
            "Lupa password",
            "Master password tidak bisa dipulihkan atau di-reset.\n\n"
            "Jika kamu masih menyimpan seed phrase atau private key wallet-mu, kamu bisa mulai ulang:\n"
            f"1. Tutup PyWallet lalu hapus file:\n{db_path()}\n"
            "2. Buka PyWallet lagi, buat master password baru.\n"
            "3. Impor wallet-mu kembali dengan seed phrase / private key.\n\n"
            "Dana tetap aman di blockchain selama seed phrase / private key-nya kamu simpan.",
        )


# ==========================================================================
# Onboarding: belum ada wallet
# ==========================================================================
class EmptyPage(QWidget):
    createRequested = Signal()
    importRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay, host = _column()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(host)
        lay.addStretch(2)
        lay.addWidget(label("PyWallet", "brand"), 0, Qt.AlignmentFlag.AlignHCenter)
        title = label("Belum ada wallet", "heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = label("Buat wallet baru, atau impor wallet yang sudah kamu punya.", "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(14)
        create = button("Buat Wallet Baru", "primary")
        create.clicked.connect(self.createRequested)
        imp = button("Impor Wallet")
        imp.clicked.connect(self.importRequested)
        lay.addWidget(create)
        lay.addWidget(imp)
        chip = label(NETWORK_LABEL, "chip")
        lay.addSpacing(8)
        lay.addWidget(chip, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(3)


# ==========================================================================
# Tab Wallet (lobi)
# ==========================================================================
class WalletTab(QWidget):
    switchRequested = Signal(int)
    createRequested = Signal()
    importRequested = Signal()
    receiveRequested = Signal()
    comingSoon = Signal(str)

    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__(parent)
        self.vault = vault
        self._wallet: WalletRecord | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 0)
        root.setSpacing(0)

        # Header: pemilih wallet + jaringan
        head = QHBoxLayout()
        head.setSpacing(8)
        self.avatar = Avatar("W", 34)
        self.switcher = QPushButton()
        self.switcher.setObjectName("flat")
        self.switcher.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switcher.setIcon(icons.icon("chevron", 16, theme.TEXT, 2.2))
        self.switcher.setIconSize(QSize(16, 16))
        self.switcher.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.switcher.setStyleSheet(
            f"QPushButton {{ font-size: 16px; font-weight: 700; color: {theme.TEXT_STRONG};"
            f" background: transparent; border: none; padding: 6px 8px; }}"
            f"QPushButton:hover {{ background: {theme.SURFACE}; }}"
        )
        self.switcher.clicked.connect(self._open_switcher)
        head.addWidget(self.avatar)
        head.addWidget(self.switcher)
        head.addStretch(1)
        head.addWidget(label(NETWORK_LABEL, "chip"))
        root.addLayout(head)
        root.addSpacing(16)

        # Alamat
        addr_row = QHBoxLayout()
        addr_row.setSpacing(2)
        self.addr = label("", "muted")
        self.copy_btn = QToolButton()
        self.copy_btn.setIcon(icons.icon("copy", 16, theme.TEXT, 2.0))
        self.copy_btn.setIconSize(QSize(16, 16))
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setToolTip("Salin alamat")
        self.copy_btn.clicked.connect(self._copy_address)
        addr_row.addWidget(self.addr)
        addr_row.addWidget(self.copy_btn)
        addr_row.addStretch(1)
        root.addLayout(addr_row)
        root.addSpacing(2)

        # Saldo
        self.balance = label("$--.--", "balance")
        root.addWidget(self.balance)
        root.addWidget(label("Belum terhubung ke jaringan", "small"))
        root.addSpacing(22)

        # Tombol aksi
        actions = QHBoxLayout()
        send = CircleAction("send", "Kirim")
        recv = CircleAction("receive", "Terima")
        trade = CircleAction("swap", "Trade")
        send.clicked.connect(lambda: self.comingSoon.emit("Kirim"))
        recv.clicked.connect(self.receiveRequested)
        trade.clicked.connect(lambda: self.comingSoon.emit("Trade"))
        for w in (send, recv, trade):
            actions.addWidget(w, 1)
        root.addLayout(actions)
        root.addSpacing(24)

        # Header daftar token
        tab_row = QHBoxLayout()
        tab = label("Token")
        tab.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {theme.TEXT_STRONG};")
        tab_row.addWidget(tab)
        tab_row.addStretch(1)
        root.addLayout(tab_row)
        underline = QFrame()
        underline.setFixedHeight(3)
        underline.setFixedWidth(34)
        underline.setStyleSheet(f"background: {theme.TEXT}; border-radius: 1px;")
        root.addSpacing(6)
        root.addWidget(underline)
        root.addWidget(divider())
        root.addSpacing(6)

        # Daftar token (saat ini hanya koin native)
        self.token_host = QWidget()
        self.token_lay = QVBoxLayout(self.token_host)
        self.token_lay.setContentsMargins(0, 0, 0, 0)
        self.token_lay.setSpacing(4)
        self.token_lay.addWidget(self._token_row("Ξ", "ETH", f"{NETWORK_NAME} ETH", "—", "—"))
        self.token_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.token_host)
        scroll.viewport().setAutoFillBackground(False)
        self.token_host.setAutoFillBackground(False)
        root.addWidget(scroll, 1)

    @staticmethod
    def _token_row(glyph: str, name: str, subtitle: str, amount: str, value: str) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(12)
        lay.addWidget(Avatar(glyph, 40))
        left = QVBoxLayout()
        left.setSpacing(0)
        n = label(name)
        n.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {theme.TEXT_STRONG};")
        left.addWidget(n)
        left.addWidget(label(subtitle, "small"))
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(0)
        a = label(amount)
        a.setAlignment(Qt.AlignmentFlag.AlignRight)
        a.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {theme.TEXT_STRONG};")
        v = label(value, "small")
        v.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(a)
        right.addWidget(v)
        lay.addLayout(right)
        return row

    # --- latar: gradasi lembut di bagian atas seperti Bitget -----------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        grad = QLinearGradient(0, 0, 0, 300)
        top = QColor(theme.ACCENT)
        top.setAlpha(150)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, QColor(theme.BG))
        p.fillRect(QRectF(0, 0, self.width(), 300), grad)

    # --- data -----------------------------------------------------------------
    def refresh(self) -> None:
        self._wallet = self.vault.get_active_wallet()
        if self._wallet is None:
            return
        self.avatar.set_text(self._wallet.name)
        self.switcher.setText(self._wallet.name)
        self.addr.setText(self._wallet.short_address)

    def _copy_address(self) -> None:
        if self._wallet:
            copy_to_clipboard(self._wallet.address, anchor=self.copy_btn)

    def _open_switcher(self) -> None:
        menu = QMenu(self)
        active = self._wallet.id if self._wallet else None
        for w in self.vault.list_wallets():
            act = menu.addAction(f"{w.name}   ·   {w.short_address}")
            act.setCheckable(True)
            act.setChecked(w.id == active)
            act.triggered.connect(lambda _=False, wid=w.id: self.switchRequested.emit(wid))
        menu.addSeparator()
        menu.addAction("Buat wallet baru").triggered.connect(self.createRequested)
        menu.addAction("Impor wallet").triggered.connect(self.importRequested)
        menu.exec(self.switcher.mapToGlobal(self.switcher.rect().bottomLeft()))


# ==========================================================================
# Tab Swap (placeholder sampai tahap 5)
# ==========================================================================
class SwapTab(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addStretch(1)
        title = label("Swap", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = label("Tukar token lewat PancakeSwap akan tersedia di tahap berikutnya.", "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addStretch(1)


# ==========================================================================
# Tab Profil
# ==========================================================================
class ProfileTab(QWidget):
    renameRequested = Signal()
    viewSecretRequested = Signal()
    deleteRequested = Signal()
    lockRequested = Signal()

    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__(parent)
        self.vault = vault
        self._wallet: WalletRecord | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 22, 20, 12)
        root.setSpacing(12)
        root.addWidget(label("Profil", "title"))

        card = Card()
        cl = QHBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(14)
        self.avatar = Avatar("W", 56)
        cl.addWidget(self.avatar)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.name = label("", "heading")
        self.addr = label("", "muted", selectable=True)
        self.kind = label("", "chip")
        info.addWidget(self.name)
        info.addWidget(self.addr)
        kind_row = QHBoxLayout()
        kind_row.addWidget(self.kind)
        kind_row.addStretch(1)
        info.addSpacing(4)
        info.addLayout(kind_row)
        cl.addLayout(info, 1)
        root.addWidget(card)
        root.addSpacing(4)

        self.rename_btn = button("Ganti nama wallet", "menuRow")
        self.secret_btn = button("Lihat seed phrase", "menuRow")
        self.delete_btn = button("Hapus wallet", "menuRowDanger")
        self.lock_btn = button("Kunci aplikasi sekarang", "menuRow")
        self.rename_btn.clicked.connect(self.renameRequested)
        self.secret_btn.clicked.connect(self.viewSecretRequested)
        self.delete_btn.clicked.connect(self.deleteRequested)
        self.lock_btn.clicked.connect(self.lockRequested)
        root.addWidget(self.rename_btn)
        root.addWidget(self.secret_btn)
        root.addWidget(self.delete_btn)
        root.addWidget(divider())
        root.addWidget(self.lock_btn)
        root.addStretch(1)
        footer = label(f"PyWallet v{APP_VERSION} · {NETWORK_LABEL}", "small")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)

    def refresh(self) -> None:
        self._wallet = self.vault.get_active_wallet()
        if self._wallet is None:
            return
        w = self._wallet
        self.avatar.set_text(w.name)
        self.name.setText(w.name)
        self.addr.setText(w.short_address)
        self.addr.setToolTip(w.address)
        is_seed = w.secret_type == SECRET_MNEMONIC
        self.kind.setText("Seed phrase" if is_seed else "Private key")
        self.secret_btn.setText("Lihat seed phrase" if is_seed else "Lihat private key")


# ==========================================================================
# Home: tab + navigasi bawah
# ==========================================================================
class HomePage(QWidget):
    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__(parent)
        self.wallet_tab = WalletTab(vault)
        self.swap_tab = SwapTab()
        self.profile_tab = ProfileTab(vault)

        self.tabs = QStackedWidget()
        for t in (self.wallet_tab, self.swap_tab, self.profile_tab):
            self.tabs.addWidget(t)

        nav = QFrame()
        nav.setObjectName("navbar")
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(12, 0, 12, 0)
        nav_lay.setSpacing(0)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, (icon_name, text) in enumerate(
            [("wallet", "Wallet"), ("swap", "Swap"), ("profile", "Profil")]
        ):
            b = NavButton(icon_name, text)
            group.addButton(b, i)
            nav_lay.addWidget(b)
            if i == 0:
                b.setChecked(True)
        group.idClicked.connect(self.tabs.setCurrentIndex)
        self._nav_group = group

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(nav)

    def refresh(self) -> None:
        self.wallet_tab.refresh()
        self.profile_tab.refresh()

    def show_tab(self, index: int) -> None:
        self._nav_group.button(index).setChecked(True)
        self.tabs.setCurrentIndex(index)
