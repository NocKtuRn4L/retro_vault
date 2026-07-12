import tempfile
import unittest
from pathlib import Path

from retrovault.core.paths import resolve_app_dir


class PathResolutionTests(unittest.TestCase):
    def test_explicit_home_wins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(resolve_app_dir(temp_dir, {"RETROVAULT_HOME": "custom"}), Path("custom"))

    def test_existing_legacy_directory_wins_over_xdg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            legacy = home / ".retrovault"
            legacy.mkdir()
            self.assertEqual(resolve_app_dir(home, {"XDG_CONFIG_HOME": "xdg"}), legacy)

    def test_xdg_used_for_fresh_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(resolve_app_dir(temp_dir, {"XDG_CONFIG_HOME": "xdg"}), Path("xdg") / "retrovault")


if __name__ == "__main__":
    unittest.main()
