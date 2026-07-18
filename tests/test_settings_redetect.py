"""Headless tests for the settings dialog emulator re-detect wiring (PR6)."""

import copy
import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from retrovault.core.config import DEFAULT_CONFIG, is_emulator_configured
from retrovault.providers.discovery import DetectResult
from retrovault.ui.settings_dialog import SettingsDialog


class SettingsRedetectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        dialog = SettingsDialog(copy.deepcopy(DEFAULT_CONFIG))
        self.addCleanup(dialog.close)
        return dialog

    def test_apply_detection_populates_rows_and_marks_configured(self):
        dialog = self._dialog()
        self.assertEqual(dialog.system_rows["nes"]["path"].text(), "")
        self.assertFalse(is_emulator_configured(dialog.config_data, "nes"))

        dialog._apply_detection_results({"mesen-ce": DetectResult(True, "exe", "C:/Mesen/Mesen.exe")})

        self.assertEqual(dialog.system_rows["nes"]["path"].text(), "C:/Mesen/Mesen.exe")
        self.assertEqual(dialog.system_rows["nes"]["launch_type"].currentText(), "exe")
        self.assertTrue(is_emulator_configured(dialog.config_data, "nes"))
        self.assertIn("Detected", dialog.detect_status.text())

    def test_apply_detection_does_not_clobber_unsaved_path(self):
        dialog = self._dialog()
        dialog.system_rows["nes"]["path"].edit.setText("C:/Custom/nes.exe")

        dialog._apply_detection_results({"mesen-ce": DetectResult(True, "exe", "C:/Mesen/Mesen.exe")})

        self.assertEqual(dialog.system_rows["nes"]["path"].text(), "C:/Custom/nes.exe")

    def test_save_persists_detected_path(self):
        dialog = self._dialog()
        dialog._apply_detection_results({"mesen-ce": DetectResult(True, "exe", "C:/Mesen/Mesen.exe")})

        with mock.patch("retrovault.ui.settings_dialog.config_mod.save_config") as save:
            dialog._save()

        saved = save.call_args.args[0]
        self.assertEqual(saved["emulators"]["nes"]["path"], "C:/Mesen/Mesen.exe")

    def test_redetect_runs_discovery_in_thread(self):
        dialog = self._dialog()
        with mock.patch(
            "retrovault.ui.settings_dialog.discovery.discover_emulators", return_value={}
        ) as discover:
            dialog._redetect()
            deadline = time.monotonic() + 2
            while dialog._threads and time.monotonic() < deadline:
                self.app.processEvents()

        self.assertFalse(dialog._threads)
        discover.assert_called_once()
        self.assertTrue(dialog.redetect_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
