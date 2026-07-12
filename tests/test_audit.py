import copy
import tempfile
import unittest
from pathlib import Path

from retrovault.core import audit
from retrovault.core.config import DEFAULT_CONFIG


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config["emulators"]["n64"] = {
            "path": r'"C:\Emulators\Project64\Project64.exe"',
            "args": '"{rom}"',
        }

    def test_load_test_rom_manifest_returns_defaults(self):
        manifest = audit.load_test_rom_manifest(path="Z:\\does-not-exist\\test_roms.json")

        self.assertIn("n64", manifest)
        self.assertEqual(manifest["n64"]["label"], "Nintendo 64 smoke ROM")

    def test_audit_test_roms_reports_missing_roms(self):
        manifest = {"n64": {"path": ""}}

        results = audit.audit_test_roms(self.config, manifest)

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

            results = audit.audit_test_roms(self.config, manifest)

        self.assertEqual(results[0]["status"], "ok")
        self.assertIn(str(emu_path), results[0]["message"])


if __name__ == "__main__":
    unittest.main()
