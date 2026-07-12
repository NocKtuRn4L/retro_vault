"""Configuration defaults, loading, saving, and migration."""

import copy
import json
import logging
from importlib import resources

from .launch import _strip_wrapping_quotes, get_emulator_config
from .paths import CONFIG_FILE


def _load_json_data(filename):
    with resources.files("retrovault.data").joinpath(filename).open("r", encoding="utf-8") as f:
        return json.load(f)


# ── Default system definitions (modular — add more here) ──────────────────────
# Shipped as read-only package data; see retrovault/data/*.json.
DEFAULT_SYSTEMS = _load_json_data("systems.json")

EMULATOR_PRESETS = _load_json_data("profiles.json")

# Platform-keyed recommended-emulator picks (windows-x86_64, linux-x86_64, linux-aarch64).
RECOMMENDED_EMULATORS = _load_json_data("recommendations.json")

SETUP_MODES = {
    "easy": {"name": "Easy Mode", "description": "Recommended standalone emulators with guided setup."},
    "advanced": {"name": "Advanced Mode", "description": "RetroArch and core management hooks live here later."},
}

DEFAULT_CONFIG = {
    "rom_dirs": [],
    "emulators": {
        "nes":     {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
        "snes":    {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
        "gb":      {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
        "gba":     {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
        "n64":     {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
        "psx":     {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
        "genesis": {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
        "gbc":     {"path": "", "args": "{rom}", "profile": "custom", "launch_type": "exe", "flatpak_id": ""},
    },
    "emulator_profiles": EMULATOR_PRESETS,
    "setup": {
        "mode": "easy",
        "completed": False,
        "advanced_ready": True,
    },
    "retroarch_path": "",
    "use_retroarch": False,
    "retroarch_cores": {
        "nes":     "nestopia_libretro",
        "snes":    "snes9x_libretro",
        "gb":      "gambatte_libretro",
        "gba":     "mgba_libretro",
        "n64":     "mupen64plus_next_libretro",
        "psx":     "mednafen_psx_hw_libretro",
        "genesis": "genesis_plus_gx_libretro",
        "gbc":     "gambatte_libretro",
    },
    "systems": DEFAULT_SYSTEMS,
    "theme": "dark",
}


def _deep_merge(defaults, overrides):
    merged = copy.deepcopy(defaults)
    if not isinstance(overrides, dict):
        return merged
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def migrate_config(cfg):
    cfg = _deep_merge(DEFAULT_CONFIG, cfg)
    for sid, sdef in DEFAULT_SYSTEMS.items():
        cfg["systems"].setdefault(sid, copy.deepcopy(sdef))
        cfg["emulators"].setdefault(sid, {"path": "", "args": "{rom}", "profile": "custom"})
        cfg["emulators"][sid].setdefault("args", "{rom}")
        cfg["emulators"][sid].setdefault("profile", "custom")
        cfg["emulators"][sid].setdefault("launch_type", "exe")
        cfg["emulators"][sid].setdefault("flatpak_id", "")
    cfg["emulator_profiles"] = _deep_merge(EMULATOR_PRESETS, cfg.get("emulator_profiles", {}))
    cfg["setup"] = _deep_merge(DEFAULT_CONFIG["setup"], cfg.get("setup", {}))
    return cfg


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            return migrate_config(cfg)
        except Exception as e:
            logging.exception("Failed to load config: %s", e)
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def get_recommended_emulator(system_key, platform_key=None):
    if platform_key is None:
        platform_key = "windows-x86_64"

    for candidate in (platform_key, "linux-x86_64", "windows-x86_64"):
        table = RECOMMENDED_EMULATORS.get(candidate)
        if not table:
            continue
        recommendation = table.get(system_key)
        if recommendation:
            return copy.deepcopy(recommendation)
    return {}


def apply_recommended_emulator(config, system_key, path=None, platform_key=None):
    updated = copy.deepcopy(config)
    recommendation = get_recommended_emulator(system_key, platform_key)
    if not recommendation:
        return updated

    emulator_cfg = updated["emulators"].setdefault(system_key, {})
    emulator_cfg["profile"] = recommendation.get("profile", "custom")
    emulator_cfg["args"] = recommendation.get("args", "{rom}")
    if path is not None:
        emulator_cfg["path"] = path
    return updated


def is_emulator_configured(config, system_key):
    emu = get_emulator_config(system_key, config)
    return bool(_strip_wrapping_quotes(emu.get("path", "")))
