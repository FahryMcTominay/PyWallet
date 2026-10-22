"""Smoke test UI (tanpa layar, memakai platform Qt 'offscreen' dan jaringan palsu)."""
import os
from decimal import Decimal

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


def test_lobby_lists_extended_tokens_sorted_by_holding(app, ready_vault, make_window):
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    fake = FakeHttp()
    install_standard(fake)
    fake.post_handlers[rpc_urls("ethereum")[0]] = make_rpc(2 * 10**18)   # 2 ETH di Ethereum
    fake.post_handlers[rpc_urls("base")[0]] = make_rpc(10**17)           # 0,1 ETH di Base
    win = make_window(v, fake)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    wt.set_mode("mainnet")
    assert wt.count_lbl.text().endswith("10 aset")
    rows = [(r.token.network, r.token.symbol) for r in wt.snapshot.rows]
    assert rows[0] == ("ethereum", "ETH") and rows[1] == ("base", "ETH")      # yang terbanyak di atas
    rest = [sym for _, sym in rows[2:]]
    assert rest == sorted(rest, key=str.lower)                                # saldo 0 urut abjad
    wt.set_mode("testnet")
    assert {r.token.network for r in wt.snapshot.rows} == {"sepolia"}


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


# --------------------------------------------------------------------------
# Token kustom: dialog tambah, detail, dan daftar di lobi
# --------------------------------------------------------------------------
def _token_env(vault):
    from .test_custom_tokens import FAKE_USDT, MYTOKEN, chain
    fake = FakeHttp()
    install_standard(fake)
    for net in ("ethereum", "base", "sepolia"):
        fake.post_handlers[rpc_urls(net)[0]] = chain(balances={MYTOKEN: 5_000_000})
    return fake, PortfolioService(fake), MYTOKEN, FAKE_USDT


def test_add_token_dialog_flow(app, ready_vault):
    from pywallet.ui.token_dialogs import AddTokenDialog

    v = ready_vault
    fake, service, mytoken, fake_usdt = _token_env(v)
    dlg = AddTokenDialog(v, service, "mainnet")
    dlg.run_in_thread = False
    assert not dlg.add_btn.isEnabled() and set(dlg.net_buttons) == {"ethereum", "base"}

    dlg.addr_edit.setText("0x123")                           # alamat rusak
    dlg.check()
    assert dlg.err.isVisible() is False and "40 karakter" in dlg.err.text()

    dlg.addr_edit.setText(mytoken)
    dlg.check()
    assert "TPC" in dlg.preview.text() and "Desimal: 6" in dlg.preview.text()
    assert not dlg.add_btn.isEnabled()                       # wajib centang pencocokan alamat dulu
    dlg.confirm.setChecked(True)
    assert dlg.add_btn.isEnabled()
    dlg.addr_edit.setText(mytoken.lower())                   # mengubah teks mereset pratinjau (huruf kecil semua tetap sah)
    assert not dlg.add_btn.isEnabled()
    dlg.check()
    dlg.confirm.setChecked(True)
    dlg._add()
    assert dlg.added is not None and dlg.added.symbol == "TPC"
    assert [t.address for t in v.list_custom_tokens()] == [mytoken]


def test_add_token_dialog_warns_on_lookalike_symbol_and_duplicates(app, ready_vault):
    from pywallet.ui.token_dialogs import AddTokenDialog

    v = ready_vault
    fake, service, mytoken, fake_usdt = _token_env(v)
    dlg = AddTokenDialog(v, service, "mainnet")
    dlg.run_in_thread = False
    dlg.addr_edit.setText(fake_usdt)
    dlg.check()
    assert "token palsu" in dlg.warn.text() and dlg.preview.text().startswith("Nama: Tether USD")
    dlg.addr_edit.setText("0xdAC17F958D2ee523a2206206994597C13D831ec7")      # USDT asli = sudah bawaan
    dlg.check()
    assert "sudah ada" in dlg.err.text() and dlg.preview.isHidden()
    dlg.addr_edit.setText("0x" + "11" * 20)                                    # bukan kontrak
    dlg.check()
    assert "Tidak ada kontrak" in dlg.err.text()
    v.add_custom_token("ethereum", mytoken, "TPC", "Token Percobaan", 6)
    dlg.addr_edit.setText(mytoken)
    dlg.check()
    assert "sudah ada di daftarmu" in dlg.err.text()
    assert dlg.explorer_url() == f"https://etherscan.io/token/{mytoken}"
    dlg._set_network("base")
    dlg.addr_edit.setText(mytoken)
    assert dlg.explorer_url() == f"https://basescan.org/token/{mytoken}"


def test_add_token_dialog_testnet_has_single_network(app, ready_vault):
    from pywallet.ui.token_dialogs import AddTokenDialog

    fake, service, mytoken, _ = _token_env(ready_vault)
    dlg = AddTokenDialog(ready_vault, service, "testnet")
    dlg.run_in_thread = False
    assert dlg.net_buttons == {}
    dlg.addr_edit.setText(mytoken)
    dlg.check()
    assert "Jaringan: Sepolia" in dlg.preview.text()


def test_lobby_shows_custom_token_and_detail_dialog(app, ready_vault, make_window, monkeypatch):
    from pywallet.portfolio import AssetRow
    from pywallet.tokens import TOKENS
    from pywallet.ui.pages import TokenRow
    from pywallet.ui.token_dialogs import TokenDetailDialog

    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    fake, _service, mytoken, _ = _token_env(v)
    v.add_custom_token("ethereum", mytoken, "TPC", "Token Percobaan", 6)
    win = make_window(v, fake)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    wt.set_mode("mainnet")
    rows = wt.findChildren(TokenRow)
    assert len(rows) == 11                                           # 10 bawaan + 1 kustom
    custom = next(r for r in rows if r.row.token.custom)
    assert custom.row.amount == Decimal("5") and wt.count_lbl.text().endswith("11 aset")

    # MainWindow membuka layar detail di dalam jendela saat baris diklik.
    clicked = []
    wt.tokenRequested.connect(clicked.append)
    custom.clicked.emit(custom.row)
    assert clicked and clicked[0].token.address == mytoken

    d = TokenDetailDialog(custom.row)                                # token kustom: alamat + tombol hapus
    assert d.addr_label.text() == mytoken and d.remove_btn is not None
    d._ask_remove()
    assert not d.remove_btn.isVisibleTo(d) and d.confirm_box.isVisibleTo(d)
    d._cancel_remove()
    assert d.remove_btn.isVisibleTo(d) and not d.removed
    d._do_remove()
    assert d.removed

    usdt = next(r for r in rows if r.row.token.symbol == "USDT")
    d2 = TokenDetailDialog(usdt.row)                                 # token bawaan: alamat + tombol "sembunyikan"
    assert d2.addr_label.text() == "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    assert d2.remove_btn.text() == "Sembunyikan dari daftar" and d2.yes_btn.text() == "Ya, sembunyikan"

    eth = AssetRow(TOKENS["ethereum"][0], Decimal(0), 3000.0, None)
    d3 = TokenDetailDialog(eth)                                      # ETH: penjelasan koin native
    assert d3.addr_label is None

    v.remove_custom_token("ethereum", mytoken)
    wt.reload_tokens()
    assert len(wt.findChildren(TokenRow)) == 10


def test_main_window_hides_builtin_token_and_it_disappears_from_lobby(app, ready_vault, make_window, monkeypatch):
    from pywallet.ui.pages import TokenRow
    from pywallet.ui.token_dialogs import TokenDetailDialog

    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    fake, _service, _mytoken, _ = _token_env(v)
    win = make_window(v, fake)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    wt.set_mode("mainnet")
    rows = wt.findChildren(TokenRow)
    usdt = next(r for r in rows if r.row.token.symbol == "USDT")
    before = len(rows)

    win.show_token(usdt.row)
    scr = win.screens.screen
    assert isinstance(scr, TokenDetailDialog)
    scr._do_remove()                   # meniru pengguna menekan "Ya, sembunyikan"
    assert win.screens.screen is None
    assert ("ethereum", usdt.row.token.address.lower()) in v.list_hidden_tokens()
    after = wt.findChildren(TokenRow)
    assert len(after) == before - 1 and not any(r.row.token.symbol == "USDT" for r in after)


def test_feature_screens_open_inside_main_window_with_back_and_esc(app, ready_vault, make_window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    fake, *_ = _token_env(v)
    win = make_window(v, fake)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    assert win.screens.screen is None and win.screens.isHidden()

    wt.addTokenRequested.emit()
    scr = win.screens.screen
    assert scr is not None and not win.screens.isHidden() and scr.parent() is win.screens
    assert not scr.isWindow()                                   # bukan jendela baru
    QTest.keyClick(scr, Qt.Key.Key_Escape)                      # Esc = kembali
    assert win.screens.screen is None and win.screens.isHidden()

    wt.addTokenRequested.emit()
    win.screens.screen.back_btn.click()                         # tombol ←
    assert win.screens.screen is None

    wt.addTokenRequested.emit()
    win.lock_app()                                              # mengunci menutup layar yang terbuka
    assert win.screens.screen is None


def test_send_screen_back_returns_to_form_before_closing(app, ready_vault, make_window):
    v = ready_vault
    v.import_mnemonic("A", HARDHAT_MNEMONIC, PW)
    fake, *_ = _token_env(v)
    win = make_window(v, fake)
    win.start()
    win._enter_app()
    win.home.wallet_tab.sendRequested.emit()
    scr = win.screens.screen
    if scr is None:                                             # saldo belum dimuat di lingkungan tes ini
        pytest.skip("saldo belum tersedia")
    scr.pages.setCurrentIndex(1)
    scr.go_back()
    assert scr.pages.currentIndex() == 0 and win.screens.screen is scr
    scr.go_back()
    assert win.screens.screen is None


def test_primary_buttons_keep_theme_color_inside_screens(app):
    """Regresi v0.9.0: stylesheet polos di layar membuat tombol utama transparan (teks/latar hilang)."""
    from PySide6.QtWidgets import QWidget

    from pywallet.ui.dialogs import ScreenBase, button

    scr = ScreenBase("Uji")
    btn = button("Simpan", "primary")
    scr.root.addWidget(btn)
    scr.resize(420, 400)
    scr.show()
    app.processEvents()
    img = btn.grab().toImage()
    px = QColor(img.pixel(img.width() // 2, 4))                    # tepi atas tombol: murni latar tombol
    assert px.name().lower() == theme.ACCENT.lower()
    assert not [w for w in scr.findChildren(QWidget) if w.styleSheet().strip().startswith("background")]
    scr.close()
