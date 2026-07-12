import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retrovault.core import launch
from retrovault.core.config import DEFAULT_CONFIG, migrate_config


class FlatpakLaunchTests(unittest.TestCase):
    def setUp(self):
        launch._reset_flatpak_cache()
        self.rom = {
            "name": "Mario Kart 64",
            "path": r"C:\ROMs\Nintendo 64\Mario Kart 64.z64",
            "system": "n64",
            "ext": ".z64",
        }
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config["emulators"]["n64"] = {
            "path": "",
            "args": '"{rom}"',
            "profile": "custom",
            "launch_type": "flatpak",
            "flatpak_id": "com.github.Rosalie241.RMG",
        }

    def tearDown(self):
        launch._reset_flatpak_cache()

    def _with_real_rom(self, tmp):
        root = Path(tmp)
        rom_path = root / "game.z64"
        rom_path.write_bytes(b"rom")
        self.rom["path"] = str(rom_path)

    def test_build_flatpak_command(self):
        cmd, error = launch.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(error)
        self.assertEqual(
            cmd,
            ["flatpak", "run", "com.github.Rosalie241.RMG", self.rom["path"]],
        )

    @patch("retrovault.core.launch.shutil.which")
    def test_validate_flatpak_not_installed_binary(self, mock_which):
        mock_which.return_value = None

        with tempfile.TemporaryDirectory() as tmp:
            self._with_real_rom(tmp)
            error = launch.validate_launch(self.rom, self.config)

        self.assertEqual(error, "flatpak is not installed")

    @patch("retrovault.core.launch.subprocess.run")
    @patch("retrovault.core.launch.shutil.which")
    def test_validate_flatpak_app_not_installed(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/flatpak"
        mock_run.return_value = unittest.mock.Mock(returncode=1)

        with tempfile.TemporaryDirectory() as tmp:
            self._with_real_rom(tmp)
            error = launch.validate_launch(self.rom, self.config)

        self.assertEqual(error, "Flatpak app not installed: com.github.Rosalie241.RMG")

    @patch("retrovault.core.launch.subprocess.run")
    @patch("retrovault.core.launch.shutil.which")
    def test_validate_flatpak_caches_info_result(self, mock_which, mock_run):
        mock_which.return_value = "/usr/bin/flatpak"
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            self._with_real_rom(tmp)
            error1 = launch.validate_launch(self.rom, self.config)
            error2 = launch.validate_launch(self.rom, self.config)

        self.assertIsNone(error1)
        self.assertIsNone(error2)
        self.assertEqual(mock_run.call_count, 1)


class BinaryLaunchTests(unittest.TestCase):
    def setUp(self):
        self.rom = {
            "name": "Metroid Prime",
            "path": "/roms/gamecube/metroid.iso",
            "system": "n64",
            "ext": ".iso",
        }
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config["emulators"]["n64"] = {
            "path": "mgba-qt",
            "args": "{rom}",
            "profile": "custom",
            "launch_type": "binary",
            "flatpak_id": "",
        }

    @patch("retrovault.core.launch.shutil.which")
    def test_build_binary_command_uses_resolved_path(self, mock_which):
        mock_which.return_value = "/usr/bin/mgba-qt"

        cmd, error = launch.build_launch_command(self.rom, self.config, platform="linux", validate=False)

        self.assertIsNone(error)
        self.assertEqual(cmd[0], "/usr/bin/mgba-qt")
        self.assertEqual(cmd[1:], [self.rom["path"]])

    @patch("retrovault.core.launch.shutil.which")
    def test_validate_binary_not_on_path(self, mock_which):
        mock_which.return_value = None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rom_path = root / "game.iso"
            rom_path.write_bytes(b"rom")
            self.rom["path"] = str(rom_path)
            error = launch.validate_launch(self.rom, self.config)

        self.assertIn("Emulator command not found on PATH", error)
        self.assertIn("mgba-qt", error)

    @patch("retrovault.core.launch.shutil.which")
    def test_validate_binary_found_on_path(self, mock_which):
        mock_which.return_value = "/usr/bin/mgba-qt"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rom_path = root / "game.iso"
            rom_path.write_bytes(b"rom")
            self.rom["path"] = str(rom_path)
            error = launch.validate_launch(self.rom, self.config)

        self.assertIsNone(error)


class MigrateConfigLaunchTypeTests(unittest.TestCase):
    def test_migrate_config_adds_exe_defaults(self):
        migrated = migrate_config({})

        for system_key, emu in migrated["emulators"].items():
            self.assertEqual(emu["launch_type"], "exe", f"{system_key} launch_type mismatch")
            self.assertEqual(emu["flatpak_id"], "", f"{system_key} flatpak_id mismatch")

    def test_migrate_config_preserves_existing_launch_type(self):
        migrated = migrate_config({
            "emulators": {"n64": {"launch_type": "flatpak", "flatpak_id": "com.example.App"}}
        })

        self.assertEqual(migrated["emulators"]["n64"]["launch_type"], "flatpak")
        self.assertEqual(migrated["emulators"]["n64"]["flatpak_id"], "com.example.App")
        # Legacy systems untouched by the override still default to exe.
        self.assertEqual(migrated["emulators"]["snes"]["launch_type"], "exe")


if __name__ == "__main__":
    unittest.main()
