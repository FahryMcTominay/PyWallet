"""Titik masuk PyWallet. Jalankan:  python main.py"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pywallet.config import APP_NAME, db_path
from pywallet.db import Database
from pywallet.ui import fonts, icons, theme
from pywallet.ui.main_window import MainWindow
from pywallet.vault import Vault


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    fonts.load_fonts()
    app.setStyleSheet(theme.build_qss())
    app.setWindowIcon(icons.app_icon())

    vault = Vault(Database(db_path()))
    window = MainWindow(vault)
    window.show()
    window.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
