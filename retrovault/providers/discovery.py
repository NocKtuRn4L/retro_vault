"""Discover installed emulators from provider manifest rules."""

from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .manifest import EmulatorManifest, ManifestRegistry, load_registry


@dataclass(frozen=True)
class DetectResult:
    found: bool
    launch_type: str = ""
    path_or_id: str = ""
    version: str | None = None


def _manifest_systems(manifest: EmulatorManifest) -> tuple[str, ...]:
    return tuple(dict.fromkeys(system for profile in manifest.profiles for system in profile.systems))


def _configured_result(config: Mapping, manifest: EmulatorManifest) -> DetectResult | None:
    for system in _manifest_systems(manifest):
        emulator = config.get("emulators", {}).get(system, {})
        launch_type = emulator.get("launch_type", "exe")
        path = str(emulator.get("path", "")).strip().strip('"\'')
        flatpak_id = str(emulator.get("flatpak_id", "")).strip()

        if launch_type == "flatpak" and flatpak_id:
            if _flatpak_installed(flatpak_id):
                return DetectResult(True, "flatpak", flatpak_id)
        elif launch_type == "binary" and path:
            if shutil.which(path):
                return DetectResult(True, "binary", path)
        elif launch_type == "exe" and path:
            if Path(path).is_file():
                return DetectResult(True, "exe", str(Path(path)))
    return None


_WINDOWS_ENV = re.compile(r"%([^%]+)%")


def _expand_windows_path(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), os.environ.get(match.group(1).upper(), match.group(0)))

    return os.path.expandvars(_WINDOWS_ENV.sub(replace, value))


def _flatpak_installed(flatpak_id: str) -> bool:
    if not flatpak_id or shutil.which("flatpak") is None:
        return False
    try:
        result = subprocess.run(
            ["flatpak", "info", flatpak_id],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def detect_emulator(config: Mapping, manifest: EmulatorManifest) -> DetectResult:
    """Detect one emulator using the precedence specified by its manifest."""
    configured = _configured_result(config, manifest)
    if configured is not None:
        return configured

    for binary in manifest.detect.binaries:
        if shutil.which(binary):
            return DetectResult(True, "binary", binary)

    for candidate in manifest.detect.windows_paths:
        expanded = Path(_expand_windows_path(candidate))
        if expanded.is_file():
            return DetectResult(True, "exe", str(expanded))

    if _flatpak_installed(manifest.detect.flatpak_id):
        return DetectResult(True, "flatpak", manifest.detect.flatpak_id)

    return DetectResult(False)


def discover_emulators(
    config: Mapping,
    registry: ManifestRegistry | None = None,
) -> dict[str, DetectResult]:
    """Run discovery for every emulator in a registry."""
    registry = registry or load_registry(config)
    return {
        emulator_id: detect_emulator(config, manifest)
        for emulator_id, manifest in registry.manifests.items()
    }


def apply_detection(
    config: Mapping,
    results: Mapping[str, DetectResult],
    registry: ManifestRegistry | None = None,
) -> dict:
    """Fill empty system emulator slots from successful detection results."""
    updated = copy.deepcopy(config)
    registry = registry or load_registry(updated)
    emulators = updated.setdefault("emulators", {})

    for emulator_id, result in results.items():
        if not result.found:
            continue
        manifest = registry.get(emulator_id)
        if manifest is None:
            continue
        for profile in manifest.profiles:
            for system in profile.systems:
                slot = emulators.setdefault(system, {})
                if slot.get("path") or slot.get("flatpak_id"):
                    continue
                slot["profile"] = emulator_id
                slot["args"] = profile.args.replace("{core}", manifest.cores.get(system, ""))
                slot["launch_type"] = result.launch_type
                if result.launch_type == "flatpak":
                    slot["path"] = ""
                    slot["flatpak_id"] = result.path_or_id
                else:
                    slot["path"] = result.path_or_id
                    slot["flatpak_id"] = ""
    return updated
