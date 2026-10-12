"""The Wish/WinUAE acceptance controller, without a VM or game disks."""

from __future__ import annotations

import argparse
import base64
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
from tools.amiga import winuaesession, winwishaccept

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


def test_controller_executes_transition_before_indoor_stationary(tmp_path, monkeypatch):
    route = _route()
    ordered = (route.phases[0], route.phases[3], route.phases[1], route.phases[2],
               route.phases[4], route.phases[5])
    route.phases = ordered
    clock = FakeClock()
    lane = SimpleNamespace(stop=lambda *args: None)
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=lane, game=FakeGame(), guards=object(),
        route=route, zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=clock.sleep)
    events = []
    monkeypatch.setattr(controller, "_up", lambda: events.append("up"))
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_await", lambda *args, **kwargs: {})
    monkeypatch.setattr(controller, "run_phase", lambda phase: events.append(phase.name))
    monkeypatch.setattr(controller, "run_actions", lambda: None)
    monkeypatch.setattr(controller, "_cleanup", lambda: controller.summary["cleanup"].update(errors=[]))
    monkeypatch.setattr(winwishaccept.winwish, "stop_wish",
                        lambda *args: events.append("stop_wish"))
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: None)

    result = controller.run_title()

    assert result["failure"] is None
    assert events == ["up", "load", "transition", "stationary", "walk", "reload",
                      "stop_wish", "reopen_step"]


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
        (tmp_path / "guards-export" / "guards.json").write_text("{}") and 0))
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


@pytest.mark.parametrize("fault", ["slot", "action", "terminal", "deadline", "source"])
def test_discovery_rejects_wrong_prepared_route_before_guest(tmp_path, fault):
    args = _discovery_args(tmp_path)
    args.manifest.write_text('{"title":"ssb","substitute":{"letter":"A"},'
                             '"state_a":{"area":16,"x":3,"y":3,"facing":2}}')
    for key in ("df0", "df1"):
        (tmp_path / f"{key}.adf").write_bytes(key.encode())
    route = _discovery_route(tmp_path)
    if fault == "slot":
        route.loaded_slot = "A"
    elif fault == "action":
        route.actions = (SimpleNamespace(enabled=True),)
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
    monkeypatch.setattr(controller, "_up", lambda: (setattr(controller, "booted", True),
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
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Controls"])
    result = controller.run_discovery()
    pair = result["checkpoints"]["ssb_leave_terminal"]
    assert pathlib.Path(pair["wish"]).read_bytes() == b"wish"
    assert pathlib.Path(pair["wish_sidecar"]).is_file()
    assert pathlib.Path(pair["controls"]).read_text() == "Controls\n"
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
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Controls"])
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


@pytest.mark.parametrize("fault", ["none", "scene", "actions", "prefix", "guard_primary",
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
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda argv: (
        (tmp_path / "guards-export" / "guards.json").write_text("{}") and 0))
    rule = json.loads(json.dumps(winwishaccept.OPENING_FIRST_RULE))
    if fault == "scene":
        args.manifest.write_text(args.manifest.read_text().replace('"opening_scene":true',
                                                                  '"opening_scene":false'))
    elif fault == "actions":
        route.actions = (SimpleNamespace(enabled=True),)
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
    else:
        result = winwishaccept.preflight(args, guest=guest, route_for=lambda *args: route,
                                         driver_sha=SHA)
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
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda argv: (
        (tmp_path / "guards-export" / "guards.json").write_text("{}") and 0))
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
    monkeypatch.setattr(winwishaccept.guardmaps, "main", lambda argv: (
        (tmp_path / "guards-export" / "guards.json").write_text("{}") and 0))
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
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Controls"])
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
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Controls"])
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
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: ["Controls"])
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
        (tmp_path / "guards-export" / "guards.json").write_text("{}") and 0))
    monkeypatch.setattr(winwishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules={name: True for phase in route.phases[:3]
               for name in (phase.initial_state, *(s.state for s in phase.steps))}
        | {"continue": True, "title": True}))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="route has no measured guards for leave_town"):
        winwishaccept.preflight(args, guest=SimpleNamespace(gh=lambda *a: pytest.fail("guest")),
                                route_for=lambda *unused: route, driver_sha=SHA)
