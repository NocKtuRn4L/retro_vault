"""Runtime platform detection (OS, architecture, Flatpak, Raspberry Pi)."""

import platform
import shutil
import sys

_DEVICE_TREE_MODEL = "/proc/device-tree/model"


def current_platform(sys_platform=None, machine=None):
    """Return a platform key like "windows-x86_64", "linux-aarch64", "darwin-arm64".

    `sys_platform`/`machine` may be supplied to override the detected values
    (used by tests); they otherwise default to `sys.platform` and
    `platform.machine()`.
    """
    if sys_platform is None:
        sys_platform = sys.platform
    if machine is None:
        machine = platform.machine()

    if sys_platform == "win32":
        return "windows-x86_64"
    if sys_platform.startswith("linux"):
        if machine.lower() in ("aarch64", "arm64"):
            return "linux-aarch64"
        return "linux-x86_64"
    if sys_platform == "darwin":
        return f"darwin-{machine}"
    return f"{sys_platform}-{machine}"


def has_flatpak():
    return shutil.which("flatpak") is not None


def is_raspberry_pi():
    try:
        with open(_DEVICE_TREE_MODEL, "rb") as f:
            content = f.read()
    except OSError:
        return False
    return b"Raspberry Pi" in content.rstrip(b"\x00")


def capabilities():
    return {
        "platform": current_platform(),
        "flatpak": has_flatpak(),
        "raspberry_pi": is_raspberry_pi(),
    }
