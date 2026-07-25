"""Color palette pulled from hitechcreations.com's own site CSS
(templates/gamers/css/custom.css and template.css), so the app reads as
a companion to the game's website rather than a generic dark-mode tool.
"""
from __future__ import annotations

from tkinter import ttk

from ahstats.paths import resource_path

# Darker, richer color palette for distinctive look
BG_DARK = "#0f1419"           # Darker background
PANEL_BG = "#1a1f26"          # Slightly lighter panels
PANEL_BG_ALT = "#242b33"      # Alternating rows
BORDER_GRAY = "#2e3440"       # Subtler borders
TEXT_BODY = "#d8dee9"         # Better contrast
TEXT_HEADING = "#eceff4"      # Crisp headings
TEXT_CREAM = "#e5e9f0"        # Cream for headers

# NEW: Replace orange with green scheme
ACCENT_GREEN = "#10b981"      # Primary action color (emerald green)
ACCENT_GREEN_HOVER = "#059669" # Hover state
ACCENT_OLIVE = "#4a5a42"      # Keep olive for navbar (military feel)
ACCENT_OLIVE_HOVER = "#5f7254"
ACCENT_BLUE = "#3b82f6"       # Secondary accent (information)
ACCENT_RED = "#ef4444"        # Danger/stop actions

# Legacy aliases for backward compatibility
ACCENT_AMBER = ACCENT_GREEN
ACCENT_AMBER_HOVER = ACCENT_GREEN_HOVER

THEME_JSON_PATH = resource_path("assets", "htc_theme.json")
APP_ICON_ICO_PATH = resource_path("assets", "app_icon.ico")
APP_ICON_PNG_PATH = resource_path("assets", "app_icon.png")


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
        background=PANEL_BG,
        fieldbackground=PANEL_BG,
        foreground=TEXT_BODY,
        borderwidth=0,
        rowheight=28,
        font=tree_font,
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT_GREEN)],
        foreground=[("selected", "#0f1419")],
    )
    style.configure(
        "Treeview.Heading",
        background=ACCENT_OLIVE,
        foreground=TEXT_CREAM,
        borderwidth=0,
        relief="flat",
        font=heading_font,
    )
    style.map(
        "Treeview.Heading",
        background=[("active", ACCENT_OLIVE_HOVER)],
    )

    # Scrollbars are ttk too, so they need the same hand-styling or they
    # come out in default light grey against the dark grids.
    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"{orient}.TScrollbar",
            background=BORDER_GRAY,
            troughcolor=BG_DARK,
            bordercolor=BG_DARK,
            arrowcolor=TEXT_BODY,
            borderwidth=0,
        )
        style.map(
            f"{orient}.TScrollbar",
            background=[("active", ACCENT_OLIVE_HOVER)],
        )


def configure_zebra_tags(tree) -> None:
    """Call once per Treeview right after creation. Pass tags=zebra_tag(i)
    to each .insert() call so alternating rows get a slightly different
    shade - makes it easier to track a row across columns."""
    tree.tag_configure("even", background=PANEL_BG)
    tree.tag_configure("odd", background=PANEL_BG_ALT)


def zebra_tag(index: int) -> tuple:
    return ("even",) if index % 2 == 0 else ("odd",)
