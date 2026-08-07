"""SearchableSelect, the type-to-filter dropdown behind the tour pickers.

Needs a Tk display, so the whole module skips without one - same bargain
the GUI smoke suite makes. No cached data required: the widget is fed
made-up tour labels, which keeps these tests meaningful on a fresh
checkout.

The labels below are shaped like the real ones on purpose. "Tour 21"
being a substring of "Melee Tour 219" is the whole reason the ranking
exists, and a set of tidy fake values wouldn't exercise it.

The three families are real too: one arena's tour list spans all of
them, because HiTech's labels changed twice. The Melee arena today holds
"Melee Tour 319" back to 201, "Late War Tour 200" back to 93, and plain
"Tour 92" back to 12 - the same career under three names.
"""
from __future__ import annotations

import unittest

from tests import gui_fixture

TOUR_LABELS = (
    ["Melee Tour %d" % n for n in range(319, 200, -1)]     # since the rename
    + ["Late War Tour %d" % n for n in range(200, 92, -1)]  # 2007 split to rename
    + ["Tour %d" % n for n in range(92, 11, -1)]            # pre-split Main Arena
)

_root = None


def setUpModule():
    """Parent the widgets to the session's shared root rather than making
    another one - see tests/gui_fixture.py."""
    global _root
    _root = gui_fixture.get_app()


class SearchableSelectTests(unittest.TestCase):
    def setUp(self):
        from ahstats.picker import SearchableSelect

        self.chosen: list[str] = []
        self.widget = SearchableSelect(
            _root, values=TOUR_LABELS, command=self.chosen.append
        )

    def tearDown(self):
        self.widget.close()
        self.widget.destroy()

    def _filter(self, text: str) -> list[str]:
        self.widget.open()
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, text)
        self.widget._refilter()
        return self.widget._filtered

    # -- ranking ------------------------------------------------------

    def test_exact_match_outranks_the_tours_that_merely_contain_it(self):
        """Typing a tour number must find that tour, not the 21x range
        that happens to contain those digits."""
        results = self._filter("Tour 21")
        self.assertEqual(results[0], "Tour 21")
        self.assertIn("Melee Tour 219", results, "substring matches should still be offered")

    def test_ranking_is_case_insensitive(self):
        self.assertEqual(self._filter("tour 92")[0], "Tour 92")

    def test_prefix_matches_come_before_matches_further_in(self):
        results = self._filter("Melee Tour 3")
        self.assertTrue(
            all(r.startswith("Melee Tour 3") for r in results),
            "only the 3xx Melee tours contain that string",
        )

    def test_order_within_a_tier_stays_newest_first(self):
        results = [r for r in self._filter("Melee Tour 31") if r.startswith("Melee")]
        self.assertEqual(results, ["Melee Tour 31%d" % n for n in range(9, -1, -1)])

    # -- matching on the tour number ----------------------------------
    #
    # These pin the bug The Fugitive reported against v1.1.1: whatever
    # you typed, Single Tour sync fetched the newest tour. Both halves of
    # it come from one arena carrying three families of label - "Melee
    # Tour 319", "Late War Tour 147", "Tour 47" - so the arena words a
    # player types rarely match the tour they want. Drop the tour-number
    # tier out of _match_rank() and every test here fails.

    def test_a_bare_number_finds_that_tour_first(self):
        """"47" is a substring of Tour 47, Late War Tour 147 and Melee
        Tour 247. Newest-first order offered 247, so Enter synced it."""
        results = self._filter("47")
        self.assertEqual(results[0], "Tour 47")
        self.assertIn("Melee Tour 247", results, "the others are still on offer")

    def test_a_bare_number_beats_the_same_digits_further_in(self):
        self.assertEqual(self._filter("92")[0], "Tour 92")
        self.assertEqual(self._filter("93")[0], "Late War Tour 93")
        self.assertEqual(self._filter("300")[0], "Melee Tour 300")

    def test_the_wrong_arena_word_still_finds_the_tour(self):
        """The box starts filled in with "Melee Tour 319", so editing
        just the number is the obvious move - and for the 189 tours in
        this arena that HiTech labelled otherwise, it matched nothing."""
        self.assertEqual(self._filter("Melee Tour 47")[0], "Tour 47")
        self.assertEqual(self._filter("Melee Tour 147")[0], "Late War Tour 147")

    def test_editing_the_number_in_place_selects_that_tour(self):
        self.widget._choose("Melee Tour 319")
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, "Melee Tour 47")
        self.assertEqual(self.widget.get(), "Tour 47")

    def test_an_exact_label_still_wins_over_its_number(self):
        """"Tour 21" typed in full is Tour 21, not the 21x range."""
        self.assertEqual(self._filter("Tour 21")[0], "Tour 21")

    def test_a_number_no_tour_has_matches_nothing(self):
        self.assertEqual(self._filter("Tour 9999"), [])

    def test_a_filter_matching_nothing_yields_nothing(self):
        self.assertEqual(self._filter("Halibut"), [])

    def test_empty_filter_shows_everything(self):
        self.widget.open()
        self.widget.entry.delete(0, "end")
        self.widget._refilter()
        self.assertEqual(len(self.widget._filtered), len(TOUR_LABELS))

    # -- popup --------------------------------------------------------

    def test_open_and_close(self):
        self.widget.open()
        self.assertIsNotNone(self.widget._popup)
        self.widget.close()
        self.assertIsNone(self.widget._popup)

    def test_opening_with_no_values_is_harmless(self):
        from ahstats.picker import SearchableSelect

        empty = SearchableSelect(_root, values=[])
        try:
            empty.open()
            self.assertIsNone(empty._popup, "an empty dropdown has nothing to show")
        finally:
            empty.destroy()

    def test_choosing_closes_the_popup_and_reports_the_value(self):
        self.widget.open()
        self.widget._choose("Tour 47")
        self.assertIsNone(self.widget._popup)
        self.assertEqual(self.widget.get(), "Tour 47")
        self.assertEqual(self.chosen, ["Tour 47"])

    def test_enter_takes_the_top_ranked_match(self):
        self._filter("Tour 21")
        self.widget._on_return(None)
        self.assertEqual(self.widget.get(), "Tour 21")

    def test_entry_mirrors_the_selection_once_the_popup_closes(self):
        self.widget.open()
        self.widget._choose("Melee Tour 300")
        self.assertEqual(self.widget.entry.get(), "Melee Tour 300")

    # -- typing without picking ---------------------------------------
    #
    # These pin the bug a player reported in v1.1.0: the box would take
    # your typing but sync the newest tour anyway. The variable only
    # moved when a value was *chosen* from the list, and the sync read
    # the variable, so a fully typed tour name was thrown away. Delete
    # the commit_typed() call in get() and every test here fails.

    def test_typed_text_becomes_the_selection_when_read(self):
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, "Tour 47")
        self.assertEqual(self.widget.get(), "Tour 47")

    def test_typed_text_wins_over_a_previous_selection(self):
        self.widget._choose("Melee Tour 318")
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, "Tour 47")
        self.assertEqual(self.widget.get(), "Tour 47")
        self.assertEqual(self.chosen[-1], "Tour 47")

    def test_typed_text_is_ranked_like_the_filtered_list(self):
        """"Tour 21" typed in full must not resolve to Melee Tour 219."""
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, "Tour 21")
        self.assertEqual(self.widget.get(), "Tour 21")

    def test_text_matching_nothing_leaves_the_selection_alone(self):
        self.widget._choose("Tour 47")
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, "Halibut")
        self.assertEqual(self.widget.get(), "Tour 47")
        self.assertEqual(self.widget.entry.get(), "Tour 47", "the entry snaps back")

    def test_typing_then_clicking_away_still_selects(self):
        """The click that dismisses the popup is usually the one on the
        Fetch button, so the typing has to survive it."""
        self.widget.open()
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, "Tour 47")
        self.widget._refilter()
        self.widget.commit_typed()
        self.assertIsNone(self.widget._popup)
        self.assertEqual(self.widget.get(), "Tour 47")

    def test_enter_with_the_popup_closed_selects(self):
        self.widget.entry.delete(0, "end")
        self.widget.entry.insert(0, "Tour 47")
        self.widget._on_return(None)
        self.assertEqual(self.widget.get(), "Tour 47")

    def test_an_emptied_box_keeps_the_current_selection(self):
        self.widget._choose("Tour 47")
        self.widget.entry.delete(0, "end")
        self.assertEqual(self.widget.get(), "Tour 47")

    # -- reloading ----------------------------------------------------

    def test_configure_replaces_the_value_list(self):
        self.widget.configure(values=["Melee Tour 318"])
        self.assertEqual(self._filter("Melee"), ["Melee Tour 318"])

    # -- the box itself -----------------------------------------------

    def test_an_empty_result_says_so_rather_than_showing_nothing(self):
        from ahstats.picker import NO_MATCH_ROW

        self._filter("Halibut")
        self.assertEqual(self.widget._listbox.get(0, "end"), (NO_MATCH_ROW,))

    def test_clicking_the_no_match_row_picks_nothing(self):
        self.widget._choose("Tour 47")
        self._filter("Halibut")
        self.widget._listbox.selection_set(0)
        self.widget._on_pick(None)
        self.assertEqual(self.widget.get(), "Tour 47")

    def test_arriving_in_the_box_selects_what_is_in_it(self):
        """So the first keystroke replaces the tour rather than
        appending to it - typing "47" into a box already reading "Melee
        Tour 319" was how the wrong tour got synced."""
        self.widget._choose("Melee Tour 319")
        self.widget._on_focus_in(None)
        self.widget.update_idletasks()  # the select-all is deferred to idle
        self.assertEqual(self.widget.entry.selection_get(), "Melee Tour 319")

    def test_reloading_while_open_refilters_in_place(self):
        self.widget.open()
        self.widget.configure(values=["Tour 12", "Tour 13"])
        self.assertEqual(self.widget._filtered, ["Tour 12", "Tour 13"])


if __name__ == "__main__":
    unittest.main()

