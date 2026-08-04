"""SQLite cache layer. Every fetch from the site gets written here so a
pilot only ever needs to re-fetch tours we don't already have (plus
whichever tour is still in progress, since its numbers keep changing).
"""
from __future__ import annotations

import datetime
import functools
import logging
import re
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger('ahstats.db')

from ahstats.parser import PilotPlaneKills, PilotTourScores, PlaneLeaderboard, PlayerPlaneStats, SquadStats
from ahstats.paths import get_app_data_dir

DEFAULT_DB_PATH = get_app_data_dir() / "ahstats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tours (
    tourid TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    arena TEXT
);

CREATE TABLE IF NOT EXISTS pilot_totals (
    gameid TEXT NOT NULL,
    stype TEXT NOT NULL,
    tourid TEXT NOT NULL,
    category TEXT NOT NULL,
    kills INTEGER, assists INTEGER, sorties INTEGER, landed INTEGER,
    bailed INTEGER, ditched INTEGER, captured INTEGER, deaths INTEGER,
    discos INTEGER, time_seconds INTEGER, rank INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (gameid, stype, tourid, category)
);

CREATE TABLE IF NOT EXISTS pilot_scores (
    gameid TEXT NOT NULL,
    stype TEXT NOT NULL,
    tourid TEXT NOT NULL,
    category TEXT NOT NULL,
    metric TEXT NOT NULL,
    score REAL,
    rank INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (gameid, stype, tourid, category, metric)
);

CREATE TABLE IF NOT EXISTS pilot_plane_kills (
    gameid TEXT NOT NULL,
    tourid TEXT NOT NULL,
    plane TEXT NOT NULL,
    days_1_7 INTEGER, days_8_14 INTEGER, days_15_21 INTEGER,
    days_22_28 INTEGER, days_28_up INTEGER, total INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (gameid, tourid, plane)
);

CREATE TABLE IF NOT EXISTS pilot_plane_kills_meta (
    gameid TEXT NOT NULL,
    tourid TEXT NOT NULL,
    total_kills INTEGER,
    total_kills_toward_rank INTEGER,
    total_kills_not_toward_rank INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (gameid, tourid)
);

CREATE TABLE IF NOT EXISTS squad_snapshots (
    squad_name TEXT NOT NULL,
    tourid TEXT NOT NULL,
    squad_co TEXT,
    member_count INTEGER,
    total_sorties INTEGER,
    total_sortie_time_seconds INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (squad_name, tourid)
);

CREATE TABLE IF NOT EXISTS squad_members (
    squad_name TEXT NOT NULL,
    tourid TEXT NOT NULL,
    member_name TEXT NOT NULL,
    kills INTEGER, kill_pct REAL, deaths INTEGER, death_pct REAL,
    kd_ratio REAL, active INTEGER,
    PRIMARY KEY (squad_name, tourid, member_name)
);

CREATE TABLE IF NOT EXISTS plane_leaderboard (
    tourid TEXT NOT NULL,
    plane TEXT NOT NULL,
    pindex INTEGER,
    kills INTEGER, deaths INTEGER, kd_ratio REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (tourid, plane)
);

CREATE TABLE IF NOT EXISTS plane_leaderboard_meta (
    tourid TEXT PRIMARY KEY,
    total_kills INTEGER,
    total_deaths INTEGER,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_plane_matrix (
    gameid TEXT NOT NULL,
    tourid TEXT NOT NULL,
    plane TEXT NOT NULL,
    kills_in INTEGER, kills_of INTEGER, killed_by INTEGER, died_in INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (gameid, tourid, plane)
);

CREATE TABLE IF NOT EXISTS pilot_plane_matrix_meta (
    gameid TEXT NOT NULL,
    tourid TEXT NOT NULL,
    total_kills INTEGER,
    total_deaths INTEGER,
    fighter_sorties INTEGER, attack_sorties INTEGER, bomber_sorties INTEGER,
    vehicleboat_sorties INTEGER, fieldgunner_sorties INTEGER,
    landed INTEGER, discos INTEGER, bails INTEGER, ditches INTEGER,
    captured INTEGER, deaths INTEGER,
    total_sorties INTEGER, total_sortie_time_seconds INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (gameid, tourid)
);

-- Track overall sync sessions
CREATE TABLE IF NOT EXISTS sync_progress (
    sync_id TEXT PRIMARY KEY,
    gameid TEXT NOT NULL,
    stype TEXT NOT NULL,
    arena TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    total_tours INTEGER,
    tours_processed INTEGER,
    tours_with_activity INTEGER,
    status TEXT
);

-- Track per-tour checkpoints within a sync
CREATE TABLE IF NOT EXISTS sync_tour_checkpoints (
    sync_id TEXT NOT NULL,
    tourid TEXT NOT NULL,
    gameid TEXT NOT NULL,
    stype TEXT NOT NULL,
    checkpoint_at TEXT NOT NULL,
    had_activity INTEGER,
    PRIMARY KEY (sync_id, tourid)
);

-- Track all fetch errors (HTTP, parse, etc.)
CREATE TABLE IF NOT EXISTS sync_errors (
    error_id TEXT PRIMARY KEY,
    sync_id TEXT,
    gameid TEXT,
    stype TEXT,
    tourid TEXT,
    fetch_type TEXT,
    error_code TEXT,
    error_message TEXT NOT NULL,
    traceback TEXT,
    occurred_at TEXT NOT NULL,
    is_resolved INTEGER DEFAULT 0,
    resolved_at TEXT,
    retry_count INTEGER DEFAULT 0
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_pilot_totals_lookup
    ON pilot_totals(gameid, stype, tourid);

CREATE INDEX IF NOT EXISTS idx_tours_arena
    ON tours(arena, start_date DESC);

CREATE INDEX IF NOT EXISTS idx_pilot_plane_matrix_lookup
    ON pilot_plane_matrix(gameid, tourid);

CREATE INDEX IF NOT EXISTS idx_sync_progress_status
    ON sync_progress(gameid, stype, status);

CREATE INDEX IF NOT EXISTS idx_sync_errors_unresolved
    ON sync_errors(gameid, stype, is_resolved, occurred_at);

-- Groups multiple game IDs one player has used (e.g. after a name
-- change) into one combined career view, a la Spatula's original
-- "define a squadron" feature.
CREATE TABLE IF NOT EXISTS identity_groups (
    group_name TEXT NOT NULL,
    stype TEXT NOT NULL,
    gameid TEXT NOT NULL,
    PRIMARY KEY (group_name, stype, gameid)
);
"""

_ARENA_PREFIXES = [
    ("LWTour", "Melee (MA)"),
    ("CtTour", "AvA (CT)"),
    ("WW1Tour", "WWI"),
    ("EWTour", "Early War (EW)"),  # separate arena, retired ~2018 - won't appear in recent tours
    ("MWTour", "Mid War (MW)"),  # separate arena, retired ~2018 - won't appear in recent tours
]

# Ordered for UI pickers: currently-active arenas first, retired ones last.
ARENA_CHOICES = list(dict.fromkeys(name for _, name in _ARENA_PREFIXES))

# Up to and including tour 92 there was one Main Arena, and HTC's tour ids
# for it carry no arena prefix at all ("Tour92"). From tour 93 the arena
# split into Late/Mid/Early War and the ids gained prefixes ("LWTour93"),
# with the Late War arena - later renamed Melee - carrying on the Main
# Arena's tour numbering unbroken: Tour92 ends 2007-09-30 and LWTour93
# begins 2007-10-01. They are one continuous career, so they share an
# arena here; the era below is what tells them apart.
_MAIN_ARENA_TOURID_RE = re.compile(r"^Tour\d+$")

ERA_MAIN_ARENA = "Main Arena"  # unprefixed tour ids, up to tour 92
ERA_CURRENT = ""  # everything since the split needs no marker


def _arena_for_tourid(tourid: str) -> str:
    for prefix, name in _ARENA_PREFIXES:
        if tourid.startswith(prefix):
            return name
    if _MAIN_ARENA_TOURID_RE.match(tourid):
        return "Melee (MA)"
    return "Unknown"


def parse_identity_ids(raw: str) -> list[str]:
    """Game IDs as typed into the identity-group editor.

    Accepts one per line or comma-separated, because people paste both.
    Order is kept - it's usually chronological, which is how a player
    thinks about their own name changes - and exact repeats are dropped,
    since the same id twice would break the insert."""
    ids: list[str] = []
    for part in raw.replace(",", "\n").split("\n"):
        name = part.strip()
        if name and name not in ids:
            ids.append(name)
    return ids


def tour_era(tourid: str) -> str:
    """Marks the pre-split Main Arena tours so that, now they sit in the
    same arena as the Melee tours that continue them, they're still
    tellable apart in the grids. Empty for everything else."""
    return ERA_MAIN_ARENA if _MAIN_ARENA_TOURID_RE.match(tourid) else ERA_CURRENT


def tour_number(tourid: str) -> int:
    """The numeric part of a tourid ('LWTour228' -> 228). Grids sort on
    this rather than the raw tourid so tours past 100 order correctly -
    the same bug Spatula fixed in his 1.5.2 by splitting out a Tour
    column from Tour Details."""
    match = re.search(r"(\d+)$", tourid)
    return int(match.group(1)) if match else 0


# The per-category views (fighter/attack/bomber/vehicle) mirror the eight
# Score/Stats grids in Spatula's app. 'total' is ours, not his.
CATEGORY_LABELS = [
    ("fighter", "Fighter"),
    ("attack", "Attack"),
    ("bomber", "Bomber"),
    ("vehicle", "Vehicle/Boat"),
]

# Column order for the Score grids, per category. HTC only publishes the
# kill-based metrics for fighters; bombers only get the damage-based ones.
SCORE_METRICS = {
    "fighter": [
        "Kills per Death + 1", "Kills per Sortie", "Kills per Hour of Flight",
        "Kills Hit Percentage", "Kill Points",
    ],
    "attack": [
        "Kills per Death + 1", "Kills per Sortie", "Kills per Hour of Flight",
        "Kills Hit Percentage", "Kill Points", "Damage per Death", "Damage per Sortie",
        "Damage Hit Percentage", "Damage Points", "Field Captures",
    ],
    "bomber": [
        "Damage per Death", "Damage per Sortie", "Damage Hit Percentage",
        "Damage Points", "Field Captures",
    ],
    "vehicle": [
        "Kills per Death + 1", "Kills per Sortie", "Kills per Hour of Flight",
        "Kills Hit Percentage", "Kill Points", "Damage per Death", "Damage per Sortie",
        "Damage Hit Percentage", "Damage Points", "Field Captures",
    ],
}

# HTC's own metric names are far too long to use as grid headings - ten
# of them side by side just truncate. These are the column captions.
SCORE_HEADERS = {
    "Kills per Death + 1": "K/Death+1",
    "Kills per Sortie": "K/Sortie",
    "Kills per Hour of Flight": "K/Hour",
    "Kills Hit Percentage": "Kill Hit%",
    "Kill Points": "Kill Pts",
    "Damage per Death": "Dmg/Death",
    "Damage per Sortie": "Dmg/Sortie",
    "Damage Hit Percentage": "Dmg Hit%",
    "Damage Points": "Dmg Pts",
    "Field Captures": "Captures",
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _in_clause(column: str, gameid) -> tuple[str, list]:
    """Builds a "column=?" or "column IN (?,?,...)" fragment so query
    methods can take either a single gameid or an identity group's list
    of gameids (multiple names one player has used over time)."""
    ids = [gameid] if isinstance(gameid, str) else list(gameid)
    placeholders = ",".join(["?"] * len(ids))
    return f"{column} IN ({placeholders})", ids


def _synchronized(method):
    """Serializes calls through self._lock. sqlite3 connections aren't
    safe to use concurrently from multiple threads, and the GUI reads
    from the main thread while sync writes from a background thread."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


def _thread_safe(cls):
    for name, attr in list(vars(cls).items()):
        if callable(attr) and not name.startswith("__"):
            setattr(cls, name, _synchronized(attr))
    return cls


@_thread_safe
class StatsDB:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        # check_same_thread=False: access is serialized by self._lock above,
        # not by sqlite3's own thread affinity check.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        # arena is stored, not computed on read, so a DB written by an
        # older build keeps whatever classification that build derived.
        # Cheap enough to re-derive on every open (a thousand-odd rows,
        # writing only what actually differs).
        changed = self.reclassify_arenas()
        if changed:
            logger.info("Reclassified the arena of %d cached tour(s)", changed)

    def close(self):
        self._conn.close()

    # -- tours -------------------------------------------------------

    def upsert_tours(self, tours) -> None:
        rows = [
            (t.tourid, t.label, t.start_date, t.end_date, _arena_for_tourid(t.tourid))
            for t in tours
        ]
        self._conn.executemany(
            "INSERT INTO tours (tourid, label, start_date, end_date, arena) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tourid) DO UPDATE SET label=excluded.label, start_date=excluded.start_date, "
            "end_date=excluded.end_date, arena=excluded.arena",
            rows,
        )
        self._conn.commit()

    def reclassify_arenas(self) -> int:
        """Re-derive the arena column for every cached tour using the
        current _ARENA_PREFIXES mapping. Needed after that mapping
        changes, since arena is stored, not computed on read. Returns
        the number of rows changed."""
        rows = self._conn.execute("SELECT tourid, arena FROM tours").fetchall()
        changed = 0
        for row in rows:
            new_arena = _arena_for_tourid(row["tourid"])
            if new_arena != row["arena"]:
                self._conn.execute("UPDATE tours SET arena=? WHERE tourid=?", (new_arena, row["tourid"]))
                changed += 1
        self._conn.commit()
        return changed

    def get_tours(self, arena: str | None = None):
        if arena:
            return self._conn.execute(
                "SELECT * FROM tours WHERE arena=? ORDER BY start_date DESC", (arena,)
            ).fetchall()
        return self._conn.execute("SELECT * FROM tours ORDER BY start_date DESC").fetchall()

    def latest_tourid(self) -> str | None:
        row = self._conn.execute("SELECT tourid FROM tours ORDER BY start_date DESC LIMIT 1").fetchone()
        return row["tourid"] if row else None

    # -- pilot tour scores --------------------------------------------

    def has_pilot_tour(self, gameid, stype: str, tourid: str) -> bool:
        clause, ids = _in_clause("gameid", gameid)
        row = self._conn.execute(
            f"SELECT 1 FROM pilot_totals WHERE {clause} AND stype=? AND tourid=? LIMIT 1",
            (*ids, stype, tourid),
        ).fetchone()
        return row is not None

    def save_pilot_tour_scores(self, gameid: str, stype: str, tourid: str, parsed: PilotTourScores) -> None:
        now = _now()
        if parsed.tours:
            self.upsert_tours(parsed.tours)

        self._conn.execute(
            "DELETE FROM pilot_totals WHERE gameid=? AND stype=? AND tourid=?", (gameid, stype, tourid)
        )
        self._conn.execute(
            "DELETE FROM pilot_scores WHERE gameid=? AND stype=? AND tourid=?", (gameid, stype, tourid)
        )

        if not parsed.totals:
            # Pilot had no activity this tour ("did not fly"). Still record
            # a zeroed 'total' row so this tour counts as checked and
            # doesn't get re-fetched on every future sync.
            self._conn.execute(
                "INSERT INTO pilot_totals (gameid, stype, tourid, category, kills, assists, sorties, "
                "landed, bailed, ditched, captured, deaths, discos, time_seconds, rank, fetched_at) "
                "VALUES (?,?,?,?,0,0,0,0,0,0,0,0,0,0,NULL,?)",
                (gameid, stype, tourid, "total", now),
            )

        for category, totals in parsed.totals.items():
            self._conn.execute(
                "INSERT INTO pilot_totals (gameid, stype, tourid, category, kills, assists, sorties, "
                "landed, bailed, ditched, captured, deaths, discos, time_seconds, rank, fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    gameid, stype, tourid, category,
                    totals.get("kills"), totals.get("assists"), totals.get("sorties"),
                    totals.get("landed"), totals.get("bailed"), totals.get("ditched"),
                    totals.get("captured"), totals.get("deaths"), totals.get("discos"),
                    totals.get("time_seconds"), totals.get("rank"), now,
                ),
            )

        for category, metrics in parsed.scores.items():
            for metric, sr in metrics.items():
                self._conn.execute(
                    "INSERT INTO pilot_scores (gameid, stype, tourid, category, metric, score, rank, fetched_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (gameid, stype, tourid, category, metric, sr.get("score"), sr.get("rank"), now),
                )
        self._conn.commit()

    def get_pilot_totals(self, gameid, stype: str, tourid: str):
        clause, ids = _in_clause("gameid", gameid)
        return self._conn.execute(
            f"SELECT * FROM pilot_totals WHERE {clause} AND stype=? AND tourid=?", (*ids, stype, tourid)
        ).fetchall()

    def get_pilot_scores(self, gameid, stype: str, tourid: str):
        clause, ids = _in_clause("gameid", gameid)
        return self._conn.execute(
            f"SELECT * FROM pilot_scores WHERE {clause} AND stype=? AND tourid=?", (*ids, stype, tourid)
        ).fetchall()

    def get_pilot_tourids(self, gameid, stype: str, arena: str | None = None):
        clause, ids = _in_clause("pt.gameid", gameid)
        if arena:
            rows = self._conn.execute(
                f"SELECT DISTINCT pt.tourid FROM pilot_totals pt JOIN tours t ON t.tourid = pt.tourid "
                f"WHERE {clause} AND pt.stype=? AND t.arena=?",
                (*ids, stype, arena),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT DISTINCT pt.tourid FROM pilot_totals pt WHERE {clause} AND pt.stype=?", (*ids, stype)
            ).fetchall()
        return {r["tourid"] for r in rows}

    def get_career_totals(self, gameid, stype: str, arena: str | None = None):
        """Sum of the 'total' category across every cached tour - the
        all-time career numbers. Pass arena to scope to one arena type
        (e.g. 'Melee (MA)') since most pilots only care about one.
        gameid may be a single id or a list (an identity group - summed
        together, e.g. a pilot who changed their in-game name)."""
        clause, ids = _in_clause("pt.gameid", gameid)
        query = (
            "SELECT COUNT(DISTINCT pt.tourid) as tours, SUM(pt.kills) as kills, SUM(pt.assists) as assists, "
            "SUM(pt.sorties) as sorties, SUM(pt.landed) as landed, SUM(pt.bailed) as bailed, "
            "SUM(pt.ditched) as ditched, SUM(pt.captured) as captured, SUM(pt.deaths) as deaths, "
            "SUM(pt.discos) as discos, SUM(pt.time_seconds) as time_seconds "
            "FROM pilot_totals pt "
        )
        params = list(ids) + [stype]
        if arena:
            query += f"JOIN tours t ON t.tourid = pt.tourid WHERE {clause} AND pt.stype=? AND pt.category='total' AND t.arena=?"
            params.append(arena)
        else:
            query += f"WHERE {clause} AND pt.stype=? AND pt.category='total'"
        return self._conn.execute(query, params).fetchone()

    def get_category_stats_series(self, gameid, stype: str, category: str, arena: str | None = None):
        """One row per tour of the raw counting stats for a single
        category - the time series behind Spatula's per-category Stats
        grids. Where our Tour Detail tab shows every category for one
        tour, this shows one category across every tour.

        Rows from an identity group's several gameids are summed per
        tour, so a pilot who renamed mid-tour still gets one row."""
        clause, ids = _in_clause("pt.gameid", gameid)
        query = (
            "SELECT pt.tourid, t.label, t.start_date, t.end_date, t.arena, "
            "SUM(pt.kills) as kills, SUM(pt.assists) as assists, SUM(pt.sorties) as sorties, "
            "SUM(pt.landed) as landed, SUM(pt.bailed) as bailed, SUM(pt.ditched) as ditched, "
            "SUM(pt.captured) as captured, SUM(pt.deaths) as deaths, SUM(pt.discos) as discos, "
            "SUM(pt.time_seconds) as time_seconds, MIN(pt.rank) as rank "
            "FROM pilot_totals pt JOIN tours t ON t.tourid = pt.tourid "
            f"WHERE {clause} AND pt.stype=? AND pt.category=?"
        )
        params = list(ids) + [stype, category]
        if arena:
            query += " AND t.arena=?"
            params.append(arena)
        query += " GROUP BY pt.tourid ORDER BY t.start_date DESC"
        return self._conn.execute(query, params).fetchall()

    def get_category_scores_series(self, gameid, stype: str, category: str, arena: str | None = None):
        """One row per tour of the HTC-computed score metrics for a
        category. Returns (metrics, rows): metrics is the ordered list of
        metric names actually present, and each row is a plain dict of
        tour info plus one key per metric.

        Scores are ratios, so unlike the counting stats they're averaged
        rather than summed across an identity group's gameids. In
        practice only one name is active in any given tour, so the
        average is over a single value."""
        clause, ids = _in_clause("ps.gameid", gameid)
        query = (
            "SELECT ps.tourid, t.label, t.start_date, t.arena, ps.metric, "
            "AVG(ps.score) as score, MIN(ps.rank) as rank "
            "FROM pilot_scores ps JOIN tours t ON t.tourid = ps.tourid "
            f"WHERE {clause} AND ps.stype=? AND ps.category=?"
        )
        params = list(ids) + [stype, category]
        if arena:
            query += " AND t.arena=?"
            params.append(arena)
        query += " GROUP BY ps.tourid, ps.metric ORDER BY t.start_date DESC"

        by_tour: dict[str, dict] = {}
        seen_metrics = set()
        for row in self._conn.execute(query, params):
            tour = by_tour.setdefault(
                row["tourid"],
                {
                    "tourid": row["tourid"], "label": row["label"],
                    "start_date": row["start_date"], "arena": row["arena"],
                },
            )
            tour[row["metric"]] = row["score"]
            seen_metrics.add(row["metric"])

        # Keep the documented column order, dropping metrics HTC didn't
        # publish for this category, then append anything unexpected so a
        # new metric shows up rather than being silently swallowed.
        ordered = [m for m in SCORE_METRICS.get(category, []) if m in seen_metrics]
        ordered += sorted(seen_metrics - set(ordered))
        return ordered, list(by_tour.values())

    # -- pilot kills by plane ------------------------------------------

    def has_pilot_plane_kills(self, gameid: str, tourid: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM pilot_plane_kills_meta WHERE gameid=? AND tourid=? LIMIT 1", (gameid, tourid)
        ).fetchone()
        return row is not None

    def save_pilot_plane_kills(self, gameid: str, tourid: str, parsed: PilotPlaneKills) -> None:
        now = _now()
        self._conn.execute("DELETE FROM pilot_plane_kills WHERE gameid=? AND tourid=?", (gameid, tourid))
        for entry in parsed.planes:
            self._conn.execute(
                "INSERT INTO pilot_plane_kills (gameid, tourid, plane, days_1_7, days_8_14, days_15_21, "
                "days_22_28, days_28_up, total, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    gameid, tourid, entry.plane, entry.days_1_7, entry.days_8_14,
                    entry.days_15_21, entry.days_22_28, entry.days_28_up, entry.total, now,
                ),
            )
        self._conn.execute(
            "INSERT INTO pilot_plane_kills_meta (gameid, tourid, total_kills, total_kills_toward_rank, "
            "total_kills_not_toward_rank, fetched_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(gameid, tourid) DO UPDATE SET total_kills=excluded.total_kills, "
            "total_kills_toward_rank=excluded.total_kills_toward_rank, "
            "total_kills_not_toward_rank=excluded.total_kills_not_toward_rank, fetched_at=excluded.fetched_at",
            (gameid, tourid, parsed.total_kills, parsed.total_kills_toward_rank, parsed.total_kills_not_toward_rank, now),
        )
        self._conn.commit()

    def get_career_kills_by_plane(self, gameid, arena: str | None = None):
        """Kills per plane type, summed across every cached tour."""
        if arena:
            clause, ids = _in_clause("pk.gameid", gameid)
            return self._conn.execute(
                f"SELECT pk.plane, SUM(pk.total) as kills FROM pilot_plane_kills pk "
                f"JOIN tours t ON t.tourid = pk.tourid WHERE {clause} AND t.arena=? "
                f"GROUP BY pk.plane ORDER BY kills DESC",
                (*ids, arena),
            ).fetchall()
        clause, ids = _in_clause("gameid", gameid)
        return self._conn.execute(
            f"SELECT plane, SUM(total) as kills FROM pilot_plane_kills WHERE {clause} "
            f"GROUP BY plane ORDER BY kills DESC",
            ids,
        ).fetchall()

    # -- squad stats ----------------------------------------------------

    def save_squad_stats(self, tourid: str, parsed: SquadStats) -> None:
        now = _now()
        self._conn.execute(
            "INSERT INTO squad_snapshots (squad_name, tourid, squad_co, member_count, total_sorties, "
            "total_sortie_time_seconds, fetched_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(squad_name, tourid) DO UPDATE SET squad_co=excluded.squad_co, "
            "member_count=excluded.member_count, total_sorties=excluded.total_sorties, "
            "total_sortie_time_seconds=excluded.total_sortie_time_seconds, fetched_at=excluded.fetched_at",
            (
                parsed.squad_name, tourid, parsed.squad_co, parsed.member_count,
                parsed.general_stats.get("total_sorties"),
                parsed.general_stats.get("total_sortie_time_seconds"), now,
            ),
        )
        self._conn.execute("DELETE FROM squad_members WHERE squad_name=? AND tourid=?", (parsed.squad_name, tourid))
        for m in parsed.members:
            self._conn.execute(
                "INSERT INTO squad_members (squad_name, tourid, member_name, kills, kill_pct, deaths, "
                "death_pct, kd_ratio, active) VALUES (?,?,?,?,?,?,?,?,?)",
                (parsed.squad_name, tourid, m.name, m.kills, m.kill_pct, m.deaths, m.death_pct, m.kd_ratio, int(m.active)),
            )
        self._conn.commit()

    def get_squad_members(self, squad_name: str, tourid: str):
        return self._conn.execute(
            "SELECT * FROM squad_members WHERE squad_name=? AND tourid=? ORDER BY kills DESC",
            (squad_name, tourid),
        ).fetchall()

    # -- arena plane leaderboard -----------------------------------------

    def has_plane_leaderboard(self, tourid: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM plane_leaderboard_meta WHERE tourid=?", (tourid,)).fetchone()
        return row is not None

    def save_plane_leaderboard(self, tourid: str, parsed: PlaneLeaderboard) -> None:
        now = _now()
        self._conn.execute("DELETE FROM plane_leaderboard WHERE tourid=?", (tourid,))
        for p in parsed.planes:
            self._conn.execute(
                "INSERT INTO plane_leaderboard (tourid, plane, pindex, kills, deaths, kd_ratio, fetched_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (tourid, p.plane, p.pindex, p.kills, p.deaths, p.kd_ratio, now),
            )
        self._conn.execute(
            "INSERT INTO plane_leaderboard_meta (tourid, total_kills, total_deaths, fetched_at) VALUES (?,?,?,?) "
            "ON CONFLICT(tourid) DO UPDATE SET total_kills=excluded.total_kills, "
            "total_deaths=excluded.total_deaths, fetched_at=excluded.fetched_at",
            (tourid, parsed.total_kills, parsed.total_deaths, now),
        )
        self._conn.commit()

    def get_plane_leaderboard(self, tourid: str):
        return self._conn.execute(
            "SELECT * FROM plane_leaderboard WHERE tourid=? ORDER BY kills DESC", (tourid,)
        ).fetchall()

    # -- pilot plane kill matrix (players.php) ---------------------------

    def has_player_plane_stats(self, gameid: str, tourid: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM pilot_plane_matrix_meta WHERE gameid=? AND tourid=? LIMIT 1", (gameid, tourid)
        ).fetchone()
        return row is not None

    def save_player_plane_stats(self, gameid: str, tourid: str, parsed: PlayerPlaneStats) -> None:
        now = _now()
        self._conn.execute("DELETE FROM pilot_plane_matrix WHERE gameid=? AND tourid=?", (gameid, tourid))
        for entry in parsed.planes:
            self._conn.execute(
                "INSERT INTO pilot_plane_matrix (gameid, tourid, plane, kills_in, kills_of, killed_by, "
                "died_in, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                (gameid, tourid, entry.plane, entry.kills_in, entry.kills_of, entry.killed_by, entry.died_in, now),
            )
        gs = parsed.general_stats
        self._conn.execute(
            "INSERT INTO pilot_plane_matrix_meta (gameid, tourid, total_kills, total_deaths, "
            "fighter_sorties, attack_sorties, bomber_sorties, vehicleboat_sorties, fieldgunner_sorties, "
            "landed, discos, bails, ditches, captured, deaths, total_sorties, total_sortie_time_seconds, "
            "fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(gameid, tourid) DO UPDATE SET total_kills=excluded.total_kills, "
            "total_deaths=excluded.total_deaths, fighter_sorties=excluded.fighter_sorties, "
            "attack_sorties=excluded.attack_sorties, bomber_sorties=excluded.bomber_sorties, "
            "vehicleboat_sorties=excluded.vehicleboat_sorties, fieldgunner_sorties=excluded.fieldgunner_sorties, "
            "landed=excluded.landed, discos=excluded.discos, bails=excluded.bails, ditches=excluded.ditches, "
            "captured=excluded.captured, deaths=excluded.deaths, total_sorties=excluded.total_sorties, "
            "total_sortie_time_seconds=excluded.total_sortie_time_seconds, fetched_at=excluded.fetched_at",
            (
                gameid, tourid, parsed.total_kills, parsed.total_deaths,
                gs.get("fighter"), gs.get("attack"), gs.get("bomber"), gs.get("vehicleboat"), gs.get("fieldgunner"),
                gs.get("landed"), gs.get("discos"), gs.get("bails"), gs.get("ditches"), gs.get("captured"),
                gs.get("deaths"), gs.get("total_sorties"), gs.get("total_sortie_time_seconds"), now,
            ),
        )
        self._conn.commit()

    def get_pilot_plane_matrix(self, gameid, tourid: str):
        clause, ids = _in_clause("gameid", gameid)
        return self._conn.execute(
            f"SELECT plane, SUM(kills_in) as kills_in, SUM(kills_of) as kills_of, "
            f"SUM(killed_by) as killed_by, SUM(died_in) as died_in "
            f"FROM pilot_plane_matrix WHERE {clause} AND tourid=? GROUP BY plane ORDER BY kills_in DESC",
            (*ids, tourid),
        ).fetchall()

    def get_matrix_planes(self, gameid, arena: str | None = None) -> list[str]:
        """Every plane this pilot has matrix data for - the model picker
        on the Obj v Obj view."""
        clause, ids = _in_clause("m.gameid", gameid)
        query = (
            "SELECT DISTINCT m.plane FROM pilot_plane_matrix m "
            "JOIN tours t ON t.tourid = m.tourid "
            f"WHERE {clause}"
        )
        params = list(ids)
        if arena:
            query += " AND t.arena=?"
            params.append(arena)
        query += " ORDER BY m.plane"
        return [r["plane"] for r in self._conn.execute(query, params)]

    def get_plane_matrix_series(self, gameid, plane: str, arena: str | None = None):
        """One row per tour for a single plane - Spatula's Obj v Obj
        grouped by Model, where you pick an aircraft and watch how it did
        across your whole career."""
        clause, ids = _in_clause("m.gameid", gameid)
        query = (
            "SELECT m.tourid, t.label, t.arena, SUM(m.kills_in) as kills_in, "
            "SUM(m.kills_of) as kills_of, SUM(m.killed_by) as killed_by, "
            "SUM(m.died_in) as died_in "
            "FROM pilot_plane_matrix m JOIN tours t ON t.tourid = m.tourid "
            f"WHERE {clause} AND m.plane=?"
        )
        params = list(ids) + [plane]
        if arena:
            query += " AND t.arena=?"
            params.append(arena)
        query += " GROUP BY m.tourid ORDER BY t.start_date DESC"
        return self._conn.execute(query, params).fetchall()

    def get_tourids_missing_matrix(self, gameid, stype: str, arena: str | None = None) -> list[str]:
        """Tours where the pilot flew but we never cached the per-plane
        matrix. Bulk syncs run before that endpoint was added left this
        gap, and has_pilot_tour() stops a re-sync from filling it - hence
        the explicit backfill."""
        clause, ids = _in_clause("pt.gameid", gameid)
        query = (
            "SELECT DISTINCT pt.tourid FROM pilot_totals pt "
            "JOIN tours t ON t.tourid = pt.tourid "
            f"WHERE {clause} AND pt.stype=? AND pt.category='total' AND pt.sorties > 0 "
            "AND NOT EXISTS (SELECT 1 FROM pilot_plane_matrix m "
            "                WHERE m.gameid = pt.gameid AND m.tourid = pt.tourid)"
        )
        params = list(ids) + [stype]
        if arena:
            query += " AND t.arena=?"
            params.append(arena)
        query += " ORDER BY t.start_date DESC"
        return [r["tourid"] for r in self._conn.execute(query, params)]

    def get_career_plane_matrix(self, gameid, arena: str | None = None):
        """Kills in/of, killed by, died in per plane type, summed across
        every cached tour - the career-wide plane-vs-plane breakdown."""
        if arena:
            clause, ids = _in_clause("pm.gameid", gameid)
            return self._conn.execute(
                f"SELECT pm.plane, SUM(pm.kills_in) as kills_in, SUM(pm.kills_of) as kills_of, "
                f"SUM(pm.killed_by) as killed_by, SUM(pm.died_in) as died_in "
                f"FROM pilot_plane_matrix pm JOIN tours t ON t.tourid = pm.tourid "
                f"WHERE {clause} AND t.arena=? GROUP BY pm.plane ORDER BY kills_in DESC",
                (*ids, arena),
            ).fetchall()
        clause, ids = _in_clause("gameid", gameid)
        return self._conn.execute(
            f"SELECT plane, SUM(kills_in) as kills_in, SUM(kills_of) as kills_of, "
            f"SUM(killed_by) as killed_by, SUM(died_in) as died_in "
            f"FROM pilot_plane_matrix WHERE {clause} GROUP BY plane ORDER BY kills_in DESC",
            ids,
        ).fetchall()

    # --- Sync progress tracking methods ---

    def start_sync(self, gameid: str, stype: str, arena: str | None, total_tours: int) -> str:
        """Create new sync session, return sync_id."""
        import uuid
        sync_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO sync_progress (sync_id, gameid, stype, arena, started_at, updated_at, "
            "total_tours, tours_processed, tours_with_activity, status) VALUES (?,?,?,?,?,?,?,0,0,'in_progress')",
            (sync_id, gameid, stype, arena, _now(), _now(), total_tours)
        )
        self._conn.commit()
        return sync_id

    def checkpoint_tour(self, sync_id: str, tourid: str, gameid: str, stype: str, had_activity: bool):
        """Save progress after processing one tour."""
        self._conn.execute(
            "INSERT INTO sync_tour_checkpoints (sync_id, tourid, gameid, stype, checkpoint_at, had_activity) "
            "VALUES (?,?,?,?,?,?)",
            (sync_id, tourid, gameid, stype, _now(), int(had_activity))
        )
        self._conn.execute(
            "UPDATE sync_progress SET tours_processed = tours_processed + 1, "
            "tours_with_activity = tours_with_activity + ?, updated_at = ? WHERE sync_id = ?",
            (int(had_activity), _now(), sync_id)
        )
        self._conn.commit()

    def finish_sync(self, sync_id: str, status: str = 'completed'):
        """Mark sync as complete or paused."""
        self._conn.execute(
            "UPDATE sync_progress SET completed_at = ?, status = ?, updated_at = ? WHERE sync_id = ?",
            (_now(), status, _now(), sync_id)
        )
        self._conn.commit()

    def get_incomplete_syncs(self, gameid: str, stype: str):
        """Find syncs that were interrupted."""
        return self._conn.execute(
            "SELECT * FROM sync_progress WHERE gameid = ? AND stype = ? AND status = 'in_progress' "
            "ORDER BY started_at DESC",
            (gameid, stype)
        ).fetchall()

    def get_sync_completed_tours(self, sync_id: str):
        """Get list of tours already processed in this sync."""
        return {row["tourid"] for row in self._conn.execute(
            "SELECT tourid FROM sync_tour_checkpoints WHERE sync_id = ?", (sync_id,)
        ).fetchall()}

    def log_error(self, sync_id: str | None, gameid: str, stype: str, tourid: str,
                  fetch_type: str, error_code: str, error_message: str, traceback_str: str):
        """Log a fetch error."""
        import uuid
        error_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO sync_errors (error_id, sync_id, gameid, stype, tourid, fetch_type, "
            "error_code, error_message, traceback, occurred_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (error_id, sync_id, gameid, stype, tourid, fetch_type, error_code, error_message, traceback_str, _now())
        )
        self._conn.commit()

    def get_failed_tours(self, gameid: str, stype: str, days: int = 7):
        """Get tours that failed in last N days."""
        return self._conn.execute(
            "SELECT DISTINCT tourid, error_message, occurred_at FROM sync_errors "
            "WHERE gameid = ? AND stype = ? AND is_resolved = 0 "
            "AND occurred_at > datetime('now', '-' || ? || ' days') "
            "ORDER BY occurred_at DESC",
            (gameid, stype, days)
        ).fetchall()

    # --- Identity groups (combined career view across name changes) ---

    def save_identity_group(self, group_name: str, stype: str, gameids: list[str]) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM identity_groups WHERE group_name=? AND stype=?", (group_name, stype)
            )
            # Deduplicated because (group_name, stype, gameid) is the primary
            # key: the same name listed twice would fail the insert and lose
            # the whole group, and a repeat is a typing slip rather than
            # something to report back at the user.
            self._conn.executemany(
                "INSERT INTO identity_groups (group_name, stype, gameid) VALUES (?,?,?)",
                [(group_name, stype, g) for g in parse_identity_ids("\n".join(gameids))],
            )

    def delete_identity_group(self, group_name: str, stype: str) -> None:
        self._conn.execute(
            "DELETE FROM identity_groups WHERE group_name=? AND stype=?", (group_name, stype)
        )
        self._conn.commit()

    def get_identity_group_names(self, stype: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT group_name FROM identity_groups WHERE stype=? ORDER BY group_name", (stype,)
        ).fetchall()
        return [r["group_name"] for r in rows]

    def get_identity_group_members(self, group_name: str, stype: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT gameid FROM identity_groups WHERE group_name=? AND stype=? ORDER BY gameid",
            (group_name, stype),
        ).fetchall()
        return [r["gameid"] for r in rows]
