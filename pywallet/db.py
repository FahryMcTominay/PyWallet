"""Database SQLite lokal.

Hanya menyimpan data milik aplikasi: pengaturan dan wallet (nama, alamat, rahasia
terenkripsi). Saldo dan riwayat transaksi tetap berada di blockchain.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

SCHEMA_VERSION = 3


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        is_new = self.path == ":memory:" or not os.path.exists(self.path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        # Saat baris dihapus, isinya ditimpa (bukan hanya ditandai kosong).
        self.conn.execute("PRAGMA secure_delete = ON")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        if is_new and self.path != ":memory:" and sys.platform != "win32":
            os.chmod(self.path, 0o600)

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self.conn.executescript(
                """
                CREATE TABLE settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE wallets (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    address         TEXT NOT NULL UNIQUE,
                    secret_type     TEXT NOT NULL CHECK (secret_type IN ('mnemonic', 'private_key')),
                    secret_enc      BLOB NOT NULL,
                    derivation_path TEXT,
                    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                );
                """
            )
            self.conn.execute("PRAGMA user_version = 1")
            self.conn.commit()
        if version < 2:
            # v2: foto profil kustom (nama file di folder avatars, bukan path penuh)
            self.conn.execute("ALTER TABLE wallets ADD COLUMN avatar TEXT")
            self.conn.execute("PRAGMA user_version = 2")
            self.conn.commit()

        if version < 3:
            # v3: token yang ditambahkan pengguna lewat contract address
            self.conn.executescript(
                """
                CREATE TABLE custom_tokens (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    network    TEXT NOT NULL,
                    address    TEXT NOT NULL,
                    symbol     TEXT NOT NULL,
                    name       TEXT NOT NULL,
                    decimals   INTEGER NOT NULL CHECK (decimals BETWEEN 0 AND 36),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    UNIQUE (network, address)
                );
                """
            )
            self.conn.execute("PRAGMA user_version = 3")
            self.conn.commit()

    # --- pengaturan -------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def close(self) -> None:
        self.conn.close()
