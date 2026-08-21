"""One QApplication for the whole session, and no real windows.

PyQt owns the QApplication from Python: drop the last reference to it and the
object is destroyed -- and `~QApplication` deletes every widget still standing
with it. Each test module builds one from a *function-scoped* `app` fixture, so
the application died at the end of whichever test held it last and the next
test built a fresh one. A plugin logging the identity of the instance at each
teardown counted **125 distinct QApplication objects in one session**, with
stretches of `None` in between. Any Qt object that outlived one
of those teardowns -- anything still in a reference cycle, anything a wider
fixture held -- was pointing at freed memory afterwards, which is where the
segfault in `findChild` came from.

Holding one for the session is the fix. `QApplication.instance()` then hands
every module's own `app` fixture the same object and nothing ever destroys it.

See `docs/112-test-harness.md` for the measurements.
"""

from __future__ import annotations

import gc
import os

import pytest

# Before Qt is imported by anything. Without this the suite opens real windows
# on whoever is logged in -- and since many tests edit a character, closing one
# asks "save before closing?", so a run buries the user in dialogs. Set here
# rather than in a Makefile so it protects every way of invoking pytest.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _one_qapplication():
    """The reference that keeps the application alive from first test to last."""
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:          # the suite also runs without the gui extra
        yield None
        return
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _collect_between_tests():
    """Collect at a moment of our choosing rather than mid-`findChild`.

    Kept from the first attempt at the segfault. It is not the cure -- it only
    moved the rate from one run in three to one in four -- but a deterministic
    collection point costs nothing measurable and keeps the windows a test
    dropped from piling up.
    """
    yield
    gc.collect()
