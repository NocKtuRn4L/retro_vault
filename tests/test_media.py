import tempfile
import unittest

from retrovault.core import media


class MediaPathTests(unittest.TestCase):
    def test_media_paths_for_builds_kind_paths_under_system(self):
        rom = {"name": "Super Mario World", "path": r"C:\roms\Super Mario World.sfc", "system": "snes"}
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = media.media_paths_for(rom, base=temp_dir)

        self.assertEqual(set(paths), {"boxart", "logo", "screenshot"})
        self.assertEqual(paths["boxart"].name, "Super Mario World.boxart.png")
        self.assertEqual(paths["boxart"].parent.name, "snes")
        self.assertEqual(paths["logo"].name, "Super Mario World.logo.png")
        self.assertEqual(paths["screenshot"].name, "Super Mario World.screenshot.png")

    def test_stem_comes_from_path_not_name(self):
        rom = {"name": "Display Name", "path": "/games/rom_file.gba", "system": "gba"}
        paths = media.media_paths_for(rom, base="/media")
        self.assertEqual(paths["boxart"].name, "rom_file.boxart.png")

    def test_falls_back_to_name_when_no_path(self):
        rom = {"name": "Some Game", "system": "nes"}
        paths = media.media_paths_for(rom, base="/media")
        self.assertEqual(paths["boxart"].name, "Some Game.boxart.png")

    def test_unsafe_characters_are_sanitized(self):
        rom = {"name": "A:B/C?D", "system": "nes"}
        paths = media.media_paths_for(rom, base="/media")
        # No reserved characters survive in the filename.
        self.assertNotIn(":", paths["boxart"].name)
        self.assertNotIn("?", paths["boxart"].name)

    def test_missing_system_uses_unknown(self):
        rom = {"name": "Orphan"}
        paths = media.media_paths_for(rom, base="/media")
        self.assertEqual(paths["boxart"].parent.name, "unknown")

    def test_has_media_reflects_disk_state(self):
        rom = {"name": "Zelda", "path": "/games/Zelda.nes", "system": "nes"}
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(media.has_media(rom, base=temp_dir))
            boxart = media.media_paths_for(rom, base=temp_dir)["boxart"]
            boxart.parent.mkdir(parents=True, exist_ok=True)
            boxart.write_bytes(b"PNG")
            self.assertTrue(media.has_media(rom, base=temp_dir))

    def test_media_dir_defaults_to_media_dir_constant(self):
        rom = {"name": "X", "path": "/g/X.nes", "system": "nes"}
        paths = media.media_paths_for(rom)
        self.assertEqual(paths["boxart"].parent, media.MEDIA_DIR / "nes")


if __name__ == "__main__":
    unittest.main()
