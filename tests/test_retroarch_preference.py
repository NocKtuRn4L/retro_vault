"""RetroArch-as-default-for-controller-mode routing (implementation plan 8b).

RetroArch's centralized controller autoconfig makes it the reliable seamless-pad
path, so it becomes the default whenever it's actually usable — without taking
over a fresh, RetroArch-less install's curated standalone emulators.
"""

import tempfile
import unittest
from pathlib import Path

from retrovault.core import launch


class UseRetroarchForTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ra = Path(self.tmp.name) / "retroarch.exe"
        self.ra.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def _cfg(self, **over):
        cfg = {
            "use_retroarch": False,
            "retroarch_path": str(self.ra),
            "retroarch_cores": {"nes": "nestopia_libretro"},
            "controller": {"prefer_retroarch": True},
        }
        cfg.update(over)
        return cfg

    def test_explicit_toggle_always_routes_retroarch(self):
        # use_retroarch keeps its meaning; validation reports any missing binary/core.
        cfg = self._cfg(use_retroarch=True, retroarch_path="", retroarch_cores={})
        self.assertTrue(launch.use_retroarch_for(cfg, "nes"))

    def test_prefer_routes_when_binary_and_core_present(self):
        self.assertTrue(launch.use_retroarch_for(self._cfg(), "nes"))

    def test_prefer_falls_back_when_binary_missing(self):
        cfg = self._cfg(retroarch_path=str(Path(self.tmp.name) / "nope.exe"))
        self.assertFalse(launch.use_retroarch_for(cfg, "nes"))

    def test_prefer_falls_back_when_no_core_for_system(self):
        self.assertFalse(launch.use_retroarch_for(self._cfg(), "psx"))

    def test_disabled_preference_uses_standalone(self):
        self.assertFalse(launch.use_retroarch_for(self._cfg(controller={"prefer_retroarch": False}), "nes"))

    def test_preference_defaults_on_when_unset(self):
        cfg = {"retroarch_path": str(self.ra), "retroarch_cores": {"nes": "nestopia_libretro"}}
        self.assertTrue(launch.use_retroarch_for(cfg, "nes"))


class BuildCommandRetroarchPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ra = Path(self.tmp.name) / "retroarch.exe"
        self.ra.write_bytes(b"x")
        self.rom_file = Path(self.tmp.name) / "game.nes"
        self.rom_file.write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def _cfg(self, prefer=True):
        return {
            "use_retroarch": False,
            "retroarch_path": str(self.ra),
            "retroarch_cores": {"nes": "nestopia_libretro"},
            "controller": {"prefer_retroarch": prefer},
            "systems": {"nes": {"extensions": [".nes"]}},
            "emulators": {"nes": {"path": "", "args": "{rom}"}},
            "emulator_profiles": {},
        }

    def test_prefer_builds_retroarch_command(self):
        rom = {"system": "nes", "path": str(self.rom_file)}
        cmd, err = launch.build_launch_command(rom, self._cfg(prefer=True))
        self.assertIsNone(err)
        self.assertEqual(cmd[0], str(self.ra))
        self.assertIn("-L", cmd)
        self.assertIn("nestopia_libretro", cmd)
        self.assertEqual(cmd[-1], str(self.rom_file))

    def test_disabled_falls_back_to_standalone_validation(self):
        # With the preference off and no standalone path, we get the standalone
        # "no emulator configured" error rather than a RetroArch command.
        rom = {"system": "nes", "path": str(self.rom_file)}
        cmd, err = launch.build_launch_command(rom, self._cfg(prefer=False))
        self.assertIsNone(cmd)
        self.assertIn("No emulator configured", err)


if __name__ == "__main__":
    unittest.main()
