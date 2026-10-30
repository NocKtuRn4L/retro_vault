"""Launches hand RetroArch the full path of cores RetroVault downloaded itself."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from retrovault.core import launch
from retrovault.core.config import DEFAULT_CONFIG


class ManagedCoreLaunchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.cores_dir = self.root / "cores"
        self.cores_dir.mkdir()
        patcher = mock.patch.object(launch, "CORES_DIR", self.cores_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(launch, "_is_flatpak_installed", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.rom_path = self.root / "Metroid (USA).nes"
        self.rom_path.write_bytes(b"NES\x1a")
        self.rom = {"name": "Metroid (USA)", "path": str(self.rom_path), "system": "nes"}
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config["controller"]["prefer_retroarch"] = False

    def _download(self, name, suffix=".so"):
        core = self.cores_dir / f"{name}{suffix}"
        core.write_bytes(b"\x7fELF")
        return str(core)

    def _flatpak_retroarch(self, args):
        self.config["emulators"]["nes"].update(
            launch_type="flatpak", flatpak_id="org.libretro.RetroArch", path="", args=args, profile="retroarch"
        )

    def test_managed_core_path_prefers_a_downloaded_core(self):
        downloaded = self._download("nestopia_libretro")

        self.assertEqual(launch.managed_core_path("nestopia_libretro", platform="linux"), downloaded)
        self.assertEqual(launch.managed_core_path("snes9x_libretro", platform="linux"), "snes9x_libretro")

    def test_managed_core_path_leaves_explicit_paths_alone(self):
        self._download("nestopia_libretro")

        self.assertEqual(launch.managed_core_path("/opt/cores/nestopia_libretro.so"), "/opt/cores/nestopia_libretro.so")

    def test_windows_looks_for_a_dll(self):
        downloaded = self._download("nestopia_libretro", suffix=".dll")

        self.assertEqual(launch.managed_core_path("nestopia_libretro", platform="win32"), downloaded)

    def test_flatpak_args_with_a_literal_core_name_use_the_download(self):
        downloaded = self._download("nestopia_libretro")
        self._flatpak_retroarch("-L nestopia_libretro {rom}")

        with mock.patch.object(launch.shutil, "which", return_value="/usr/bin/flatpak"):
            cmd, error = launch.build_launch_command(self.rom, self.config, platform="linux")

        self.assertIsNone(error)
        self.assertEqual(cmd, ["flatpak", "run", "org.libretro.RetroArch", "-L", downloaded, str(self.rom_path)])

    def test_core_placeholder_uses_the_download(self):
        downloaded = self._download("nestopia_libretro")
        self._flatpak_retroarch("-L {core} {rom}")

        with mock.patch.object(launch.shutil, "which", return_value="/usr/bin/flatpak"):
            cmd, _error = launch.build_launch_command(self.rom, self.config, platform="linux")

        self.assertEqual(cmd[3:], ["-L", downloaded, str(self.rom_path)])

    def test_core_without_a_download_is_passed_by_name(self):
        self._flatpak_retroarch("-L nestopia_libretro {rom}")

        with mock.patch.object(launch.shutil, "which", return_value="/usr/bin/flatpak"):
            cmd, _error = launch.build_launch_command(self.rom, self.config, platform="linux")

        self.assertEqual(cmd[3:], ["-L", "nestopia_libretro", str(self.rom_path)])

    def test_retroarch_binary_route_uses_the_download(self):
        downloaded = self._download("nestopia_libretro")
        retroarch = self.root / "retroarch"
        retroarch.write_bytes(b"exe")
        self.config["use_retroarch"] = True
        self.config["retroarch_path"] = str(retroarch)

        cmd, error = launch.build_launch_command(self.rom, self.config, platform="linux")

        self.assertIsNone(error)
        self.assertEqual(cmd, [str(retroarch), "-L", downloaded, str(self.rom_path)])


if __name__ == "__main__":
    unittest.main()
