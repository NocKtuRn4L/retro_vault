import os
import time
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

    @mock.patch("retrovault.ui.setup_wizard.discovery.discover_emulators", return_value={})
    def test_detection_thread_runs_and_finishes(self, discover):
        wizard = self.make_wizard()

        wizard._detect_all()
        deadline = time.monotonic() + 2
        while wizard._threads and time.monotonic() < deadline:
            self.app.processEvents()

        self.assertFalse(wizard._threads)
        discover.assert_called_once()

    def test_completed_detection_reports_not_found(self):
        wizard = self.make_wizard()

        wizard._detection_complete({"mesen-ce": DetectResult(False)})

        self.assertEqual(wizard.rows["nes"]["status"].text(), "NOT FOUND")

    def test_download_progress_is_visible_and_updates_in_place(self):
        wizard = self.make_wizard()
        bar = wizard.rows["nes"]["progress"]

        wizard._set_busy(("nes",), True, show_progress=True)
        self.assertTrue(bar.isHidden())
        self.assertEqual(wizard.rows["nes"]["status"].text(), "QUEUED")
        wizard._update_progress("mesen-ce", 25, 100)

        self.assertFalse(bar.isHidden())
        self.assertEqual(wizard.rows["nes"]["status"].text(), "INSTALLING")
        self.assertEqual(bar.value(), 25)
        self.assertEqual(bar.maximum(), 100)
        self.assertEqual(bar.parentWidget(), wizard.rows["nes"]["path"].parentWidget())

    def test_bulk_progress_only_activates_current_emulator(self):
        wizard = self.make_wizard()
        wizard._set_busy(tuple(wizard.rows), True, show_progress=True)

        wizard._update_progress("mesen-ce", 0, 0)

        self.assertFalse(wizard.rows["nes"]["progress"].isHidden())
        self.assertFalse(wizard.rows["snes"]["progress"].isHidden())
        self.assertTrue(wizard.rows["n64"]["progress"].isHidden())
        self.assertEqual(wizard.rows["n64"]["status"].text(), "QUEUED")

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


    @mock.patch("retrovault.ui.setup_wizard.installer.uninstall", return_value=None)
    @mock.patch("retrovault.ui.setup_wizard.config_mod.save_config")
    @mock.patch("retrovault.ui.setup_wizard.audit_mod.load_test_rom_manifest", return_value={})
    def test_install_then_uninstall_swaps_button_and_clears_slots(self, _manifest, _save, _uninstall):
        wizard = self.make_wizard()
        # Install mesen-ce → covers NES and SNES
        wizard._install_complete({"mesen-ce": Path("C:/Mesen/Mesen.exe")})
        self.assertEqual(wizard.rows["nes"]["status"].text(), "READY")
        self.assertEqual(wizard.rows["nes"]["install"].text(), "UNINSTALL")
        self.assertEqual(wizard.rows["snes"]["install"].text(), "UNINSTALL")
        self.assertIn("installed_path", wizard.rows["nes"])
        self.assertIn("installed_path", wizard.rows["snes"])

        # Click UNINSTALL on NES → both NES and SNES clear
        wizard._toggle_install("nes")
        self.assertEqual(wizard.rows["nes"]["status"].text(), "NEEDED")
        self.assertEqual(wizard.rows["snes"]["status"].text(), "NEEDED")
        self.assertEqual(wizard.rows["nes"]["install"].text(), "INSTALL")
        self.assertEqual(wizard.rows["snes"]["install"].text(), "INSTALL")
        self.assertNotIn("installed_path", wizard.rows["nes"])
        self.assertNotIn("installed_path", wizard.rows["snes"])
        self.assertEqual(wizard.config_data["emulators"]["nes"]["path"], "")
        self.assertEqual(wizard.config_data["emulators"]["snes"]["path"], "")

    @mock.patch("retrovault.ui.setup_wizard.installer.uninstall", return_value=None)
    @mock.patch("retrovault.ui.setup_wizard.config_mod.save_config")
    @mock.patch("retrovault.ui.setup_wizard.audit_mod.load_test_rom_manifest", return_value={})
    def test_install_then_install_on_installed_system_does_not_reinstall(self, _manifest, _save, _uninstall):
        """_toggle_install on a row with installed_path calls uninstall, not install."""
        wizard = self.make_wizard()
        with mock.patch.object(wizard, "_install_system") as install_spy:
            wizard._install_complete({"mesen-ce": Path("C:/Mesen/Mesen.exe")})
            wizard._toggle_install("nes")
            install_spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
