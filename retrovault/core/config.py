"""Configuration defaults, loading, saving, and migration."""

import copy
import json
import logging

from .launch import _strip_wrapping_quotes, get_emulator_config
from .paths import CONFIG_FILE


# ── Default system definitions (modular — add more here) ──────────────────────
DEFAULT_SYSTEMS = {
    "nes": {
        "name": "Nintendo NES",
        "short": "NES",
        "extensions": [".nes"],
        "emulator_key": "nes",
        "color": "#e74c3c",
        "icon": "🎮",
    },
    "snes": {
        "name": "Super Nintendo",
        "short": "SNES",
        "extensions": [".sfc", ".smc"],
        "emulator_key": "snes",
        "color": "#8e44ad",
        "icon": "🕹️",
    },
    "gb": {
        "name": "Game Boy",
        "short": "GB",
        "extensions": [".gb"],
        "emulator_key": "gb",
        "color": "#27ae60",
        "icon": "📱",
    },
    "gba": {
        "name": "Game Boy Advance",
        "short": "GBA",
        "extensions": [".gba"],
        "emulator_key": "gba",
        "color": "#2980b9",
        "icon": "🎯",
    },
    "n64": {
        "name": "Nintendo 64",
        "short": "N64",
        "extensions": [".z64", ".n64", ".v64"],
        "emulator_key": "n64",
        "color": "#e67e22",
        "icon": "🏆",
    },
    "psx": {
        "name": "PlayStation 1",
        "short": "PSX",
        "extensions": [".bin", ".cue", ".iso", ".img"],
        "emulator_key": "psx",
        "color": "#2c3e50",
        "icon": "💿",
    },
    "genesis": {
        "name": "Sega Genesis",
        "short": "GEN",
        "extensions": [".md", ".bin", ".gen", ".smd"],
        "emulator_key": "genesis",
        "color": "#16a085",
        "icon": "⚡",
    },
    "gbc": {
        "name": "Game Boy Color",
        "short": "GBC",
        "extensions": [".gbc"],
        "emulator_key": "gbc",
        "color": "#f39c12",
        "icon": "🌈",
    },
}

EMULATOR_PRESETS = {
    "custom": {"name": "Custom", "args": "{rom}"},
    "project64": {"name": "Project64", "args": '"{rom}"'},
    "retroarch": {"name": "RetroArch", "args": "-L {core} {rom}"},
    "mgba": {"name": "mGBA", "args": '"{rom}"'},
    "duckstation": {"name": "DuckStation", "args": '"{rom}"'},
    "snes9x": {"name": "Snes9x", "args": '"{rom}"'},
    "fceux": {"name": "FCEUX", "args": '"{rom}"'},
}

RECOMMENDED_EMULATORS = {
    "nes": {
        "name": "MesenCE",
        "profile": "custom",
        "args": '"{rom}"',
        "url": "https://github.com/nesdev-org/MesenCE/releases",
        "notes": "Best all-around standalone pick for NES.",
    },
    "snes": {
        "name": "MesenCE",
        "profile": "custom",
        "args": '"{rom}"',
        "url": "https://github.com/nesdev-org/MesenCE/releases",
        "notes": "Shared with NES for a simple all-in-one setup.",
    },
    "gb": {
        "name": "mGBA",
        "profile": "mgba",
        "args": '"{rom}"',
        "url": "https://mgba.io/downloads.html",
        "notes": "Recommended for GB, GBC, and GBA.",
    },
    "gbc": {
        "name": "mGBA",
        "profile": "mgba",
        "args": '"{rom}"',
        "url": "https://mgba.io/downloads.html",
        "notes": "Recommended for GB, GBC, and GBA.",
    },
    "gba": {
        "name": "mGBA",
        "profile": "mgba",
        "args": '"{rom}"',
        "url": "https://mgba.io/downloads.html",
        "notes": "Recommended for GB, GBC, and GBA.",
    },
    "n64": {
        "name": "Rosalie's Mupen GUI",
        "profile": "custom",
        "args": '"{rom}"',
        "url": "https://github.com/Rosalie241/RMG/releases",
        "notes": "Default N64 recommendation. Project64 remains the familiar Windows alternate.",
    },
    "psx": {
        "name": "DuckStation",
        "profile": "duckstation",
        "args": '"{rom}"',
        "url": "https://github.com/stenzek/duckstation/releases/tag/latest",
        "notes": "Requires a BIOS from the user's own console.",
    },
    "genesis": {
        "name": "ares",
        "profile": "custom",
        "args": '"{rom}"',
        "url": "https://ares-emu.net/download",
        "notes": "Current Genesis default for Easy Mode.",
    },
}

SETUP_MODES = {
    "easy": {"name": "Easy Mode", "description": "Recommended standalone emulators with guided setup."},
    "advanced": {"name": "Advanced Mode", "description": "RetroArch and core management hooks live here later."},
}

DEFAULT_CONFIG = {
    "rom_dirs": [],
    "emulators": {
        "nes":     {"path": "", "args": "{rom}", "profile": "custom"},
        "snes":    {"path": "", "args": "{rom}", "profile": "custom"},
        "gb":      {"path": "", "args": "{rom}", "profile": "custom"},
        "gba":     {"path": "", "args": "{rom}", "profile": "custom"},
        "n64":     {"path": "", "args": "{rom}", "profile": "custom"},
        "psx":     {"path": "", "args": "{rom}", "profile": "custom"},
        "genesis": {"path": "", "args": "{rom}", "profile": "custom"},
        "gbc":     {"path": "", "args": "{rom}", "profile": "custom"},
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


def get_recommended_emulator(system_key):
    return copy.deepcopy(RECOMMENDED_EMULATORS.get(system_key, {}))


def apply_recommended_emulator(config, system_key, path=None):
    updated = copy.deepcopy(config)
    recommendation = get_recommended_emulator(system_key)
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
