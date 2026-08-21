"""Aircraft HTC has renamed since the early tours.

The Ki-61 of the pre-split Main Arena tours and today's Ki-61-I-Tei are
one aeroplane, as are the old P-40B and today's P-40C, but the cache
stored whatever name the page carried, so a pilot who flew both eras saw
two rows with the career split between them. Offline - every test builds
its own throwaway database.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ahstats.db import PLANE_RENAMES, StatsDB, canonical_plane
from ahstats.parser import PilotPlaneKillEntry, PilotPlaneKills


def _temp_db_path(name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix="ahstats_test_")) / name


class CanonicalPlaneTests(unittest.TestCase):
    def test_superseded_names_map_forward(self):
        self.assertEqual(canonical_plane("Ki-61"), "Ki-61-I-Tei")
        self.assertEqual(canonical_plane("P-40B"), "P-40C")

    def test_current_names_are_left_alone(self):
        for name in ("Ki-61-I-Tei", "P-40C", "P-40E", "Spitfire Mk IX", ""):
            with self.subTest(plane=name):
                self.assertEqual(canonical_plane(name), name)

    def test_no_rename_chains(self):
        """A -> B -> C would leave B rows behind on a single pass."""
        for new in PLANE_RENAMES.values():
            self.assertNotIn(new, PLANE_RENAMES)


class CanonicalizePlanesTests(unittest.TestCase):
    """Plane names are stored as fetched, so databases written before a
    rename entered PLANE_RENAMES have to repair themselves on open - the
    same contract as reclassify_arenas()."""

    def setUp(self):
        self.path = _temp_db_path("renames.db")
        self.db = StatsDB(self.path)
        self.addCleanup(self.db.close)
        self.db._conn.executemany(
            "INSERT INTO tours (tourid, label, start_date, end_date, arena) VALUES (?,?,?,?,?)",
            [("Tour17", "Tour 17", "2002-01-01", "2002-01-31", "Melee (MA)"),
             ("LWTour304", "Tour 304", "2025-01-01", "2025-01-31", "Melee (MA)")],
        )

    def _add_matrix_row(self, tourid, plane, kills_in):
        self.db._conn.execute(
            "INSERT INTO pilot_plane_matrix (gameid, tourid, plane, kills_in, kills_of, "
            "killed_by, died_in, fetched_at) VALUES ('Steely',?,?,?,0,0,0,'now')",
            (tourid, plane, kills_in),
        )
        self.db._conn.commit()

    def test_old_name_rows_fold_onto_the_current_name(self):
        self._add_matrix_row("Tour17", "Ki-61", 6)
        self._add_matrix_row("LWTour304", "Ki-61-I-Tei", 1)

        self.assertEqual(self.db.canonicalize_planes(), 1)

        planes = self.db.get_matrix_planes("Steely")
        self.assertEqual(planes, ["Ki-61-I-Tei"])
        career = {r["plane"]: r["kills_in"] for r in self.db.get_career_plane_matrix("Steely")}
        self.assertEqual(career, {"Ki-61-I-Tei": 7})
        # The old tour keeps its own row - a rename is not a merge of tours.
        self.assertEqual(len(self.db.get_plane_matrix_series("Steely", "Ki-61-I-Tei")), 2)

    def test_it_runs_on_open(self):
        self._add_matrix_row("Tour30", "P-40B", 3)
        self.db.close()

        reopened = StatsDB(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(
            [r["plane"] for r in reopened.get_career_plane_matrix("Steely")], ["P-40C"]
        )

    def test_it_is_idempotent(self):
        self._add_matrix_row("Tour17", "Ki-61", 6)
        self.db.canonicalize_planes()
        self.assertEqual(self.db.canonicalize_planes(), 0)

    def test_a_collision_in_one_tour_sums_rather_than_drops(self):
        """Shouldn't happen - the renames are clean cutovers - but losing
        a row silently would be worse than a wrong-looking total."""
        self._add_matrix_row("Tour17", "Ki-61", 6)
        self._add_matrix_row("Tour17", "Ki-61-I-Tei", 2)

        self.db.canonicalize_planes()

        career = {r["plane"]: r["kills_in"] for r in self.db.get_career_plane_matrix("Steely")}
        self.assertEqual(career, {"Ki-61-I-Tei": 8})

    def test_new_fetches_are_stored_under_the_current_name(self):
        """Without normalising on write, a re-sync of an old tour would
        put the superseded name straight back."""
        self.db.save_pilot_plane_kills(
            "Steely", "Tour17",
            PilotPlaneKills(
                pilot_name="Steely", tour_label="Tour 17",
                planes=[PilotPlaneKillEntry("Ki-61", 6, 0, 0, 0, 0, 6)],
            ),
        )
        rows = self.db.get_career_kills_by_plane("Steely")
        self.assertEqual([(r["plane"], r["kills"]) for r in rows], [("Ki-61-I-Tei", 6)])


if __name__ == "__main__":
    unittest.main()
