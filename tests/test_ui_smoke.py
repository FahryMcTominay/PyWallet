"""Smoke test UI (tanpa layar, memakai platform Qt 'offscreen' dan jaringan palsu)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pywallet import wallet_core  # noqa: E402
from pywallet.avatars import AvatarStore  # noqa: E402
from pywallet.config import GRACE_SECONDS  # noqa: E402
from pywallet.db import Database  # noqa: E402
from pywallet.portfolio import PortfolioService  # noqa: E402
from pywallet.ui import decor, theme  # noqa: E402
from pywallet.ui.dialogs import (  # noqa: E402
    CreateWalletDialog,
    DeleteWalletDialog,
    ImportWalletDialog,
    PasswordDialog,
    RenameDialog,
)
from pywallet.ui.main_window import PAGE_EMPTY, PAGE_HOME, PAGE_SETUP, PAGE_UNLOCK, MainWindow  # noqa: E402
from pywallet.vault import Vault  # noqa: E402

from .fakes import FakeHttp, install_standard, make_rpc, rpc_urls  # noqa: E402

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


@pytest.fixture
def make_window(tmp_path):
    """Jendela dengan jaringan palsu (tanpa thread, tanpa akses internet) dan folder avatar sementara."""

    def build(vault, http=None):
        service = PortfolioService(http or FakeHttp())   # FakeHttp kosong = semua permintaan gagal
        store = AvatarStore(tmp_path / "avatars")
        return MainWindow(vault, service=service, avatar_store=store, async_loading=False)

    return build


def photo(path, color="#ff8800", w=300, h=200):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return str(path)


def test_first_run_shows_setup_then_empty(app, vault, make_window):
    win = make_window(vault)
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


def test_unlock_flow_and_grace(app, ready_vault, clock, make_window):
    v = ready_vault
    win = make_window(v)
    win.start()
    assert win.stack.currentIndex() == PAGE_UNLOCK       # belum pernah aktif -> wajib password
    win.unlock_page.pw.edit.setText("salah")
    win.unlock_page._submit()
    assert win.stack.currentIndex() == PAGE_UNLOCK
    win.unlock_page.pw.edit.setText(PW)
    win.unlock_page._submit()
    assert win.stack.currentIndex() == PAGE_EMPTY        # belum ada wallet

    win.close()                                          # buka lagi < 5 menit -> tanpa password
    clock.t += GRACE_SECONDS - 10
    win2 = make_window(v)
    win2.start()
    assert win2.stack.currentIndex() == PAGE_EMPTY

    win2.close()                                         # buka lagi > 5 menit -> minta password
    clock.t += GRACE_SECONDS + 1
    win3 = make_window(v)
    win3.start()
    assert win3.stack.currentIndex() == PAGE_UNLOCK


def test_lock_now_forces_password(app, ready_vault, make_window):
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    win = make_window(v)
    win.start()
    win._enter_app()
    assert win.stack.currentIndex() == PAGE_HOME
    win.lock_app()
    assert win.stack.currentIndex() == PAGE_UNLOCK
    win.close()
    win2 = make_window(v)
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


def test_lobby_shows_active_wallet_and_switching(app, ready_vault, make_window):
    v = ready_vault
    a = v.import_mnemonic("Pertama", HARDHAT_MNEMONIC, PW)
    v.create_wallet("Kedua", wallet_core.generate_mnemonic(), PW)
    win = make_window(v)
    win.start()
    win._enter_app()
    assert win.home.wallet_tab.switcher.text() == "Kedua"
    win.switch_wallet(a.id)
    assert win.home.wallet_tab.switcher.text() == "Pertama"
    assert win.home.profile_tab.name.text() == "Pertama"
    assert win.home.profile_tab.secret_btn.text() == "Lihat seed phrase"


# --- foto profil ---------------------------------------------------------------
def test_avatar_set_replace_remove_and_cleanup_on_delete(app, ready_vault, make_window, tmp_path):
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    win = make_window(v)
    win.start()
    win._enter_app()
    store = win.store
    pt = win.home.profile_tab
    assert not pt.avatar.has_photo

    win.change_avatar(photo(tmp_path / "satu.png"))
    first = v.get_active_wallet().avatar
    assert first and store.path(first) is not None
    assert pt.avatar.has_photo and win.home.wallet_tab.avatar.has_photo

    win.change_avatar(photo(tmp_path / "dua.png", "#0088ff"))
    second = v.get_active_wallet().avatar
    assert second != first
    assert store.path(first) is None and store.path(second) is not None   # foto lama dibuang

    win.remove_avatar()
    assert v.get_active_wallet().avatar is None
    assert store.path(second) is None and not pt.avatar.has_photo

    win.change_avatar(photo(tmp_path / "tiga.png"))
    third = v.get_active_wallet().avatar
    wallet = v.get_active_wallet()
    v.delete_wallet(wallet.id, PW)
    store.remove(wallet.avatar)
    assert store.path(third) is None


def test_avatar_rejects_non_image(app, ready_vault, make_window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    win = make_window(v)
    win.start()
    win._enter_app()
    fake = tmp_path / "bukan_gambar.png"
    fake.write_text("ini teks, bukan gambar")
    win.change_avatar(str(fake))
    assert shown and v.get_active_wallet().avatar is None


# --- switch satuan & jaringan -----------------------------------------------------
def test_unit_and_network_switch_render_and_persist(app, ready_vault, make_window):
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    fake = FakeHttp()
    install_standard(fake)                                        # ETH $3000, 1 USD = Rp16.000
    fake.post_handlers[rpc_urls("ethereum")[0]] = make_rpc(2 * 10**18)       # 2 ETH di mainnet
    fake.post_handlers[rpc_urls("sepolia")[0]] = make_rpc(5 * 10**17)        # 0,5 ETH di Sepolia

    win = make_window(v, fake)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    assert wt.mode == "testnet"                                   # bawaan aman: testnet
    wt.set_unit("eth")
    assert wt.balance.text() == "0.5 ETH"                         # saldo ETH Sepolia
    wt.set_unit("usd")
    assert wt.balance.text() == "$0.00"                           # testnet tidak bernilai uang
    assert "tidak bernilai uang" in wt.note_lbl.text()

    wt.set_mode("mainnet")
    assert wt.balance.text() == "$6,000.00"
    wt.set_unit("idr")
    assert wt.balance.text() == "Rp96.000.000"
    wt.set_unit("eth")
    assert wt.balance.text() == "2 ETH"

    assert v.get_pref("network_mode") == "mainnet" and v.get_pref("display_unit") == "eth"
    win2 = make_window(v, fake)                                   # pilihan diingat saat dibuka ulang
    assert win2.home.wallet_tab.mode == "mainnet" and win2.home.wallet_tab.unit == "eth"


def test_lobby_lists_only_native_eth_while_extended_list_is_off(app, ready_vault, make_window):
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    win = make_window(v)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    for mode in ("testnet", "mainnet"):
        wt.set_mode(mode)
        assert wt.count_lbl.text().endswith("1 aset")


def test_decor_toggle_in_profile_persists(app, ready_vault, make_window):
    v = ready_vault
    v.create_wallet("Utama", HARDHAT_MNEMONIC, PW)
    win = make_window(v)
    win.start()
    win._enter_app()
    pt = win.home.profile_tab
    assert decor.ENABLED and "hidup" in pt.decor_btn.text()
    pt.decor_btn.click()
    assert not decor.ENABLED and "mati" in pt.decor_btn.text()
    assert v.get_pref("decor") == "0"
    for w in (win.home.wallet_tab, win.home.swap_tab, pt):
        w.grab()                                  # tetap bisa dirender tanpa motif
    win2 = make_window(v)                         # pilihan diingat saat aplikasi dibuka lagi
    assert not decor.ENABLED and "mati" in win2.home.profile_tab.decor_btn.text()
    win2.home.profile_tab.decor_btn.click()
    assert decor.ENABLED and v.get_pref("decor") == "1"


def test_tab_switch_slides_and_settles(app, ready_vault, make_window):
    from PySide6.QtTest import QTest

    v = ready_vault
    v.create_wallet("Utama", HARDHAT_MNEMONIC, PW)
    win = make_window(v)
    win.start()
    win._enter_app()
    win.show()
    tabs = win.home.tabs
    QTest.qWait(50)
    win.home._nav_group.button(1).click()            # Swap
    assert tabs.is_animating()
    QTest.qWait(tabs.DURATION_MS + 150)
    assert not tabs.is_animating() and tabs.currentIndex() == 1
    assert tabs.currentWidget().pos().x() == 0 and tabs.currentWidget().isVisible()
    assert not win.home.wallet_tab.isVisible()
    win.home._nav_group.button(2).click()            # klik beruntun: tidak boleh macet
    win.home._nav_group.button(0).click()
    QTest.qWait(tabs.DURATION_MS + 150)
    assert tabs.currentIndex() == 0 and tabs.currentWidget().pos().x() == 0
    assert not win.home.profile_tab.isVisible() and not win.home.swap_tab.isVisible()
    win.close()
