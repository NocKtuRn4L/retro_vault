"""Real-network Qt smoke test for emulator provisioning.

Run explicitly; unittest discovery does not include this module.
"""

import argparse
import copy
import os
import tempfile
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from retrovault.core.config import DEFAULT_CONFIG
from retrovault.providers import installer
from retrovault.providers.manifest import load_shipped_registry
from retrovault.ui.setup_wizard import SetupWizard


def main(system_id="nes"):
    app = QApplication.instance() or QApplication([])
    original_install = installer.install

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        app_dir = Path(temp_dir)

        def isolated_install(*args, **kwargs):
            kwargs["app_dir"] = app_dir
            return original_install(*args, **kwargs)

        with (
            mock.patch("retrovault.ui.setup_wizard.installer.install", side_effect=isolated_install),
            mock.patch("retrovault.ui.setup_wizard.config_mod.save_config"),
            mock.patch("retrovault.ui.setup_wizard.audit_mod.load_test_rom_manifest", return_value={}),
            mock.patch("retrovault.ui.setup_wizard.detect.current_platform", return_value="windows-x86_64"),
        ):
            wizard = SetupWizard(copy.deepcopy(DEFAULT_CONFIG), registry=load_shipped_registry())
            wizard.show()
            QTest.mouseClick(wizard.rows[system_id]["install"], Qt.MouseButton.LeftButton)

            progress_seen = False
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                app.processEvents()
                bar = wizard.rows[system_id]["progress"]
                progress_seen |= bar.maximum() > 0 and 0 < bar.value() < bar.maximum()
                terminal = "installed_path" in wizard.rows[system_id] or wizard.instruction.isVisible()
                if not wizard._threads and terminal:
                    break
                time.sleep(0.01)

            app.processEvents()
            assert not wizard._threads, "installer thread did not finish within 180 seconds"
            row = wizard.rows[system_id]
            assert "installed_path" in row, wizard.instruction.text() or "install did not reach a terminal state"
            installed_path = Path(row["installed_path"])
            assert progress_seen, "no determinate progress update was observed"
            assert installed_path.is_file(), f"installed executable missing: {installed_path}"
            assert row["status"].text() == "READY", row["status"].text()
            assert row["install"].text() == "UNINSTALL", row["install"].text()
            assert row["progress"].format() == "COMPLETE", row["progress"].format()
            print(f"PASS: downloaded and installed {installed_path.name}")
            wizard.close()
            app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", default="nes")
    main(parser.parse_args().system)
