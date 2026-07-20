"""Logging configuration for AHSTATS application."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from ahstats.paths import get_app_data_dir


def setup_logging(log_file: Path | None = None) -> logging.Logger:
    """Configure logging for entire application.

    Args:
        log_file: Path to log file. If None, defaults to ahstats.log in the
            app data dir (project root in dev, %LOCALAPPDATA%\\AHStats when
            packaged as a onefile exe).

    Returns:
        Logger instance for the ahstats module.
    """
    if log_file is None:
        log_file = get_app_data_dir() / "ahstats.log"

    handlers = [logging.FileHandler(log_file, encoding='utf-8')]
    # A --noconsole/--windowed exe has no real stdout, so a StreamHandler
    # would raise on every log call. Only attach it when one exists.
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers,
    )
    return logging.getLogger('ahstats')
