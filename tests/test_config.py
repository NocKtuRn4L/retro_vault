import copy
import unittest

from retrovault.core import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(config.DEFAULT_CONFIG)

    def test_migrate_config_deep_merges_nested_defaults(self):
        migrated = config.migrate_config({"emulators": {"n64": {"path": "Project64.exe"}}})

        self.assertIn("nes", migrated["emulators"])
        self.assertEqual(migrated["emulators"]["n64"]["args"], "{rom}")
        self.assertEqual(migrated["emulators"]["n64"]["profile"], "custom")
        self.assertIn("project64", migrated["emulator_profiles"])
        self.assertEqual(migrated["setup"]["mode"], "easy")
        self.assertFalse(migrated["setup"]["completed"])

    def test_apply_recommended_emulator_sets_profile_args_and_path(self):
        updated = config.apply_recommended_emulator(self.config, "psx", path=r"C:\Emulators\duckstation.exe")

        self.assertEqual(updated["emulators"]["psx"]["profile"], "duckstation")
        self.assertEqual(updated["emulators"]["psx"]["args"], '"{rom}"')
        self.assertEqual(updated["emulators"]["psx"]["path"], r"C:\Emulators\duckstation.exe")
        self.assertEqual(self.config["emulators"]["psx"]["path"], "")

    def test_get_recommended_emulator_returns_expected_choice(self):
        recommendation = config.get_recommended_emulator("n64", platform_key="windows-x86_64")

        self.assertEqual(recommendation["name"], "Rosalie's Mupen GUI")
        self.assertIn("github.com/Rosalie241/RMG", recommendation["url"])

    def test_get_recommended_emulator_linux_aarch64_genesis_uses_retroarch(self):
        recommendation = config.get_recommended_emulator("genesis", platform_key="linux-aarch64")

        self.assertIn("RetroArch", recommendation["name"])

    def test_get_recommended_emulator_unknown_platform_falls_back_to_windows_table(self):
        unknown = config.get_recommended_emulator("n64", platform_key="totally-unknown-platform")
        windows = config.get_recommended_emulator("n64", platform_key="windows-x86_64")

        self.assertEqual(unknown, windows)
        self.assertEqual(unknown["name"], "Rosalie's Mupen GUI")

    def test_default_systems_loaded_from_json_has_all_keys_with_ascii_icons(self):
        expected_keys = {"nes", "snes", "gb", "gba", "n64", "psx", "genesis", "gbc"}

        self.assertEqual(set(config.DEFAULT_SYSTEMS.keys()), expected_keys)
        for system_key, system_def in config.DEFAULT_SYSTEMS.items():
            icon = system_def["icon"]
            self.assertTrue(icon.isascii(), f"icon for {system_key} is not ascii: {icon!r}")
            self.assertEqual(icon, system_def["short"])


if __name__ == "__main__":
    unittest.main()
