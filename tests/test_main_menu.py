"""Headless tests for the controller-navigable main menu (top-bar actions)."""

import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from retrovault.input.actions import Action, ActionEvent
    from retrovault.input.backend import NullBackend
    from retrovault.ui import main_window as mw
    from retrovault.ui.main_menu import MainMenuDialog
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


FAKE_LIBRARY = [
    {"name": "Alpha", "system": "nes", "ext": ".nes", "path": "/roms/alpha.nes"},
]


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainMenuDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _feed(self, dialog, action):
        return dialog.handle_controller_action(ActionEvent(action))

    def test_up_down_move_selection_and_clamp(self):
        dialog = MainMenuDialog(["A", "B", "C"])
        try:
            self.assertEqual(dialog.list.currentRow(), 0)
            self._feed(dialog, Action.DOWN)
            self.assertEqual(dialog.list.currentRow(), 1)
            self._feed(dialog, Action.DOWN)
            self._feed(dialog, Action.DOWN)  # clamp at last
            self.assertEqual(dialog.list.currentRow(), 2)
            self._feed(dialog, Action.UP)
            self.assertEqual(dialog.list.currentRow(), 1)
        finally:
            dialog.close()

    def test_accept_chooses_current_row(self):
        dialog = MainMenuDialog(["A", "B", "C"])
        self._feed(dialog, Action.DOWN)  # -> row 1
        handled = self._feed(dialog, Action.ACCEPT)
        self.assertTrue(handled)
        self.assertEqual(dialog.chosen_index, 1)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_back_dismisses_without_choice(self):
        dialog = MainMenuDialog(["A", "B"])
        self._feed(dialog, Action.BACK)
        self.assertEqual(dialog.chosen_index, -1)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_menu_button_also_dismisses(self):
        dialog = MainMenuDialog(["A", "B"])
        self._feed(dialog, Action.MENU)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainMenuDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        with (
            mock.patch.object(mw, "load_library", return_value=list(FAKE_LIBRARY)),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            return MainWindow()

    def test_menu_exposes_the_top_bar_actions(self):
        window = self._make_window()
        try:
            labels = [label for label, _ in window._menu_actions()]
            self.assertEqual(
                labels,
                ["Search Games", "Scan ROMs", "Add ROM Folder", "Setup Wizard", "Settings", "Exit RetroVault"],
            )
        finally:
            window.close()

    def test_choosing_scan_runs_scan(self):
        window = self._make_window()
        try:
            window.on_scan_roms = mock.Mock()
            with mock.patch.object(mw, "MainMenuDialog") as dialog_cls:
                inst = dialog_cls.return_value
                inst.exec.return_value = QDialog.DialogCode.Accepted
                inst.chosen_index = 1  # Scan ROMs
                window._open_menu()
            window.on_scan_roms.assert_called_once()
        finally:
            window.close()

    def test_choosing_settings_opens_settings(self):
        window = self._make_window()
        try:
            window.on_settings = mock.Mock()
            with mock.patch.object(mw, "MainMenuDialog") as dialog_cls:
                inst = dialog_cls.return_value
                inst.exec.return_value = QDialog.DialogCode.Accepted
                inst.chosen_index = 4  # Settings
                window._open_menu()
            window.on_settings.assert_called_once()
        finally:
            window.close()

    def test_dismissed_menu_runs_nothing(self):
        window = self._make_window()
        try:
            window.on_scan_roms = mock.Mock()
            window.on_settings = mock.Mock()
            with mock.patch.object(mw, "MainMenuDialog") as dialog_cls:
                inst = dialog_cls.return_value
                inst.exec.return_value = QDialog.DialogCode.Rejected
                inst.chosen_index = -1
                window._open_menu()
            window.on_scan_roms.assert_not_called()
            window.on_settings.assert_not_called()
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
