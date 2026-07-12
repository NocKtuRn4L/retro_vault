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
        recommendation = config.get_recommended_emulator("n64")

        self.assertEqual(recommendation["name"], "Rosalie's Mupen GUI")
        self.assertIn("github.com/Rosalie241/RMG", recommendation["url"])


if __name__ == "__main__":
    unittest.main()
