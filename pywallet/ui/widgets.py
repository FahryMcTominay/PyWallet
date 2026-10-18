"""Widget yang dipakai ulang di banyak layar."""
from __future__ import annotations

import qrcode
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
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

from ..avatars import AvatarStore
from ..config import CLIPBOARD_CLEAR_SECONDS, assets_dir
from ..networks import NETWORKS
from ..tokens import Token
from ..vault import WalletRecord
from . import decor, icons, theme


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


def styled(lb: QLabel, color: str, size: int = 14, weight: int = 400) -> QLabel:
    lb.setStyleSheet(f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent;")
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


_eth_pixmap: QPixmap | None = None


def eth_logo() -> QPixmap:
    """Logo Ethereum (PNG transparan di assets/eth.png)."""
    global _eth_pixmap
    if _eth_pixmap is None:
        _eth_pixmap = QPixmap(str(assets_dir() / "eth.png"))
    return _eth_pixmap


def _draw_pixmap_smooth(p: QPainter, pm: QPixmap, target: QRectF) -> None:
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawPixmap(target, pm, QRectF(pm.rect()))


# --------------------------------------------------------------------------
# Latar halaman dengan cahaya lembut (dipakai halaman login/onboarding)
# --------------------------------------------------------------------------
class GlowPage(QWidget):
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        w, h = self.width(), self.height()
        g1 = QRadialGradient(QPointF(w * 0.12, h * 0.08), max(w, h) * 0.75)
        c1 = QColor(theme.ACCENT_DEEP)
        c1.setAlpha(170)
        g1.setColorAt(0.0, c1)
        g1.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g1)
        g2 = QRadialGradient(QPointF(w * 0.95, h * 0.98), max(w, h) * 0.8)
        c2 = QColor(theme.SURFACE)
        c2.setAlpha(210)
        g2.setColorAt(0.0, c2)
        g2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g2)
        decor.paint_backdrop(p, w, h, "login")


# --------------------------------------------------------------------------
# Kartu bergradasi (kartu saldo, kartu profil)
# --------------------------------------------------------------------------
class GradientCard(QFrame):
    def __init__(self, parent: QWidget | None = None, radius: int = 22):
        super().__init__(parent)
        self._radius = radius

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor(theme.ACCENT_DEEP))
        grad.setColorAt(1.0, QColor(theme.SURFACE))
        p.fillPath(path, grad)
        p.setClipPath(path)
        glow = QColor(theme.ACCENT)
        glow.setAlpha(34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(rect.right() - 20, rect.top() + 10), rect.height() * 0.55, rect.height() * 0.55)
        glow.setAlpha(20)
        p.setBrush(glow)
        p.drawEllipse(QPointF(rect.right() - rect.width() * 0.35, rect.bottom() + 20), rect.height() * 0.5, rect.height() * 0.5)
        p.setClipping(False)
        pen = QPen(QColor(219, 208, 204, 50), 1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


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
# Avatar wallet: foto kustom, atau gradien unik per alamat + huruf pertama nama
# --------------------------------------------------------------------------
_PRESETS = [
    ("#2C6A78", "#DBD0CC"),
    ("#02596C", "#43B8C9"),
    ("#3A4044", "#9AA6A8"),
    ("#185565", "#86C9D3"),
    ("#4E5A5E", "#DBD0CC"),
    ("#0B7285", "#A5E3EC"),
    ("#8C5A44", "#F0D6C4"),
    ("#5E7F86", "#E6EEF0"),
]


def avatar_colors(address: str) -> tuple[str, str]:
    try:
        idx = int(address[2:10], 16)
    except (ValueError, IndexError):
        idx = 0
    return _PRESETS[idx % len(_PRESETS)]


class Avatar(QWidget):
    clicked = Signal()

    def __init__(self, size: int = 36, badge: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self._text = "?"
        self._colors = _PRESETS[0]
        self._pix: QPixmap | None = None
        self._badge = badge
        self.setFixedSize(size, size)
        if badge:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Ganti foto profil")

    def set_wallet(self, wallet: WalletRecord | None, store: AvatarStore | None) -> None:
        self._pix = None
        if wallet is None:
            self._text, self._colors = "?", _PRESETS[0]
        else:
            self._text = (wallet.name or "?")[:1].upper()
            self._colors = avatar_colors(wallet.address)
            path = store.path(wallet.avatar) if store else None
            if path is not None:
                pm = QPixmap(str(path))
                if not pm.isNull():
                    dpr = 2.0
                    side = int(self._size * dpr)
                    self._pix = pm.scaled(
                        side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        self.update()

    @property
    def has_photo(self) -> bool:
        return self._pix is not None

    def mousePressEvent(self, event) -> None:
        if self._badge and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        disc = QRectF(0, 0, s, s)
        if self._badge:
            disc = QRectF(0, 0, s - 2, s - 2)
        clip = QPainterPath()
        clip.addEllipse(disc)
        p.save()
        p.setClipPath(clip)
        if self._pix is not None:
            _draw_pixmap_smooth(p, self._pix, disc)
        else:
            grad = QLinearGradient(disc.topLeft(), disc.bottomRight())
            grad.setColorAt(0.0, QColor(self._colors[0]))
            grad.setColorAt(1.0, QColor(self._colors[1]))
            p.fillRect(disc, grad)
        p.restore()
        if self._pix is None:
            p.setPen(QColor(theme.TEXT_STRONG))
            font = QFont(self.font())
            font.setBold(True)
            font.setPixelSize(int(s * 0.44))
            p.setFont(font)
            p.drawText(disc, Qt.AlignmentFlag.AlignCenter, self._text)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(disc.adjusted(0.5, 0.5, -0.5, -0.5))
        if self._badge:
            d = max(22, int(s * 0.3))
            r = QRectF(s - d - 1, s - d - 1, d, d)
            p.setPen(QPen(QColor(theme.BG), 2))
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(r)
            ic = icons.pixmap("camera", int(d * 0.62), theme.BG, 2.2)
            p.drawPixmap(int(r.x() + d * 0.19), int(r.y() + d * 0.19), ic)


# --------------------------------------------------------------------------
# Ikon token: logo Ethereum / huruf pada lencana warna + lencana jaringan
# --------------------------------------------------------------------------
class TokenIcon(QWidget):
    def __init__(self, token: Token, size: int = 40, parent: QWidget | None = None):
        super().__init__(parent)
        self.token = token
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        disc = QRectF(0, 0, s, s)
        t = self.token
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.color))
        p.drawEllipse(disc)
        if t.is_native:
            pad = s * 0.22
            _draw_pixmap_smooth(p, eth_logo(), QRectF(pad, pad, s - 2 * pad, s - 2 * pad))
        else:
            p.setPen(QColor("#FFFFFF"))
            font = QFont(self.font())
            font.setBold(True)
            font.setPixelSize(int(s * 0.46))
            p.setFont(font)
            p.drawText(disc, Qt.AlignmentFlag.AlignCenter, t.glyph or t.symbol[:1])
        net = NETWORKS[t.network]
        if t.network != "ethereum":
            d = s * 0.42
            r = QRectF(s - d + 2, s - d + 2, d, d)
            p.setPen(QPen(QColor(theme.SURFACE), 2))
            p.setBrush(QColor(net.badge_color))
            p.drawEllipse(r)
            p.setPen(QColor("#FFFFFF"))
            font = QFont(self.font())
            font.setBold(True)
            font.setPixelSize(int(d * 0.6))
            p.setFont(font)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, net.badge_text)


# --------------------------------------------------------------------------
# Grafik mini (sparkline)
# --------------------------------------------------------------------------
class Sparkline(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._values: list[float] = []
        self.setFixedSize(92, 38)

    def set_values(self, values: list[float]) -> None:
        self._values = list(values)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        v = self._values
        if len(v) < 2:
            pen = QPen(QColor(210, 193, 182, 70), 1.5, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(2, h / 2), QPointF(w - 2, h / 2))
            return
        lo, hi = min(v), max(v)
        span = (hi - lo) or 1.0
        pts = [
            QPointF(2 + i * (w - 4) / (len(v) - 1), h - 4 - (x - lo) / span * (h - 8)) for i, x in enumerate(v)
        ]
        color = QColor(theme.SUCCESS if v[-1] >= v[0] else theme.DANGER)
        fill = QPainterPath(pts[0])
        for pt in pts[1:]:
            fill.lineTo(pt)
        fill.lineTo(QPointF(pts[-1].x(), h))
        fill.lineTo(QPointF(pts[0].x(), h))
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        top = QColor(color)
        top.setAlpha(70)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        p.fillPath(fill, grad)
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        p.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line)


# --------------------------------------------------------------------------
# Tombol aksi bulat (Kirim / Terima / Trade)
# --------------------------------------------------------------------------
class CircleAction(QWidget):
    clicked = Signal()

    def __init__(self, icon_name: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.btn = QToolButton()
        self.btn.setIcon(icons.icon(icon_name, 24, theme.BG, 2.1))
        self.btn.setIconSize(QSize(24, 24))
        self.btn.setFixedSize(52, 52)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(
            f"QToolButton {{ background: {theme.ACCENT}; border-radius: 26px; }}"
            f"QToolButton:hover {{ background: {theme.ACCENT_HOVER}; }}"
            f"QToolButton:pressed {{ background: {theme.ACCENT_PRESSED}; }}"
        )
        self.btn.clicked.connect(self.clicked)
        self.caption = label(text)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 0)   # ruang untuk telinga kecil di atas tombol
        lay.setSpacing(6)
        lay.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.caption)

    def paintEvent(self, _event) -> None:
        """Aksen kecil: sepasang telinga kucing bergaya sketsa yang mengintip dari balik tombol."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = self.btn.geometry()
        decor.draw_ears_on_circle(
            p, QRectF(g), 17, theme.TEXT, 0.85, fill=theme.ACCENT, fill_alpha=1.0, spread=40
        )


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
        color = QColor(theme.ACCENT_HOVER) if self.isChecked() else QColor(theme.TEXT)
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
            p.setBrush(QColor(theme.ACCENT))
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
