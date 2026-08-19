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

from ahstats import __version__, export, sync
from ahstats.db import CATEGORY_LABELS, DEFAULT_DB_PATH, StatsDB, tour_number
from tests import gui_fixture

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

        # One App for the whole session, pointed at this pilot - see
        # tests/gui_fixture.py for why it isn't built per class.
        cls.app = gui_fixture.get_app()
        gui_fixture.reset(cls.app, cls.PILOT, STYPE, ARENA)
        cls.db = cls.app.db

    def setUp(self):
        # Each test starts from the same known selection. The App is
        # shared across classes now, so the pilot is reset here too - the
        # other class points it somewhere else.
        gui_fixture.reset(self.app, self.PILOT, STYPE, ARENA)

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

    def test_model_picker_offers_every_plane_in_the_cache(self):
        """The A6M3 report: an aircraft in the database has to be in the
        picker. A Tk option menu of this length is taller than the screen
        and silently drops the entries that don't fit."""
        planes = self.db.get_matrix_planes(self.PILOT, arena=ARENA)
        if not planes:
            self.skipTest("no plane matrix cached - run the backfill")

        self.app.planes_scope_var.set("By Model")
        self.app.on_planes_scope_changed()
        self.app.planes_model_dropdown.open()
        self.app.planes_model_dropdown._refilter()
        try:
            self.assertEqual(self.app.planes_model_dropdown._filtered, planes)
        finally:
            self.app.planes_model_dropdown.close()

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

    # -- pre-split Main Arena tours ----------------------------------------

    def test_melee_scope_reaches_the_pre_split_main_arena_tours(self):
        """Through Tour 92 the Main Arena's ids carry no prefix. They were
        once filed under an arena no picker could select, which hid them
        from every view; selecting Melee (MA) must reach them."""
        self.app.arena_var.set(ARENA)
        self.app.on_arena_changed()

        cached = {row["tourid"] for row in self.db.get_tours()}
        pre_split = {t for t in cached if t.startswith("Tour")}
        if not pre_split:
            self.skipTest("no pre-93 tours in the cache at all")

        reachable = {row["tourid"] for row in self.db.get_tours(arena=ARENA)}
        self.assertTrue(
            pre_split <= reachable,
            f"{len(pre_split - reachable)} pre-93 tour(s) are cached but "
            f"unreachable under {ARENA}",
        )

    def test_era_column_marks_pre_split_tours_and_only_those(self):
        self.app.arena_var.set(ARENA)
        self.app.category_var.set("Fighter")
        self.app.category_view_var.set("Stats")
        self.app.refresh_category()

        columns = self.app.category_grid.columns
        self.assertIn("Era", columns)
        tour_index, era_index = columns.index("Tour"), columns.index("Era")

        rows = self.app.category_grid.visible_rows()
        self.assertTrue(rows, "no cached rows to check")
        for row in rows:
            with self.subTest(tour=row[tour_index]):
                # Every row in this grid is a Melee (MA) tour; the era is
                # what says which side of the tour-93 split it sits on.
                expected = "Main Arena" if int(row[tour_index]) <= 92 else ""
                self.assertEqual(row[era_index], expected)

    # -- sync range ---------------------------------------------------------

    def test_tour_range_accepts_a_span_however_it_is_entered(self):
        self.app.range_from_entry.delete(0, "end")
        self.app.range_to_entry.delete(0, "end")
        self.app.range_from_entry.insert(0, "21")
        self.app.range_to_entry.insert(0, "92")
        self.assertEqual(self.app._parse_tour_range(), (21, 92))

        # Entered backwards is an obvious slip, not an error.
        self.app.range_from_entry.delete(0, "end")
        self.app.range_to_entry.delete(0, "end")
        self.app.range_from_entry.insert(0, "92")
        self.app.range_to_entry.insert(0, "21")
        self.assertEqual(self.app._parse_tour_range(), (21, 92))

    def test_sync_mode_switching_shows_the_right_controls(self):
        for mode, expected in (
            ("Tour Range", "Sync Tour Range"),
            ("Single Tour", "Sync This Tour"),
            ("Full History", "Sync Full History"),
        ):
            with self.subTest(mode=mode):
                self.app.sync_mode_var.set(mode)
                self.app.on_sync_mode_changed()
                self.assertEqual(self.app.sync_btn.cget("text"), expected)
                range_shown = bool(self.app.range_from_entry.winfo_manager())
                self.assertEqual(range_shown, mode == "Tour Range")
        self.app.sync_mode_var.set("Full History")
        self.app.on_sync_mode_changed()

    def test_single_tour_picker_is_loaded_before_anything_is_synced(self):
        """v1.1.0: the sync bar's tour picker was only filled by a sync
        or an arena change, so on a normal launch its dropdown arrow
        opened an empty list. It's built from the cache at startup now."""
        cached = list(self.app.db.get_tours(arena=self.app._selected_arena()))
        picker = self.app.single_tour_dropdown
        self.assertEqual(len(picker._values), len(cached))
        self.assertTrue(picker._values, "the test pilot's cache has tours")
        picker.open()
        self.addCleanup(picker.close)
        self.assertIsNotNone(picker._popup, "the arrow must open a list")

    def test_a_typed_tour_is_the_tour_that_gets_synced(self):
        """v1.1.0: typing a tour into the sync box was ignored and the
        newest tour synced instead."""
        picker = self.app.single_tour_dropdown
        oldest = picker._values[-1]
        picker.entry.delete(0, "end")
        picker.entry.insert(0, oldest)
        self.assertEqual(picker.get(), oldest)
        self.assertEqual(
            self.app._tour_label_to_id.get(picker.get()),
            self.app._tour_label_to_id[oldest],
        )

    # -- sync progress ------------------------------------------------------

    def _progress_line(self) -> str:
        self.app._tick_progress()
        return self.app.progress_detail_label.cget("text")

    def test_progress_line_reports_position_and_percent(self):
        self.app._start_progress(200)
        self.addCleanup(self.app._stop_progress)
        self.app._progress_current = 50

        line = self._progress_line()
        self.assertIn("tour 50 of 200", line)
        self.assertIn("25%", line)

    def test_progress_keeps_moving_between_fetches(self):
        """The whole point of the ticker: fetches land every 3 seconds,
        so the line has to change on its own in between or the app looks
        hung. Nothing here touches the network - it re-reads the clock."""
        self.app._start_progress(200)
        self.addCleanup(self.app._stop_progress)
        self.app._progress_current = 50

        first = self._progress_line()
        self.app._progress_started_at -= 5  # 5 seconds pass, no fetch completes
        second = self._progress_line()

        self.assertNotEqual(first, second, "the line went stale between fetches")
        self.assertIn("00:00:05", second)
        self.assertIn("tour 50 of 200", second, "position should not have moved")

    def test_spinner_advances_on_every_tick(self):
        self.app._start_progress(10)
        self.addCleanup(self.app._stop_progress)
        frames = {self._progress_line()[0] for _ in range(4)}
        self.assertGreater(len(frames), 1, "spinner is not animating")

    def test_estimate_waits_for_a_measured_rate(self):
        """One tour in isn't a rate worth quoting."""
        self.app._start_progress(100)
        self.addCleanup(self.app._stop_progress)

        self.app._progress_current = 1
        self.assertNotIn("left", self._progress_line())

        self.app._progress_current = 2
        self.assertIn("left", self._progress_line())

    def test_estimate_is_measured_not_assumed(self):
        """10 tours in 100 seconds is 10s each - slower than the 3s rate
        limit floor, because HiTech's response time sits on top of it. The
        estimate must reflect what actually happened, not the floor."""
        self.app._start_progress(110)
        self.addCleanup(self.app._stop_progress)
        self.app._progress_current = 10
        self.app._progress_started_at -= 100

        # 100 remaining at 10s each = 1000s = 00:16:40
        self.assertIn("00:16:40", self._progress_line())

    def test_stopping_cancels_the_ticker(self):
        self.app._start_progress(10)
        self.app._stop_progress("all done")

        self.assertIsNone(self.app._progress_tick_id)
        self.assertIsNone(self.app._progress_started_at)
        self.assertEqual(self.app.progress_detail_label.cget("text"), "all done")

    def test_starting_twice_does_not_stack_tickers(self):
        self.app._start_progress(10)
        self.addCleanup(self.app._stop_progress)
        first = self.app._progress_tick_id
        self.app._start_progress(20)

        self.assertEqual(self.app._progress_tick_id, first, "a second ticker was scheduled")
        self.assertEqual(self.app._progress_total, 20, "counters should still have been reset")

    def test_queued_progress_moves_the_bar(self):
        """The sync thread publishes through the queue; the poller is what
        turns that into a bar position."""
        self.app._start_progress(100)
        self.addCleanup(self.app._stop_progress)

        self.app.progress_queue.put(sync.SyncProgress(25, 100, "Fetching Melee Tour 300..."))
        self.app._poll_queue()
        self.app.after_cancel(self.app._poll_after_id)  # don't leave two pollers running

        self.assertAlmostEqual(self.app.progress_bar.get(), 0.25, places=2)
        self.assertEqual(self.app._progress_current, 25)
        self.assertIn("Melee Tour 300", self.app.status_label.cget("text"))

    # -- identity group editor ---------------------------------------------

    TEST_GROUP = "__ahstats_test_group__"

    def _open_group_editor(self):
        """The dialog's widgets are built in local scope, so reach them
        the way a user would - by walking the window that just opened."""
        before = set(self.app.winfo_children())
        self.app.on_manage_groups_clicked()
        dialog = next(w for w in self.app.winfo_children() if w not in before)
        dialog.update()  # let it map, so its widgets can take focus
        self.addCleanup(dialog.destroy)
        self.addCleanup(self.app.db.delete_identity_group, self.TEST_GROUP, STYPE)
        return dialog

    @staticmethod
    def _descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from PilotSmokeTests._descendants(child)

    def _find(self, dialog, cls_name, text=None):
        for widget in self._descendants(dialog):
            if type(widget).__name__ != cls_name:
                continue
            if text is None:
                return widget
            try:
                if widget.cget("text") == text:
                    return widget
            except Exception:
                continue
        raise AssertionError(f"no {cls_name} {'named ' + repr(text) if text else ''} in the dialog")

    def test_group_editor_saves_more_than_ten_ids(self):
        """Reported as a limit of ten. There is none - the old one-line
        editor just scrolled the earlier names out of sight."""
        dialog = self._open_group_editor()
        ids = [f"Pilot{n:02d}" for n in range(15)]

        self._find(dialog, "CTkEntry").insert(0, self.TEST_GROUP)
        self._find(dialog, "CTkTextbox").insert("1.0", "\n".join(ids))
        self._find(dialog, "CTkButton", "Save").invoke()

        self.assertEqual(
            sorted(self.app.db.get_identity_group_members(self.TEST_GROUP, STYPE)),
            sorted(ids),
        )

    def test_group_editor_shows_the_id_count(self):
        """The count is how a user sees that nothing was truncated, which
        is the whole complaint this editor was rebuilt to answer."""
        dialog = self._open_group_editor()
        box = self._find(dialog, "CTkTextbox")
        box.insert("1.0", "MDJOE\nFugitive\nSnuggie")

        # CTkTextbox forwards bind() to the Tk Text it wraps, so the
        # keystroke has to be delivered there rather than to the wrapper.
        # It also needs the focus and a keysym: Tk routes key events to the
        # focused widget, and a bare <KeyRelease> with no key isn't a
        # complete enough event to dispatch - it silently does nothing.
        box._textbox.focus_force()
        box._textbox.event_generate("<KeyRelease>", keysym="a", when="now")
        dialog.update()

        self.assertTrue(
            self._find_labels_containing(dialog, "3 game ID(s)"),
            "the editor should say how many IDs it holds",
        )
        self.assertTrue(
            self._find_labels_containing(dialog, "no limit"),
            "the editor should say outright that there is no cap",
        )

    def test_group_editor_refuses_a_group_of_one(self):
        """A group combining a single ID is just that ID - saving it would
        only add a confusing entry to the Career View picker."""
        dialog = self._open_group_editor()
        self._find(dialog, "CTkEntry").insert(0, self.TEST_GROUP)
        self._find(dialog, "CTkTextbox").insert("1.0", "MDJOE")
        self._find(dialog, "CTkButton", "Save").invoke()

        self.assertEqual(self.app.db.get_identity_group_members(self.TEST_GROUP, STYPE), [])

    def test_saved_group_appears_in_the_career_view_picker(self):
        dialog = self._open_group_editor()
        self._find(dialog, "CTkEntry").insert(0, self.TEST_GROUP)
        self._find(dialog, "CTkTextbox").insert("1.0", "MDJOE\nFugitive")
        self._find(dialog, "CTkButton", "Save").invoke()

        self.addCleanup(self.app.identity_view_var.set, "Single ID")
        self.addCleanup(self.app.refresh_identity_view_dropdown)
        self.assertIn(self.TEST_GROUP, self.app.identity_view_dropdown.cget("values"))

    def test_active_group_makes_queries_span_its_members(self):
        """`_effective_gameid()` is what turns a group into the list of
        ids every view then queries by."""
        self.app.db.save_identity_group(self.TEST_GROUP, STYPE, ["MDJOE", "Fugitive"])
        self.addCleanup(self.app.db.delete_identity_group, self.TEST_GROUP, STYPE)
        self.app.refresh_identity_view_dropdown()

        self.app.identity_view_var.set(self.TEST_GROUP)
        self.addCleanup(self.app.identity_view_var.set, "Single ID")

        self.assertEqual(sorted(self.app._effective_gameid()), ["Fugitive", "MDJOE"])

        self.app.identity_view_var.set("Single ID")
        self.assertEqual(self.app._effective_gameid(), self.PILOT)

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

