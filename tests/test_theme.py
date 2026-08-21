"""The light/dark palette, the settings file, and the appearance switch.

The colour-pair and settings tests are offline and window-free. The
switch itself needs the shared App - it repaints real grids - so that
class uses tests/gui_fixture.py like the rest of the GUI suite, and puts
the mode back afterwards so it can't leak into another test's window.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import customtkinter as ctk

from ahstats import settings, theme
from tests import gui_fixture


class ColorPairTests(unittest.TestCase):
    """Every palette entry has to be a (light, dark) pair, or the light
    theme is silently half-applied: CTk widgets take a bare string
    happily and just show the same colour in both modes."""

    PALETTE = ("BG_DARK", "PANEL_BG", "PANEL_BG_ALT", "BORDER_GRAY", "TEXT_BODY",
               "TEXT_HEADING", "TEXT_MUTED", "TEXT_CREAM", "ACCENT_OLIVE",
               "ACCENT_OLIVE_HOVER", "ACCENT_GREEN", "ACCENT_GREEN_HOVER",
               "ACCENT_BLUE", "ACCENT_RED", "STATUS_WARNING", "STATUS_ERROR",
               "SELECT_FG")

    def test_every_colour_is_a_light_dark_pair(self):
        for name in self.PALETTE:
            with self.subTest(color=name):
                value = getattr(theme, name)
                self.assertIsInstance(value, tuple)
                self.assertEqual(len(value), 2)
                for half in value:
                    self.assertRegex(half, r"^#[0-9a-fA-F]{6}$")

    def test_color_picks_the_half_matching_the_mode(self):
        original = theme.get_mode()
        self.addCleanup(ctk.set_appearance_mode, original)

        ctk.set_appearance_mode("Light")
        self.assertEqual(theme.color(theme.PANEL_BG), theme.PANEL_BG[0])
        ctk.set_appearance_mode("Dark")
        self.assertEqual(theme.color(theme.PANEL_BG), theme.PANEL_BG[1])

    def test_color_passes_a_flat_string_through(self):
        # Call sites shouldn't have to know which kind they hold.
        self.assertEqual(theme.color("#123456"), "#123456")

    def test_light_and_dark_are_actually_different(self):
        # Olive is deliberately identical in both - it's the masthead
        # identity - so it's excluded. Everything else must move.
        for name in self.PALETTE:
            if name.startswith("ACCENT_OLIVE"):
                continue
            with self.subTest(color=name):
                light, dark = getattr(theme, name)
                self.assertNotEqual(light, dark)


class ThemeJsonTests(unittest.TestCase):
    """The customtkinter theme file is where the CTk widgets get their
    light halves. A bare string there means that widget ignores the
    light theme entirely."""

    def test_widget_colours_carry_both_modes(self):
        data = json.loads(Path(theme.THEME_JSON_PATH).read_text(encoding="utf-8"))
        for widget, options in data.items():
            if widget == "CTkFont":
                continue
            for option, value in options.items():
                if not option.endswith("color") or value == "transparent":
                    continue
                with self.subTest(widget=widget, option=option):
                    self.assertIsInstance(value, list)
                    self.assertEqual(len(value), 2)


class SettingsTests(unittest.TestCase):
    """Preferences live in a small JSON file, and every failure path has
    to land on the defaults rather than raise - a preference is never
    worth taking the app down for."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        real = settings.get_app_data_dir
        settings.get_app_data_dir = lambda: Path(self.tmp.name)
        self.addCleanup(setattr, settings, "get_app_data_dir", real)

    def test_defaults_when_nothing_is_saved(self):
        self.assertEqual(settings.load()["appearance_mode"], "Dark")

    def test_round_trip(self):
        settings.save(appearance_mode="Light")
        self.assertEqual(settings.get("appearance_mode"), "Light")

    def test_unknown_keys_are_ignored(self):
        settings.save(appearance_mode="Light", nonsense="x")
        self.assertNotIn("nonsense", settings.load())

    def test_a_corrupt_file_falls_back_to_defaults(self):
        settings.settings_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(settings.load()["appearance_mode"], "Dark")

    def test_a_file_holding_a_list_falls_back_to_defaults(self):
        settings.settings_path().write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(settings.load()["appearance_mode"], "Dark")


class ModeSwitchTests(unittest.TestCase):
    """Switching has to repaint the things that don't repaint
    themselves: ttk styles, grid row tags, chart canvases."""

    def setUp(self):
        self.app = gui_fixture.get_app()
        self.original = theme.get_mode()
        self.addCleanup(lambda: theme.set_mode(self.original))
        # on_appearance_changed saves the preference, and the user's own
        # settings.json is not this suite's to rewrite.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        real = settings.get_app_data_dir
        settings.get_app_data_dir = lambda: Path(self.tmp.name)
        self.addCleanup(setattr, settings, "get_app_data_dir", real)

    def test_switching_restyles_the_treeview(self):
        from tkinter import ttk

        style = ttk.Style()
        theme.set_mode("Light")
        self.assertEqual(style.lookup("Treeview", "background"), theme.PANEL_BG[0])
        theme.set_mode("Dark")
        self.assertEqual(style.lookup("Treeview", "background"), theme.PANEL_BG[1])

    def test_listeners_are_called(self):
        calls = []
        theme.on_mode_change(lambda: calls.append(theme.get_mode()))
        theme.set_mode("Light")
        self.assertEqual(calls, ["Light"])

    def test_a_dead_listener_is_dropped_not_raised(self):
        # Charts and grids outlive nothing gracefully - by the time one
        # raises, its widget is usually already destroyed.
        def boom():
            raise RuntimeError("widget destroyed")

        theme.on_mode_change(boom)
        theme.set_mode("Light")     # must not raise
        theme.set_mode("Dark")
        self.assertNotIn(boom, theme._listeners)

    def test_the_picker_and_the_app_agree(self):
        self.app.on_appearance_changed("Light")
        self.assertEqual(theme.get_mode(), "Light")
        self.app.on_appearance_changed("Dark")
        self.assertEqual(theme.get_mode(), "Dark")


if __name__ == "__main__":
    unittest.main()
