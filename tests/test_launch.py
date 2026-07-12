import copy
import tempfile
import unittest
from pathlib import Path

import launcher


class LaunchCommandTests(unittest.TestCase):
    def setUp(self):
        self.rom = {
            "name": "Mario Kart 64",
            "path": r"C:\ROMs\Nintendo 64\Mario Kart 64.z64",
            "system": "n64",
            "ext": ".z64",
        }
        self.config = copy.deepcopy(launcher.DEFAULT_CONFIG)
        self.config["emulators"]["n64"] = {
            "path": r'"C:\Emulators\Project64\Project64.exe"',
            "args": '"{rom}"',
        }

    def test_windows_command_preserves_rom_path_with_spaces(self):
        cmd, error = launcher.build_launch_command(self.rom, self.config, platform="win32", validate=False)

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

        cmd, error = launcher.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(error)
        self.assertEqual(cmd[1:], ["--fullscreen", self.rom["path"]])

    def test_missing_emulator_returns_error(self):
        self.config["emulators"]["n64"]["path"] = ""

        cmd, error = launcher.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(cmd)
        self.assertIn("No emulator configured", error)

    def test_windows_launch_details_use_emulator_directory(self):
        cmd, error = launcher.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        params, working_dir = launcher._windows_launch_details(cmd)

        self.assertIsNone(error)
        self.assertIn('"C:\\ROMs\\Nintendo 64\\Mario Kart 64.z64"', params)
        self.assertEqual(working_dir, r"C:\Emulators\Project64")

    def test_profile_args_are_used_when_system_args_are_empty(self):
        self.config["emulators"]["n64"]["args"] = ""
        self.config["emulators"]["n64"]["profile"] = "project64"

        cmd, error = launcher.build_launch_command(self.rom, self.config, platform="win32", validate=False)

        self.assertIsNone(error)
        self.assertEqual(cmd[1:], [self.rom["path"]])

    def test_migrate_config_deep_merges_nested_defaults(self):
        migrated = launcher.migrate_config({"emulators": {"n64": {"path": "Project64.exe"}}})

        self.assertIn("nes", migrated["emulators"])
        self.assertEqual(migrated["emulators"]["n64"]["args"], "{rom}")
        self.assertEqual(migrated["emulators"]["n64"]["profile"], "custom")
        self.assertIn("project64", migrated["emulator_profiles"])
        self.assertEqual(migrated["setup"]["mode"], "easy")
        self.assertFalse(migrated["setup"]["completed"])

    def test_validate_launch_requires_existing_rom(self):
        error = launcher.validate_launch(self.rom, self.config)

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

            error = launcher.validate_launch(self.rom, self.config)

        self.assertIsNone(error)

    def test_apply_recommended_emulator_sets_profile_args_and_path(self):
        updated = launcher.apply_recommended_emulator(self.config, "psx", path=r"C:\Emulators\duckstation.exe")

        self.assertEqual(updated["emulators"]["psx"]["profile"], "duckstation")
        self.assertEqual(updated["emulators"]["psx"]["args"], '"{rom}"')
        self.assertEqual(updated["emulators"]["psx"]["path"], r"C:\Emulators\duckstation.exe")
        self.assertEqual(self.config["emulators"]["psx"]["path"], "")

    def test_get_recommended_emulator_returns_expected_choice(self):
        recommendation = launcher.get_recommended_emulator("n64")

        self.assertEqual(recommendation["name"], "Rosalie's Mupen GUI")
        self.assertIn("github.com/Rosalie241/RMG", recommendation["url"])

    def test_load_test_rom_manifest_returns_defaults(self):
        manifest = launcher.load_test_rom_manifest(path="Z:\\does-not-exist\\test_roms.json")

        self.assertIn("n64", manifest)
        self.assertEqual(manifest["n64"]["label"], "Nintendo 64 smoke ROM")

    def test_audit_test_roms_reports_missing_roms(self):
        manifest = {"n64": {"path": ""}}

        results = launcher.audit_test_roms(self.config, manifest)

        self.assertEqual(results[0]["system"], "n64")
        self.assertEqual(results[0]["status"], "missing_rom")

    def test_audit_test_roms_reports_ok_for_valid_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rom_path = root / "game.z64"
            emu_path = root / "Project64.exe"
            rom_path.write_bytes(b"rom")
            emu_path.write_bytes(b"exe")
            self.config["emulators"]["n64"]["path"] = str(emu_path)
            manifest = {"n64": {"path": str(rom_path)}}

            results = launcher.audit_test_roms(self.config, manifest)

        self.assertEqual(results[0]["status"], "ok")
        self.assertIn(str(emu_path), results[0]["message"])


if __name__ == "__main__":
    unittest.main()
