"""Token kustom: validasi alamat, baca info dari blockchain (palsu), database, portofolio, dan dialog."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pywallet.db import Database  # noqa: E402
from pywallet.portfolio import PortfolioService  # noqa: E402
from pywallet.rpc import RpcClient, RpcError, decode_abi_string, fetch_token_info  # noqa: E402
from pywallet.tokens import (  # noqa: E402
    InvalidContractAddress,
    make_custom_token,
    normalize_contract_address,
    tokens_for_mode,
)
from pywallet.vault import DuplicateWallet, Vault, VaultError  # noqa: E402

from pywallet.httpclient import HttpError  # noqa: E402

from .fakes import FakeHttp, abi_bytes32, abi_string, install_standard, make_chain, rpc_urls  # noqa: E402

ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
MYTOKEN = "0x1234567890AbcdEF1234567890aBcdef12345678"
MYTOKEN = normalize_contract_address(MYTOKEN.lower())
OTHER = normalize_contract_address("0x" + "ab" * 20)
USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
FAKE_USDT = normalize_contract_address("0x" + "cd" * 20)


def chain(**kw):
    contracts = {
        MYTOKEN: {"name": "Token Percobaan", "symbol": "TPC", "decimals": 6},
        OTHER: {"name": "Maker", "symbol": "MKR", "decimals": 18, "bytes32": True},
        FAKE_USDT: {"name": "Tether USD", "symbol": "USDT", "decimals": 6},
        USDT: {"name": "Tether USD", "symbol": "USDT", "decimals": 6},
    }
    return make_chain(contracts, **kw)


def rpc_with(handler, network="ethereum"):
    fake = FakeHttp()
    fake.post_handlers[rpc_urls(network)[0]] = handler
    return RpcClient(fake, rpc_urls(network)), fake


# --------------------------------------------------------------------------
# Validasi alamat
# --------------------------------------------------------------------------
def test_normalize_accepts_lowercase_and_no_prefix():
    expected = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    assert normalize_contract_address(USDT.lower()) == expected
    assert normalize_contract_address(USDT[2:].lower()) == expected
    assert normalize_contract_address("  " + USDT + " ") == expected


@pytest.mark.parametrize("bad", ["", "0x123", "xyz", "0x" + "g" * 40, "0x" + "0" * 40,
                                 "0xdAC17F958D2ee523a2206206994597C13D831ec8"])   # checksum salah
def test_normalize_rejects_bad_input(bad):
    with pytest.raises(InvalidContractAddress):
        normalize_contract_address(bad)


# --------------------------------------------------------------------------
# Baca info token dari blockchain
# --------------------------------------------------------------------------
def test_abi_string_decoding_both_forms():
    assert decode_abi_string(abi_string("USD Coin")) == "USD Coin"
    assert decode_abi_string(abi_bytes32("MKR")) == "MKR"
    for bad in (None, "0x", "zz", "0x" + "00" * 40, "0x" + (32).to_bytes(32, "big").hex() + (500).to_bytes(32, "big").hex()):
        with pytest.raises(RpcError):
            decode_abi_string(bad)


def test_fetch_token_info_ok_and_legacy_bytes32():
    rpc, _ = rpc_with(chain())
    info = fetch_token_info(rpc, MYTOKEN)
    assert (info.name, info.symbol, info.decimals, info.address) == ("Token Percobaan", "TPC", 6, MYTOKEN)
    assert fetch_token_info(rpc, OTHER).symbol == "MKR"


def test_fetch_token_info_errors_are_clear():
    rpc, _ = rpc_with(chain())
    with pytest.raises(RpcError, match="Tidak ada kontrak"):
        fetch_token_info(rpc, normalize_contract_address("0x" + "11" * 20))       # bukan kontrak
    broken, _ = rpc_with(make_chain({MYTOKEN: {"name": "x", "symbol": "x", "decimals": 1, "broken": True}}))
    with pytest.raises(RpcError, match="ERC-20"):
        fetch_token_info(broken, MYTOKEN)
    down = RpcClient(FakeHttp(), rpc_urls("ethereum"))
    with pytest.raises(RpcError, match="terhubung"):
        fetch_token_info(down, MYTOKEN)


# --------------------------------------------------------------------------
# Database & vault
# --------------------------------------------------------------------------
@pytest.fixture
def vault(tmp_path):
    return Vault(Database(tmp_path / "t.db"))


def test_vault_add_list_remove_custom_token(vault):
    tok = vault.add_custom_token("ethereum", MYTOKEN.lower(), "TPC", "Token Percobaan", 6)
    assert tok.custom and tok.address == MYTOKEN and tok.key == f"ethereum:{MYTOKEN.lower()}"
    assert [t.symbol for t in vault.list_custom_tokens()] == ["TPC"]
    with pytest.raises(DuplicateWallet):
        vault.add_custom_token("ethereum", MYTOKEN, "TPC", "x", 6)
    vault.add_custom_token("base", MYTOKEN, "TPC", "Token Percobaan", 6)       # alamat sama, jaringan lain: boleh
    vault.remove_custom_token("ethereum", MYTOKEN)
    assert [t.network for t in vault.list_custom_tokens()] == ["base"]


def test_vault_rejects_builtin_bad_network_and_bad_data(vault):
    with pytest.raises(DuplicateWallet, match="bawaan"):
        vault.add_custom_token("ethereum", USDT, "USDT", "Tether USD", 6)
    with pytest.raises(VaultError):
        vault.add_custom_token("nowhere", MYTOKEN, "X", "X", 6)
    with pytest.raises(VaultError):
        vault.add_custom_token("ethereum", "0x123", "X", "X", 6)
    with pytest.raises(VaultError):
        vault.add_custom_token("ethereum", MYTOKEN, "", "X", 6)
    with pytest.raises(VaultError):
        vault.add_custom_token("ethereum", MYTOKEN, "X", "X", 99)


def test_custom_tokens_survive_reopen(tmp_path):
    path = tmp_path / "persist.db"
    Vault(Database(path)).add_custom_token("sepolia", MYTOKEN, "TPC", "Token Percobaan", 6)
    assert [t.symbol for t in Vault(Database(path)).list_custom_tokens()] == ["TPC"]


# --------------------------------------------------------------------------
# Portofolio
# --------------------------------------------------------------------------
def test_tokens_for_mode_adds_custom_only_for_matching_mode():
    on_eth = make_custom_token("ethereum", MYTOKEN, "TPC", "T", 6)
    on_sep = make_custom_token("sepolia", MYTOKEN, "TPC", "T", 6)
    assert on_eth in tokens_for_mode("mainnet", [on_eth, on_sep]) and on_sep not in tokens_for_mode("mainnet", [on_eth, on_sep])
    assert on_sep in tokens_for_mode("testnet", [on_eth, on_sep])


def test_portfolio_loads_custom_token_balance_without_price():
    tok = make_custom_token("ethereum", MYTOKEN, "TPC", "Token Percobaan", 6)
    fake = FakeHttp()
    install_standard(fake)
    fake.post_handlers[rpc_urls("ethereum")[0]] = chain(native_wei=0, balances={MYTOKEN: 2_500_000})
    fake.post_handlers[rpc_urls("base")[0]] = chain()
    snap = PortfolioService(fake).load(ADDR, "mainnet", [tok])
    row = next(r for r in snap.rows if r.token.custom)
    assert row.amount == Decimal("2.5") and row.price_usd is None and row.value_usd is None
    assert snap.rows[0] is row                       # dimiliki tapi tanpa harga: di atas yang saldonya 0


def test_same_symbol_custom_token_does_not_clash_with_builtin():
    tok = make_custom_token("ethereum", FAKE_USDT, "USDT", "Tether USD", 6)
    fake = FakeHttp()
    install_standard(fake)
    fake.post_handlers[rpc_urls("ethereum")[0]] = chain(balances={FAKE_USDT: 7_000_000, USDT: 1_000_000})
    fake.post_handlers[rpc_urls("base")[0]] = chain()
    snap = PortfolioService(fake).load(ADDR, "mainnet", [tok])
    amounts = {r.token.address: r.amount for r in snap.rows if r.token.symbol == "USDT"}
    assert amounts == {USDT: Decimal(1), FAKE_USDT: Decimal(7)}


def test_service_token_info_uses_selected_network():
    fake = FakeHttp()
    fake.post_handlers[rpc_urls("sepolia")[0]] = chain()
    info = PortfolioService(fake).token_info("sepolia", MYTOKEN)
    assert info.symbol == "TPC"


# --------------------------------------------------------------------------
# Harga token kustom menurut contract address (CoinGecko, permintaan gabungan)
# --------------------------------------------------------------------------
NEAR = "0x85F17Cf997934a597031b2E18a9aB6ebD4B9f6a4"
CG_COIN = "https://api.coingecko.com/api/v3/coins/ethereum/contract/"
CG_SIMPLE = "https://api.coingecko.com/api/v3/simple/price"


class FakeCoinGecko:
    """Meniru CoinGecko. `listed`: alamat (huruf kecil) -> (id koin, harga, perubahan 24 jam)."""

    def __init__(self, listed, platform="ethereum"):
        self.listed = {k.lower(): v for k, v in listed.items()}
        self.platform = platform
        self.coin_calls: list[str] = []
        self.simple_calls: list[list[str]] = []

    def install(self, fake):
        def coin(url, params):
            addr = url.removeprefix(CG_COIN).lower()
            self.coin_calls.append(addr)
            if addr not in self.listed:
                raise HttpError("404: coin not found")
            return {"id": self.listed[addr][0], "platforms": {self.platform: addr}}

        def simple(url, params):
            ids = params["ids"].split(",")
            self.simple_calls.append(ids)
            by_id = {v[0]: v for v in self.listed.values()}
            return {i: {"usd": by_id[i][1], "usd_24h_change": by_id[i][2]} for i in ids if i in by_id}

        fake.get_handlers[CG_COIN] = coin
        fake.get_handlers[CG_SIMPLE] = simple
        return self


def near_chain(extra=None):
    contracts = {NEAR: {"name": "NEAR", "symbol": "NEAR", "decimals": 24}}
    balances = {NEAR: 4 * 10**24}
    for addr, (name, sym, dec, bal) in (extra or {}).items():
        contracts[addr] = {"name": name, "symbol": sym, "decimals": dec}
        balances[addr] = bal
    return make_chain(contracts, balances=balances)


def mainnet_fake(chain_handler):
    fake = FakeHttp()
    install_standard(fake)
    fake.post_handlers[rpc_urls("ethereum")[0]] = chain_handler
    fake.post_handlers[rpc_urls("base")[0]] = chain()
    return fake


def test_custom_token_gets_price_and_coin_id_is_resolved_once():
    tok = make_custom_token("ethereum", NEAR, "NEAR", "NEAR Protocol", 24)
    fake = mainnet_fake(near_chain())
    cg = FakeCoinGecko({NEAR: ("near", 2.5, -3.2)}).install(fake)
    svc = PortfolioService(fake)
    snap = svc.load(ADDR, "mainnet", [tok])
    row = next(r for r in snap.rows if r.token.custom)
    assert row.amount == Decimal(4) and row.price_usd == 2.5 and row.change_pct == -3.2 and row.value_usd == 10.0
    assert snap.resolved_ids == {("ethereum", NEAR.lower()): "near"}
    # Setelah ID tersimpan di token, muat berikutnya tidak mencari lagi.
    tok2 = make_custom_token("ethereum", NEAR, "NEAR", "NEAR Protocol", 24, "near")
    svc.prices._id_quote_cache.clear()
    snap2 = svc.load(ADDR, "mainnet", [tok2])
    assert snap2.resolved_ids == {} and len(cg.coin_calls) == 1
    assert next(r for r in snap2.rows if r.token.custom).price_usd == 2.5


def test_many_custom_tokens_use_one_combined_price_request():
    """Laporan pengguna: >1 token kustom membuat semua harga hilang. Kini semuanya lewat satu permintaan."""
    a = make_custom_token("ethereum", NEAR, "NEAR", "NEAR Protocol", 24, "near")
    b = make_custom_token("ethereum", OTHER, "MKR", "Maker", 18, "maker")
    c = make_custom_token("ethereum", MYTOKEN, "TPC", "Test", 6, "tpc")
    fake = mainnet_fake(near_chain({OTHER: ("Maker", "MKR", 18, 10**18), MYTOKEN: ("T", "TPC", 6, 5)}))
    cg = FakeCoinGecko({NEAR: ("near", 2.5, 1.0), OTHER: ("maker", 1800.0, 0.5), MYTOKEN: ("tpc", 0.1, None)}).install(fake)
    snap = PortfolioService(fake).load(ADDR, "mainnet", [a, b, c])
    assert {r.token.symbol: r.price_usd for r in snap.rows if r.token.custom} == {"NEAR": 2.5, "MKR": 1800.0, "TPC": 0.1}
    assert len(cg.simple_calls) == 1 and sorted(cg.simple_calls[0]) == ["maker", "near", "tpc"] and cg.coin_calls == []


def test_lookalike_symbol_does_not_borrow_a_real_price():
    """Token tiruan bersimbol sama (alamat beda) tidak terdaftar di CoinGecko -> tanpa harga."""
    real = make_custom_token("ethereum", NEAR, "NEAR", "NEAR Protocol", 24)
    fake_tok = make_custom_token("ethereum", OTHER, "NEAR", "NEAR Protocol", 24)
    fake = mainnet_fake(near_chain({OTHER: ("NEAR", "NEAR", 24, 10**24)}))
    FakeCoinGecko({NEAR: ("near", 2.5, 1.0)}).install(fake)
    snap = PortfolioService(fake).load(ADDR, "mainnet", [real, fake_tok])
    assert {r.token.address: r.price_usd for r in snap.rows if r.token.custom} == {NEAR: 2.5, OTHER: None}


def test_coin_id_is_rejected_when_platform_address_does_not_match():
    from pywallet.prices import PriceService
    fake = FakeHttp()
    fake.get_handlers[CG_COIN] = lambda u, p: {"id": "near", "platforms": {"ethereum": "0x" + "ab" * 20}}
    assert PriceService(fake).resolve_coin_id("ethereum", NEAR) is None
    fake.get_handlers[CG_COIN] = lambda u, p: {"id": "near"}                  # tanpa daftar platform
    assert PriceService(fake).resolve_coin_id("ethereum", NEAR) is None


def test_testnet_custom_tokens_are_never_priced():
    tok = make_custom_token("sepolia", NEAR, "NEAR", "x", 18)
    fake = FakeHttp()
    install_standard(fake)
    fake.post_handlers[rpc_urls("sepolia")[0]] = chain(balances={NEAR: 10**18})
    snap = PortfolioService(fake).load(ADDR, "testnet", [tok])
    assert [r for r in snap.rows if r.token.custom][0].price_usd is None
    assert not any("coingecko" in u for _, u in fake.calls)


def test_unlisted_token_lookup_is_negatively_cached_and_limited():
    from pywallet.prices import MAX_ID_LOOKUPS, PriceService
    fake = FakeHttp()
    cg = FakeCoinGecko({}).install(fake)
    ps = PriceService(fake)
    addrs = [("0x" + f"{i:040x}", None) for i in range(1, 7)]
    assert ps.custom_quotes("ethereum", addrs).quotes == {}
    assert len(cg.coin_calls) == MAX_ID_LOOKUPS                    # sisanya menunggu muat ulang berikutnya
    ps.custom_quotes("ethereum", addrs[:MAX_ID_LOOKUPS])
    assert len(cg.coin_calls) == MAX_ID_LOOKUPS                    # yang gagal tidak ditanya ulang dulu


def test_prices_survive_a_transient_failure_and_ignore_garbage():
    from pywallet.prices import PriceService
    fake = FakeHttp()
    cg = FakeCoinGecko({NEAR: ("near", 2.5, None)}).install(fake)
    ps = PriceService(fake)
    assert ps.custom_quotes("ethereum", [(NEAR, "near")]).quotes[NEAR.lower()].usd == 2.5
    ps._id_quote_cache = {k: (v[0] - 999, v[1]) for k, v in ps._id_quote_cache.items()}   # cache kedaluwarsa
    del fake.get_handlers[CG_SIMPLE]                                # API sedang mati
    assert ps.custom_quotes("ethereum", [(NEAR, "near")]).quotes[NEAR.lower()].usd == 2.5  # harga terakhir
    fake.get_handlers[CG_SIMPLE] = lambda u, p: {"near": {"usd": "bukan angka"}, "maker": {"usd": -1}}
    assert PriceService(fake).custom_quotes("ethereum", [(NEAR, "near"), (OTHER, "maker")]).quotes == {}
    assert PriceService(fake).custom_quotes("", [(NEAR, "near")]).quotes == {}
    assert cg.coin_calls == []


# --------------------------------------------------------------------------
# Sembunyikan token bawaan & tampilkan lagi
# --------------------------------------------------------------------------
def test_vault_hide_and_unhide_builtin_token(vault):
    assert vault.list_hidden_tokens() == frozenset()
    vault.hide_builtin_token("ethereum", USDT.lower())
    vault.hide_builtin_token("ethereum", USDT)                                 # ganda tidak masalah
    assert vault.list_hidden_tokens() == {("ethereum", USDT.lower())}
    with pytest.raises(VaultError):
        vault.hide_builtin_token("ethereum", MYTOKEN)                          # bukan token bawaan
    assert vault.unhide_builtin_token("ethereum", USDT).symbol == "USDT"
    assert vault.list_hidden_tokens() == frozenset()


def test_hidden_builtin_tokens_leave_the_list_but_native_never_does():
    hidden = {("ethereum", USDT.lower())}
    symbols = [t.symbol for t in tokens_for_mode("mainnet", (), hidden) if t.network == "ethereum"]
    assert "USDT" not in symbols and "ETH" in symbols and "USDC" in symbols
    native_hidden = {("ethereum", "")}
    assert any(t.is_native and t.network == "ethereum" for t in tokens_for_mode("mainnet", (), native_hidden))


def test_portfolio_skips_hidden_tokens():
    fake = mainnet_fake(chain(balances={USDT: 1_000_000}))
    snap = PortfolioService(fake).load(ADDR, "mainnet", (), {("ethereum", USDT.lower())})
    assert not any(r.token.address == USDT for r in snap.rows)


def test_hidden_builtin_can_be_restored_through_add_token_dialog(tmp_path):
    from PySide6.QtWidgets import QApplication

    from pywallet.ui.token_dialogs import AddTokenDialog
    QApplication.instance() or QApplication([])
    v = Vault(Database(tmp_path / "r.db"))
    v.hide_builtin_token("ethereum", USDT)
    fake = FakeHttp()
    dlg = AddTokenDialog(v, PortfolioService(fake), "mainnet")
    dlg.run_in_thread = False
    dlg.addr_edit.setText(USDT)
    dlg.check()
    assert "bawaan" in dlg.preview.text() and dlg.add_btn.isEnabled() and dlg.confirm.isHidden()
    assert dlg.add_btn.text() == "Tampilkan lagi" and not fake.calls            # tanpa tanya jaringan
    dlg._add()
    assert dlg.added.symbol == "USDT" and v.list_hidden_tokens() == frozenset()
    dlg.deleteLater()
    dlg2 = AddTokenDialog(v, PortfolioService(fake), "mainnet")
    dlg2.addr_edit.setText(USDT)
    dlg2.check()
    assert "sudah ada" in dlg2.err.text()                                       # sekarang sudah tampil
    dlg2.deleteLater()


# --------------------------------------------------------------------------
# Ketahanan harga token kustom (laporan: harga hilang acak, hilang semua setelah login ulang)
# --------------------------------------------------------------------------
def test_rate_limit_on_lookup_is_not_remembered_as_not_listed():
    """429 saat mencari ID itu gangguan sementara, bukan 'tidak terdaftar'."""
    from pywallet.prices import PriceService
    fake = FakeHttp()
    state = {"fail": True}

    def coin(url, params):
        if state["fail"]:
            raise HttpError("https://api.coingecko.com/...: HTTP Error 429: Too Many Requests")
        return {"id": "near", "platforms": {"ethereum": NEAR.lower()}}

    fake.get_handlers[CG_COIN] = coin
    ps = PriceService(fake)
    assert ps.resolve_coin_id("ethereum", NEAR) is None
    assert ("ethereum", NEAR.lower()) not in ps._id_negative                  # tidak dicatat sebagai 'tidak terdaftar'
    state["fail"] = False
    assert ps.resolve_coin_id("ethereum", NEAR) is None                      # masih istirahat sebentar
    ps._lookup_pause_until = 0
    assert ps.resolve_coin_id("ethereum", NEAR) == "near"


def test_rate_limit_stops_further_lookups_in_the_same_load():
    from pywallet.prices import PriceService
    fake = FakeHttp()
    calls = []

    def coin(url, params):
        calls.append(url)
        raise HttpError("429")

    fake.get_handlers[CG_COIN] = coin
    ps = PriceService(fake)
    ps.custom_quotes("ethereum", [("0x" + f"{i:040x}", None) for i in range(1, 6)])
    assert len(calls) == 1                                                   # setelah 429 berhenti, tidak menghujani API


def test_persisted_prices_are_used_when_coingecko_refuses():
    """Setelah login ulang memori kosong; harga terakhir dari database mencegah harga hilang semua."""
    import time as _t

    from pywallet.prices import PriceService
    fake = FakeHttp()
    fake.get_handlers[CG_SIMPLE] = lambda u, p: (_ for _ in ()).throw(HttpError("429"))
    saved = {"near": (2.5, -1.0, _t.time() - 3600)}
    got = PriceService(fake).custom_quotes("ethereum", [(NEAR, "near")], saved)
    assert got.quotes[NEAR.lower()].usd == 2.5 and got.fresh == {}
    old = {"near": (2.5, -1.0, _t.time() - 90_000)}                          # lebih dari 24 jam: terlalu basi
    assert PriceService(fake).custom_quotes("ethereum", [(NEAR, "near")], old).quotes == {}


def test_missing_in_response_keeps_old_price_instead_of_dropping_it():
    import time as _t

    from pywallet.prices import PriceService
    fake = FakeHttp()
    fake.get_handlers[CG_SIMPLE] = lambda u, p: {}                            # respons kosong sesaat
    got = PriceService(fake).custom_quotes("ethereum", [(NEAR, "near")], {"near": (2.5, None, _t.time())})
    assert got.quotes[NEAR.lower()].usd == 2.5


def test_vault_price_cache_roundtrip_and_prunes_unknown_ids(vault):
    import time as _t
    now = _t.time()
    vault.add_custom_token("ethereum", NEAR, "NEAR", "NEAR", 24)
    vault.set_custom_coingecko_id("ethereum", NEAR.lower(), "near")
    vault.update_price_cache({"near": (2.5, None, now)})
    vault.update_price_cache({"sampah": (1.0, 1.0, now)})                      # baru dimasukkan: ikut tersimpan
    assert set(vault.get_price_cache()) == {"near", "sampah"}
    vault.update_price_cache({"near": (2.6, 1.5, now)})                        # 'sampah' bukan milik token mana pun: dibuang
    cache = vault.get_price_cache()
    assert set(cache) == {"near"} and cache["near"][:2] == (2.6, 1.5)
    vault.db.set_setting("price_cache", "bukan json")
    assert vault.get_price_cache() == {}
    with pytest.raises(VaultError):
        vault.set_custom_coingecko_id("ethereum", NEAR, "ID Tidak Valid!")


def test_ids_found_by_a_superseded_load_are_still_saved(tmp_path):
    """Muat data yang kedaluwarsa (rid lama) tetap menyimpan ID & harga yang sudah ditemukan."""
    from PySide6.QtWidgets import QApplication

    from pywallet.portfolio import Snapshot
    from pywallet.ui.pages import WalletTab
    QApplication.instance() or QApplication([])
    v = Vault(Database(tmp_path / "s.db"))
    v.add_custom_token("ethereum", NEAR, "NEAR", "NEAR", 24)
    tab = WalletTab(v, PortfolioService(FakeHttp()))
    snap = Snapshot(mode="mainnet", address=ADDR, rows=[], resolved_ids={("ethereum", NEAR.lower()): "near"},
                    price_updates={"near": (2.5, None, 1.0)})
    tab._request_id = 5
    tab._on_loaded(3, snap)                                                   # rid 3 sudah usang
    assert tab.snapshot is None                                               # hasilnya sendiri tidak dipakai
    assert v.list_custom_tokens()[0].coingecko_id == "near" and v.get_price_cache()["near"][0] == 2.5
    tab.deleteLater()


def test_many_tokens_get_resolved_over_successive_loads_and_prices_then_persist():
    tokens = [(f"0x{i:040x}", f"coin{i}") for i in range(1, 8)]
    fake = mainnet_fake(make_chain({}))
    cg = FakeCoinGecko({a: (cid, float(i), None) for i, (a, cid) in enumerate(tokens, 1)}).install(fake)
    svc = PortfolioService(fake)
    known: dict[str, str] = {}                                                # ID yang 'tersimpan' di database
    for _round in range(4):
        toks = [make_custom_token("ethereum", normalize_contract_address(a), f"T{i}", "t", 18, known.get(a.lower()))
                for i, (a, _cid) in enumerate(tokens, 1)]
        snap = svc.load(ADDR, "mainnet", toks)
        known.update({addr: cid for (_net, addr), cid in snap.resolved_ids.items()})
    priced = {r.token.symbol for r in snap.rows if r.token.custom and r.price_usd}
    assert len(known) == 7 and priced == {f"T{i}" for i in range(1, 8)}       # semua akhirnya berharga
    assert len(cg.coin_calls) == 7                                            # tiap token dicari ID-nya sekali saja
