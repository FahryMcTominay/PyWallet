"""Konstanta dan lokasi data PyWallet."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PyWallet"
APP_VERSION = "0.10.1"

# Jeda tanpa master password: jika aplikasi terakhir aktif < 5 menit lalu,
# lobi bisa dibuka tanpa password. Aksi sensitif tetap meminta password.
GRACE_SECONDS = 5 * 60

MIN_PASSWORD_LENGTH = 8
MAX_WALLET_NAME_LENGTH = 32

SECRET_VIEW_TIMEOUT = 30        # detik, layar seed/private key menutup otomatis
CLIPBOARD_CLEAR_SECONDS = 30    # detik, clipboard dibersihkan setelah menyalin rahasia
HEARTBEAT_MS = 30_000           # catat "terakhir aktif" tiap 30 detik saat aplikasi terbuka

DEFAULT_DERIVATION_PATH = "m/44'/60'/0'/0/0"

# Daftar token mainnet yang diperluas (ETH di Base, USDT/USDC, dan koin populer lainnya).
# Ubah ke False untuk kembali ke tampilan ETH saja (kode dan tesnya tetap ada).
EXTENDED_TOKEN_LIST = True


def data_dir() -> Path:
    """Folder data aplikasi. Di Windows: %APPDATA%\\PyWallet."""
    override = os.environ.get("PYWALLET_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    else:
        base = Path.home() / ".pywallet"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "pywallet.db"


def avatars_dir() -> Path:
    return data_dir() / "avatars"


def assets_dir() -> Path:
    """Folder aset bawaan (logo, font). Mendukung aplikasi yang dibungkus PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "pywallet" / "assets"
    return Path(__file__).parent / "assets"
