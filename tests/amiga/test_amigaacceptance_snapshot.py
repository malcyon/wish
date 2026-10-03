"""The Amiga accept route's `snapshot NAME` and `restore NAME` steps, and the camp list's."""

from __future__ import annotations

import pytest

from tests.amiga import test_amigaacceptance_camp as camp
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    KEYS,
    _accept,
    readings,
)
from tests.amiga.test_amigaacceptance_camp import STEPS, _camp_run
from tools.amiga import acceptance, route_camp, route_silver_blades
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep


class FakePipe:
    def __init__(self):
        self.calls = []

    def snapshot(self, name, holder, token=None):
        self.calls.append(("snapshot", name, holder))
        return f"snapshot {name}"

    def restore(self, name, holder, token=None):
        self.calls.append(("restore", name, holder))
        return f"restore {name}"


@pytest.fixture
def pipe(monkeypatch):
    fake = FakePipe()
    monkeypatch.setattr(acceptance, "snapshot_pipe", lambda: fake)
    return fake


def _log(tmp_path):
    return next(tmp_path.rglob("*.jsonl")).read_text()


def test_marks_snapshot_and_restore_through_the_pipe_before_the_named_steps(
        tmp_path, clock, readings, pipe):  # noqa: F811
    # Before the first walk step (index 11) and before the camp key (index 13).
    marks = {11: (("snapshot", "walk"),), 13: (("restore", "walk"),)}
    guest, result = _accept(tmp_path, clock, marks=marks)
    assert pipe.calls == [("snapshot", "walk", "wish672-test"), ("restore", "walk", "wish672-test")]
    assert result["error"] == "" and measure._keys(guest) == KEYS
    assert [e for e in result["events"] if "snapshot" in e or "restore" in e] == [
        {"snapshot": "walk", "step": 12}, {"restore": "walk", "step": 14}]
    log = _log(tmp_path)
    assert '"event": "restore"' in log and "stay on the disk image" in log


def test_a_restore_after_a_game_save_since_its_snapshot_stops_before_the_claim(
        tmp_path, clock, readings, pipe):  # noqa: F811
    # The B write is route index 8; the snapshot comes before it, the restore after.
    marks = {5: (("snapshot", "early"),), 11: (("restore", "early"),)}
    with pytest.raises(RouteError, match="save came between"):
        _accept(tmp_path, clock, marks=marks)
    assert pipe.calls == []


def test_a_restore_with_no_snapshot_before_it_stops_before_the_claim(
        tmp_path, clock, readings, pipe):  # noqa: F811
    with pytest.raises(RouteError, match="no snapshot"):
        _accept(tmp_path, clock, marks={11: (("restore", "walk"),)})
    assert pipe.calls == []


def test_camp_list_steps_parse_and_are_checked():
    assert route_camp.parse_steps("snapshot a;view;restore a") == (
        "snapshot a", "view", "restore a")
    for text, why in (("restore a;view", "no snapshot"), ("snapshot ;view", "NAME"),
                      ("snapshot a b;view", "NAME"), ("snapshot a/b;view", "NAME"),
                      ("snapshot a", "empty")):
        with pytest.raises(RouteError, match=why):
            route_camp.parse_steps(text)


def test_camp_machine_steps_are_not_route_steps_and_mark_their_place():
    tokens = ("snapshot a", "view 1", "heal", "restore a")
    base = route_silver_blades.published_title("A")
    title = route_camp.camp_title(base, tokens, 6, name="ssb")
    plain = route_camp.camp_title(base, ("view 1", "heal"), 6, name="ssb")
    assert title.route == plain.route
    at = base.route.index(route_camp.CAMP_SAVE_STEP)
    assert route_camp.camp_marks(title, tokens, 6, name="ssb") == {
        at: (("snapshot", "a"),), at + len(plain.route) - len(base.route): (("restore", "a"),)}


def test_a_camp_run_snapshots_and_restores_around_a_camp_step(tmp_path, clock, monkeypatch, pipe):
    steps = ("snapshot leg", "view 1", "restore leg", *STEPS)
    guest, result = _camp_run(tmp_path, clock, monkeypatch, steps=steps)
    assert result["error"] == ""
    assert [c[:2] for c in pipe.calls] == [("snapshot", "leg"), ("restore", "leg")]
    keys = camp._keys(guest)
    view = keys.index("V", keys.index("E") + 1)
    assert view > 0
