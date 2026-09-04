from __future__ import annotations

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


import gc
import importlib.util
import os
import pathlib
import sys

import pytest

_TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"


def load_tools_module(name: str):
    """Import ``tools/<name>.py`` by file path, without leaving ``tools/`` on
    ``sys.path`` for whatever pytest collects next.

    ``tools/wish.py`` is a plain module that happens to share the real
    ``wish`` *package*'s name. Six test files used to put ``tools/`` on
    ``sys.path`` permanently with a bare ``sys.path.insert(0, ...)``, which
    let ``tools/wish.py`` shadow the package for every later ``from wish
    import ...`` in the same process -- collection-order luck, not safety;
    see #203 (Six test files shadow the wish package with tools/wish.py,
    which stops the suite collecting). Importing the real package here,
    first, and never leaving ``tools/`` on ``sys.path`` afterwards, is what
    keeps that from happening regardless of what runs this function or when.

    Reuses an already-loaded module by name rather than re-executing it, so
    two test files asking for ``session`` get the same module object -- and
    so the same classes -- rather than each getting its own copy that fails
    ``isinstance`` against the other's.
    """
    import wish  # noqa: F401
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    added = str(_TOOLS) not in sys.path
    if added:
        sys.path.insert(0, str(_TOOLS))
    try:
        spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            # A module that failed half way through must not stay cached, or
            # the next `load_tools_module(name)` in this process gets the
            # broken object instead of a fresh error.
            sys.modules.pop(name, None)
            raise
        return module
    finally:
        if added:
            sys.path[:] = [p for p in sys.path if p != str(_TOOLS)]

# Before Qt is imported by anything. Without this the suite opens real windows
# on whoever is logged in -- and since many tests edit a character, closing one
# asks "save before closing?", so a run buries the user in dialogs. Set here
# rather than in a Makefile so it protects every way of invoking pytest.
#
# **Forced, not defaulted.** This was `setdefault`, which does nothing for the
# one person most likely to be running the suite: a desktop session that
# exports `QT_QPA_PLATFORM` for its own compositor -- COSMIC and KDE both do --
# kept its own value and got the real windows the line exists to prevent. The
# variable a developer sets for their desktop is not a statement about how they
# want their tests to run.
#
# `WISH_TEST_PLATFORM` is the way to mean it: set it to `wayland`, `xcb` or
# anything else and that is used instead, so watching the windows go by is
# still one variable away.
os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_TEST_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _one_qapplication():
    """The reference that keeps the application alive from first test to last.

    "The session" is one `pytest-xdist` worker's own process under `-n auto`
    -- each gets its own interpreter and so its own single `QApplication`,
    never two workers sharing one. Nothing here needed to change for that;
    it is the same reason `_isolate_config` below only had to lean on
    `tmp_path`, which pytest already keeps distinct per worker.
    """
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


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """No test writes to the real config directory, on any platform.

    `automap/paths.py` reads the XDG variables on Linux and `APPDATA` on
    Windows. Ten test helpers set only the XDG pair, which is correct here and
    silently wrong on a Windows runner: notes and settings land in the runner's
    real profile and leak from one test into the next. That is what made
    `test_an_empty_untyped_popover_adds_nothing` fail on Windows and pass
    everywhere else.

    Setting all four here means no individual test can forget a platform.
    """
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path))
