"""Identity groups: several game IDs viewed as one career.

A player who flew as MDJOE and later as Fugitive has one continuous
history under two names, and a group is how the app puts it back
together. Offline - every test builds its own throwaway database, so
none of this touches the user's cache.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ahstats.db import StatsDB, parse_identity_ids


def _temp_db_path(name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix="ahstats_test_")) / name


class ParseIdentityIdsTests(unittest.TestCase):
    def test_one_per_line(self):
        self.assertEqual(parse_identity_ids("MDJOE\nFugitive"), ["MDJOE", "Fugitive"])

    def test_comma_separated(self):
        self.assertEqual(parse_identity_ids("MDJOE, Fugitive"), ["MDJOE", "Fugitive"])

    def test_mixed_separators_and_stray_whitespace(self):
        self.assertEqual(
            parse_identity_ids("  MDJOE ,Fugitive\n\n  Snuggie  \n"),
            ["MDJOE", "Fugitive", "Snuggie"],
        )

    def test_blank_input_yields_nothing(self):
        for raw in ("", "   ", "\n\n", " , , "):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(parse_identity_ids(raw), [])

    def test_order_is_preserved(self):
        """Players list their names chronologically; keep that order."""
        names = ["First", "Second", "Third", "Fourth"]
        self.assertEqual(parse_identity_ids("\n".join(names)), names)

    def test_exact_repeats_are_dropped(self):
        """The same id twice would break the insert - see the round-trip
        test below, which is the bug this prevents."""
        self.assertEqual(parse_identity_ids("MDJOE\nFugitive\nMDJOE"), ["MDJOE", "Fugitive"])

    def test_names_differing_only_in_case_are_both_kept(self):
        """Deliberately not deduplicated: this code has no business
        deciding two differently-spelled ids are the same pilot."""
        self.assertEqual(parse_identity_ids("Steely\nsteely"), ["Steely", "steely"])


class IdentityGroupStorageTests(unittest.TestCase):
    def setUp(self):
        self.db = StatsDB(_temp_db_path("groups.db"))

    def tearDown(self):
        self.db.close()

    def test_round_trip(self):
        self.db.save_identity_group("MyTotals", "pilot", ["MDJOE", "Fugitive"])
        self.assertEqual(
            sorted(self.db.get_identity_group_members("MyTotals", "pilot")),
            ["Fugitive", "MDJOE"],
        )
        self.assertEqual(self.db.get_identity_group_names("pilot"), ["MyTotals"])

    def test_a_duplicated_id_does_not_lose_the_group(self):
        """Reported as a crash: (group_name, stype, gameid) is the primary
        key, so listing a name twice used to fail the whole insert."""
        self.db.save_identity_group("MyTotals", "pilot", ["MDJOE", "Fugitive", "MDJOE"])
        self.assertEqual(
            sorted(self.db.get_identity_group_members("MyTotals", "pilot")),
            ["Fugitive", "MDJOE"],
        )

    def test_no_limit_on_how_many_ids_a_group_holds(self):
        """Reported as "groups seem to be limited to 10". There is no
        limit; the old single-line editor just hid the overflow."""
        for count in (10, 11, 15, 50):
            with self.subTest(count=count):
                ids = [f"Pilot{n:03d}" for n in range(count)]
                self.db.save_identity_group(f"Group{count}", "pilot", ids)
                self.assertEqual(
                    sorted(self.db.get_identity_group_members(f"Group{count}", "pilot")),
                    sorted(ids),
                )

    def test_saving_again_replaces_the_membership(self):
        self.db.save_identity_group("MyTotals", "pilot", ["MDJOE", "Fugitive"])
        self.db.save_identity_group("MyTotals", "pilot", ["Fugitive", "Snuggie"])
        self.assertEqual(
            sorted(self.db.get_identity_group_members("MyTotals", "pilot")),
            ["Fugitive", "Snuggie"],
        )

    def test_blank_entries_are_ignored(self):
        self.db.save_identity_group("MyTotals", "pilot", ["MDJOE", "  ", "", "Fugitive"])
        self.assertEqual(
            sorted(self.db.get_identity_group_members("MyTotals", "pilot")),
            ["Fugitive", "MDJOE"],
        )

    def test_pilot_and_squad_groups_are_separate_namespaces(self):
        self.db.save_identity_group("MyTotals", "pilot", ["MDJOE", "Fugitive"])
        self.db.save_identity_group("MyTotals", "squad", ["Rolling Thunder", "The Few"])

        self.assertEqual(len(self.db.get_identity_group_members("MyTotals", "pilot")), 2)
        self.assertIn("Rolling Thunder", self.db.get_identity_group_members("MyTotals", "squad"))
        self.assertNotIn("MDJOE", self.db.get_identity_group_members("MyTotals", "squad"))

    def test_delete_removes_only_the_named_group(self):
        self.db.save_identity_group("MyTotals", "pilot", ["MDJOE", "Fugitive"])
        self.db.save_identity_group("Wingmen", "pilot", ["Lusche", "Steely"])

        self.db.delete_identity_group("MyTotals", "pilot")

        self.assertEqual(self.db.get_identity_group_names("pilot"), ["Wingmen"])
        self.assertEqual(self.db.get_identity_group_members("MyTotals", "pilot"), [])

    def test_delete_leaves_the_other_stype_alone(self):
        self.db.save_identity_group("MyTotals", "pilot", ["MDJOE", "Fugitive"])
        self.db.save_identity_group("MyTotals", "squad", ["The Few", "Rolling Thunder"])

        self.db.delete_identity_group("MyTotals", "pilot")

        self.assertEqual(self.db.get_identity_group_names("pilot"), [])
        self.assertEqual(self.db.get_identity_group_names("squad"), ["MyTotals"])

    def test_unknown_group_reads_back_empty_rather_than_raising(self):
        self.assertEqual(self.db.get_identity_group_members("NoSuchGroup", "pilot"), [])


class IdentityGroupQueryTests(unittest.TestCase):
    """A group's whole point is that queries sum across its members."""

    def setUp(self):
        self.db = StatsDB(_temp_db_path("group_queries.db"))

    def tearDown(self):
        self.db.close()

    def test_career_totals_accept_a_list_of_ids(self):
        """`_in_clause` builds `IN (?,?,...)` so every query method takes
        either one id or a group's worth. Long lists included - SQLite
        has a bound on host parameters and a career of name changes
        shouldn't come near it, but nor should it fail quietly."""
        for ids in (["MDJOE"], ["MDJOE", "Fugitive"], [f"Pilot{n}" for n in range(50)]):
            with self.subTest(count=len(ids)):
                # No cached rows for these ids: the point is that the
                # query builds and runs, not what it returns.
                self.assertIsNotNone(self.db.get_career_totals(ids, "pilot"))
                self.assertEqual(self.db.get_pilot_tourids(ids, "pilot"), set())


if __name__ == "__main__":
    unittest.main()
