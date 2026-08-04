# Changelog

Every released version, newest first. The same text goes on the
[Releases](https://github.com/steelington/AHStats/releases) page, where the
Windows exe for each version is attached.

## v1.1.0 - The missing eighty-one tours

Tours you flew before October 2007 were in the database all along and the app
was hiding them. This release is mostly the fix for that, plus the things
players asked for while reporting it.

Reported by **Fugitive** (formerly **MDJOE**) and **Lusche** - this release
exists because they took the time to say what was wrong. Thanks, gents.

### Fixed

**Pre-Tour-93 Main Arena tours are visible again.** Aces High ran a single Main
Arena through Tour 92, and HiTech's tour ids for those tours carry no arena
letters - just "Tour92". From Tour 93 the arena split into Late/Mid/Early War
and the ids picked up prefixes ("LWTour93"), with the Late War arena - later
renamed Melee - carrying on the Main Arena's numbering without a break: Tour 92
ends 2007-09-30, Late War Tour 93 begins 2007-10-01. One unbroken career.

AHSTATS was filing the unprefixed ids under an arena of their own that no
picker offered, so with **Melee (MA)** selected everything before Tour 93
simply wasn't there - missing from Career Summary, Tour History, Kills by Plane
and Graphs alike. Only "All" reached them, and that dragged in every other
arena with them. Those tours now sit in Melee (MA) where they belong. On a full
cache that is 81 more tours - 307 instead of 226 - going back to Tour 12 and
2000-12-26.

**Your existing database repairs itself.** Nothing to re-sync, nothing to
delete. AHSTATS re-derives the arena of every cached tour when it opens the
database, so the tours are there the first time you launch this version.

**Listing the same game ID twice no longer loses the group.** Putting a name in
an identity group twice used to fail the save outright, taking the rest of the
group with it. Repeats are now ignored.

### New

**Era column** on Tour History and on Kills by Plane grouped by model. Now that
the pre-split tours share an arena with the Melee tours that continue them, the
older ones are marked "Main Arena" so you can still tell at a glance which side
of the 2007 split a tour falls on.

**Tour Range sync mode**, alongside Full History and Single Tour. Type a first
and last tour number and sync just that stretch - tours 21 to 92, say - instead
of fetching three hundred tours at three seconds apiece or picking them off one
at a time. The numbers are read within the arena you have selected. Entering
them backwards works fine.

**Type-to-filter tour pickers.** Every tour picker - Single Tour sync, Tour
Detail, Squad, Arena Planes - is now a search box. The lists hold one entry per
tour ever run and grow by one a month, and Windows was rendering them as a
column with a tiny scroll arrow at each end: no scrollbar, no mouse wheel, no
sane way to reach Tour 12. Now you type "92" and there it is. The wheel and the
scrollbar work, and Enter takes the first match - and the tour you typed is the
first match, not the ones that merely contain those digits, so "Tour 21" finds
Tour 21 rather than Tour 210 through 219.

**The identity group editor shows every ID at once.** Groups combine several
game IDs into one career view for players who have changed name over the years.
The old single-line box scrolled the earlier names out of sight once a list got
long, which read as a limit of about ten. There was never a limit and there
still isn't - the box is now multi-line, one ID per line (commas still work if
you paste them), with a live count beside it.

**Sync progress that looks alive.** Fetches are rate-limited to one every three
seconds, so the old progress bar sat still long enough to look hung. It is now
taller and in a row of its own, with a line underneath that redraws four times
a second showing which tour of how many, percent done, elapsed time and a
measured estimate of the time remaining. Full history, tour range, single tour,
resumed syncs and plane backfill all report through it.

**A standing note on the Squad tab.** "So-and-so is not part of a squad" is
HiTech's own answer for some players and tours - the website says the same
thing when you look it up there. It kept getting reported as a bug in this app.
The tab now says so up front, and the dialog explains where the answer came
from.

### Notes

- HiTech's own tour dropdown begins at Tour 12, so Tours 1 through 11 are not
  offered by their server and no version of this app can fetch them.
- Windows, 64-bit. No install - download and run.
- Data is cached locally in `ahstats.db`; existing databases carry over.

## v1.0.4 - Spatula feature parity

The features Spatula's original AHPilotStats had that this didn't: the **Tour
History** tab with the eight per-category Score/Stats grids, sorting and
filtering on every grid, a running-totals footer that follows the filters, Obj
v Obj grouped by model with a **Backfill Plane Data** button, and a **Graphs**
tab with 17 trend types.

Fixed: tours you didn't fly now cache correctly. HiTech bolds the pilot name on
the "did not fly" page but not on the scores page, which broke header
detection - those tours failed to parse, were never cached, and got re-fetched
on every full sync.

## v1.0.3

Career / Selected Tour scope toggle on the Kills by Plane tab.

## v1.0.2

Fixed the Single Tour sync flow for first-time users: an explicit **Fetch
Tours** button loads the tour list, and the dropdown and sync button now agree
on what is selected.

## v1.0.1

Log the real reason when CA bundle patching fails, instead of failing silently.

## v1.0.0

First public release, with a packaged Windows exe.
