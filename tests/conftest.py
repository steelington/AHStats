"""Session-wide teardown for the shared Tk root (see gui_fixture)."""
from __future__ import annotations

import pytest

from tests import gui_fixture


@pytest.fixture(scope="session", autouse=True)
def _shared_tk_root():
    yield
    gui_fixture.shutdown()
