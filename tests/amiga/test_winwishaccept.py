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
