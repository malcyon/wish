"""The Curse tavern-fight driver: the walk, the fight's answers and bar log, and its fail-closed paths."""

from __future__ import annotations

import argparse
import hashlib
import json

import pytest

from automap import gamedisks
from tools.amiga import amigakeys, cursefight
from tools.amiga.winuaesession import RouteError
from tools.registry import specimens

#: The way from EVOKER's slot D square, 3,14 facing east, to the tavern at 6,10.
ROUTE = [0, 0, 0, 1, 0, 1, 1]
START = {"area": 1, "x": 3, "y": 14, "facing": 1}
NAMES = ["GALAIN", "HOLLAND", "IILANDA", "SUNDRA", "EVOKER"]


def _member(name, **fields):
    row = {"name": name, "control": 0xB2 if name == "EVOKER" else 0,
           "status": 1 if name == "EVOKER" else 0, "side": 0, "quickfight": 0, "hit_points": 6}
    row.update(fields)
    return row


def _manifest(save="F"):
    return {"title": "curse", "fight": {
        "load": "D", "save": save, "place": dict(START), "route": list(ROUTE), "names": NAMES,
        "members": {name: {k: v for k, v in _member(name).items() if k != "name"}
                    for name in NAMES}}}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.5)


class Game:
    """A guest, guard map and memory over one scripted game.

    The party walks on the map: NP8 steps, NP4 and NP6 turn, and a box waiting for RETURN
    takes any other key. `boxes` puts a box up after the step that reaches a square. Every
    other screen comes from `script`, one per grab, the last one staying.
    """

    def __init__(self, clock, script=("world",), boxes=(), owners=(), parties=()):
        self.clock, self.script = clock, list(script)
        self.x, self.y, self.facing = START["x"], START["y"], START["facing"]
        self.boxes = set(boxes)
        self.box = False
        self.current = None
        self.keys: list[str] = []
        self.pressed_on: list[str | None] = []
        self.owners = list(owners)
        self.parties = list(parties)
        self.holder = "holder"
        self.walking = True

    # Guest
    def grab(self, label, raw, crop, timeout):
        self.clock.now += 1
        if self.walking:
            self.current = "continue" if self.box else "world"
        else:
            self.current = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)
        self.pressed_on.append(self.current)
        if not self.walking:
            return
        if self.box:
            self.box = key != "RET"
            return
        if key == "NP8":
            dx, dy = cursefight.STEP[self.facing]
            self.x, self.y = self.x + dx, self.y + dy
            self.box = (self.x, self.y) in self.boxes
        elif key in ("NP4", "NP6"):
            self.facing = (self.facing + (1 if key == "NP6" else -1)) % 4

    # Guards
    def __contains__(self, state):
        return state in cursefight.KNOWN

    def __call__(self, state, crop):
        return state == self.current

    # Memory
    def fix(self):
        return (self.x, self.y, self.facing)

    def owner(self):
        return self.owners.pop(0)

    def party(self):
        return self.parties.pop(0)


def _screens(tmp_path, game, clock, budget=100_000):
    return cursefight.Screens(game, "holder", tmp_path / "shots", game, budget,
                              clock=clock, sleep=clock.sleep)


def _keys_allowed(screens, game):
    pressed = [event for event in screens.events if "key" in event]
    assert [event["key"] for event in pressed] == game.keys
    for event in pressed:
        assert event["key"] in cursefight.ALLOWED_KEYS[event["from"]], event


def test_guard_rules_add_the_fight_screens_to_the_curse_map():
    rules = cursefight.guard_rules()
    assert set(cursefight.KNOWN) <= set(rules)
    for state, rule in cursefight.FIGHT_GUARDS.items():
        assert rules[state] == rule
    assert set(cursefight.ALLOWED_KEYS) <= set(cursefight.KNOWN)


def test_every_allowed_key_is_an_amiga_key():
    for keys in cursefight.ALLOWED_KEYS.values():
        for key in keys:
            assert amigakeys.lookup(key).amiga is not None, key


def test_walk_turns_and_steps_to_the_tavern(tmp_path):
    clock = Clock()
    game = Game(clock)
    screens = _screens(tmp_path, game, clock)
    steps = cursefight.walk(screens, game, START, ROUTE)
    assert (game.x, game.y) == cursefight.TAVERN
    assert game.keys == ["NP4", "NP8", "NP8", "NP8", "NP6", "NP8", "NP4", "NP8", "NP6",
                         "NP8", "NP8"]
    assert [(s["x"], s["y"]) for s in steps][-1] == cursefight.TAVERN
    assert set(game.pressed_on) == {"world"}
    _keys_allowed(screens, game)


def test_walk_answers_a_box_and_sends_the_key_it_took_again(tmp_path):
    clock = Clock()
    game = Game(clock)
    screens = _screens(tmp_path, game, clock)
    original = game.press
    late = {"done": False}

    def press(holder, key, timeout):
        # The box comes up only after the grab that let the next key out, so it takes that key.
        if (game.x, game.y) == (4, 10) and not late["done"] and key != "RET":
            late["done"] = True
            game.keys.append(key)
            game.pressed_on.append(game.current)
            game.box = True
            return
        original(holder, key, timeout)

    game.boxes = set()
    game.press = press
    cursefight.walk(screens, game, START, ROUTE)
    assert (game.x, game.y) == cursefight.TAVERN
    assert game.keys.count("NP6") == 3


def test_walk_presses_return_on_a_box_before_the_next_key(tmp_path):
    clock = Clock()
    game = Game(clock, boxes={(4, 10)})
    screens = _screens(tmp_path, game, clock)
    cursefight.walk(screens, game, START, ROUTE)
    assert (game.x, game.y) == cursefight.TAVERN
    at = game.keys.index("RET")
    assert game.pressed_on[at] == "continue" and game.keys[at + 1] == "NP6"
    _keys_allowed(screens, game)


def test_walk_stops_when_the_party_is_not_where_the_slot_put_it(tmp_path):
    clock = Clock()
    game = Game(clock)
    game.x = 4
    with pytest.raises(RouteError, match="stands at"):
        cursefight.walk(_screens(tmp_path, game, clock), game, START, ROUTE)
    assert game.keys == []


def test_walk_stops_when_a_step_does_not_move_the_party(tmp_path):
    clock = Clock()
    game = Game(clock)
    game.press = lambda holder, key, timeout: game.keys.append(key)
    with pytest.raises(RouteError, match="left the party"):
        cursefight.walk(_screens(tmp_path, game, clock), game, START, ROUTE)
    assert game.keys == ["NP4"]


#: A brawl: two bars, each grabbed twice (the bar and the check after the owner read),
#: monster turns no guard knows, then the end screens and the map.
FIGHT = [None, "tavern", None, "combat_bar", "combat_bar", None, None, "combat_bar",
         "combat_bar", None, "continue_battle", "continue", "treasure", "treasure_left",
         "continue", "continue", "investigate", "world"]


def _owner(name, quick=0):
    return {"address": 0xC5B078, **_member(name, quickfight=quick)}


def test_fight_answers_every_screen_and_logs_each_bar_owner(tmp_path):
    clock = Clock()
    game = Game(clock, FIGHT, owners=[_owner("SUNDRA"), _owner("EVOKER")])
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    found = cursefight.fight(screens, game, ["EVOKER"])
    assert [bar["owner"] for bar in found["bars"]] == ["SUNDRA", "EVOKER"]
    assert found["bars"][1]["control"] == 0xB2 and found["bars"][1]["quickfight"] == 0
    assert game.keys == ["Q", "Q", "N", "RET", "E", "N", "RET", "RET", "N"]
    assert [e["bar"]["owner"] for e in screens.events if "bar" in e] == ["SUNDRA", "EVOKER"]
    _keys_allowed(screens, game)


def test_fight_stops_when_a_named_member_had_no_bar(tmp_path):
    clock = Clock()
    game = Game(clock, FIGHT, owners=[_owner("SUNDRA"), _owner("GALAIN")])
    game.walking = False
    with pytest.raises(RouteError, match="EVOKER.*no command bar"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])


def test_fight_stops_when_the_bar_goes_before_its_owner_is_read(tmp_path):
    clock = Clock()
    game = Game(clock, [None, "combat_bar", None], owners=[_owner("EVOKER")])
    game.walking = False
    with pytest.raises(RouteError, match="went before"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == []


@pytest.mark.parametrize("screen", ["camp", "loaded_menu", "title", "exit_game"])
def test_fight_stops_on_a_known_screen_it_does_not_answer(tmp_path, screen):
    clock = Clock()
    game = Game(clock, [None, screen])
    game.walking = False
    with pytest.raises(RouteError, match="mid-fight"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == []


def test_fight_stops_on_an_unknown_screen_that_stays_still(tmp_path):
    clock = Clock()
    game = Game(clock, [None])
    game.walking = False
    with pytest.raises(RouteError, match="no guard knows stayed"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == [] and clock.now < cursefight.FIGHT_STALL + 10


def test_fight_waits_through_unknown_screens_that_keep_changing(tmp_path, monkeypatch):
    clock = Clock()
    turns = [None] * 200
    game = Game(clock, [None, "combat_bar", "combat_bar", *turns, "continue_battle", "world"],
                owners=[_owner("EVOKER")])
    game.walking = False
    frames = iter(range(10_000))
    monkeypatch.setattr(cursefight, "_digest", lambda shot: str(next(frames)))
    found = cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert clock.now > cursefight.FIGHT_STALL and game.keys == ["Q", "N"]
    assert found["bars"][0]["owner"] == "EVOKER"


def test_fight_stops_at_its_time_limit(tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, [None])
    game.walking = False
    frames = iter(range(10_000))
    monkeypatch.setattr(cursefight, "_digest", lambda shot: str(next(frames)))
    with pytest.raises(RouteError, match="still going"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])


def test_fight_stops_when_the_tavern_bar_stays_after_punch(tmp_path):
    clock = Clock()
    game = Game(clock, ["tavern"])
    game.walking = False
    with pytest.raises(RouteError, match="tavern bar stayed"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == []


def test_fight_does_not_end_on_a_map_that_does_not_hold(tmp_path):
    clock = Clock()
    script = [None, "combat_bar", "combat_bar", None, "world", "continue", "world"]
    game = Game(clock, script, owners=[_owner("EVOKER")])
    game.walking = False
    found = cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == ["Q", "RET"]
    assert found["answered"][-1]["screen"] == "continue"


@pytest.mark.parametrize("change, match", [
    ({"quickfight": 0}, "quickfight 0"), ({"hit_points": 0}, "fell"),
    ({"status": 6}, "fell"), ({"control": 0}, "fell")])
def test_check_members_needs_quickfight_and_the_member_standing(change, match):
    party = [_member(name, quickfight=1) for name in NAMES]
    party[-1].update(change)
    with pytest.raises(RouteError, match=match):
        cursefight.check_members(party, _manifest(), ["EVOKER"])


def test_check_members_passes_a_quick_standing_member():
    party = [_member(name, quickfight=1) for name in NAMES]
    assert cursefight.check_members(party, _manifest(), ["EVOKER"])["EVOKER"]["quickfight"] == 1


#: Boot, load with two load errors, begin; the walk and the fight are replaced; then camp,
#: save and the exit question.
DRIVE = [None, "intro", "front_end", "title", "load_picker", None, "load_error", "load_error",
         "loaded_menu", "loaded_menu", "world", "tavern", "world", "camp",
         "camp_save_picker", None, "exit_game", "exit_game", "camp"]


def _drive(tmp_path, monkeypatch, save=True, parties=None):
    clock = Clock()
    loaded = [_member(name) for name in NAMES]
    after = [_member(name, quickfight=1) for name in NAMES]
    game = Game(clock, DRIVE, parties=parties or [loaded, after])
    game.walking = False
    walked = []
    monkeypatch.setattr(cursefight, "walk", lambda *a: walked.append(a) or [])
    monkeypatch.setattr(cursefight, "fight",
                        lambda *a: {"bars": [{"owner": "EVOKER"}], "answered": []})
    screens = _screens(tmp_path, game, clock)
    found = cursefight.drive(screens, _manifest(), ["EVOKER"], game, save=save)
    return found, game, screens, walked


def test_drive_loads_walks_fights_and_saves_once(tmp_path, monkeypatch):
    found, game, screens, walked = _drive(tmp_path, monkeypatch)
    assert game.keys == ["ESC", "ESC", "L", "D", "RET", "RET", "B", "P", "E", "S", "F", "N"]
    assert found["load_errors"] == 2 and walked
    assert found["members"]["EVOKER"]["quickfight"] == 1
    _keys_allowed(screens, game)


def test_drive_with_no_save_stops_after_the_checks(tmp_path, monkeypatch):
    found, game, screens, _ = _drive(tmp_path, monkeypatch, save=False)
    assert game.keys[-1] == "P" and "S" not in game.keys
    _keys_allowed(screens, game)


def test_drive_stops_before_saving_when_the_member_fell(tmp_path, monkeypatch):
    loaded = [_member(name) for name in NAMES]
    fallen = [_member(name, quickfight=1) for name in NAMES]
    fallen[-1]["hit_points"] = 0
    with pytest.raises(RouteError, match="fell"):
        _drive(tmp_path, monkeypatch, parties=[loaded, fallen])


def test_drive_stops_when_the_loaded_party_differs(tmp_path, monkeypatch):
    loaded = [_member(name) for name in NAMES[:-1]]
    with pytest.raises(RouteError, match="loaded party"):
        _drive(tmp_path, monkeypatch, parties=[loaded, loaded])


@pytest.mark.parametrize("on, key", [("world", "S"), ("camp", "E"), ("combat_bar", "D"),
                                     ("combat_bar", "SPACE"), ("tavern", "H"),
                                     ("loaded_menu", "D"), ("nowhere", "A")])
def test_a_key_outside_the_allowlist_is_never_sent(tmp_path, on, key):
    clock = Clock()
    game = Game(clock)
    screens = _screens(tmp_path, game, clock)
    with pytest.raises(RouteError, match="not a key"):
        screens.press(key, on)
    assert game.keys == [] and screens.events == []


def _read(members, *, verify=(), unchanged=True):
    return {"letter": "F", "verify": list(verify), "loaded_slot_unchanged": unchanged,
            "members": members}


def test_verdict_passes_a_quick_member_saved_as_loaded():
    members = [_member(name, quickfight=1) for name in NAMES]
    assert cursefight.verdict(_read(members), _manifest(), ["EVOKER"]) == []


@pytest.mark.parametrize("change, match", [
    ({"quickfight": 0}, "quickfight 0"), ({"control": 0}, "saved as"),
    ({"hit_points": 0}, "0 hit points")])
def test_verdict_names_each_problem(change, match):
    members = [_member(name, quickfight=1) for name in NAMES]
    members[-1].update(change)
    problems = cursefight.verdict(_read(members), _manifest(), ["EVOKER"])
    assert any(match in p for p in problems), problems


def test_verdict_needs_the_disk_and_the_loaded_slot_intact():
    members = [_member(name, quickfight=1) for name in NAMES]
    problems = cursefight.verdict(_read(members, verify=["bad"], unchanged=False),
                                  _manifest(), ["EVOKER"])
    assert len(problems) == 2
    problems = cursefight.verdict(_read(members[:-1]), _manifest(), ["EVOKER"])
    assert any("saved party" in p for p in problems)


class LaneGuest:
    def __init__(self):
        self.calls = []

    def _run(self, *args, timeout):
        self.calls.append(args)
        return '{"muted": true}'

    def silence(self, proof):
        return True


def _staged(tmp_path, save="F"):
    disks = {}
    for key in ("save", "diskb"):
        path = tmp_path / f"{key}.adf"
        path.write_bytes(key.encode())
        disks[key] = {"path": str(path), "sha256": hashlib.sha256(key.encode()).hexdigest()}
    source = tmp_path / "source.adf"
    source.write_bytes(b"source")
    manifest = {**_manifest(save), "disks": disks, "registered": {}}
    manifest["fight"]["source"] = {"path": str(source),
                                   "sha256": hashlib.sha256(b"source").hexdigest()}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    return path


def _args(tmp_path, manifest, members=("EVOKER",), no_save=False):
    return argparse.Namespace(manifest=manifest, holder="holder", out=tmp_path / "run",
                              budget=600, wait_lane=0, member=list(members), no_save=no_save)


@pytest.mark.parametrize("problem", ["out_exists", "not_staged", "hash", "slot_taken",
                                     "no_member", "unknown_member"])
def test_run_stops_before_the_guest(tmp_path, monkeypatch, problem):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(cursefight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(cursefight.curseadd, "slot_letters", lambda disk: ["A", "D"])
    members = ("EVOKER",)
    if problem == "out_exists":
        (tmp_path / "run").mkdir()
    elif problem == "not_staged":
        value = json.loads(manifest.read_text())
        del value["fight"]
        manifest.write_text(json.dumps(value))
    elif problem == "hash":
        (tmp_path / "diskb.adf").write_bytes(b"changed")
    elif problem == "slot_taken":
        monkeypatch.setattr(cursefight.curseadd, "slot_letters", lambda disk: ["D", "F"])
    elif problem == "no_member":
        members = ()
    else:
        members = ("BRUTUS",)
    guest = LaneGuest()
    with pytest.raises(RouteError):
        cursefight.run(_args(tmp_path, manifest, members), guest=guest, guards=object(),
                       boot=pytest.fail, halt=pytest.fail, memory=object())
    assert guest.calls == []


def _run(tmp_path, monkeypatch, *, drive, problems=(), no_save=False):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(cursefight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(cursefight.curseadd, "slot_letters", lambda disk: ["D"])
    monkeypatch.setattr(cursefight.curseadd, "mute", lambda guest, out, timeout: out / "mute.json")
    monkeypatch.setattr(cursefight, "drive", drive)
    fetched = tmp_path / "fetched-save.adf"
    fetched.write_bytes(b"fetched")
    monkeypatch.setattr(cursefight, "read_back", lambda path, value: {"path": str(path)})
    monkeypatch.setattr(cursefight, "verdict", lambda found, value, members: list(problems))
    halted = []
    receipt = None
    try:
        receipt = cursefight.run(
            _args(tmp_path, manifest, no_save=no_save), guest=LaneGuest(), guards=object(),
            boot=lambda *a, **k: {"claim": "ok"}, memory=object(),
            halt=lambda *a, **k: halted.append(k) or {"fetched": {"save": {"path": str(fetched)}}})
    finally:
        written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    return receipt, written, halted


def test_run_halts_and_fails_when_the_route_stops(tmp_path, monkeypatch):
    def drive(*args, **kwargs):
        raise RouteError("expected world, saw ['camp']")

    with pytest.raises(RouteError, match="saw"):
        _run(tmp_path, monkeypatch, drive=drive)
    written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert written["success"] is False and "read_back" not in written


@pytest.mark.parametrize("problems", [[], ["EVOKER was saved with quickfight 0"]])
def test_run_succeeds_only_on_a_clean_read_back(tmp_path, monkeypatch, problems):
    drive = lambda *a, **k: {"bars": []}  # noqa: E731
    if problems:
        with pytest.raises(RouteError, match="quickfight"):
            _run(tmp_path, monkeypatch, drive=drive, problems=problems)
    else:
        receipt, written, halted = _run(tmp_path, monkeypatch, drive=drive)
        assert receipt["success"] and written["source_hashes"] == "unchanged" and halted


def test_run_with_no_save_reads_nothing_back(tmp_path, monkeypatch):
    seen = {}

    def drive(screens, manifest, members, memory, *, save):
        seen["save"] = save
        return {"bars": []}

    receipt, _written, _halted = _run(tmp_path, monkeypatch, drive=drive, no_save=True)
    assert seen["save"] is False and "read_back" not in receipt and receipt["success"]


def _registered_inputs():
    specimen = (specimens.tree_root() / "coab-amiga" / "WISH-SPEC-wish-plane-303-curse-evoker-add"
                / "fetched-save.adf")
    found = []
    for root in gamedisks.candidates("amiga"):
        if root.exists():
            found += sorted(root.rglob("CurseOfTheAzureBonds_B.adf"))
    if not specimen.is_file() or not found:
        pytest.skip("the EVOKER specimen or Curse disk B is not on this machine")
    return specimen, found[0]


def test_stage_plans_the_tavern_walk_from_the_evoker_slot(tmp_path):
    specimen, diskb = _registered_inputs()
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps({
        "title": "curse", "registered": {},
        "disks": {"save": {"path": str(specimen), "sha256": digest(specimen)},
                  "diskb": {"path": str(diskb), "sha256": digest(diskb)}}}))
    before = digest(specimen)
    path = cursefight.stage(prep, specimen, tmp_path / "out", load="D", save="F")
    staged = json.loads(path.read_text())
    fight = staged["fight"]
    assert fight["route"] == ROUTE and fight["place"] == START
    assert fight["names"] == NAMES
    assert fight["members"]["EVOKER"]["control"] == 0xB2
    assert fight["members"]["EVOKER"]["status"] == 1
    assert fight["members"]["EVOKER"]["quickfight"] == 0
    assert digest(specimen) == before == staged["disks"]["save"]["sha256"]
    with pytest.raises(RouteError, match="already on"):
        cursefight.stage(prep, specimen, tmp_path / "out2", load="D", save="A")
    assert not (tmp_path / "out2").exists()
