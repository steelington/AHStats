"""Tour id classification, and the sync narrowing that reads it.

Offline and self-contained: every test builds its own throwaway database
rather than touching the user's cache, so these run on a fresh checkout
with no data synced.

The rule under test is the one piece of Aces High history the code has to
know and a reader can't guess: through Tour 92 there was a single Main
Arena, whose tour ids carry no prefix at all. From Tour 93 the arena split
and the ids gained prefixes, with the Late War arena - later renamed Melee
- continuing the same numbering. Classifying the unprefixed ids as
anything other than "Melee (MA)" hides eighty-odd tours from every view,
which is exactly what happened before.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from ahstats import sync
from ahstats.db import StatsDB, _arena_for_tourid, tour_era, tour_number
from ahstats.parser import TourOption


def _temp_db_path(name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix="ahstats_test_")) / name


class ArenaClassificationTests(unittest.TestCase):
    def test_prefixed_ids_map_to_their_arena(self):
        cases = {
            "LWTour318": "Melee (MA)",
            "LWTour93": "Melee (MA)",
            "CtTour200": "AvA (CT)",
            "WW1Tour50": "WWI",
            "EWTour100": "Early War (EW)",
            "MWTour100": "Mid War (MW)",
        }
        for tourid, expected in cases.items():
            with self.subTest(tourid=tourid):
                self.assertEqual(_arena_for_tourid(tourid), expected)

    def test_unprefixed_ids_are_the_same_arena_as_the_melee_tours_that_follow(self):
        """Tour92 ends 2007-09-30 and LWTour93 begins the next day; they
        are one continuous career and must scope together."""
        for tourid in ("Tour12", "Tour21", "Tour92"):
            with self.subTest(tourid=tourid):
                self.assertEqual(_arena_for_tourid(tourid), "Melee (MA)")

    def test_unprefixed_ids_never_land_in_an_unselectable_bucket(self):
        """The original bug: they were classified "Legacy", which was not
        in ARENA_CHOICES, so no arena picker could reach them."""
        from ahstats.db import ARENA_CHOICES

        for tourid in ("Tour12", "Tour92"):
            with self.subTest(tourid=tourid):
                self.assertIn(_arena_for_tourid(tourid), ARENA_CHOICES)

    def test_unrecognised_ids_are_not_silently_folded_into_an_arena(self):
        self.assertEqual(_arena_for_tourid("SomethingNew42"), "Unknown")


class TourEraTests(unittest.TestCase):
    def test_pre_split_tours_are_marked(self):
        for tourid in ("Tour12", "Tour92"):
            with self.subTest(tourid=tourid):
                self.assertEqual(tour_era(tourid), "Main Arena")

    def test_everything_since_the_split_is_unmarked(self):
        for tourid in ("LWTour93", "LWTour318", "CtTour200", "WW1Tour50"):
            with self.subTest(tourid=tourid):
                self.assertEqual(tour_era(tourid), "")

    def test_era_distinguishes_tours_that_share_an_arena(self):
        """Era earns its place only if it separates ids the arena column
        no longer does."""
        self.assertEqual(_arena_for_tourid("Tour92"), _arena_for_tourid("LWTour93"))
        self.assertNotEqual(tour_era("Tour92"), tour_era("LWTour93"))

    def test_tour_number_ignores_the_prefix(self):
        self.assertEqual(tour_number("Tour92"), 92)
        self.assertEqual(tour_number("LWTour318"), 318)


class ReclassifyOnOpenTests(unittest.TestCase):
    """`arena` is stored, not computed on read, so a database written by
    an older build keeps that build's classification until something
    rewrites it. StatsDB.__init__ is that something."""

    def _write_stale_db(self, path: Path) -> None:
        """A database as an older build left it: the pre-93 tours filed
        under the unselectable "Legacy" bucket."""
        db = StatsDB(path)
        db.upsert_tours([
            TourOption("Tour92", "Tour 92", "2007-09-01", "2007-09-30"),
            TourOption("LWTour93", "Late War Tour 93", "2007-10-01", "2007-10-31"),
        ])
        db.close()
        conn = sqlite3.connect(str(path))
        with conn:
            conn.execute("UPDATE tours SET arena='Legacy' WHERE tourid='Tour92'")
        conn.close()

    def test_opening_an_old_database_repairs_it(self):
        path = _temp_db_path("stale.db")
        self._write_stale_db(path)

        conn = sqlite3.connect(str(path))
        before = conn.execute("SELECT arena FROM tours WHERE tourid='Tour92'").fetchone()[0]
        conn.close()
        self.assertEqual(before, "Legacy", "test setup failed to create a stale row")

        db = StatsDB(path)  # the repair happens here, with no user action
        try:
            tourids = {row["tourid"] for row in db.get_tours(arena="Melee (MA)")}
        finally:
            db.close()

        self.assertEqual(
            tourids, {"Tour92", "LWTour93"},
            "reopening the database should have brought the pre-93 tour back into Melee (MA)",
        )

    def test_repair_reports_what_it_changed_and_is_idempotent(self):
        path = _temp_db_path("stale_twice.db")
        self._write_stale_db(path)

        db = StatsDB(path)  # __init__ already repaired the one stale row
        try:
            self.assertEqual(
                db.reclassify_arenas(), 0,
                "a second pass should find nothing left to change",
            )
        finally:
            db.close()

    def test_correctly_classified_rows_are_left_alone(self):
        path = _temp_db_path("clean.db")
        db = StatsDB(path)
        db.upsert_tours([TourOption("LWTour318", "Melee Tour 318", "2026-07-01", "2026-07-31")])
        self.assertEqual(db.reclassify_arenas(), 0)
        db.close()


class _RecordingClient:
    """Stands in for AhScoreClient, recording which tours a sync asks
    for. Returns a page the parser will reject, so sync_pilot logs the
    failure and moves on - we only care which tours it reached for."""

    def __init__(self):
        self.requested: list[str] = []

    def fetch_pilot_tour_scores(self, gameid, stype="pilot", tourid=""):
        self.requested.append(tourid)
        return "<html><body>not a scores page</body></html>"


class TourRangeSyncTests(unittest.TestCase):
    """The range narrowing itself - no network, no parsing."""

    def setUp(self):
        self.path = _temp_db_path("range.db")
        self.db = StatsDB(self.path)
        self.db.upsert_tours([
            TourOption(f"LWTour{n}", f"Melee Tour {n}", f"20{n:02d}-01-01", f"20{n:02d}-01-31")
            for n in range(90, 100)
        ])
        self.client = _RecordingClient()

    def tearDown(self):
        self.db.close()

    def _sync(self, tour_range):
        sync.sync_pilot(
            self.client, self.db, "TestPilot", "pilot",
            arena="Melee (MA)", fetch_plane_kills=False,
            tour_range=tour_range, stop_event=threading.Event(),
        )
        return [tour_number(t) for t in self.client.requested]

    def test_range_limits_the_fetch_to_the_span(self):
        self.assertEqual(sorted(self._sync((93, 95))), [93, 94, 95])

    def test_range_is_inclusive_at_both_ends(self):
        fetched = self._sync((90, 99))
        self.assertIn(90, fetched)
        self.assertIn(99, fetched)

    def test_no_range_fetches_everything_in_the_arena(self):
        self.assertEqual(len(self._sync(None)), 10)

    def test_a_range_matching_nothing_fetches_nothing(self):
        self.assertEqual(self._sync((500, 600)), [])


if __name__ == "__main__":
    unittest.main()
