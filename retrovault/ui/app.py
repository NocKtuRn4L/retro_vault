"""PySide6 application entry point for RetroVault."""

import sys
from importlib import resources

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main(window_mode=None):
    """Launch the RetroVault GUI.

    ``window_mode`` overrides the config-driven window-mode policy
    (``"desktop"`` | ``"fullscreen"`` | ``"kiosk"``). When ``None`` the mode is
    resolved from config, defaulting to ``"desktop"`` so normal PC/dev runs stay
    windowed. Callable with no args for backward compatibility.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("RetroVault")

    theme = resources.files("retrovault.ui").joinpath("theme.qss").read_text(encoding="utf-8")
    app.setStyleSheet(theme)

    window = MainWindow()
    effective = window_mode if window_mode is not None else window.config_data.get("window_mode", "desktop")
    window.apply_window_mode(effective)
    window.maybe_prompt_first_run_setup()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
