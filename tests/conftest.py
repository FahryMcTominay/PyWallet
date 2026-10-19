"""Pengaturan bersama tes."""
import gc

import pytest


@pytest.fixture(autouse=True)
def cleanup_qt_widgets():
    """Hancurkan semua jendela/dialog yang dibuat sebuah tes selagi Qt masih hidup.

    Widget yang baru dibersihkan saat Python hendak berhenti bisa membuat proses crash (Qt sudah ditutup lebih
    dulu), padahal semua tes lulus."""
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is not None:
        for w in app.topLevelWidgets():
            w.close()
            w.deleteLater()
        app.processEvents()
    gc.collect()
