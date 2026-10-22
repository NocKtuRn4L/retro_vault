"""Headless tests for LibraryFilterProxyModel sentinel filters (PR D, #4)."""

import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPersistentModelIndex, Qt
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


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class LibrarySortTests(unittest.TestCase):
    """Column sorting happens in the source model, not row-by-row in the proxy."""

    SYSTEMS = {"nes": {"short": "NES"}, "snes": {"short": "SNES"}, "gb": {"short": "GB"}}

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _proxy(self, library=None):
        model = LibraryModel(list(library or FAKE_LIBRARY), self.SYSTEMS)
        proxy = LibraryFilterProxyModel()
        proxy.setSourceModel(model)
        return proxy

    def _ordered_names(self, proxy):
        return [proxy.index(row, 0).data() for row in range(proxy.rowCount())]

    def test_sorts_by_each_column_in_the_model(self):
        library = [
            {"name": "delta", "system": "snes", "ext": ".smc"},
            {"name": "Bravo", "system": "nes", "ext": ".nes"},
            {"name": "alpha", "system": "snes", "ext": ".sfc"},
            {"name": "Charlie", "system": "gb", "ext": ".gb"},
        ]
        proxy = self._proxy(library)

        proxy.sort(0, Qt.SortOrder.AscendingOrder)  # case-insensitive by name
        self.assertEqual(self._ordered_names(proxy), ["alpha", "Bravo", "Charlie", "delta"])
        self.assertEqual(proxy.sortColumn(), -1)  # the proxy itself never sorts

        proxy.sort(0, Qt.SortOrder.DescendingOrder)
        self.assertEqual(self._ordered_names(proxy), ["delta", "Charlie", "Bravo", "alpha"])

        proxy.sort(1, Qt.SortOrder.AscendingOrder)  # by system label, then name
        self.assertEqual(self._ordered_names(proxy), ["Charlie", "Bravo", "alpha", "delta"])

        proxy.sort(2, Qt.SortOrder.AscendingOrder)  # by extension
        self.assertEqual(self._ordered_names(proxy), ["Charlie", "Bravo", "alpha", "delta"])

    def test_sort_keeps_the_selected_game_selected(self):
        proxy = self._proxy()
        proxy.sort(0, Qt.SortOrder.AscendingOrder)
        selected = QPersistentModelIndex(proxy.index(1, 0))  # Bravo
        self.assertEqual(selected.data(), "Bravo")

        proxy.sort(0, Qt.SortOrder.DescendingOrder)

        self.assertEqual(selected.data(), "Bravo")
        self.assertEqual(selected.row(), 2)

    def test_new_library_keeps_the_chosen_sort(self):
        proxy = self._proxy()
        proxy.sort(0, Qt.SortOrder.DescendingOrder)

        proxy.sourceModel().set_library(FAKE_LIBRARY + [{"name": "Echo", "system": "nes"}])

        self.assertEqual(self._ordered_names(proxy), ["Echo", "Delta", "Charlie", "Bravo", "Alpha"])

    def test_recent_view_survives_header_sorts_and_leaving_it(self):
        proxy = self._proxy()
        proxy.sort(0, Qt.SortOrder.AscendingOrder)
        proxy.set_system_filter("__recent__")
        proxy.sort(0, Qt.SortOrder.AscendingOrder)  # a header click while in the view
        self.assertEqual(self._ordered_names(proxy), ["Bravo", "Alpha"])

        proxy.set_system_filter("")

        self.assertEqual(self._ordered_names(proxy), ["Alpha", "Bravo", "Charlie", "Delta"])
        self.assertEqual(proxy.sortColumn(), -1)

    def test_refresh_rom_signals_the_rows_new_position(self):
        proxy = self._proxy()
        proxy.sort(0, Qt.SortOrder.DescendingOrder)
        model = proxy.sourceModel()
        bravo = next(rom for rom in model.library if rom["name"] == "Bravo")
        changed = []
        model.dataChanged.connect(lambda top_left, *_: changed.append(top_left.row()))

        model.refresh_rom(bravo)

        self.assertEqual(changed, [model.library.index(bravo)])

    def test_switching_views_does_not_compare_rows_through_data(self):
        # Regression guard: a proxy-side sort calls data() for every pairwise
        # comparison (hundreds of thousands of Python calls at 20k games).
        class CountingModel(LibraryModel):
            calls = 0

            def data(self, index, role=Qt.ItemDataRole.DisplayRole):
                CountingModel.calls += 1
                return super().data(index, role)

        systems = ("nes", "snes", "gb")
        library = [{"name": f"Game {i:05d}", "system": systems[i % 3]} for i in range(5000)]
        proxy = LibraryFilterProxyModel()
        proxy.setSourceModel(CountingModel(library, self.SYSTEMS))

        proxy.sort(0, Qt.SortOrder.AscendingOrder)
        for key in ("nes", "", "snes", "__recent__", "gb", ""):
            proxy.set_system_filter(key)

        self.assertLess(CountingModel.calls, 100)
        self.assertEqual(proxy.index(0, 0).data(), "Game 00000")


if __name__ == "__main__":
    unittest.main()
