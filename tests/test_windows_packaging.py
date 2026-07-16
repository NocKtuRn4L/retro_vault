"""Static contract checks for the Windows packaging definitions."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PACKAGING = ROOT / "packaging" / "windows"


class WindowsPackagingTests(unittest.TestCase):
    def test_windows_icon_is_shipped(self):
        self.assertTrue((WINDOWS_PACKAGING / "retrovault.ico").is_file())

    def test_pyinstaller_spec_is_one_folder_and_ships_runtime_data(self):
        spec = (WINDOWS_PACKAGING / "retrovault.spec").read_text(encoding="utf-8")

        self.assertIn("COLLECT(", spec)
        self.assertIn('exclude_binaries=True', spec)
        self.assertIn('"entrypoint.py"', spec)
        self.assertIn('"data/*"', spec)
        self.assertIn('"data/emulators/*.json"', spec)
        self.assertIn('"ui/*.qss"', spec)
        self.assertIn('"PySide6.QtNetwork"', spec)
        self.assertIn('"PySide6.QtQml"', spec)
        self.assertIn('"qt6network.dll"', spec)

    def test_pyinstaller_spec_bundles_pygame_and_sdl(self):
        spec = (WINDOWS_PACKAGING / "retrovault.spec").read_text(encoding="utf-8")

        # SDL2 native libraries ride along inside pygame-ce and must be
        # collected, or the frozen app crashes with a missing SDL2 DLL.
        self.assertIn("collect_dynamic_libs", spec)
        self.assertIn('collect_dynamic_libs("pygame")', spec)
        self.assertIn('collect_data_files("pygame")', spec)
        self.assertIn('hiddenimports=["pygame"]', spec)

    def test_build_script_supports_clean_and_installer_builds(self):
        script = (WINDOWS_PACKAGING / "build.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$Clean", script)
        self.assertIn("Close the packaged RetroVault app before rebuilding", script)
        self.assertIn("[switch]$Installer", script)
        self.assertIn('"-m", "PyInstaller"', script)
        self.assertIn('"setup.iss"', script)

    def test_inno_setup_packages_the_one_folder_output(self):
        installer = (WINDOWS_PACKAGING / "setup.iss").read_text(encoding="utf-8")

        self.assertIn("dist\\RetroVault\\*", installer)
        self.assertIn("recursesubdirs", installer)
        self.assertIn("RetroVault.exe", installer)


if __name__ == "__main__":
    unittest.main()
