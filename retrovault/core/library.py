"""ROM library scanning and persistence."""

import json
from pathlib import Path

from .paths import LIBRARY_FILE


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
