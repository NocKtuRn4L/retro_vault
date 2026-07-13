"""Install emulator artifacts from typed provider strategies."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from ..core.paths import APP_DIR
from .manifest import InstallStrategy

DOWNLOAD_DIR = APP_DIR / "downloads"
EMULATOR_DIR = APP_DIR / "emulators"
ProgressCallback = Callable[[int, int | None], None]


class InstallError(RuntimeError):
    """Raised when an emulator strategy cannot be completed."""


class ChecksumError(InstallError):
    """Raised when a downloaded artifact fails SHA-256 verification."""


@dataclass(frozen=True)
class InstallInstruction:
    """A privileged command that must be run by the user."""

    command: str


def install(
    emulator_id: str,
    version: str,
    strategy: InstallStrategy,
    *,
    assume_yes: bool = False,
    progress: ProgressCallback | None = None,
    app_dir: Path = APP_DIR,
    opener: Callable[..., object] = urllib.request.urlopen,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path | str | InstallInstruction:
    """Run a strategy, trying its nested fallback when installation fails."""
    current: InstallStrategy | None = strategy
    errors: list[str] = []
    while current is not None:
        try:
            return _install_strategy(
                emulator_id,
                version,
                current,
                assume_yes=assume_yes,
                progress=progress,
                app_dir=app_dir,
                opener=opener,
                runner=runner,
            )
        except (InstallError, OSError, subprocess.SubprocessError) as error:
            errors.append(str(error))
            if current.fallback is None:
                raise
            current = current.fallback
    detail = "; ".join(message for message in errors if message)
    raise InstallError(detail or f"No install strategy is available for {emulator_id}")


def _install_strategy(
    emulator_id: str,
    version: str,
    strategy: InstallStrategy,
    *,
    assume_yes: bool,
    progress: ProgressCallback | None,
    app_dir: Path,
    opener: Callable[..., object],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Path | str | InstallInstruction:
    if strategy.strategy == "download":
        return _install_download(emulator_id, version, strategy, progress, app_dir, opener, runner)
    if strategy.strategy == "flatpak":
        command = ["flatpak", "install"]
        if assume_yes:
            command.append("-y")
        command.extend(["--user", "flathub", strategy.flatpak_id])
        runner(command, check=True, text=True)
        return strategy.flatpak_id
    if strategy.strategy == "apt":
        return InstallInstruction(f"sudo apt install {strategy.package}")
    if strategy.strategy == "unavailable":
        raise InstallError(strategy.reason or "Install strategy is unavailable")
    raise InstallError(f"Unsupported install strategy: {strategy.strategy}")


def _install_download(
    emulator_id: str,
    version: str,
    strategy: InstallStrategy,
    progress: ProgressCallback | None,
    app_dir: Path,
    opener: Callable[..., object],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Path:
    safe_id = _safe_component(emulator_id, "emulator id")
    safe_version = _safe_component(version, "version")
    filename = Path(urlparse(strategy.url).path).name or f"{safe_id}-{safe_version}.download"
    download_dir = app_dir / "downloads"
    artifact = download_dir / filename
    download_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    done = 0
    try:
        with opener(strategy.url, timeout=30) as response, artifact.open("wb") as output:
            total = _content_length(response)
            if progress:
                progress(0, total)
            while chunk := response.read(1024 * 128):
                output.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Exception:
        artifact.unlink(missing_ok=True)
        raise

    actual = digest.hexdigest()
    if actual.lower() != strategy.sha256.lower():
        artifact.unlink(missing_ok=True)
        raise ChecksumError(f"SHA-256 mismatch for {filename}: expected {strategy.sha256}, got {actual}")

    destination = app_dir / "emulators" / safe_id / safe_version
    temporary = destination.with_name(f"{destination.name}.tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    try:
        _extract(artifact, temporary, strategy.archive, strategy.exe, runner)
        executable = _resolve_executable(temporary, strategy.exe)
        if strategy.archive.lower() == "appimage":
            executable.chmod(executable.stat().st_mode | 0o111)
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return _resolve_executable(destination, strategy.exe).resolve()


def _content_length(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    value = headers.get("Content-Length") if headers is not None else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract(
    artifact: Path,
    destination: Path,
    archive: str,
    executable: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    archive_type = archive.lower()
    if archive_type == "zip":
        with zipfile.ZipFile(artifact) as package:
            _validate_members(destination, (item.filename for item in package.infolist()))
            package.extractall(destination)
        return
    if archive_type == "7z":
        tar = shutil.which("tar")
        if tar is None:
            raise InstallError("7z extraction requires bsdtar (tar.exe on Windows)")
        listing = runner(
            [tar, "-tf", str(artifact)],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
        _validate_members(destination, listing.stdout.splitlines())
        runner(
            [tar, "-xf", str(artifact), "-C", str(destination)],
            check=True,
            text=True,
            timeout=120,
        )
        return
    if archive_type in {"tar", "tar.gz", "tgz", "tar.bz2", "tbz2", "tar.xz", "txz"}:
        with tarfile.open(artifact, "r:*") as package:
            members = package.getmembers()
            _validate_members(destination, (item.name for item in members))
            if any(item.issym() or item.islnk() for item in members):
                raise InstallError("Tar archives containing links are not supported")
            package.extractall(destination)
        return
    if archive_type == "appimage":
        shutil.copy2(artifact, destination / Path(executable).name)
        return
    raise InstallError(f"Unsupported archive format: {archive}")


def _validate_members(destination: Path, members: object) -> None:
    root = destination.resolve()
    for member in members:
        target = (destination / str(member)).resolve()
        if os.path.commonpath((root, target)) != str(root):
            raise InstallError(f"Archive member escapes install directory: {member}")


def _resolve_executable(destination: Path, executable: str) -> Path:
    direct = destination / executable
    if direct.is_file():
        return direct
    matches = [path for path in destination.rglob(Path(executable).name) if path.is_file()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise InstallError(f"Installed executable was not found: {executable}")
    raise InstallError(f"Installed executable is ambiguous: {executable}")


def uninstall(
    emulator_id: str,
    strategy: InstallStrategy,
    installed_path: Path | str | InstallInstruction,
    *,
    app_dir: Path = APP_DIR,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InstallInstruction | None:
    """Remove an installed emulator.

    Returns None on success, or an InstallInstruction for privileged removal.
    Raises InstallError on failure.
    """
    if isinstance(installed_path, InstallInstruction):
        return InstallInstruction(f"sudo apt remove {strategy.package}")

    if isinstance(installed_path, str) or strategy.strategy == "flatpak":
        flatpak_id = installed_path if isinstance(installed_path, str) else strategy.flatpak_id
        try:
            runner(["flatpak", "uninstall", "-y", "--user", flatpak_id], check=True, text=True)
        except subprocess.CalledProcessError:
            raise InstallError(f"Failed to uninstall Flatpak app: {flatpak_id}")
        return None

    if isinstance(installed_path, Path):
        safe_id = _safe_component(emulator_id, "emulator id")
        emulator_root = app_dir / "emulators" / safe_id
        if emulator_root.exists():
            shutil.rmtree(emulator_root)
        return None

    raise InstallError(f"Unsupported uninstall target type for {emulator_id}")


def _safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise InstallError(f"Invalid {label}: {value!r}")
    return value
