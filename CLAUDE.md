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

The project uses:
- **customtkinter** - Modern dark-mode tkinter wrapper for GUI
- **requests** - HTTP client with SSL handling
- **beautifulsoup4** - HTML parsing
- **Pillow** - Image handling
- **certifi** - CA certificate bundle

No `requirements.txt` exists. Dependencies must be inferred from imports.

## Architecture

### Core Module Organization

**ahstats/** contains 7 modules (~2,034 lines total):

1. **gui.py** (478 lines) - Main application window with 5 tabs:
   - Career Summary: Aggregated stats across all tours
   - Tour Detail: Per-tour breakdowns by category
   - Kills by Plane: Matrix of kills in/of/by/died-in per aircraft
   - Squad: One-off squad member roster and stats
   - Arena Planes: Leaderboard of aircraft performance

2. **db.py** (492 lines) - SQLite persistence layer with 9 tables:
   - `tours`, `pilot_totals`, `pilot_scores`, `pilot_plane_kills`
   - `squad_snapshots`, `squad_members`, `plane_leaderboard`
   - Thread-safe with explicit locking for concurrent access
   - Aggregation queries for career totals, plane kill matrices

3. **parser.py** (502 lines) - BeautifulSoup HTML parsers for 5 endpoints
   - Table-based HTML with no CSS selectors available
   - Parsing done by matching header text in `<th>` elements
   - Dataclasses: `PilotTourScores`, `SquadStats`, `PlaneLeaderboard`, etc.
   - Regex helpers: `_to_int()`, `_to_float()`, `_to_seconds()` for extracting values

4. **client.py** (178 lines) - HTTP client with special SSL handling
   - Rate-limited: 3+ second delay between requests
   - Fetches missing Sectigo intermediate certificate and caches to `_cache/ca_bundle.pem`
   - User-Agent spoofing for browser compatibility
   - Endpoints: `www.hitechcreations.com/component/ahscore/`, `bbs.hitechcreations.com/scores/`

5. **sync.py** (154 lines) - Fetch orchestration layer
   - `sync_pilot(pilot, callback)` - Full history download with tour discovery
   - `fetch_single_tour(pilot, tourid, callback)` - Single tour refresh
   - `fetch_squad_snapshot()`, `fetch_plane_leaderboard_snapshot()` - One-off queries
   - Smart re-fetch detection: only updates live tours

6. **export.py** (174 lines) - Data export to CSV and HTML
   - `export_pilot_tours_csv()` - Per-tour summary
   - `export_pilot_plane_kills_csv()` - Career kills-by-plane matrix
   - `export_html_report()` - Self-contained interactive HTML with embedded JSON

7. **theme.py** (56 lines) - UI theming
   - Color palette matching hitechcreations.com CSS (olive/amber WW2 aesthetic)
   - ttk.Treeview styling for dark mode compatibility
   - References `assets/htc_theme.json` for customtkinter config

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
- Sync operations run on background thread (see `gui.py:_on_sync_click()`)
- Progress updates via `queue.Queue` polled every 100ms by GUI
- Database uses `threading.Lock` for concurrent access safety

### Database Schema Notes

- `tours` table has: `tourid` (primary key), `label`, `start_date`, `end_date`, `arena`
- `pilot_totals` stores per-tour aggregated stats (kills, assists, sorties, deaths, etc.) by category
- `pilot_plane_kills` tracks weekly kill breakdown by aircraft type
- All queries filter by `arena` field for multi-arena support

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

To modify appearance, edit these files and restart the app.

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
