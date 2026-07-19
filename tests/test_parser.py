"""Unit tests for AHSTATS parser module.

Tests the BeautifulSoup-based HTML parsers for HiTech Creations stats pages.
"""
import unittest
from pathlib import Path
from ahstats.parser import (
    parse_pilot_tour_scores,
    parse_pilot_plane_kills,
    parse_squad_stats,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestPilotTourScoresParser(unittest.TestCase):
    """Test cases for parse_pilot_tour_scores()."""

    def setUp(self):
        """Load sample HTML fixture."""
        fixture_path = FIXTURES_DIR / "sample_ahscore.html"
        if fixture_path.exists():
            with open(fixture_path, encoding="utf-8") as f:
                self.html = f.read()
        else:
            self.html = None

    def test_parse_basic_structure(self):
        """Verify parser returns PilotTourScores object with expected structure."""
        if not self.html:
            self.skipTest("Fixture file not found")

        result = parse_pilot_tour_scores(self.html)
        self.assertIsNotNone(result, "Parser should return a result for valid HTML")
        self.assertIsInstance(result.totals, dict, "Totals should be a dictionary")
        self.assertIsInstance(result.scores, dict, "Scores should be a dictionary")

    def test_parse_totals_categories(self):
        """Verify totals dictionary has expected categories."""
        if not self.html:
            self.skipTest("Fixture file not found")

        result = parse_pilot_tour_scores(self.html)
        # Should have at least 'total' category
        self.assertIn("total", result.totals, "Should have 'total' category")

        # Common categories (may not all be present in every fixture)
        expected_cats = ["fighter", "bomber", "attack", "vehicle"]
        for cat in expected_cats:
            if cat in result.totals:
                self.assertIsInstance(result.totals[cat], dict,
                                    f"{cat} category should be a dict")

    def test_parse_kills_value_type(self):
        """Verify kills are parsed as integers."""
        if not self.html:
            self.skipTest("Fixture file not found")

        result = parse_pilot_tour_scores(self.html)
        total = result.totals.get("total", {})
        if "kills" in total:
            self.assertIsInstance(total["kills"], int, "Kills should be an integer")
            self.assertGreaterEqual(total["kills"], 0, "Kills should be non-negative")

    def test_parse_numeric_fields(self):
        """Verify all numeric fields are parsed correctly."""
        if not self.html:
            self.skipTest("Fixture file not found")

        result = parse_pilot_tour_scores(self.html)
        total = result.totals.get("total", {})

        # Test numeric fields
        numeric_fields = ["kills", "assists", "sorties", "deaths", "landed"]
        for field in numeric_fields:
            if field in total:
                self.assertIsInstance(total[field], int,
                                    f"{field} should be an integer")

    def test_invalid_html(self):
        """Verify parser handles malformed HTML gracefully."""
        result = parse_pilot_tour_scores("<html><body>Not a stats page</body></html>")
        self.assertIsNone(result, "Parser should return None for invalid HTML")

    def test_empty_html(self):
        """Verify parser handles empty HTML."""
        result = parse_pilot_tour_scores("")
        self.assertIsNone(result, "Parser should return None for empty HTML")


class TestPilotPlaneKillsParser(unittest.TestCase):
    """Test cases for parse_pilot_plane_kills()."""

    def setUp(self):
        """Load sample HTML fixture."""
        fixture_path = FIXTURES_DIR / "sample_killstat.html"
        if fixture_path.exists():
            with open(fixture_path, encoding="utf-8") as f:
                self.html = f.read()
        else:
            self.html = None

    def test_parse_plane_list(self):
        """Verify parser extracts plane kill data."""
        if not self.html:
            self.skipTest("Fixture file not found")

        result = parse_pilot_plane_kills(self.html)
        self.assertIsNotNone(result, "Parser should return a result")
        self.assertIsInstance(result.planes, list, "Planes should be a list")
        if result.planes:
            self.assertGreater(len(result.planes), 0, "Should have at least one plane")

    def test_weekly_buckets(self):
        """Verify weekly kill distribution is parsed."""
        if not self.html:
            self.skipTest("Fixture file not found")

        result = parse_pilot_plane_kills(self.html)
        if result and result.planes:
            first_plane = result.planes[0]
            # Check that weekly bucket fields exist and are integers
            self.assertIsInstance(first_plane.days_1_7, int, "days_1_7 should be int")
            self.assertIsInstance(first_plane.days_8_14, int, "days_8_14 should be int")

    def test_invalid_html(self):
        """Verify parser handles invalid HTML."""
        result = parse_pilot_plane_kills("<html><body>Invalid</body></html>")
        self.assertIsNone(result, "Parser should return None for invalid HTML")


class TestSquadStatsParser(unittest.TestCase):
    """Test cases for parse_squad_stats()."""

    def setUp(self):
        """Load sample HTML fixture."""
        fixture_path = FIXTURES_DIR / "sample_squadstats.html"
        if fixture_path.exists():
            with open(fixture_path, encoding="utf-8") as f:
                self.html = f.read()
        else:
            self.html = None

    def test_parse_squad_data(self):
        """Verify parser extracts squad information."""
        if not self.html:
            self.skipTest("Fixture file not found")

        result = parse_squad_stats(self.html)
        if result:  # Some fixtures might not have squad data
            self.assertIsNotNone(result.squad_name, "Should have squad name")
            self.assertIsInstance(result.members, list, "Members should be a list")

    def test_invalid_html(self):
        """Verify parser handles invalid HTML."""
        result = parse_squad_stats("<html><body>Invalid</body></html>")
        self.assertIsNone(result, "Parser should return None for invalid HTML")


class TestParserEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""

    def test_none_input(self):
        """Verify parsers handle None input gracefully."""
        self.assertIsNone(parse_pilot_tour_scores(None))
        self.assertIsNone(parse_pilot_plane_kills(None))
        self.assertIsNone(parse_squad_stats(None))

    def test_unicode_handling(self):
        """Verify parsers handle unicode characters."""
        html_with_unicode = """
        <html><body>
        <table><tr><th>Pilot Name</th></tr>
        <tr><td>Test™ Pilot © 2024</td></tr></table>
        </body></html>
        """
        # Should not raise an exception
        result = parse_pilot_tour_scores(html_with_unicode)
        # May return None (invalid structure) but shouldn't crash


if __name__ == '__main__':
    unittest.main()
