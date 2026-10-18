"""The Wish/WinUAE acceptance controller, without a VM or game disks."""

from __future__ import annotations

import argparse
import base64
import dataclasses
import io
import json
import pathlib
import struct
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from PIL import Image

from goldbox import amiga_dax
from goldbox.amiga_adf import AmigaDisk
from goldbox.geo import GEO_SIZE
from tests.amiga import test_maproute
from tools.amiga import winuaesession, winwishaccept

SHA = "0123456789abcdef0123456789abcdef01234567"


def _args(tmp_path, leg="mapping"):
    return argparse.Namespace(title="ssb", sha=SHA, holder="test-acw",
                              manifest=tmp_path / "prepare.json",
                              mute_proof=tmp_path / "mute.json", out=tmp_path,
                              deadline=3300, leg=leg)


def _phase(name, initial, *steps, ready=True, reason=None):
    return SimpleNamespace(name=name, initial_state=initial, steps=steps,
                           ready=ready, reason=reason)


def _step(kind, state, key=None, encounters=None):
    return SimpleNamespace(kind=kind, state=state, key=key,
                           drive=None, media=None, snapshot=None,
                           encounters=encounters, checkpoint=None, expected=None)


def _route(*, failed_walk=False):
    walk = _phase("walk", "world", _step("encounters", "world", encounters=True),
                  _step("move", "unknown" if failed_walk else "world", key="NP8"),
                  _step("move", "world", key="NP8"))
    phases = (_phase("load", "title", _step("key", "world", key="L")),
              _phase("stationary", "world"), walk,
              _phase("transition", "world"), _phase("reload", "world"),
              _phase("reopen_step", "world"))
    return SimpleNamespace(title="ssb", game_key="secret-of-the-silver-blades",
                           amiga_title=SimpleNamespace(wait_limits={}, title_limit=30, interstitials=()),
                           phases=phases, actions=(), media=(), mounted=(),
                           unresolved=(), provenance={}, loaded_slot="B")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.25
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeGame:
    def __init__(self):
        self.keys = []
        self.last_shot = {"source": "fake"}
        self._pipe = None

    def grab(self, state, raw, crop, timeout):
        pathlib.Path(raw).write_bytes(b"raw")
        pathlib.Path(crop).write_bytes(state.encode())
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)


@dataclass(frozen=True)
class Expected:
    engine: dict | None = None
    window: dict | None = None
    compare_to: str | None = None
    relation: str | None = None


def test_unrecognized_walk_stops_later_keys_restores_encounters_and_goes_down(tmp_path, monkeypatch):
    clock, game = FakeClock(), FakeGame()
    lane = SimpleNamespace(status=lambda timeout: "no claims")
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=lane, game=game,
        guards=lambda state, path: state != "unknown", route=_route(failed_walk=True),
        zipped=tmp_path / "build.zip", info={"media": {}, "build_sha": SHA},
        clock=clock, sleep=clock.sleep)
    calls = []

    def up(restarts_emulator=False):
        controller.booted = True
        game.holder = "test-acw"

    def section():
        controller.pipe_released = True

    def switch(enabled):
        controller.encounters_on = enabled
        calls.append(f"encounters-{enabled}")
        controller.encounters = SimpleNamespace(
            keys=lambda names: (game.keys.extend(names) or {"pressed": names}))

    monkeypatch.setattr(controller, "flag_controls", lambda: None)
    monkeypatch.setattr(controller, "_up", up)
    monkeypatch.setattr(controller, "_game_section", section)
    monkeypatch.setattr(controller, "_switch", switch)
    monkeypatch.setattr(winwishaccept.winwish, "collect_log", lambda *args: ["wish.log"])
    monkeypatch.setattr(winwishaccept.winwish, "down", lambda *args: calls.append("down") or {})
    result = controller.run_title()

    assert game.keys == ["L", "NP8"]
    assert calls == ["encounters-True", "encounters-False", "down"]
    assert "unknown screen was not recognized" in result["failure"]
    assert result["mapping"]["walk"]["status"] == "unproven"
    assert result["cleanup"]["errors"] == []
    assert (tmp_path / "summary.json").is_file()
    assert any("game_frame" in line for line in (tmp_path / "events.jsonl").read_text().splitlines())


def test_an_unready_transition_blocks_preflight_before_a_guest_call(tmp_path):
    args = _args(tmp_path)
    args.manifest.write_text("{}")
    route = _route()
    route.phases = tuple(_phase(p.name, p.initial_state, *p.steps,
                                ready=p.name != "transition",
                                reason="measured entrance guard missing" if p.name == "transition" else None)
                         for p in route.phases)
    guest = SimpleNamespace(gh=lambda *args: pytest.fail("guest touched before route readiness"))
    with pytest.raises(winwishaccept.AcceptanceStop, match="transition: measured entrance guard missing"):
        winwishaccept.preflight(args, guest=guest, route_for=lambda title, manifest: route,
                               driver_sha=SHA)


def test_controller_executes_transition_before_indoor_stationary(tmp_path, monkeypatch):
    route = _route()
    ordered = (route.phases[0], route.phases[3], route.phases[1], route.phases[2],
               route.phases[4], route.phases[5])
    route.phases = ordered
    clock = FakeClock()
    lane = SimpleNamespace(stop=lambda *args: None, start=lambda *args, **kwargs: None)
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=lane, game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    events = []
    monkeypatch.setattr(controller, "_up", lambda restarts_emulator=False: (events.append("up"), setattr(controller, "launch", ((), ()))))
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_await", lambda *args, **kwargs: {})
    monkeypatch.setattr(controller, "run_phase", lambda phase, namespace=None: events.append(
        f"{namespace}:{phase.name}" if namespace else phase.name))
    monkeypatch.setattr(controller, "flag_controls", lambda: None)
    monkeypatch.setattr(controller, "run_actions", lambda: None)
    monkeypatch.setattr(controller, "_cleanup", lambda: controller.summary["cleanup"].update(errors=[]))
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish",
                        lambda *args: events.append("stop_wish"))
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: None)

    result = controller.run_title()

    assert result["failure"] is None
    # The mapping leg ends at the disconnect grabs; restarting the game and reloading the
    # party belong to the reconnect leg, so no "reconnect-load:load" follows.
    assert events == ["up", "load", "transition", "stationary", "walk", "reload",
                      "stop_wish", "reopen_step"]


def test_the_disconnect_step_restarts_the_game_on_the_same_lane_and_regrabs_wish(
        tmp_path, monkeypatch):
    route = _route()
    clock = FakeClock()
    events = []
    lane = SimpleNamespace(
        stop=lambda *args: events.append("lane-stop"),
        start=lambda holder, *drives, timeout, options: events.append(
            ("lane-start", holder, drives, options)))
    controller = winwishaccept.Controller(
        _args(tmp_path, leg="reconnect"), guest=object(), lane=lane, game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=lambda seconds: (events.append(("sleep", seconds)), clock.sleep(seconds)))

    def up(restarts_emulator=False):
        controller.launch = (("C:/a.adf", "C:/b.adf"), ("nr_floppies=3",))

    monkeypatch.setattr(controller, "_up", up)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: events.append("map-tab"))
    monkeypatch.setattr(controller, "_await", lambda *args, **kwargs: {})
    monkeypatch.setattr(controller, "run_phase", lambda phase, namespace=None: None)
    monkeypatch.setattr(controller, "flag_controls", lambda: None)
    monkeypatch.setattr(controller, "run_actions", lambda: None)
    monkeypatch.setattr(controller, "_cleanup", lambda: controller.summary["cleanup"].update(errors=[]))
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish", lambda *args: None)
    monkeypatch.setattr(winwishaccept.winwish, "shot",
                        lambda guest, holder, window, path: events.append(("shot", holder, window, path.name)))

    result = controller.run_title()

    assert result["failure"] is None
    tail = events[events.index("lane-stop") - 1:]
    shots = [name for kind, *rest in tail if kind == "shot" for name in rest[-1:]]
    assert tail[0] == ("shot", "test-acw", "wish", "connected.png")
    assert shots == ["connected.png", "disconnect-0.png", "disconnect-1.png", "disconnect-2.png",
                     "reconnected.png"]
    assert tail[1] == "lane-stop"
    start = tail.index(("lane-start", "test-acw", ("C:/a.adf", "C:/b.adf"), ("nr_floppies=3",)))
    assert tail[start + 1] == "map-tab"
    assert tail[start + 2] == ("sleep", winwishaccept.ROSTER_SECONDS)
    assert tail[start + 3] == ("shot", "test-acw", "wish", "reconnected.png")
    assert tail.index(("shot", "test-acw", "wish", "disconnect-2.png")) < start
    assert result["mapping"]["reconnect"]["status"] == "awaiting image review"


def _disconnect_controller(tmp_path, monkeypatch, *, start=None, launch=((), ()),
                           reload_step=None, leg="reconnect", pipe=None, lanes=None, running=None):
    """A controller at the disconnect step, with the real cleanup and everything before it stubbed."""
    route = _route()
    clock = FakeClock()
    events = []
    lane = SimpleNamespace(
        stop=lambda *args: events.append("lane-stop"),
        start=start or (lambda *args, **kwargs: events.append("lane-start")),
        status=lambda timeout: "no claims")
    controller = winwishaccept.Controller(
        _args(tmp_path, leg=leg), guest=SimpleNamespace(lane_run=lambda holder: running), lane=lane, game=FakeGame(),
        guards=object(), route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)

    controller.up_calls = []

    def up(restarts_emulator=False):
        controller.up_calls.append(restarts_emulator)
        controller.booted = True
        controller.launch = launch
        controller.pipe = pipe
        controller.lanes = lanes

    monkeypatch.setattr(controller, "_up", up)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_await", lambda *args, **kwargs: {})
    controller.phases_run = []

    def run_phase(phase, namespace=None):
        controller.phases_run.append((phase.name, namespace))
        if namespace:
            events.append("reload")
            if reload_step:
                reload_step(controller)

    monkeypatch.setattr(controller, "run_phase", run_phase)
    monkeypatch.setattr(controller, "flag_controls", lambda: None)
    monkeypatch.setattr(controller, "run_actions", lambda: None)
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish", lambda *args: None)
    monkeypatch.setattr(winwishaccept.winwish, "shot",
                        lambda guest, holder, window, path: events.append(path.name))
    monkeypatch.setattr(winwishaccept.winwish, "collect_log", lambda *args: ["wish.log"])
    monkeypatch.setattr(winwishaccept.winwish, "down",
                        lambda *args: events.append("down") or {})
    return controller, events


def test_a_game_that_cannot_be_restarted_is_found_before_the_lane_is_stopped(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(tmp_path, monkeypatch, launch=None)

    result = controller.run_title()

    assert "launch settings were not recorded" in result["failure"]
    assert "lane-stop" not in events and "connected.png" not in events
    assert result["mapping"]["disconnect"]["status"] == "unproven"
    assert events[-1] == "down"


def test_a_failed_restart_leaves_the_row_unproven_and_still_goes_down(tmp_path, monkeypatch):
    def start(*args, **kwargs):
        raise winuaesession.RouteError("lane start timed out")

    controller, events = _disconnect_controller(tmp_path, monkeypatch, start=start)

    result = controller.run_title()

    assert "lane start timed out" in result["failure"]
    assert result["mapping"]["reconnect"]["status"] == "unproven"
    assert "lane start timed out" in result["mapping"]["reconnect"]["reason"]
    assert result["mapping"]["disconnect"]["status"] == "awaiting image review"
    assert events[-2:] == ["disconnect-2.png", "down"]
    assert result["cleanup"]["errors"] == []


def test_a_restarted_game_is_stopped_before_cleanup_copies_the_media(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(tmp_path, monkeypatch)

    result = controller.run_title()

    assert result["failure"] is None
    assert events[-3:] == ["reconnected.png", "lane-stop", "down"]
    assert events.count("lane-stop") == 2
    assert events.index("lane-start") < events.index("reload") < events.index("reconnected.png")
    assert controller.phases_run[-1] == ("load", "reconnect-load")


def test_the_reload_keys_use_their_own_budget_and_not_the_mapping_cap(tmp_path, monkeypatch):
    def press(controller):
        controller._press("L")

    controller, events = _disconnect_controller(tmp_path, monkeypatch, reload_step=press)
    cap = winwishaccept.ORDINARY_MAPPING_COMMANDS["ssb"]
    controller.mapping_commands = cap
    controller.action_commands = controller.action_limit

    result = controller.run_title()

    assert result["failure"] is None
    assert (controller.mapping_commands, controller.action_commands) == (cap, controller.action_limit)
    assert controller.reconnect_commands == 1 and controller.reconnect_limit is None
    assert controller.game.keys == ["L"]


def test_a_second_reload_key_is_stopped_by_the_reload_budget(tmp_path, monkeypatch):
    def press_twice(controller):
        controller._press("L")
        controller._press("L")

    controller, events = _disconnect_controller(tmp_path, monkeypatch, reload_step=press_twice)

    result = controller.run_title()

    assert "1-command reconnect cap" in result["failure"]
    assert controller.game.keys == ["L"]
    assert result["mapping"]["reconnect"]["status"] == "unproven"


def test_a_failed_reload_leaves_the_reconnect_row_unproven_with_its_reason(tmp_path, monkeypatch):
    def fail(controller):
        raise winwishaccept.AcceptanceStop("title was not recognized")

    controller, events = _disconnect_controller(tmp_path, monkeypatch, reload_step=fail)

    result = controller.run_title()

    assert result["mapping"]["reconnect"]["status"] == "unproven"
    assert "title was not recognized" in result["mapping"]["reconnect"]["reason"]
    assert "reconnected.png" not in events
    assert events[-2:] == ["lane-stop", "down"]
    assert controller.reconnect_limit is None


def test_up_records_the_floppies_and_settings_the_restart_will_reuse(tmp_path, monkeypatch):
    route = _route()
    route.mounted = ("a", "b", "c")
    route.amiga_title = SimpleNamespace(wait_limits={}, title_limit=30, interstitials=(),
                                        options=("scale=2",))
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=FakeClock(), sleep=FakeClock().sleep)
    controller.remotes = {"a": "C:/a.adf", "b": "C:/b.adf", "c": "C:/c.adf"}
    seen = []
    monkeypatch.setattr(winwishaccept.winwish, "up",
                        lambda guest, lane, values: seen.append(values) or {})

    controller._up()

    assert controller.launch == (("C:/a.adf", "C:/b.adf", "C:/c.adf"),
                                 ("nr_floppies=3", "floppy2type=0", "scale=2"))
    assert seen[0].df0 == "C:/a.adf" and seen[0].uae_option == ["scale=2"]


def test_up_says_whether_the_run_restarts_its_emulator(tmp_path, monkeypatch):
    route = _route()
    route.mounted = ("a",)
    route.amiga_title = SimpleNamespace(wait_limits={}, title_limit=30, interstitials=(), options=())
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=FakeClock(), sleep=FakeClock().sleep)
    controller.remotes = {"a": "C:/a.adf"}
    seen = []
    monkeypatch.setattr(winwishaccept.winwish, "up",
                        lambda guest, lane, values: seen.append(values) or {"winuae": "ok pid=1 pipe=WinUAE_1"})

    controller._up()
    controller._up(restarts_emulator=True)

    assert [values.keep_lanes for values in seen] == [False, False]
    assert [values.restarts_emulator for values in seen] == [False, True]
    assert controller.pipe == "WinUAE_1"


@pytest.mark.parametrize("leg", ["mapping", "reconnect"])
def test_the_disconnect_leg_claims_one_lane_and_says_it_restarts(tmp_path, monkeypatch, leg):
    controller, _ = _disconnect_controller(tmp_path, monkeypatch, leg=leg)

    controller.run_title()

    assert controller.up_calls == [True]


def test_a_restart_on_another_pipe_stops_with_both_names(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(
        tmp_path, monkeypatch, pipe="WinUAE", lanes="every",
        start=lambda *args, **kwargs: "ok pid=1 session=1 pipe=WinUAE_1")

    result = controller.run_title()

    assert "WinUAE_1" in result["failure"] and "not Wish's WinUAE" in result["failure"]
    assert result["mapping"]["reconnect"]["status"] != "awaiting image review"
    assert events[-1] == "down"


def test_a_restart_on_another_pipe_is_reconnected_when_wish_follows_the_lane(tmp_path, monkeypatch):
    controller, _ = _disconnect_controller(
        tmp_path, monkeypatch, pipe="WinUAE", lanes="one", running=(2, "WinUAE_1"),
        start=lambda *args, **kwargs: "ok pid=1 session=1 pipe=WinUAE_1")

    result = controller.run_title()

    assert result["failure"] is None
    assert result["mapping"]["reconnect"]["status"] == "awaiting image review"


@pytest.mark.parametrize("running", [(2, "WinUAE_2"), None])
def test_a_restart_whose_run_receipt_differs_from_the_reopened_pipe_stops(tmp_path, monkeypatch, running):
    controller, events = _disconnect_controller(
        tmp_path, monkeypatch, pipe="WinUAE", lanes="one", running=running,
        start=lambda *args, **kwargs: "ok pid=1 session=1 pipe=WinUAE_1")

    result = controller.run_title()

    assert "run receipt names" in result["failure"]
    assert result["mapping"]["reconnect"]["status"] != "awaiting image review"
    assert events[-1] == "down"


def test_a_restart_that_names_no_pipe_stops_even_when_wish_follows_the_lane(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(
        tmp_path, monkeypatch, pipe="WinUAE", lanes="one",
        start=lambda *args, **kwargs: "ok pid=1 session=1")

    result = controller.run_title()

    assert "named no pipe" in result["failure"]
    assert events[-1] == "down"


def test_a_restart_on_the_same_pipe_is_reconnected(tmp_path, monkeypatch):
    controller, _ = _disconnect_controller(
        tmp_path, monkeypatch, pipe="WinUAE_1",
        start=lambda *args, **kwargs: "ok pid=1 session=1 pipe=WinUAE_1")

    result = controller.run_title()

    assert result["failure"] is None
    assert result["mapping"]["reconnect"]["status"] == "awaiting image review"


@pytest.mark.parametrize("fault,reason", [
    ("missing", "required phases missing"),
    ("duplicate", "repeats a phase name"),
    ("load_order", "load must be the first phase"),
    ("walk_order", "stationary must precede walk"),
    ("reopen_order", "reload must precede reopen_step"),
    ("future_checkpoint", "checkpoint later must precede"),
    ("missing_checkpoint", "checkpoint absent must precede"),
    ("duplicate_checkpoint", "checkpoint mark is repeated"),
])
def test_invalid_phase_dependencies_stop_before_guest_up(tmp_path, fault, reason):
    route = _route()
    phases = list(route.phases)
    if fault == "missing":
        phases.pop(3)
    elif fault == "duplicate":
        phases.append(phases[3])
    elif fault == "load_order":
        phases[0], phases[1] = phases[1], phases[0]
    elif fault == "walk_order":
        phases[1], phases[2] = phases[2], phases[1]
    elif fault == "reopen_order":
        phases[4], phases[5] = phases[5], phases[4]
    else:
        first = _step("observe", "world")
        first.checkpoint = "mark"
        if fault in ("future_checkpoint", "missing_checkpoint"):
            first.expected = Expected(compare_to=(
                "later" if fault == "future_checkpoint" else "absent"))
            phases[1] = _phase("stationary", "world", first)
            if fault == "future_checkpoint":
                later = _step("observe", "world")
                later.checkpoint = "later"
                phases[2] = _phase("walk", "world", later)
        else:
            repeated = _step("observe", "world")
            repeated.checkpoint = "mark"
            phases[1] = _phase("stationary", "world", first, repeated)
    route.phases = tuple(phases)
    args = _args(tmp_path)
    args.manifest.write_text("{}")
    guest = SimpleNamespace(gh=lambda *args: pytest.fail("guest touched before route validation"))

    with pytest.raises(winwishaccept.AcceptanceStop, match=reason):
        winwishaccept.preflight(args, guest=guest, route_for=lambda title, manifest: route,
                               driver_sha=SHA)


def test_unreadable_checkpoint_stops_before_another_key(tmp_path, monkeypatch):
    from automap import amigaparty
    from tools.amiga import amigatarget

    clock, game = FakeClock(), FakeGame()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=game,
        guards=lambda state, path: True, route=_route(),
        zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    target = SimpleNamespace(fix=lambda: None, geo=lambda: None, close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: target)
    monkeypatch.setattr(amigaparty, "read_party", lambda target: None)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: 1)
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party|||"])
    phase = _phase("walk", "world",
                   SimpleNamespace(**{**vars(_step("observe", "world")),
                                      "checkpoint": "lost_fix",
                                      "expected": Expected(engine={"x": 3})}),
                   _step("move", "world", key="NP8"))
    with pytest.raises(winwishaccept.AcceptanceStop, match="lost_fix"):
        controller.run_phase(phase)
    assert game.keys == []
    assert controller.checkpoints["lost_fix"]["comparison"]["status"] == "unproven"


def test_a_loading_frame_without_a_game_crop_is_retried(tmp_path):
    clock, game = FakeClock(), FakeGame()
    count = 0

    def grab(state, raw, crop, timeout):
        nonlocal count
        count += 1
        pathlib.Path(raw).write_bytes(b"loading" if count == 1 else b"title")
        if count == 1:
            return False
        pathlib.Path(crop).write_bytes(b"title")
        return True

    game.grab = grab
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=game,
        guards=lambda state, path: pathlib.Path(path).read_bytes() == b"title",
        route=_route(), zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    frame = controller._await("title", limit=30)
    assert count == 2
    assert pathlib.Path(frame["crop"]).read_bytes() == b"title"
    assert (tmp_path / "game-000.raw.png").read_bytes() == b"loading"


def test_a_declared_travel_window_coordinate_is_checked(tmp_path):
    clock = FakeClock()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(),
        guards=object(), route=_route(), zipped=tmp_path / "build.zip",
        info={"media": {}}, clock=clock, sleep=clock.sleep)
    reading = {"fix": {"x": 8, "y": 29, "outdoors": True,
                       "facing": None, "area": 26}, "geo_sha256": "a"}
    verdict = controller._compare_checkpoint(
        "loaded", Expected(window={"x": 7, "y": 29}), reading)
    assert verdict["status"] == "failed"
    assert "window x" in verdict["reason"]


def test_a_declared_travel_direction_accepts_east_heading(tmp_path):
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(),
        guards=object(), route=_route(), zipped=tmp_path / "build.zip",
        info={"media": {}}, clock=FakeClock())
    reading = {"fix": {"x": 7, "y": 29, "outdoors": True,
                       "facing": None, "heading": 2, "area": 26},
               "geo_sha256": "a"}
    verdict = controller._compare_checkpoint(
        "loaded", Expected(engine={"facing": 1}, window={"x": 7, "y": 29}), reading)
    assert verdict["status"] == "awaiting image review"


def test_a_declared_travel_direction_rejects_missing_or_wrong_heading(tmp_path):
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(),
        guards=object(), route=_route(), zipped=tmp_path / "build.zip",
        info={"media": {}}, clock=FakeClock())
    for heading, status in ((None, "unproven"), (4, "failed")):
        reading = {"fix": {"x": 7, "y": 29, "outdoors": True,
                           "facing": None, "heading": heading, "area": 26},
                   "geo_sha256": "a"}
        verdict = controller._compare_checkpoint(
            "loaded", Expected(engine={"facing": 1}, window={"x": 7, "y": 29}),
            reading)
        assert verdict["status"] == status


def test_map_only_flag_controls_require_every_button_disabled(tmp_path, monkeypatch):
    clock = FakeClock()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=SimpleNamespace(**{**vars(_route()), "title": "pool"}),
        zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    controller.pipe_released = False
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    names = ("Heal party", "Save spells", "Restore spells", "Identify",
             "Quickfight off", "Fast Travel")
    modes = iter((True, False, True))
    def controls(*args):
        enabled = next(modes)
        # Fast Travel has no flag of its own, so it reads as it does with the flags on.
        return [f"Button|{name}|{name}|enabled={True if name == 'Fast Travel' else enabled}"
                for name in names]
    monkeypatch.setattr(winwishaccept.winwish, "ui", controls)
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: 1)
    restarts = []
    monkeypatch.setattr(winwishaccept.winwish, "restart_wish",
                        lambda *args, **kwargs: restarts.append(kwargs))
    controller.flag_controls()
    assert [entry["features"] for entry in restarts] == [False, True]
    assert all(value["status"] == "awaiting image review"
               for value in controller.summary["flags"].values())


def _flag_run(tmp_path, monkeypatch, readings):
    """Run flag_controls with readings[mode][name] -> enabled; returns the controller."""
    clock = FakeClock()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=SimpleNamespace(**{**vars(_route()), "title": "pool"}),
        zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    controller.pipe_released = False
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    modes = iter(readings)
    def controls(*args):
        reading = next(modes)
        return [f"Button|{name}|{name}|enabled={enabled}" for name, enabled in reading.items()]
    monkeypatch.setattr(winwishaccept.winwish, "ui", controls)
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: 1)
    monkeypatch.setattr(winwishaccept.winwish, "restart_wish", lambda *args, **kwargs: None)
    return controller


def _readings(actions, travel):
    names = ("Heal party", "Save spells", "Restore spells", "Identify", "Quickfight off")
    return {**{name: actions for name in names}, "Fast Travel": travel}


def test_map_only_leaves_fast_travel_enabled_as_with_the_flags_on(tmp_path, monkeypatch):
    # The pool-accept2 listings: only the five flagged actions change in map-only mode.
    controller = _flag_run(tmp_path, monkeypatch, [
        _readings(True, True), _readings(False, True), _readings(True, True)])
    controller.flag_controls()
    assert [value["status"] for value in controller.summary["flags"].values()] == [
        "awaiting image review"] * 3


def test_map_only_still_stops_on_an_enabled_action(tmp_path, monkeypatch):
    heal_on = {**_readings(False, True), "Heal party": True}
    controller = _flag_run(tmp_path, monkeypatch, [_readings(True, True), heal_on])
    with pytest.raises(winwishaccept.AcceptanceStop, match="map-only flag left an action enabled"):
        controller.flag_controls()


def test_map_only_stops_when_fast_travel_differs_from_the_flags_on_state(tmp_path, monkeypatch):
    controller = _flag_run(tmp_path, monkeypatch, [_readings(True, True), _readings(False, False)])
    with pytest.raises(winwishaccept.AcceptanceStop, match="changed Fast Travel"):
        controller.flag_controls()


def _action_controller(tmp_path, monkeypatch, *, guard=True):
    route = _route()
    show = _phase("show", "world", SimpleNamespace(**{**vars(_step("observe", "sheet")),
                                                       "checkpoint": "view", "expected": None}))
    back = _phase("back", "sheet", SimpleNamespace(**{**vars(_step("key", "world", "E")),
                                                      "checkpoint": "world", "expected": None}))
    route.actions = (SimpleNamespace(kind="heal", enabled=True, selector="hp", show=show, back=back),)
    clock, game = FakeClock(), FakeGame()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=game,
        guards=lambda state, path: guard if state == "sheet" else True,
        route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        controller.checkpoints.update({name: {"game": frame}}))
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args, **kwargs:
                        ["Button|Heal party|heal|enabled=True"])
    return controller, game


def test_heal_action_guards_before_click_and_keeps_distinct_visits(tmp_path, monkeypatch):
    controller, game = _action_controller(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(controller, "_action_input", lambda action: {
        "member": "A", "slot": 0, "before": [], "baseline": [], "staged": {"hp": 15}})
    monkeypatch.setattr(controller, "_action_readback", lambda: [])
    monkeypatch.setattr(controller, "_verify_action", lambda *args, **kwargs: None)
    original_grab = game.grab

    def grab(state, raw, crop, timeout):
        events.append(("frame", state))
        return original_grab(state, raw, crop, timeout)

    game.grab = grab

    def ui(*args, **kwargs):
        if args[2] == "click":
            events.append(("click", args[3]))
            return []
        return ["Button|Heal party|heal|enabled=True"]

    monkeypatch.setattr(winwishaccept.winwish, "ui", ui)
    controller.run_actions()
    assert events.index(("frame", "sheet")) < events.index(("click", ("Heal party",)))
    assert events.index(("click", ("Heal party",))) < len(events) - 2
    assert {"heal.before.view", "heal.after.view"} <= controller.checkpoints.keys()
    assert controller.summary["actions"]["heal"]["status"] == "awaiting image review"
    assert len(controller.summary["actions"]["heal"]["observed"]["clicks"]) == 1


@pytest.mark.parametrize("failed_after", [False, True])
def test_failed_action_view_stops_and_keeps_click_if_it_happened(tmp_path, monkeypatch,
                                                                  failed_after):
    controller, game = _action_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_action_input", lambda action: {
        "member": "A", "slot": 0, "before": [], "baseline": []})
    monkeypatch.setattr(controller, "_action_readback", lambda: [])
    monkeypatch.setattr(controller, "_verify_action", lambda *args, **kwargs: None)
    calls = []
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args, **kwargs:
                        calls.append(args[2]) or ["Button|Heal party|heal|enabled=True"])
    count = 0

    def guards(state, path):
        nonlocal count
        if state == "sheet":
            count += 1
            # The before visit sees the sheet both after Show and before Back.
            return count <= 2 if failed_after else False
        return True

    controller.guards = guards
    with pytest.raises(winwishaccept.AcceptanceStop):
        controller.run_actions()
    assert calls.count("click") == int(failed_after)
    entry = controller.summary["actions"]["heal"]
    assert entry["status"] == "unproven"
    assert len(entry["observed"]["clicks"]) == int(failed_after)
    assert (tmp_path / "game-000.raw.png").exists()


def test_action_bound_counts_visits_selections_and_original_reload(tmp_path):
    route = _route()
    pair = _phase("show", "world", _step("select", "world"), _step("key", "sheet", "V"))
    back = _phase("back", "sheet", _step("key", "world", "E"))
    route.actions = (SimpleNamespace(kind="heal", enabled=True, show=pair, back=back),)
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    assert controller.action_limit == 2 * (7 + 1 + 1) + 1 + 1
    for _ in range(controller.action_limit):
        controller._count(action=True)
    with pytest.raises(winwishaccept.AcceptanceStop, match="cap is reached"):
        controller._count(action=True)


def test_full_party_action_deltas_include_zero_hp_and_all_item_nodes(tmp_path):
    from automap import amigaparty

    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=_route(), zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    row = amigaparty.ROWS[controller.route.game_key]

    def record(slot, hp, maximum, flags=None):
        raw = bytearray(row.record_size)
        raw[row.hp.offset] = hp
        raw[row.hp_max.offset] = maximum
        item = []
        if flags is not None:
            node = bytearray(row.items.size)
            node[row.hidden.offset] = flags
            item = [[slot + 100, node.hex()]]
        return {"slot": slot, "name": f"Member{slot}", "address": slot + 1000,
                "raw": raw.hex(), "items": item}

    before = [record(0, 15, 20, 0x07), record(1, 7, 10, 0xA5), record(2, 0, 9)]
    healed = [record(0, 20, 20, 0x07), record(1, 10, 10, 0xA5), record(2, 0, 9)]
    controller._verify_action("heal", {"baseline": before}, healed)
    identified = [record(0, 15, 20, 0), record(1, 7, 10, 0xA0), record(2, 0, 9)]
    controller._verify_action("identify", {"baseline": before}, identified)
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("identify", {"baseline": before}, identified[:1] + before[1:])


def test_identify_ignores_the_item_text_the_game_rewrites_but_not_other_bytes(tmp_path):
    from automap import amigaparty

    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=_route(), zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    controller.route.game_key = "pool-of-radiance"
    row = amigaparty.ROWS[controller.route.game_key]
    assert row.title == "Pool of Radiance"
    text = winwishaccept.RECOMPOSED_ITEM_TEXT[row.title]
    assert text <= row.hidden.offset

    def member(node):
        return [{"slot": 0, "name": "Member0", "address": 1000,
                 "raw": bytes(row.record_size).hex(), "items": [[100, bytes(node).hex()]]}]

    node = bytearray(row.items.size)
    node[:7] = b"Long Sw"
    node[row.hidden.offset] = 7
    before = member(node)
    rewritten = bytearray(node)
    rewritten[:7] = b"\x00Yes  \x00"
    rewritten[row.hidden.offset] = 0
    controller._verify_action("identify", {"baseline": before}, member(rewritten))
    for offset in (row.hidden.offset + 1, text):
        bad = bytearray(rewritten)
        bad[offset] ^= 0x01
        with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
            controller._verify_action("identify", {"baseline": before}, member(bad))
    retexted = bytearray(node)
    retexted[:7] = b"\x00Yes  \x00"
    healed = member(retexted)
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("heal", {"baseline": before}, healed)
    wrong = bytearray(rewritten)
    wrong[row.hidden.offset] = 4
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("identify", {"baseline": before}, member(wrong))


def test_final_reload_is_separate_and_compares_original_party_and_location(tmp_path, monkeypatch):
    from automap import amigaparty

    controller, game = _action_controller(tmp_path, monkeypatch)
    controller.route.phases = tuple(
        _phase("reload", "world", SimpleNamespace(**{**vars(_step("key", "world", "L")),
                                                     "checkpoint": "returned", "expected": None}))
        if phase.name == "reload" else phase for phase in controller.route.phases)
    row = amigaparty.ROWS[controller.route.game_key]
    record = {"slot": 0, "name": "A", "address": 100,
              "raw": bytes(row.record_size).hex(), "items": []}
    initial = {"fix": {"area": 3, "x": 4, "y": 5}, "geo_sha256": "map",
               "party": [record]}
    controller.checkpoints["loaded"] = {"observed": initial}
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        controller.checkpoints.update({name: {"observed": {
                            **initial, "party": [{**record, "address": 500}]}}}))
    controller._final_reload()
    assert controller.summary["original_slot_reload"]["status"] == "awaiting image review"
    assert controller.checkpoints["loaded"]["observed"] is initial
    assert controller.action_commands == 1
    assert "original_slot_reload.returned" in controller.checkpoints

    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        controller.checkpoints.update({name: {"observed": {
                            **initial, "fix": {**initial["fix"], "x": 9}}}}))
    with pytest.raises(winwishaccept.AcceptanceStop, match="changed location"):
        controller._final_reload()
    assert controller.summary["original_slot_reload"]["status"] == "unproven"


@pytest.mark.parametrize("view,stops", [
    ({"outdoors": True}, False), ({"world_map": True}, False), ({}, True)])
def test_final_reload_compares_the_map_hash_only_in_an_area_view(tmp_path, monkeypatch, view,
                                                                  stops):
    from automap import amigaparty

    controller, game = _action_controller(tmp_path, monkeypatch)
    controller.route.phases = tuple(
        _phase("reload", "world", SimpleNamespace(**{**vars(_step("key", "world", "L")),
                                                     "checkpoint": "returned", "expected": None}))
        if phase.name == "reload" else phase for phase in controller.route.phases)
    row = amigaparty.ROWS[controller.route.game_key]
    record = {"slot": 0, "name": "A", "address": 100,
              "raw": bytes(row.record_size).hex(), "items": []}
    initial = {"fix": {"area": 3, "x": 4, "y": 5, **view}, "geo_sha256": "map",
               "party": [record]}
    controller.checkpoints["loaded"] = {"observed": initial}
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        controller.checkpoints.update({name: {"observed": {
                            **initial, "geo_sha256": "other"}}}))
    if stops:
        with pytest.raises(winwishaccept.AcceptanceStop, match="changed location or party"):
            controller._final_reload()
    else:
        controller._final_reload()
        assert controller.summary["original_slot_reload"]["status"] == "awaiting image review"


def test_spells_save_clear_and_restore_compare_all_members(tmp_path):
    from automap import amigaparty

    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=_route(), zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    row = amigaparty.ROWS[controller.route.game_key]

    def member(slot, values):
        raw = bytearray(row.record_size)
        raw[row.memorised.offset:row.memorised.offset + len(values)] = values
        return {"slot": slot, "name": f"Member{slot}", "address": slot + 100,
                "raw": raw.hex(), "items": []}

    baseline = [member(0, b"\x03\x04"), member(1, b"\x08\x09")]
    context = {"slot": 0, "spell_index": 0, "baseline": baseline}
    controller._verify_action("spells", context, baseline)
    controller._verify_action("spells", context,
                              [member(0, b"\x00\x04"), member(1, b"\x08\x09")], step="cleared")
    controller._verify_action("spells", context, baseline)
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("spells", context,
                                  [member(0, b"\x03\x04"), member(1, b"\x08\x00")])


def test_staging_preserves_every_other_member_and_item(tmp_path):
    from automap import amigaparty

    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=_route(), zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    row = amigaparty.ROWS[controller.route.game_key]

    def member(slot, hp):
        raw = bytearray(row.record_size)
        raw[row.slot] = slot
        raw[row.hp.offset] = hp
        raw[row.hp_max.offset] = 20
        return amigaparty.AmigaMember(row, slot, 1000 + slot * 100, bytes(raw))

    party = [member(0, 20), member(1, 7)]
    before = [controller._member_record(member) for member in party]
    modified = bytearray(party[0].raw)
    modified[row.hp.offset] = 15
    staged = [amigaparty.AmigaMember(row, 0, party[0].address, bytes(modified)), party[1]]
    context = {"slot": 0, "before": before,
               "baseline": [controller._member_record(member) for member in staged],
               "staged": {"hp": 15}}
    controller._verify_staging("heal", context, party)
    context["baseline"][1]["raw"] = bytes(row.record_size).hex()
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected byte"):
        controller._verify_staging("heal", context, party)


def test_save_spells_releases_the_pipe_before_readback(tmp_path, monkeypatch):
    controller, _game = _action_controller(tmp_path, monkeypatch)
    controller.route.actions[0].kind = "spells"
    controller.summary["actions"]["spells"] = controller.summary["actions"].pop("heal")
    controller.action_limit = winwishaccept._action_budget(controller.route)
    controller.pipe_released = False
    monkeypatch.setattr(controller, "_action_input", lambda action: {
        "member": "A", "slot": 0, "spell_index": 0, "before": [], "baseline": []})
    monkeypatch.setattr(controller, "_verify_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, "_action_readback", lambda: (
        pytest.fail("readback while Wish owns the pipe") if not controller.pipe_released else []))
    monkeypatch.setattr(controller, "_game_section", lambda: setattr(controller, "pipe_released", True))
    monkeypatch.setattr(controller, "_map_section", lambda: setattr(controller, "pipe_released", False))
    monkeypatch.setattr(controller, "_fresh_party", lambda: (
        SimpleNamespace(write=lambda *args: None, close=lambda: None),
        [SimpleNamespace(slot=0, address=100,
                         row=SimpleNamespace(memorised=SimpleNamespace(offset=5)))]))
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args, **kwargs: [
        "Button|Save spells|save|enabled=True",
        "Button|Restore spells|restore|enabled=True"])
    controller.run_actions()
    assert controller.summary["actions"]["spells"]["status"] == "awaiting image review"


@pytest.fixture(autouse=True)
def _no_wish_log_errors(monkeypatch):
    monkeypatch.setattr(winwishaccept.winwish, "wish_log_errors", lambda guest, holder: [])


VALUE_ERROR_BLOCK = {
    "file": "wish-20261016-195731.log",
    "lines": ["20:21:04 ERROR unhandled exception",
              "Traceback (most recent call last):",
              "ValueError: A write of 141 bytes is not between 1 and 64."],
    "exception": "ValueError: A write of 141 bytes is not between 1 and 64."}


def _spells_controller(tmp_path, monkeypatch):
    controller, _game = _action_controller(tmp_path, monkeypatch)
    controller.route.actions[0].kind = "spells"
    controller.summary["actions"]["spells"] = controller.summary["actions"].pop("heal")
    controller.action_limit = winwishaccept._action_budget(controller.route)
    monkeypatch.setattr(controller, "_action_input", lambda action: {
        "member": "A", "slot": 0, "spell_index": 0, "before": [], "baseline": []})
    monkeypatch.setattr(controller, "_action_readback", lambda: [])
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_fresh_party", lambda: (
        SimpleNamespace(write=lambda *args: None, close=lambda: None),
        [SimpleNamespace(slot=0, address=100,
                         row=SimpleNamespace(memorised=SimpleNamespace(offset=5)))]))
    return controller


def _clicking(clicked):
    def ui(*args, **kwargs):
        if args[2] == "click":
            clicked.append(args[3])
            return ["ok"]
        return ["Button|Save spells|save|enabled=True",
                "Button|Restore spells|restore|enabled=True"]
    return ui


def test_an_exception_in_wishs_log_after_restore_spells_stops_the_run(tmp_path, monkeypatch):
    controller = _spells_controller(tmp_path, monkeypatch)
    clicked: list = []
    verified: list = []
    monkeypatch.setattr(controller, "_verify_action", lambda kind, context, after, step="action": (
        verified.append(step)))
    monkeypatch.setattr(winwishaccept.winwish, "ui", _clicking(clicked))
    monkeypatch.setattr(winwishaccept.winwish, "wish_log_errors", lambda guest, holder: (
        [VALUE_ERROR_BLOCK] if ("Restore spells",) in clicked else []))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="ValueError: A write of 141 bytes is not between 1 and 64."):
        controller.run_actions()
    reason = controller.summary["actions"]["spells"]["reason"]
    assert "after Restore spells" in reason and "ValueError: A write of 141 bytes" in reason
    # Only the Save spells and cleared checks ran; the Restore spells check did not.
    assert verified == ["action", "cleared"]


def test_a_block_already_in_wishs_log_before_the_click_does_not_stop_the_run(tmp_path, monkeypatch):
    controller = _spells_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_verify_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(winwishaccept.winwish, "ui", _clicking([]))
    monkeypatch.setattr(winwishaccept.winwish, "wish_log_errors",
                        lambda guest, holder: [VALUE_ERROR_BLOCK])
    controller.run_actions()
    assert controller.summary["actions"]["spells"]["status"] == "awaiting image review"


def test_an_unreadable_wish_log_is_recorded_and_the_run_goes_on(tmp_path, monkeypatch):
    controller = _spells_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_verify_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(winwishaccept.winwish, "ui", _clicking([]))

    def unreadable(guest, holder):
        raise winwishaccept.winwish.GuestError("the guest said: nothing", step="wish log",
                                               exit_code=1, command_length=0)

    monkeypatch.setattr(winwishaccept.winwish, "wish_log_errors", unreadable)
    events: list = []
    real_log = controller.log
    monkeypatch.setattr(controller, "log", lambda event, **kw: (events.append(event), real_log(event, **kw))[1])
    controller.run_actions()
    assert controller.summary["actions"]["spells"]["status"] == "awaiting image review"
    assert "wish_log_unread" in events
    # An unreadable mark skips the check, so each of the two clicks counts once.
    assert controller.summary["wish_log_unread"] == 2


def test_dispatched_click_without_acknowledgement_keeps_uncertain_attempt(tmp_path, monkeypatch):
    controller, _game = _action_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_action_input", lambda action: {
        "member": "A", "slot": 0, "before": [], "baseline": []})
    monkeypatch.setattr(controller, "_action_readback", lambda: [])
    attempts = []

    def ui(*args, **kwargs):
        if args[2] == "click":
            attempts.append(args[3])
            raise RuntimeError("response lost after dispatch")
        return ["Button|Heal party|heal|enabled=True"]

    monkeypatch.setattr(winwishaccept.winwish, "ui", ui)
    with pytest.raises(winwishaccept.AcceptanceStop, match="no acknowledgement"):
        controller.run_actions()
    entry = controller.summary["actions"]["heal"]
    assert entry["status"] == "unproven"
    assert attempts == [("Heal party",)]
    assert len(entry["observed"]["clicks"]) == 1
    click = entry["observed"]["clicks"][0]
    assert click["control"] == "Heal party"
    assert pathlib.Path(click["listing"]).is_file()
    assert click["acknowledged"] is False


def test_failed_action_after_view_retains_before_checkpoint_and_failed_frame(tmp_path, monkeypatch):
    controller, _game = _action_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_action_input", lambda action: {
        "member": "A", "slot": 0, "before": [], "baseline": []})
    monkeypatch.setattr(controller, "_action_readback", lambda: [])
    monkeypatch.setattr(controller, "_verify_action", lambda *args, **kwargs: None)
    count = 0

    def guard(state, path):
        nonlocal count
        if state == "sheet":
            count += 1
            return count <= 2
        return True

    controller.guards = guard
    with pytest.raises(winwishaccept.AcceptanceStop):
        controller.run_actions()
    entry = controller.summary["actions"]["heal"]
    assert entry["status"] == "unproven"
    assert "heal.before.view" in entry["evidence"]
    assert "heal.after.view" not in entry["evidence"]
    assert str(sorted(tmp_path.glob("game-*.raw.png"))[-1]) in entry["evidence"]
    assert entry["observed"]["clicks"][0]["acknowledged"] is True


def test_levelup_checks_every_selected_record_byte_and_hit_point_arithmetic(tmp_path):
    from automap import amigalevelup as levelup
    from automap import amigaparty

    route = _route()
    route.title, route.game_key = "darkness", levelup.POOLS_OF_DARKNESS
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    row = amigaparty.ROWS[route.game_key]
    raw = bytearray(row.record_size)
    raw[0x58], raw[0x79], raw[0x9D + 2] = 5, 18, 8
    raw[0x44:0x48] = levelup.pod_threshold(2, 9).to_bytes(4, "big")
    raw[0x81], raw[0x191] = 80, 50
    item = [[900, bytes(row.items.size).hex()]]
    baseline = {"slot": 0, "name": "A", "address": 100, "raw": raw.hex(), "items": item}
    context = {"slot": 0, "baseline": [baseline], "levelup_effects": []}

    class Dice:
        def randint(self, low, high):
            return 9

    trained = bytearray(levelup.apply_to(
        raw, levelup.plan(raw, route.game_key, rng=Dice(),
                          items=[bytes.fromhex(item[0][1])])))
    valid = {**baseline, "raw": trained.hex()}
    controller._verify_action("levelup", context, [valid])
    unrelated = bytearray(trained)
    unrelated[0x10] ^= 1
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("levelup", context, [{**valid, "raw": unrelated.hex()}])
    wrong_hp = bytearray(trained)
    wrong_hp[0x81] += 1
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("levelup", context, [{**valid, "raw": wrong_hp.hex()}])
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("levelup", context, [{**valid, "items": []}])


def _pod_party(ready_slots, tmp_path):
    """Four Pools of Darkness members; those in `ready_slots` already have the fighter's
    experience for the next level."""
    from automap import amigalevelup as levelup
    from automap import amigaparty

    row = amigaparty.ROWS[levelup.POOLS_OF_DARKNESS]
    members = []
    for slot in range(4):
        raw = bytearray(row.record_size)
        raw[row.slot], raw[0x58], raw[0x79], raw[0x9D + 2] = slot, 5, 18, 8
        raw[0x81], raw[0x191] = 80, 50
        experience = levelup.pod_threshold(2, 9) if slot in ready_slots else 0
        raw[levelup._POD_EXPERIENCE:levelup._POD_EXPERIENCE + 4] = experience.to_bytes(4, "big")
        raw[row.name:row.name + 2] = b"M" + bytes([ord("0") + slot])
        members.append(amigaparty.AmigaMember(row, slot, 0x1000 + 0x200 * slot, bytes(raw)))
    return members


def _levelup_controller(tmp_path, monkeypatch, members):
    from automap import amigalevelup as levelup
    from automap import amigaparty

    route = _route()
    route.title, route.game_key = "darkness", levelup.POOLS_OF_DARKNESS
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    writes = []

    class Target:
        def write(self, address, data):
            writes.append((address, bytes(data)))
            for index, member in enumerate(members):
                at = address - member.address
                if 0 <= at < len(member.raw):
                    raw = bytearray(member.raw)
                    raw[at:at + len(data)] = data
                    members[index] = dataclasses.replace(member, raw=bytes(raw))

        def close(self):
            pass

    monkeypatch.setattr(controller, "_fresh_party", lambda: (Target(), list(members)))
    monkeypatch.setattr(amigaparty, "read_party", lambda target: list(members))
    return controller, writes


def test_levelup_picks_the_first_eligible_member_when_several_cards_are_enabled(
        tmp_path, monkeypatch):
    members = _pod_party({1, 2, 3}, tmp_path)
    controller, writes = _levelup_controller(tmp_path, monkeypatch, members)
    context = controller._action_input(SimpleNamespace(kind="levelup", selector="levelup"))
    assert context["slot"] == 1 and context["member"] == "M1"
    assert writes == []


def test_levelup_stages_the_first_member_that_can_be_raised_when_none_is_eligible(
        tmp_path, monkeypatch):
    from automap import amigalevelup as levelup

    members = _pod_party(set(), tmp_path)
    controller, writes = _levelup_controller(tmp_path, monkeypatch, members)
    context = controller._action_input(SimpleNamespace(kind="levelup", selector="levelup"))
    assert context["slot"] == 0
    assert writes == [(members[0].address + levelup._POD_EXPERIENCE,
                       levelup.pod_threshold(2, 9).to_bytes(4, "big"))]


def test_levelup_clicks_the_chosen_members_own_card_among_several_enabled(tmp_path, monkeypatch):
    members = _pod_party({0, 1, 2, 3}, tmp_path)
    controller, _ = _levelup_controller(tmp_path, monkeypatch, members)
    prefix = "QApplication.WishWindow.centralwidget.tabs.automap_roster_inner"
    listing = []
    for n in range(4):
        listing.append(f"Text|M{n}  |{prefix}.card_{n}.card_{n}_name|enabled=True||1.{n}|offscreen=False|0,0,1,1")
        listing.append(f"Button|Level up|{prefix}.card_{n}.card_{n}_level_up|enabled=True||2.{n}|offscreen=False|0,0,1,1")
    clicks = []

    def ui(guest, holder, command, labels=(), **kwargs):
        if command == "click":
            clicks.append(kwargs["automation_id"])
            return None
        return listing

    monkeypatch.setattr(winwishaccept.winwish, "ui", ui)
    context = {"kind": "levelup", "member": "M2", "slot": 2, "evidence": [], "clicks": []}
    controller._unique_action(automation_id="card_2_level_up", context=context)
    assert clicks == ["card_2_level_up"]
    wrong = {"kind": "levelup", "member": "M3", "slot": 2, "evidence": [], "clicks": []}
    with pytest.raises(winwishaccept.AcceptanceStop, match="does not name M3"):
        controller._unique_action(automation_id="card_2_level_up", context=wrong)
    listing[5] = listing[5].replace("enabled=True", "enabled=False")
    with pytest.raises(winwishaccept.AcceptanceStop, match="absent, ambiguous or disabled"):
        controller._unique_action(automation_id="card_2_level_up", context=dict(context, evidence=[]))


def test_levelup_stops_when_a_member_other_than_the_selected_one_changes(tmp_path, monkeypatch):
    from automap import amigalevelup as levelup

    members = _pod_party({0, 1}, tmp_path)
    controller, _ = _levelup_controller(tmp_path, monkeypatch, members)
    records = [controller._member_record(member) for member in members]
    context = {"slot": 0, "baseline": records, "levelup_effects": []}

    class Dice:
        def randint(self, low, high):
            return 9

    def trained(member):
        return levelup.apply_to(member.raw, levelup.plan_member(member, levelup.POOLS_OF_DARKNESS,
                                                                  rng=Dice())).hex()

    after = [dict(record) for record in records]
    after[0]["raw"] = trained(members[0])
    controller._verify_action("levelup", context, after)
    after[1]["raw"] = trained(members[1])
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("levelup", context, after)


_TITLES = {  # route title, game key, the title's threshold, experience offset
    "pool": ("pool-of-radiance", "por_threshold", "_POR_EXPERIENCE"),
    "curse": ("curse-of-the-azure-bonds", "curse_threshold", "_CU_EXPERIENCE"),
    "ssb": ("secret-of-the-silver-blades", "ssb_threshold", "_SB_EXPERIENCE"),
}


def _title_fighter(title, *, extra_class=None, ready=False):
    """A synthetic level-1 fighter record of the title, with 10/10 hit points and CON 16."""
    from automap import amigalevelup as lv
    from automap import amigaparty

    key = _TITLES[title][0]
    levels_at, con, hp_max, hp_current, cls, slots = {
        "pool": (lv._POR_LEVELS, lv._POR_CONSTITUTION, lv._POR_HP_MAX, lv._POR_HP_CURRENT,
                 lv._POR_CLASS, lv.POR_SLOTS),
        "curse": (lv._CU_LEVELS, lv._CU_CONSTITUTION, lv._CU_HP_MAX, lv._CU_HP_CURRENT,
                  lv._CU_CLASS, lv.CURSE_SLOTS),
        "ssb": (lv._SB_LEVELS, lv._SB_CONSTITUTION, lv._SB_HP_MAX, lv._SB_HP_CURRENT,
                None, lv.SSB_SLOTS),
    }[title]
    threshold = getattr(lv, _TITLES[title][1])
    experience = getattr(lv, _TITLES[title][2])
    raw = bytearray(amigaparty.ROWS[key].record_size)
    fighter = slots.index("fighter")
    raw[levels_at + fighter] = 1
    held = [fighter]
    if extra_class is not None:
        raw[levels_at + slots.index(extra_class)] = 1
        held.append(slots.index(extra_class))
    raw[con], raw[hp_max], raw[hp_current] = 16, 10, 10
    if cls is not None:
        raw[cls] = 2
    if ready:
        need = max(threshold(slot, 2) for slot in held)
        raw[experience:experience + 4] = need.to_bytes(4, "big")
    return raw, fighter


def _title_party(title, specs):
    """Members from (extra_class, ready) pairs, one per slot."""
    from automap import amigaparty

    key = _TITLES[title][0]
    row = amigaparty.ROWS[key]
    members = []
    for slot, (extra, ready) in enumerate(specs):
        raw, _ = _title_fighter(title, extra_class=extra, ready=ready)
        raw[row.slot] = slot
        raw[row.name:row.name + 2] = b"M" + bytes([ord("0") + slot])
        members.append(amigaparty.AmigaMember(row, slot, 0x1000 + 0x200 * slot, bytes(raw)))
    return members


def _title_controller(tmp_path, monkeypatch, title, members):
    controller, writes = _levelup_controller(tmp_path, monkeypatch, members)
    controller.route.title, controller.route.game_key = title, _TITLES[title][0]
    return controller, writes


@pytest.mark.parametrize("title", sorted(_TITLES))
def test_levelup_stages_the_title_threshold_when_none_is_eligible(title, tmp_path, monkeypatch):
    from automap import amigalevelup as lv

    members = _title_party(title, [(None, False)] * 2)
    controller, writes = _title_controller(tmp_path, monkeypatch, title, members)
    context = controller._action_input(SimpleNamespace(kind="levelup", selector="levelup"))
    threshold = getattr(lv, _TITLES[title][1])
    fighter = _title_fighter(title)[1]
    assert context["slot"] == 0
    assert writes == [(members[0].address + getattr(lv, _TITLES[title][2]),
                       threshold(fighter, 2).to_bytes(4, "big"))]


@pytest.mark.parametrize("title", ["pool", "curse", "ssb", "darkness"])
def test_levelup_verifies_hit_point_arithmetic_on_every_title(title, tmp_path):
    from automap import amigalevelup as levelup
    from automap import amigaparty

    key = levelup.POOLS_OF_DARKNESS if title == "darkness" else _TITLES[title][0]
    route = _route()
    route.title, route.game_key = title, key
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    row = amigaparty.ROWS[key]
    if title == "darkness":
        raw = bytearray(row.record_size)
        raw[0x58], raw[0x79], raw[0x9D + 2] = 5, 18, 8
        raw[0x44:0x48] = levelup.pod_threshold(2, 9).to_bytes(4, "big")
        raw[0x81], raw[0x191] = 80, 50
    else:
        raw, _ = _title_fighter(title, ready=True)
    offsets = controller._levelup_offsets(key)
    item = [[900, bytes(row.items.size).hex()]]
    baseline = {"slot": 0, "name": "A", "address": 100, "raw": raw.hex(), "items": item}
    context = {"slot": 0, "baseline": [baseline], "levelup_effects": []}

    class Dice:
        def randint(self, low, high):
            return 9

    trained = bytearray(levelup.apply_to(
        bytes(raw), levelup.plan(bytes(raw), key, rng=Dice(), items=[bytes.fromhex(item[0][1])])))
    assert trained[offsets.hp_max] != raw[offsets.hp_max]
    valid = {**baseline, "raw": trained.hex()}
    controller._verify_action("levelup", context, [valid])
    unrelated = bytearray(trained)
    unrelated[0x10] ^= 1
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("levelup", context, [{**valid, "raw": unrelated.hex()}])
    wrong_hp = bytearray(trained)
    wrong_hp[offsets.hp_max] += 1
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("levelup", context, [{**valid, "raw": wrong_hp.hex()}])
    with pytest.raises(winwishaccept.AcceptanceStop, match="unexpected bytes"):
        controller._verify_action("levelup", context, [{**valid, "items": []}])


def test_levelup_skips_a_member_whose_press_asks_for_a_spell(tmp_path, monkeypatch):
    from automap import amigalevelup as levelup

    members = _pod_party({0, 1}, tmp_path)
    controller, writes = _levelup_controller(tmp_path, monkeypatch, members)
    real = levelup.plan_member

    def plan_member(member, key, **kwargs):
        if member.slot == 0:
            raise levelup.NeedsSpell([1])
        return real(member, key, **kwargs)

    monkeypatch.setattr(levelup, "plan_member", plan_member)
    context = controller._action_input(SimpleNamespace(kind="levelup", selector="levelup"))
    assert context["slot"] == 1 and writes == []


def test_levelup_stops_before_any_write_when_no_member_qualifies(tmp_path, monkeypatch):
    from automap import amigalevelup as levelup

    members = _pod_party(set(), tmp_path)
    controller, writes = _levelup_controller(tmp_path, monkeypatch, members)

    def plan_member(member, key, **kwargs):
        raise levelup.CannotLevel("no")

    monkeypatch.setattr(levelup, "plan_member", plan_member)
    with pytest.raises(winwishaccept.AcceptanceStop, match="none can be staged"):
        controller._action_input(SimpleNamespace(kind="levelup", selector="levelup"))
    assert writes == []


@pytest.mark.parametrize("title,chosen", [("pool", 1), ("curse", 1), ("ssb", 0)])
def test_levelup_skips_a_multiclass_member_on_pool_and_curse(title, chosen, tmp_path, monkeypatch):
    members = _title_party(title, [("cleric", True), (None, True)])
    controller, _ = _title_controller(tmp_path, monkeypatch, title, members)
    context = controller._action_input(SimpleNamespace(kind="levelup", selector="levelup"))
    assert context["slot"] == chosen


def test_pool_persist_preflight_accepts_every_action(tmp_path):
    from tools.amiga import maproute

    route = maproute.route_for("pool", test_maproute._manifest("pool", tmp_path))
    for kind in ("heal", "identify", "quickfight", "levelup"):
        actions = winwishaccept._check_persist(SimpleNamespace(action=[kind]), route)
        assert [action.kind for action in actions] == [kind]


def _packed_map(raw):
    """Encode a synthetic DAX block with literal runs in reverse read order."""
    bits = []
    for start in range(0, len(raw), 8):
        chunk = raw[::-1][start:start + 8]
        bits.extend((0, 0, *((len(chunk) - 1) >> shift & 1 for shift in (2, 1, 0))))
        bits.extend(byte >> shift & 1 for byte in chunk for shift in range(7, -1, -1))
    bits.extend([0] * (-len(bits) % 32))
    words = [sum(bit << offset for offset, bit in enumerate(bits[start:start + 32]))
             for start in range(0, len(bits), 32)]
    check = 1
    for word in words:
        check ^= word
    result = (b"".join(struct.pack(">I", word) for word in reversed(words))
              + struct.pack(">III", 1, check, len(raw)))
    assert amiga_dax.unpack(result, len(raw)) == raw
    return result


def _dax_map(ident, geo):
    block = _packed_map(b"\x00\x04" + geo)
    entry = amiga_dax.ENTRY.pack(ident, 0, len(block), GEO_SIZE + 2)
    return struct.pack(">H", len(entry)) + entry + block


def _glib_maps(entries):
    index = struct.pack(">H", len(entries)) + b"".join(
        struct.pack(">HH", ident, number) for number, (ident, _) in enumerate(entries, 1))
    blocks = [index, *(geo for _, geo in entries)]
    start = 16 + 4 * (len(blocks) + 1)
    offsets = [start]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    return (b"GLIB" + struct.pack(">IHH", sum(map(len, blocks)), len(blocks), 0)
            + b"GEO " + b"".join(struct.pack(">I", offset) for offset in offsets)
            + b"".join(blocks))


def _map_controller(tmp_path, title, *images):
    route = _route()
    route.title = title
    route.media = tuple(SimpleNamespace(path=image) for image in images)
    return winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())


def test_pool_dax_identifies_area_26_from_a_matching_resident_map(tmp_path):
    resident = bytes((index * 37 + 11) & 0xff for index in range(GEO_SIZE))
    disk = AmigaDisk.blank("POOLDATA")
    disk.write_file("geo.dax", _dax_map(26, resident))
    image = tmp_path / "pool2.adf"
    image.write_bytes(disk.to_bytes())
    controller = _map_controller(tmp_path, "pool", image)

    assert controller._area_of(resident) == 26
    assert controller._area_of(bytes(GEO_SIZE)) is None


def test_library_lookup_remains_valid_without_pool_dax_fallback(tmp_path):
    resident = bytes((index * 13 + 3) & 0xff for index in range(GEO_SIZE))
    disk = AmigaDisk.blank("Secret 2")
    disk.make_dir("DISK2")
    disk.write_file("DISK2/GEO.GLB", _glib_maps([(0x10, resident)]))
    image = tmp_path / "secret2.adf"
    image.write_bytes(disk.to_bytes())

    assert _map_controller(tmp_path, "ssb", image)._area_of(resident) == 0x10


def test_pool_library_takes_precedence_over_dax_on_same_medium(tmp_path):
    resident = bytes((index * 17 + 5) & 0xff for index in range(GEO_SIZE))
    disk = AmigaDisk.blank("POOLDATA")
    disk.write_file("GEO.GLB", _glib_maps([(0x10, resident)]))
    disk.write_file("geo.dax", _dax_map(26, resident))
    image = tmp_path / "both.adf"
    image.write_bytes(disk.to_bytes())

    assert _map_controller(tmp_path, "pool", image)._area_of(resident) == 0x10


def test_other_titles_do_not_consult_dax_without_a_library(tmp_path):
    resident = bytes((index * 19 + 9) & 0xff for index in range(GEO_SIZE))
    disk = AmigaDisk.blank("Secret 2")
    disk.write_file("geo.dax", _dax_map(26, resident))
    image = tmp_path / "secret2.adf"
    image.write_bytes(disk.to_bytes())

    assert _map_controller(tmp_path, "ssb", image)._area_of(resident) is None


def test_identical_maps_with_two_ids_remain_ambiguous(tmp_path):
    resident = bytes((index * 23 + 7) & 0xff for index in range(GEO_SIZE))
    disk = AmigaDisk.blank("Secret 2")
    disk.write_file("GEO.GLB", _glib_maps([(0x10, resident), (0x1a, resident)]))
    image = tmp_path / "ambiguous.adf"
    image.write_bytes(disk.to_bytes())

    assert _map_controller(tmp_path, "ssb", image)._area_of(resident) is None


def _discovery_route(tmp_path):
    from tools.amiga import maproute, route_silver_blades

    route = _route()
    route.amiga_title = SimpleNamespace(
        wait_limits=route_silver_blades.OPENING_WAIT_LIMITS, title_limit=30,
        interstitials=route_silver_blades.PUBLISHED_INTERSTITIALS)
    route.loaded_slot = "D"
    route.mounted = ("df0", "df1")
    route.phases = (maproute._load("ssb", "D", opening_scene=True), maproute._ssb_stationary(),
                    maproute._ssb_walk(), *(_phase(p.name, p.initial_state,
                                                   ready=False, reason="unmeasured")
                                            for p in route.phases[3:]))
    route.actions = maproute._actions("ssb")
    route.guard_path = tmp_path / "guards_silver_blades.json"
    route.media = tuple(SimpleNamespace(key=key, path=tmp_path / f"{key}.adf",
                                        sha256=winwishaccept.digest(tmp_path / f"{key}.adf"))
                        for key in route.mounted)
    return route


def _discovery_args(tmp_path):
    args = _args(tmp_path)
    args.discover = "ssb-leave"
    args.deadline = 1800
    return args


def test_discovery_preflight_only_accepts_measured_prefix(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    args = _discovery_args(tmp_path)
    args.manifest.write_text('{"title":"ssb","substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    pinned = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
              "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path, sha256=pinned[m.key])
                        for m in route.media)
    original_digest = winwishaccept.digest
    monkeypatch.setattr(winwishaccept, "digest", lambda path: pinned[path.stem]
                        if path.suffix == ".adf" else original_digest(path))
    route.guard_path.write_text("{}")
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda executable: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda args: (
        (pathlib.Path(args[args.index("--out") + 1]) / "guards.json").write_text("{}") and 0))
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={name: True for phase in route.phases[:3]
               for name in (phase.initial_state, *(s.state for s in phase.steps))}
        | {"continue": True}))
    zip_path = tmp_path / "artifact.zip"
    zip_path.write_bytes(b"build")
    (tmp_path / winwishaccept.winwish.COMMIT_FILE).write_text(SHA)
    monkeypatch.setattr(winwishaccept.winwish, "fetch", lambda *args: zip_path)
    monkeypatch.setattr(winwishaccept.winwish, "pick_run", lambda *args: 17)
    monkeypatch.setattr(winwishaccept.winwish, "check_zip_commit", lambda *args: None)
    guest = SimpleNamespace(gh=lambda *args: "[]")
    result = winwishaccept.preflight(args, guest=guest, route_for=lambda *args: route,
                                      driver_sha=SHA)
    assert result[0] is route
    assert result[3]["media"]["df0"]["source_sha256"] == route.media[0].sha256
    assert result[3]["provenance"]["approved_media_sha256"] == pinned
    ordinary = _args(tmp_path)
    ordinary.out = tmp_path / "ordinary"
    with pytest.raises(winwishaccept.AcceptanceStop, match="route incomplete"):
        winwishaccept.preflight(ordinary, guest=guest, route_for=lambda *args: route,
                                driver_sha=SHA)


@pytest.mark.parametrize("key", ["df0", "df1"])
def test_discovery_self_hashed_replacement_media_stops_before_artifact(tmp_path, key,
                                                                        monkeypatch):
    from tools.amiga import route_silver_blades

    args = _discovery_args(tmp_path)
    args.manifest.write_text('{"title":"ssb","substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for name in ("df0", "df1"):
        (tmp_path / f"{name}.adf").write_bytes(name.encode())
    route = _discovery_route(tmp_path)
    pins = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
            "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path,
                        sha256=m.sha256 if m.key == key else pins[m.key])
                        for m in route.media)
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda *args: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda *args: True)
    monkeypatch.setattr(winwishaccept.winwish, "fetch",
                        lambda *args: pytest.fail("artifact touched before media pin"))
    with pytest.raises(winwishaccept.AcceptanceStop, match="approved DF0/DF1 pins"):
        winwishaccept.preflight(args, guest=object(), route_for=lambda *args: route,
                                driver_sha=SHA)


@pytest.mark.parametrize("fault", ["slot", "terminal", "deadline", "source"])
def test_discovery_rejects_wrong_prepared_route_before_guest(tmp_path, fault):
    args = _discovery_args(tmp_path)
    args.manifest.write_text('{"title":"ssb","substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    if fault == "slot":
        route.loaded_slot = "A"
    elif fault == "terminal":
        route.phases = (*route.phases[:2], _phase("walk", "world", _step("move", "world", "NP8")),
                        *route.phases[3:])
    elif fault == "deadline":
        args.deadline = 2101
    else:
        args.manifest.write_text(args.manifest.read_text().replace('"A"', '"B"'))
    with pytest.raises(winwishaccept.AcceptanceStop):
        winwishaccept.preflight(args, guest=SimpleNamespace(
            gh=lambda *args: pytest.fail("guest touched")), route_for=lambda *args: route,
            driver_sha=SHA)


def _discovery_controller(tmp_path, monkeypatch):
    from tools.amiga import amigatarget

    route = _discovery_route(tmp_path) if all((tmp_path / f"{key}.adf").exists()
                                               for key in ("df0", "df1")) else None
    if route is None:
        for key in ("df0", "df1"):
            (tmp_path / f"{key}.adf").write_bytes(key.encode())
        route = _discovery_route(tmp_path)
    clock, game = FakeClock(), FakeGame()
    game.last_shot = {"source": "winuae-pipe", "pid": 12, "counter": 3}
    original_grab = game.grab
    def advancing_grab(state, raw, crop, timeout):
        exact = original_grab(state, raw, crop, timeout)
        game.last_shot = {"source": "winuae-pipe", "pid": 12,
                          "counter": game.last_shot["counter"] + 1}
        return exact
    game.grab = advancing_grab
    game.snapshot = lambda name, holder: snapshots.append(name)
    game.restore = lambda name, holder: snapshots.append("restore:" + name)
    game.get = lambda remote, path, timeout: pathlib.Path(path).write_bytes(b"working")
    snapshots, calls = [], []
    lane = SimpleNamespace(status=lambda timeout: "no claims")
    controller = winwishaccept.Controller(
        _discovery_args(tmp_path), guest=object(), lane=lane, game=game,
        guards=lambda state, path: True, route=route, zipped=tmp_path / "artifact.zip",
        info={"media": {m.key: {} for m in route.media}}, clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(controller, "_up", lambda restarts_emulator=False: (setattr(controller, "booted", True),
                                                    controller.remotes.update({"df0": "a", "df1": "b"})))
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    state = {"on": False, "rows": []}
    def switch(enabled):
        state["on"] = enabled
        state["rows"] = [1] if enabled else []
        controller.encounters_on = enabled
        controller.encounters = SimpleNamespace(state=SimpleNamespace(load=lambda: dict(state)),
            keys=lambda names: (game.keys.extend(names) or {"pressed": names}))
        calls.append(("switch", enabled))
    monkeypatch.setattr(controller, "_switch", switch)
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame: (
        controller.checkpoints.update({name: {"comparison": {"status": "awaiting image review"},
                                              "game": frame}}),
        calls.append(("checkpoint", name))))
    monkeypatch.setattr(winwishaccept.winwish, "collect_log", lambda *args: [])
    monkeypatch.setattr(winwishaccept.winwish, "down", lambda *args: calls.append(("down",)) or {})
    target = SimpleNamespace(fix=lambda: SimpleNamespace(x=3, y=3, facing=2),
                             geo=lambda: b"synthetic", close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: target)
    monkeypatch.setattr(controller, "_area_of", lambda geo: 16)
    return controller, game, clock, snapshots, calls


def test_only_terminal_unknown_checkpoint_requires_a_readable_fix(tmp_path, monkeypatch):
    controller, *_ = _discovery_controller(tmp_path, monkeypatch)
    unreadable = {"fix": None, "geo_sha256": "synthetic", "party": None}
    verdict = controller._compare_checkpoint("ssb_leave_terminal", None, unreadable)
    assert verdict["status"] == "unproven"
    assert verdict["reason"] == "the game fix was not readable"
    assert verdict["observed"] is unreadable
    assert controller._compare_checkpoint("ordinary_unknown", None, unreadable)["status"] == (
        "awaiting image review")
    readable = {**unreadable, "fix": {"x": 15, "y": 8, "facing": 1}}
    verdict = controller._compare_checkpoint("ssb_leave_terminal", None, readable)
    assert verdict["status"] == "awaiting image review"
    assert verdict["observed"] is readable


@pytest.mark.parametrize("readable", [False, True])
def test_terminal_discovery_real_checkpoint_retains_pair_and_fix_verdict(tmp_path,
                                                                         monkeypatch, readable):
    from automap import amigaparty
    from tools.amiga import amigatarget, route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    previous = controller._checkpoint
    real_checkpoint = winwishaccept.Controller._checkpoint
    def checkpoint(name, expected, frame):
        if name == "ssb_leave_terminal":
            return real_checkpoint(controller, name, expected, frame)
        return previous(name, expected, frame)
    monkeypatch.setattr(controller, "_checkpoint", checkpoint)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(amigaparty, "read_party", lambda target: None)
    terminal = SimpleNamespace(x=15, y=8, facing=1, outdoors=False,
                               world_map=False, window=None, heading=None)
    restored = SimpleNamespace(x=3, y=3, facing=2)
    fixes = iter((terminal if readable else None, restored))
    target = SimpleNamespace(fix=lambda: next(fixes), geo=lambda: b"synthetic",
                             close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: target)
    def shot(guest, holder, kind, path):
        pathlib.Path(path).write_bytes(b"wish")
        pathlib.Path(str(path) + ".json").write_text("{}")
    monkeypatch.setattr(winwishaccept.winwish, "shot", shot)
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party|||"])
    result = controller.run_discovery()
    pair = result["checkpoints"]["ssb_leave_terminal"]
    assert pathlib.Path(pair["wish"]).read_bytes() == b"wish"
    assert pathlib.Path(pair["wish_sidecar"]).is_file()
    assert pathlib.Path(pair["controls"]).read_text() == "Text|Party|||\n"
    assert pair["pair_atomic"] is False
    assert pair["game"] is result["discovery"]["evidence"][-1]
    assert (pair["observed"]["fix"] is None) == (not readable)
    assert game.keys[-1] == "NP8"
    if readable:
        assert result["failure"] is None
        assert pair["comparison"]["status"] == "awaiting image review"
        assert result["discovery"]["status"] == "awaiting image review"
    else:
        assert "the game fix was not readable" in result["failure"]
        assert pair["comparison"]["status"] == "unproven"
        assert result["discovery"]["status"] == "failed"
        assert result["cleanup"]["restored"] is True


def test_discovery_prefix_and_only_one_terminal_key_without_actions(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, snapshots, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    monkeypatch.setattr(controller, "run_actions", lambda: pytest.fail("actions must stay disabled"))
    result = controller.run_discovery()
    assert result["failure"] is None
    assert result["completed_sequence"] == ["load", "stationary", "walk"]
    assert game.keys[-1:] == ["NP8"]
    assert game.keys.count("NP8") == 18
    assert controller.mapping_commands == len(game.keys) == 6 + 2 + 4 + 17 + 5 + 1
    assert result["challenge_key_count"] is None
    assert result["challenge_key_count_verified"] is False
    assert snapshots == ["ssb_new_verdigris", "ssb_leave_terminal"]
    assert len(result["discovery"]["evidence"]) == 3
    assert result["discovery"]["evidence"][0]["shot_source"]["counter"] > 3
    assert "ssb_leave_terminal" in controller.checkpoints
    assert all(result["mapping"][name]["status"] == "unproven"
               for name in ("transition", "reload", "reopen"))
    assert ("down",) in calls


def test_discovery_answer_failure_never_sends_movement(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (1, "missing"))
    result = controller.run_discovery()
    assert "journal was not answered" in result["failure"]
    assert game.keys == ["P", "L", "D", "V", "E", "B"]
    assert controller.mapping_commands == 6
    assert result["challenge_key_count"] is None
    assert result["challenge_key_count_verified"] is False
    assert ("down",) in calls


@pytest.mark.parametrize("frame_count,seconds", [(0, 0), (2, 5.25), (3, 0)])
def test_discovery_pipe_capture_caps_frames_and_five_seconds(tmp_path, monkeypatch,
                                                               frame_count, seconds):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    count = 0
    def grab(state, raw, crop, timeout):
        nonlocal count
        if state == "ssb_leave_unknown":
            count += 1
            assert count <= 3 and timeout <= 5
            if frame_count == 0:
                clock.now += 5
                return original(state, raw, crop, timeout)
            if count == frame_count:
                clock.now += seconds
        return original(state, raw, crop, timeout)
    game.grab = grab
    result = controller.run_discovery()
    assert count <= 3
    assert "five seconds" in result["failure"] if seconds > 5 else count >= 1
    assert game.keys[-1] == "NP8"
    assert ("down",) in calls


def test_discovery_keeps_first_frame_and_partial_raw_when_second_grab_raises(tmp_path,
                                                                              monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    count = 0
    def grab(state, raw, crop, timeout):
        nonlocal count
        if state == "ssb_leave_unknown":
            count += 1
            if count == 2:
                pathlib.Path(raw).write_bytes(b"partial")
                raise RuntimeError("second pipe grab failed")
        return original(state, raw, crop, timeout)
    game.grab = grab
    result = controller.run_discovery()
    frames = result["discovery"]["evidence"]
    assert len(frames) == 2 and "second pipe grab failed" in result["failure"]
    assert pathlib.Path(frames[0]["raw"]).is_file()
    assert frames[0]["shot_source"]["counter"] > 3
    assert pathlib.Path(frames[1]["raw"]).read_bytes() == b"partial"
    assert frames[1]["crop"] is None and frames[1]["shot_source"] is None
    assert frames[1]["error"] == "RuntimeError: second pipe grab failed"
    assert "ssb_leave_terminal" not in controller.checkpoints
    assert game.keys[-1] == "NP8"


def test_discovery_keeps_frame_on_timeout_and_picks_last_exact_pair(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, _ = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    def grab(state, raw, crop, timeout):
        exact = original(state, raw, crop, timeout)
        if state == "ssb_leave_unknown":
            clock.now += 5.25
        return exact
    game.grab = grab
    result = controller.run_discovery()
    assert "five seconds" in result["failure"]
    assert len(result["discovery"]["evidence"]) == 1
    assert result["discovery"]["evidence"][0]["crop"] is not None
    assert "ssb_leave_terminal" not in controller.checkpoints

    other = tmp_path / "last-exact"
    other.mkdir()
    controller, game, _, _, calls = _discovery_controller(other, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    count = 0
    def mixed(state, raw, crop, timeout):
        nonlocal count
        exact = original(state, raw, crop, timeout)
        if state == "ssb_leave_unknown":
            count += 1
            if count == 3:
                pathlib.Path(crop).unlink()
                return False
        return exact
    game.grab = mixed
    result = controller.run_discovery()
    assert result["failure"] is None
    assert result["discovery"]["evidence"][-1]["crop"] is None
    assert ("checkpoint", "ssb_leave_terminal") in calls
    assert result["checkpoints"]["ssb_leave_terminal"]["game"] is (
        result["discovery"]["evidence"][1])
    assert result["checkpoints"]["ssb_leave_terminal"]["comparison"]["status"] == (
        "awaiting image review")


def test_discovery_without_exact_terminal_crop_fails_without_pair(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    def raw_only(state, raw, crop, timeout):
        exact = original(state, raw, crop, timeout)
        if state == "ssb_leave_unknown":
            pathlib.Path(crop).unlink()
            return False
        return exact
    game.grab = raw_only
    result = controller.run_discovery()
    assert "no exact terminal crop" in result["failure"]
    assert len(result["discovery"]["evidence"]) == 3
    assert all(frame["crop"] is None and pathlib.Path(frame["raw"]).is_file()
               for frame in result["discovery"]["evidence"])
    assert "ssb_leave_terminal" not in controller.checkpoints
    assert game.keys[-1] == "NP8"


def test_discovery_teardown_reserves_stop_release_then_bounded_transfers(tmp_path,
                                                                          monkeypatch):
    controller, game, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    controller.booted = True
    controller.remotes.update(df0="a", df1="b")
    controller.summary["discovery"] = winwishaccept.row()
    clock.now = controller.total_end - 300
    requests = []
    controller.guest = SimpleNamespace(run=lambda command, timeout: (
        requests.append(("guest", timeout)) or (0, "ok")))
    controller.lane = SimpleNamespace(
        stop=lambda holder, timeout: requests.append(("stop", timeout)),
        release=lambda holder, timeout: requests.append(("release", timeout)),
        status=lambda timeout: requests.append(("status", timeout)) or "no claims")
    game.get = lambda remote, path, timeout: (
        requests.append(("get", timeout)) or pathlib.Path(path).write_bytes(b"working"))
    def down(guest, lane, holder):
        guest.run(["winvm", "ps"], 300)
        lane.stop(holder, 300)
        lane.release(holder, 300)
        requests.append(("down",))
        return {}
    monkeypatch.setattr(winwishaccept.winwish, "down", down)
    monkeypatch.setattr(winwishaccept.winwish, "collect_log",
                        lambda *args: pytest.fail("optional logs before holder teardown"))
    controller._cleanup_discovery()
    assert [name for name, *_ in requests] == [
        "guest", "stop", "release", "down", "status", "get", "get"]
    assert requests[0][1] <= 180 and requests[1][1] <= 240
    assert requests[2][1] <= 300
    assert requests[4][1] <= 30 and all(item[1] <= 60 for item in requests[-2:])
    assert controller.summary["cleanup"]["errors"] == []


def test_discovery_low_time_still_attempts_release_and_marks_holder_unknown(tmp_path,
                                                                              monkeypatch):
    controller, game, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    controller.booted = True
    controller.remotes.update(df0="a", df1="b")
    controller.summary["discovery"] = winwishaccept.row()
    clock.now = controller.total_end - 1
    requests = []
    controller.guest = SimpleNamespace(run=lambda command, timeout:
                                       pytest.fail("guest call spent release reserve"))
    controller.lane = SimpleNamespace(
        stop=lambda holder, timeout: pytest.fail("stop spent release reserve"),
        release=lambda holder, timeout: requests.append(("release", timeout)),
        status=lambda timeout: pytest.fail("status spent release reserve"))
    game.get = lambda *args, **kwargs: pytest.fail("transfer spent release reserve")
    def down(guest, lane, holder):
        with pytest.raises(winwishaccept.RouteError):
            guest.run(["winvm", "ps"], 300)
        with pytest.raises(winwishaccept.RouteError):
            lane.stop(holder, 300)
        lane.release(holder, 300)
        clock.now = controller.total_end
        raise winwishaccept.RouteError("guest and stop unverified")
    monkeypatch.setattr(winwishaccept.winwish, "down", down)
    controller._cleanup_discovery()
    assert len(requests) == 1 and requests[0][0] == "release"
    assert "holder test-acw release is unverified" in controller.summary["cleanup"]["errors"]
    assert any("working medium df0" in error for error in controller.summary["cleanup"]["errors"])
    assert controller.summary["failure"].startswith("Cleanup:")
    assert controller.summary["discovery"]["status"] == "failed"


def test_discovery_wrong_fix_restores_before_down_and_sends_no_later_key(tmp_path,
                                                                          monkeypatch):
    from tools.amiga import amigatarget, route_silver_blades

    controller, game, _, snapshots, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    def checkpoint(name, expected, frame):
        if name == "ssb_south_2":
            raise winwishaccept.AcceptanceStop("wrong fix at south checkpoint")
        controller.checkpoints[name] = {"comparison": {"status": "awaiting image review"}}
    monkeypatch.setattr(controller, "_checkpoint", checkpoint)
    target = SimpleNamespace(fix=lambda: SimpleNamespace(x=3, y=3, facing=2),
                             geo=lambda: b"synthetic", close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: target)
    monkeypatch.setattr(controller, "_area_of", lambda geo: 16)
    result = controller.run_discovery()
    assert "wrong fix" in result["failure"]
    assert game.keys[-2:] == ["NP8", "NP8"]
    assert "restore:ssb_new_verdigris" in snapshots
    assert result["cleanup"]["restored_fix"] == {
        "area": 16, "x": 3, "y": 3, "facing": 2}
    assert result["cleanup"]["restored"] is True
    assert ("down",) in calls


def test_discovery_failed_encounter_enable_checks_persistent_state_and_off(tmp_path,
                                                                            monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    saved = {"on": False, "rows": []}
    def switch(enabled):
        controller.encounters = SimpleNamespace(state=SimpleNamespace(load=lambda: dict(saved)))
        if enabled:
            saved.update(on=True, rows=[1])
            raise winwishaccept.AcceptanceStop("enable failed after persistent write")
        saved.update(on=False, rows=[])
        controller.encounters_on = False
        calls.append(("off",))
    monkeypatch.setattr(controller, "_switch", switch)
    result = controller.run_discovery()
    assert "enable failed" in result["failure"]
    assert result["cleanup"]["encounters_before"] == {"on": True, "rows": [1]}
    assert ("off",) in calls
    assert game.keys == ["P", "L", "D", "V", "E", "B", "E", "N",
                         "NP4", "NP6", "NP6", "NP4"]
    assert ("down",) in calls


def test_discovery_cleanup_closes_wish_when_the_editor_tab_cannot_be_shown_and_still_turns_encounters_off(
        tmp_path, monkeypatch):
    controller, game, _, snapshots, calls = _discovery_controller(tmp_path, monkeypatch)
    # The controller's own tab switch, with the click that cannot be made.
    monkeypatch.setattr(controller, "_game_section",
                        winwishaccept.Controller._game_section.__get__(controller))

    def show_tab(guest, holder, name):
        calls.append(("tab", name))
        raise winwishaccept.winwish.WinwishError(f"fail no control named {name}")

    monkeypatch.setattr(winwishaccept.winwish, "show_tab", show_tab)
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish",
                        lambda guest, holder: calls.append(("stop_wish",)) or "ok closed")
    controller._switch(True)
    controller.discovery_snapshot = True
    controller.summary["failure"] = "WinwishError: fail no control named Character Editor"
    controller.summary["discovery"] = winwishaccept.row()
    controller._cleanup_discovery()
    errors = controller.summary["cleanup"]["errors"]
    assert calls.index(("stop_wish",)) < calls.index(("switch", False))
    assert controller.encounters.state.load() == {"on": False, "rows": []}
    assert controller.summary["cleanup"]["restored"] is True
    assert "restore:ssb_new_verdigris" in snapshots
    assert not any("outstanding" in error for error in errors)
    assert any(error.startswith("encounters: the editor tab could not be shown")
               and "Wish was closed" in error for error in errors)
    # Wish is closed once; nothing later tries the tab again.
    assert calls.count(("tab", "Character Editor")) == 1
    assert calls.count(("stop_wish",)) == 1


def test_restore_names_what_suppression_is_outstanding(tmp_path, monkeypatch):
    controller, _, _, snapshots, calls = _discovery_controller(tmp_path, monkeypatch)
    controller._switch(True)
    monkeypatch.setattr(controller, "_switch", lambda enabled: calls.append(("switch", enabled)))
    controller.discovery_snapshot = True
    controller.summary["failure"] = "stopped"
    controller.summary["discovery"] = winwishaccept.row()
    controller._cleanup_discovery()
    assert "restore: cannot restore with encounter suppression outstanding (on: True, rows: [1])" in (
        controller.summary["cleanup"]["errors"])
    assert not any(name.startswith("restore:") for name in snapshots)


def test_discovery_cleanup_overrun_is_failure_and_still_downs(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, _, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    def down(*args):
        clock.now = 1801
        calls.append(("down",))
        return {}
    monkeypatch.setattr(winwishaccept.winwish, "down", down)
    result = controller.run_discovery()
    assert "total budget" in result["failure"]
    assert result["discovery"]["status"] == "failed"
    assert "total budget" in result["cleanup"]["errors"][-1]
    assert ("down",) in calls


def test_discovery_mapping_press_cap_and_parser(tmp_path, monkeypatch):
    parser = winwishaccept._parser()
    base = ["--title", "ssb", "--manifest", str(tmp_path / "prepare.json"),
            "--sha", SHA, "--holder", "test-acw", "--mute-proof",
            str(tmp_path / "mute.json"), "--out", str(tmp_path)]
    assert parser.parse_args(base + ["--discover", "ssb-leave"]).discover == "ssb-leave"
    controller, *_ = _discovery_controller(tmp_path, monkeypatch)
    controller.mapping_commands = 40
    with pytest.raises(winwishaccept.AcceptanceStop, match="40-command mapping cap"):
        controller._press("NP8")


def test_discovery_title_and_route_time_stop_before_any_key(tmp_path, monkeypatch):
    controller, game, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    def wait(state, *, limit=90):
        assert state == "title" and limit == 300
        clock.now = controller.route_end
        controller.left(1)
    monkeypatch.setattr(controller, "_await", wait)
    result = controller.run_discovery()
    assert "bounded route time" in result["failure"]
    assert game.keys == []
    assert ("down",) in calls


def _opening_controller(tmp_path, monkeypatch):
    controller, game, clock, snapshots, calls = _discovery_controller(tmp_path, monkeypatch)
    controller.args.discover = "ssb-opening-first"
    class Guards:
        rules = {"ssb_opening_first": winwishaccept.OPENING_FIRST_RULE}

        def __call__(self, state, crop):
            return True

    controller.guards = Guards()
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        controller.checkpoints.update({name: {"observed": {"fix": {"x": 7}},
                                                              "game": frame}}))
    return controller, game, clock, snapshots, calls


def test_rebound_equal_pipe_receipts_preserve_each_opening_frame_and_event(tmp_path,
                                                                           monkeypatch):
    from tools.amiga import amigadrive

    controller, _, clock, _, _ = _opening_controller(tmp_path, monkeypatch)
    guest = winuaesession.WinGuest()
    guest.holder = "test-acw"
    source = {"source": "winuae-pipe", "pid": 1912, "counter": 1}
    guest.last_shot = source.copy()
    replies = []
    for shade in (27, 53, 79):
        encoded = io.BytesIO()
        Image.new("RGB", (752, 574), (shade, 34, 51)).save(encoded, "PNG")
        replies.append("\n".join(("ok shot pid=1912 counter=001 ms=500", "WINVM-SHOT-BEGIN",
                                  base64.b64encode(encoded.getvalue()).decode(), "WINVM-SHOT-END")))
    sent = []
    def run(*args, timeout):
        sent.append(args)
        return replies.pop(0)
    monkeypatch.setattr(guest, "_run", run)
    monkeypatch.setattr(amigadrive, "_last_counter", {})
    controller.game = guest
    controller.summary["discovery"] = winwishaccept.row()
    frame = controller._capture_unknown_frames("ssb_opening_unknown", "opening", clock() + 5)
    evidence = controller.summary["discovery"]["evidence"]
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(sent) == len(evidence) == len(events) == 3
    assert all(command[0] == "ssh" and command[1].endswith(" shot -Holder test-acw")
               for command in sent)
    assert frame is evidence[-1]
    assert all(item["shot_source"] == source for item in (*evidence, *events))
    assert all(pathlib.Path(item["raw"]).is_file() and pathlib.Path(item["crop"]).is_file()
               for item in evidence)
    assert len({pathlib.Path(item["raw"]).read_bytes() for item in evidence}) == 3
    guest.last_shot["counter"] = 99
    assert all(item["shot_source"] == source for item in (*evidence, *events))


@pytest.mark.parametrize("receipt", [None, {"source": "fake", "pid": 1912, "counter": 1},
                                          {"source": "winuae-pipe", "pid": 0, "counter": 1},
                                          {"source": "winuae-pipe", "pid": 1912, "counter": None}])
def test_opening_exact_crop_without_fresh_valid_receipt_fails_with_evidence(tmp_path,
                                                                             monkeypatch, receipt):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _opening_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    if receipt is not None:
        original = game.grab
        def grab(state, raw, crop, timeout):
            exact = original(state, raw, crop, timeout)
            if state == "ssb_opening_unknown":
                game.last_shot = receipt.copy()
            return exact
        game.grab = grab
    else:
        original = game.grab
        def grab(state, raw, crop, timeout):
            if state == "ssb_opening_unknown":
                pathlib.Path(raw).write_bytes(b"raw")
                pathlib.Path(crop).write_bytes(b"crop")
                return True
            return original(state, raw, crop, timeout)
        game.grab = grab
    result = controller.run_opening_first()
    evidence = result["discovery"]["evidence"]
    assert "fresh valid pipe shot provenance" in result["failure"]
    assert result["discovery"]["status"] == "failed" and ("down",) in calls
    assert len(evidence) == 1 and pathlib.Path(evidence[0]["raw"]).is_file()
    assert pathlib.Path(evidence[0]["crop"]).is_file()
    assert evidence[0]["shot_source"] == receipt
    assert "ssb_opening_after_first" not in result["checkpoints"]
    assert game.keys[-1] == "RET"


def test_opening_crop_error_keeps_fresh_pipe_receipt_and_raw(tmp_path, monkeypatch):
    from tools.amiga import amigadrive, screens

    controller, _, clock, _, _ = _opening_controller(tmp_path, monkeypatch)
    guest = winuaesession.WinGuest()
    guest.holder = "test-acw"
    encoded = io.BytesIO()
    Image.new("RGB", (752, 574), (27, 34, 51)).save(encoded, "PNG")
    reply = "\n".join(("ok shot pid=1912 counter=001 ms=500", "WINVM-SHOT-BEGIN",
                       base64.b64encode(encoded.getvalue()).decode(), "WINVM-SHOT-END"))
    monkeypatch.setattr(guest, "_run", lambda *args, timeout: reply)
    monkeypatch.setattr(amigadrive, "_last_counter", {})
    canonical = screens.canonical_file
    crops = 0
    def broken_crop(raw, crop):
        nonlocal crops
        crops += 1
        if crops == 2:
            raise RuntimeError("crop failed")
        return canonical(raw, crop)
    monkeypatch.setattr(screens, "canonical_file", broken_crop)
    controller.game = guest
    controller.summary["discovery"] = winwishaccept.row()
    with pytest.raises(RuntimeError, match="crop failed"):
        controller._capture_unknown_frames("ssb_opening_unknown", "opening", clock() + 5)
    frames = controller.summary["discovery"]["evidence"]
    frame = frames[1]
    event = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[1])
    assert len(frames) == 2 and pathlib.Path(frames[0]["crop"]).is_file()
    assert pathlib.Path(frame["raw"]).is_file() and frame["crop"] is None
    assert frame["shot_source"] == event["shot_source"] == {
        "source": "winuae-pipe", "pid": 1912, "counter": 1}
    assert frame["error"] == "RuntimeError: crop failed"


def test_opening_first_only_sends_the_known_prefix_and_one_return(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, snapshots, calls = _opening_controller(tmp_path, monkeypatch)
    answers = []
    monkeypatch.setattr(route_silver_blades, "run_journal_answer",
                        lambda executable, holder, disk, timeout: (
                            answers.append((executable, holder, disk, timeout)) or (0, "answered")))
    result = controller.run_opening_first()
    assert result["failure"] is None
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET"]
    assert controller.mapping_commands == 7
    assert len(answers) == 1 and answers[0][2] == controller.route.media[0].path
    assert result["completed_sequence"] == ["opening_menu"]
    assert len(result["discovery"]["evidence"]) == 3
    assert result["challenge_key_count"] is None
    assert result["challenge_key_count_verified"] is False
    assert all(row["status"] == "unproven" for row in result["mapping"].values()
            if row is not result["mapping"]["title"])
    assert result["discovery"]["status"] == "awaiting image review"
    assert snapshots == [] and ("down",) in calls


@pytest.mark.parametrize("fault", ["answer", "page", "journal"])
def test_opening_first_never_returns_without_answer_and_exact_page(tmp_path, monkeypatch, fault):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _opening_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer",
                        lambda *args: (1, "bad answer") if fault == "answer" else (0, "ok"))
    if fault == "page":
        monkeypatch.setattr(controller, "_await", lambda state, **kwargs: (
            (_ for _ in ()).throw(winwishaccept.AcceptanceStop("page mismatch"))
            if state == "ssb_opening_first" else {}))
    if fault == "journal":
        monkeypatch.setattr(controller, "_await", lambda state, **kwargs: (
            (_ for _ in ()).throw(winwishaccept.AcceptanceStop("journal mismatch"))
            if state == "journal" else {}))
    result = controller.run_opening_first()
    assert result["failure"] is not None
    assert game.keys == ["P", "L", "D", "V", "E", "B"]
    assert ("down",) in calls


@pytest.mark.parametrize("fault", ["missing", "late", "partial", "no_fix"])
def test_opening_capture_fails_closed_and_preserves_raw_frames(tmp_path, monkeypatch, fault):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _opening_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    original = game.grab
    count = 0
    def grab(state, raw, crop, timeout):
        nonlocal count
        if state == "ssb_opening_unknown":
            count += 1
            assert count <= 3 and timeout <= 5
            if fault == "partial" and count == 2:
                pathlib.Path(raw).write_bytes(b"partial")
                raise RuntimeError("second pipe grab failed")
            exact = original(state, raw, crop, timeout)
            if fault == "missing":
                pathlib.Path(crop).unlink()
                return False
            if fault == "late":
                clock.now += 5.25
            return exact
        return original(state, raw, crop, timeout)
    game.grab = grab
    if fault == "no_fix":
        monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                            controller.checkpoints.update({name: {"observed": {"fix": None},
                                                                  "game": frame}}))
    result = controller.run_opening_first()
    assert result["failure"] is not None
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET"]
    assert 1 <= count <= 3
    assert all(pathlib.Path(frame["raw"]).is_file() for frame in result["discovery"]["evidence"])
    assert result["discovery"]["status"] == "failed" and ("down",) in calls
    if fault == "partial":
        assert result["discovery"]["evidence"][1]["error"] == "RuntimeError: second pipe grab failed"
        assert result["discovery"]["evidence"][1]["crop"] is None
        assert result["discovery"]["evidence"][1]["shot_source"] is None
        assert "ssb_opening_after_first" not in result["checkpoints"]


def test_opening_parser_and_mapping_cap(tmp_path, monkeypatch):
    parser = winwishaccept._parser()
    assert "ssb-opening-first" in parser._option_string_actions["--discover"].choices
    controller, game, *_ = _opening_controller(tmp_path, monkeypatch)
    controller.mapping_commands = 40
    with pytest.raises(winwishaccept.AcceptanceStop, match="40-command mapping cap"):
        controller._press("RET")
    assert game.keys == []


@pytest.mark.parametrize("readable", [False, True])
def test_opening_real_checkpoint_pairs_last_exact_frame_and_requires_fix(tmp_path,
                                                                          monkeypatch, readable):
    from automap import amigaparty
    from tools.amiga import amigatarget, route_silver_blades

    controller, game, _, _, _ = _opening_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        winwishaccept.Controller._checkpoint(controller, name, expected, frame))
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(amigaparty, "read_party", lambda target: None)
    fix = SimpleNamespace(x=7, y=13, facing=0, outdoors=False, world_map=False,
                          window=None, heading=None) if readable else None
    target = SimpleNamespace(fix=lambda: fix, geo=lambda: None, close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: target)
    def shot(guest, holder, kind, path):
        pathlib.Path(path).write_bytes(b"wish")
        pathlib.Path(str(path) + ".json").write_text("{}")
    monkeypatch.setattr(winwishaccept.winwish, "shot", shot)
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party|||"])
    result = controller.run_opening_first()
    pair = result["checkpoints"]["ssb_opening_after_first"]
    assert pair["game"] is result["discovery"]["evidence"][-1]
    assert pathlib.Path(pair["wish"]).read_bytes() == b"wish"
    assert pathlib.Path(pair["wish_sidecar"]).is_file()
    assert pair["pair_atomic"] is False
    assert pair["observed"]["fix"] is not None if readable else pair["observed"]["fix"] is None
    assert pair["comparison"]["status"] == (
        "awaiting image review" if readable else "unproven")
    assert result["discovery"]["status"] == (
        "awaiting image review" if readable else "failed")
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET"]


def _story_screens(controller, game, *, first_pages=9, after_pages=3, hold=None):
    """Drive the fake guest through the opening story as the measured run showed it."""
    st = {"show": "title", "pages": 0, "after": False}
    controller.guards = lambda state, path: path.read_bytes().decode() == state

    def grab(state, raw, crop, timeout):
        pathlib.Path(raw).write_bytes(b"raw")
        shown = state if state.startswith("ssb_leave") else st["show"]
        pathlib.Path(crop).write_bytes(shown.encode())
        game.last_shot = {"source": "winuae-pipe", "pid": 12,
                          "counter": game.last_shot.get("counter", 3) + 1}
        return True

    def press(holder, key, timeout):
        game.keys.append(key)
        show = st["show"]
        if key == "RET" and show == "continue":
            st["pages"] -= 1
            if st["pages"] <= 0:
                st["show"] = "world" if st["after"] else "treasure_bar"
        elif key == "E" and show == "treasure_bar":
            st["show"] = "treasure"
        elif key == "N" and show == "treasure":
            st["show"], st["pages"], st["after"] = "continue", after_pages, True
        elif key in ("P", "L", "D", "V", "E", "B"):
            st["show"] = {"P": "party_menu", "L": "load_picker", "D": "loaded_menu",
                          "V": "sheet", "E": "loaded_menu", "B": "journal"}[key]

    def answer(*args):
        st["show"], st["pages"] = hold or "continue", first_pages
        return 0, "answered"

    game.grab, game.press = grab, press
    return st, answer


def test_discovery_plays_the_opening_story_in_one_boot(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    _, answer = _story_screens(controller, game)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", answer)
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[:6] == ["P", "L", "D", "V", "E", "B"]
    assert game.keys[6:] [:14] == ["RET"] * 9 + ["E", "N"] + ["RET"] * 3
    assert controller.mapping_commands == 6 + 2 + 4 + 17 + 5 + 1
    assert result["interstitial_keys"] == 12
    assert "loaded" in controller.checkpoints


def test_a_thirteenth_story_page_gets_no_key(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    _, answer = _story_screens(controller, game, first_pages=13)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", answer)
    result = controller.run_discovery()
    assert "treasure_bar screen was not recognized" in result["failure"]
    assert game.keys.count("RET") == 12


def test_an_unrecognised_screen_after_the_journal_gets_no_key(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    _, answer = _story_screens(controller, game, hold="mystery")
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", answer)
    result = controller.run_discovery()
    assert "treasure_bar screen was not recognized" in result["failure"]
    assert "RET" not in game.keys


def test_ordinary_routing_does_not_return_from_a_story_page(tmp_path, monkeypatch):
    from tools.amiga import maproute, route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    _, answer = _story_screens(controller, game)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", answer)
    controller.args.discover = None
    controller.discovery = False
    load = maproute._load("ssb", "D")
    with pytest.raises(winwishaccept.AcceptanceStop, match="world screen was not recognized"):
        controller.run_phase(load)
    assert game.keys == ["P", "L", "D", "V", "E", "B"]


def test_a_story_page_in_a_later_phase_gets_no_key(tmp_path, monkeypatch):
    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    st, _ = _story_screens(controller, game)
    st["show"] = "continue"
    stationary = controller.route.phases[1]
    with pytest.raises(winwishaccept.AcceptanceStop, match="world screen was not recognized"):
        controller.run_phase(stationary)
    assert game.keys == []


@pytest.mark.parametrize("fault", ["none", "scene", "prefix", "guard_primary",
                                   "guard_footer", "guard_missing", "pin"])
def test_opening_preflight_requires_independent_two_box_rule_and_pins(tmp_path, monkeypatch, fault):
    from tools.amiga import maproute, route_silver_blades

    args = _discovery_args(tmp_path)
    args.discover = "ssb-opening-first"
    args.manifest.write_text('{"title":"ssb","opening_scene":true,"substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    pins = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
            "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path, sha256=pins[m.key])
                        for m in route.media)
    original_digest = winwishaccept.digest
    monkeypatch.setattr(winwishaccept, "digest", lambda path: pins[path.stem]
                        if path.suffix == ".adf" else original_digest(path))
    route.guard_path.write_text("{}")
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda executable: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda args: (
        (pathlib.Path(args[args.index("--out") + 1]) / "guards.json").write_text("{}") and 0))
    rule = json.loads(json.dumps(winwishaccept.OPENING_FIRST_RULE))
    if fault == "scene":
        args.manifest.write_text(args.manifest.read_text().replace('"opening_scene":true',
                                                                  '"opening_scene":false'))
    elif fault == "prefix":
        route.phases = (maproute._load("ssb", "A"), *route.phases[1:])
    elif fault == "pin":
        route.media = tuple(SimpleNamespace(key=m.key, path=m.path,
                            sha256="0" * 64 if m.key == "df0" else m.sha256)
                            for m in route.media)
    elif fault == "guard_primary":
        rule["sha256"] = "0" * 64
    elif fault == "guard_footer":
        rule["and"][0]["sha256"] = "0" * 64
    elif fault == "guard_missing":
        rule = None
    phase = maproute._load("ssb", "D")
    states = {"title", *(step.state for step in phase.steps[:6])}
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={**{state: True for state in states},
               **({"ssb_opening_first": rule} if rule is not None else {})}))
    zip_path = tmp_path / "artifact.zip"
    zip_path.write_bytes(b"build")
    (tmp_path / winwishaccept.winwish.COMMIT_FILE).write_text(SHA)
    monkeypatch.setattr(winwishaccept.winwish, "fetch", lambda *args: zip_path)
    monkeypatch.setattr(winwishaccept.winwish, "pick_run", lambda *args: 17)
    monkeypatch.setattr(winwishaccept.winwish, "check_zip_commit", lambda *args: None)
    guest = SimpleNamespace(gh=lambda *args: "[]")
    if fault != "none":
        with pytest.raises(winwishaccept.AcceptanceStop):
            winwishaccept.preflight(args, guest=guest, route_for=lambda *args: route,
                                    driver_sha=SHA)
        # A failed start leaves no export folder to block the next one.
        assert not (tmp_path / "guards-export").exists()
        assert not list(tmp_path.glob(".guards-export.*"))
    else:
        result = winwishaccept.preflight(args, guest=guest, route_for=lambda *args: route,
                                         driver_sha=SHA)
        assert (tmp_path / "guards-export" / "guards.json").is_file()
        assert result[3]["guards"]["export"] == str(tmp_path / "guards-export" / "guards.json")
        assert not list(tmp_path.glob(".guards-export.*"))
        assert result[3]["provenance"]["approved_media_sha256"] == pins


@pytest.mark.parametrize("mode", ["ssb-opening-second", "ssb-opening-after-second",
                                  "ssb-opening-after-third"])
@pytest.mark.parametrize("fault", [None, "missing", "prose", "footer"])
def test_second_page_preflight_requires_both_independent_boxes_before_artifact(
        tmp_path, monkeypatch, mode, fault):
    from tools.amiga import maproute, route_silver_blades

    args = _discovery_args(tmp_path)
    args.discover = mode
    if mode == "ssb-opening-after-third":
        args.deadline = 1500
    args.manifest.write_text('{"title":"ssb","opening_scene":true,"substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    pins = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
            "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path, sha256=pins[m.key])
                        for m in route.media)
    original_digest = winwishaccept.digest
    monkeypatch.setattr(winwishaccept, "digest", lambda path: pins[path.stem]
                        if path.suffix == ".adf" else original_digest(path))
    route.guard_path.write_text("{}")
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda executable: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda args: (
        (pathlib.Path(args[args.index("--out") + 1]) / "guards.json").write_text("{}") and 0))
    second = json.loads(json.dumps(winwishaccept.OPENING_SECOND_RULE))
    third = json.loads(json.dumps(winwishaccept.OPENING_THIRD_RULE))
    if fault == "prose":
        second["sha256"] = "0" * 64
    elif fault == "footer":
        second["and"][0]["sha256"] = "0" * 64
    phase = maproute._load("ssb", "D")
    states = {"title", *(step.state for step in phase.steps[:6])}
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={**{state: True for state in states},
               "ssb_opening_first": winwishaccept.OPENING_FIRST_RULE,
               **({} if fault == "missing" else {"ssb_opening_second": second}),
               **({"ssb_opening_third": third} if mode == "ssb-opening-after-third" else {})}))
    zip_path = tmp_path / "artifact.zip"
    zip_path.write_bytes(b"build")
    (tmp_path / winwishaccept.winwish.COMMIT_FILE).write_text(SHA)
    fetches = []
    monkeypatch.setattr(winwishaccept.winwish, "fetch", lambda *argv: (
        fetches.append(argv) or zip_path))
    monkeypatch.setattr(winwishaccept.winwish, "pick_run", lambda *argv: 17)
    monkeypatch.setattr(winwishaccept.winwish, "check_zip_commit", lambda *argv: None)
    guest = SimpleNamespace(gh=lambda *argv: "[]")
    if fault:
        with pytest.raises(winwishaccept.AcceptanceStop,
                           match="measured guards" if fault == "missing" else "second opening discovery"):
            winwishaccept.preflight(args, guest=guest, route_for=lambda *argv: route,
                                    driver_sha=SHA)
        assert not fetches
    else:
        assert winwishaccept.preflight(args, guest=guest, route_for=lambda *argv: route,
                                       driver_sha=SHA)[0] is route
        assert len(fetches) == 1


def _second_controller(tmp_path, monkeypatch, mode, frames):
    controller, game, clock, snapshots, calls = _opening_controller(tmp_path, monkeypatch)
    controller.args.discover = mode
    previous = game.grab
    seen = iter(frames)

    def grab(state, raw, crop, timeout):
        exact = previous(state, raw, crop, timeout)
        if state in ("ssb_opening_unknown", "ssb_opening_after_second_unknown",
                     "ssb_opening_after_third_unknown"):
            pathlib.Path(crop).write_bytes(next(seen))
        elif state == "ssb_opening_second":
            pathlib.Path(crop).write_bytes(b"second")
        elif state == "ssb_opening_third":
            pathlib.Path(crop).write_bytes(b"third")
        return exact

    game.grab = grab
    class Guards:
        rules = {"ssb_opening_first": winwishaccept.OPENING_FIRST_RULE,
                 "ssb_opening_second": winwishaccept.OPENING_SECOND_RULE}

        def __call__(self, state, crop):
            return state not in ("ssb_opening_second", "ssb_opening_third") or (
                pathlib.Path(crop).read_bytes() == state.removeprefix("ssb_opening_").encode())

    controller.guards = Guards()
    return controller, game, clock, snapshots, calls


def _third_controller(tmp_path, monkeypatch, frames):
    controller, game, clock, snapshots, calls = _second_controller(
        tmp_path, monkeypatch, "ssb-opening-after-third", frames)
    controller.args.deadline = 1500
    controller.total_end = controller.started + 1500
    controller.route_end = controller.total_end - winwishaccept.CLEANUP_SECONDS
    controller.clock = lambda: clock.now
    controller.guards.rules = {**controller.guards.rules,
                               "ssb_opening_third": winwishaccept.OPENING_THIRD_RULE}
    return controller, game, clock, snapshots, calls


def test_third_page_default_total_budget_includes_cleanup(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(winwishaccept.winwish, "Guest", lambda: object())
    monkeypatch.setattr(winwishaccept, "WinGuest", lambda: object())
    def preflight(args, **kwargs):
        seen.append(args.deadline)
        raise winwishaccept.AcceptanceStop("stop before lane claim")
    monkeypatch.setattr(winwishaccept, "preflight", preflight)
    argv = ["--title", "ssb", "--discover", "ssb-opening-after-third",
            "--manifest", str(tmp_path / "prepare.json"), "--sha", SHA,
            "--holder", "test-acw", "--mute-proof", str(tmp_path / "mute.json"),
            "--out", str(tmp_path)]
    assert winwishaccept.main(argv) == 2
    assert seen == [1500]


@pytest.mark.parametrize("deadline", [1501, 1800])
def test_third_page_over_budget_stops_preflight_before_guest_or_boot(tmp_path, deadline):
    args = _discovery_args(tmp_path)
    args.discover = "ssb-opening-after-third"
    args.deadline = deadline
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="--deadline must be above 300 and at most 1500"):
        winwishaccept.preflight(args, guest=object(), route_for=lambda *unused:
                                pytest.fail("route inspected after budget stop"), driver_sha=SHA)


@pytest.mark.parametrize("mode", ["ssb-leave", "ssb-opening-after-second"])
def test_prior_discovery_modes_still_admit_1800_seconds(tmp_path, mode):
    args = _discovery_args(tmp_path)
    args.discover = mode
    with pytest.raises(winwishaccept.AcceptanceStop, match="prepared manifest is missing"):
        winwishaccept.preflight(args, guest=object(), route_for=lambda *unused:
                                pytest.fail("route inspected without manifest"), driver_sha=SHA)


def test_third_page_mode_sends_one_guarded_return_then_captures_fresh_unknown(
        tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, snapshots, calls = _third_controller(
        tmp_path, monkeypatch,
        (b"second", b"partial", b"third", b"after-third", b"after-third", b"after-third"))
    answers = []
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (
        answers.append(args) or (0, "answered")))
    result = controller.run_opening_second()
    assert result["failure"] is None and len(answers) == 1
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET", "RET", "RET"]
    assert result["checkpoints"]["ssb_opening_third"]["game"] is result["discovery"]["evidence"][2]
    assert result["checkpoints"]["ssb_opening_after_third"]["game"] is result["discovery"]["evidence"][5]
    assert result["discovery"]["evidence"][5]["shot_source"]["source"] == "winuae-pipe"
    assert result["discovery"]["status"] == "awaiting image review"
    assert snapshots == [] and result["cleanup"]["errors"] == [] and ("down",) in calls


def test_third_page_both_late_draws_fit_post_ack_windows_without_fourth_key(
        tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _third_controller(
        tmp_path, monkeypatch,
        (b"second", b"partial", b"partial", b"third",
         b"partial", b"partial", b"after-third"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original_press, original_grab = game.press, game.grab
    captures = []
    def press(holder, key, timeout):
        original_press(holder, key, timeout)
        if key == "RET":
            clock.now += 1.7
    def grab(state, raw, crop, timeout):
        if state in ("ssb_opening_after_second_unknown", "ssb_opening_after_third_unknown"):
            captures.append((state, timeout))
            clock.now += 1.55
        return original_grab(state, raw, crop, timeout)
    game.press, game.grab = press, grab
    result = controller.run_opening_second()
    assert result["failure"] is None
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET", "RET", "RET"]
    assert [state for state, _ in captures] == (["ssb_opening_after_second_unknown"] * 3
                                                 + ["ssb_opening_after_third_unknown"] * 3)
    assert all(0 < timeout <= 5 for _, timeout in captures)
    assert result["checkpoints"]["ssb_opening_third"]["game"] is result["discovery"]["evidence"][3]
    assert result["checkpoints"]["ssb_opening_after_third"]["game"] is (
        result["discovery"]["evidence"][6])
    assert result["cleanup"]["errors"] == [] and ("down",) in calls


@pytest.mark.parametrize("frames", [
    (b"second", b"first", b"first", b"first"),
    (b"second", b"second", b"second", b"second"),
    (b"second", b"partial", b"partial", b"partial"),
])
def test_third_page_requires_complete_current_capture_before_return(
        tmp_path, monkeypatch, frames):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _third_controller(tmp_path, monkeypatch, frames)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    result = controller.run_opening_second()
    assert "ssb_opening_third was not recognized" in result["failure"]
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET", "RET"]
    assert "ssb_opening_third" not in result["checkpoints"]
    assert len(result["discovery"]["evidence"]) == 4
    assert all(pathlib.Path(frame["raw"]).is_file() for frame in result["discovery"]["evidence"])
    assert result["cleanup"]["errors"] == [] and ("down",) in calls


@pytest.mark.parametrize("fault", ["stale", "no_receipt", "late", "checkpoint",
                                    "unreadable", "reconfirm", "reconfirm_stale"])
def test_third_page_faults_stop_before_third_return_and_preserve_evidence(
        tmp_path, monkeypatch, fault):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _third_controller(
        tmp_path, monkeypatch, (b"second", b"third"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original_grab, original_checkpoint, original_await = (
        game.grab, controller._checkpoint, controller._await)
    def grab(state, raw, crop, timeout):
        previous = game.last_shot
        exact = original_grab(state, raw, crop, timeout)
        if state == "ssb_opening_after_second_unknown":
            if fault == "stale":
                game.last_shot = previous
            elif fault == "no_receipt":
                game.last_shot = {"source": "fake", "pid": 12, "counter": 4}
            elif fault == "late":
                clock.now += 5.25
        return exact
    def checkpoint(name, expected, frame):
        if name == "ssb_opening_third" and fault == "checkpoint":
            raise winwishaccept.AcceptanceStop("delayed third checkpoint failed")
        original_checkpoint(name, expected, frame)
        if name == "ssb_opening_third" and fault == "unreadable":
            controller.checkpoints[name]["observed"]["fix"] = None
    def await_state(state, **kwargs):
        if state == "ssb_opening_third" and fault == "reconfirm":
            raise winwishaccept.AcceptanceStop("third page changed before Return")
        previous = game.last_shot
        frame = original_await(state, **kwargs)
        if state == "ssb_opening_third" and fault == "reconfirm_stale":
            frame["shot_source"] = previous
        return frame
    game.grab = grab
    monkeypatch.setattr(controller, "_checkpoint", checkpoint)
    monkeypatch.setattr(controller, "_await", await_state)
    result = controller.run_opening_second()
    assert result["failure"] and result["discovery"]["status"] == "failed"
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET", "RET"]
    assert "ssb_opening_after_third" not in result["checkpoints"]
    assert all(pathlib.Path(frame["raw"]).is_file() for frame in result["discovery"]["evidence"])
    assert result["cleanup"]["errors"] == [] and ("down",) in calls


@pytest.mark.parametrize("fault", ["late", "receipt", "raw", "unreadable"])
def test_post_third_capture_stays_fresh_and_bounded_without_fourth_return(
        tmp_path, monkeypatch, fault):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _third_controller(
        tmp_path, monkeypatch,
        (b"second", b"third", b"after-third", b"after-third", b"after-third"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original_press, original_grab, original_checkpoint = (
        game.press, game.grab, controller._checkpoint)
    captures = []
    def press(holder, key, timeout):
        original_press(holder, key, timeout)
        if key == "RET":
            clock.now += 1.7
    def grab(state, raw, crop, timeout):
        previous = game.last_shot
        if state == "ssb_opening_after_third_unknown":
            captures.append(timeout)
            clock.now += 5.25 if fault == "late" else 1.55
        exact = original_grab(state, raw, crop, timeout)
        if state == "ssb_opening_after_third_unknown":
            if fault == "receipt":
                game.last_shot = previous
            elif fault == "raw":
                pathlib.Path(crop).unlink()
                return False
        return exact
    def checkpoint(name, expected, frame):
        original_checkpoint(name, expected, frame)
        if name == "ssb_opening_after_third" and fault == "unreadable":
            controller.checkpoints[name]["observed"]["fix"] = None
    game.press, game.grab = press, grab
    monkeypatch.setattr(controller, "_checkpoint", checkpoint)
    result = controller.run_opening_second()
    assert result["failure"] and game.keys == [
        "P", "L", "D", "V", "E", "B", "RET", "RET", "RET"]
    assert captures and all(0 < timeout <= 5 for timeout in captures)
    if fault == "raw":
        assert "no exact terminal crop" in result["failure"]
        assert all(frame["crop"] is None for frame in result["discovery"]["evidence"][2:])
    assert all(pathlib.Path(frame["raw"]).is_file() for frame in result["discovery"]["evidence"])
    assert result["cleanup"]["errors"] == [] and ("down",) in calls


def test_third_opening_rule_accepts_only_one_of_122_retained_crops(tmp_path):
    from tools.amiga import guardmaps, screens
    from tools.registry import scratch

    root = scratch.cache_dir("acceptance") / "WISH-1"
    current = root / "ssb-after-second2"
    crops = ([current / f"game-{n:03d}.png" for n in range(42)]
             + [current / f"opening-{n}.png" for n in range(2)]
             + [current / f"after-second-{n}.png" for n in range(3)]
             + [root / "ssb-leave1" / f"game-{n:03d}.png" for n in range(71)]
             + [root / "ssb-opening-first1" / name for name in
                ("game-042.png", "opening-0.png", "opening-1.png", "opening-2.png")])
    if not all(path.is_file() for path in crops):
        pytest.skip("the 122 retained Silver Blades opening crops are not on this machine")
    assert guardmaps.main(["export", "--title", "ssb", "--out", str(tmp_path)]) == 0
    guards = screens.PixelGuards(tmp_path / "guards.json")
    assert guards.rules["ssb_opening_third"] == winwishaccept.OPENING_THIRD_RULE
    matched = [path for path in crops if guards("ssb_opening_third", path)]
    assert matched == [current / "after-second-2.png"]
    assert guards("continue", current / "after-second-2.png")
    assert not guards("ssb_opening_third", current / "after-second-0.png")
    assert not guards("ssb_opening_third", current / "after-second-1.png")
    with Image.open(current / "after-second-2.png") as image:
        for part in (winwishaccept.OPENING_THIRD_RULE,
                     winwishaccept.OPENING_THIRD_RULE["and"][0]):
            changed = image.convert("RGB")
            box = part["box"]
            pixel = changed.getpixel((box[0], box[1]))
            changed.putpixel((box[0], box[1]), (pixel[0] ^ 1, pixel[1], pixel[2]))
            altered = tmp_path / f"altered-{box[1]}.png"
            changed.save(altered)
            assert not guards("ssb_opening_third", altered)


@pytest.mark.parametrize("fault", ["missing", "prose", "footer"])
def test_third_page_preflight_rejects_changed_export_before_fetch(tmp_path, monkeypatch, fault):
    from tools.amiga import maproute, route_silver_blades

    args = _discovery_args(tmp_path)
    args.discover = "ssb-opening-after-third"
    args.deadline = 1500
    args.manifest.write_text('{"title":"ssb","opening_scene":true,"substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    pins = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
            "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path, sha256=pins[m.key])
                        for m in route.media)
    original_digest = winwishaccept.digest
    monkeypatch.setattr(winwishaccept, "digest", lambda path: pins[path.stem]
                        if path.suffix == ".adf" else original_digest(path))
    route.guard_path.write_text("{}")
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda executable: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda args: (
        (pathlib.Path(args[args.index("--out") + 1]) / "guards.json").write_text("{}") and 0))
    third = json.loads(json.dumps(winwishaccept.OPENING_THIRD_RULE))
    if fault == "prose":
        third["sha256"] = "0" * 64
    elif fault == "footer":
        third["and"][0]["sha256"] = "0" * 64
    phase = maproute._load("ssb", "D")
    states = {"title", *(step.state for step in phase.steps[:6])}
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={**{state: True for state in states},
               "ssb_opening_first": winwishaccept.OPENING_FIRST_RULE,
               "ssb_opening_second": winwishaccept.OPENING_SECOND_RULE,
               **({} if fault == "missing" else {"ssb_opening_third": third})}))
    monkeypatch.setattr(winwishaccept.winwish, "fetch", lambda *argv:
                        pytest.fail("artifact touched before third-page guard"))
    with pytest.raises(winwishaccept.AcceptanceStop):
        winwishaccept.preflight(args, guest=SimpleNamespace(gh=lambda *argv: "[]"),
                                route_for=lambda *argv: route, driver_sha=SHA)


@pytest.mark.parametrize("fault", ["missing", "prose", "footer"])
def test_third_page_controller_rechecks_independent_guard_before_keys(
        tmp_path, monkeypatch, fault):
    controller, game, _, _, calls = _third_controller(tmp_path, monkeypatch, (b"second",))
    rules = dict(controller.guards.rules)
    third = json.loads(json.dumps(winwishaccept.OPENING_THIRD_RULE))
    if fault == "missing":
        rules.pop("ssb_opening_third")
    elif fault == "prose":
        third["sha256"] = "0" * 64
        rules["ssb_opening_third"] = third
    else:
        third["and"][0]["sha256"] = "0" * 64
        rules["ssb_opening_third"] = third
    controller.guards.rules = rules
    result = controller.run_opening_second()
    assert "independent exact two-box guard" in result["failure"]
    assert game.keys == [] and result["cleanup"]["errors"] == []
    assert not controller.booted and ("down",) not in calls


@pytest.mark.parametrize("name", ["ssb_opening_third", "ssb_opening_after_third"])
def test_third_page_unknown_checkpoints_require_readable_fix(tmp_path, monkeypatch, name):
    controller, *_ = _discovery_controller(tmp_path, monkeypatch)
    verdict = controller._compare_checkpoint(name, None, {"fix": None})
    assert verdict["status"] == "unproven"
    assert verdict["reason"] == "the game fix was not readable"


def test_third_page_retains_delayed_wish_pairs_for_both_new_checkpoints(
        tmp_path, monkeypatch):
    from automap import amigaparty
    from tools.amiga import amigatarget, route_silver_blades

    controller, game, _, _, calls = _third_controller(
        tmp_path, monkeypatch,
        (b"second", b"third", b"after-third", b"after-third", b"after-third"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = controller._checkpoint
    def checkpoint(name, expected, frame):
        if name in ("ssb_opening_third", "ssb_opening_after_third"):
            return winwishaccept.Controller._checkpoint(controller, name, expected, frame)
        return original(name, expected, frame)
    monkeypatch.setattr(controller, "_checkpoint", checkpoint)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(amigaparty, "read_party", lambda target: None)
    fix = SimpleNamespace(x=7, y=13, facing=0, outdoors=False, world_map=False,
                          window=None, heading=None)
    target = SimpleNamespace(fix=lambda: fix, geo=lambda: None, close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: target)
    def shot(guest, holder, kind, path):
        pathlib.Path(path).write_bytes(b"wish")
        pathlib.Path(str(path) + ".json").write_text("{}")
    monkeypatch.setattr(winwishaccept.winwish, "shot", shot)
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party|||"])
    result = controller.run_opening_second()
    assert result["failure"] is None
    for name, index in (("ssb_opening_third", 1), ("ssb_opening_after_third", 4)):
        pair = result["checkpoints"][name]
        assert pair["game"] is result["discovery"]["evidence"][index]
        assert pair["pair_atomic"] is False and pathlib.Path(pair["wish_sidecar"]).is_file()
        assert pathlib.Path(pair["wish"]).read_bytes() == b"wish"
        assert pair["comparison"]["status"] == "awaiting image review"
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET", "RET", "RET"]
    assert result["cleanup"]["errors"] == [] and ("down",) in calls


@pytest.mark.parametrize("mode,keys,frames", [
    ("ssb-opening-second", 1, (b"partial", b"second")),
    ("ssb-opening-after-second", 2, (b"partial", b"second", b"unknown", b"unknown", b"unknown"))])
def test_second_page_modes_stop_at_first_match_or_send_only_one_more_guarded_return(
        tmp_path, monkeypatch, mode, keys, frames):
    from tools.amiga import route_silver_blades

    controller, game, _, snapshots, calls = _second_controller(tmp_path, monkeypatch, mode, frames)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    result = controller.run_opening_second()
    assert result["failure"] is None
    assert game.keys == ["P", "L", "D", "V", "E", "B"] + ["RET"] * keys
    assert controller.mapping_commands == 6 + keys
    assert result["completed_sequence"] == ["opening_menu"]
    assert result["challenge_key_count"] is None
    assert result["challenge_key_count_verified"] is False
    assert len(result["discovery"]["evidence"]) == len(frames)
    assert result["checkpoints"]["ssb_opening_second"]["game"] is result["discovery"]["evidence"][1]
    assert ("ssb_opening_after_second" in result["checkpoints"]) is (keys == 2)
    assert snapshots == [] and ("down",) in calls
    assert all(result["mapping"][name]["status"] == "unproven"
               for name in ("load", "stationary", "walk", "transition", "reload", "reopen"))


@pytest.mark.parametrize("mode,returns,frame_count", [
    ("ssb-opening-second", 1, 3),
    ("ssb-opening-after-second", 2, 6),
])
def test_second_page_capture_window_starts_after_each_delayed_return(
        tmp_path, monkeypatch, mode, returns, frame_count):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _second_controller(
        tmp_path, monkeypatch, mode,
        (b"partial", b"partial", b"second", b"unknown", b"unknown", b"unknown"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    controller.clock = lambda: clock.now
    original_press, original_grab = game.press, game.grab
    captures = []

    def press(holder, key, timeout):
        original_press(holder, key, timeout)
        if key == "RET":
            clock.now += 1.7

    def grab(state, raw, crop, timeout):
        if state in ("ssb_opening_unknown", "ssb_opening_after_second_unknown"):
            captures.append((state, timeout))
            clock.now += 1.55
        return original_grab(state, raw, crop, timeout)

    game.press, game.grab = press, grab
    result = controller.run_opening_second()

    assert result["failure"] is None
    assert game.keys == ["P", "L", "D", "V", "E", "B"] + ["RET"] * returns
    assert len(captures) == frame_count
    assert all(0 < timeout <= 5 for _, timeout in captures)
    assert len(result["discovery"]["evidence"]) == frame_count
    assert result["checkpoints"]["ssb_opening_second"]["game"] is result["discovery"]["evidence"][2]
    if returns == 2:
        assert result["checkpoints"]["ssb_opening_after_second"]["game"] is (
            result["discovery"]["evidence"][5])
    assert result["cleanup"]["errors"] == [] and ("down",) in calls


def test_late_second_page_frame_stops_before_later_return_and_cleans_up(
        tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _second_controller(
        tmp_path, monkeypatch, "ssb-opening-after-second",
        (b"partial", b"partial", b"second"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    controller.clock = lambda: clock.now
    original_press, original_grab = game.press, game.grab
    captures = 0

    def press(holder, key, timeout):
        original_press(holder, key, timeout)
        if key == "RET":
            clock.now += 1.7

    def grab(state, raw, crop, timeout):
        nonlocal captures
        if state == "ssb_opening_unknown":
            captures += 1
            clock.now += 1.55 if captures < 3 else 1.95
        return original_grab(state, raw, crop, timeout)

    game.press, game.grab = press, grab
    result = controller.run_opening_second()

    assert result["failure"] == "AcceptanceStop: terminal pipe frames exceeded five seconds"
    assert captures == 3 and len(result["discovery"]["evidence"]) == 3
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET"]
    assert "ssb_opening_second" not in result["checkpoints"]
    assert result["cleanup"]["errors"] == [] and ("down",) in calls


def test_after_second_needs_a_new_exact_frame_and_keeps_all_inexact_raws(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _second_controller(
        tmp_path, monkeypatch, "ssb-opening-after-second",
        (b"second", b"partial", b"partial", b"partial"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    previous = game.grab
    def grab(state, raw, crop, timeout):
        exact = previous(state, raw, crop, timeout)
        if state == "ssb_opening_after_second_unknown":
            pathlib.Path(crop).unlink()
            return False
        return exact
    game.grab = grab
    result = controller.run_opening_second()
    frames = result["discovery"]["evidence"]
    assert "no exact terminal crop" in result["failure"]
    assert result["discovery"]["status"] == "failed"
    assert len(frames) == 4 and frames[0]["crop"] is not None
    assert all(frame["crop"] is None and frame["shot_source"]["source"] == "winuae-pipe"
               and pathlib.Path(frame["raw"]).is_file() for frame in frames[1:])
    assert "ssb_opening_second" in result["checkpoints"]
    assert "ssb_opening_after_second" not in result["checkpoints"]
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET", "RET"]
    assert ("down",) in calls


def test_unknown_capture_with_prior_exact_frame_and_expired_window_takes_no_new_shot(
        tmp_path, monkeypatch):
    controller, game, clock, _, _ = _opening_controller(tmp_path, monkeypatch)
    previous = {"raw": "prior.raw.png", "crop": "prior.png",
                "shot_source": {"source": "winuae-pipe", "pid": 12, "counter": 1}}
    controller.summary["discovery"] = winwishaccept.row(evidence=[previous])
    game.grab = lambda *args: pytest.fail("capture started after its deadline")
    with pytest.raises(winwishaccept.AcceptanceStop, match="no terminal pipe frame"):
        controller._capture_unknown_frames("ssb_opening_after_second_unknown", "after-second",
                                           clock() - 1)
    assert controller.summary["discovery"]["evidence"] == [previous]


@pytest.mark.parametrize("frames", [(b"partial", b"partial", b"partial"),
                                     (b"partial", b"partial", b"second")])
def test_second_page_mismatch_or_late_match_preserves_frames_without_extra_return(
        tmp_path, monkeypatch, frames):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _second_controller(
        tmp_path, monkeypatch, "ssb-opening-after-second", frames)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    if frames[-1] == b"second":
        original = game.grab
        count = 0
        def late(state, raw, crop, timeout):
            nonlocal count
            exact = original(state, raw, crop, timeout)
            if state == "ssb_opening_unknown":
                count += 1
                if count == 3:
                    clock.now += 5.25
            return exact
        game.grab = late
    result = controller.run_opening_second()
    assert result["failure"] and result["discovery"]["status"] == "failed"
    assert len(result["discovery"]["evidence"]) == 3
    assert all(pathlib.Path(frame["raw"]).is_file() for frame in result["discovery"]["evidence"])
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET"]
    assert "ssb_opening_second" not in result["checkpoints"] and ("down",) in calls


def test_second_page_reconfirmation_blocks_later_return_and_unreadable_fix_keeps_pair(
        tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _second_controller(
        tmp_path, monkeypatch, "ssb-opening-after-second", (b"second",))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    previous = controller._await
    def await_state(state, **kwargs):
        if state == "ssb_opening_second":
            raise winwishaccept.AcceptanceStop("second page changed before Return")
        return previous(state, **kwargs)
    monkeypatch.setattr(controller, "_await", await_state)
    result = controller.run_opening_second()
    assert "second page changed" in result["failure"]
    assert game.keys[-1:] == ["RET"]
    assert set(result["checkpoints"]) == {"load_sheet", "ssb_opening_second"}
    assert result["checkpoints"]["ssb_opening_second"]["game"] is result["discovery"]["evidence"][0]
    assert ("down",) in calls

    other = tmp_path / "missing-fix"
    other.mkdir()
    controller, game, _, _, _ = _second_controller(
        other, monkeypatch, "ssb-opening-after-second", (b"second",))
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        controller.checkpoints.update({name: {"observed": {"fix": None}, "game": frame}}))
    result = controller.run_opening_second()
    assert "game fix was not readable" in result["failure"]
    assert result["checkpoints"]["ssb_opening_second"]["game"] is result["discovery"]["evidence"][0]
    assert game.keys[-1:] == ["RET"]


@pytest.mark.parametrize("fault", ["partial", "receipt", "no_exact"])
def test_second_page_capture_failure_preserves_evidence_and_never_sends_later_return(
        tmp_path, monkeypatch, fault):
    from tools.amiga import route_silver_blades

    controller, game, _, _, calls = _second_controller(
        tmp_path, monkeypatch, "ssb-opening-after-second",
        (b"partial", b"second", b"partial"))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    previous = game.grab
    count = 0
    def grab(state, raw, crop, timeout):
        nonlocal count
        if state == "ssb_opening_unknown":
            count += 1
            if fault == "partial" and count == 2:
                pathlib.Path(raw).write_bytes(b"partial")
                raise RuntimeError("pipe shot failed")
        prior_receipt = game.last_shot
        exact = previous(state, raw, crop, timeout)
        if state == "ssb_opening_unknown" and count == 2:
            if fault == "receipt":
                # A reused receipt object is not evidence of a new shot.
                game.last_shot = prior_receipt
            elif fault == "no_exact":
                pathlib.Path(crop).unlink()
                return False
        return exact
    game.grab = grab
    result = controller.run_opening_second()
    assert result["failure"] and result["discovery"]["status"] == "failed"
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET"]
    assert len(result["discovery"]["evidence"]) >= 2
    assert all(pathlib.Path(frame["raw"]).is_file() for frame in result["discovery"]["evidence"])
    assert "ssb_opening_second" not in result["checkpoints"] and ("down",) in calls
    if fault == "partial":
        assert result["discovery"]["evidence"][1]["error"] == "RuntimeError: pipe shot failed"
    if fault == "receipt":
        assert "fresh valid pipe shot provenance" in result["failure"]


@pytest.mark.parametrize("readable", [False, True])
def test_second_page_real_checkpoint_retains_delayed_nonatomic_wish_pair(
        tmp_path, monkeypatch, readable):
    from automap import amigaparty
    from tools.amiga import amigatarget, route_silver_blades

    controller, game, _, _, calls = _second_controller(
        tmp_path, monkeypatch, "ssb-opening-second", (b"second",))
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "ok"))
    monkeypatch.setattr(controller, "_checkpoint", lambda name, expected, frame:
                        winwishaccept.Controller._checkpoint(controller, name, expected, frame))
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(amigaparty, "read_party", lambda target: None)
    fix = SimpleNamespace(x=7, y=13, facing=0, outdoors=False, world_map=False,
                          window=None, heading=None) if readable else None
    target = SimpleNamespace(fix=lambda: fix, geo=lambda: None, close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: target)
    def shot(guest, holder, kind, path):
        pathlib.Path(path).write_bytes(b"wish")
        pathlib.Path(str(path) + ".json").write_text("{}")
    monkeypatch.setattr(winwishaccept.winwish, "shot", shot)
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party|||"])
    result = controller.run_opening_second()
    pair = result["checkpoints"]["ssb_opening_second"]
    assert pair["game"] is result["discovery"]["evidence"][0]
    assert pair["pair_atomic"] is False and pathlib.Path(pair["wish_sidecar"]).is_file()
    assert pathlib.Path(pair["wish"]).read_bytes() == b"wish"
    assert pair["comparison"]["status"] == (
        "awaiting image review" if readable else "unproven")
    assert (result["failure"] is None) is readable
    assert game.keys == ["P", "L", "D", "V", "E", "B", "RET"] and ("down",) in calls


class _PartyMemory:
    """A Silver Blades party list in a byte image; each `read_blocks` call is one round trip."""

    BASE, SIZE, DATA = 0xC00000, 0x80000, 0xC50000

    def __init__(self, items):
        from automap import amiga, amigaparty

        self.layout = amiga.MACHINES["secret-of-the-silver-blades"]
        self.row = amigaparty.ROWS["secret-of-the-silver-blades"]
        self.data_base = self.DATA
        self.memory = ((self.BASE, self.SIZE),)
        self.image = bytearray(self.SIZE)
        self.calls = []
        records = (0xC60000, 0xC60200)
        self._put(self.DATA + self.row.head, records[0])
        for slot, (address, name) in enumerate(zip(records, (b"PAINE", b"EPONA"))):
            self.image[address - self.BASE:address - self.BASE + len(name)] = name
            self.image[address - self.BASE + self.row.slot] = slot
            self._put(address + self.row.next_offset, records[slot + 1] if slot == 0 else 0)
        self.items = []
        for _ in range(items):
            self.add_item()

    def _put(self, address, value):
        at = address - self.BASE
        self.image[at:at + 4] = value.to_bytes(4, "big")

    def add_item(self):
        address = 0xC66000 + 0x50 * len(self.items)
        self.image[address - self.BASE + 1] = len(self.items) + 1
        link = (self.items[-1] + self.row.items.link if self.items
                else 0xC60000 + self.row.items.head)
        self._put(link, address)
        self.items.append(address)

    def read_blocks(self, blocks):
        self.calls.append(list(blocks))
        return [bytes(self.image[a - self.BASE:a - self.BASE + n]) for a, n, *_ in blocks]

    def read(self, address, length):
        return self.read_blocks([(address, length)])[0]

    def fix(self):
        return SimpleNamespace(x=3, y=3, facing=2, outdoors=False, world_map=False,
                               window=None, heading=None)

    def geo(self):
        return None

    def close(self):
        pass


def _party_checkpoint_controller(tmp_path, monkeypatch, memory):
    from tools.amiga import amigatarget

    clock = FakeClock()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=SimpleNamespace(), game=FakeGame(),
        guards=lambda state, path: True, route=_route(), zipped=tmp_path / "build.zip",
        info={"media": {}, "build_sha": SHA}, clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda *args: memory)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_game_section", lambda: None)

    def shot(guest, holder, kind, path):
        pathlib.Path(path).write_bytes(b"wish")

    monkeypatch.setattr(winwishaccept.winwish, "shot", shot)
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party|||"])
    return controller


def test_unchanged_party_is_read_in_one_batch_at_a_later_checkpoint(tmp_path, monkeypatch):
    from automap import amigaparty

    memory = _PartyMemory(items=24)
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, memory)
    controller._checkpoint("loaded", None, {"raw": "game"})
    first_calls = len(memory.calls)
    # One read for the head, one per record, one per item level.
    assert first_calls == 1 + 2 + 24
    controller._checkpoint("turn_east", None, {"raw": "game"})
    assert len(memory.calls) - first_calls == 1
    observed = controller.checkpoints["turn_east"]["observed"]["party"]
    assert observed == controller.checkpoints["loaded"]["observed"]["party"]
    assert [len(member["items"]) for member in observed] == [24, 0]
    fresh = amigaparty.read_party(memory)
    assert [member["raw"] for member in observed] == [m.raw.hex() for m in fresh]


def test_the_first_checkpoint_stops_a_wish_that_never_connected(tmp_path, monkeypatch):
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, _PartyMemory(items=1))
    looks = []
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: looks.append(1) or [
        "ListItem|14:21:03 Waiting to connect...|||", "Text|Party - waiting for a game|||",
        "Button|Heal|||enabled=False"])
    with pytest.raises(winwishaccept.AcceptanceStop, match="waiting for a game"):
        controller._checkpoint("loaded", None, {"raw": "game"})
    assert len(looks) > 1
    assert "loaded" not in controller.checkpoints


def test_a_dump_without_a_party_heading_stops_the_first_checkpoint(tmp_path, monkeypatch):
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, _PartyMemory(items=1))
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Button|Heal|||enabled=True"])
    with pytest.raises(winwishaccept.AcceptanceStop, match="no Party heading"):
        controller._checkpoint("loaded", None, {"raw": "game"})
    assert controller.summary["party_heading_seen"] is False


def test_the_first_checkpoint_records_that_the_party_heading_was_seen(tmp_path, monkeypatch):
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, _PartyMemory(items=1))
    controller._checkpoint("loaded", None, {"raw": "game"})
    assert controller.summary["party_heading_seen"] is True


def test_the_connection_wait_stops_when_the_route_time_runs_out(tmp_path, monkeypatch):
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, _PartyMemory(items=1))
    controller.route_end = controller.clock() + 12
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party - waiting for a game|||"])
    with pytest.raises(winwishaccept.AcceptanceStop, match="route time ran out"):
        controller._checkpoint("loaded", None, {"raw": "game"})
    assert controller.clock() < controller.route_end + winwishaccept.CONNECT_POLL


def test_a_stale_waiting_row_does_not_stop_a_wish_that_connected(tmp_path, monkeypatch):
    """A build that never withdraws the Messages row keeps it after connecting; the Party heading shows the connection."""
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, _PartyMemory(items=1))
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: [
        "ListItem|13:47:18  Waiting to connect...|||", "Text|Party|||", "Button|Heal|||enabled=True"])
    controller._checkpoint("loaded", None, {"raw": "game"})
    assert "loaded" in controller.checkpoints


def test_the_wait_for_a_connection_outlasts_the_measured_connect_time():
    assert winwishaccept.CONNECT_WAIT >= 184 * 1.25


def test_the_first_checkpoint_goes_on_once_wish_connects(tmp_path, monkeypatch):
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, _PartyMemory(items=1))
    replies = iter([["Text|Party - waiting for a game|||"], ["Text|Party|||", "Button|Heal|||enabled=True"]])
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: next(replies))
    controller._checkpoint("loaded", None, {"raw": "game"})
    assert "loaded" in controller.checkpoints


def test_changed_party_list_is_read_live_after_the_batch(tmp_path, monkeypatch):
    from automap import amigaparty

    memory = _PartyMemory(items=3)
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, memory)
    controller._checkpoint("loaded", None, {"raw": "game"})
    memory.add_item()
    before = len(memory.calls)
    controller._checkpoint("turn_east", None, {"raw": "game"})
    assert len(memory.calls) - before == 2
    observed = controller.checkpoints["turn_east"]["observed"]["party"]
    fresh = amigaparty.read_party(memory)
    assert [[address for address, _raw in member["items"]] for member in observed] == [
        [node.address for node in member.item_nodes] for member in fresh]
    assert len(observed[0]["items"]) == 4


def test_checkpoint_event_records_where_its_time_went(tmp_path, monkeypatch):
    memory = _PartyMemory(items=1)
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, memory)
    controller._checkpoint("loaded", None, {"raw": "game"})
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    timings = next(e for e in events if e["event"] == "checkpoint")["timings"]
    assert set(timings) == {"connect", "party", "fix", "geo", "map_tab", "settle",
                            "wish_shot", "controls"}
    assert timings["settle"] >= 10
    assert all(value >= 0 for value in timings.values())
    record = controller.checkpoints["loaded"]
    assert record["timings"] == timings
    assert record["party_reads"] == {"batched_blocks": 0, "live_reads": 4}


@pytest.mark.parametrize("deadline", [1801, 2100])
def test_leave_discovery_admits_a_2100_second_deadline(tmp_path, deadline):
    args = _discovery_args(tmp_path)
    args.deadline = deadline
    with pytest.raises(winwishaccept.AcceptanceStop, match="prepared manifest is missing"):
        winwishaccept.preflight(args, guest=object(), route_for=lambda *unused:
                                pytest.fail("route inspected without manifest"), driver_sha=SHA)


def test_leave_discovery_stops_above_2100_seconds(tmp_path):
    args = _discovery_args(tmp_path)
    args.deadline = 2101
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="--deadline must be above 300 and at most 2100"):
        winwishaccept.preflight(args, guest=object(), route_for=lambda *unused:
                                pytest.fail("route inspected after budget stop"), driver_sha=SHA)


@pytest.mark.parametrize("mode", ["ssb-opening-first", "ssb-opening-second",
                                  "ssb-opening-after-second"])
def test_opening_discovery_modes_keep_the_1800_second_bound(tmp_path, mode):
    args = _discovery_args(tmp_path)
    args.discover = mode
    args.deadline = 1801
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="--deadline must be above 300 and at most 1800"):
        winwishaccept.preflight(args, guest=object(), route_for=lambda *unused:
                                pytest.fail("route inspected after budget stop"), driver_sha=SHA)


@pytest.mark.parametrize(("mode", "expected"), [("ssb-leave", 2100),
                                                ("ssb-opening-first", 1800),
                                                (None, 3300)])
def test_default_deadline_per_mode(tmp_path, monkeypatch, mode, expected):
    seen = []
    monkeypatch.setattr(winwishaccept.winwish, "Guest", lambda: object())
    monkeypatch.setattr(winwishaccept, "WinGuest", lambda: object())

    def preflight(args, **kwargs):
        seen.append(args.deadline)
        raise winwishaccept.AcceptanceStop("stop before lane claim")

    monkeypatch.setattr(winwishaccept, "preflight", preflight)
    argv = ["--title", "ssb", "--manifest", str(tmp_path / "prepare.json"), "--sha", SHA,
            "--holder", "test-acw", "--mute-proof", str(tmp_path / "mute.json"),
            "--out", str(tmp_path)]
    if mode:
        argv += ["--discover", mode]
    assert winwishaccept.main(argv) == 2
    assert seen == [expected]


def _timed_out(message="winvm ssh exceeded its 1.9s limit"):
    return winuaesession.ShotTimedOut(f"winuae.ps1 shot returned '{message}'")


def test_leave_terminal_window_counts_from_the_np8(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, _ = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original_press, original_grab = game.press, game.grab
    allowed = []

    def press(holder, key, timeout):
        original_press(holder, key, timeout)
        if key == "NP8":
            clock.now += 3.5

    def grab(state, raw, crop, timeout):
        if state == "ssb_leave_unknown":
            allowed.append(timeout)
        return original_grab(state, raw, crop, timeout)

    game.press, game.grab = press, grab
    result = controller.run_discovery()
    assert result["failure"] is None
    assert allowed and allowed[0] > 4


def test_terminal_shot_timeout_is_retried_without_a_key(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    attempts = 0

    def grab(state, raw, crop, timeout):
        nonlocal attempts
        if state == "ssb_leave_unknown":
            attempts += 1
            if attempts == 1:
                clock.now += 1
                raise _timed_out()
        return original(state, raw, crop, timeout)

    game.grab = grab
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[-1] == "NP8"
    timeouts = result["discovery"]["shot_timeouts"]
    assert len(timeouts) == 1 and "1.9s limit" in timeouts[0]["error"]
    assert 2 <= attempts <= 3
    assert ("checkpoint", "ssb_leave_terminal") in calls
    assert result["checkpoints"]["ssb_leave_terminal"]["game"]["crop"] is not None


def test_terminal_shot_timeouts_are_recorded_and_stop_once_the_window_is_spent(
        tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    attempts = 0

    def grab(state, raw, crop, timeout):
        nonlocal attempts
        if state == "ssb_leave_unknown":
            attempts += 1
            clock.now += 2
            raise _timed_out()
        return original(state, raw, crop, timeout)

    game.grab = grab
    result = controller.run_discovery()
    assert result["failure"].startswith("ShotTimedOut")
    assert 2 <= attempts <= 3
    assert len(result["discovery"]["shot_timeouts"]) == attempts
    assert game.keys[-1] == "NP8"
    assert "ssb_leave_terminal" not in controller.checkpoints
    assert ("down",) in calls


def test_await_retries_a_timed_out_shot_within_its_own_limit(tmp_path):
    clock, game = FakeClock(), FakeGame()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=SimpleNamespace(), game=game,
        guards=lambda state, path: True, route=_route(), zipped=tmp_path / "build.zip",
        info={"media": {}, "build_sha": SHA}, clock=clock, sleep=clock.sleep)
    original = game.grab
    attempts = 0

    def grab(state, raw, crop, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            clock.now += 20
            raise _timed_out("winvm ssh exceeded its 20.0s limit")
        return original(state, raw, crop, timeout)

    game.grab = grab
    frame = controller._await("world", limit=90)
    assert frame["crop"] is not None and attempts == 2
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["state"] for e in events if e["event"] == "shot_retry"] == ["world"]
    assert len(controller.summary["shot_timeouts"]) == 1


def test_await_stops_with_the_timeout_once_its_limit_is_spent(tmp_path):
    clock, game = FakeClock(), FakeGame()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=SimpleNamespace(), game=game,
        guards=lambda state, path: True, route=_route(), zipped=tmp_path / "build.zip",
        info={"media": {}, "build_sha": SHA}, clock=clock, sleep=clock.sleep)
    keys_before = list(game.keys)

    def grab(state, raw, crop, timeout):
        clock.now += 20
        raise _timed_out("winvm ssh exceeded its 20.0s limit")

    game.grab = grab
    with pytest.raises(winuaesession.ShotTimedOut):
        controller._await("world", limit=30)
    assert game.keys == keys_before


def test_terminal_timeout_after_a_good_frame_keeps_that_frame(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    controller, game, clock, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    original = game.grab
    attempts = 0

    def grab(state, raw, crop, timeout):
        nonlocal attempts
        if state == "ssb_leave_unknown":
            attempts += 1
            if attempts == 2:
                clock.now += timeout
                raise _timed_out("winvm ssh exceeded its 1.5s limit")
        return original(state, raw, crop, timeout)

    game.grab = grab
    result = controller.run_discovery()
    assert result["failure"] is None
    assert attempts == 2
    assert len(result["discovery"]["shot_timeouts"]) == 1
    first = result["discovery"]["evidence"][0]
    assert result["checkpoints"]["ssb_leave_terminal"]["game"] is first
    assert first["crop"] is not None
    assert game.keys[-1] == "NP8"


class _StillClock:
    """A clock that moves only when something sleeps, so a loop without a sleep shows."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_await_waits_between_shots_that_time_out_at_once(tmp_path):
    clock, game = _StillClock(), FakeGame()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=SimpleNamespace(), game=game,
        guards=lambda state, path: True, route=_route(), zipped=tmp_path / "build.zip",
        info={"media": {}, "build_sha": SHA}, clock=clock, sleep=clock.sleep)
    attempts = 0

    def grab(state, raw, crop, timeout):
        nonlocal attempts
        attempts += 1
        assert attempts <= 50, "the wait spun without sleeping"
        raise _timed_out("winvm ssh exceeded its 20.0s limit")

    game.grab = grab
    with pytest.raises(winuaesession.ShotTimedOut,
                       match="world screen was not recognized before its deadline") as caught:
        controller._await("world", limit=10)
    assert attempts <= 11
    assert len(controller.summary["shot_timeouts"]) == attempts
    assert isinstance(caught.value.__cause__, winuaesession.ShotTimedOut)
    assert "20.0s limit" in str(caught.value)



def _leave_yes_controller(tmp_path, monkeypatch, guards=lambda state, path: True):
    from tools.amiga import maproute, route_silver_blades

    controller, game, clock, snapshots, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    controller.args.discover = "ssb-leave-yes"
    controller.route.phases = (*controller.route.phases[:3], maproute._ssb_transition(),
                               *controller.route.phases[4:])
    controller.guards = guards
    return controller, game, snapshots, calls


def test_leave_yes_discovery_answers_yes_only_on_the_guarded_question(tmp_path, monkeypatch):
    seen = []
    controller, game, snapshots, calls = _leave_yes_controller(
        tmp_path, monkeypatch, guards=lambda state, path: seen.append(state) or True)
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[-2:] == ["NP8", "Y"]
    assert game.keys.count("Y") == 1
    assert seen.index("leave_town") < len(seen) - 1
    assert controller.mapping_commands == 6 + 2 + 4 + 17 + 5 + 1 + 1
    assert result["completed_sequence"] == ["load", "stationary", "walk", "transition"]
    assert ("checkpoint", "ssb_ruins_arrival") in calls
    assert "ssb_leave_terminal" not in controller.checkpoints
    assert result["mapping"]["transition"]["status"] == "awaiting image review"
    assert result["discovery"]["status"] == "awaiting image review"
    assert snapshots[0] == "ssb_new_verdigris"
    assert ("down",) in calls


@pytest.mark.parametrize("mode", ["discovery", "opening"])
def test_discovery_and_opening_press_no_action_on_a_route_with_enabled_actions(
        tmp_path, monkeypatch, mode):
    from tools.amiga import route_silver_blades

    monkeypatch.setattr(route_silver_blades, "run_journal_answer", lambda *args: (0, "answered"))
    if mode == "opening":
        controller, game, _, _, _ = _opening_controller(tmp_path, monkeypatch)
    else:
        controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    assert {a.kind for a in controller.route.actions if a.enabled} == {
        "heal", "identify", "quickfight", "levelup"}
    before = json.loads(json.dumps(controller.summary["actions"]))
    result = (controller.run_opening_first() if mode == "opening"
              else controller.run_discovery())
    assert result["failure"] is None
    assert game.keys
    assert controller.action_commands == 0
    assert result["actions"] == before


def test_leave_yes_discovery_sends_no_yes_when_the_question_is_not_recognized(
        tmp_path, monkeypatch):
    controller, game, _, calls = _leave_yes_controller(
        tmp_path, monkeypatch, guards=lambda state, path: state != "leave_town")
    result = controller.run_discovery()
    assert "leave_town screen was not recognized" in result["failure"]
    assert game.keys[-1] == "NP8" and "Y" not in game.keys
    assert ("checkpoint", "ssb_ruins_arrival") not in calls
    assert result["mapping"]["transition"]["status"] == "unproven"
    assert ("down",) in calls


def test_leave_yes_discovery_needs_the_measured_transition(tmp_path, monkeypatch):
    controller, game, _, _ = _leave_yes_controller(tmp_path, monkeypatch)
    controller.route.phases = (*controller.route.phases[:3],
                               _phase("transition", "world", ready=False, reason="unmeasured"),
                               *controller.route.phases[4:])
    result = controller.run_discovery()
    assert "guarded leave-town transition" in result["failure"]
    assert game.keys == []


def test_leave_yes_discovery_admits_the_leave_town_deadline(tmp_path):
    args = _discovery_args(tmp_path)
    args.discover = "ssb-leave-yes"
    args.deadline = 2100
    with pytest.raises(winwishaccept.AcceptanceStop, match="prepared manifest is missing"):
        winwishaccept.preflight(args, guest=object(), route_for=lambda *unused:
                                pytest.fail("route inspected without manifest"), driver_sha=SHA)
    assert winwishaccept._deadline_limit("ssb-leave-yes") == 2100


def test_leave_yes_preflight_requires_the_leave_town_guard(tmp_path, monkeypatch):
    from tools.amiga import maproute, route_silver_blades

    args = _discovery_args(tmp_path)
    args.discover = "ssb-leave-yes"
    args.deadline = 2100
    args.manifest.write_text('{"title":"ssb","substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    route.phases = (*route.phases[:3], maproute._ssb_transition(), *route.phases[4:])
    pinned = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
              "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path, sha256=pinned[m.key])
                        for m in route.media)
    original_digest = winwishaccept.digest
    monkeypatch.setattr(winwishaccept, "digest", lambda path: pinned[path.stem]
                        if path.suffix == ".adf" else original_digest(path))
    route.guard_path.write_text("{}")
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda executable: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda args: (
        (pathlib.Path(args[args.index("--out") + 1]) / "guards.json").write_text("{}") and 0))
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={name: True for phase in route.phases[:3]
               for name in (phase.initial_state, *(s.state for s in phase.steps))}
        | {"continue": True, "title": True}))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="route has no measured guards for leave_town"):
        winwishaccept.preflight(args, guest=SimpleNamespace(gh=lambda *a: pytest.fail("guest")),
                                route_for=lambda *unused: route, driver_sha=SHA)


def test_camp_load_discovery_presses_load_only_on_the_guarded_camp(tmp_path, monkeypatch):
    seen = []
    controller, game, snapshots, calls = _leave_yes_controller(
        tmp_path, monkeypatch, guards=lambda state, path: seen.append(state) or True)
    controller.args.discover = "ssb-camp-load"
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[-9:] == ["NP8", "Y", "E", "L", "Y", "D", "B", "E", "N"]
    assert seen.index("camp") > seen.index("leave_town")
    assert seen.index("load_anyway") > seen.index("camp")
    assert seen.index("load_picker", seen.index("load_anyway")) > seen.index("load_anyway")
    assert controller.mapping_commands == winwishaccept.CAMP_LOAD_MAPPING_COMMANDS == (
        6 + 2 + 4 + 17 + 5 + 1 + 1 + 2 + 5)
    assert result["completed_sequence"] == [
        "load", "stationary", "walk", "transition", "camp", "camp_load", "camp_reload"]
    assert ("checkpoint", "ssb_ruins_arrival") in calls
    assert ("checkpoint", "ssb_camp_reloaded") in calls
    taken = [call[1] for call in calls if call[0] == "checkpoint"]
    assert not any(name.startswith("ssb_camp_after") for name in taken)
    assert "ssb_camp_load_unknown" not in taken
    assert snapshots[-1] == "ssb_camp_load_terminal"
    assert result["mapping"]["transition"]["status"] == "awaiting image review"
    assert result["mapping"]["reload"]["status"] == "awaiting image review"
    assert result["discovery"]["status"] == "awaiting image review"
    assert result["discovery"]["reason"] == "The camp reload pair awaits image review"
    assert ("down",) in calls


def test_camp_load_discovery_sends_no_load_when_camp_is_not_recognized(tmp_path, monkeypatch):
    controller, game, _, calls = _leave_yes_controller(
        tmp_path, monkeypatch, guards=lambda state, path: state != "camp")
    controller.args.discover = "ssb-camp-load"
    result = controller.run_discovery()
    assert "camp screen was not recognized" in result["failure"]
    assert game.keys[-3:] == ["NP8", "Y", "E"]
    assert ("checkpoint", "ssb_camp_reloaded") not in calls
    assert ("down",) in calls


def test_camp_load_discovery_has_the_leave_town_deadline():
    assert winwishaccept._deadline_limit("ssb-camp-load") == 2100
    assert "ssb-camp-load" in winwishaccept.LEAVE_MODES


def test_camp_load_preflight_requires_the_camp_guard(tmp_path, monkeypatch):
    from tools.amiga import maproute, route_silver_blades

    args = _discovery_args(tmp_path)
    args.discover = "ssb-camp-load"
    args.deadline = 2100
    args.manifest.write_text('{"title":"ssb","substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    route.phases = (*route.phases[:3], maproute._ssb_transition(), *route.phases[4:])
    pinned = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
              "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path, sha256=pinned[m.key])
                        for m in route.media)
    original_digest = winwishaccept.digest
    monkeypatch.setattr(winwishaccept, "digest", lambda path: pinned[path.stem]
                        if path.suffix == ".adf" else original_digest(path))
    route.guard_path.write_text("{}")
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda executable: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda args: (
        (pathlib.Path(args[args.index("--out") + 1]) / "guards.json").write_text("{}") and 0))
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={name: True for phase in route.phases[:4]
               for name in (phase.initial_state, *(s.state for s in phase.steps))}
        | {"continue": True, "title": True}))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="route has no measured guards for camp"):
        winwishaccept.preflight(args, guest=SimpleNamespace(gh=lambda *a: pytest.fail("guest")),
                                route_for=lambda *unused: route, driver_sha=SHA)


def test_camp_load_encamps_on_a_world_frame_taken_after_the_arrival_pair(tmp_path, monkeypatch):
    order = []
    controller, game, _, calls = _leave_yes_controller(tmp_path, monkeypatch)
    controller.args.discover = "ssb-camp-load"
    original_grab, original_press = game.grab, game.press
    checkpoint = controller._checkpoint

    def grab(state, raw, crop, timeout):
        order.append(("grab", state))
        return original_grab(state, raw, crop, timeout)

    def press(holder, key, timeout):
        order.append(("key", key))
        return original_press(holder, key, timeout)

    def record(name, expected, frame):
        order.append(("checkpoint", name))
        return checkpoint(name, expected, frame)

    game.grab, game.press = grab, press
    monkeypatch.setattr(controller, "_checkpoint", record)
    result = controller.run_discovery()
    assert result["failure"] is None
    arrival = order.index(("checkpoint", "ssb_ruins_arrival"))
    encamp = order.index(("key", "E"), arrival)
    assert ("grab", "world") in order[arrival:encamp]
    load = order.index(("key", "L"), encamp)
    assert ("grab", "camp") in order[encamp:load]


def _camp_load_controller(tmp_path, monkeypatch, *, after_camp):
    """A camp-load run whose guards answer `after_camp(state)` once camp has matched."""
    armed = []

    def guards(state, path):
        if armed:
            return after_camp(state)
        if state == "camp":
            armed.append(True)
        return True

    controller, game, snapshots, calls = _leave_yes_controller(tmp_path, monkeypatch, guards=guards)
    controller.args.discover = "ssb-camp-load"
    return controller, game, calls


def _checkpoints(calls):
    return [call[1] for call in calls if call[0] == "checkpoint"]


def test_camp_load_sends_no_yes_when_the_question_is_not_recognized(tmp_path, monkeypatch):
    controller, game, calls = _camp_load_controller(
        tmp_path, monkeypatch, after_camp=lambda state: state != "load_anyway")
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[-3:] == ["Y", "E", "L"]
    assert _checkpoints(calls)[-1] == "ssb_camp_after_l"
    assert result["discovery"]["status"] == "awaiting image review"
    assert result["discovery"]["reason"] == "The screen after camp L is not measured"
    assert result["mapping"]["reload"]["status"] == "unproven"
    assert "camp_load" not in result["completed_sequence"]
    assert ("down",) in calls


def test_camp_load_sends_no_slot_when_the_picker_is_not_recognized(tmp_path, monkeypatch):
    controller, game, calls = _camp_load_controller(
        tmp_path, monkeypatch, after_camp=lambda state: state != "load_picker")
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[-2:] == ["L", "Y"]
    assert _checkpoints(calls)[-1] == "ssb_camp_after_y"
    assert result["discovery"]["reason"] == "The screen after camp Y is not measured"
    assert result["mapping"]["reload"]["status"] == "unproven"


def test_camp_load_stops_on_an_unmeasured_screen_after_the_slot(tmp_path, monkeypatch):
    controller, game, calls = _camp_load_controller(
        tmp_path, monkeypatch,
        after_camp=lambda state: state not in ("loaded_menu", "world"))
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[-3:] == ["L", "Y", "D"]
    assert _checkpoints(calls)[-1] == "ssb_camp_after_slot"
    assert result["discovery"]["reason"] == "The screen after slot D is not measured"
    assert result["completed_sequence"][-1] == "camp_load"
    assert result["mapping"]["reload"]["status"] == "unproven"


def test_camp_load_checks_a_slot_that_returns_straight_to_the_world(tmp_path, monkeypatch):
    controller, game, calls = _camp_load_controller(
        tmp_path, monkeypatch, after_camp=lambda state: state != "loaded_menu")
    result = controller.run_discovery()
    assert result["failure"] is None
    assert game.keys[-3:] == ["L", "Y", "D"]
    assert _checkpoints(calls)[-1] == "ssb_camp_reloaded"
    assert result["completed_sequence"][-2:] == ["camp_load", "camp_reload"]
    assert result["mapping"]["reload"]["status"] == "awaiting image review"


def test_camp_load_without_an_exact_frame_stops_without_a_key(tmp_path, monkeypatch):
    controller, game, calls = _camp_load_controller(
        tmp_path, monkeypatch, after_camp=lambda state: state != "load_anyway")
    original = controller._capture
    monkeypatch.setattr(controller, "_capture", lambda state, check=True: (
        {**original(state, check=check), "crop": None} if state == "load_anyway"
        else original(state, check=check)))
    result = controller.run_discovery()
    assert "no exact crop was taken" in result["failure"]
    assert game.keys[-1] == "L"
    assert "ssb_camp_after_l" not in _checkpoints(calls)


def test_camp_load_key_cap_is_its_own(tmp_path, monkeypatch):
    controller, *_ = _discovery_controller(tmp_path, monkeypatch)
    controller.args.discover = "ssb-camp-load"
    controller.mapping_commands = winwishaccept.CAMP_LOAD_MAPPING_COMMANDS - 1
    controller._count()
    with pytest.raises(winwishaccept.AcceptanceStop, match="43-command mapping cap"):
        controller._count()
    controller.args.discover = "ssb-leave-yes"
    controller.mapping_commands = winwishaccept.MAX_MAPPING_COMMANDS
    with pytest.raises(winwishaccept.AcceptanceStop, match="40-command mapping cap"):
        controller._count()


def test_camp_load_preflight_requires_the_load_anyway_guard(tmp_path, monkeypatch):
    from tools.amiga import maproute, route_silver_blades

    args = _discovery_args(tmp_path)
    args.discover = "ssb-camp-load"
    args.deadline = 2100
    args.manifest.write_text('{"title":"ssb","substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    route.phases = (*route.phases[:3], maproute._ssb_transition(), *route.phases[4:])
    pinned = {"df0": winwishaccept.DISCOVERY_DF0_SHA256,
              "df1": route_silver_blades.DISK_B_SHA256}
    route.media = tuple(SimpleNamespace(key=m.key, path=m.path, sha256=pinned[m.key])
                        for m in route.media)
    original_digest = winwishaccept.digest
    monkeypatch.setattr(winwishaccept, "digest", lambda path: pinned[path.stem]
                        if path.suffix == ".adf" else original_digest(path))
    route.guard_path.write_text("{}")
    monkeypatch.setattr(route_silver_blades, "journal_preflight", lambda executable: None)
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda args: (
        (pathlib.Path(args[args.index("--out") + 1]) / "guards.json").write_text("{}") and 0))
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={name: True for phase in route.phases[:4]
               for name in (phase.initial_state, *(s.state for s in phase.steps))}
        | {"continue": True, "title": True, "camp": True}))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match=r"route has no measured guards for load_anyway\Z"):
        winwishaccept.preflight(args, guest=SimpleNamespace(gh=lambda *a: pytest.fail("guest")),
                                route_for=lambda *unused: route, driver_sha=SHA)


def _failing_tab(controller, monkeypatch, calls, stop_wish):
    def show_tab(guest, holder, name):
        calls.append(("tab", name))
        raise winwishaccept.winwish.WinwishError(f"fail no control named {name}")

    monkeypatch.setattr(controller, "_game_section",
                        winwishaccept.Controller._game_section.__get__(controller))
    monkeypatch.setattr(winwishaccept.winwish, "show_tab", show_tab)
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish", stop_wish)


def test_encounters_are_still_turned_off_when_closing_wish_fails(tmp_path, monkeypatch):
    controller, _, _, _, calls = _discovery_controller(tmp_path, monkeypatch)

    def stop_wish(guest, holder):
        calls.append(("stop_wish",))
        raise winwishaccept.winwish.WinwishError("ssh: connection lost")

    _failing_tab(controller, monkeypatch, calls, stop_wish)
    controller.discovery = False
    controller.booted = False
    controller._switch(True)
    controller._cleanup()
    errors = controller.summary["cleanup"]["errors"]
    assert any(error.startswith("encounters: ") and "closing Wish failed (ssh: connection lost)" in error
               for error in errors)
    assert controller.pipe_released
    assert not controller.wish_closed
    assert calls.index(("stop_wish",)) < calls.index(("switch", False))
    assert controller.encounters.state.load() == {"on": False, "rows": []}


def test_a_failure_unrelated_to_the_tab_does_not_close_wish(tmp_path, monkeypatch):
    controller, _, _, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_game_section",
                        lambda: (_ for _ in ()).throw(OSError("ssh dropped")))
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish",
                        lambda guest, holder: calls.append(("stop_wish",)))
    with pytest.raises(OSError):
        controller._free_pipe()
    assert ("stop_wish",) not in calls


def test_the_ordinary_cleanup_closes_wish_when_the_editor_tab_cannot_be_shown_and_turns_encounters_off(
        tmp_path, monkeypatch):
    controller, _, _, _, calls = _discovery_controller(tmp_path, monkeypatch)
    _failing_tab(controller, monkeypatch, calls,
                 lambda guest, holder: calls.append(("stop_wish",)) or "ok closed")
    controller.discovery = False
    controller.booted = False
    controller._switch(True)
    controller._cleanup()
    errors = controller.summary["cleanup"]["errors"]
    assert calls.index(("stop_wish",)) < calls.index(("switch", False))
    assert controller.encounters.state.load() == {"on": False, "rows": []}
    assert any(error.startswith("encounters: the editor tab could not be shown") for error in errors)


def test_encounters_are_switched_off_and_wish_kept_when_the_tab_step_fails_for_another_reason(
        tmp_path, monkeypatch):
    controller, _, _, _, calls = _discovery_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_game_section",
                        lambda: (_ for _ in ()).throw(OSError("ssh dropped")))
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish",
                        lambda guest, holder: calls.append(("stop_wish",)))
    controller.discovery = False
    controller.booted = False
    controller._switch(True)
    controller._cleanup()
    errors = controller.summary["cleanup"]["errors"]
    assert ("switch", False) in calls and ("stop_wish",) not in calls
    assert controller.encounters.state.load() == {"on": False, "rows": []}
    assert any("encounters: ssh dropped" in error for error in errors)


def _reload_screens(controller, game, *, first_pages=9, after_pages=3):
    """Extend the story fake with the camp LOAD screens that lead into the reload."""
    st, answer = _story_screens(controller, game, first_pages=first_pages, after_pages=after_pages)
    story_press = game.press
    camp = {("world", "E"): "camp", ("camp", "L"): "load_anyway",
            ("load_anyway", "Y"): "load_picker"}

    def press(holder, key, timeout):
        if (st["show"], key) in camp:
            game.keys.append(key)
            st["show"] = camp[(st["show"], key)]
        else:
            story_press(holder, key, timeout)

    game.press = press
    return st, answer


def _real_ssb_phases():
    from tools.amiga import maproute

    return maproute._phases("ssb", maproute._load("ssb", "D", opening_scene=True), "D")


def test_story_pages_during_the_reload_are_answered(tmp_path, monkeypatch):
    from tools.amiga import maproute, route_silver_blades

    controller, game, _, _, _ = _discovery_controller(tmp_path, monkeypatch)
    st, answer = _reload_screens(controller, game)
    st["show"] = "world"
    monkeypatch.setattr(route_silver_blades, "run_journal_answer", answer)
    controller.args.discover = None
    controller.discovery = False
    controller.run_phase(maproute._ssb_reload("D"))
    assert game.keys == ["E", "L", "Y", "D", "B", *["RET"] * 9, "E", "N", *["RET"] * 3]
    assert "ssb_camp_reloaded" in controller.checkpoints


def _ordinary_ssb_controller(tmp_path, monkeypatch, extra_phase=()):
    controller, *_ = _discovery_controller(tmp_path, monkeypatch)
    controller.route.phases = (*_real_ssb_phases(), *extra_phase)
    controller.args.discover = None
    return controller


def test_the_full_pool_route_fits_the_ordinary_key_limit_and_has_a_walkout_row(
        tmp_path, monkeypatch):
    from tools.amiga import maproute

    phases = maproute._phases("pool", maproute._load("pool", "A"), "A")
    keys = sum(winwishaccept._phase_keys(phase) for phase in phases)
    assert keys == winwishaccept.ORDINARY_MAPPING_COMMANDS["pool"] == 55
    controller, *_ = _discovery_controller(tmp_path, monkeypatch)
    controller.route.title = "pool"
    controller.route.phases = phases
    controller.args.discover = None
    for _ in range(keys):
        controller._count()
    with pytest.raises(winwishaccept.AcceptanceStop, match="55-command mapping cap"):
        controller._count()
    walkout = [step.checkpoint for phase in phases if phase.name == "walkout"
               for step in phase.steps if step.checkpoint]
    assert walkout[-1] == "pool_walkout_grid"
    pool = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=SimpleNamespace(**{**vars(_route()), "title": "pool", "phases": phases}),
        zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    assert list(pool.summary["mapping"]).index("walkout") == list(
        pool.summary["mapping"]).index("reopen") + 1
    plain = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=_route(), zipped=tmp_path / "build.zip", info={"media": {}}, clock=FakeClock())
    assert "walkout" not in plain.summary["mapping"]


def test_the_full_silver_blades_route_fits_the_ordinary_key_limit(tmp_path, monkeypatch):
    controller = _ordinary_ssb_controller(tmp_path, monkeypatch)
    keys = sum(1 for phase in controller.route.phases for step in phase.steps
               if step.kind in ("key", "turn", "move", "insert"))
    assert winwishaccept.ORDINARY_MAPPING_COMMANDS["ssb"] == 44 == keys
    for _ in range(44):
        controller._count()
    with pytest.raises(winwishaccept.AcceptanceStop, match="44-command mapping cap"):
        controller._count()


def test_a_route_with_more_keys_than_its_title_limit_stops(tmp_path, monkeypatch):
    extra = (_phase("extra", "world", _step("key", "world", key="NP8")),)
    controller = _ordinary_ssb_controller(tmp_path, monkeypatch, extra)
    with pytest.raises(winwishaccept.AcceptanceStop, match="44-command mapping cap"):
        for _ in range(45):
            controller._count()
    assert controller.mapping_commands == 44


def test_other_titles_and_discovery_keep_the_default_key_limit(tmp_path, monkeypatch):
    controller = _ordinary_ssb_controller(tmp_path, monkeypatch)
    controller.args.discover = "ssb-leave"
    controller.mapping_commands = 40
    with pytest.raises(winwishaccept.AcceptanceStop, match="40-command mapping cap"):
        controller._count()
    controller.args.discover = None
    controller.route.title = "curse"
    with pytest.raises(winwishaccept.AcceptanceStop, match="40-command mapping cap"):
        controller._count()


def test_the_flag_check_runs_on_silver_blades(tmp_path, monkeypatch):
    clock = FakeClock()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=_route(), zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    names = ("Heal party", "Save spells", "Restore spells", "Identify",
             "Quickfight off", "Fast Travel")
    modes = iter((True, False, True))
    def controls(*args):
        enabled = next(modes)
        # Fast Travel has no flag of its own, so it reads as it does with the flags on.
        return [f"Button|{name}|{name}|enabled={True if name == 'Fast Travel' else enabled}"
                for name in names]
    monkeypatch.setattr(winwishaccept.winwish, "ui", controls)
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: 1)
    monkeypatch.setattr(winwishaccept.winwish, "restart_wish", lambda *args, **kwargs: None)
    controller.flag_controls()
    assert set(controller.summary["flags"]) == {"on", "map_only", "restored"}


def test_ordinary_silver_blades_preflight_checks_the_journal_answer(tmp_path, monkeypatch):
    from tools.amiga import route_silver_blades

    called = []
    monkeypatch.setattr(route_silver_blades, "journal_preflight",
                        lambda python: called.append(python))
    args = _args(tmp_path)
    args.manifest.write_text("{}")
    guest = SimpleNamespace(gh=lambda *args: pytest.fail("guest touched before the mute proof"))
    with pytest.raises(winwishaccept.AcceptanceStop, match="mute"):
        winwishaccept.preflight(args, guest=guest, route_for=lambda title, manifest: _route(),
                               driver_sha=SHA)
    assert called


def _map_walk_controller(tmp_path, monkeypatch, *, tab_seconds=8.0):
    """The discovery controller with `--walk-tab map` over a fake party that a scheduled key
    moves, with its tab, key, shot, read and switch calls in one list."""
    from automap import amigaparty
    from tools.amiga import amigatarget

    controller, game, clock, _, _ = _discovery_controller(tmp_path, monkeypatch)
    controller.args.walk_tab = "map"
    monkeypatch.delattr(controller, "_game_section")
    monkeypatch.delattr(controller, "_checkpoint")
    events = []
    party = {"x": 3, "y": 3, "facing": 2}
    grab = game.grab
    game.grab = lambda state, raw, crop, timeout: (events.append(("game_shot", state)),
                                                   grab(state, raw, crop, timeout))[1]
    game.press = lambda holder, key, timeout: events.append(("press", key))

    def schedule_key(holder, key, lead, timeout):
        events.append(("schedule", key))
        if key == "NP8":
            step = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}[party["facing"]]
            party["x"] += step[0]
            party["y"] += step[1]
        else:
            party["facing"] = (party["facing"] + (1 if key == "NP6" else -1)) % 4
        return "404"
    game.schedule_key = schedule_key

    def show_tab(guest, holder, name):
        clock.now += tab_seconds if name == "Automapper" else 1.0
        events.append(("tab", name))
        return []
    monkeypatch.setattr(winwishaccept.winwish, "show_tab", show_tab)

    def shot(guest, holder, kind, path):
        events.append(("wish_shot", pathlib.Path(path).name))
        pathlib.Path(path).write_bytes(b"wish")
    monkeypatch.setattr(winwishaccept.winwish, "shot", shot)
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Text|Party|||"])
    target = SimpleNamespace(
        fix=lambda: SimpleNamespace(**party, outdoors=False, world_map=False,
                                    window=None, heading=None),
        geo=lambda: b"synthetic", close=lambda: None)
    monkeypatch.setattr(amigatarget, "connect_pipe",
                        lambda *args: (events.append(("engine_read",)), target)[1])
    monkeypatch.setattr(amigaparty, "read_party", lambda target: None)
    monkeypatch.setattr(controller, "_compare_checkpoint",
                        lambda name, expected, engine: winwishaccept.row("awaiting image review"))

    class Encounters:
        state = SimpleNamespace(load=lambda: {"on": controller.encounters_on, "rows": []})

        def __init__(self):
            self.press = lambda key: events.append(("press", key))

        def keys(self, names):
            events.append(("encounters_apply", tuple(names)))
            for name in names:
                self.press(name)
            return {"action": "keys", "pressed": list(names)}

    def switch(enabled):
        controller.encounters = controller.encounters or Encounters()
        controller.encounters_on = enabled
        events.append(("switch", enabled, clock.now))
    monkeypatch.setattr(controller, "_switch", switch)
    controller.pipe_released = True
    return controller, events, clock, party


def test_map_walk_guards_every_key_and_keeps_the_automapper_showing_while_it_lands(
        tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, events, _, party = _map_walk_controller(tmp_path, monkeypatch)
    walk = maproute._ssb_walk()
    controller.run_phase(walk)
    keys = [step for step in walk.steps if step.kind in ("move", "turn")]
    assert len(keys) == 22 and party == {"x": 15, "y": 8, "facing": 1}
    expected = []
    for index, step in enumerate(keys, 1):
        name = step.checkpoint or f"walk_key_{index:02d}"
        # The screen is guarded, and on the first key the party read, before the key is queued.
        expected += [("game_shot", "world"), *([("engine_read",)] if index == 1 else []),
                     ("encounters_apply", (step.key,)), ("schedule", step.key),
                     ("tab", "Automapper"), ("wish_shot", f"wish-{name}.png"),
                     ("tab", "Character Editor"), ("game_shot", "world"), ("engine_read",)]
    first = events.index(("encounters_apply", (keys[0].key,))) - 2
    # No key goes in by the pipe, and nothing changes tab while a queued key lands.
    assert not [event for event in events if event[0] == "press"]
    assert [e for e in events[first:] if e[0] != "switch"] == expected + [("game_shot", "world")]
    assert [record["key"] for record in controller.summary["map_walk_keys"]] == [
        step.key for step in keys]
    for step in keys:
        if step.checkpoint:
            checkpoint = controller.checkpoints[step.checkpoint]
            assert checkpoint["walk_tab"] == "map"
            schedule = checkpoint["schedule"]
            assert schedule["tab_shown_s"] < schedule["key_earliest_s"] - winwishaccept.WALK_TAB_MARGIN
            assert schedule["shot_s"] >= schedule["key_latest_s"] + winwishaccept.WALK_SETTLE
    assert controller.keys_pending_until is None
    assert controller.summary["completed_sequence"] == ["walk"]


def test_map_walk_stops_when_a_queued_key_leaves_the_party_where_it_was(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, events, _, party = _map_walk_controller(tmp_path, monkeypatch)
    controller.game.schedule_key = lambda holder, key, lead, timeout: (
        events.append(("schedule", key)), "404")[1]
    with pytest.raises(winwishaccept.AcceptanceStop, match="stayed at 3,3"):
        controller.run_phase(maproute._ssb_walk())
    assert [event for event in events if event[0] == "schedule"] == [("schedule", "NP8")]
    assert controller.summary["map_walk_keys"][0]["fix_after"] == {"x": 3, "y": 3, "facing": 2}


def test_map_walk_stops_before_the_wish_shot_when_the_automapper_shows_too_late(tmp_path,
                                                                                  monkeypatch):
    from tools.amiga import maproute

    controller, events, _, _ = _map_walk_controller(tmp_path, monkeypatch, tab_seconds=40.0)
    with pytest.raises(winwishaccept.AcceptanceStop, match="Automapper"):
        controller.run_phase(maproute._ssb_walk())
    assert [event for event in events if event[0] == "schedule"] == [("schedule", "NP8")]
    assert not [event for event in events if event[0] in ("wish_shot", "press")]


def test_map_walk_stops_before_the_wish_shot_when_route_time_cuts_the_settle(tmp_path,
                                                                              monkeypatch):
    from tools.amiga import maproute

    controller, events, _, _ = _map_walk_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "left", lambda limit: min(limit, 20.0))
    with pytest.raises(winwishaccept.AcceptanceStop, match="could have landed"):
        controller.run_phase(maproute._ssb_walk())
    assert not [event for event in events if event[0] in ("wish_shot", "press")]


def test_cleanup_waits_for_a_queued_key_before_turning_encounters_off(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, events, clock, _ = _map_walk_controller(tmp_path, monkeypatch, tab_seconds=28.0)
    with pytest.raises(winwishaccept.AcceptanceStop, match="Automapper"):
        controller.run_phase(maproute._ssb_walk())
    pending = controller.keys_pending_until
    assert pending is not None and clock.now < pending
    controller._cleanup()
    switched_off = [event for event in events if event[:2] == ("switch", False)]
    assert switched_off and switched_off[-1][2] >= pending
    assert controller.keys_pending_until is None
    waits = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()
             if '"scheduled_key_wait"' in line]
    assert len(waits) == 1 and waits[0]["seconds"] > 0


def test_cleanup_waits_when_the_key_schedule_raises_after_sending(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, events, clock, _ = _map_walk_controller(tmp_path, monkeypatch)
    queued = []

    def schedule_key(holder, key, lead, timeout):
        queued.append(clock.now - 0.25)  # the deadline argument read the clock once since
        raise winwishaccept.AcceptanceStop("reply lost after the send")
    controller.game.schedule_key = schedule_key
    with pytest.raises(winwishaccept.AcceptanceStop, match="reply lost"):
        controller.run_phase(maproute._ssb_walk())
    bound = winwishaccept._latest_landing(queued[0], winwishaccept.MIN_EMULATION_SPEED)
    assert controller.keys_pending_until == bound
    controller._cleanup()
    switched_off = [event for event in events if event[:2] == ("switch", False)]
    assert switched_off and switched_off[-1][2] >= bound


def test_cleanup_waits_for_a_key_that_lands_late_after_the_stop(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, events, clock, _ = _map_walk_controller(tmp_path, monkeypatch)
    queued = []

    def schedule_key(holder, key, lead, timeout):
        queued.append(clock.now - 0.25)  # the deadline argument read the clock once since
        clock.sleep(3.0)  # the debugger call takes time; the key lands after its reply
        queued.append(clock.now + 0.25)  # the clock read that follows the reply
        return "404"
    controller.game.schedule_key = schedule_key
    with pytest.raises(winwishaccept.AcceptanceStop, match="stayed at 3,3"):
        controller.run_phase(maproute._ssb_walk())
    bound = winwishaccept._latest_landing(queued[1], winwishaccept.SLOW_EMULATION_SPEED)
    assert controller.keys_pending_until == bound
    assert bound > winwishaccept._latest_landing(queued[0], winwishaccept.SLOW_EMULATION_SPEED)
    controller._cleanup()
    switched_off = [event for event in events if event[:2] == ("switch", False)]
    assert switched_off and switched_off[-1][2] >= bound


def test_walk_tab_parser_and_computed_deadline(tmp_path):
    parser = winwishaccept._parser()
    base = ["--title", "ssb", "--manifest", str(tmp_path / "prepare.json"),
            "--sha", SHA, "--holder", "test-acw", "--mute-proof",
            str(tmp_path / "mute.json"), "--out", str(tmp_path), "--discover", "ssb-camp-load"]
    assert parser.parse_args(base).walk_tab == "editor"
    assert parser.parse_args(base + ["--walk-tab", "map"]).walk_tab == "map"
    assert winwishaccept._deadline_limit("ssb-camp-load", "map") == (
        winwishaccept.LEAVE_DISCOVERY_SECONDS - winwishaccept.EDITOR_WALK_SECONDS
        + -(-11 * winwishaccept.MAP_WALK_KEYS * winwishaccept.MAP_KEY_SECONDS // 10))
    args = _discovery_args(tmp_path)
    args.discover, args.walk_tab = "ssb-opening-first", "map"
    with pytest.raises(winwishaccept.AcceptanceStop, match="walk-tab map"):
        winwishaccept.preflight(args, guest=object(), route_for=None)


def test_reset_soft_resets_the_holders_amiga_through_the_pipe_and_requires_its_reply(monkeypatch):
    from automap import amiga

    holders = []

    def soft_reset(self):
        holders.append(self.holder)
        return "404"
    monkeypatch.setattr(amiga.WinuaePipe, "soft_reset", soft_reset)
    guest = winuaesession.WinGuest()
    assert guest.reset("test-acw", 30) == "404"
    assert holders == ["test-acw"]
    monkeypatch.setattr(amiga.WinuaePipe, "soft_reset", lambda self: "Unknown command")
    with pytest.raises(winuaesession.RouteError, match="Unknown command"):
        guest.reset("test-acw", 30)


def test_schedule_key_queues_one_key_through_the_pipe_and_requires_its_reply(monkeypatch):
    from automap import amiga

    queued = []

    def press_later(self, code, frames, hold=6):
        queued.append((self.holder, code, frames, hold))
        return "404"
    monkeypatch.setattr(amiga.WinuaePipe, "press_later", press_later)
    guest = winuaesession.WinGuest()
    assert guest.schedule_key("test-acw", "NP8", 1500, 30) == "404"
    assert queued == [("test-acw", 0x3E, 1500, winuaesession.KEY_HOLD_FRAMES)]
    monkeypatch.setattr(amiga.WinuaePipe, "press_later", lambda self, code, frames, hold=6:
                        "Unknown command")
    with pytest.raises(winuaesession.RouteError, match="Unknown command"):
        guest.schedule_key("test-acw", "NP8", 1500, 30)
    for key in ("F11", "NOSUCHKEY"):
        with pytest.raises(winuaesession.RouteError):
            guest.schedule_key("test-acw", key, 1500, 30)


def _screen_controller(tmp_path, title, interstitials, first, *, guards=None):
    """A controller whose fake screen shows `first`, with guards that match the screen's own name."""
    clock, game = FakeClock(), FakeGame()
    screen = {"show": first}

    def grab(state, raw, crop, timeout):
        pathlib.Path(raw).write_bytes(b"raw")
        pathlib.Path(crop).write_bytes(screen["show"].encode())
        return True

    game.grab = grab
    route = _route()
    route.title = title
    route.amiga_title = SimpleNamespace(wait_limits={}, title_limit=300,
                                        interstitials=interstitials)
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=SimpleNamespace(stop=lambda *args: None),
        game=game, guards=guards or (lambda state, path: path.read_bytes().decode() == state),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    controller.pipe_released = True
    return controller, game, screen


def test_the_pool_code_wheel_is_answered_before_the_title(tmp_path, monkeypatch):
    from tools.amiga import route_pool

    controller, game, screen = _screen_controller(
        tmp_path, "pool", route_pool.POOL.interstitials, "wheel")
    game.press = lambda holder, key, timeout: (game.keys.append(key), screen.update(
        show="title" if (screen["show"], key) == ("wheel", "RET") else screen["show"]))
    monkeypatch.setattr(controller, "_up", lambda restarts_emulator=False: None)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_cleanup",
                        lambda: controller.summary["cleanup"].update(errors=[]))

    def stop(route):
        raise winwishaccept.AcceptanceStop("the route ends after the title")

    monkeypatch.setattr(winwishaccept, "_phase_map", stop)
    result = controller.run_title()
    assert game.keys == ["RET"]
    assert result["interstitial_keys"] == 1
    assert result["mapping"]["title"]["status"] == "awaiting image review"


def test_a_slow_intro_gets_one_escape_and_a_party_menu_counts_as_the_title_passed(tmp_path):
    from tools.amiga import route_darkness

    controller, game, screen = _screen_controller(
        tmp_path, "darkness", route_darkness.DARKNESS.interstitials, "intro")
    clock = controller.clock
    game.press = lambda holder, key, timeout: game.keys.append(key)
    plain_sleep = controller.sleep

    def sleep(seconds):
        plain_sleep(seconds)
        if clock.now > 4:
            screen["show"] = "party_menu"

    controller.sleep = sleep
    frame = controller._await_title()
    assert game.keys == ["ESC"]
    assert frame["passed"] == "party_menu"
    assert controller._title_passed == "party_menu"


def test_the_load_phase_skips_its_title_key_once_the_party_menu_is_showing(tmp_path, monkeypatch):
    controller, game, screen = _screen_controller(tmp_path, "pool", (), "party_menu")
    controller._title_passed = "party_menu"
    controller._title_frame = {"crop": None}
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    phase = _phase("load", "title", _step("key", "party_menu", "P"))
    controller.run_phase(phase)
    assert game.keys == []


def test_a_new_title_wait_clears_a_title_passed_flag_left_by_an_earlier_one(tmp_path):
    controller, game, screen = _screen_controller(tmp_path, "pool", (), "mystery")
    controller._title_passed = "party_menu"
    controller._title_frame = {"crop": None}
    with pytest.raises(winwishaccept.AcceptanceStop, match="title screen was not recognized"):
        controller._await_title()
    assert controller._title_passed is None


def test_a_passed_title_with_a_phase_that_does_not_start_there_stops_with_the_mismatch(
        tmp_path, monkeypatch):
    controller, game, screen = _screen_controller(tmp_path, "curse", (), "party_menu")
    controller._title_passed = "party_menu"
    controller._title_frame = {"crop": None}
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    phase = _phase("load", "title", _step("key", "load_picker", "L"))
    with pytest.raises(winwishaccept.AcceptanceStop, match="ended on party_menu"):
        controller.run_phase(phase)
    assert game.keys == []


def test_the_title_row_says_when_the_wait_ended_on_the_party_menu():
    plain = winwishaccept._title_row({"crop": "a"})
    assert plain["observed"] is None
    passed = winwishaccept._title_row({"crop": "a", "passed": "party_menu"})
    assert passed["observed"] == {"screen": "party_menu"}
    assert passed["status"] == "awaiting image review"


def test_a_second_wheel_frame_or_an_unknown_frame_gets_no_title_key(tmp_path):
    from tools.amiga import route_pool

    controller, game, screen = _screen_controller(
        tmp_path, "pool", route_pool.POOL.interstitials, "wheel")
    with pytest.raises(winwishaccept.AcceptanceStop, match="title screen was not recognized"):
        controller._await_title()
    assert game.keys == ["RET"]
    controller, game, screen = _screen_controller(
        tmp_path / "unknown", "pool", route_pool.POOL.interstitials, "mystery")
    with pytest.raises(winwishaccept.AcceptanceStop, match="title screen was not recognized"):
        controller._await_title()
    assert game.keys == []


@pytest.mark.parametrize("measured", [True, False])
def test_the_curse_wheel_is_answered_only_where_its_guard_is_measured(tmp_path, monkeypatch,
                                                                      measured):
    from tools.amiga import amigacursewheel, route_curse

    class Guards:
        rules = {"title": {}, "front_end": {}, **({"curse_wheel": {}} if measured else {})}

        def __call__(self, state, path):
            return state in self.rules and path.read_bytes().decode() == state

    controller, game, screen = _screen_controller(
        tmp_path, "curse", route_curse.CURSE.interstitials, "curse_wheel", guards=Guards())
    answered = []

    def answer(holder, settle, *, guard):
        assert guard() and guard()
        answered.append((holder, settle))
        screen["show"] = "title"
        return True

    monkeypatch.setattr(amigacursewheel, "answer", answer)
    if measured:
        controller._await_title()
        assert answered == [("test-acw", winwishaccept.WHEEL_SETTLE)]
        assert controller.summary["interstitial_keys"] == 2
    else:
        with pytest.raises(winwishaccept.AcceptanceStop, match="title screen was not recognized"):
            controller._await_title()
        assert answered == []
    assert game.keys == []



def test_a_wheel_screen_that_changes_mid_answer_stops_the_run_with_no_further_key(tmp_path,
                                                                                monkeypatch):
    from tools.amiga import amigacursewheel, route_curse

    class Guards:
        rules = {"title": {}, "curse_wheel": {}}

        def __call__(self, state, path):
            return state in self.rules and path.read_bytes().decode() == state

    controller, game, screen = _screen_controller(
        tmp_path, "curse", route_curse.CURSE.interstitials, "curse_wheel", guards=Guards())
    # A stand-in reader and character: nothing here is a real challenge or answer.
    reader = SimpleNamespace(read_challenge=lambda image: {
        "box": 0, "pattern": 0, "espruar": 0, "dethek": 0})
    arithmetic = SimpleNamespace(answer_from_screen=lambda *args: "X")
    monkeypatch.setattr(amigacursewheel, "_wheel_modules", lambda: (reader, arithmetic))
    monkeypatch.setattr(amigacursewheel.amigadrive, "shot", lambda holder, out: {})
    monkeypatch.setattr(amigacursewheel.screens, "canonical_file", lambda source, out: None)
    monkeypatch.setattr(amigacursewheel, "_to_reader_scale", lambda path, screen=None: None)
    pressed = []
    monkeypatch.setattr(amigacursewheel.amigadrive, "press", lambda holder, key, settle: (
        pressed.append(key), screen.update(show="mystery")))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="curse_wheel: the code-wheel screen changed"):
        controller._await_title()
    assert pressed == ["X"]
    assert game.keys == []
    assert "interstitial_keys" not in controller.summary

def test_a_page_during_an_encounter_controlled_walk_goes_through_the_switch(tmp_path):
    from tools.amiga import maproute

    controller, game, screen = _screen_controller(
        tmp_path, "darkness", (("continue", ("keys", "RET"), frozenset({"world"}), 3),), "world")
    sent = []

    def keys(names):
        sent.extend(names)
        screen["show"] = "continue" if names == ["NP8"] else "world"
        return {"pressed": names}

    controller.encounters_on = True
    controller.encounters = SimpleNamespace(keys=keys)
    walk = maproute.Phase("walk", "world", (maproute.Step("move", "world", key="NP8"),),
                          pages=("continue",))
    controller.run_phase(walk)
    assert sent == ["NP8", "RET"]
    assert game.keys == []
    assert controller.summary["interstitial_keys"] == 1


def test_a_page_a_phase_does_not_declare_gets_no_key(tmp_path):
    from tools.amiga import maproute

    controller, game, screen = _screen_controller(
        tmp_path, "darkness", (("continue", ("keys", "RET"), frozenset({"world"}), 3),), "world")
    game.press = lambda holder, key, timeout: (game.keys.append(key), screen.update(show="continue"))
    walk = maproute.Phase("walk", "world", (maproute.Step("move", "world", key="NP8"),))
    with pytest.raises(winwishaccept.AcceptanceStop, match="world screen was not recognized"):
        controller.run_phase(walk)
    assert game.keys == ["NP8"]
    unknown = maproute.Phase("walk", "world", (), pages=("journal",))
    with pytest.raises(winwishaccept.AcceptanceStop, match="names page journal"):
        winwishaccept._declared_pages(controller.route, [unknown])


class _WorldMapMemory(_PartyMemory):
    def fix(self):
        return SimpleNamespace(x=0, y=0, facing=None, outdoors=False, world_map=True,
                               window=None, heading=None, world_node=6, world_leg=2)


def test_a_checkpoint_records_and_checks_the_world_node(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller = _party_checkpoint_controller(tmp_path, monkeypatch, _WorldMapMemory(items=0))
    controller._checkpoint("curse_world", maproute.Expected(
        engine={"world_map": 1, "world_node": 6}), {"raw": "game"})
    record = controller.checkpoints["curse_world"]
    assert (record["observed"]["fix"]["world_node"], record["observed"]["fix"]["world_leg"]) == (6, 2)
    assert record["comparison"]["status"] == "awaiting image review"
    with pytest.raises(winwishaccept.AcceptanceStop, match="engine world_node reads 6, expected 7"):
        controller._checkpoint("curse_world_again", maproute.Expected(
            engine={"world_node": 7}), {"raw": "game"})


def test_view_changed_passes_on_a_new_view_and_fails_on_the_same_one(tmp_path):
    from tools.amiga import maproute

    controller, _, _ = _screen_controller(tmp_path, "curse", (), "world")
    indoors = {"x": 2, "y": 6, "facing": 1, "outdoors": False, "world_map": False, "area": 16}
    controller.checkpoints["yulash"] = {"observed": {"fix": indoors, "geo_sha256": "a"}}
    expected = maproute.Expected(compare_to="yulash", relation="view_changed")
    world = {"fix": {**indoors, "x": 0, "y": 0, "facing": None, "world_map": True},
             "geo_sha256": "a"}
    assert controller._compare_checkpoint("world", expected, world)["status"] == (
        "awaiting image review")
    same = controller._compare_checkpoint("still", expected, {"fix": dict(indoors), "geo_sha256": "a"})
    assert same["status"] == "failed"
    assert "the view stayed" in same["reason"]


def _relaunch_phase():
    from tools.amiga import maproute

    return maproute.Phase("reload", "cli", (maproute.Step(
        "type", "wheel", keys=("P", "R", "O", "G", "R", "A", "M", "RET"), screen="cli",
        relaunch=True),))


def test_a_relaunch_clears_the_party_nodes_and_the_encounter_target(tmp_path):
    controller, game, screen = _screen_controller(tmp_path, "pool", (), "cli")
    game.press = lambda holder, key, timeout: (game.keys.append(key), screen.update(
        show="wheel" if key == "RET" else "cli"))
    controller.party_nodes = [(0xC60000, 340)]
    controller.encounters = SimpleNamespace(state=SimpleNamespace(
        load=lambda: {"on": False, "rows": []}))
    controller.run_phase(_relaunch_phase())
    assert controller.party_nodes == []
    assert controller.encounters is None


@pytest.mark.parametrize("outstanding", ["on", "rows"])
def test_a_relaunch_with_suppression_outstanding_sends_no_key(tmp_path, outstanding):
    controller, game, _ = _screen_controller(tmp_path, "pool", (), "cli")
    controller.party_nodes = [(0xC60000, 340)]
    controller.encounters_on = outstanding == "on"
    controller.encounters = SimpleNamespace(state=SimpleNamespace(
        load=lambda: {"on": False, "rows": [1] if outstanding == "rows" else []}))
    with pytest.raises(winwishaccept.AcceptanceStop, match="restarts with encounter suppression"):
        controller.run_phase(_relaunch_phase())
    assert game.keys == []
    assert controller.party_nodes == [(0xC60000, 340)]


def test_a_relaunch_whose_wait_fails_still_forgets_the_old_program(tmp_path):
    controller, game, screen = _screen_controller(tmp_path, "pool", (), "cli")
    game.press = lambda holder, key, timeout: (game.keys.append(key), screen.update(
        show="mystery" if key == "RET" else "cli"))
    controller.party_nodes = [(0xC60000, 340)]
    controller.encounters = SimpleNamespace(state=SimpleNamespace(
        load=lambda: {"on": False, "rows": []}))
    with pytest.raises(winwishaccept.AcceptanceStop, match="wheel screen was not recognized"):
        controller.run_phase(_relaunch_phase())
    assert game.keys[-1] == "RET"
    assert controller.party_nodes == []
    assert controller.encounters is None


def _type_controller(tmp_path, monkeypatch, changes_after=None):
    """A CLI that shows `mystery` once `changes_after` is typed, with every guard check logged."""
    controller, game, screen = _screen_controller(tmp_path, "pool", (), "cli")
    waits, guards = [], []
    real_await, real_first = controller._await, controller._await_first
    monkeypatch.setattr(controller, "_await", lambda state, **kwargs: (
        waits.append((state, list(game.keys))), real_await(state, **kwargs))[1])
    monkeypatch.setattr(controller, "_await_first", lambda states, **kwargs: (
        guards.append((states, list(game.keys))), real_first(states, **kwargs))[1])
    game.press = lambda holder, key, timeout: (game.keys.append(key), screen.update(
        show="wheel" if key == "RET" else "mystery" if key == changes_after else screen["show"]))
    return controller, game, waits, guards


_TYPED = ("P", "R", "O", "G", "R", "A", "M", "RET")


def test_a_type_step_guards_each_key_and_awaits_its_state_once(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, game, waits, guards = _type_controller(tmp_path, monkeypatch)
    controller.run_phase(maproute.Phase("reload", "cli", (maproute.Step(
        "type", "wheel", keys=_TYPED, screen="cli"),)))
    assert game.keys == list(_TYPED)
    assert guards == [(("cli",), list(_TYPED[:n])) for n in range(len(_TYPED))]
    assert waits == [("cli", []), ("wheel", list(_TYPED))]
    assert controller.mapping_commands == 8


def test_a_type_step_stops_before_the_next_key_when_its_screen_changes(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, game, waits, guards = _type_controller(tmp_path, monkeypatch, changes_after="O")
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="cli was not recognized before typed key 4 of 8"):
        controller.run_phase(maproute.Phase("reload", "cli", (maproute.Step(
            "type", "wheel", keys=_TYPED, screen="cli"),)))
    assert game.keys == ["P", "R", "O"]
    assert waits == [("cli", [])]


@pytest.mark.parametrize("step,reason", [
    ({"kind": "type", "state": "wheel"}, "type step needs its keys"),
    ({"kind": "type", "state": "wheel", "keys": _TYPED}, "needs the screen its keys go to"),
    ({"kind": "type", "state": "", "keys": _TYPED, "screen": "cli"}, "type step needs a screen to wait for"),
    ({"kind": "key", "state": "", "key": "RET", "relaunch": True}, "key step needs a screen to wait for"),
])
def test_a_type_or_relaunch_step_without_a_screen_stops_preflight(step, reason):
    from tools.amiga import maproute

    with pytest.raises(winwishaccept.AcceptanceStop, match=reason):
        winwishaccept._check_steps(SimpleNamespace(phases=(maproute.Phase(
            "reload", "cli", (maproute.Step(**step),)),)))


def test_checkpoint_reads_are_recorded_without_a_verdict(tmp_path, monkeypatch):
    from tools.amiga import maproute

    memory = _PartyMemory(items=0)
    memory._put(memory.DATA + 0x57AC, 0xC70000)
    memory.image[0xC70024 - memory.BASE:0xC70027 - memory.BASE] = bytes((1, 34, 14))
    controller = _party_checkpoint_controller(tmp_path, monkeypatch, memory)
    reads = (maproute.Read("overland", "base", 0x57AC, 3, hop=0x24),
             maproute.Read("unset", "base", 0x57B0, 3, hop=0x24))
    controller._checkpoint("overland_step", None, {"raw": "game"}, reads=reads)
    record = controller.checkpoints["overland_step"]
    first, second = record["observed"]["memory_reads"]
    assert (first["pointer"], first["address"], first["hex"]) == (0xC70000, 0xC70024, "01220e")
    assert "the pointer is null" in second["error"]
    assert record["comparison"]["status"] == "awaiting image review"
    with pytest.raises(winwishaccept.AcceptanceStop, match="reads need a checkpoint"):
        winwishaccept._check_steps(SimpleNamespace(phases=(maproute.Phase(
            "transition", "world", (maproute.Step("move", "world", key="NP8", reads=reads),)),)))


def _echo_png(path, echoed):
    """A 100x40 crop: fixed text in the top 20 rows, and a line below that shows `echoed` characters."""
    image = Image.new("RGB", (100, 40), (0, 0, 0))
    for x in range(50):
        for y in range(20):
            image.putpixel((x, y), (200, 200, 200) if (x + y) % 3 else (0, 0, 90))
    for x in range(echoed * 4):
        for y in range(25, 35):
            image.putpixel((x, y), (255, 255, 255))
    image.save(path)


def _echo_controller(tmp_path, monkeypatch, rule_box):
    from tools.amiga import screens

    reference = tmp_path / "reference.png"
    _echo_png(reference, 0)
    rule = screens.guard_rule(reference, rule_box)
    rules = tmp_path / "guards.json"
    rules.write_text(json.dumps({"cli": rule}))
    controller, game, screen = _screen_controller(
        tmp_path, "pool", (), "cli", guards=screens.PixelGuards(rules))
    typed = []

    def grab(state, raw, crop, timeout):
        pathlib.Path(raw).write_bytes(b"raw")
        _echo_png(crop, len(typed))
        return True

    game.grab = grab
    game.press = lambda holder, key, timeout: (game.keys.append(key), typed.append(key))
    # The wheel state is matched by name only; the CLI crop above never equals it.
    monkeypatch.setattr(controller, "_await", lambda state, **kwargs: {"crop": None})
    return controller, game


def test_a_type_step_on_an_echoing_screen_passes_with_a_guard_that_leaves_the_line_out(
        tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, game = _echo_controller(tmp_path, monkeypatch, [0, 0, 50, 20])
    controller.run_phase(maproute.Phase("reload", "cli", (maproute.Step(
        "type", "wheel", keys=_TYPED, screen="cli"),)))
    assert game.keys == list(_TYPED)


def test_a_type_step_on_an_echoing_screen_stops_at_key_2_when_the_guard_covers_the_line(
        tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, game = _echo_controller(tmp_path, monkeypatch, [0, 0, 100, 40])
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="cli was not recognized before typed key 2 of 8"):
        controller.run_phase(maproute.Phase("reload", "cli", (maproute.Step(
            "type", "wheel", keys=_TYPED, screen="cli"),)))
    assert game.keys == ["P"]


def test_a_type_step_settles_before_the_guard_frame_of_every_key_after_the_first(
        tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, game, waits, guards = _type_controller(tmp_path, monkeypatch)
    events = []
    real_sleep = controller.sleep
    controller.sleep = lambda seconds: (events.append(("sleep", seconds)), real_sleep(seconds))[1]
    real_first = controller._await_first
    monkeypatch.setattr(controller, "_await_first", lambda states, **kwargs: (
        events.append(("guard", len(game.keys))), real_first(states, **kwargs))[1])
    controller.run_phase(maproute.Phase("reload", "cli", (maproute.Step(
        "type", "wheel", keys=_TYPED, screen="cli"),)))
    settles = [(at, e) for at, e in enumerate(events)
               if e == ("sleep", winwishaccept.WHEEL_SETTLE)]
    assert len(settles) == len(_TYPED) - 1
    for at, _ in settles:
        assert events[at + 1][0] == "guard"


def _reset_phase():
    from tools.amiga import maproute

    return maproute.Phase("reload", "reboot", (
        maproute.Step("reset", "title", relaunch=True),
        maproute.Step("key", "load_picker", key="L")), pages=("front_end",))


def test_a_reset_step_resets_once_answers_the_boot_pages_and_forgets_the_old_program(tmp_path):
    controller, game, screen = _screen_controller(
        tmp_path, "curse", (("front_end", ("keys", "ESC"), frozenset({"title"}), 4),), "reboot")
    resets = []
    game.reset = lambda holder, timeout: (resets.append(holder), screen.update(show="front_end"))
    game.press = lambda holder, key, timeout: (game.keys.append(key), screen.update(
        show={"ESC": "title", "L": "load_picker"}[key]))
    controller.party_nodes = [(0xC60000, 340)]
    controller.encounters = SimpleNamespace(state=SimpleNamespace(
        load=lambda: {"on": False, "rows": []}))
    controller.run_phase(_reset_phase())
    assert resets == ["test-acw"]
    assert game.keys == ["ESC", "L"]
    assert controller.mapping_commands == 1
    assert controller.party_nodes == [] and controller.encounters is None


def test_a_reset_with_suppression_on_sends_nothing(tmp_path):
    controller, game, _ = _screen_controller(tmp_path, "curse", (), "reboot")
    resets = []
    game.reset = lambda holder, timeout: resets.append(holder)
    controller.encounters_on = True
    with pytest.raises(winwishaccept.AcceptanceStop, match="restarts with encounter suppression"):
        controller.run_phase(_reset_phase())
    assert resets == [] and game.keys == []


def test_a_reset_step_must_be_declared_a_relaunch():
    from tools.amiga import maproute

    with pytest.raises(winwishaccept.AcceptanceStop, match="a reset step restarts the program"):
        winwishaccept._check_steps(SimpleNamespace(phases=(maproute.Phase(
            "reload", "reboot", (maproute.Step("reset", "title"),)),)))
    winwishaccept._check_steps(SimpleNamespace(phases=(_reset_phase(),)))


def _hires_controller(tmp_path, title, raw_source):
    """A controller whose grab keeps `raw_source` as the raw frame and, as `WinGuest.grab` does
    for a hires window, writes no crop and answers False."""
    controller, game, _ = _screen_controller(tmp_path, title, (), "unused")

    def grab(state, raw, crop, timeout):
        pathlib.Path(raw).write_bytes(pathlib.Path(raw_source).read_bytes())
        return False

    game.grab = grab
    return controller


def _hires_frame(path):
    """A 752x574 frame whose window holds one-pixel columns, as a hires AmigaDOS window does."""
    image = Image.new("RGB", (752, 574), (0, 0, 0))
    for x in range(16, 736, 2):
        for y in range(4, 572):
            image.putpixel((x, y), (255, 255, 255))
    image.save(path)
    return path


@pytest.mark.parametrize("title,state", [("pool", "cli"), ("curse", "reboot")])
def test_a_hires_window_is_cut_plainly_only_for_its_titles_amigados_screen(tmp_path, title, state):
    from tools.amiga import screens

    raw = _hires_frame(tmp_path / "hires.png")
    with pytest.raises(screens.NotExactCapture):
        screens.canonical(Image.open(raw))
    controller = _hires_controller(tmp_path, title, raw)
    frame = controller._capture(state, check=False)
    assert frame["hires"] is True
    with Image.open(frame["crop"]) as crop:
        assert crop.size == (720, 568)
        assert crop.getpixel((0, 0)) == (255, 255, 255) and crop.getpixel((1, 0)) == (0, 0, 0)
    assert controller._capture("world", check=False)["crop"] is None
    other = _hires_controller(tmp_path / "other", "darkness", raw)
    assert other._capture(state, check=False)["crop"] is None


@pytest.mark.parametrize("title,frame,state", [
    ("pool", "WISH-1/pool-cap1/31-afterY_t5.png", "cli"),
    ("curse", "WISH-1/cc-cap1/36-afterY_5.png", "reboot"),
])
def test_the_captured_amigados_windows_are_recognised_from_the_raw_winuae_frame(
        tmp_path, title, frame, state):
    """Reads the capture boots' raw frames, so it skips on a machine without them."""
    from tools.amiga import guardmaps, screens
    from tools.registry import scratch

    raw = scratch.cache_dir("acceptance") / frame
    if not raw.is_file():
        pytest.skip("the capture boots' raw frames are not on this machine")
    out = tmp_path / "guards"
    maps = pathlib.Path(guardmaps.__file__).parent
    assert guardmaps.main(["--maps", str(maps), "export", "--title", title, "--out", str(out)]) == 0
    controller = _hires_controller(tmp_path, title, raw)
    controller.guards = screens.PixelGuards(out / "guards.json")
    assert controller._still_on(state)
    assert controller._await_first(("world",), limit=2)[0] is None


def test_the_plain_cut_of_an_exact_frame_is_the_canonical_crop(tmp_path):
    from tools.amiga import screens

    native = Image.new("RGB", (376, 287), (0, 0, 0))
    for x in range(376):
        for y in range(0, 287, 3):
            native.putpixel((x, y), ((x * 7) % 256, (y * 5) % 256, 90))
    raw = tmp_path / "exact.png"
    native.resize((752, 574), Image.NEAREST).save(raw)
    crop = tmp_path / "cut.png"
    assert winwishaccept._plain_cut(raw, crop)
    with Image.open(raw) as image, Image.open(crop) as cut:
        assert cut.tobytes() == screens.canonical(image).tobytes()
    odd = tmp_path / "odd.png"
    Image.new("RGB", (100, 100)).save(odd)
    assert not winwishaccept._plain_cut(odd, tmp_path / "none.png")


def test_a_restarted_game_that_will_not_stop_fails_the_run_and_its_stop_is_bounded(
        tmp_path, monkeypatch):
    controller, events = _disconnect_controller(tmp_path, monkeypatch)
    stops = []

    def stop(holder, timeout):
        stops.append(timeout)
        if len(stops) == 2:
            raise winuaesession.RouteError("stop timed out")

    controller.lane.stop = stop

    result = controller.run_title()

    assert result["failure"] is None
    assert any("stop timed out" in error for error in result["cleanup"]["errors"])
    assert stops[1] <= 60 and stops[1] <= controller.total_end
    assert events[-1] == "down"


def test_no_time_left_is_an_error_rather_than_a_stop_with_no_timeout(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(
        tmp_path, monkeypatch,
        start=lambda *args, **kwargs: setattr(controller, "total_end", -1.0))
    stops = []
    controller.lane.stop = lambda holder, timeout: stops.append(timeout)

    result = controller.run_title()

    assert stops == [60.0]
    assert any("no time is left" in error for error in result["cleanup"]["errors"])


@pytest.mark.parametrize("leg", ["mapping", "persist", "reconnect"])
def test_every_leg_has_the_whole_route_time_to_the_cleanup_reserve(tmp_path, monkeypatch, leg):
    # The restart and reload used to be subtracted from every mapping run, which left the
    # longer titles' routes short of their last checkpoints; the reconnect leg alone does them.
    controller, _ = _disconnect_controller(tmp_path, monkeypatch, leg=leg)
    controller._set_deadlines()

    assert controller.route_end == controller.started + 3300 - winwishaccept.CLEANUP_SECONDS


def test_the_mapping_leg_grabs_the_disconnect_and_never_restarts_the_game(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(tmp_path, monkeypatch, leg="mapping")

    result = controller.run_title()

    assert result["failure"] is None
    assert events[events.index("connected.png"):events.index("lane-stop") + 4] == [
        "connected.png", "lane-stop", "disconnect-0.png", "disconnect-1.png", "disconnect-2.png"]
    assert "lane-start" not in events and "reconnected.png" not in events
    assert "reconnect" not in result["mapping"]
    assert controller.restarted is False


def test_the_mapping_leg_presses_no_action_on_a_route_with_enabled_actions(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(tmp_path, monkeypatch, leg="mapping")
    controller.route.actions = (SimpleNamespace(kind="heal", enabled=True, selector="hp",
                                                show=None, back=None),)
    controller.summary["actions"]["heal"] = winwishaccept.row()
    monkeypatch.setattr(controller, "run_actions", lambda: pytest.fail("actions pressed"))
    monkeypatch.setattr(controller, "_final_reload", lambda: pytest.fail("final reload ran"))

    result = controller.run_title()

    assert result["failure"] is None
    assert result["actions"]["heal"]["status"] == "unproven"
    assert result["actions"]["heal"]["reason"] == "pressed only on the persist leg"


def test_the_mapping_leg_stops_preflight_on_an_action_option():
    args = winwishaccept._parser().parse_args([
        "--title", "pool", "--manifest", "m", "--sha", SHA, "--holder", "h", "--mute-proof", "p",
        "--out", "o", "--leg", "mapping", "--action", "heal"])
    args.deadline = 1500

    with pytest.raises(winwishaccept.AcceptanceStop, match="--action needs --leg persist"):
        winwishaccept.preflight(args, guest=object(), route_for=None)


def test_the_reconnect_leg_runs_only_the_load_then_the_disconnect_and_reload(tmp_path, monkeypatch):
    controller, events = _disconnect_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "flag_controls", lambda: pytest.fail("flags set"))
    monkeypatch.setattr(controller, "run_actions", lambda: pytest.fail("actions pressed"))

    result = controller.run_title()

    assert result["failure"] is None
    assert controller.phases_run == [("load", None), ("load", "reconnect-load")]
    assert tuple(result["mapping"]) == winwishaccept.RECONNECT_ROWS
    assert result["actions"] == {}
    assert result["mapping"]["reconnect"]["status"] == "awaiting image review"


@pytest.mark.parametrize("extra, message", [
    (["--discover", "ssb-leave"], "not a discovery mode"),
    (["--action", "heal"], "presses no actions")])
def test_the_reconnect_leg_stops_preflight_for_a_discovery_mode_or_an_action(
        tmp_path, extra, message):
    args = winwishaccept._parser().parse_args([
        "--title", "pool", "--manifest", "m", "--sha", SHA, "--holder", "h", "--mute-proof", "p",
        "--out", "o", "--leg", "reconnect", *extra])
    args.deadline = 1500

    with pytest.raises(winwishaccept.AcceptanceStop, match=message):
        winwishaccept.preflight(args, guest=object(), route_for=None)


def test_the_parser_takes_the_reconnect_leg():
    args = winwishaccept._parser().parse_args([
        "--title", "pool", "--manifest", "m", "--sha", SHA, "--holder", "h", "--mute-proof", "p",
        "--out", "o", "--leg", "reconnect", "--deadline", "1500"])
    assert (args.leg, args.deadline) == ("reconnect", 1500)


def test_the_reload_starts_with_no_pipe_from_the_game_before_the_restart(tmp_path, monkeypatch):
    seen = []
    controller, events = _disconnect_controller(
        tmp_path, monkeypatch, reload_step=lambda c: seen.append(c.game._pipe))
    controller.game._pipe = "the first emulator's pipe"

    controller.run_title()

    assert seen == [None]


# ---- the persist leg: a save to a free slot, reloaded by the game's own Load ----

#: What each key does on the Silver Blades screens the persist leg meets: (screen, key) -> screen.
_SSB_SCREENS = {
    ("title", "L"): "world",
    ("world", "E"): "camp", ("camp", "S"): "camp_save_picker",
    ("camp_save_picker", "F"): "exit_game", ("exit_game", "N"): "camp",
    ("camp", "L"): "load_anyway", ("load_anyway", "Y"): "load_picker",
    ("load_picker", "F"): "loaded_menu", ("loaded_menu", "B"): "journal",
    ("treasure_bar", "E"): "treasure", ("treasure", "N"): "world",
}


class _ScreenGame(FakeGame):
    """A game that shows one named screen and changes it only on the keys in `table`."""

    def __init__(self, table, screen="title"):
        super().__init__()
        self.table, self.screen = dict(table), screen

    def grab(self, state, raw, crop, timeout):
        pathlib.Path(raw).write_bytes(b"raw")
        pathlib.Path(crop).write_bytes(self.screen.encode())
        return True

    def press(self, holder, key, timeout):
        super().press(holder, key, timeout)
        self.screen = self.table.get((self.screen, key), self.screen)


def _persist_args(tmp_path, **extra):
    args = _args(tmp_path)
    args.leg, args.action, args.wait_lanes = "persist", None, 0
    for name, value in extra.items():
        setattr(args, name, value)
    return args


def _persist_rig(tmp_path, monkeypatch, table, *, route=None, letter="F", actions=("heal",)):
    """A persist-leg controller on a scripted game, with everything outside the leg stubbed."""
    clock, game = FakeClock(), _ScreenGame(table)
    controller = winwishaccept.Controller(
        _persist_args(tmp_path), guest=object(), lane=object(), game=game,
        guards=lambda state, path: path.read_bytes().decode() == state,
        route=route or _route(), zipped=tmp_path / "build.zip",
        info={"media": {}, "persist": {"letter": letter, "actions": list(actions)}},
        clock=clock, sleep=clock.sleep)
    events = []

    def checkpoint(name, expected, frame, **kwargs):
        controller.checkpoints[name] = {"expected": expected}
        events.append((name, len(game.keys)))

    def answer():
        game.keys.append("JOURNAL")
        game.screen = "treasure_bar"

    monkeypatch.setattr(controller, "_up", lambda: setattr(controller, "booted", True))
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_await_title", lambda: {})
    monkeypatch.setattr(controller, "_checkpoint", checkpoint)
    monkeypatch.setattr(controller, "_answer_journal", answer)
    monkeypatch.setattr(controller, "run_actions", lambda: game.keys.append("ACTIONS"))
    monkeypatch.setattr(controller, "_action_readback",
                        lambda: events.append(("readback", len(game.keys))) or [])
    monkeypatch.setattr(controller, "_verify_persist", lambda: events.append(("verify", len(game.keys))))
    monkeypatch.setattr(controller, "_final_reload", lambda: game.keys.append("FINAL"))
    monkeypatch.setattr(controller, "_cleanup", lambda: None)
    monkeypatch.setattr(controller, "_verify_disk_slot", lambda: None)
    controller.summary["persistence"]["status"] = "awaiting image review"
    return controller, game, events


def test_persist_saves_after_the_last_action_then_loads_that_letter(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, game, events = _persist_rig(tmp_path, monkeypatch, _SSB_SCREENS)

    result = controller.run_persist()

    assert result["failure"] is None
    assert game.keys == ["L", "ACTIONS", "E", "S", "F", "N", "L", "Y", "F", "B", "JOURNAL",
                         "E", "N", "FINAL"]
    # The state is taken before camp opens, the party read once camp's bar is up, and the
    # reload is compared with the first.
    assert events[0] == ("persist_saved", 2)
    assert events[1] == ("readback", 3)
    assert events[-2][0] == "persist_reloaded"
    assert controller.checkpoints["persist_reloaded"]["expected"] == maproute.Expected(
        compare_to="persist_saved", relation="equal")
    assert controller.action_commands == 10 <= controller.action_limit
    assert controller.mapping_commands == 1


def test_persist_branches_only_on_guarded_screens(tmp_path, monkeypatch):
    # A load picker straight after L has no LOAD ANYWAY question to answer.
    table = {**_SSB_SCREENS, ("camp", "L"): "load_picker"}
    controller, game, _ = _persist_rig(tmp_path, monkeypatch, table)
    assert controller.run_persist()["failure"] is None
    assert game.keys[6:] == ["L", "F", "B", "JOURNAL", "E", "N", "FINAL"]

    # No treasure offer after the journal: the world bar is already up.
    controller, game, _ = _persist_rig(tmp_path / "b", monkeypatch, _SSB_SCREENS)
    monkeypatch.setattr(controller, "_answer_journal", lambda: setattr(game, "screen", "world"))
    assert controller.run_persist()["failure"] is None
    assert game.keys[6:] == ["L", "Y", "F", "B", "FINAL"]


def test_an_unknown_screen_after_load_gets_no_further_key_and_keeps_its_frame(tmp_path, monkeypatch):
    table = {**_SSB_SCREENS, ("camp", "L"): "mystery"}
    controller, game, _ = _persist_rig(tmp_path, monkeypatch, table)
    controller.summary["persistence"]["status"] = "unproven"

    result = controller.run_persist()

    assert game.keys == ["L", "ACTIONS", "E", "S", "F", "N", "L"]
    assert "persist reload: the screen after L" in result["failure"]
    assert list(tmp_path.glob("game-*.raw.png"))
    assert result["persistence"]["reason"] == result["failure"]


def test_persist_leg_runs_only_the_title_prefix(tmp_path, monkeypatch):
    from tools.amiga import maproute

    seen = {}
    for title, manifest in (("pool", test_maproute._manifest("pool", tmp_path)),
                            ("curse", test_maproute._yulash_manifest(tmp_path))):
        route = maproute.route_for(title, manifest)
        controller, _, _ = _persist_rig(tmp_path / title, monkeypatch, {}, route=route, letter="E")
        names = []
        monkeypatch.setattr(controller, "run_phase", lambda phase, *a, names=names, **k: names.append(phase.name))
        monkeypatch.setattr(controller, "_persist_save", lambda: None)
        monkeypatch.setattr(controller, "_persist_reload", lambda: None)
        monkeypatch.setattr(controller, "_await", lambda *a, **k: {})
        controller.run_persist()
        seen[title] = names

    assert seen == {"pool": ["load", "outdoor", "transition"], "curse": ["load"]}


def test_wait_lanes_is_passed_to_up_and_not_charged_to_the_route_deadline(tmp_path, monkeypatch):
    route = _route()
    route.mounted = ()
    route.amiga_title = SimpleNamespace(wait_limits={}, title_limit=30, interstitials=(), options=())
    clock = FakeClock()
    controller = winwishaccept.Controller(
        _persist_args(tmp_path, wait_lanes=600), guest=object(), lane=object(), game=FakeGame(),
        guards=object(), route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    seen = []

    def up(guest, lane, values):
        seen.append(values.wait_lanes)
        clock.now += 500
        return {}

    monkeypatch.setattr(winwishaccept.winwish, "up", up)
    monkeypatch.setattr(winwishaccept.winwish, "floppy_paths", lambda values: [])
    monkeypatch.setattr(controller, "_stage_media", lambda: None)
    before = controller.route_end

    controller._up()

    assert seen == [600]
    assert controller.route_end - before > 499
    assert controller.total_end - clock.now == pytest.approx(3300, abs=1)
    controller.args.wait_lanes = 0
    after = controller.route_end
    controller._up()
    assert controller.route_end == after


@pytest.mark.parametrize("seconds", (-1, 1801))
def test_wait_lanes_outside_zero_to_1800_stops_preflight_before_the_guest(tmp_path, seconds):
    args = _persist_args(tmp_path, wait_lanes=seconds)

    with pytest.raises(winwishaccept.AcceptanceStop, match="--wait-lanes"):
        winwishaccept.preflight(args, guest=object(), route_for=None)


def test_the_parser_takes_the_leg_repeatable_actions_and_wait_lanes():
    args = winwishaccept._parser().parse_args([
        "--title", "pool", "--manifest", "m", "--sha", SHA, "--holder", "h", "--mute-proof", "p",
        "--out", "o", "--leg", "persist", "--action", "heal", "--action", "spells",
        "--wait-lanes", "1800"])
    assert (args.leg, args.action, args.wait_lanes) == ("persist", ["heal", "spells"], 1800)
    default = winwishaccept._parser().parse_args([
        "--title", "pool", "--manifest", "m", "--sha", SHA, "--holder", "h", "--mute-proof", "p",
        "--out", "o"])
    assert (default.leg, default.action, default.wait_lanes) == ("mapping", None, 0)


def _persist_record(row, slot=0, *, name="A", hp=None, flip=None, items=None):
    raw = bytearray(row.record_size)
    if hp is not None:
        raw[row.hp.offset] = hp
    for at in flip or ():
        raw[at] ^= 0xFF
    return {"slot": slot, "name": name, "address": 1000 + slot, "raw": raw.hex(),
            "items": [[2000, node.hex()] for node in items or ()]}


def _verify_rig(tmp_path, monkeypatch, before, after, ran):
    from automap import amigaparty

    controller, _, _ = _persist_rig(tmp_path, monkeypatch, {})
    monkeypatch.undo()
    controller.summary["persistence"].update(persist_before=before, evidence=[])
    controller.summary["actions"] = {
        kind: {"status": "awaiting image review", "observed": context}
        for kind, context in ran.items()}
    controller.persist = {"letter": "F", "actions": list(ran)}
    controller._game_section = lambda: None
    controller._action_readback = lambda: after
    return controller, amigaparty.ROWS[controller.route.game_key]


def _heal_context(row, staged=15):
    return {"slot": 0, "member": "A", "staged": {"hp": staged},
            "baseline": [_persist_record(row, hp=staged)]}


def test_persist_reports_an_action_field_lost_over_the_reload_as_failed(tmp_path, monkeypatch):
    from automap import amigaparty

    row = amigaparty.ROWS["secret-of-the-silver-blades"]
    # Heal wrote 20 and the reload brought back the staged 15.
    controller, _ = _verify_rig(tmp_path, monkeypatch, [_persist_record(row, hp=20)],
                                [_persist_record(row, hp=15)], {"heal": _heal_context(row)})

    controller._verify_persist()

    result = controller.summary["persistence"]
    assert result["status"] == "failed"
    assert "hit points still hold the staged 15" in result["reason"]
    assert result["differing"]["in_action_spots"] == [f"A+0x{row.hp.offset:03X}"]


def test_persist_reports_another_changed_byte_as_unproven_with_its_offsets(tmp_path, monkeypatch):
    from automap import amigaparty

    row = amigaparty.ROWS["secret-of-the-silver-blades"]
    spots = {row.hp.offset, row.hp_max.offset, row.memorised.offset, row.hidden.offset,
             *(i for offset in row.pointers for i in range(offset, offset + 4))}
    if row.quickfight is not None:
        spots.add(row.quickfight.offset)
    other = next(i for i in range(1, row.record_size) if i not in spots)
    controller, _ = _verify_rig(
        tmp_path, monkeypatch, [_persist_record(row, hp=20)],
        [_persist_record(row, hp=20, flip=[other])], {"heal": _heal_context(row)})

    controller._verify_persist()

    result = controller.summary["persistence"]
    assert result["status"] == "unproven"
    assert f"A+0x{other:03X}" in result["reason"]
    assert result["differing"]["in_action_spots"] == []


def test_persist_accepts_a_reload_that_keeps_wish_s_value_and_changes_nothing_else(tmp_path, monkeypatch):
    from automap import amigaparty

    row = amigaparty.ROWS["secret-of-the-silver-blades"]
    pointer = row.pointers[0]
    after = _persist_record(row, hp=20)
    # A heap address is placed again by the reload and is not a difference.
    raw = bytearray.fromhex(after["raw"])
    raw[pointer:pointer + 4] = b"\x12\x34\x56\x78"
    after["raw"] = raw.hex()
    controller, _ = _verify_rig(tmp_path, monkeypatch, [_persist_record(row, hp=20)], [after],
                                {"heal": _heal_context(row)})

    controller._verify_persist()

    result = controller.summary["persistence"]
    assert result["status"] == "awaiting image review" and result["reason"] is None
    assert result["persist_after"] == [after]


def test_persist_checks_the_identify_byte_on_the_item_node(tmp_path, monkeypatch):
    from automap import amigaparty

    row = amigaparty.ROWS["secret-of-the-silver-blades"]

    def node(hidden):
        data = bytearray(row.items.size)
        data[row.hidden.offset] = hidden
        return data

    context = {"slot": 0, "member": "A", "staged": {"item_address": 2000, "hidden_staged": 7},
               "baseline": [_persist_record(row, items=[node(7)])]}
    # Wish cleared the hidden bits; the reload brings the staged byte back.
    controller, _ = _verify_rig(tmp_path, monkeypatch, [_persist_record(row, items=[node(0)])],
                                [_persist_record(row, items=[node(7)])], {"identify": context})

    controller._verify_persist()

    result = controller.summary["persistence"]
    assert result["status"] == "failed"
    assert result["differing"]["in_action_spots"] == [f"A item 0+0x{row.hidden.offset:02X}"]
    assert "identify: the item still holds the staged hidden byte" in result["reason"]


def _disk_rig(tmp_path, monkeypatch, reading, copied="working.adf"):
    controller, _, _ = _persist_rig(tmp_path, monkeypatch, {})
    monkeypatch.undo()
    controller.summary["persistence"].update(persist_after=[{"name": "Ann "}, {"name": "Bob"}])
    controller.route.amiga_title = SimpleNamespace(save_disk="df0", read_slot=lambda disk, letter: reading)
    controller.info["media"] = {"df0": {"guest_working_copy": copied}}
    monkeypatch.setattr("goldbox.amiga_adf.AmigaDisk.open", classmethod(lambda cls, path: object()))
    return controller


@pytest.mark.parametrize("reading,status", [
    ({"names": ["ANN", "bob"]}, "awaiting image review"),
    ({"names": ["ANN"]}, "unproven"),
    ({"missing": True, "sha256": None}, "failed"),
    ({"decode_error": "ValueError: x"}, "failed"),
])
def test_the_persist_slot_must_be_on_the_fetched_disk_and_list_the_same_names(
        tmp_path, monkeypatch, reading, status):
    controller = _disk_rig(tmp_path, monkeypatch, reading)
    controller.summary["persistence"]["status"] = "awaiting image review"

    controller._verify_disk_slot()

    result = controller.summary["persistence"]
    assert result["status"] == status
    assert result["disk_slot"] == reading
    assert (controller.summary["failure"] is None) == (status == "awaiting image review")


def test_a_working_disk_that_was_not_fetched_leaves_the_slot_unproven(tmp_path, monkeypatch):
    controller = _disk_rig(tmp_path, monkeypatch, {"names": []}, copied=None)
    controller.summary["persistence"]["status"] = "awaiting image review"

    controller._verify_disk_slot()

    assert controller.summary["persistence"]["status"] == "unproven"


def test_the_persist_leg_reload_compares_with_loaded_not_with_phases_it_skipped(tmp_path, monkeypatch):
    from tools.amiga import maproute

    controller, _ = _final_reload_rig(tmp_path, monkeypatch, "persist")
    # A title whose reload restarts the game; Silver Blades and Pools of Darkness are answered by screen.
    controller.route.title = "pool"
    phases = []
    monkeypatch.setattr(controller, "run_phase", lambda phase, namespace=None: (
        phases.append(phase), controller.checkpoints.update({"original_slot_reload.x": {"observed": {
            "fix": {"x": 1}, "geo_sha256": "g", "party": []}}}))[0])

    controller._final_reload()

    assert phases[0].steps[-1].expected == maproute.Expected(engine={"area": 16})

    controller, _ = _final_reload_rig(tmp_path / "m", monkeypatch, "mapping")
    monkeypatch.setattr(controller, "run_phase", lambda phase, namespace=None: (
        phases.append(phase), controller.checkpoints.update({"original_slot_reload.x": {"observed": {
            "fix": {"x": 1}, "geo_sha256": "g", "party": []}}}))[0])
    controller._final_reload()
    assert phases[1].steps[-1].expected.compare_to == "ssb_ruins_arrival"


def _final_reload_rig(tmp_path, monkeypatch, leg):
    from tools.amiga import maproute

    route = _route()
    expected = maproute.Expected(engine={"area": 16}, compare_to="ssb_ruins_arrival",
                                 relation="area_changed")
    reload = maproute.Phase("reload", "world", (maproute.Step(
        "key", "world", key="L", checkpoint="back", expected=expected),))
    route.phases = tuple(reload if phase.name == "reload" else phase for phase in route.phases)
    args = _persist_args(tmp_path, leg=leg)
    controller = winwishaccept.Controller(
        args, guest=object(), lane=object(), game=FakeGame(), guards=object(), route=route,
        zipped=tmp_path / "build.zip", info={"media": {}, "persist": {"letter": "F", "actions": []}},
        clock=FakeClock())
    controller.checkpoints["loaded"] = {"observed": {"fix": {"x": 1}, "geo_sha256": "g", "party": []}}
    return controller, route


def test_an_action_the_run_does_not_select_is_not_staged(tmp_path, monkeypatch):
    controller, game = _action_controller(tmp_path, monkeypatch)
    heal = controller.route.actions[0]
    identify = SimpleNamespace(kind="identify", enabled=True, selector="item", show=heal.show,
                               back=heal.back)
    controller.route.actions = (heal, identify)
    controller.summary["actions"]["identify"] = winwishaccept.row()
    controller.args.action = ["identify"]
    staged = []

    def stage(action):
        staged.append(action.kind)
        raise winwishaccept.AcceptanceStop("stop after staging")

    monkeypatch.setattr(controller, "_action_input", stage)

    with pytest.raises(winwishaccept.AcceptanceStop):
        controller.run_actions()

    assert staged == ["identify"]
    assert controller.summary["actions"]["heal"]["reason"] == "not selected by --action"


@pytest.mark.parametrize("wanted,message", [(["levelup"], "is not an action"),
                                            (["spells"], "is not enabled")])
def test_an_unknown_or_disabled_action_stops_the_persist_leg_before_a_lane(
        tmp_path, wanted, message):
    from tools.amiga import maproute

    route = maproute.route_for("pool", test_maproute._manifest("pool", tmp_path))
    heal = dataclasses.replace(route.actions[0], enabled=True)
    route = dataclasses.replace(route, actions=(
        heal, *(a for a in route.actions[1:] if a.kind != "levelup")), unresolved=())
    args = _persist_args(tmp_path, action=wanted)

    with pytest.raises(winwishaccept.AcceptanceStop, match=message):
        winwishaccept._check_persist(args, route)


def test_persist_letter_on_the_prepared_disk_stops_preflight_before_the_guest(tmp_path, monkeypatch):
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import maproute

    manifest = test_maproute._manifest("pool", tmp_path)
    for key, entry in manifest["disks"].items():
        disk = AmigaDisk.blank()
        if key == "save":
            for letter in "DEFGHIJ":
                disk.write_file(f"/savgam{letter}.dat", b"x")
        path = tmp_path / f"{key}.adf"
        disk.save(path)
        entry["path"], entry["sha256"] = str(path), winwishaccept.digest(path)
    args = _persist_args(tmp_path, title="pool", manifest=tmp_path / "prepare.json",
                         out=tmp_path / "out")
    args.manifest.write_text(json.dumps(manifest))
    monkeypatch.setattr(winwishaccept.winwish, "_mute_proof", lambda path: True)

    def route_for(title, manifest):
        route = maproute.route_for(title, manifest)
        heal = dataclasses.replace(route.actions[0], enabled=True,
                                   show=maproute.Phase("show", "world", ()),
                                   back=maproute.Phase("back", "world", ()))
        return dataclasses.replace(route, actions=(heal, *route.actions[1:]), unresolved=())

    with pytest.raises(winwishaccept.AcceptanceStop, match="every persist save letter"):
        winwishaccept.preflight(args, guest=object(), route_for=route_for)
    assert not (tmp_path / "out").exists()


def test_names_that_differ_on_the_disk_are_unproven_with_both_lists(tmp_path, monkeypatch):
    controller = _disk_rig(tmp_path, monkeypatch, {"names": ["ANN"]})
    controller.summary["persistence"]["status"] = "awaiting image review"

    controller._verify_disk_slot()

    result = controller.summary["persistence"]
    assert result["status"] == "unproven"
    assert "['ANN']" in result["reason"] and "['ANN', 'BOB']" in result["reason"]


def _original_reload_rig(tmp_path, monkeypatch, title, table):
    from tools.amiga import maproute

    route = _route()
    route.title = title
    controller, game, events = _persist_rig(tmp_path, monkeypatch, table, route=route)
    game.screen = "world"
    last = maproute.Phase("reload", "world", (maproute.Step(
        "key", "world", key="B", checkpoint="back", expected=maproute.Expected(engine={"area": 16})),))
    return controller, game, events, last


_SSB_ORIGINAL = {
    ("world", "E"): "camp", ("camp", "L"): "load_anyway", ("load_anyway", "Y"): "load_picker",
    ("load_picker", "B"): "loaded_menu", ("loaded_menu", "B"): "journal",
    ("treasure_bar", "E"): "treasure", ("treasure", "N"): "world",
}
_DARKNESS_ORIGINAL = {
    ("world", "E"): "camp", ("camp", "L"): "load_anyway", ("load_anyway", "Y"): "load_from",
    ("load_from", "P"): "load_picker", ("load_picker", "B"): "loaded_menu",
    ("loaded_menu", "B"): "world",
}


@pytest.mark.parametrize("asks,keys", [
    (True, ["E", "L", "Y", "B", "B", "JOURNAL", "E", "N"]),
    (False, ["E", "L", "B", "B", "JOURNAL", "E", "N"]),
])
def test_the_original_slot_reload_answers_silver_blades_by_screen(
        tmp_path, monkeypatch, asks, keys):
    table = _SSB_ORIGINAL if asks else {**_SSB_ORIGINAL, ("camp", "L"): "load_picker"}
    controller, game, events, last = _original_reload_rig(tmp_path, monkeypatch, "ssb", table)

    controller._reload_original_by_screen(last)

    assert game.keys == keys
    assert events == [("original_slot_reload.back", len(keys))]
    assert controller.action_commands == len(keys) - 1


@pytest.mark.parametrize("asks,keys", [
    (True, ["E", "L", "Y", "P", "B", "B"]),
    (False, ["E", "L", "P", "B", "B"]),
])
def test_the_original_slot_reload_answers_pools_of_darkness_by_screen(
        tmp_path, monkeypatch, asks, keys):
    table = _DARKNESS_ORIGINAL if asks else {**_DARKNESS_ORIGINAL, ("camp", "L"): "load_from"}
    controller, game, events, last = _original_reload_rig(tmp_path, monkeypatch, "darkness", table)

    controller._reload_original_by_screen(last)

    assert game.keys == keys
    assert events == [("original_slot_reload.back", len(keys))]


def test_an_unknown_screen_after_the_original_reload_s_camp_load_gets_no_key(tmp_path, monkeypatch):
    table = {**_SSB_ORIGINAL, ("camp", "L"): "mystery"}
    controller, game, events, last = _original_reload_rig(tmp_path, monkeypatch, "ssb", table)

    with pytest.raises(winwishaccept.AcceptanceStop, match="persist reload: the screen after L"):
        controller._reload_original_by_screen(last)

    assert game.keys == ["E", "L"] and events == []
    assert list(tmp_path.glob("game-*.raw.png"))


def test_the_persist_leg_final_reload_goes_by_screen_for_the_branched_titles(tmp_path, monkeypatch):
    controller, _ = _final_reload_rig(tmp_path, monkeypatch, "persist")
    called = []
    monkeypatch.setattr(controller, "_reload_original_by_screen", lambda phase: (
        called.append(phase), controller.checkpoints.update({"original_slot_reload.back": {
            "observed": {"fix": {"x": 1}, "geo_sha256": "g", "party": []}}}))[0])
    monkeypatch.setattr(controller, "run_phase", lambda *a, **k: pytest.fail("ran the phase"))

    controller._final_reload()

    assert len(called) == 1 and called[0].steps[-1].expected.compare_to is None


def test_a_guest_failure_event_carries_the_step_exit_code_and_command_length():
    error = winwishaccept.winwish.GuestError("x", step="stage put", exit_code=255,
                                             command_length=7)
    assert winwishaccept.guest_failure_fields(error) == {
        "step": "stage put", "exit_code": 255, "command_length": 7}
    assert winwishaccept.guest_failure_fields(ValueError("x")) == {}


def test_the_restart_answers_the_boot_pages_and_the_code_wheel_before_the_load(
        tmp_path, monkeypatch):
    # The restarted game shows Curse's code-wheel page again; without the title wait's
    # interstitials the reload stops with "title screen was not recognized".
    controller, events = _disconnect_controller(tmp_path, monkeypatch)
    controller.route.title = "curse"
    controller.guards = SimpleNamespace(rules={"curse_wheel": True})
    monkeypatch.setattr(controller, "_await", lambda state, **kwargs: events.append(
        ("await", state, [page[0] for page in kwargs.get("interstitials", ())])) or {})
    controller.lane.start = lambda *args, **kwargs: events.append("lane-start")

    result = controller.run_title()

    assert result["failure"] is None
    restart = events.index("lane-start")
    assert ("await", "title", ["curse_wheel"]) in events[restart:]
    assert events.index(("await", "title", ["curse_wheel"]), restart) < events.index(
        "reload", restart)


# ---- the continue page a camp LOAD can end on ----

def _continue_after_answer(game):
    game.keys.append("JOURNAL")
    game.screen = "continue"


def test_persist_reload_presses_return_on_the_continue_page_after_the_journal_answer(
        tmp_path, monkeypatch):
    table = {**_SSB_SCREENS, ("continue", "RET"): "treasure_bar"}
    controller, game, _ = _persist_rig(tmp_path, monkeypatch, table)
    monkeypatch.setattr(controller, "_answer_journal", lambda: _continue_after_answer(game))

    result = controller.run_persist()

    assert result["failure"] is None
    assert game.keys[6:] == ["L", "Y", "F", "B", "JOURNAL", "RET", "E", "N", "FINAL"]
    assert controller.action_commands <= controller.action_limit


def test_persist_reload_ends_on_the_world_bar_after_the_continue_page(tmp_path, monkeypatch):
    table = {**_SSB_SCREENS, ("continue", "RET"): "world"}
    controller, game, events = _persist_rig(tmp_path, monkeypatch, table)
    monkeypatch.setattr(controller, "_answer_journal", lambda: _continue_after_answer(game))

    assert controller.run_persist()["failure"] is None
    assert game.keys[6:] == ["L", "Y", "F", "B", "JOURNAL", "RET", "FINAL"]
    assert ("persist_reloaded", len(game.keys) - 1) in events


def test_a_continue_page_that_never_turns_is_pressed_a_bounded_number_of_times(tmp_path, monkeypatch):
    table = {**_SSB_SCREENS, ("continue", "RET"): "continue"}
    controller, game, _ = _persist_rig(tmp_path, monkeypatch, table)
    monkeypatch.setattr(controller, "_answer_journal", lambda: _continue_after_answer(game))

    result = controller.run_persist()

    assert game.keys.count("RET") == winwishaccept.PERSIST_CONTINUE_PAGES
    assert "still on a continue page" in result["failure"]


def test_the_original_slot_reload_presses_return_on_the_continue_page(tmp_path, monkeypatch):
    table = {**_SSB_ORIGINAL, ("continue", "RET"): "treasure_bar"}
    controller, game, events, last = _original_reload_rig(tmp_path, monkeypatch, "ssb", table)
    monkeypatch.setattr(controller, "_answer_journal", lambda: _continue_after_answer(game))

    controller._reload_original_by_screen(last)

    assert game.keys == ["E", "L", "Y", "B", "B", "JOURNAL", "RET", "E", "N"]
    assert events == [("original_slot_reload.back", 9)]


def test_pools_of_darkness_presses_return_on_a_continue_page_before_the_world_bar(tmp_path, monkeypatch):
    table = {**_DARKNESS_ORIGINAL, ("loaded_menu", "B"): "continue", ("continue", "RET"): "world"}
    controller, game, events, last = _original_reload_rig(tmp_path, monkeypatch, "darkness", table)

    controller._reload_original_by_screen(last)

    assert game.keys == ["E", "L", "Y", "P", "B", "B", "RET"]
    assert events == [("original_slot_reload.back", 7)]


def test_the_continue_guard_recognises_the_page_the_first_live_persist_run_stopped_on(tmp_path):
    # A frame from the player's own run (game-136.raw.png of the first live Silver Blades
    # persist run); it is not in the repository, so the test skips without it.
    frame = (pathlib.Path.home() / ".cache/wish/acceptance/WISH-359/persist/ssb/heal1/game-136.png")
    if not frame.is_file():
        pytest.skip("the first live persist run's frame is not on this machine")
    from tools.amiga import guardmaps, screens

    export = tmp_path / "export"
    export.mkdir()
    guard_dir = pathlib.Path(winwishaccept.__file__).parent
    assert guardmaps.main(["--maps", str(guard_dir), "export", "--title", "ssb", "--out", str(export)]) == 0
    guards = screens.PixelGuards(export / "guards.json")

    assert guards("continue", frame)
    assert not guards("world", frame) and not guards("treasure_bar", frame)


class _LaggyGame(_ScreenGame):
    """A game that keeps showing the old screen for `lag` grabs after the keys in `lagged`."""

    def __init__(self, table, lagged, lag, screen="title"):
        super().__init__(table, screen)
        self.lagged, self.lag, self.pending = lagged, lag, None

    def grab(self, state, raw, crop, timeout):
        if self.pending is not None:
            target, left = self.pending
            self.pending = (target, left - 1) if left > 1 else None
            if left <= 1:
                self.screen = target
        return super().grab(state, raw, crop, timeout)

    def press(self, holder, key, timeout):
        before = self.screen
        super().press(holder, key, timeout)
        if (before, key) in self.lagged and self.screen != before:
            self.pending, self.screen = (self.screen, self.lag), before


def test_a_stale_continue_frame_after_return_does_not_get_a_second_return(tmp_path, monkeypatch):
    table = {**_SSB_SCREENS, ("continue", "RET"): "treasure_bar"}
    controller, game, _ = _persist_rig(tmp_path, monkeypatch, table)
    laggy = _LaggyGame(table, {("continue", "RET")}, 2)
    controller.game = laggy
    monkeypatch.setattr(controller, "_answer_journal", lambda: _continue_after_answer(laggy))

    result = controller.run_persist()

    assert result["failure"] is None
    # The game redraws two grabs late; the unchanged frame in between is not a second page.
    assert laggy.keys[5:] == ["L", "Y", "F", "B", "JOURNAL", "RET", "E", "N"]


def test_every_key_of_the_worst_persist_reloads_fits_the_action_budget(tmp_path):
    from tools.amiga import maproute

    route = maproute.route_for("ssb", test_maproute._manifest("ssb", tmp_path))
    controller = winwishaccept.Controller(
        _persist_args(tmp_path), guest=object(), lane=object(), game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip",
        info={"media": {}, "persist": {"letter": "E", "actions": []}}, clock=FakeClock())
    pages = winwishaccept.PERSIST_CONTINUE_PAGES
    saved, rest = maproute.persist_phases(route, "E")
    # The camp save, then each reload with every continue page answered: L, Y, the slot, B,
    # E and N after the camp key, which the original-slot reload also presses.
    worst = (winwishaccept._phase_keys(saved) + winwishaccept._phase_keys(rest)
             + (6 + pages) + (1 + 6 + pages))

    assert worst <= controller.action_limit


def _opening_story_table(base):
    """Silver Blades' opening story after a load: nine pages, the treasure offer, three more.

    Each page is a different picture of the one `continue` screen, as the game types its text."""
    table = dict(base)
    for number in range(1, 9):
        table[(f"continue#{number}", "RET")] = f"continue#{number + 1}"
    table[("continue#9", "RET")] = "treasure_bar"
    table[("treasure", "N")] = "continue#10"
    table[("continue#10", "RET")] = "continue#11"
    table[("continue#11", "RET")] = "continue#12"
    table[("continue#12", "RET")] = "world"
    return table


def _story_guards(state, path):
    return path.read_bytes().decode().split("#")[0] == state


def test_persist_reload_answers_the_twelve_page_opening_story(tmp_path, monkeypatch):
    controller, game, _ = _persist_rig(tmp_path, monkeypatch, _opening_story_table(_SSB_SCREENS))
    controller.guards = _story_guards
    monkeypatch.setattr(controller, "_answer_journal", lambda: setattr(game, "screen", "continue#1"))

    result = controller.run_persist()

    assert result["failure"] is None
    assert game.keys.count("RET") == 12
    assert controller.action_commands <= controller.action_limit


def test_the_original_slot_reload_answers_the_twelve_page_opening_story(tmp_path, monkeypatch):
    controller, game, events, last = _original_reload_rig(
        tmp_path, monkeypatch, "ssb", _opening_story_table(_SSB_ORIGINAL))
    controller.guards = _story_guards
    monkeypatch.setattr(controller, "_answer_journal", lambda: setattr(game, "screen", "continue#1"))

    controller._reload_original_by_screen(last)

    assert game.keys.count("RET") == 12
    assert events == [("original_slot_reload.back", len(game.keys))]


def test_the_page_cap_counts_the_whole_camp_load_not_each_wait(tmp_path, monkeypatch):
    # Pages before and after the treasure offer share one cap of PERSIST_CONTINUE_PAGES.
    pages = winwishaccept.PERSIST_CONTINUE_PAGES
    table = _opening_story_table(_SSB_ORIGINAL)
    table[("continue#12", "RET")] = "continue#13"
    for number in range(13, pages + 3):
        table[(f"continue#{number}", "RET")] = f"continue#{number + 1}"
    controller, game, _, last = _original_reload_rig(tmp_path, monkeypatch, "ssb", table)
    controller.guards = _story_guards
    monkeypatch.setattr(controller, "_answer_journal", lambda: setattr(game, "screen", "continue#1"))

    with pytest.raises(winwishaccept.AcceptanceStop, match="still on a continue page"):
        controller._reload_original_by_screen(last)

    assert game.keys.count("RET") == pages


def _control_args(extra):
    args = winwishaccept._parser().parse_args([
        "--manifest", "m", "--sha", SHA, "--holder", "h", "--mute-proof", "p", "--out", "o",
        "--quickfight-control", *extra])
    args.deadline = 1500
    return args


@pytest.mark.parametrize("extra", [
    ["--title", "ssb", "--leg", "fight"],
    ["--title", "darkness", "--leg", "persist", "--action", "quickfight"],
    ["--title", "pool", "--leg", "persist", "--action", "quickfight"],
    ["--title", "ssb", "--leg", "persist", "--action", "heal"],
    ["--title", "ssb", "--leg", "persist", "--action", "quickfight", "--action", "heal"],
    ["--title", "curse", "--leg", "persist"]])
def test_quickfight_control_needs_the_persist_leg_curse_or_ssb_and_quickfight_alone(extra):
    with pytest.raises(winwishaccept.AcceptanceStop, match="--quickfight-control runs only"):
        winwishaccept.preflight(_control_args(extra), guest=object(), route_for=None)


def _quickfight_record(row, value, name="A"):
    raw = bytearray(row.record_size)
    raw[row.quickfight.offset] = value
    return {"slot": 0, "name": name, "address": 1000, "raw": raw.hex(), "items": []}


def test_quickfight_control_stages_one_and_never_clicks_quickfight_off(tmp_path, monkeypatch):
    from automap import amigaparty

    controller, _game = _action_controller(tmp_path, monkeypatch)
    controller.quickfight_control = True
    controller.route.actions[0].kind = "quickfight"
    controller.summary["actions"]["quickfight"] = controller.summary["actions"].pop("heal")
    row = amigaparty.ROWS[controller.route.game_key]
    staged = [_quickfight_record(row, 1)]
    monkeypatch.setattr(controller, "_action_input", lambda action: {
        "member": "A", "slot": 0, "before": [], "baseline": staged, "staged": {"quickfight": 1}})
    monkeypatch.setattr(controller, "_action_readback", lambda: staged)
    clicks = []
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args, **kwargs: (
        clicks.append(args[3]) if args[2] == "click" else None) or [])

    controller.run_actions()

    entry = controller.summary["actions"]["quickfight"]
    assert clicks == []
    assert entry["status"] == "unproven"
    assert entry["reason"] == "control run: Quickfight off not pressed"
    assert entry["observed"]["after"] == staged


def _control_rig(tmp_path, monkeypatch, *, camp=1, reloaded=1, disk=1, copied="working.adf"):
    from automap import amigaparty

    controller, _, _ = _persist_rig(tmp_path, monkeypatch, {})
    monkeypatch.undo()
    row = amigaparty.ROWS[controller.route.game_key]
    controller.quickfight_control = True
    controller.summary["quickfight_control"] = winwishaccept.row()
    controller.summary["actions"] = {"quickfight": {"status": "unproven", "observed": {"member": "Ann"}}}
    controller.summary["persistence"].update(
        persist_before=[_quickfight_record(row, camp, "ANN ")],
        persist_after=[_quickfight_record(row, reloaded, "ANN ")])
    controller.route.amiga_title = SimpleNamespace(save_disk="df0")
    controller.info["media"] = {"df0": {"guest_working_copy": copied}}
    saved = SimpleNamespace(characters=[
        SimpleNamespace(name="Ann", raw=bytes.fromhex(_quickfight_record(row, disk)["raw"]))])
    monkeypatch.setattr("goldbox.amiga_adf.AmigaDisk.open", classmethod(lambda cls, path: object()))
    monkeypatch.setattr("goldbox.amiga_savegame.read_slot", lambda disk_, letter: saved)
    return controller


def test_quickfight_control_passes_when_camp_disk_and_reload_read_one(tmp_path, monkeypatch):
    controller = _control_rig(tmp_path, monkeypatch)

    controller._verify_quickfight_control()

    assert controller.summary["quickfight_control"]["status"] == "passed"
    assert controller.summary["quickfight_control"]["observed"] == {"camp": 1, "disk": 1, "reloaded": 1}


def test_quickfight_control_fails_when_the_saved_slot_holds_zero(tmp_path, monkeypatch):
    controller = _control_rig(tmp_path, monkeypatch, disk=0, reloaded=0)

    controller._verify_quickfight_control()

    entry = controller.summary["quickfight_control"]
    assert entry["status"] == "failed"
    assert "cannot be counted" in entry["reason"]


def test_quickfight_control_unproven_without_a_fetched_disk_or_a_camp_one(tmp_path, monkeypatch):
    controller = _control_rig(tmp_path, monkeypatch, copied=None)
    controller._verify_quickfight_control()
    assert controller.summary["quickfight_control"]["status"] == "unproven"

    controller = _control_rig(tmp_path, monkeypatch, camp=0, disk=0)
    controller._verify_quickfight_control()
    assert controller.summary["quickfight_control"]["status"] == "unproven"


def test_a_run_without_the_control_option_has_no_control_row(tmp_path, monkeypatch):
    controller, _, _ = _persist_rig(tmp_path, monkeypatch, {})

    controller._verify_quickfight_control()

    assert "quickfight_control" not in controller.summary


def _pod_item_party(row, prefix_text, hidden=0x07):
    node = bytearray(row.items.size)
    node[:len(prefix_text)] = prefix_text
    node[0x36] = hidden
    return [{"slot": 0, "name": "A", "raw": bytes(row.record_size).hex(),
             "items": [[100, node.hex()]]}]


def test_pools_of_darkness_reload_ignores_item_bytes_the_save_does_not_write():
    from automap import amigaparty

    row = amigaparty.ROWS["pools-of-darkness"]
    named = _pod_item_party(row, b"Plate Mail +3 ")
    bare = _pod_item_party(row, b"")
    assert (winwishaccept.Controller._without_addresses(named, row)
            == winwishaccept.Controller._without_addresses(bare, row))
    changed = _pod_item_party(row, b"", hidden=0x05)
    assert (winwishaccept.Controller._without_addresses(bare, row)
            != winwishaccept.Controller._without_addresses(changed, row))
