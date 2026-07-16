import copy
import sys
import tempfile
import unittest
from pathlib import Path

from retrovault.core import launch
from retrovault.core.config import DEFAULT_CONFIG


class LaunchCommandTests(unittest.TestCase):
    def setUp(self):
        self.rom = {
            "name": "Mario Kart 64",
            "path": r"C:\ROMs\Nintendo 64\Mario Kart 64.z64",
            "system": "n64",
            "ext": ".z64",
        }
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config["emulators"]["n64"] = {
            "path": r'"C:\Emulators\Project64\Project64.exe"',
            "args": '"{rom}"',
        }

    def test_windows_command_preserves_rom_path_with_spaces(self):
        cmd, error = launch.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(error)
        self.assertEqual(
            cmd,
            [
                r"C:\Emulators\Project64\Project64.exe",
                r"C:\ROMs\Nintendo 64\Mario Kart 64.z64",
            ],
        )

    def test_windows_command_keeps_extra_args(self):
        self.config["emulators"]["n64"]["args"] = "--fullscreen \"{rom}\""

        cmd, error = launch.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(error)
        self.assertEqual(cmd[1:], ["--fullscreen", self.rom["path"]])

    def test_missing_emulator_returns_error(self):
        self.config["emulators"]["n64"]["path"] = ""

        cmd, error = launch.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(cmd)
        self.assertIn("No emulator configured", error)

    @unittest.skipUnless(sys.platform == "win32", "resolves a Windows working directory via host pathlib")
    def test_windows_launch_details_use_emulator_directory(self):
        cmd, error = launch.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        params, working_dir = launch._windows_launch_details(cmd)

        self.assertIsNone(error)
        self.assertIn('"C:\\ROMs\\Nintendo 64\\Mario Kart 64.z64"', params)
        self.assertEqual(working_dir, r"C:\Emulators\Project64")

    def test_profile_args_are_used_when_system_args_are_empty(self):
        self.config["emulators"]["n64"]["args"] = ""
        self.config["emulators"]["n64"]["profile"] = "project64"

        cmd, error = launch.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(error)
        self.assertEqual(cmd[1:], [self.rom["path"]])

    def test_validate_launch_requires_existing_rom(self):
        error = launch.validate_launch(self.rom, self.config)

        self.assertIn("ROM file not found", error)

    def test_validate_launch_accepts_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rom_path = root / "game.z64"
            emu_path = root / "Project64.exe"
            rom_path.write_bytes(b"rom")
            emu_path.write_bytes(b"exe")
            self.rom["path"] = str(rom_path)
            self.config["emulators"]["n64"]["path"] = str(emu_path)

            error = launch.validate_launch(self.rom, self.config)

        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
