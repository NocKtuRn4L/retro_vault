#!/usr/bin/env python3
"""Compatibility shim — RetroVault now lives in the retrovault package.

Run `python launcher.py` as before, or use the installed `retrovault` command.
"""

from retrovault.__main__ import main

if __name__ == "__main__":
    main()
