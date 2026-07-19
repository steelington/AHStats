"""Logging configuration for AHSTATS application."""
from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_file: Path | None = None) -> logging.Logger:
    """Configure logging for entire application.

    Args:
        log_file: Path to log file. If None, defaults to ahstats.log in project root.

    Returns:
        Logger instance for the ahstats module.
    """
    if log_file is None:
        log_file = Path(__file__).parent.parent / "ahstats.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()  # Also print to console
        ]
    )
    return logging.getLogger('ahstats')
