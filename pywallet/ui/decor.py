"""Motif dekoratif bergaya sketsa: telinga kucing, bintang, kucing kartun, dan pita besar.

Semua bentuk digambar dengan QPainter (tanpa file gambar) dan dirancang untuk dipakai pada opacity
rendah di latar belakang, sebagai aksen saja. Semuanya motif orisinal buatan sendiri.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from . import theme

# Hiasan latar bisa dimatikan pengguna (Profil -> Hiasan latar). Aksen kecil pada tombol tetap tampil.
ENABLED = True


def set_enabled(value: bool) -> None:
    global ENABLED
    ENABLED = bool(value)


def _c(hex_color: str, alpha: float) -> QColor:
    col = QColor(hex_color)
    col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


class _Xf:
    """Konteks transformasi: geser, putar, skala (opsional cermin horizontal)."""

    def __init__(self, p: QPainter, x: float = 0, y: float = 0, scale: float = 1.0,
                 rot: float = 0.0, flip: bool = False):
        self.p, self.x, self.y, self.s, self.rot, self.flip = p, x, y, scale, rot, flip

    def __enter__(self):
        self.p.save()
        self.p.translate(self.x, self.y)
        if self.rot:
            self.p.rotate(self.rot)
        self.p.scale(-self.s if self.flip else self.s, self.s)
        return self

    def __exit__(self, *_):
        self.p.restore()


def _pen(color: QColor, width: float, scale: float) -> QPen:
    return QPen(color, width / max(scale, 1e-6), Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def _sketch(p: QPainter, path: QPainterPath, color: str, alpha: float, width: float, scale: float,
            ghost: bool = True) -> None:
    """Goresan bergaya sketsa: satu goresan samar sedikit bergeser + satu goresan utama."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    if ghost:
        p.save()
        p.translate(0.9, -0.7)
        p.setPen(_pen(_c(color, alpha * 0.4), width * 0.8, scale))
        p.drawPath(path)
        p.restore()
    p.setPen(_pen(_c(color, alpha), width, scale))
    p.drawPath(path)


# ==========================================================================
# Telinga kucing
# ==========================================================================
def _ear_outline() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(-10, 0)
    path.quadTo(-11.5, -13, -1.5, -22)
    path.quadTo(8, -15, 10, 0)
    return path


def _ear_inner() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(-5, -1)
    path.quadTo(-5.5, -9, -1, -14)
    path.quadTo(3, -9, 5, -1)
    return path


def draw_ear(p: QPainter, x: float, y: float, size: float, rot: float, color: str, alpha: float,
             fill: str | None = None, fill_alpha: float = 0.0) -> None:
    """Satu telinga; (x, y) = titik tengah pangkal, `size` = lebar pangkal dalam piksel."""
    s = size / 20.0
    with _Xf(p, x, y, s, rot):
        outline = _ear_outline()
        if fill:
            closed = QPainterPath(outline)
            closed.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(fill, fill_alpha))
            p.drawPath(closed)
        _sketch(p, outline, color, alpha, 1.5, s)
        _sketch(p, _ear_inner(), color, alpha * 0.8, 1.2, s, ghost=False)


def draw_ears_on_circle(p: QPainter, rect: QRectF, size: float, color: str, alpha: float,
                        fill: str | None = None, fill_alpha: float = 0.0, spread: float = 40.0) -> None:
    """Sepasang telinga di tepi atas sebuah lingkaran/bulatan yang menempati `rect`."""
    cx, r = rect.center().x(), rect.width() / 2
    for sign in (-1, 1):
        th = math.radians(spread)
        ex = cx + sign * r * math.sin(th)
        ey = rect.top() + r - r * math.cos(th) + size * 0.12
        draw_ear(p, ex, ey, size, sign * spread * 0.85, color, alpha, fill, fill_alpha)


def draw_ear_pair(p: QPainter, cx: float, base_y: float, size: float, gap: float, color: str, alpha: float,
                  fill: str | None = None, fill_alpha: float = 0.0) -> None:
    """Sepasang telinga berdampingan di atas tepi datar (mengintip dari balik kartu)."""
    for sign in (-1, 1):
        draw_ear(p, cx + sign * gap / 2, base_y, size, sign * 12, color, alpha, fill, fill_alpha)


# ==========================================================================
# Bintang
# ==========================================================================
def star_polygon(cx: float, cy: float, r: float, inner: float = 0.46, rot: float = -90.0) -> QPolygonF:
    pts = []
    for i in range(10):
        ang = math.radians(rot + i * 36)
        rad = r if i % 2 == 0 else r * inner
        pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return QPolygonF(pts)


def draw_star(p: QPainter, cx: float, cy: float, r: float, color: str, alpha: float, rot: float = -90.0,
              outline_only: bool = False) -> None:
    p.save()
    if outline_only:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(color, alpha), max(1.0, r * 0.14), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(color, alpha))
    p.drawPolygon(star_polygon(cx, cy, r, rot=rot))
    p.restore()


def draw_sparkle(p: QPainter, cx: float, cy: float, r: float, color: str, alpha: float) -> None:
    """Kilau 4 sudut."""
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.quadTo(cx, cy, cx + r, cy)
    path.quadTo(cx, cy, cx, cy + r)
    path.quadTo(cx, cy, cx - r, cy)
    path.quadTo(cx, cy, cx, cy - r)
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(color, alpha))
    p.drawPath(path)
    p.restore()


# ==========================================================================
# Pita besar
# ==========================================================================
def _bow_loop() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(0.10, -0.06)
    path.cubicTo(0.30, -0.52, 0.80, -0.66, 0.98, -0.46)
    path.cubicTo(1.08, -0.20, 1.08, 0.20, 0.98, 0.46)
    path.cubicTo(0.80, 0.66, 0.30, 0.52, 0.10, 0.06)
    path.closeSubpath()
    return path


def _bow_tail(left: bool) -> QPainterPath:
    path = QPainterPath()
    pts = [(-0.10, 0.10), (-0.60, 1.00), (-0.44, 0.90), (-0.36, 1.06), (-0.04, 0.22)] if left else \
          [(0.10, 0.10), (0.52, 0.96), (0.38, 0.88), (0.28, 1.04), (0.04, 0.22)]
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)
    path.closeSubpath()
    return path


def draw_bow(p: QPainter, cx: float, cy: float, width: float, fill: str, fill_alpha: float,
             line: str, line_alpha: float, rot: float = 0.0) -> None:
    """Pita besar dengan dua gelungan, simpul, dan dua ekor. `width` = bentang total."""
    s = width / 2.2
    with _Xf(p, cx, cy, s, rot):
        shapes = [_bow_loop()]
        mirror = QPainterPath()
        for i in range(shapes[0].elementCount()):
            e = shapes[0].elementAt(i)
            if e.type == QPainterPath.ElementType.MoveToElement:
                mirror.moveTo(-e.x, e.y)
            elif e.type == QPainterPath.ElementType.LineToElement:
                mirror.lineTo(-e.x, e.y)
            elif e.type == QPainterPath.ElementType.CurveToElement:
                c1, c2 = shapes[0].elementAt(i), shapes[0].elementAt(i + 1)
                end = shapes[0].elementAt(i + 2)
                mirror.cubicTo(-c1.x, c1.y, -c2.x, c2.y, -end.x, end.y)
        mirror.closeSubpath()
        parts = [_bow_tail(True), _bow_tail(False), shapes[0], mirror]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(fill, fill_alpha))
        for part in parts:
            p.drawPath(part)
        for part in parts:
            _sketch(p, part, line, line_alpha, 1.3, s)
        # simpul
        knot = QPainterPath()
        knot.addRoundedRect(QRectF(-0.17, -0.22, 0.34, 0.44), 0.09, 0.09)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(fill, min(1.0, fill_alpha * 1.8)))
        p.drawPath(knot)
        _sketch(p, knot, line, line_alpha, 1.3, s)
        # lipatan kain
        for sign in (-1, 1):
            fold = QPainterPath()
            fold.moveTo(sign * 0.2, -0.04)
            fold.cubicTo(sign * 0.45, -0.22, sign * 0.7, -0.26, sign * 0.88, -0.16)
            _sketch(p, fold, line, line_alpha * 0.7, 1.0, s, ghost=False)


# ==========================================================================
# Kucing kartun (sketsa)
# ==========================================================================
def draw_cat(p: QPainter, x: float, y: float, width: float, color: str, alpha: float,
             full: bool = True, flip: bool = False) -> None:
    """Kucing duduk bergaya kartun. (x, y) = pojok kiri-atas; tinggi = 1,2 x lebar jika `full`."""
    s = width / 100.0
    with _Xf(p, x + (width if flip else 0), y, s, 0.0, flip):
        # telinga
        for pts in (((22, 34), (17, 12), (26, 5), (46, 14)), ((78, 34), (83, 12), (74, 5), (54, 14))):
            ear = QPainterPath()
            ear.moveTo(*pts[0])
            ear.quadTo(*pts[1], *pts[2])
            ear.lineTo(*pts[3])
            _sketch(p, ear, color, alpha, 1.7, s)
        for pts in (((27, 26), (25, 14), (30, 11)), ((73, 26), (75, 14), (70, 11))):
            inner = QPainterPath()
            inner.moveTo(*pts[0])
            inner.quadTo(*pts[1], *pts[2])
            _sketch(p, inner, color, alpha * 0.8, 1.3, s, ghost=False)
        # kepala
        head = QPainterPath()
        head.addEllipse(QRectF(20, 12, 60, 52))
        _sketch(p, head, color, alpha, 1.9, s)
        # mata (menyipit senang)
        for ex in (38, 62):
            eye = QPainterPath()
            eye.moveTo(ex - 6, 41)
            eye.quadTo(ex, 33, ex + 6, 41)
            _sketch(p, eye, color, alpha, 1.8, s, ghost=False)
        # hidung & mulut
        nose = QPainterPath()
        nose.moveTo(47, 46.5)
        nose.lineTo(53, 46.5)
        nose.lineTo(50, 50.5)
        nose.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(color, alpha))
        p.drawPath(nose)
        mouth = QPainterPath()
        mouth.moveTo(50, 50.5)
        mouth.lineTo(50, 54)
        mouth.moveTo(50, 54)
        mouth.quadTo(46, 58, 42.5, 54.5)
        mouth.moveTo(50, 54)
        mouth.quadTo(54, 58, 57.5, 54.5)
        _sketch(p, mouth, color, alpha, 1.5, s, ghost=False)
        # kumis
        for sign in (-1, 1):
            for dy, tipdy in ((-1, -4), (3, 3)):
                w = QPainterPath()
                w.moveTo(50 + sign * 21, 49 + dy)
                w.lineTo(50 + sign * 40, 49 + dy + tipdy)
                _sketch(p, w, color, alpha * 0.85, 1.3, s, ghost=False)
        if not full:
            return
        # badan
        body = QPainterPath()
        body.moveTo(33, 63)
        body.cubicTo(20, 82, 20, 104, 32, 114)
        body.lineTo(68, 114)
        body.cubicTo(80, 104, 80, 82, 67, 63)
        _sketch(p, body, color, alpha, 1.9, s)
        # kaki depan
        for px in (43, 57):
            paw = QPainterPath()
            paw.addEllipse(QRectF(px - 8, 109, 16, 9))
            _sketch(p, paw, color, alpha, 1.5, s, ghost=False)
        chest = QPainterPath()
        chest.moveTo(50, 72)
        chest.lineTo(50, 104)
        _sketch(p, chest, color, alpha * 0.6, 1.2, s, ghost=False)
        # ekor melingkar
        tail = QPainterPath()
        tail.moveTo(70, 110)
        tail.cubicTo(96, 114, 104, 92, 92, 78)
        tail.cubicTo(86, 71, 78, 76, 83, 83)
        _sketch(p, tail, color, alpha, 1.9, s)


# ==========================================================================
# Latar belakang halaman
# ==========================================================================
_STARS = {
    "login": [(0.12, 0.30, 5, "star"), (0.88, 0.18, 4, "sparkle"), (0.20, 0.62, 3.5, "sparkle"),
              (0.84, 0.50, 5.5, "star"), (0.08, 0.82, 4, "star"), (0.60, 0.86, 3, "sparkle")],
    "lobby": [(0.06, 0.47, 3.5, "sparkle"), (0.93, 0.56, 4.5, "star"), (0.12, 0.70, 4, "star"),
              (0.88, 0.80, 3, "sparkle"), (0.52, 0.64, 3, "sparkle")],
    "profile": [(0.92, 0.10, 4, "sparkle"), (0.07, 0.62, 4.5, "star"), (0.90, 0.58, 3.5, "sparkle"),
                (0.15, 0.86, 3, "sparkle")],
    "swap": [(0.18, 0.18, 4, "star"), (0.84, 0.26, 3.5, "sparkle"), (0.10, 0.74, 3.5, "sparkle"),
             (0.90, 0.80, 4.5, "star")],
}


def _scatter(p: QPainter, w: float, h: float, kind: str, alpha: float) -> None:
    for rx, ry, r, shape in _STARS.get(kind, []):
        if shape == "star":
            draw_star(p, rx * w, ry * h, r, theme.STAR, alpha * 1.1)
        else:
            draw_sparkle(p, rx * w, ry * h, r * 1.5, theme.TEXT, alpha)


def paint_backdrop(p: QPainter, w: float, h: float, kind: str) -> None:
    """Gambar motif latar (opacity rendah). Panggil setelah mengisi warna dasar."""
    if not ENABLED:
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind == "login":
        draw_bow(p, w * 0.86, h * 0.06, w * 0.82, theme.ACCENT_DEEP, 0.26, theme.ACCENT, 0.15, rot=12)
        draw_cat(p, w - 128, h - 104 * 1.2 - 70, 104, theme.TEXT, 0.17, full=True)
        _scatter(p, w, h, "login", 0.30)
    elif kind == "lobby":
        draw_bow(p, w * 0.95, h * 0.07, w * 0.78, theme.ACCENT_DEEP, 0.30, theme.ACCENT, 0.18, rot=14)
        draw_cat(p, w * 0.5 - 56, h - 112 * 1.2 - 22, 112, theme.TEXT, 0.15, full=True)
        _scatter(p, w, h, "lobby", 0.28)
    elif kind == "profile":
        draw_bow(p, w * 0.08, h * 0.60, w * 0.66, theme.ACCENT_DEEP, 0.26, theme.ACCENT, 0.16, rot=-16)
        draw_cat(p, w - 118, h - 96 * 1.2 - 56, 96, theme.TEXT, 0.14, full=True)
        _scatter(p, w, h, "profile", 0.28)
    elif kind == "swap":
        draw_bow(p, w * 0.5, h * 0.74, w * 0.86, theme.ACCENT_DEEP, 0.24, theme.ACCENT, 0.15, rot=3)
        _scatter(p, w, h, "swap", 0.28)
    p.restore()
