"""Download libretro cores from the libretro buildbot into RetroVault's cores directory.

The buildbot only serves rolling nightly cores, so there is no version to pin.
Each core is instead checked against the CRC-32 the buildbot publishes in its
``.index-extended`` listing (the same check RetroArch's own Core Downloader
makes), and its binary header must match the platform before it is installed.
"""

from __future__ import annotations

import os
import struct
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..core.paths import CORES_DIR
from .installer import ChecksumError, InstallError

BUILDBOT_URL = "https://buildbot.libretro.com/nightly"
CoreProgressCallback = Callable[[str, int, int | None], None]


@dataclass(frozen=True)
class CorePlatform:
    path: str
    suffix: str
    elf_machine: int | None = None  # e_machine a Linux core must declare


CORE_PLATFORMS = {
    "linux-aarch64": CorePlatform("linux/aarch64", ".so", elf_machine=183),
    "linux-x86_64": CorePlatform("linux/x86_64", ".so", elf_machine=62),
    "windows-x86_64": CorePlatform("windows/x86_64", ".dll"),
}


@dataclass(frozen=True)
class IndexEntry:
    date: str
    crc: int


def core_platform(platform_key: str) -> CorePlatform:
    platform = CORE_PLATFORMS.get(platform_key)
    if platform is None:
        raise InstallError(f"libretro cores are not available for {platform_key}")
    return platform


def core_filename(name: str, platform_key: str) -> str:
    return f"{name}{core_platform(platform_key).suffix}"


def index_url(platform_key: str) -> str:
    return f"{BUILDBOT_URL}/{core_platform(platform_key).path}/latest/.index-extended"


def core_url(name: str, platform_key: str) -> str:
    return f"{BUILDBOT_URL}/{core_platform(platform_key).path}/latest/{core_filename(name, platform_key)}.zip"


def parse_index(text: str) -> dict[str, IndexEntry]:
    """Map each ``<core>.zip`` filename to its build date and CRC-32."""
    entries = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        date, crc, filename = parts
        try:
            entries[filename] = IndexEntry(date, int(crc, 16))
        except ValueError:
            continue
    return entries


def fetch_index(platform_key: str, opener: Callable[..., object] = urllib.request.urlopen) -> dict[str, IndexEntry]:
    url = index_url(platform_key)
    try:
        with opener(url, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
    except OSError as error:
        raise InstallError(f"Could not reach the libretro core index: {error}") from error
    entries = parse_index(text)
    if not entries:
        raise InstallError(f"The libretro core index at {url} was empty or unreadable")
    return entries


def install_cores(
    names: Iterable[str],
    platform_key: str,
    cores_dir: Path = CORES_DIR,
    opener: Callable[..., object] = urllib.request.urlopen,
    progress: CoreProgressCallback | None = None,
) -> dict[str, Path]:
    """Download each named core that is missing or out of date; return name -> path.

    A core already on disk with the index's CRC is kept without downloading.
    Raises :class:`InstallError` (or :class:`ChecksumError`) on the first core
    that can't be fetched or verified; cores installed before it stay in place.
    """
    platform = core_platform(platform_key)
    wanted = list(dict.fromkeys(name for name in names if name))
    if not wanted:
        return {}
    index = fetch_index(platform_key, opener)
    cores_dir.mkdir(parents=True, exist_ok=True)
    installed = {}
    for name in wanted:
        _validate_core_name(name)
        filename = core_filename(name, platform_key)
        entry = index.get(f"{filename}.zip")
        if entry is None:
            raise InstallError(f"libretro has no {name} core for {platform_key}")
        destination = cores_dir / filename
        if destination.is_file() and _file_crc(destination) == entry.crc:
            if progress:
                progress(name, 1, 1)
            installed[name] = destination
            continue
        _download_core(name, core_url(name, platform_key), filename, entry, platform, destination, opener, progress)
        installed[name] = destination
    return installed


def _download_core(
    name: str,
    url: str,
    filename: str,
    entry: IndexEntry,
    platform: CorePlatform,
    destination: Path,
    opener: Callable[..., object],
    progress: CoreProgressCallback | None,
) -> None:
    archive = destination.with_name(f"{filename}.zip.part")
    partial = destination.with_name(f"{filename}.part")
    try:
        _fetch(name, url, archive, opener, progress)
        with zipfile.ZipFile(archive) as package:
            try:
                member = package.getinfo(filename)
            except KeyError as error:
                raise InstallError(f"{filename}.zip does not contain {filename}") from error
            if member.CRC != entry.crc:
                raise ChecksumError(
                    f"CRC-32 mismatch for {filename}: libretro lists {entry.crc:08x}, archive has {member.CRC:08x}"
                )
            with package.open(member) as source, partial.open("wb") as output:
                while chunk := source.read(1024 * 1024):  # ZipExtFile re-checks the CRC as it reads
                    output.write(chunk)
        _check_binary(partial, filename, platform)
        os.replace(partial, destination)
    except zipfile.BadZipFile as error:
        raise ChecksumError(f"Downloaded {filename}.zip is corrupt: {error}") from error
    finally:
        archive.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)


def _fetch(
    name: str,
    url: str,
    target: Path,
    opener: Callable[..., object],
    progress: CoreProgressCallback | None,
) -> None:
    done = 0
    try:
        with opener(url, timeout=30) as response, target.open("wb") as output:
            total = _content_length(response)
            if progress:
                progress(name, 0, total)
            while chunk := response.read(1024 * 128):
                output.write(chunk)
                done += len(chunk)
                if progress:
                    progress(name, done, total)
    except OSError as error:
        raise InstallError(f"Could not download the {name} core: {error}") from error


def _check_binary(path: Path, filename: str, platform: CorePlatform) -> None:
    with path.open("rb") as binary:
        header = binary.read(20)
    if platform.suffix == ".dll":
        if not header.startswith(b"MZ"):
            raise InstallError(f"{filename} is not a Windows DLL")
        return
    if len(header) < 20 or not header.startswith(b"\x7fELF"):
        raise InstallError(f"{filename} is not a Linux shared library")
    (machine,) = struct.unpack_from("<H", header, 18)
    if platform.elf_machine is not None and machine != platform.elf_machine:
        raise InstallError(f"{filename} was built for a different CPU (ELF machine {machine})")


def _validate_core_name(name: str) -> None:
    if Path(name).name != name or name in {".", ".."} or not name.endswith("_libretro"):
        raise InstallError(f"Invalid libretro core name: {name!r}")


def _file_crc(path: Path) -> int:
    crc = 0
    with path.open("rb") as binary:
        for chunk in iter(lambda: binary.read(1024 * 1024), b""):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def _content_length(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    value = headers.get("Content-Length") if headers is not None else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
