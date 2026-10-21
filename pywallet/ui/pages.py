"""Layar utama: setup, unlock, onboarding kosong, dan tab Wallet / Swap / Profil."""
from __future__ import annotations

import threading
import time
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..avatars import AvatarStore
from ..config import APP_VERSION, MIN_PASSWORD_LENGTH, db_path
from ..formatting import (
    UNIT_ETH,
    UNIT_IDR,
    UNIT_USD,
    UNITS,
    format_amount,
    format_eth,
    format_idr,
    format_percent,
    format_price,
    format_usd,
)
from ..networks import MODE_LABELS, MODE_MAINNET, MODE_TESTNET, MODES, NETWORKS
from ..portfolio import AssetRow, PortfolioService, Snapshot, sort_assets
from ..tokens import TOKENS, active_networks, tokens_for_mode
from ..vault import SECRET_MNEMONIC, Vault, VaultError, WalletRecord, validate_new_password
from . import decor, fonts, icons, theme
from .dialogs import button
from .widgets import (
    Avatar,
    Card,
    CircleAction,
    GlowPage,
    GradientCard,
    NavButton,
    PasswordField,
    SlideStack,
    Sparkline,
    TokenIcon,
    copy_to_clipboard,
    divider,
    label,
    styled,
)

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
REFRESH_MS = 30_000
UNIT_LABELS = {UNIT_USD: "USD", UNIT_IDR: "IDR", UNIT_ETH: "ETH"}


def format_date(iso: str) -> str:
    try:
        d = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
    except ValueError:
        return iso


# ==========================================================================
# Halaman login / setup / onboarding (satu kerangka: latar cahaya + font Poppins)
# ==========================================================================
class LoginPage(GlowPage):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(fonts.login_stylesheet())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 20)
        col_host = QWidget()
        col_host.setMaximumWidth(400)
        self.col = QVBoxLayout(col_host)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(12)
        outer.addStretch(2)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(col_host, 100)      # lebar penuh sampai batas 400 px, lalu rata tengah
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(3)

        mark = icons.app_icon().pixmap(QSize(84, 84))
        mark_lbl = label()
        mark_lbl.setPixmap(mark)
        mark_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_lbl.setFixedHeight(88)
        self.col.addWidget(mark_lbl)
        brand = label("PyWallet", "brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.col.addWidget(brand)

        foot = QHBoxLayout()
        foot.addStretch(1)
        shield = label()
        shield.setPixmap(icons.pixmap("shield", 16, theme.MUTED_HEX, 2.0))
        note = label("Kunci wallet terenkripsi dan hanya tersimpan di komputer ini", "small")
        foot.addWidget(shield)
        foot.addWidget(note)
        foot.addStretch(1)
        outer.addLayout(foot)

    def add_heading(self, title: str, subtitle: str) -> None:
        t = label(title, "loginTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s = label(subtitle, "loginSub", wrap=True)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.col.addSpacing(4)
        self.col.addWidget(t)
        self.col.addWidget(s)
        self.col.addSpacing(8)


class SetupPage(LoginPage):
    completed = Signal()

    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__(parent)
        self.vault = vault
        self.add_heading("Selamat datang", "Buat master password untuk melindungi wallet-mu.")
        self.pw1 = PasswordField(f"Master password (min. {MIN_PASSWORD_LENGTH} karakter)")
        self.pw2 = PasswordField("Ulangi master password")
        self.pw2.returnPressed.connect(self._submit)
        self.col.addWidget(self.pw1)
        self.col.addWidget(self.pw2)
        self.col.addWidget(
            label(
                "Password ini tidak bisa dipulihkan. Jika lupa, wallet hanya bisa dipulihkan dengan "
                "seed phrase atau private key-nya.",
                "infobox",
                wrap=True,
            )
        )
        self.err = label("", "error", wrap=True)
        self.err.hide()
        self.col.addWidget(self.err)
        self.ok = button("Buat Password", "primary")
        self.ok.clicked.connect(self._submit)
        self.col.addWidget(self.ok)

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


class UnlockPage(LoginPage):
    unlocked = Signal()

    def __init__(self, vault: Vault, parent: QWidget | None = None):
        super().__init__(parent)
        self.vault = vault
        self._fails = 0
        self.add_heading("Selamat datang kembali", "Masukkan master password untuk membuka wallet-mu.")
        self.pw = PasswordField("Master password")
        self.pw.returnPressed.connect(self._submit)
        self.col.addWidget(self.pw)
        self.err = label("", "error", wrap=True)
        self.err.hide()
        self.col.addWidget(self.err)
        self.ok = button("Buka", "primary")
        self.ok.clicked.connect(self._submit)
        self.col.addWidget(self.ok)
        forgot = button("Lupa password?", "link")
        forgot.clicked.connect(self._forgot)
        self.col.addWidget(forgot, 0, Qt.AlignmentFlag.AlignHCenter)

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


class EmptyPage(LoginPage):
    createRequested = Signal()
    importRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.add_heading("Belum ada wallet", "Buat wallet baru, atau impor wallet yang sudah kamu punya.")
        create = button("Buat Wallet Baru", "primary")
        create.clicked.connect(self.createRequested)
        imp = button("Impor Wallet")
        imp.clicked.connect(self.importRequested)
        self.col.addWidget(create)
        self.col.addWidget(imp)


# ==========================================================================
# Baris token
# ==========================================================================
class TokenRow(Card):
    clicked = Signal(object)   # memancarkan AssetRow yang diklik

    def __init__(self, row: AssetRow, snap: Snapshot | None, unit: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.row = row
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Lihat detail dan contract address")
        t = row.token
        net = NETWORKS[t.network]
        dim = not row.has_balance
        strong = "rgba(245, 238, 233, 150)" if dim else theme.TEXT_STRONG

        self.setMinimumHeight(66)   # tinggi tetap agar daftar panjang bisa di-scroll, bukan menyempit
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(12)
        lay.addWidget(TokenIcon(t, 40))

        left = QVBoxLayout()
        left.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(styled(label(t.symbol), strong, 15, 700))
        fiat = snap is not None and snap.fiat_enabled
        if fiat and row.change_pct is not None:
            up = row.change_pct >= 0
            top.addWidget(styled(label(format_percent(row.change_pct)),
                                 theme.SUCCESS if up else theme.DANGER, 11, 600))
        top.addStretch(1)
        left.addLayout(top)
        sub = net.name + (" · Kustom" if t.custom else "")
        if snap is not None and not fiat:
            sub += " · Testnet"
        elif fiat and row.price_usd is not None:
            sub += f" · {format_price(row.price_usd)}"
        left.addWidget(styled(label(sub), theme.MUTED, 12))
        lay.addLayout(left, 1)

        amount = "—" if row.amount is None else format_amount(row.amount)
        if snap is None:
            value = ""
        elif not fiat:
            value = "Tidak bernilai" if row.has_balance else ""
        else:
            v = snap.row_value(row, unit)
            if v is None:
                value = "—"
            elif unit == UNIT_USD:
                value = format_usd(v)
            elif unit == UNIT_IDR:
                value = format_idr(v)
            else:
                value = format_eth(v)
        right = QVBoxLayout()
        right.setSpacing(1)
        a = styled(label(amount), strong, 15, 700)
        a.setAlignment(Qt.AlignmentFlag.AlignRight)
        v = styled(label(value), theme.MUTED, 12)
        v.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(a)
        right.addWidget(v)
        lay.addLayout(right)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row)
        super().mousePressEvent(event)


# ==========================================================================
# Tab Wallet (lobi)
# ==========================================================================
class WalletTab(QWidget):
    switchRequested = Signal(int)
    createRequested = Signal()
    importRequested = Signal()
    receiveRequested = Signal()
    sendRequested = Signal()
    historyRequested = Signal()
    addTokenRequested = Signal()
    tokenRequested = Signal(object)    # AssetRow yang diklik
    comingSoon = Signal(str)
    _loaded = Signal(int, object)

    def __init__(
        self,
        vault: Vault,
        avatar_store: AvatarStore | None = None,
        service: PortfolioService | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.vault = vault
        self.store = avatar_store
        self.service = service or PortfolioService()
        self.run_in_thread = True
        self._wallet: WalletRecord | None = None
        self.snapshot: Snapshot | None = None
        self._request_id = 0
        self._loading = False
        self._last_error = False

        mode = vault.get_pref("network_mode", MODE_TESTNET)
        self.mode = mode if mode in MODES else MODE_TESTNET
        unit = vault.get_pref("display_unit", UNIT_USD)
        self.unit = unit if unit in UNITS else UNIT_USD

        self._loaded.connect(self._on_loaded)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 0)
        root.setSpacing(0)

        # --- Header: pemilih wallet + mode jaringan ---------------------------
        head = QHBoxLayout()
        head.setSpacing(8)
        self.avatar = Avatar(36)
        self.switcher = QPushButton()
        self.switcher.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switcher.setIcon(icons.icon("chevron", 16, theme.TEXT, 2.2))
        self.switcher.setIconSize(QSize(16, 16))
        self.switcher.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.switcher.setStyleSheet(
            f"QPushButton {{ font-size: 16px; font-weight: 700; color: {theme.TEXT_STRONG};"
            f" background: transparent; border: none; padding: 6px 8px; border-radius: 10px; }}"
            f"QPushButton:hover {{ background: {theme.SURFACE}; }}"
        )
        self.switcher.clicked.connect(self._open_switcher)
        self.mode_btn = QPushButton()
        self.mode_btn.setObjectName("modeChip")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.setIconSize(QSize(10, 10))
        self.mode_btn.clicked.connect(self._open_mode_menu)
        head.addWidget(self.avatar)
        head.addWidget(self.switcher)
        head.addStretch(1)
        head.addWidget(self.mode_btn)
        root.addLayout(head)
        root.addSpacing(10)

        # --- Alamat + muat ulang -------------------------------------------------
        addr_row = QHBoxLayout()
        addr_row.setSpacing(2)
        self.addr = label("", "muted")
        self.copy_btn = QToolButton()
        self.copy_btn.setIcon(icons.icon("copy", 16, theme.TEXT, 2.0))
        self.copy_btn.setIconSize(QSize(16, 16))
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setToolTip("Salin alamat")
        self.copy_btn.clicked.connect(self._copy_address)
        self.status = label("", "small")
        self.refresh_btn = QToolButton()
        self.refresh_btn.setIcon(icons.icon("refresh", 16, theme.TEXT, 2.0))
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setToolTip("Muat ulang saldo dan harga")
        self.refresh_btn.clicked.connect(self.refresh_data)
        addr_row.addWidget(self.addr)
        addr_row.addWidget(self.copy_btn)
        addr_row.addStretch(1)
        addr_row.addWidget(self.status)
        addr_row.addWidget(self.refresh_btn)
        root.addLayout(addr_row)
        root.addSpacing(8)

        # --- Kartu saldo ------------------------------------------------------------
        card = GradientCard()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(styled(label("Total aset"), theme.TEXT, 13, 600))
        top.addStretch(1)
        self.unit_group = QButtonGroup(self)
        self.unit_group.setExclusive(True)
        self.unit_buttons: dict[str, QPushButton] = {}
        for i, u in enumerate(UNITS):
            b = QPushButton(UNIT_LABELS[u])
            b.setObjectName("pill")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(u == self.unit)
            self.unit_group.addButton(b, i)
            self.unit_buttons[u] = b
            top.addWidget(b)
        self.unit_group.idClicked.connect(lambda i: self.set_unit(UNITS[i]))
        cl.addLayout(top)
        self.balance = label("—", "balance")
        cl.addWidget(self.balance)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.change_lbl = label("")
        self.note_lbl = styled(label(""), theme.MUTED, 12)
        bottom.addWidget(self.change_lbl)
        bottom.addWidget(self.note_lbl)
        bottom.addStretch(1)
        cl.addLayout(bottom)
        root.addWidget(card)
        root.addSpacing(18)

        # --- Tombol aksi ---------------------------------------------------------------
        actions = QHBoxLayout()
        send = CircleAction("send", "Kirim")
        recv = CircleAction("receive", "Terima")
        trade = CircleAction("swap", "Trade")
        send.clicked.connect(self.sendRequested)
        recv.clicked.connect(self.receiveRequested)
        trade.clicked.connect(lambda: self.comingSoon.emit("Trade"))
        for w in (send, recv, trade):
            actions.addWidget(w, 1)
        root.addLayout(actions)
        root.addSpacing(16)

        # --- Strip harga ETH -------------------------------------------------------------------
        strip = Card()
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(14, 9, 14, 9)
        sl.setSpacing(10)
        sl.addWidget(TokenIcon(TOKENS["ethereum"][0], 32))
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        tcol.addWidget(styled(label("Ethereum"), theme.TEXT_STRONG, 14, 700))
        self.eth_sub = styled(label("Harga pasar ETH"), theme.MUTED, 11)
        tcol.addWidget(self.eth_sub)
        sl.addLayout(tcol, 1)
        pcol = QVBoxLayout()
        pcol.setSpacing(0)
        self.eth_price = styled(label("—"), theme.TEXT_STRONG, 14, 700)
        self.eth_price.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.eth_change = label("")
        self.eth_change.setAlignment(Qt.AlignmentFlag.AlignRight)
        pcol.addWidget(self.eth_price)
        pcol.addWidget(self.eth_change)
        sl.addLayout(pcol)
        self.spark = Sparkline()
        sl.addWidget(self.spark)
        root.addWidget(strip)
        root.addSpacing(10)

        self.hint = label(
            "Belum punya ETH Sepolia? Salin alamat wallet-mu di atas, lalu minta ETH testnet gratis dari "
            "faucet Sepolia. ETH testnet tidak bernilai uang.",
            "infobox",
            wrap=True,
        )
        self.hint.hide()
        root.addWidget(self.hint)

        # --- Judul daftar token -----------------------------------------------------------------
        header = QHBoxLayout()
        title = label("Token")
        title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {theme.TEXT_STRONG};")
        header.addWidget(title)
        header.addStretch(1)
        self.count_lbl = label("", "small")
        header.addWidget(self.count_lbl)
        header.addSpacing(8)
        self.history_btn = button("Riwayat", "pill")
        self.history_btn.setToolTip("Riwayat transaksi wallet ini")
        self.history_btn.clicked.connect(self.historyRequested)
        header.addWidget(self.history_btn)
        header.addSpacing(6)
        self.add_token_btn = button("＋ Token", "pill")
        self.add_token_btn.setToolTip("Tambah token lewat contract address")
        self.add_token_btn.clicked.connect(self.addTokenRequested)
        header.addWidget(self.add_token_btn)
        root.addSpacing(4)
        root.addLayout(header)
        underline = QFrame()
        underline.setFixedSize(34, 3)
        underline.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 1px;")
        root.addSpacing(4)
        root.addWidget(underline)
        root.addWidget(divider())
        root.addSpacing(8)

        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 0, 12)
        self.list_lay.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.list_host)
        scroll.viewport().setAutoFillBackground(False)
        self.list_host.setAutoFillBackground(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

    # --- latar: gradasi lembut di bagian atas seperti Bitget -------------------------------
    def paintEvent(self, _event) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QLinearGradient, QPainter

        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        grad = QLinearGradient(0, 0, 0, 260)
        top = QColor(theme.ACCENT_DEEP)
        top.setAlpha(200)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, QColor(theme.BG))
        p.fillRect(QRectF(0, 0, self.width(), 260), grad)
        decor.paint_backdrop(p, self.width(), self.height(), "lobby")

    # --- data ----------------------------------------------------------------------------------------
    def refresh(self) -> None:
        """Dipanggil saat wallet aktif berganti / data wallet berubah."""
        wallet = self.vault.get_active_wallet()
        if (wallet and self._wallet and wallet.address != self._wallet.address) or wallet is None:
            self.snapshot = None
        self._wallet = wallet
        self._render()
        if self.snapshot is None:
            self.refresh_data()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._wallet and (self.snapshot is None or time.time() - self.snapshot.fetched_at > REFRESH_MS / 1000):
            self.refresh_data()

    def _auto_refresh(self) -> None:
        if self.isVisible() and not self._loading:
            self.refresh_data()

    def refresh_data(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet is None:
            return
        self._request_id += 1
        rid, address, mode = self._request_id, wallet.address, self.mode
        custom = self.vault.list_custom_tokens()   # dibaca di thread utama (SQLite), lalu dipakai di thread kerja
        hidden = self.vault.list_hidden_tokens()
        price_cache = self.vault.get_price_cache()
        self._loading = True
        self.status.setText("Memuat…")
        self.status.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")

        def work() -> None:
            try:
                result = self.service.load(address, mode, custom, hidden, price_cache)
            except Exception as exc:  # noqa: BLE001 - apa pun yang gagal tidak boleh menjatuhkan UI
                result = exc
            try:
                self._loaded.emit(rid, result)
            except RuntimeError:   # widget sudah dihancurkan saat jendela ditutup
                pass

        if self.run_in_thread:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def _persist_discoveries(self, result) -> None:
        """Simpan ID koin dan harga yang baru ditemukan. Dilakukan SEBELUM memeriksa apakah hasilnya kedaluwarsa:
        hasil yang terpakai-buang pun sudah menghabiskan kuota API, jadi temuannya jangan sampai hilang."""
        for (network, addr), coin_id in result.resolved_ids.items():
            try:
                self.vault.set_custom_coingecko_id(network, addr, coin_id)
            except VaultError:
                pass
        if result.price_updates:
            self.vault.update_price_cache(result.price_updates)

    def _on_loaded(self, rid: int, result) -> None:
        if not isinstance(result, Exception):
            self._persist_discoveries(result)
        if rid != self._request_id:
            return   # hasil kedaluwarsa (wallet/mode sudah berganti)
        self._loading = False
        if isinstance(result, Exception):
            self.status.setText("Gagal memuat data")
            self.status.setStyleSheet(f"color: {theme.DANGER}; font-size: 12px;")
            return
        self.snapshot = result
        self._render()

    # --- tampilan ---------------------------------------------------------------------------------------
    def set_unit(self, unit: str) -> None:
        if unit not in UNITS:
            return
        self.unit = unit
        self.vault.set_pref("display_unit", unit)
        self.unit_buttons[unit].setChecked(True)
        self._render()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES or mode == self.mode:
            return
        self.mode = mode
        self.vault.set_pref("network_mode", mode)
        self.snapshot = None
        self._render()
        self.refresh_data()

    def _open_mode_menu(self) -> None:
        menu = QMenu(self)
        for mode in (MODE_MAINNET, MODE_TESTNET):
            detail = ", ".join(n.name for n in active_networks(mode, (), ()))
            act = menu.addAction(f"{MODE_LABELS[mode]}   ·   {detail}")
            act.setCheckable(True)
            act.setChecked(mode == self.mode)
            act.triggered.connect(lambda _=False, m=mode: self.set_mode(m))
        menu.exec(self.mode_btn.mapToGlobal(self.mode_btn.rect().bottomRight() - self._menu_offset(menu)))

    @staticmethod
    def _menu_offset(menu: QMenu):
        from PySide6.QtCore import QPoint

        return QPoint(menu.sizeHint().width(), 0)

    def _set_balance_text(self, text: str) -> None:
        size = 38 if len(text) <= 10 else 31 if len(text) <= 14 else 25
        self.balance.setStyleSheet(
            f"font-size: {size}px; font-weight: 700; color: {theme.TEXT_STRONG}; background: transparent;"
        )
        self.balance.setText(text)

    def _render(self) -> None:
        wallet = self._wallet
        is_test = self.mode == MODE_TESTNET
        # header
        if wallet:
            self.avatar.set_wallet(wallet, self.store)
            self.switcher.setText(wallet.name)
            self.addr.setText(wallet.short_address)
        self.mode_btn.setText(f"{MODE_LABELS[self.mode]}  ▾")
        self.mode_btn.setIcon(icons.dot_icon("#D9A35B" if is_test else theme.SUCCESS))

        snap = self.snapshot
        if snap is not None and wallet and (snap.address != wallet.address or snap.mode != self.mode):
            snap = None

        # kartu saldo
        change_text, change_color = "", theme.MUTED
        note = ""
        if snap is None:
            self._set_balance_text("—")
        else:
            total = snap.total_in(self.unit)
            if total is None:
                text = "—"
                note = "Kurs belum tersedia"
            elif self.unit == UNIT_USD:
                text = format_usd(total)
            elif self.unit == UNIT_IDR:
                text = format_idr(total)
            else:
                text = format_eth(total)
            self._set_balance_text(text)
            if not snap.fiat_enabled:
                note = "Aset testnet tidak bernilai uang" if self.unit != UNIT_ETH else "Saldo ETH Sepolia (testnet)"
            else:
                chg = snap.change_pct()
                if chg is not None and self.unit != UNIT_ETH:
                    arrow = "▲" if chg >= 0 else "▼"
                    change_text = f"{arrow} {format_percent(abs(chg)).lstrip('+')}"
                    change_color = theme.SUCCESS if chg >= 0 else theme.DANGER
                    note = "24 jam"
                elif self.unit == UNIT_ETH:
                    note = "Setara nilai seluruh aset dalam ETH"
                if snap.has_unpriced_holdings():
                    note = "Sebagian aset belum ada harganya"
        self.change_lbl.setText(change_text)
        self.change_lbl.setVisible(bool(change_text))
        styled(self.change_lbl, change_color, 13, 700)
        self.note_lbl.setText(note)

        # strip ETH
        eth_usd = snap.eth_usd if snap else None
        self.eth_price.setText(format_price(eth_usd) if eth_usd else "—")
        if snap and snap.eth_change is not None:
            up = snap.eth_change >= 0
            self.eth_change.setText(f"{'▲' if up else '▼'} {format_percent(abs(snap.eth_change)).lstrip('+')}")
            styled(self.eth_change, theme.SUCCESS if up else theme.DANGER, 11, 600)
        else:
            self.eth_change.setText("")
        self.spark.set_values(snap.eth_spark if snap else [])
        self.eth_sub.setText("Harga pasar ETH (mainnet)" if is_test else "Harga pasar ETH")

        # status
        if snap is not None and not self._loading:
            if snap.errors:
                self.status.setText(" · ".join(snap.errors))
                hint = "Coba muat ulang. Endpoint RPC/harga publik kadang membatasi permintaan."
                self.status.setToolTip("\n".join([hint, *snap.details]))
                self.status.setStyleSheet(f"color: {theme.DANGER}; font-size: 12px;")
            else:
                self.status.setText("Diperbarui " + time.strftime("%H:%M", time.localtime(snap.fetched_at)))
                self.status.setToolTip("")
                self.status.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")

        self.hint.setVisible(is_test and snap is not None and not snap.has_holdings)
        self._render_rows(snap)

    def _render_rows(self, snap: Snapshot | None) -> None:
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)      # langsung lepas agar tidak tampil ganda sebelum benar-benar dihapus
                w.deleteLater()
        rows = snap.rows if snap else sort_assets(
            [AssetRow(t, None, None, None) for t in tokens_for_mode(self.mode, self.vault.list_custom_tokens(), self.vault.list_hidden_tokens())]
        )
        held = [r for r in rows if r.has_balance]
        rest = [r for r in rows if not r.has_balance]
        self.count_lbl.setText(f"{len(held)} dimiliki · {len(rows)} aset" if snap else f"{len(rows)} aset")
        for r in held:
            self.list_lay.addWidget(self._token_row(r, snap))
        if rest:
            if snap is not None and len(rows) > 1:
                cap = "Token populer lainnya" if held else "Token populer"
                self.list_lay.addWidget(styled(label(cap), theme.MUTED, 12, 600))
            for r in rest:
                self.list_lay.addWidget(self._token_row(r, snap))
        self.list_lay.addStretch(1)

    def _token_row(self, r: AssetRow, snap: Snapshot | None) -> TokenRow:
        row = TokenRow(r, snap, self.unit)
        row.clicked.connect(self.tokenRequested)
        return row

    def reload_tokens(self) -> None:
        """Dipanggil setelah daftar token kustom berubah: muat ulang daftar dan saldo."""
        self.snapshot = None
        self._render()
        self.refresh_data()

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
class _BackdropMixin:
    """Latar polos + motif dekoratif beropacity rendah (lihat decor.py)."""

    backdrop_kind = "profile"

    def paintEvent(self, _event) -> None:
        from PySide6.QtGui import QColor, QPainter

        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        decor.paint_backdrop(p, self.width(), self.height(), self.backdrop_kind)


class SwapTab(_BackdropMixin, QWidget):
    backdrop_kind = "swap"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.addStretch(2)
        disc = label()
        disc.setPixmap(icons.pixmap("swap", 40, theme.BG, 2.0))
        disc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disc.setFixedSize(84, 84)
        disc.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 42px;")
        lay.addWidget(disc, 0, Qt.AlignmentFlag.AlignHCenter)
        title = label("Swap", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = label("Tukar token langsung dari wallet-mu lewat PancakeSwap.", "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(10)
        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 14)
        cl.setSpacing(8)
        cl.addWidget(styled(label("Segera hadir"), theme.TEXT_STRONG, 14, 700))
        for line in (
            "Estimasi harga dan biaya sebelum menukar",
            "Batas slippage yang bisa diatur",
            "Konfirmasi dengan master password",
        ):
            cl.addWidget(styled(label("•  " + line, wrap=True), theme.TEXT, 13))
        lay.addWidget(card)
        lay.addStretch(3)


# ==========================================================================
# Tab Profil
# ==========================================================================
class ProfileTab(_BackdropMixin, QWidget):
    backdrop_kind = "profile"
    renameRequested = Signal()
    viewSecretRequested = Signal()
    deleteRequested = Signal()
    lockRequested = Signal()
    avatarRequested = Signal()
    removeAvatarRequested = Signal()
    decorToggled = Signal()
    apiKeyRequested = Signal()

    def __init__(self, vault: Vault, avatar_store: AvatarStore | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.vault = vault
        self.store = avatar_store
        self._wallet: WalletRecord | None = None
        # Isi profil bisa lebih tinggi dari jendela kecil, jadi diletakkan di area yang bisa digulir.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 20, 18, 12)
        root.setSpacing(10)
        root.addWidget(label("Profil", "title"))

        hero = GradientCard()
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(16, 16, 16, 16)
        hl.setSpacing(16)
        self.avatar = Avatar(84, badge=True)
        self.avatar.clicked.connect(self.avatarRequested)
        hl.addWidget(self.avatar)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.name = label("", "heading")
        self.addr = label("", "muted", selectable=True)
        self.kind = label("", "chip")
        info.addStretch(1)
        info.addWidget(self.name)
        info.addWidget(self.addr)
        kind_row = QHBoxLayout()
        kind_row.addWidget(self.kind)
        kind_row.addStretch(1)
        info.addSpacing(4)
        info.addLayout(kind_row)
        info.addStretch(1)
        hl.addLayout(info, 1)
        root.addWidget(hero)

        # Rincian wallet
        details = Card()
        dl = QVBoxLayout(details)
        dl.setContentsMargins(16, 10, 16, 10)
        dl.setSpacing(6)
        self.full_addr = label("", "small", wrap=True, selectable=True)
        self.created = styled(label(""), theme.TEXT_STRONG, 13, 600)
        self.path = styled(label(""), theme.TEXT_STRONG, 13, 600)
        self._path_row = self._detail_row("Derivation path", self.path)
        dl.addWidget(styled(label("Alamat lengkap"), theme.MUTED, 12))
        dl.addWidget(self.full_addr)
        dl.addWidget(divider())
        dl.addLayout(self._detail_row("Dibuat", self.created))
        dl.addLayout(self._path_row)
        root.addWidget(details)
        root.addSpacing(2)

        self.photo_btn = button("Ganti foto profil", "menuRow")
        self.remove_photo_btn = button("Hapus foto profil", "menuRow")
        self.rename_btn = button("Ganti nama wallet", "menuRow")
        self.secret_btn = button("Lihat seed phrase", "menuRow")
        self.delete_btn = button("Hapus wallet", "menuRowDanger")
        self.decor_btn = button("Hiasan latar: hidup", "menuRow")
        self.api_btn = button("API key riwayat: belum diatur", "menuRow")
        self.lock_btn = button("Kunci aplikasi sekarang", "menuRow")
        self.api_btn.clicked.connect(self.apiKeyRequested)
        self.photo_btn.clicked.connect(self.avatarRequested)
        self.remove_photo_btn.clicked.connect(self.removeAvatarRequested)
        self.rename_btn.clicked.connect(self.renameRequested)
        self.secret_btn.clicked.connect(self.viewSecretRequested)
        self.delete_btn.clicked.connect(self.deleteRequested)
        self.lock_btn.clicked.connect(self.lockRequested)
        self.decor_btn.clicked.connect(self.decorToggled)
        for b in (self.photo_btn, self.remove_photo_btn, self.rename_btn, self.secret_btn, self.decor_btn, self.api_btn, self.delete_btn):
            root.addWidget(b)
        root.addWidget(divider())
        root.addWidget(self.lock_btn)
        root.addStretch(1)
        footer = label(f"PyWallet v{APP_VERSION}", "small")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(footer)

    @staticmethod
    def _detail_row(title: str, value: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(styled(label(title), theme.MUTED, 12))
        row.addStretch(1)
        row.addWidget(value)
        return row

    def set_decor_state(self, on: bool) -> None:
        self.decor_btn.setText("Hiasan latar: hidup" if on else "Hiasan latar: mati")

    def refresh(self) -> None:
        self.api_btn.setText("API key riwayat: terpasang" if self.vault.get_history_api_key() else "API key riwayat: belum diatur")
        self._wallet = self.vault.get_active_wallet()
        if self._wallet is None:
            return
        w = self._wallet
        self.avatar.set_wallet(w, self.store)
        self.name.setText(w.name)
        self.addr.setText(w.short_address)
        self.full_addr.setText(w.address)
        self.created.setText(format_date(w.created_at))
        is_seed = w.secret_type == SECRET_MNEMONIC
        self.kind.setText("Seed phrase" if is_seed else "Private key")
        self.path.setText(w.derivation_path or "—")
        for i in range(self._path_row.count()):
            item = self._path_row.itemAt(i).widget()
            if item:
                item.setVisible(is_seed)
        self.secret_btn.setText("Lihat seed phrase" if is_seed else "Lihat private key")
        self.remove_photo_btn.setVisible(self.avatar.has_photo)
        self.photo_btn.setText("Ganti foto profil" if self.avatar.has_photo else "Pilih foto profil")


# ==========================================================================
# Home: tab + navigasi bawah
# ==========================================================================
class HomePage(QWidget):
    def __init__(
        self,
        vault: Vault,
        avatar_store: AvatarStore | None = None,
        service: PortfolioService | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.wallet_tab = WalletTab(vault, avatar_store, service)
        self.swap_tab = SwapTab()
        self.profile_tab = ProfileTab(vault, avatar_store)

        self.tabs = SlideStack()
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
        group.idClicked.connect(self.tabs.slide_to)
        self._nav_group = group

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(nav)

    def refresh(self) -> None:
        self.wallet_tab.refresh()
        self.profile_tab.refresh()

    def repaint_decor(self) -> None:
        for t in (self.wallet_tab, self.swap_tab, self.profile_tab):
            t.update()

    def show_tab(self, index: int) -> None:
        self._nav_group.button(index).setChecked(True)
        self.tabs.slide_to(index)
