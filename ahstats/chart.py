"""A small line-chart widget drawn straight onto a tkinter Canvas.

Spatula's Graphs tab used NPlot. The equivalent here would be matplotlib,
but it (plus numpy) adds tens of megabytes to the PyInstaller build for
what are simple XY trend lines, so these are drawn by hand. That also
means the charts pick up the app's palette exactly.
"""
from __future__ import annotations

import tkinter as tk

from ahstats import theme

# Room for axis labels; the plot area is what's left inside these.
MARGIN_LEFT = 66
MARGIN_RIGHT = 18
MARGIN_TOP = 30
MARGIN_BOTTOM = 54  # room for tick labels and the axis caption below them


def _nice_step(span: float, target_ticks: int = 5) -> float:
    """A round-numbered gridline interval (1, 2, 5, 10, 20, 50...) that
    puts roughly target_ticks lines across the given span."""
    if span <= 0:
        return 1.0
    rough = span / max(1, target_ticks)
    magnitude = 10 ** int(_floor_log10(rough))
    for multiple in (1, 2, 2.5, 5, 10):
        if magnitude * multiple >= rough:
            return magnitude * multiple
    return magnitude * 10


def _floor_log10(value: float) -> float:
    import math

    return math.floor(math.log10(value)) if value > 0 else 0


def _format_tick(value: float) -> str:
    if abs(value) >= 10000:
        return f"{value:,.0f}"
    if abs(value) >= 10 or value == int(value):
        return f"{value:,.0f}"
    return f"{value:,.2f}"


class TrendChart(tk.Canvas):
    """Plots a single series of (x, y) points as a line with markers."""

    def __init__(self, parent, height=380, **kwargs):
        super().__init__(
            parent, height=height, bg=theme.color(theme.PANEL_BG),
            highlightthickness=0, bd=0, **kwargs
        )
        self._points: list[tuple[float, float]] = []
        self._title = ""
        self._ylabel = ""
        self._message = "Pick a graph to plot."
        self.bind("<Configure>", lambda _e: self._redraw())
        # A Canvas takes flat colors, so nothing on it follows a
        # light/dark switch by itself - repaint on the way through.
        theme.on_mode_change(self._apply_mode)

    def _apply_mode(self) -> None:
        """Re-colour and re-draw for the current appearance mode.

        Raises if the chart has been destroyed, which is how theme drops
        a dead listener - see theme.on_mode_change."""
        self.configure(bg=theme.color(theme.PANEL_BG))
        self._redraw()

    def plot(self, points, title="", ylabel="", message="") -> None:
        """points: (x, y) pairs, x ascending. Pass message instead to show
        an explanation when there's nothing to draw."""
        self._points = [(float(x), float(y)) for x, y in points]
        self._title = title
        self._ylabel = ylabel
        self._message = message
        self._redraw()

    # -- drawing ------------------------------------------------------

    def _redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 60 or height < 60:
            return

        if self._title:
            self.create_text(
                width / 2, 14, text=self._title, fill=theme.color(theme.TEXT_HEADING),
                font=("Segoe UI", 12, "bold"),
            )

        if not self._points:
            self.create_text(
                width / 2, height / 2,
                text=self._message or "No data for this selection.",
                fill=theme.color(theme.TEXT_BODY), font=("Segoe UI", 11),
            )
            return

        left, right = MARGIN_LEFT, width - MARGIN_RIGHT
        top, bottom = MARGIN_TOP, height - MARGIN_BOTTOM
        if right <= left or bottom <= top:
            return

        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        if y_min > 0:
            y_min = 0  # trends read better against a zero baseline
        if y_max == y_min:
            y_max = y_min + 1
        if x_max == x_min:
            x_max = x_min + 1

        def sx(x):
            return left + (x - x_min) / (x_max - x_min) * (right - left)

        def sy(y):
            return bottom - (y - y_min) / (y_max - y_min) * (bottom - top)

        # Horizontal gridlines + y tick labels
        step = _nice_step(y_max - y_min)
        tick = (int(y_min / step)) * step
        while tick <= y_max + step / 2:
            if tick >= y_min - step / 2:
                y = sy(tick)
                if top - 1 <= y <= bottom + 1:
                    self.create_line(left, y, right, y, fill=theme.color(theme.BORDER_GRAY))
                    self.create_text(
                        left - 6, y, text=_format_tick(tick), anchor="e",
                        fill=theme.color(theme.TEXT_BODY), font=("Segoe UI", 9),
                    )
            tick += step

        # Axes
        self.create_line(left, top, left, bottom, fill=theme.color(theme.TEXT_BODY))
        self.create_line(left, bottom, right, bottom, fill=theme.color(theme.TEXT_BODY))

        # X tick labels - a handful of tour numbers, evenly spaced
        label_count = max(2, min(10, len(self._points)))
        seen = set()
        for i in range(label_count):
            index = round(i * (len(self._points) - 1) / (label_count - 1))
            x_value = self._points[index][0]
            if x_value in seen:
                continue
            seen.add(x_value)
            self.create_text(
                sx(x_value), bottom + 8, text=f"{x_value:.0f}", anchor="n",
                fill=theme.color(theme.TEXT_BODY), font=("Segoe UI", 9),
            )
        self.create_text(
            (left + right) / 2, height - 6, text="Tour", anchor="s",
            fill=theme.color(theme.TEXT_BODY), font=("Segoe UI", 9),
        )
        if self._ylabel:
            self.create_text(
                12, (top + bottom) / 2, text=self._ylabel, angle=90,
                fill=theme.color(theme.TEXT_BODY), font=("Segoe UI", 9),
            )

        # The series itself
        coords = []
        for x, y in self._points:
            coords.extend((sx(x), sy(y)))
        if len(coords) >= 4:
            self.create_line(*coords, fill=theme.color(theme.ACCENT_GREEN), width=2, smooth=False)

        # Markers, but only when they won't turn into a solid bar
        if len(self._points) <= 120:
            for x, y in self._points:
                px, py = sx(x), sy(y)
                self.create_oval(
                    px - 2.5, py - 2.5, px + 2.5, py + 2.5,
                    fill=theme.color(theme.ACCENT_GREEN), outline=theme.color(theme.BG_DARK),
                )
