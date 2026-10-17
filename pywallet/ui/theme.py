"""Palette dan stylesheet (QSS) PyWallet.

Empat warna dasar dari palette pengguna; warna fungsional (bahaya/sukses) dan
turunan teks ditambahkan hanya untuk keterbacaan.
"""
from __future__ import annotations

# Palette utama
BG = "#1B3C53"        # latar utama
SURFACE = "#234C6A"   # kartu, panel
ACCENT = "#456882"    # tombol sekunder, garis, elemen aktif
TEXT = "#D2C1B6"      # teks dan tombol utama

# Turunan / fungsional
TEXT_STRONG = "#F5EEE9"
MUTED = "rgba(210, 193, 182, 150)"
MUTED_HEX = "#9FA9AE"
DANGER = "#F09A8A"
SUCCESS = "#8FD3B6"
TEXT_HOVER = "#E2D5CC"

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
QLabel#chip     {{ background: {SURFACE}; border: 1px solid {ACCENT}; border-radius: 12px;
                   padding: 4px 10px; font-size: 12px; color: {TEXT_STRONG}; }}
QLabel#warnbox  {{ background: rgba(240, 154, 138, 36); border: 1px solid {DANGER};
                   border-radius: 12px; padding: 12px; color: {TEXT_STRONG}; }}
QLabel#infobox  {{ background: {SURFACE}; border: 1px solid {ACCENT}; border-radius: 12px;
                   padding: 12px; }}
QLabel#word     {{ background: {SURFACE}; border: 1px solid {ACCENT}; border-radius: 10px;
                   padding: 9px 10px; color: {TEXT_STRONG}; font-weight: 600; }}
QLabel#secret   {{ background: {SURFACE}; border: 1px solid {ACCENT}; border-radius: 12px;
                   padding: 14px; color: {TEXT_STRONG};
                   font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace; }}

QFrame#card {{ background: {SURFACE}; border-radius: 16px; }}
QFrame#divider {{ background: {ACCENT}; max-height: 1px; min-height: 1px; }}
QFrame#navbar {{ background: {SURFACE}; border-top: 1px solid {ACCENT}; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {ACCENT}; border-radius: 12px;
    padding: 11px 18px; color: {TEXT_STRONG};
}}
QPushButton:hover {{ background: {ACCENT}; }}
QPushButton:pressed {{ background: {BG}; }}
QPushButton:disabled {{ color: {MUTED}; background: {SURFACE}; border-color: {SURFACE}; }}
QPushButton#primary {{
    background: {TEXT}; color: {BG}; border: none; font-weight: 700;
}}
QPushButton#primary:hover {{ background: {TEXT_HOVER}; }}
QPushButton#primary:disabled {{ background: {ACCENT}; color: {MUTED}; }}
QPushButton#danger {{ color: {DANGER}; border-color: {DANGER}; background: transparent; }}
QPushButton#danger:hover {{ background: rgba(240, 154, 138, 40); }}
QPushButton#dangerSolid {{ background: {DANGER}; color: {BG}; border: none; font-weight: 700; }}
QPushButton#dangerSolid:disabled {{ background: {ACCENT}; color: {MUTED}; }}
QPushButton#flat {{ background: transparent; border: none; padding: 6px 8px; }}
QPushButton#flat:hover {{ background: {SURFACE}; }}
QPushButton#link {{ background: transparent; border: none; color: {TEXT}; text-decoration: underline;
                    padding: 4px; }}
QPushButton#menuRow {{ text-align: left; padding: 14px 16px; border-radius: 14px; }}
QPushButton#menuRowDanger {{ text-align: left; padding: 14px 16px; border-radius: 14px;
                             color: {DANGER}; border-color: {SURFACE}; }}
QPushButton#menuRowDanger:hover {{ background: rgba(240, 154, 138, 40); }}
QPushButton#segment {{ border-radius: 10px; padding: 9px 14px; background: transparent;
                       border: 1px solid {ACCENT}; }}
QPushButton#segment:checked {{ background: {TEXT}; color: {BG}; border-color: {TEXT}; font-weight: 700; }}

QToolButton {{ background: transparent; border: none; border-radius: 10px; padding: 6px; }}
QToolButton:hover {{ background: {SURFACE}; }}

QLineEdit, QPlainTextEdit {{
    background: {BG}; border: 1px solid {ACCENT}; border-radius: 10px;
    padding: 10px 12px; color: {TEXT_STRONG};
    selection-background-color: {ACCENT}; selection-color: {TEXT_STRONG};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {TEXT}; }}
QLineEdit:disabled {{ color: {MUTED}; }}

QCheckBox {{ spacing: 10px; color: {TEXT}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
                        border: 1px solid {ACCENT}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {TEXT}; border-color: {TEXT}; }}

QMenu {{ background: {SURFACE}; border: 1px solid {ACCENT}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 9px 22px 9px 14px; border-radius: 6px; color: {TEXT_STRONG}; }}
QMenu::item:selected {{ background: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {ACCENT}; margin: 6px 8px; }}

QToolTip {{ background: {SURFACE}; color: {TEXT_STRONG}; border: 1px solid {ACCENT}; padding: 5px 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {ACCENT}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QMessageBox {{ background: {BG}; }}
"""
