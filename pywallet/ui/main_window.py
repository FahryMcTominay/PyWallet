"""Jendela utama: mengatur alur setup -> unlock -> lobi dan menjalankan dialog CRUD."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from ..config import APP_NAME, HEARTBEAT_MS
from ..vault import Vault
from . import icons
from .dialogs import (
    CreateWalletDialog,
    DeleteWalletDialog,
    ImportWalletDialog,
    PasswordDialog,
    ReceiveDialog,
    RenameDialog,
    SecretDialog,
)
from .pages import NETWORK_LABEL, EmptyPage, HomePage, SetupPage, UnlockPage

PAGE_SETUP, PAGE_UNLOCK, PAGE_EMPTY, PAGE_HOME = range(4)


class MainWindow(QMainWindow):
    def __init__(self, vault: Vault):
        super().__init__()
        self.vault = vault
        self._unlocked = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.resize(460, 820)
        self.setMinimumSize(400, 640)

        self.setup_page = SetupPage(vault)
        self.unlock_page = UnlockPage(vault)
        self.empty_page = EmptyPage()
        self.home = HomePage(vault)

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
        lay.addWidget(self.stack, 100)
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
        wt.comingSoon.connect(self._coming_soon)

        pt = self.home.profile_tab
        pt.renameRequested.connect(self.rename_wallet)
        pt.viewSecretRequested.connect(self.view_secret)
        pt.deleteRequested.connect(self.delete_wallet)
        pt.lockRequested.connect(self.lock_app)

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
            self.refresh_all()
            self.home.show_tab(0)

    def receive(self) -> None:
        wallet = self.vault.get_active_wallet()
        if wallet:
            ReceiveDialog(wallet, NETWORK_LABEL, self).exec()

    def lock_app(self) -> None:
        self.vault.lock_now()
        self._show_unlock()

    def _coming_soon(self, feature: str) -> None:
        stage = {"Kirim": "tahap 4", "Trade": "tahap 5"}.get(feature, "tahap berikutnya")
        QMessageBox.information(self, feature, f"Fitur {feature} akan hadir di {stage}.")
