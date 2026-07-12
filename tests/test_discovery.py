import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from retrovault.core.config import DEFAULT_CONFIG
from retrovault.providers.discovery import (
    DetectResult,
    apply_detection,
    detect_emulator,
    discover_emulators,
)
from retrovault.providers.manifest import ManifestRegistry, load_shipped_registry, manifest_from_dict


def make_manifest(**detect):
    return manifest_from_dict(
        {
            "id": "example",
            "name": "Example",
            "website": "https://example.invalid",
            "license": "MIT",
            "profiles": [{"systems": ["nes", "snes"], "args": '--play "{rom}"'}],
            "detect": detect,
        }
    )


class DiscoveryTests(unittest.TestCase):
    def test_configured_valid_path_has_priority(self):
        manifest = make_manifest(binaries=["example"])
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "user-selected-name.exe"
            executable.touch()
            config = {"emulators": {"nes": {"path": str(executable), "launch_type": "exe"}}}
            with mock.patch("retrovault.providers.discovery.shutil.which") as which:
                result = detect_emulator(config, manifest)

        self.assertEqual(result, DetectResult(True, "exe", str(executable)))
        which.assert_not_called()

    def test_path_binary_detection_uses_manifest_order(self):
        manifest = make_manifest(binaries=["example-gui", "example"])

        with mock.patch(
            "retrovault.providers.discovery.shutil.which",
            side_effect=lambda binary: "C:/bin/example.exe" if binary == "example" else None,
        ):
            result = detect_emulator({}, manifest)

        self.assertEqual(result, DetectResult(True, "binary", "example"))

    def test_expanded_windows_path_precedes_flatpak(self):
        manifest = make_manifest(
            binaries=[],
            windows_paths=[r"%EXAMPLE_HOME%\example.exe"],
            flatpak_id="org.example.App",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "example.exe"
            executable.touch()
            with mock.patch.dict(os.environ, {"EXAMPLE_HOME": temp_dir}), mock.patch(
                "retrovault.providers.discovery.subprocess.run"
            ) as run:
                result = detect_emulator({}, manifest)

        self.assertEqual(result, DetectResult(True, "exe", str(executable)))
        run.assert_not_called()

    def test_flatpak_info_detection(self):
        manifest = make_manifest(flatpak_id="org.example.App")
        completed = subprocess.CompletedProcess([], 0)

        with mock.patch("retrovault.providers.discovery.subprocess.run", return_value=completed) as run:
            result = detect_emulator({}, manifest)

        self.assertEqual(result, DetectResult(True, "flatpak", "org.example.App"))
        run.assert_called_once_with(
            ["flatpak", "info", "org.example.App"],
            capture_output=True,
            check=False,
        )

    def test_discover_returns_typed_missing_result(self):
        manifest = make_manifest()
        registry = ManifestRegistry({manifest.id: manifest})

        results = discover_emulators({}, registry)

        self.assertEqual(results, {"example": DetectResult(False)})


class ApplyDetectionTests(unittest.TestCase):
    def test_retroarch_detection_wires_each_system_core(self):
        registry = load_shipped_registry()
        result = DetectResult(True, "binary", "retroarch")

        updated = apply_detection({"emulators": {}}, {"retroarch": result}, registry)

        self.assertIn("nestopia_libretro", updated["emulators"]["nes"]["args"])
        self.assertNotIn("{core}", updated["emulators"]["nes"]["args"])

    def setUp(self):
        self.manifest = make_manifest()
        self.registry = ManifestRegistry({self.manifest.id: self.manifest})

    def test_fills_empty_slots_with_manifest_profile(self):
        original = copy.deepcopy(DEFAULT_CONFIG)
        results = {"example": DetectResult(True, "binary", "example")}

        updated = apply_detection(original, results, self.registry)

        for system in ("nes", "snes"):
            self.assertEqual(
                updated["emulators"][system],
                {
                    "path": "example",
                    "args": '--play "{rom}"',
                    "profile": "example",
                    "launch_type": "binary",
                    "flatpak_id": "",
                },
            )
        self.assertEqual(original, DEFAULT_CONFIG)

    def test_never_overwrites_user_values(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["emulators"]["nes"] = {
            "path": "C:/User/chosen.exe",
            "args": "--user {rom}",
            "profile": "custom",
            "launch_type": "exe",
            "flatpak_id": "",
        }

        updated = apply_detection(
            config,
            {"example": DetectResult(True, "flatpak", "org.example.App")},
            self.registry,
        )

        self.assertEqual(updated["emulators"]["nes"], config["emulators"]["nes"])
        self.assertEqual(updated["emulators"]["snes"]["flatpak_id"], "org.example.App")
        self.assertEqual(updated["emulators"]["snes"]["args"], '--play "{rom}"')


if __name__ == "__main__":
    unittest.main()
