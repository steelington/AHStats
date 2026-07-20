"""Path resolution that works both running from source and packaged as a
PyInstaller onefile exe.

Two distinct concerns:
  - Bundled read-only assets (icons, theme JSON, chart.js) - PyInstaller
    extracts these to a temp dir each launch (sys._MEIPASS); __file__
    doesn't reliably point there for pure-Python modules bundled in the
    PYZ archive.
  - Writable user data (SQLite cache, logs, CA-cert cache) - must NOT
    live under the onefile temp extraction dir, since that's wiped and
    recreated fresh on every launch. Needs a real per-user directory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent


def resource_path(*parts: str) -> Path:
    """Path to a bundled read-only asset, relative to the ahstats package
    dir, e.g. resource_path("assets", "app_icon.ico"). Works both running
    from source and frozen (PyInstaller must bundle ahstats/assets under
    the same relative "ahstats/assets" location in the onefile archive)."""
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS) / "ahstats"
    else:
        base = PACKAGE_DIR
    return base.joinpath(*parts)


def get_app_data_dir() -> Path:
    """Where the app stores its database, cache, and logs.

    Frozen (packaged exe): %LOCALAPPDATA%\\AHStats - a proper per-user
    Windows data directory. Running from source: the project root, for
    easy dev inspection (matches the pre-packaging default).
    """
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AHStats"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return PACKAGE_DIR.parent
