"""Ikon vektor sederhana yang digambar dengan QPainter (tanpa file gambar)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)


def _poly(p: QPainter, *pts: tuple[float, float]) -> None:
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))


def draw_icon(p: QPainter, name: str) -> None:
    """Menggambar ikon pada kanvas 24x24 (pena dan kuas sudah diatur pemanggil)."""
    if name == "send":
        p.drawLine(QPointF(12, 19), QPointF(12, 5))
        _poly(p, (6, 11), (12, 5), (18, 11))
    elif name == "receive":
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        _poly(p, (6, 13), (12, 19), (18, 13))
    elif name == "swap":
        p.drawLine(QPointF(5, 8), QPointF(19, 8))
        _poly(p, (15, 4), (19, 8), (15, 12))
        p.drawLine(QPointF(19, 16), QPointF(5, 16))
        _poly(p, (9, 12), (5, 16), (9, 20))
    elif name == "copy":
        p.drawRoundedRect(QRectF(9, 9, 11, 11), 2, 2)
        _poly(p, (9, 15), (4, 15), (4, 4), (15, 4), (15, 9))
    elif name == "chevron":
        _poly(p, (6, 9), (12, 15), (18, 9))
    elif name == "wallet":
        p.drawRoundedRect(QRectF(3, 6, 18, 13), 3, 3)
        _poly(p, (3, 10), (21, 10))
        old_brush = p.brush()
        p.setBrush(p.pen().color())
        p.drawEllipse(QPointF(16.5, 14.5), 1.1, 1.1)
        p.setBrush(old_brush)
    elif name == "profile":
        p.drawEllipse(QPointF(12, 8), 4, 4)
        path = QPainterPath()
        path.moveTo(4, 21)
        path.cubicTo(4, 16, 8, 14, 12, 14)
        path.cubicTo(16, 14, 20, 16, 20, 21)
        p.drawPath(path)
    elif name == "plus":
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "check":
        _poly(p, (5, 12.5), (10, 17.5), (19, 7))
    elif name == "camera":
        p.drawRoundedRect(QRectF(3, 7, 18, 13), 3, 3)
        _poly(p, (8, 7), (9.5, 4.5), (14.5, 4.5), (16, 7))
        p.drawEllipse(QPointF(12, 13.5), 3.3, 3.3)
    elif name == "refresh":
        p.drawArc(QRectF(4.5, 4.5, 15, 15), 40 * 16, 260 * 16)
        _poly(p, (18.5, 3.5), (18.8, 8.2), (14.2, 8.5))
    elif name == "shield":
        path = QPainterPath()
        path.moveTo(12, 3)
        path.lineTo(20, 6)
        path.lineTo(20, 12)
        path.cubicTo(20, 16.5, 16.5, 19.8, 12, 21)
        path.cubicTo(7.5, 19.8, 4, 16.5, 4, 12)
        path.lineTo(4, 6)
        path.closeSubpath()
        p.drawPath(path)
        _poly(p, (8.8, 12), (11, 14.2), (15.2, 9.8))
    elif name == "lock":
        p.drawRoundedRect(QRectF(5, 11, 14, 10), 2.5, 2.5)
        path = QPainterPath()
        path.moveTo(8, 11)
        path.lineTo(8, 8)
        path.arcTo(QRectF(8, 3, 8, 10), 180, -180)
        path.lineTo(16, 11)
        p.drawPath(path)


def pixmap(name: str, size: int, color: str | QColor, stroke: float = 1.9, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24)
    pen = QPen(QColor(color), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    draw_icon(p, name)
    p.end()
    return pm


def icon(name: str, size: int, color: str | QColor, stroke: float = 1.9) -> QIcon:
    return QIcon(pixmap(name, size, color, stroke))


def dot_icon(color: str | QColor, size: int = 10, dpr: float = 2.0) -> QIcon:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


def app_icon() -> QIcon:
    """Ikon aplikasi: dompet pada kotak biru-teal, dengan sepasang telinga kucing kecil di atasnya."""
    from . import decor, theme

    size = 128
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    decor.draw_ear_pair(p, size / 2, 40, 30, 62, theme.ACCENT, 1.0, fill=theme.SURFACE, fill_alpha=1.0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.SURFACE))
    p.drawRoundedRect(QRectF(6, 26, size - 12, size - 32), 28, 28)
    p.setPen(QPen(QColor(theme.ACCENT), 3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(7.5, 27.5, size - 15, size - 35), 27, 27)
    p.save()
    p.translate(0, 12)
    p.scale(size / 32, size / 32)
    p.translate(4, 3)
    pen = QPen(QColor(theme.TEXT_STRONG), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    draw_icon(p, "wallet")
    p.restore()
    p.end()
    return QIcon(pm)
