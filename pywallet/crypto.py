"""Enkripsi rahasia wallet: scrypt (KDF) + AES-256-GCM.

Kunci tidak pernah disimpan. Setiap kali dibutuhkan, kunci diturunkan ulang
dari master password lalu dibuang.
"""
from __future__ import annotations

import os
import unicodedata

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Parameter scrypt bawaan (~32 MiB memori, sekitar 0.1 detik).
DEFAULT_KDF = {"n": 2**15, "r": 8, "p": 1}

KEY_LEN = 32
SALT_LEN = 16
NONCE_LEN = 12
_VERSION = b"\x01"


class DecryptionError(Exception):
    """Data rusak, dimodifikasi, atau kunci salah."""


def new_salt() -> bytes:
    return os.urandom(SALT_LEN)


def derive_key(password: str, salt: bytes, kdf: dict | None = None) -> bytes:
    params = kdf or DEFAULT_KDF
    normalized = unicodedata.normalize("NFKC", password).encode("utf-8")
    return Scrypt(
        salt=salt, length=KEY_LEN, n=params["n"], r=params["r"], p=params["p"]
    ).derive(normalized)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Format: versi(1) | nonce(12) | ciphertext+tag. `aad` mengikat data ke record-nya."""
    nonce = os.urandom(NONCE_LEN)
    return _VERSION + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < 1 + NONCE_LEN + 16 or blob[:1] != _VERSION:
        raise DecryptionError("Format data tidak dikenali.")
    nonce = blob[1 : 1 + NONCE_LEN]
    try:
        return AESGCM(key).decrypt(nonce, blob[1 + NONCE_LEN :], aad)
    except InvalidTag as exc:
        raise DecryptionError("Kunci salah atau data rusak.") from exc
