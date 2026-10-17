"""Font bawaan aplikasi: Poppins (SIL Open Font License 1.1, lihat assets/fonts/OFL.txt).

Dipakai di halaman login/setup agar kesannya lebih ramah dan tidak kaku. Jika file font tidak
ditemukan, tampilan otomatis memakai font sistem.
"""
from __future__ import annotations

from PySide6.QtGui import QFontDatabase

from ..config import assets_dir
from . import theme

LOGIN_FAMILY = "Poppins"
_loaded = False


def load_fonts() -> bool:
    global _loaded
    ok = False
    for ttf in sorted((assets_dir() / "fonts").glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(ttf)) >= 0:
            ok = True
    _loaded = ok
    return ok


def login_stylesheet() -> str:
    """Stylesheet tingkat halaman: mengganti font keluarga untuk semua widget di halaman login."""
    return (
        f'QWidget {{ font-family: "{LOGIN_FAMILY}", {theme.FONT_STACK}; }}'
        f'QLabel#brand {{ font-size: 34px; font-weight: 700; }}'
        f'QLabel#loginTitle {{ font-size: 21px; font-weight: 600; color: {theme.TEXT_STRONG}; }}'
        f'QLabel#loginSub {{ font-size: 14px; color: {theme.MUTED}; }}'
        f'QLineEdit {{ padding: 12px 14px; font-size: 14px; }}'
        f'QPushButton#primary {{ padding: 13px 18px; font-size: 15px; font-weight: 600; }}'
    )
