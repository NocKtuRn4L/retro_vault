import copy
import hashlib
import tempfile
import unittest
import zlib
from pathlib import Path

from retrovault.core import config
from retrovault.providers import scraper
from retrovault.providers.scraper import (
    GameInfo,
    Scraper,
    ScreenScraperClient,
    platform_id_for,
    rom_hashes,
    rom_header_size,
    scrape_rom,
)

# A representative jeuInfos.php response (trimmed to the fields we parse).
GAME_FIXTURE = {
    "response": {
        "jeu": {
            "id": "3",
            "noms": [{"region": "us", "text": "Super Mario World"}],
            "synopsis": [
                {"langue": "en", "text": "Mario travels to Dinosaur Land."},
                {"langue": "fr", "text": "Mario voyage au pays des dinosaures."},
            ],
            "genres": [
                {"noms": [{"langue": "en", "text": "Platform"}, {"langue": "fr", "text": "Plateforme"}]}
            ],
            "joueurs": {"text": "1-2"},
            "note": {"text": "18"},
            "dates": [
                {"region": "us", "text": "1991-08-13"},
                {"region": "jp", "text": "1990"},
            ],
            "medias": [
                {"type": "box-2D", "region": "eu", "url": "https://ss/boxart-eu.png", "format": "png"},
                {"type": "box-2D", "region": "us", "url": "https://ss/boxart-us.png", "format": "png"},
                {"type": "wheel", "region": "wor", "url": "https://ss/logo.png", "format": "png"},
                {"type": "ss", "region": "us", "url": "https://ss/screen.png", "format": "png"},
            ],
        }
    }
}

EMPTY_FIXTURE = {"response": {}}


class FakeTransport:
    """In-memory HttpTransport serving fixture JSON and fake image bytes.

    ``known_crc`` limits hash hits to lookups for that one CRC, so tests can tell
    a full-file hash from a header-stripped one.
    """

    def __init__(self, *, hash_response=None, name_response=None, media=None, known_crc=None):
        self.hash_response = hash_response
        self.name_response = name_response
        self.media = media or {}
        self.known_crc = known_crc
        self.calls = []

    def get_json(self, url, params):
        self.calls.append(dict(params))
        if params.get("crc") or params.get("md5"):
            if self.known_crc is not None and params.get("crc") != self.known_crc:
                return EMPTY_FIXTURE
            return self.hash_response if self.hash_response is not None else EMPTY_FIXTURE
        if params.get("romnom"):
            return self.name_response if self.name_response is not None else EMPTY_FIXTURE
        return EMPTY_FIXTURE

    def get_bytes(self, url):
        if url in self.media:
            return self.media[url]
        raise KeyError(url)


def _make_rom(tmp_dir, content=b"ROMDATA", name="Super Mario World", system="snes"):
    rom_path = Path(tmp_dir) / f"{name}.sfc"
    rom_path.write_bytes(content)
    return {"name": name, "path": str(rom_path), "system": system}


def _ines_header(trainer=False):
    """A 16-byte iNES header; flags 6 bit 2 marks a 512-byte trainer."""
    return b"NES\x1a" + bytes([2, 1, 0x04 if trainer else 0]) + bytes(9)


def _crc(data):
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


class PlatformMapTests(unittest.TestCase):
    def test_all_eight_systems_are_mapped(self):
        expected = {"nes", "snes", "gb", "gbc", "gba", "n64", "psx", "genesis"}
        self.assertTrue(expected.issubset(scraper.SCRAPER_DATA["platforms"].keys()))
        for system in expected:
            self.assertIsInstance(platform_id_for(system), int)

    def test_unknown_system_returns_none(self):
        self.assertIsNone(platform_id_for("dreamcast"))

    def test_media_types_cover_all_kinds(self):
        self.assertEqual(set(scraper.SCRAPER_DATA["media_types"]), {"boxart", "logo", "screenshot"})


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.client = ScreenScraperClient(FakeTransport(hash_response=GAME_FIXTURE), config={"scraper": {"region": "us"}})

    def test_find_game_parses_metadata(self):
        info = self.client.find_game("snes", crc="deadbeef")
        self.assertIsInstance(info, GameInfo)
        self.assertEqual(info.metadata["synopsis"], "Mario travels to Dinosaur Land.")
        self.assertEqual(info.metadata["genre"], "Platform")
        self.assertEqual(info.metadata["players"], "1-2")
        self.assertEqual(info.metadata["rating"], "18")
        self.assertEqual(info.metadata["year"], "1991")

    def test_find_game_prefers_configured_region_media(self):
        info = self.client.find_game("snes", crc="deadbeef")
        self.assertEqual(info.media_urls["boxart"], "https://ss/boxart-us.png")
        self.assertEqual(info.media_urls["logo"], "https://ss/logo.png")
        self.assertEqual(info.media_urls["screenshot"], "https://ss/screen.png")

    def test_find_game_sends_platform_id(self):
        transport = FakeTransport(hash_response=GAME_FIXTURE)
        ScreenScraperClient(transport).find_game("snes", crc="abc")
        self.assertEqual(transport.calls[0]["systemeid"], str(platform_id_for("snes")))
        self.assertEqual(transport.calls[0]["crc"], "abc")

    def test_no_result_returns_none(self):
        client = ScreenScraperClient(FakeTransport(hash_response=EMPTY_FIXTURE))
        self.assertIsNone(client.find_game("snes", crc="deadbeef"))

    def test_transport_error_fails_soft(self):
        class Boom:
            def get_json(self, url, params):
                raise RuntimeError("network down")

            def get_bytes(self, url):
                raise RuntimeError("network down")

        self.assertIsNone(ScreenScraperClient(Boom()).find_game("snes", crc="x"))

    def test_find_game_with_no_keys_returns_none_without_calling(self):
        transport = FakeTransport()
        self.assertIsNone(ScreenScraperClient(transport).find_game("snes"))
        self.assertEqual(transport.calls, [])

    def test_client_satisfies_scraper_protocol(self):
        self.assertIsInstance(ScreenScraperClient(FakeTransport()), Scraper)


class ScrapeRomTests(unittest.TestCase):
    def test_hash_hit_downloads_media_and_returns_metadata(self):
        media_bytes = {
            "https://ss/boxart-us.png": b"BOX",
            "https://ss/logo.png": b"LOGO",
            "https://ss/screen.png": b"SCREEN",
        }
        transport = FakeTransport(hash_response=GAME_FIXTURE, media=media_bytes)
        client = ScreenScraperClient(transport, config={"scraper": {"region": "us"}})
        with tempfile.TemporaryDirectory() as tmp_dir:
            rom = _make_rom(tmp_dir)
            media_base = Path(tmp_dir) / "media"
            all_media = {"scraper": {"media": ["boxart", "logo", "screenshot"]}}
            result = scrape_rom(rom, all_media, client, media_base=media_base)

            self.assertEqual(result["metadata"]["genre"], "Platform")
            self.assertEqual(set(result["media"]), {"boxart", "logo", "screenshot"})
            for kind, path_str in result["media"].items():
                self.assertTrue(Path(path_str).is_file(), kind)
            self.assertEqual(Path(result["media"]["boxart"]).read_bytes(), b"BOX")
        # Only the hash lookup ran (no name fallback needed).
        self.assertEqual(len(transport.calls), 1)

    def test_downloads_only_box_art_by_default(self):
        media_bytes = {
            "https://ss/boxart-us.png": b"BOX",
            "https://ss/logo.png": b"LOGO",
            "https://ss/screen.png": b"SCREEN",
        }
        transport = FakeTransport(hash_response=GAME_FIXTURE, media=media_bytes)
        client = ScreenScraperClient(transport, config={"scraper": {"region": "us"}})
        with tempfile.TemporaryDirectory() as tmp_dir:
            rom = _make_rom(tmp_dir)
            result = scrape_rom(rom, {}, client, media_base=Path(tmp_dir) / "media")

            self.assertEqual(set(result["media"]), {"boxart"})
            self.assertEqual(sorted(p.name for p in (Path(tmp_dir) / "media").rglob("*.png")),
                             [Path(result["media"]["boxart"]).name])

    def test_name_fallback_when_hash_misses(self):
        transport = FakeTransport(
            hash_response=EMPTY_FIXTURE,
            name_response=GAME_FIXTURE,
            media={
                "https://ss/boxart-us.png": b"BOX",
                "https://ss/logo.png": b"LOGO",
                "https://ss/screen.png": b"SCREEN",
            },
        )
        client = ScreenScraperClient(transport, config={"scraper": {"region": "us"}})
        with tempfile.TemporaryDirectory() as tmp_dir:
            rom = _make_rom(tmp_dir)
            result = scrape_rom(rom, {}, client, media_base=Path(tmp_dir) / "media")
            self.assertEqual(result["metadata"]["players"], "1-2")
            self.assertIn("boxart", result["media"])
        # Hash call (empty) then name fallback.
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(transport.calls[0].get("crc") or transport.calls[0].get("md5"))
        self.assertIn("romnom", transport.calls[1])

    def test_no_result_returns_empty_soft(self):
        transport = FakeTransport(hash_response=EMPTY_FIXTURE, name_response=EMPTY_FIXTURE)
        client = ScreenScraperClient(transport)
        with tempfile.TemporaryDirectory() as tmp_dir:
            rom = _make_rom(tmp_dir)
            result = scrape_rom(rom, {}, client, media_base=Path(tmp_dir) / "media")
        self.assertEqual(result, {"media": {}, "metadata": {}})

    def test_missing_media_bytes_skipped_but_metadata_kept(self):
        # Transport serves JSON but no image bytes -> media download fails soft.
        transport = FakeTransport(hash_response=GAME_FIXTURE, media={})
        client = ScreenScraperClient(transport, config={"scraper": {"region": "us"}})
        with tempfile.TemporaryDirectory() as tmp_dir:
            rom = _make_rom(tmp_dir)
            result = scrape_rom(rom, {}, client, media_base=Path(tmp_dir) / "media")
        self.assertEqual(result["media"], {})
        self.assertEqual(result["metadata"]["genre"], "Platform")

    def test_headered_nes_retries_with_header_stripped_hash(self):
        data = b"PRG" * 100
        # Only the header-free data is "on record"; the full-file hash misses.
        transport = FakeTransport(hash_response=GAME_FIXTURE, known_crc=_crc(data))
        client = ScreenScraperClient(transport, config={"scraper": {"region": "us"}})
        with tempfile.TemporaryDirectory() as tmp_dir:
            rom = _make_rom(tmp_dir, content=_ines_header() + data, system="nes")
            result = scrape_rom(rom, {}, client, media_base=Path(tmp_dir) / "media")
        self.assertEqual(result["metadata"]["genre"], "Platform")
        # Full-file hash, then the stripped hash hit; no name lookup needed.
        self.assertEqual([call.get("crc") for call in transport.calls], [_crc(_ines_header() + data), _crc(data)])

    def test_header_retry_runs_before_name_fallback(self):
        transport = FakeTransport(hash_response=EMPTY_FIXTURE, name_response=GAME_FIXTURE)
        client = ScreenScraperClient(transport, config={"scraper": {"region": "us"}})
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1 KiB of data behind a 512-byte copier header.
            rom = _make_rom(tmp_dir, content=bytes(512) + b"S" * 1024)
            result = scrape_rom(rom, {}, client, media_base=Path(tmp_dir) / "media")
        self.assertEqual(result["metadata"]["genre"], "Platform")
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(transport.calls[1]["crc"], _crc(b"S" * 1024))
        self.assertIn("romnom", transport.calls[2])


class HeaderSizeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _write(self, content):
        path = self.dir / "rom.bin"
        path.write_bytes(content)
        return path

    def test_ines_header(self):
        self.assertEqual(rom_header_size(self._write(_ines_header() + b"x" * 64), "nes"), 16)

    def test_ines_header_with_trainer(self):
        path = self._write(_ines_header(trainer=True) + bytes(512) + b"x" * 64)
        self.assertEqual(rom_header_size(path, "nes"), 528)

    def test_nes_without_magic_is_headerless(self):
        self.assertEqual(rom_header_size(self._write(b"x" * 64), "nes"), 0)

    def test_header_only_file_is_ignored(self):
        self.assertEqual(rom_header_size(self._write(_ines_header()), "nes"), 0)

    def test_snes_copier_header(self):
        self.assertEqual(rom_header_size(self._write(bytes(512 + 2048)), "snes"), 512)

    def test_snes_without_copier_header(self):
        self.assertEqual(rom_header_size(self._write(bytes(2048)), "snes"), 0)

    def test_other_systems_never_report_a_header(self):
        self.assertEqual(rom_header_size(self._write(_ines_header() + b"x" * 64), "gb"), 0)

    def test_missing_file(self):
        self.assertEqual(rom_header_size(self.dir / "missing.nes", "nes"), 0)


class HashTests(unittest.TestCase):
    def test_rom_hashes_match_known_values(self):
        content = b"hello world"
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "rom.nes"
            path.write_bytes(content)
            crc, md5 = rom_hashes(path)
        self.assertEqual(crc, f"{zlib.crc32(content) & 0xFFFFFFFF:08x}")
        self.assertEqual(len(md5), 32)

    def test_skip_hashes_only_the_data_after_the_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "rom.nes"
            path.write_bytes(_ines_header() + b"game data")
            crc, md5 = rom_hashes(path, skip=16)
        self.assertEqual(crc, _crc(b"game data"))
        self.assertEqual(md5, hashlib.md5(b"game data").hexdigest())

    def test_oversized_files_are_not_hashed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "big.iso"
            path.write_bytes(b"x" * 1024)
            self.assertEqual(rom_hashes(path, max_bytes=10), (None, None))

    def test_missing_file_returns_none(self):
        self.assertEqual(rom_hashes("/does/not/exist.nes"), (None, None))


class ConfigScraperBlockTests(unittest.TestCase):
    def test_default_config_has_scraper_block(self):
        block = config.DEFAULT_CONFIG["scraper"]
        self.assertEqual(block["provider"], "libretro")
        self.assertFalse(block["enabled"])
        self.assertEqual(block["region"], "us")

    def test_migrate_adds_scraper_block_and_preserves_user_values(self):
        migrated = config.migrate_config({"scraper": {"username": "me", "enabled": True}})
        self.assertEqual(migrated["scraper"]["username"], "me")
        self.assertTrue(migrated["scraper"]["enabled"])
        # Unspecified keys filled from defaults.
        self.assertEqual(migrated["scraper"]["provider"], "libretro")
        self.assertEqual(migrated["scraper"]["region"], "us")

    def test_migrate_adds_scraper_block_when_absent(self):
        migrated = config.migrate_config(copy.deepcopy({"rom_dirs": []}))
        self.assertIn("scraper", migrated)


if __name__ == "__main__":
    unittest.main()
