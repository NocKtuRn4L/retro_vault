"""Headless tests for the game detail panel (PR #2b)."""

import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.input.backend import NullBackend
    from retrovault.ui import main_window as mw
    from retrovault.ui.detail_panel import DetailPanel, _format_duration
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


BARE_ROM = {"name": "Bare Game", "system": "nes", "ext": ".nes", "path": "/roms/bare.nes"}

ENRICHED_ROM = {
    "name": "Super Enriched",
    "system": "snes",
    "ext": ".sfc",
    "path": "/roms/enriched.sfc",
    "media": {"boxart": "/nonexistent/boxart.png"},
    "metadata": {
        "synopsis": "A sprawling adventure across pixelated worlds.",
        "genre": "RPG",
        "players": 2,
        "rating": "9/10",
        "year": 1994,
    },
    "play_seconds": 5025,  # 1h 23m
    "play_count": 4,
    "ra_earned": 12,
    "ra_total": 40,
}

SYSTEMS = {
    "nes": {"name": "Nintendo Entertainment System", "short": "NES"},
    "snes": {"name": "Super Nintendo", "short": "SNES"},
}

FAKE_LIBRARY = [
    dict(BARE_ROM),
    dict(ENRICHED_ROM),
]


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class DetailPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    # ── Standalone panel ──────────────────────────────────────────────────────
    def test_renders_none_without_error(self):
        panel = DetailPanel(SYSTEMS)
        panel.update_for(None)
        self.assertIn("No game", panel.name_label.text())
        self.assertEqual(panel.boxart_label.text(), "NO IMAGE")

    def test_renders_bare_entry_without_error(self):
        panel = DetailPanel(SYSTEMS)
        panel.update_for(BARE_ROM)
        self.assertEqual(panel.name_label.text(), "Bare Game")
        self.assertEqual(panel.system_label.text(), "Nintendo Entertainment System")
        # No metadata / media -> fact rows hidden, placeholder box art.
        # (isHidden reflects the explicit hide; isVisible would be False anyway
        # because the standalone panel is never shown as a top-level window.)
        self.assertTrue(panel.genre_label.isHidden())
        self.assertTrue(panel.synopsis_label.isHidden())
        self.assertTrue(panel.achievements_label.isHidden())
        self.assertEqual(panel.boxart_label.text(), "NO IMAGE")

    def test_renders_enriched_entry(self):
        panel = DetailPanel(SYSTEMS)
        panel.update_for(ENRICHED_ROM)
        self.assertEqual(panel.name_label.text(), "Super Enriched")
        self.assertEqual(panel.system_label.text(), "Super Nintendo")
        self.assertIn("RPG", panel.genre_label.text())
        self.assertIn("1994", panel.year_label.text())
        self.assertIn("2", panel.players_label.text())
        self.assertIn("9/10", panel.rating_label.text())
        self.assertIn("adventure", panel.synopsis_label.text())
        self.assertFalse(panel.synopsis_label.isHidden())
        self.assertIn("1h 23m", panel.playtime_label.text())
        self.assertIn("4 plays", panel.playtime_label.text())
        self.assertEqual(panel.achievements_label.text(), "12 / 40 achievements")
        # Missing box-art file falls back to the placeholder, not a crash.
        self.assertEqual(panel.boxart_label.text(), "NO IMAGE")

    def test_missing_media_dict_is_safe(self):
        panel = DetailPanel(SYSTEMS)
        panel.update_for({"name": "X", "system": "nes", "media": None, "metadata": None})
        self.assertEqual(panel.boxart_label.text(), "NO IMAGE")

    def test_switching_between_entries_updates(self):
        panel = DetailPanel(SYSTEMS)
        panel.update_for(ENRICHED_ROM)
        self.assertFalse(panel.achievements_label.isHidden())
        panel.update_for(BARE_ROM)
        self.assertTrue(panel.achievements_label.isHidden())
        self.assertEqual(panel.name_label.text(), "Bare Game")

    def test_system_falls_back_to_upper_key(self):
        panel = DetailPanel({})  # no systems mapping
        panel.update_for(BARE_ROM)
        self.assertEqual(panel.system_label.text(), "NES")

    def test_format_duration(self):
        self.assertEqual(_format_duration(5025), "1h 23m")
        self.assertEqual(_format_duration(120), "2m")
        self.assertEqual(_format_duration(45), "45s")
        self.assertEqual(_format_duration(None), "")

    # ── Integration with MainWindow ───────────────────────────────────────────
    def _make_window(self):
        with (
            mock.patch.object(mw, "load_library", return_value=list(FAKE_LIBRARY)),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
        ):
            return MainWindow()

    def test_window_has_detail_panel(self):
        window = self._make_window()
        try:
            self.assertIsInstance(window.detail_panel, DetailPanel)
        finally:
            window.close()

    def test_panel_updates_on_selection_change(self):
        window = self._make_window()
        try:
            row0 = window.proxy.index(0, 0)
            window.table.setCurrentIndex(row0)
            name0 = window._selected_rom().get("name")
            self.assertEqual(window.detail_panel.name_label.text(), name0)

            row1 = window.proxy.index(1, 0)
            window.table.setCurrentIndex(row1)
            name1 = window._selected_rom().get("name")
            self.assertEqual(window.detail_panel.name_label.text(), name1)
            self.assertNotEqual(name0, name1)
        finally:
            window.close()

    def test_detail_panel_toggle_hides_and_shows(self):
        window = self._make_window()
        try:
            window.show()
            self.assertTrue(window.detail_panel.isVisible())
            window.detail_panel.setVisible(False)
            self.assertFalse(window.detail_panel.isVisible())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
