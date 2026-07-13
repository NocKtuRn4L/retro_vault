"""Headless tests for controller navigation inside modal dialogs (PR9)."""

import copy
import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QMessageBox,
        QPushButton,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    from retrovault.core import config as config_mod
    from retrovault.input.actions import Action, ActionEvent
    from retrovault.input.backend import NullBackend
    from retrovault.providers.manifest import load_shipped_registry
    from retrovault.ui import controller_nav
    from retrovault.ui import main_window as mw
    from retrovault.ui import setup_wizard as sw
    from retrovault.ui.main_window import MainWindow
    from retrovault.ui.settings_dialog import SettingsDialog
    from retrovault.ui.setup_wizard import SetupWizard

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


FAKE_LIBRARY = [
    {"name": "Alpha", "system": "nes", "ext": ".nes", "path": "/roms/alpha.nes"},
    {"name": "Bravo", "system": "nes", "ext": ".nes", "path": "/roms/bravo.nes"},
]


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ControllerNavHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog_with_buttons(self):
        dialog = QDialog()
        layout = QVBoxLayout(dialog)
        first = QPushButton("first")
        disabled = QPushButton("disabled")
        disabled.setEnabled(False)
        second = QPushButton("second")
        controller_nav.make_focusable(first, disabled, second)
        for btn in (first, disabled, second):
            layout.addWidget(btn)
        dialog.show()
        self.app.processEvents()
        return dialog, first, disabled, second

    def test_move_focus_skips_disabled(self):
        dialog, first, disabled, second = self._dialog_with_buttons()
        try:
            first.setFocus()
            self.app.processEvents()
            landed = controller_nav.move_focus(dialog, forward=True)
            # Qt never lands focus on a disabled control.
            self.assertIsNot(landed, disabled)
            self.assertTrue(landed is None or landed.isEnabled())
        finally:
            dialog.close()

    def test_switch_tab_changes_and_clamps(self):
        tabs = QTabWidget()
        for i in range(3):
            tabs.addTab(QWidget(), f"T{i}")
        try:
            self.assertEqual(tabs.currentIndex(), 0)
            self.assertEqual(controller_nav.switch_tab(tabs, 1), 1)
            self.assertEqual(controller_nav.switch_tab(tabs, 1), 2)
            # Clamp at the top end.
            self.assertEqual(controller_nav.switch_tab(tabs, 1), 2)
            self.assertEqual(controller_nav.switch_tab(tabs, -1), 1)
            self.assertEqual(controller_nav.switch_tab(tabs, -5), 0)
        finally:
            tabs.deleteLater()

    def test_activate_focused_clicks_button(self):
        dialog, first, _disabled, _second = self._dialog_with_buttons()
        try:
            fired = {"count": 0}
            first.clicked.connect(lambda: fired.__setitem__("count", fired["count"] + 1))
            with mock.patch.object(QApplication, "focusWidget", return_value=first):
                self.assertTrue(controller_nav.activate_focused(dialog))
            self.assertEqual(fired["count"], 1)
        finally:
            dialog.close()

    def test_activate_focused_ignores_disabled_button(self):
        dialog, _first, disabled, _second = self._dialog_with_buttons()
        try:
            fired = {"count": 0}
            disabled.clicked.connect(lambda: fired.__setitem__("count", fired["count"] + 1))
            with mock.patch.object(QApplication, "focusWidget", return_value=disabled):
                self.assertFalse(controller_nav.activate_focused(dialog))
            self.assertEqual(fired["count"], 0)
        finally:
            dialog.close()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class SettingsDialogNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        cfg = copy.deepcopy(config_mod.DEFAULT_CONFIG)
        dialog = SettingsDialog(cfg)
        dialog.show()
        self.app.processEvents()
        return dialog

    def _feed(self, dialog, action):
        return dialog.handle_controller_action(ActionEvent(action))

    def test_left_right_switches_tabs(self):
        dialog = self._dialog()
        try:
            self.assertEqual(dialog.tabs.currentIndex(), 0)
            self.assertTrue(self._feed(dialog, Action.RIGHT))
            self.assertEqual(dialog.tabs.currentIndex(), 1)
            self.assertTrue(self._feed(dialog, Action.NEXT_SYSTEM))
            self.assertEqual(dialog.tabs.currentIndex(), 2)
            self.assertTrue(self._feed(dialog, Action.LEFT))
            self.assertEqual(dialog.tabs.currentIndex(), 1)
            self.assertTrue(self._feed(dialog, Action.PREV_SYSTEM))
            self.assertEqual(dialog.tabs.currentIndex(), 0)
        finally:
            dialog.close()

    def test_back_triggers_reject(self):
        dialog = self._dialog()
        try:
            with mock.patch.object(dialog, "reject") as reject:
                self.assertTrue(self._feed(dialog, Action.BACK))
                reject.assert_called_once()
        finally:
            dialog.close()

    def test_menu_is_ignored(self):
        dialog = self._dialog()
        try:
            self.assertFalse(self._feed(dialog, Action.MENU))
        finally:
            dialog.close()

    def test_up_down_moves_focus(self):
        dialog = self._dialog()
        try:
            with mock.patch.object(controller_nav, "move_focus") as mocked:
                # settings_dialog imported move_focus by name, so patch there too.
                with mock.patch("retrovault.ui.settings_dialog.move_focus", mocked):
                    self.assertTrue(self._feed(dialog, Action.DOWN))
                    self.assertTrue(self._feed(dialog, Action.UP))
            self.assertEqual(mocked.call_count, 2)
            self.assertTrue(mocked.call_args_list[0].kwargs["forward"])
            self.assertFalse(mocked.call_args_list[1].kwargs["forward"])
        finally:
            dialog.close()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class SetupWizardNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wizard(self, platform="windows-x86_64"):
        patcher = mock.patch("retrovault.ui.setup_wizard.detect.current_platform", return_value=platform)
        patcher.start()
        self.addCleanup(patcher.stop)
        wizard = SetupWizard(config_mod.DEFAULT_CONFIG, registry=load_shipped_registry())
        self.addCleanup(wizard.close)
        wizard.show()
        self.app.processEvents()
        return wizard

    def _feed(self, wizard, action):
        return wizard.handle_controller_action(ActionEvent(action))

    def test_directions_move_focus(self):
        wizard = self._wizard()
        with mock.patch("retrovault.ui.setup_wizard.move_focus") as mocked:
            self.assertTrue(self._feed(wizard, Action.DOWN))
            self.assertTrue(self._feed(wizard, Action.UP))
            self.assertTrue(self._feed(wizard, Action.LEFT))
            self.assertTrue(self._feed(wizard, Action.RIGHT))
        self.assertEqual(mocked.call_count, 4)
        self.assertEqual(
            [c.kwargs["forward"] for c in mocked.call_args_list],
            [True, False, False, True],
        )

    def test_back_rejects(self):
        wizard = self._wizard()
        with mock.patch.object(wizard, "reject") as reject:
            self.assertTrue(self._feed(wizard, Action.BACK))
            reject.assert_called_once()

    def test_menu_ignored(self):
        wizard = self._wizard()
        self.assertFalse(self._feed(wizard, Action.MENU))

    def test_uninstall_confirmation_declined(self):
        wizard = self._wizard()
        row = wizard.rows["nes"]
        row["installed_path"] = "C:/Mesen/Mesen.exe"
        with (
            mock.patch.object(sw.QApplication, "focusWidget", return_value=row["install"]),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No),
            mock.patch.object(wizard, "_toggle_install") as toggle,
        ):
            self.assertTrue(self._feed(wizard, Action.ACCEPT))
            toggle.assert_not_called()

    def test_uninstall_confirmation_accepted(self):
        wizard = self._wizard()
        row = wizard.rows["nes"]
        row["installed_path"] = "C:/Mesen/Mesen.exe"
        with (
            mock.patch.object(sw.QApplication, "focusWidget", return_value=row["install"]),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            mock.patch.object(wizard, "_toggle_install") as toggle,
        ):
            self.assertTrue(self._feed(wizard, Action.ACCEPT))
            toggle.assert_called_once_with("nes")

    def test_accept_non_uninstall_button_activates(self):
        wizard = self._wizard()
        row = wizard.rows["nes"]
        # No installed_path -> plain activation path, not the confirm dialog.
        with (
            mock.patch.object(sw.QApplication, "focusWidget", return_value=row["detect"]),
            mock.patch("retrovault.ui.setup_wizard.activate_focused", return_value=True) as activate,
            mock.patch.object(QMessageBox, "question") as question,
        ):
            self.assertTrue(self._feed(wizard, Action.ACCEPT))
            question.assert_not_called()
            activate.assert_called_once()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainWindowDelegationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        with (
            mock.patch.object(mw, "load_library", return_value=list(FAKE_LIBRARY)),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            window = MainWindow()
        return window

    def test_delegates_to_active_modal_with_handler(self):
        window = self._make_window()
        try:
            fake_modal = mock.Mock()
            start_row = window._selected_proxy_row()
            with mock.patch.object(mw.QApplication, "activeModalWidget", return_value=fake_modal):
                window._on_controller_action(ActionEvent(Action.DOWN))
            fake_modal.handle_controller_action.assert_called_once()
            # The main table must NOT have moved while the modal was active.
            self.assertEqual(window._selected_proxy_row(), start_row)
        finally:
            window.close()

    def test_foreign_modal_without_handler_does_nothing(self):
        window = self._make_window()
        try:
            # A native file dialog: a modal widget with no handle_controller_action.
            file_dialog = QWidget()
            start_row = window._selected_proxy_row()
            with mock.patch.object(mw.QApplication, "activeModalWidget", return_value=file_dialog):
                window._on_controller_action(ActionEvent(Action.DOWN))
            self.assertEqual(window._selected_proxy_row(), start_row)
        finally:
            window.close()

    def test_no_modal_still_navigates_main_window(self):
        window = self._make_window()
        try:
            with mock.patch.object(mw.QApplication, "activeModalWidget", return_value=None):
                window._on_controller_action(ActionEvent(Action.DOWN))
            self.assertEqual(window._selected_proxy_row(), 0)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
