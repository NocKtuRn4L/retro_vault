import copy
import os
import unittest
import warnings

from retrovault.core import config as config_mod
from retrovault.providers.manifest import (
    FullscreenPolicy,
    ManifestError,
    effective_fullscreen,
    load_shipped_registry,
    manifest_from_dict,
)

_HEADLESS = False
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: F401

    from retrovault.ui.settings_dialog import SettingsDialog

    _HEADLESS = True
except Exception:  # pragma: no cover - Qt not importable
    _HEADLESS = False


def _base_manifest(**overrides):
    data = {
        "id": "demo",
        "name": "Demo",
        "website": "https://example.test",
        "license": "MIT",
        "profiles": [{"systems": ["nes"], "args": "{rom}"}],
        "detect": {"binaries": ["demo"]},
    }
    data.update(overrides)
    return data


class FullscreenManifestTests(unittest.TestCase):
    def test_arg_mode_parses(self):
        manifest = manifest_from_dict(_base_manifest(fullscreen={"mode": "arg", "arg": "--fullscreen"}))
        self.assertEqual(manifest.fullscreen, FullscreenPolicy(mode="arg", arg="--fullscreen"))

    def test_config_mode_parses(self):
        manifest = manifest_from_dict(
            _base_manifest(fullscreen={"mode": "config", "file": "settings.ini", "key": "Fullscreen", "value": "true"})
        )
        self.assertEqual(
            manifest.fullscreen,
            FullscreenPolicy(mode="config", config_file="settings.ini", config_key="Fullscreen", config_value="true"),
        )

    def test_absent_fullscreen_defaults_to_inherit(self):
        manifest = manifest_from_dict(_base_manifest())
        self.assertEqual(manifest.fullscreen, FullscreenPolicy())
        self.assertEqual(manifest.fullscreen.mode, "inherit")

    def test_arg_mode_requires_arg(self):
        with self.assertRaises(ManifestError):
            manifest_from_dict(_base_manifest(fullscreen={"mode": "arg"}))

    def test_config_mode_requires_file_key_value(self):
        for missing in ("file", "key", "value"):
            data = {"mode": "config", "file": "s.ini", "key": "K", "value": "true"}
            del data[missing]
            with self.assertRaises(ManifestError):
                manifest_from_dict(_base_manifest(fullscreen=data))

    def test_invalid_mode_raises(self):
        with self.assertRaises(ManifestError):
            manifest_from_dict(_base_manifest(fullscreen={"mode": "borderless"}))


class ShippedRegistryFullscreenTests(unittest.TestCase):
    def test_all_shipped_manifests_parse_with_fullscreen_policy(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            registry = load_shipped_registry()
        self.assertTrue(registry.manifests)
        for manifest in registry.manifests.values():
            self.assertIsInstance(manifest.fullscreen, FullscreenPolicy)

    def test_known_arg_emulators(self):
        registry = load_shipped_registry()
        self.assertEqual(registry.get("mgba").fullscreen.mode, "arg")
        self.assertEqual(registry.get("retroarch").fullscreen.mode, "arg")


class EffectiveFullscreenTests(unittest.TestCase):
    def setUp(self):
        self.inherit = FullscreenPolicy()
        self.arg = FullscreenPolicy(mode="arg", arg="-f")

    def test_force_windowed_never_fullscreen(self):
        cfg = {"fullscreen_preference": "force_windowed"}
        self.assertFalse(effective_fullscreen(self.arg, cfg))
        self.assertFalse(effective_fullscreen(self.inherit, cfg))
        self.assertFalse(effective_fullscreen(self.arg, cfg, kiosk=True))

    def test_prefer_always_fullscreen(self):
        cfg = {"fullscreen_preference": "prefer"}
        self.assertTrue(effective_fullscreen(self.arg, cfg))
        self.assertTrue(effective_fullscreen(self.inherit, cfg))

    def test_emulator_honors_policy(self):
        cfg = {"fullscreen_preference": "emulator"}
        self.assertTrue(effective_fullscreen(self.arg, cfg))
        self.assertFalse(effective_fullscreen(self.inherit, cfg))

    def test_default_preference_when_absent(self):
        self.assertTrue(effective_fullscreen(self.arg, {}))
        self.assertFalse(effective_fullscreen(self.inherit, {}))
        self.assertFalse(effective_fullscreen(self.inherit, None))

    def test_kiosk_forces_fullscreen_under_emulator_preference(self):
        cfg = {"fullscreen_preference": "emulator"}
        self.assertTrue(effective_fullscreen(self.inherit, cfg, platform_key="linux-aarch64", kiosk=True))
        self.assertTrue(effective_fullscreen(self.arg, cfg, kiosk=True))


class ConfigFullscreenTests(unittest.TestCase):
    def test_default_preference_is_emulator(self):
        self.assertEqual(config_mod.DEFAULT_CONFIG["fullscreen_preference"], "emulator")

    def test_migrate_empty_config_sets_default(self):
        migrated = config_mod.migrate_config({})
        self.assertEqual(migrated["fullscreen_preference"], "emulator")

    def test_migrate_preserves_override(self):
        migrated = config_mod.migrate_config({"fullscreen_preference": "prefer"})
        self.assertEqual(migrated["fullscreen_preference"], "prefer")


@unittest.skipUnless(_HEADLESS, "PySide6 not available")
class SettingsDialogFullscreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_control_exists_and_save_persists(self):
        cfg = copy.deepcopy(config_mod.DEFAULT_CONFIG)
        cfg["fullscreen_preference"] = "prefer"
        dialog = SettingsDialog(cfg)
        self.addCleanup(dialog.close)
        # Control initialized from config.
        self.assertEqual(dialog.fullscreen_preference.currentText(), "Prefer fullscreen")
        # Change selection and persist via _save (patched save_config to avoid disk writes).
        dialog.fullscreen_preference.setCurrentText("Force windowed")
        saved = {}
        original = config_mod.save_config
        config_mod.save_config = lambda data: saved.update({"data": data})
        try:
            dialog._save()
        finally:
            config_mod.save_config = original
        self.assertEqual(saved["data"]["fullscreen_preference"], "force_windowed")
        self.assertEqual(dialog.config_data["fullscreen_preference"], "force_windowed")


if __name__ == "__main__":
    unittest.main()
