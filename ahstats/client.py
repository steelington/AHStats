"""Rate-limited HTTP client for HiTech Creations' public stats pages.

All four endpoints below are plain, unauthenticated public forms (no
cookies, no CSRF token) - we're just automating what a browser does when
a player submits the stats lookup form on the website. To stay a good
citizen and avoid tripping any IP-based abuse detection, every request
goes through a single shared session with an enforced minimum delay
between calls.

Endpoints:
  - www.hitechcreations.com/component/ahscore/index.php
      Pilot or squad score summary for one tour (Joomla component).
  - bbs.hitechcreations.com/scores/squadstats.php
      Roster + stats for a player's current squad, for one tour.
  - bbs.hitechcreations.com/scores/planes.php
      Arena-wide kills/deaths leaderboard by plane type, for one tour.
  - bbs.hitechcreations.com/newscores/killstat.php
      One pilot's kills broken down by plane type (with weekly buckets), for one tour.
  - bbs.hitechcreations.com/scores/players.php
      One pilot's full per-plane kill matrix (kills in/of, killed by, died
      in) plus a sortie-type breakdown including Field Gunner, for one tour.

Certificate note: hitechcreations.com's server does not send its
intermediate certificate during the TLS handshake. Browsers silently
paper over this via AIA-fetching; plain HTTP clients don't, so
verification fails even though the chain is legitimate (Sectigo DV).
We fix this properly by fetching the missing intermediate once and
verifying against a combined bundle, rather than disabling verification.
"""
from __future__ import annotations

import logging
import ssl
import threading
import time

logger = logging.getLogger('ahstats.client')

import certifi
import requests

from ahstats.paths import get_app_data_dir

AHSCORE_URL = "https://www.hitechcreations.com/component/ahscore/index.php"
SQUADSTATS_URL = "https://bbs.hitechcreations.com/scores/squadstats.php"
PLANES_URL = "https://bbs.hitechcreations.com/scores/planes.php"
KILLSTAT_URL = "https://bbs.hitechcreations.com/newscores/killstat.php"
PLAYERS_URL = "https://bbs.hitechcreations.com/scores/players.php"

# Missing from the server's handshake; fetched once and cached alongside
# certifi's root bundle so verification succeeds without disabling it.
SECTIGO_INTERMEDIATE_URL = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"
_CACHE_DIR = get_app_data_dir() / "_cache"
_BUNDLE_PATH = _CACHE_DIR / "ca_bundle.pem"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_MIN_INTERVAL = 3.0  # seconds between requests, be polite


def _build_ca_bundle() -> str:
    """Return a path to a CA bundle that includes the Sectigo intermediate
    hitechcreations.com's server fails to send. Cached on disk after the
    first successful fetch.
    """
    if _BUNDLE_PATH.exists():
        return str(_BUNDLE_PATH)

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(SECTIGO_INTERMEDIATE_URL, timeout=10)
    resp.raise_for_status()
    intermediate_pem = ssl.DER_cert_to_PEM_cert(resp.content)

    with open(certifi.where(), "r", encoding="ascii") as f:
        bundle = f.read()
    bundle += "\n" + intermediate_pem

    _BUNDLE_PATH.write_text(bundle, encoding="ascii")
    return str(_BUNDLE_PATH)


class AhScoreClient:
    """Thread-safe, rate-limited client for fetching stats pages."""

    def __init__(self, min_interval: float = DEFAULT_MIN_INTERVAL, timeout: float = 60.0):
        self.min_interval = min_interval
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        try:
            self._session.verify = _build_ca_bundle()
        except requests.RequestException:
            # Fall back to default verification; individual requests will
            # raise a clear SSL error instead of failing silently insecure.
            pass
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_request_time)
            if wait > 0:
                time.sleep(wait)
            self._last_request_time = time.monotonic()

    def _get(self, url: str, params: dict) -> str:
        self._throttle()
        headers = {"Referer": "https://www.hitechcreations.com/"}
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(f"HTTP GET failed for {url}: {e}")
            raise

    def _post(self, url: str, data: dict, referer: str) -> str:
        self._throttle()
        headers = {
            "Origin": "https://www.hitechcreations.com" if "hitechcreations.com" in url else None,
            "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        headers = {k: v for k, v in headers.items() if v}
        try:
            resp = self._session.post(url, data=data, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(f"HTTP POST failed for {url}: {e}")
            raise

    def fetch_ahscore_landing_page(self) -> str:
        """Plain GET of the stats lookup form, same as a browser's first
        visit. Returns the full tour dropdown list but no pilot data -
        used to discover which tours exist before looking anyone up.
        """
        params = {"option": "com_ahscore", "task": "ahscore", "Itemid": "240", "view": "pilotranks"}
        return self._get(AHSCORE_URL, params)

    def fetch_pilot_tour_scores(self, gameid: str, stype: str = "pilot", tourid: str = "") -> str:
        """Score summary for a pilot or squad, for one specific tour.
        tourid must be a real tour id - an empty/blank tourid returns a
        "did not fly" page rather than defaulting to the current tour.
        Also returns the full tour dropdown list in the page.
        """
        if stype not in ("pilot", "squad"):
            raise ValueError("stype must be 'pilot' or 'squad'")
        data = {
            "option": "com_ahscore",
            "task": "ahscore",
            "Itemid": "240",
            "view": "pilotranks",
            "stype": stype,
            "tourid": tourid,
            "gameid": gameid,
        }
        return self._post(AHSCORE_URL, data, referer="https://www.hitechcreations.com/component/ahscore/?Itemid=240")

    def fetch_squad_stats(self, playername: str, tourid: str) -> str:
        """Roster + stats for playername's current squad, for one tour."""
        data = {"playername": playername, "selectTour": tourid, "action": "1", "Submit": "Get Stats"}
        return self._post(SQUADSTATS_URL, data, referer=SQUADSTATS_URL)

    def fetch_plane_leaderboard(self, tourid: str) -> str:
        """Arena-wide kills/deaths by plane type, for one tour."""
        data = {"selectTour": tourid, "action": "1", "Submit": "Get Stats"}
        return self._post(PLANES_URL, data, referer=PLANES_URL)

    def fetch_pilot_kills_by_plane(self, player: str, tourid: str, kt: int = 0) -> str:
        """One pilot's kills broken down by plane type, for one tour.
        kt appears to just be an echoed kill-count parameter; pass the
        pilot's known total kills for that tour if available, else 0.
        """
        params = {"selectTour": tourid, "player": player, "kt": str(kt)}
        return self._get(KILLSTAT_URL, params)

    def fetch_player_plane_stats(self, playername: str, tourid: str) -> str:
        """One pilot's full per-plane kill matrix (kills in/of, killed by,
        died in) plus a sortie-type breakdown, for one tour."""
        data = {"playername": playername, "selectTour": tourid, "action": "1", "Submit": "Get Stats"}
        return self._post(PLAYERS_URL, data, referer=PLAYERS_URL)
