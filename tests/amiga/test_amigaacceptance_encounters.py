"""The accept run's encounter switch: on for the walk, off before every save and before the guest stops."""

from __future__ import annotations

import argparse
import json

import pytest

from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    AcceptGuest,
    _accept,
    readings,
)
from tests.amiga.test_amigaacceptance_measure import _measure, clock  # noqa: F401
from tests.amiga.test_amigaacceptance_snapshot import FakePipe, _encounter_guard
from tools.amiga import acceptance
from tools.amiga.winuaesession import RouteError

WALK = ["NP8", "NP8"]


class FakeSwitch:
    """Records `on` and `off` in the guest's own call list, so their order against key presses is seen."""

    def __init__(self, guest, off_reply=None, off_replies=()):
        self.guest, self.off_reply = guest, off_reply
        self.off_replies = list(off_replies)

    def on(self):
        self.guest.calls.append(("encounters", "on"))
        return {"action": "on"}

    def off(self):
        self.guest.calls.append(("encounters", "off"))
        if self.off_replies:
            return self.off_replies.pop(0)
        return self.off_reply or {"action": "off"}


def _sequence(guest):
    """Every key, switch change and stop, in the order they happened."""
    out = []
    for call in guest.calls:
        if call[0] == "press":
            out.append(call[2])
        elif call[0] == "encounters":
            out.append(f"switch {call[1]}")
        elif call[0] in ("stop", "snapshot", "restore"):
            out.append(call[0])
    return out


def _on_when_walking_and_off_before_each_save(sequence):
    """The switch state at every key, and at the stop, from the sequence."""
    on, state = False, []
    for item in sequence:
        if item == "switch on":
            on = True
        elif item == "switch off":
            on = False
        else:
            state.append((item, on))
    return state


def test_a_default_run_never_touches_the_switch_and_records_it(tmp_path, clock, readings):  # noqa: F811
    guest, result = _accept(tmp_path, clock)
    assert not any(c[0] == "encounters" for c in guest.calls)
    assert result["no_encounters"] is False
    assert json.loads((tmp_path / "recon1" / "summary.json").read_text())["no_encounters"] is False


def test_the_switch_is_on_for_the_walk_and_off_before_both_saves(tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest, encounters=FakeSwitch(guest))
    state = dict(_on_when_walking_and_off_before_each_save(_sequence(guest)))
    assert result["error"] == ""
    assert all(on for key, on in _on_when_walking_and_off_before_each_save(_sequence(guest))
               if key in WALK)
    # The camp key and its save letter come after the walk, and the menu save before it.
    for key, on in _on_when_walking_and_off_before_each_save(_sequence(guest)):
        if key not in WALK:
            assert not on, key
    assert "B" in state and "D" in state and state["D"] is False
    assert result["no_encounters"] is True
    assert json.loads((tmp_path / "recon1" / "summary.json").read_text())["no_encounters"] is True


def test_the_switch_goes_off_when_a_walk_step_raises(tmp_path, clock, readings):  # noqa: F811
    # The eleventh key is the first walk step.
    guest = AcceptGuest(clock, raises=(11, RouteError("the lane dropped")))
    _, result = _accept(tmp_path, clock, guest=guest, encounters=FakeSwitch(guest))
    sequence = _sequence(guest)
    assert "lane dropped" in result["error"]
    assert sequence.index("switch on") < sequence.index("stop")
    assert sequence[sequence.index("stop") - 1] == "switch off"
    assert result["no_encounters"] is True


def test_a_switch_that_cannot_go_off_fails_the_run(tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    stuck = FakeSwitch(guest, off_reply={"action": "off", "error": "a row did not go back"})
    _, result = _accept(tmp_path, clock, guest=guest, encounters=stuck)
    assert "did not go back" in result["error"]
    assert result["success"] is False


def test_the_switch_is_only_for_accept_and_measure_runs(tmp_path, clock, readings):  # noqa: F811
    with pytest.raises(RouteError, match="accept or measure"):
        _accept(tmp_path, clock, reload=True, encounters=object())


def test_no_encounters_needs_winuae():
    args = argparse.Namespace(emulator="fsuae", no_encounters=True)
    with pytest.raises(RouteError, match="--no-encounters"):
        acceptance._check_emulator(args)


def test_the_option_builds_no_switch_when_not_given():
    assert acceptance._encounters(argparse.Namespace(no_encounters=False), "holder") == {}


def _pipe_on(guest):
    """A pipe whose snapshots and restores are listed among the guest's calls."""
    fake = FakePipe(guest)
    guest.snapshot = lambda name, holder: (guest.calls.append(("snapshot", name)),
                                           fake.snapshot(name, holder))[1]
    guest.restore = lambda name, holder: (guest.calls.append(("restore", name)),
                                          fake.restore(name, holder))[1]
    return fake


def test_a_failed_off_is_tried_again_before_the_guest_stops(tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    switch = FakeSwitch(guest, off_replies=[{"action": "off", "error": "a row did not go back"}])
    _, result = _accept(tmp_path, clock, guest=guest, encounters=switch)
    sequence = _sequence(guest)
    # The first off, before the camp key, failed and stopped the run; the cleanup's off went through.
    assert "did not complete" in result["error"] and result["success"] is False
    assert sequence.count("switch off") == 2 and sequence[-2:] == ["switch off", "stop"]
    assert "D" not in sequence and "encounters_off_error" not in result


def test_a_walk_retry_restores_with_the_switch_off_and_walks_again_with_it_on(
        tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    fake = _pipe_on(guest)
    _, result = _accept(tmp_path, clock, guest=guest, guard=_encounter_guard(fake, 1),
                        walk_retry=2, encounters=FakeSwitch(guest))
    sequence = _sequence(guest)
    assert result["error"] == ""
    restore = sequence.index("restore")
    assert sequence[restore - 1] == "switch off"
    assert sequence[restore + 1] == "switch on" and sequence[restore + 2] == "NP8"
    assert all(on for key, on in _on_when_walking_and_off_before_each_save(sequence)
               if key in WALK)
    assert not dict(_on_when_walking_and_off_before_each_save(sequence))["D"]


def test_a_snapshot_after_a_walk_step_is_taken_with_the_switch_off(tmp_path, clock, readings):  # noqa: F811
    guest = AcceptGuest(clock)
    _pipe_on(guest)
    # Before the camp key (step 14), straight after the second walk step.
    _, result = _accept(tmp_path, clock, guest=guest, encounters=FakeSwitch(guest),
                        marks={13: (("snapshot", "camp"),), 14: (("restore", "camp"),)})
    sequence = _sequence(guest)
    assert sequence[sequence.index("snapshot") - 1] == "switch off"
    assert sequence[sequence.index("restore") - 1] != "switch on"
    assert all(not on for key, on in _on_when_walking_and_off_before_each_save(sequence)
               if key in ("S", "D"))


def test_an_answer_step_between_walk_steps_has_the_switch_off(tmp_path, clock, readings, monkeypatch):  # noqa: F811
    route = list(acceptance.ACCEPT_ROUTE)
    route.insert(12, (None, "world", "answer"))
    monkeypatch.setattr(acceptance, "ACCEPT_ROUTE", tuple(route))
    guest = AcceptGuest(clock)
    _accept(tmp_path, clock, guest=guest, encounters=FakeSwitch(guest))
    sequence = _sequence(guest)
    walks = [i for i, x in enumerate(sequence) if x == "NP8"]
    assert len(walks) == 2
    between = sequence[walks[0] + 1:walks[1]]
    assert between == ["switch off", "switch on"]


def test_the_measure_route_of_a_legacy_title_takes_no_switch(tmp_path, clock):  # noqa: F811
    with pytest.raises(RouteError, match="needs a title route"):
        _measure(tmp_path, AcceptGuest(clock), encounters=object())
