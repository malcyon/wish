"""The Curse tavern-fight driver: the walk, the fight's answers and bar log, and its fail-closed paths."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
from unittest import mock

import pytest

from automap import gamedisks
from tools.amiga import amigakeys, cursefight
from tools.amiga.screens import PixelGuards
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
        # One fight-mode reading per poll of an unguarded screen; the last one stays.
        self.modes = [True]

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

    mode_error = None

    def in_fight(self):
        return self.modes.pop(0) if len(self.modes) > 1 else self.modes[0]


def _screens(tmp_path, game, clock, budget=100_000):
    return cursefight.Screens(game, "holder", tmp_path / "shots", game, budget,
                              clock=clock, sleep=clock.sleep)


def _keys_allowed(screens, game):
    pressed = [event for event in screens.events if "key" in event]
    assert [event["key"] for event in pressed] == game.keys
    for event in pressed:
        assert event["key"] in type(screens).allowed[event["from"]], event


def test_guard_rules_add_the_fight_screens_to_the_curse_map():
    rules = cursefight.guard_rules()
    assert set(cursefight.KNOWN) - set(rules) <= (set(cursefight.CAST_UNCAPTURED)
                                                  | set(cursefight.CAST_UNREACHED))
    for state, rule in cursefight.FIGHT_GUARDS.items():
        assert rules[state] == rule
    assert set(cursefight.ALLOWED_KEYS) <= set(cursefight.KNOWN) | set(cursefight.PIT_KNOWN)


def test_every_allowed_key_is_an_amiga_key():
    for keys in (*cursefight.ALLOWED_KEYS.values(), *cursefight.CAST_ALLOWED_KEYS.values()):
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
#: monster turns no guard knows, then the end screens as every won brawl captured shows them
#: (THE PARTY HAS WON, treasure, the script's "tossed outside" line, one more box) and the map.
FIGHT = [None, "tavern", None, "combat_bar", "combat_bar", None, None, "combat_bar",
         "combat_bar", None, "continue_battle", "party_won", "treasure", "treasure_left",
         "tossed", "continue", "investigate", "world"]


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
    game = Game(clock, [None, "combat_bar", "combat_bar", *turns, "continue_battle", "party_won",
                        "world"], owners=[_owner("EVOKER")])
    game.walking = False
    frames = iter(range(10_000))
    monkeypatch.setattr(cursefight, "_digest", lambda shot: str(next(frames)))
    found = cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert clock.now > cursefight.FIGHT_STALL and game.keys == ["Q", "N", "RET"]
    assert found["bars"][0]["owner"] == "EVOKER"


def _animated(monkeypatch):
    frames = iter(range(100_000))
    monkeypatch.setattr(cursefight, "_digest", lambda shot: str(next(frames)))


def test_fight_stops_on_an_animated_unknown_screen_outside_a_fight(tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, [None])
    game.walking = False
    game.modes = [False]
    _animated(monkeypatch)
    with pytest.raises(RouteError, match="no guard matching"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == [] and clock.now < cursefight.FIGHT_STALL + 10


def test_fight_waits_out_a_long_unguarded_stretch_while_the_game_is_in_a_fight(
        tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, [None, "combat_bar", "combat_bar", *[None] * 240, "continue_battle",
                        "party_won", "world"], owners=[_owner("EVOKER")])
    game.walking = False
    _animated(monkeypatch)
    found = cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert clock.now > 600 and found["outcome"] == "won"


def test_fight_stops_when_the_fight_mode_ends_during_an_unguarded_stretch(tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, [None])
    game.walking = False
    game.modes = [True] * 100 + [False]
    _animated(monkeypatch)
    with pytest.raises(RouteError, match="no guard matching"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert 250 < clock.now < 250 + cursefight.FIGHT_STALL + 10


def test_the_stop_names_the_last_mode_read_error(tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, [None])
    game.walking = False
    game.modes = [False]
    game.mode_error = "OSError: pipe closed"
    _animated(monkeypatch)
    with pytest.raises(RouteError, match="mode read: OSError: pipe closed"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])


class _Pipe:
    """A located target whose mode byte reads as `modes` in turn; an Exception raises."""

    def __init__(self, monkeypatch, modes, row=5):
        from types import SimpleNamespace

        from automap import amigaparty

        self.modes = list(modes)
        self.reads = 0
        monkeypatch.setattr(amigaparty, "row_for", lambda target: SimpleNamespace(combat_value=row))
        monkeypatch.setattr(amigaparty, "mode", self.mode)

    def mode(self, target):
        self.reads += 1
        value = self.modes.pop(0) if len(self.modes) > 1 else self.modes[0]
        if isinstance(value, Exception):
            raise value
        return value


def _memory(target=object()):
    memory = cursefight.Memory("holder")
    memory._target = target
    return memory


def test_a_failed_mode_read_keeps_the_last_state_the_game_was_read_in(monkeypatch):
    _Pipe(monkeypatch, [5, OSError("pipe closed"), None, 6])
    memory = _memory()
    assert memory.in_fight() is True and memory.mode_error is None
    assert memory.in_fight() is True and "pipe closed" in memory.mode_error
    assert memory.in_fight() is True and "did not read" in memory.mode_error
    assert memory.in_fight() is False and memory.mode_error is None


def test_a_mode_read_that_never_worked_reads_as_not_in_a_fight(monkeypatch):
    _Pipe(monkeypatch, [OSError("pipe closed")])
    memory = _memory()
    assert memory.in_fight() is False and "pipe closed" in memory.mode_error


def test_a_mode_read_that_hangs_fails_after_its_limit(monkeypatch):
    import threading

    release = threading.Event()
    pipe = _Pipe(monkeypatch, [5])
    monkeypatch.setattr(pipe, "mode", lambda target: release.wait(5) and 5)
    from automap import amigaparty

    monkeypatch.setattr(amigaparty, "mode", pipe.mode)
    monkeypatch.setattr(cursefight, "MODE_READ_LIMIT", 0.05)
    memory = _memory()
    try:
        assert memory.in_fight() is False and "no answer" in memory.mode_error
    finally:
        release.set()


def test_the_mode_read_never_locates_the_game(monkeypatch):
    pipe = _Pipe(monkeypatch, [5])
    tries = []

    class Unlocated(cursefight.Memory):
        def target(self):
            tries.append(1)
            raise OSError("no machine found")

    memory = Unlocated("holder")
    for _ in range(5):
        assert memory.in_fight() is False
    assert tries == [] and pipe.reads == 0 and "not located" in memory.mode_error
    memory._target = object()
    assert memory.in_fight() is True and memory.mode_error is None


def test_fight_keeps_going_while_guards_match_and_keys_are_answered(tmp_path, monkeypatch):
    clock = Clock()
    script = [None, "combat_bar", "combat_bar", *["treasure", None] * 60,
              "continue_battle", "party_won", "world"]
    game = Game(clock, script, owners=[_owner("EVOKER")])
    game.walking = False
    game.modes = [False]
    _animated(monkeypatch)
    found = cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert clock.now > cursefight.FIGHT_STALL and found["outcome"] == "won"


@pytest.mark.parametrize("screen", ["combat_bar", "continue_battle", "treasure"])
def test_fight_stops_on_a_known_screen_that_never_changes(tmp_path, screen):
    clock = Clock()
    owners = [_owner("EVOKER") for _ in range(200)]
    game = Game(clock, [None, screen], owners=owners)
    game.walking = False
    with pytest.raises(RouteError, match="unchanged mid-fight"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert len(game.keys) < cursefight.FIGHT_STALL / cursefight.AFTER_KEY + 5


def test_fight_waits_for_the_first_bar_on_the_map_shortly_after_punch(tmp_path):
    clock = Clock()
    game = Game(clock, ["world", "world", "tavern", "combat_bar", "combat_bar", "party_won",
                        "world"], owners=[_owner("EVOKER")])
    game.walking = False
    found = cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == ["Q", "RET"] and found["bars"][0]["owner"] == "EVOKER"


def test_fight_stops_on_a_map_that_stays_after_punch(tmp_path):
    clock = Clock()
    game = Game(clock, ["world"])
    game.walking = False
    with pytest.raises(RouteError, match="world showed mid-fight"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == []


def test_fight_stops_at_its_time_limit(tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, ["treasure"])
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
    script = [None, "combat_bar", "combat_bar", None, "party_won", "world", "continue", "world"]
    game = Game(clock, script, owners=[_owner("EVOKER")])
    game.walking = False
    found = cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])
    assert game.keys == ["Q", "RET", "RET"]
    assert found["answered"][-1]["screen"] == "continue"


#: A brawl's end screens with a box the guards take for a plain `continue` where THE PARTY HAS
#: WON belongs, then the script's "tossed outside" line and the street.
UNJUDGED = ["continue_battle", "continue", "treasure", "treasure_left", "tossed", "world"]


@pytest.mark.parametrize("bars, match", [
    (True, "without the party_won screen"), (False, "world showed mid-fight")])
def test_fight_that_reaches_the_map_without_the_won_message_stops_the_run(tmp_path, bars, match):
    clock = Clock()
    start = [None, "tavern", "combat_bar", "combat_bar", None] if bars else [None, "tavern", None]
    game = Game(clock, [*start, *UNJUDGED], owners=[_owner("EVOKER")])
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    with pytest.raises(RouteError, match=match):
        cursefight.fight(screens, game, [])
    assert game.keys == [*(["Q"] if bars else []), "N", "RET", "E", "N", "RET"]
    _keys_allowed(screens, game)


def test_tavern_fight_ends_lost_on_the_destroyed_message_with_one_return(tmp_path):
    clock = Clock()
    script = [None, "tavern", "combat_bar", "combat_bar", None, "party_destroyed", "title"]
    game = Game(clock, script, owners=[_owner("EVOKER")])
    game.walking = False
    screens = _screens(tmp_path, game, clock)
    found = cursefight.fight(screens, game, ["EVOKER"])
    assert found["outcome"] == "lost" and game.keys == ["Q", "RET"]
    assert found["answered"][-1]["screen"] == "party_destroyed"
    _keys_allowed(screens, game)


def test_fight_without_the_tossed_text_still_stops_on_a_map_with_no_bar(tmp_path):
    clock = Clock()
    game = Game(clock, [None, "continue_battle", "continue", "world"])
    game.walking = False
    with pytest.raises(RouteError, match="world showed mid-fight"):
        cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])


def test_fight_reports_a_won_brawl_as_won(tmp_path):
    clock = Clock()
    game = Game(clock, FIGHT, owners=[_owner("SUNDRA"), _owner("EVOKER")])
    game.walking = False
    assert cursefight.fight(_screens(tmp_path, game, clock), game, ["EVOKER"])["outcome"] == "won"


def test_tossed_guard_matches_the_captured_text_and_not_the_frames_around_it(tmp_path):
    shots = pathlib.Path.home() / ".cache/wish/acceptance/WISH-390/run2/screens"
    frames = {n: shots / f"{n}-fight.png" for n in (113, 114, 115)}
    if not all(f.is_file() for f in frames.values()):
        pytest.skip("the WISH-390 run 2 capture is not on this machine")
    rules = tmp_path / "guards.json"
    rules.write_text(json.dumps(cursefight.guard_rules()))
    guards = PixelGuards(rules)
    assert guards("tossed", frames[114])
    assert guards("continue", frames[114])
    assert not guards("tossed", frames[113]) and not guards("tossed", frames[115])
    assert not guards("party_won", frames[114])


#: The won brawls captured, each from its CONTINUE BATTLE frame to the first map frame after
#: the brawl. In every one the game shows THE PARTY HAS WON one frame after CONTINUE BATTLE and
#: THE SURVIVORS ARE TOSSED OUTSIDE after the treasure; WISH-390's run had no command bar.
WON_BRAWLS = {
    "WISH-303/i4-dos/stage/run2": (177, 184),
    "WISH-303/i4-dos/stage/run1": (169, 176),
    "WISH-303/i4-c64/stage/run2": (215, 222),
    "WISH-390/run2": (110, 115),
}
ACCEPTANCE = pathlib.Path.home() / ".cache/wish/acceptance"


def _brawl_frames(run):
    first, last = WON_BRAWLS[run]
    frames = [ACCEPTANCE / run / "screens" / f"{n}-fight.png" for n in range(first, last + 1)]
    if not all(f.is_file() for f in frames):
        pytest.skip(f"the {run} capture is not on this machine")
    return frames


def _real_guards(tmp_path):
    rules = tmp_path / "guards.json"
    rules.write_text(json.dumps(cursefight.guard_rules()))
    return PixelGuards(rules)


@pytest.mark.parametrize("run", sorted(WON_BRAWLS))
def test_party_won_guard_names_the_won_message_and_no_other_end_screen(tmp_path, run):
    frames = _brawl_frames(run)
    guards = _real_guards(tmp_path)
    named = [next((s for s in cursefight.KNOWN if s in guards and guards(s, f)), None)
             for f in frames]
    assert named[:5] == ["continue_battle", "party_won", "treasure", "treasure_left", "tossed"]
    assert named[-1] == "world" and named.count("party_won") == 1


class FrameGame:
    """A guest and memory that show captured frames in order, the last one staying."""

    def __init__(self, clock, frames):
        self.clock, self.frames = clock, list(frames)
        self.keys: list[str] = []
        self.holder = "holder"

    def grab(self, label, raw, crop, timeout):
        self.clock.now += 1
        frame = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        pathlib.Path(crop).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(crop).write_bytes(frame.read_bytes())
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)

    def owner(self):
        raise AssertionError("the replay holds no command bar")


@pytest.mark.parametrize("run", sorted(WON_BRAWLS))
def test_a_captured_won_brawl_replays_as_won(tmp_path, run):
    clock = Clock()
    game = FrameGame(clock, _brawl_frames(run))
    screens = cursefight.Screens(game, "holder", tmp_path / "shots", _real_guards(tmp_path),
                                 100_000, clock=clock, sleep=clock.sleep)
    found = cursefight.fight(screens, game, [])
    assert found["outcome"] == "won"
    assert [a["screen"] for a in found["answered"]] == [
        "continue_battle", "party_won", "treasure", "treasure_left", "tossed",
        *(["continue", "investigate"] if run != "WISH-390/run2" else [])]


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


def _drive(tmp_path, monkeypatch, save=True, parties=None, script=DRIVE, games=None,
           outcome="won"):
    clock = Clock()
    loaded = [_member(name) for name in NAMES]
    after = [_member(name, quickfight=1) for name in NAMES]
    game = Game(clock, script, parties=parties or [loaded, after])
    game.walking = False
    if games is not None:
        games.append(game)
    walked = []
    monkeypatch.setattr(cursefight, "walk", lambda *a: walked.append(a) or [])
    monkeypatch.setattr(cursefight, "fight",
                        lambda *a: {"bars": [{"owner": "EVOKER"}], "answered": [],
                                    "outcome": outcome})
    screens = _screens(tmp_path, game, clock)
    found = cursefight.drive(screens, _manifest(), ["EVOKER"], game, save=save)
    return found, game, screens, walked


def test_drive_loads_walks_fights_and_saves_once(tmp_path, monkeypatch):
    found, game, screens, walked = _drive(tmp_path, monkeypatch)
    assert game.keys == ["ESC", "ESC", "L", "D", "RET", "RET", "B", "P", "E", "S", "F", "N"]
    assert found["load_errors"] == 2 and walked
    assert found["members"]["EVOKER"]["quickfight"] == 1
    _keys_allowed(screens, game)


def test_drive_stops_before_the_save_when_the_watched_member_died_in_a_won_brawl(
        tmp_path, monkeypatch):
    loaded = [_member(name) for name in NAMES]
    after = [_member(name, quickfight=1) for name in NAMES]
    after[-1].update(hit_points=0, status=6)
    with pytest.raises(RouteError, match="EVOKER fell"):
        _drive(tmp_path, monkeypatch, parties=[loaded, after])


def test_drive_at_the_tavern_stops_at_a_destroyed_party_saving_nothing(tmp_path, monkeypatch):
    clock = Clock()
    game = Game(clock, DRIVE, parties=[[_member(name) for name in NAMES]])
    game.walking = False
    monkeypatch.setattr(cursefight, "walk", lambda *a: [])
    monkeypatch.setattr(
        cursefight, "fight",
        lambda *a, **k: {"bars": [{"owner": "EVOKER"}],
                         "answered": [{"screen": "party_destroyed", "key": "RET"}],
                         "outcome": "lost"})
    found = cursefight.drive(_screens(tmp_path, game, clock), _manifest(), ["EVOKER"], game,
                             save=True)
    assert found["destroyed"] and "after" not in found and "members" not in found
    assert game.keys[-1] == "P"


def test_verdict_of_a_won_fight_reports_a_watched_member_saved_dead():
    members = [_member(name, quickfight=1) for name in NAMES]
    members[-1].update(hit_points=0, status=6)
    problems = cursefight.verdict(_read(members), _manifest(), ["EVOKER"], "won")
    assert any("loaded as" in p for p in problems)
    assert "EVOKER was saved at 0 hit points" in problems


def test_verdict_of_a_lost_fight_skips_the_quickfight_and_standing_checks():
    members = [_member(name) for name in NAMES]
    members[-1].update(hit_points=0, status=1)
    found = _read(members)
    assert cursefight.verdict(found, _manifest(), ["EVOKER"], "lost") == []
    assert cursefight.verdict(found, _manifest(), ["EVOKER"])


def test_verdict_of_a_lost_fight_still_catches_a_changed_control():
    members = [_member(name) for name in NAMES]
    members[-1].update(control=0)
    problems = cursefight.verdict(_read(members), _manifest(), ["EVOKER"], "lost")
    assert len(problems) == 1 and "EVOKER was saved as" in problems[0]


def test_read_takes_the_outcome_from_a_receipt_or_an_option_and_needs_one(tmp_path, capsys):
    members = [_member(name) for name in NAMES]
    members[-1].update(hit_points=0)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(_manifest()))
    found = _read(members) | {"verify": [], "loaded_slot_unchanged": True}
    receipt = tmp_path / "r.json"
    receipt.write_text(json.dumps({"outcome": "lost"}))
    base = ["read", "--manifest", str(manifest), "--disk", "d.adf", "--member", "EVOKER"]
    with mock.patch.object(cursefight, "read_back", return_value=found):
        assert cursefight.main([*base, "--receipt", str(receipt)]) == 0
        assert cursefight.main([*base, "--outcome", "lost"]) == 0
        assert cursefight.main([*base, "--outcome", "won"]) == 1
        capsys.readouterr()
        assert cursefight.main(base) == 2
    assert "one of --receipt and --outcome" in capsys.readouterr().err


def test_read_judges_a_receipt_with_no_fight_as_unfought(tmp_path, capsys):
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(_manifest()))
    found = _read([_member(name) for name in NAMES]) | {"verify": [], "loaded_slot_unchanged": True}
    base = ["read", "--manifest", str(manifest), "--disk", "d.adf", "--member", "EVOKER"]
    judged = []

    def verdict(found, manifest, members, outcome="won"):
        judged.append(outcome)
        return []

    with mock.patch.object(cursefight, "read_back", return_value=found), \
            mock.patch.object(cursefight, "verdict", verdict):
        for body in ({"fight": False}, {"outcome": "won", "fight": True}):
            receipt = tmp_path / "r.json"
            receipt.write_text(json.dumps(body))
            assert cursefight.main([*base, "--receipt", str(receipt)]) == 0
        # A receipt that neither names an outcome nor says no fight was made is
        # not guessed at.
        receipt.write_text(json.dumps({}))
        assert cursefight.main([*base, "--receipt", str(receipt)]) == 2
    assert judged == ["unfought", "won"]
    assert "not won, lost or unfought" in capsys.readouterr().err


def test_verdict_checks_the_picture_only_for_a_member_staged_with_one():
    members = [_member(name, picture=0x16) for name in NAMES]
    assert cursefight.verdict(_read(members), _manifest(), ["EVOKER"], "unfought") == []
    staged = _manifest()
    staged["fight"]["members"]["EVOKER"]["picture"] = 0x16
    members[-1]["picture"] = 0x17
    assert cursefight.verdict(_read(members), staged, ["EVOKER"], "unfought") == [
        "EVOKER was saved with picture 23, staged with 22"]


def test_drive_answers_the_injuries_question_before_the_punch_bar(tmp_path, monkeypatch):
    script = [*DRIVE[:11], "injuries", "injuries", "tavern", *DRIVE[12:]]
    found, game, screens, _walked = _drive(tmp_path, monkeypatch, script=script)
    assert game.keys == ["ESC", "ESC", "L", "D", "RET", "RET", "B", "I", "P", "E", "S", "F", "N"]
    assert game.pressed_on[7:9] == ["injuries", "tavern"]
    _keys_allowed(screens, game)


def test_drive_stops_when_the_injuries_question_stays(tmp_path, monkeypatch):
    script = [*DRIVE[:11], "injuries"]
    games = []
    with pytest.raises(RouteError, match="tavern did not show"):
        _drive(tmp_path, monkeypatch, script=script, games=games)
    # One answer only: a screen that does not go is not pressed again.
    assert games[0].keys.count("I") == 1


def test_injuries_guard_matches_the_captured_bar_and_not_the_punch_bar(tmp_path):
    shot = pathlib.Path.home() / ".cache/wish/acceptance/WISH-390/run1/screens/051-tavern.png"
    if not shot.is_file():
        pytest.skip("the WISH-390 injuries capture is not on this machine")
    rules = tmp_path / "guards.json"
    rules.write_text(json.dumps(cursefight.guard_rules()))
    guards = PixelGuards(rules)
    assert guards("injuries", shot) and not guards("tavern", shot)


def test_drive_looks_at_the_map_before_pressing_e(tmp_path, monkeypatch):
    script = [*DRIVE[:11], "tavern", "camp", *DRIVE[14:]]
    with pytest.raises(RouteError, match="expected world, saw"):
        _drive(tmp_path, monkeypatch, script=script)


def test_read_needs_a_member(tmp_path, capsys):
    assert cursefight.main(["read", "--manifest", str(tmp_path / "m.json"),
                            "--disk", str(tmp_path / "d.adf")]) == 2
    assert "at least one --member" in capsys.readouterr().err


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


@pytest.mark.parametrize("on, key", [("world", "S"), ("camp", "E"), ("combat_bar", "E"),
                                     ("aim", "E"), ("aim", "M"), ("spell_list", "E"),
                                     ("abort_spell", "Y"),
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
    monkeypatch.setattr(cursefight, "verdict", lambda found, value, members, outcome="won": list(problems))
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


@pytest.mark.parametrize("outcome", ["won", "lost"])
def test_run_records_whether_the_fight_was_won_apart_from_success(tmp_path, monkeypatch, outcome):
    drive = lambda *a, **k: {"bars": [], "outcome": outcome}  # noqa: E731
    receipt, written, _halted = _run(tmp_path, monkeypatch, drive=drive)
    assert receipt["success"] and written["fight_won"] is (outcome == "won")


def test_run_with_no_save_reads_nothing_back(tmp_path, monkeypatch):
    seen = {}

    def drive(screens, manifest, members, memory, *, save, found):
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


# -- the Pit of Moander: a wandering fight in area 17 -------------------------------------

#: The converted C64 join save's square, 1,4 facing west, and the walk `pit_plan` gives it
#: over `GEO11`: north onto 1,3, then back and forth between 1,3 and 0,3.
PIT_START = {"area": 17, "x": 1, "y": 4, "facing": 3}
PIT_PLAN = {"kind": "pit", "route": [0], "square": [1, 3], "facing": 3,
            "roll_squares": [[0, 3], [1, 3]]}


class PitGame(Game):
    """The scripted game with the Pit's screens known and the gate readable."""

    def __init__(self, clock, *args, gates=(0x80,), uncaptured=(), **kwargs):
        super().__init__(clock, *args, **kwargs)
        self.x, self.y, self.facing = PIT_START["x"], PIT_START["y"], PIT_START["facing"]
        self.gates = list(gates)
        self.uncaptured = set(uncaptured)

    def __contains__(self, state):
        return state in cursefight.PIT_KNOWN and state not in self.uncaptured

    def __call__(self, state, crop):
        return state in self and state == self.current

    def variable(self, var):
        assert var == cursefight.PIT_GATE
        return self.gates.pop(0) if len(self.gates) > 1 else self.gates[0]


def _pit_screens(tmp_path, game, clock, budget=100_000):
    return cursefight.PitScreens(game, "holder", tmp_path / "shots", game, budget,
                                 clock=clock, sleep=clock.sleep)


def _pit_manifest(save="B"):
    manifest = _manifest(save)
    manifest["fight"].update(load="A", place=dict(PIT_START), **PIT_PLAN)
    return manifest


def test_pit_walk_steps_onto_the_roll_squares_until_a_step_meets_the_monsters(tmp_path):
    clock = Clock()
    game = PitGame(clock, boxes={(0, 3)})
    screens = _pit_screens(tmp_path, game, clock)
    found = cursefight.pit_walk(screens, game, PIT_START, PIT_PLAN)
    assert game.keys == ["NP6", "NP8", "NP4", "NP8"]
    assert [(s["x"], s["y"]) for s in found["steps"]] == [(1, 3), (0, 3)]
    assert found["met"] and set(game.pressed_on) == {"world"}
    _keys_allowed(screens, game)


def test_pit_walk_sends_no_step_onto_a_square_outside_the_roll_squares(tmp_path):
    clock = Clock()
    game = PitGame(clock)
    plan = {**PIT_PLAN, "roll_squares": [[1, 3]]}
    with pytest.raises(RouteError, match="0,3 ahead of 1,3 is not one of the plan's roll squares"):
        cursefight.pit_walk(_pit_screens(tmp_path, game, clock), game, PIT_START, plan)
    assert game.keys == ["NP6", "NP8", "NP4"] and (game.x, game.y) == (1, 3)


def test_pit_walk_reads_the_square_before_each_step(tmp_path):
    clock = Clock()
    game = PitGame(clock)
    original = game.press

    def press(holder, key, timeout):
        original(holder, key, timeout)
        if key == "NP4":
            # Something moved the party along with the turn, and the turn's own read missed it.
            game.y = 2

    game.press = press
    reads = iter([(1, 4, 3), (1, 4, 0), (1, 4, 0), (1, 3, 0), (1, 3, 3)])
    game.fix = lambda: next(reads, (game.x, game.y, game.facing))
    with pytest.raises(RouteError, match="stands at .*no step was sent"):
        cursefight.pit_walk(_pit_screens(tmp_path, game, clock), game, PIT_START, PIT_PLAN)
    assert game.keys == ["NP6", "NP8", "NP4"]


def test_pit_walk_stops_when_the_party_is_not_where_the_slot_put_it(tmp_path):
    clock = Clock()
    game = PitGame(clock)
    game.x = 2
    with pytest.raises(RouteError, match="stands at"):
        cursefight.pit_walk(_pit_screens(tmp_path, game, clock), game, PIT_START, PIT_PLAN)
    assert game.keys == []


def test_pit_walk_stops_after_its_step_limit(tmp_path):
    clock = Clock()
    game = PitGame(clock)
    with pytest.raises(RouteError, match="4 steps .* met no fight"):
        cursefight.pit_walk(_pit_screens(tmp_path, game, clock), game, PIT_START, PIT_PLAN,
                            limit=4)
    assert game.keys.count("NP8") == 5


#: A Pit fight: the encounter's page, the slugs' question, the map still drawn while the
#: monsters load, two bars, then the end screens and the map.
PIT_FIGHT = ["continue", "attack_evade", "world", None, "combat_bar", "combat_bar", None,
             "combat_bar", "combat_bar", None, "continue_battle", "treasure", "treasure_left",
             "world"]


def test_pit_fight_answers_attack_and_logs_the_first_bar(tmp_path):
    clock = Clock()
    game = PitGame(clock, PIT_FIGHT, owners=[_owner("SUNDRA"), _owner("EVOKER")])
    game.walking = False
    screens = _pit_screens(tmp_path, game, clock)
    found = cursefight.fight(screens, game, ["EVOKER"], cursefight.PIT_FIGHT)
    assert game.keys == ["RET", "A", "Q", "Q", "N", "E", "N"]
    assert game.pressed_on[1] == "attack_evade"
    assert [bar["owner"] for bar in found["bars"]] == ["SUNDRA", "EVOKER"]
    assert found["outcome"] == "won"
    _keys_allowed(screens, game)


def test_the_slugs_question_is_uncaptured_and_a_run_stops_on_it_unpressed(tmp_path):
    rules = cursefight.guard_rules()
    assert cursefight.missing(rules) == ["attack_evade"]
    assert (set(cursefight.PIT_KNOWN) - set(cursefight.UNCAPTURED)
            - set(cursefight.CAST_UNCAPTURED) - set(cursefight.CAST_UNREACHED)) <= set(rules)
    assert cursefight.ALLOWED_KEYS["attack_evade"] == frozenset({"A"})
    clock = Clock()
    game = PitGame(clock, ["continue", "attack_evade"], uncaptured={"attack_evade"})
    game.walking = False
    with pytest.raises(RouteError, match="no guard knows stayed"):
        cursefight.fight(_pit_screens(tmp_path, game, clock), game, ["EVOKER"],
                         cursefight.PIT_FIGHT)
    assert game.keys == ["RET"]


#: Boot, load slot A, begin; the walk and the fight are replaced; then camp, save to B and
#: the exit question.
PIT_DRIVE = [None, "intro", "front_end", "title", "load_picker", None, "loaded_menu",
             "loaded_menu", "world", "world", "camp", "camp_save_picker", None, "exit_game",
             "exit_game", "camp"]


def _pit_drive(tmp_path, monkeypatch, gates=(0x80,), games=None, save=True):
    clock = Clock()
    loaded = [_member(name) for name in NAMES]
    after = [_member(name, quickfight=1) for name in NAMES]
    game = PitGame(clock, PIT_DRIVE, parties=[loaded, after], gates=gates)
    game.walking = False
    if games is not None:
        games.append(game)
    walked = []
    monkeypatch.setattr(cursefight, "pit_walk",
                        lambda *a: walked.append(a) or {"steps": [], "met": "shot"})
    monkeypatch.setattr(cursefight, "walk", pytest.fail)
    seen = {}

    def fight(screens, memory, members, rules=None, found=None):
        seen["rules"] = rules
        return {"bars": [{"owner": "EVOKER", "shot": "bar.png"}], "answered": [],
                "outcome": "won"}

    monkeypatch.setattr(cursefight, "fight", fight)
    screens = _pit_screens(tmp_path, game, clock)
    found = cursefight.drive(screens, _pit_manifest(), ["EVOKER"], game, save=save)
    return found, game, screens, walked, seen


def test_drive_in_the_pit_checks_the_gate_walks_fights_and_saves_once(tmp_path, monkeypatch):
    found, game, screens, walked, seen = _pit_drive(tmp_path, monkeypatch,
                                                    gates=(0x80, 0x80))
    assert game.keys == ["ESC", "ESC", "L", "A", "B", "E", "S", "B", "N"]
    assert walked and seen["rules"] is cursefight.PIT_FIGHT
    assert found[cursefight.LIVE_GATE] == 0x80 and found[cursefight.GATE_AFTER] == 0x80
    assert found["first_bar"] == {"owner": "EVOKER", "shot": "bar.png"}
    assert found["members"]["EVOKER"]["quickfight"] == 1
    assert "P" not in game.keys
    _keys_allowed(screens, game)


def test_drive_in_the_pit_stops_before_any_step_when_the_gate_did_not_load(tmp_path, monkeypatch):
    games = []
    with pytest.raises(RouteError, match="reads 0 in the running game"):
        _pit_drive(tmp_path, monkeypatch, gates=(0,), games=games)
    assert games[0].keys[-1] == "B"


def test_run_of_a_pit_stage_uses_the_pit_screens_and_names_the_uncaptured_ones(
        tmp_path, monkeypatch):
    manifest = _staged(tmp_path)
    value = json.loads(manifest.read_text())
    value["fight"].update(PIT_PLAN)
    manifest.write_text(json.dumps(value))
    monkeypatch.setattr(cursefight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(cursefight.curseadd, "slot_letters", lambda disk: ["D"])
    monkeypatch.setattr(cursefight.curseadd, "mute", lambda guest, out, timeout: out / "mute.json")
    kinds = []

    def drive(screens, manifest, members, memory, *, save, found):
        kinds.append(type(screens))
        found["walk"] = {"steps": []}
        raise RouteError("a screen no guard knows stayed 90s unchanged mid-fight")

    monkeypatch.setattr(cursefight, "drive", drive)
    with pytest.raises(RouteError, match="no guard knows"):
        cursefight.run(_args(tmp_path, manifest), guest=LaneGuest(), guards=object(),
                       boot=lambda *a, **k: {"claim": "ok"}, memory=object(),
                       halt=lambda *a, **k: {"fetched": {}})
    written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert kinds == [cursefight.PitScreens]
    assert written["uncaptured"] == ["attack_evade"] and written["walk"] == {"steps": []}


def _pit_source(tmp_path, specimen):
    """The EVOKER specimen's slot D moved to the converted join save's Pit square, 1,4 west."""
    from goldbox import amiga_adf, amiga_savegame
    from tools.amiga.staging import replace_file_in_place

    pit = tmp_path / "pit-source.adf"
    pit.write_bytes(specimen.read_bytes())
    disk = amiga_adf.AmigaDisk.open(pit)
    saved = amiga_savegame.read_slot(disk, "D", amiga_savegame.CURSE.key)
    data = amiga_savegame.with_square(saved, x=1, y=4, facing=6)
    for word in (0x49F2, 0x49C5):  # the area and its resident map, in Pool's numbering
        at = amiga_savegame.CURSE.vm_offset(word)
        data = data[:at] + (17).to_bytes(2, "big") + data[at + 2:]
    replace_file_in_place(disk, amiga_savegame.slot_path(amiga_savegame.CURSE, "D"), data)
    disk.save(pit)
    return pit


def test_stage_sets_the_pit_gate_and_plans_the_walk_over_the_roll_squares(tmp_path):
    from goldbox import amiga_adf

    specimen, diskb = _registered_inputs()
    pit = _pit_source(tmp_path, specimen)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps({
        "title": "curse", "registered": {},
        "disks": {"save": {"path": str(pit), "sha256": digest(pit)},
                  "diskb": {"path": str(diskb), "sha256": digest(diskb)}}}))
    before = digest(pit)
    path = cursefight.stage(prep, pit, tmp_path / "out", load="D", save="F")
    staged = json.loads(path.read_text())
    fight = staged["fight"]
    assert {k: fight[k] for k in PIT_PLAN} == PIT_PLAN
    assert fight["place"] == PIT_START
    assert fight["staged"] == {"4C2D": {"before": 0, "after": 0x80}}
    assert digest(pit) == before == fight["source"]["sha256"]
    copy = pathlib.Path(staged["disks"]["save"]["path"])
    assert digest(copy) == staged["disks"]["save"]["sha256"] != before
    source = cursefight._slot(amiga_adf.AmigaDisk.open(pit), "D").data
    data = cursefight._slot(amiga_adf.AmigaDisk.open(copy), "D").data
    assert cursefight.gate_word(data) == 0x80
    assert [i for i in range(len(data)) if data[i] != source[i]] == [
        _gate_offset() + 1]
    back = cursefight.read_back(copy, {**staged, "fight": {**fight, "save": "D"}})
    assert back[cursefight.SAVED_GATE] == 0x80 and back["loaded_slot_unchanged"]


def _gate_offset():
    from goldbox import amiga_savegame

    return amiga_savegame.CURSE.vm_offset(cursefight.PIT_GATE - 0x200)


def test_stage_names_both_areas_it_knows_for_a_slot_elsewhere(tmp_path, monkeypatch):
    specimen, diskb = _registered_inputs()
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps({
        "title": "curse", "registered": {},
        "disks": {"save": {"path": str(specimen), "sha256": digest(specimen)},
                  "diskb": {"path": str(diskb), "sha256": digest(diskb)}}}))
    real = cursefight.amiga_savegame.state_from_savegame
    monkeypatch.setattr(cursefight.amiga_savegame, "state_from_savegame",
                        lambda saved: dataclasses.replace(real(saved), area=3))
    with pytest.raises(RouteError, match="area 3; .*Tilverton, area 1, and the Pit of Moander, "
                                         "area 17"):
        cursefight.stage(prep, specimen, tmp_path / "out", load="D", save="F")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("gate, problem", [(0x80, False), (0, True), (None, True)])
def test_verdict_of_a_pit_run_needs_the_staged_gate_in_the_saved_slot(gate, problem):
    members = [_member(name, quickfight=1) for name in NAMES]
    found = {**_read(members), **({} if gate is None else {cursefight.SAVED_GATE: gate})}
    problems = cursefight.verdict(found, _pit_manifest(), ["EVOKER"])
    assert problems == ([f"the saved slot holds $4C2D = {gate}, not the staged 128"]
                        if problem else [])
    assert cursefight.verdict(_read(members), _manifest(), ["EVOKER"]) == []


# -- a destroyed party in the Pit, and the save-only run ----------------------------------

#: The Pit run that lost to shambling mounds: its last frame before the destroyed message,
#: and the message itself.
PIT_RUN1 = pathlib.Path.home() / ".cache/wish/acceptance/WISH-388/c64join-amiga-pit/run1/screens"


def test_party_destroyed_guard_matches_the_pit_frame_and_not_the_frame_before(tmp_path):
    frames = {n: PIT_RUN1 / f"{n}-fight.png" for n in (187, 216)}
    if not all(f.is_file() for f in frames.values()):
        pytest.skip("the WISH-388 Pit run 1 capture is not on this machine")
    rules = tmp_path / "guards.json"
    rules.write_text(json.dumps(cursefight.guard_rules()))
    guards = PixelGuards(rules)
    assert guards("party_destroyed", frames[216])
    assert not guards("party_destroyed", frames[187])
    assert [s for s in cursefight.PIT_KNOWN if s in guards and guards(s, frames[216])] == [
        "party_destroyed"]


def test_pit_fight_ends_lost_on_the_destroyed_message_with_one_return(tmp_path):
    clock = Clock()
    script = ["continue", "world", "combat_bar", "combat_bar", None, "party_destroyed", "title"]
    game = PitGame(clock, script, owners=[_owner("EVOKER")])
    game.walking = False
    screens = _pit_screens(tmp_path, game, clock)
    found = cursefight.fight(screens, game, ["EVOKER"], cursefight.PIT_FIGHT)
    assert found["outcome"] == "lost" and game.keys == ["RET", "Q", "RET"]
    assert game.pressed_on[-1] == "party_destroyed"
    assert found["answered"][-1]["screen"] == "party_destroyed"
    _keys_allowed(screens, game)


def test_drive_in_the_pit_stops_at_a_destroyed_party_saving_nothing(tmp_path, monkeypatch):
    clock = Clock()
    loaded = [_member(name) for name in NAMES]
    game = PitGame(clock, PIT_DRIVE, parties=[loaded])
    game.walking = False
    monkeypatch.setattr(cursefight, "pit_walk", lambda *a: {"steps": [], "met": "shot"})
    monkeypatch.setattr(
        cursefight, "fight",
        lambda *a, **k: {"bars": [{"owner": "EVOKER", "shot": "bar.png"}],
                         "answered": [{"screen": "party_destroyed", "key": "RET"}],
                         "outcome": "lost"})
    found = cursefight.drive(_pit_screens(tmp_path, game, clock), _pit_manifest(), ["EVOKER"],
                             game, save=True)
    assert found["destroyed"] and found["outcome"] == "lost"
    assert game.keys == ["ESC", "ESC", "L", "A", "B"] and "after" not in found
    assert cursefight.GATE_AFTER not in found


def test_drive_with_no_fight_camps_and_saves_as_loaded(tmp_path, monkeypatch):
    clock = Clock()
    game = PitGame(clock, PIT_DRIVE, parties=[[_member(name) for name in NAMES]])
    game.walking = False
    for name in ("pit_walk", "walk", "fight"):
        monkeypatch.setattr(cursefight, name, pytest.fail)
    screens = _pit_screens(tmp_path, game, clock)
    found = cursefight.drive(screens, _pit_manifest(), ["EVOKER"], game, save=True,
                             no_fight=True)
    assert game.keys == ["ESC", "ESC", "L", "A", "B", "E", "S", "B", "N"]
    assert "outcome" not in found and cursefight.LIVE_GATE not in found
    _keys_allowed(screens, game)


def test_run_reports_a_destroyed_party_and_reads_nothing_back(tmp_path, monkeypatch):
    drive = lambda *a, **k: {"bars": [], "outcome": "lost", "destroyed": True}  # noqa: E731
    with pytest.raises(RouteError, match="destroyed, so nothing was saved"):
        _run(tmp_path, monkeypatch, drive=drive)
    written = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert written["problems"] == ["the party was destroyed, so nothing was saved"]
    assert written["fight_won"] is False and "read_back" not in written


def test_run_with_no_fight_saves_and_judges_the_read_back_unfought(tmp_path, monkeypatch):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(cursefight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(cursefight.curseadd, "slot_letters", lambda disk: ["D"])
    monkeypatch.setattr(cursefight.curseadd, "mute", lambda guest, out, timeout: out / "mute.json")
    seen = {}

    def drive(screens, manifest, members, memory, *, save, found, no_fight=False):
        seen.update(save=save, no_fight=no_fight)
        return {}

    monkeypatch.setattr(cursefight, "drive", drive)
    monkeypatch.setattr(cursefight, "read_back", lambda path, value: {"path": str(path)})
    monkeypatch.setattr(cursefight, "verdict",
                        lambda found, value, members, outcome="won": seen.update(outcome=outcome)
                        or [])
    fetched = tmp_path / "fetched-save.adf"
    fetched.write_bytes(b"fetched")
    args = _args(tmp_path, manifest)
    args.no_fight = True
    receipt = cursefight.run(args, guest=LaneGuest(), guards=object(),
                             boot=lambda *a, **k: {"claim": "ok"}, memory=object(),
                             halt=lambda *a, **k: {"fetched": {"save": {"path": str(fetched)}}})
    assert seen == {"save": True, "no_fight": True, "outcome": "unfought"}
    assert receipt["success"] and receipt["fight"] is False and "fight_won" not in receipt


def test_run_with_no_fight_and_no_save_stops_before_the_guest(tmp_path):
    manifest = _staged(tmp_path)
    args = _args(tmp_path, manifest, no_save=True)
    args.no_fight = True
    guest = LaneGuest()
    with pytest.raises(RouteError, match="--no-fight saves"):
        cursefight.run(args, guest=guest, guards=object(), boot=pytest.fail, halt=pytest.fail,
                       memory=object())
    assert guest.calls == [] and not (tmp_path / "run").exists()


def test_verdict_of_an_unfought_save_skips_quickfight_and_checks_the_picture():
    members = [_member(name, picture=0x16) for name in NAMES]
    manifest = _manifest()
    for name in NAMES:
        manifest["fight"]["members"][name]["picture"] = 0x16
    assert cursefight.verdict(_read(members), manifest, ["EVOKER"], "unfought") == []
    assert any("quickfight 0" in p
               for p in cursefight.verdict(_read(members), manifest, ["EVOKER"], "won"))
    members[-1]["picture"] = 0
    assert cursefight.verdict(_read(members), manifest, ["EVOKER"], "unfought") == [
        "EVOKER was saved with picture 0, staged with 22"]


def test_the_fight_driver_reads_the_party_with_the_shared_limit():
    from tools.amiga import curseadd, ssbfight

    assert cursefight.READ_LIMIT == ssbfight.READ_LIMIT == curseadd.READ_LIMIT >= 70


# -- the cast: a staged Confusion on the caster's bars, aimed at a watched member -----------

BRUTUS_AT, GALAIN_AT, HOLLAND_AT = 0xC5B000, 0xC5A000, 0xC5C000
CAST_NAMES = ["GALAIN", "HOLLAND", "IILANDA", "SUNDRA", "BRUTUS"]


def _watch(effects=(), left=3, status=1, control=0xB3, hp=60, kind=4):
    return {"BRUTUS": {"address": BRUTUS_AT, "control": control, "picture": 0, "status": status,
                       "side": 0, "quickfight": 0, "hit_points": hp, "creature_type": kind,
                       "effects": list(effects), "spell_left": 0},
            "GALAIN": {"address": GALAIN_AT, "control": 0, "picture": 0, "status": 0, "side": 0,
                       "quickfight": 0, "hit_points": 9, "creature_type": 0, "effects": [],
                       "spell_left": left}}


class CastGame(Game):
    """The scripted game with the cast's memory: each grab writes its screen's name as the
    crop, so a held frame keeps its digest; `unguarded` screens have no guard. A bar reads the
    next of `watches`; a poll reads BRUTUS alone, the next of `polls` (a `RouteError` in it
    fails that read), or with no `polls` the row the last bar read."""

    def __init__(self, clock, script, *, owners=(), watches=(), aims=((BRUTUS_AT, 6),),
                 ids=(0x52, 0x52, 0x52), unguarded=(), polls=(), poll_seconds=0.0,
                 poll_hold=None):
        super().__init__(clock, script, owners=owners)
        #: Seconds of the run's clock each poll's read takes, and an event a poll's read
        #: waits on before it answers.
        self.poll_seconds, self.poll_hold = poll_seconds, poll_hold
        self.walking = False
        self.watches, self.aims = list(watches), list(aims)
        self.ids = list(ids)
        self.unguarded = set(unguarded)
        self.polls = list(polls)
        self.last_watch = None
        self.polled = 0

    def grab(self, label, raw, crop, timeout):
        super().grab(label, raw, crop, timeout)
        pathlib.Path(crop).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(crop).write_bytes(str(self.current).encode())
        return True

    def __contains__(self, state):
        return ((state in cursefight.KNOWN or state == "brutus_runs_away")
                and state not in self.unguarded)

    def __call__(self, state, crop):
        return state in self and state == self.current

    def watch(self, names, spell):
        assert spell == 0x52
        if names == ["BRUTUS"]:
            self.polled += 1
            if self.poll_hold is not None:
                self.poll_hold.wait(5)
            self.clock.now += self.poll_seconds
            if not self.polls:
                return {"BRUTUS": (self.last_watch or self.watches[0])["BRUTUS"]}
            row = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
            if isinstance(row, Exception):
                raise row
            return {"BRUTUS": row}
        assert names == ["BRUTUS", "GALAIN"]
        self.last_watch = self.watches.pop(0) if len(self.watches) > 1 else self.watches[0]
        return self.last_watch

    def spell_list(self):
        return 0xC60000, list(self.ids)

    def casting(self, address):
        assert address == GALAIN_AT
        return 0x52

    def turn_pointer(self):
        """HOLLAND is in turn while a monster's frame shows, GALAIN otherwise."""
        return HOLLAND_AT if self.current == "~monster" else GALAIN_AT

    def aim(self):
        return self.aims.pop(0) if len(self.aims) > 1 else self.aims[0]


def _cast_screens(tmp_path, game, clock):
    return cursefight.CastScreens(game, "holder", tmp_path / "shots", game, 100_000,
                                  clock=clock, sleep=clock.sleep)


def _cast(game, capture=False):
    return cursefight.Cast(game, "GALAIN", 0x52, "BRUTUS", "BRUTUS", capture=capture)


#: HOLLAND's bar, GALAIN's bar (CAST), the list, the aim menu straight after it (one NEXT,
#: then TARGET), the cast beginning, GALAIN's bar with BRUTUS confused (DONE), GALAIN's bar
#: once BRUTUS goes berserk (QUICK), then the won message and the map.
CAST_FIGHT = ["combat_bar", "combat_bar", "combat_bar", "combat_bar", "spell_list", "aim",
              "aim", "aim", "~begun", "combat_bar", "combat_bar", "combat_bar", "combat_bar",
              "party_won", "world"]


def _cast_owners():
    return [{"address": HOLLAND_AT, **_member("HOLLAND")},
            *({"address": GALAIN_AT, **_member("GALAIN")} for _ in range(3))]


def test_the_cast_runs_on_the_casters_bars_and_quick_elsewhere(tmp_path):
    clock = Clock()
    game = CastGame(clock, CAST_FIGHT, owners=_cast_owners(),
                    watches=[_watch(), _watch(), _watch((35,), left=2),
                             _watch((35, 137), left=2)],
                    aims=[(HOLLAND_AT, 6), (BRUTUS_AT, 6)])
    screens = _cast_screens(tmp_path, game, clock)
    cast = _cast(game)
    found = cursefight.fight(screens, game, [], cast=cast)
    assert game.keys == ["Q", "C", "C", "N", "T", "D", "Q", "RET"]
    assert found["outcome"] == "won" and [b["owner"] for b in found["bars"]] == [
        "HOLLAND", "GALAIN", "GALAIN", "GALAIN"]
    log = cast.log()
    assert log["events"] == [{"bar": 2, "left_before": 3, "listed": 3, "casting_after_list": 0x52,
                              "aims": 1, "casting_at_aim": 0x52, "aim_count": 6,
                              "targets": [HOLLAND_AT, BRUTUS_AT], "outcome": "aimed",
                              "next_presses": 1, "target": BRUTUS_AT,
                              "casting_after_target": 0x52, "left_after": 2, "spent": 1}]
    assert log["lowered_seen"] and log["quick"] and len(log["reads"]) == 4
    assert "E" not in game.keys
    _keys_allowed(screens, game)


def test_the_caster_gets_quick_once_his_spell_runs_out(tmp_path):
    clock = Clock()
    game = CastGame(clock, ["combat_bar", "combat_bar", "party_won", "world"],
                    owners=[{"address": GALAIN_AT, **_member("GALAIN")}],
                    watches=[_watch(left=0)])
    found = cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=_cast(game))
    assert game.keys == ["Q", "RET"] and found["outcome"] == "won"


def test_a_spell_list_holding_another_spell_stops_the_run_before_any_key(tmp_path):
    clock = Clock()
    game = CastGame(clock, ["combat_bar", "combat_bar", "spell_list"],
                    owners=[{"address": GALAIN_AT, **_member("GALAIN")}],
                    watches=[_watch()], ids=(0x52, 0x0F))
    with pytest.raises(RouteError, match=r"holds \[82, 15\]"):
        cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=_cast(game))
    assert game.keys == ["C"]


def test_an_aim_that_cycles_without_the_target_stops_with_no_target_key(tmp_path):
    clock = Clock()
    game = CastGame(clock, ["combat_bar", "combat_bar", "spell_list", "aim"],
                    owners=[{"address": GALAIN_AT, **_member("GALAIN")}],
                    watches=[_watch()], aims=[(HOLLAND_AT, 6), (GALAIN_AT, 6), (HOLLAND_AT, 6)])
    with pytest.raises(RouteError, match="came back"):
        cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=_cast(game))
    assert game.keys == ["C", "C", "N", "N"] and "T" not in game.keys


def test_the_aim_menu_with_nothing_begun_stops_the_run(tmp_path):
    clock = Clock()
    game = CastGame(clock, ["aim"])
    with pytest.raises(RouteError, match="no spell chosen"):
        cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=_cast(game))
    assert game.keys == []


def test_a_capture_with_the_guards_keeps_the_aim_menu_and_presses_nothing_on_it(tmp_path):
    clock = Clock()
    game = CastGame(clock, ["combat_bar", "combat_bar", "spell_list", "aim"],
                    owners=[{"address": GALAIN_AT, **_member("GALAIN")}], watches=[_watch()])
    cast = _cast(game, capture=True)
    found = cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=cast)
    assert found["outcome"] == "captured" and game.keys == ["C", "C"]
    assert [c["screen"] for c in cast.captures] == ["spell_list", "aim"]
    assert cast.captures[1]["target"] == BRUTUS_AT and cast.captures[1]["pointer"] == GALAIN_AT
    assert cast.events[-1].get("outcome") is None


def test_a_capture_with_the_list_guarded_keeps_an_unguarded_aim_menu_unpressed(tmp_path):
    clock = Clock()
    script = ["combat_bar", "combat_bar", "spell_list", *["~aim"] * 8]
    game = CastGame(clock, script, owners=[{"address": GALAIN_AT, **_member("GALAIN")}],
                    watches=[_watch()], unguarded=("aim",))
    cast = _cast(game, capture=True)
    found = cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=cast)
    assert found["outcome"] == "captured" and game.keys == ["C", "C"]
    shots = {c["screen"]: pathlib.Path(c["shot"]).read_bytes() for c in cast.captures}
    assert shots == {"spell_list": b"spell_list", "aim": b"~aim"}


def test_a_capture_sends_no_key_to_an_unguarded_frame_a_stale_list_names(tmp_path):
    """The list's ids stay in memory after it closes, so an unguarded frame that memory takes
    for the list is kept and ends the capture, and gets no CAST."""
    clock = Clock()
    script = ["combat_bar", "combat_bar", *["~stale"] * 8]
    game = CastGame(clock, script, owners=[{"address": GALAIN_AT, **_member("GALAIN")}],
                    watches=[_watch()], unguarded=("spell_list", "aim"))
    cast = _cast(game, capture=True)
    found = cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=cast)
    assert found["outcome"] == "captured" and game.keys == ["C"]
    assert [(c["screen"], c["guarded"]) for c in cast.captures] == [("spell_list", False)]
    assert cast.phase == "chose"


def test_a_capture_takes_no_frame_while_another_is_in_turn(tmp_path):
    clock = Clock()
    script = ["combat_bar", "combat_bar", *["~monster"] * 200]
    game = CastGame(clock, script, owners=[{"address": GALAIN_AT, **_member("GALAIN")}],
                    watches=[_watch()], unguarded=("spell_list", "aim"))
    with pytest.raises(RouteError, match="unchanged mid-fight"):
        cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=_cast(game, True))
    assert game.keys == ["C"]


@pytest.mark.parametrize("on, key", [("combat_bar", "C"), ("combat_bar", "D"),
                                     ("spell_list", "C"), ("aim", "N"), ("aim", "T"),
                                     ("abort_spell", "N")])
def test_a_fight_with_no_cast_never_sends_a_cast_key(tmp_path, on, key):
    clock = Clock()
    game = Game(clock)
    with pytest.raises(RouteError, match="not a key"):
        _screens(tmp_path, game, clock).press(key, on)
    cast_screens = _cast_screens(tmp_path / "cast", game, clock)
    cast_screens.press(key, on)
    assert game.keys == [key]


@pytest.mark.parametrize("on, key", [("combat_bar", "E"), ("aim", "E"), ("aim", "M"),
                                     ("spell_list", "E"), ("abort_spell", "Y")])
def test_a_cast_run_never_sends_exit_or_an_unlisted_key(tmp_path, on, key):
    clock = Clock()
    game = Game(clock)
    with pytest.raises(RouteError, match="not a key"):
        _cast_screens(tmp_path, game, clock).press(key, on)
    assert game.keys == []


def _log(reads, events=None):
    return {"watch": "BRUTUS", "spell": 0x52,
            "events": [{"outcome": "aimed", "spent": 1}] if events is None else events,
            "reads": reads}


LOADED = {"control": 0xB3, "status": 1}


def _saved(**fields):
    row = {"name": "BRUTUS", "control": 0, "status": 1, "hit_points": 60, "creature_type": 4,
           "effects": []}
    row.update(fields)
    return row


def test_cast_verdict_passes_a_lowered_member_saved_living_under_orders():
    log = _log([_watch(), _watch((35,)), _watch((137,)), _watch(control=0)])
    assert cursefight.cast_verdict(log, _watch(control=0), _saved(), LOADED) == ("pass", [])


@pytest.mark.parametrize("saved, after, match", [
    (_saved(effects=[142]), _watch(control=0), "saved holding effects"),
    (_saved(hit_points=0), _watch(control=0), "0 hit points saved"),
    (_saved(status=0), _watch(control=0), "status 0 saved"),
    (None, _watch(control=0), "no saved reading"),
])
def test_cast_verdict_names_what_keeps_a_lowered_member_from_passing(saved, after, match):
    log = _log([_watch((137,))])
    kind, problems = cursefight.cast_verdict(log, after, saved, LOADED)
    assert kind == "inconclusive" and any(match in p for p in problems), problems


def test_cast_verdict_refutes_a_member_still_under_the_game_after_137():
    log = _log([_watch((142,))])
    kind, problems = cursefight.cast_verdict(log, _watch(), _saved(control=0xB3), LOADED)
    assert kind == "refuted" and "still reads control 0xb3" in problems[0]


def _row(effects=(), status=1, control=0xB3, frame=1):
    return {"frame": frame, "when": "poll", **{k: v for k, v in _watch(
        effects, status=status, control=control)["BRUTUS"].items()
        if k in cursefight.WATCHED_FIELDS}}


def test_cast_verdict_judges_a_member_who_ran_off_the_map_fled_with_control_cleared():
    """Stage 3's run-away branch: 142 at a bar, status 3 only at a poll between bars, and the
    after-fight pass leaving him at status 0 with control 0 and the zombie's type."""
    log = {**_log([_watch((142,))]), "changes": [_row((142,), status=3, frame=99)]}
    after, saved = _watch(control=0, status=0), _saved(status=0)
    assert cursefight.cast_verdict(log, after, saved, LOADED) == ("fled", [])
    kind, problems = cursefight.cast_verdict(log, after, _saved(status=0, creature_type=0),
                                             LOADED)
    assert kind == "fled" and "saved with type 0, not 4" in problems[0]
    kind, problems = cursefight.cast_verdict(log, after, _saved(status=1), LOADED)
    assert kind == "fled" and "status 1 saved, not 0x00 and 0" in problems[0]


def test_cast_verdict_takes_the_runs_away_frame_as_running():
    log = {**_log([_watch((35,))]), "changes": [_row((35,), status=3, frame=99)],
           "runs_away_frames": [{"frame": 64, "shot": "064-fight.png"}]}
    assert cursefight.cast_verdict(log, _watch(control=0, status=0), _saved(status=0),
                                   LOADED) == ("fled", [])


def test_cast_verdict_keeps_a_member_who_fled_under_the_game_fled_and_names_his_control():
    """Spec 66adfbd2 records leaving the map as its own outcome, not a refutation."""
    log = {**_log([_watch((142,))]), "changes": [_row((142,), status=3)]}
    kind, problems = cursefight.cast_verdict(log, _watch(status=0), _saved(status=0, control=0xB3),
                                             LOADED)
    assert kind == "fled" and problems == [
        "BRUTUS ran off the map but reads control 0xb3, status 0 live, not 0x00 and 0",
        "BRUTUS ran off the map but reads control 0xb3, status 0 saved, not 0x00 and 0"]


def test_cast_verdict_keeps_a_berserk_member_who_left_the_map_under_the_game_got_away():
    log = {**_log([_watch((137,))]), "changes": [_row((137,), status=3)]}
    kind, problems = cursefight.cast_verdict(log, _watch(status=0), _saved(status=0, control=0xB3),
                                             LOADED)
    assert kind == "got_away" and problems == [
        "BRUTUS held 137, got away and reads control 0xb3 live, not 0x00",
        "BRUTUS held 137, got away and reads control 0xb3 saved, not 0x00"]
    assert cursefight.cast_verdict(log, _watch(status=0, control=0), _saved(status=0),
                                   LOADED) == ("got_away", [])


def test_cast_verdict_records_got_away_without_running_as_its_own_outcome():
    log = {**_log([_watch((35,))]), "changes": [_row((35,), status=3)]}
    saved = _saved(status=0, control=0xB3)
    assert cursefight.cast_verdict(log, _watch(status=0), saved, LOADED) == ("got_away", [])
    kind, problems = cursefight.cast_verdict(log, _watch(status=0),
                                             _saved(status=0, creature_type=0), LOADED)
    assert kind == "got_away" and "expected 0, 4" in problems[0]


def test_cast_verdict_expects_the_loaded_status_only_of_the_berserk_form():
    """142 with no read off the map is not judged against status 1, however he was saved."""
    log = _log([_watch((142,))])
    for saved in (_saved(), _saved(status=0)):
        kind, problems = cursefight.cast_verdict(log, _watch(control=0, status=saved["status"]),
                                                 saved, LOADED)
        assert kind == "inconclusive" and problems == [
            "BRUTUS held 142 but no read caught him off the map (status 3)"]


def test_cast_verdict_of_the_stage_3_receipt_names_the_missing_read_off_the_map():
    receipt_path = ACCEPTANCE / "WISH-303/i6/stage/run1/receipt.json"
    if not receipt_path.is_file():
        pytest.skip("the WISH-303 stage 3 receipt is not on this machine")
    receipt = json.loads(receipt_path.read_text())
    saved = [m for m in receipt["read_back"]["members"] if m["name"] == "BRUTUS"]
    loaded = json.loads(pathlib.Path(receipt["manifest"]).read_text())["fight"]["members"]["BRUTUS"]
    kind, problems = cursefight.cast_verdict(receipt["cast"], receipt["watch_after"], saved[0],
                                             loaded)
    assert kind == "inconclusive" and problems == [
        "BRUTUS held 142 but no read caught him off the map (status 3)"]


#: GALAIN's bar (CAST, and its second look), the list, the aim menu (TARGET, and its second
#: look), BRUTUS's runs-away message, two frames of the fight with no bar, then the won
#: message and the map. The fight loop's own grabs, the ones it polls at, are 1, 3, 4 and 6-10.
RUN_AWAY_FIGHT = ["combat_bar", "combat_bar", "spell_list", "aim", "aim", "brutus_runs_away",
                  "~monster", "~monster2", "party_won", "world"]


def test_every_fight_poll_reads_the_watched_member_and_logs_each_change_with_its_frame(
        tmp_path):
    clock = Clock()
    polls = [_watch()["BRUTUS"], _watch()["BRUTUS"], _watch()["BRUTUS"],
             _watch((35, 142))["BRUTUS"], _watch((35, 142), status=3)["BRUTUS"],
             _watch((35, 142), status=3)["BRUTUS"], _watch(status=0, control=0)["BRUTUS"]]
    game = CastGame(clock, RUN_AWAY_FIGHT, owners=[{"address": GALAIN_AT, **_member("GALAIN")}],
                    watches=[_watch()], aims=[(BRUTUS_AT, 6)], polls=polls)
    screens = _cast_screens(tmp_path, game, clock)
    cast = _cast(game)
    found = cursefight.fight(screens, game, [], cast=cast)
    assert found["outcome"] == "won" and game.keys == ["C", "C", "T", "RET"]
    assert game.polled >= len(polls)
    assert [(c["frame"], c["status"], c["control"], c["effects"]) for c in cast.changes] == [
        (1, 1, 0xB3, []), (6, 1, 0xB3, [35, 142]), (7, 3, 0xB3, [35, 142]), (9, 0, 0, [])]
    assert [f["frame"] for f in cast.runs_away_frames] == [6]
    assert cast.lowered and cast.log()["changes"] == cast.changes
    assert any("watch_change" in e for e in screens.events)
    _keys_allowed(screens, game)


def test_a_failed_poll_is_logged_and_the_fight_goes_on(tmp_path):
    clock = Clock()
    polls = [_watch()["BRUTUS"], RouteError("no answer"), _watch(status=3)["BRUTUS"]]
    game = CastGame(clock, ["~monster", "~monster2", "party_won", "world"], polls=polls,
                    watches=[_watch()])
    cast = _cast(game)
    found = cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=cast)
    assert found["outcome"] == "won"
    assert [e["frame"] for e in cast.poll_errors] == [2]
    assert [(c["frame"], c["status"]) for c in cast.changes] == [(1, 1), (3, 3)]


def test_a_poll_that_outlives_its_limit_is_never_joined_by_a_second_read(tmp_path, monkeypatch):
    """The first poll's read hangs; every later grab skips its poll while that read runs."""
    import threading

    monkeypatch.setattr(cursefight, "POLL_READ_LIMIT", 0.05)
    hold = threading.Event()
    clock = Clock()
    game = CastGame(clock, ["~monster", "~monster2", "~monster", "party_won", "world"],
                    watches=[_watch()], poll_hold=hold)
    cast = _cast(game)
    try:
        found = cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=cast)
        assert found["outcome"] == "won"
        assert game.polled == 1 and cast.polls_skipped >= 4
        assert [e["frame"] for e in cast.poll_errors] == [1]
        assert "no answer" in cast.poll_errors[0]["error"]
    finally:
        hold.set()


def test_poll_time_counts_toward_no_fight_timer(tmp_path):
    """A held frame polled with a 40 s read each time is a held frame of a few seconds."""
    clock = Clock()
    game = CastGame(clock, ["~still"] * 5 + ["party_won", "world"], watches=[_watch()],
                    poll_seconds=40.0)
    found = cursefight.fight(_cast_screens(tmp_path, game, clock), game, [], cast=_cast(game))
    assert found["outcome"] == "won" and game.polled >= 5
    assert clock.now > cursefight.FIGHT_STALL * 2


def test_reads_of_the_located_game_never_overlap(monkeypatch):
    """A second thread's read waits for the first, as a worker a bounded read gave up on
    would still be reading when the next read starts."""
    import threading

    from automap import amiga

    state = {"active": 0, "most": 0, "located": 0}
    first_in, second_in = threading.Event(), threading.Event()

    class Target:
        data_base = 0

        def locate(self):
            state["located"] += 1

        def read(self, address, size):
            state["active"] += 1
            state["most"] = max(state["most"], state["active"])
            if address == 1:
                first_in.set()
                second_in.wait(0.5)
            else:
                second_in.set()
            state["active"] -= 1
            return bytes(size)

    monkeypatch.setattr(amiga, "AmigaTarget", lambda pipe, machine: Target())
    monkeypatch.setattr(amiga, "WinuaePipe", lambda holder: None)
    memory = cursefight.Memory("holder")
    first = threading.Thread(target=lambda: memory.target().read(1, 4))
    first.start()
    assert first_in.wait(2)
    second = threading.Thread(target=lambda: memory.target().read(2, 4))
    second.start()
    first.join(3)
    second.join(3)
    assert state == {"active": 0, "most": 1, "located": 1}
    assert memory.target().data_base == 0


def test_a_fight_with_no_cast_reads_no_member_between_bars(tmp_path):
    clock = Clock()
    game = CastGame(clock, ["~monster", "~monster2", "party_won", "world"], watches=[_watch()])
    found = cursefight.fight(_screens(tmp_path, game, clock), game, [])
    assert found["outcome"] == "won" and game.polled == 0


def test_the_runs_away_guard_names_brutus_running_and_no_other_stage_3_frame(tmp_path):
    shots = ACCEPTANCE / "WISH-303/i6/stage/run1/screens"
    frames = sorted(f for f in shots.glob("*-fight.png")) if shots.is_dir() else []
    if not any(f.name == "064-fight.png" for f in frames):
        pytest.skip("the WISH-303 stage 3 frames are not on this machine")
    guards = _real_guards(tmp_path)
    assert [f.name for f in frames if guards("brutus_runs_away", f)] == ["064-fight.png"]


def test_cast_verdict_needs_a_cast_and_one_copy_spent_per_cast():
    kind, problems = cursefight.cast_verdict(_log([_watch()], events=[]), _watch(), _saved(),
                                             LOADED)
    assert kind == "inconclusive" and "no cast event" in problems
    assert any("never held 137 or 142" in p for p in problems)
    kind, problems = cursefight.cast_verdict(
        _log([_watch((137,))], events=[{"outcome": "aimed", "spent": 2}]),
        _watch(control=0), _saved(), LOADED)
    assert kind == "inconclusive" and problems == ["cast 1 (aimed) spent 2 of 82, not 1"]


@pytest.mark.parametrize("text, match", [
    ("BRUTUS:control=0", "writes only"), ("BRUTUS:status=1", "writes only"),
    ("BRUTUS:creature_type=0", "writes only"), ("BRUTUS:side=1", "writes only"),
    ("NOBODY:hp=60", "not in the party"), ("BRUTUS:hp=0", "not 1 to 255"),
    ("GALAIN:memorised0=128", "not 1 to 127"), ("BRUTUS:hp=60,hp=61", "twice"),
    ("BRUTUS", "not NAME:FIELD"), ("GALAIN:memorised84=82", "writes only")])
def test_a_stage_record_writes_only_hit_points_and_memorised_slots(text, match):
    with pytest.raises(RouteError, match=match):
        cursefight.parse_records([text], CAST_NAMES)


def test_apply_records_writes_each_byte_in_its_members_block():
    blocks = ((0, 0x1AC), (0x1AC, 0x358))
    data = bytes(0x358)
    plans = cursefight.parse_records(["B:hp=0x3C,hp_max=60", "A:memorised0=82,memorised2=82"],
                                     ["A", "B"])
    out, staged = cursefight.apply_records(data, blocks, ["A", "B"], plans)
    assert [i for i in range(len(out)) if out[i]] == [0x1E, 0x20, 0x1AC + 0x78, 0x1AC + 0x1A9]
    assert staged[0]["fields"]["hp"] == {"record_offset": 0x1A9, "file_offset": 0x1AC + 0x1A9,
                                         "before": 0, "after": 60}
    with pytest.raises(RouteError, match="not an empty slot"):
        cursefight.apply_records(out, blocks, ["A", "B"],
                                 cursefight.parse_records(["A:memorised0=82"], ["A", "B"]))
    with pytest.raises(RouteError, match="above hp_max"):
        cursefight.apply_records(data, blocks, ["A", "B"],
                                 cursefight.parse_records(["A:hp=9"], ["A", "B"]))


def _brutus_inputs():
    specimen = (specimens.tree_root() / "coab-amiga"
                / "WISH-SPEC-wish303-s4-curse-brutus-pool-add-slot-d" / "fetched-save.adf")
    _evoker, diskb = _registered_inputs()
    if not specimen.is_file():
        pytest.skip("the BRUTUS specimen is not on this machine")
    return specimen, diskb


def test_stage_writes_only_the_staged_bytes_into_the_brutus_slot(tmp_path):
    specimen, diskb = _brutus_inputs()
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps({
        "title": "curse", "registered": {},
        "disks": {"save": {"path": str(specimen), "sha256": digest(specimen)},
                  "diskb": {"path": str(diskb), "sha256": digest(diskb)}}}))
    path = cursefight.stage(prep, specimen, tmp_path / "out", load="D", save="F",
                            records=["BRUTUS:hp=60,hp_max=60",
                                     "GALAIN:memorised0=82,memorised1=82,memorised2=82"])
    staged = json.loads(path.read_text())
    fight = staged["fight"]
    before = cursefight.amiga_adf.AmigaDisk.open(specimen).read_file("/SAVE/savgamD.dat")
    disk = cursefight.amiga_adf.AmigaDisk.open(pathlib.Path(staged["disks"]["save"]["path"]))
    after = disk.read_file("/SAVE/savgamD.dat")
    assert disk.verify() == []
    assert [(i, before[i], after[i]) for i in range(len(before)) if before[i] != after[i]] == [
        (0x3237, 0, 82), (0x3238, 0, 82), (0x3239, 0, 82), (0x3BED, 11, 60), (0x3D1E, 11, 60)]
    assert fight["spells"]["GALAIN"] == [82, 82, 82]
    assert fight["members"]["BRUTUS"]["control"] == 0xB3
    assert fight["members"]["BRUTUS"]["status"] == 1
    assert fight["members"]["BRUTUS"]["hit_points"] == 60
    assert [r["name"] for r in fight["staged_records"]] == ["BRUTUS", "GALAIN"]


def _cast_args(tmp_path, manifest, **options):
    args = _args(tmp_path, manifest, members=())
    args.cast, args.aim, args.watch, args.capture = "GALAIN:CONFUSION", "BRUTUS", "BRUTUS", False
    for key, value in options.items():
        setattr(args, key, value)
    return args


def _cast_staged(tmp_path, spells=(0x52, 0x52, 0x52)):
    manifest = _staged(tmp_path)
    value = json.loads(manifest.read_text())
    value["fight"]["names"] = CAST_NAMES
    value["fight"]["members"]["BRUTUS"] = {"control": 0xB3, "status": 1}
    value["fight"]["spells"] = {"GALAIN": list(spells)}
    manifest.write_text(json.dumps(value))
    return manifest


@pytest.mark.parametrize("problem, match", [
    ("no_guards", "capture them with --capture"), ("other_spell", "staged list holds"),
    ("no_spell", "staged list holds"), ("capture_alone", "--capture needs --cast"),
    ("aim_alone", "go together"), ("absent", "not in slot"), ("number", "not 1 to 127")])
def test_a_cast_run_stops_before_the_guest(tmp_path, monkeypatch, problem, match):
    spells = {"other_spell": (0x52, 0x0F), "no_spell": ()}.get(problem, (0x52, 0x52, 0x52))
    manifest = _cast_staged(tmp_path, spells)
    monkeypatch.setattr(cursefight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(cursefight.curseadd, "slot_letters", lambda disk: ["D"])
    options = {"capture_alone": {"cast": None, "aim": None, "watch": None, "capture": True},
               "aim_alone": {"cast": None, "watch": None},
               "absent": {"aim": "EVOKER"}, "number": {"cast": "GALAIN:200"}}.get(problem, {})
    if problem == "no_guards":
        monkeypatch.setattr(cursefight, "FIGHT_GUARDS", {
            k: v for k, v in cursefight.FIGHT_GUARDS.items() if k not in ("spell_list", "aim")})
    guest = LaneGuest()
    with pytest.raises(RouteError, match=match):
        cursefight.run(_cast_args(tmp_path, manifest, **options), guest=guest, guards=object(),
                       boot=pytest.fail, halt=pytest.fail, memory=object())
    assert guest.calls == []


def test_a_capture_run_saves_nothing_and_needs_both_frames(tmp_path, monkeypatch):
    manifest = _cast_staged(tmp_path)
    monkeypatch.setattr(cursefight.amiga_adf.AmigaDisk, "open", lambda path: object())
    monkeypatch.setattr(cursefight.curseadd, "slot_letters", lambda disk: ["D"])
    monkeypatch.setattr(cursefight.curseadd, "mute", lambda guest, out, timeout: out / "mute.json")
    seen = {}

    def drive(screens, manifest, members, memory, *, save, found, cast):
        seen.update(save=save, capture=cast.capture)
        cast.captures += [{"screen": "spell_list"}, {"screen": "aim"}]
        return {"bars": [], "outcome": "captured"}

    monkeypatch.setattr(cursefight, "drive", drive)
    receipt = cursefight.run(_cast_args(tmp_path, manifest, capture=True), guest=LaneGuest(),
                             guards=object(), boot=lambda *a, **k: {"claim": "ok"},
                             memory=object(), halt=lambda *a, **k: {"fetched": {}})
    assert seen == {"save": False, "capture": True}
    assert receipt["success"] and receipt["save"] is False and receipt["problems"] == []
    assert receipt["cast_uncaptured"] == []


def test_the_cast_guards_name_the_captured_list_and_aim_menu_and_nothing_else(tmp_path):
    shots = ACCEPTANCE / "WISH-303/i6cap/cap1/screens"
    frames = {name: shots / f"{name}-fight.png" for name in ("051", "054", "055", "061")}
    if not all(f.is_file() for f in frames.values()):
        pytest.skip("the WISH-303 cast capture is not on this machine")
    guards = _real_guards(tmp_path)
    named = {name: [s for s in cursefight.KNOWN if s in guards and guards(s, f)]
             for name, f in frames.items()}
    assert named == {"051": ["combat_bar"], "054": ["spell_list"], "055": ["aim"],
                     "061": ["aim"]}
