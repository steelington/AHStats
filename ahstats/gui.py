"""customtkinter GUI for looking up and caching Aces High stats."""
from __future__ import annotations

import queue
import threading
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image

from ahstats import __version__, export, sync, theme
from ahstats import grid as gridmod
from ahstats.client import AhScoreClient
from ahstats.chart import TrendChart
from ahstats.grid import GridView
from ahstats.db import (
    ARENA_CHOICES,
    CATEGORY_LABELS,
    SCORE_HEADERS,
    StatsDB,
    tour_number,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme(str(theme.THEME_JSON_PATH))

ARENA_PICKER_VALUES = ARENA_CHOICES + ["All"]


def _fmt_hms(total_seconds) -> str:
    if not total_seconds:
        return "00:00:00"
    total_seconds = int(total_seconds)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Aces High Stats v{__version__}")
        self.geometry("1300x760")
        self.minsize(1200, 600)
        self.configure(fg_color=theme.BG_DARK)
        if theme.APP_ICON_ICO_PATH.exists():
            self.iconbitmap(str(theme.APP_ICON_ICO_PATH))
        theme.style_treeview()

        self.db = StatsDB()
        self.client = AhScoreClient()
        self.stop_event = threading.Event()
        self.progress_queue: queue.Queue = queue.Queue()
        self.sync_thread: threading.Thread | None = None

        self._tour_label_to_id: dict[str, str] = {}
        self._pending_squad_fetch: tuple[str, str] | None = None
        self._pending_arena_fetch: str | None = None

        # Both are tracked so destroy() can cancel them - a pending
        # 'after' that fires into a torn-down interpreter raises
        # "invalid command name".
        self._poll_after_id: str | None = None
        self._startup_after_id: str | None = None

        self._build_top_bar()
        self._build_tabs()
        self.refresh_identity_view_dropdown()
        self._poll_queue()  # reschedules itself, storing _poll_after_id
        self._startup_after_id = self.after(500, self._check_incomplete_syncs)

    def destroy(self):
        """Cancel pending timers before tearing the window down."""
        for after_id in (self._poll_after_id, self._startup_after_id):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except Exception:  # already fired, or interpreter going away
                    pass
        self._poll_after_id = self._startup_after_id = None
        super().destroy()

    # ---------------- top bar ----------------

    def _build_masthead(self):
        masthead = ctk.CTkFrame(self, fg_color=theme.ACCENT_OLIVE, corner_radius=0)
        masthead.pack(fill="x")

        if theme.APP_ICON_PNG_PATH.exists():
            logo_image = ctk.CTkImage(
                light_image=Image.open(theme.APP_ICON_PNG_PATH),
                dark_image=Image.open(theme.APP_ICON_PNG_PATH),
                size=(56, 56),
            )
            ctk.CTkLabel(masthead, image=logo_image, text="").pack(side="left", padx=(14, 10), pady=8)

        title_frame = ctk.CTkFrame(masthead, fg_color="transparent")
        title_frame.pack(side="left", pady=8)

        # Version sits beside the title so it's on screen in any
        # screenshot - a bug report that names the build is worth far more
        # than one that doesn't.
        title_row = ctk.CTkFrame(title_frame, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(
            title_row, text="ACES HIGH STATS", text_color=theme.TEXT_HEADING,
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            title_row, text=f"v{__version__}", text_color=theme.TEXT_BODY,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(10, 0), pady=(8, 0))

        ctk.CTkLabel(
            title_frame, text="a homage to Spatula's original AHPilotStats",
            text_color=theme.TEXT_BODY, font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

    def _build_top_bar(self):
        self._build_masthead()

        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=20, pady=(8, 8))

        ctk.CTkLabel(bar, text="Pilot/Squad ID:").pack(side="left", padx=(8, 4))
        self.gameid_entry = ctk.CTkEntry(bar, width=140)
        self.gameid_entry.pack(side="left", padx=4)

        self.stype_var = ctk.StringVar(value="pilot")
        ctk.CTkSegmentedButton(
            bar, values=["pilot", "squad"], variable=self.stype_var, command=self.on_stype_changed
        ).pack(side="left", padx=8)

        ctk.CTkLabel(bar, text="Arena:").pack(side="left", padx=(12, 4))
        self.arena_var = ctk.StringVar(value=ARENA_CHOICES[0])  # Melee (MA) - what most pilots want
        ctk.CTkSegmentedButton(
            bar, values=ARENA_PICKER_VALUES, variable=self.arena_var, command=self.on_arena_changed
        ).pack(side="left", padx=4)

        # Identity group ("MyTotals"-style combined career view across a
        # name change) - own row, the top row is already crowded with
        # the arena picker.
        identity_row = ctk.CTkFrame(self)
        identity_row.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(identity_row, text="Career View:").pack(side="left", padx=(8, 4))
        self.identity_view_var = ctk.StringVar(value="Single ID")
        self.identity_view_dropdown = ctk.CTkOptionMenu(
            identity_row, variable=self.identity_view_var, values=["Single ID"],
            command=self.on_identity_view_changed, width=180,
        )
        self.identity_view_dropdown.pack(side="left", padx=4)
        ctk.CTkButton(
            identity_row, text="Manage Groups...", command=self.on_manage_groups_clicked,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY, width=130,
        ).pack(side="left", padx=4)

        # Sync mode selector
        sync_mode_row = ctk.CTkFrame(self)
        sync_mode_row.pack(fill="x", padx=20, pady=(8, 4))
        ctk.CTkLabel(sync_mode_row, text="Sync Mode:").pack(side="left", padx=(8, 4))
        self.sync_mode_var = ctk.StringVar(value="Full History")
        ctk.CTkSegmentedButton(
            sync_mode_row, values=["Full History", "Single Tour"],
            variable=self.sync_mode_var, command=self.on_sync_mode_changed
        ).pack(side="left", padx=4)

        # Tour selector for single tour mode (initially hidden)
        self.single_tour_label = ctk.CTkLabel(sync_mode_row, text="Tour:")
        self.single_tour_var = ctk.StringVar()
        self.single_tour_dropdown = ctk.CTkOptionMenu(
            sync_mode_row, variable=self.single_tour_var, values=[""], width=200
        )
        self.fetch_tours_btn = ctk.CTkButton(
            sync_mode_row, text="Fetch Tours", command=self.on_fetch_tours_clicked,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY, width=100
        )

        row2 = ctk.CTkFrame(self)
        row2.pack(fill="x", padx=20, pady=(0, 10))

        self.sync_btn = ctk.CTkButton(
            row2, text="Sync Full History", command=self.on_sync_clicked,
            font=ctk.CTkFont(size=13, weight="bold"), height=36
        )
        self.sync_btn.pack(side="left", padx=(8, 4))

        self.stop_btn = ctk.CTkButton(
            row2, text="Stop", command=self.on_stop_clicked, state="disabled",
            fg_color=theme.ACCENT_RED, hover_color="#dc2626", height=36
        )
        self.stop_btn.pack(side="left", padx=4)

        self.status_label = ctk.CTkLabel(
            row2, text="Enter Pilot ID above, then choose sync mode",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#999"
        )
        self.status_label.pack(side="left", padx=12)

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=20, pady=(0, 10))

    def _selected_arena(self) -> str | None:
        """None means 'All' - no arena filter."""
        val = self.arena_var.get()
        return None if val == "All" else val

    def on_arena_changed(self, _value=None):
        self.refresh_career()
        self.refresh_tour_dropdown()
        self.refresh_planes()
        self.refresh_category()
        self.refresh_graph()

    def _effective_gameid(self):
        """The single typed game ID, or - if an identity group is active
        - the list of member game IDs to sum together (e.g. a pilot who
        changed their in-game name partway through their career)."""
        group = self.identity_view_var.get()
        if group and group != "Single ID":
            members = self.db.get_identity_group_members(group, self.stype_var.get())
            if members:
                return members
        return self.gameid_entry.get().strip()

    def refresh_identity_view_dropdown(self):
        groups = self.db.get_identity_group_names(self.stype_var.get())
        values = ["Single ID"] + groups
        self.identity_view_dropdown.configure(values=values)
        if self.identity_view_var.get() not in values:
            self.identity_view_var.set("Single ID")

    def on_identity_view_changed(self, _value=None):
        self.refresh_career()
        self.refresh_tour_dropdown()
        self.refresh_planes()
        self.refresh_category()
        self.refresh_graph()

    def on_stype_changed(self, _value=None):
        self.refresh_identity_view_dropdown()
        self.refresh_career()
        self.refresh_tour_dropdown()
        self.refresh_planes()
        self.refresh_category()
        self.refresh_graph()

    def on_manage_groups_clicked(self):
        stype = self.stype_var.get()
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Manage Identity Groups ({stype})")
        dialog.geometry("480x420")
        dialog.transient(self)

        top = ctk.CTkFrame(dialog)
        top.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(top, text="Existing group:").pack(side="left", padx=(0, 4))
        existing_var = ctk.StringVar(value="")
        existing_dropdown = ctk.CTkOptionMenu(top, variable=existing_var, values=[""], width=180)
        existing_dropdown.pack(side="left", padx=4)

        form = ctk.CTkFrame(dialog)
        form.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(form, text="Group Name:").pack(anchor="w", padx=4, pady=(4, 0))
        name_entry = ctk.CTkEntry(form, width=400, placeholder_text="e.g. MyTotals")
        name_entry.pack(fill="x", padx=4, pady=(0, 8))
        ctk.CTkLabel(form, text="Game IDs (comma-separated, e.g. every name you've ever used):").pack(
            anchor="w", padx=4
        )
        ids_entry = ctk.CTkEntry(form, width=400, placeholder_text="e.g. MDJOE, Fugitive")
        ids_entry.pack(fill="x", padx=4, pady=(0, 8))

        status_label = ctk.CTkLabel(dialog, text="", text_color=theme.ACCENT_OLIVE)
        status_label.pack(anchor="w", padx=14)

        def load_group_list():
            groups = self.db.get_identity_group_names(stype)
            existing_dropdown.configure(values=[""] + groups)

        def on_existing_selected(value):
            if not value:
                name_entry.delete(0, "end")
                ids_entry.delete(0, "end")
                return
            members = self.db.get_identity_group_members(value, stype)
            name_entry.delete(0, "end")
            name_entry.insert(0, value)
            ids_entry.delete(0, "end")
            ids_entry.insert(0, ", ".join(members))

        existing_dropdown.configure(command=on_existing_selected)

        def on_save():
            name = name_entry.get().strip()
            ids = [g.strip() for g in ids_entry.get().split(",") if g.strip()]
            if not name or len(ids) < 2:
                status_label.configure(
                    text="Enter a group name and at least 2 game IDs.", text_color=theme.ACCENT_RED
                )
                return
            self.db.save_identity_group(name, stype, ids)
            status_label.configure(text=f"Saved '{name}' with {len(ids)} identities.", text_color=theme.ACCENT_OLIVE)
            load_group_list()
            existing_var.set(name)
            self.refresh_identity_view_dropdown()

        def on_delete():
            name = existing_var.get()
            if not name:
                status_label.configure(text="Select an existing group to delete first.", text_color=theme.ACCENT_RED)
                return
            self.db.delete_identity_group(name, stype)
            status_label.configure(text=f"Deleted '{name}'.", text_color=theme.ACCENT_OLIVE)
            name_entry.delete(0, "end")
            ids_entry.delete(0, "end")
            existing_var.set("")
            load_group_list()
            self.refresh_identity_view_dropdown()

        btns = ctk.CTkFrame(dialog)
        btns.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(btns, text="Save", command=on_save).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Delete Selected", command=on_delete,
            fg_color=theme.ACCENT_RED, hover_color="#dc2626",
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Close", command=dialog.destroy,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY,
        ).pack(side="left", padx=4)

        load_group_list()

    def on_sync_mode_changed(self, _value=None):
        """Toggle between Full History and Single Tour sync modes."""
        mode = self.sync_mode_var.get()
        if mode == "Single Tour":
            # Show tour selector
            self.single_tour_label.pack(side="left", padx=(12, 4))
            self.single_tour_dropdown.pack(side="left", padx=4)
            self.fetch_tours_btn.pack(side="left", padx=4)
            self.sync_btn.configure(text="Sync This Tour")

            if self._tour_label_to_id:
                self.status_label.configure(
                    text=f"{len(self._tour_label_to_id)} tours available - select one and click 'Sync This Tour'",
                    text_color=theme.ACCENT_OLIVE
                )
            else:
                self.status_label.configure(
                    text="Click 'Fetch Tours' to load the tour list, then pick one",
                    text_color="#ff9900"
                )
        else:
            # Hide tour selector
            self.single_tour_label.pack_forget()
            self.single_tour_dropdown.pack_forget()
            self.fetch_tours_btn.pack_forget()
            self.sync_btn.configure(text="Sync Full History")
            self.status_label.configure(
                text="Enter Pilot ID above, then click 'Sync Full History'",
                text_color="#999"
            )

    def on_fetch_tours_clicked(self):
        """Populate the tour list (and _tour_label_to_id) for Single Tour
        mode. Cheap no-op if tours are already cached - just re-reads
        from the DB, so safe to click any time the dropdown looks empty
        or stale (e.g. after switching arenas)."""
        self.fetch_tours_btn.configure(state="disabled")
        self.status_label.configure(text="Discovering tours...", text_color=theme.ACCENT_OLIVE)

        def worker():
            try:
                sync.ensure_tour_list(self.client, self.db)
                self.progress_queue.put(("TOURS_FETCHED",))
            except Exception as e:
                self.progress_queue.put(("TOURS_FETCH_ERROR", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- tabs ----------------

    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self._build_career_tab(self.tabs.add("Career Summary"))
        self._build_tour_tab(self.tabs.add("Tour Detail"))
        self._build_category_tab(self.tabs.add("Tour History"))
        self._build_planes_tab(self.tabs.add("Kills by Plane"))
        self._build_squad_tab(self.tabs.add("Squad"))
        self._build_arena_tab(self.tabs.add("Arena Planes"))
        self._build_graphs_tab(self.tabs.add("Graphs"))

    @staticmethod
    def _make_grid(parent, columns, height=10):
        """A sortable, filterable, scrollable grid whose first column is
        the wide label column (plane name, member name, metric...)."""
        grid = GridView(parent, height=height, wide=(columns[0],))
        grid.set_columns(columns, wide=(columns[0],))
        for name in columns[1:]:
            grid.tree.column(name, width=110, anchor="center")
        grid.tree.column(columns[0], width=170, anchor="w")
        return grid

    def _build_career_tab(self, frame):
        self.career_status_label = ctk.CTkLabel(
            frame, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=theme.ACCENT_OLIVE
        )
        self.career_status_label.pack(anchor="w", padx=10, pady=(10, 0))

        self.career_grid = self._make_grid(frame, ["Metric", "Value"], height=11)
        self.career_grid.pack(fill="x", padx=10, pady=10)

        btns = ctk.CTkFrame(frame)
        btns.pack(fill="x", padx=10, pady=6)
        ctk.CTkButton(
            btns, text="Refresh from Cache", command=self.refresh_career,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Export Tours CSV", command=self.export_tours_csv,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Export Plane Kills CSV", command=self.export_planes_csv,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Export HTML Report", command=self.export_html,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=4)

    def _build_tour_tab(self, frame):
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(top, text="Tour Period:").pack(side="left", padx=4)
        self.tour_var = ctk.StringVar()
        self.tour_dropdown = ctk.CTkOptionMenu(top, variable=self.tour_var, values=[""], command=self.on_tour_selected)
        self.tour_dropdown.pack(side="left", padx=4)
        ctk.CTkButton(
            top, text="Refresh Tour List", command=self.refresh_tour_dropdown,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=4)
        self.fetch_tour_btn = ctk.CTkButton(
            top, text="Fetch This Tour", command=self.on_fetch_single_tour,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.fetch_tour_btn.pack(side="left", padx=4)
        ctk.CTkButton(
            top, text="View Failed Tours", command=self.on_view_errors,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=4)

        self.tour_status_label = ctk.CTkLabel(
            frame, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=theme.ACCENT_OLIVE
        )
        self.tour_status_label.pack(anchor="w", padx=10)

        self.tour_grid = self._make_grid(
            frame, ["Category", "Kills", "Assists", "Sorties", "Landed", "Deaths", "Flight Time", "Rank"], height=10
        )
        self.tour_grid.pack(fill="both", expand=True, padx=10, pady=10)

    def _build_category_tab(self, frame):
        """Spatula's eight per-category grids (Fighter/Attack/Bomber/
        Vehicle-Boat x Score/Stats). He gave each its own tab; with our
        five existing tabs that would be thirteen across the top, so the
        category and view are pickers here instead - same eight grids,
        two clicks to any of them."""
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", padx=10, pady=(10, 0))

        ctk.CTkLabel(top, text="Category:").pack(side="left", padx=(8, 4))
        self.category_var = ctk.StringVar(value="Fighter")
        ctk.CTkSegmentedButton(
            top, values=[label for _, label in CATEGORY_LABELS],
            variable=self.category_var, command=lambda _=None: self.refresh_category(),
        ).pack(side="left", padx=4)

        ctk.CTkLabel(top, text="View:").pack(side="left", padx=(16, 4))
        self.category_view_var = ctk.StringVar(value="Stats")
        ctk.CTkSegmentedButton(
            top, values=["Stats", "Score"],
            variable=self.category_view_var, command=lambda _=None: self.refresh_category(),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            top, text="Refresh from Cache", command=self.refresh_category,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=12)

        self.category_status_label = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=theme.ACCENT_OLIVE
        )
        self.category_status_label.pack(anchor="w", padx=10, pady=(6, 0))

        # Columns are re-applied on every refresh: the Score view's
        # columns depend on which metrics HTC publishes for the category.
        self.category_grid = GridView(frame, height=20, wide=("Details", "Arena"))
        self._add_grid_toolbar(frame, self.category_grid)
        self.category_grid.set_columns(self._STATS_COLUMNS, wide=("Details", "Arena"))
        self.category_grid.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.category_totals_label = self._build_totals_footer(frame, self.category_grid)

    def _add_grid_toolbar(self, frame, grid):
        """Quick-filter box and a clear button for a grid. Sorting and
        per-column filters live on the headings themselves (left-click to
        sort, right-click to filter)."""
        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(4, 4))
        ctk.CTkLabel(bar, text="Filter:").pack(side="left", padx=(0, 4))
        entry = ctk.CTkEntry(bar, width=200, placeholder_text="match any column...")
        entry.pack(side="left", padx=4)
        entry.bind("<KeyRelease>", lambda _e: grid.set_quick_filter(entry.get()))

        def clear():
            entry.delete(0, "end")
            grid.clear_filters()

        ctk.CTkButton(
            bar, text="Clear Filters", command=clear, width=110,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY,
        ).pack(side="left", padx=6)
        ctk.CTkLabel(
            bar, text="click a heading to sort  •  right-click to filter that column",
            font=ctk.CTkFont(size=11), text_color="#8b93a1",
        ).pack(side="left", padx=10)
        return entry

    def _build_totals_footer(self, frame, grid):
        """Spatula's running-totals boxes (his 1.4.0). Totals follow the
        filters, so filtering to one arena or a tour range re-totals."""
        label = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=theme.TEXT_HEADING, anchor="w",
        )
        label.pack(fill="x", padx=12, pady=(0, 8))
        grid.on_change = lambda rows: self._update_totals(label, grid, rows)
        return label

    @staticmethod
    def _update_totals(label, grid, rows):
        """Sum whichever of the totalled columns this grid actually has."""
        columns = grid.columns
        totals = []
        sums = {}
        for name in ("Kills", "Kills In", "Assists", "Sorties", "Deaths", "Died In"):
            if name not in columns:
                continue
            index = columns.index(name)
            values = [gridmod.as_number(r[index]) for r in rows]
            sums[name] = sum(v for v in values if v is not None)
            totals.append(f"Total {name}: {sums[name]:,.0f}")

        kills = sums.get("Kills", sums.get("Kills In"))
        deaths = sums.get("Deaths", sums.get("Died In"))
        if kills is not None and deaths is not None:
            ratio = kills / deaths if deaths else kills
            totals.append(f"Kills/Death: {ratio:,.2f}")

        label.configure(text="     ".join(totals) if totals else "")

    _STATS_COLUMNS = [
        "Tour", "Details", "Arena", "Kills", "Assists", "Sorties", "Landed",
        "Bailed", "Ditched", "Captured", "Deaths", "Disco", "Time",
    ]

    def refresh_category(self):
        gameid = self._effective_gameid()
        stype = self.stype_var.get()
        arena = self._selected_arena()
        category = next(
            (key for key, label in CATEGORY_LABELS if label == self.category_var.get()),
            "fighter",
        )

        if not gameid:
            self.category_grid.set_columns(self._STATS_COLUMNS, wide=("Details", "Arena"))
            self.category_grid.set_rows([])
            self.category_status_label.configure(text="Enter a Pilot ID above.")
            return

        if self.category_view_var.get() == "Score":
            self._refresh_category_scores(gameid, stype, category, arena)
        else:
            self._refresh_category_stats(gameid, stype, category, arena)

    def _category_context(self, gameid, arena, count):
        group = f" [group: {self.identity_view_var.get()}]" if isinstance(gameid, list) else ""
        return f"{count} tour(s){' (' + arena + ')' if arena else ' (all arenas)'}{group}"

    def _refresh_category_stats(self, gameid, stype, category, arena):
        rows = self.db.get_category_stats_series(gameid, stype, category, arena=arena)
        self.category_grid.set_columns(self._STATS_COLUMNS, wide=("Details", "Arena"))
        self.category_grid.set_rows([
            (
                tour_number(row["tourid"]), row["label"], row["arena"],
                row["kills"], row["assists"], row["sorties"], row["landed"],
                row["bailed"], row["ditched"], row["captured"], row["deaths"],
                row["discos"], _fmt_hms(row["time_seconds"]),
            )
            for row in rows
        ])
        self.category_status_label.configure(
            text=f"{self.category_var.get()} stats - {self._category_context(gameid, arena, len(rows))}"
            if rows else "No cached data. Click 'Sync Full History' to fetch."
        )

    def _refresh_category_scores(self, gameid, stype, category, arena):
        metrics, rows = self.db.get_category_scores_series(gameid, stype, category, arena=arena)
        columns = ["Tour", "Details", "Arena"] + [SCORE_HEADERS.get(m, m) for m in metrics]
        self.category_grid.set_columns(columns, wide=("Details", "Arena"))
        table = []
        for row in rows:
            values = [tour_number(row["tourid"]), row["label"], row["arena"]]
            for metric in metrics:
                score = row.get(metric)
                values.append("" if score is None else round(score, 2))
            table.append(tuple(values))
        self.category_grid.set_rows(table)
        self.category_status_label.configure(
            text=f"{self.category_var.get()} score - {self._category_context(gameid, arena, len(rows))}"
            if rows else "No cached data. Click 'Sync Full History' to fetch."
        )

    def _build_planes_tab(self, frame):
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", padx=10, pady=(10, 0))
        # "By Model" is Spatula's Obj v Obj "Group By: Model" - pick an
        # aircraft and see a row per tour instead of a row per aircraft.
        ctk.CTkLabel(top, text="Group by:").pack(side="left", padx=(0, 4))
        self.planes_scope_var = ctk.StringVar(value="Career")
        ctk.CTkSegmentedButton(
            top, values=["Career", "Selected Tour", "By Model"],
            variable=self.planes_scope_var, command=self.on_planes_scope_changed
        ).pack(side="left", padx=4)

        self.planes_model_label = ctk.CTkLabel(top, text="Model:")
        self.planes_model_var = ctk.StringVar()
        self.planes_model_dropdown = ctk.CTkOptionMenu(
            top, variable=self.planes_model_var, values=[""], width=160,
            command=lambda _=None: self.refresh_planes(),
        )

        ctk.CTkButton(
            top, text="Refresh from Cache", command=self.refresh_planes,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=8)
        self.backfill_btn = ctk.CTkButton(
            top, text="Backfill Plane Data", command=self.on_backfill_planes,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY, width=150,
        )
        self.backfill_btn.pack(side="left", padx=4)

        self.planes_status_label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=11))
        self.planes_status_label.pack(anchor="w", padx=10, pady=(6, 0))

        self.planes_grid = self._make_grid(
            frame, ["Plane", "Kills In", "Kills Of", "Killed By", "Died In"], height=20
        )
        self._add_grid_toolbar(frame, self.planes_grid)
        self.planes_grid.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.planes_totals_label = self._build_totals_footer(frame, self.planes_grid)

    # Spatula's Graphs tab, case for case. Each entry says how to get a
    # y-value per tour: a ratio of two stat columns, a single stat, or one
    # of HTC's own published score metrics.
    #   ("ratio", numerator, denominator, denominator_plus_1)
    #   ("value", column, scale)
    #   ("score", metric name)
    GRAPHS = {
        "Kill/Death Trend": ("ratio", "kills", "deaths", True),
        "HTC Kill/Death Trend": ("score", "Kills per Death + 1"),
        "Kill/Landed Trend": ("ratio", "kills", "landed", False),
        "Kill/Sortie Trend": ("ratio", "kills", "sorties", False),
        "Kill/Hour Trend": ("ratio", "kills", "hours", False),
        "Kill/Assist Trend": ("ratio", "kills", "assists", False),
        "Hit % Trend": ("score", "Kills Hit Percentage"),
        "Sorties/Landed Trend": ("ratio", "sorties", "landed", False),
        "Sorties/Death Trend": ("ratio", "sorties", "deaths", True),
        "Total Kills Trend": ("value", "kills", 1),
        "Total Assists Trend": ("value", "assists", 1),
        "Total Sorties Trend": ("value", "sorties", 1),
        "Total Landed Trend": ("value", "landed", 1),
        "Total Bailed Trend": ("value", "bailed", 1),
        "Total Captured Trend": ("value", "captured", 1),
        "Total Death Trend": ("value", "deaths", 1),
        "Total Time Trend": ("value", "time_seconds", 1 / 3600),
    }

    def _build_graphs_tab(self, frame):
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", padx=10, pady=(10, 0))

        ctk.CTkLabel(top, text="Category:").pack(side="left", padx=(8, 4))
        self.graph_category_var = ctk.StringVar(value="Fighter")
        ctk.CTkSegmentedButton(
            top, values=[label for _, label in CATEGORY_LABELS],
            variable=self.graph_category_var, command=lambda _=None: self.refresh_graph(),
        ).pack(side="left", padx=4)

        ctk.CTkLabel(top, text="Graph:").pack(side="left", padx=(16, 4))
        self.graph_var = ctk.StringVar(value="Kill/Death Trend")
        ctk.CTkOptionMenu(
            top, variable=self.graph_var, values=list(self.GRAPHS),
            command=lambda _=None: self.refresh_graph(), width=220,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            top, text="Refresh from Cache", command=self.refresh_graph,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY,
        ).pack(side="left", padx=12)

        self.graph_status_label = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=11), text_color="#8b93a1"
        )
        self.graph_status_label.pack(anchor="w", padx=10, pady=(6, 0))

        self.chart = TrendChart(frame)
        self.chart.pack(fill="both", expand=True, padx=10, pady=10)

    def refresh_graph(self):
        gameid = self._effective_gameid()
        if not gameid:
            self.chart.plot([], message="Enter a Pilot ID above.")
            self.graph_status_label.configure(text="")
            return

        stype = self.stype_var.get()
        arena = self._selected_arena()
        name = self.graph_var.get()
        spec = self.GRAPHS[name]
        category = next(
            (key for key, label in CATEGORY_LABELS if label == self.graph_category_var.get()),
            "fighter",
        )

        points = (
            self._score_points(gameid, stype, category, arena, spec[1])
            if spec[0] == "score"
            else self._stats_points(gameid, stype, category, arena, spec)
        )
        # Plotted oldest-first so the line reads left to right in time.
        points.sort(key=lambda p: p[0])

        title = f"{self.graph_category_var.get()} - {name}"
        arena_label = arena if arena else "all arenas"

        # One point isn't a trend - it draws as a lone dot against an empty
        # grid, which reads as a broken graph rather than as thin data.
        if len(points) < 2:
            category_label = self.graph_category_var.get()
            detail = (
                f"Only 1 tour of {category_label} data cached ({arena_label})"
                if points else
                f"No {category_label} data cached ({arena_label})"
            )
            self.chart.plot(
                [], title=title,
                message=f"{detail}.\nA trend needs at least 2 tours - sync more to plot this.",
            )
            self.graph_status_label.configure(text=detail + " - not enough for a trend")
            return

        self.chart.plot(points, title=title, ylabel=name.replace(" Trend", ""))
        self.graph_status_label.configure(text=f"{len(points)} tour(s) plotted ({arena_label})")

    def _score_points(self, gameid, stype, category, arena, metric):
        _metrics, rows = self.db.get_category_scores_series(gameid, stype, category, arena=arena)
        return [
            (tour_number(row["tourid"]), row[metric])
            for row in rows
            if row.get(metric) is not None
        ]

    def _stats_points(self, gameid, stype, category, arena, spec):
        rows = self.db.get_category_stats_series(gameid, stype, category, arena=arena)
        points = []
        for row in rows:
            if spec[0] == "value":
                _kind, column, scale = spec
                points.append((tour_number(row["tourid"]), (row[column] or 0) * scale))
                continue

            _kind, numerator, denominator, plus_one = spec
            top = row[numerator] or 0
            bottom = (row["time_seconds"] or 0) / 3600 if denominator == "hours" else (row[denominator] or 0)
            if plus_one:
                bottom += 1
            # A tour with no sorties (or no landings, etc.) has no
            # meaningful ratio - leave it out rather than plotting a zero
            # that looks like a bad tour.
            if bottom:
                points.append((tour_number(row["tourid"]), top / bottom))
        return points

    def _build_squad_tab(self, frame):
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(top, text="Player Name:").pack(side="left", padx=4)
        self.squad_player_entry = ctk.CTkEntry(top, width=140, placeholder_text="Enter player name...")
        self.squad_player_entry.pack(side="left", padx=4)
        ctk.CTkButton(
            top, text="Use My ID", command=self.on_use_my_pilot_id,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY,
            width=80
        ).pack(side="left", padx=4)
        ctk.CTkLabel(top, text="Tour:").pack(side="left", padx=(12, 4))
        self.squad_tour_var = ctk.StringVar()
        self.squad_tour_dropdown = ctk.CTkOptionMenu(
            top, variable=self.squad_tour_var, values=[""], width=200
        )
        self.squad_tour_dropdown.pack(side="left", padx=4)
        ctk.CTkButton(
            top, text="Fetch Squad Stats", command=self.on_fetch_squad,
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left", padx=8)

        self.squad_status_label = ctk.CTkLabel(
            frame, text="",
            font=ctk.CTkFont(size=11), text_color="#999"
        )
        self.squad_status_label.pack(anchor="w", padx=10, pady=(0, 10))

        # Add instructional hint
        self.squad_hint_label = ctk.CTkLabel(
            frame,
            text="ℹ️ First time? (1) Enter Pilot ID at top → (2) Click 'Sync Full History' → (3) Return here to select tour",
            font=ctk.CTkFont(size=10),
            text_color="#666",
            wraplength=800,
            justify="left"
        )
        self.squad_hint_label.pack(anchor="w", padx=10, pady=(0, 10))

        self.squad_grid = self._make_grid(
            frame, ["Member", "Kills", "Kill %", "Deaths", "Death %", "K/D", "Active"], height=18
        )
        self._add_grid_toolbar(frame, self.squad_grid)
        self.squad_grid.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.squad_totals_label = self._build_totals_footer(frame, self.squad_grid)

    def _build_arena_tab(self, frame):
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(top, text="Tour:").pack(side="left", padx=4)
        self.arena_tour_var = ctk.StringVar()
        self.arena_tour_dropdown = ctk.CTkOptionMenu(
            top, variable=self.arena_tour_var, values=[""], width=200
        )
        self.arena_tour_dropdown.pack(side="left", padx=4)
        ctk.CTkButton(
            top, text="Fetch Arena Leaderboard", command=self.on_fetch_arena,
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left", padx=8)

        self.arena_status_label = ctk.CTkLabel(
            frame, text="",
            font=ctk.CTkFont(size=11), text_color="#999"
        )
        self.arena_status_label.pack(anchor="w", padx=10, pady=(0, 10))

        # Add instructional hint
        self.arena_hint_label = ctk.CTkLabel(
            frame,
            text="ℹ️ First time? (1) Enter Pilot ID at top → (2) Click 'Sync Full History' → (3) Return here to select tour",
            font=ctk.CTkFont(size=10),
            text_color="#666",
            wraplength=800,
            justify="left"
        )
        self.arena_hint_label.pack(anchor="w", padx=10, pady=(0, 10))

        self.arena_grid = self._make_grid(frame, ["Plane", "Kills", "Deaths", "K/D"], height=18)
        self._add_grid_toolbar(frame, self.arena_grid)
        self.arena_grid.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.arena_totals_label = self._build_totals_footer(frame, self.arena_grid)

    # ---------------- sync (pilot/squad tour history) ----------------

    def _sync_target_ids(self) -> list[str]:
        """Real game IDs to actually fetch from HiTech's servers. Syncing
        always hits literal IDs (never a virtual group), but if the ID field
        is left blank while an identity group is active, fall back to
        syncing every member of that group in turn - this is what users
        expect when they've picked a group in Career View and forgot the
        group is view-only for the ID field itself."""
        gameid = self.gameid_entry.get().strip()
        if gameid:
            return [gameid]
        group = self.identity_view_var.get()
        if group and group != "Single ID":
            members = self.db.get_identity_group_members(group, self.stype_var.get())
            if members:
                return members
        return []

    def on_sync_clicked(self):
        gameids = self._sync_target_ids()
        if not gameids:
            messagebox.showwarning("Missing ID", "Enter a pilot or squad game ID first.")
            return
        if self.sync_thread and self.sync_thread.is_alive():
            return

        stype = self.stype_var.get()
        arena = self._selected_arena()
        sync_mode = self.sync_mode_var.get()

        # Handle Single Tour mode
        if sync_mode == "Single Tour":
            label = self.single_tour_var.get()
            tourid = self._tour_label_to_id.get(label)
            if not tourid:
                messagebox.showwarning("No Tour Selected", "Select a tour from the dropdown first.")
                return

            self.sync_btn.configure(state="disabled")
            status = f"Syncing {label} for {len(gameids)} member(s)..." if len(gameids) > 1 else f"Syncing {label}..."
            self.status_label.configure(text=status)
            self.progress_bar.set(0.5)

            def worker():
                try:
                    flew = [
                        gid for gid in gameids
                        if sync.fetch_single_tour(
                            self.client, self.db, gid, stype, tourid, fetch_plane_kills=True
                        )
                    ]
                    # "No activity" is a real, cached answer - say so rather
                    # than reporting a successful sync of nothing.
                    message = (
                        f"Done - synced {label}"
                        if flew
                        else f"{label}: no recorded activity for {', '.join(gameids)}"
                    )
                    self.progress_queue.put(sync.SyncProgress(1, 1, message))
                except Exception as e:
                    self.progress_queue.put(sync.SyncProgress(0, 1, f"Error: {e}"))
                finally:
                    self.progress_queue.put(("DONE_SYNC",))

            self.sync_thread = threading.Thread(target=worker, daemon=True)
            self.sync_thread.start()
            return

        # Handle Full History mode
        all_tours = self.db.get_tours(arena=arena)
        to_fetch_count = 0
        for gid in gameids:
            cached_tourids = self.db.get_pilot_tourids(gid, stype, arena=arena)
            to_fetch_count += sum(
                1 for t in all_tours
                if t["tourid"] not in cached_tourids or sync._is_tour_live(t)
            )

        if to_fetch_count > 10:  # Only warn for large syncs
            est_minutes = (to_fetch_count * 3) // 60  # 3 sec per tour minimum
            member_note = f" across {len(gameids)} member(s)" if len(gameids) > 1 else ""
            confirm = messagebox.askyesno(
                "Long Sync Ahead",
                f"This will fetch {to_fetch_count} tours{member_note} and take approximately "
                f"{est_minutes}-{est_minutes + 5} minutes.\n\nContinue?"
            )
            if not confirm:
                return

        self.stop_event = threading.Event()
        self.sync_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="Starting sync...")
        self.progress_bar.set(0)
        stop_event = self.stop_event

        def worker():
            def progress_cb(p: sync.SyncProgress):
                self.progress_queue.put(p)
            try:
                for gid in gameids:
                    if stop_event.is_set():
                        break
                    sync.sync_pilot(
                        self.client, self.db, gid, stype, arena=arena,
                        progress_cb=progress_cb, stop_event=stop_event,
                    )
            except Exception as e:
                self.progress_queue.put(sync.SyncProgress(0, 1, f"Error: {e}"))
            finally:
                self.progress_queue.put(("DONE_SYNC",))

        self.sync_thread = threading.Thread(target=worker, daemon=True)
        self.sync_thread.start()

    def on_stop_clicked(self):
        self.stop_event.set()
        self.status_label.configure(text="Stopping...")

    def _check_incomplete_syncs(self):
        """Called on startup to offer resuming interrupted syncs."""
        gameid = self.gameid_entry.get().strip()
        if not gameid:
            return

        stype = self.stype_var.get()
        incomplete = self.db.get_incomplete_syncs(gameid, stype)
        if not incomplete:
            return

        incomplete_sync = incomplete[0]  # Most recent
        arena_label = incomplete_sync["arena"] if incomplete_sync["arena"] else "all arenas"
        response = messagebox.askyesno(
            "Resume Interrupted Sync?",
            f"Found incomplete sync from {incomplete_sync['started_at'][:10]} for {arena_label}.\n"
            f"Progress: {incomplete_sync['tours_processed']}/{incomplete_sync['total_tours']} tours.\n\n"
            f"Resume where you left off?"
        )

        if response:
            self._resume_sync(incomplete_sync["sync_id"])

    def _resume_sync(self, sync_id: str):
        """Resume a paused sync."""
        if self.sync_thread and self.sync_thread.is_alive():
            return

        gameid = self.gameid_entry.get().strip()
        stype = self.stype_var.get()
        arena = self._selected_arena()

        self.stop_event = threading.Event()
        self.sync_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="Resuming sync...")
        self.progress_bar.set(0)

        stop_event = self.stop_event

        def worker():
            def progress_cb(p: sync.SyncProgress):
                self.progress_queue.put(p)
            try:
                sync.sync_pilot(
                    self.client, self.db, gameid, stype, arena=arena,
                    progress_cb=progress_cb, stop_event=stop_event,
                    resume_sync_id=sync_id,
                )
            except Exception as e:
                self.progress_queue.put(sync.SyncProgress(0, 1, f"Error: {e}"))
            finally:
                self.progress_queue.put(("DONE_SYNC",))

        self.sync_thread = threading.Thread(target=worker, daemon=True)
        self.sync_thread.start()

    def _poll_queue(self):
        try:
            while True:
                item = self.progress_queue.get_nowait()
                if isinstance(item, sync.SyncProgress):
                    self.status_label.configure(text=item.message)
                    if item.total:
                        self.progress_bar.set(item.current / item.total)
                    continue

                tag = item[0]
                if tag == "DONE_SYNC":
                    self.sync_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.refresh_career()
                    self.refresh_tour_dropdown()
                    self.refresh_planes()
                    self.refresh_category()
                    self.refresh_graph()
                elif tag == "SQUAD_RESULT":
                    self._show_squad_results(item[1])
                elif tag == "ARENA_RESULT":
                    self._show_arena_results(item[1])
                elif tag == "TOUR_FETCH_DONE":
                    self.fetch_tour_btn.configure(state="normal")
                    if self.tour_var.get() == item[1]:
                        self.on_tour_selected(item[1])
                    self.refresh_career()
                    self.refresh_planes()
                    self.refresh_category()
                    self.refresh_graph()
                elif tag == "BACKFILL_DONE":
                    self.backfill_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status_label.configure(
                        text=f"Backfill complete - filled {item[1]} tour(s)",
                        text_color=theme.ACCENT_OLIVE,
                    )
                    self._refresh_model_dropdown()
                    self.refresh_planes()
                elif tag == "BACKFILL_ERROR":
                    self.backfill_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status_label.configure(text=f"Backfill error: {item[1]}", text_color="#ff0000")
                elif tag == "TOUR_FETCH_ERROR":
                    self.fetch_tour_btn.configure(state="normal")
                    self.tour_status_label.configure(text=f"Error: {item[1]}")
                elif tag == "TOURS_FETCHED":
                    self.fetch_tours_btn.configure(state="normal")
                    self.refresh_tour_dropdown()
                    count = len(self._tour_label_to_id)
                    if count:
                        self.status_label.configure(
                            text=f"{count} tours available - select one and click 'Sync This Tour'",
                            text_color=theme.ACCENT_OLIVE
                        )
                    else:
                        self.status_label.configure(text="No tours found.", text_color="#ff9900")
                elif tag == "TOURS_FETCH_ERROR":
                    self.fetch_tours_btn.configure(state="normal")
                    self.status_label.configure(text=f"Error loading tours: {item[1]}", text_color="#ff0000")
        except queue.Empty:
            pass
        self._poll_after_id = self.after(150, self._poll_queue)

    # ---------------- career ----------------

    def refresh_career(self):
        gameid = self._effective_gameid()
        stype = self.stype_var.get()
        self.career_grid.set_rows([])
        if not gameid:
            self.career_status_label.configure(text="")
            return

        arena = self._selected_arena()
        career = self.db.get_career_totals(gameid, stype, arena=arena)
        if not career or not career["tours"]:
            arena_name = arena if arena else "all arenas"
            self.career_status_label.configure(text=f"No cached data for {arena_name}. Click 'Sync Full History' to fetch.")
            self.career_grid.set_rows([("No cached data yet", "")])
            return

        group_label = f" [group: {self.identity_view_var.get()}]" if isinstance(gameid, list) else ""
        arena_label = f" ({arena})" if arena else " (all arenas)"
        self.career_status_label.configure(
            text=f"Showing career totals from {career['tours']} tour(s){arena_label}{group_label}"
        )

        kills = career["kills"] or 0
        deaths = career["deaths"] or 0
        kd = round(kills / deaths, 2) if deaths else kills
        rows = [
            ("Tours Synced", career["tours"]),
            ("Total Kills", kills),
            ("Total Assists", career["assists"]),
            ("Total Sorties", career["sorties"]),
            ("Total Deaths", deaths),
            ("Career K/D", kd),
            ("Total Landed", career["landed"]),
            ("Total Bailed", career["bailed"]),
            ("Total Ditched", career["ditched"]),
            ("Total Captured", career["captured"]),
            ("Flight Time", _fmt_hms(career["time_seconds"])),
        ]
        self.career_grid.set_rows(rows)

    # ---------------- tour detail ----------------

    def refresh_tour_dropdown(self):
        """Lists every known tour for the selected arena, cached or not,
        so a pilot can pick a specific period and fetch just that one.
        Reads from cache only - run a sync first to discover tours on a
        fresh install (avoids blocking the GUI thread on a network call)."""
        tours = list(self.db.get_tours(arena=self._selected_arena()))
        tours.sort(key=lambda t: t["start_date"] or "", reverse=True)

        self._tour_label_to_id = {t["label"]: t["tourid"] for t in tours}
        labels = [t["label"] for t in tours]

        # Update Tour Detail dropdown
        self.tour_dropdown.configure(values=labels or [""])
        if labels:
            self.tour_var.set(labels[0])
            self.on_tour_selected(labels[0])
        else:
            self.tour_var.set("")
            self.tour_grid.set_rows([])
            self.tour_status_label.configure(text="")

        # Also update Squad dropdown
        self.squad_tour_dropdown.configure(values=labels or [""])
        if labels:
            self.squad_tour_var.set(labels[0])
            self.squad_status_label.configure(
                text=f"✓ Tours loaded. Enter player name, select tour, then click 'Fetch Squad Stats'",
                text_color=theme.ACCENT_OLIVE
            )
            # Hide the workflow hint once tours are loaded
            self.squad_hint_label.pack_forget()
        else:
            self.squad_tour_var.set("")
            self.squad_status_label.configure(
                text="⚠️ No tours available. Go to top of window → Enter Pilot ID → Click 'Sync Full History'",
                text_color="#ff9900"
            )
            # Show the workflow hint when no tours
            self.squad_hint_label.pack(anchor="w", padx=10, pady=(0, 10))

        # Also update Arena Planes dropdown
        self.arena_tour_dropdown.configure(values=labels or [""])
        if labels:
            self.arena_tour_var.set(labels[0])
            self.arena_status_label.configure(
                text=f"✓ Tours loaded. Select tour above, then click 'Fetch Arena Leaderboard'",
                text_color=theme.ACCENT_OLIVE
            )
            # Hide the workflow hint once tours are loaded
            self.arena_hint_label.pack_forget()
        else:
            self.arena_tour_var.set("")
            self.arena_status_label.configure(
                text="⚠️ No tours available. Go to top of window → Enter Pilot ID → Click 'Sync Full History'",
                text_color="#ff9900"
            )
            # Show the workflow hint when no tours
            self.arena_hint_label.pack(anchor="w", padx=10, pady=(0, 10))

        # Also update Single Tour dropdown (for sync mode)
        self.single_tour_dropdown.configure(values=labels or [""])
        if labels:
            self.single_tour_var.set(labels[0])

    def on_tour_selected(self, label):
        gameid = self._effective_gameid()
        stype = self.stype_var.get()
        tourid = self._tour_label_to_id.get(label)
        self.tour_grid.set_rows([])
        if not tourid:
            self.tour_status_label.configure(text="")
            return
        if not gameid or not self.db.has_pilot_tour(gameid, stype, tourid):
            self.tour_status_label.configure(text="Not fetched yet - click 'Fetch This Tour'.")
            return
        rows = list(self.db.get_pilot_totals(gameid, stype, tourid))
        # A cached tour with no sorties is a "did not fly" answer, not a
        # failed fetch - label it so it isn't mistaken for missing data.
        if not any(row["sorties"] for row in rows):
            self.tour_status_label.configure(text=f"No recorded activity in {label}.")
        else:
            self.tour_status_label.configure(text="")
        self.tour_grid.set_rows([
            (
                row["category"], row["kills"], row["assists"], row["sorties"],
                row["landed"], row["deaths"], _fmt_hms(row["time_seconds"]), row["rank"],
            )
            for row in rows
        ])
        # Keep Kills by Plane in sync if it's following the selected tour.
        if self.planes_scope_var.get() == "Selected Tour":
            self.refresh_planes()

    def on_fetch_single_tour(self):
        gameids = self._sync_target_ids()
        stype = self.stype_var.get()
        label = self.tour_var.get()
        tourid = self._tour_label_to_id.get(label)
        if not gameids or not tourid:
            messagebox.showwarning("Missing info", "Enter a pilot/squad ID and pick a tour first.")
            return

        self.fetch_tour_btn.configure(state="disabled")
        self.tour_status_label.configure(text=f"Fetching {label}...")

        def worker():
            try:
                for gid in gameids:
                    sync.fetch_single_tour(self.client, self.db, gid, stype, tourid)
            except Exception as e:
                self.progress_queue.put(("TOUR_FETCH_ERROR", str(e)))
            else:
                self.progress_queue.put(("TOUR_FETCH_DONE", label))

        threading.Thread(target=worker, daemon=True).start()

    def on_view_errors(self):
        """Show dialog with recent fetch errors."""
        gameid = self.gameid_entry.get().strip()
        if not gameid:
            messagebox.showwarning("Missing ID", "Enter a pilot or squad game ID first.")
            return

        stype = self.stype_var.get()
        errors = self.db.get_failed_tours(gameid, stype, days=30)
        if not errors:
            messagebox.showinfo("No Errors", "No failed tours in the last 30 days.")
            return

        # Create toplevel window with error list
        dialog = ctk.CTkToplevel(self)
        dialog.title("Failed Tours")
        dialog.geometry("700x400")

        tree = self._make_grid(dialog, ["Tour", "Error", "Date"], height=15)
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        tree.set_rows([
            (err["tourid"], err["error_message"][:60], err["occurred_at"][:10])
            for err in errors
        ])

        ctk.CTkButton(dialog, text="Close", command=dialog.destroy).pack(pady=10)

    # ---------------- kills by plane ----------------

    def on_planes_scope_changed(self, _value=None):
        """Show the model picker only in By Model mode."""
        by_model = self.planes_scope_var.get() == "By Model"
        if by_model:
            self.planes_model_label.pack(side="left", padx=(12, 4))
            self.planes_model_dropdown.pack(side="left", padx=4)
            self._refresh_model_dropdown()
        else:
            self.planes_model_label.pack_forget()
            self.planes_model_dropdown.pack_forget()
        self.refresh_planes()

    def _refresh_model_dropdown(self):
        gameid = self._effective_gameid()
        planes = self.db.get_matrix_planes(gameid, arena=self._selected_arena()) if gameid else []
        self.planes_model_dropdown.configure(values=planes or [""])
        if planes and self.planes_model_var.get() not in planes:
            self.planes_model_var.set(planes[0])
        elif not planes:
            self.planes_model_var.set("")

    _MODEL_COLUMNS = ["Tour", "Details", "Arena", "Kills In", "Kills Of", "Killed By", "Died In", "Kills/Death"]
    _PLANE_COLUMNS = ["Plane", "Kills In", "Kills Of", "Killed By", "Died In"]

    def refresh_planes(self):
        gameid = self._effective_gameid()
        stype = self.stype_var.get()
        scope = self.planes_scope_var.get()

        if scope != "By Model" and self.planes_grid.columns != tuple(self._PLANE_COLUMNS):
            self.planes_grid.set_columns(self._PLANE_COLUMNS, wide=("Plane",))
        self.planes_grid.set_rows([])
        if not gameid:
            self.planes_status_label.configure(text="")
            return

        if scope == "By Model":
            self._refresh_planes_by_model(gameid)
            return

        if self.planes_scope_var.get() == "Selected Tour":
            label = self.tour_var.get()
            tourid = self._tour_label_to_id.get(label)
            if not tourid:
                self.planes_status_label.configure(text="No tour selected - pick one on the Tour Detail tab first.")
                return
            if not self.db.has_pilot_tour(gameid, stype, tourid):
                self.planes_status_label.configure(text=f"{label} isn't fetched yet - use 'Fetch This Tour' on the Tour Detail tab.")
                return
            self.planes_status_label.configure(text=f"Showing {label} only")
            self.planes_grid.set_rows([
                (row["plane"], row["kills_in"], row["kills_of"], row["killed_by"], row["died_in"])
                for row in self.db.get_pilot_plane_matrix(gameid, tourid)
            ])
            return

        # Show how many tours are being aggregated
        arena = self._selected_arena()
        cached_tourids = self.db.get_pilot_tourids(gameid, stype, arena=arena)
        tour_count = len(cached_tourids)

        if tour_count == 0:
            arena_name = arena if arena else "all arenas"
            self.planes_status_label.configure(text=f"No cached data for {arena_name}. Click 'Sync Full History' to fetch.")
            return

        arena_label = f" ({arena})" if arena else " (all arenas)"
        self.planes_status_label.configure(text=f"Showing career totals from {tour_count} tour(s){arena_label}")

        self.planes_grid.set_rows([
            (row["plane"], row["kills_in"], row["kills_of"], row["killed_by"], row["died_in"])
            for row in self.db.get_career_plane_matrix(gameid, arena=arena)
        ])

    def _refresh_planes_by_model(self, gameid):
        arena = self._selected_arena()
        plane = self.planes_model_var.get()
        self.planes_grid.set_columns(self._MODEL_COLUMNS, wide=("Details", "Arena"))
        if not plane:
            self.planes_status_label.configure(
                text="No per-plane data cached yet - use 'Backfill Plane Data' or sync a tour."
            )
            self.planes_grid.set_rows([])
            return

        rows = self.db.get_plane_matrix_series(gameid, plane, arena=arena)
        table = []
        for row in rows:
            died_in = row["died_in"] or 0
            kills_in = row["kills_in"] or 0
            # Spatula's Kills/Death column: deaths+1, so a tour with kills
            # and no deaths still gets a finite, comparable number.
            table.append((
                tour_number(row["tourid"]), row["label"], row["arena"],
                kills_in, row["kills_of"], row["killed_by"], died_in,
                round(kills_in / (died_in + 1), 2),
            ))
        self.planes_grid.set_rows(table)
        self.planes_status_label.configure(
            text=f"{plane} across {len(rows)} tour(s){' (' + arena + ')' if arena else ' (all arenas)'}"
            if rows else f"No cached data for {plane}."
        )

    def on_backfill_planes(self):
        """Fill in per-plane matrix data for tours synced before that
        endpoint was wired up. Rate-limited like any other fetch, so this
        is slow for a long career - hence the confirmation."""
        gameid = self.gameid_entry.get().strip()
        if not gameid:
            messagebox.showwarning("No Pilot ID", "Enter your Pilot ID first.")
            return
        stype = self.stype_var.get()
        arena = self._selected_arena()
        missing = self.db.get_tourids_missing_matrix(gameid, stype, arena=arena)
        if not missing:
            messagebox.showinfo("Nothing to do", "Every cached tour already has per-plane data.")
            return

        minutes = max(1, round(len(missing) * 3 / 60))
        if not messagebox.askyesno(
            "Backfill Plane Data",
            f"{len(missing)} tour(s) are missing per-plane data.\n\n"
            f"Fetching them takes roughly {minutes} minute(s) at the 3-second "
            f"rate limit. You can press Stop at any time.\n\nStart now?",
        ):
            return

        self.stop_event.clear()
        self.backfill_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        def worker():
            try:
                filled = sync.backfill_plane_matrix(
                    self.client, self.db, gameid, missing,
                    progress_cb=self.progress_queue.put,
                    stop_event=self.stop_event,
                )
                self.progress_queue.put(("BACKFILL_DONE", filled))
            except Exception as e:
                self.progress_queue.put(("BACKFILL_ERROR", str(e)))

        self.sync_thread = threading.Thread(target=worker, daemon=True)
        self.sync_thread.start()

    # ---------------- squad (one-off, per tour) ----------------

    def on_use_my_pilot_id(self):
        """Copy pilot ID from main field to squad player field."""
        pilot_id = self.gameid_entry.get().strip()
        if pilot_id:
            self.squad_player_entry.delete(0, "end")
            self.squad_player_entry.insert(0, pilot_id)
            self.squad_status_label.configure(
                text=f"Ready to fetch squad roster for {pilot_id}",
                text_color=theme.ACCENT_OLIVE
            )
        else:
            messagebox.showwarning("No Pilot ID", "Enter your Pilot ID in the main field first.")

    def on_fetch_squad(self):
        player = self.squad_player_entry.get().strip() or self.gameid_entry.get().strip()
        label = self.squad_tour_var.get()
        tourid = self._tour_label_to_id.get(label)

        if not player:
            messagebox.showwarning("Missing info", "Enter a player name.")
            return

        if not tourid:
            messagebox.showwarning(
                "No Tours Available",
                "The tour list is empty.\n\n"
                "To populate tours:\n"
                "1. Enter your Pilot ID at the top of the window\n"
                "2. Select an arena (e.g., 'Melee (MA)')\n"
                "3. Click 'Sync Full History'\n"
                "4. Return to this tab to select a tour"
            )
            return

        self.squad_status_label.configure(text=f"Fetching squad for {label}...", text_color=theme.ACCENT_OLIVE)

        def worker():
            squad_name = sync.fetch_squad_snapshot(self.client, self.db, player, tourid)
            self.progress_queue.put(("SQUAD_RESULT", (squad_name, tourid)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_squad_results(self, result):
        squad_name, tourid = result
        self.squad_grid.set_rows([])
        if not squad_name:
            self.squad_status_label.configure(
                text="No squad found for that player/tour",
                text_color="#999"
            )
            messagebox.showinfo("No data", "No squad found for that player/tour.")
            return

        self.squad_status_label.configure(
            text=f"Showing squad: {squad_name}",
            text_color=theme.ACCENT_OLIVE
        )
        self.squad_grid.set_rows([
            (
                row["member_name"], row["kills"], row["kill_pct"], row["deaths"],
                row["death_pct"], row["kd_ratio"], "Yes" if row["active"] else "No",
            )
            for row in self.db.get_squad_members(squad_name, tourid)
        ])

    # ---------------- arena planes (one-off, per tour) ----------------

    def on_fetch_arena(self):
        label = self.arena_tour_var.get()
        tourid = self._tour_label_to_id.get(label)

        if not tourid:
            messagebox.showwarning(
                "No Tours Available",
                "The tour list is empty.\n\n"
                "To populate tours:\n"
                "1. Enter your Pilot ID at the top of the window\n"
                "2. Select an arena (e.g., 'Melee (MA)')\n"
                "3. Click 'Sync Full History'\n"
                "4. Return to this tab to select a tour"
            )
            return

        self.arena_status_label.configure(text=f"Fetching arena leaderboard for {label}...", text_color=theme.ACCENT_OLIVE)

        def worker():
            ok = sync.fetch_plane_leaderboard_snapshot(self.client, self.db, tourid)
            self.progress_queue.put(("ARENA_RESULT", (tourid, label) if ok else None))

        threading.Thread(target=worker, daemon=True).start()

    def _show_arena_results(self, result):
        self.arena_grid.set_rows([])
        if not result:
            self.arena_status_label.configure(
                text="No leaderboard found for that tour",
                text_color="#999"
            )
            messagebox.showinfo("No data", "No leaderboard found for that tour.")
            return

        tourid, label = result
        self.arena_status_label.configure(
            text=f"Showing arena leaderboard for {label}",
            text_color=theme.ACCENT_OLIVE
        )

        self.arena_grid.set_rows([
            (row["plane"], row["kills"], row["deaths"], row["kd_ratio"])
            for row in self.db.get_plane_leaderboard(tourid)
        ])

    # ---------------- export ----------------

    def export_tours_csv(self):
        gameid = self.gameid_entry.get().strip()
        if not gameid:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"{gameid}_tours.csv")
        if path:
            export.export_pilot_tours_csv(self.db, gameid, self.stype_var.get(), path)

    def export_planes_csv(self):
        gameid = self.gameid_entry.get().strip()
        if not gameid:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"{gameid}_kills_by_plane.csv")
        if path:
            export.export_pilot_plane_kills_csv(self.db, gameid, path)

    def export_html(self):
        gameid = self.gameid_entry.get().strip()
        if not gameid:
            return
        path = filedialog.asksaveasfilename(defaultextension=".html", initialfile=f"{gameid}_report.html")
        if path:
            export.export_html_report(self.db, gameid, self.stype_var.get(), path)

    # ---------------- lifecycle ----------------

    def on_close(self):
        self.stop_event.set()
        self.db.close()
        self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
