"""Orchestrates fetching + parsing + caching, so a second lookup for the
same pilot only has to fetch whatever's new since the last sync.
"""
from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ahstats.client import AhScoreClient
from ahstats.db import StatsDB
from bs4 import BeautifulSoup

logger = logging.getLogger('ahstats.sync')

from ahstats.parser import (
    parse_pilot_plane_kills,
    parse_pilot_tour_scores,
    parse_plane_leaderboard,
    parse_player_plane_stats,
    parse_squad_stats,
    parse_tour_list,
)


@dataclass
class SyncProgress:
    current: int
    total: int
    message: str


ProgressCallback = Optional[Callable[[SyncProgress], None]]


def _today_str() -> str:
    return datetime.date.today().isoformat()


def _is_tour_live(tour_row) -> bool:
    """A tour with no end_date yet parsed, or whose end date hasn't
    passed, is still accumulating stats and should be re-fetched even
    if we already have a cached copy."""
    end_date = tour_row["end_date"]
    return not end_date or end_date >= _today_str()


def ensure_tour_list(client: AhScoreClient, db: StatsDB, progress_cb: ProgressCallback = None) -> None:
    """Make sure the tours table is populated, fetching the landing page
    once if it's empty."""
    if db.get_tours():
        return
    if progress_cb:
        progress_cb(SyncProgress(0, 1, "Discovering available tours..."))
    html = client.fetch_ahscore_landing_page()
    tours = parse_tour_list(BeautifulSoup(html, "lxml"))
    if tours:
        db.upsert_tours(tours)


def fetch_single_tour(
    client: AhScoreClient,
    db: StatsDB,
    gameid: str,
    stype: str,
    tourid: str,
    fetch_plane_kills: bool = True,
) -> bool:
    """Fetch + cache one specific tour for a pilot/squad. Returns True if
    the pilot had recorded activity that tour (False for a valid "did not
    fly" response, which is still cached to avoid re-fetching)."""
    try:
        html = client.fetch_pilot_tour_scores(gameid, stype, tourid=tourid)
    except Exception as e:
        logger.error(f"HTTP error fetching tour {tourid}: {e}")
        raise  # Re-raise to be caught by sync_pilot

    parsed = parse_pilot_tour_scores(html)
    if parsed is None:
        logger.warning(f"Failed to parse tour scores for {tourid} (unexpected page format)")
        return False  # unexpected page - don't cache, allow retry later
    db.save_pilot_tour_scores(gameid, stype, tourid, parsed)
    if not parsed.totals:
        return False  # valid "did not fly" - cached, but nothing to show

    if fetch_plane_kills and stype == "pilot":
        total_kills = parsed.totals.get("total", {}).get("kills", 0)
        if total_kills:
            pk_html = client.fetch_pilot_kills_by_plane(gameid, tourid, kt=total_kills)
            pk_parsed = parse_pilot_plane_kills(pk_html)
            if pk_parsed:
                db.save_pilot_plane_kills(gameid, tourid, pk_parsed)

        # Richer per-plane matrix (kills of/killed by/died in) plus the
        # Field Gunner sortie count that the ahscore endpoint omits.
        pp_html = client.fetch_player_plane_stats(gameid, tourid)
        pp_parsed = parse_player_plane_stats(pp_html)
        if pp_parsed and pp_parsed.planes:
            db.save_player_plane_stats(gameid, tourid, pp_parsed)
    return True


def sync_pilot(
    client: AhScoreClient,
    db: StatsDB,
    gameid: str,
    stype: str = "pilot",
    arena: str | None = None,
    fetch_plane_kills: bool = True,
    progress_cb: ProgressCallback = None,
    stop_event: threading.Event | None = None,
    resume_sync_id: str | None = None,
) -> int:
    """Fetch every tour we don't already have cached for this pilot, plus
    any tour that's still in progress. Pass arena (e.g. 'Melee (MA)') to
    restrict to one arena type - most pilots only care about one.
    Returns the number of tours fetched with recorded activity.

    Args:
        resume_sync_id: If provided, resume from an interrupted sync session
    """
    stop_event = stop_event or threading.Event()
    ensure_tour_list(client, db, progress_cb)

    all_tours = db.get_tours(arena=arena)
    cached_tourids = db.get_pilot_tourids(gameid, stype, arena=arena)

    # Resume from checkpoint if provided
    if resume_sync_id:
        completed_tours = db.get_sync_completed_tours(resume_sync_id)
        to_fetch = [t for t in all_tours if t["tourid"] not in completed_tours]
        sync_id = resume_sync_id
        logger.info(f"Resuming sync {sync_id}, {len(to_fetch)} tours remaining")
    else:
        to_fetch = [t for t in all_tours if t["tourid"] not in cached_tourids or _is_tour_live(t)]
        sync_id = db.start_sync(gameid, stype, arena, len(to_fetch))
        logger.info(f"Starting new sync {sync_id}, {len(to_fetch)} tours to fetch")

    fetched = 0
    stopped_early = False
    for i, tour in enumerate(to_fetch):
        if stop_event.is_set():
            stopped_early = True
            break

        tourid = tour["tourid"]
        if progress_cb:
            progress_cb(SyncProgress(i + 1, len(to_fetch), f"Fetching {tour['label']}..."))

        if stop_event.is_set():
            stopped_early = True
            break

        # Wrap fetch in try/except for error logging
        try:
            had_activity = fetch_single_tour(client, db, gameid, stype, tourid, fetch_plane_kills)
            if had_activity:
                fetched += 1
            db.checkpoint_tour(sync_id, tourid, gameid, stype, had_activity)
        except Exception as e:
            import traceback
            logger.error(f"Failed to fetch tour {tourid}: {e}")
            db.log_error(sync_id, gameid, stype, tourid, 'pilot_tour',
                        type(e).__name__, str(e), traceback.format_exc())
            # Continue with next tour instead of stopping entire sync

    if stopped_early:
        db.finish_sync(sync_id, status='paused')
        logger.info(f"Sync {sync_id} paused by user at {fetched}/{len(to_fetch)} tours")
    else:
        db.finish_sync(sync_id, status='completed')
        logger.info(f"Sync {sync_id} completed: {fetched}/{len(to_fetch)} tours had activity")

    if progress_cb:
        progress_cb(SyncProgress(len(to_fetch), len(to_fetch), f"Done - fetched {fetched} tour(s)."))

    return fetched


def fetch_squad_snapshot(client: AhScoreClient, db: StatsDB, playername: str, tourid: str) -> str | None:
    """One-off fetch of a squad's roster/stats for a single tour. Returns
    the squad name on success, or None if the player/tour had no squad."""
    html = client.fetch_squad_stats(playername, tourid)
    parsed = parse_squad_stats(html)
    if parsed is None or not parsed.squad_name:
        return None
    db.save_squad_stats(tourid, parsed)
    return parsed.squad_name


def fetch_plane_leaderboard_snapshot(client: AhScoreClient, db: StatsDB, tourid: str) -> bool:
    """One-off fetch of the arena-wide plane kill/death leaderboard for a single tour."""
    html = client.fetch_plane_leaderboard(tourid)
    parsed = parse_plane_leaderboard(html)
    if parsed is None or not parsed.planes:
        return False
    db.save_plane_leaderboard(tourid, parsed)
    return True
