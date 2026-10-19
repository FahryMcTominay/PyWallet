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
