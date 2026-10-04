"""The Amiga accept route's `snapshot NAME` and `restore NAME` steps, and the camp list's."""

from __future__ import annotations

import pytest

from tests.amiga import test_amigaacceptance_camp as camp
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance_accept import (  # noqa: F401
    KEYS,
    AcceptGuest,
    MapGuard,
    _accept,
    readings,
)
from tests.amiga.test_amigaacceptance_camp import STEPS, _camp_run
from tools.amiga import acceptance, route_camp, route_silver_blades
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep


class FakePipe:
    """A pipe that, like WinUAE, takes the screen back to what it showed at the snapshot."""

    def __init__(self, guest=None):
        self.calls = []
        self.guest, self.presses = guest, {}

    def snapshot(self, name, holder, token=None):
        self.calls.append(("snapshot", name, holder))
        if self.guest:
            self.presses[name] = self.guest.presses
        return f"snapshot {name}"

    def restore(self, name, holder, token=None):
        self.calls.append(("restore", name, holder))
        if self.guest:
            self.guest.presses = self.presses[name]
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
    bare = route_camp.camp_title(base, ("view 1", "heal"), 6, name="ssb")
    assert title.route == bare.route
    at = base.route.index(route_camp.CAMP_SAVE_STEP)
    assert route_camp.camp_marks(title, tokens, 6, name="ssb") == {
        at: (("snapshot", "a"),), at + len(bare.route) - len(base.route): (("restore", "a"),)}


def test_a_camp_run_snapshots_and_restores_around_a_camp_step(tmp_path, clock, monkeypatch, pipe):
    steps = ("snapshot leg", "view 1", "restore leg", *STEPS)
    guest, result = _camp_run(tmp_path, clock, monkeypatch, steps=steps)
    assert result["error"] == ""
    assert [c[:2] for c in pipe.calls] == [("snapshot", "leg"), ("restore", "leg")]
    keys = camp._keys(guest)
    view = keys.index("V", keys.index("E") + 1)
    assert view > 0


def test_a_rest_a_restore_undid_is_not_counted_in_the_clock():
    rested = route_camp.rest_minutes
    assert rested(("snapshot a", "rest 1h", "restore a")) == 0
    assert rested(("rest 30m", "snapshot a", "rest 1h", "restore a", "rest 5m")) == 35
    assert rested(("rest 1h", "snapshot a", "rest 1h", "restore A")) == 60


def test_the_users_snapshot_name_keeps_its_case_and_matches_without_it():
    tokens = route_camp.parse_steps("Snapshot Leg;VIEW;restore leg")
    assert tokens == ("snapshot Leg", "view", "restore leg")


def test_a_mark_before_the_first_step_is_blocked_before_the_claim(tmp_path, clock, readings, pipe):  # noqa: F811
    with pytest.raises(RouteError, match="before the first route step"):
        _accept(tmp_path, clock, marks={0: (("snapshot", "walk"),)})
    assert pipe.calls == []


def test_a_restore_puts_back_the_screen_and_the_world_crop_the_run_remembers(
        tmp_path, clock, readings, monkeypatch):  # noqa: F811
    from tests.amiga.test_amigaacceptance_accept import AcceptGuest
    guest = AcceptGuest(clock)
    fake = FakePipe(guest)
    monkeypatch.setattr(acceptance, "snapshot_pipe", lambda: fake)
    # Snapshot after the journal answer, restore after the first move, then the second move.
    _, result = _accept(tmp_path, clock, guest=guest,
                        marks={11: (("snapshot", "walk"),), 12: (("restore", "walk"),)})
    assert result["error"] == ""
    # The restored screen is waited for before the next key.
    assert any(c[0] in ("grab", "capture") and "world-after-restore" in c[1] for c in guest.calls)
    moves = [e for e in result["events"] if "crop_changed" in e]
    # The second move leaves the crop the snapshot showed, and the run must know it changed.
    assert moves[1]["crop_changed"] is True


def test_a_restore_puts_back_the_camp_sheets_and_the_last_rest_marker(
        tmp_path, clock, monkeypatch, pipe):  # noqa: F811
    steps = ("snapshot s", "rest 60m", "view 1", "restore s", "view 1")
    _, result = _camp_run(tmp_path, clock, monkeypatch, steps=steps)
    assert result["error"] == ""
    # Only the sheet after the restore counts, and the undone rest left no marker.
    assert len(result["camp_sheets"]) == 1
    assert "sheets_before_last_rest" not in result


def test_a_restore_that_lands_on_another_camp_screen_stops_the_run(
        tmp_path, clock, monkeypatch, pipe):  # noqa: F811
    # The camp bar is not a strict state, so only the restore's own wait can stop this.
    restored = []
    original = pipe.restore
    pipe.restore = lambda *a, **k: (restored.append(1), original(*a, **k))[1]
    steps = ("snapshot s", "view 1", "restore s", *STEPS)
    _, result = _camp_run(tmp_path, clock, monkeypatch, steps=steps,
                          on_also={"camp": lambda p: not restored})
    assert "after restoring s" in result["error"] and "camp screen was not recognized" in result["error"]
    assert result["success"] is False


def _encounter_guard(pipe, times):
    """A world guard that fails every grab of step 12 until `times` restores have happened."""
    def world(path):
        restores = sum(1 for call in pipe.calls if call[0] == "restore")
        return not (path.stem == "12-world" and restores < times)
    return MapGuard(on={"world": world})


def test_a_walk_retry_restores_the_snapshot_and_walks_the_leg_again(
        tmp_path, clock, readings, monkeypatch):  # noqa: F811
    guest = AcceptGuest(clock)
    fake = FakePipe(guest)
    monkeypatch.setattr(acceptance, "snapshot_pipe", lambda: fake)
    _, result = _accept(tmp_path, clock, guest=guest, guard=_encounter_guard(fake, 1),
                        walk_retry=2)
    assert result["error"] == "" and result["success"] is True
    assert [c[:2] for c in fake.calls] == [("snapshot", "walk-leg"), ("restore", "walk-leg")]
    assert [(r["attempt"], r["step"]) for r in result["walk_retries"]] == [(1, 12)]
    assert "world screen was not recognized" in result["walk_retries"][0]["error"]
    # The first move went out twice: once into the miss, once after the restore.
    assert measure._keys(guest) == "P L C V I E E S B B NP8 NP8 NP8 E S D N".split()
    assert '"event": "walk_retry"' in _log(tmp_path)


def test_a_walk_retry_that_runs_out_stops_the_run_naming_the_step(
        tmp_path, clock, readings, monkeypatch):  # noqa: F811
    guest = AcceptGuest(clock)
    fake = FakePipe(guest)
    monkeypatch.setattr(acceptance, "snapshot_pipe", lambda: fake)
    _, result = _accept(tmp_path, clock, guest=guest, guard=_encounter_guard(fake, 99),
                        walk_retry=1)
    assert result["success"] is False
    assert "step 12 (world) after 1 walk retries" in result["error"]
    assert [c[0] for c in fake.calls] == ["snapshot", "restore"]
    assert len(result["walk_retries"]) == 1


def test_without_walk_retry_the_walk_makes_no_snapshot_and_a_miss_is_unchanged(
        tmp_path, clock, readings, pipe):  # noqa: F811
    guest, result = _accept(tmp_path, clock)
    assert result["error"] == "" and "walk_retries" not in result
    assert pipe.calls == [] and measure._keys(guest) == KEYS


def test_a_walk_retry_snapshot_name_is_not_free_for_a_camp_step(
        tmp_path, clock, readings, pipe):  # noqa: F811
    with pytest.raises(RouteError, match="walk-leg"):
        _accept(tmp_path, clock, walk_retry=1, marks={14: (("snapshot", "Walk-Leg"),)})
    assert pipe.calls == []
