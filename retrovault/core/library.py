"""ROM library scanning and persistence."""

import json
import os
import re
from pathlib import Path

from .paths import COLLECTIONS_FILE, LIBRARY_FILE

# Fields that ``scan_roms`` derives from disk and fully owns. Everything else on
# a library entry (favorite, play_seconds, play_count, last_played, media,
# metadata, ra_*, ...) is enrichment added elsewhere and must survive a rescan.
SCAN_FIELDS = ("name", "path", "system", "ext", "size")

# A ``.bin``/``.img`` file at least this large, with no associated ``.cue``, is
# treated as a PlayStation disc image rather than a Sega Genesis cartridge.
# Genesis carts top out around 4-8 MB; PSX data tracks run tens to hundreds of
# MB, so the gap is wide and this threshold is not sensitive to its exact value.
_DISC_SIZE_THRESHOLD = 24 * 1024 * 1024

# ``FILE "<name>" <TYPE>`` lines in a .cue sheet name the disc's data tracks.
_CUE_FILE_RE = re.compile(r'FILE\s+"([^"]+)"', re.IGNORECASE)


def _path_key(path):
    """Canonical comparison key for a filesystem path (case-insensitive OS-safe)."""
    return os.path.normcase(os.path.abspath(str(path)))


def parse_cue_tracks(cue_path):
    """Return the data-file names a ``.cue`` sheet references.

    Parses ``FILE "<name>" <type>`` lines, returning each name exactly as written
    in the sheet (resolved against the cue's directory by the caller). Tolerant of
    an unreadable/binary file, odd whitespace, and missing referenced files — it
    never raises, returning ``[]`` on any read error.
    """
    names = []
    try:
        with open(cue_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                match = _CUE_FILE_RE.search(line)
                if match:
                    names.append(match.group(1))
    except OSError:
        pass
    return names


def _classify_system(size, candidates):
    """Pick the system id for a file whose extension has several candidates.

    ``candidates`` preserves system-definition order. The only real ambiguity
    today is ``.bin`` (claimed by both ``psx`` and ``genesis``): a large image is
    a PSX disc track, a small one a Genesis cart. Cue-referenced ``.bin`` files
    are excluded before this is reached, so only *standalone* ``.bin`` files land
    here. Unambiguous extensions (one candidate) skip the heuristic entirely.
    """
    if len(candidates) == 1:
        return candidates[0]
    if "psx" in candidates and "genesis" in candidates:
        return "psx" if (size or 0) >= _DISC_SIZE_THRESHOLD else "genesis"
    # Any other overlap: keep the first-defined system (previous behaviour).
    return candidates[0]


def _fingerprint(entry):
    """A cheap move-resilient identity for an entry: ``(ext, size)``.

    Used as a secondary match when a file's path changes between scans (moved or
    renamed) so its enrichment isn't lost. ``None`` when size is unknown, since a
    fingerprint without a size is too weak to match on.
    """
    size = entry.get("size")
    if size is None:
        return None
    return (entry.get("ext"), size)


def merge_scan(old_library, new_library):
    """Carry enriched per-game fields from a previous library onto a fresh scan.

    ``scan_roms`` rebuilds entries from disk containing only :data:`SCAN_FIELDS`.
    Any extra fields added later — favorites, play time, cached artwork paths,
    scraped metadata — would be lost every rescan. This copies those extra
    fields from ``old_library`` onto matching ``new_library`` entries.

    Matching is primarily by absolute path. For an old entry whose path is gone
    from the new scan (the file was moved or renamed), a secondary match by
    ``(ext, size)`` fingerprint carries its enrichment to the single new entry
    with the same fingerprint — but only when that match is *unambiguous* (exactly
    one unclaimed old and one unclaimed new entry share it), never a guess. Fresh
    scan fields always win, so scan-owned values on the moved file stay correct;
    enrichment for paths that truly disappeared is dropped.

    Keying enrichment on the non-scan fields generically (rather than an explicit
    list) means future enrichment fields are preserved automatically.
    """
    old_entries = list(old_library or [])
    new_entries = list(new_library or [])

    # Enrichment (everything outside SCAN_FIELDS) keyed by path.
    preserved_by_path = {}
    for entry in old_entries:
        path = entry.get("path")
        if not path:
            continue
        extra = {k: v for k, v in entry.items() if k not in SCAN_FIELDS}
        if extra:
            preserved_by_path[path] = extra

    new_paths = {e.get("path") for e in new_entries}

    # Secondary index: old entries whose path vanished, grouped by fingerprint.
    # Only fingerprints shared by exactly one such old entry are eligible, so an
    # ambiguous fingerprint never mis-assigns enrichment.
    orphan_by_fp = {}
    for entry in old_entries:
        if entry.get("path") in new_paths:
            continue  # still present by path; handled above
        extra = {k: v for k, v in entry.items() if k not in SCAN_FIELDS}
        if not extra:
            continue
        fp = _fingerprint(entry)
        if fp is None:
            continue
        orphan_by_fp.setdefault(fp, []).append(extra)

    # Count new entries per fingerprint so we only claim a unique target.
    new_fp_counts = {}
    for entry in new_entries:
        if entry.get("path") in preserved_by_path:
            continue  # matched by path; not a move target
        fp = _fingerprint(entry)
        if fp is not None:
            new_fp_counts[fp] = new_fp_counts.get(fp, 0) + 1

    merged = []
    for entry in new_entries:
        path = entry.get("path")
        extra = preserved_by_path.get(path)
        if extra is None:
            # Try a unique fingerprint match for a moved/renamed file.
            fp = _fingerprint(entry)
            candidates = orphan_by_fp.get(fp) if fp is not None else None
            if candidates and len(candidates) == 1 and new_fp_counts.get(fp) == 1:
                extra = candidates.pop()
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


def load_collections():
    """Load user collections (a list of ``{"name": str, "paths": [str, ...]}``).

    Collections are library data, not settings, so they live in their own
    ``collections.json`` (see the pinned decision in the implementation plan).
    Returns an empty list when the file is missing or unreadable.
    """
    if COLLECTIONS_FILE.exists():
        try:
            with open(COLLECTIONS_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_collections(collections):
    with open(COLLECTIONS_FILE, "w") as f:
        json.dump(collections, f, indent=2)


def scan_roms(config):
    library = []
    # Each extension maps to the list of systems that claim it, in definition
    # order, so genuinely ambiguous extensions (``.bin``) can be disambiguated
    # per file rather than silently going to whichever system was defined last.
    ext_to_systems = {}
    for sid, sdef in config["systems"].items():
        for ext in sdef["extensions"]:
            ext_to_systems.setdefault(ext.lower(), []).append(sid)

    for rom_dir in config["rom_dirs"]:
        p = Path(rom_dir)
        if not p.is_dir():
            continue

        files = [f for f in p.rglob("*") if f.is_file()]

        # First pass: a .cue sheet owns its disc. Collect every data track it
        # references so those .bin/.img/.iso files don't also become their own
        # (junk) library entries — a multi-track PSX dump is one game, not N+1.
        consumed = set()
        for f in files:
            if f.suffix.lower() == ".cue":
                for name in parse_cue_tracks(f):
                    consumed.add(_path_key(f.parent / name))

        for f in files:
            ext = f.suffix.lower()
            candidates = ext_to_systems.get(ext)
            if not candidates:
                continue  # unknown extension
            if ext != ".cue" and _path_key(f) in consumed:
                continue  # a data track already represented by its .cue
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            library.append({
                "name": f.stem,
                "path": str(f),
                "system": _classify_system(size, candidates),
                "ext": ext,
                "size": size,
            })
    library.sort(key=lambda x: (x["system"], x["name"].lower()))
    return library
