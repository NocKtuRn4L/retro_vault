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
import html
import http.client
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Mapping, Optional, Protocol, runtime_checkable

from ..core.media import media_paths_for

log = logging.getLogger(__name__)

# ── ROM hashing ───────────────────────────────────────────────────────────────
_HASH_CHUNK = 1024 * 1024
# ScreenScraper images (esp. PSX discs) can be hundreds of MB; skip hashing
# oversized files and let the name-based lookup handle them instead.
_MAX_HASH_BYTES = 512 * 1024 * 1024


# Some dumps carry a header in front of the game data, and the same game hashes
# differently with and without it. Which variant ScreenScraper has on record
# varies, so a hash miss is retried on the data alone (see scrape_rom).
_INES_MAGIC = b"NES\x1a"
_INES_HEADER_BYTES = 16
_INES_TRAINER_BYTES = 512
_SNES_COPIER_HEADER_BYTES = 512


def rom_header_size(path: str | Path, system: str) -> int:
    """Return the size of a strippable header in front of the ROM data, or 0.

    NES: an iNES / NES 2.0 header (16 bytes, plus a 512-byte trainer when bit 2
    of flags 6 is set). SNES: a 512-byte copier header, which leaves the file
    size 512 bytes past a 1 KiB boundary. Other systems never report a header.
    """
    p = Path(path)
    try:
        size = p.stat().st_size
        if system == "nes":
            with p.open("rb") as handle:
                header = handle.read(_INES_HEADER_BYTES)
            if len(header) < _INES_HEADER_BYTES or not header.startswith(_INES_MAGIC):
                return 0
            skip = _INES_HEADER_BYTES + (_INES_TRAINER_BYTES if header[6] & 0x04 else 0)
        elif system == "snes" and size % 1024 == _SNES_COPIER_HEADER_BYTES:
            skip = _SNES_COPIER_HEADER_BYTES
        else:
            return 0
    except OSError:
        return 0
    # A "header" that is the whole file leaves nothing meaningful to hash.
    return skip if size > skip else 0


def rom_hashes(
    path: str | Path, *, max_bytes: int = _MAX_HASH_BYTES, skip: int = 0
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(crc32, md5)`` hex digests for a ROM, streamed off disk.

    ``skip`` leaves out that many leading bytes, e.g. a header found by
    :func:`rom_header_size`. Returns ``(None, None)`` when the file is missing,
    unreadable, or larger than ``max_bytes`` (in which case the caller should
    fall back to a name lookup).
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
            handle.seek(skip)
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


def wanted_media(config: Mapping) -> tuple[str, ...]:
    """Media kinds to download, from ``config["scraper"]["media"]``.

    Defaults to box art alone, the only kind the UI shows; logos and
    screenshots each cost a download per game.
    """
    kinds = (config.get("scraper") or {}).get("media")
    return tuple(kinds) if kinds else ("boxart",)


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

    uses_hashes = True
    # ScreenScraper limits concurrent requests per account (one thread for
    # free accounts), so lookups stay sequential.
    max_workers = 1

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

    Performs a hash-based lookup (CRC/MD5) first. On a miss, NES/SNES files that
    carry a header are retried with the header excluded from the hash, before
    falling back to a name lookup. Then downloads any found media into the
    local cache. Returns
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

    # Name-matched providers ignore hashes; don't read every ROM to make them.
    hashed = bool(path) and getattr(client, "uses_hashes", True)
    crc = md5 = None
    if hashed:
        crc, md5 = rom_hashes(path)

    info: Optional[GameInfo] = None
    if crc or md5:
        info = client.find_game(system, crc=crc, md5=md5)
    if info is None and hashed and (header := rom_header_size(path, system)):
        bare_crc, bare_md5 = rom_hashes(path, skip=header)
        if bare_crc or bare_md5:
            info = client.find_game(system, crc=bare_crc, md5=bare_md5)
    if info is None and name:
        info = client.find_game(system, name=name)
    if info is None:
        return result

    result["metadata"] = dict(info.metadata)
    paths = media_paths_for(rom, media_base)
    wanted = wanted_media(config)
    for kind, url in info.media_urls.items():
        dest = paths.get(kind)
        if dest is None or kind not in wanted:
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
    only, no text metadata. Only the kinds in :func:`wanted_media` are looked up.

    Each ``<Named_*>`` folder's directory listing names every image it holds, so
    it is read once per system and kind, and URLs are returned only for images
    that exist: a game without art costs no request, and a name that differs
    only in letter case still matches. If a listing can't be read, URLs are
    returned optimistically; a missing image then 404s and is skipped by
    :func:`scrape_rom`'s fail-soft download, so no empty files are cached.
    """

    # Characters libretro-thumbnails replaces with "_" in its file names.
    _UNSAFE = set('&*/:`<>?\\|"')
    # Image links in the server's (Apache) directory listings.
    _INDEX_LINK = re.compile(r'<a href="([^"?/][^"]*)\.png"')

    uses_hashes = False
    # Static files behind a CDN: a few downloads at once hide the server's
    # ~0.3 s round trip without hammering it.
    max_workers = 6

    def __init__(self, transport: HttpTransport, config: Optional[Mapping] = None, data: Mapping = SCRAPER_DATA) -> None:
        self.transport = transport
        self.config = config or {}
        self.data = data
        self._indexes: dict = {}
        self._index_lock = threading.Lock()

    def _libretro(self) -> Mapping:
        return self.data.get("libretro", {})

    @classmethod
    def normalize_name(cls, name: str) -> str:
        """Apply libretro-thumbnails' filename character substitutions."""
        return "".join("_" if ch in cls._UNSAFE else ch for ch in name).strip()

    def _index(self, folder_url: str):
        """``(names, {casefolded name: name})`` for the images in ``folder_url``.

        ``None`` when the listing can't be read. Fetched once per folder and
        shared by the scrape's worker threads.
        """
        with self._index_lock:
            if folder_url not in self._indexes:
                self._indexes[folder_url] = self._read_index(folder_url)
            return self._indexes[folder_url]

    def _read_index(self, folder_url: str):
        try:
            body = self.transport.get_bytes(folder_url + "/").decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - fall back to optimistic URLs
            log.info("thumbnail listing not available: %s (%s)", folder_url, e)
            return None
        names = {html.unescape(urllib.parse.unquote(href)) for href in self._INDEX_LINK.findall(body)}
        if not names:
            return None
        return names, {name.casefold(): name for name in names}

    def find_game(
        self,
        system: str,
        *,
        crc: Optional[str] = None,
        md5: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[GameInfo]:
        quote = urllib.parse.quote
        libretro = self._libretro()
        folder = libretro.get("systems", {}).get(system)
        if not folder or not name:
            return None
        base = str(libretro.get("base_url", "")).rstrip("/")
        safe = self.normalize_name(name)
        wanted = wanted_media(self.config)
        media_urls = {}
        for kind, sub in libretro.get("media_paths", {}).items():
            if kind not in wanted:
                continue
            folder_url = f"{base}/{quote(folder)}/{sub}"
            image = safe
            index = self._index(folder_url)
            if index is not None:
                names, folded = index
                image = safe if safe in names else folded.get(safe.casefold())
                if image is None:
                    continue  # the server has no such image
            media_urls[kind] = f"{folder_url}/{quote(image)}.png"
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
    """A :class:`HttpTransport` over the standard library. Never used in tests.

    Each thread keeps one connection per host open between requests. A fresh
    HTTPS connection per request (``urlopen``) roughly doubled the time of
    every thumbnail download. Proxies and redirects go through ``urlopen``.
    Non-200 responses raise ``urllib.error.HTTPError``, as ``urlopen`` does.
    """

    _REDIRECTS = (301, 302, 303, 307, 308)

    def __init__(self, *, timeout: float = 15.0, user_agent: str = "retrovault") -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self._local = threading.local()

    def _urlopen(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def _get(self, url: str) -> bytes:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or urllib.request.getproxies().get(parts.scheme):
            return self._urlopen(url)
        connections = self._local.__dict__.setdefault("connections", {})
        key = (parts.scheme, parts.netloc)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        for attempt in range(2):
            connection = connections.get(key)
            if connection is None:
                factory = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
                connection = connections[key] = factory(parts.netloc, timeout=self.timeout)
            try:
                connection.request("GET", target, headers={"User-Agent": self.user_agent})
                response = connection.getresponse()
                body = response.read()
            except (http.client.HTTPException, OSError):
                connection.close()
                del connections[key]
                if attempt:
                    raise
                continue  # the server may have dropped the idle connection; reconnect once
            if response.status == 200:
                return body
            if response.status in self._REDIRECTS:
                return self._urlopen(url)
            raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
        raise AssertionError("unreachable")

    def get_bytes(self, url: str) -> bytes:
        return self._get(url)

    def get_json(self, url: str, params: Mapping[str, str]) -> dict:
        full = url + ("?" + urllib.parse.urlencode(dict(params)) if params else "")
        return json.loads(self._get(full).decode("utf-8"))


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

    Entries whose wanted media (see :func:`wanted_media`) is already in the
    cache are pointed at those files without a lookup, unless ``force``. That
    also recovers covers downloaded by a run that was interrupted before the
    library was saved. Merges any found ``media``/``metadata`` onto a copy of
    each entry (so ``core.library.merge_scan`` preserves it across rescans).

    Lookups run on up to ``client.max_workers`` threads (default 1) and results
    keep the library's order. Calls ``on_progress(done, total)`` from the
    calling thread after each entry, and stops starting lookups — leaving the
    remaining entries untouched — when ``should_cancel()`` returns True;
    lookups already running finish. A single entry's failure never aborts the
    run.
    """
    items = list(library or [])
    total = len(items)
    updated = list(items)
    wanted = wanted_media(config)
    workers = max(1, int(getattr(client, "max_workers", 1)))
    done = 0

    def scrape(index):
        rom = items[index]
        try:
            result = scrape_rom(rom, config, client, media_base=media_base)
        except Exception:  # noqa: BLE001 - one bad entry must not abort the batch
            log.warning("scrape failed for %s", rom.get("name"), exc_info=True)
            result = {"media": {}, "metadata": {}}
        entry = dict(rom)
        if result.get("media"):
            entry["media"] = {**entry.get("media", {}), **result["media"]}
        if result.get("metadata"):
            entry["metadata"] = {**entry.get("metadata", {}), **result["metadata"]}
        return index, entry

    def finish(futures):
        nonlocal done
        for future in futures:
            index, entry = future.result()
            updated[index] = entry
            done += 1
            if on_progress:
                on_progress(done, total)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scrape") as pool:
        running = set()
        for index, rom in enumerate(items):
            if should_cancel and should_cancel():
                break
            cached = {} if force else {
                kind: str(path)
                for kind, path in media_paths_for(rom, media_base).items()
                if kind in wanted and path.exists()
            }
            if cached:
                updated[index] = {**rom, "media": {**(rom.get("media") or {}), **cached}}
                done += 1
                if on_progress:
                    on_progress(done, total)
                continue
            running.add(pool.submit(scrape, index))
            if len(running) >= 2 * workers:  # bounded queue: cancel stays prompt
                finished, running = wait(running, return_when=FIRST_COMPLETED)
                finish(finished)
        finish(running)
    return updated
