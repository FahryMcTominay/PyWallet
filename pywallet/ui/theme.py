"""Palette dan stylesheet (QSS) PyWallet.

Tema bernuansa kucing dengan palette yang diambil dari gambar referensi pengguna:
  abu-abu gelap (baju)       -> BG
  biru tua kehijauan (pita)  -> SURFACE / ACCENT_DEEP
  teal (pita utama)          -> ACCENT
  abu-abu pucat (rambut)     -> TEXT
Warna lain (garis halus, bahaya, sukses, bintang) hanya pelengkap agar keterbacaan terjaga.
"""
from __future__ import annotations

# --- Palette inti -------------------------------------------------------------
BG = "#1D2124"            # latar utama: abu-abu gelap
SURFACE = "#10414E"       # kartu, panel: biru tua kehijauan (gelap)
ACCENT = "#43B8C9"        # aksen utama & tombol utama: teal
ACCENT_DEEP = "#02596C"   # biru tua kehijauan pekat (gradasi kartu, pita dekoratif)
TEXT = "#DBD0CC"          # teks: abu-abu pucat hangat

# --- Turunan -----------------------------------------------------------------------
SURFACE_HI = "#185565"    # hover pada permukaan
LINE = "#2C6A78"          # garis & bingkai halus
TEXT_STRONG = "#F6F1EE"
ACCENT_HOVER = "#5FCBDB"
ACCENT_PRESSED = "#2E9EAF"
DISABLED_BG = "#3A4044"
DANGER = "#F08C7C"
SUCCESS = "#86DDA0"
STAR = "#C47A55"          # tembaga hangat, khusus motif bintang kecil
MUTED_HEX = "#9AA6A8"


def rgba(hex_color: str, alpha: int) -> str:
    """'#RRGGBB' + alpha 0..255 -> string rgba() untuk QSS."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


MUTED = rgba(TEXT, 190)

FONT_STACK = '"Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif'


def build_qss() -> str:
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#root {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#title    {{ font-size: 22px; font-weight: 700; color: {TEXT_STRONG}; }}
QLabel#heading  {{ font-size: 17px; font-weight: 700; color: {TEXT_STRONG}; }}
QLabel#brand    {{ font-size: 30px; font-weight: 800; color: {TEXT_STRONG}; letter-spacing: 1px; }}
QLabel#muted    {{ color: {MUTED}; }}
QLabel#small    {{ color: {MUTED}; font-size: 12px; }}
QLabel#error    {{ color: {DANGER}; font-size: 13px; }}
QLabel#balance  {{ font-size: 40px; font-weight: 700; color: {TEXT_STRONG}; }}
QLabel#mono     {{ font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; }}
QLabel#chip     {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
                   padding: 4px 10px; font-size: 12px; color: {TEXT_STRONG}; }}
QLabel#warnbox  {{ background: {rgba(DANGER, 36)}; border: 1px solid {DANGER};
                   border-radius: 12px; padding: 12px; color: {TEXT_STRONG}; }}
QLabel#infobox  {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
                   padding: 12px; }}
QLabel#word     {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px;
                   padding: 9px 10px; color: {TEXT_STRONG}; font-weight: 600; }}
QLabel#secret   {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
                   padding: 14px; color: {TEXT_STRONG};
                   font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; }}

QFrame#card {{ background: {SURFACE}; border-radius: 16px; }}
QFrame#divider {{ background: {LINE}; max-height: 1px; min-height: 1px; }}
QFrame#navbar {{ background: {SURFACE}; border-top: 1px solid {LINE}; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
    padding: 11px 18px; color: {TEXT_STRONG};
}}
QPushButton:hover {{ background: {SURFACE_HI}; }}
QPushButton:pressed {{ background: {BG}; }}
QPushButton:disabled {{ color: {MUTED}; background: {SURFACE}; border-color: {SURFACE}; }}
QPushButton#primary {{
    background: {ACCENT}; color: {BG}; border: none; font-weight: 700;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: {DISABLED_BG}; color: {MUTED}; }}
QPushButton#danger {{ color: {DANGER}; border-color: {DANGER}; background: transparent; }}
QPushButton#danger:hover {{ background: {rgba(DANGER, 40)}; }}
QPushButton#dangerSolid {{ background: {DANGER}; color: {BG}; border: none; font-weight: 700; }}
QPushButton#dangerSolid:disabled {{ background: {DISABLED_BG}; color: {MUTED}; }}
QPushButton#flat {{ background: transparent; border: none; padding: 6px 8px; }}
QPushButton#flat:hover {{ background: {SURFACE}; }}
QPushButton#link {{ background: transparent; border: none; color: {TEXT}; text-decoration: underline;
                    padding: 4px; }}
QPushButton#menuRow {{ text-align: left; padding: 14px 16px; border-radius: 14px; }}
QPushButton#menuRowDanger {{ text-align: left; padding: 14px 16px; border-radius: 14px;
                             color: {DANGER}; border-color: {SURFACE}; }}
QPushButton#menuRowDanger:hover {{ background: {rgba(DANGER, 40)}; }}
QPushButton#pill {{ border-radius: 12px; padding: 4px 12px; font-size: 12px; background: {rgba(BG, 120)};
                    border: 1px solid {rgba(TEXT, 70)}; color: {TEXT_STRONG}; }}
QPushButton#pill:hover {{ background: {rgba(BG, 200)}; }}
QPushButton#pill:checked {{ background: {ACCENT}; color: {BG}; border-color: {ACCENT}; font-weight: 700; }}
QPushButton#modeChip {{ border-radius: 15px; padding: 6px 12px 6px 10px; font-size: 12px; background: {SURFACE};
                        border: 1px solid {LINE}; color: {TEXT_STRONG}; }}
QPushButton#modeChip:hover {{ background: {SURFACE_HI}; }}
QPushButton#segment {{ border-radius: 10px; padding: 9px 14px; background: transparent;
                       border: 1px solid {LINE}; }}
QPushButton#segment:checked {{ background: {ACCENT}; color: {BG}; border-color: {ACCENT}; font-weight: 700; }}

QToolButton {{ background: transparent; border: none; border-radius: 10px; padding: 6px; }}
QToolButton:hover {{ background: {SURFACE}; }}

QLineEdit, QPlainTextEdit {{
    background: {BG}; border: 1px solid {LINE}; border-radius: 10px;
    padding: 10px 12px; color: {TEXT_STRONG};
    selection-background-color: {ACCENT_DEEP}; selection-color: {TEXT_STRONG};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:disabled {{ color: {MUTED}; }}

QCheckBox {{ spacing: 10px; color: {TEXT}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
                        border: 1px solid {LINE}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QMenu {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 9px 22px 9px 14px; border-radius: 6px; color: {TEXT_STRONG}; }}
QMenu::item:selected {{ background: {SURFACE_HI}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 6px 8px; }}

QToolTip {{ background: {SURFACE}; color: {TEXT_STRONG}; border: 1px solid {LINE}; padding: 5px 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QMessageBox {{ background: {BG}; }}
"""
