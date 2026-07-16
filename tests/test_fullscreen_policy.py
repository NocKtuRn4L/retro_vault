"""Headless tests for the PR7 cross-platform window-mode / fullscreen policy."""

import os
import unittest
from unittest import mock

from retrovault.core.config import migrate_config

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.input.backend import NullBackend
    from retrovault.ui import main_window as mw
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


FAKE_LIBRARY = [
    {"name": "Alpha", "system": "nes", "ext": ".nes", "path": "/roms/alpha.nes"},
    {"name": "Bravo", "system": "snes", "ext": ".sfc", "path": "/roms/bravo.sfc"},
]


class WindowModeConfigTests(unittest.TestCase):
    def test_default_window_mode_is_desktop(self):
        self.assertEqual(migrate_config({})["window_mode"], "desktop")

    def test_window_mode_override_round_trips(self):
        self.assertEqual(migrate_config({"window_mode": "kiosk"})["window_mode"], "kiosk")

    def test_window_mode_fullscreen_round_trips(self):
        self.assertEqual(migrate_config({"window_mode": "fullscreen"})["window_mode"], "fullscreen")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ApplyWindowModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        with (
            mock.patch.object(mw, "load_library", return_value=list(FAKE_LIBRARY)),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            return MainWindow()

    def test_fullscreen_mode_sets_fullscreen(self):
        window = self._make_window()
        try:
            window.apply_window_mode("fullscreen")
            self.assertTrue(window.isFullScreen())
            self.assertEqual(window._window_mode, "fullscreen")
            self.assertFalse(window._kiosk)
        finally:
            window.close()

    def test_desktop_mode_is_not_fullscreen(self):
        window = self._make_window()
        try:
            window.apply_window_mode("fullscreen")
            window.apply_window_mode("desktop")
            self.assertFalse(window.isFullScreen())
            self.assertEqual(window._window_mode, "desktop")
            self.assertFalse(window._kiosk)
        finally:
            window.close()

    def test_kiosk_mode_is_frameless_fullscreen(self):
        window = self._make_window()
        try:
            window.apply_window_mode("kiosk")
            self.assertTrue(window._kiosk)
            self.assertTrue(window.isFullScreen())
            self.assertEqual(window._window_mode, "kiosk")
        finally:
            window.close()

    def test_apply_window_mode_resolves_from_config(self):
        window = self._make_window()
        try:
            window.config_data["window_mode"] = "fullscreen"
            window.apply_window_mode()  # no arg -> resolve from config
            self.assertTrue(window.isFullScreen())
            self.assertEqual(window._window_mode, "fullscreen")
        finally:
            window.close()

    def test_restore_foreground_runs_and_keeps_fullscreen(self):
        window = self._make_window()
        try:
            window.apply_window_mode("fullscreen")
            window.restore_foreground()  # must not raise
            self.assertTrue(window.isFullScreen())
        finally:
            window.close()

    def test_restore_foreground_in_desktop_does_not_fullscreen(self):
        window = self._make_window()
        try:
            window.apply_window_mode("desktop")
            window.restore_foreground()  # must not raise
            self.assertFalse(window.isFullScreen())
        finally:
            window.close()


class KioskFlagParsingTests(unittest.TestCase):
    def test_kiosk_flag_forces_kiosk_mode(self):
        import retrovault.ui.app as app_module

        captured = {}

        def stub(window_mode=None):
            captured["window_mode"] = window_mode

        with mock.patch.object(app_module, "main", stub):
            from retrovault import __main__ as entry

            entry.main(["--kiosk"])

        self.assertEqual(captured.get("window_mode"), "kiosk")

    def test_normal_run_uses_default_window_mode(self):
        import retrovault.ui.app as app_module

        captured = {"called": False}

        def stub(window_mode=None):
            captured["called"] = True
            captured["window_mode"] = window_mode

        with mock.patch.object(app_module, "main", stub):
            from retrovault import __main__ as entry

            entry.main([])

        self.assertTrue(captured["called"])
        self.assertIsNone(captured["window_mode"])


if __name__ == "__main__":
    unittest.main()
