"""Vault: logika inti PyWallet (tanpa UI).

CRUD wallet + master password + jeda 5 menit.

Dua tingkat akses:
  * Data publik (nama, alamat) disimpan tanpa enkripsi -> lobi bisa dibuka tanpa
    password selama masih dalam jeda.
  * Rahasia (seed phrase / private key) selalu terenkripsi. Membuat, mengimpor,
    melihat rahasia, dan menghapus wallet SELALU meminta master password.
"""
from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable

from . import crypto, wallet_core
from .config import (
    DEFAULT_DERIVATION_PATH,
    GRACE_SECONDS,
    MAX_WALLET_NAME_LENGTH,
    MIN_PASSWORD_LENGTH,
)
from .crypto import DecryptionError
from .db import Database

SECRET_MNEMONIC = "mnemonic"
SECRET_PRIVATE_KEY = "private_key"

_VERIFIER_PLAINTEXT = b"pywallet-verifier-ok"
_VERIFIER_AAD = b"pywallet:verifier"


class VaultError(Exception):
    """Galat yang pesannya aman ditampilkan ke pengguna."""


class InvalidPassword(VaultError):
    pass


class DuplicateWallet(VaultError):
    pass


class WalletNotFound(VaultError):
    pass


@dataclass(frozen=True)
class WalletRecord:
    id: int
    name: str
    address: str
    secret_type: str
    derivation_path: str | None
    created_at: str
    avatar: str | None = None   # nama file foto profil kustom (None = avatar bawaan)

    @property
    def short_address(self) -> str:
        return f"{self.address[:6]}…{self.address[-4:]}"


@dataclass(frozen=True)
class RevealedSecret:
    kind: str   # SECRET_MNEMONIC | SECRET_PRIVATE_KEY
    value: str


def _aad(address: str) -> bytes:
    return f"pywallet:v1:{address}".encode()


def validate_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise VaultError("Nama wallet tidak boleh kosong.")
    if len(cleaned) > MAX_WALLET_NAME_LENGTH:
        raise VaultError(f"Nama wallet maksimal {MAX_WALLET_NAME_LENGTH} karakter.")
    if any(unicodedata.category(ch).startswith("C") for ch in cleaned):
        raise VaultError("Nama wallet mengandung karakter yang tidak diizinkan.")
    return cleaned


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise VaultError(f"Password minimal {MIN_PASSWORD_LENGTH} karakter.")


class Vault:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time):
        self.db = db
        self._clock = clock

    # ------------------------------------------------------------------
    # Master password
    # ------------------------------------------------------------------
    def is_initialized(self) -> bool:
        return self.db.get_setting("verifier") is not None

    def setup_master_password(self, password: str, kdf: dict | None = None) -> None:
        if self.is_initialized():
            raise VaultError("Master password sudah dibuat.")
        validate_new_password(password)
        params = kdf or crypto.DEFAULT_KDF
        salt = crypto.new_salt()
        key = crypto.derive_key(password, salt, params)
        verifier = crypto.encrypt(key, _VERIFIER_PLAINTEXT, _VERIFIER_AAD)
        self.db.set_setting("kdf_params", json.dumps(params))
        self.db.set_setting("kdf_salt", salt.hex())
        self.db.set_setting("verifier", verifier.hex())

    def _key_for(self, password: str) -> bytes:
        """Turunkan kunci dari password dan pastikan benar. Kunci tidak disimpan."""
        if not self.is_initialized():
            raise VaultError("Master password belum dibuat.")
        params = json.loads(self.db.get_setting("kdf_params"))
        salt = bytes.fromhex(self.db.get_setting("kdf_salt"))
        key = crypto.derive_key(password, salt, params)
        try:
            crypto.decrypt(key, bytes.fromhex(self.db.get_setting("verifier")), _VERIFIER_AAD)
        except DecryptionError as exc:
            raise InvalidPassword("Password salah.") from exc
        return key

    def verify_password(self, password: str) -> bool:
        try:
            self._key_for(password)
            return True
        except InvalidPassword:
            return False

    # ------------------------------------------------------------------
    # Jeda 5 menit
    # ------------------------------------------------------------------
    def touch(self) -> None:
        """Catat bahwa aplikasi sedang aktif (dipanggil berkala dan saat ditutup)."""
        self.db.set_setting("last_active", str(int(self._clock())))

    def lock_now(self) -> None:
        """Hapus jeda: pembukaan berikutnya wajib memakai password."""
        self.db.set_setting("last_active", "0")

    def within_grace(self) -> bool:
        raw = self.db.get_setting("last_active")
        if not raw:
            return False
        elapsed = self._clock() - int(raw)
        return 0 <= elapsed < GRACE_SECONDS

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    @staticmethod
    def _record(row) -> WalletRecord:
        return WalletRecord(
            id=row["id"],
            name=row["name"],
            address=row["address"],
            secret_type=row["secret_type"],
            derivation_path=row["derivation_path"],
            created_at=row["created_at"],
            avatar=row["avatar"],
        )

    _COLUMNS = "id, name, address, secret_type, derivation_path, created_at, avatar"

    def list_wallets(self) -> list[WalletRecord]:
        rows = self.db.conn.execute(f"SELECT {self._COLUMNS} FROM wallets ORDER BY id").fetchall()
        return [self._record(r) for r in rows]

    def get_wallet(self, wallet_id: int) -> WalletRecord:
        row = self.db.conn.execute(
            f"SELECT {self._COLUMNS} FROM wallets WHERE id = ?", (wallet_id,)
        ).fetchone()
        if row is None:
            raise WalletNotFound("Wallet tidak ditemukan.")
        return self._record(row)

    def suggest_name(self) -> str:
        existing = {w.name.lower() for w in self.list_wallets()}
        n = len(existing) + 1
        while f"wallet {n}" in existing:
            n += 1
        return f"Wallet {n}"

    def get_active_wallet(self) -> WalletRecord | None:
        wallets = self.list_wallets()
        if not wallets:
            return None
        raw = self.db.get_setting("active_wallet_id")
        if raw:
            for w in wallets:
                if w.id == int(raw):
                    return w
        return wallets[0]

    def set_active_wallet(self, wallet_id: int) -> None:
        self.get_wallet(wallet_id)  # pastikan ada
        self.db.set_setting("active_wallet_id", str(wallet_id))

    # ------------------------------------------------------------------
    # Create / Import
    # ------------------------------------------------------------------
    def _add_wallet(
        self,
        name: str,
        address: str,
        secret_type: str,
        secret: str,
        path: str | None,
        password: str,
    ) -> WalletRecord:
        name = validate_name(name)
        key = self._key_for(password)  # InvalidPassword jika salah

        if self.db.conn.execute("SELECT 1 FROM wallets WHERE address = ?", (address,)).fetchone():
            existing = self.db.conn.execute(
                "SELECT name FROM wallets WHERE address = ?", (address,)
            ).fetchone()["name"]
            raise DuplicateWallet(f"Wallet ini sudah ada di aplikasi dengan nama “{existing}”.")
        if self.db.conn.execute("SELECT 1 FROM wallets WHERE name = ?", (name,)).fetchone():
            raise DuplicateWallet(f"Nama “{name}” sudah dipakai wallet lain.")

        blob = crypto.encrypt(key, secret.encode(), _aad(address))
        with self.db.conn:
            cur = self.db.conn.execute(
                "INSERT INTO wallets (name, address, secret_type, secret_enc, derivation_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, address, secret_type, blob, path),
            )
        self.set_active_wallet(cur.lastrowid)
        return self.get_wallet(cur.lastrowid)

    def create_wallet(self, name: str, mnemonic: str, password: str) -> WalletRecord:
        """Simpan wallet baru dari mnemonic yang sudah dibuat (dan diverifikasi) oleh UI."""
        account = wallet_core.account_from_mnemonic(mnemonic)
        return self._add_wallet(
            name,
            account.address,
            SECRET_MNEMONIC,
            wallet_core.normalize_mnemonic(mnemonic),
            DEFAULT_DERIVATION_PATH,
            password,
        )

    def import_mnemonic(self, name: str, phrase: str, password: str) -> WalletRecord:
        account = wallet_core.account_from_mnemonic(phrase)
        return self._add_wallet(
            name,
            account.address,
            SECRET_MNEMONIC,
            wallet_core.normalize_mnemonic(phrase),
            DEFAULT_DERIVATION_PATH,
            password,
        )

    def import_private_key(self, name: str, private_key: str, password: str) -> WalletRecord:
        account = wallet_core.account_from_private_key(private_key)
        return self._add_wallet(
            name,
            account.address,
            SECRET_PRIVATE_KEY,
            wallet_core.normalize_private_key(private_key),
            None,
            password,
        )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def rename_wallet(self, wallet_id: int, new_name: str) -> WalletRecord:
        new_name = validate_name(new_name)
        self.get_wallet(wallet_id)
        clash = self.db.conn.execute(
            "SELECT 1 FROM wallets WHERE name = ? AND id != ?", (new_name, wallet_id)
        ).fetchone()
        if clash:
            raise DuplicateWallet(f"Nama “{new_name}” sudah dipakai wallet lain.")
        with self.db.conn:
            self.db.conn.execute("UPDATE wallets SET name = ? WHERE id = ?", (new_name, wallet_id))
        return self.get_wallet(wallet_id)

    def set_avatar(self, wallet_id: int, filename: str | None) -> WalletRecord:
        """Simpan nama file foto profil (None = kembali ke avatar bawaan)."""
        self.get_wallet(wallet_id)
        with self.db.conn:
            self.db.conn.execute("UPDATE wallets SET avatar = ? WHERE id = ?", (filename, wallet_id))
        return self.get_wallet(wallet_id)

    # ------------------------------------------------------------------
    # Preferensi tampilan (bukan data sensitif)
    # ------------------------------------------------------------------
    def get_pref(self, key: str, default: str | None = None) -> str | None:
        return self.db.get_setting(f"pref:{key}", default)

    def set_pref(self, key: str, value: str) -> None:
        self.db.set_setting(f"pref:{key}", value)

    # ------------------------------------------------------------------
    # Sensitif: lihat rahasia & hapus (selalu butuh password)
    # ------------------------------------------------------------------
    def reveal_secret(self, wallet_id: int, password: str) -> RevealedSecret:
        record = self.get_wallet(wallet_id)
        key = self._key_for(password)
        row = self.db.conn.execute(
            "SELECT secret_enc FROM wallets WHERE id = ?", (wallet_id,)
        ).fetchone()
        try:
            plain = crypto.decrypt(key, bytes(row["secret_enc"]), _aad(record.address))
        except DecryptionError as exc:
            raise VaultError("Data wallet rusak dan tidak bisa dibuka.") from exc
        return RevealedSecret(kind=record.secret_type, value=plain.decode())

    def delete_wallet(self, wallet_id: int, password: str) -> None:
        """Hapus wallet dari aplikasi. Dana tetap aman di blockchain dan bisa
        dipulihkan lagi lewat seed phrase / private key."""
        self.get_wallet(wallet_id)
        self._key_for(password)
        with self.db.conn:
            self.db.conn.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))
        active = self.db.get_setting("active_wallet_id")
        if active and int(active) == wallet_id:
            remaining = self.list_wallets()
            if remaining:
                self.db.set_setting("active_wallet_id", str(remaining[0].id))
            else:
                self.db.set_setting("active_wallet_id", "")
