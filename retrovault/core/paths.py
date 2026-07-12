"""Application data locations and logging setup."""

import logging
from pathlib import Path

APP_DIR = Path.home() / ".retrovault"
CONFIG_FILE = APP_DIR / "config.json"
LIBRARY_FILE = APP_DIR / "library.json"
LOG_FILE = APP_DIR / "retrovault.log"
TEST_ROM_FILE = APP_DIR / "test_roms.json"


def init_app_dirs():
    """Create the app data directory and configure file logging.

    Called from the entry point, not at import time, so importing
    retrovault.core has no filesystem side effects.
    """
    APP_DIR.mkdir(exist_ok=True)
    try:
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.CRITICAL)
