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
    "remote_catalog_url": "",
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
    # Window-mode policy for the RetroVault frontend itself (see
    # retrovault.ui.main_window.MainWindow.apply_window_mode):
    #   "desktop"    — normal windowed (dev/PC default)
    #   "fullscreen" — borderless fullscreen frontend
    #   "kiosk"      — frameless + fullscreen for boot-to-frontend
    "window_mode": "desktop",
    # Global fullscreen preference applied on top of each emulator's manifest policy:
    #   "emulator"       — use each emulator's own fullscreen policy (arg/config/inherit)
    #   "prefer"         — prefer fullscreen wherever supported, including "inherit" emulators
    #   "force_windowed" — never force fullscreen
    # RetroArch defaults to fullscreen in Raspberry Pi kiosk mode; see
    # retrovault.providers.manifest.effective_fullscreen for the resolver.
    "fullscreen_preference": "emulator",
    "controller": {
        "enabled": True,
        "dead_zone": 0.35,        # left-stick dead zone, 0..1
        "repeat_delay_ms": 400,   # initial delay before a held direction repeats
        "repeat_rate_ms": 120,    # interval between repeats while held
        "accept_button": "south",  # "south" or "east" — which face button is Accept
        # Prefer RetroArch (centralized controller autoconfig -> seamless pads with
        # no per-emulator setup) whenever it's configured with a core for a system.
        # Inert until RetroArch is actually set up, so a fresh install keeps using
        # its curated standalone emulators. See core.launch.use_retroarch_for.
        "prefer_retroarch": True,
    },
    # Metadata + artwork scraping (see retrovault.providers.scraper). The default
    # "libretro" provider (libretro-thumbnails) needs no account and matches box
    # art by ROM name. "screenscraper" is richer (hash-accurate + text metadata)
    # but requires user credentials. Scraping only runs when the user asks for it.
    "scraper": {
        "provider": "libretro",
        "username": "",
        "password": "",
        "region": "us",
        "enabled": False,
    },
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
    cfg["controller"] = _deep_merge(DEFAULT_CONFIG["controller"], cfg.get("controller", {}))
    cfg["scraper"] = _deep_merge(DEFAULT_CONFIG["scraper"], cfg.get("scraper", {}))
    cfg.setdefault("fullscreen_preference", DEFAULT_CONFIG["fullscreen_preference"])
    cfg.setdefault("window_mode", DEFAULT_CONFIG["window_mode"])
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
    if emu.get("launch_type") == "flatpak":
        return bool(emu.get("flatpak_id", "").strip())
    return bool(_strip_wrapping_quotes(emu.get("path", "")))
