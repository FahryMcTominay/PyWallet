"""Smoke test UI (tanpa layar, memakai platform Qt 'offscreen')."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pywallet import wallet_core  # noqa: E402
from pywallet.config import GRACE_SECONDS  # noqa: E402
from pywallet.db import Database  # noqa: E402
from pywallet.ui import theme  # noqa: E402
from pywallet.ui.dialogs import (  # noqa: E402
    CreateWalletDialog,
    DeleteWalletDialog,
    ImportWalletDialog,
    PasswordDialog,
    RenameDialog,
)
from pywallet.ui.main_window import PAGE_EMPTY, PAGE_HOME, PAGE_SETUP, PAGE_UNLOCK, MainWindow  # noqa: E402
from pywallet.vault import Vault  # noqa: E402

PW = "rahasia-kuat-123"
FAST_KDF = {"n": 2**10, "r": 8, "p": 1}
HARDHAT_MNEMONIC = "test test test test test test test test test test test junk"
HARDHAT_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.build_qss())
    return a


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def vault(tmp_path, clock):
    return Vault(Database(tmp_path / "ui.db"), clock=clock)


@pytest.fixture
def ready_vault(vault):
    vault.setup_master_password(PW, kdf=FAST_KDF)
    return vault


def test_first_run_shows_setup_then_empty(app, vault):
    win = MainWindow(vault)
    win.start()
    assert win.stack.currentIndex() == PAGE_SETUP
    win.setup_page.pw1.edit.setText("pendek")
    win.setup_page.pw2.edit.setText("pendek")
    win.setup_page._submit()
    assert win.stack.currentIndex() == PAGE_SETUP        # ditolak: < 8 karakter
    win.setup_page.pw1.edit.setText(PW)
    win.setup_page.pw2.edit.setText("beda")
    win.setup_page._submit()
    assert win.stack.currentIndex() == PAGE_SETUP        # ditolak: tidak sama
    win.setup_page.pw2.edit.setText(PW)
    win.setup_page._submit()
    assert vault.is_initialized()
    assert win.stack.currentIndex() == PAGE_EMPTY


def test_unlock_flow_and_grace(app, ready_vault, clock):
    v = ready_vault
    # Belum pernah aktif -> wajib password
    win = MainWindow(v)
    win.start()
    assert win.stack.currentIndex() == PAGE_UNLOCK
    win.unlock_page.pw.edit.setText("salah")
    win.unlock_page._submit()
    assert win.stack.currentIndex() == PAGE_UNLOCK
    win.unlock_page.pw.edit.setText(PW)
    win.unlock_page._submit()
    assert win.stack.currentIndex() == PAGE_EMPTY        # belum ada wallet

    # Tutup aplikasi, buka lagi < 5 menit -> tanpa password
    win.close()
    clock.t += GRACE_SECONDS - 10
    win2 = MainWindow(v)
    win2.start()
    assert win2.stack.currentIndex() == PAGE_EMPTY       # langsung masuk, bukan halaman unlock

    # Buka lagi > 5 menit -> minta password
    win2.close()
    clock.t += GRACE_SECONDS + 1
    win3 = MainWindow(v)
    win3.start()
    assert win3.stack.currentIndex() == PAGE_UNLOCK


def test_lock_now_forces_password(app, ready_vault):
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    win = MainWindow(v)
    win.start()
    win._enter_app()
    assert win.stack.currentIndex() == PAGE_HOME
    win.lock_app()
    assert win.stack.currentIndex() == PAGE_UNLOCK
    win.close()
    win2 = MainWindow(v)
    win2.start()
    assert win2.stack.currentIndex() == PAGE_UNLOCK


def test_create_dialog_requires_correct_words_and_password(app, ready_vault):
    v = ready_vault
    d = CreateWalletDialog(v)
    d.name_edit.setText("Utama")
    d._to_seed()
    assert d.stack.currentIndex() == 1
    d.stack.setCurrentIndex(2)

    d.pw_field.edit.setText(PW)
    for e in d._check_edits:
        e.setText("salah")
    d._create()
    assert d.created is None and v.list_wallets() == []

    for e, i in zip(d._check_edits, d._check_idx):
        e.setText(d._words[i])
    d.pw_field.edit.setText("password-salah")
    d._create()
    assert d.created is None and v.list_wallets() == []

    d.pw_field.edit.setText(PW)
    d._create()
    assert d.created is not None and len(v.list_wallets()) == 1


def test_create_dialog_rejects_duplicate_name(app, ready_vault):
    v = ready_vault
    v.import_mnemonic("Utama", HARDHAT_MNEMONIC, PW)
    d = CreateWalletDialog(v)
    d.name_edit.setText("utama")
    d._to_seed()
    assert d.stack.currentIndex() == 0


def test_import_dialog_modes(app, ready_vault):
    v = ready_vault
    d = ImportWalletDialog(v)
    d.name_edit.setText("Seed")
    d.seed_edit.setPlainText(HARDHAT_MNEMONIC)
    d.pw_field.edit.setText(PW)
    d._submit()
    assert d.imported and d.imported.address == HARDHAT_ADDRESS

    d2 = ImportWalletDialog(v)
    d2.name_edit.setText("Kunci")
    d2.key_btn.click()
    d2.key_edit.setText("0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
    d2.pw_field.edit.setText(PW)
    d2._submit()
    assert d2.imported is None                      # alamat sama -> ditolak sebagai duplikat
    assert len(v.list_wallets()) == 1


def test_rename_dialog(app, ready_vault):
    v = ready_vault
    w = v.import_mnemonic("Lama", HARDHAT_MNEMONIC, PW)
    d = RenameDialog(v, w)
    d.edit.setText("Baru")
    d._save()
    assert d.updated and v.get_wallet(w.id).name == "Baru"


def test_delete_dialog_gating(app, ready_vault):
    v = ready_vault
    w = v.import_mnemonic("Hapus Aku", HARDHAT_MNEMONIC, PW)
    d = DeleteWalletDialog(v, w)
    assert not d.ok.isEnabled()
    d.backup_check.setChecked(True)
    d.name_edit.setText("hapus aku")                # harus persis sama
    d.pw_field.edit.setText(PW)
    assert not d.ok.isEnabled()
    d.name_edit.setText("Hapus Aku")
    assert d.ok.isEnabled()
    d.pw_field.edit.setText("salah")
    d._delete()
    assert not d.deleted and len(v.list_wallets()) == 1
    d.pw_field.edit.setText(PW)
    d._delete()
    assert d.deleted and v.list_wallets() == []


def test_password_dialog_keeps_open_on_wrong_password(app, ready_vault):
    v = ready_vault
    w = v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    d = PasswordDialog("Lihat", "msg", lambda pw: v.reveal_secret(w.id, pw))
    d.field.edit.setText("salah")
    d._submit()
    assert d.result_value is None and d.result() == 0
    d.field.edit.setText(PW)
    d._submit()
    assert d.result_value.value == HARDHAT_MNEMONIC


def test_lobby_shows_active_wallet_and_switching(app, ready_vault):
    v = ready_vault
    a = v.import_mnemonic("Pertama", HARDHAT_MNEMONIC, PW)
    v.create_wallet("Kedua", wallet_core.generate_mnemonic(), PW)
    win = MainWindow(v)
    win.start()
    win._enter_app()
    assert win.home.wallet_tab.switcher.text() == "Kedua"
    win.switch_wallet(a.id)
    assert win.home.wallet_tab.switcher.text() == "Pertama"
    assert win.home.profile_tab.name.text() == "Pertama"
    assert win.home.profile_tab.secret_btn.text() == "Lihat seed phrase"
