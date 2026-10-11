"""The Wish/WinUAE acceptance controller, without a VM or game disks."""

from __future__ import annotations

import argparse
import pathlib
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from tools.amiga import winwishaccept

SHA = "0123456789abcdef0123456789abcdef01234567"


def _args(tmp_path):
    return argparse.Namespace(title="ssb", sha=SHA, holder="test-acw",
                              manifest=tmp_path / "prepare.json",
                              mute_proof=tmp_path / "mute.json", out=tmp_path,
                              deadline=3300)


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
                           amiga_title=SimpleNamespace(wait_limits={}, title_limit=30),
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

    def up():
        controller.booted = True
        game.holder = "test-acw"

    def section():
        controller.pipe_released = True

    def switch(enabled):
        controller.encounters_on = enabled
        calls.append(f"encounters-{enabled}")
        controller.encounters = SimpleNamespace(
            keys=lambda names: (game.keys.extend(names) or {"pressed": names}))

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
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: [])
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
    modes = iter((True, False, True, True))
    def controls(*args):
        enabled = next(modes)
        return [f"Button|{name}|{name}|enabled={enabled}" for name in names]
    monkeypatch.setattr(winwishaccept.winwish, "ui", controls)
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: 1)
    restarts = []
    monkeypatch.setattr(winwishaccept.winwish, "restart_wish",
                        lambda *args, **kwargs: restarts.append(kwargs))
    controller.flag_controls()
    assert [entry["features"] for entry in restarts] == [False, False, True]
    assert [entry["flag"] for entry in restarts] == [True, False, True]
    assert all(value["status"] == "awaiting image review"
               for value in controller.summary["flags"].values())
