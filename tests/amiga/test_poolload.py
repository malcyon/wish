"""Tests for the guarded Pool of Radiance load on a lane `acceptance.py boot` started."""

from __future__ import annotations

import argparse
import json
import pathlib

import pytest

from goldbox import geo
from tools.amiga import poolload, poolremove

NAMES = ["GRON", "SKULLCRUSHER", "PRINCESS FATIMA"]
PLACE = (13, 6, 5, geo.NORTH)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Game:
    """A Pool start: frames no guard can read while AmigaDOS starts it, then the wheel."""

    def __init__(self, dos_frames=3):
        self.dos_frames = dos_frames
        self.screen = "wheel"
        self.place = PLACE
        self.names = list(NAMES)
        self.keys: list[tuple[str, int]] = []

    def press(self, key):
        self.keys.append((key, self.dos_frames))
        moves = {("wheel", "RET"): "title", ("title", "RET"): "party_menu",
                 ("party_menu", "L"): "save_path", ("save_path", "RET"): "load_picker",
                 ("load_picker", "A"): "world"}
        self.screen = moves.get((self.screen, key), self.screen)


class Guest:
    def __init__(self, game):
        self.game = game
        self.holder = None

    def grab(self, state, raw, crop, timeout):
        assert self.holder == "h"
        if self.game.dos_frames:
            self.game.dos_frames -= 1
            return False
        crop.write_text(self.game.screen)
        return True

    def press(self, holder, key, timeout):
        self.game.press(key)
        return "ok"


class Guards:
    def __init__(self, path):
        self.rules = {state: state for state in json.loads(pathlib.Path(path).read_text())}

    def __contains__(self, state):
        return state in self.rules

    def __call__(self, state, crop):
        return state in self.rules and pathlib.Path(crop).read_text() == state


class Live:
    def __init__(self, game):
        self.game = game

    def place(self):
        return self.game.place

    def members(self):
        return [(name, 0x1000 + n, b"") for n, name in enumerate(self.game.names)]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(poolremove, "time", clock)
    monkeypatch.setattr(poolload, "time", clock)
    monkeypatch.setattr(poolremove, "PixelGuards", Guards)
    game = Game()
    manifest = {"title": "pool", "loaded_letter": "A", "names_a": [n.replace(" ", "") for n in NAMES],
                "state_a": {"area": 13, "x": 6, "y": 5, "facing": geo.NORTH}}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))

    def go(**changes):
        args = argparse.Namespace(manifest=path, holder="h", out=tmp_path / "out", guards=None,
                                  budget=poolload.BUDGET)
        path.write_text(json.dumps({**manifest, **changes}))
        return poolload.run(args, guest=Guest(game), live_factory=lambda holder: Live(game))

    return argparse.Namespace(game=game, go=go, out=tmp_path / "out")


def test_no_key_goes_until_a_guard_reads_the_screen_and_the_slot_loads(rig):
    receipt = rig.go()
    assert receipt["success"], receipt.get("error")
    assert [key for key, _ in rig.game.keys] == ["RET", "RET", "L", "RET", "A"]
    assert all(dos_left == 0 for _, dos_left in rig.game.keys)
    assert receipt["loaded"] == {"place": list(PLACE), "names": NAMES}


def test_the_receipt_lists_each_guarded_screen_and_key(rig):
    rig.go()
    written = json.loads((rig.out / "load.json").read_text())
    assert written["success"]
    assert [e["screen"] for e in written["screens"] if "screen" in e] == [
        "wheel", "title", "party_menu", "save_path", "load_picker", "world"]


def test_a_party_on_another_square_fails(rig):
    rig.game.place = (13, 6, 15, geo.SOUTH)
    receipt = rig.go()
    assert not receipt["success"] and "6, 15" in receipt["error"]


def test_another_party_fails(rig):
    rig.game.names = ["GRON"]
    receipt = rig.go()
    assert not receipt["success"] and "not the slot's" in receipt["error"]


def test_a_start_that_never_shows_the_title_fails_without_a_key(rig, monkeypatch):
    rig.game.dos_frames = 10**9
    monkeypatch.setattr(poolload, "BUDGET", 50.0)
    receipt = rig.go()
    assert not receipt["success"] and rig.game.keys == []


def test_the_guards_are_the_pool_files_with_the_extra_rules_on_top(tmp_path):
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"world": {"box": [0, 0, 1, 1], "sha256": "0" * 64}}))
    rules = json.loads(poolload.guard_file(tmp_path, extra).read_text())
    pool = json.loads(poolremove.GUARDS.read_text())["guards"]
    assert set(rules) == set(pool) and rules["world"] == {"box": [0, 0, 1, 1], "sha256": "0" * 64}


def test_a_manifest_of_another_title_stops_before_any_screen(rig):
    with pytest.raises(poolremove.RouteError):
        rig.go(title="darkness")
    assert rig.game.keys == []


def test_main_exits_nonzero_when_the_load_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(poolload, "run", lambda args: {"success": False, "error": "no"})
    assert poolload.main(["--manifest", str(tmp_path / "p.json"), "--holder", "h",
                          "--out", str(tmp_path / "o")]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "no"
