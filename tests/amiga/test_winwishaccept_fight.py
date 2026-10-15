"""The Wish/WinUAE acceptance driver's fight leg, without a VM or game disks."""

from __future__ import annotations

import argparse
import json
import pathlib
from types import SimpleNamespace

import pytest

from automap import amigaparty
from tools.amiga import winwishaccept

SHA = "0123456789abcdef0123456789abcdef01234567"
GAME_KEY = "test-fight-title"
LISTING = ["Button|Heal party|heal|enabled={heal}", "Button|Save spells|store|enabled=False",
           "Button|Restore spells|restore|enabled=False", "Button|Identify|identify|enabled=False",
           "Button|Quickfight off|quickfight|enabled={quick}",
           "Button|Level up|card_0_level_up|enabled=False"]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.25
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ScriptGame:
    """A game whose frames are the named screens of `screens`, in turn, the last one repeated."""

    def __init__(self, screens=()):
        self.screens = list(screens)
        self.keys = []
        self.restores = []
        self.snapshots = []
        self.last_shot = {"source": "fake"}
        self._pipe = None

    def grab(self, state, raw, crop, timeout):
        screen = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        pathlib.Path(raw).write_bytes(b"raw")
        pathlib.Path(crop).write_text(screen)
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)

    def snapshot(self, name, holder):
        self.snapshots.append(name)

    def restore(self, name, holder):
        self.restores.append(name)


def _controller(tmp_path, *, media=(), info_media=None, game=None):
    route = SimpleNamespace(title="darkness", game_key=GAME_KEY, phases=(), actions=(),
                            media=tuple(media), mounted=(), unresolved=(), provenance={},
                            loaded_slot="B",
                            amiga_title=SimpleNamespace(wait_limits={}, title_limit=30,
                                                        interstitials=()))
    args = argparse.Namespace(title="darkness", sha=SHA, holder="test-fight",
                              manifest=tmp_path / "prepare.json", mute_proof=tmp_path / "mute.json",
                              out=tmp_path / "run", deadline=3300, leg="fight")
    clock = FakeClock()
    controller = winwishaccept.Controller(
        args, guest=object(), lane=object(), game=game or ScriptGame(["world"]),
        guards=lambda state, path: pathlib.Path(path).read_text() == state, route=route,
        zipped=tmp_path / "build.zip",
        info={"media": info_media or {}, "fight": {"survive": False, "place": None}},
        clock=clock, sleep=clock.sleep)
    return controller


@pytest.fixture
def fight_row(monkeypatch):
    def make(legal=frozenset()):
        row = SimpleNamespace(mode=0x5B12, combat_value=5, combat_legal=frozenset(legal))
        monkeypatch.setitem(amigaparty.ROWS, GAME_KEY, row)
        return row
    return make


def _greyed(controller, monkeypatch, *, heal=False, quick=False, after=None):
    """Fake the pipe and Wish around `_greyed_check`; returns the click log."""
    party = [{"slot": 0, "name": "IN RANGE", "raw": "00" * 8, "items": []}]
    readbacks = [party, after or party]
    clicks = []
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_capture", lambda state: {"raw": f"{state}.raw.png",
                                                               "crop": f"{state}.png"})
    monkeypatch.setattr(controller, "_read_mode", lambda: 5)
    monkeypatch.setattr(controller, "_action_readback", lambda: readbacks.pop(0))

    def checkpoint(name, expected, frame, reads=()):
        path = controller.out / f"controls-{name}.txt"
        path.write_text("\n".join(line.format(heal=heal, quick=quick) for line in LISTING) + "\n")
        controller.checkpoints[name] = {"controls": str(path), "reads": reads}

    monkeypatch.setattr(controller, "_checkpoint", checkpoint)

    def ui(guest, holder, action, names=(), **kwargs):
        clicks.append((action, names))
        raise RuntimeError("the control is disabled")

    monkeypatch.setattr(winwishaccept.winwish, "ui", ui)
    return clicks


MEMORY = SimpleNamespace(holder="test-fight", owner=lambda: {"name": "IN RANGE", "address": 0xC657C0})


def test_fight_greyed_check_stops_on_an_enabled_action_in_a_fight(tmp_path, monkeypatch, fight_row):
    fight_row()
    controller = _controller(tmp_path)
    clicks = _greyed(controller, monkeypatch, heal=True)
    with pytest.raises(winwishaccept.AcceptanceStop, match="enabled in a fight: Heal party"):
        controller._greyed_check(MEMORY)
    assert controller.summary["fight_greyed"]["status"] == "failed"
    assert clicks == []


def test_fight_greyed_check_accepts_a_combat_legal_action_enabled(tmp_path, monkeypatch, fight_row):
    fight_row({"clear-quickfight"})
    controller = _controller(tmp_path)
    clicks = _greyed(controller, monkeypatch, quick=True)
    controller._greyed_check(MEMORY)
    greyed = controller.summary["fight_greyed"]
    assert greyed["status"] == "awaiting image review", greyed["reason"]
    assert greyed["observed"]["enabled"]["Quickfight off"] is True
    # One click on a greyed button, its error kept, never taken as an action.
    assert clicks == [("click", ("Heal party",))]
    assert "disabled" in greyed["observed"]["click"]["error"]
    assert controller.action_commands == 0


def test_a_greyed_click_that_changes_a_party_byte_fails_the_row(tmp_path, monkeypatch, fight_row):
    fight_row()
    controller = _controller(tmp_path)
    changed = [{"slot": 0, "name": "IN RANGE", "raw": "00" * 5 + "5f" + "00" * 2, "items": []}]
    _greyed(controller, monkeypatch, after=changed)
    controller._greyed_check(MEMORY)
    greyed = controller.summary["fight_greyed"]
    assert greyed["status"] == "failed"
    assert "IN RANGE +0x05" in greyed["reason"]


def test_fight_records_the_mode_on_each_new_screen(tmp_path, monkeypatch):
    game = ScriptGame(["world", "world", "encounter", "combat_bar"])
    controller = _controller(tmp_path, game=game)
    controller.greyed_done = True
    modes = iter([4, 4, 5, 5])
    monkeypatch.setattr(amigaparty, "mode", lambda target: next(modes))
    memory = SimpleNamespace(holder="test-fight", _target=object(), target=lambda: object())
    screens = winwishaccept._fight_screens(controller, winwishaccept.fight_plan("darkness"), memory)
    seen = [screens.look("fight")[0] for _ in range(3)]
    screens.press("A", "encounter")
    assert screens.look("fight")[0] == ["combat_bar"]
    screens.press("Q", "combat_bar")
    assert seen == [["world"], ["world"], ["encounter"]]
    table = [(entry["screen"], entry.get("key"), entry["mode"])
             for entry in controller.summary["fight"]["modes"]]
    assert table == [("world", None, 4), ("encounter", "A", 4), ("combat_bar", "Q", 5)]
    assert game.keys == ["A", "Q"]
    assert controller.action_commands == 2


def test_the_first_key_on_a_command_bar_waits_for_the_greyed_check(tmp_path, monkeypatch):
    game = ScriptGame(["combat_bar"])
    controller = _controller(tmp_path, game=game)
    order = []
    monkeypatch.setattr(controller, "_fight_bar", lambda memory: order.append("check"))
    monkeypatch.setattr(game, "press", lambda holder, key, timeout: order.append(key))
    memory = SimpleNamespace(holder="test-fight", _target=None)
    screens = winwishaccept._fight_screens(controller, winwishaccept.fight_plan("darkness"), memory)
    screens.press("Q", "combat_bar")
    controller.greyed_done = True
    screens.press("Q", "combat_bar")
    assert order == ["check", "Q", "Q"]


def _media(tmp_path):
    return [SimpleNamespace(key="disk3", path=tmp_path / "disk3.adf", sha256="a" * 64)]


@pytest.mark.parametrize("fetched,status", [("a" * 64, "passed"), ("b" * 64, "failed"),
                                            (None, "unproven")])
def test_fight_leg_rejects_a_working_disk_that_changed(tmp_path, fetched, status):
    entry = {} if fetched is None else {"guest_working_sha256": fetched}
    controller = _controller(tmp_path, media=_media(tmp_path), info_media={"disk3": entry})
    controller._verify_no_write()
    result = controller.summary["fight_no_write"]
    assert result["status"] == status
    assert result["observed"]["disk3"] == {"staged": "a" * 64, "fetched": fetched}
    assert (controller.summary["failure"] is not None) == (status == "failed")


@pytest.mark.parametrize("leg", ["mapping", "persist", "reconnect"])
def test_a_fight_specimen_never_passes_the_mapping_or_persist_leg(tmp_path, leg):
    args = argparse.Namespace(title="ssb", sha=SHA, holder="h", manifest=tmp_path / "prepare.json",
                              mute_proof=tmp_path / "mute.json", out=tmp_path, deadline=3300,
                              leg=leg, action=None)
    args.manifest.write_text(json.dumps({"title": "ssb", "fight": {"load": "D"}}))
    with pytest.raises(winwishaccept.AcceptanceStop, match="runs only with --leg fight"):
        winwishaccept.preflight(args, guest=object(), driver_sha=SHA,
                                route_for=lambda *a: pytest.fail("route read for a fight stage"))


def _curse_route(slot="B", unresolved=()):
    load = SimpleNamespace(name="load", initial_state="title", steps=(), ready=True, reason=None)
    other = SimpleNamespace(name="walk", initial_state="world", steps=(), ready=False,
                            reason="The walk is not measured.")
    return SimpleNamespace(title="curse", loaded_slot=slot, phases=(load, other),
                           unresolved=("Curse needs the registered Yulash slot C.",
                                       "The walk is not measured.", *unresolved))


def _curse_manifest(**changes):
    pin = winwishaccept.FIGHT_PINS["curse"]
    fight = {"source": {"sha256": pin["source_sha256"]}, "load": "B", "place": dict(pin["place"]),
             "route": [1, 2]}
    fight.update(changes)
    return {"title": "curse", "state_a": dict(pin["place"]), "fight": fight}


def test_the_fight_leg_takes_the_pinned_specimen_past_the_route_gap(tmp_path):
    found = winwishaccept._check_fight(_curse_route(), _curse_manifest())
    assert found["place"] == winwishaccept.FIGHT_PINS["curse"]["place"]


@pytest.mark.parametrize("changes,match", [({"source": {"sha256": "c" * 64}}, "pinned source"),
                                           ({"load": "D"}, "another slot"),
                                           ({"route": []}, "no walk to the tavern")])
def test_the_fight_leg_stops_on_a_specimen_other_than_the_pin(tmp_path, changes, match):
    with pytest.raises(winwishaccept.AcceptanceStop, match=match):
        winwishaccept._check_fight(_curse_route(), _curse_manifest(**changes))


def test_the_pin_does_not_excuse_another_unresolved_reason(tmp_path):
    with pytest.raises(winwishaccept.AcceptanceStop, match="route incomplete: The load"):
        winwishaccept._check_fight(_curse_route(unresolved=("The load is wrong.",)),
                                   _curse_manifest())


def test_pool_fights_only_from_the_routes_own_specimen():
    route = SimpleNamespace(title="pool", unresolved=("Pool needs the registered outdoor source.",))
    with pytest.raises(winwishaccept.AcceptanceStop, match="route's own outdoor specimen"):
        winwishaccept._fight_specimen("pool", {}, route)


def _ssb_stage(tmp_path, source_sha=None):
    source = tmp_path / "source.adf"
    source.write_bytes(b"source disk")
    sha = winwishaccept.digest(source)
    manifest = {"fight": {"staged": {"4C2D": {"before": 0, "after": 1}},
                          "source": {"path": str(source), "sha256": source_sha or sha}}}
    route = SimpleNamespace(media=(SimpleNamespace(key="df0", path=tmp_path / "df0.adf"),),
                            mounted=("df0",), loaded_slot="D")
    return manifest, route


@pytest.mark.parametrize("gate,source_sha,match", [(0, None, "reads \\$4C2D = 0"),
                                                   (1, "d" * 64, "source disk")])
def test_the_silver_blades_stage_must_read_back_its_gate_and_source(tmp_path, monkeypatch, gate,
                                                                     source_sha, match):
    manifest, route = _ssb_stage(tmp_path, source_sha)
    monkeypatch.setattr(winwishaccept, "_staged_gate", lambda path, letter: gate)
    with pytest.raises(winwishaccept.AcceptanceStop, match=match):
        winwishaccept._check_fight_stage("ssb", manifest, route)


def test_the_silver_blades_stage_records_its_gate(tmp_path, monkeypatch):
    manifest, route = _ssb_stage(tmp_path)
    monkeypatch.setattr(winwishaccept, "_staged_gate", lambda path, letter: 1)
    assert winwishaccept._check_fight_stage("ssb", manifest, route)["value"] == 1


class WalkScreens:
    def __init__(self, looks):
        self.looks = list(looks)
        self.keys = []

    def wait(self, states, limit, past=()):
        return "world"

    def look(self, label):
        state = self.looks.pop(0)
        return ([state] if state else []), pathlib.Path(f"{label}.png")

    def press(self, key, on):
        self.keys.append((on, key))


def test_the_walk_turns_after_a_wall_answers_its_pages_and_stops_on_an_encounter(tmp_path,
                                                                                 monkeypatch):
    game = ScriptGame(["world"])
    controller = _controller(tmp_path, game=game)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    fixes = iter([(4, 7, 1), (4, 7, 1), (4, 7, 1), (4, 7, 0), (4, 7, 0)])
    memory = SimpleNamespace(fix=lambda: next(fixes))
    screens = WalkScreens(["world", "world", "continue", "encounter"])
    plan = winwishaccept.fight_plan("darkness")
    walked = controller._walk_to_fight(plan, screens, memory)
    assert screens.keys == [("world", "NP8"), ("world", "NP4"), ("world", "NP8"),
                            ("continue", "RET")]
    assert walked["met"] == "encounter"
    assert game.snapshots == [winwishaccept.FIGHT_WALK_SNAPSHOT] and game.restores == []


def test_the_walk_restores_on_a_screen_it_does_not_answer_and_then_stops(tmp_path, monkeypatch):
    game = ScriptGame(["world"])
    controller = _controller(tmp_path, game=game)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    memory = SimpleNamespace(fix=lambda: (1, 1, 0))
    screens = WalkScreens(["camp"] * 3)
    plan = winwishaccept.fight_plan("darkness")
    with pytest.raises(winwishaccept.AcceptanceStop, match="does not answer"):
        controller._walk_to_fight(plan, screens, memory)
    assert game.restores == [winwishaccept.FIGHT_WALK_SNAPSHOT] * winwishaccept.FIGHT_RESTORES
    assert [key for _on, key in screens.keys] == ["NP8", "NP4", "NP4"]


def test_the_fight_load_expects_the_specimens_own_square():
    from tools.amiga import maproute

    load = maproute._load("darkness", "B")
    route = SimpleNamespace(phases=(load,))
    place = winwishaccept.FIGHT_PINS["darkness"]["place"]
    phase = winwishaccept._fight_load(route, place)
    loaded = next(step for step in phase.steps if step.checkpoint == "loaded")
    assert dict(loaded.expected.engine) == {"x": 4, "y": 7, "facing": 1}
    assert [s.key for s in phase.steps] == [s.key for s in load.steps]
    assert winwishaccept._fight_load(route, None) is load


def test_each_fight_plan_names_only_states_its_title_guards():
    for title, guards in (("pool", "guards_pool.json"), ("darkness", "guards_darkness.json")):
        plan = winwishaccept.fight_plan(title)
        path = pathlib.Path(winwishaccept.__file__).with_name(guards)
        have = set(json.loads(path.read_text())["guards"])
        assert plan.states() <= have, plan.states() - have
        assert plan.allowed["world"] == frozenset({"NP8", "NP4"})
