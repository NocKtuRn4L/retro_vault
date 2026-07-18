"""Local media (artwork) cache path helpers.

Scraped artwork is cached on disk under :data:`MEDIA_DIR` as
``<system>/<rom-stem>.<kind>.png``. These helpers build those paths so the
scraper (which writes them) and the UI (which reads them) agree on a single
layout. Nothing here touches the network.
"""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath
from typing import Mapping

from .paths import MEDIA_DIR

# Media kinds cached per game. Kept in sync with the ``media`` entry field in
# the library schema (see docs/implementation-plans.md).
MEDIA_KINDS = ("boxart", "logo", "screenshot")

# Characters that are unsafe in a filename on Windows (and awkward elsewhere).
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _rom_stem(rom: Mapping) -> str:
    """Filesystem-safe stem for a library entry, derived from its ROM path."""
    path = str(rom.get("path", "") or "")
    # PureWindowsPath treats both "/" and "\\" as separators on every platform,
    # so the cache stem is derived deterministically from a ROM path regardless
    # of whether the library was scanned on Windows or Linux (and regardless of
    # which OS the CI runner uses).
    stem = PureWindowsPath(path).stem if path else ""
    if not stem:
        stem = str(rom.get("name", "") or "")
    stem = _UNSAFE.sub("_", stem).strip().rstrip(".")
    return stem or "unknown"


def _system(rom: Mapping) -> str:
    system = str(rom.get("system", "") or "").strip()
    return _UNSAFE.sub("_", system) or "unknown"


def media_dir_for(rom: Mapping, base: Path | str | None = None) -> Path:
    """Directory holding a game's cached media (``<base>/<system>``)."""
    root = Path(base) if base is not None else MEDIA_DIR
    return root / _system(rom)


def media_paths_for(rom: Mapping, base: Path | str | None = None) -> dict[str, Path]:
    """Map each media kind to its cache path for ``rom``.

    Returns ``{"boxart": Path, "logo": Path, "screenshot": Path}`` under
    ``<base>/<system>/<rom-stem>.<kind>.png``. ``base`` defaults to
    :data:`MEDIA_DIR`; tests pass a temp directory. No files are created.
    """
    directory = media_dir_for(rom, base)
    stem = _rom_stem(rom)
    return {kind: directory / f"{stem}.{kind}.png" for kind in MEDIA_KINDS}


def has_media(rom: Mapping, base: Path | str | None = None) -> bool:
    """True if any cached media file for ``rom`` already exists on disk."""
    return any(path.exists() for path in media_paths_for(rom, base).values())
