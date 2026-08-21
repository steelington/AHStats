"""A tiny key/value store for UI preferences.

Deliberately not the database: this has to be readable before the app
has decided anything, it is a handful of values, and a corrupt or
missing file must never be worse than a shrug. Every failure path -
absent, unreadable, not JSON, JSON that isn't an object, read-only
directory - lands on the defaults and carries on.

Nothing here leaves the machine.
"""
from __future__ import annotations

import json
import logging

from ahstats.paths import get_app_data_dir

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"

DEFAULTS = {
    "appearance_mode": "Dark",   # "Dark" or "Light"
}


def settings_path():
    return get_app_data_dir() / SETTINGS_FILENAME


def load() -> dict:
    """Stored settings over the defaults. Never raises."""
    values = dict(DEFAULTS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            values.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except FileNotFoundError:
        pass
    except Exception as error:            # noqa: BLE001 - a bad file is not fatal
        logger.debug("Ignoring unreadable settings: %s", error)
    return values


def get(key: str):
    return load().get(key, DEFAULTS.get(key))


def save(**changes) -> None:
    """Merge `changes` into the stored settings. Never raises."""
    values = load()
    values.update({k: v for k, v in changes.items() if k in DEFAULTS})
    try:
        with open(settings_path(), "w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2)
    except Exception as error:            # noqa: BLE001 - a preference is not worth a crash
        logger.debug("Could not save settings: %s", error)
