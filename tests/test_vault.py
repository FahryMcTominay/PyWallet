import sqlite3

import pytest

from pywallet import wallet_core
from pywallet.config import GRACE_SECONDS
from pywallet.db import SCHEMA_VERSION, Database
from pywallet.vault import (
    SECRET_MNEMONIC,
    SECRET_PRIVATE_KEY,
    DuplicateWallet,
    InvalidPassword,
    Vault,
    VaultError,
    WalletNotFound,
)
from pywallet.wallet_core import InvalidSecret

FAST_KDF = {"n": 2**10, "r": 8, "p": 1}  # cepat untuk test

# Vektor uji standar (Hardhat/Anvil): akun #0
TEST_MNEMONIC = "test test test test test test test test test test test junk"
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
TEST_PRIVKEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
PW = "kata-sandi-kuat-123"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def vault(tmp_path, clock):
    v = Vault(Database(tmp_path / "t.db"), clock=clock)
    v.setup_master_password(PW, kdf=FAST_KDF)
    return v


# --- master password ------------------------------------------------------
def test_setup_and_verify(vault):
    assert vault.is_initialized()
    assert vault.verify_password(PW)
    assert not vault.verify_password("salah-banget")


def test_setup_rejects_short_password(tmp_path):
    v = Vault(Database(tmp_path / "x.db"))
    with pytest.raises(VaultError):
        v.setup_master_password("pendek", kdf=FAST_KDF)
    assert not v.is_initialized()


def test_setup_only_once(vault):
    with pytest.raises(VaultError):
        vault.setup_master_password("password-lain-123", kdf=FAST_KDF)


# --- create / import ------------------------------------------------------
def test_known_vector_from_mnemonic():
    assert wallet_core.account_from_mnemonic(TEST_MNEMONIC).address == TEST_ADDRESS
    assert wallet_core.account_from_private_key(TEST_PRIVKEY).address == TEST_ADDRESS


def test_generate_mnemonic_is_12_valid_words():
    phrase = wallet_core.generate_mnemonic()
    assert len(phrase.split()) == 12
    wallet_core.account_from_mnemonic(phrase)  # tidak error


def test_create_wallet(vault):
    phrase = wallet_core.generate_mnemonic()
    w = vault.create_wallet("Utama", phrase, PW)
    assert w.name == "Utama"
    assert w.secret_type == SECRET_MNEMONIC
    assert w.address == wallet_core.account_from_mnemonic(phrase).address
    assert vault.get_active_wallet().id == w.id


def test_import_mnemonic_normalizes_input(vault):
    messy = "  TEST test  test test test test test test test test test   JUNK \n"
    w = vault.import_mnemonic("Hardhat", messy, PW)
    assert w.address == TEST_ADDRESS


def test_import_private_key_with_and_without_prefix(vault):
    w = vault.import_private_key("PK", TEST_PRIVKEY[2:].upper(), PW)
    assert w.address == TEST_ADDRESS
    assert w.secret_type == SECRET_PRIVATE_KEY
    assert w.derivation_path is None


@pytest.mark.parametrize(
    "bad",
    ["", "bukan seed", "test " * 11 + "test", "a" * 20],
)
def test_import_invalid_mnemonic(vault, bad):
    with pytest.raises(InvalidSecret):
        vault.import_mnemonic("X", bad, PW)
    assert vault.list_wallets() == []


@pytest.mark.parametrize("bad", ["", "0x1234", "zz" * 32, "0x" + "0" * 64])
def test_import_invalid_private_key(vault, bad):
    with pytest.raises(InvalidSecret):
        vault.import_private_key("X", bad, PW)


def test_wrong_password_blocks_create_and_import(vault):
    with pytest.raises(InvalidPassword):
        vault.import_mnemonic("A", TEST_MNEMONIC, "salah-banget")
    with pytest.raises(InvalidPassword):
        vault.create_wallet("B", wallet_core.generate_mnemonic(), "salah-banget")
    assert vault.list_wallets() == []


def test_duplicate_address_across_secret_types(vault):
    vault.import_mnemonic("Satu", TEST_MNEMONIC, PW)
    with pytest.raises(DuplicateWallet, match="Satu"):
        vault.import_private_key("Dua", TEST_PRIVKEY, PW)


def test_duplicate_name_is_case_insensitive(vault):
    vault.import_mnemonic("Utama", TEST_MNEMONIC, PW)
    with pytest.raises(DuplicateWallet):
        vault.create_wallet("utama", wallet_core.generate_mnemonic(), PW)


@pytest.mark.parametrize("bad", ["", "   ", "x" * 33, "a\x00b"])
def test_invalid_names(vault, bad):
    with pytest.raises(VaultError):
        vault.import_mnemonic(bad, TEST_MNEMONIC, PW)


# --- rename ---------------------------------------------------------------
def test_rename(vault):
    w = vault.import_mnemonic("Lama", TEST_MNEMONIC, PW)
    renamed = vault.rename_wallet(w.id, "  Baru   Banget ")
    assert renamed.name == "Baru Banget"
    assert renamed.address == w.address


def test_rename_to_own_name_other_case_ok_but_clash_rejected(vault):
    a = vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    b = vault.create_wallet("B", wallet_core.generate_mnemonic(), PW)
    assert vault.rename_wallet(a.id, "a").name == "a"
    with pytest.raises(DuplicateWallet):
        vault.rename_wallet(b.id, "A")


def test_rename_missing(vault):
    with pytest.raises(WalletNotFound):
        vault.rename_wallet(999, "X")


# --- reveal ---------------------------------------------------------------
def test_reveal_mnemonic_and_private_key(vault):
    a = vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    secret = vault.reveal_secret(a.id, PW)
    assert secret.kind == SECRET_MNEMONIC and secret.value == TEST_MNEMONIC

    pk = wallet_core.generate_mnemonic()
    acct = wallet_core.account_from_mnemonic(pk)
    b = vault.import_private_key("B", acct.key.hex(), PW)
    secret = vault.reveal_secret(b.id, PW)
    assert secret.kind == SECRET_PRIVATE_KEY
    assert wallet_core.account_from_private_key(secret.value).address == acct.address


def test_reveal_wrong_password(vault):
    a = vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    with pytest.raises(InvalidPassword):
        vault.reveal_secret(a.id, "salah-banget")


def test_secret_is_not_plaintext_in_db(vault, tmp_path):
    vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    vault.import_private_key("B", wallet_core.account_from_mnemonic(
        wallet_core.generate_mnemonic()).key.hex(), PW)
    vault.db.conn.commit()
    raw = (tmp_path / "t.db").read_bytes()
    assert b"test test test" not in raw
    assert b"junk" not in raw


def test_ciphertext_bound_to_address(vault):
    """Menukar blob terenkripsi antar-wallet harus gagal (AAD = alamat)."""
    a = vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    b = vault.create_wallet("B", wallet_core.generate_mnemonic(), PW)
    conn = vault.db.conn
    blob_a = conn.execute("SELECT secret_enc FROM wallets WHERE id=?", (a.id,)).fetchone()[0]
    with conn:
        conn.execute("UPDATE wallets SET secret_enc=? WHERE id=?", (blob_a, b.id))
    with pytest.raises(VaultError):
        vault.reveal_secret(b.id, PW)


# --- delete ---------------------------------------------------------------
def test_delete_requires_password_and_can_reimport(vault):
    a = vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    with pytest.raises(InvalidPassword):
        vault.delete_wallet(a.id, "salah-banget")
    assert len(vault.list_wallets()) == 1

    vault.delete_wallet(a.id, PW)
    assert vault.list_wallets() == []
    assert vault.get_active_wallet() is None

    # bisa diimpor kembali dengan seed phrase yang sama -> alamat sama
    again = vault.import_mnemonic("A lagi", TEST_MNEMONIC, PW)
    assert again.address == a.address


def test_delete_moves_active_wallet(vault):
    a = vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    b = vault.create_wallet("B", wallet_core.generate_mnemonic(), PW)
    assert vault.get_active_wallet().id == b.id
    vault.delete_wallet(b.id, PW)
    assert vault.get_active_wallet().id == a.id


def test_set_active_wallet(vault):
    a = vault.import_mnemonic("A", TEST_MNEMONIC, PW)
    vault.create_wallet("B", wallet_core.generate_mnemonic(), PW)
    vault.set_active_wallet(a.id)
    assert vault.get_active_wallet().id == a.id


def test_suggest_name(vault):
    assert vault.suggest_name() == "Wallet 1"
    vault.import_mnemonic("Wallet 1", TEST_MNEMONIC, PW)
    assert vault.suggest_name() == "Wallet 2"


# --- jeda 5 menit -----------------------------------------------------------
def test_grace_window(vault, clock):
    assert not vault.within_grace()          # belum pernah aktif
    vault.touch()
    clock.t += GRACE_SECONDS - 1
    assert vault.within_grace()              # < 5 menit
    clock.t += 2
    assert not vault.within_grace()          # >= 5 menit


def test_lock_now_and_clock_rollback(vault, clock):
    vault.touch()
    vault.lock_now()
    assert not vault.within_grace()
    vault.touch()
    clock.t -= 3600                          # jam mundur -> jangan percaya
    assert not vault.within_grace()


def test_persists_across_reopen(tmp_path):
    path = tmp_path / "p.db"
    v1 = Vault(Database(path))
    v1.setup_master_password(PW, kdf=FAST_KDF)
    v1.import_mnemonic("A", TEST_MNEMONIC, PW)
    v1.db.close()

    v2 = Vault(Database(path))
    assert v2.is_initialized()
    assert [w.name for w in v2.list_wallets()] == ["A"]
    assert v2.reveal_secret(v2.list_wallets()[0].id, PW).value == TEST_MNEMONIC
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
