"""Widget kecil yang dipakai ulang di banyak layar."""
from __future__ import annotations

import qrcode
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..config import CLIPBOARD_CLEAR_SECONDS
from . import icons, theme


# --------------------------------------------------------------------------
# Helper
# --------------------------------------------------------------------------
def label(text: str = "", name: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.Shape.HLine)
    return line


def copy_to_clipboard(text: str, sensitive: bool = False, anchor: QWidget | None = None) -> None:
    """Salin teks. Untuk data sensitif, clipboard dibersihkan otomatis setelah beberapa detik."""
    clipboard = QGuiApplication.clipboard()
    clipboard.setText(text)
    if sensitive:
        def _clear() -> None:
            if clipboard.text() == text:
                clipboard.clear()
        QTimer.singleShot(CLIPBOARD_CLEAR_SECONDS * 1000, _clear)
    if anchor is not None:
        msg = "Tersalin" + (f" (dihapus otomatis dalam {CLIPBOARD_CLEAR_SECONDS} dtk)" if sensitive else "")
        QToolTip.showText(anchor.mapToGlobal(anchor.rect().bottomLeft()), msg, anchor, anchor.rect(), 1800)


# --------------------------------------------------------------------------
# Input password dengan tombol tampil/sembunyi
# --------------------------------------------------------------------------
class PasswordField(QWidget):
    returnPressed = Signal()
    textChanged = Signal(str)

    def __init__(self, placeholder: str = "Password", parent: QWidget | None = None):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(self.returnPressed)
        self.edit.textChanged.connect(self.textChanged)
        self.toggle = QToolButton()
        self.toggle.setText("Tampilkan")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._on_toggle)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.toggle)
        self.setFocusProxy(self.edit)

    def _on_toggle(self, shown: bool) -> None:
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        self.toggle.setText("Sembunyikan" if shown else "Tampilkan")

    def text(self) -> str:
        return self.edit.text()

    def clear(self) -> None:
        self.edit.clear()


# --------------------------------------------------------------------------
# Avatar bundar dengan huruf pertama nama wallet
# --------------------------------------------------------------------------
class Avatar(QWidget):
    def __init__(self, text: str = "?", size: int = 36, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = (text or "?")[:1].upper()
        self._size = size
        self.setFixedSize(size, size)

    def set_text(self, text: str) -> None:
        self._text = (text or "?")[:1].upper()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.TEXT))
        p.drawEllipse(self.rect())
        p.setPen(QColor(theme.BG))
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(int(self._size * 0.45))
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


# --------------------------------------------------------------------------
# Tombol aksi bulat (Kirim / Terima / Trade)
# --------------------------------------------------------------------------
class CircleAction(QWidget):
    clicked = Signal()

    def __init__(self, icon_name: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.btn = QToolButton()
        self.btn.setIcon(icons.icon(icon_name, 26, theme.BG, 2.1))
        self.btn.setIconSize(QSize(26, 26))
        self.btn.setFixedSize(54, 54)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(
            f"QToolButton {{ background: {theme.TEXT}; border-radius: 27px; }}"
            f"QToolButton:hover {{ background: {theme.TEXT_HOVER}; }}"
            f"QToolButton:pressed {{ background: {theme.ACCENT}; }}"
        )
        self.btn.clicked.connect(self.clicked)
        self.caption = label(text)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.caption)


# --------------------------------------------------------------------------
# Tombol navigasi bawah
# --------------------------------------------------------------------------
class NavButton(QAbstractButton):
    def __init__(self, icon_name: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(62)

    def sizeHint(self) -> QSize:
        return QSize(90, 62)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.TEXT_STRONG) if self.isChecked() else QColor(theme.TEXT)
        if not self.isChecked():
            color.setAlpha(150)
        pm = icons.pixmap(self._icon_name, 24, color, 1.9)
        x = (self.width() - 24) // 2
        p.drawPixmap(x, 9, pm)
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setBold(self.isChecked())
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(0, 36, self.width(), 20), Qt.AlignmentFlag.AlignCenter, self.text())
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.TEXT))
            p.drawRoundedRect(QRectF((self.width() - 28) / 2, 0, 28, 3), 1.5, 1.5)


# --------------------------------------------------------------------------
# QR code (digambar langsung dari matriks, tanpa Pillow)
# --------------------------------------------------------------------------
class QRWidget(QWidget):
    def __init__(self, data: str, size: int = 220, parent: QWidget | None = None):
        super().__init__(parent)
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
        qr.add_data(data)
        qr.make(fit=True)
        self._matrix = qr.get_matrix()
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.TEXT_STRONG))
        p.drawRoundedRect(self.rect(), 14, 14)
        n = len(self._matrix)
        quiet = 16
        cell = (self.width() - 2 * quiet) / n
        p.setBrush(QColor(theme.BG))
        for r, row in enumerate(self._matrix):
            for c, on in enumerate(row):
                if on:
                    p.drawRect(QRectF(quiet + c * cell, quiet + r * cell, cell + 0.6, cell + 0.6))


# --------------------------------------------------------------------------
# Kartu bergaya (container dengan latar SURFACE)
# --------------------------------------------------------------------------
class Card(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
