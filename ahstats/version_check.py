"""Ask GitHub whether a newer release has been published.

What this sends: one anonymous HTTPS GET to the public GitHub releases
API. No pilot name, no database contents, no machine identifier, no
telemetry of any kind - the request carries a User-Agent naming the app
and its version and nothing else. Nothing is collected, stored, or sent
anywhere as a result of the check.

It is deliberately best-effort. No network, GitHub down or rate-limited
(60 anonymous calls an hour per IP), a tag that doesn't parse, a
malformed response - all of it resolves to "no update known", silently.
An update check that interrupts the app to complain it couldn't run is
worse than no update check.

The app never downloads or installs anything. The most it does is offer
to open the release page in the user's browser.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import requests

from ahstats import __version__

logger = logging.getLogger(__name__)

REPO = "steelington/AHStats"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
TIMEOUT = 6.0

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class Release:
    """A published release newer than what's running."""
    version: str        # normalised, no leading "v" - e.g. "1.2.0"
    url: str            # the release page, for the browser
    name: str = ""      # the release title, if GitHub gave one


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """Numeric parts of a version string, or None if there aren't any.

    Tolerant on purpose: "v1.1.5", "1.1.5", and "Release 1.1.5-beta" all
    give (1, 1, 5). A pre-release suffix is ignored rather than treated
    as older, because /releases/latest never returns pre-releases in the
    first place.
    """
    if not text:
        return None
    match = _VERSION_RE.search(text)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str | None, current: str | None) -> bool:
    """True if `candidate` is a strictly higher version than `current`.

    Shorter versions are zero-padded, so 1.2 == 1.2.0 and 1.2.1 > 1.2.
    Anything unparseable is not newer - an odd tag must never nag.
    """
    new = parse_version(candidate)
    old = parse_version(current)
    if new is None or old is None:
        return False
    length = max(len(new), len(old))
    new += (0,) * (length - len(new))
    old += (0,) * (length - len(old))
    return new > old


def fetch_latest_release(timeout: float = TIMEOUT) -> Release | None:
    """The newest published release on GitHub, or None if unknown.

    /releases/latest already excludes drafts and pre-releases, so what
    comes back is what a user should be running.
    """
    try:
        resp = requests.get(
            LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"AHStats/{__version__}",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as error:                # noqa: BLE001 - never fatal
        logger.debug("Update check failed: %s: %s", type(error).__name__, error)
        return None

    version = parse_version(data.get("tag_name"))
    if version is None:
        logger.debug("Update check: unparseable tag %r", data.get("tag_name"))
        return None
    return Release(
        version=".".join(str(part) for part in version),
        url=data.get("html_url") or RELEASES_PAGE,
        name=(data.get("name") or "").strip(),
    )


def check_for_update(current_version: str = __version__,
                     timeout: float = TIMEOUT) -> Release | None:
    """The newer release, or None if up to date or the check failed."""
    release = fetch_latest_release(timeout)
    if release is None or not is_newer(release.version, current_version):
        return None
    logger.info("Update available: v%s (running v%s)", release.version, current_version)
    return release


def check_in_background(callback, current_version: str = __version__) -> threading.Thread:
    """Run the check on a daemon thread; call `callback(release)` if - and
    only if - there is something newer.

    The callback runs on the worker thread, so a Tk caller must bounce it
    back to the GUI thread with `after`. Daemon, so a check still in
    flight never holds the app open at exit.
    """
    def run():
        try:
            release = check_for_update(current_version)
        except Exception as error:            # noqa: BLE001 - never fatal
            logger.debug("Update check thread failed: %s", error)
            return
        if release is not None:
            try:
                callback(release)
            except Exception as error:        # noqa: BLE001 - never fatal
                logger.debug("Update callback failed: %s", error)

    thread = threading.Thread(target=run, name="update-check", daemon=True)
    thread.start()
    return thread
