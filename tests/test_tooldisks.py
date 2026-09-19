"""A disk-reading tool with no disks stops with a message instead of scanning
the directory it happens to be run from.

Each tool is imported afresh with no `$POR_DISKS`, no registry and an empty
home, so its module-level disk constant is the one a machine without disks
produces. `tool_disks` looks in `$POR_DISKS` first, then in the search, and
answers `None` when neither finds anything.
"""
from __future__ import annotations

import importlib
import pathlib
import sys
import types

import pytest

from automap import paths

pytestmark = pytest.mark.usefixtures("no_registry")

NO_DISKS = "No game disks found. Set $POR_DISKS."


@pytest.fixture(autouse=True)
def _nowhere(monkeypatch, tmp_path):
    """No variable, no registry, a home with nothing in it, and a working
    directory that `disk_candidates()` will search and find empty."""
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.setattr(paths, "_home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fresh(monkeypatch):
    """Import modules again, so their module-level disk constant is computed
    under the isolation above, and put the originals back afterwards."""

    def load(*dotted):
        for name in dotted:
            pkg, leaf = name.rsplit(".", 1)
            package = importlib.import_module(pkg)
            importlib.import_module(name)
            monkeypatch.setattr(package, leaf, getattr(package, leaf))
            monkeypatch.delitem(sys.modules, name, raising=False)
        return [importlib.import_module(name) for name in dotted]

    return load


# -- the lookup ----------------------------------------------------------------


def test_tool_disks_is_none_when_nothing_answers():
    assert paths.tool_disks() is None


def test_tool_disks_takes_the_variable_at_its_word(monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("POR_DISKS", str(empty))
    assert paths.tool_disks() == pathlib.Path(empty)


def test_tool_disks_ignores_an_empty_variable(monkeypatch):
    monkeypatch.setenv("POR_DISKS", "")
    assert paths.tool_disks() is None


def test_tool_disks_falls_back_to_the_search(monkeypatch, tmp_path):
    found = tmp_path / "PoR"
    found.mkdir()
    (found / "POOL1.D64").write_bytes(b"")
    assert paths.tool_disks() == found


def test_tool_disks_calls_find_disks_by_its_module_name(monkeypatch, tmp_path):
    """A test that patches `paths.find_disks` has to reach it."""
    monkeypatch.setattr(paths, "find_disks", lambda game=None: tmp_path / "x")
    assert paths.tool_disks() == tmp_path / "x"


# -- the guard, for the tools that read the disks ------------------------------


def test_the_constant_is_none_with_no_disks(fresh):
    (walk,) = fresh("tools.areas.eclwalk")
    assert walk.DISKS is None


def test_eclwalk_stops_with_no_disks(fresh, monkeypatch):
    (walk,) = fresh("tools.areas.eclwalk")
    monkeypatch.setattr(sys, "argv", ["eclwalk.py", "list"])
    with pytest.raises(SystemExit) as stopped:
        walk.main()
    assert str(stopped.value) == NO_DISKS


def test_exitroute_stops_with_no_disks(fresh):
    _, route = fresh("tools.areas.eclwalk", "tools.areas.exitroute")
    with pytest.raises(SystemExit) as stopped:
        route.main(["ECL07", "A904"])
    assert str(stopped.value) == NO_DISKS


def test_genexits_stops_with_no_disks(fresh):
    _, gen = fresh("tools.areas.eclwalk", "tools.generate.genexits")
    with pytest.raises(SystemExit) as stopped:
        gen.build()
    assert str(stopped.value) == NO_DISKS


# -- an explicit --disks reaches the staging, and an empty one is no disks -----


def _stub_session(monkeypatch, module, staged):
    """Replace everything in `module` that launches or stages, and record the
    disk folder `stage_disks` is given. `Session.boot` fails, which stops the
    run straight after staging."""
    slot = types.SimpleNamespace(
        n=99, display=99, dir="", teardown=lambda: None, release=lambda: None)

    class Session:
        def __init__(self, *a, **k):
            pass

        def boot(self):
            return False

        def terminate(self):
            pass

    monkeypatch.setattr(module.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(module.S, "stage_disks",
                        lambda slot, disks, *a, **k: staged.append(disks))
    monkeypatch.setattr(module.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(module.S, "Session", Session)
    return slot


def test_wallpins_stages_the_disks_it_was_given(fresh, monkeypatch, tmp_path):
    (pins,) = fresh("tools.areas.wallpins")
    staged = []
    slot = _stub_session(monkeypatch, pins, staged)
    slot.dir = str(tmp_path / "slot")
    (tmp_path / "slot").mkdir()
    given = tmp_path / "disks"
    given.mkdir()
    with pytest.raises(RuntimeError, match="Boot failed"):
        pins.main(["--disks", str(given), "--out", str(tmp_path / "out")])
    assert staged == [given]


def test_wallpins_stops_with_no_disks(fresh, monkeypatch):
    (pins,) = fresh("tools.areas.wallpins")
    _stub_session(monkeypatch, pins, [])  # a missing guard must not claim a pool slot
    with pytest.raises(SystemExit) as stopped:
        pins.main([])
    assert str(stopped.value) == NO_DISKS


def test_fasttravelrun_stops_with_an_empty_disks_argument(fresh, monkeypatch):
    (run,) = fresh("tools.areas.fasttravelrun")
    _stub_session(monkeypatch, run, [])  # a missing guard must not claim a pool slot
    with pytest.raises(SystemExit) as stopped:
        run.main(["--disks", ""])
    assert str(stopped.value) == NO_DISKS


def test_fasttravelrun_stops_with_no_disks(fresh, monkeypatch):
    (run,) = fresh("tools.areas.fasttravelrun")
    _stub_session(monkeypatch, run, [])  # a missing guard must not claim a pool slot
    with pytest.raises(SystemExit) as stopped:
        run.main([])
    assert str(stopped.value) == NO_DISKS
