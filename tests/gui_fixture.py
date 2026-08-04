"""One Tk root, shared by every GUI test in the session.

Each test class used to build its own `App`, which meant building a
second Tk root in the same interpreter once the first was gone. Tk is
unenthusiastic about that: it intermittently failed with "Can't find a
usable init.tcl", and because the suite treats an unbuildable window as
a skip, roughly one run in three quietly dropped 39 tests instead of
failing. Silent coverage loss is worse than a red run - a real GUI
regression could sail through - so the root is built once here and
handed out.

`App` is what gets built rather than a bare root, since the smoke tests
need it anyway and a plain `CTk()` alongside it would be a second root
again.
"""
from __future__ import annotations

import unittest

_app = None
_unavailable: str | None = None


def get_app():
    """The session's App, built on first use.

    Raises SkipTest if it can't be built - and remembers that, so the
    rest of the suite skips quickly instead of retrying a failing
    window build once per class."""
    global _app, _unavailable

    if _unavailable is not None:
        raise unittest.SkipTest(_unavailable)
    if _app is not None:
        return _app

    try:
        import ahstats.gui as gui
    except Exception as e:  # pragma: no cover - import guard
        _unavailable = f"GUI unavailable: {e}"
        raise unittest.SkipTest(_unavailable)

    try:
        _app = gui.App()
    except Exception as e:  # no display, no Tcl, etc.
        _unavailable = f"cannot create window: {e}"
        raise unittest.SkipTest(_unavailable)
    return _app


def reset(app, gameid: str, stype: str, arena: str) -> None:
    """Point the shared App at one pilot. Called per test class, since
    the App now outlives them."""
    app.gameid_entry.delete(0, "end")
    app.gameid_entry.insert(0, gameid)
    app.stype_var.set(stype)
    app.identity_view_var.set("Single ID")
    app.arena_var.set(arena)
    app.sync_mode_var.set("Full History")
    app.on_sync_mode_changed()


def shutdown() -> None:
    """Tear the root down at the end of the session."""
    global _app
    if _app is None:
        return
    # Cancel every pending 'after', not just the app's own. App.destroy()
    # handles its timers, but customtkinter keeps a DPI check that
    # reschedules itself forever, so there is always one queued. Left
    # alone they fire into a torn-down interpreter and spray Tk errors
    # over the test output.
    try:
        for after_id in _app.tk.splitlist(_app.tk.call("after", "info")):
            try:
                _app.after_cancel(after_id)
            except Exception:
                pass
    except Exception:
        pass
    try:
        _app.destroy()
    except Exception:
        pass
    _app = None
