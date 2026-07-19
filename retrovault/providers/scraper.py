"""Metadata + artwork scraping behind a provider-agnostic interface.

The concrete provider here is ScreenScraper (screenscraper.fr), but the network
layer sits behind two small interfaces so that:

* other providers (IGDB, TheGamesDB) can be added by implementing :class:`Scraper`;
* tests inject a fake :class:`HttpTransport` and run entirely against recorded
  fixture JSON — **no live network is performed at import or in tests**.

The public entry point is :func:`scrape_rom`, which a future UI PR calls and
whose ``{"media": ..., "metadata": ...}`` result is written onto the library
entry dict (and preserved across rescans by ``core.library.merge_scan``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import zlib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Mapping, Optional, Protocol, runtime_checkable

from ..core.media import has_media, media_paths_for

log = logging.getLogger(__name__)

# ── ROM hashing ───────────────────────────────────────────────────────────────
_HASH_CHUNK = 1024 * 1024
# ScreenScraper images (esp. PSX discs) can be hundreds of MB; skip hashing
# oversized files and let the name-based lookup handle them instead.
_MAX_HASH_BYTES = 512 * 1024 * 1024


def rom_hashes(path: str | Path, *, max_bytes: int = _MAX_HASH_BYTES) -> tuple[Optional[str], Optional[str]]:
    """Return ``(crc32, md5)`` hex digests for a ROM, streamed off disk.

    Returns ``(None, None)`` when the file is missing, unreadable, or larger than
    ``max_bytes`` (in which case the caller should fall back to a name lookup).
    """
    p = Path(path)
    try:
        if p.stat().st_size > max_bytes:
            return None, None
    except OSError:
        return None, None

    crc = 0
    md5 = hashlib.md5()
    try:
        with p.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK):
                crc = zlib.crc32(chunk, crc)
                md5.update(chunk)
    except OSError:
        return None, None
    return f"{crc & 0xFFFFFFFF:08x}", md5.hexdigest()


# ── Scraper config (data/scraper.json) ────────────────────────────────────────
def _load_scraper_data() -> dict:
    with resources.files("retrovault.data").joinpath("scraper.json").open("r", encoding="utf-8") as f:
        return json.load(f)


SCRAPER_DATA = _load_scraper_data()


def platform_id_for(system: str, data: Mapping = SCRAPER_DATA) -> Optional[int]:
    """Map a RetroVault system id (e.g. ``"snes"``) to a ScreenScraper systemeid."""
    return data.get("platforms", {}).get(system)


# ── Interfaces ────────────────────────────────────────────────────────────────
@runtime_checkable
class HttpTransport(Protocol):
    """Minimal HTTP surface a scraper needs. Tests supply a fake."""

    def get_json(self, url: str, params: Mapping[str, str]) -> dict:
        ...

    def get_bytes(self, url: str) -> bytes:
        ...


@dataclass
class GameInfo:
    """Parsed, provider-neutral result of a lookup."""

    metadata: dict = field(default_factory=dict)
    # media kind ("boxart"/"logo"/"screenshot") -> remote URL
    media_urls: dict = field(default_factory=dict)


@runtime_checkable
class Scraper(Protocol):
    """A metadata/artwork provider. Implementations wrap one remote API."""

    def find_game(
        self,
        system: str,
        *,
        crc: Optional[str] = None,
        md5: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[GameInfo]:
        ...

    def fetch_media(self, url: str) -> Optional[bytes]:
        ...


# ── ScreenScraper implementation ──────────────────────────────────────────────
class ScreenScraperClient:
    """A :class:`Scraper` backed by the ScreenScraper API v2.

    The network layer is the injected ``transport``; ``config`` supplies the
    user's credentials/region (see the ``"scraper"`` block in ``DEFAULT_CONFIG``).
    """

    def __init__(
        self,
        transport: HttpTransport,
        config: Optional[Mapping] = None,
        data: Mapping = SCRAPER_DATA,
    ) -> None:
        self.transport = transport
        self.config = config or {}
        self.data = data

    # -- request building --
    def _endpoint(self) -> str:
        api = self.data.get("api", {})
        base = str(api.get("base_url", "")).rstrip("/")
        endpoint = api.get("game_info_endpoint", "jeuInfos.php")
        return f"{base}/{endpoint}"

    def _base_params(self) -> dict:
        api = self.data.get("api", {})
        scraper_cfg = self.config.get("scraper", {}) if isinstance(self.config, Mapping) else {}
        return {
            "output": api.get("output", "json"),
            "softname": api.get("softname", "retrovault"),
            "ssid": scraper_cfg.get("username", ""),
            "sspassword": scraper_cfg.get("password", ""),
        }

    def find_game(
        self,
        system: str,
        *,
        crc: Optional[str] = None,
        md5: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[GameInfo]:
        params = self._base_params()
        platform = platform_id_for(system, self.data)
        if platform is not None:
            params["systemeid"] = str(platform)
        if crc:
            params["crc"] = crc
        if md5:
            params["md5"] = md5
        if name:
            params["romnom"] = name
        # Nothing to look up by.
        if not (crc or md5 or name):
            return None

        try:
            payload = self.transport.get_json(self._endpoint(), params)
        except Exception:  # noqa: BLE001 - fail soft on any transport/parse error
            log.warning("scraper lookup failed for system=%s name=%s", system, name, exc_info=True)
            return None
        return self._parse(payload)

    def fetch_media(self, url: str) -> Optional[bytes]:
        if not url:
            return None
        try:
            return self.transport.get_bytes(url)
        except Exception:  # noqa: BLE001 - fail soft
            log.warning("scraper media download failed: %s", url, exc_info=True)
            return None

    # -- response parsing --
    def _region_prefs(self) -> tuple[str, ...]:
        scraper_cfg = self.config.get("scraper", {}) if isinstance(self.config, Mapping) else {}
        region = str(scraper_cfg.get("region", "us") or "us").lower()
        # Region for media, language for text; keep a broad, ordered preference.
        return (region, "wor", "us", "eu", "jp", "en", "ss")

    def _parse(self, payload: Mapping) -> Optional[GameInfo]:
        if not isinstance(payload, Mapping):
            return None
        jeu = (payload.get("response") or {}).get("jeu")
        if not isinstance(jeu, Mapping) or not jeu:
            return None
        return GameInfo(
            metadata=self._parse_metadata(jeu),
            media_urls=self._parse_media(jeu),
        )

    def _parse_metadata(self, jeu: Mapping) -> dict:
        prefs = self._region_prefs()
        metadata: dict = {}

        synopsis = _localized(jeu.get("synopsis"), prefs)
        if synopsis:
            metadata["synopsis"] = synopsis

        genres = jeu.get("genres")
        genre = ""
        if isinstance(genres, list) and genres:
            genre = _localized(genres[0].get("noms") if isinstance(genres[0], Mapping) else None, prefs)
        if genre:
            metadata["genre"] = genre

        players = _text(jeu.get("joueurs"))
        if players:
            metadata["players"] = players

        rating = _text(jeu.get("note"))
        if rating:
            metadata["rating"] = rating

        year = _year(_localized(jeu.get("dates"), prefs, key="region"))
        if year:
            metadata["year"] = year

        return metadata

    def _parse_media(self, jeu: Mapping) -> dict:
        medias = jeu.get("medias")
        if not isinstance(medias, list):
            return {}
        prefs = self._region_prefs()
        type_map = self.data.get("media_types", {})
        urls: dict = {}
        for kind, wanted_types in type_map.items():
            url = _best_media(medias, wanted_types, prefs)
            if url:
                urls[kind] = url
        return urls


# ── Parsing helpers (module-level, pure) ──────────────────────────────────────
def _text(value) -> str:
    """Pull ``text`` from a ScreenScraper scalar node (a dict or a plain string)."""
    if isinstance(value, Mapping):
        return str(value.get("text", "") or "").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _localized(entries, prefs: tuple[str, ...], key: str = "langue") -> str:
    """Pick the best localized ``text`` from a list of ``{key, text}`` dicts.

    ScreenScraper tags text/date nodes with a ``langue`` (or ``region``) code.
    Prefer entries whose code is earliest in ``prefs``; fall back to the first.
    """
    if isinstance(entries, Mapping):
        entries = [entries]
    if not isinstance(entries, list) or not entries:
        return ""
    dict_entries = [e for e in entries if isinstance(e, Mapping)]
    if not dict_entries:
        return ""
    for pref in prefs:
        for entry in dict_entries:
            code = str(entry.get(key, entry.get("region", entry.get("langue", ""))) or "").lower()
            if code == pref:
                return str(entry.get("text", "") or "").strip()
    return str(dict_entries[0].get("text", "") or "").strip()


def _best_media(medias: list, wanted_types, prefs: tuple[str, ...]) -> str:
    """Choose one media URL matching ``wanted_types``, preferring region order."""
    candidates = [
        m for m in medias
        if isinstance(m, Mapping) and m.get("type") in wanted_types and m.get("url")
    ]
    if not candidates:
        return ""
    # Prefer the earliest wanted type, then the earliest preferred region.
    def sort_key(media: Mapping) -> tuple[int, int]:
        try:
            type_rank = list(wanted_types).index(media.get("type"))
        except ValueError:
            type_rank = len(wanted_types)
        region = str(media.get("region", "") or "").lower()
        region_rank = prefs.index(region) if region in prefs else len(prefs)
        return (type_rank, region_rank)

    return str(sorted(candidates, key=sort_key)[0].get("url", "") or "")


def _year(date_text: str) -> str:
    """Extract a 4-digit year from a ScreenScraper date string."""
    for token in str(date_text).replace("/", "-").split("-"):
        token = token.strip()
        if len(token) == 4 and token.isdigit():
            return token
    stripped = str(date_text).strip()
    return stripped[:4] if stripped[:4].isdigit() else ""


# ── Entry point ───────────────────────────────────────────────────────────────
def scrape_rom(
    rom: Mapping,
    config: Mapping,
    client: Scraper,
    *,
    media_base=None,
) -> dict:
    """Scrape one library entry and cache its artwork.

    Performs a hash-based lookup (CRC/MD5) first, falling back to a name lookup,
    then downloads any found media into the local cache. Returns
    ``{"media": {kind: abs_path_str, ...}, "metadata": {...}}`` for the caller to
    write onto the library entry. Always fails soft: a game with no result yields
    empty ``media``/``metadata`` and never raises.

    ``client`` is any :class:`Scraper` (in production a
    :class:`ScreenScraperClient` wrapping a real transport; in tests one wrapping
    a fake transport that serves fixture JSON). ``media_base`` overrides the media
    cache root (tests pass a temp directory).
    """
    result = {"media": {}, "metadata": {}}
    system = str(rom.get("system", "") or "")
    path = rom.get("path")
    name = str(rom.get("name", "") or "") or (Path(str(path)).stem if path else "")

    crc = md5 = None
    if path:
        crc, md5 = rom_hashes(path)

    info: Optional[GameInfo] = None
    if crc or md5:
        info = client.find_game(system, crc=crc, md5=md5)
    if info is None and name:
        info = client.find_game(system, name=name)
    if info is None:
        return result

    result["metadata"] = dict(info.metadata)
    paths = media_paths_for(rom, media_base)
    for kind, url in info.media_urls.items():
        dest = paths.get(kind)
        if dest is None:
            continue
        data = client.fetch_media(url)
        if not data:
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        except OSError:
            log.warning("failed to cache media %s for %s", kind, name, exc_info=True)
            continue
        result["media"][kind] = str(dest)
    return result


# ── libretro-thumbnails implementation ────────────────────────────────────────
class LibretroThumbnailsClient:
    """A name-matched :class:`Scraper` backed by the libretro-thumbnails image set.

    No account or API key: images are static files at
    ``<base>/<system folder>/<Named_*>/<game name>.png``. Matching is by the ROM's
    (No-Intro-style) name — hashes are ignored — and this source provides images
    only, no text metadata. URLs are returned optimistically for each media kind;
    a game that lacks a given kind 404s and is skipped by :func:`scrape_rom`'s
    fail-soft download, so no empty files are cached.
    """

    # Characters libretro-thumbnails replaces with "_" in its file names.
    _UNSAFE = set('&*/:`<>?\\|"')

    def __init__(self, transport: HttpTransport, config: Optional[Mapping] = None, data: Mapping = SCRAPER_DATA) -> None:
        self.transport = transport
        self.config = config or {}
        self.data = data

    def _libretro(self) -> Mapping:
        return self.data.get("libretro", {})

    @classmethod
    def normalize_name(cls, name: str) -> str:
        """Apply libretro-thumbnails' filename character substitutions."""
        return "".join("_" if ch in cls._UNSAFE else ch for ch in name).strip()

    def find_game(
        self,
        system: str,
        *,
        crc: Optional[str] = None,
        md5: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[GameInfo]:
        from urllib.parse import quote

        libretro = self._libretro()
        folder = libretro.get("systems", {}).get(system)
        if not folder or not name:
            return None
        base = str(libretro.get("base_url", "")).rstrip("/")
        safe = self.normalize_name(name)
        media_urls = {
            kind: f"{base}/{quote(folder)}/{sub}/{quote(safe)}.png"
            for kind, sub in libretro.get("media_paths", {}).items()
        }
        return GameInfo(metadata={}, media_urls=media_urls)

    def fetch_media(self, url: str) -> Optional[bytes]:
        if not url:
            return None
        try:
            return self.transport.get_bytes(url)
        except Exception:  # noqa: BLE001 - fail soft (404 for a missing kind is normal)
            log.info("thumbnail not available: %s", url)
            return None


# ── Concrete transport (real network; injected in production, faked in tests) ──
class UrllibTransport:
    """A :class:`HttpTransport` over ``urllib``. Never used in tests."""

    def __init__(self, *, timeout: float = 15.0, user_agent: str = "retrovault") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def _open(self, url: str):
        import urllib.request

        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        return urllib.request.urlopen(request, timeout=self.timeout)

    def get_bytes(self, url: str) -> bytes:
        with self._open(url) as response:
            return response.read()

    def get_json(self, url: str, params: Mapping[str, str]) -> dict:
        import urllib.parse

        full = url + ("?" + urllib.parse.urlencode(dict(params)) if params else "")
        with self._open(full) as response:
            return json.loads(response.read().decode("utf-8"))


def build_client(config: Mapping, transport: HttpTransport) -> Scraper:
    """Construct the configured provider client around ``transport``.

    Defaults to the account-free libretro-thumbnails source; ``screenscraper`` is
    available for richer metadata when the user supplies credentials. Unknown
    providers fall back to libretro so the app degrades gracefully.
    """
    provider = str((config.get("scraper") or {}).get("provider", "libretro"))
    if provider == "screenscraper":
        return ScreenScraperClient(transport, config)
    if provider and provider != "libretro":
        log.warning("unknown scraper provider %r; using libretro-thumbnails", provider)
    return LibretroThumbnailsClient(transport, config)


def scrape_library(
    library,
    config: Mapping,
    client: Scraper,
    *,
    media_base=None,
    on_progress=None,
    should_cancel=None,
    force: bool = False,
):
    """Scrape media/metadata for every entry, returning a NEW library list.

    Entries that already have cached media are skipped unless ``force``. Merges
    any found ``media``/``metadata`` onto a copy of each entry (so
    ``core.library.merge_scan`` preserves it across rescans). Calls
    ``on_progress(done, total)`` after each entry and stops early — leaving the
    remaining entries untouched — when ``should_cancel()`` returns True. A single
    entry's failure never aborts the run.
    """
    items = list(library or [])
    total = len(items)
    updated = []
    for index, rom in enumerate(items, start=1):
        if should_cancel and should_cancel():
            updated.extend(items[index - 1:])
            break
        entry = dict(rom)
        if force or not has_media(rom, media_base):
            try:
                result = scrape_rom(rom, config, client, media_base=media_base)
            except Exception:  # noqa: BLE001 - one bad entry must not abort the batch
                log.warning("scrape failed for %s", rom.get("name"), exc_info=True)
                result = {"media": {}, "metadata": {}}
            if result.get("media"):
                entry["media"] = {**entry.get("media", {}), **result["media"]}
            if result.get("metadata"):
                entry["metadata"] = {**entry.get("metadata", {}), **result["metadata"]}
        updated.append(entry)
        if on_progress:
            on_progress(index, total)
    return updated
