"""Typed emulator manifest loading, validation, and catalog caching."""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from ..core.paths import APP_DIR

CATALOG_CACHE_DIR = APP_DIR / "catalog"
CATALOG_CACHE_FILE = CATALOG_CACHE_DIR / "catalog.json"


class ManifestError(ValueError):
    """Raised when a provider manifest is structurally invalid."""


@dataclass(frozen=True)
class EmulatorProfile:
    systems: tuple[str, ...]
    args: str = "{rom}"


@dataclass(frozen=True)
class DetectionRules:
    binaries: tuple[str, ...] = ()
    windows_paths: tuple[str, ...] = ()
    flatpak_id: str = ""


@dataclass(frozen=True)
class InstallStrategy:
    strategy: str
    url: str = ""
    sha256: str = ""
    archive: str = ""
    exe: str = ""
    package: str = ""
    flatpak_id: str = ""
    reason: str = ""
    fallback: InstallStrategy | None = None

    @property
    def available(self) -> bool:
        return self.strategy != "unavailable"


@dataclass(frozen=True)
class EmulatorManifest:
    id: str
    name: str
    website: str
    license: str
    profiles: tuple[EmulatorProfile, ...]
    detect: DetectionRules
    install: Mapping[str, InstallStrategy] = field(default_factory=dict)
    cores: Mapping[str, str] = field(default_factory=dict)

    def strategy_for(self, platform_key: str) -> InstallStrategy:
        """Resolve the exact platform strategy without crossing OS or architecture."""
        strategy = self.install.get(platform_key)
        if strategy is not None:
            return strategy
        return InstallStrategy("unavailable", reason=f"No install strategy for {platform_key}")


@dataclass(frozen=True)
class ManifestRegistry:
    manifests: Mapping[str, EmulatorManifest]
    source: str = "shipped"

    def get(self, emulator_id: str) -> EmulatorManifest | None:
        return self.manifests.get(emulator_id)

    def strategy_for(self, emulator_id: str, platform_key: str) -> InstallStrategy:
        manifest = self.get(emulator_id)
        if manifest is None:
            return InstallStrategy("unavailable", reason=f"Unknown emulator: {emulator_id}")
        return manifest.strategy_for(platform_key)


def _warn_unknown(data: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        warnings.warn(f"Unknown keys in {context}: {', '.join(unknown)}", UserWarning, stacklevel=3)


def _require_string(data: Mapping[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{context}.{key} must be a non-empty string")
    return value


def _string_tuple(value: Any, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ManifestError(f"{context} must be a list of non-empty strings")
    return tuple(value)


def _parse_strategy(data: Any, context: str) -> InstallStrategy:
    if not isinstance(data, dict):
        raise ManifestError(f"{context} must be an object")
    allowed = {"strategy", "url", "sha256", "archive", "exe", "package", "flatpak_id", "reason", "fallback"}
    _warn_unknown(data, allowed, context)
    strategy = _require_string(data, "strategy", context)
    if strategy not in {"download", "apt", "flatpak", "unavailable"}:
        raise ManifestError(f"{context}.strategy is unsupported: {strategy}")
    kwargs = {key: data.get(key, "") for key in allowed - {"strategy", "fallback"}}
    if not all(isinstance(value, str) for value in kwargs.values()):
        raise ManifestError(f"{context} strategy fields must be strings")
    fallback = _parse_strategy(data["fallback"], f"{context}.fallback") if "fallback" in data else None
    parsed = InstallStrategy(strategy=strategy, fallback=fallback, **kwargs)
    if strategy == "download":
        if not parsed.url or not parsed.archive or not parsed.exe:
            raise ManifestError(f"{context} download strategy requires url, archive, and exe")
        if len(parsed.sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in parsed.sha256):
            raise ManifestError(f"{context} download strategy requires a valid SHA-256")
    elif strategy == "apt" and not parsed.package:
        raise ManifestError(f"{context} apt strategy requires package")
    elif strategy == "flatpak" and not parsed.flatpak_id:
        raise ManifestError(f"{context} flatpak strategy requires flatpak_id")
    elif strategy == "unavailable" and not parsed.reason:
        raise ManifestError(f"{context} unavailable strategy requires reason")
    return parsed


def manifest_from_dict(data: Any, context: str = "manifest") -> EmulatorManifest:
    if not isinstance(data, dict):
        raise ManifestError(f"{context} must be an object")
    _warn_unknown(data, {"id", "name", "website", "license", "profiles", "detect", "install", "cores"}, context)
    profiles_data = data.get("profiles")
    if not isinstance(profiles_data, list) or not profiles_data:
        raise ManifestError(f"{context}.profiles must be a non-empty list")
    profiles = []
    for index, profile in enumerate(profiles_data):
        profile_context = f"{context}.profiles[{index}]"
        if not isinstance(profile, dict):
            raise ManifestError(f"{profile_context} must be an object")
        _warn_unknown(profile, {"systems", "args"}, profile_context)
        systems = _string_tuple(profile.get("systems"), f"{profile_context}.systems")
        if not systems:
            raise ManifestError(f"{profile_context}.systems must not be empty")
        args = profile.get("args", "{rom}")
        if not isinstance(args, str) or "{rom}" not in args:
            raise ManifestError(f"{profile_context}.args must contain {{rom}}")
        profiles.append(EmulatorProfile(systems, args))

    detect_data = data.get("detect", {})
    if not isinstance(detect_data, dict):
        raise ManifestError(f"{context}.detect must be an object")
    _warn_unknown(detect_data, {"binaries", "windows_paths", "flatpak_id"}, f"{context}.detect")
    flatpak_id = detect_data.get("flatpak_id", "")
    if not isinstance(flatpak_id, str):
        raise ManifestError(f"{context}.detect.flatpak_id must be a string")
    detection = DetectionRules(
        binaries=_string_tuple(detect_data.get("binaries"), f"{context}.detect.binaries"),
        windows_paths=_string_tuple(detect_data.get("windows_paths"), f"{context}.detect.windows_paths"),
        flatpak_id=flatpak_id,
    )

    install_data = data.get("install", {})
    if not isinstance(install_data, dict):
        raise ManifestError(f"{context}.install must be an object")
    installs = {key: _parse_strategy(value, f"{context}.install.{key}") for key, value in install_data.items()}
    cores = data.get("cores", {})
    if not isinstance(cores, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value for key, value in cores.items()
    ):
        raise ManifestError(f"{context}.cores must map system ids to non-empty core names")
    return EmulatorManifest(
        id=_require_string(data, "id", context),
        name=_require_string(data, "name", context),
        website=_require_string(data, "website", context),
        license=_require_string(data, "license", context),
        profiles=tuple(profiles),
        detect=detection,
        install=installs,
        cores=cores,
    )


def _registry_from_documents(documents: list[Any], source: str) -> ManifestRegistry:
    manifests: dict[str, EmulatorManifest] = {}
    for index, document in enumerate(documents):
        manifest = manifest_from_dict(document, f"{source}[{index}]")
        if manifest.id in manifests:
            raise ManifestError(f"Duplicate emulator id in {source}: {manifest.id}")
        manifests[manifest.id] = manifest
    if not manifests:
        raise ManifestError(f"{source} contains no manifests")
    return ManifestRegistry(manifests, source)


def load_shipped_registry() -> ManifestRegistry:
    directory = resources.files("retrovault.data").joinpath("emulators")
    documents = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".json"):
            with entry.open("r", encoding="utf-8") as handle:
                documents.append(json.load(handle))
    return _registry_from_documents(documents, "shipped")


def _catalog_documents(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("manifests"), list):
        return data["manifests"]
    raise ManifestError("catalog must be a list or an object containing a manifests list")


def load_cached_registry(cache_file: Path = CATALOG_CACHE_FILE) -> ManifestRegistry:
    with cache_file.open("r", encoding="utf-8") as handle:
        return _registry_from_documents(_catalog_documents(json.load(handle)), "remote-cache")


def fetch_remote_catalog(
    url: str,
    cache_file: Path = CATALOG_CACHE_FILE,
    opener: Callable[..., Any] = urlopen,
) -> ManifestRegistry:
    if not url:
        raise ValueError("Remote catalog URL is empty")
    with opener(url, timeout=10) as response:
        payload = response.read()
    data = json.loads(payload.decode("utf-8"))
    registry = _registry_from_documents(_catalog_documents(data), "remote")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(cache_file)
    return registry


def load_registry(
    config: Mapping[str, Any] | None = None,
    *,
    refresh_remote: bool = True,
    cache_file: Path = CATALOG_CACHE_FILE,
    opener: Callable[..., Any] = urlopen,
) -> ManifestRegistry:
    """Load remote, cached, or shipped manifests in descending preference order."""
    remote_url = str((config or {}).get("remote_catalog_url", "")).strip()
    if remote_url and refresh_remote:
        try:
            return fetch_remote_catalog(remote_url, cache_file, opener)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            logging.warning("Unable to refresh emulator catalog: %s", error)
    if remote_url and cache_file.is_file():
        try:
            return load_cached_registry(cache_file)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            logging.warning("Ignoring invalid cached emulator catalog: %s", error)
    return load_shipped_registry()
