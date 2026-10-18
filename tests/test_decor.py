"""Motif latar bertema kucing/pita: dirender tanpa galat, dan bisa dimatikan lewat Profil."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from pywallet.ui import decor, theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def restore_flag():
    before = decor.ENABLED
    yield
    decor.set_enabled(before)


def _render(kind, w=460, h=840):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(theme.BG))
    p = QPainter(img)
    decor.paint_backdrop(p, w, h, kind)
    p.end()
    return img


@pytest.mark.parametrize("kind", ["login", "lobby", "profile", "swap"])
def test_backdrop_draws_something_but_not_everything(app, kind):
    decor.set_enabled(True)
    img = _render(kind)
    bg = QColor(theme.BG).rgb()
    changed = sum(1 for y in range(0, img.height(), 6) for x in range(0, img.width(), 6) if img.pixel(x, y) != bg)
    total = (img.height() // 6 + 1) * (img.width() // 6 + 1)
    assert 0.02 < changed / total < 0.6      # ada motif, tetapi tidak memenuhi seisi latar


def test_disabled_backdrop_leaves_background_untouched(app):
    decor.set_enabled(False)
    img = _render("lobby")
    bg = QColor(theme.BG).rgb()
    assert all(img.pixel(x, y) == bg for x in range(0, img.width(), 7) for y in range(0, img.height(), 7))


def _painted(draw, w=160, h=160):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p)
    p.end()
    return sum(1 for y in range(h) for x in range(w) if QColor.fromRgba(img.pixel(x, y)).alpha() > 0)


def test_doodle_ears_are_unfilled_lines(app):
    from PySide6.QtCore import QRectF
    n = _painted(lambda p: decor.draw_doodle_ears_on_circle(p, QRectF(30, 40, 100, 100), 12, "#ffffff", 1.0))
    assert 50 < n < 1500            # ada goresan, tetapi bukan bidang terisi
