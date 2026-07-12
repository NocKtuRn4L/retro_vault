"""PySide6 application entry point for RetroVault."""

import sys
from importlib import resources

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RetroVault")

    theme = resources.files("retrovault.ui").joinpath("theme.qss").read_text(encoding="utf-8")
    app.setStyleSheet(theme)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
