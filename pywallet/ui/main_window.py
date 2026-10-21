"""Jendela utama: mengatur alur setup -> unlock -> lobi dan menjalankan dialog CRUD."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from ..avatars import IMAGE_FILTER, AvatarError, AvatarStore
from ..config import APP_NAME, HEARTBEAT_MS, avatars_dir
from ..networks import MODE_LABELS
from ..portfolio import PortfolioService
from ..tokens import active_networks
from ..vault import Vault
from . import decor, icons
from .dialogs import (
    CreateWalletDialog,
    DeleteWalletDialog,
    ImportWalletDialog,
    PasswordDialog,
    ReceiveDialog,
    RenameDialog,
    SecretDialog,
)
from .pages import EmptyPage, HomePage, SetupPage, UnlockPage
from .history_dialog import ApiKeyDialog, HistoryDialog
from .send_dialog import SendDialog
from .token_dialogs import AddTokenDialog, TokenDetailDialog

PAGE_SETUP, PAGE_UNLOCK, PAGE_EMPTY, PAGE_HOME = range(4)


class MainWindow(QMainWindow):
    def __init__(
        self,
        vault: Vault,
        service: PortfolioService | None = None,
        avatar_store: AvatarStore | None = None,
        async_loading: bool = True,
    ):
        super().__init__()
        self.vault = vault
        self.store = avatar_store or AvatarStore(avatars_dir())
        self._unlocked = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.resize(460, 840)
        self.setMinimumSize(400, 660)

        decor.set_enabled(vault.get_pref("decor", "1") != "0")
        self.setup_page = SetupPage(vault)
        self.unlock_page = UnlockPage(vault)
        self.empty_page = EmptyPage()
        self.home = HomePage(vault, self.store, service)
        self.home.wallet_tab.run_in_thread = async_loading

        self.stack = QStackedWidget()
        for page in (self.setup_page, self.unlock_page, self.empty_page, self.home):
            self.stack.addWidget(page)

        # Konten dibatasi lebarnya dan diletakkan di tengah agar tetap rapi saat jendela dibesarkan.
        root = QWidget()
        root.setObjectName("root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        self.stack.setMaximumWidth(620)
        lay.addWidget(self.stack, 10_000)   # pinggir hanya terisi saat jendela lebih lebar dari 620 px
        lay.addStretch(1)
        self.setCentralWidget(root)

        self.setup_page.completed.connect(self._enter_app)
        self.unlock_page.unlocked.connect(self._enter_app)
        self.empty_page.createRequested.connect(self.create_wallet)
        self.empty_page.importRequested.connect(self.import_wallet)

        wt = self.home.wallet_tab
        wt.switchRequested.connect(self.switch_wallet)
        wt.createRequested.connect(self.create_wallet)
        wt.importRequested.connect(self.import_wallet)
        wt.receiveRequested.connect(self.receive)
        wt.sendRequested.connect(self.send)
        wt.historyRequested.connect(self.show_history)
        wt.comingSoon.connect(self._coming_soon)
        wt.addTokenRequested.connect(self.add_token)
        wt.tokenRequested.connect(self.show_token)

        pt = self.home.profile_tab
        pt.renameRequested.connect(self.rename_wallet)
        pt.viewSecretRequested.connect(self.view_secret)
        pt.deleteRequested.connect(self.delete_wallet)
        pt.lockRequested.connect(self.lock_app)
        pt.avatarRequested.connect(self.change_avatar)
        pt.removeAvatarRequested.connect(self.remove_avatar)
        pt.decorToggled.connect(self.toggle_decor)
        pt.apiKeyRequested.connect(self.set_api_key)
        pt.set_decor_state(decor.ENABLED)

        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(self._beat)
        self._heartbeat.start(HEARTBEAT_MS)

    # ------------------------------------------------------------------
    # Alur awal
    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self.vault.is_initialized():
            self.stack.setCurrentIndex(PAGE_SETUP)
        elif self.vault.within_grace():
            self._enter_app()   # dalam jeda 5 menit: lobi terbuka tanpa password
        else:
            self._show_unlock()

    def _show_unlock(self) -> None:
        self._unlocked = False
        self.stack.setCurrentIndex(PAGE_UNLOCK)
        self.unlock_page.focus_input()

    def _enter_app(self) -> None:
        self._unlocked = True
        self.vault.touch()
        self.refresh_all()

    def refresh_all(self) -> None:
        if self.vault.list_wallets():
            self.home.refresh()
            self.stack.setCurrentIndex(PAGE_HOME)
        else:
            self.stack.setCurrentIndex(PAGE_EMPTY)

    def _beat(self) -> None:
        if self._unlocked:
            self.vault.touch()

    def closeEvent(self, event) -> None:
        if self._unlocked:
            self.vault.touch()   # menandai awal jeda 5 menit
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Aksi CRUD
    # ------------------------------------------------------------------
    def create_wallet(self) -> None:
        dlg = CreateWalletDialog(self.vault, self)
        if dlg.exec():
            self.refresh_all()
            self.home.show_tab(0)

    def import_wallet(self) -> None:
        dlg = ImportWalletDialog(self.vault, self)
        if dlg.exec():
            self.refresh_all()
            self.home.show_tab(0)

    def switch_wallet(self, wallet_id: int) -> None:
        self.vault.set_active_wallet(wallet_id)
        self.home.refresh()

    def rename_wallet(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet and RenameDialog(self.vault, wallet, self).exec():
            self.home.refresh()

    def view_secret(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet is None:
            return
        kind = "seed phrase" if wallet.secret_type == "mnemonic" else "private key"
        ask = PasswordDialog(
            f"Lihat {kind}",
            f"Masukkan master password untuk menampilkan {kind} wallet “{wallet.name}”.",
            action=lambda pw: self.vault.reveal_secret(wallet.id, pw),
            ok_text="Tampilkan",
            parent=self,
        )
        if ask.exec() and ask.result_value is not None:
            SecretDialog(wallet, ask.result_value, self).exec()
            ask.result_value = None

    def delete_wallet(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet is None:
            return
        dlg = DeleteWalletDialog(self.vault, wallet, self)
        if dlg.exec() and dlg.deleted:
            self.store.remove(wallet.avatar)   # foto profil ikut dihapus bersama wallet-nya
            self.refresh_all()
            self.home.show_tab(0)

    # ------------------------------------------------------------------
    # Foto profil
    # ------------------------------------------------------------------
    def change_avatar(self, source: str | None = None) -> None:
        """Ganti foto profil wallet aktif. `source` hanya dipakai tes (melewati dialog file).

        Alur (penjelasan lengkap: docs/PANDUAN.md, bagian 3):
          1. pilih file gambar dari komputer
          2. AvatarStore memotong persegi, memperkecil, lalu menyimpan salinan di folder avatars
          3. nama file baru dicatat di database (kolom `avatar` milik wallet)
          4. foto lama dihapus, lalu semua halaman digambar ulang
        """
        wallet = self.vault.get_active_wallet()
        if wallet is None:
            return
        if not source:
            source, _ = QFileDialog.getOpenFileName(self, "Pilih foto profil", "", IMAGE_FILTER)
            if not source:
                return
        try:
            filename = self.store.import_image(wallet.id, source)
        except AvatarError as exc:
            QMessageBox.warning(self, "Foto profil", str(exc))
            return
        self.vault.set_avatar(wallet.id, filename)
        self.store.remove(wallet.avatar)       # buang foto lama
        self.home.refresh()

    def remove_avatar(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet is None or not wallet.avatar:
            return
        self.vault.set_avatar(wallet.id, None)
        self.store.remove(wallet.avatar)
        self.home.refresh()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------
    def add_token(self) -> None:
        wt = self.home.wallet_tab
        dlg = AddTokenDialog(self.vault, wt.service, wt.mode, self)
        dlg.run_in_thread = wt.run_in_thread
        accepted = dlg.exec() and dlg.added is not None
        dlg.deleteLater()                    # dialog sekali pakai: lepaskan setelah ditutup
        if accepted:
            wt.reload_tokens()

    def show_token(self, row) -> None:
        dlg = TokenDetailDialog(row, self)
        accepted = dlg.exec() and dlg.removed
        dlg.deleteLater()
        if accepted:
            if row.token.custom:
                self.vault.remove_custom_token(row.token.network, row.token.address)
            else:
                self.vault.hide_builtin_token(row.token.network, row.token.address)
            self.home.wallet_tab.reload_tokens()

    def toggle_decor(self) -> None:
        on = not decor.ENABLED
        decor.set_enabled(on)
        self.vault.set_pref("decor", "1" if on else "0")
        self.home.profile_tab.set_decor_state(on)
        for page in (self.setup_page, self.unlock_page, self.empty_page):
            page.update()
        self.home.repaint_decor()

    def send(self) -> None:
        wallet = self.vault.get_active_wallet()
        wt = self.home.wallet_tab
        snap = wt.snapshot
        if wallet is None:
            return
        if snap is None or snap.address != wallet.address or snap.mode != wt.mode:
            QMessageBox.information(self, "Kirim", "Saldo belum selesai dimuat. Tunggu sebentar lalu coba lagi.")
            return
        dlg = SendDialog(self.vault, wt.service, wallet, snap.rows, self)
        dlg.run_in_thread = wt.run_in_thread
        dlg.exec()
        sent = dlg.sent_hash is not None
        dlg.deleteLater()
        if sent:
            wt.reload_tokens()               # muat ulang saldo setelah transaksi dikirim

    def set_api_key(self) -> None:
        dlg = ApiKeyDialog(self.vault, self)
        dlg.exec()
        dlg.deleteLater()
        self.home.profile_tab.refresh()

    def show_history(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet is None:
            return
        wt = self.home.wallet_tab
        dlg = HistoryDialog(self.vault, wt.service, wallet, wt.mode, self, run_in_thread=wt.run_in_thread)
        dlg.exec()
        dlg.deleteLater()

    def receive(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet:
            mode = self.home.wallet_tab.mode
            names = ", ".join(n.name for n in active_networks(mode))
            ReceiveDialog(wallet, f"{names} ({MODE_LABELS[mode]})", self).exec()

    def lock_app(self) -> None:
        self.vault.lock_now()
        self._show_unlock()

    def _coming_soon(self, feature: str) -> None:
        stage = {"Trade": "tahap 5"}.get(feature, "tahap berikutnya")
        QMessageBox.information(self, feature, f"Fitur {feature} akan hadir di {stage}.")
