"""libretro-thumbnails provider + scrape_library batch (implementation plan 1b).

Account-free, name-matched box art. All tests run offline against a fake
transport — no live network.
"""

import tempfile
import unittest
from pathlib import Path

from retrovault.core import media
from retrovault.providers import scraper


class FakeTransport:
    """Serves bytes for a known set of URLs; 404s (raises) for anything else."""

    def __init__(self, available):
        self.available = set(available)
        self.requested = []

    def get_bytes(self, url):
        self.requested.append(url)
        if url in self.available:
            return b"\x89PNG\r\n\x1a\n" + b"fakeimage"
        raise FileNotFoundError(url)

    def get_json(self, url, params):
        return {}


class LibretroClientTests(unittest.TestCase):
    def test_normalize_name_substitutes_unsafe_chars(self):
        self.assertEqual(scraper.LibretroThumbnailsClient.normalize_name("Ratchet & Clank"), "Ratchet _ Clank")
        self.assertEqual(scraper.LibretroThumbnailsClient.normalize_name("Where/Is:It?"), "Where_Is_It_")

    def test_find_game_builds_named_urls(self):
        client = scraper.LibretroThumbnailsClient(FakeTransport([]))
        info = client.find_game("gbc", name="Pokemon - Crystal Version (USA)")
        self.assertIsNotNone(info)
        self.assertEqual(info.metadata, {})
        self.assertIn("Nintendo%20-%20Game%20Boy%20Color", info.media_urls["boxart"])
        self.assertIn("Named_Boxarts", info.media_urls["boxart"])
        self.assertIn("Pokemon%20-%20Crystal%20Version%20%28USA%29.png", info.media_urls["boxart"])
        self.assertIn("Named_Snaps", info.media_urls["screenshot"])

    def test_find_game_none_for_unknown_system_or_no_name(self):
        client = scraper.LibretroThumbnailsClient(FakeTransport([]))
        self.assertIsNone(client.find_game("dreamcast", name="X"))
        self.assertIsNone(client.find_game("gbc", name=None))

    def test_fetch_media_fails_soft_on_missing(self):
        client = scraper.LibretroThumbnailsClient(FakeTransport([]))
        self.assertIsNone(client.fetch_media("https://example/missing.png"))


class BuildClientTests(unittest.TestCase):
    def test_defaults_to_libretro(self):
        self.assertIsInstance(scraper.build_client({}, FakeTransport([])), scraper.LibretroThumbnailsClient)

    def test_libretro_explicit(self):
        cfg = {"scraper": {"provider": "libretro"}}
        self.assertIsInstance(scraper.build_client(cfg, FakeTransport([])), scraper.LibretroThumbnailsClient)

    def test_screenscraper_when_selected(self):
        cfg = {"scraper": {"provider": "screenscraper"}}
        self.assertIsInstance(scraper.build_client(cfg, FakeTransport([])), scraper.ScreenScraperClient)


class ScrapeLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _rom(self, name="Pokemon - Crystal Version (USA)", system="gbc"):
        return {"name": name, "system": system, "path": "", "ext": ".gbc"}

    def _client_with_boxart(self, rom):
        boxart_url = scraper.LibretroThumbnailsClient(FakeTransport([])).find_game(
            rom["system"], name=rom["name"]
        ).media_urls["boxart"]
        return scraper.LibretroThumbnailsClient(FakeTransport([boxart_url])), boxart_url

    def test_populates_media_onto_entries(self):
        rom = self._rom()
        client, boxart_url = self._client_with_boxart(rom)
        progress = []
        out = scraper.scrape_library(
            [rom], {}, client, media_base=self.base,
            on_progress=lambda d, t: progress.append((d, t)),
        )
        self.assertEqual(len(out), 1)
        self.assertIn("boxart", out[0]["media"])
        self.assertTrue(Path(out[0]["media"]["boxart"]).is_file())
        self.assertEqual(progress, [(1, 1)])

    def test_skips_entries_that_already_have_media_unless_forced(self):
        rom = self._rom()
        # Pre-create the boxart so has_media() is True.
        boxart = media.media_paths_for(rom, self.base)["boxart"]
        boxart.parent.mkdir(parents=True, exist_ok=True)
        boxart.write_bytes(b"existing")
        client, _ = self._client_with_boxart(rom)

        scraper.scrape_library([rom], {}, client, media_base=self.base)
        self.assertEqual(client.transport.requested, [])  # skipped, no network

        scraper.scrape_library([rom], {}, client, media_base=self.base, force=True)
        self.assertTrue(client.transport.requested)  # forced -> did fetch

    def test_cancel_leaves_remaining_entries_untouched(self):
        roms = [self._rom(name=f"Game {i}") for i in range(3)]
        client = scraper.LibretroThumbnailsClient(FakeTransport([]))
        out = scraper.scrape_library(
            roms, {}, client, media_base=self.base,
            should_cancel=lambda: True,  # cancel before the first entry
        )
        self.assertEqual(len(out), 3)
        self.assertTrue(all("media" not in e for e in out))


if __name__ == "__main__":
    unittest.main()
