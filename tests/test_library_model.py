"""Headless tests for LibraryFilterProxyModel sentinel filters (PR D, #4)."""

import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.ui.library_model import LibraryFilterProxyModel, LibraryModel

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


FAKE_LIBRARY = [
    {"name": "Alpha", "system": "nes", "ext": ".nes", "path": "/roms/alpha.nes",
     "favorite": True, "last_played": "2026-07-10T12:00:00"},
    {"name": "Bravo", "system": "nes", "ext": ".nes", "path": "/roms/bravo.nes",
     "last_played": "2026-07-15T09:30:00"},
    {"name": "Charlie", "system": "snes", "ext": ".sfc", "path": "/roms/charlie.sfc",
     "favorite": True},
    {"name": "Delta", "system": "snes", "ext": ".sfc", "path": "/roms/delta.sfc"},
]


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ProxyFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _proxy(self, library=None):
        model = LibraryModel(list(library or FAKE_LIBRARY), {})
        proxy = LibraryFilterProxyModel()
        proxy.setSourceModel(model)
        return proxy

    def _names(self, proxy):
        return {
            proxy.index(row, 0).data()
            for row in range(proxy.rowCount())
        }

    def _ordered_names(self, proxy):
        return [proxy.index(row, 0).data() for row in range(proxy.rowCount())]

    # ── Favorites ─────────────────────────────────────────────────────────────
    def test_favorites_filter_shows_only_favorites(self):
        proxy = self._proxy()
        proxy.set_system_filter("__favorites__")
        self.assertEqual(self._names(proxy), {"Alpha", "Charlie"})

    def test_favorites_filter_empty_when_none_favorited(self):
        library = [dict(rom, favorite=False) for rom in FAKE_LIBRARY]
        proxy = self._proxy(library)
        proxy.set_system_filter("__favorites__")
        self.assertEqual(proxy.rowCount(), 0)

    # ── Recently played ───────────────────────────────────────────────────────
    def test_recent_filter_shows_only_played_games(self):
        proxy = self._proxy()
        proxy.set_system_filter("__recent__")
        self.assertEqual(self._names(proxy), {"Alpha", "Bravo"})

    def test_recent_filter_orders_most_recent_first(self):
        proxy = self._proxy()
        proxy.sort(0)  # view sorts ascending; recent view overrides via lessThan
        proxy.set_system_filter("__recent__")
        # Bravo was played 2026-07-15, Alpha 2026-07-10 -> Bravo first.
        self.assertEqual(self._ordered_names(proxy), ["Bravo", "Alpha"])

    # ── Collections ───────────────────────────────────────────────────────────
    def test_collection_filter_matches_member_paths(self):
        proxy = self._proxy()
        proxy.set_collections([
            {"name": "RPGs", "paths": ["/roms/charlie.sfc", "/roms/delta.sfc"]},
        ])
        proxy.set_system_filter("collection:RPGs")
        self.assertEqual(self._names(proxy), {"Charlie", "Delta"})

    def test_collection_filter_unknown_name_shows_nothing(self):
        proxy = self._proxy()
        proxy.set_collections([{"name": "RPGs", "paths": ["/roms/charlie.sfc"]}])
        proxy.set_system_filter("collection:DoesNotExist")
        self.assertEqual(proxy.rowCount(), 0)

    def test_plain_system_filter_still_works(self):
        proxy = self._proxy()
        proxy.set_system_filter("nes")
        self.assertEqual(self._names(proxy), {"Alpha", "Bravo"})

    def test_search_combines_with_favorites(self):
        proxy = self._proxy()
        proxy.set_system_filter("__favorites__")
        proxy.set_search_text("alph")
        self.assertEqual(self._names(proxy), {"Alpha"})


if __name__ == "__main__":
    unittest.main()
