from decimal import Decimal

import pytest
from eth_utils import is_checksum_address

from pywallet import config
from pywallet.formatting import (
    format_amount,
    format_eth,
    format_idr,
    format_percent,
    format_price,
    format_usd,
)
from pywallet.networks import MODES, NETWORKS
from pywallet.portfolio import AssetRow, PortfolioService, Snapshot, sort_assets
from pywallet.prices import FX_FALLBACK_URL, PriceService
from pywallet.rpc import RpcClient, RpcError, encode_balance_of, fetch_balances
from pywallet.tokens import TOKENS, Token, tokens_for_mode

from .fakes import FakeHttp, install_standard, make_binance, make_rpc, rpc_urls



@pytest.fixture(autouse=True)
def extended_tokens(monkeypatch):
    """Daftar token diperluas dimatikan di produksi (config), tetapi jalurnya tetap diuji di sini."""
    monkeypatch.setattr(config, "EXTENDED_TOKEN_LIST", True)


ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
ETH = 10**18


def tok(network, symbol, decimals=18, address=None, price_symbol=None, peg=None):
    return Token(network, symbol, symbol, decimals, address, price_symbol, peg)


# --------------------------------------------------------------------------
# Daftar token / jaringan
# --------------------------------------------------------------------------
def test_all_token_addresses_are_valid_checksum_and_unique():
    for net, tokens in TOKENS.items():
        assert net in NETWORKS
        addrs = [t.address for t in tokens if t.address]
        assert all(is_checksum_address(a) for a in addrs), net
        assert len(addrs) == len({a.lower() for a in addrs})
        assert len({t.symbol for t in tokens}) == len(tokens)
        assert sum(t.is_native for t in tokens) == 1          # tepat satu koin native


def test_mainnet_covers_requested_assets():
    keys = {t.key for t in tokens_for_mode("mainnet")}
    for required in ("ethereum:ETH", "base:ETH", "ethereum:USDT", "ethereum:USDC"):
        assert required in keys
    assert len(keys) >= 10                                    # + koin populer lain
    assert {t.network for t in tokens_for_mode("testnet")} == {"sepolia"}


def test_every_priced_token_has_price_source():
    for t in tokens_for_mode("mainnet") + tokens_for_mode("testnet"):
        assert t.price_symbol or t.peg_usd, t.key


def test_modes_reference_known_networks():
    for nets in MODES.values():
        assert all(n in NETWORKS for n in nets)
    assert NETWORKS["sepolia"].is_testnet and not NETWORKS["base"].is_testnet


# --------------------------------------------------------------------------
# RPC
# --------------------------------------------------------------------------
def test_encode_balance_of():
    data = encode_balance_of(ADDR)
    assert data.startswith("0x70a08231") and len(data) == 2 + 8 + 64
    assert data.endswith(ADDR[2:].lower())


def test_rpc_batch_ok():
    fake = FakeHttp()
    url = "https://rpc.test"
    fake.post_handlers[url] = make_rpc(native_wei=2 * ETH, token_raw={"0xaa": 5})
    rpc = RpcClient(fake, [url])
    out = rpc.batch([("eth_getBalance", [ADDR, "latest"]), ("eth_call", [{"to": "0xAA", "data": "0x"}, "latest"])])
    assert out == [hex(2 * ETH), hex(5)]
    assert len(fake.calls) == 1                               # satu permintaan batch


def test_rpc_falls_back_to_sequential_when_batch_unsupported():
    fake = FakeHttp()
    url = "https://rpc.test"
    fake.post_handlers[url] = make_rpc(native_wei=ETH, batch=False)
    rpc = RpcClient(fake, [url])
    out = rpc.batch([("eth_getBalance", [ADDR, "latest"])] * 3)
    assert out == [hex(ETH)] * 3
    assert len(fake.calls) == 1 + 3                           # 1 batch gagal + 3 satuan


def test_rpc_failover_to_second_endpoint():
    fake = FakeHttp()
    fake.post_handlers["https://b.test"] = make_rpc(native_wei=7)
    rpc = RpcClient(fake, ["https://a.test", "https://b.test"])     # a tidak merespons
    assert rpc.call("eth_getBalance", [ADDR, "latest"]) == hex(7)


def test_rpc_all_down_returns_errors_without_retry_storm():
    fake = FakeHttp()
    rpc = RpcClient(fake, ["https://a.test", "https://b.test"])
    out = rpc.batch([("eth_getBalance", [ADDR, "latest"])] * 5)
    assert all(isinstance(x, RpcError) for x in out)
    assert len(fake.calls) == 2                               # hanya 1 percobaan per endpoint


def test_fetch_balances_partial_error():
    fake = FakeHttp()
    url = "https://rpc.test"

    def handler(payload):
        res = make_rpc(native_wei=ETH)(payload)
        res[1] = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "execution reverted"}}
        return res

    fake.post_handlers[url] = handler
    tokens = TOKENS["ethereum"][:2]                           # ETH + USDT
    out = fetch_balances(RpcClient(fake, [url]), ADDR, tokens)
    assert out["ethereum:ETH"] == ETH
    assert isinstance(out["ethereum:USDT"], RpcError)


def test_empty_return_data_means_zero():
    fake = FakeHttp()
    url = "https://rpc.test"
    fake.post_handlers[url] = lambda p: [{"id": i, "result": "0x"} for i in range(len(p))]
    out = fetch_balances(RpcClient(fake, [url]), ADDR, TOKENS["ethereum"][:2])
    assert list(out.values()) == [0, 0]


# --------------------------------------------------------------------------
# Harga
# --------------------------------------------------------------------------
def test_quotes_parse_and_fallback_per_symbol():
    fake = FakeHttp()
    install_standard(fake, prices={"ETHUSDT": (3000.0, 2.5), "BTCUSDT": (100000.0, -1.0)})
    ps = PriceService(fake)
    q = ps.quotes(["ETHUSDT", "BTCUSDT"])
    assert q["ETHUSDT"].usd == 3000.0 and q["ETHUSDT"].change_pct == 2.5
    # satu simbol tidak valid -> permintaan batch gagal, simbol lain tetap didapat
    q = ps.quotes(["ETHUSDT", "NOPEUSDT"])
    assert set(q) == {"ETHUSDT"}


def test_quotes_failover_host_and_total_failure():
    fake = FakeHttp()
    fake.get_handlers["https://api.binance.com"] = make_binance({"ETHUSDT": (1.0, 0.0)})
    assert PriceService(fake).quotes(["ETHUSDT"])["ETHUSDT"].usd == 1.0   # host pertama mati
    assert PriceService(FakeHttp()).quotes(["ETHUSDT"]) == {}


def test_usd_idr_sources():
    fake = FakeHttp()
    install_standard(fake, usdt_idr=16250.5)
    assert PriceService(fake).usd_idr() == 16250.5

    fake = FakeHttp()
    install_standard(fake, usdt_idr=None)                                  # Binance tak punya pair
    fake.get_handlers[FX_FALLBACK_URL] = lambda u, p: {"rates": {"IDR": 16100.0}}
    assert PriceService(fake).usd_idr() == 16100.0

    assert PriceService(FakeHttp()).usd_idr() is None


def test_sparkline():
    fake = FakeHttp()
    install_standard(fake)
    assert len(PriceService(fake).sparkline()) == 24
    assert PriceService(FakeHttp()).sparkline() == []


# --------------------------------------------------------------------------
# Pengurutan aset
# --------------------------------------------------------------------------
def row(network, symbol, amount, price=None):
    return AssetRow(tok(network, symbol), None if amount is None else Decimal(str(amount)), price, None)


def order(rows):
    return [(r.token.network, r.token.symbol) for r in sort_assets(rows)]


def test_sort_largest_value_first_then_zero_alphabetical():
    rows = [
        row("ethereum", "USDT", 0, 1.0),
        row("ethereum", "WBTC", 0.001, 100000.0),   # $100
        row("ethereum", "AAVE", 0, 200.0),
        row("ethereum", "ETH", 0.5, 3000.0),        # $1500
        row("base", "ETH", 0.1, 3000.0),            # $300
        row("ethereum", "USDC", 200, 1.0),          # $200
        row("base", "cbBTC", 0, 100000.0),
        row("ethereum", "DAI", 0, 1.0),
        row("ethereum", "LINK", 0, 15.0),
    ]
    assert order(rows) == [
        ("ethereum", "ETH"), ("base", "ETH"), ("ethereum", "USDC"), ("ethereum", "WBTC"),
        ("ethereum", "AAVE"), ("base", "cbBTC"), ("ethereum", "DAI"), ("ethereum", "LINK"),
        ("ethereum", "USDT"),
    ]


def test_value_not_amount_decides_order():
    # jumlah SHIB jauh lebih banyak (1 juta), tetapi nilainya ($20) lebih kecil daripada 0.01 ETH ($30)
    rows = [row("ethereum", "SHIB", 1_000_000, 0.00002), row("ethereum", "ETH", 0.01, 3000.0)]
    assert [s for _, s in order(rows)] == ["ETH", "SHIB"]


def test_zero_balance_ties_sorted_by_symbol_then_network():
    rows = [row("ethereum", "ETH", 0, 3000.0), row("base", "ETH", 0, 3000.0), row("ethereum", "AAVE", 0)]
    assert order(rows) == [("ethereum", "AAVE"), ("base", "ETH"), ("ethereum", "ETH")]


def test_unpriced_holdings_come_after_priced_but_before_zero():
    rows = [
        row("ethereum", "AAA", 0, 1.0),
        row("ethereum", "MYSTERY", 10, None),
        row("ethereum", "ETH", 0.001, 3000.0),
    ]
    assert [s for _, s in order(rows)] == ["ETH", "MYSTERY", "AAA"]


def test_failed_rows_are_treated_as_zero_group():
    rows = [row("base", "USDC", None, 1.0), row("ethereum", "ETH", 1, 3000.0), row("ethereum", "AAVE", 0, 200.0)]
    assert [s for _, s in order(rows)] == ["ETH", "AAVE", "USDC"]


# --------------------------------------------------------------------------
# Snapshot: total & satuan
# --------------------------------------------------------------------------
def snapshot(mode="mainnet", **kw):
    rows = [
        AssetRow(tok("ethereum", "ETH"), Decimal("1"), 3000.0, 2.0),
        AssetRow(tok("ethereum", "USDC"), Decimal("500"), 1.0, 0.0),
    ]
    return Snapshot(mode=mode, address=ADDR, rows=rows, usd_idr=16000.0, eth_usd=3000.0, **kw)


def test_totals_in_three_units():
    s = snapshot()
    assert s.total_in("usd") == 3500.0
    assert s.total_in("idr") == 3500.0 * 16000
    assert s.total_in("eth") == Decimal("3500") / Decimal("3000")
    assert s.row_value(s.rows[1], "usd") == 500.0
    assert s.row_value(s.rows[0], "idr") == 3000.0 * 16000


def test_units_degrade_gracefully_without_rates():
    s = snapshot()
    s.usd_idr = None
    s.eth_usd = None
    assert s.total_in("idr") is None and s.total_in("eth") is None
    assert s.total_in("usd") == 3500.0


def test_portfolio_change_is_value_weighted():
    s = snapshot()
    # ETH $3000 naik 2% => kemarin 2941.18; USDC 500 tetap => total 3500 vs 3441.18
    assert s.change_pct() == pytest.approx((3500 / (3000 / 1.02 + 500) - 1) * 100)


def test_testnet_is_valueless_and_eth_unit_is_native_balance():
    rows = [
        AssetRow(tok("sepolia", "ETH", address=None), Decimal("0.25"), 3000.0, 1.0),
        AssetRow(tok("sepolia", "USDC", address="0xabc"), Decimal("10"), 1.0, 0.0),
    ]
    s = Snapshot(mode="testnet", address=ADDR, rows=rows, usd_idr=16000.0, eth_usd=3000.0)
    assert not s.fiat_enabled
    assert s.total_in("usd") == 0.0 and s.total_in("idr") == 0.0
    assert s.total_in("eth") == Decimal("0.25")
    assert s.row_value(rows[0], "usd") is None
    assert s.change_pct() is None


# --------------------------------------------------------------------------
# PortfolioService end-to-end (HTTP palsu)
# --------------------------------------------------------------------------
def build_service(eth_wei=2 * ETH, base_wei=ETH // 2, usdc_raw=1_500_000_000, fail_base=False):
    fake = FakeHttp()
    install_standard(fake)
    eth_usdc = TOKENS["ethereum"][2].address          # USDC mainnet
    fake.post_handlers[rpc_urls("ethereum")[0]] = make_rpc(eth_wei, {eth_usdc: usdc_raw})
    if not fail_base:
        fake.post_handlers[rpc_urls("base")[0]] = make_rpc(base_wei)
    return PortfolioService(fake), fake


def test_service_mainnet_end_to_end():
    svc, _ = build_service()
    snap = svc.load(ADDR, "mainnet")
    assert snap.errors == []
    by_key = {r.token.key: r for r in snap.rows}
    assert by_key["ethereum:ETH"].amount == Decimal("2")
    assert by_key["base:ETH"].amount == Decimal("0.5")
    assert by_key["ethereum:USDC"].amount == Decimal("1500")        # 6 desimal
    # urutan: ETH 2 ($6000), USDC ($1500), ETH Base ($1500 -> seri: jumlah lebih besar dulu), sisanya 0
    top = [r.token.key for r in snap.rows[:3]]
    assert top[0] == "ethereum:ETH" and set(top[1:]) == {"ethereum:USDC", "base:ETH"}
    zeros = [r.token.symbol.lower() for r in snap.rows[3:]]
    assert zeros == sorted(zeros)
    assert snap.total_usd() == pytest.approx(2 * 3000 + 0.5 * 3000 + 1500)
    assert snap.usd_idr == 16000.0 and snap.eth_usd == 3000.0 and len(snap.eth_spark) == 24


def test_service_reports_network_failure_but_keeps_others():
    svc, _ = build_service(fail_base=True)
    snap = svc.load(ADDR, "mainnet")
    assert snap.errors == ["Saldo Base gagal dimuat"]
    base_eth = next(r for r in snap.rows if r.token.key == "base:ETH")
    assert base_eth.amount is None
    assert next(r for r in snap.rows if r.token.key == "ethereum:ETH").amount == Decimal("2")


def test_service_prices_down_uses_stablecoin_peg():
    svc, fake = build_service()
    fake.get_handlers.clear()                                       # semua API harga mati
    snap = svc.load(ADDR, "mainnet")
    assert "Harga pasar gagal dimuat" in snap.errors
    usdc = next(r for r in snap.rows if r.token.key == "ethereum:USDC")
    assert usdc.price_usd == 1.0 and usdc.value_usd == 1500.0       # cadangan peg stablecoin
    eth = next(r for r in snap.rows if r.token.key == "ethereum:ETH")
    assert eth.price_usd is None and snap.eth_usd is None


def test_service_testnet_ranks_with_reference_prices():
    fake = FakeHttp()
    install_standard(fake)
    sepolia_link = TOKENS["sepolia"][2].address
    fake.post_handlers[rpc_urls("sepolia")[0]] = make_rpc(ETH // 10, {sepolia_link: 50 * ETH})
    snap = PortfolioService(fake).load(ADDR, "testnet")
    # 0.1 ETH ($300) vs 50 LINK ($750): LINK lebih besar menurut harga referensi
    assert [r.token.symbol for r in snap.rows[:2]] == ["LINK", "ETH"]
    assert snap.total_in("usd") == 0.0 and snap.total_in("eth") == Decimal("0.1")


# --------------------------------------------------------------------------
# Format
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fn,value,expected",
    [
        (format_usd, 1234.5, "$1,234.50"),
        (format_usd, 0.004, "<$0.01"),
        (format_usd, 0, "$0.00"),
        (format_idr, 52345678.4, "Rp52.345.678"),
        (format_idr, 0, "Rp0"),
        (format_amount, Decimal("0.00657"), "0.00657"),
        (format_amount, Decimal("5.95544"), "5.9554"),
        (format_amount, Decimal("12345.678"), "12,345.68"),
        (format_amount, Decimal("0"), "0"),
        (format_amount, Decimal("0.0000001"), "<0.000001"),
        (format_eth, Decimal("1.1666666666"), "1.166667 ETH"),
        (format_eth, Decimal("0"), "0 ETH"),
        (format_price, 3201.554, "$3,201.55"),
        (format_price, 0.00002, "$0.00002000"),
        (format_percent, 1.234, "+1.23%"),
        (format_percent, -0.5, "-0.50%"),
    ],
)
def test_formatting(fn, value, expected):
    assert fn(value) == expected
