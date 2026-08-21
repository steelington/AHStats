"""Color palette pulled from hitechcreations.com's own site CSS
(templates/gamers/css/custom.css and template.css), so the app reads as
a companion to the game's website rather than a generic dark-mode tool.

**Every color here is a `(light, dark)` pair.** That is customtkinter's
own convention: hand a CTk widget a two-tuple and it picks the right
half for the current appearance mode, and re-picks it - live, on widgets
already on screen - when the mode changes. So the light theme costs the
CTk half of the app nothing but a second column of values.

The rest of the app is not so lucky. tkinter's Canvas, Listbox and
ttk.Treeview take one flat color string, so anything drawing on those
must resolve the pair itself with `color()` **at draw time**, and
re-draw when the mode changes. `set_mode()` handles the ttk styling and
then calls back everything registered through `on_mode_change()`.
"""
from __future__ import annotations

from tkinter import ttk

import customtkinter as ctk

from ahstats.paths import resource_path

MODES = ("Dark", "Light")

# Each entry is (light, dark).
BG_DARK = ("#e9edf1", "#0f1419")        # window background
PANEL_BG = ("#ffffff", "#1a1f26")       # panels, even grid rows
PANEL_BG_ALT = ("#eef1f5", "#242b33")   # odd grid rows
BORDER_GRAY = ("#c2cad4", "#2e3440")    # borders, scrollbar thumb
TEXT_BODY = ("#1e252d", "#d8dee9")
TEXT_HEADING = ("#0f1419", "#eceff4")
TEXT_MUTED = ("#5b6672", "#8b93a1")     # hints and counts beside a field

# Olive is the app's identity - the masthead band and grid headings - so
# it stays put in both modes, with cream text on it either way. A light
# theme that repainted the masthead would just be a different app.
ACCENT_OLIVE = ("#4a5a42", "#4a5a42")
ACCENT_OLIVE_HOVER = ("#5f7254", "#5f7254")
TEXT_CREAM = ("#f2f5f8", "#e5e9f0")     # header text on olive

# The accents darken in light mode: #10b981 on white is bright enough to
# hurt, and fails contrast for text.
ACCENT_GREEN = ("#0b8f63", "#10b981")   # primary action, selection
ACCENT_GREEN_HOVER = ("#0a7a55", "#059669")
ACCENT_BLUE = ("#2563eb", "#3b82f6")    # informational
ACCENT_RED = ("#dc2626", "#ef4444")     # danger / stop
ACCENT_RED_HOVER = ("#b91c1c", "#dc2626")
STATUS_WARNING = ("#a95c00", "#ff9900")
STATUS_ERROR = ("#c00000", "#ff4444")
SELECT_FG = ("#ffffff", "#0f1419")      # text on a green selection

# Legacy aliases for backward compatibility
ACCENT_AMBER = ACCENT_GREEN
ACCENT_AMBER_HOVER = ACCENT_GREEN_HOVER

THEME_JSON_PATH = resource_path("assets", "htc_theme.json")
APP_ICON_ICO_PATH = resource_path("assets", "app_icon.ico")
APP_ICON_PNG_PATH = resource_path("assets", "app_icon.png")

_listeners: list = []


def get_mode() -> str:
    """"Light" or "Dark" - whatever customtkinter is actually showing.

    Asked of customtkinter rather than tracked here, so there is one
    source of truth and no way for the two to drift apart.
    """
    return "Light" if ctk.get_appearance_mode() == "Light" else "Dark"


def color(value):
    """Resolve a (light, dark) pair for the mode on screen right now.

    Needed by every non-CTk widget - Canvas, Listbox, ttk styles - which
    take one flat color. Passing an already-flat string through is
    deliberate: it keeps call sites from having to care which they hold.
    """
    if isinstance(value, (tuple, list)):
        return value[0] if get_mode() == "Light" else value[1]
    return value


def on_mode_change(callback) -> None:
    """Register something to re-draw when the mode changes.

    Charts and grids draw with flat colors resolved at draw time, so
    they need telling; CTk widgets recolor themselves and do not.
    A callback that raises is dropped rather than allowed to break the
    switch - by the time it raises, its widget is usually already gone.
    """
    _listeners.append(callback)


def set_mode(mode: str) -> None:
    """Switch the whole app between "Light" and "Dark", live."""
    mode = "Light" if str(mode).lower().startswith("l") else "Dark"
    ctk.set_appearance_mode(mode)
    style_treeview()
    for callback in list(_listeners):
        try:
            callback()
        except Exception:            # noqa: BLE001 - a dead widget must not block the switch
            _listeners.remove(callback)


def style_treeview() -> None:
    """ttk.Treeview isn't a customtkinter widget, so it doesn't pick up
    the CTk theme automatically - style it to match by hand."""
    import tkinter.font as tkfont

    style = ttk.Style()
    style.theme_use("clam")  # 'clam' honors color overrides on Windows; the default 'vista' theme mostly ignores them

    # Create larger fonts for better readability
    tree_font = tkfont.Font(family="Segoe UI", size=11)
    heading_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

    style.configure(
        "Treeview",
        background=color(PANEL_BG),
        fieldbackground=color(PANEL_BG),
        foreground=color(TEXT_BODY),
        borderwidth=0,
        rowheight=28,
        font=tree_font,
        # borderwidth=0 doesn't stop clam drawing its bevel: it frames
        # every grid in near-white unless these are given dark values.
        # BORDER_GRAY rather than the background, so the grid still has
        # an edge - just one that belongs to the theme.
        bordercolor=color(BORDER_GRAY),
        lightcolor=color(BORDER_GRAY),
        darkcolor=color(BORDER_GRAY),
    )
    style.map(
        "Treeview",
        background=[("selected", color(ACCENT_GREEN))],
        foreground=[("selected", color(SELECT_FG))],
    )
    style.configure(
        "Treeview.Heading",
        background=color(ACCENT_OLIVE),
        foreground=color(TEXT_CREAM),
        borderwidth=0,
        relief="flat",
        font=heading_font,
    )
    style.map(
        "Treeview.Heading",
        background=[("active", color(ACCENT_OLIVE_HOVER))],
    )

    # Scrollbars are ttk too, so they need the same hand-styling or they
    # come out in default light grey against the dark grids.
    #
    # "TScrollbar" has to be in this list. A ttk.Scrollbar keeps the bare
    # class name as its style whatever -orient says: only its *layout* is
    # picked by orientation. Styling just Vertical/Horizontal therefore
    # configured two names nothing was using, and every scrollbar in the
    # app - the grids and the tour dropdown alike - kept clam's light
    # grey trough and 3D arrows in the middle of a dark window.
    for name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            name,
            background=color(BORDER_GRAY),
            troughcolor=color(BG_DARK),
            bordercolor=color(BG_DARK),
            arrowcolor=color(TEXT_BODY),
            borderwidth=0,
            relief="flat",
            gripcount=0,  # clam draws grip ridges on the thumb by default
            # clam bevels every element with these two; left at their
            # defaults they outline the thumb and both arrows in near-white.
            lightcolor=color(BG_DARK),
            darkcolor=color(BG_DARK),
        )
        style.map(
            name,
            background=[("active", color(ACCENT_OLIVE_HOVER)), ("disabled", color(PANEL_BG))],
            arrowcolor=[("disabled", color(BORDER_GRAY))],
        )


def configure_zebra_tags(tree) -> None:
    """Call once per Treeview right after creation. Pass tags=zebra_tag(i)
    to each .insert() call so alternating rows get a slightly different
    shade - makes it easier to track a row across columns."""
    # Foreground as well as background: a tag set once in dark mode
    # would otherwise keep pale text when the app switches to light.
    tree.tag_configure("even", background=color(PANEL_BG), foreground=color(TEXT_BODY))
    tree.tag_configure("odd", background=color(PANEL_BG_ALT), foreground=color(TEXT_BODY))


def zebra_tag(index: int) -> tuple:
    return ("even",) if index % 2 == 0 else ("odd",)
