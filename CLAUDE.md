# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AHSTATS is a Python desktop application for viewing Aces High (MMOG) pilot and squad statistics. It scrapes and caches data from HiTech Creations' public stats pages into a SQLite database and presents it via a customtkinter GUI. This is a modern redesign of the legacy C# .NET application in `legacy_source/`.

## Running the Application

```bash
python app.py
```

Entry point: `app.py` imports and calls `ahstats.gui.main()`

## Dependencies

Declared in `requirements.txt` (`pip install -r requirements.txt`):
- **customtkinter** - Modern dark-mode tkinter wrapper for GUI
- **requests** - HTTP client with SSL handling
- **beautifulsoup4** + **lxml** - HTML parsing
- **Pillow** - Image handling
- **certifi** - CA certificate bundle

Tests run with pytest (`python -m pytest tests/ -q`), which is not in
`requirements.txt` - install it separately.

## Architecture

### Core Module Organization

**ahstats/** contains 15 modules (~5,100 lines total). Line counts below are
approximate and drift; don't trust them for anything but a sense of scale.

1. **gui.py** (~1,800 lines) - Main application window with 7 tabs:
   - Career Summary: Aggregated stats across all tours
   - Tour Detail: Per-tour breakdowns by category
   - Tour History: One row per tour, per category, in Stats or Score view
   - Kills by Plane: Matrix of kills in/of/by/died-in per aircraft
   - Squad: One-off squad member roster and stats
   - Arena Planes: Leaderboard of aircraft performance
   - Graphs: 17 trend types per category
   Also owns the sync bar (Full History / Tour Range / Single Tour), the
   progress ticker, and the identity-group editor dialog.

2. **db.py** (~900 lines) - SQLite persistence layer:
   - `tours`, `pilot_totals`, `pilot_scores`, `pilot_plane_kills`,
     `pilot_plane_matrix`, `squad_snapshots`, `squad_members`,
     `plane_leaderboard`, `identity_groups`
   - Sync tracking: `sync_progress`, `sync_tour_checkpoints`, `sync_errors`
   - Thread-safe with explicit locking for concurrent access
   - Aggregation queries for career totals, plane kill matrices
   - Arena/era classification of tour ids (see below)

3. **parser.py** (~530 lines) - BeautifulSoup HTML parsers for 5 endpoints
   - Table-based HTML with no CSS selectors available
   - Parsing done by matching header text in `<th>` elements
   - Dataclasses: `PilotTourScores`, `SquadStats`, `PlaneLeaderboard`, etc.
   - Regex helpers: `_to_int()`, `_to_float()`, `_to_seconds()` for extracting values

4. **client.py** (~190 lines) - HTTP client with special SSL handling
   - Rate-limited: 3+ second delay between requests
   - Fetches missing Sectigo intermediate certificate and caches to `_cache/ca_bundle.pem`
   - User-Agent spoofing for browser compatibility
   - Endpoints: `www.hitechcreations.com/component/ahscore/`, `bbs.hitechcreations.com/scores/`

5. **sync.py** (~260 lines) - Fetch orchestration layer
   - `sync_pilot(...)` - Full history download with tour discovery; the
     optional `tour_range=(first, last)` narrows it to a span of tour
     numbers (inclusive, within the selected arena)
   - `fetch_single_tour(pilot, tourid, callback)` - Single tour refresh
   - `fetch_squad_snapshot()`, `fetch_plane_leaderboard_snapshot()` - One-off queries
   - Checkpointing and resume; smart re-fetch detection only updates live tours

6. **export.py** (~360 lines) - Data export to CSV and HTML
   - `export_pilot_tours_csv()` - Per-tour summary
   - `export_pilot_plane_kills_csv()` - Career kills-by-plane matrix
   - `export_html_report()` - Self-contained interactive HTML with embedded JSON

7. **grid.py** (~280 lines) - `GridView`, the sortable/filterable/exportable
   grid every tab's table is built on (left-click a heading to sort,
   right-click to filter, quick-filter box, running-totals footer support)

8. **picker.py** (~235 lines) - `SearchableSelect`, a type-to-filter dropdown
   used for the tour pickers. Drop-in for `CTkOptionMenu` (`variable`,
   `values`, `command`, `width`, `configure(values=...)`). Needed because Tk
   renders a 300-entry option menu with scroll arrows and no wheel or
   scrollbar. Matches rank exact > prefix > substring, stable-sorted, so
   typing "Tour 21" puts Tour 21 above Tour 210-219.

9. **chart.py** (~170 lines) - `TrendChart`, the canvas-drawn line chart behind
   the Graphs tab (no external plotting dependency)

10. **theme.py** (~100 lines) - UI theming
    - Color palette matching hitechcreations.com CSS (olive/amber WW2 aesthetic)
    - ttk.Treeview styling for dark mode compatibility
    - References `assets/htc_theme.json` for customtkinter config

11. **paths.py** (~45 lines) - App data dir and PyInstaller-aware
    `resource_path()`

12. **logger.py** (~35 lines) - Centralized logging to `ahstats.log`

13. **version_check.py** (~140 lines) - Asks GitHub whether a newer release
    exists. One anonymous GET to the public releases API of
    `steelington/AHStats`; no telemetry, nothing collected, nothing
    downloaded. Every failure - offline, rate-limited, odd tag - resolves
    to "no update" silently. `gui.App` starts it on a daemon thread at
    launch and shows a masthead badge if something newer turns up.

14. **settings.py** (~60 lines) - A tiny JSON key/value store in the app
    data dir for UI preferences (currently just `appearance_mode`).
    Deliberately not the database: it has to be readable before the app
    has decided anything, and a corrupt file must be a shrug, not a
    crash.

15. **__init__.py** - `__version__`, the single source of truth for the version
    shown in the window title and masthead. Bump it in the same commit that
    tags a release.

### Data Flow

```
HiTech Website HTML
    ↓ (client.py - rate-limited HTTP)
parser.py (BeautifulSoup extraction)
    ↓ (dataclasses)
db.py (SQLite persistence)
    ↓ (aggregation queries)
gui.py (customtkinter display)
    ↓ (export.py)
CSV / HTML reports
```

### Threading Model

- GUI runs on main thread
- Sync operations run on background thread (see `gui.py:on_sync_clicked()`)
- Progress updates via `queue.Queue` polled every 100ms by GUI
- The progress detail line is redrawn on its own 250ms `after()` ticker
  (`gui.py:_tick_progress()`) reading counters the sync thread published, so it
  keeps moving through the 3s rate-limit gap between fetches
- Database uses `threading.Lock` for concurrent access safety

### Database Schema Notes

- `tours` table has: `tourid` (primary key), `label`, `start_date`, `end_date`, `arena`
- `pilot_totals` stores per-tour aggregated stats (kills, assists, sorties, deaths, etc.) by category
- `pilot_plane_kills` tracks weekly kill breakdown by aircraft type
- All queries filter by `arena` field for multi-arena support

### Arena and Era Classification (non-obvious domain knowledge)

`arena` is derived from the tour id by `db._arena_for_tourid()` and **stored**,
not computed on read. The prefixes are straightforward:

| Prefix | Arena |
|---|---|
| `LWTour` | Melee (MA) |
| `CtTour` | AvA (CT) |
| `WW1Tour` | WWI |
| `EWTour` | Early War (EW) - retired ~2018 |
| `MWTour` | Mid War (MW) - retired ~2018 |

The trap is the ids with **no prefix at all** (`Tour92`). Aces High ran a single
Main Arena through Tour 92; from Tour 93 it split into Late/Mid/Early War and
the ids gained prefixes. The Late War arena - later renamed Melee - continued
the Main Arena's numbering unbroken: `Tour92` ends 2007-09-30, `LWTour93` begins
2007-10-01. They are one continuous career, so **unprefixed ids map to
"Melee (MA)"**.

Do not invent a separate bucket for them. An earlier build classified them as
`"Legacy"`, which was not in `ARENA_CHOICES` and therefore not selectable in any
picker - 81 tours (Tour12-Tour92, back to 2000-12-26) were unreachable from
every view unless the user picked "All", which also pulled in every other arena.

`db.tour_era()` is what tells the two apart in the UI: it returns
`"Main Arena"` for unprefixed ids and `""` for everything else, and feeds the
**Era** column on the Tour History and Kills-by-Plane-by-model grids.

Because `arena` is stored, databases written by older builds keep the old
classification. `StatsDB.__init__` therefore calls `reclassify_arenas()` on
every open, re-deriving and writing back only rows that differ - existing user
databases repair themselves on next launch. Keep that call if you touch
`__init__`.

HTC's own tour dropdown starts at Tour 12, so Tours 1-11 are not fetchable at
all. That is upstream, not a bug here.

`tests/test_tours.py` covers all of this offline - keep it passing.

### Renamed aircraft (same trap, different column)

HTC has renamed a few planes over the years, and `plane` is stored as
fetched, so one aeroplane can sit in the cache under two names and show as
two rows with the career split between them. `db.PLANE_RENAMES` maps the
superseded name onto the current one (`Ki-61` -> `Ki-61-I-Tei`, `P-40B` ->
`P-40C`; both changed at the tour 92/93 split and never overlap).

Two halves, both needed: the three `save_*` methods normalise on write via
`canonical_plane()`, and `StatsDB.__init__` calls `canonicalize_planes()` on
every open to fold rows older builds wrote - exactly the `reclassify_arenas()`
contract. Adding a rename is one dict entry; keep both calls if you touch
`__init__` or the savers. `tests/test_plane_renames.py` covers it.

### Parsing Strategy

HiTech's HTML has:
- Table-based layouts with no CSS classes or IDs
- Header matching done by text content (e.g., "Total Kills", "Fighter Kills")
- Numeric values extracted via regex (handles commas, negatives)
- Time strings parsed from "hh:mm:ss" or "N days hh:mm:ss" format

### SSL Certificate Handling

HiTech's server doesn't send intermediate cert during TLS handshake. Solution:
1. Fetch Sectigo intermediate from `http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt`
2. Convert DER to PEM, append to certifi bundle
3. Cache to `ahstats/_cache/ca_bundle.pem`
4. Use combined bundle for all requests

See `client.py:_ensure_ca_bundle()` for implementation.

### Rate Limiting

Client enforces 3+ second delay between requests to avoid IP blocking:
- Uses `threading.Lock` + `time.sleep()` in `AhScoreClient._request()`
- Tracks `_last_request_time` to calculate delay
- All HTTP calls go through single shared session

## Testing

```bash
python -m pytest tests/ -q
```

Baseline: 212 passed, 694 subtests passed, **0 skipped**.

| File | Needs a window? | Needs cached data? | Covers |
|---|---|---|---|
| `test_parser.py` | no | no (fixtures) | the five HTML parsers |
| `test_tours.py` | no | no | arena/era classification, `reclassify_arenas()`, tour-range narrowing |
| `test_identity_groups.py` | no | no | `parse_identity_ids()`, group storage, multi-ID queries |
| `test_plane_renames.py` | no | no | `PLANE_RENAMES`, normalising on write, `canonicalize_planes()` |
| `test_version_check.py` | badge class only | no | version parsing/compare, the background check, the masthead badge |
| `test_theme.py` | switch class only | no | the (light, dark) palette, the theme JSON, settings, live mode switching |
| `test_widgets.py` | yes | no | `SearchableSelect` filtering, ranking, popup |
| `test_gui_smoke.py` | yes | yes | the real window against the local cache, per pilot |

A skip is a warning sign, not background noise. The suite treats an unbuildable
window as a skip, which twice hid a real loss of coverage: antivirus blocking
file creation, and then a second Tk root failing to build. Both times ~39 tests
vanished and the run still looked green. **If you see skips, find out why
before trusting the run.**

That second-root problem is why every GUI test shares one `App`, built once in
`tests/gui_fixture.py` and torn down by the session fixture in
`tests/conftest.py`. Don't build a `CTk()` or an `App()` directly in a test -
call `gui_fixture.get_app()`. Because the App outlives each class, reset it with
`gui_fixture.reset(app, pilot, stype, arena)` in `setUp`.

`test_gui_smoke.py` runs its whole assertion set against two pilots, so a test
can't pass on one career's quirks. It writes nothing to the user's database
except a group named `__ahstats_test_group__`, removed via `addCleanup`.

When fixing a bug, check the new test actually fails without the fix -
reintroduce the bug, run, revert. Several tests here were written that way and
the comments say which bug they pin.

## Releases

- `CHANGELOG.md` holds the user-facing notes for every version, newest first;
  the same text goes on the GitHub release, which carries the built exe.
- Notes are written for Aces High players, not developers: what changed for
  them, and whether they need to do anything (re-sync, etc.).
- Bump `ahstats/__init__.py:__version__` in the same commit that tags the
  release, or the running app claims the previous version.

## Legacy Source

`legacy_source/` contains the original C# .NET Windows Forms application (Visual Studio 2013):
- **AHPilotStats/**: Main Windows Forms app with Unity DI, NUnit tests
- **HTCPilotStatsSvc/**: Service layer
- **DgvFilterPopup/**, **SignedSgmlReader/**, **nPlot/**: Third-party components

Not under active development. Reference only.

## Theme Customization

UI colors defined in:
- `ahstats/assets/htc_theme.json` - customtkinter theme config
- `ahstats/theme.py` - Python color constants + ttk.Treeview styling

### Light and dark (non-obvious)

**Every color in `theme.py` is a `(light, dark)` pair**, and every color
in the theme JSON is a two-element list. That is customtkinter's own
convention: a CTk widget handed a two-tuple picks the right half for the
current appearance mode and re-picks it live when the mode changes. So
the CTk half of the app follows the Dark/Light picker in the masthead for
free, and a bare color string anywhere is a bug - it silently shows the
same shade in both modes.

Nothing else follows automatically. `tkinter.Canvas` (chart.py),
`tkinter.Listbox` (picker.py) and every ttk style take one flat string,
so they must resolve pairs with `theme.color(...)` **at draw time** and
re-draw on a switch. `theme.set_mode()` re-runs `style_treeview()` and
then calls back everything registered via `theme.on_mode_change()` -
which `GridView` and `TrendChart` do in their constructors. A listener
that raises is dropped, since by then its widget is usually destroyed.

One trap the segmented button sets: it uses a single `text_color` for
selected *and* unselected chips. That is why the light theme's selected
chip is pale olive rather than deep olive - dark text has to stay legible
on both. Buttons that override `fg_color` to a panel shade also need an
explicit `text_color=theme.TEXT_BODY`; the palette default is cream, for
olive buttons.

The choice is saved by `settings.py` and applied by
`gui.py`'s `ctk.set_appearance_mode(settings.get("appearance_mode"))`
before any widget is built, so the app never flashes dark on its way to
light. `tests/test_theme.py` covers all of this.

## Key Constraints

1. **No API**: All data comes from screen-scraping HTML forms
2. **Polite scraping**: 3+ second rate limit is mandatory
3. **Thread safety**: All DB access must use locks
4. **No external HTML dependencies**: Exports must be self-contained
5. **Multi-arena support**: All queries must filter by arena or handle "All"

## Common Patterns

**Adding a new stat field:**
1. Update parser in `parser.py` (add to dataclass)
2. Add column to relevant table in `db.py` schema
3. Update insert/query methods in `db.py`
4. Add column to GUI treeview in `gui.py`

**Adding a new endpoint:**
1. Add URL constant to `client.py`
2. Add request method to `AhScoreClient` class
3. Create parser function in `parser.py`
4. Add orchestration to `sync.py`
5. Wire up GUI controls in `gui.py`

**Debugging HTML parsing:**
- Inspect raw HTML by printing `response.text` from client
- BeautifulSoup debugging: use `.prettify()` to see structure
- Header matching: check exact text content with `.get_text(strip=True)`
