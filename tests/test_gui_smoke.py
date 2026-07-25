"""End-to-end smoke tests that drive the real GUI against the local cache.

These build an actual App, point it at a pilot, and exercise every tab,
picker, sort and filter the way a user would - then assert the data that
comes back is what the database says it should be. The point is to catch
a tab that silently renders nothing, which unit tests on the parsers
can't see.

Deliberately offline: only the cache-reading paths are exercised, never
the fetch buttons, so the suite never touches HiTech's servers and never
depends on their availability. Anything requiring a fetch is asserted
against its empty state instead.

Skips cleanly when there's no cached data for the pilot (a fresh clone,
or CI) rather than failing.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ahstats import __version__, export
from ahstats.db import CATEGORY_LABELS, DEFAULT_DB_PATH, StatsDB, tour_number

STYPE = "pilot"
ARENA = "Melee (MA)"

# A category needs enough cached tours for sorting and filtering to mean
# anything; below this the assertions can't distinguish working from
# broken, so the suite skips instead of giving a false pass.
MIN_TOURS = 5


def _cache_is_usable(pilot: str) -> tuple[bool, str]:
    if not Path(DEFAULT_DB_PATH).exists():
        return False, f"no cache at {DEFAULT_DB_PATH}"
    db = StatsDB(DEFAULT_DB_PATH)
    try:
        rows = db.get_category_stats_series(pilot, STYPE, "fighter", arena=ARENA)
    finally:
        db.close()
    if len(rows) < MIN_TOURS:
        return False, f"only {len(rows)} cached {ARENA} tours for {pilot}"
    return True, ""


class PilotSmokeTests:
    """Every check, run against one pilot's cache.

    A mixin rather than a TestCase on purpose: unittest collects any
    TestCase subclass it finds in the module, so a base class holding the
    tests would be run once with no pilot set. Subclasses below pair this
    with TestCase and supply PILOT.

    Running the same assertions over more than one pilot is what stops a
    test from passing on the quirks of a single career - one pilot might
    have flown every tour, or never flown a bomber, and hide a whole
    broken view.

    One App instance is shared across the class; building it is slow.
    """

    PILOT: str

    @classmethod
    def setUpClass(cls):
        usable, why = _cache_is_usable(cls.PILOT)
        if not usable:
            raise unittest.SkipTest(why)

        try:
            import ahstats.gui as gui
        except Exception as e:  # pragma: no cover - import guard
            raise unittest.SkipTest(f"GUI unavailable: {e}")

        try:
            cls.app = gui.App()
        except Exception as e:  # no display, etc.
            raise unittest.SkipTest(f"cannot create window: {e}")

        cls.app.gameid_entry.delete(0, "end")
        cls.app.gameid_entry.insert(0, cls.PILOT)
        cls.app.stype_var.set(STYPE)
        cls.app.identity_view_var.set("Single ID")
        cls.app.arena_var.set(ARENA)
        cls.db = cls.app.db

    @classmethod
    def tearDownClass(cls):
        app = getattr(cls, "app", None)
        if app is None:
            return
        # Cancel every pending 'after', not just our own. App.destroy()
        # handles the app's timers, but customtkinter keeps its own -
        # notably a DPI check that reschedules itself forever, so there is
        # always one queued. Left alone they fire into a torn-down
        # interpreter and spray Tk errors over the test output.
        try:
            for after_id in app.tk.splitlist(app.tk.call("after", "info")):
                try:
                    app.after_cancel(after_id)
                except Exception:
                    pass
        except Exception:
            pass
        app.destroy()

    def setUp(self):
        # Each test starts from the same known selection.
        self.app.arena_var.set(ARENA)
        self.app.identity_view_var.set("Single ID")

    # -- helpers ------------------------------------------------------

    def _tour_with_activity(self):
        """(label, tourid) of a cached tour the pilot actually flew."""
        for row in self.db.get_category_stats_series(self.PILOT, STYPE, "total", arena=ARENA):
            if row["sorties"]:
                return row["label"], row["tourid"]
        self.skipTest("no cached tour with activity")

    # -- career summary -----------------------------------------------

    def test_career_summary_populates(self):
        self.app.refresh_career()
        rows = dict(self.app.career_grid.visible_rows())
        self.assertIn("Total Kills", rows)

        career = self.db.get_career_totals(self.PILOT, STYPE, arena=ARENA)
        self.assertEqual(rows["Total Kills"], career["kills"])
        self.assertEqual(rows["Tours Synced"], career["tours"])
        self.assertGreater(rows["Total Kills"], 0, "career kills should not be zero")

    # -- tour detail ---------------------------------------------------

    def test_tour_detail_shows_every_category(self):
        self.app.refresh_tour_dropdown()
        label, tourid = self._tour_with_activity()
        self.app.tour_var.set(label)
        self.app.on_tour_selected(label)

        rows = self.app.tour_grid.visible_rows()
        categories = {r[0] for r in rows}
        self.assertEqual(len(rows), len(self.db.get_pilot_totals(self.PILOT, STYPE, tourid)))
        self.assertIn("total", categories)
        self.assertTrue(
            any(r[1] for r in rows), f"{label} was chosen for having activity but shows no kills"
        )

    def test_tour_detail_labels_a_did_not_fly_tour(self):
        """A cached zero tour must read as 'no activity', not 'not fetched'."""
        self.app.refresh_tour_dropdown()
        zero = next(
            (r for r in self.db.get_category_stats_series(self.PILOT, STYPE, "total", arena=ARENA)
             if not r["sorties"]),
            None,
        )
        if zero is None:
            self.skipTest("no cached did-not-fly tour")

        self.app.tour_var.set(zero["label"])
        self.app.on_tour_selected(zero["label"])
        status = self.app.tour_status_label.cget("text")
        self.assertIn("No recorded activity", status)
        self.assertNotIn("Not fetched", status)

    # -- tour history (the eight per-category grids) -------------------

    def test_all_eight_category_grids_populate(self):
        expected = len(self.db.get_category_stats_series(self.PILOT, STYPE, "fighter", arena=ARENA))
        for view in ("Stats", "Score"):
            for key, label in CATEGORY_LABELS:
                with self.subTest(category=label, view=view):
                    self.app.category_view_var.set(view)
                    self.app.category_var.set(label)
                    self.app.refresh_category()

                    rows = self.app.category_grid.visible_rows()
                    self.assertEqual(
                        len(rows), expected,
                        f"{label}/{view} should have one row per cached tour",
                    )
                    self.assertGreater(len(self.app.category_grid.columns), 3)

    def test_stats_grid_matches_database(self):
        self.app.category_view_var.set("Stats")
        self.app.category_var.set("Fighter")
        self.app.refresh_category()

        rows = self.app.category_grid.visible_rows()
        db_rows = self.db.get_category_stats_series(self.PILOT, STYPE, "fighter", arena=ARENA)
        by_tour = {tour_number(r["tourid"]): r for r in db_rows}
        columns = self.app.category_grid.columns

        for row in rows[:10]:
            source = by_tour[row[0]]
            self.assertEqual(row[columns.index("Kills")], source["kills"])
            self.assertEqual(row[columns.index("Sorties")], source["sorties"])
            self.assertEqual(row[columns.index("Deaths")], source["deaths"])

    def test_score_grid_uses_category_specific_metrics(self):
        """HTC publishes kill metrics for fighters but not for bombers."""
        self.app.category_view_var.set("Score")

        self.app.category_var.set("Fighter")
        self.app.refresh_category()
        self.assertIn("K/Death+1", self.app.category_grid.columns)

        self.app.category_var.set("Bomber")
        self.app.refresh_category()
        bomber_columns = self.app.category_grid.columns
        self.assertIn("Dmg/Sortie", bomber_columns)
        self.assertNotIn("K/Death+1", bomber_columns)

    # -- sorting and filtering ------------------------------------------

    def test_sorting_toggles_direction(self):
        self.app.category_view_var.set("Stats")
        self.app.category_var.set("Fighter")
        self.app.refresh_category()
        grid = self.app.category_grid
        index = grid.columns.index("Kills")

        grid.sort_by("Kills")
        ascending = [r[index] for r in grid.visible_rows()]
        self.assertEqual(ascending, sorted(ascending), "first click should sort ascending")

        grid.sort_by("Kills")
        descending = [r[index] for r in grid.visible_rows()]
        self.assertEqual(descending, sorted(descending, reverse=True), "second click should reverse")
        self.assertEqual(len(ascending), len(descending), "sorting must not drop rows")

    def test_quick_filter_narrows_without_losing_data(self):
        self.app.category_view_var.set("Stats")
        self.app.category_var.set("Fighter")
        self.app.refresh_category()
        grid = self.app.category_grid
        total = len(grid.visible_rows())

        grid.set_quick_filter("zzzz-no-such-tour")
        self.assertEqual(len(grid.visible_rows()), 0)

        grid.set_quick_filter("")
        self.assertEqual(len(grid.visible_rows()), total, "clearing the filter must restore every row")

    def test_column_filter_applies_numeric_range(self):
        from ahstats.grid import ColumnFilter

        self.app.category_view_var.set("Stats")
        self.app.category_var.set("Fighter")
        self.app.refresh_category()
        grid = self.app.category_grid
        index = grid.columns.index("Kills")

        threshold = 10
        grid._filters["Kills"] = ColumnFilter(low=threshold)
        grid._rebuild()

        rows = grid.visible_rows()
        if not rows:
            self.skipTest(f"no tours with >= {threshold} kills")
        self.assertTrue(all(int(r[index]) >= threshold for r in rows))
        self.assertIn("⚑", grid.tree.heading("Kills", "text"), "filtered column should be flagged")

        grid.clear_filters()

    def test_totals_footer_follows_the_filter(self):
        self.app.category_view_var.set("Stats")
        self.app.category_var.set("Fighter")
        self.app.refresh_category()
        grid = self.app.category_grid
        index = grid.columns.index("Kills")

        expected = sum(int(r[index]) for r in grid.visible_rows())
        self.assertIn(f"{expected:,}", self.app.category_totals_label.cget("text"))

        grid.set_quick_filter("zzzz-no-such-tour")
        self.assertIn("Total Kills: 0", self.app.category_totals_label.cget("text"))
        grid.set_quick_filter("")

    # -- kills by plane / obj v obj --------------------------------------

    def test_plane_matrix_career_scope(self):
        self.app.planes_scope_var.set("Career")
        self.app.on_planes_scope_changed()

        rows = self.app.planes_grid.visible_rows()
        expected = len(self.db.get_career_plane_matrix(self.PILOT, arena=ARENA))
        self.assertEqual(len(rows), expected)
        if not rows:
            self.skipTest("no plane matrix cached - run the backfill")
        self.assertEqual(self.app.planes_grid.columns[0], "Plane")

    def test_plane_matrix_by_model(self):
        planes = self.db.get_matrix_planes(self.PILOT, arena=ARENA)
        if not planes:
            self.skipTest("no plane matrix cached - run the backfill")

        self.app.planes_scope_var.set("By Model")
        self.app.on_planes_scope_changed()
        # Pick whichever model has the most tours, so the view is exercised
        # with more than a single row wherever possible.
        best = max(planes, key=lambda p: len(self.db.get_plane_matrix_series(self.PILOT, p, arena=ARENA)))
        self.app.planes_model_var.set(best)
        self.app.refresh_planes()

        rows = self.app.planes_grid.visible_rows()
        self.assertEqual(len(rows), len(self.db.get_plane_matrix_series(self.PILOT, best, arena=ARENA)))
        self.assertEqual(self.app.planes_grid.columns[0], "Tour")
        self.assertIn("Kills/Death", self.app.planes_grid.columns)

    def test_switching_scope_restores_plane_columns(self):
        """By Model swaps the columns out; going back must restore them."""
        self.app.planes_scope_var.set("By Model")
        self.app.on_planes_scope_changed()
        self.app.planes_scope_var.set("Career")
        self.app.on_planes_scope_changed()
        self.assertEqual(self.app.planes_grid.columns[0], "Plane")

    # -- graphs -----------------------------------------------------------

    def test_every_graph_renders_for_every_category(self):
        for label in [lab for _, lab in CATEGORY_LABELS]:
            for name in self.app.GRAPHS:
                with self.subTest(category=label, graph=name):
                    self.app.graph_category_var.set(label)
                    self.app.graph_var.set(name)
                    self.app.refresh_graph()  # must not raise
                    self.assertTrue(self.app.graph_status_label.cget("text"))

    def test_fighter_kill_death_trend_has_a_point_per_tour(self):
        self.app.graph_category_var.set("Fighter")
        self.app.graph_var.set("Kill/Death Trend")
        self.app.refresh_graph()

        expected = len(self.db.get_category_stats_series(self.PILOT, STYPE, "fighter", arena=ARENA))
        self.assertEqual(len(self.app.chart._points), expected)
        self.assertIn("plotted", self.app.graph_status_label.cget("text"))

    def test_graph_x_axis_runs_oldest_to_newest(self):
        self.app.graph_category_var.set("Fighter")
        self.app.graph_var.set("Total Kills Trend")
        self.app.refresh_graph()

        xs = [x for x, _ in self.app.chart._points]
        self.assertEqual(xs, sorted(xs), "tours must plot left to right in order")

    def test_thin_data_explains_itself_instead_of_drawing_one_dot(self):
        """A single tour can't be a trend - the chart should say so."""
        self.app.gameid_entry.delete(0, "end")
        self.app.gameid_entry.insert(0, "zzzz-no-such-pilot")
        try:
            self.app.graph_category_var.set("Fighter")
            self.app.graph_var.set("Kill/Death Trend")
            self.app.refresh_graph()
            self.assertEqual(self.app.chart._points, [])
            self.assertIn("No Fighter data", self.app.graph_status_label.cget("text"))
        finally:
            self.app.gameid_entry.delete(0, "end")
            self.app.gameid_entry.insert(0, self.PILOT)

    # -- arena scoping -----------------------------------------------------

    def test_arena_picker_scopes_every_view(self):
        self.app.arena_var.set(ARENA)
        self.app.on_arena_changed()
        scoped = len(self.app.category_grid.visible_rows())

        self.app.arena_var.set("All")
        self.app.on_arena_changed()
        everything = len(self.app.category_grid.visible_rows())

        self.assertGreaterEqual(everything, scoped)
        self.assertGreater(everything, 0)

    # -- views needing a fetch we deliberately don't perform ---------------

    def test_fetch_only_views_start_empty(self):
        """Squad and Arena Planes need a live fetch; offline they must be
        empty and say so rather than showing stale or bogus rows."""
        self.assertEqual(self.app.squad_grid.visible_rows(), [])
        self.assertEqual(self.app.arena_grid.visible_rows(), [])

    # -- build identification -----------------------------------------------

    def test_window_title_carries_the_version(self):
        """A screenshot should identify the build it came from."""
        self.assertIn(__version__, self.app.title())

    def test_masthead_shows_the_version(self):
        found = self._find_labels_containing(self.app, f"v{__version__}")
        self.assertTrue(found, f"no masthead label showing v{__version__}")

    def _find_labels_containing(self, widget, text):
        """Walk the widget tree looking for a label with this text - the
        masthead labels aren't stored on the App, so find them live."""
        matches = []
        for child in widget.winfo_children():
            try:
                value = child.cget("text")
            except Exception:
                value = None
            if isinstance(value, str) and text in value:
                matches.append(value)
            matches.extend(self._find_labels_containing(child, text))
        return matches

    # -- exports ------------------------------------------------------------

    def test_exports_write_real_content(self):
        """Exercised directly - the buttons open a save dialog that would
        block a headless run."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tours.csv"
            export.export_pilot_tours_csv(self.db, self.PILOT, STYPE, csv_path)
            self.assertGreater(csv_path.stat().st_size, 0)
            self.assertIn(",", csv_path.read_text(encoding="utf-8").splitlines()[0])

            planes_path = Path(tmp) / "planes.csv"
            export.export_pilot_plane_kills_csv(self.db, self.PILOT, planes_path)
            self.assertTrue(planes_path.exists())

            html_path = Path(tmp) / "report.html"
            export.export_html_report(self.db, self.PILOT, STYPE, html_path)
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("<html", html.lower())
            self.assertNotIn("http://", html.split("<body")[0], "report must be self-contained")


class SteelySmokeTest(PilotSmokeTests, unittest.TestCase):
    """A long, patchy career: 226 Melee tours, 74 of them never flown."""

    PILOT = "Steely"


class EaglerSmokeTest(PilotSmokeTests, unittest.TestCase):
    """A second, independently-shaped career, so the assertions can't
    quietly encode one pilot's habits as if they were the rules."""

    PILOT = "Eagler"


if __name__ == "__main__":
    unittest.main(verbosity=2)
