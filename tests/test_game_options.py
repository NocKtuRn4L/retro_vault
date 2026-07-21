"""Headless tests for the controller-reachable Game Options menu (C1).

The mouse context menu is unreachable from a gamepad; ``Action.OPTIONS`` (bound
to the west face button) opens a ``MainMenuDialog`` exposing the same per-game
actions. These verify the routing, the action list, and that choosing a row runs
the matching handler — without spinning a real modal loop.
"""

import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from retrovault.input.actions import Action, ActionEvent
    from retrovault.input.backend import NullBackend
    from retrovault.ui import main_window as mw
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


FAKE_LIBRARY = [
    {"name": "Alpha", "system": "nes", "ext": ".nes", "path": "/roms/alpha.nes"},
    {"name": "Bravo", "system": "nes", "ext": ".nes", "path": "/roms/bravo.nes"},
]


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class GameOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        with (
            mock.patch.object(mw, "load_library", return_value=[dict(r) for r in FAKE_LIBRARY]),
            mock.patch.object(mw, "load_collections", return_value=[]),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            return MainWindow()

    def test_options_action_routes_to_game_options(self):
        window = self._make_window()
        try:
            # OPTIONS is deferred via QTimer.singleShot(0, self._open_game_options)
            # (same nested-event-loop reason as MENU). Patch singleShot so the test
            # neither spins the event loop nor leaks a timer that could later open
            # a real modal.
            with mock.patch.object(mw.QTimer, "singleShot") as single_shot:
                window._on_controller_action(ActionEvent(Action.OPTIONS))
                single_shot.assert_called_once()
                self.assertEqual(single_shot.call_args[0][1], window._open_game_options)
        finally:
            window.close()

    def test_options_actions_mirror_context_menu(self):
        window = self._make_window()
        try:
            rom = FAKE_LIBRARY[0]
            labels = [label for label, _ in window._game_options_actions(rom)]
            self.assertEqual(
                labels,
                [
                    "Launch",
                    "Add to Favorites",
                    "Add to Collection…",
                    "Open File Location",
                    "Remove from Library",
                ],
            )
        finally:
            window.close()

    def test_favorite_label_reflects_state(self):
        window = self._make_window()
        try:
            rom = dict(FAKE_LIBRARY[0], favorite=True)
            labels = [label for label, _ in window._game_options_actions(rom)]
            self.assertIn("Remove from Favorites", labels)
        finally:
            window.close()

    def test_choosing_launch_runs_handler(self):
        window = self._make_window()
        try:
            window._focus_games_column()  # select first row so _selected_rom works
            # Replace the dialog entirely so no real modal loop runs; make it
            # "choose" row 0 (Launch).
            with mock.patch.object(mw, "MainMenuDialog") as dialog_cls:
                inst = dialog_cls.return_value
                inst.exec.return_value = QDialog.DialogCode.Accepted
                inst.chosen_index = 0
                with mock.patch.object(window, "on_launch_selected") as launch:
                    window._open_game_options()
                self.assertTrue(launch.called)
        finally:
            window.close()

    def test_no_selection_shows_message_and_opens_nothing(self):
        window = self._make_window()
        try:
            window.table.clearSelection()
            window.table.selectionModel().clearCurrentIndex()
            with mock.patch.object(mw.MainMenuDialog, "exec") as dlg_exec:
                window._open_game_options()
                self.assertFalse(dlg_exec.called)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
