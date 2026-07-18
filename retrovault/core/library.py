"""ROM library scanning and persistence."""

import json
from pathlib import Path

from .paths import LIBRARY_FILE

# Fields that ``scan_roms`` derives from disk and fully owns. Everything else on
# a library entry (favorite, play_seconds, play_count, last_played, media,
# metadata, ra_*, ...) is enrichment added elsewhere and must survive a rescan.
SCAN_FIELDS = ("name", "path", "system", "ext")


def merge_scan(old_library, new_library):
    """Carry enriched per-game fields from a previous library onto a fresh scan.

    ``scan_roms`` rebuilds entries from disk containing only :data:`SCAN_FIELDS`.
    Any extra fields added later — favorites, play time, cached artwork paths,
    scraped metadata — would be lost every rescan. This copies those extra
    fields from ``old_library`` onto matching ``new_library`` entries, keyed by
    absolute path. Fresh scan fields always win, so a moved/renamed file is
    reflected correctly; enrichment for paths no longer present is dropped.

    Keying on the non-scan fields generically (rather than an explicit list)
    means future enrichment fields are preserved automatically.
    """
    preserved = {}
    for entry in old_library or []:
        path = entry.get("path")
        if not path:
            continue
        extra = {k: v for k, v in entry.items() if k not in SCAN_FIELDS}
        if extra:
            preserved[path] = extra

    merged = []
    for entry in new_library or []:
        extra = preserved.get(entry.get("path"))
        # Scan-owned fields take precedence over any stale copy in ``extra``.
        merged.append({**extra, **entry} if extra else entry)
    return merged


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
