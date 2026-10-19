"""Saklar EXTENDED_TOKEN_LIST: aktif (True) secara bawaan; bila dimatikan hanya koin native ETH yang tampil."""
import pytest
from decimal import Decimal

from pywallet import config
from pywallet.portfolio import PortfolioService
from pywallet.tokens import active_networks, tokens_for_mode

from .fakes import FakeHttp, install_standard, make_rpc, rpc_urls

ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setattr(config, "EXTENDED_TOKEN_LIST", False)


def test_flag_is_on_by_default():
    assert config.EXTENDED_TOKEN_LIST is True


def test_default_mainnet_list_is_the_agreed_set():
    assert [t.key for t in tokens_for_mode("mainnet")] == [
        "ethereum:ETH", "ethereum:USDT", "ethereum:USDC", "ethereum:DAI", "ethereum:WBTC",
        "ethereum:LINK", "ethereum:UNI", "ethereum:CAKE", "base:ETH", "base:USDC",
    ]


def test_only_native_eth_when_flag_off(flag_off):
    assert [t.key for t in tokens_for_mode("mainnet")] == ["ethereum:ETH"]
    assert [t.key for t in tokens_for_mode("testnet")] == ["sepolia:ETH"]
    assert [n.key for n in active_networks("mainnet")] == ["ethereum"]
    assert [n.key for n in active_networks("testnet")] == ["sepolia"]


def test_flag_on_includes_requested_assets():
    keys = {t.key for t in tokens_for_mode("mainnet")}
    assert {"ethereum:ETH", "base:ETH", "ethereum:USDT", "ethereum:USDC"} <= keys
    assert [n.key for n in active_networks("mainnet")] == ["ethereum", "base"]


def test_mainnet_load_does_not_touch_base_rpc_when_flag_off(flag_off):
    fake = FakeHttp()
    install_standard(fake)
    fake.post_handlers[rpc_urls("ethereum")[0]] = make_rpc(2 * 10**18)
    fake.post_handlers[rpc_urls("base")[0]] = make_rpc(10**18)
    snap = PortfolioService(fake).load(ADDR, "mainnet")
    assert [r.token.key for r in snap.rows] == ["ethereum:ETH"]
    assert snap.rows[0].amount == Decimal("2")
    assert not any(url in rpc_urls("base") for _, url in fake.calls)
