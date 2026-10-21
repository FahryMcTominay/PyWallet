"""Riwayat transaksi: parser format Etherscan, penggabungan dengan catatan lokal, dan dialog."""
import os
import time
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pywallet import history as H  # noqa: E402
from pywallet.db import Database  # noqa: E402
from pywallet.httpclient import HttpError  # noqa: E402
from pywallet.networks import NETWORKS  # noqa: E402
from pywallet.portfolio import PortfolioService  # noqa: E402
from pywallet.tokens import TOKENS  # noqa: E402
from pywallet.vault import SentTx, Vault, VaultError  # noqa: E402

from .fakes import FakeHttp, FakeSendChain  # noqa: E402

ME = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
OTHER = "0x" + "12" * 20
SCAM = "0x" + "99" * 20
USDC = TOKENS["sepolia"][1].address
UNKNOWN = "0x" + "77" * 20
H1, H2, H3, H4, H5, H6 = ("0x" + c * 64 for c in "123456")


def tx_row(h, frm, to, value=0, ts=1_700_000_000, inp="0x", err="0"):
    return {"hash": h, "from": frm.lower(), "to": to.lower(), "value": str(value), "timeStamp": str(ts),
            "input": inp, "isError": err, "txreceipt_status": "0" if err == "1" else "1"}


def tok_row(h, frm, to, value, contract=USDC, sym="USDC", dec=6, ts=1_700_000_100):
    return {"hash": h, "from": frm.lower(), "to": to.lower(), "value": str(value), "timeStamp": str(ts),
            "contractAddress": contract.lower(), "tokenSymbol": sym, "tokenDecimal": str(dec)}


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def test_parse_txlist_directions_and_calls():
    rows = [
        tx_row(H1, ME, OTHER, 10**17),                         # keluar
        tx_row(H2, OTHER, ME, 5 * 10**16),                     # masuk
        tx_row(H3, ME, OTHER, 0, inp="0x095ea7b3" + "0" * 128),  # approve = panggilan kontrak
        tx_row(H4, ME, OTHER, 10**17, err="1"),                # gagal
        tx_row(H5, ME, ME, 1),                                 # ke diri sendiri
        tx_row(H6, OTHER, "0x" + "55" * 20, 5),                # bukan urusan wallet ini: diabaikan
        {"hash": "bukan-hash"},                                # sampah: diabaikan
        "bukan dict",
    ]
    items = {i.tx_hash: i for i in H.parse_txlist(rows, ME, "sepolia")}
    assert set(items) == {H1, H2, H3, H4, H5}
    assert items[H1].direction == "out" and items[H1].amount == Decimal("0.1") and items[H1].symbol == "ETH"
    assert items[H2].direction == "in" and items[H2].counterparty == OTHER
    assert items[H3].direction == "call" and items[H3].amount is None
    assert items[H4].status == "failed"
    assert items[H5].direction == "self"


def test_parse_tokentx_hides_zero_value_poisoning_and_flags_unknown():
    rows = [
        tok_row(H1, OTHER, ME, 2_500_000),
        tok_row(H2, SCAM, ME, 0),                              # address poisoning
        tok_row(H3, OTHER, ME, 10**18, contract=UNKNOWN, sym="FREE‮MONEY", dec=18),
        tok_row(H4, ME, OTHER, 1_000_000),
    ]
    items, hidden = H.parse_tokentx(rows, ME, "sepolia", {USDC.lower()})
    assert hidden == 1 and len(items) == 3
    by = {i.tx_hash: i for i in items}
    assert by[H1].amount == Decimal("2.5") and by[H1].known_token and by[H1].direction == "in"
    assert by[H3].known_token is False and "‮" not in by[H3].symbol      # karakter kontrol dibuang
    assert by[H4].direction == "out"


def test_merge_drops_contract_call_that_has_token_transfer():
    txs = H.parse_txlist([tx_row(H1, ME, USDC, 0, inp="0xa9059cbb" + "0" * 128),
                          tx_row(H2, ME, OTHER, 0, inp="0x095ea7b3" + "0" * 128)], ME, "sepolia")
    transfers, _ = H.parse_tokentx([tok_row(H1, ME, OTHER, 1_000_000)], ME, "sepolia", set())
    merged = H.merge("sepolia", txs, transfers)
    assert sorted((i.tx_hash, i.direction) for i in merged) == sorted([(H1, "out"), (H2, "call")])


# --------------------------------------------------------------------------
# Layanan (jaringan palsu)
# --------------------------------------------------------------------------
def explorer(rows_by_action):
    def handler(url, params):
        action = params["action"]
        result = rows_by_action.get(action, [])
        if isinstance(result, Exception):
            raise result
        if isinstance(result, str):
            return {"status": "0", "message": "NOTOK", "result": result}
        if not result:
            return {"status": "0", "message": "No transactions found", "result": []}
        return {"status": "1", "message": "OK", "result": result}
    return handler


def service(rows_by_action, chain=None, network="sepolia"):
    fake = FakeHttp()
    fake.get_handlers[NETWORKS[network].history_api] = explorer(rows_by_action)
    if chain:
        fake.post_handlers[NETWORKS[network].rpc_urls[0]] = chain.handler
    return PortfolioService(fake)


def test_service_loads_sorts_and_merges_local_pending(tmp_path):
    svc = service({"txlist": [tx_row(H1, ME, OTHER, 10**17, ts=1000), tx_row(H2, OTHER, ME, 5, ts=3000)],
                   "tokentx": [tok_row(H3, OTHER, ME, 1_000_000, ts=2000)]})
    local = [SentTx("sepolia", H4, ME, OTHER, "ETH", 18, None, 10**16, "pending", None, 4000),
             SentTx("sepolia", H1, ME, OTHER, "ETH", 18, None, 10**17, "pending", None, 1000)]   # sudah ada di explorer
    res = svc.history.load(ME, "testnet", local, TOKENS["sepolia"])
    assert [i.tx_hash for i in res.items] == [H4, H2, H3, H1]               # terbaru dulu
    assert res.items[0].local and res.items[0].status == "pending"
    assert not res.errors


def test_service_updates_pending_status_from_receipt():
    chain = FakeSendChain(receipt_status=1)
    svc = service({}, chain)
    local = [SentTx("sepolia", H1, ME, OTHER, "ETH", 18, None, 10**16, "pending", None, 4000)]
    res = svc.history.load(ME, "testnet", local)
    assert res.items[0].status == "success" and res.updates == [("sepolia", H1, "success", 17)]
    res2 = service({}, FakeSendChain(receipt_status=None)).history.load(ME, "testnet", local)
    assert res2.items[0].status == "pending" and res2.updates == []


def test_service_reports_explorer_failures_without_losing_local():
    svc = service({"txlist": HttpError("down")})
    local = [SentTx("sepolia", H1, ME, OTHER, "ETH", 18, None, 10**16, "success", 5, 4000)]
    res = svc.history.load(ME, "testnet", local)
    assert res.errors and [i.tx_hash for i in res.items] == [H1]            # catatan lokal tetap tampil
    svc_rate = service({"txlist": "Max rate limit reached"})
    svc_rate.history._sleep = lambda _s: None
    rate = svc_rate.history.load(ME, "testnet")
    assert rate.errors and rate.items == [] and "rate limit" in rate.errors[0].lower()   # alasan ikut ditampilkan


def test_service_token_failure_keeps_native_transactions():
    svc = service({"txlist": [tx_row(H1, ME, OTHER, 10**17)], "tokentx": HttpError("down")})
    res = svc.history.load(ME, "testnet")
    assert [i.tx_hash for i in res.items] == [H1] and any("token" in e.lower() for e in res.errors)


def test_mainnet_mode_queries_both_networks():
    fake = FakeHttp()
    fake.get_handlers[NETWORKS["ethereum"].history_api] = explorer({"txlist": [tx_row(H1, ME, OTHER, 1, ts=10)]})
    fake.get_handlers[NETWORKS["base"].history_api] = explorer({"txlist": [tx_row(H2, OTHER, ME, 1, ts=20)]})
    res = PortfolioService(fake).history.load(ME, "mainnet")
    assert [(i.network, i.tx_hash) for i in res.items] == [("base", H2), ("ethereum", H1)]


# --------------------------------------------------------------------------
# Vault: catatan lokal
# --------------------------------------------------------------------------
@pytest.fixture
def vault(tmp_path):
    return Vault(Database(tmp_path / "h.db"))


def test_vault_tx_log_roundtrip(vault):
    tx = SentTx("sepolia", H1.upper().replace("0X", "0x"), ME, OTHER, "USDC", 6, USDC, 1_500_000, "pending", None, 123)
    vault.record_sent_tx(tx)
    vault.record_sent_tx(tx)                                               # ganda diabaikan
    got = vault.list_sent_txs(ME)
    assert len(got) == 1 and got[0].amount_raw == 1_500_000 and got[0].tx_hash == H1.lower()
    assert vault.list_sent_txs(ME, ("base",)) == [] and vault.list_sent_txs(OTHER) == []
    vault.set_tx_status("sepolia", H1, "success", 99)
    assert vault.list_sent_txs(ME)[0].status == "success" and vault.list_sent_txs(ME)[0].block == 99
    with pytest.raises(VaultError):
        vault.set_tx_status("sepolia", H1, "aneh")


def test_old_database_is_migrated_to_latest(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                       "CREATE TABLE wallets (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE,"
                       "address TEXT NOT NULL UNIQUE, secret_type TEXT NOT NULL, secret_enc BLOB NOT NULL,"
                       "derivation_path TEXT, created_at TEXT NOT NULL DEFAULT '', avatar TEXT);"
                       "PRAGMA user_version = 2;")
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 5
    db.conn.execute("SELECT * FROM tx_log").fetchall()


# --------------------------------------------------------------------------
# Dialog
# --------------------------------------------------------------------------
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    from pywallet.ui import theme
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.build_qss())
    return app


PW = "kata-sandi-kuat-1"
FAST_KDF = {"n": 2**10, "r": 8, "p": 1}


def test_history_dialog_renders_rows_and_updates_status(qapp, tmp_path, monkeypatch):
    from pywallet.ui.history_dialog import HistoryDialog, HistoryRow

    v = Vault(Database(tmp_path / "d.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    wallet = v.import_mnemonic("Utama", "test test test test test test test test test test test junk", PW)
    assert wallet.address == ME
    v.record_sent_tx(SentTx("sepolia", H4, ME, OTHER, "ETH", 18, None, 10**16, "pending", None, int(time.time())))
    svc = service({"txlist": [tx_row(H1, OTHER, ME, 2 * 10**18, ts=1_700_000_000),
                              tx_row(H2, ME, OTHER, 0, ts=1_700_000_500, inp="0x095ea7b3" + "0" * 128)],
                   "tokentx": [tok_row(H3, OTHER, ME, 5_000_000, contract=UNKNOWN, sym="AIRDROP", ts=1_700_000_900),
                               tok_row(H5, SCAM, ME, 0)]}, FakeSendChain(receipt_status=1))
    dlg = HistoryDialog(v, svc, wallet, "testnet", run_in_thread=False)
    rows = dlg.findChildren(HistoryRow)
    assert len(rows) == 4
    texts = " ".join(lbl.text() for r in rows for lbl in r.findChildren(type(dlg.status)))
    assert "Diterima" in texts and "Panggilan kontrak" in texts and "Terkirim" in texts
    assert "Token tidak dikenal" in texts                  # token airdrop asing ditandai
    assert "disembunyikan" in dlg.note.text()              # transfer nol disembunyikan
    assert v.list_sent_txs(ME)[0].status == "success"      # status 'menunggu' diperbarui dari receipt
    opened = []
    monkeypatch.setattr("pywallet.ui.history_dialog.open_url", opened.append)
    rows[0].clicked.emit(rows[0].item)
    assert opened and opened[0].startswith("https://sepolia.etherscan.io/tx/0x")
    dlg.deleteLater()


def test_history_dialog_shows_error_when_everything_fails(qapp, tmp_path):
    from pywallet.ui.history_dialog import HistoryDialog

    v = Vault(Database(tmp_path / "e.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    wallet = v.create_wallet("Utama", "test test test test test test test test test test test junk", PW)
    svc = PortfolioService(FakeHttp())                    # semua permintaan gagal
    dlg = HistoryDialog(v, svc, wallet, "testnet", run_in_thread=False)
    assert not dlg.status.isHidden() and "gagal" in dlg.status.text().lower()
    dlg.deleteLater()


def test_lobby_history_button_and_send_records_log(tmp_path, monkeypatch, qapp):
    """Tombol Riwayat membuka dialog; mengirim dari SendDialog mencatat transaksi di tx_log."""
    from decimal import Decimal as D

    from pywallet.avatars import AvatarStore
    from pywallet.portfolio import AssetRow
    from pywallet.ui.history_dialog import HistoryDialog
    from pywallet.ui.main_window import MainWindow
    from pywallet.ui.send_dialog import SendDialog
    from pywallet.wallet_core import generate_mnemonic

    v = Vault(Database(tmp_path / "m.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    wallet = v.create_wallet("Utama", generate_mnemonic(), PW)
    chain = FakeSendChain()
    fake = FakeHttp()
    fake.post_handlers[NETWORKS["sepolia"].rpc_urls[0]] = chain.handler
    svc = PortfolioService(fake)

    dlg = SendDialog(v, svc, wallet, [AssetRow(TOKENS["sepolia"][0], D("1"), None, None)])
    dlg.run_in_thread = False
    dlg.addr_edit.setText(OTHER)
    dlg.amount_edit.setText("0.1")
    dlg._on_next()
    dlg.pw_field.edit.setText(PW)
    dlg.send_btn.click()
    logged = v.list_sent_txs(wallet.address)
    assert len(logged) == 1 and logged[0].amount_raw == 10**17 and logged[0].tx_hash == dlg.sent_hash
    assert logged[0].status == "success"                  # receipt palsu = sukses; status ikut diperbarui
    dlg.deleteLater()

    win = MainWindow(v, service=svc, avatar_store=AvatarStore(tmp_path / "av"), async_loading=False)
    win.start()
    win._enter_app()
    win.home.wallet_tab.set_mode("testnet")
    opened = []
    monkeypatch.setattr(HistoryDialog, "exec", lambda self: opened.append((self.wallet.id, self.mode)) or 0)
    win.home.wallet_tab.history_btn.click()
    assert opened == [(wallet.id, "testnet")]


def test_native_coin_listed_as_symbolless_token_is_not_duplicated():
    """Laporan pengguna: tiap transfer ETH muncul dua kali, yang kedua bersimbol 'None' dan 'Token tidak dikenal'."""
    pseudo = tok_row(H1, ME, OTHER, 24 * 10**15, contract="0x" + "ee" * 20, sym="", dec=18)
    pseudo["tokenSymbol"] = None
    real = tok_row(H2, ME, OTHER, 1_000_000)                       # token sungguhan tetap tampil
    odd = tok_row(H3, OTHER, ME, 5, contract=UNKNOWN, sym="", dec=0)  # tanpa simbol dan bukan duplikat: tetap tampil
    odd["tokenSymbol"] = None
    txs = H.parse_txlist([tx_row(H1, ME, OTHER, 24 * 10**15)], ME, "sepolia")
    transfers, _ = H.parse_tokentx([pseudo, real, odd], ME, "sepolia", {USDC.lower()})
    merged = H.merge("sepolia", txs, transfers)
    assert sorted((i.tx_hash, i.symbol) for i in merged) == sorted([(H1, "ETH"), (H2, "USDC"), (H3, "?")])


def flaky_service(fail_times, rows, error="https://x/api: HTTP Error 429: Too Many Requests"):
    """Explorer yang menolak `fail_times` permintaan pertama (mis. kena rate limit), lalu normal."""
    state = {"calls": 0}
    ok = explorer(rows)

    def handler(url, params):
        state["calls"] += 1
        if state["calls"] <= fail_times:
            raise HttpError(error)
        return ok(url, params)

    fake = FakeHttp()
    fake.get_handlers[NETWORKS["sepolia"].history_api] = handler
    svc = PortfolioService(fake)
    svc.history._sleep = lambda _s: None
    return svc, state


def test_rate_limit_is_retried_then_succeeds():
    svc, state = flaky_service(2, {"txlist": [tx_row(H1, ME, OTHER, 1)], "tokentx": []})
    res = svc.history.load(ME, "testnet")
    assert [i.tx_hash for i in res.items] == [H1] and not res.errors
    assert state["calls"] == 4                       # 2 gagal + txlist ok + tokentx ok


def test_persistent_rate_limit_reports_the_reason():
    svc, _ = flaky_service(99, {})
    res = svc.history.load(ME, "testnet")
    assert res.errors and "429" in res.errors[0]


def test_reopening_quickly_uses_cache_and_force_bypasses_it():
    svc, state = flaky_service(0, {"txlist": [tx_row(H1, ME, OTHER, 1)], "tokentx": []})
    svc.history.load(ME, "testnet")
    calls = state["calls"]
    res = svc.history.load(ME, "testnet")            # dibuka lagi segera: tanpa permintaan baru
    assert state["calls"] == calls and [i.tx_hash for i in res.items] == [H1]
    svc.history.load(ME, "testnet", force=True)      # tombol Muat ulang
    assert state["calls"] == calls * 2


def test_failure_after_success_falls_back_to_old_data():
    svc, state = flaky_service(0, {"txlist": [tx_row(H1, ME, OTHER, 1)], "tokentx": []})
    svc.history.load(ME, "testnet")
    state["calls"] = -999                            # mulai sekarang bukan 'sukses' lagi
    svc.history.http.get_handlers[NETWORKS["sepolia"].history_api] = lambda u, p: (_ for _ in ()).throw(HttpError("down"))
    res = svc.history.load(ME, "testnet", force=True)
    assert [i.tx_hash for i in res.items] == [H1] and "data lama" in res.errors[0]


# --------------------------------------------------------------------------
# API key (Blockscout PRO)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", "   ", "a b", "key&x=1", "k\ney", "kü", "x" * 129, "key?apikey=1"])
def test_api_key_validation_rejects_unsafe_values(vault, bad):
    with pytest.raises(VaultError):
        from pywallet.vault import validate_api_key
        validate_api_key(bad)


def test_vault_api_key_roundtrip(vault):
    assert vault.get_history_api_key() == ""
    vault.set_history_api_key("  proapi_AbC-123  ")
    assert vault.get_history_api_key() == "proapi_AbC-123"
    vault.set_history_api_key(None)
    assert vault.get_history_api_key() == ""
    with pytest.raises(VaultError):
        vault.set_history_api_key("bad key!")


def test_history_uses_pro_endpoint_only_when_key_is_set():
    seen = []
    ok = explorer({"txlist": [tx_row(H1, ME, OTHER, 1)], "tokentx": []})

    def public(url, params):
        seen.append(("public", params.get("apikey")))
        return ok(url, params)

    def pro(url, params):
        seen.append(("pro", params.get("apikey")))
        return ok(url, params)

    fake = FakeHttp()
    fake.get_handlers[NETWORKS["sepolia"].history_api] = public
    fake.get_handlers["https://api.blockscout.com/11155111/api"] = pro
    svc = PortfolioService(fake)
    svc.history.load(ME, "testnet", force=True)
    svc.history.load(ME, "testnet", force=True, api_key="proapi_secret")
    assert ("public", None) in seen and ("pro", "proapi_secret") in seen
    assert not any(kind == "public" and key for kind, key in seen)       # key tidak bocor ke endpoint publik


def test_error_text_never_contains_the_api_key():
    exc = HttpError("https://api.blockscout.com/1/api?module=account&apikey=proapi_secret&x=1: HTTP Error 429")
    assert "secret" not in H.reason_of(exc) and "429" in H.reason_of(exc)
    exc2 = HttpError("timeout apikey=proapi_secret")
    assert "secret" not in H.reason_of(exc2)


def test_api_key_dialog_and_profile_button(qapp, tmp_path):
    from pywallet.ui.history_dialog import ApiKeyDialog
    from pywallet.ui.pages import ProfileTab

    v = Vault(Database(tmp_path / "k.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    v.import_mnemonic("Utama", "test test test test test test test test test test test junk", PW)
    tab = ProfileTab(v)
    tab.refresh()
    assert "belum diatur" in tab.api_btn.text()

    dlg = ApiKeyDialog(v)
    dlg.field.edit.setText("bad key!")
    dlg._save()
    assert not dlg.changed and not dlg.err.isHidden() and v.get_history_api_key() == ""
    dlg.field.edit.setText("proapi_ok-1")
    dlg._save()
    assert dlg.changed and v.get_history_api_key() == "proapi_ok-1"
    tab.refresh()
    assert "terpasang" in tab.api_btn.text()

    dlg2 = ApiKeyDialog(v)
    assert not dlg2.remove_btn.isHidden()
    dlg2._remove()
    assert v.get_history_api_key() == ""
    dlg.deleteLater()
    dlg2.deleteLater()
    tab.deleteLater()


def test_history_dialog_hints_about_api_key_on_429(qapp, tmp_path):
    from pywallet.ui.history_dialog import HistoryDialog

    v = Vault(Database(tmp_path / "n.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    w = v.import_mnemonic("Utama", "test test test test test test test test test test test junk", PW)
    svc, _ = flaky_service(99, {})
    dlg = HistoryDialog(v, svc, w, "testnet", run_in_thread=False)
    assert "API key" in dlg.status.text() and "429" in dlg.status.text()
    dlg.deleteLater()


def test_base_stays_on_public_api_even_with_key_and_403_falls_back():
    seen = []
    ok = explorer({"txlist": [tx_row(H1, ME, OTHER, 1)], "tokentx": []})

    def record(kind):
        def handler(url, params):
            seen.append((kind, url, params.get("apikey")))
            return ok(url, params)
        return handler

    fake = FakeHttp()
    fake.get_handlers[NETWORKS["base"].history_api] = record("base-public")
    fake.get_handlers["https://api.blockscout.com/8453/api"] = record("base-pro")      # tidak boleh dipakai
    PortfolioService(fake).history.load(ME, "mainnet", api_key="proapi_x")             # ethereum tak punya handler: gagal, abaikan
    assert seen and all(kind == "base-public" and key is None for kind, _u, key in seen)

    # Paket key menolak (403): otomatis jatuh ke API publik pada permintaan yang sama.
    fake2 = FakeHttp()

    def denied(url, params):
        raise HttpError("https://api.blockscout.com/11155111/api?apikey=x: HTTP Error 403: Forbidden")

    fake2.get_handlers["https://api.blockscout.com/11155111/api"] = denied
    fake2.get_handlers[NETWORKS["sepolia"].history_api] = ok
    res = PortfolioService(fake2).history.load(ME, "testnet", api_key="proapi_x")
    assert [i.tx_hash for i in res.items] == [H1] and not res.errors


def test_key_rejected_for_network_falls_back_to_public_api():
    """Base tidak termasuk paket gratis Blockscout PRO: dengan key terpasang, riwayat Base tetap lewat API publik."""
    ok = explorer({"txlist": [tx_row(H1, ME, OTHER, 1)], "tokentx": []})
    fake = FakeHttp()

    def pro(url, params):
        raise HttpError("https://api.blockscout.com/8453/api?apikey=proapi_x: HTTP Error 402: Payment Required")

    fake.get_handlers["https://api.blockscout.com/8453/api"] = pro
    fake.get_handlers[NETWORKS["base"].history_api] = ok
    fake.get_handlers["https://api.blockscout.com/1/api"] = lambda u, p: ok(u, p)
    fake.get_handlers[NETWORKS["ethereum"].history_api] = ok
    res = PortfolioService(fake).history.load(ME, "mainnet", api_key="proapi_x")
    assert not res.errors and {i.network for i in res.items} == {"base", "ethereum"}
