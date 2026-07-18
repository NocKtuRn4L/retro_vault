"""Headless tests for favorites/collections wiring in MainWindow (PR D, #4)."""

import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from retrovault.input.backend import NullBackend
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
class MainWindowFavoritesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self, collections=None):
        with (
            mock.patch.object(mw, "load_library", return_value=[dict(r) for r in FAKE_LIBRARY]),
            mock.patch.object(mw, "load_collections", return_value=list(collections or [])),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            return MainWindow()

    def _sidebar_keys(self, window):
        return [
            window.sidebar.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(window.sidebar.count())
        ]

    def test_sidebar_prepends_sentinel_rows(self):
        window = self._make_window(collections=[{"name": "RPGs", "paths": []}])
        try:
            keys = self._sidebar_keys(window)
            self.assertEqual(keys[0], "__favorites__")
            self.assertEqual(keys[1], "__recent__")
            self.assertEqual(keys[2], "collection:RPGs")
            self.assertIn("", keys)  # ALL GAMES
            # Virtual rows come before ALL GAMES.
            self.assertLess(keys.index("collection:RPGs"), keys.index(""))
        finally:
            window.close()

    def test_toggle_favorite_selected_persists_and_flags_entry(self):
        window = self._make_window()
        try:
            with mock.patch.object(mw, "save_library") as save:
                window._focus_games_column()  # selects first visible row
                window._toggle_favorite_selected()
                self.assertTrue(save.called)
            rom = window._selected_rom()
            self.assertTrue(rom.get("favorite"))
            # Toggling again clears it.
            with mock.patch.object(mw, "save_library"):
                window._toggle_favorite_selected()
            self.assertFalse(window._selected_rom().get("favorite"))
        finally:
            window.close()

    def test_menu_actions_include_toggle_favorite(self):
        window = self._make_window()
        try:
            labels = [label for label, _ in window._menu_actions()]
            self.assertIn("Toggle Favorite (selected game)", labels)
        finally:
            window.close()

    def test_toggle_collection_membership_persists(self):
        window = self._make_window(collections=[{"name": "RPGs", "paths": []}])
        try:
            rom = FAKE_LIBRARY[2]  # Charlie
            with mock.patch.object(mw, "save_collections") as save:
                window._toggle_collection_membership(rom, "RPGs")
                self.assertTrue(save.called)
            self.assertIn("/roms/charlie.sfc", window._get_collections()[0]["paths"])
            # Toggling again removes it.
            with mock.patch.object(mw, "save_collections"):
                window._toggle_collection_membership(rom, "RPGs")
            self.assertNotIn("/roms/charlie.sfc", window._get_collections()[0]["paths"])
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
