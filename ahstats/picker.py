"""A type-to-filter dropdown, for pickers with far too many entries.

CTkOptionMenu is fine for the handful of values an arena or category
picker holds, but the tour pickers carry one entry per tour ever run -
over three hundred of them, and growing by one a month. Tk renders a
menu that long as a column with a scroll arrow at each end: no
scrollbar, no mouse wheel, and no way to get from Tour 300 to Tour 12
except by holding the mouse still on an arrow. This replaces it.

Typing filters the list; the wheel and the scrollbar both work, because
the popup is a plain Tk Listbox rather than a menu.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from ahstats import theme

# Show at most this many rows at once; the rest are a scroll away.
MAX_VISIBLE_ROWS = 14


class SearchableSelect(ctk.CTkFrame):
    """Drop-in replacement for CTkOptionMenu where the list is long.

    Matches the parts of CTkOptionMenu's interface this app actually
    uses - `variable`, `values`, `command`, `width`, and `configure
    (values=...)` - so swapping one for the other is a one-line change
    at each call site."""

    def __init__(self, parent, variable=None, values=(), width=200, command=None, placeholder="", **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._variable = variable if variable is not None else ctk.StringVar()
        self._values = list(values)
        self._command = command
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
        self.entry.bind("<Down>", lambda _e: self.open())
        self.entry.bind("<Escape>", lambda _e: self.close())
        self.entry.bind("<Return>", self._on_return)
        self._variable.trace_add("write", lambda *_: self._show_variable())
        self._show_variable()

    # -- value ---------------------------------------------------------

    def get(self) -> str:
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
        if self._popup is not None or not self._values:
            return

        self._popup = tk.Toplevel(self)
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

    def close(self) -> None:
        if self._popup is None:
            return
        try:
            self.winfo_toplevel().unbind("<Button-1>", self._click_binding)
        except tk.TclError:
            pass
        self._popup.destroy()
        self._popup = None
        self._listbox = None
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
            matches = [v for v in self._values if needle in v.casefold()]
            # An exact match goes first, then values starting with what was
            # typed, then the rest. Without this, typing "Tour 21" buries
            # Tour 21 under Tour 210-219, which all contain it as a
            # substring - and Enter would take the wrong one. Sorting is
            # stable, so within each tier the list keeps its newest-first
            # order.
            matches.sort(key=lambda v: self._match_rank(v.casefold(), needle))
            self._filtered = matches
        else:
            self._filtered = list(self._values)

        self._listbox.delete(0, "end")
        for value in self._filtered:
            self._listbox.insert("end", value)
        if select_current and current in self._filtered:
            index = self._filtered.index(current)
            self._listbox.selection_set(index)
            self._listbox.see(index)

    @staticmethod
    def _match_rank(value: str, needle: str) -> int:
        """0 for an exact match, 1 for a prefix, 2 for anything else.
        Both arguments must already be casefolded."""
        if value == needle:
            return 0
        if value.startswith(needle):
            return 1
        return 2

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

    def _on_pick(self, _event) -> None:
        if self._listbox is None:
            return
        selection = self._listbox.curselection()
        if selection:
            self._choose(self._filtered[selection[0]])

    def _on_global_click(self, event) -> None:
        """Close on a click outside the widget or its popup."""
        if self._popup is None:
            return
        widget = event.widget
        while widget is not None:
            if widget in (self, self.entry, self.button, self._popup):
                return
            widget = getattr(widget, "master", None)
        self.close()

    def _choose(self, value: str) -> None:
        self.close()
        self._variable.set(value)
        self._show_variable()
        if self._command:
            self._command(value)
