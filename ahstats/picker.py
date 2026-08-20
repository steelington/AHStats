"""A type-to-filter dropdown, for pickers with far too many entries.

CTkOptionMenu is fine for the handful of values an arena or category
picker holds, but the tour pickers carry one entry per tour ever run -
over three hundred of them, and growing by one a month. Tk renders a
menu that long as a column with a scroll arrow at each end: no
scrollbar, no mouse wheel, and no way to get from Tour 300 to Tour 12
except by holding the mouse still on an arrow. This replaces it.

The Kills-by-Plane model picker has the same problem for the same
reason: a long career meets a hundred and twenty-odd aircraft, which is
a menu twenty-four hundred pixels tall. Tk clips that to the screen and
the entries that fall off the top - the As, so the Zeroes - simply are
not there to click.

Typing filters the list; the wheel and the scrollbar both work, because
the popup is a plain Tk Listbox rather than a menu.
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from ahstats import theme

# Show at most this many rows at once; the rest are a scroll away.
MAX_VISIBLE_ROWS = 14

# Shown in place of the list when nothing matches, so an empty dropdown
# reads as "no such tour" rather than as a broken one.
NO_MATCH_ROW = "(no tour matches that)"

_TRAILING_NUMBER = re.compile(r"(\d+)\s*$")


def tour_number(text: str) -> int | None:
    """The tour number at the end of a label or a typed filter.

    Tour labels are an arena name and a number - "Melee Tour 319", "Late
    War Tour 147", or just "Tour 47" for the pre-split Main Arena - and
    players think in the number. Returns None for anything without one
    ("Combat Theater", a half-typed word)."""
    match = _TRAILING_NUMBER.search(text)
    return int(match.group(1)) if match else None


class SearchableSelect(ctk.CTkFrame):
    """Drop-in replacement for CTkOptionMenu where the list is long.

    Matches the parts of CTkOptionMenu's interface this app actually
    uses - `variable`, `values`, `command`, `width`, and `configure
    (values=...)` - so swapping one for the other is a one-line change
    at each call site."""

    def __init__(self, parent, variable=None, values=(), width=200, command=None, placeholder="",
                 match_numbers: bool = True, no_match_text: str = NO_MATCH_ROW, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._variable = variable if variable is not None else ctk.StringVar()
        self._values = list(values)
        self._command = command
        # Tour labels end in the number players think in; aircraft names
        # end in a mark or a model number that means nothing across
        # aircraft. Ranking "A6M3" against everything ending in 3 puts
        # the M-3 halftrack above the Zero, so plane pickers turn this
        # off. See _match_rank.
        self._match_numbers = match_numbers
        self._no_match_text = no_match_text
        self._popup: tk.Toplevel | None = None
        self._listbox: tk.Listbox | None = None
        self._filtered: list[str] = []
        # While the entry mirrors the selected value we must not treat
        # that programmatic write as the user typing a filter.
        self._syncing = False

        self.entry = ctk.CTkEntry(self, width=width, placeholder_text=placeholder)
        self.entry.pack(side="left", fill="x", expand=True)
        self.button = ctk.CTkButton(
            self, text="▼", width=28, command=self.toggle,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY,
        )
        self.button.pack(side="left", padx=(2, 0))

        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<Button-1>", lambda _e: self.open())
        # Arriving in the box selects what's in it, so the first
        # keystroke replaces the whole label. Without this the box is
        # pre-filled with the current tour and typing appends to it.
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<Down>", lambda _e: self.open())
        self.entry.bind("<Escape>", lambda _e: self.close())
        self.entry.bind("<Return>", self._on_return)
        # Typing a tour name and tabbing straight to the button is a
        # selection too - see commit_typed().
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self._variable.trace_add("write", lambda *_: self._show_variable())
        self._show_variable()

    # -- value ---------------------------------------------------------

    def get(self) -> str:
        """The selected value, resolving anything typed but not yet picked.

        Callers must read this rather than the StringVar they passed in.
        The variable only changes when a value is *chosen*, so a player
        who types "Melee Tour 47" and clicks a Fetch button without ever
        touching the list would otherwise have their typing ignored and
        the previous selection - the newest tour - fetched instead."""
        self.commit_typed()
        return self._variable.get()

    def set(self, value: str) -> None:
        self._variable.set(value)

    def _show_variable(self) -> None:
        """Mirror the variable into the entry, unless the user is
        mid-filter - overwriting what they're typing would be rude."""
        if self._popup is not None:
            return
        self._syncing = True
        self.entry.delete(0, "end")
        self.entry.insert(0, self._variable.get())
        self._syncing = False

    def configure(self, **kwargs):
        """`values=` reloads the list; everything else goes to the frame."""
        if "values" in kwargs:
            self._values = list(kwargs.pop("values"))
            if self._popup is not None:
                self._refilter()
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "state" in kwargs:
            state = kwargs.pop("state")
            self.entry.configure(state=state)
            self.button.configure(state=state)
        if kwargs:
            super().configure(**kwargs)

    # -- popup ---------------------------------------------------------

    def toggle(self) -> None:
        self.close() if self._popup is not None else self.open()

    def open(self) -> None:
        # A popup destroyed behind our back - the window closing under
        # it, say - would otherwise leave a dead handle here and wedge
        # the widget shut: open() would decline to build a second one
        # and _show_variable would decline to touch the entry, so the
        # box would sit on one value with no list, forever.
        if self._popup is not None and not self._popup.winfo_exists():
            self._popup = None
            self._listbox = None
        if self._popup is not None or not self._values:
            return

        self._popup = tk.Toplevel(self)
        # Withdrawn until _place_popup has put it where it belongs. A
        # fresh Toplevel starts life at the screen's top-left corner,
        # and building the list runs update_idletasks, which maps it
        # there - so without this the dropdown flashes in the corner of
        # the screen before jumping under the entry.
        self._popup.wm_withdraw()
        self._popup.wm_overrideredirect(True)  # no title bar - this is a dropdown, not a window
        self._popup.configure(bg=theme.BORDER_GRAY)
        self._popup.transient(self.winfo_toplevel())

        frame = tk.Frame(self._popup, bg=theme.BORDER_GRAY, bd=0)
        frame.pack(fill="both", expand=True, padx=1, pady=1)

        self._listbox = tk.Listbox(
            frame, activestyle="none", borderwidth=0, highlightthickness=0,
            bg=theme.PANEL_BG, fg=theme.TEXT_BODY,
            selectbackground=theme.ACCENT_GREEN, selectforeground=theme.BG_DARK,
            font=("Segoe UI", 10), exportselection=False,
        )
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scrollbar.set)
        self._listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._listbox.bind("<Double-Button-1>", self._on_pick)
        self._listbox.bind("<Return>", self._on_pick)
        self._listbox.bind("<ButtonRelease-1>", self._on_pick)
        self._listbox.bind("<Escape>", lambda _e: self.close())
        # Tk's own Listbox bindings cover the wheel, but only once the
        # pointer is over the list; bind it on the popup too so a wheel
        # turn anywhere in the dropdown scrolls.
        self._popup.bind("<MouseWheel>", self._on_wheel)

        self._refilter(select_current=True)
        self._place_popup()
        # A click anywhere else should dismiss the dropdown. Binding on
        # the toplevel rather than grabbing keeps the rest of the window
        # responsive while it's open.
        self._click_binding = self.winfo_toplevel().bind("<Button-1>", self._on_global_click, add="+")

    def close(self, keep_typed: bool = False) -> None:
        """Dismiss the popup. `keep_typed` leaves the entry as the user
        left it instead of snapping it back to the current selection,
        for callers that are about to resolve that text themselves."""
        if self._popup is None:
            return
        # Drop our handles first, so a failure below still leaves the
        # widget usable rather than permanently half-open.
        popup, self._popup, self._listbox = self._popup, None, None
        try:
            self.winfo_toplevel().unbind("<Button-1>", getattr(self, "_click_binding", None))
        except tk.TclError:
            pass
        try:
            popup.destroy()
        except tk.TclError:  # already gone
            pass
        if not keep_typed:
            self._show_variable()

    def _place_popup(self) -> None:
        """Sit the popup directly under the entry, flipping above it if
        there isn't room below - the sync bar is near the bottom of the
        window on smaller screens."""
        self.update_idletasks()
        rows = max(1, min(len(self._filtered), MAX_VISIBLE_ROWS))
        self._listbox.configure(height=rows)
        self._popup.update_idletasks()

        width = max(self.winfo_width(), 240)
        height = self._popup.winfo_reqheight()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        if y + height > self.winfo_screenheight():
            y = max(0, self.winfo_rooty() - height)
        self._popup.wm_geometry(f"{width}x{height}+{x}+{y}")
        # Now, and not before, it is fit to be seen. Harmless on the
        # refilter path, where it is already up.
        self._popup.wm_deiconify()
        self._popup.lift()

    # -- filtering -----------------------------------------------------

    def _on_key(self, event) -> None:
        if self._syncing or event.keysym in ("Return", "Escape", "Up", "Down"):
            return
        self.open()
        self._refilter()
        if self._popup is not None:
            self._place_popup()

    def _refilter(self, select_current: bool = False) -> None:
        if self._listbox is None:
            return
        needle = self.entry.get().strip().casefold()
        current = self._variable.get()
        # A match on the whole entry contents means the user hasn't
        # started filtering yet - show everything rather than the one row.
        if needle and needle != current.casefold():
            self._filtered = self._ranked(needle)
        else:
            self._filtered = list(self._values)

        self._listbox.delete(0, "end")
        for value in self._filtered:
            self._listbox.insert("end", value)
        if not self._filtered:
            self._listbox.insert("end", self._no_match_text)
        if select_current and current in self._filtered:
            index = self._filtered.index(current)
            self._listbox.selection_set(index)
            self._listbox.see(index)

    def _ranked(self, needle: str) -> list[str]:
        """Values matching `needle`, best match first.

        `needle` must already be casefolded. Sorting is stable, so within
        a tier the list keeps its newest-first order."""
        wanted = tour_number(needle) if self._match_numbers else None
        scored = []
        for value in self._values:
            rank = self._match_rank(value.casefold(), needle, wanted)
            if rank is not None:
                scored.append((rank, value))
        scored.sort(key=lambda pair: pair[0])
        return [value for _, value in scored]

    @staticmethod
    def _match_rank(value: str, needle: str, wanted: int | None) -> int | None:
        """How well one value matches, lower being better; None for no
        match at all. `value` and `needle` must both be casefolded.

        The tour number outranks a plain substring for two reasons, both
        of them things players actually did:

        - Typing the bare number. "47" appears in Tour 47, Late War Tour
          147 and Melee Tour 247, and the newest-first list offers 247 -
          so Enter synced a tour thirty years of arena time away from the
          one asked for.
        - Editing the number in the box without touching the arena name.
          The picker starts filled in with the current tour, so changing
          "Melee Tour 319" to "Melee Tour 47" is the obvious move - but
          tour 47 predates the arena split and is labelled plain "Tour
          47", so that matched nothing and the box snapped back to 319.
          The same trap covers every Late War tour, 93 through 200.
        """
        if value == needle:
            return 0
        if wanted is not None and tour_number(value) == wanted:
            return 1
        if value.startswith(needle):
            return 2
        if needle in value:
            return 3
        return None

    # -- selection -----------------------------------------------------

    def _on_wheel(self, event) -> str:
        if self._listbox is not None:
            self._listbox.yview_scroll(-1 * (event.delta // 120), "units")
        return "break"

    def _on_return(self, _event) -> None:
        """Enter takes the first match, so filtering to one tour and
        hitting Enter is the whole interaction."""
        if self._popup is not None and self._filtered:
            self._choose(self._filtered[0])
        else:
            self.commit_typed()

    def _on_focus_in(self, _event) -> None:
        """Select the whole entry when focus lands in it.

        Deferred to idle because the click that brings focus here is
        still being handled: Tk's own Entry binding sets the insertion
        cursor and clears the selection after this runs. A later click
        inside the box fires no FocusIn, so it still places the cursor
        normally for anyone who does want to edit in place."""
        self.after_idle(self._select_all)

    def _select_all(self) -> None:
        try:
            self.entry.select_range(0, "end")
            self.entry.icursor("end")
        except tk.TclError:  # the entry went away while we waited
            pass

    def _on_focus_out(self, _event) -> None:
        # While the popup is open the focus can land on the listbox;
        # that's still mid-selection, so leave the typing alone.
        if self._popup is None:
            self.commit_typed()

    def commit_typed(self) -> None:
        """Turn whatever is in the entry into a selection.

        The best match wins, ranked the same way the filtered list is,
        so a fully typed tour name beats the tours that merely contain
        it. Text that matches nothing is discarded and the entry snaps
        back to the current selection - better than silently syncing a
        tour the player never asked for."""
        self.close(keep_typed=True)
        needle = self.entry.get().strip().casefold()
        if not needle:
            self._show_variable()
            return
        if needle == self._variable.get().casefold():
            return
        matches = self._ranked(needle)
        if matches:
            self._select(matches[0])
        else:
            self._show_variable()

    def _on_pick(self, _event) -> None:
        if self._listbox is None:
            return
        selection = self._listbox.curselection()
        # The "no matches" row is a message, not a value - clicking it
        # must not pick anything.
        if selection and selection[0] < len(self._filtered):
            self._choose(self._filtered[selection[0]])

    def _on_global_click(self, event) -> None:
        """Close on a click outside the widget or its popup, keeping
        whatever was typed - the click is usually on the very button
        that acts on the selection."""
        if self._popup is None:
            return
        widget = event.widget
        while widget is not None:
            if widget in (self, self.entry, self.button, self._popup):
                return
            widget = getattr(widget, "master", None)
        self.commit_typed()

    def _choose(self, value: str) -> None:
        self.close()
        self._select(value)

    def _select(self, value: str) -> None:
        self._variable.set(value)
        self._show_variable()
        if self._command:
            self._command(value)
