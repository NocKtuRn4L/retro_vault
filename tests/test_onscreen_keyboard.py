"""Headless tests for the controller-navigable on-screen keyboard."""

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
    from retrovault.ui.onscreen_keyboard import OnScreenKeyboard

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class OnScreenKeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _feed(self, kb, action):
        return kb.handle_controller_action(ActionEvent(action))

    def _type_char(self, kb, ch):
        """Navigate the grid to ``ch`` and press it (row/col walk from origin)."""
        for r, row in enumerate(kb._keys):
            for c, (label, _kind, _value) in enumerate(row):
                if label == ch:
                    kb._row, kb._col = r, c
                    kb._focus_current()
                    self._feed(kb, Action.ACCEPT)
                    return
        raise AssertionError(f"key {ch!r} not found")

    def test_accept_types_and_del_removes(self):
        kb = OnScreenKeyboard()
        try:
            self._type_char(kb, "h")
            self._type_char(kb, "i")
            self.assertEqual(kb.text(), "hi")
            self._feed(kb, Action.BACK)  # quick backspace
            self.assertEqual(kb.text(), "h")
        finally:
            kb.close()

    def test_initial_text_is_preserved(self):
        kb = OnScreenKeyboard("mario")
        try:
            self.assertEqual(kb.text(), "mario")
        finally:
            kb.close()

    def test_directional_navigation_clamps(self):
        kb = OnScreenKeyboard()
        try:
            kb._row, kb._col = 0, 0
            self._feed(kb, Action.UP)  # clamp at top
            self.assertEqual((kb._row, kb._col), (0, 0))
            self._feed(kb, Action.LEFT)  # clamp at left
            self.assertEqual((kb._row, kb._col), (0, 0))
            self._feed(kb, Action.RIGHT)
            self.assertEqual((kb._row, kb._col), (0, 1))
            self._feed(kb, Action.DOWN)
            self.assertEqual(kb._row, 1)
        finally:
            kb.close()

    def test_down_into_shorter_row_clamps_column(self):
        kb = OnScreenKeyboard()
        try:
            # Row 0 has 10 keys; move to the last column then down into shorter rows.
            kb._row, kb._col = 0, 9
            self._feed(kb, Action.DOWN)  # row 1 has 10 too
            self._feed(kb, Action.DOWN)  # row 2 "asdfghjkl" has 9
            self.assertLessEqual(kb._col, len(kb._keys[kb._row]) - 1)
        finally:
            kb.close()

    def test_shoulder_shortcuts_space_and_backspace(self):
        kb = OnScreenKeyboard("ab")
        try:
            self._feed(kb, Action.NEXT_SYSTEM)  # space
            self.assertEqual(kb.text(), "ab ")
            self._feed(kb, Action.PREV_SYSTEM)  # backspace
            self.assertEqual(kb.text(), "ab")
        finally:
            kb.close()

    def test_done_key_accepts_with_text(self):
        kb = OnScreenKeyboard("zelda")
        self._feed(kb, Action.MENU)  # Start confirms
        self.assertEqual(kb.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(kb.text(), "zelda")

    def test_cancel_key_rejects(self):
        kb = OnScreenKeyboard("x")
        # Find and press the CANCEL key.
        for r, row in enumerate(kb._keys):
            for c, (label, _k, _v) in enumerate(row):
                if label == "CANCEL":
                    kb._row, kb._col = r, c
                    kb.handle_controller_action(ActionEvent(Action.ACCEPT))
        self.assertEqual(kb.result(), QDialog.DialogCode.Rejected)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class SearchViaKeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self):
        with (
            mock.patch.object(mw, "load_library", return_value=[]),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            return MainWindow()

    def test_accepted_keyboard_sets_search_text(self):
        window = self._make_window()
        try:
            with mock.patch.object(mw, "OnScreenKeyboard") as kb_cls:
                inst = kb_cls.return_value
                inst.exec.return_value = QDialog.DialogCode.Accepted
                inst.text.return_value = "castlevania"
                window.on_search_via_keyboard()
            self.assertEqual(window.search_box.text(), "castlevania")
        finally:
            window.close()

    def test_cancelled_keyboard_leaves_search_untouched(self):
        window = self._make_window()
        try:
            window.search_box.setText("before")
            with mock.patch.object(mw, "OnScreenKeyboard") as kb_cls:
                inst = kb_cls.return_value
                inst.exec.return_value = QDialog.DialogCode.Rejected
                inst.text.return_value = "ignored"
                window.on_search_via_keyboard()
            self.assertEqual(window.search_box.text(), "before")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
