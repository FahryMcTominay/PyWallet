"""Tes lapisan swap (tanpa UI): encoding kontrak, kutipan, rencana, dan transaksi approve/swap."""
from __future__ import annotations

import os
import time
from decimal import Decimal

import pytest
from eth_abi import decode
from eth_account import Account

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pywallet import swap, tx  # noqa: E402
from pywallet.networks import NETWORKS  # noqa: E402
from pywallet.rpc import RpcClient  # noqa: E402
from pywallet.tokens import TOKENS  # noqa: E402

from .fakes import FakeDexChain, FakeHttp  # noqa: E402

NET = NETWORKS["sepolia"]
PROV = swap.providers_for("sepolia")[0]
ETH, USDC, LINK, WETH = TOKENS["sepolia"]
ME = "0x" + "ab" * 20
ME_CS = swap._addr(ME)


def rpc_for(chain: FakeDexChain) -> RpcClient:
    fake = FakeHttp()
    fake.post_handlers[NET.rpc_urls[0]] = chain.handler
    return RpcClient(fake, NET.rpc_urls)


def chain(**kw) -> FakeDexChain:
    return FakeDexChain(quoter=PROV.quoter, **kw)


def test_selectors_match_known_values():
    assert swap.SEL_APPROVE == "095ea7b3" and swap.SEL_ALLOWANCE == "dd62ed3e"
    assert swap.SEL_SWAP == "04e45aaf" and swap.SEL_MULTICALL == "5ae401dc"
    assert swap.SEL_UNWRAP == "49404b7c" and swap.SEL_QUOTE == "c6a5026a"


def test_provider_addresses_are_valid_checksums():
    for p in swap.providers_for("sepolia"):
        for a in (p.router, p.quoter, p.factory, p.weth):
            assert swap._addr(a) == a
    assert PROV.weth == WETH.address                      # WETH uji di daftar token = WETH milik DEX
    assert swap.swap_networks(("ethereum", "sepolia", "base")) == ("sepolia",)


@pytest.mark.parametrize("text,bps", [("0.5", 50), ("0,5", 50), (" 1 % ", 100), ("3", 300), ("0.01", 1), ("50", 5000)])
def test_parse_slippage_ok(text, bps):
    assert swap.parse_slippage(text) == bps


@pytest.mark.parametrize("text", ["", "abc", "0", "0.001", "51", "-1", "1.2.3"])
def test_parse_slippage_rejects(text):
    with pytest.raises(swap.SwapError):
        swap.parse_slippage(text)


def test_min_out_rounds_down():
    assert swap.min_out_for(1000, 50) == 995 and swap.min_out_for(999, 50) == 994


def test_encode_swap_token_to_token_has_no_unwrap():
    data = swap.encode_swap(PROV, USDC.address, LINK.address, 3000, 5_000_000, 4_000_000, ME, False, 1_900_000_000)
    assert data.startswith("0x" + swap.SEL_MULTICALL)
    deadline, calls = decode(["uint256", "bytes[]"], bytes.fromhex(data[10:]))
    assert deadline == 1_900_000_000 and len(calls) == 1 and calls[0][:4].hex() == swap.SEL_SWAP
    (tin, tout, fee, recipient, amt, mn, lim), = decode(
        ["(address,address,uint24,address,uint256,uint256,uint160)"], calls[0][4:])
    assert (tin, tout, fee, recipient, amt, mn, lim) == (
        USDC.address.lower(), LINK.address.lower(), 3000, ME_CS.lower(), 5_000_000, 4_000_000, 0)


def test_encode_swap_native_out_unwraps_to_user():
    data = swap.encode_swap(PROV, USDC.address, PROV.weth, 500, 1, 7, ME, True, 1_900_000_000)
    _deadline, calls = decode(["uint256", "bytes[]"], bytes.fromhex(data[10:]))
    assert len(calls) == 2 and calls[1][:4].hex() == swap.SEL_UNWRAP
    (mn, to), = [decode(["uint256", "address"], calls[1][4:])]
    assert mn == 7 and to == ME_CS.lower()
    (_a, _b, _c, recipient, *_), = decode(["(address,address,uint24,address,uint256,uint256,uint160)"], calls[0][4:])
    assert recipient == swap.ADDRESS_THIS                 # WETH diterima router dulu, baru dibuka


def test_swap_tokens_maps_native_to_weth_and_rejects_same_pair():
    assert swap.swap_tokens(PROV, ETH, USDC) == (PROV.weth, USDC.address)
    with pytest.raises(swap.SwapError):
        swap.swap_tokens(PROV, ETH, WETH)                 # ETH <-> WETH bukan swap
    with pytest.raises(swap.SwapError):
        swap.swap_tokens(PROV, USDC, USDC)
    with pytest.raises(swap.SwapError):
        swap.swap_tokens(PROV, TOKENS["ethereum"][0], USDC)


def test_prepare_swap_picks_best_fee_tier():
    c = chain(pools={500: 1_900_000, 3000: 2_050_000, 10000: 2_000_000})
    plan = swap.prepare_swap(rpc_for(c), NET, PROV, ETH, USDC, 10**15, ME, 10**18)
    assert plan.quote.fee == 3000 and plan.quote.amount_out == 2_050_000
    assert sorted(c.quote_calls) == sorted(PROV.fee_tiers)           # semua tier ditanya (satu batch)
    assert plan.min_out == 2_050_000 * 9950 // 10000
    assert not plan.needs_approval                                    # native tidak butuh izin
    assert plan.rate == Decimal("2050")                               # 2,05 USDC untuk 0,001 ETH
    assert plan.token_in == PROV.weth and plan.unwrap_native_out is False


def test_prepare_swap_needs_approval_depends_on_allowance():
    amt = 5_000_000
    low = swap.prepare_swap(rpc_for(chain(allowance=amt - 1)), NET, PROV, USDC, ETH, amt, ME, 10**7)
    assert low.needs_approval and low.unwrap_native_out
    ok = swap.prepare_swap(rpc_for(chain(allowance=amt)), NET, PROV, USDC, ETH, amt, ME, 10**7)
    assert not ok.needs_approval and ok.est_gas() < low.est_gas()


def test_prepare_swap_no_pool_and_errors():
    with pytest.raises(swap.SwapError, match="kolam likuiditas"):
        swap.prepare_swap(rpc_for(chain(pools={})), NET, PROV, ETH, USDC, 10**15, ME, 10**18)
    with pytest.raises(swap.SwapError, match="tidak cukup"):
        swap.prepare_swap(rpc_for(chain()), NET, PROV, ETH, USDC, 10**19, ME, 10**18)
    with pytest.raises(swap.SwapError, match="chain ID"):
        swap.prepare_swap(rpc_for(chain(chain_id=1)), NET, PROV, ETH, USDC, 10**15, ME, 10**18)
    down = RpcClient(FakeHttp(), NET.rpc_urls)
    with pytest.raises(swap.SwapError, match="terhubung"):
        swap.prepare_swap(down, NET, PROV, ETH, USDC, 10**15, ME, 10**18)


def test_prepare_swap_requires_gas_money():
    c = chain(native_wei=10**9)                                       # hampir nol ETH untuk gas
    with pytest.raises(swap.SwapError, match="biaya gas"):
        swap.prepare_swap(rpc_for(c), NET, PROV, USDC, ETH, 1_000_000, ME, 10**7)
    c2 = chain(native_wei=10**15)                                     # jual ETH: jumlah + gas harus muat
    with pytest.raises(swap.SwapError, match="biaya gas"):
        swap.prepare_swap(rpc_for(c2), NET, PROV, ETH, USDC, 10**15, ME, 10**15)


def test_approve_is_exact_amount_not_unlimited():
    data = swap.encode_approve(PROV.router, 123)
    spender, amount = decode(["address", "uint256"], bytes.fromhex(data[10:]))
    assert data.startswith("0x095ea7b3") and spender == PROV.router.lower() and amount == 123


def test_prepare_call_builds_signable_fields():
    c = chain(estimate_gas=150_000)
    plan = swap.prepare_call(rpc_for(c), NET, ME, PROV.router, "0x1234", value=5)
    f = plan.tx_fields(tx.SPEED_NORMAL)
    assert f["to"] == PROV.router and f["value"] == 5 and f["data"] == "0x1234" and f["type"] == 2
    assert f["gas"] == 187_500 and f["nonce"] == 7 and f["chainId"] == 11155111


def test_prepare_call_estimate_revert_is_friendly():
    c = chain(estimate_error="execution reverted: Too little received")
    with pytest.raises(swap.SwapError, match="slippage"):
        swap.prepare_call(rpc_for(c), NET, ME, PROV.router, "0x")


def test_wait_receipt_polls_until_found():
    calls = []
    c = chain(receipt_status=None)
    rpc = rpc_for(c)
    assert swap.wait_receipt(rpc, "0x" + "11" * 32, attempts=3, delay=0, sleep=calls.append) is None
    assert len(calls) == 2
    c.receipt_status = 1
    r = swap.wait_receipt(rpc, "0x" + "11" * 32, attempts=3, delay=0, sleep=calls.append)
    assert r is not None and r.success


def test_signed_swap_recovers_sender():
    acct = Account.create()
    c = chain()
    plan = swap.prepare_swap(rpc_for(c), NET, PROV, ETH, USDC, 10**15, acct.address, 10**18)
    call = swap.prepare_call(rpc_for(c), NET, acct.address, PROV.router, plan.swap_calldata(), plan.swap_value())
    signed = acct.sign_transaction(call.tx_fields(tx.SPEED_NORMAL))
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    assert Account.recover_transaction(raw) == acct.address
    assert time.time() - plan.created_at < swap.QUOTE_MAX_AGE


# --------------------------------------------------------------------------
# Layar Swap
# --------------------------------------------------------------------------
from .test_send import PW, qapp, vault, wallet  # noqa: E402,F401  (fixture bersama)
from pywallet.portfolio import AssetRow, PortfolioService  # noqa: E402


def decode_sent(raw: str) -> dict:
    from eth_account.typed_transactions import TypedTransaction
    from hexbytes import HexBytes
    return TypedTransaction.from_bytes(HexBytes(raw)).transaction.dictionary


def make_screen(vault, wallet, chain, rows=None):
    from pywallet.ui.swap_screen import SwapScreen
    fake = FakeHttp()
    fake.post_handlers[NET.rpc_urls[0]] = chain.handler
    rows = rows if rows is not None else [
        AssetRow(ETH, Decimal("1"), None, None),
        AssetRow(USDC, Decimal("5"), 1.0, None),
        AssetRow(LINK, Decimal("0"), None, None),
        AssetRow(WETH, Decimal("0"), None, None),
    ]
    scr = SwapScreen(vault, PortfolioService(fake), wallet, rows)
    scr.run_in_thread = False
    return scr


def pick(combo, prefix):
    for i in range(combo.count()):
        if combo.itemText(i).startswith(prefix):
            combo.setCurrentIndex(i)
            return
    raise AssertionError(f"{prefix} tidak ada di {[combo.itemText(i) for i in range(combo.count())]}")


def test_screen_native_to_token_full_flow(qapp, vault, wallet):
    chain = chain_(pools={3000: 2_000_000})
    scr = make_screen(vault, wallet, chain)
    pick(scr.sell_combo, "ETH")
    pick(scr.buy_combo, "USDC")
    scr.amount_edit.setText("0,001")
    scr._on_next()
    assert scr.pages.currentIndex() == 1
    text = scr.summary_text()
    assert "0.001 ETH" in text and "≈ 2 USDC" in text and "Uniswap V3" in text and "fee 0.3%" in text
    assert scr.summary_values["approve"].isHidden()                       # native: tanpa izin

    scr.swap_btn.click()                                                  # tanpa password
    assert chain.sent == [] and not scr.review_err.isHidden()
    scr.pw_field.edit.setText("salah-banget-1")
    scr.swap_btn.click()
    assert chain.sent == [] and "salah" in scr.review_err.text().lower()

    scr.pw_field.edit.setText(PW)
    scr.swap_btn.click()
    assert len(chain.sent) == 1 and scr.sent_hash is not None
    f = decode_sent(chain.sent[0])
    assert f["to"].hex() == PROV.router.lower().removeprefix("0x") and f["value"] == 10**15
    assert f["data"].hex().startswith(swap.SEL_MULTICALL)
    assert Account.recover_transaction(chain.sent[0]) == wallet.address
    assert scr.pages.currentIndex() == 2 and "Berhasil" in scr.status_title.text()
    logged = vault.list_sent_txs(wallet.address)
    assert len(logged) == 1 and logged[0].symbol == "ETH" and logged[0].amount_raw == 10**15
    assert logged[0].to_address == PROV.router and logged[0].status == "success"
    assert scr._pw == ""                                                  # password tidak tersimpan setelah selesai


def chain_(**kw) -> FakeDexChain:
    return FakeDexChain(quoter=PROV.quoter, **kw)


def test_screen_token_to_native_sends_approve_then_swap(qapp, vault, wallet):
    chain = chain_(pools={500: 4 * 10**14}, allowance=0)
    scr = make_screen(vault, wallet, chain)
    pick(scr.sell_combo, "USDC")
    pick(scr.buy_combo, "ETH")
    scr.amount_edit.setText("5")
    scr._on_next()
    assert scr.pages.currentIndex() == 1
    assert "Perlu" in scr.summary_values["approve"].text() and not scr.summary_values["approve"].isHidden()
    scr.pw_field.edit.setText(PW)
    scr.swap_btn.click()
    assert len(chain.sent) == 2
    approve, swap_tx = (decode_sent(r) for r in chain.sent)
    assert approve["to"].hex() == USDC.address.lower().removeprefix("0x")
    assert approve["data"].hex().startswith(swap.SEL_APPROVE)
    spender, amount = decode(["address", "uint256"], bytes(approve["data"])[4:])
    assert spender == PROV.router.lower() and amount == 5_000_000        # izin pas jumlah swap, bukan tak terbatas
    assert swap_tx["to"].hex() == PROV.router.lower().removeprefix("0x") and swap_tx["value"] == 0
    assert "Berhasil" in scr.status_title.text() and scr.sent_hash is not None


def test_screen_approval_failure_stops_before_swap(qapp, vault, wallet):
    chain = chain_(allowance=0, receipt_status=0)
    scr = make_screen(vault, wallet, chain)
    pick(scr.sell_combo, "USDC")
    pick(scr.buy_combo, "ETH")
    scr.amount_edit.setText("1")
    scr._on_next()
    scr.pw_field.edit.setText(PW)
    scr.swap_btn.click()
    assert len(chain.sent) == 1 and scr.sent_hash is None                # hanya izin; swap tidak dikirim
    assert "tidak jadi" in scr.status_title.text() and "izin" in scr.status_detail.text().lower()
    assert scr._pw == "" and vault.list_sent_txs(wallet.address) == []


def test_screen_swap_estimate_revert_is_reported_without_sending(qapp, vault, wallet):
    chain = chain_(estimate_error="execution reverted: Too little received")
    scr = make_screen(vault, wallet, chain)
    pick(scr.sell_combo, "ETH")
    pick(scr.buy_combo, "USDC")
    scr.amount_edit.setText("0.001")
    scr._on_next()
    scr.pw_field.edit.setText(PW)
    scr.swap_btn.click()
    assert chain.sent == [] and "slippage" in scr.status_detail.text() and scr._pw == ""


def test_screen_form_validation_and_pair_options(qapp, vault, wallet):
    scr = make_screen(vault, wallet, chain_())
    pick(scr.sell_combo, "ETH")
    symbols = [r.token.symbol for r in scr._buy_options]
    assert "ETH" not in symbols and "WETH" not in symbols and {"USDC", "LINK"} <= set(symbols)   # ETH<->WETH tidak ditawarkan
    pick(scr.sell_combo, "USDC")
    symbols = [r.token.symbol for r in scr._buy_options]
    assert "USDC" not in symbols and "ETH" in symbols

    pick(scr.sell_combo, "ETH")
    scr.amount_edit.setText("abc")
    scr._on_next()
    assert "tidak valid" in scr.form_err.text().lower() and scr.pages.currentIndex() == 0
    scr.amount_edit.setText("0.1")
    scr.slip_edit.setText("99")
    scr._on_next()
    assert "50%" in scr.form_err.text()
    scr.slip_edit.setText("0.5")
    scr._fill_max()                                                       # seluruh saldo native: tidak menyisakan gas
    scr._on_next()
    assert "biaya gas" in scr.form_err.text() and scr.pages.currentIndex() == 0
    scr.amount_edit.setText("5")
    scr._on_next()
    assert "tidak cukup" in scr.form_err.text()


def test_screen_no_pool_message(qapp, vault, wallet):
    scr = make_screen(vault, wallet, chain_(pools={}))
    pick(scr.sell_combo, "ETH")
    pick(scr.buy_combo, "LINK")
    scr.amount_edit.setText("0.01")
    scr._on_next()
    assert "kolam likuiditas" in scr.form_err.text() and scr.pages.currentIndex() == 0


def test_screen_stale_quote_is_refreshed_before_signing(qapp, vault, wallet):
    chain = chain_()
    scr = make_screen(vault, wallet, chain)
    pick(scr.sell_combo, "ETH")
    pick(scr.buy_combo, "USDC")
    scr.amount_edit.setText("0.001")
    scr._on_next()
    old = scr._plan
    object.__setattr__(old, "created_at", time.time() - swap.QUOTE_MAX_AGE - 5)
    scr.pw_field.edit.setText(PW)
    scr.swap_btn.click()
    assert chain.sent == [] and scr._plan is not old and scr.pages.currentIndex() == 1
    assert not scr.review_note.isHidden() and "diperbarui" in scr.review_note.text()
    scr.pw_field.edit.setText(PW)
    scr.swap_btn.click()
    assert len(chain.sent) == 1


def test_screen_back_and_close(qapp, vault, wallet):
    scr = make_screen(vault, wallet, chain_())
    pick(scr.sell_combo, "ETH")
    pick(scr.buy_combo, "USDC")
    scr.amount_edit.setText("0.001")
    scr._on_next()
    done = []
    scr.finished.connect(done.append)
    scr.go_back()
    assert scr.pages.currentIndex() == 0 and done == []
    scr.go_back()
    assert done == [0]


def test_screen_without_balance_shows_hint(qapp, vault, wallet):
    scr = make_screen(vault, wallet, chain_(), rows=[AssetRow(ETH, Decimal(0), None, None)])
    assert not scr._sell_rows and not hasattr(scr, "balance_lbl")          # hanya pesan + tombol Tutup


def test_lobby_trade_button(tmp_path, monkeypatch, qapp):
    from pywallet.avatars import AvatarStore
    from pywallet.db import Database
    from pywallet.ui.main_window import MainWindow
    from pywallet.ui.swap_screen import SwapScreen
    from PySide6.QtWidgets import QMessageBox

    from .fakes import FakeSendChain, install_standard
    from .test_send import FAST_KDF
    from pywallet.vault import Vault
    from pywallet.wallet_core import generate_mnemonic

    v = Vault(Database(tmp_path / "w.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    v.create_wallet("Utama", generate_mnemonic(), PW)
    fake = FakeHttp()
    fake.post_handlers[NET.rpc_urls[0]] = FakeSendChain(native_wei=3 * 10**18).handler
    install_standard(fake)
    win = MainWindow(v, service=PortfolioService(fake), avatar_store=AvatarStore(tmp_path / "av"), async_loading=False)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    wt.set_mode("mainnet")
    wt.swapRequested.emit()
    assert win.screens.screen is None and shown and "Sepolia" in shown[0]       # mainnet belum didukung: penjelasan
    wt.set_mode("testnet")
    wt.swapRequested.emit()
    assert isinstance(win.screens.screen, SwapScreen)
    win.screens.screen.back_btn.click()
    assert win.screens.screen is None
