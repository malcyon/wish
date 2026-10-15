"""The Silver Blades wandering-fight driver: the stage, the walk, the fight's answers, the capture
mode and their fail-closed paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import types

import pytest

from goldbox import amiga_adf, amiga_port, amiga_savegame, dos_port
from tools.amiga import amigakeys, ssbfight
from tools.amiga.screens import PixelGuards
from tools.amiga.winuaesession import RouteError
from tools.registry import scratch, specimens

START = {"area": 16, "x": 3, "y": 7, "facing": 2}
#: Two street squares, 3,7 and 3,6 north of it.
PLAN = {"route": [], "square": [3, 7], "facing": 0}
NAMES = ["Guy de Valois", "PAINE", "EPONA", "MALACHITE", "DOMINIC", "MORGAINE"]


def _member(name, **fields):
    row = {"name": name, "control": 0, "status": 0, "side": 0, "quickfight": 0,
           "hit_points": 8}
    row.update(fields)
    return row


def _manifest(save="E"):
    return {"title": "ssb", "issue": "391",
            "disks": {"df0": {"path": "df0.adf"}},
            "fight": {"load": "D", "save": save, "place": dict(START), **PLAN, "names": NAMES,
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

    While walking, NP8 steps, NP4 and NP6 turn, and a step onto a square in `fights` brings
    up the encounter page. Otherwise every screen comes from `script`, one per grab, the last
    one staying.
    """

    def __init__(self, clock, script=("world",), fights=(), owners=(), parties=()):
        self.clock, self.script = clock, list(script)
        self.x, self.y, self.facing = START["x"], START["y"], START["facing"]
        self.fights = set(fights)
        self.met = False
        self.current = None
        self.keys: list[str] = []
        self.pressed_on: list[str | None] = []
        self.owners = list(owners)
        self.parties = list(parties)
        self.holder = "holder"
        self.walking = True
        self.frame = 0
        self.gate = 1
        self.pointer = 0

    # Guest
    def grab(self, label, raw, crop, timeout):
        self.clock.now += 1
        if self.walking:
            self.current = "continue" if self.met else "world"
        else:
            self.current = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        crop.write_bytes(str(self.current).encode())
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)
        self.pressed_on.append(self.current)
        if not self.walking or self.met:
            return
        if key == "NP8":
            dx, dy = ssbfight.STEP[self.facing]
            self.x, self.y = self.x + dx, self.y + dy
            self.met = (self.x, self.y) in self.fights
        elif key in ("NP4", "NP6"):
            self.facing = (self.facing + (1 if key == "NP6" else -1)) % 4

    # Guards
    def __contains__(self, state):
        return state in ssbfight.KNOWN

    def __call__(self, state, crop):
        return state == self.current

    # Memory
    def fix(self):
        return (self.x, self.y, self.facing)

    def owner(self):
        return self.owners.pop(0) if len(self.owners) > 1 else self.owners[0]

    def party(self):
        return self.parties.pop(0)

    mode_error = None

    def in_fight(self):
        return True

    def variable(self, var):
        assert var == ssbfight.GATE
        return self.gate

    def turn_pointer(self):
        return self.pointer


def _screens(tmp_path, game, clock, budget=100_000):
    return ssbfight.Screens(game, "holder", tmp_path / "shots", game, budget,
                            clock=clock, sleep=clock.sleep)


def _keys_allowed(screens, game):
    pressed = [event for event in screens.events if "key" in event]
    assert [event["key"] for event in pressed] == game.keys
    for event in pressed:
        assert event["key"] in ssbfight.ALLOWED_KEYS[event["from"]], event


def _owner(name, **fields):
    return {"address": 0xC50000, **_member(name, **fields)}


# -- the guard map ---------------------------------------------------------------------------

def test_guard_rules_cover_every_known_screen_but_the_uncaptured_ones():
    rules = ssbfight.guard_rules()
    on_file = json.loads(ssbfight.GUARDS.read_text())["guards"]
    assert ssbfight.missing(rules) == [s for s in ssbfight.UNCAPTURED if s not in on_file]
    assert set(ssbfight.KNOWN) - set(ssbfight.UNCAPTURED) <= set(rules)
    assert ssbfight.TREASURE_SHORT in rules["treasure_bar"]
    assert set(ssbfight.ALLOWED_KEYS) <= set(ssbfight.KNOWN)


def test_guard_rules_load_as_pixel_guards(tmp_path):
    path = tmp_path / "guards.json"
    path.write_text(json.dumps(ssbfight.guard_rules()))
    assert "treasure_bar" in PixelGuards(path)


def test_every_allowed_key_is_an_amiga_key():
    for keys in ssbfight.ALLOWED_KEYS.values():
        for key in keys:
            assert amigakeys.lookup(key).amiga is not None, key


def test_the_short_treasure_rule_reads_both_kept_treasure_bars(tmp_path):
    root = scratch.cache_dir("acceptance")
    crops = [root / "640/ssb2/accept1/shots/11-world.png",
             root / "640/ssb2/accept2/shots/11-world.png"]
    world = root / "672/26293716ee-amiga-accept1b/accept1b/shots/11-world.png"
    if not all(p.is_file() for p in (*crops, world)):
        pytest.skip("the kept Silver Blades treasure-bar crops are not on this machine")
    path = tmp_path / "guards.json"
    path.write_text(json.dumps({"short": ssbfight.TREASURE_SHORT}))
    guards = PixelGuards(path)
    assert all(guards("short", crop) for crop in crops)
    assert not guards("short", world)


def test_the_combat_bar_rule_reads_the_captured_bar_and_not_the_encounter_page(tmp_path):
    shots = scratch.cache_dir("acceptance") / "WISH-391" / "cap1" / "screens"
    bar, page = shots / "097-capture.png", shots / "088-step.png"
    if not (bar.is_file() and page.is_file()):
        pytest.skip("the WISH-391 combat-bar capture is not on this machine")
    path = tmp_path / "guards.json"
    path.write_text(json.dumps(ssbfight.guard_rules()))
    guards = PixelGuards(path)
    assert guards("combat_bar", bar) and not guards("combat_bar", page)
    assert guards("continue", page)


def test_the_continue_battle_rule_reads_the_bar_and_not_the_fight_before_it(tmp_path):
    shots = scratch.cache_dir("acceptance") / "WISH-391" / "full3" / "screens"
    # The bar held from 129 to the stop at 155; 128 is the fight just before it.
    first, last, before = (shots / f"{n}-fight.png" for n in ("129", "155", "128"))
    if not all(p.is_file() for p in (first, last, before)):
        pytest.skip("the WISH-391 full3 frames are not on this machine")
    path = tmp_path / "guards.json"
    path.write_text(json.dumps(ssbfight.guard_rules()))
    guards = PixelGuards(path)
    assert guards("continue_battle", first) and guards("continue_battle", last)
    assert not any(guards(s, last) for s in ssbfight.KNOWN if s != "continue_battle")
    assert not guards("continue_battle", before)


def test_fight_answers_each_continue_battle_bar_no_once(tmp_path):
    clock = Clock()
    game = Game(clock, ["continue", None, "combat_bar", "combat_bar", None, "continue_battle",
                        None, "continue_battle", "party_won", "world"],
                owners=[_owner("PAINE")])
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    found = ssbfight.fight(screens, game, ["PAINE"])
    assert found["outcome"] == "won" and game.keys == ["RET", "Q", "N", "N", "RET"]
    _keys_allowed(screens, game)


# -- staging ----------------------------------------------------------------------------------

class Geo:
    """A 16x16 map of `STREET` squares with no walls, but for `other` squares."""

    def __init__(self, other=(), walls=()):
        self.other, self.walls = set(other), set(walls)

    def attributes(self, x, y):
        return 0x81 if (x, y) in self.other else ssbfight.STREET

    def is_passable(self, x, y, facing):
        return (x, y, facing) not in self.walls


def test_wander_plan_stays_where_the_party_stands_on_a_street():
    assert ssbfight.wander_plan(Geo(), (3, 7)) == {"route": [], "square": [3, 7], "facing": 0}


def test_wander_plan_skips_a_walled_or_scripted_neighbour():
    geo = Geo(other={(3, 6)}, walls={(3, 7, 1)})
    assert ssbfight.wander_plan(geo, (3, 7))["facing"] == 2


def test_wander_plan_walks_off_a_scripted_square_over_streets_only():
    others = {(x, y) for x in range(16) for y in range(16) if x < 5} - {(4, 7)}
    plan = ssbfight.wander_plan(Geo(other=others), (3, 7))
    assert plan["route"] == [1] and plan["square"] == [4, 7]


def test_wander_plan_stops_when_no_street_pair_is_reachable():
    others = {(x, y) for x in range(16) for y in range(16)} - {(3, 7)}
    with pytest.raises(RouteError, match="no street square"):
        ssbfight.wander_plan(Geo(other=others), (3, 7))


def test_with_word_changes_only_the_gate_word():
    data = bytes(range(256)) * 40
    staged = ssbfight.with_word(data, ssbfight.GATE, 1)
    at = amiga_savegame.SILVER_BLADES.vm_offset(ssbfight.GATE - 0x200)
    assert ssbfight.word(staged, ssbfight.GATE) == 1 and len(staged) == len(data)
    assert {i for i in range(len(data)) if data[i] != staged[i]} <= {at, at + 1}


def _specimen():
    path = (specimens.tree_root() / "ssb-amiga" / "WISH-SPEC-amiga-ssb-foundation-walked"
            / "fetched-df0.adf")
    try:
        diskb = ssbfight.route_silver_blades.find_disk_b()
    except RouteError:
        diskb = None
    if not path.is_file() or diskb is None:
        pytest.skip("the foundation-walked specimen or Silver Blades disk B is not on this machine")
    return path, diskb


def test_stage_sets_the_gate_in_a_copy_and_plans_the_walk(tmp_path):
    source, diskb = _specimen()
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    before = digest(source)
    path = ssbfight.stage(source, tmp_path / "out", load="B", save="E", diskb=diskb)
    staged = json.loads(path.read_text())
    fight = staged["fight"]
    assert fight["place"] == {"area": 16, "x": 3, "y": 5, "facing": 2}
    # North of 3,5 is 3,4, a scripted square (0x87); east is the street square 4,5.
    assert fight["route"] == [] and fight["square"] == [3, 5] and fight["facing"] == 1
    assert fight["staged"] == {"4C2D": {"before": 0, "after": 1}}
    assert fight["noted"]["4BF2"] == 16 and fight["noted"]["4CD9"] == 0
    assert fight["names"][1:] == NAMES[1:]
    assert digest(source) == before == fight["source"]["sha256"]
    assert fight["staged_records"] == []
    original = amiga_adf.AmigaDisk.open(source).read_file("/SAVE/savgamB.sav")
    copy = amiga_adf.AmigaDisk.open(staged["disks"]["df0"]["path"])
    assert not copy.verify()
    written = copy.read_file("/SAVE/savgamB.sav")
    changed = [i for i in range(len(original)) if original[i] != written[i]]
    at = amiga_savegame.SILVER_BLADES.vm_offset(ssbfight.GATE - 0x200)
    assert len(written) == len(original) and set(changed) <= {at, at + 1} and changed
    assert ssbfight.word(written, ssbfight.GATE) == 1
    assert copy.read_file("/SAVE/savgamC.sav") == amiga_adf.AmigaDisk.open(source).read_file(
        "/SAVE/savgamC.sav")


def test_stage_writes_the_named_members_hit_points_with_the_gate(tmp_path):
    source, diskb = _specimen()
    path = ssbfight.stage(source, tmp_path / "out", load="B", save="E", diskb=diskb,
                          records=["5:hp_max=150,hp_current=150"])
    fight = json.loads(path.read_text())["fight"]
    disk = amiga_adf.AmigaDisk.open(source)
    original = disk.read_file("/SAVE/savgamB.sav")
    saved = amiga_savegame.read_slot(disk, "B", ssbfight.TITLE)
    copy = amiga_adf.AmigaDisk.open(json.loads(path.read_text())["disks"]["df0"]["path"])
    written = copy.read_file("/SAVE/savgamB.sav")
    start = saved.blocks[4][0]
    hp = {start + ssbfight.stage_field_offset("hp_max"),
          start + ssbfight.stage_field_offset("hp_current")}
    gate = amiga_savegame.SILVER_BLADES.vm_offset(ssbfight.GATE - 0x200)
    changed = {i for i in range(len(original)) if original[i] != written[i]}
    assert hp <= changed <= hp | {gate, gate + 1}
    dominic = fight["staged_records"][0]
    assert dominic["member"] == 5 and dominic["name"] == NAMES[4]
    assert dominic["fields"]["hp_current"]["after"] == 150
    assert dominic["fields"]["hp_current"]["before"] == saved.characters[4].raw[0x152]
    assert fight["members"][NAMES[4]]["hit_points"] == 150
    assert fight["members"][fight["names"][0]]["hit_points"] != 150


def test_the_staged_fields_sit_where_the_field_map_puts_them_in_a_record():
    # The offsets the driver reads a live record by are the ones the stage writes.
    assert ssbfight.stage_field_offset("hp_current") == ssbfight.RECORD["hit_points"]
    assert ssbfight.stage_field_offset("hp_max") == 0x70


@pytest.mark.parametrize("records, match", [
    (["1:armour=3"], "writes only"), (["1:hp_current=0"], "1 to 255"),
    (["1:hp_max=256"], "1 to 255"), (["7:hp_max=9"], "members 1 to 6"),
    (["0:hp_max=9"], "members 1 to 6"), (["2:hp_max=9", "2:hp_current=9"], "twice"),
    (["nonsense"], "MEMBER:FIELD"), (["1:hp_current=200"], "above hp_max")])
def test_stage_records_that_cannot_be_written_stop_before_anything_is(tmp_path, records, match):
    source, diskb = _specimen()
    with pytest.raises(RouteError, match=match):
        ssbfight.stage(source, tmp_path / "out", load="B", save="E", diskb=diskb, records=records)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("load, save, match", [("B", "C", "already on"),
                                               ("C", "E", "keeps for its own"),
                                               ("A", "E", "not set out"),
                                               ("G", "H", "not on")])
def test_stage_stops_before_writing_anything(tmp_path, load, save, match):
    source, diskb = _specimen()
    with pytest.raises(RouteError, match=match):
        ssbfight.stage(source, tmp_path / "out", load=load, save=save, diskb=diskb)
    assert not (tmp_path / "out").exists()


# -- the walk ---------------------------------------------------------------------------------

def test_wander_turns_steps_and_stops_on_the_step_that_meets_the_fight(tmp_path):
    clock = Clock()
    game = Game(clock, fights={(3, 7)})
    game.fights = set()
    screens = _screens(tmp_path, game, clock)
    original = game.press
    steps = {"n": 0}

    def press(holder, key, timeout):
        original(holder, key, timeout)
        if key == "NP8":
            steps["n"] += 1
            game.met = steps["n"] == 3

    game.press = press
    found = ssbfight.wander(screens, game, START, PLAN)
    # North to 3,6, about and south to 3,7, about and north again, where the fight comes.
    assert game.keys == ["NP6", "NP6", "NP8", "NP6", "NP6", "NP8", "NP6", "NP6", "NP8"]
    assert [(s["x"], s["y"]) for s in found["steps"]] == [(3, 6), (3, 7), (3, 6)]
    assert set(game.pressed_on) == {"world"} and found["met"]
    _keys_allowed(screens, game)


def test_wander_holds_the_map_before_each_next_key(tmp_path):
    clock = Clock()
    game = Game(clock)
    screens = _screens(tmp_path, game, clock)
    times = []
    original = game.press

    def press(holder, key, timeout):
        times.append((key, clock.now))
        original(holder, key, timeout)
        game.met = len([k for k, _ in times if k == "NP8"]) == 2

    game.press = press
    ssbfight.wander(screens, game, START, PLAN)
    step, after = times[2], times[3]
    assert step[0] == "NP8" and after[1] - step[1] >= ssbfight.STEP_SETTLE


def test_wander_walks_the_route_first(tmp_path):
    clock = Clock()
    game = Game(clock, fights={(5, 7)})
    plan = {"route": [1, 1], "square": [5, 7], "facing": 1}
    found = ssbfight.wander(_screens(tmp_path, game, clock), game, START, plan)
    assert game.keys == ["NP4", "NP8", "NP8"] and found["steps"][-1]["x"] == 5


def test_wander_stops_when_the_party_is_not_where_the_slot_put_it(tmp_path):
    clock = Clock()
    game = Game(clock)
    game.y = 6
    with pytest.raises(RouteError, match="stands at"):
        ssbfight.wander(_screens(tmp_path, game, clock), game, START, PLAN)
    assert game.keys == []


def test_wander_stops_when_a_step_does_not_move_the_party(tmp_path):
    clock = Clock()
    game = Game(clock)
    original = game.press
    game.press = lambda holder, key, timeout: (game.keys.append(key) if key == "NP8"
                                               else original(holder, key, timeout))
    with pytest.raises(RouteError, match="NP8 left the party"):
        ssbfight.wander(_screens(tmp_path, game, clock), game, START, PLAN)
    assert game.keys == ["NP6", "NP6", "NP8"]


def test_wander_stops_after_its_step_limit(tmp_path):
    clock = Clock()
    game = Game(clock)
    with pytest.raises(RouteError, match="met no fight"):
        ssbfight.wander(_screens(tmp_path, game, clock), game, START, PLAN, limit=4)
    assert game.keys.count("NP8") == 4


# -- the fight --------------------------------------------------------------------------------

#: The encounter page, a monster turn, two bars each grabbed twice, the won page, the treasure
#: bar, the offer to go back for the treasure, and the map.
FIGHT = ["continue", None, "combat_bar", "combat_bar", None, "combat_bar", "combat_bar", None,
         "party_won", "treasure_bar", "treasure", "world"]


@pytest.mark.parametrize("bar", ["treasure_bar", "treasure_bar_no_share"])
def test_fight_answers_every_screen_and_logs_each_bar_owner(tmp_path, bar):
    clock = Clock()
    script = [bar if screen == "treasure_bar" else screen for screen in FIGHT]
    game = Game(clock, script, owners=[_owner("PAINE"), _owner("Guy de Valois")])
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    found = ssbfight.fight(screens, game, ["GUY DE VALOIS"])
    assert found["outcome"] == "won"
    assert [bar["owner"] for bar in found["bars"]] == ["PAINE", "Guy de Valois"]
    assert game.keys == ["RET", "Q", "Q", "RET", "E", "N"]
    assert game.pressed_on[-3:] == ["party_won", bar, "treasure"]
    assert found["won_page"] == found["answered"][-3]["shot"]
    _keys_allowed(screens, game)


def test_fight_does_not_call_a_fight_won_without_the_won_page(tmp_path):
    clock = Clock()
    game = Game(clock, ["continue", None, "combat_bar", "combat_bar", None, "continue", "world"],
                owners=[_owner("PAINE")])
    game.walking = False
    found = {}
    with pytest.raises(RouteError, match="no won page"):
        ssbfight.fight(_screens(tmp_path, game, clock), game, ["PAINE"], found=found)
    assert "won_page" not in found


def _full5(*numbers):
    """Frames of the WISH-391 full5 run: the party won, and the run stalled on the treasure bar
    with no SHARE button from 190 to 313, its picture animating through three frames."""
    shots = scratch.cache_dir("acceptance") / "WISH-391" / "full5" / "screens"
    frames = {n: shots / f"{n}-fight.png" for n in numbers}
    if not all(p.is_file() for p in frames.values()):
        pytest.skip("the WISH-391 full5 frames are not on this machine")
    return frames


def _committed_guards(tmp_path):
    path = tmp_path / "guards.json"
    path.write_text(json.dumps(ssbfight.guard_rules()))
    return PixelGuards(path)


def test_the_won_page_rule_reads_the_won_page_only(tmp_path):
    # 188 is CONTINUE BATTLE, 189 the won page that got RETURN, 190 the treasure bar after it.
    frames = _full5("188", "189", "190")
    guards = _committed_guards(tmp_path)
    assert {s for s in ssbfight.KNOWN if guards(s, frames["189"])} == {"party_won", "continue"}
    assert ssbfight.KNOWN.index("party_won") < ssbfight.KNOWN.index("continue")
    assert not guards("party_won", frames["188"]) and not guards("party_won", frames["190"])


def test_the_shareless_treasure_bar_rule_reads_every_frame_of_the_stall(tmp_path):
    # 190, 191 and 194 are the three animation frames; 313 is the last before the stop.
    frames = _full5("189", "190", "191", "194", "313")
    guards = _committed_guards(tmp_path)
    for n in ("190", "191", "194", "313"):
        assert [s for s in ssbfight.KNOWN if guards(s, frames[n])] == ["treasure_bar_no_share"], n
    assert not guards("treasure_bar_no_share", frames["189"])


def test_drive_leaves_a_won_fight_by_exit_and_saves(tmp_path, monkeypatch):
    clock = Clock()
    loaded = [_member(name) for name in NAMES]
    after = [_member(name, quickfight=1) for name in NAMES]
    # The map holds for the fight loop's settle, then the save starts from it.
    script = [*DRIVE[:11], "continue", "combat_bar", "combat_bar", None, "continue_battle",
              "party_won", "treasure_bar_no_share", "treasure", "world", "world", "world",
              *DRIVE[11:]]
    game = Game(clock, script, owners=[_owner("PAINE")], parties=[loaded, after])
    game.walking = False
    monkeypatch.setattr(ssbfight, "wander", lambda *a: {"steps": [], "met": "shot"})
    screens = _screens(tmp_path, game, clock)
    found = ssbfight.drive(screens, _manifest(), ["PAINE"], game,
                           lambda *a: (0, "answered"), save=True)
    assert found["outcome"] == "won" and found["won_page"]
    assert game.keys == ["ESC", "P", "L", "D", "B", "RET", "Q", "N", "RET", "E", "N",
                         "E", "S", "E", "N"]
    assert game.pressed_on[9:11] == ["treasure_bar_no_share", "treasure"]
    _keys_allowed(screens, game)


@pytest.mark.parametrize("end, last", [("party_destroyed", ["RET"]), ("party_menu", []),
                                       ("loaded_menu", []), ("title", [])])
def test_fight_records_a_lost_fight_and_presses_nothing_after(tmp_path, end, last):
    clock = Clock()
    game = Game(clock, ["continue", None, "combat_bar", "combat_bar", None, end, "world"],
                owners=[_owner("PAINE")])
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    found = ssbfight.fight(screens, game, ["Guy de Valois"])
    # The defeat screen gets its one key and nothing after it is grabbed.
    assert found["outcome"] == "lost" and game.keys == ["RET", "Q", *last]
    assert game.script == ["world"]
    _keys_allowed(screens, game)


def test_the_party_destroyed_rule_reads_the_defeat_frame_only(tmp_path):
    shots = scratch.cache_dir("acceptance") / "WISH-391" / "full2" / "screens"
    # The message held from 146 to the stop at 165; 145 is the last battlefield frame.
    frames = {n: shots / f"{n}-fight.png" for n in ("070", "145", "146", "165")}
    if not all(p.is_file() for p in frames.values()):
        pytest.skip("the WISH-391 full2 frames are not on this machine")
    path = tmp_path / "guards.json"
    path.write_text(json.dumps(ssbfight.guard_rules()))
    guards = PixelGuards(path)
    assert guards("party_destroyed", frames["146"]) and guards("party_destroyed", frames["165"])
    assert not guards("party_destroyed", frames["145"])
    assert not guards("party_destroyed", frames["070"])


def test_fight_leaves_its_bars_and_answers_when_it_stops(tmp_path):
    clock = Clock()
    game = Game(clock, ["continue", None, "combat_bar", "combat_bar", None, "camp"],
                owners=[_owner("PAINE")])
    game.walking = False
    found = {}
    with pytest.raises(RouteError, match="camp showed mid-fight"):
        ssbfight.fight(_screens(tmp_path, game, clock), game, ["PAINE"], found=found)
    assert [bar["owner"] for bar in found["bars"]] == ["PAINE"]
    assert [a["key"] for a in found["answered"]] == ["RET", "Q"]


def test_run_keeps_a_stopped_fights_bars_in_the_receipt(tmp_path, monkeypatch):
    def drive(*args, found, **kwargs):
        found.update(bars=[{"owner": "PAINE"}], answered=[{"screen": "combat_bar", "key": "Q"}])
        raise RouteError("a screen no guard knows stayed 90s unchanged mid-fight")

    with pytest.raises(RouteError, match="unchanged"):
        _run(tmp_path, monkeypatch, drive=drive)
    written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert written["bars"] == [{"owner": "PAINE"}] and written["answered"][0]["key"] == "Q"


def test_fight_stops_when_a_named_member_had_no_bar(tmp_path):
    clock = Clock()
    game = Game(clock, FIGHT, owners=[_owner("PAINE"), _owner("EPONA")])
    game.walking = False
    with pytest.raises(RouteError, match="no command bar"):
        ssbfight.fight(_screens(tmp_path, game, clock), game, ["Guy de Valois"])


@pytest.mark.parametrize("screen", ["camp", "exit_game", "camp_save_picker", "journal"])
def test_fight_stops_on_a_known_screen_it_does_not_answer(tmp_path, screen):
    clock = Clock()
    game = Game(clock, [None, screen])
    game.walking = False
    with pytest.raises(RouteError, match="mid-fight"):
        ssbfight.fight(_screens(tmp_path, game, clock), game, ["PAINE"])
    assert game.keys == []


def test_fight_stops_on_an_unknown_screen_that_stays_still(tmp_path):
    clock = Clock()
    game = Game(clock, [None])
    game.walking = False
    with pytest.raises(RouteError, match="no guard knows stayed"):
        ssbfight.fight(_screens(tmp_path, game, clock), game, ["PAINE"])
    assert game.keys == []


def test_fight_stops_when_the_map_comes_back_with_no_bar(tmp_path):
    clock = Clock()
    game = Game(clock, ["continue", "world"])
    game.walking = False
    with pytest.raises(RouteError, match="world showed mid-fight"):
        ssbfight.fight(_screens(tmp_path, game, clock), game, ["PAINE"])
    assert game.keys == ["RET"]


# -- the capture ------------------------------------------------------------------------------

def test_capture_waits_out_a_monster_turn_and_keeps_a_members_bar(tmp_path, monkeypatch):
    clock = Clock()
    still = [None] * 40
    game = Game(clock, ["continue", *still], owners=[_owner("BC WIZARD", side=1)] * 12
                + [_owner("PAINE")])
    game.walking = False
    found = ssbfight.capture(_screens(tmp_path, game, clock), game, before=0)
    assert found["outcome"] == "bar" and found["owner"]["name"] == "PAINE"
    assert game.keys == ["RET"]


def test_capture_does_not_take_a_companions_turn_for_a_bar(tmp_path):
    clock = Clock()
    game = Game(clock, [None], owners=[_owner("SIEGLINDA", control=0xB3)])
    game.walking = False
    with pytest.raises(RouteError, match="no member's command bar"):
        ssbfight.capture(_screens(tmp_path, game, clock), game, before=0)
    assert game.keys == []


def test_capture_does_not_take_a_stale_turn_pointer_for_a_bar(tmp_path):
    # The pointer still names PAINE's record from a fight before the walk.
    clock = Clock()
    game = Game(clock, [None], owners=[_owner("PAINE")])
    game.walking = False
    with pytest.raises(RouteError, match="no member's command bar"):
        ssbfight.capture(_screens(tmp_path, game, clock), game, before=0xC50000)
    assert game.keys == []


def test_capture_marks_a_bar_known_only_by_stillness_unconfirmed(tmp_path):
    clock = Clock()
    game = Game(clock, [None], owners=[_owner("PAINE")])
    game.walking = False
    found = ssbfight.capture(_screens(tmp_path, game, clock), game, before=0)
    assert found["outcome"] == "bar" and found["confirmed"] is False


def test_capture_confirms_a_bar_the_guard_knows(tmp_path):
    clock = Clock()
    game = Game(clock, ["combat_bar"], owners=[_owner("PAINE")])
    game.walking = False
    found = ssbfight.capture(_screens(tmp_path, game, clock), game, before=0)
    assert found["outcome"] == "bar" and found["confirmed"] is True


def test_capture_records_a_party_destroyed_before_any_bar(tmp_path):
    clock = Clock()
    game = Game(clock, ["continue", None, "party_menu"], owners=[None])
    game.walking = False
    found = ssbfight.capture(_screens(tmp_path, game, clock), game, before=0)
    assert found["outcome"] == "lost" and game.keys == ["RET"]


# -- the whole drive ---------------------------------------------------------------------------

#: Boot to the title, load slot D, begin past the journal; the walk and the fight are replaced;
#: then camp, the save with the journal before the picker, and the exit question.
DRIVE = [None, "credits", "title", "party_menu", "load_picker", None, "scrolls_dropped",
         "loaded_menu", "loaded_menu", "journal", "world", "world", "camp", "journal",
         "camp_save_picker", None, "exit_game", "exit_game", "camp"]


def _drive(tmp_path, monkeypatch, *, save=True, capture_only=False, outcome="won",
           parties=None, script=DRIVE, retries=0, fight=None, found=None, manifest=None):
    clock = Clock()
    loaded = [_member(name) for name in NAMES]
    after = [_member(name, quickfight=1) for name in NAMES]
    game = Game(clock, script, parties=parties or [loaded, after])
    game.walking = False
    answers = []
    monkeypatch.setattr(ssbfight, "wander", lambda *a: {"steps": [], "met": "shot"})
    outcomes = [outcome] if isinstance(outcome, str) else list(outcome)
    monkeypatch.setattr(ssbfight, "fight", fight or (lambda *a, **k: {
        "outcome": outcomes.pop(0), "bars": [{"owner": "PAINE"}]}))
    monkeypatch.setattr(ssbfight, "capture", lambda *a: {"outcome": "bar"})

    def answer(holder, adf, timeout):
        answers.append(game.current)
        return 0, "answered"

    screens = _screens(tmp_path, game, clock)
    found = ssbfight.drive(screens, manifest or _manifest(), ["PAINE"], game, answer, save=save,
                           capture_only=capture_only, retries=retries, found=found)
    return found, game, screens, answers


def test_after_defeat_keeps_every_screen_and_names_where_it_rests(tmp_path):
    clock = Clock()
    game = Game(clock, [None, "party_destroyed", None, "title", "title", "credits"])
    game.walking = False
    found = ssbfight.after_defeat(_screens(tmp_path, game, clock))
    assert found["landing"] == "title" and len(found["screens"]) == 5
    assert found["screens"][3]["states"] == ["title"] and game.keys == []


def test_after_defeat_names_no_landing_when_none_holds(tmp_path):
    clock = Clock()
    game = Game(clock, [None, "load_anyway"])
    game.walking = False
    found = ssbfight.after_defeat(_screens(tmp_path, game, clock))
    assert found["landing"] is None and game.keys == []
    assert clock.now >= ssbfight.AFTER_DEFEAT_LIMIT


#: Attempt one to the map, a defeat that rests on the party menu, attempt two from the load
#: picker to the map, then the won fight's camp save.
RETRY = [None, "credits", "title", "party_menu", "load_picker", "loaded_menu", "journal",
         "world", "party_menu", "party_menu", "load_picker", "loaded_menu", "journal", "world",
         "world", "camp", "camp_save_picker", "exit_game", "camp"]


def test_drive_retries_a_lost_fight_from_the_party_menu_and_saves_the_win(tmp_path,
                                                                        monkeypatch):
    loaded = [_member(name) for name in NAMES]
    after = [_member(name, quickfight=1) for name in NAMES]
    found, game, screens, answers = _drive(
        tmp_path, monkeypatch, outcome=["lost", "won"], script=RETRY, retries=1,
        parties=[loaded, loaded, after])
    assert game.keys == ["ESC", "P", "L", "D", "B", "L", "D", "B", "E", "S", "E", "N"]
    assert [a["outcome"] for a in found["attempts"]] == ["lost", "won"]
    assert found["attempts"][0]["after_defeat"]["landing"] == "party_menu"
    assert found["outcome"] == "won" and answers == ["journal", "journal"]
    _keys_allowed(screens, game)


def test_drive_without_retries_records_where_the_defeat_rested(tmp_path, monkeypatch):
    found, game, _, _ = _drive(tmp_path, monkeypatch, outcome="lost", script=RETRY[:10])
    assert game.keys == ["ESC", "P", "L", "D", "B"]
    assert found["outcome"] == "lost"
    assert found["attempts"][0]["after_defeat"]["landing"] == "party_menu"


def test_drive_stops_retrying_on_a_landing_with_no_measured_way_back(tmp_path, monkeypatch):
    script = [*RETRY[:8], "loaded_menu", "loaded_menu"]
    with pytest.raises(RouteError, match="no measured way back"):
        _drive(tmp_path, monkeypatch, outcome=["lost", "won"], script=script, retries=1)


def test_drive_loads_begins_fights_and_saves_once(tmp_path, monkeypatch):
    found, game, screens, answers = _drive(tmp_path, monkeypatch)
    assert game.keys == ["ESC", "P", "L", "D", "B", "E", "S", "E", "N"]
    assert answers == ["journal", "journal"]
    assert found["members"]["PAINE"]["quickfight"] == 1
    assert found["saved"] == "E"
    _keys_allowed(screens, game)


def _staged_hp(value):
    manifest = _manifest()
    manifest["fight"]["staged_records"] = [
        {"member": 2, "name": "PAINE", "fields": {"hp_current": {"before": 8, "after": value}}}]
    return manifest


def test_begin_goes_on_when_the_loaded_hit_points_are_the_staged_ones(tmp_path, monkeypatch):
    found, _, _, _ = _drive(tmp_path, monkeypatch, manifest=_staged_hp(8))
    assert found["outcome"] == "won"


def test_begin_stops_when_the_game_did_not_keep_a_staged_hit_point_value(tmp_path, monkeypatch):
    with pytest.raises(RouteError, match="PAINE was staged at 150 hit points; the game holds 8"):
        _drive(tmp_path, monkeypatch, manifest=_staged_hp(150))


def test_drive_reads_the_gate_and_the_turn_pointer_before_the_walk(tmp_path, monkeypatch):
    found, _, _, _ = _drive(tmp_path, monkeypatch)
    assert found["wander_gate_4C2D"] == 1 and found["turn_before"] == 0


def test_drive_stops_on_the_map_when_the_running_gate_is_not_one(tmp_path, monkeypatch):
    monkeypatch.setattr(Game, "variable", lambda self, var: 0)
    with pytest.raises(RouteError, match="4C2D"):
        _drive(tmp_path, monkeypatch)


def test_drive_with_capture_stops_after_the_walk(tmp_path, monkeypatch):
    found, game, screens, _ = _drive(tmp_path, monkeypatch, capture_only=True)
    assert game.keys == ["ESC", "P", "L", "D", "B"] and found["capture"] == {"outcome": "bar"}


def test_drive_saves_nothing_after_a_lost_fight(tmp_path, monkeypatch):
    found, game, _, _ = _drive(tmp_path, monkeypatch, outcome="lost")
    assert game.keys[-1] == "B" and found["outcome"] == "lost" and "members" not in found


def test_drive_stops_when_the_loaded_party_differs(tmp_path, monkeypatch):
    loaded = [_member(name) for name in NAMES[:-1]]
    with pytest.raises(RouteError, match="loaded party"):
        _drive(tmp_path, monkeypatch, parties=[loaded, loaded])


def test_drive_stops_before_saving_when_a_member_fell(tmp_path, monkeypatch):
    loaded = [_member(name) for name in NAMES]
    fallen = [_member(name, quickfight=1) for name in NAMES]
    fallen[1]["hit_points"] = 0
    with pytest.raises(RouteError, match="fell"):
        _drive(tmp_path, monkeypatch, parties=[loaded, fallen])


@pytest.mark.parametrize("on, key", [("world", "S"), ("camp", "E"), ("combat_bar", "D"),
                                     ("combat_bar", "SPACE"), ("journal", "RET"),
                                     ("party_destroyed", "N"), ("loaded_menu", "D")])
def test_a_key_outside_the_allowlist_is_never_sent(tmp_path, on, key):
    clock = Clock()
    game = Game(clock)
    screens = _screens(tmp_path, game, clock)
    with pytest.raises(RouteError, match="not a key"):
        screens.press(key, on)
    assert game.keys == [] and screens.events == []


# -- the run ----------------------------------------------------------------------------------

class LaneGuest:
    def __init__(self):
        self.calls = []

    def _run(self, *args, timeout):
        self.calls.append(args)
        return '{"muted": true}'

    def silence(self, proof):
        return True


def _staged(tmp_path):
    manifest = _manifest()
    disks = {}
    for key in ("df0", "df1"):
        path = tmp_path / f"{key}.adf"
        path.write_bytes(key.encode())
        disks[key] = {"path": str(path), "sha256": hashlib.sha256(key.encode()).hexdigest()}
    source = tmp_path / "source.adf"
    source.write_bytes(b"source")
    manifest.update({"disks": disks, "registered": {}})
    manifest["fight"]["source"] = {"path": str(source),
                                   "sha256": hashlib.sha256(b"source").hexdigest()}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    return path


def _args(tmp_path, manifest, members=("PAINE",), no_save=False, capture=False,
          journal_python="python"):
    return argparse.Namespace(manifest=manifest, holder="holder", out=tmp_path / "run",
                              budget=600, wait_lane=0, member=list(members), no_save=no_save,
                              capture=capture, journal_python=journal_python)


@pytest.mark.parametrize("problem", ["out_exists", "not_staged", "hash", "slot_taken",
                                     "unknown_member", "no_journal", "no_bar_guard"])
def test_run_stops_before_the_guest(tmp_path, monkeypatch, problem):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(ssbfight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(ssbfight.amiga_savegame, "slots_present", lambda disk, title: ["D"])
    rules = {**ssbfight.guard_rules(), "combat_bar": ssbfight.TREASURE_SHORT}
    monkeypatch.setattr(ssbfight, "guard_rules", lambda: rules)
    kwargs = {}
    if problem == "out_exists":
        (tmp_path / "run").mkdir()
    elif problem == "not_staged":
        value = json.loads(manifest.read_text())
        del value["fight"]
        manifest.write_text(json.dumps(value))
    elif problem == "hash":
        (tmp_path / "df1.adf").write_bytes(b"changed")
    elif problem == "slot_taken":
        monkeypatch.setattr(ssbfight.amiga_savegame, "slots_present",
                            lambda disk, title: ["D", "E"])
    elif problem == "unknown_member":
        kwargs["members"] = ("BRUTUS",)
    elif problem == "no_journal":
        kwargs["journal_python"] = None
    else:
        del rules["combat_bar"]
    guest = LaneGuest()
    with pytest.raises(RouteError):
        ssbfight.run(_args(tmp_path, manifest, **kwargs), guest=guest, guards=object(),
                     boot=pytest.fail, halt=pytest.fail, memory=object(),
                     preflight=lambda python: None)
    assert guest.calls == []


def _run(tmp_path, monkeypatch, *, drive, problems=(), no_save=False, capture=False,
         members=("PAINE",), verdict=None, read=None):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(ssbfight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(ssbfight.amiga_savegame, "slots_present", lambda disk, title: ["D"])
    monkeypatch.setattr(ssbfight.curseadd, "mute", lambda guest, out, timeout: out / "mute.json")
    monkeypatch.setattr(ssbfight, "drive", drive)
    rules = {**ssbfight.guard_rules(), "combat_bar": ssbfight.TREASURE_SHORT}
    monkeypatch.setattr(ssbfight, "guard_rules", lambda: rules)
    fetched = tmp_path / "fetched-df0.adf"
    fetched.write_bytes(b"fetched")
    monkeypatch.setattr(ssbfight, "read_back", lambda path, value: read or {"path": str(path)})
    shown = []
    monkeypatch.setattr(ssbfight, "verdict", verdict or (
        lambda found, value, members, after=None: shown.append(after) or list(problems)))
    halted = []
    receipt = None
    try:
        receipt = ssbfight.run(
            _args(tmp_path, manifest, members=members, no_save=no_save, capture=capture),
            guest=LaneGuest(),
            guards=object(), boot=lambda *a, **k: {"claim": "ok"}, memory=object(),
            preflight=lambda python: None,
            halt=lambda *a, **k: halted.append(k) or {"fetched": {"df0": {"path": str(fetched)}}})
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


@pytest.mark.parametrize("problems", [[], ["PAINE was saved with quickfight 0"]])
def test_run_succeeds_only_on_a_clean_read_back(tmp_path, monkeypatch, problems):
    drive = lambda *a, **k: {"outcome": "won", "bars": []}  # noqa: E731
    if problems:
        with pytest.raises(RouteError, match="quickfight"):
            _run(tmp_path, monkeypatch, drive=drive, problems=problems)
    else:
        receipt, written, halted = _run(tmp_path, monkeypatch, drive=drive)
        assert receipt["success"] and written["source_hashes"] == "unchanged" and halted


@pytest.mark.parametrize("retries, capture", [(4, False), (1, True), (-1, False)])
def test_run_bounds_the_retries_before_the_guest(tmp_path, monkeypatch, retries, capture):
    manifest = _staged(tmp_path)
    args = _args(tmp_path, manifest, capture=capture)
    args.retry_lost = retries
    guest = LaneGuest()
    with pytest.raises(RouteError, match="retry-lost"):
        ssbfight.run(args, guest=guest, guards=object(), boot=pytest.fail, halt=pytest.fail,
                     memory=object(), preflight=lambda python: None)
    assert guest.calls == []


def test_run_fails_a_lost_fight_and_reads_nothing_back(tmp_path, monkeypatch):
    drive = lambda *a, **k: {"outcome": "lost", "bars": []}  # noqa: E731
    with pytest.raises(RouteError, match="destroyed"):
        _run(tmp_path, monkeypatch, drive=drive)
    written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert "read_back" not in written and written["halt"]
    assert written["saved"] is None and "save" not in written
    assert written["save_requested"] is True


def test_run_with_capture_saves_nothing_and_needs_no_bar_guard(tmp_path, monkeypatch):
    seen = {}

    def drive(screens, manifest, members, memory, answer, *, save, capture_only, retries,
              found):
        seen.update(save=save, capture_only=capture_only, retries=retries)
        return {"capture": {"outcome": "bar", "shot": "s.png", "confirmed": True,
                            "support": "the combat_bar guard"}}

    receipt, _written, _halted = _run(tmp_path, monkeypatch, drive=drive, capture=True)
    assert seen == {"save": False, "capture_only": True, "retries": 0}
    assert receipt["success"] and "read_back" not in receipt


def test_run_keeps_the_readings_made_before_a_step_stopped(tmp_path, monkeypatch):
    def drive(*args, found, **kwargs):
        found.update(wander_gate_4C2D=1, turn_before=0)
        raise RouteError("a screen no guard knows stayed 90s unchanged mid-fight")

    with pytest.raises(RouteError, match="unchanged"):
        _run(tmp_path, monkeypatch, drive=drive)
    written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert written["wander_gate_4C2D"] == 1 and written["turn_before"] == 0
    assert not written["success"]


def test_run_fails_a_capture_nothing_confirms(tmp_path, monkeypatch):
    def drive(*args, **kwargs):
        return {"capture": {"outcome": "bar", "shot": "s.png", "confirmed": False,
                            "support": "stillness and the turn pointer only"}}

    with pytest.raises(RouteError, match="nothing confirms"):
        _run(tmp_path, monkeypatch, drive=drive, capture=True)
    written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert written["success"] is False and written["halt"]


def test_run_checks_the_journal_interpreter_before_the_boot(tmp_path, monkeypatch):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(ssbfight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(ssbfight.amiga_savegame, "slots_present", lambda disk, title: ["D"])

    def preflight(python):
        raise RouteError(f"the journal interpreter {python!r} cannot import numpy and PIL")

    guest = LaneGuest()
    with pytest.raises(RouteError, match="numpy"):
        ssbfight.run(_args(tmp_path, manifest, capture=True), guest=guest, guards=object(),
                     boot=pytest.fail, halt=pytest.fail, memory=object(), preflight=preflight)
    assert guest.calls == []


def test_read_needs_a_member(tmp_path, capsys):
    assert ssbfight.main(["read", "--manifest", str(tmp_path / "m.json"),
                          "--disk", str(tmp_path / "d.adf")]) == 2
    assert "at least one --member" in capsys.readouterr().err


def test_memory_reads_silver_blades_records_through_the_shared_reader():
    raw = bytearray(ssbfight.RECORD_SIZE)
    for field, at in ssbfight.RECORD.items():
        raw[at] = len(field)
    memory = ssbfight.Memory("holder")
    assert memory.fields(bytes(raw)) == {field: len(field) for field in ssbfight.RECORD}
    assert (memory.title, memory.current) == (ssbfight.TITLE, 0x516C)
    assert ssbfight.cursefight.Memory("holder").current == ssbfight.cursefight.CURRENT


def test_drive_top_level_describes_the_latest_attempt_when_it_stops(tmp_path, monkeypatch):
    calls = []

    def fight(*args, found, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {"outcome": "lost", "bars": [{"owner": "PAINE"}]}
        found["bars"] = []
        raise RouteError("stopped in the second fight")

    loaded = [_member(name) for name in NAMES]
    top = {}
    with pytest.raises(RouteError, match="second fight"):
        _drive(tmp_path, monkeypatch, script=RETRY[:14], retries=1, fight=fight, found=top,
               parties=[loaded, loaded])
    assert len(top["attempts"]) == 2
    assert "outcome" not in top and top["bars"] == []
    assert top["walk"] == top["attempts"][1]["walk"]


def test_drive_top_level_drops_the_earlier_attempts_readings_when_begin_stops(tmp_path,
                                                                           monkeypatch):
    loaded = [_member(name) for name in NAMES]
    top = {}
    with pytest.raises(RouteError):
        _drive(tmp_path, monkeypatch, outcome=["lost", "won"], script=RETRY[:12], retries=1,
               found=top, parties=[loaded, loaded[:-1]])
    assert "outcome" not in top and "bars" not in top and "walk" not in top
    assert top["loaded"] == loaded[:-1]


def test_drive_keeps_a_stopped_fights_partial_bars_at_the_top_without_retries(tmp_path,
                                                                           monkeypatch):
    def fight(*args, found, **kwargs):
        found["bars"] = [{"owner": "PAINE"}]
        raise RouteError("mid-fight")

    top = {}
    with pytest.raises(RouteError, match="mid-fight"):
        _drive(tmp_path, monkeypatch, script=RETRY[:8], fight=fight, found=top)
    assert top["bars"] == [{"owner": "PAINE"}]


def test_after_defeat_keeps_the_frames_taken_when_it_stops(tmp_path):
    clock = Clock()
    game = Game(clock, [None, "party_destroyed", None])
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    real, grabs = screens.look, []

    def look(label):
        if len(grabs) == 2:
            raise RouteError("deadline")
        grabs.append(1)
        return real(label)

    screens.look = look
    into = {}
    with pytest.raises(RouteError, match="deadline"):
        ssbfight.after_defeat(screens, into)
    assert len(into["screens"]) == 2 and into["landing"] is None


@pytest.mark.parametrize("landing, script, keys", [
    ("credits", [None, "credits", "title", "party_menu", "load_picker"], ["ESC", "P", "L"]),
    ("title", ["title", "party_menu", "load_picker"], ["P", "L"]),
    ("load_picker", ["load_picker"], []),
    ("party_menu", ["party_menu", "load_picker"], ["L"]),
])
def test_to_load_picker_reaches_the_picker_from_each_landing(tmp_path, landing, script, keys):
    clock = Clock()
    game = Game(clock, script)
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    ssbfight.to_load_picker(screens, landing)
    assert game.keys == keys
    _keys_allowed(screens, game)


def test_drive_with_retries_spent_ends_lost_after_every_attempt_and_saves_nothing(tmp_path,
                                                                               monkeypatch):
    loaded = [_member(name) for name in NAMES]
    found, game, _, _ = _drive(
        tmp_path, monkeypatch, outcome=["lost", "lost"], script=RETRY, retries=1,
        parties=[loaded, loaded])
    assert found["outcome"] == "lost"
    assert [a["outcome"] for a in found["attempts"]] == ["lost", "lost"]
    assert not {"E", "S", "N"} & set(game.keys)


# -- a run that names no member -----------------------------------------------------------------

def _petrified_party():
    """Five members turned to stone and one standing, all holding quickfight 1."""
    return [_member(name, quickfight=1, status=0 if name == NAMES[0] else 7,
                    hit_points=150 if name == NAMES[0] else 0) for name in NAMES]


def _saved_manifest_read(party):
    return {"verify": [], "loaded_slot_unchanged": True, "members": [dict(m) for m in party]}


def test_run_without_a_member_reaches_the_read_back_after_a_won_fight(tmp_path, monkeypatch):
    after = _petrified_party()

    def drive(*a, found, **k):
        found.update(outcome="won", saved="E", after=after, bars=[{"owner": "PAINE"}])
        return found

    read = _saved_manifest_read(after)
    manifest = _manifest()
    real_verdict = ssbfight.verdict
    receipt, written, _ = _run(tmp_path, monkeypatch, drive=drive, members=(), read=read,
                               verdict=lambda found, value, members, after=None:
                               real_verdict(found, manifest, members, after))
    assert receipt["success"] and written["problems"] == [] and written["saved"] == "E"


def test_run_without_a_member_fails_a_win_that_was_not_saved(tmp_path, monkeypatch):
    drive = lambda *a, **k: {"outcome": "won", "after": [], "bars": []}  # noqa: E731
    with pytest.raises(RouteError, match="not a won fight saved"):
        _run(tmp_path, monkeypatch, drive=drive, members=(),
             verdict=lambda found, value, members, after=None: [])


def test_check_bars_stops_when_a_bar_owner_holds_quickfight_zero():
    party = [_member(name, quickfight=1) for name in NAMES]
    party[1]["quickfight"] = 0
    with pytest.raises(RouteError, match="PAINE had a command bar and holds quickfight 0"):
        ssbfight.check_bars(party, [{"owner": "PAINE"}])


def test_check_bars_ignores_status_and_hit_points():
    party = _petrified_party()
    assert set(ssbfight.check_bars(party, [{"owner": "PAINE"}, {"owner": "PAINE"}])) == {"PAINE"}


def test_drive_without_members_saves_a_win_that_petrified_five(tmp_path, monkeypatch):
    loaded = [_member(name) for name in NAMES]
    found, game, _, _ = _drive_nomembers(tmp_path, monkeypatch, [loaded, _petrified_party()])
    assert found["saved"] == "E" and set(found["members"]) == {"PAINE"}


def _drive_nomembers(tmp_path, monkeypatch, parties):
    clock = Clock()
    game = Game(clock, DRIVE, parties=parties)
    game.walking = False
    monkeypatch.setattr(ssbfight, "wander", lambda *a: {"steps": [], "met": "shot"})
    monkeypatch.setattr(ssbfight, "fight", lambda *a, **k: {
        "outcome": "won", "bars": [{"owner": "PAINE"}]})
    found = ssbfight.drive(_screens(tmp_path, game, clock), _manifest(), [], game,
                           lambda holder, adf, timeout: (0, "answered"), save=True)
    return found, game, None, None


def test_verdict_without_a_member_compares_the_save_with_the_party_after_the_fight():
    after = _petrified_party()
    same = _saved_manifest_read(after)
    assert ssbfight.verdict(same, _manifest(), [], after) == []
    for field, value in (("status", 0), ("hit_points", 5), ("side", 1)):
        moved = _saved_manifest_read(after)
        moved["members"][1][field] = value
        problems = ssbfight.verdict(moved, _manifest(), [], after)
        assert len(problems) == 1 and "PAINE" in problems[0]


def test_check_bars_stops_when_nobody_had_a_command_bar():
    with pytest.raises(RouteError, match="no member having a command bar"):
        ssbfight.check_bars(_petrified_party(), [])


# -- the save-only mode ------------------------------------------------------------------------

def test_the_picture_offset_is_where_the_field_map_puts_the_combat_picture():
    # The same DOS field Curse keeps at 0x126 and its Amiga record at 0x127.
    dos = {f.name: f.offset for f in dos_port.layout_for(dos_port.SECRET_OF_THE_SILVER_BLADES)}
    assert ssbfight.RECORD["picture"] == amiga_port.SILVER_BLADES_DELTAS.offset(dos["unnamed_0ab"])


class _Disk:
    """Enough of an ADF for `stage`: one slot file, verified, copied as bytes."""

    def __init__(self, data):
        self.data = data

    def verify(self):
        return []

    def read_file(self, path):
        return self.data

    def save(self, path):
        pass


def _stage_without_a_fight(tmp_path, monkeypatch, *, fight, area=68, save="B"):
    source, diskb = tmp_path / "a.adf", tmp_path / "b.adf"
    source.write_bytes(b"disk one")
    diskb.write_bytes(b"disk two")
    state = types.SimpleNamespace(area=area, x=2, y=3, facing=1)
    members = [types.SimpleNamespace(name=n, raw=bytes(ssbfight.RECORD_SIZE)) for n in NAMES]
    saved = types.SimpleNamespace(characters=members, blocks=(), data=b"slot")
    monkeypatch.setattr(ssbfight.route_silver_blades, "DISK_B_SHA256", ssbfight.sha256(diskb))
    monkeypatch.setattr(ssbfight.amiga_adf.AmigaDisk, "open", lambda path: _Disk(b"slot"))
    monkeypatch.setattr(ssbfight.amiga_savegame, "slots_present", lambda disk, title: ["A"])
    monkeypatch.setattr(ssbfight.amiga_savegame, "state_from_savegame", lambda slot: state)
    monkeypatch.setattr(ssbfight.world_state, "has_not_set_out", lambda s: False)
    monkeypatch.setattr(ssbfight, "_slot", lambda disk, letter: saved)
    monkeypatch.setattr(ssbfight, "with_word", lambda data, address, value: b"gate")
    monkeypatch.setattr(ssbfight, "word", lambda data, address: 1 if data == b"gate" else 0)
    monkeypatch.setattr(ssbfight, "area_map", lambda diskb: pytest.fail("no map is read"))
    written = []
    monkeypatch.setattr(ssbfight, "replace_file_in_place",
                        lambda disk, path, data: written.append(data))
    monkeypatch.setattr(ssbfight, "wander_plan", lambda geo, start: PLAN)
    path = ssbfight.stage(source, tmp_path / "out", load="A", save=save, diskb=diskb, fight=fight)
    return json.loads(path.read_text())["fight"], written


def test_stage_without_a_fight_takes_a_slot_in_any_area_and_plants_no_gate(tmp_path, monkeypatch):
    fight, written = _stage_without_a_fight(tmp_path, monkeypatch, fight=False)
    assert fight["place"]["area"] == 68 and fight["fight"] is False
    assert fight["staged"] == {} and "route" not in fight
    assert written == [b"slot"]
    assert set(fight["members"]) == set(NAMES)
    assert all("picture" in row and "control" in row for row in fight["members"].values())


def test_stage_asking_for_a_fight_still_stops_outside_new_verdigris(tmp_path, monkeypatch):
    with pytest.raises(RouteError, match="area 68"):
        _stage_without_a_fight(tmp_path, monkeypatch, fight=True)
    assert not (tmp_path / "out").exists()


NO_FIGHT_DRIVE = [None, "credits", "title", "party_menu", "load_picker", None, "scrolls_dropped",
                  "loaded_menu", "loaded_menu", "journal", "world", "world", "camp", "journal",
                  "camp_save_picker", None, "exit_game", "exit_game", "camp"]


def test_drive_without_a_fight_loads_camps_and_saves_without_walking_or_reading_the_gate(
        tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, NO_FIGHT_DRIVE, parties=[[_member(name) for name in NAMES]])
    game.walking = False
    game.variable = pytest.fail
    for name in ("wander", "fight", "capture"):
        monkeypatch.setattr(ssbfight, name, pytest.fail)
    answers = []
    screens = _screens(tmp_path, game, clock)
    found = ssbfight.drive(screens, _manifest(), [], game,
                           lambda holder, adf, timeout: answers.append(game.current) or (0, "answered"),
                           save=True, no_fight=True)
    assert game.keys == ["ESC", "P", "L", "D", "B", "E", "S", "E", "N"]
    assert found["saved"] == "E" and "outcome" not in found and ssbfight.LIVE_GATE not in found
    _keys_allowed(screens, game)


def _saved(manifest, **changes):
    rows = [{"name": name, **{k: v for k, v in row.items()}}
            for name, row in manifest["fight"]["members"].items()]
    rows[1].update(changes)
    return {"verify": [], "loaded_slot_unchanged": True, "members": rows}


def _unfought_manifest():
    manifest = _manifest()
    for row in manifest["fight"]["members"].values():
        row.update(picture=0x16, control=0)
    manifest["fight"]["members"]["PAINE"].update(picture=0x17, control=0x80)
    return manifest


def test_the_verdict_of_an_unfought_save_is_clean_when_every_picture_and_control_is_as_loaded():
    manifest = _unfought_manifest()
    assert ssbfight.verdict(_saved(manifest), manifest, [], outcome="unfought") == []


@pytest.mark.parametrize("changes, match", [({"picture": 0x01}, "picture"),
                                            ({"control": 0}, "saved as")])
def test_the_verdict_of_an_unfought_save_checks_a_member_nobody_named(changes, match):
    manifest = _unfought_manifest()
    problems = ssbfight.verdict(_saved(manifest, **changes), manifest, [], outcome="unfought")
    assert len(problems) == 1 and "PAINE" in problems[0] and match in problems[0]


def test_the_verdict_of_a_fought_save_still_wants_a_party_after_the_fight():
    manifest = _unfought_manifest()
    problems = ssbfight.verdict(_saved(manifest), manifest, [])
    assert problems == ["no reading of the party after the fight to compare the save with"]


def test_run_without_a_fight_saves_and_judges_the_read_back_unfought(tmp_path, monkeypatch):
    seen = {}

    def drive(screens, manifest, members, memory, answer, *, save, capture_only, retries, found,
              no_fight=False):
        seen.update(save=save, no_fight=no_fight)
        return {"saved": "E"}

    def verdict(found, manifest, members, after=None, outcome="won"):
        seen["outcome"] = outcome
        return []

    manifest = _staged(tmp_path)
    value = json.loads(manifest.read_text())
    value["fight"]["fight"] = False
    manifest.write_text(json.dumps(value))
    rules = {k: v for k, v in ssbfight.guard_rules().items() if k != "combat_bar"}
    monkeypatch.setattr(ssbfight, "guard_rules", lambda: rules)
    monkeypatch.setattr(ssbfight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(ssbfight.amiga_savegame, "slots_present", lambda disk, title: ["D"])
    monkeypatch.setattr(ssbfight.curseadd, "mute", lambda guest, out, timeout: out / "mute.json")
    monkeypatch.setattr(ssbfight, "drive", drive)
    monkeypatch.setattr(ssbfight, "read_back", lambda path, value: {})
    monkeypatch.setattr(ssbfight, "verdict", verdict)
    fetched = tmp_path / "fetched-df0.adf"
    fetched.write_bytes(b"fetched")
    args = _args(tmp_path, manifest, members=())
    args.no_fight = True
    receipt = ssbfight.run(args, guest=LaneGuest(), guards=object(), memory=object(),
                           boot=lambda *a, **k: {"claim": "ok"}, preflight=lambda python: None,
                           halt=lambda *a, **k: {"fetched": {"df0": {"path": str(fetched)}}})
    assert seen == {"save": True, "no_fight": True, "outcome": "unfought"}
    assert receipt["success"] and receipt["fight"] is False


@pytest.mark.parametrize("how", ["no_save", "capture", "fight_asked_of_a_no_fight_stage"])
def test_run_stops_before_the_guest_when_the_save_only_mode_is_contradicted(tmp_path, how):
    manifest = _staged(tmp_path)
    value = json.loads(manifest.read_text())
    value["fight"]["fight"] = how != "fight_asked_of_a_no_fight_stage"
    manifest.write_text(json.dumps(value))
    args = _args(tmp_path, manifest, no_save=how == "no_save", capture=how == "capture")
    args.no_fight = how != "fight_asked_of_a_no_fight_stage"
    guest = LaneGuest()
    with pytest.raises(RouteError, match="no-fight"):
        ssbfight.run(args, guest=guest, guards=object(), boot=pytest.fail, halt=pytest.fail,
                     memory=object(), preflight=lambda python: None)
    assert guest.calls == []


@pytest.mark.parametrize("save", ["C", "F"])
def test_stage_stops_before_writing_anything_when_the_save_letter_is_one_the_boot_keeps(
        tmp_path, monkeypatch, save):
    with pytest.raises(RouteError, match=f"slot {save} is a letter the boot keeps"):
        _stage_without_a_fight(tmp_path, monkeypatch, fight=False, save=save)
    assert not (tmp_path / "out").exists()
