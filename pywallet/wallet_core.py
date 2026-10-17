"""Pembuatan dan pemulihan akun EVM dari seed phrase (BIP39/BIP44) atau private key."""
from __future__ import annotations

import re

from eth_account import Account
from eth_account.signers.local import LocalAccount

from .config import DEFAULT_DERIVATION_PATH

Account.enable_unaudited_hdwallet_features()

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class InvalidSecret(ValueError):
    """Seed phrase atau private key tidak valid (pesan aman, tanpa membocorkan isi)."""


def generate_mnemonic(num_words: int = 12) -> str:
    _, mnemonic = Account.create_with_mnemonic(num_words=num_words)
    return mnemonic


def normalize_mnemonic(text: str) -> str:
    return " ".join(text.lower().split())


def account_from_mnemonic(text: str, path: str = DEFAULT_DERIVATION_PATH) -> LocalAccount:
    phrase = normalize_mnemonic(text)
    count = len(phrase.split())
    if count not in (12, 24):
        raise InvalidSecret(f"Seed phrase harus 12 atau 24 kata (terdeteksi {count} kata).")
    try:
        return Account.from_mnemonic(phrase, account_path=path)
    except Exception as exc:  # kata tidak ada di daftar BIP39 / checksum salah
        raise InvalidSecret(
            "Seed phrase tidak valid. Periksa ejaan kata dan urutannya."
        ) from exc


def normalize_private_key(text: str) -> str:
    raw = text.strip()
    if raw[:2].lower() == "0x":
        raw = raw[2:]
    if not _HEX64.match(raw):
        raise InvalidSecret("Private key harus 64 karakter heksadesimal (boleh diawali 0x).")
    return "0x" + raw.lower()


def account_from_private_key(text: str) -> LocalAccount:
    key = normalize_private_key(text)
    try:
        return Account.from_key(key)
    except Exception as exc:
        raise InvalidSecret("Private key tidak valid.") from exc
