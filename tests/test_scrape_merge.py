"""Tests for MainWindow._merge_scrape_result (G5 scan/scrape race guard).

The scrape worker runs against a snapshot of the library taken when the scrape
began. If a rescan or removal lands while the (multi-minute) scrape runs, the
result must be merged onto the *current* library by path rather than replacing
it wholesale. These exercise that merge in isolation via a lightweight stub host.
"""

import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: F401  (import guard only)

    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


class _StubHost:
    def __init__(self, library):
        self.library = library


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class ScrapeMergeTests(unittest.TestCase):
    def _merge(self, host, updated):
        return MainWindow._merge_scrape_result(host, updated)

    def test_overlays_media_and_metadata_by_path(self):
        host = _StubHost([{"path": "/roms/a.nes", "name": "A"}])
        updated = [{
            "path": "/roms/a.nes", "name": "A",
            "media": {"boxart": "/cache/a.png"},
            "metadata": {"genre": "Platformer"},
        }]
        self._merge(host, updated)
        self.assertEqual(host.library[0]["media"], {"boxart": "/cache/a.png"})
        self.assertEqual(host.library[0]["metadata"], {"genre": "Platformer"})

    def test_concurrent_addition_is_preserved(self):
        # A rescan added /roms/b.nes after the scrape snapshot was taken; the
        # scrape result (which never saw it) must not drop it.
        host = _StubHost([
            {"path": "/roms/a.nes", "name": "A"},
            {"path": "/roms/b.nes", "name": "B"},  # added mid-scrape
        ])
        updated = [{"path": "/roms/a.nes", "name": "A", "media": {"boxart": "/cache/a.png"}}]
        self._merge(host, updated)
        paths = [e["path"] for e in host.library]
        self.assertEqual(paths, ["/roms/a.nes", "/roms/b.nes"])
        self.assertNotIn("media", host.library[1])

    def test_result_for_removed_path_is_ignored(self):
        # /roms/gone.nes was removed mid-scrape; its scraped result is dropped.
        host = _StubHost([{"path": "/roms/a.nes", "name": "A"}])
        updated = [
            {"path": "/roms/a.nes", "name": "A", "media": {"boxart": "/cache/a.png"}},
            {"path": "/roms/gone.nes", "name": "Gone", "media": {"boxart": "/cache/g.png"}},
        ]
        self._merge(host, updated)
        self.assertEqual(len(host.library), 1)
        self.assertEqual(host.library[0]["path"], "/roms/a.nes")

    def test_untouched_entries_keep_existing_media(self):
        host = _StubHost([{"path": "/roms/a.nes", "name": "A", "media": {"boxart": "/old.png"}}])
        # Scrape found nothing new for it (no media key).
        self._merge(host, [{"path": "/roms/a.nes", "name": "A"}])
        self.assertEqual(host.library[0]["media"], {"boxart": "/old.png"})


if __name__ == "__main__":
    unittest.main()
