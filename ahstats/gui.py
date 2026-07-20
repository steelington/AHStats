"""customtkinter GUI for looking up and caching Aces High stats."""
from __future__ import annotations

import queue
import threading
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image

from ahstats import export, sync, theme
from ahstats.client import AhScoreClient
from ahstats.db import ARENA_CHOICES, StatsDB

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
        self.title("Aces High Stats")
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

        self._build_top_bar()
        self._build_tabs()
        self._poll_queue()
        self.after(500, self._check_incomplete_syncs)  # Check for interrupted syncs after GUI loads

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
        ctk.CTkLabel(
            title_frame, text="ACES HIGH STATS", text_color=theme.TEXT_HEADING,
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(anchor="w")
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
        ctk.CTkSegmentedButton(bar, values=["pilot", "squad"], variable=self.stype_var).pack(side="left", padx=8)

        ctk.CTkLabel(bar, text="Arena:").pack(side="left", padx=(12, 4))
        self.arena_var = ctk.StringVar(value=ARENA_CHOICES[0])  # Melee (MA) - what most pilots want
        ctk.CTkSegmentedButton(
            bar, values=ARENA_PICKER_VALUES, variable=self.arena_var, command=self.on_arena_changed
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
        self._build_planes_tab(self.tabs.add("Kills by Plane"))
        self._build_squad_tab(self.tabs.add("Squad"))
        self._build_arena_tab(self.tabs.add("Arena Planes"))

    @staticmethod
    def _make_tree(parent, columns, height=10):
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=height)
        for c in columns:
            tree.heading(c, text=c)
            tree.column(c, width=110, anchor="center")
        tree.column(columns[0], width=170, anchor="w")
        return tree

    def _build_career_tab(self, frame):
        self.career_status_label = ctk.CTkLabel(
            frame, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=theme.ACCENT_OLIVE
        )
        self.career_status_label.pack(anchor="w", padx=10, pady=(10, 0))

        self.career_tree = self._make_tree(frame, ["Metric", "Value"], height=11)
        self.career_tree.pack(fill="x", padx=10, pady=10)

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

        self.tour_tree = self._make_tree(
            frame, ["Category", "Kills", "Assists", "Sorties", "Landed", "Deaths", "Flight Time", "Rank"], height=10
        )
        self.tour_tree.pack(fill="both", expand=True, padx=10, pady=10)

    def _build_planes_tab(self, frame):
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(top, text="Scope:").pack(side="left", padx=(0, 4))
        self.planes_scope_var = ctk.StringVar(value="Career")
        ctk.CTkSegmentedButton(
            top, values=["Career", "Selected Tour"],
            variable=self.planes_scope_var, command=self.on_planes_scope_changed
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            top, text="Refresh from Cache", command=self.refresh_planes,
            fg_color=theme.PANEL_BG_ALT, hover_color=theme.BORDER_GRAY
        ).pack(side="left", padx=8)

        self.planes_status_label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=11))
        self.planes_status_label.pack(anchor="w", padx=10, pady=(6, 0))

        self.planes_tree = self._make_tree(
            frame, ["Plane", "Kills In", "Kills Of", "Killed By", "Died In"], height=20
        )
        self.planes_tree.pack(fill="both", expand=True, padx=10, pady=10)

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

        self.squad_tree = self._make_tree(
            frame, ["Member", "Kills", "Kill %", "Deaths", "Death %", "K/D", "Active"], height=18
        )
        self.squad_tree.pack(fill="both", expand=True, padx=10, pady=10)

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

        self.arena_tree = self._make_tree(frame, ["Plane", "Kills", "Deaths", "K/D"], height=18)
        self.arena_tree.pack(fill="both", expand=True, padx=10, pady=10)

    # ---------------- sync (pilot/squad tour history) ----------------

    def on_sync_clicked(self):
        gameid = self.gameid_entry.get().strip()
        if not gameid:
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
            self.status_label.configure(text=f"Syncing {label}...")
            self.progress_bar.set(0.5)

            def worker():
                try:
                    sync.fetch_single_tour(self.client, self.db, gameid, stype, tourid, fetch_plane_kills=True)
                    self.progress_queue.put(sync.SyncProgress(1, 1, f"Done - synced {label}"))
                except Exception as e:
                    self.progress_queue.put(sync.SyncProgress(0, 1, f"Error: {e}"))
                finally:
                    self.progress_queue.put(("DONE_SYNC",))

            self.sync_thread = threading.Thread(target=worker, daemon=True)
            self.sync_thread.start()
            return

        # Handle Full History mode
        all_tours = self.db.get_tours(arena=arena)
        cached_tourids = self.db.get_pilot_tourids(gameid, stype, arena=arena)

        # Count tours that need fetching (uncached or live)
        to_fetch_count = sum(
            1 for t in all_tours
            if t["tourid"] not in cached_tourids or sync._is_tour_live(t)
        )

        if to_fetch_count > 10:  # Only warn for large syncs
            est_minutes = (to_fetch_count * 3) // 60  # 3 sec per tour minimum
            confirm = messagebox.askyesno(
                "Long Sync Ahead",
                f"This will fetch {to_fetch_count} tours and take approximately "
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
                sync.sync_pilot(
                    self.client, self.db, gameid, stype, arena=arena,
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
        self.after(150, self._poll_queue)

    # ---------------- career ----------------

    def refresh_career(self):
        gameid = self.gameid_entry.get().strip()
        stype = self.stype_var.get()
        self.career_tree.delete(*self.career_tree.get_children())
        if not gameid:
            self.career_status_label.configure(text="")
            return

        arena = self._selected_arena()
        career = self.db.get_career_totals(gameid, stype, arena=arena)
        if not career or not career["tours"]:
            arena_name = arena if arena else "all arenas"
            self.career_status_label.configure(text=f"No cached data for {arena_name}. Click 'Sync Full History' to fetch.")
            self.career_tree.insert("", "end", values=("No cached data yet", ""))
            return

        arena_label = f" ({arena})" if arena else " (all arenas)"
        self.career_status_label.configure(text=f"Showing career totals from {career['tours']} tour(s){arena_label}")

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
        for r in rows:
            self.career_tree.insert("", "end", values=r)

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
            self.tour_tree.delete(*self.tour_tree.get_children())
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
        gameid = self.gameid_entry.get().strip()
        stype = self.stype_var.get()
        tourid = self._tour_label_to_id.get(label)
        self.tour_tree.delete(*self.tour_tree.get_children())
        if not tourid:
            self.tour_status_label.configure(text="")
            return
        if not gameid or not self.db.has_pilot_tour(gameid, stype, tourid):
            self.tour_status_label.configure(text="Not fetched yet - click 'Fetch This Tour'.")
            return
        self.tour_status_label.configure(text="")
        for row in self.db.get_pilot_totals(gameid, stype, tourid):
            self.tour_tree.insert("", "end", values=(
                row["category"], row["kills"], row["assists"], row["sorties"],
                row["landed"], row["deaths"], _fmt_hms(row["time_seconds"]), row["rank"],
            ))
        # Keep Kills by Plane in sync if it's following the selected tour.
        if self.planes_scope_var.get() == "Selected Tour":
            self.refresh_planes()

    def on_fetch_single_tour(self):
        gameid = self.gameid_entry.get().strip()
        stype = self.stype_var.get()
        label = self.tour_var.get()
        tourid = self._tour_label_to_id.get(label)
        if not gameid or not tourid:
            messagebox.showwarning("Missing info", "Enter a pilot/squad ID and pick a tour first.")
            return

        self.fetch_tour_btn.configure(state="disabled")
        self.tour_status_label.configure(text=f"Fetching {label}...")

        def worker():
            try:
                sync.fetch_single_tour(self.client, self.db, gameid, stype, tourid)
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

        tree = self._make_tree(dialog, ["Tour", "Error", "Date"], height=15)
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        for err in errors:
            tree.insert("", "end", values=(
                err["tourid"], err["error_message"][:60], err["occurred_at"][:10]
            ))

        ctk.CTkButton(dialog, text="Close", command=dialog.destroy).pack(pady=10)

    # ---------------- kills by plane ----------------

    def on_planes_scope_changed(self, _value=None):
        self.refresh_planes()

    def refresh_planes(self):
        gameid = self.gameid_entry.get().strip()
        stype = self.stype_var.get()
        self.planes_tree.delete(*self.planes_tree.get_children())
        if not gameid:
            self.planes_status_label.configure(text="")
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
            for row in self.db.get_pilot_plane_matrix(gameid, tourid):
                self.planes_tree.insert("", "end", values=(
                    row["plane"], row["kills_in"], row["kills_of"], row["killed_by"], row["died_in"],
                ))
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

        for row in self.db.get_career_plane_matrix(gameid, arena=arena):
            self.planes_tree.insert("", "end", values=(
                row["plane"], row["kills_in"], row["kills_of"], row["killed_by"], row["died_in"],
            ))

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
        self.squad_tree.delete(*self.squad_tree.get_children())
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
        for row in self.db.get_squad_members(squad_name, tourid):
            self.squad_tree.insert("", "end", values=(
                row["member_name"], row["kills"], row["kill_pct"], row["deaths"],
                row["death_pct"], row["kd_ratio"], "Yes" if row["active"] else "No",
            ))

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
        self.arena_tree.delete(*self.arena_tree.get_children())
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

        for row in self.db.get_plane_leaderboard(tourid):
            self.arena_tree.insert("", "end", values=(row["plane"], row["kills"], row["deaths"], row["kd_ratio"]))

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
