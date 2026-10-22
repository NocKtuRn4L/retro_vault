"""libretro-thumbnails provider + scrape_library batch (implementation plan 1b).

Account-free, name-matched box art. All tests run offline against a fake
transport or a loopback-only HTTP server — no live network.
"""

import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

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
        all_media = {"scraper": {"media": ["boxart", "logo", "screenshot"]}}
        client = scraper.LibretroThumbnailsClient(FakeTransport([]), all_media)
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


GBC_BOXARTS = "https://thumbnails.libretro.com/Nintendo%20-%20Game%20Boy%20Color/Named_Boxarts"
# Trimmed from a real thumbnails.libretro.com listing (Apache autoindex).
GBC_INDEX = b"""<html><head><title>Index of /Nintendo - Game Boy Color/Named_Boxarts</title></head><body>
<table><tr><th><a href="?C=N;O=D">Name</a></th></tr>
<tr><td><a href="/Nintendo%20-%20Game%20Boy%20Color/">Parent Directory</a></td></tr>
<tr><td><a href="Pokemon%20-%20Crystal%20Version%20(USA).png">Pokemon - Crystal Version (USA).png</a></td></tr>
<tr><td><a href="Tom%20_%20Jerry%20(USA).png">Tom _ Jerry (USA).png</a></td></tr>
<tr><td><a href="RoboCop%20Versus%20The%20Terminator%20(USA).png">RoboCop Versus The Terminator (USA).png</a></td></tr>
<tr><td><a href="Wario%20Land%203%20(World)%20(En,Ja).png">Wario Land 3 (World) (En,Ja).png</a></td></tr>
</table></body></html>"""


class IndexTransport(FakeTransport):
    """FakeTransport that also serves the GBC box-art directory listing."""

    def __init__(self, available, index=GBC_INDEX):
        super().__init__(available)
        self.index = index

    def get_bytes(self, url):
        if url == GBC_BOXARTS + "/" and self.index is not None:
            self.requested.append(url)
            return self.index
        return super().get_bytes(url)


class LibretroIndexTests(unittest.TestCase):
    def test_only_images_in_the_listing_are_requested(self):
        transport = IndexTransport([])
        client = scraper.LibretroThumbnailsClient(transport)

        crystal = client.find_game("gbc", name="Pokemon - Crystal Version (USA)")
        missing = client.find_game("gbc", name="Not A Real Game (USA)")
        jerry = client.find_game("gbc", name="Tom & Jerry (USA)")

        self.assertEqual(crystal.media_urls, {
            "boxart": GBC_BOXARTS + "/Pokemon%20-%20Crystal%20Version%20%28USA%29.png",
        })
        self.assertEqual(missing.media_urls, {})
        self.assertIn("Tom%20_%20Jerry", jerry.media_urls["boxart"])
        self.assertEqual(transport.requested, [GBC_BOXARTS + "/"])  # listing read once

    def test_name_differing_only_in_case_uses_the_servers_spelling(self):
        client = scraper.LibretroThumbnailsClient(IndexTransport([]))

        info = client.find_game("gbc", name="RoboCop versus The Terminator (USA)")

        self.assertIn("RoboCop%20Versus%20The%20Terminator", info.media_urls["boxart"])

    def test_unreadable_listing_falls_back_to_optimistic_urls(self):
        transport = IndexTransport([], index=None)
        client = scraper.LibretroThumbnailsClient(transport)

        first = client.find_game("gbc", name="Some Game (USA)")
        client.find_game("gbc", name="Other Game (USA)")

        self.assertEqual(first.media_urls, {"boxart": GBC_BOXARTS + "/Some%20Game%20%28USA%29.png"})
        self.assertEqual(transport.requested, [GBC_BOXARTS + "/"])  # failure cached, not retried

    def test_does_not_hash_roms(self):
        with tempfile.TemporaryDirectory() as tmp:
            rom_file = Path(tmp) / "Pokemon - Crystal Version (USA).zip"
            rom_file.write_bytes(b"PK" + b"\0" * 64)
            rom = {"name": rom_file.stem, "system": "gbc", "path": str(rom_file), "ext": ".zip"}
            client = scraper.LibretroThumbnailsClient(IndexTransport([GBC_BOXARTS + "/Pokemon%20-%20Crystal%20Version%20%28USA%29.png"]))

            with mock.patch.object(scraper, "rom_hashes", side_effect=AssertionError("hashed")):
                result = scraper.scrape_rom(rom, {}, client, media_base=Path(tmp) / "media")

            self.assertEqual(set(result["media"]), {"boxart"})


class ParallelScrapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _roms(self, count):
        return [{"name": f"Game {i:03d} (USA)", "system": "gbc", "path": "", "ext": ".zip"} for i in range(count)]

    def _client(self, roms, missing=()):
        names = [rom["name"] for rom in roms if rom["name"] not in missing]
        index = "".join(f'<a href="{name}.png">x</a>' for name in names).encode()
        urls = [scraper.LibretroThumbnailsClient(FakeTransport([])).find_game("gbc", name=n).media_urls["boxart"]
                for n in names]
        return scraper.LibretroThumbnailsClient(IndexTransport(urls, index=index))

    def test_results_keep_library_order_and_progress_counts_up(self):
        roms = self._roms(40)
        client = self._client(roms, missing={"Game 007 (USA)"})
        progress = []

        out = scraper.scrape_library(roms, {}, client, media_base=self.base,
                                     on_progress=lambda done, total: progress.append((done, total)))

        self.assertGreater(client.max_workers, 1)
        self.assertEqual([e["name"] for e in out], [r["name"] for r in roms])
        self.assertNotIn("media", out[7])
        self.assertTrue(all(Path(e["media"]["boxart"]).is_file() for i, e in enumerate(out) if i != 7))
        self.assertEqual(progress, [(n, 40) for n in range(1, 41)])

    def test_rescrape_links_covers_left_by_an_interrupted_run(self):
        roms = self._roms(3)
        cover = media.media_paths_for(roms[1], self.base)["boxart"]
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(b"downloaded before the app quit")
        client = self._client(roms)

        out = scraper.scrape_library(roms, {}, client, media_base=self.base)

        self.assertEqual(out[1]["media"], {"boxart": str(cover)})
        self.assertEqual(cover.read_bytes(), b"downloaded before the app quit")
        self.assertNotIn(scraper.LibretroThumbnailsClient(FakeTransport([])).find_game(
            "gbc", name=roms[1]["name"]).media_urls["boxart"], client.transport.requested)

    def test_cancel_mid_run_keeps_finished_entries_and_leaves_the_rest(self):
        roms = self._roms(30)
        client = self._client(roms)
        calls = 0

        def should_cancel():
            nonlocal calls
            calls += 1
            return calls > 10

        out = scraper.scrape_library(roms, {}, client, media_base=self.base, should_cancel=should_cancel)

        self.assertEqual(len(out), 30)
        self.assertTrue(all("media" in e for e in out[:10]))
        self.assertTrue(all("media" not in e for e in out[10:]))


class _ThumbnailHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive

    def do_GET(self):  # noqa: N802 - http.server API
        self.server.connections.add(self.client_address)
        if self.path == "/moved.png":
            self.send_response(301)
            self.send_header("Location", "/a.png")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"PNG:" + self.path.encode() if self.path != "/missing.png" else b"not found"
        self.send_response(200 if self.path != "/missing.png" else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class UrllibTransportTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ThumbnailHandler)
        self.server.connections = set()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        patcher = mock.patch.object(scraper.urllib.request, "getproxies", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reuses_one_connection_per_thread(self):
        transport = scraper.UrllibTransport(timeout=5)

        bodies = [transport.get_bytes(f"{self.base}/{name}.png") for name in ("a", "b", "c")]

        self.assertEqual(bodies, [b"PNG:/a.png", b"PNG:/b.png", b"PNG:/c.png"])
        self.assertEqual(len(self.server.connections), 1)

    def test_missing_image_raises_http_error_and_connection_survives(self):
        transport = scraper.UrllibTransport(timeout=5)

        with self.assertRaises(urllib.error.HTTPError) as caught:
            transport.get_bytes(f"{self.base}/missing.png")
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(transport.get_bytes(f"{self.base}/a.png"), b"PNG:/a.png")
        self.assertEqual(len(self.server.connections), 1)

    def test_follows_redirects(self):
        transport = scraper.UrllibTransport(timeout=5)

        self.assertEqual(transport.get_bytes(f"{self.base}/moved.png"), b"PNG:/a.png")


if __name__ == "__main__":
    unittest.main()
