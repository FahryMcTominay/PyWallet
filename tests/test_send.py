"""Kirim aset (tahap 4): validasi input, estimasi gas, tanda tangan, pengiriman, dan dialog."""
import os
import time
from decimal import Decimal

import pytest
from eth_account import Account

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pywallet import tx  # noqa: E402
from pywallet.db import Database  # noqa: E402
from pywallet.networks import NETWORKS  # noqa: E402
from pywallet.portfolio import AssetRow, PortfolioService  # noqa: E402
from pywallet.rpc import RpcClient  # noqa: E402
from pywallet.tokens import TOKENS  # noqa: E402
from pywallet.vault import InvalidPassword, Vault, VaultError  # noqa: E402
from pywallet.wallet_core import generate_mnemonic  # noqa: E402

from .fakes import FakeHttp, FakeSendChain  # noqa: E402

PW = "kata-sandi-kuat-1"
FAST_KDF = {"n": 2**10, "r": 8, "p": 1}
NET = NETWORKS["sepolia"]
ETH = TOKENS["sepolia"][0]
USDC = TOKENS["sepolia"][1]
TO = "0x" + "12" * 20
TO_CS = tx.normalize_recipient(TO)


def rpc_for(chain: FakeSendChain) -> RpcClient:
    fake = FakeHttp()
    fake.post_handlers[NET.rpc_urls[0]] = chain.handler
    return RpcClient(fake, NET.rpc_urls)


@pytest.fixture
def vault(tmp_path):
    v = Vault(Database(tmp_path / "t.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    return v


@pytest.fixture
def wallet(vault):
    return vault.create_wallet("Utama", generate_mnemonic(), PW)


# --------------------------------------------------------------------------
# Validasi input
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text,dec,expected", [
    ("1", 18, 10**18), ("0.5", 18, 5 * 10**17), ("0,25", 6, 250_000), (" 1.000001 ", 6, 1_000_001),
    ("0.000000000000000001", 18, 1),
])
def test_parse_amount_ok(text, dec, expected):
    assert tx.parse_amount(text, dec) == expected


@pytest.mark.parametrize("text,dec", [
    ("", 18), ("0", 18), ("-1", 18), ("abc", 18), ("1e5", 18), ("1.2.3", 18), ("1,000.5", 18),
    ("0.0000001", 6),     # lebih banyak desimal daripada yang didukung token
])
def test_parse_amount_rejects(text, dec):
    with pytest.raises(tx.TransferError):
        tx.parse_amount(text, dec)


def test_normalize_recipient():
    assert tx.normalize_recipient(" " + TO + " ") == "0x1212121212121212121212121212121212121212"
    good = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    assert tx.normalize_recipient(good) == good
    assert tx.normalize_recipient(good.lower()) == good
    for bad in ["", "0x123", "0x" + "g" * 40, "0x" + "0" * 40, "vitalik.eth",
                "0xdAC17F958D2ee523a2206206994597C13D831ec8"]:    # checksum salah
        with pytest.raises(tx.TransferError):
            tx.normalize_recipient(bad)


def test_encode_transfer():
    data = tx.encode_transfer(TO_CS, 1_000_000)
    assert data == "0xa9059cbb" + "0" * 24 + "12" * 20 + hex(1_000_000)[2:].rjust(64, "0")


# --------------------------------------------------------------------------
# prepare_transfer
# --------------------------------------------------------------------------
def prep(chain, token=ETH, amount=10**17, balance=10**18, send_max=False, to=TO_CS, sender="0x" + "aa" * 20):
    return tx.prepare_transfer(rpc_for(chain), NET, token, sender, to, amount, balance, send_max)


def test_prepare_native_eip1559():
    plan = prep(FakeSendChain())
    assert plan.eip1559 and plan.gas_limit == 21_000 and plan.nonce == 7 and plan.chain_id == NET.chain_id
    slow, normal, fast = (plan.fees[s].max_fee_per_gas for s in tx.SPEEDS)
    assert slow < normal < fast
    f = plan.tx_fields(tx.SPEED_NORMAL)
    assert f["type"] == 2 and f["to"] == TO_CS and f["value"] == 10**17 and f["data"] == "0x"
    assert f["maxPriorityFeePerGas"] <= f["maxFeePerGas"]
    assert plan.fee_wei(tx.SPEED_NORMAL) == 21_000 * f["maxFeePerGas"]


def test_prepare_legacy_network_uses_gas_price():
    plan = prep(FakeSendChain(base_fee=None))
    assert not plan.eip1559
    f = plan.tx_fields(tx.SPEED_FAST)
    assert "gasPrice" in f and "maxFeePerGas" not in f and "type" not in f


def test_prepare_token_transfer_builds_erc20_call():
    plan = prep(FakeSendChain(estimate_gas=60_000), token=USDC, amount=1_000_000, balance=5_000_000)
    f = plan.tx_fields(tx.SPEED_NORMAL)
    assert f["to"] == USDC.address and f["value"] == 0
    assert f["data"] == tx.encode_transfer(TO_CS, 1_000_000)
    assert plan.gas_limit == 72_000                        # estimasi + 20%


def test_prepare_rejects_wrong_chain_id():
    with pytest.raises(tx.TransferError, match="chain ID"):
        prep(FakeSendChain(chain_id=1))


def test_prepare_network_down():
    fake = FakeHttp()
    rpc = RpcClient(fake, NET.rpc_urls)
    with pytest.raises(tx.TransferError, match="terhubung"):
        tx.prepare_transfer(rpc, NET, ETH, "0x" + "aa" * 20, TO_CS, 1, 10)


def test_prepare_reports_estimate_revert_in_friendly_words():
    with pytest.raises(tx.TransferError, match="Kontrak menolak"):
        prep(FakeSendChain(estimate_error="execution reverted: ERC20: transfer amount exceeds balance"),
             token=USDC, amount=1_000_000, balance=5_000_000)


def test_prepare_blocks_self_send_and_token_contract_target():
    me = "0x" + "aa" * 20
    with pytest.raises(tx.TransferError, match="sendiri"):
        prep(FakeSendChain(), to=tx.normalize_recipient(me), sender=me)
    with pytest.raises(tx.TransferError, match="kontrak token"):
        prep(FakeSendChain(), token=USDC, amount=1, balance=10, to=USDC.address)


def test_prepare_warns_when_recipient_is_contract():
    plan = prep(FakeSendChain(codes=[TO_CS]))
    assert plan.warnings and "kontrak" in plan.warnings[0]


def test_token_transfer_needs_native_for_gas():
    with pytest.raises(tx.TransferError, match="koin native"):
        prep(FakeSendChain(native_wei=0), token=USDC, amount=1_000_000, balance=5_000_000)


def test_native_amount_plus_fee_must_fit_balance():
    with pytest.raises(tx.TransferError, match="biaya gas"):
        prep(FakeSendChain(native_wei=10**18), amount=10**18 - 1000, balance=10**18)


def test_send_max_native_subtracts_fee():
    plan = prep(FakeSendChain(), amount=10**18, balance=10**18, send_max=True)
    for speed in tx.SPEEDS:
        assert plan.final_amount(speed) + plan.fee_wei(speed) == 10**18
        assert plan.tx_fields(speed)["value"] == plan.final_amount(speed)
        plan.check_funds(speed)
    assert plan.final_amount(tx.SPEED_FAST) < plan.final_amount(tx.SPEED_SLOW)


def test_send_max_token_sends_full_token_balance():
    plan = prep(FakeSendChain(estimate_gas=60_000), token=USDC, amount=5_000_000, balance=5_000_000, send_max=True)
    assert plan.final_amount(tx.SPEED_NORMAL) == 5_000_000      # biaya gas dibayar dari koin native, bukan token


# --------------------------------------------------------------------------
# Tanda tangan & pengiriman
# --------------------------------------------------------------------------
def test_sign_transfer_recovers_wallet_address(vault, wallet):
    plan = prep(FakeSendChain(), sender=wallet.address)
    raw, tx_hash = vault.sign_transfer(wallet.id, PW, plan.tx_fields(tx.SPEED_NORMAL))
    assert raw.startswith("0x") and tx_hash.startswith("0x") and len(tx_hash) == 66
    assert Account.recover_transaction(raw) == wallet.address


def test_sign_transfer_requires_correct_password(vault, wallet):
    plan = prep(FakeSendChain(), sender=wallet.address)
    with pytest.raises(InvalidPassword):
        vault.sign_transfer(wallet.id, "salah-banget-1", plan.tx_fields(tx.SPEED_NORMAL))


def test_sign_transfer_works_with_imported_private_key(vault):
    acct = Account.create()
    w = vault.import_private_key("Kunci", acct.key.hex(), PW)
    plan = prep(FakeSendChain(), sender=w.address)
    raw, _ = vault.sign_transfer(w.id, PW, plan.tx_fields(tx.SPEED_SLOW))
    assert Account.recover_transaction(raw) == acct.address


def test_broadcast_and_receipt():
    chain = FakeSendChain()
    rpc = rpc_for(chain)
    assert tx.broadcast(rpc, "0xdeadbeef") == "0x" + "ab" * 32
    assert chain.sent == ["0xdeadbeef"]
    assert tx.fetch_receipt(rpc, "0x" + "ab" * 32) == tx.Receipt(True, 17)
    assert tx.fetch_receipt(rpc_for(FakeSendChain(receipt_status=0)), "0x1").success is False
    assert tx.fetch_receipt(rpc_for(FakeSendChain(receipt_status=None)), "0x1") is None


@pytest.mark.parametrize("raw,expect", [
    ("insufficient funds for gas * price + value", "tidak cukup"),
    ("nonce too low", "Nonce"),
    ("replacement transaction underpriced", "terlalu rendah"),
    ("already known", "sudah dikirim"),
])
def test_broadcast_errors_are_friendly(raw, expect):
    with pytest.raises(tx.TransferError, match=expect):
        tx.broadcast(rpc_for(FakeSendChain(send_error=raw)), "0x00")


def test_explorer_tx_url():
    assert tx.explorer_tx_url("sepolia", "0xabc") == "https://sepolia.etherscan.io/tx/0xabc"


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


def make_dialog(vault, wallet, chain, rows=None, qapp=None):
    from pywallet.ui.send_dialog import SendDialog
    fake = FakeHttp()
    fake.post_handlers[NET.rpc_urls[0]] = chain.handler
    service = PortfolioService(fake)
    rows = rows if rows is not None else [
        AssetRow(ETH, Decimal("1"), None, None),
        AssetRow(USDC, Decimal("5"), 1.0, None),
    ]
    dlg = SendDialog(vault, service, wallet, rows)
    dlg.run_in_thread = False
    return dlg


def test_dialog_full_flow_native(qapp, vault, wallet):
    chain = FakeSendChain()
    dlg = make_dialog(vault, wallet, chain)
    dlg.addr_edit.setText(TO)
    dlg.amount_edit.setText("0,25")
    dlg._on_next()
    assert dlg.pages.currentIndex() == 1
    assert TO_CS in dlg.summary_text() and "0.25 ETH" in dlg.summary_text() and "Sepolia" in dlg.summary_text()
    assert dlg.warn_box.isHidden()                       # testnet tanpa peringatan tambahan

    dlg.send_btn.click()                                 # tanpa password
    assert chain.sent == [] and not dlg.review_err.isHidden()
    dlg.pw_field.edit.setText("salah-banget-1")
    dlg.send_btn.click()
    assert chain.sent == [] and "salah" in dlg.review_err.text().lower()

    dlg.speed_buttons[tx.SPEED_FAST].click()
    dlg.pw_field.edit.setText(PW)
    dlg.send_btn.click()
    assert len(chain.sent) == 1 and dlg.sent_hash == "0x" + "ab" * 32
    signed = Account.recover_transaction(chain.sent[0])
    assert signed == wallet.address
    assert dlg.pages.currentIndex() == 2 and "Berhasil" in dlg.status_title.text()
    dlg.deleteLater()


def test_dialog_token_transfer_and_max(qapp, vault, wallet):
    chain = FakeSendChain(estimate_gas=60_000)
    dlg = make_dialog(vault, wallet, chain)
    dlg.asset_combo.setCurrentIndex(1)                   # USDC
    dlg.addr_edit.setText(TO)
    dlg.max_btn.click()
    assert dlg.amount_edit.text() == "5"
    dlg._on_next()
    assert "5 USDC" in dlg.summary_text() and "Total" not in dlg.summary_text()
    dlg.pw_field.edit.setText(PW)
    dlg.send_btn.click()
    assert len(chain.sent) == 1
    decoded = Account.recover_transaction(chain.sent[0])
    assert decoded == wallet.address
    dlg.deleteLater()


def test_dialog_validation_errors_stay_on_form(qapp, vault, wallet):
    dlg = make_dialog(vault, wallet, FakeSendChain())
    dlg.addr_edit.setText("0x123")
    dlg.amount_edit.setText("1")
    dlg._on_next()
    assert dlg.pages.currentIndex() == 0 and not dlg.form_err.isHidden()
    dlg.addr_edit.setText(TO)
    dlg.amount_edit.setText("2")                         # saldo hanya 1 ETH
    dlg._on_next()
    assert dlg.pages.currentIndex() == 0 and "tidak cukup" in dlg.form_err.text()
    dlg.amount_edit.setText("0")
    dlg._on_next()
    assert dlg.pages.currentIndex() == 0
    dlg.deleteLater()


def test_dialog_send_max_native_reduces_amount_with_speed(qapp, vault, wallet):
    dlg = make_dialog(vault, wallet, FakeSendChain())
    dlg.addr_edit.setText(TO)
    dlg.max_btn.click()
    dlg._on_next()
    slow = dlg._plan.final_amount(tx.SPEED_SLOW)
    dlg.speed_buttons[tx.SPEED_FAST].click()
    assert dlg._plan.final_amount(tx.SPEED_FAST) < slow
    assert dlg.send_btn.isEnabled()
    dlg.deleteLater()


def test_dialog_broadcast_failure_shows_message(qapp, vault, wallet):
    dlg = make_dialog(vault, wallet, FakeSendChain(send_error="nonce too low"))
    dlg.addr_edit.setText(TO)
    dlg.amount_edit.setText("0.1")
    dlg._on_next()
    dlg.pw_field.edit.setText(PW)
    dlg.send_btn.click()
    assert dlg.sent_hash is None and "gagal" in dlg.status_title.text().lower()
    assert "Nonce" in dlg.status_detail.text()
    dlg.deleteLater()


def test_dialog_without_balance_shows_hint(qapp, vault, wallet):
    dlg = make_dialog(vault, wallet, FakeSendChain(), rows=[AssetRow(ETH, Decimal("0"), None, None)])
    assert dlg.pages.currentIndex() == 0 and not hasattr(dlg, "balance_lbl")
    dlg.deleteLater()


def test_dialog_stale_plan_is_refreshed_before_signing(qapp, vault, wallet):
    chain = FakeSendChain()
    dlg = make_dialog(vault, wallet, chain)
    dlg.addr_edit.setText(TO)
    dlg.amount_edit.setText("0.1")
    dlg._on_next()
    old = dlg._plan
    chain.nonce = 9
    object.__setattr__(old, "created_at", time.time() - tx.PLAN_MAX_AGE - 5)
    dlg.pw_field.edit.setText(PW)
    dlg.send_btn.click()
    assert chain.sent == []                              # belum dikirim: pengguna harus meninjau ulang
    assert dlg._plan.nonce == 9 and not dlg.review_note.isHidden()
    dlg.pw_field.edit.setText(PW)
    dlg.send_btn.click()
    assert len(chain.sent) == 1
    dlg.deleteLater()


def test_vault_refuses_mismatched_key(vault, wallet):
    plan = prep(FakeSendChain(), sender=wallet.address)
    # Alamat yang tersimpan diubah paksa -> penandatanganan harus ditolak, bukan mengirim dari akun lain.
    with vault.db.conn:
        vault.db.conn.execute("UPDATE wallets SET address = ? WHERE id = ?", ("0x" + "11" * 20, wallet.id))
    with pytest.raises(VaultError):
        vault.sign_transfer(wallet.id, PW, plan.tx_fields(tx.SPEED_NORMAL))


# --------------------------------------------------------------------------
# Tombol Kirim di lobi
# --------------------------------------------------------------------------
def test_lobby_send_button_opens_dialog_with_loaded_balances(tmp_path, monkeypatch, qapp):
    from pywallet.avatars import AvatarStore
    from pywallet.ui.main_window import MainWindow
    from pywallet.ui.send_dialog import SendDialog

    from .fakes import install_standard

    v = Vault(Database(tmp_path / "w.db"))
    v.setup_master_password(PW, kdf=FAST_KDF)
    wallet = v.create_wallet("Utama", generate_mnemonic(), PW)
    chain = FakeSendChain(native_wei=3 * 10**18)
    fake = FakeHttp()
    fake.post_handlers[NET.rpc_urls[0]] = chain.handler
    install_standard(fake)
    win = MainWindow(v, service=PortfolioService(fake), avatar_store=AvatarStore(tmp_path / "av"),
                     async_loading=False)
    win.start()
    win._enter_app()
    wt = win.home.wallet_tab
    wt.set_mode("testnet")

    seen = {}

    def fake_exec(self):
        seen["rows"] = [r.token.symbol for r in self._rows]
        seen["wallet"] = self.wallet.id
        self.sent_hash = "0x" + "ab" * 32
        return 1

    monkeypatch.setattr(SendDialog, "exec", fake_exec)
    reloads = []
    monkeypatch.setattr(wt, "reload_tokens", lambda: reloads.append(1))
    wt.sendRequested.emit()
    assert seen == {"rows": ["ETH"], "wallet": wallet.id}    # hanya aset yang punya saldo
    assert reloads == [1]                                    # saldo dimuat ulang setelah terkirim
