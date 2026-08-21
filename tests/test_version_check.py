"""The update check, offline.

Nothing here touches the network: `fetch_latest_release` is stubbed, so
the suite still passes on a machine with no internet and never spends
one of GitHub's 60 anonymous calls an hour.
"""
from __future__ import annotations

import unittest

from ahstats import version_check as vc
from tests import gui_fixture


class TestParseVersion(unittest.TestCase):
    def test_accepts_the_shapes_a_tag_actually_takes(self):
        for text, expected in [
            ("v1.1.5", (1, 1, 5)),
            ("1.1.5", (1, 1, 5)),
            ("V2.0", (2, 0)),
            ("release-1.2.3-beta", (1, 2, 3)),
            ("7", (7,)),
        ]:
            with self.subTest(text=text):
                self.assertEqual(vc.parse_version(text), expected)

    def test_returns_none_when_there_is_no_version(self):
        for text in ("", None, "latest", "v"):
            with self.subTest(text=text):
                self.assertIsNone(vc.parse_version(text))


class TestIsNewer(unittest.TestCase):
    def test_ordering(self):
        self.assertTrue(vc.is_newer("1.1.6", "1.1.5"))
        self.assertTrue(vc.is_newer("1.2.0", "1.1.9"))
        self.assertTrue(vc.is_newer("2.0.0", "1.9.9"))
        self.assertFalse(vc.is_newer("1.1.5", "1.1.5"))
        self.assertFalse(vc.is_newer("1.1.4", "1.1.5"))

    def test_double_digit_parts_compare_numerically_not_as_text(self):
        # "1.10.0" < "1.9.0" as strings; the whole reason for the tuple.
        self.assertTrue(vc.is_newer("1.10.0", "1.9.0"))
        self.assertFalse(vc.is_newer("1.9.0", "1.10.0"))

    def test_short_versions_are_zero_padded(self):
        self.assertFalse(vc.is_newer("1.2", "1.2.0"))
        self.assertTrue(vc.is_newer("1.2.1", "1.2"))

    def test_unparseable_is_never_newer(self):
        # An odd tag must not nag the user forever.
        self.assertFalse(vc.is_newer("nightly", "1.1.5"))
        self.assertFalse(vc.is_newer("1.1.6", "nightly"))
        self.assertFalse(vc.is_newer(None, None))


class TestCheckForUpdate(unittest.TestCase):
    def setUp(self):
        self._real_fetch = vc.fetch_latest_release
        self.addCleanup(setattr, vc, "fetch_latest_release", self._real_fetch)

    def _stub(self, release):
        vc.fetch_latest_release = lambda timeout=None: release

    def test_reports_a_newer_release(self):
        self._stub(vc.Release("1.2.0", "https://example.invalid/1.2.0", "New"))
        found = vc.check_for_update("1.1.5")
        self.assertIsNotNone(found)
        self.assertEqual(found.version, "1.2.0")

    def test_silent_when_up_to_date_or_ahead(self):
        self._stub(vc.Release("1.1.5", "https://example.invalid/1.1.5"))
        self.assertIsNone(vc.check_for_update("1.1.5"))
        self.assertIsNone(vc.check_for_update("1.2.0"))

    def test_a_failed_fetch_is_not_an_error(self):
        # No network, GitHub down, rate-limited: all the same answer.
        self._stub(None)
        self.assertIsNone(vc.check_for_update("1.1.5"))

    def test_background_check_never_calls_back_when_up_to_date(self):
        self._stub(None)
        calls = []
        vc.check_in_background(calls.append, "1.1.5").join(timeout=5)
        self.assertEqual(calls, [])

    def test_background_check_calls_back_with_the_release(self):
        release = vc.Release("9.9.9", "https://example.invalid/9.9.9")
        self._stub(release)
        calls = []
        vc.check_in_background(calls.append, "1.1.5").join(timeout=5)
        self.assertEqual(calls, [release])

    def test_a_raising_callback_does_not_kill_the_thread(self):
        self._stub(vc.Release("9.9.9", "https://example.invalid/9.9.9"))

        def boom(release):
            raise RuntimeError("GUI already gone")

        thread = vc.check_in_background(boom, "1.1.5")
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()


class UpdateBadgeTests(unittest.TestCase):
    """The notice itself: a masthead button, only packed once there is
    something newer, opening the release page and nothing else."""

    def setUp(self):
        self.app = gui_fixture.get_app()
        self.addCleanup(self.app.update_button.pack_forget)

    def test_hidden_until_there_is_an_update(self):
        # Nothing has reported one, so it must not be laid out at all.
        # winfo_manager rather than winfo_ismapped: the test window is
        # never actually shown, so nothing in it is ever "mapped".
        self.assertEqual(self.app.update_button.winfo_manager(), "")

    def test_shows_the_new_version(self):
        release = vc.Release("9.9.9", "https://example.invalid/9.9.9")
        self.app._show_update_notice(release)
        self.app.update_idletasks()
        self.assertIn("9.9.9", self.app.update_button.cget("text"))
        self.assertEqual(self.app.update_button.winfo_manager(), "pack")

    def test_the_button_opens_the_release_page_and_downloads_nothing(self):
        opened = []
        import webbrowser

        real = webbrowser.open
        webbrowser.open = opened.append
        self.addCleanup(setattr, webbrowser, "open", real)

        self.app._show_update_notice(vc.Release("9.9.9", "https://example.invalid/9.9.9"))
        self.app._open_release_page()
        self.assertEqual(opened, ["https://example.invalid/9.9.9"])
