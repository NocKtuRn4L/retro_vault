#!/usr/bin/env python3
"""
RetroVault - Modular ROM Launcher
A cross-platform desktop frontend for managing and launching ROMs
via external emulator backends.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import copy
import json
import logging
import os
import shlex
import subprocess
import sys
import webbrowser
from pathlib import Path
import threading


# ── Config paths ──────────────────────────────────────────────────────────────
APP_DIR = Path.home() / ".retrovault"
CONFIG_FILE = APP_DIR / "config.json"
LIBRARY_FILE = APP_DIR / "library.json"
LOG_FILE = APP_DIR / "retrovault.log"
TEST_ROM_FILE = APP_DIR / "test_roms.json"

APP_DIR.mkdir(exist_ok=True)
try:
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
except OSError:
    logging.basicConfig(level=logging.CRITICAL)


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


# ── Config helpers ─────────────────────────────────────────────────────────────
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


def load_library():
    if LIBRARY_FILE.exists():
        try:
            with open(LIBRARY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_library(lib):
    with open(LIBRARY_FILE, "w") as f:
        json.dump(lib, f, indent=2)


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

        results.append({
            "system": system_key,
            "status": "ok",
            "message": subprocess.list2cmdline(cmd),
        })
    return results


# ── ROM scanning ───────────────────────────────────────────────────────────────
def scan_roms(config):
    library = []
    ext_to_system = {}
    for sid, sdef in config["systems"].items():
        for ext in sdef["extensions"]:
            ext_to_system[ext.lower()] = sid

    for rom_dir in config["rom_dirs"]:
        p = Path(rom_dir)
        if not p.is_dir():
            continue
        for f in p.rglob("*"):
            if f.is_file():
                ext = f.suffix.lower()
                if ext in ext_to_system:
                    library.append({
                        "name": f.stem,
                        "path": str(f),
                        "system": ext_to_system[ext],
                        "ext": ext,
                    })
    library.sort(key=lambda x: (x["system"], x["name"].lower()))
    return library


# ── Launch logic ───────────────────────────────────────────────────────────────
def _strip_wrapping_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _split_args_template(args_template, rom_path, platform=None):
    platform = platform or sys.platform
    args_template = (args_template or "{rom}").strip()

    if not args_template or "{rom}" not in args_template:
        return [rom_path]

    if platform == "win32":
        placeholder = "__RETROVAULT_ROM_PATH__"
        args_str = args_template.replace("{rom}", placeholder)
        try:
            parts = shlex.split(args_str, posix=False)
        except ValueError:
            return [rom_path]
        return [
            rom_path if _strip_wrapping_quotes(part) == placeholder else _strip_wrapping_quotes(part)
            for part in parts
        ]

    rom_quoted = shlex.quote(rom_path)
    args_str = args_template.replace("{rom}", rom_quoted)
    try:
        return shlex.split(args_str, posix=True)
    except ValueError:
        return [rom_path]


def _resolve_core_arg(arg, config, system_key):
    if arg != "{core}":
        return arg
    return config.get("retroarch_cores", {}).get(system_key, "")


def get_emulator_config(system_key, config):
    emu = copy.deepcopy(config.get("emulators", {}).get(system_key, {}))
    profile_key = emu.get("profile", "custom")
    profile = config.get("emulator_profiles", {}).get(profile_key, {})
    if not emu.get("args") and profile.get("args"):
        emu["args"] = profile["args"]
    emu.setdefault("args", "{rom}")
    emu.setdefault("profile", profile_key)
    return emu


def validate_launch(rom, config):
    system_key = rom.get("system", "")
    rom_path = rom.get("path", "")
    if not rom_path or not Path(rom_path).is_file():
        return f"ROM file not found:\n{rom_path}"

    if config.get("use_retroarch"):
        retroarch_path = _strip_wrapping_quotes(config.get("retroarch_path", ""))
        if not retroarch_path:
            return "RetroArch is enabled, but no RetroArch binary is configured."
        if not Path(retroarch_path).is_file():
            return f"RetroArch executable not found:\n{retroarch_path}"
        core = config.get("retroarch_cores", {}).get(system_key, "")
        if not core:
            return "No RetroArch core configured for this system."
        return None

    emu = get_emulator_config(system_key, config)
    emu_path = _strip_wrapping_quotes(emu.get("path", ""))
    if not emu_path:
        return f"No emulator configured for {system_key.upper()}.\nGo to Settings -> Emulators to set one up."
    if not Path(emu_path).is_file():
        return f"Emulator executable not found:\n{emu_path}\n\nCheck the path in Settings -> Emulators."
    return None


def build_launch_command(rom, config, platform=None, validate=True):
    platform = platform or sys.platform
    system_key = rom["system"]
    rom_path = rom["path"]

    if validate:
        error = validate_launch(rom, config)
        if error:
            return None, error

    if config.get("use_retroarch") and config.get("retroarch_path"):
        ra = _strip_wrapping_quotes(config["retroarch_path"])
        core = config["retroarch_cores"].get(system_key, "")
        if not core:
            return None, "No RetroArch core configured for this system."
        return [ra, "-L", core, rom_path], None

    emu = get_emulator_config(system_key, config)
    emu_path = _strip_wrapping_quotes(emu.get("path", ""))
    if not emu_path:
        return None, f"No emulator configured for {system_key.upper()}.\nGo to Settings -> Emulators to set one up."

    extra_args = _split_args_template(emu.get("args", "{rom}"), rom_path, platform=platform)
    extra_args = [_resolve_core_arg(arg, config, system_key) for arg in extra_args]
    return [emu_path] + extra_args, None


def _windows_launch_details(cmd):
    exe_path = Path(cmd[0])
    working_dir = str(exe_path.parent) if exe_path.parent != Path(".") else None
    return subprocess.list2cmdline(cmd[1:]), working_dir


def _command_working_dir(cmd):
    exe_path = Path(cmd[0])
    if exe_path.parent == Path("."):
        return None
    return str(exe_path.parent)


def _windows_shell_execute(cmd, verb="open"):
    import ctypes

    params, working_dir = _windows_launch_details(cmd)
    return ctypes.windll.shell32.ShellExecuteW(
        None,       # hwnd
        verb,       # "open" respects the EXE manifest; "runas" forces elevation.
        cmd[0],     # exe path
        params,     # arguments
        working_dir,
        1,          # SW_SHOWNORMAL
    )


def launch_rom(rom, config):
    cmd, error = build_launch_command(rom, config)
    if error:
        logging.warning("Launch validation failed for %s: %s", rom.get("path"), error)
        return False, error


    try:
        logging.info("Launching ROM '%s' with command: %s", rom.get("name"), subprocess.list2cmdline(cmd))
        if sys.platform == "win32":
            try:
                proc = subprocess.Popen(cmd, cwd=_command_working_dir(cmd))
                logging.info("Launch started with pid %s", proc.pid)
                return True, f"Launched! PID {proc.pid}"
            except PermissionError:
                logging.info("Popen permission denied; retrying with ShellExecute runas")
                ret = _windows_shell_execute(cmd, verb="runas")
            except OSError as e:
                logging.info("Popen failed with %s; retrying with ShellExecute open", e)
                ret = _windows_shell_execute(cmd, verb="open")
            # ShellExecuteW returns > 32 on success
            if ret <= 32:
                logging.error("ShellExecute failed with code %s for %s", ret, cmd[0])
                return False, (
                    f"ShellExecute failed (code {ret}) launching:\n{cmd[0]}\n\n"
                    "Make sure the path is correct in Settings → Emulators."
                )
            logging.info("Launch handed to ShellExecute with code %s", ret)
        else:
            proc = subprocess.Popen(cmd, cwd=_command_working_dir(cmd), close_fds=True)
            logging.info("Launch started with pid %s", proc.pid)
        return True, "Launched!"
    except FileNotFoundError:
        logging.exception("Emulator executable not found")
        return False, (
            f"Emulator executable not found:\n{cmd[0]}\n\n"
            "Check the path in Settings → Emulators."
        )
    except PermissionError:
        logging.exception("Permission denied launching emulator")
        return False, (
            f"Permission denied launching:\n{cmd[0]}\n\n"
            "Windows blocked the launch even with elevation.\n"
            "Try running RetroVault itself as administrator."
        )
    except Exception as e:
        logging.exception("Unexpected launch error")
        return False, f"{type(e).__name__}: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════════════════════

COLORS = {
    "bg":        "#0d0d0d",
    "panel":     "#141414",
    "card":      "#1a1a1a",
    "border":    "#2a2a2a",
    "accent":    "#ff3c3c",
    "accent2":   "#ff8c00",
    "text":      "#f0f0f0",
    "subtext":   "#888888",
    "hover":     "#252525",
    "selected":  "#1f1f1f",
    "success":   "#00c853",
    "warning":   "#ffd600",
}

FONTS = {
    "title":   ("Courier New", 22, "bold"),
    "heading": ("Courier New", 13, "bold"),
    "body":    ("Courier New", 11),
    "small":   ("Courier New", 9),
    "tag":     ("Courier New", 8, "bold"),
}


class RetroVault(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RetroVault")
        self.geometry("1100x700")
        self.minsize(800, 550)
        self.configure(bg=COLORS["bg"])

        self.config_data = load_config()
        self.library = load_library()
        self.filtered_library = list(self.library)
        self.selected_system = "all"
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._on_search)
        self.status_var = tk.StringVar(value="Welcome to RetroVault")

        self._build_ui()
        self._refresh_library_view()
        self.after(250, self._maybe_open_setup_wizard)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        topbar = tk.Frame(self, bg=COLORS["bg"], height=60)
        topbar.pack(fill=tk.X, padx=0, pady=0)
        topbar.pack_propagate(False)

        title_lbl = tk.Label(topbar, text="▶ RETROVAULT",
                             font=FONTS["title"], bg=COLORS["bg"],
                             fg=COLORS["accent"])
        title_lbl.pack(side=tk.LEFT, padx=20, pady=10)

        # Search
        search_frame = tk.Frame(topbar, bg=COLORS["border"], bd=0)
        search_frame.pack(side=tk.LEFT, padx=10, pady=14)
        tk.Label(search_frame, text=" 🔍 ", bg=COLORS["border"],
                 fg=COLORS["subtext"], font=FONTS["body"]).pack(side=tk.LEFT)
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var,
                                     bg=COLORS["border"], fg=COLORS["text"],
                                     insertbackground=COLORS["text"],
                                     relief=tk.FLAT, font=FONTS["body"], width=28,
                                     bd=4)
        self.search_entry.pack(side=tk.LEFT)

        # Buttons
        btn_frame = tk.Frame(topbar, bg=COLORS["bg"])
        btn_frame.pack(side=tk.RIGHT, padx=16)
        self._btn(btn_frame, "⟳ SCAN ROMS", self._scan_roms, accent=True).pack(side=tk.RIGHT, padx=4)
        self._btn(btn_frame, "⚙ SETTINGS", self._open_settings).pack(side=tk.RIGHT, padx=4)
        self._btn(btn_frame, "SETUP", self._open_setup_wizard).pack(side=tk.RIGHT, padx=4)
        self._btn(btn_frame, "+ ADD ROM DIR", self._add_rom_dir).pack(side=tk.RIGHT, padx=4)

        # Divider
        tk.Frame(self, bg=COLORS["accent"], height=2).pack(fill=tk.X)

        # Main area
        main = tk.Frame(self, bg=COLORS["bg"])
        main.pack(fill=tk.BOTH, expand=True)

        # Left sidebar
        sidebar = tk.Frame(main, bg=COLORS["panel"], width=190)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="SYSTEMS", font=FONTS["tag"],
                 bg=COLORS["panel"], fg=COLORS["subtext"],
                 padx=16, pady=12).pack(anchor="w")

        self.sidebar_frame = tk.Frame(sidebar, bg=COLORS["panel"])
        self.sidebar_frame.pack(fill=tk.BOTH, expand=True)
        self._build_sidebar()

        # Separator
        tk.Frame(main, bg=COLORS["border"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # Right: ROM list
        right = tk.Frame(main, bg=COLORS["bg"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Column headers
        header = tk.Frame(right, bg=COLORS["card"], height=32)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        for text, anchor, width in [("GAME", "w", 500), ("SYSTEM", "center", 120), ("EXT", "center", 70)]:
            tk.Label(header, text=text, font=FONTS["tag"], bg=COLORS["card"],
                     fg=COLORS["subtext"], anchor=anchor, width=width//8,
                     padx=16).pack(side=tk.LEFT)

        # Scrollable list
        list_frame = tk.Frame(right, bg=COLORS["bg"])
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, bg=COLORS["border"],
                                  troughcolor=COLORS["bg"],
                                  activebackground=COLORS["accent"])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"],
                                 highlightthickness=0,
                                 yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.canvas.yview)

        self.rom_list_inner = tk.Frame(self.canvas, bg=COLORS["bg"])
        self.canvas_window = self.canvas.create_window((0, 0), window=self.rom_list_inner, anchor="nw")

        self.rom_list_inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Status bar
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill=tk.X)
        statusbar = tk.Frame(self, bg=COLORS["panel"], height=28)
        statusbar.pack(fill=tk.X)
        statusbar.pack_propagate(False)
        self.status_lbl = tk.Label(statusbar, textvariable=self.status_var,
                                    font=FONTS["small"], bg=COLORS["panel"],
                                    fg=COLORS["subtext"], padx=16)
        self.status_lbl.pack(side=tk.LEFT, pady=4)

        self.count_lbl = tk.Label(statusbar, text="",
                                   font=FONTS["small"], bg=COLORS["panel"],
                                   fg=COLORS["subtext"], padx=16)
        self.count_lbl.pack(side=tk.RIGHT, pady=4)

    def _btn(self, parent, text, cmd, accent=False):
        bg = COLORS["accent"] if accent else COLORS["card"]
        fg = COLORS["bg"] if accent else COLORS["text"]
        b = tk.Label(parent, text=text, font=FONTS["tag"],
                     bg=bg, fg=fg, padx=12, pady=6, cursor="hand2",
                     relief=tk.FLAT)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg=COLORS["accent2"] if accent else COLORS["hover"]))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _build_sidebar(self):
        for w in self.sidebar_frame.winfo_children():
            w.destroy()

        systems = self.config_data.get("systems", {})
        counts = {}
        for rom in self.library:
            counts[rom["system"]] = counts.get(rom["system"], 0) + 1

        entries = [("all", "🗂", "ALL GAMES", len(self.library))]
        for sid, sdef in systems.items():
            if counts.get(sid, 0) > 0:
                entries.append((sid, sdef["icon"], sdef["short"], counts.get(sid, 0)))

        for sid, icon, label, count in entries:
            is_sel = self.selected_system == sid
            row = tk.Frame(self.sidebar_frame,
                            bg=COLORS["accent"] if is_sel else COLORS["panel"],
                            cursor="hand2")
            row.pack(fill=tk.X, padx=8, pady=2)

            tk.Label(row, text=f"{icon} {label}", font=FONTS["body"],
                     bg=row["bg"], fg=COLORS["bg"] if is_sel else COLORS["text"],
                     padx=12, pady=7, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(row, text=str(count), font=FONTS["small"],
                     bg=row["bg"],
                     fg=COLORS["bg"] if is_sel else COLORS["subtext"],
                     padx=8).pack(side=tk.RIGHT)

            row.bind("<Button-1>", lambda e, s=sid: self._select_system(s))
            for child in row.winfo_children():
                child.bind("<Button-1>", lambda e, s=sid: self._select_system(s))
            row.bind("<Enter>", lambda e, r=row, s=sid: r.config(
                bg=COLORS["accent"] if self.selected_system == s else COLORS["hover"]))
            row.bind("<Leave>", lambda e, r=row, s=sid: r.config(
                bg=COLORS["accent"] if self.selected_system == s else COLORS["panel"]))

    def _refresh_library_view(self):
        for w in self.rom_list_inner.winfo_children():
            w.destroy()

        query = self.search_var.get().strip().lower()
        systems = self.config_data.get("systems", {})

        self.filtered_library = [
            r for r in self.library
            if (self.selected_system == "all" or r["system"] == self.selected_system)
            and (not query or query in r["name"].lower())
        ]

        if not self.filtered_library:
            msg = "No ROMs found."
            if not self.library:
                msg = "No ROMs in library.\nClick '+ ADD ROM DIR' to add a folder,\nthen '⟳ SCAN ROMS'."
            tk.Label(self.rom_list_inner, text=msg, font=FONTS["body"],
                     bg=COLORS["bg"], fg=COLORS["subtext"],
                     pady=60).pack()
        else:
            for i, rom in enumerate(self.filtered_library):
                self._make_rom_row(i, rom, systems)

        count_text = f"{len(self.filtered_library)} ROM{'s' if len(self.filtered_library) != 1 else ''}"
        self.count_lbl.config(text=count_text)
        self._build_sidebar()

    def _make_rom_row(self, i, rom, systems):
        sdef = systems.get(rom["system"], {})
        color = sdef.get("color", COLORS["subtext"])
        icon = sdef.get("icon", "?")
        sname = sdef.get("short", rom["system"].upper())
        bg = COLORS["bg"] if i % 2 == 0 else COLORS["card"]

        row = tk.Frame(self.rom_list_inner, bg=bg, cursor="hand2")
        row.pack(fill=tk.X)

        # Icon + name
        name_frame = tk.Frame(row, bg=bg)
        name_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=16, pady=7)
        tk.Label(name_frame, text=icon, font=FONTS["body"],
                 bg=bg, fg=color).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(name_frame, text=rom["name"], font=FONTS["body"],
                 bg=bg, fg=COLORS["text"], anchor="w").pack(side=tk.LEFT)

        # System badge
        badge = tk.Label(row, text=sname, font=FONTS["tag"],
                          bg=color, fg="white", padx=6, pady=2, width=7)
        badge.pack(side=tk.RIGHT, padx=(0, 80), pady=5)

        # Ext
        tk.Label(row, text=rom["ext"], font=FONTS["small"],
                 bg=bg, fg=COLORS["subtext"], width=6).pack(side=tk.RIGHT, padx=8)

        # Hover + click
        def on_enter(e, r=row, children=None):
            r.config(bg=COLORS["hover"])
            for c in r.winfo_children():
                try:
                    c.config(bg=COLORS["hover"])
                except Exception:
                    pass
                for cc in c.winfo_children():
                    try:
                        cc.config(bg=COLORS["hover"])
                    except Exception:
                        pass

        def on_leave(e, r=row, orig=bg):
            r.config(bg=orig)
            for c in r.winfo_children():
                try:
                    c.config(bg=orig)
                except Exception:
                    pass
                for cc in c.winfo_children():
                    try:
                        cc.config(bg=orig)
                    except Exception:
                        pass

        def on_click(e, r=rom):
            self._launch(r)

        row.bind("<Enter>", on_enter)
        row.bind("<Leave>", on_leave)
        row.bind("<Double-Button-1>", on_click)
        for child in row.winfo_children():
            child.bind("<Double-Button-1>", on_click)
            child.bind("<Enter>", on_enter)
            child.bind("<Leave>", on_leave)
            for cc in child.winfo_children():
                cc.bind("<Double-Button-1>", on_click)
                cc.bind("<Enter>", on_enter)
                cc.bind("<Leave>", on_leave)

        # Right-click context menu
        def show_menu(e, r=rom):
            menu = tk.Menu(self, tearoff=0, bg=COLORS["card"],
                            fg=COLORS["text"], activebackground=COLORS["accent"],
                            activeforeground=COLORS["bg"],
                            font=FONTS["small"], bd=0)
            menu.add_command(label=f"▶  Launch {r['name']}", command=lambda: self._launch(r))
            menu.add_separator()
            menu.add_command(label="📂  Open file location",
                              command=lambda: self._open_location(r))
            menu.add_command(label="🗑  Remove from library",
                              command=lambda: self._remove_rom(r))
            menu.tk_popup(e.x_root, e.y_root)

        row.bind("<Button-3>", show_menu)
        for child in row.winfo_children():
            child.bind("<Button-3>", show_menu)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _select_system(self, sid):
        self.selected_system = sid
        self._refresh_library_view()

    def _on_search(self, *args):
        self._refresh_library_view()

    def _launch(self, rom):
        self.status_var.set(f"Launching {rom['name']}...")
        def do_launch():
            ok, msg = launch_rom(rom, self.config_data)
            self.after(0, self._post_launch, rom, ok, msg)

        threading.Thread(target=do_launch, daemon=True).start()

    def _post_launch(self, rom, ok, msg):
        if ok:
            self.status_var.set(f"▶ Launched: {rom['name']}")
        else:
            self.status_var.set(f"⚠ Launch failed")
            messagebox.showerror("Launch Error", msg, parent=self)

    def _open_location(self, rom):
        path = Path(rom["path"]).parent
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _remove_rom(self, rom):
        self.library = [r for r in self.library if r["path"] != rom["path"]]
        save_library(self.library)
        self._refresh_library_view()
        self.status_var.set(f"Removed: {rom['name']}")

    def _add_rom_dir(self):
        d = filedialog.askdirectory(title="Select ROM Directory", parent=self)
        if d and d not in self.config_data["rom_dirs"]:
            self.config_data["rom_dirs"].append(d)
            save_config(self.config_data)
            self.status_var.set(f"Added ROM directory: {d}")

    def _scan_roms(self):
        self.status_var.set("Scanning...")
        self.update()

        def do_scan():
            new_lib = scan_roms(self.config_data)
            save_library(new_lib)
            self.library = new_lib
            self.after(0, self._post_scan, len(new_lib))

        threading.Thread(target=do_scan, daemon=True).start()

    def _post_scan(self, count):
        self._refresh_library_view()
        self.status_var.set(f"Scan complete — {count} ROM{'s' if count != 1 else ''} found")

    # ── Settings window ────────────────────────────────────────────────────────

    def _maybe_open_setup_wizard(self):
        if not self.config_data.get("setup", {}).get("completed", False):
            self._open_setup_wizard()

    def _open_url(self, url):
        try:
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Open URL", f"Could not open:\n{url}\n\n{type(e).__name__}: {e}", parent=self)

    def _open_setup_wizard(self):
        win = tk.Toplevel(self)
        win.title("RetroVault Setup")
        win.geometry("980x640")
        win.configure(bg=COLORS["bg"])
        win.grab_set()

        setup_cfg = self.config_data.get("setup", {})
        mode_var = tk.StringVar(value=setup_cfg.get("mode", "easy"))

        tk.Label(win, text="SETUP", font=FONTS["heading"],
                 bg=COLORS["bg"], fg=COLORS["accent"], padx=20, pady=14).pack(anchor="w")
        tk.Frame(win, bg=COLORS["accent"], height=2).pack(fill=tk.X)
        tk.Label(
            win,
            text="Easy Mode keeps RetroVault focused on recommended standalone emulators. "
                 "Advanced Mode is reserved for RetroArch and core setup later.",
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            padx=20,
            pady=12,
            justify=tk.LEFT,
            wraplength=920,
        ).pack(anchor="w")

        mode_row = tk.Frame(win, bg=COLORS["bg"])
        mode_row.pack(fill=tk.X, padx=20, pady=(0, 8))
        tk.Radiobutton(
            mode_row,
            text=SETUP_MODES["easy"]["name"],
            variable=mode_var,
            value="easy",
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["text"],
            selectcolor=COLORS["card"],
            activebackground=COLORS["bg"],
        ).pack(side=tk.LEFT, padx=(0, 16))
        tk.Radiobutton(
            mode_row,
            text=f"{SETUP_MODES['advanced']['name']} (Coming Soon)",
            variable=mode_var,
            value="advanced",
            state=tk.DISABLED,
            font=FONTS["body"],
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            selectcolor=COLORS["card"],
            activebackground=COLORS["bg"],
        ).pack(side=tk.LEFT)

        easy_frame = tk.LabelFrame(
            win,
            text=" Easy Mode Recommendations ",
            font=FONTS["tag"],
            bg=COLORS["bg"],
            fg=COLORS["accent"],
            bd=1,
            relief=tk.GROOVE,
        )
        easy_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=8)

        setup_vars = {}
        for sid, sdef in self.config_data["systems"].items():
            recommendation = get_recommended_emulator(sid)
            emu_cfg = get_emulator_config(sid, self.config_data)
            path_var = tk.StringVar(value=emu_cfg.get("path", ""))
            setup_vars[sid] = path_var

            row = tk.Frame(easy_frame, bg=COLORS["bg"])
            row.pack(fill=tk.X, padx=10, pady=6)

            left = tk.Frame(row, bg=COLORS["bg"], width=280)
            left.pack(side=tk.LEFT, fill=tk.Y)
            left.pack_propagate(False)
            tk.Label(left, text=f"{sdef['short']}  {recommendation.get('name', 'Custom')}",
                     font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["text"],
                     anchor="w").pack(fill=tk.X)
            tk.Label(left, text=recommendation.get("notes", "No recommendation yet."),
                     font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["subtext"],
                     anchor="w", justify=tk.LEFT, wraplength=260).pack(fill=tk.X)

            center = tk.Frame(row, bg=COLORS["bg"])
            center.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
            tk.Entry(center, textvariable=path_var, font=FONTS["small"],
                     bg=COLORS["card"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], relief=tk.FLAT).pack(fill=tk.X)

            actions = tk.Frame(row, bg=COLORS["bg"])
            actions.pack(side=tk.RIGHT)
            self._btn(actions, "DOWNLOAD", lambda rec=recommendation: self._open_url(rec["url"])).pack(side=tk.LEFT, padx=4)
            self._btn(actions, "BROWSE", lambda v=path_var: self._browse_file(v)).pack(side=tk.LEFT, padx=4)
            status_text = "READY" if is_emulator_configured(self.config_data, sid) else "NEEDED"
            status_fg = COLORS["success"] if status_text == "READY" else COLORS["warning"]
            tk.Label(actions, text=status_text, font=FONTS["tag"],
                     bg=COLORS["bg"], fg=status_fg, padx=6, pady=6).pack(side=tk.LEFT)

        tk.Label(
            win,
            text="Save uses recommended standalone emulator profiles and turns RetroArch off. "
                 "Advanced Mode will reuse this setup model later for RetroArch/core workflows.",
            font=FONTS["small"],
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            padx=20,
            pady=8,
            justify=tk.LEFT,
            wraplength=920,
        ).pack(anchor="w")

        def save_setup():
            self.config_data["setup"]["mode"] = "easy"
            self.config_data["setup"]["completed"] = True
            self.config_data["use_retroarch"] = False
            for sid, path_var in setup_vars.items():
                self.config_data = apply_recommended_emulator(self.config_data, sid, path=path_var.get())
            save_config(self.config_data)
            self.status_var.set("Easy Mode setup saved.")
            win.destroy()

        tk.Frame(win, bg=COLORS["border"], height=1).pack(fill=tk.X)
        save_row = tk.Frame(win, bg=COLORS["bg"])
        save_row.pack(fill=tk.X, padx=16, pady=10)
        self._btn(save_row, "SAVE EASY MODE", save_setup, accent=True).pack(side=tk.RIGHT)
        self._btn(save_row, "CLOSE", win.destroy).pack(side=tk.RIGHT, padx=8)

    def _open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings — RetroVault")
        win.geometry("980x620")
        win.configure(bg=COLORS["bg"])
        win.grab_set()

        tk.Label(win, text="⚙ SETTINGS", font=FONTS["heading"],
                 bg=COLORS["bg"], fg=COLORS["accent"], padx=20, pady=14).pack(anchor="w")
        tk.Frame(win, bg=COLORS["accent"], height=2).pack(fill=tk.X)

        notebook = ttk.Notebook(win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["card"],
                         foreground=COLORS["text"], padding=[12, 6],
                         font=FONTS["tag"])
        style.map("TNotebook.Tab", background=[("selected", COLORS["accent"])],
                   foreground=[("selected", COLORS["bg"])])

        # Tab 1: Emulators
        emu_frame = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(emu_frame, text="EMULATORS")

        ra_frame = tk.LabelFrame(emu_frame, text=" RetroArch ", font=FONTS["tag"],
                                   bg=COLORS["bg"], fg=COLORS["accent"],
                                   bd=1, relief=tk.GROOVE)
        ra_frame.pack(fill=tk.X, padx=12, pady=8)

        use_ra_var = tk.BooleanVar(value=self.config_data.get("use_retroarch", False))
        tk.Checkbutton(ra_frame, text="Use RetroArch as universal backend",
                        variable=use_ra_var, font=FONTS["body"],
                        bg=COLORS["bg"], fg=COLORS["text"],
                        selectcolor=COLORS["card"],
                        activebackground=COLORS["bg"]).pack(anchor="w", padx=8, pady=4)

        ra_path_var = tk.StringVar(value=self.config_data.get("retroarch_path", ""))
        self._path_row(ra_frame, "RetroArch binary:", ra_path_var, file=True)

        # Per-system emulators
        sys_frame = tk.LabelFrame(emu_frame, text=" Standalone Emulators ",
                                    font=FONTS["tag"], bg=COLORS["bg"],
                                    fg=COLORS["accent"], bd=1, relief=tk.GROOVE)
        sys_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        canvas2 = tk.Canvas(sys_frame, bg=COLORS["bg"], highlightthickness=0)
        sb2 = tk.Scrollbar(sys_frame, command=canvas2.yview)
        canvas2.configure(yscrollcommand=sb2.set)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        canvas2.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas2, bg=COLORS["bg"])
        canvas2.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas2.configure(scrollregion=canvas2.bbox("all")))

        emu_vars = {}
        profiles = self.config_data.get("emulator_profiles", EMULATOR_PRESETS)
        profile_choices = list(profiles.keys())
        for sid, sdef in self.config_data["systems"].items():
            emu_cfg = get_emulator_config(sid, self.config_data)
            path_var = tk.StringVar(value=emu_cfg.get("path", ""))
            args_var = tk.StringVar(value=emu_cfg.get("args", "{rom}"))
            profile_var = tk.StringVar(value=emu_cfg.get("profile", "custom"))
            emu_vars[sid] = (path_var, args_var, profile_var)

            row = tk.Frame(inner, bg=COLORS["bg"])
            row.pack(fill=tk.X, padx=8, pady=3)
            tk.Label(row, text=f"{sdef['icon']} {sdef['name']}",
                      font=FONTS["body"], bg=COLORS["bg"],
                      fg=COLORS["text"], width=22, anchor="w").pack(side=tk.LEFT)
            tk.Entry(row, textvariable=path_var, font=FONTS["small"],
                      bg=COLORS["card"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], relief=tk.FLAT,
                      width=28).pack(side=tk.LEFT, padx=4)
            tk.Label(row, text="args:", font=FONTS["small"],
                      bg=COLORS["bg"], fg=COLORS["subtext"]).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=args_var, font=FONTS["small"],
                      bg=COLORS["card"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], relief=tk.FLAT,
                      width=14).pack(side=tk.LEFT, padx=4)
            tk.Label(row, text="profile:", font=FONTS["small"],
                      bg=COLORS["bg"], fg=COLORS["subtext"]).pack(side=tk.LEFT)
            profile_menu = tk.OptionMenu(row, profile_var, *profile_choices)
            profile_menu.config(bg=COLORS["card"], fg=COLORS["text"],
                                activebackground=COLORS["hover"], bd=0,
                                highlightthickness=0, font=FONTS["small"],
                                width=9)
            profile_menu["menu"].config(bg=COLORS["card"], fg=COLORS["text"],
                                         activebackground=COLORS["accent"])
            profile_menu.pack(side=tk.LEFT, padx=4)
            apply_btn = tk.Label(row, text="USE", font=FONTS["tag"],
                                 bg=COLORS["card"], fg=COLORS["text"],
                                 padx=6, cursor="hand2")
            apply_btn.pack(side=tk.LEFT)
            apply_btn.bind(
                "<Button-1>",
                lambda e, pv=profile_var, av=args_var: av.set(
                    profiles.get(pv.get(), profiles["custom"]).get("args", "{rom}")
                ),
            )
            btn = tk.Label(row, text="📂", font=FONTS["body"],
                            bg=COLORS["bg"], cursor="hand2")
            btn.pack(side=tk.LEFT)
            btn.bind("<Button-1>", lambda e, v=path_var: self._browse_file(v))

        # Tab 2: ROM Directories
        dirs_frame = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(dirs_frame, text="ROM DIRS")

        tk.Label(dirs_frame, text="ROM search directories:",
                  font=FONTS["body"], bg=COLORS["bg"],
                  fg=COLORS["subtext"], padx=12, pady=8).pack(anchor="w")

        dirs_listbox = tk.Listbox(dirs_frame, bg=COLORS["card"],
                                   fg=COLORS["text"], font=FONTS["small"],
                                   selectbackground=COLORS["accent"],
                                   relief=tk.FLAT, bd=0, height=10)
        dirs_listbox.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        for d in self.config_data["rom_dirs"]:
            dirs_listbox.insert(tk.END, d)

        btn_row = tk.Frame(dirs_frame, bg=COLORS["bg"])
        btn_row.pack(fill=tk.X, padx=12, pady=4)

        def add_dir():
            d = filedialog.askdirectory(parent=win)
            if d:
                dirs_listbox.insert(tk.END, d)

        def remove_dir():
            sel = dirs_listbox.curselection()
            if sel:
                dirs_listbox.delete(sel[0])

        self._btn(btn_row, "+ ADD", add_dir, accent=True).pack(side=tk.LEFT, padx=4)
        self._btn(btn_row, "- REMOVE", remove_dir).pack(side=tk.LEFT, padx=4)

        # Tab 3: Systems
        sys_tab = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(sys_tab, text="SYSTEMS")

        tk.Label(sys_tab,
                  text="Systems are auto-detected by file extension.\nAdd custom systems by editing the config file directly.",
                  font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["subtext"],
                  padx=12, pady=8, justify=tk.LEFT).pack(anchor="w")

        for sid, sdef in self.config_data["systems"].items():
            row = tk.Frame(sys_tab, bg=COLORS["card"])
            row.pack(fill=tk.X, padx=12, pady=2)
            tk.Label(row, text=f"{sdef['icon']}  {sdef['name']}",
                      font=FONTS["body"], bg=COLORS["card"],
                      fg=COLORS["text"], padx=12, pady=6, width=28, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text="  ".join(sdef["extensions"]),
                      font=FONTS["small"], bg=COLORS["card"],
                      fg=COLORS["subtext"], padx=8).pack(side=tk.LEFT)

        tk.Label(sys_tab, text=f"Config file: {CONFIG_FILE}",
                  font=FONTS["small"], bg=COLORS["bg"],
                  fg=COLORS["subtext"], padx=12, pady=8).pack(anchor="w", side=tk.BOTTOM)

        # Save button
        def save_settings():
            # ROM dirs
            self.config_data["rom_dirs"] = list(dirs_listbox.get(0, tk.END))
            # RetroArch
            self.config_data["use_retroarch"] = use_ra_var.get()
            self.config_data["retroarch_path"] = ra_path_var.get()
            # Emulators
            for sid, (pv, av, profv) in emu_vars.items():
                self.config_data["emulators"][sid] = {
                    "path": pv.get(),
                    "args": av.get(),
                    "profile": profv.get(),
                }
            save_config(self.config_data)
            self.status_var.set("Settings saved.")
            win.destroy()

        tk.Frame(win, bg=COLORS["border"], height=1).pack(fill=tk.X)
        save_row = tk.Frame(win, bg=COLORS["bg"])
        save_row.pack(fill=tk.X, padx=16, pady=10)
        self._btn(save_row, "✓ SAVE SETTINGS", save_settings, accent=True).pack(side=tk.RIGHT)
        self._btn(save_row, "✕ CANCEL", win.destroy).pack(side=tk.RIGHT, padx=8)

    def _path_row(self, parent, label, var, file=False):
        row = tk.Frame(parent, bg=COLORS["bg"])
        row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(row, text=label, font=FONTS["small"],
                  bg=COLORS["bg"], fg=COLORS["subtext"], width=20, anchor="w").pack(side=tk.LEFT)
        tk.Entry(row, textvariable=var, font=FONTS["small"],
                  bg=COLORS["card"], fg=COLORS["text"],
                  insertbackground=COLORS["text"], relief=tk.FLAT, width=36).pack(side=tk.LEFT, padx=4)
        browse = tk.Label(row, text="📂", font=FONTS["body"],
                           bg=COLORS["bg"], cursor="hand2")
        browse.pack(side=tk.LEFT)
        if file:
            browse.bind("<Button-1>", lambda e: self._browse_file(var))
        else:
            browse.bind("<Button-1>", lambda e: self._browse_dir(var))

    def _browse_file(self, var):
        f = filedialog.askopenfilename(parent=self)
        if f:
            var.set(f)

    def _browse_dir(self, var):
        d = filedialog.askdirectory(parent=self)
        if d:
            var.set(d)

    # ── Canvas helpers ─────────────────────────────────────────────────────────

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--audit-test-roms":
        manifest = load_test_rom_manifest()
        results = audit_test_roms(load_config(), manifest)
        for result in results:
            print(f"{result['system']}: {result['status']} - {result['message']}")
        sys.exit(0 if all(r["status"] == "ok" for r in results) else 1)
    app = RetroVault()
    app.mainloop()
