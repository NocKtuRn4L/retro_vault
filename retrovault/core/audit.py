"""Test-ROM manifest handling and emulator wiring audit."""

import copy
import json
import logging
import subprocess
from pathlib import Path

from .config import _deep_merge
from .launch import build_launch_command, get_emulator_config
from .paths import TEST_ROM_FILE

DEFAULT_TEST_ROM_MANIFEST = {
    "nes": {
        "path": "",
        "label": "NES smoke ROM",
        "notes": "Use a legal homebrew or test ROM.",
    },
    "snes": {
        "path": "",
        "label": "SNES smoke ROM",
        "notes": "Use a legal homebrew or test ROM.",
    },
    "gb": {
        "path": "",
        "label": "Game Boy smoke ROM",
        "notes": "Use a legal homebrew or test ROM.",
    },
    "gbc": {
        "path": "",
        "label": "Game Boy Color smoke ROM",
        "notes": "Use a legal homebrew or test ROM.",
    },
    "gba": {
        "path": "",
        "label": "Game Boy Advance smoke ROM",
        "notes": "Use a legal homebrew or test ROM.",
    },
    "n64": {
        "path": "",
        "label": "Nintendo 64 smoke ROM",
        "notes": "Use a legal homebrew ROM.",
    },
    "psx": {
        "path": "",
        "label": "PlayStation smoke image",
        "notes": "Use a legal homebrew image and a BIOS you own if required.",
    },
    "genesis": {
        "path": "",
        "label": "Genesis smoke ROM",
        "notes": "Use a legal homebrew or test ROM.",
    },
}


def load_test_rom_manifest(path=TEST_ROM_FILE):
    if Path(path).exists():
        try:
            with open(path) as f:
                manifest = json.load(f)
            return _deep_merge(DEFAULT_TEST_ROM_MANIFEST, manifest)
        except Exception as e:
            logging.exception("Failed to load test ROM manifest: %s", e)
    return copy.deepcopy(DEFAULT_TEST_ROM_MANIFEST)


def save_test_rom_manifest(manifest, path=TEST_ROM_FILE):
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)


def audit_test_roms(config, manifest):
    results = []
    for system_key, entry in manifest.items():
        rom_path = entry.get("path", "").strip()
        if not rom_path:
            results.append({
                "system": system_key,
                "status": "missing_rom",
                "message": "No test ROM configured.",
            })
            continue

        rom = {
            "name": Path(rom_path).stem,
            "path": rom_path,
            "system": system_key,
            "ext": Path(rom_path).suffix.lower(),
        }
        cmd, error = build_launch_command(rom, config, validate=True)
        if error:
            results.append({
                "system": system_key,
                "status": "error",
                "message": error,
            })
            continue

        status = "ok"
        if not config.get("use_retroarch"):
            launch_type = get_emulator_config(system_key, config).get("launch_type", "exe")
            if launch_type != "exe":
                status = f"ok [{launch_type}]"
        results.append({
            "system": system_key,
            "status": status,
            "message": subprocess.list2cmdline(cmd),
        })
    return results
