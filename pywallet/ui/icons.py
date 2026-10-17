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


def app_icon() -> QIcon:
    """Ikon aplikasi: dompet beige pada kotak biru tua."""
    from . import theme

    size = 128
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.SURFACE))
    p.drawRoundedRect(QRectF(0, 0, size, size), 28, 28)
    p.scale(size / 32, size / 32)
    p.translate(4, 4)
    p.scale(1.0, 1.0)
    pen = QPen(QColor(theme.TEXT), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    draw_icon(p, "wallet")
    p.end()
    return QIcon(pm)
