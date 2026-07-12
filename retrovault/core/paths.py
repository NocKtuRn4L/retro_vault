"""Application data locations and logging setup."""

import logging
import os
from pathlib import Path


def resolve_app_dir(home=None, environ=None):
    """Resolve config storage while preserving existing legacy installations."""
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    override = environ.get("RETROVAULT_HOME")
    if override:
        return Path(override).expanduser()
    legacy = home / ".retrovault"
    if legacy.exists():
        return legacy
    xdg_home = environ.get("XDG_CONFIG_HOME")
    if xdg_home:
        return Path(xdg_home).expanduser() / "retrovault"
    return legacy


APP_DIR = resolve_app_dir()
CONFIG_FILE = APP_DIR / "config.json"
LIBRARY_FILE = APP_DIR / "library.json"
LOG_FILE = APP_DIR / "retrovault.log"
TEST_ROM_FILE = APP_DIR / "test_roms.json"


def init_app_dirs():
    """Create the app data directory and configure file logging.

    Called from the entry point, not at import time, so importing
    retrovault.core has no filesystem side effects.
    """
    APP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.CRITICAL)
