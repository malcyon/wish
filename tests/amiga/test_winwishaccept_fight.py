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


@pytest.fixture(autouse=True)
def _no_wish_log_errors(monkeypatch):
    monkeypatch.setattr(winwishaccept.winwish, "wish_log_errors", lambda guest, holder: [])


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


def _controller(tmp_path, *, media=(), info_media=None, game=None, **flags):
    route = SimpleNamespace(title="darkness", game_key=GAME_KEY, phases=(), actions=(),
                            media=tuple(media), mounted=(), unresolved=(), provenance={},
                            loaded_slot="B",
                            amiga_title=SimpleNamespace(wait_limits={}, title_limit=30,
                                                        interstitials=(), options=()))
    args = argparse.Namespace(title="darkness", sha=SHA, holder="test-fight",
                              manifest=tmp_path / "prepare.json", mute_proof=tmp_path / "mute.json",
                              out=tmp_path / "run", deadline=3300, leg="fight", **flags)
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
    def make(legal=frozenset(), **extra):
        row = SimpleNamespace(mode=0x5B12, combat_value=5, combat_legal=frozenset(legal), **extra)
        monkeypatch.setitem(amigaparty.ROWS, GAME_KEY, row)
        return row
    return make


def _greyed(controller, monkeypatch, *, heal=False, quick=False, after=None, click="disabled",
            party=None):
    """Fake the pipe and Wish around `_greyed_check`; returns the click log."""
    party = party or [{"slot": 0, "name": "IN RANGE", "raw": "00" * 8, "items": []}]
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
        if click == "disabled":
            raise winwishaccept.winwish.ControlDisabled(f"fail {names[0]} is disabled", names[0])
        if click == "missing":
            raise winwishaccept.winwish.WinwishError(f"no control named {names[0]}")
        return ["clicked"]

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
    # One click on a greyed button, which the click layer answers as disabled; never an action.
    assert clicks == [("click", ("Heal party",))]
    assert greyed["observed"]["click"]["disabled"] == "Heal party"
    assert controller.action_commands == 0


@pytest.mark.parametrize("click,status,reason", [
    ("missing", "unproven", "found no greyed button: WinwishError: no control named Heal party"),
    ("reply", "failed", "was carried out, so the button was enabled")])
def test_only_the_disabled_answer_proves_the_clicked_button_greyed(tmp_path, monkeypatch,
                                                                    fight_row, click, status,
                                                                    reason):
    fight_row()
    controller = _controller(tmp_path)
    _greyed(controller, monkeypatch, click=click)
    controller._greyed_check(MEMORY)
    greyed = controller.summary["fight_greyed"]
    assert greyed["status"] == status
    assert reason in greyed["reason"]


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


@pytest.mark.parametrize("looks", [[None], ["world", None]])
def test_the_walk_stops_at_once_on_an_unrecognized_screen_or_a_failed_grab(tmp_path, monkeypatch,
                                                                         looks):
    game = ScriptGame(["world"])
    controller = _controller(tmp_path, game=game)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    memory = SimpleNamespace(fix=lambda: (1, 1, 0))
    # settled() looks again for a while before it gives up on a frame no guard knows.
    screens = WalkScreens([*looks, *[None] * 40])
    plan = winwishaccept.fight_plan("darkness")
    with pytest.raises(winwishaccept.AcceptanceStop, match="no recognized screen; kept walk.png"):
        controller._walk_to_fight(plan, screens, memory)
    assert game.restores == []
    assert len(screens.keys) == len(looks)


def test_no_fight_plan_allows_a_save_or_camp_key():
    saving = {"camp", "camp_save_picker", "save_picker", "exit_game", "load_picker", "title",
              "party_menu", "loaded_menu"}
    for title in ("pool", "curse", "ssb", "darkness"):
        plan = winwishaccept.fight_plan(title)
        assert set(plan.allowed) <= plan.named(), (title, set(plan.allowed) - plan.named())
        assert not saving & set(plan.allowed), (title, saving & set(plan.allowed))
        assert plan.allowed["world"] <= {"NP2", "NP4", "NP6", "NP8"}, (title, plan.allowed["world"])


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


def test_the_darkness_pin_loads_onto_the_overland_where_the_square_is_zero(tmp_path):
    from tools.amiga import maproute

    pin = winwishaccept.FIGHT_PINS["darkness"]
    manifest = {"state_a": pin["place"],
                "substitute": {"sha256": pin["substitute_sha256"], "letter": "D"}}
    route = SimpleNamespace(title="darkness", loaded_slot="B", phases=(maproute._load("darkness", "B"),))
    specimen = winwishaccept._fight_specimen("darkness", manifest, route)
    assert specimen["loaded"] == {"world_map": True}
    phase = winwishaccept._fight_load(route, specimen["place"], specimen["loaded"])
    loaded = next(step for step in phase.steps if step.checkpoint == "loaded")
    assert dict(loaded.expected.engine) == {"world_map": True}
    controller = _controller(tmp_path)
    overland = {"fix": {"x": 0, "y": 0, "facing": None, "outdoors": False, "world_map": True}}
    assert controller._compare_checkpoint("loaded", loaded.expected, overland)["status"] == (
        "awaiting image review")
    indoors = {"fix": {"x": 4, "y": 7, "facing": 1, "outdoors": False, "world_map": False}}
    assert controller._compare_checkpoint("loaded", loaded.expected, indoors)["status"] == "failed"


def test_only_darkness_pins_a_load_other_than_its_square():
    assert [t for t, pin in winwishaccept.FIGHT_PINS.items() if "loaded" in pin] == ["darkness"]


def test_pool_answers_the_short_treasure_bar_as_a_second_treasure_guard(tmp_path):
    plan = winwishaccept.fight_plan("pool")
    assert plan.extra_guards["treasure"] == [{
        "box": [54, 418, 460, 432],
        "sha256": "772c3ec8bfe073937ddeaec782ebcf86f68a5dbfe4a822583de16176ed61721b"}]
    assert plan.rules.answers["treasure"] == "E"
    exported = tmp_path / "guards.json"
    base = pathlib.Path(winwishaccept.__file__).with_name("guards_pool.json")
    exported.write_text(json.dumps(json.loads(base.read_text())["guards"]))
    long_bar = json.loads(exported.read_text())["treasure"]
    winwishaccept._merge_guards(exported, plan.extra_guards)
    merged = json.loads(exported.read_text())["treasure"]
    assert merged == [*(long_bar if isinstance(long_bar, list) else [long_bar]),
                      *plan.extra_guards["treasure"]]
    assert all(not winwishaccept.fight_plan(t).extra_guards.get("treasure")
               for t in ("darkness",))


def test_each_fight_plan_names_only_states_its_title_guards():
    for title, guards in (("pool", "guards_pool.json"), ("darkness", "guards_darkness.json")):
        plan = winwishaccept.fight_plan(title)
        path = pathlib.Path(winwishaccept.__file__).with_name(guards)
        have = set(json.loads(path.read_text())["guards"])
        assert plan.states() <= have, plan.states() - have
        assert plan.allowed["world"] == frozenset({"NP8", "NP4"})


# --- the clear-quickfight edge, the dip check and Quickfight off in a fight -----------------

def _args_for(tmp_path, **flags):
    base = dict(title="darkness", sha=SHA, holder="h", manifest=tmp_path / "prepare.json",
                mute_proof=tmp_path / "mute.json", out=tmp_path, deadline=3300, leg="fight",
                action=None)
    base.update(flags)
    return argparse.Namespace(**base)


@pytest.mark.parametrize("flags,match", [
    ({"leg": "mapping", "watch": True}, "--watch needs --leg fight"),
    ({"leg": "persist", "press_quickfight_off": True}, "--press-quickfight-off needs --leg fight"),
    ({"watch_dip": True, "title": "curse"}, "--watch-dip needs --watch"),
    ({"watch": True, "watch_dip": True, "title": "ssb"}, "--watch-dip runs only on Curse"),
    ({"press_quickfight_off": True, "title": "curse"}, "--press-quickfight-off runs only on Pools")])
def test_watch_needs_the_fight_leg_and_dip_and_press_need_their_title(tmp_path, flags, match):
    args = _args_for(tmp_path, **flags)
    with pytest.raises(winwishaccept.AcceptanceStop, match=match):
        winwishaccept.preflight(args, guest=object(), driver_sha=SHA,
                                route_for=lambda *a: pytest.fail("route read for a bad flag"))


@pytest.mark.parametrize("watch", [False, True])
def test_watch_seeds_clear_quickfight_into_up(tmp_path, monkeypatch, watch):
    controller = _controller(tmp_path, watch=watch)
    seen = []
    monkeypatch.setattr(winwishaccept.winwish, "up",
                        lambda guest, lane, args: seen.append(args.clear_quickfight) or {})
    controller._up()
    assert seen == [watch]


def _members(*rows):
    return [list(row) for row in rows]


class World(ScriptGame):
    """The game at CONTINUE BATTLE: members are [control, quickfight, other] bytes. A queued key
    lands when the driver has slept past its lead; Wish clears QUICK only if the Automapper is
    showing then."""

    def __init__(self, members, *, wish_clears=True, game_clears=False, companions_cleared=False,
                 land_mode=6, land_screen="party_won", restore_mode=5, restore_shift=False,
                 other_changes=False, award=False):
        super().__init__(["world"])
        self.members = members
        self.options = dict(wish_clears=wish_clears, game_clears=game_clears,
                            companions_cleared=companions_cleared, land_mode=land_mode,
                            land_screen=land_screen, restore_mode=restore_mode,
                            restore_shift=restore_shift, other_changes=other_changes,
                            award=award)
        self.tab, self.mode, self.screen = "editor", 5, "continue_battle"
        self.pending = None
        self.events = []
        self.saved = None

    def schedule_key(self, holder, key, lead_frames, timeout):
        self.pending = key
        self.events.append(("key", key, self.tab))
        return "ok"

    def land(self):
        if self.pending is None:
            return
        self.pending = None
        opts = self.options
        self.mode, self.screen = opts["land_mode"], opts["land_screen"]
        wish = self.tab == "map"
        if opts["award"]:
            # What the game writes itself (experience, fight teardown) lands in both branches.
            for member in self.members:
                member[2] += 1
        for member in self.members:
            if member[1] == 1 and (
                    (wish and opts["wish_clears"] and (member[0] == 0 or opts["companions_cleared"]))
                    or (not wish and opts["game_clears"] and member[0] == 0)):
                member[1] = 0
        if wish and opts["other_changes"]:
            self.members[0][2] ^= 1

    def snapshot(self, name, holder):
        super().snapshot(name, holder)
        self.saved = [list(member) for member in self.members]
        self.events.append(("snapshot", name))

    def restore(self, name, holder):
        super().restore(name, holder)
        self.members = [list(member) for member in self.saved]
        self.mode, self.screen = self.options["restore_mode"], "continue_battle"
        if self.options["restore_shift"]:
            self.members[0][2] ^= 1
        self.events.append(("restore", name))

    def readback(self):
        return [{"slot": at, "name": f"M{at}", "address": 0x1000 + 0x100 * at,
                 "raw": bytes(member).hex(), "items": []} for at, member in enumerate(self.members)]


def _edge_row(fight_row):
    return fight_row(control=amigaparty.Spot(0, 1, 0x80), quickfight=amigaparty.Spot(1),
                     after_fight_value=6)


def _edge(tmp_path, monkeypatch, fight_row, members, **options):
    """A controller over a `World`, with the screens, tabs and reads faked around it."""
    _edge_row(fight_row)
    world = World(members, **options)
    clock = FakeClock()
    controller = _controller(tmp_path, game=world, watch=True)
    monkeypatch.setattr(controller, "_game_section",
                        lambda: (setattr(world, "tab", "editor"), world.events.append(("tab", "editor"))))
    monkeypatch.setattr(controller, "_map_section",
                        lambda: (setattr(world, "tab", "map"), world.events.append(("tab", "map"))))

    def await_(state, limit=90, interstitials=()):
        if world.screen != state:
            raise winwishaccept.AcceptanceStop(f"{state} screen was not recognized; last {world.screen}")
        return {"raw": f"{state}.raw.png"}

    monkeypatch.setattr(controller, "_await", await_)
    monkeypatch.setattr(controller, "_read_mode", lambda: world.mode)
    monkeypatch.setattr(controller, "_action_readback", world.readback)
    monkeypatch.setattr(controller, "_lap", lambda timings: (lambda name: None))
    monkeypatch.setattr(controller, "_wish_pair", lambda name, lap: (
        pathlib.Path(f"wish-{name}.png"), pathlib.Path(f"controls-{name}.txt")))

    def sleep(seconds):
        clock.sleep(seconds)
        if seconds >= 30:
            world.land()

    controller.sleep = sleep
    controller.clock = clock
    return controller, world


ONE_QUICK = _members((0, 1, 7))


def test_edge_is_the_n_on_continue_battle_scheduled_with_the_automapper_showing(
        tmp_path, monkeypatch, fight_row):
    controller, world = _edge(tmp_path, monkeypatch, fight_row, _members((0, 1, 7), (0x80, 1, 7)))
    screens = winwishaccept._fight_screens(controller, winwishaccept.fight_plan("darkness"),
                                           SimpleNamespace(holder="h", _target=None))
    screens.press("N", "continue_battle")
    sequence = [event for event in world.events if event[0] != "snapshot"]
    assert sequence == [("tab", "editor"), ("key", "N", "editor"), ("restore", "fight_edge"),
                        ("key", "N", "editor"), ("tab", "map"), ("tab", "editor")]
    # The second key is queued on the editor tab and the Automapper shown before it lands.
    assert world.snapshots == ["fight_edge"]
    assert world.keys == []
    assert controller.action_commands == 2
    assert screens.events == [{"from": "continue_battle", "key": "N"}]
    assert controller.edge_done


@pytest.mark.parametrize("options,status,reason", [
    ({}, "awaiting image review", None),
    ({"game_clears": True}, "failed", "the game itself cleared QUICK on M0")])
def test_watch_control_keeps_the_editor_tab_and_fails_on_a_cleared_byte(
        tmp_path, monkeypatch, fight_row, options, status, reason):
    controller, world = _edge(tmp_path, monkeypatch, fight_row, _members((0, 1, 7)), **options)
    controller._watch_edge("N")
    control = controller.summary["watch_control_b"]
    assert control["status"] == status and control["reason"] == reason
    assert world.events[1:3] == [("snapshot", "fight_edge"), ("key", "N", "editor")]


@pytest.mark.parametrize("row_name", ["watch_control_b", "watch_a"])
def test_watch_branches_require_mode_6_on_party_won(tmp_path, monkeypatch, fight_row, row_name):
    controller, _world = _edge(tmp_path, monkeypatch, fight_row, _members((0, 1, 7)), land_mode=5)
    controller._watch_edge("N")
    result = controller.summary[row_name]
    assert result["status"] == "failed" and "the mode reads 5, not 6" in result["reason"]


@pytest.mark.parametrize("options,reason", [
    ({}, None),
    ({"award": True}, None),
    ({"award": True, "other_changes": True}, "bytes other than QUICK changed: M0 +0x02"),
    ({"wish_clears": False}, "QUICK still set on M0"),
    ({"companions_cleared": True}, "a companion's QUICK byte changed on M1"),
    ({"other_changes": True}, "bytes other than QUICK changed: M0 +0x02")])
def test_watch_a_requires_the_set_cleared_and_companions_kept(
        tmp_path, monkeypatch, fight_row, options, reason):
    controller, _world = _edge(tmp_path, monkeypatch, fight_row,
                               _members((0, 1, 7), (0x80, 1, 7)), **options)
    controller._watch_edge("N")
    result = controller.summary["watch_a"]
    assert result["reason"] == reason
    assert result["status"] == ("failed" if reason else "awaiting image review")
    if not reason:
        assert result["evidence"][:2] == ["wish-watch_a.png", "controls-watch_a.txt"]


@pytest.mark.parametrize("options", [{"restore_mode": 6}, {"restore_shift": True}])
def test_watch_restore_mismatch_leaves_both_rows_unproven(tmp_path, monkeypatch, fight_row, options):
    controller, world = _edge(tmp_path, monkeypatch, fight_row, _members((0, 1, 7)), **options)
    with pytest.raises(winwishaccept.AcceptanceStop, match="fight_edge restore"):
        controller._watch_edge("N")
    assert [controller.summary[name]["status"] for name in ("watch_control_b", "watch_a")] == [
        "unproven", "unproven"]
    assert [event for event in world.events if event[0] == "key"] == [("key", "N", "editor")]


def test_an_unguarded_page_after_n_stops_without_a_key(tmp_path, monkeypatch, fight_row):
    controller, world = _edge(tmp_path, monkeypatch, fight_row, _members((0, 1, 7)),
                              land_screen="camp")
    with pytest.raises(winwishaccept.AcceptanceStop, match="party_won screen was not recognized"):
        controller._watch_edge("N")
    assert [event for event in world.events if event[0] == "key"] == [("key", "N", "editor")]
    assert world.keys == [] and "restore" not in [event[0] for event in world.events]


def test_an_edge_with_nobody_on_quick_sends_the_key_the_ordinary_way(tmp_path, monkeypatch, fight_row):
    controller, world = _edge(tmp_path, monkeypatch, fight_row, _members((0, 0, 7), (0x80, 1, 7)))
    assert controller._watch_edge("N") is False
    assert controller.summary["watch_a"]["status"] == "unproven"
    assert [event for event in world.events if event[0] == "key"] == []


def _dip_party(row_):
    member = lambda slot, control: SimpleNamespace(  # noqa: E731
        slot=slot, name=f"M{slot}", address=0x1000 + 0x100 * slot,
        raw=bytes([control, 0, 0]))
    return [member(0, 0x80), member(1, 0)]


class DipTarget:
    def __init__(self, party):
        self.party, self.writes = party, []

    def write(self, address, data):
        self.writes.append((address, data))
        for member in self.party:
            if member.address + 1 == address:
                member.raw = bytes([member.raw[0], data[0], member.raw[2]])

    def close(self):
        pass


def test_watch_dip_stages_one_byte_and_fails_on_zero_at_the_first_bar(
        tmp_path, monkeypatch, fight_row):
    from automap import amiga
    from tools.amiga import amigatarget

    row_ = _edge_row(fight_row)
    party = _dip_party(row_)
    target = DipTarget(party)
    monkeypatch.setattr(amigatarget, "connect_pipe", lambda holder, machine: target)
    monkeypatch.setattr(amiga, "MACHINES", {GAME_KEY: object()}, raising=False)
    monkeypatch.setattr(amigaparty, "read_party", lambda target_: party)
    controller = _controller(tmp_path, watch=True, watch_dip=True)
    controller._stage_dip()
    # One byte, on the first member that is not a companion.
    assert target.writes == [(0x1101, b"\x01")]
    assert controller.dip["slot"] == 1
    for staged, status in ((1, "awaiting image review"), (0, "failed")):
        records = [{"slot": 1, "name": "M1", "address": 0x1100, "raw": bytes([0, staged, 0]).hex(),
                    "items": []}]
        controller._dip_at_first_bar(row_, records)
        assert controller.summary["watch_dip"]["status"] == status
    assert "evidence only" in controller.summary["watch_dip"]["expected"]


def _pod(tmp_path, monkeypatch, fight_row, bars, *, x_after=0, press=True):
    """A controller whose Quickfight off press is faked: the click clears X's byte to `x_after`."""
    row_ = _edge_row(fight_row)
    controller = _controller(tmp_path, game=ScriptGame(["combat_bar"]), press_quickfight_off=press)
    state = {"x": 1}
    order = []
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    monkeypatch.setattr(controller, "_map_section", lambda: order.append("map"))

    def readback():
        return [{"slot": 0, "name": "X", "address": 0xA0, "raw": bytes([0, state["x"], 0]).hex(),
                 "items": []},
                {"slot": 1, "name": "Y", "address": 0xB0, "raw": bytes([0, 1, 0]).hex(), "items": []}]

    def ui(guest, holder, action, names=(), **kwargs):
        order.append((action, names))
        state["x"] = x_after
        return ["invoked"]

    game = controller.game
    monkeypatch.setattr(game, "restore", lambda name, holder: (game.restores.append(name),
                                                               state.update(x=1)))
    monkeypatch.setattr(controller, "_action_readback", readback)
    monkeypatch.setattr(winwishaccept.winwish, "ui", ui)
    controller.summary["fight"]["found"]["bars"] = bars
    controller.greyed_done = True
    return controller, order, row_


X_BAR = {"owner": "X", "address": 0xA0, "control": 0, "quickfight": 1, "hit_points": 9,
         "shot": "x1.png", "number": 1}
Y_BAR = {"owner": "Y", "address": 0xB0, "control": 0, "quickfight": 1, "hit_points": 9,
         "shot": "y1.png", "number": 2}


def test_quickfight_off_press_triggers_at_the_first_bar_of_another_member(
        tmp_path, monkeypatch, fight_row):
    controller, order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR, dict(X_BAR)])
    game = controller.game
    memory = SimpleNamespace(holder="h", _target=None)
    screens = winwishaccept._fight_screens(controller, winwishaccept.fight_plan("darkness"), memory)
    screens.press("Q", "combat_bar")
    # X again: no press, no snapshot.
    assert order == [] and game.snapshots == [] and game.keys == ["Q"]
    controller.summary["fight"]["found"]["bars"] = [X_BAR, Y_BAR]
    screens.press("Q", "combat_bar")
    assert game.snapshots == ["pod_qf"]
    assert order == ["map", ("click", ("Quickfight off",))]
    assert game.keys == ["Q", "Q"]
    screens.press("Q", "combat_bar")
    assert game.snapshots == ["pod_qf"]


def _replay(controller, monkeypatch, first, second, *, restored_owner=0xB0):
    """Run `_pod_replay` with the fight loop faked: `second` are the bars of the replayed fight."""
    from tools.amiga import cursefight

    controller.summary["fight"]["found"]["bars"] = first
    monkeypatch.setattr(controller, "_await", lambda state, limit=90, interstitials=(): {})

    def fight(screens, memory, members, rules, found=None):
        found["bars"] = second
        return {"outcome": "won"}

    monkeypatch.setattr(cursefight, "fight", fight)
    memory = SimpleNamespace(holder="h", owner=lambda: {"name": "Y", "address": restored_owner})
    controller._pod_replay(winwishaccept.fight_plan("darkness"), None, memory)


def test_quickfight_off_a_needs_x_cleared_and_a_later_bar_for_x(tmp_path, monkeypatch, fight_row):
    controller, _order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR, Y_BAR], x_after=1)
    with pytest.raises(winwishaccept.AcceptanceStop, match="X still reads QUICK 1"):
        controller._press_quickfight_off([X_BAR, Y_BAR])
    assert controller.summary["qf_press_a"]["status"] == "failed"

    controller, _order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR, Y_BAR])
    controller._press_quickfight_off([X_BAR, Y_BAR])
    assert controller.summary["qf_press_a"]["status"] == "unproven"
    _replay(controller, monkeypatch, [X_BAR, Y_BAR, dict(X_BAR, shot="x2.png")], [Y_BAR])
    assert controller.summary["qf_press_a"]["status"] == "awaiting image review"
    assert controller.summary["qf_press_a"]["evidence"] == ["x2.png"]


def test_an_exception_in_wishs_log_after_the_quickfight_off_press_stops_the_run(
        tmp_path, monkeypatch, fight_row):
    controller, order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR, Y_BAR])
    block = {"file": "wish-1.log", "lines": ["10:00:00 ERROR unhandled exception", "KeyError: 'x'"],
             "exception": "KeyError: 'x'"}
    monkeypatch.setattr(winwishaccept.winwish, "wish_log_errors", lambda guest, holder: (
        [block] if ("click", ("Quickfight off",)) in order else []))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match="Wish logged an exception after Quickfight off: KeyError: 'x'"):
        controller._press_quickfight_off([X_BAR, Y_BAR])


def test_quickfight_off_b_fails_when_x_gets_a_bar_after_the_restore(tmp_path, monkeypatch, fight_row):
    for second, status in (([Y_BAR, dict(X_BAR, shot="x3.png")], "failed"),
                           ([Y_BAR], "awaiting image review")):
        controller, _order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR, Y_BAR])
        controller._press_quickfight_off([X_BAR, Y_BAR])
        _replay(controller, monkeypatch, [X_BAR, Y_BAR], second)
        assert controller.summary["qf_press_b"]["status"] == status
        assert controller.game.restores == ["pod_qf"]
    controller, _order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR, Y_BAR])
    controller._press_quickfight_off([X_BAR, Y_BAR])
    with pytest.raises(winwishaccept.AcceptanceStop, match="pod_qf restore"):
        _replay(controller, monkeypatch, [X_BAR, Y_BAR], [Y_BAR], restored_owner=0xA0)
    assert controller.summary["qf_press_b"]["status"] == "unproven"


def test_quickfight_off_unproven_when_the_fight_ends_before_x_turn(tmp_path, monkeypatch, fight_row):
    controller, _order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR])
    _replay(controller, monkeypatch, [X_BAR], [])
    for name in ("qf_press_a", "qf_press_b"):
        assert controller.summary[name]["status"] == "unproven"
        assert "ended before a second member's command bar" in controller.summary[name]["reason"]
    controller, _order, _row = _pod(tmp_path, monkeypatch, fight_row, [X_BAR, Y_BAR])
    controller._press_quickfight_off([X_BAR, Y_BAR])
    _replay(controller, monkeypatch, [X_BAR, Y_BAR], [Y_BAR])
    assert controller.summary["qf_press_a"]["status"] == "unproven"
    assert "ended before X's next turn" in controller.summary["qf_press_a"]["reason"]


@pytest.mark.parametrize("seen,status", [([4, 5, 5], "awaiting image review"),
                                         ([4, 5, 3, 5], "unproven")])
def test_watch_rows_need_every_mode_after_the_first_bar_to_be_2_4_or_5(
        tmp_path, monkeypatch, fight_row, seen, status):
    controller, _world = _edge(tmp_path, monkeypatch, fight_row, _members((0, 1, 7)))
    # A 3 before the first bar does not count.
    controller.summary["fight"]["modes"][:] = (
        [{"screen": "world", "mode": 3}, {"screen": "combat_bar", "mode": seen[0]}]
        + [{"screen": "encounter", "mode": mode} for mode in seen[1:]])
    controller._watch_edge("N")
    for name in ("watch_control_b", "watch_a"):
        assert controller.summary[name]["status"] == status
        assert (controller.summary[name]["reason"] is None) == (status != "unproven")
