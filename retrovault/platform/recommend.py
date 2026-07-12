"""Platform-aware wrappers around core.config's recommendation lookups.

Unlike `core.config.get_recommended_emulator` (which defaults to the
"windows-x86_64" table when no platform_key is given), the functions here
auto-detect the current machine via `detect.current_platform()`.
"""

from ..core import config as _config
from . import detect

_FALLBACK_CHAIN_TAIL = ("linux-x86_64", "windows-x86_64")


def get_recommended_emulator(system_key, platform_key=None):
    if platform_key is None:
        platform_key = detect.current_platform()
    return _config.get_recommended_emulator(system_key, platform_key=platform_key)


def apply_recommended_emulator(config, system_key, path=None, platform_key=None):
    if platform_key is None:
        platform_key = detect.current_platform()
    return _config.apply_recommended_emulator(config, system_key, path=path, platform_key=platform_key)


def default_backend(platform_key=None):
    if platform_key is None:
        platform_key = detect.current_platform()

    for candidate in (platform_key, *_FALLBACK_CHAIN_TAIL):
        table = _config.RECOMMENDED_EMULATORS.get(candidate)
        if not table:
            continue
        backend = table.get("_default_backend")
        if backend:
            return backend
    return None
