import copy
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path

from retrovault.core import config
from retrovault.providers.manifest import (
    EmulatorManifest,
    InstallStrategy,
    ManifestError,
    fetch_remote_catalog,
    load_registry,
    load_shipped_registry,
    manifest_from_dict,
)


def valid_manifest(emulator_id="test-emulator"):
    return {
        "id": emulator_id,
        "name": "Test Emulator",
        "website": "https://example.invalid",
        "license": "MIT",
        "profiles": [{"systems": ["nes"], "args": '"{rom}"'}],
        "detect": {"binaries": ["test-emulator"]},
        "install": {
            "windows-x86_64": {
                "strategy": "unavailable",
                "reason": "No pinned artifact is available.",
            }
        },
    }


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ManifestValidationTests(unittest.TestCase):
    def test_config_migration_adds_remote_catalog_url(self):
        migrated = config.migrate_config({})

        self.assertEqual(migrated["remote_catalog_url"], "")

    def test_shipped_manifests_load_and_include_expected_ids(self):
        registry = load_shipped_registry()

        self.assertEqual(
            set(registry.manifests),
            {"ares", "duckstation", "mesen-ce", "mgba", "retroarch", "rmg"},
        )
        self.assertEqual(registry.get("retroarch").cores, config.DEFAULT_CONFIG["retroarch_cores"])

    def test_manifest_is_typed(self):
        manifest = manifest_from_dict(valid_manifest())

        self.assertIsInstance(manifest, EmulatorManifest)
        self.assertEqual(manifest.profiles[0].systems, ("nes",))

    def test_shipped_downloads_are_pinned_and_have_sha256(self):
        registry = load_shipped_registry()
        downloads = []
        for manifest in registry.manifests.values():
            downloads.extend(strategy for strategy in manifest.install.values() if strategy.strategy == "download")

        self.assertTrue(downloads)
        for strategy in downloads:
            self.assertNotIn("/latest/", strategy.url)
            self.assertEqual(len(strategy.sha256), 64)
            int(strategy.sha256, 16)

    def test_unknown_keys_warn(self):
        document = valid_manifest()
        document["future_field"] = True

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manifest_from_dict(document)

        self.assertTrue(any("future_field" in str(item.message) for item in caught))

    def test_download_requires_real_shape_sha256(self):
        document = valid_manifest()
        document["install"]["windows-x86_64"] = {
            "strategy": "download",
            "url": "https://example.invalid/emulator.zip",
            "sha256": "not-a-checksum",
            "archive": "zip",
            "exe": "emulator.exe",
        }

        with self.assertRaisesRegex(ManifestError, "valid SHA-256"):
            manifest_from_dict(document)


class StrategyResolutionTests(unittest.TestCase):
    def test_missing_platform_is_unavailable(self):
        manifest = manifest_from_dict(valid_manifest())

        strategy = manifest.strategy_for("linux-aarch64")

        self.assertEqual(strategy.strategy, "unavailable")
        self.assertIn("No install strategy", strategy.reason)

    def test_explicit_unavailable_stops_fallback(self):
        document = valid_manifest()
        document["install"]["linux-aarch64"] = {
            "strategy": "unavailable",
            "reason": "Architecture deliberately unsupported.",
        }
        manifest = manifest_from_dict(document)

        strategy = manifest.strategy_for("linux-aarch64")

        self.assertEqual(strategy.reason, "Architecture deliberately unsupported.")

    def test_unknown_emulator_is_unavailable(self):
        strategy = load_shipped_registry().strategy_for("missing", "windows-x86_64")

        self.assertIsInstance(strategy, InstallStrategy)
        self.assertFalse(strategy.available)


class RemoteCatalogTests(unittest.TestCase):
    def test_remote_catalog_is_validated_cached_and_preferred(self):
        payload = json.dumps({"manifests": [valid_manifest("remote-emulator")]}).encode()
        calls = []

        def opener(url, timeout):
            calls.append((url, timeout))
            return FakeResponse(payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "catalog.json"
            registry = load_registry(
                {"remote_catalog_url": "https://example.invalid/catalog.json"},
                cache_file=cache_file,
                opener=opener,
            )

            self.assertEqual(registry.source, "remote")
            self.assertIn("remote-emulator", registry.manifests)
            self.assertTrue(cache_file.is_file())
            self.assertEqual(calls, [("https://example.invalid/catalog.json", 10)])

    def test_failed_refresh_prefers_valid_cache(self):
        payload = {"manifests": [valid_manifest("cached-emulator")]}

        def failing_opener(url, timeout):
            raise OSError("offline")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "catalog.json"
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
            registry = load_registry(
                {"remote_catalog_url": "https://example.invalid/catalog.json"},
                cache_file=cache_file,
                opener=failing_opener,
            )

        self.assertEqual(registry.source, "remote-cache")
        self.assertIn("cached-emulator", registry.manifests)

    def test_invalid_remote_does_not_replace_valid_cache(self):
        cached = {"manifests": [valid_manifest("cached-emulator")]}
        invalid = json.dumps({"manifests": [{"id": "broken"}]}).encode()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "catalog.json"
            cache_file.write_text(json.dumps(cached), encoding="utf-8")
            with self.assertRaises(ManifestError):
                fetch_remote_catalog(
                    "https://example.invalid/catalog.json",
                    cache_file,
                    lambda url, timeout: FakeResponse(invalid),
                )
            registry = load_registry(
                {"remote_catalog_url": "https://example.invalid/catalog.json"},
                refresh_remote=False,
                cache_file=cache_file,
            )

        self.assertIn("cached-emulator", registry.manifests)

    def test_empty_remote_url_uses_shipped_registry(self):
        registry = load_registry(copy.deepcopy(config.DEFAULT_CONFIG))

        self.assertEqual(registry.source, "shipped")


if __name__ == "__main__":
    unittest.main()
