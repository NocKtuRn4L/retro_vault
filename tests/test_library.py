import tempfile
import unittest
from pathlib import Path

from retrovault.core import library


class MergeScanTests(unittest.TestCase):
    def _entry(self, path, system="nes", **extra):
        base = {"name": Path(path).stem, "path": path, "system": system, "ext": ".nes"}
        base.update(extra)
        return base

    def test_preserves_enriched_fields_across_rescan(self):
        old = [self._entry("/roms/mario.nes", favorite=True, play_seconds=3600,
                            media={"boxart": "/cache/mario.png"})]
        # A fresh scan yields only the disk-derived fields.
        new = [self._entry("/roms/mario.nes")]

        merged = library.merge_scan(old, new)

        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["favorite"])
        self.assertEqual(merged[0]["play_seconds"], 3600)
        self.assertEqual(merged[0]["media"], {"boxart": "/cache/mario.png"})

    def test_scan_fields_take_precedence_over_stale_copy(self):
        # Old entry has a stale system; the fresh scan value must win.
        old = [self._entry("/roms/game.sfc", system="nes", favorite=True)]
        new = [self._entry("/roms/game.sfc", system="snes")]

        merged = library.merge_scan(old, new)

        self.assertEqual(merged[0]["system"], "snes")
        self.assertTrue(merged[0]["favorite"])

    def test_drops_enrichment_for_removed_paths(self):
        old = [self._entry("/roms/gone.nes", favorite=True)]
        new = [self._entry("/roms/present.nes")]

        merged = library.merge_scan(old, new)

        paths = {e["path"] for e in merged}
        self.assertEqual(paths, {"/roms/present.nes"})
        self.assertNotIn("favorite", merged[0])

    def test_new_games_pass_through_untouched(self):
        merged = library.merge_scan([], [self._entry("/roms/fresh.nes")])
        self.assertEqual(len(merged), 1)
        self.assertNotIn("favorite", merged[0])

    def test_handles_none_and_missing_paths(self):
        # None inputs and entries without a path must not raise.
        self.assertEqual(library.merge_scan(None, None), [])
        old = [{"name": "no path", "system": "nes"}]
        new = [self._entry("/roms/ok.nes")]
        merged = library.merge_scan(old, new)
        self.assertEqual(len(merged), 1)


class ScanRomsTests(unittest.TestCase):
    def _config(self, rom_dir):
        return {
            "rom_dirs": [str(rom_dir)],
            "systems": {
                "nes": {"name": "NES", "short": "NES", "extensions": [".nes"]},
                "snes": {"name": "SNES", "short": "SNES", "extensions": [".sfc", ".smc"]},
            },
        }

    def test_scan_maps_extensions_to_systems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mario.nes").write_bytes(b"x")
            (root / "zelda.sfc").write_bytes(b"x")
            (root / "notes.txt").write_bytes(b"x")  # ignored: unknown ext
            (root / "sub").mkdir()
            (root / "sub" / "metroid.smc").write_bytes(b"x")  # recursive

            lib = library.scan_roms(self._config(root))

            by_name = {e["name"]: e for e in lib}
            self.assertEqual(set(by_name), {"mario", "zelda", "metroid"})
            self.assertEqual(by_name["mario"]["system"], "nes")
            self.assertEqual(by_name["zelda"]["system"], "snes")
            self.assertEqual(by_name["metroid"]["system"], "snes")

    def test_scan_skips_missing_dirs(self):
        lib = library.scan_roms({"rom_dirs": ["/no/such/dir"],
                                 "systems": {"nes": {"extensions": [".nes"]}}})
        self.assertEqual(lib, [])

    def test_rescan_then_merge_keeps_enrichment(self):
        # End-to-end: enrich a scanned entry, rescan, merge — enrichment survives.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mario.nes").write_bytes(b"x")
            config = self._config(root)

            first = library.scan_roms(config)
            first[0]["favorite"] = True
            first[0]["play_seconds"] = 120

            second = library.scan_roms(config)
            merged = library.merge_scan(first, second)

            self.assertTrue(merged[0]["favorite"])
            self.assertEqual(merged[0]["play_seconds"], 120)


if __name__ == "__main__":
    unittest.main()
