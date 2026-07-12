import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from retrovault.core.config import DEFAULT_CONFIG
from retrovault.providers.discovery import DetectResult
from retrovault.providers.installer import InstallInstruction
from retrovault.providers.manifest import load_shipped_registry
from retrovault.ui.setup_wizard import SetupWizard


class SetupWizardProvisioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_wizard(self, platform="windows-x86_64"):
        patcher = mock.patch("retrovault.ui.setup_wizard.detect.current_platform", return_value=platform)
        patcher.start()
        self.addCleanup(patcher.stop)
        wizard = SetupWizard(DEFAULT_CONFIG, registry=load_shipped_registry())
        self.addCleanup(wizard.close)
        return wizard

    def test_rows_expose_pr16_controls_and_states(self):
        wizard = self.make_wizard()
        self.assertEqual(wizard.rows["nes"]["status"].text(), "NEEDED")
        self.assertEqual(wizard.rows["nes"]["detect"].text(), "DETECT")
        self.assertEqual(wizard.rows["nes"]["install"].text(), "INSTALL")

    def test_detection_wires_found_emulator(self):
        wizard = self.make_wizard()
        wizard._detection_complete({"mesen-ce": DetectResult(True, "exe", "C:/Mesen/Mesen.exe")})
        self.assertEqual(wizard.rows["nes"]["status"].text(), "FOUND")
        self.assertEqual(wizard.config_data["emulators"]["nes"]["path"], "C:/Mesen/Mesen.exe")

    @mock.patch("retrovault.ui.setup_wizard.config_mod.save_config")
    @mock.patch("retrovault.ui.setup_wizard.audit_mod.load_test_rom_manifest", return_value={})
    def test_linux_retroarch_install_wires_flatpak_and_cores(self, _manifest, _save):
        wizard = self.make_wizard("linux-aarch64")
        wizard._install_complete({"retroarch": "org.libretro.RetroArch"})
        self.assertFalse(wizard.config_data["use_retroarch"])
        self.assertEqual(wizard.config_data["emulators"]["gba"]["launch_type"], "flatpak")
        self.assertEqual(wizard.config_data["emulators"]["gba"]["flatpak_id"], "org.libretro.RetroArch")
        self.assertEqual(wizard.config_data["retroarch_cores"]["gba"], "mgba_libretro")
        self.assertEqual(wizard.rows["gba"]["status"].text(), "READY")

        wizard._save()
        self.assertEqual(wizard.config_data["emulators"]["gba"]["path"], "")
        self.assertEqual(wizard.config_data["emulators"]["gba"]["flatpak_id"], "org.libretro.RetroArch")

    @mock.patch("retrovault.ui.setup_wizard.config_mod.save_config")
    @mock.patch("retrovault.ui.setup_wizard.audit_mod.load_test_rom_manifest", return_value={})
    def test_apt_instruction_is_copyable(self, _manifest, _save):
        wizard = self.make_wizard("linux-aarch64")
        wizard._install_complete({"mgba": InstallInstruction("sudo apt install mgba-qt")})
        self.assertTrue(wizard.instruction.isReadOnly())
        self.assertEqual(wizard.instruction.text(), "sudo apt install mgba-qt")

    @mock.patch("retrovault.ui.setup_wizard.config_mod.save_config")
    @mock.patch("retrovault.ui.setup_wizard.audit_mod.audit_test_roms")
    @mock.patch(
        "retrovault.ui.setup_wizard.audit_mod.load_test_rom_manifest",
        return_value={"nes": {"path": "test.nes"}, "gba": {"path": ""}},
    )
    def test_post_install_audits_only_configured_roms(self, _load, audit, _save):
        audit.return_value = [{"system": "nes", "status": "ok", "message": "command"}]
        wizard = self.make_wizard()
        wizard._install_complete({"mesen-ce": Path("C:/Mesen/Mesen.exe")})
        self.assertEqual(set(audit.call_args.args[1]), {"nes"})
        self.assertIn("NES: OK", wizard.audit_results.text())

    @mock.patch("retrovault.ui.setup_wizard.shutil.which", return_value="")
    def test_use_retroarch_for_all_falls_back_to_flatpak_on_pi(self, _which):
        wizard = self.make_wizard("linux-aarch64")
        wizard._use_retroarch_for_all()
        slot = wizard.config_data["emulators"]["gba"]
        self.assertEqual(slot["launch_type"], "flatpak")
        self.assertEqual(slot["flatpak_id"], "org.libretro.RetroArch")
        self.assertEqual(slot["path"], "")
        self.assertIn("mgba_libretro", slot["args"])
        self.assertFalse(wizard.config_data["use_retroarch"])
        self.assertEqual(wizard.rows["gba"]["status"].text(), "READY")

    @mock.patch("retrovault.ui.setup_wizard.shutil.which", return_value="/usr/bin/retroarch")
    def test_use_retroarch_for_all_uses_local_binary_when_available(self, _which):
        wizard = self.make_wizard("linux-aarch64")
        wizard._use_retroarch_for_all()
        self.assertTrue(wizard.config_data["use_retroarch"])
        self.assertEqual(wizard.config_data["retroarch_path"], "/usr/bin/retroarch")
        slot = wizard.config_data["emulators"]["gba"]
        self.assertEqual(slot.get("launch_type", "exe"), "exe")  # untouched by binary path
        self.assertEqual(wizard.rows["gba"]["status"].text(), "READY")


if __name__ == "__main__":
    unittest.main()
