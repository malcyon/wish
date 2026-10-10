"""The party menu's `ADD CHARACTER TO PARTY` as a Pool acceptance step, `add
WHO`, on a fake of the screens the game draws: the list is the training
hall's (`tests/c64/test_c64creation.py`'s `add list`, from `cited/264`), a
name at column 4 with a star at column 3 for a member already in the party,
`EXIT` under the last name and the prompt below it."""

from __future__ import annotations

import json
import pathlib

import pytest

from tests.c64.test_c64acceptance import (
    _HEAD,
    _MENU_ROWS,
    _drive,
    _fixture_disk,
    _Pool,
    _remove_run,
    _RemoveSession,
    _stopped_before_a_slot,
    _window,
)
from tools.c64 import acceptance as A

_LEFT = ["MAGNUS                           9 9", "SILAS                           10 9",
         "ROLAND                          10 7", "LADY KATHERINE                   8 5",
         "MALCYON                          8 4"]
_BRUTUS = "BRUTUS                           9 11"


def _menu(panel):
    lines = {2: _HEAD, **{4 + i: name for i, name in enumerate(panel)}}
    lines.update({13 + i: row for i, row in enumerate(_MENU_ROWS)})
    return _window(lines)


def _add_screen(names, starred):
    """The ADD list: each name from row 2, `*` before a member, `EXIT`, a
    blank row and the prompt."""
    lines = {2 + i: ("  *" if name in starred else "   ") + name
             for i, name in enumerate(names)}
    lines[2 + len(names)] = "   EXIT"
    lines[4 + len(names)] = "ADD CHARACTER TO PARTY"
    return _window(lines)


_NAMES = ["MAGNUS", "SILAS", "ROLAND", "LADY KATHERINE", "MALCYON", "BRUTUS"]


def test_the_add_list_is_read_with_its_stars_and_the_menu_is_not_it():
    assert A.add_list(_add_screen(_NAMES, _NAMES[:5])) == [
        ("MAGNUS", True), ("SILAS", True), ("ROLAND", True),
        ("LADY KATHERINE", True), ("MALCYON", True), ("BRUTUS", False)]
    # The party menu carries the prompt's words as a choice.
    assert A.add_list(_menu(_LEFT)) is None
    assert A.menu_panel(_menu(_LEFT + [_BRUTUS])) == _LEFT + [_BRUTUS]


def test_the_add_step_parses_on_the_party_menu_only():
    steps = A.parse_steps(["load", "remove BRUTUS", "add BRUTUS", "walk-fight I"])
    assert [s.text for s in steps][1:3] == ["remove BRUTUS", "add BRUTUS"]
    assert A.ends_on_party_menu(A.parse_steps(["load", "remove 1", "add BRUTUS"]))
    for bad in (["load", "add"], ["load", "view 1", "add BRUTUS"],
                ["load", "add 1"]):
        with pytest.raises(ValueError):
            A.parse_steps(bad)


def test_add_takes_the_unstarred_name_waits_for_its_star_and_leaves_by_exit(
        tmp_path, monkeypatch):
    screens = {"menu": _menu(_LEFT), "list": _add_screen(_NAMES, _NAMES[:5]),
               "taken": _add_screen(_NAMES, _NAMES),
               "back": _menu(_LEFT + [_BRUTUS])}
    moves = {("menu", ("row", A.ADD_ROW)): "list",
             ("list", ("row", "BRUTUS")): "taken",
             ("taken", ("row", "EXIT")): "back"}
    sess = _RemoveSession(screens, moves, "menu", _fixture_disk(tmp_path))
    run, log = _remove_run(tmp_path, monkeypatch, sess)
    got = run.add("BRUTUS")
    log.close()
    assert sess.sent == [("row", A.ADD_ROW), ("row", "BRUTUS"), ("row", "EXIT")]
    assert got["listed"][-1] == ["BRUTUS", False]
    assert got["starred"] and got["panel"] == _LEFT + [_BRUTUS]
    assert run.at_menu and sess.state == "back"


def test_add_fails_for_a_name_already_in_the_party_or_not_listed(
        tmp_path, monkeypatch):
    screens = {"menu": _menu(_LEFT), "list": _add_screen(_NAMES, _NAMES[:5])}
    moves = {("menu", ("row", A.ADD_ROW)): "list"}
    for who in ("MAGNUS", "DIRTEN"):
        sess = _RemoveSession(screens, moves, "menu", _fixture_disk(tmp_path))
        run, log = _remove_run(tmp_path, monkeypatch, sess)
        with pytest.raises(A.StepFailed):
            run.add(who)
        log.close()
        assert sess.sent == [("row", A.ADD_ROW)]


def test_an_add_the_game_does_not_star_fails_the_step(tmp_path, monkeypatch):
    screens = {"menu": _menu(_LEFT), "list": _add_screen(_NAMES, _NAMES[:5])}
    moves = {("menu", ("row", A.ADD_ROW)): "list", ("list", ("row", "BRUTUS")): "list"}
    sess = _RemoveSession(screens, moves, "menu", _fixture_disk(tmp_path))
    run, log = _remove_run(tmp_path, monkeypatch, sess)
    monkeypatch.setattr(A, "ADD_WAIT", 0)
    with pytest.raises(A.StepFailed, match="BRUTUS"):
        run.add("BRUTUS")
    log.close()


def test_a_run_with_remove_then_add_stays_on_the_menu_until_the_next_step(
        tmp_path, monkeypatch):
    calls = []

    class Menu(_Pool):
        at_menu = False

        def load_party(self):
            calls.append("load_party")
            self.at_menu = True
            return {}

        def remove(self, who):
            calls.append(f"remove {who}")
            return {}

        def add(self, who):
            calls.append(f"add {who}")
            return {"who": who}

        def enter_world(self):
            calls.append("enter_world")
            self.at_menu = False
            return {}

        def view(self, who):
            calls.append(f"view {who}")
            return {}

    rc, _, out = _drive(tmp_path, monkeypatch,
                        ["load", "remove BRUTUS", "add BRUTUS", "view BRUTUS"],
                        pool=Menu)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert rc == 0, summary.get("lost")
    assert calls == ["load_party", "remove BRUTUS", "add BRUTUS", "enter_world",
                     "view BRUTUS"]


def test_the_add_step_is_pool_only(tmp_path, monkeypatch):
    _stopped_before_a_slot(tmp_path, monkeypatch, [
        "--title", "curse", "--save", str(_fixture_disk(tmp_path)),
        "--disks", str(tmp_path), "--steps", "load", "remove 1", "add X"])
    assert pathlib.Path(tmp_path).is_dir()
