"""Headless tests for controller-driven navigation in MainWindow (PR6)."""

import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.input.actions import Action, ActionEvent
    from retrovault.input.backend import NullBackend
    from retrovault.input.router import ControllerRouter
    from retrovault.ui import main_window as mw
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


FAKE_LIBRARY = [
    {"name": "Alpha", "system": "nes", "ext": ".nes", "path": "/roms/alpha.nes"},
    {"name": "Bravo", "system": "nes", "ext": ".nes", "path": "/roms/bravo.nes"},
    {"name": "Charlie", "system": "snes", "ext": ".sfc", "path": "/roms/charlie.sfc"},
]


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainWindowNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        """Build a MainWindow with a seeded in-memory library and no real backend."""
        with (
            mock.patch.object(mw, "load_library", return_value=list(FAKE_LIBRARY)),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            window = MainWindow()
        return window

    def _feed(self, window, action):
        window._on_controller_action(ActionEvent(action))

    # ── Wiring ────────────────────────────────────────────────────────────────
    def test_controller_stack_is_wired(self):
        window = self._make_window()
        try:
            self.assertIsNotNone(window.controller)
            self.assertIsInstance(window.controller, ControllerRouter)
            self.assertFalse(window._controller_busy)
        finally:
            window.close()

    # ── Table navigation ──────────────────────────────────────────────────────
    def test_up_down_moves_selection(self):
        window = self._make_window()
        try:
            # No selection yet -> DOWN selects the first visible row.
            self._feed(window, Action.DOWN)
            self.assertEqual(window._selected_proxy_row(), 0)

            self._feed(window, Action.DOWN)
            self.assertEqual(window._selected_proxy_row(), 1)

            self._feed(window, Action.UP)
            self.assertEqual(window._selected_proxy_row(), 0)

            # Clamp at the top.
            self._feed(window, Action.UP)
            self.assertEqual(window._selected_proxy_row(), 0)
        finally:
            window.close()

    def test_down_clamps_at_bottom(self):
        window = self._make_window()
        try:
            last = window.proxy.rowCount() - 1
            for _ in range(window.proxy.rowCount() + 3):
                self._feed(window, Action.DOWN)
            self.assertEqual(window._selected_proxy_row(), last)
        finally:
            window.close()

    # ── Sidebar / system filter navigation ────────────────────────────────────
    def test_right_left_changes_sidebar(self):
        window = self._make_window()
        try:
            self.assertEqual(window.sidebar.currentRow(), 0)
            self._feed(window, Action.RIGHT)
            self.assertEqual(window.sidebar.currentRow(), 1)
            self._feed(window, Action.LEFT)
            self.assertEqual(window.sidebar.currentRow(), 0)
        finally:
            window.close()

    def test_next_prev_system_changes_sidebar(self):
        window = self._make_window()
        try:
            self.assertEqual(window.sidebar.currentRow(), 0)
            self._feed(window, Action.NEXT_SYSTEM)
            self.assertEqual(window.sidebar.currentRow(), 1)
            # Changing the filter should auto-select the first visible ROM.
            self.assertEqual(window._selected_proxy_row(), 0)
            self._feed(window, Action.PREV_SYSTEM)
            self.assertEqual(window.sidebar.currentRow(), 0)
        finally:
            window.close()

    # ── Buttons ───────────────────────────────────────────────────────────────
    def test_accept_launches_selected_rom(self):
        window = self._make_window()
        try:
            self._feed(window, Action.DOWN)  # select row 0
            selected = window._selected_rom()
            captured = {}

            def stub():
                captured["rom"] = window._selected_rom()

            window.on_launch_selected = stub
            self._feed(window, Action.ACCEPT)
            self.assertEqual(captured.get("rom"), selected)
        finally:
            window.close()

    def test_menu_opens_settings(self):
        window = self._make_window()
        try:
            window.on_settings = mock.Mock()
            self._feed(window, Action.MENU)
            window.on_settings.assert_called_once()
        finally:
            window.close()

    # ── Busy guard ────────────────────────────────────────────────────────────
    def test_busy_suppresses_all_actions(self):
        window = self._make_window()
        try:
            window._controller_busy = True
            window.on_launch_selected = mock.Mock()
            window.on_settings = mock.Mock()
            start_sidebar = window.sidebar.currentRow()
            start_row = window._selected_proxy_row()

            for action in (Action.DOWN, Action.UP, Action.RIGHT, Action.LEFT, Action.ACCEPT, Action.MENU):
                self._feed(window, action)

            self.assertEqual(window.sidebar.currentRow(), start_sidebar)
            self.assertEqual(window._selected_proxy_row(), start_row)
            window.on_launch_selected.assert_not_called()
            window.on_settings.assert_not_called()
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
