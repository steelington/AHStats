# Changelog

Every released version, newest first. The same text goes on the
[Releases](https://github.com/steelington/AHStats/releases) page, where the
Windows exe for each version is attached.

## v1.2.0 - A light theme, and it tells you when there's an update

Two things people asked for: the app now tells you when there is a newer
version, and it comes in a light colour scheme as well as the dark one.

Nothing to re-sync and nothing to delete.

### New

**It tells you when there's an update.** On startup the app asks GitHub
whether a newer version has been released. If there is one, a green
**Update available** button appears in the top right - click it and the
release page opens in your browser, where the exe is attached. If there
isn't, you see nothing at all.

To be clear about what that does and doesn't do: it asks GitHub one
question and reads the answer. Nothing about you, your pilot, your
scores or your machine is sent, nothing is recorded anywhere, and the
app never downloads or installs anything by itself - updating stays a
thing you do, by hand, when you feel like it. If you're offline, or
GitHub is having a bad day, the check gives up quietly and the app
carries on as normal.

**Light theme.** There's a **Dark / Light** switch in the top right, next
to where the update notice appears. It changes the whole app on the
spot - grids, graphs, dropdowns and all - with no restart, and it
remembers which one you picked for next time. The olive masthead stays
olive in both, because that's the app.

## v1.1.5 - The Model box opens where you clicked

A follow-up to v1.1.4, reported by **Shane** again: the new **Model** picker
on Kills by Plane could flash something in the top-left corner of the screen
and then leave the box sitting on the A-20G with no list to choose from.

Nothing to re-sync and nothing to delete.

### Fixed

**The Model list appeared in the corner of the screen instead of under the
box.** The list was being put on screen for an instant before it was moved
into place, so what you saw was a flicker in the top-left corner of the
monitor - and depending on where the window sat, sometimes that flicker was
all you got. It now stays hidden until it is where it belongs.

**The Model box could get stuck on one aircraft.** If the list ever
disappeared without the app noticing, the box would refuse to open a new one
and refuse to change what it showed - locked on whichever aircraft was first
in the list, usually the A-20G. It now notices and recovers.

**The Model list follows the arena.** Switching arena, or pilot, left the
previous list in the box: aircraft you never flew there were still offered,
and aircraft you only flew in the new arena were missing. Switch to All now
and the WWI aircraft appear where they should.

## v1.1.4 - The whole aircraft list, and a wheel that works

The **Model** picker on Kills by Plane now filters as you type and scrolls
with the mouse wheel. Both reported by **Shane** - thanks for the catch, and
for spotting it precisely enough to find the cause.

Nothing to re-sync and nothing to delete.

### Fixed

**Aircraft were missing from the "By Model" list.** The A6M3 among them, and
anything else near the top of the alphabet. The data was in your cache the
whole time - the list itself was the problem. A long career meets around a
hundred and thirty aircraft, and Windows draws a menu that long taller than
the screen, then quietly cuts off whatever doesn't fit.

The picker is now the same type-to-filter box as the tour pickers: type
"A6M" and you get the three Zeroes, type "109" and you get every Messerschmitt.

### Changed

**The Model list scrolls with the mouse wheel** and has a real scrollbar,
instead of the hold-the-pointer-on-an-arrow menu it had before.

*The 109G-10 rolling into the 109K-4 is HiTech's own doing, not ours - AHStats
shows the aircraft names exactly as the stats pages report them.*

## v1.1.3 - Scrollbars and grid borders that match the rest of the app

Cosmetic only. Nothing to re-sync, nothing to delete, and nothing behaves
differently - it just stops looking like two applications stitched together.

### Fixed

**Scrollbars are dark.** Every scrollbar in the app - down the grids, down the
tour dropdown - was drawn in light grey with a ridged thumb and raised 3D
arrows, a Windows 95 control sitting in the middle of a dark window. The theme
had always meant to style them; it was setting the colours on a name none of
the scrollbars actually used, so they quietly kept the defaults.

**Grids are no longer framed in white.** Same cause: a near-white bevel drawn
around every table. The grids now carry the same soft grey edge as the rest of
the panels.

## v1.1.2 - Type a tour number, get that tour

v1.1.1 read what you typed into the tour box, but then went looking for it in
the wrong place, so Single Tour sync could still fetch a tour you never asked
for. Reported again by **The Fugitive** - thanks for staying on it.

Nothing to re-sync and nothing to delete. Your cache is untouched.

### Fixed

**Typing a tour number finds that tour.** One arena's tour list carries three
generations of HiTech's own naming: Melee Tour 319 down to 201, Late War Tour
200 down to 93, and plain Tour 92 down to 12 - all one continuous career. The
picker was matching your typing as plain text against those labels, which went
wrong two ways:

- Typing the bare number. "47" appears in Tour 47, Late War Tour 147 and Melee
  Tour 247, and the newest-first list put Melee Tour 247 at the top - so Enter
  synced a tour twenty years away from the one you wanted.
- Editing the number in the box. The box arrives filled in with the current
  tour, so changing "Melee Tour 319" to "Melee Tour 47" is the natural move -
  but there is no tour by that name, so it matched nothing and the box snapped
  straight back to 319. That covered 189 of the 308 tours in the Melee list.

The tour number is now what the picker matches on. Type 47 and you get Tour 47;
type 93 and you get Late War Tour 93; leave the arena name wrong and it still
finds the tour. A label typed in full still wins over the tours that merely
contain those digits, so "Tour 21" is Tour 21, not Tour 210.

**Clicking into the tour box selects what's in it**, so the first thing you type
replaces the tour rather than being tacked onto the end of it. Click, type the
number, press Enter. Click a second time if you would rather edit in place.

**A filter matching no tour says so.** The list used to just go empty, which
looked like the dropdown had broken again.

## v1.1.1 - Single Tour sync actually picks the tour

The type-to-filter tour pickers that arrived in v1.1.0 had two ways of not
working, and Single Tour sync ran into both of them: the dropdown arrow opened
nothing, and a tour typed into the box was ignored in favour of the newest tour.
Both are fixed.

Nothing to re-sync and nothing to delete - this release only changes the way the
pickers behave. Your cache is untouched.

Reported by **The Fugitive**, with both symptoms described precisely enough to
reproduce them on the first try. That is worth a lot - thanks.

### Fixed

**The dropdown arrow opens the tour list.** The pickers were only filled after a
sync finished, or after you changed the arena or the pilot/squad setting. On an
ordinary launch - open the app, switch Sync Mode to Single Tour, click the arrow
- the list had nothing in it yet, so the arrow appeared dead. Every tour picker
in the app now loads from your local cache the moment the window opens: Single
Tour sync, Tour Detail, Squad and Arena Planes alike.

**Typing a tour name now selects that tour.** The box would take your typing,
but the tour that got synced was whatever had been selected before - which, on a
fresh launch, is always the newest tour. So no matter what you typed, you got
the current tour. What is in the box is now read at the moment you click the
button, so typing the tour and clicking Sync This Tour is the whole interaction;
you never have to pick from the list.

Typed text is matched the same way the filtered list is ranked, so the tour you
typed wins over the ones that merely contain those digits - "Tour 21" finds
Tour 21, not Tour 210 through 219. Text matching no tour at all is discarded and
the box snaps back to the tour that is still selected, rather than quietly
syncing something you never asked for.

One naming note while you are in there: HiTech's own labels changed over the
years, so the tours between the 2007 split and the Melee rename read as "Late
War Tour 200", the recent ones as "Melee Tour 318", and the pre-split ones as
plain "Tour 47". Filtering on the number alone finds any of them.

## v1.1.0 - The missing eighty-one tours

Tours you flew before October 2007 were in the database all along and the app
was hiding them. This release is mostly the fix for that, plus the things
players asked for while reporting it.

Reported by **The Fugitive** and **Lusche** - this release
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
