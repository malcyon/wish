#!/usr/bin/env python3
"""Take an Amiga Curse party into a fight, log each command bar's owner, and save.

`stage` puts a copy of a Curse save disk some earlier run fetched in place of a prepare run's
disk A and writes a manifest. A slot in Tilverton (area 1) gets the tavern brawl; a slot in the
Pit of Moander (area 17) gets a wandering fight, and the copy's slot has the Pit's wandering
gate `$4C2D` set to `$80`, a value the area's script writes itself. `run` boots it in one muted
WinUAE lane and, pressing only on guarded screens, loads the slot and begins. In Tilverton it
walks the area's own map (`GEO.GLB` on disk B) to the tavern at 6,10 and answers PUNCH
BARKEEP; in the Pit it reads the gate back from the running game, then steps between two of
`GEO11`'s roll squares, reading the party's square before each step and stepping only onto a
roll square, until a step brings up a screen that is not the map, and answers the giant
slugs' ATTACK EVADE with ATTACK. Either way it answers every command bar with QUICK, so the
fight runs itself as the DOS fight step's does, and at each bar it reads whose bar it is from
memory and logs it. After the fight it checks each `--member` had a bar, now holds
quickfight 1 and still stands, then camps and saves once to the staged letter, halts,
fetches the disk and reads the slot back. `--no-save` stops after that check. A party the
fight destroys gets RETURN on the destroyed message, and the run ends there, lost, saving
nothing. A brawl counts as won only once the game shows THE PARTY HAS WON. `--no-fight`
loads the slot, begins, then camps and saves at once, with no walk and no fight, and reads
the save back, each member's combat picture included. Memory is only read, never written, so the Pit's gate stays at `$80` in a save the run makes; the
receipt records it.

`stage --stage-record NAME:FIELD=VALUE` writes hit points, their maximum or a memorised slot on
one member of the copy, and nothing else. `run --cast CASTER:SPELL --aim MEMBER --watch MEMBER`
has the caster cast a staged spell on his own bars: CAST, the list checked in memory to hold
only that spell, NEXT on the aim menu until the target is MEMBER's record, then TARGET; DONE
while the watched member is confused, and QUICK once he has held effect 137 or 142 or the
spell is spent. The watched member is read with the caster at every bar and after the fight,
and on every other poll of the fight alone, his record and effect nodes in one request; every
fight grab is checked for his runs-away, forced-to-flee and berserk messages with no read.
Each change is logged with its frame. The receipt judges the run from his saved row first,
pass, fled, got_away, refuted or inconclusive, with the readings and messages as notes
(`cast_verdict`). `--capture` takes the
list and the aim menu from memory and a held frame, stops at the aim menu and saves nothing.
`read` reads a fetched disk's saved slot against a staged manifest.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import hashlib
import json
import pathlib
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox import amiga_adf, amiga_savegame  # noqa: E402
from tools.amiga import acceptance, curseadd, route_curse  # noqa: E402
from tools.amiga.screens import PixelGuards  # noqa: E402
from tools.amiga.staging import replace_file_in_place, sha256  # noqa: E402
from tools.amiga.winuaesession import RouteError, WinGuest, terminating  # noqa: E402

require = curseadd.require
write_json = curseadd.write_json
TITLE = route_curse.CURSE_KEY

#: Tilverton's tavern: area 1, square 6,10, whose bar starts the brawl (the DOS fight step's
#: `CURSE_TAVERN`), walked over the area's own map, `GEO01` in disk B's `GEO.GLB`.
TAVERN_AREA = 1
TAVERN_GEO = "GEO01"
TAVERN = (6, 10)
#: Record offsets in `/Curse`: name at 0, control 0xF7, the combat picture 0x127 (a joined
#: companion's own, DOS 0x126), status 0x19A, side 0x19C, quickfight 0x19D (QUICK at 0x386C
#: sets it; the turn test at 0x2C24 reads it), hit points 0x1A9.
RECORD = {"control": 0xF7, "picture": 0x127, "status": 0x19A, "side": 0x19C,
          "quickfight": 0x19D, "hit_points": 0x1A9}
RECORD_SIZE = 0x1AC
#: The data-hunk global holding the record whose turn it is: the turn routine 0x2B68 stores
#: it at 0x2BB6, before 0x2C24 picks the command bar or the computer's turn.
CURRENT = 0x3CFC

#: The screens this route adds to the Curse guard map. The load error is the one a slot
#: holding a Pool import shows four times while it loads (`Invalid item (%d/%d)`, printed by
#: 0x39FCA, which waits for a key and goes on unless it is `q`).
FIGHT_GUARDS = {
    "load_error": {"box": [60, 416, 600, 430],
                   "sha256": "4a6806c8d6012a5bbd5ded17d87c260f61d5fcd05ec2e2cd025ffa4418a1fa71"},
    "tavern": {"box": [72, 404, 592, 426],
               "sha256": "729a8de7b9157b080928e2e212f775c0738ffd23b20344ddbc82aa2b75f9ae17"},
    # ASK ABOUT INJURIES / IGNORE THEM, which a save whose brawl already happened shows
    # before the PUNCH bar; the text line above it (the bartender's black eye) is the `and`.
    "injuries": {"box": [72, 404, 556, 426],
                 "sha256": "43f01d090eccc05783eeedda1c69823ad0474432caf91960c4fbb6370f76f71d",
                 "and": [{"box": [74, 302, 690, 318],
                          "sha256": "67c4990b5d5d9b01fabe5b7b710219be9e0bcdacf41f882e9a72ba2ed4d2098b"}]},
    # The brawl script's line after every fight it starts, won or lost (`ECL01 $8ACA`, the
    # same block in disk B's `ECL.GLB`), over the same RETURN bar as every `continue` box.
    "tossed": {"box": [74, 302, 690, 318],
               "sha256": "c0673a24f91bb7991f3c3139ce81fbc68556aee0ae50230a88d853ad4fe9c8f8"},
    # THE PARTY HAS WON, the first line of the game's end-of-fight message (`/Curse 0x2D620`)
    # over the RETURN bar, cut from the four won brawls kept (WISH-303 `i4-dos/stage/run2/
    # screens/178-fight.png`, `run1` 170, `i4-c64/stage/run2` 216, WISH-390 `run2` 111).
    "party_won": {"box": [74, 78, 640, 96],
                  "sha256": "64177b35adb9b7300e0e46e77a5de3f0973a5ada6de8336a8937ea04fe12cc4d",
                  "and": [{"box": [72, 404, 686, 426],
                           "sha256": "1bf2400681523aa4dc95ae92305564fd26f826fa60277596e7801505cb6dd73c"}]},
    # The destroyed party's message over a PRESS ANY KEY bar, cut from the Pit run that lost
    # to shambling mounds (WISH-388 `c64join-amiga-pit/run1/screens/216-fight.png`); the text
    # box alone would also match the same words over another bar, so the bar is the `and`.
    "party_destroyed": {"box": [90, 108, 656, 146],
                        "sha256": "ee9bc04a0212b97c277a22fd81edb01de359ad6cb1668a2128456fd1344d7c7b",
                        "and": [{"box": [72, 404, 686, 426],
                                 "sha256": "64ccbcfd2cec635e30dc2c838c8039916f77553e5a819c06412a00640054197b"}]},
    # MOVE VIEW AIM, the start of every member's command bar.
    "combat_bar": {"box": [72, 404, 288, 426],
                   "sha256": "140a5633d4aa744c3cf0bcf3d4a1bd5870f0ca7701590fa635ddd66abdff61df"},
    "continue_battle": {"box": [72, 404, 434, 426],
                        "sha256": "9c43f3c3f0819edd3f09e9d5843cb8dfaf923834790425cd0dabfdf6ab868914"},
    "treasure": {"box": [72, 404, 384, 426],
                 "sha256": "16e9130520404b31cfbee989cc1a167a940b5a441aea7e2e048e2d569ec8edb3"},
    # Two YES NO bars, told apart by the question's first line.
    "treasure_left": {"box": [72, 404, 178, 426],
                      "sha256": "89b99bc33b8a2b0494ad7d39adcf238a8802b4fec1186f7ce8774f168ff04a73",
                      "and": [{"box": [74, 302, 690, 318],
                               "sha256": "4876bed5dd347da0b9f1d21713a1a52711ed08a02668a71f67b5ff979021223f"}]},
    "investigate": {"box": [72, 404, 178, 426],
                    "sha256": "89b99bc33b8a2b0494ad7d39adcf238a8802b4fec1186f7ce8774f168ff04a73",
                    "and": [{"box": [74, 302, 690, 318],
                             "sha256": "62e2c5b54a7168bf15231eb25872aa96f17c857a1994d07fcecf3c381750cdd2"}]},
    # CHOOSE SPELL: CAST EXIT under the caster's spells in memory, and the aim menu (AIM: NEXT
    # PREV MANUAL TARGET CNTR. EXIT) with SPELL:CONFUSION above it, cut from the brawl capture
    # WISH-303 `i6cap/cap1/screens/054-fight.png` and `055-fight.png`; neither matches any of
    # the 5513 earlier 720x568 Amiga frames under the acceptance folder.
    "spell_list": {"box": [72, 404, 434, 426],
                   "sha256": "5dd38cfa6b6676cd31e6ec0724d03c8b28cfa870c47d6fda54b6f4604a053560"},
    "aim": {"box": [72, 404, 686, 426],
            "sha256": "2d90f56c352c39fe6525cd7d759a8b9cf8109c4f36e75128059767fe22511d09",
            "and": [{"box": [74, 388, 320, 402],
                     "sha256": "9bc6bec89c50a9423888368a8e63f57b7ebbb9c0396baa6af386306b6f46ff06"}]},
    # BRUTUS RUNS AWAY in the combat panel, the game's message as effect 142 takes him, cut
    # from the Confusion run WISH-303 `i6/stage/run1/screens/064-fight.png`. It is never a
    # state of the fight loop and gets no key: a `--watch BRUTUS` poll records its frames.
    "brutus_runs_away": {"box": [426, 190, 600, 224],
                         "sha256": "c09b5c811a5c98865751d5560584e9fabaf460bce9b2d58af55b844bf18e9d15"},
    # BRUTUS IS FORCED TO FLEE, three lines, which the computer turn (`/Curse 0x6764`) prints
    # while the flag Confusion's run-away arm sets is up; cut from `i6/stage/run2/screens/
    # 062-fight.png`, and 084 shows the same.
    "brutus_forced_to_flee": {"box": [426, 190, 680, 240],
                              "sha256": "4700664f796207dde5eb6f493d4b609d5b558e78689fae461653b655769d2aa3"},
    # BRUTUS GOES BERSERK, never drawn for him: his name line from run2 062 (the same rows in
    # run1 064 and run2 084) and the verb line, with the blank line under it, from run2 070
    # (GALAIN GOES BERSERK), which matches the BAR PATRON lines of 079 and 085 too. The name
    # line ends at row 208 because GALAIN's G reaches rows 206-207.
    "brutus_berserk": {"box": [426, 190, 680, 208],
                       "sha256": "447b6c9189311984f680c9d691d2597df4da4f62028c16cf91497a2604187cec",
                       "and": [{"box": [426, 208, 680, 240],
                                "sha256": "68ece7193fedeb61b704ed1999abcecf85e40b740d95f7de21945d18a4448fd3"}]},
}
#: The watched member's messages, by name, and the guard of each: checked on every fight
#: grab, with no memory read. None of them is a state of the fight loop or gets a key.
MESSAGE_GUARDS = {"BRUTUS": {"runs_away": "brutus_runs_away",
                             "forced_to_flee": "brutus_forced_to_flee",
                             "berserk": "brutus_berserk"}}
#: "party_won", "party_destroyed" and "tossed" come before "continue": the first known screen
#: a grab matches names it.
KNOWN = ("intro", "front_end", "title", "load_picker", "load_error", "loaded_menu", "world",
         "party_won", "party_destroyed", "tossed", "continue", "tavern", "injuries", "combat_bar", "continue_battle", "treasure",
         "treasure_left", "investigate", "camp", "camp_save_picker", "exit_game",
         "spell_list", "aim", "abort_spell")
#: The only keys each screen may receive. The tavern's L(EAVE) is for a bar shown again after
#: the fight; the investigate question is answered NO, which keeps the party out of a second fight.
ALLOWED_KEYS = {
    "intro": frozenset({"ESC"}), "front_end": frozenset({"ESC"}), "title": frozenset({"L"}),
    "load_picker": frozenset("ABCDEFGHIJ"), "load_error": frozenset({"RET"}),
    "loaded_menu": frozenset({"B"}), "world": frozenset({"NP4", "NP6", "NP8", "E"}),
    "continue": frozenset({"RET"}), "tossed": frozenset({"RET"}),
    "party_won": frozenset({"RET"}),
    "tavern": frozenset({"P", "L"}), "injuries": frozenset({"I"}),
    "combat_bar": frozenset({"Q"}), "continue_battle": frozenset({"N"}),
    "treasure": frozenset({"E"}), "treasure_left": frozenset({"N"}),
    "investigate": frozenset({"N"}), "camp": frozenset({"S"}),
    "camp_save_picker": frozenset("ABCDEFGHIJ"), "exit_game": frozenset({"N"}),
    "attack_evade": frozenset({"A"}), "party_destroyed": frozenset({"RET"}),
}
#: A `--cast` run's keys: CAST and DONE on a bar as well as QUICK, CAST on the list, NEXT and
#: TARGET on the aim menu (never EXIT), and NO to the abort question. A fight with no cast
#: keeps `ALLOWED_KEYS`.
CAST_ALLOWED_KEYS = {
    **ALLOWED_KEYS, "combat_bar": frozenset({"Q", "C", "D"}),
    "spell_list": frozenset({"C"}), "aim": frozenset({"N", "T"}), "abort_spell": frozenset({"N"}),
}
#: Answers to the screens that come between the first command bar and the map.
FIGHT_ANSWERS = {"combat_bar": "Q", "continue_battle": "N", "treasure": "E",
                 "treasure_left": "N", "investigate": "N", "continue": "RET", "tossed": "RET",
                 "party_won": "RET", "party_destroyed": "RET"}
#: Facing steps (0 N, 1 E, 2 S, 3 W) and the key that turns the party by each.
TURN_KEYS = {1: ("NP6",), 2: ("NP6", "NP6"), 3: ("NP4",)}
STEP = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}
#: Load errors a run answers before it stops; a slot holding a Pool import shows four.
LOAD_ERRORS = 8
#: Seconds any screen may stay unchanged mid-fight, or an unguarded screen may stay up with
#: no guard matching and no key pressed while the game is not in a fight, before the run
#: stops: a still screen is a key the game ignores or a question nobody answers, and an
#: animated one no guard knows is a bar nobody answers.
FIGHT_STALL = 90.0
#: Seconds the whole fight may take; a fight of QUICK turns takes about ten minutes.
FIGHT_LIMIT = 1500.0
#: Seconds after a key before the next grab, so a screen the key replaces is not read again.
AFTER_KEY = 3.0
#: Seconds the tavern bar may stay on screen after PUNCH before the run stops.
TAVERN_LINGER = 15.0
#: Seconds the map must hold before the fight is taken as over.
MAP_SETTLE = 6.0
#: Seconds the run waits for a step or a turn to show in the party's live square.
MOVE_LIMIT = 20.0
READ_LIMIT = curseadd.READ_LIMIT
#: Seconds one read of the game's mode byte may take before it counts as failed.
MODE_READ_LIMIT = 5.0
POST_WRITE_WAIT = 20.0
SLOT = curseadd.SLOT

#: The Pit of Moander, area 17, walked over its own map, `GEO11` in disk B's `GEO.GLB`. Its
#: script, the `ECL.GLB` block for area 17, is the C64's `ECL11` byte for byte. Its step
#: entry masks the square byte with `$3F` and sends id 0 to the wandering roll, which with
#: the gate `$4C2D` at `$80` rolls on every such step and fights under 15 (`$85A3`-`$85E3`);
#: at 0 it never rolls. Every arm the roll picks with the gate at `$80` fights.
PIT_AREA = 17
PIT_GEO = "GEO11"
PIT = "pit"
PIT_GATE = 0x4C2D
PIT_GATE_ON = 0x80
PIT_SQUARE_MASK = 0x3F
#: Steps between the two roll squares the walk takes looking for the fight before the run stops.
PIT_STEPS = 60
#: Seconds the map must hold after a step before the next key: a fight's monsters load with
#: the map bar still drawn, and a key sent then would land in the fight.
STEP_SETTLE = 12.0
#: Seconds the map, still drawn while the monsters load, may show before the first bar.
PIT_LINGER = 60.0
#: The receipt's names for the gate read from the running game at the first map screen and
#: after the fight, and from the saved slot read back.
LIVE_GATE = f"wander_gate_{PIT_GATE:04X}"
GATE_AFTER = f"wander_gate_{PIT_GATE:04X}_after_fight"
SAVED_GATE = f"saved_wander_gate_{PIT_GATE:04X}"
#: Pit screens the Curse guard map has no rule for. No grab matches one, so a run that meets
#: it presses nothing on it and stops after `FIGHT_STALL`, keeping the frame; `missing` lists
#: those still without a rule.
UNCAPTURED = {
    "attack_evade": "the giant slugs' ATTACK EVADE bar (`HORIZMENU` at `ECL11 $90DC`)",
}
#: "party_destroyed" comes before "continue": the first known screen a grab matches names it.
PIT_KNOWN = ("intro", "front_end", "title", "load_picker", "load_error", "loaded_menu", "world",
             "party_destroyed", "continue", "attack_evade", "combat_bar", "continue_battle", "treasure",
             "treasure_left", "camp", "camp_save_picker", "exit_game", "spell_list", "aim",
             "abort_spell")
#: Answers to the screens between the step that met the monsters and the map after the fight;
#: the slugs' question gets ATTACK, never EVADE, and the destroyed party's message RETURN.
PIT_ANSWERS = {"continue": "RET", "attack_evade": "A", "combat_bar": "Q",
               "continue_battle": "N", "treasure": "E", "treasure_left": "N",
               "party_destroyed": "RET"}

#: Spell ids `--cast` takes by name: Curse's spell row 82 (`g1EDE + 16 * 82`) is Confusion.
SPELLS = {"CONFUSION": 0x52}
#: Record offsets the cast reads besides `RECORD`: the memorised list (84 bytes, a listed spell
#: is 1-0x7F), the creature type, and the pointer to the member's combat block, whose byte 0
#: holds the spell he has begun casting.
MEMORISED = 0x1E
MEMORISED_SIZE = 0x54
CREATURE_TYPE = 0x11B
COMBAT_BLOCK = 0x192
#: Data-hunk globals: the spell list's head (a pointer, set while a list is built) and its ids
#: (`0x2FD26`); the aim menu's target record (`0x9F38` stores it, TARGET takes it) and the
#: count of combatants NEXT steps through (a byte).
SPELL_LIST_HEAD = 0x63E2
SPELL_LIST = 0x63E6
AIM_TARGET = 0x4FE6
AIM_COUNT = 0x4FE0
#: Effect ids: confused (35), goes berserk (137) and runs away (142). Confusion's handler
#: (`0x10A94`) rolls 1-100 each turn: 1-10 adds 142 and sets the flee flag (combat block +0x12),
#: 61-80 adds 137. Removing 137 or 142 clears a control of `$B3` (`0x12626`, `0x126A8`), and
#: removing 142 clears the flee flag.
CONFUSED = 35
BERSERK = 137
RUNS_AWAY = 142
LOWERING = (BERSERK, RUNS_AWAY)
#: The status a member gets on leaving the map ("Got Away", `0xF1F0`).
GOT_AWAY = 3
#: NEXT presses the aim may take when the count byte reads 0 or more than this.
AIM_PRESSES = 24
#: Seconds the caster's bar may still show after CAST before the run stops.
CAST_LINGER = 12.0
#: Seconds an unguarded screen must hold before `--capture` takes it as the list or the aim.
CAPTURE_STILL = 5.0
#: The cast's screens; the guard map has rules for both, and `--capture` would take them
#: again from memory and a held frame. A run lists those without a rule as uncaptured.
CAST_UNCAPTURED = {
    "spell_list": "the combat spell list, `Spells in Memory` (`0x2388C`)",
    "aim": "the aim menu, `Next Prev Manual Target Center Exit` (`0x9F38`)",
}
#: A cast screen no run reaches, so it has no rule and is not listed as uncaptured: the abort
#: question shows only after EXIT on the aim menu, which the run never presses.
CAST_UNREACHED = {
    "abort_spell": "the `Abort Spell?` question (EXIT on the aim menu)",
}
#: The watched member's fields a poll compares; a change in any of them is logged with its
#: frame. No established record or combat-block offset holds his combat map square, so none
#: is read.
WATCHED_FIELDS = ("control", "status", "hit_points", "quickfight", "creature_type", "effects")
#: Seconds one poll's read of the watched member may take; a failed poll is logged and the
#: fight goes on.
POLL_READ_LIMIT = 10.0
#: A record's effect list (`amigaparty`'s Curse row): head pointer at +0xF2, nodes of 10
#: bytes, the id at +0 and the next node's address at +6.
EFFECT_HEAD = 0xF2
EFFECT_LINK = 0x06
EFFECT_SIZE = 0x0A
#: Nodes a poll follows before it takes the list as broken.
EFFECT_LIMIT = 64
#: Record fields `stage --stage-record` may write: hit points and their maximum, and one
#: memorised slot each (`memorised0` is +0x1E). Control, status, type, side and effects are
#: never written.
STAGE_FIELDS = {"hp": RECORD["hit_points"], "hp_max": 0x78,
                **{f"memorised{i}": MEMORISED + i for i in range(MEMORISED_SIZE)}}


class Screens(curseadd.Screens):
    known = KNOWN
    allowed = ALLOWED_KEYS


class PitScreens(curseadd.Screens):
    known = PIT_KNOWN
    allowed = ALLOWED_KEYS


class CastScreens(Screens):
    allowed = CAST_ALLOWED_KEYS


class CastPitScreens(PitScreens):
    allowed = CAST_ALLOWED_KEYS


def guard_rules() -> dict:
    """The Curse guard map with this route's screens added."""
    rules = curseadd.guard_rules()
    require(not set(FIGHT_GUARDS) & set(rules), "a fight guard name is already a Curse guard")
    return {**rules, **FIGHT_GUARDS}


def missing(rules: dict) -> list[str]:
    """The `UNCAPTURED` screens the guard map still has no rule for."""
    return [state for state in UNCAPTURED if state not in rules]


def gate_word(data: bytes) -> int:
    """The Pit's gate from a saved game's bytes; `amiga_savegame.word` takes Pool's numbering."""
    return amiga_savegame.word(data, PIT_GATE - 0x200, amiga_savegame.CURSE)


def with_gate(data: bytes, value: int) -> bytes:
    """The saved game's bytes with the Pit's gate replaced."""
    at = amiga_savegame.CURSE.vm_offset(PIT_GATE - 0x200)
    return data[:at] + value.to_bytes(2, "big") + data[at + 2:]


def roll_square(geo, x: int, y: int) -> bool:
    """A Pit square whose step runs only the wandering roll: id 0 once masked as `$8523` masks it."""
    return 0 <= x < 16 and 0 <= y < 16 and geo.attributes(x, y) & PIT_SQUARE_MASK == 0


def pit_plan(geo, start: tuple[int, int]) -> dict:
    """The facings to the nearest roll square with a roll square open beside it both ways, the
    facing from it to that neighbour, and every roll square the walk may step onto. Only roll
    squares are entered, so no other square's script runs on the way."""
    def pair(x: int, y: int) -> int | None:
        for facing, (dx, dy) in STEP.items():
            if (roll_square(geo, x + dx, y + dy) and geo.is_passable(x, y, facing)
                    and geo.is_passable(x + dx, y + dy, (facing + 2) % 4)):
                return facing
        return None

    previous: dict[tuple[int, int], Any] = {start: None}
    queue = collections.deque([start])
    while queue:
        here = queue.popleft()
        if roll_square(geo, *here) and pair(*here) is not None:
            route, at = [], here
            while previous[at]:
                at, facing = previous[at]
                route.append(facing)
            facing = pair(*here)
            dx, dy = STEP[facing]
            squares = {here, (here[0] + dx, here[1] + dy)}
            at = start
            for heading in reversed(route):
                at = (at[0] + STEP[heading][0], at[1] + STEP[heading][1])
                squares.add(at)
            return {"route": list(reversed(route)), "square": list(here), "facing": facing,
                    "roll_squares": sorted([list(sq) for sq in squares])}
        for facing, (dx, dy) in STEP.items():
            nxt = (here[0] + dx, here[1] + dy)
            if nxt in previous or not roll_square(geo, *nxt) or not geo.is_passable(*here, facing):
                continue
            previous[nxt] = (here, facing)
            queue.append(nxt)
    raise RouteError(f"no roll square with an open roll square beside it is reachable from {start}")


def _slot(disk: amiga_adf.AmigaDisk, letter: str):
    return amiga_savegame.read_slot(disk, letter, TITLE)


def member_fields(raw: bytes) -> dict[str, int]:
    return {field: raw[at] for field, at in RECORD.items()}


def _name(raw: bytes) -> str:
    return raw[:0x10].split(b"\0", 1)[0].replace(b"\xff", b" ").decode("latin-1")


def _digest(shot: pathlib.Path) -> str | None:
    """The crop's bytes as a digest, None for a grab that left no crop."""
    try:
        return hashlib.sha256(pathlib.Path(shot).read_bytes()).hexdigest()
    except OSError:
        return None


def plan(geo, start: tuple[int, int], target: tuple[int, int]) -> list[int]:
    """The facings of the shortest walk over `geo` (`cursethac0.plan`, the DOS step's planner)."""
    from tools.curse_of_the_azure_bonds import cursethac0  # noqa: PLC0415

    return cursethac0.plan(geo, start, target)


def area_map(diskb: pathlib.Path, name: str):
    """The map `name` out of disk B's `GEO.GLB`."""
    from automap import amiga  # noqa: PLC0415

    maps = amiga.load_maps(diskb)
    require(name in maps, f"{diskb} holds no {name}")
    return maps[name]


def tavern_map(diskb: pathlib.Path):
    """`TAVERN_GEO` out of disk B's `GEO.GLB`."""
    return area_map(diskb, TAVERN_GEO)


def stage_slot(local: pathlib.Path, load: str, staged: bytes) -> dict:
    """Write `staged` over slot `load` of the copy at `local`, in place; the copy's new digest."""
    path = amiga_savegame.slot_path(amiga_savegame.CURSE, load)
    copy = amiga_adf.AmigaDisk.open(local)
    replace_file_in_place(copy, path, staged)
    copy.save(local)
    check = amiga_adf.AmigaDisk.open(local)
    require(not check.verify() and check.read_file(path) == staged,
            "the staged slot does not read back")
    return {"path": str(local), "sha256": sha256(local)}


def stage_gate(local: pathlib.Path, load: str) -> dict:
    """Set the Pit's gate in slot `load` of the copy at `local`, in place; the copy's new digest."""
    path = amiga_savegame.slot_path(amiga_savegame.CURSE, load)
    staged = with_gate(amiga_adf.AmigaDisk.open(local).read_file(path), PIT_GATE_ON)
    digest = stage_slot(local, load, staged)
    check = amiga_adf.AmigaDisk.open(local)
    require(gate_word(check.read_file(path)) == PIT_GATE_ON, "the staged gate does not read back")
    return digest


def parse_records(records: list[str], names: list[str]) -> list[dict]:
    """Read and check every `NAME:FIELD=VALUE[,FIELD=VALUE]` before anything is written.

    A value is decimal or `0x` hex. Stops on a member outside the party or named twice, a
    field outside `STAGE_FIELDS`, a field named twice, or a value out of range: hit points
    1-255, a memorised spell 1-0x7F.
    """
    plans: list[dict] = []
    for text in records:
        name, sep, fields_text = text.partition(":")
        require(bool(sep) and bool(name) and bool(fields_text),
                f"stage record {text!r} is not NAME:FIELD=VALUE[,FIELD=VALUE]")
        require(name in names, f"{name} is not in the party: {names}")
        require(all(plan["name"] != name for plan in plans), f"{name} is named twice")
        changes: dict[str, int] = {}
        for part in fields_text.split(","):
            field, sep, value = part.partition("=")
            require(bool(sep), f"stage record field {part!r} is not FIELD=VALUE")
            require(field in STAGE_FIELDS,
                    f"a stage record writes only hp, hp_max and memorised0-memorised"
                    f"{MEMORISED_SIZE - 1}, not {field!r}")
            require(field not in changes, f"stage record names {field} twice")
            try:
                number = int(value, 0)
            except ValueError:
                raise RouteError(f"stage record value {value!r} is not a number") from None
            top = 0x7F if field.startswith("memorised") else 0xFF
            require(1 <= number <= top, f"{field} {number} is not 1 to {top}")
            changes[field] = number
        plans.append({"name": name, "changes": changes})
    return plans


def apply_records(data: bytes, blocks: tuple, names: list[str],
                  plans: list[dict]) -> tuple[bytes, list[dict]]:
    """The saved game's bytes with each planned field written, and what the manifest records:
    each byte's record and file offset, before and after.

    Stops, with nothing returned, on a memorised slot that was not empty or a member whose hit
    points end above his maximum."""
    out = bytearray(data)
    staged: list[dict] = []
    for plan in plans:
        start = blocks[names.index(plan["name"])][0]
        fields = {}
        for field, value in plan["changes"].items():
            at = start + STAGE_FIELDS[field]
            require(not field.startswith("memorised") or out[at] == 0,
                    f"{plan['name']}'s {field} holds {out[at]:#04x}, not an empty slot")
            fields[field] = {"record_offset": STAGE_FIELDS[field], "file_offset": at,
                             "before": out[at], "after": value}
            out[at] = value
        hp, top = out[start + STAGE_FIELDS["hp"]], out[start + STAGE_FIELDS["hp_max"]]
        require(hp <= top, f"{plan['name']}: hp {hp} is above hp_max {top}")
        staged.append({"name": plan["name"], "fields": fields})
    return bytes(out), staged


def spells_of(raw: bytes) -> list[int]:
    """The ids the combat spell list would offer from a record's memorised slots: 1-0x7F."""
    return [b for b in raw[MEMORISED:MEMORISED + MEMORISED_SIZE] if 0 < b < 0x80]


def stage(manifest_path: pathlib.Path, source_disk: pathlib.Path, out: pathlib.Path, *,
          load: str, save: str, records: list[str] | None = None) -> pathlib.Path:
    """Copy a Curse save disk in as a prepare run's disk A and write `out/prepare.json`.

    Each of `records` (`parse_records`) is written into the loaded slot of the copy in the
    same in-place write as a Pit gate, and the manifest lists every byte written."""
    require(not out.exists(), f"{out} already exists")
    require(bool(SLOT.fullmatch(load)) and bool(SLOT.fullmatch(save)) and load != save,
            "the load and save letters must be two letters A-J")
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("title") == "curse", "the manifest is not a Curse prepare")
    for key, entry in (("diskb", manifest["disks"]["diskb"]), *manifest["registered"].items()):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"the {key} disk hash differs")
    source_hash = sha256(source_disk)
    disk = amiga_adf.AmigaDisk.open(source_disk)
    problems = disk.verify()
    require(not problems, f"{source_disk} fails ADF verification: {problems}")
    letters = curseadd.slot_letters(disk)
    require(load in letters, f"slot {load} is not on {source_disk}: {letters}")
    require(save not in letters, f"slot {save} is already on {source_disk}")
    saved = _slot(disk, load)
    names = [m.name for m in saved.characters]
    plans = parse_records(records or [], names)
    state = amiga_savegame.state_from_savegame(saved)
    place = {"area": state.area, "x": state.x, "y": state.y, "facing": state.facing}
    require(state.area in (TAVERN_AREA, PIT_AREA),
            f"slot {load} is in area {state.area}; the route knows only Tilverton, area "
            f"{TAVERN_AREA}, and the Pit of Moander, area {PIT_AREA}")
    diskb = pathlib.Path(manifest["disks"]["diskb"]["path"])
    if state.area == TAVERN_AREA:
        walk_plan: dict[str, Any] = {"route": plan(tavern_map(diskb), (state.x, state.y), TAVERN)}
        require(bool(walk_plan["route"]), f"no way from {state.x},{state.y} to the tavern")
    else:
        walk_plan = {"kind": PIT, **pit_plan(area_map(diskb, PIT_GEO), (state.x, state.y))}
    out.mkdir(parents=True)
    disks = {}
    for key, source in (("save", source_disk), ("diskb", diskb)):
        local = out / f"{key}.adf"
        shutil.copyfile(source, local)
        disks[key] = {"path": str(local), "sha256": sha256(local)}
    require(disks["save"]["sha256"] == source_hash, "the copy differs from the source disk")
    if state.area == PIT_AREA:
        walk_plan["staged"] = {f"{PIT_GATE:04X}": {"before": gate_word(saved.data),
                                                   "after": PIT_GATE_ON}}
        disks["save"] = stage_gate(pathlib.Path(disks["save"]["path"]), load)
    now = saved
    staged_records: list[dict] = []
    if plans:
        local = pathlib.Path(disks["save"]["path"])
        path = amiga_savegame.slot_path(amiga_savegame.CURSE, load)
        before = amiga_adf.AmigaDisk.open(local).read_file(path)
        written, staged_records = apply_records(before, saved.blocks, names, plans)
        disks["save"] = stage_slot(local, load, written)
        now = _slot(amiga_adf.AmigaDisk.open(local), load)
        require([m.name for m in now.characters] == names, "the staged slot's party differs")
    staged = {**manifest, "disks": disks,
              "prepared_from": {"path": str(manifest_path.resolve()),
                                "save_sha256": manifest["disks"]["save"]["sha256"]},
              "fight": {"source": {"path": str(source_disk.resolve()), "sha256": source_hash},
                        "load": load, "save": save, "place": place, **walk_plan,
                        "names": names, "staged_records": staged_records,
                        "spells": {m.name: spells_of(m.raw) for m in now.characters},
                        "members": {m.name: member_fields(m.raw) for m in now.characters}}}
    path = out / "prepare.json"
    write_json(path, staged)
    return path


class Memory:
    """Reads of the running game through WinUAE's pipe: never a write.

    The class attributes name the title, the global holding the record in turn and the
    record's fields; a subclass for another title replaces them.
    """

    title = TITLE
    current = CURRENT
    record = RECORD
    record_size = RECORD_SIZE

    def __init__(self, holder: str):
        self.holder = holder
        self._target: Any = None
        self._in_fight: bool | None = None
        #: The last mode read's error, None while the reads work.
        self.mode_error: str | None = None
        #: Held for every call on the located game, so a read a timed-out worker is still
        #: making never runs beside another on the same pipe.
        self._lock = threading.RLock()

    def target(self) -> Any:
        with self._lock:
            if self._target is None:
                from automap import amiga  # noqa: PLC0415

                target = amiga.AmigaTarget(amiga.WinuaePipe(holder=self.holder),
                                           amiga.MACHINES[self.title])
                target.locate()
                self._target = Serial(target, self._lock)
            return self._target

    def fields(self, raw: bytes) -> dict[str, int]:
        return {field: raw[at] for field, at in self.record.items()}

    def fix(self) -> tuple[int, int, int] | None:
        fix = self.target().fix()
        return None if fix is None else (fix.x, fix.y, fix.facing)

    def turn_pointer(self) -> int:
        """The address the global names as the record in turn; 0 before any turn."""
        target = self.target()
        return int.from_bytes(target.read(target.data_base + self.current, 4), "big")

    def owner(self) -> dict | None:
        address = self.turn_pointer()
        if not address:
            return None
        raw = bytes(self.target().read(address, self.record_size))
        return {"address": address, "name": _name(raw), **self.fields(raw)}

    def party(self) -> list[dict]:
        from automap import amigaparty  # noqa: PLC0415

        members = amigaparty.read_party(self.target())
        require(members is not None, "the party list does not read")
        return [{"name": m.name, **self.fields(m.raw)} for m in members]

    def in_fight(self) -> bool:
        """Whether the game's mode byte reads as a fight, from the last read that worked.

        A read that fails keeps the last answer and leaves its error in `mode_error`; before
        any read has worked it reads as not in a fight. It never locates the game: the sweep
        is the run's own step, and one that outlasts the read limit would fail every poll.
        """
        from automap import amigaparty  # noqa: PLC0415

        target = self._target
        if target is None:
            self.mode_error = "the game is not located yet"
            return bool(self._in_fight)

        def read(_holder: str) -> bool:
            row = amigaparty.row_for(target)
            require(row is not None, "the title has no party row")
            mode = amigaparty.mode(target)
            require(mode is not None, "the mode byte did not read")
            return mode == row.combat_value

        try:
            self._in_fight = curseadd.bounded(read, self.holder, MODE_READ_LIMIT)
            self.mode_error = None
        except RouteError as exc:
            self.mode_error = str(exc)
        return bool(self._in_fight)

    def variable(self, var: int) -> int | None:
        """A script variable's value in the running game, None when it does not read."""
        from automap import amigavars  # noqa: PLC0415

        return amigavars.read_variable(self.target(), self.title, var).value

    def _global(self, offset: int, size: int) -> int:
        target = self.target()
        return int.from_bytes(target.read(target.data_base + offset, size), "big")

    def watch(self, names: list[str], spell: int) -> dict[str, dict]:
        """Each named member's control, status, hit points, quickfight, creature type, effect
        ids in chain order, record address, and how many of `spell` he holds memorised."""
        from automap import amigaparty  # noqa: PLC0415

        members = amigaparty.read_party(self.target())
        require(members is not None, "the party list does not read")
        rows = {}
        for name in names:
            found = [m for m in members if m.name == name]
            require(len(found) == 1, f"{name} is in the party {len(found)} times")
            nodes = found[0].effects()
            rows[name] = watch_row(found[0].raw, found[0].address,
                                   [raw[0] for _at, raw in nodes], spell)
            rows[name]["nodes"] = [at for at, _raw in nodes]
        return rows

    def record_and_nodes(self, address: int, nodes: list[int]) -> list[bytes]:
        """The record at `address` and the effect nodes at `nodes`, in one request."""
        blocks = [(address, self.record_size), *((at, EFFECT_SIZE) for at in nodes)]
        return [bytes(raw) for raw in self.target().read_blocks(blocks)]

    def spell_list(self) -> tuple[int, list[int]]:
        """The combat spell list: its head pointer and every nonzero id in it."""
        target = self.target()
        ids = bytes(target.read(target.data_base + SPELL_LIST, MEMORISED_SIZE))
        return self._global(SPELL_LIST_HEAD, 4), [b for b in ids if b]

    def casting(self, address: int) -> int | None:
        """The spell the record at `address` has begun casting, None with no combat block."""
        target = self.target()
        block = int.from_bytes(target.read(address + COMBAT_BLOCK, 4), "big")
        return None if not block else bytes(target.read(block, 1))[0]

    def aim(self) -> tuple[int, int]:
        """The aim menu's target record address and the count of combatants NEXT steps through."""
        return self._global(AIM_TARGET, 4), self._global(AIM_COUNT, 1)


class Serial:
    """A located game whose every method call holds one lock.

    `WinuaePipe` sends each request on its own connection with no lock of its own, and the
    pipe takes one client at a time, so a worker `curseadd.bounded` gave up on can still be
    reading when the next read starts; under the lock that read waits instead.
    """

    def __init__(self, target: Any, lock: Any):
        self._inner, self._lock = target, lock

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._inner, name)
        if not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return value(*args, **kwargs)

        return call


def watch_row(raw: bytes, address: int, effects: list[int], spell: int) -> dict:
    """One watched member's reading: `RECORD`'s fields, his type, effects and spells left."""
    return {"address": address, **{field: raw[at] for field, at in RECORD.items()},
            "creature_type": raw[CREATURE_TYPE], "effects": list(effects),
            "spell_left": raw[MEMORISED:MEMORISED + MEMORISED_SIZE].count(spell)}


def _u32(raw: bytes, at: int) -> int:
    return int.from_bytes(raw[at:at + 4], "big")


def poll_row(blocks: list[bytes], address: int, nodes: list[int]) -> tuple[dict, list[int]]:
    """One poll's reading from `Memory.record_and_nodes`: the record's fields and effect ids,
    and the effect list's node addresses as far as this read could follow them.

    The list is followed from the record's head through the nodes read with it. When it reaches
    a node not among them (the list changed since the last read), `effects` is None and the
    addresses end with that node, so the next poll reads it. Raises `RouteError` on a list that
    comes back on itself or runs past `EFFECT_LIMIT`."""
    raw = blocks[0]
    fetched = dict(zip(nodes, blocks[1:]))
    chain: list[int] = []
    effects: list[int] | None = []
    at = _u32(raw, EFFECT_HEAD)
    while at:
        require(at not in chain and len(chain) < EFFECT_LIMIT,
                f"the effect list at {address:#x} does not end: {[hex(a) for a in chain]}")
        chain.append(at)
        node = fetched.get(at)
        if node is None:
            effects = None
            break
        effects.append(node[0])
        at = _u32(node, EFFECT_LINK)
    row = {"address": address, "name": _name(raw), **{f: raw[o] for f, o in RECORD.items()},
           "creature_type": raw[CREATURE_TYPE], "effects": effects}
    return row, chain


def walk(screens: Screens, memory: Memory, start: dict, route: list[int]) -> list[dict]:
    """Turn and step along `route`, each key on the map and each move read back from memory."""
    steps = []
    x, y, facing = start["x"], start["y"], start["facing"]
    seen = memory.fix()
    require(seen == (x, y, facing), f"the party stands at {seen}, not the loaded {x},{y},{facing}")

    def on_map() -> None:
        while screens.wait(("world", "continue"), 60) == "continue":
            screens.press("RET", "continue")
            screens.sleep(AFTER_KEY)

    def until(want: tuple[int, int, int]) -> tuple[int, int, int] | None:
        end = screens.clock() + MOVE_LIMIT
        got = None
        while screens.clock() < end:
            got = memory.fix()
            if got == want:
                break
            screens.sleep(1.0)
        return got

    def move(key: str, want: tuple[int, int, int]) -> None:
        """Press `key` on the map; a box that took the key is answered and the key sent once more."""
        for attempt in (1, 2):
            on_map()
            screens.press(key, "world")
            got = until(want)
            if got == want:
                return
            if attempt == 1 and "continue" in screens.look("move")[0]:
                continue
            break
        raise RouteError(f"{key} left the party at {got}, not {want}")

    for heading in route:
        for key in TURN_KEYS.get((heading - facing) % 4, ()):
            facing = (facing + (1 if key == "NP6" else -1)) % 4
            move(key, (x, y, facing))
        dx, dy = STEP[heading]
        x, y = x + dx, y + dy
        move("NP8", (x, y, facing))
        steps.append({"x": x, "y": y, "facing": facing})
        screens.sleep(AFTER_KEY)
    return steps


def pit_walk(screens: Any, memory: Any, start: dict, fight_: dict,
             limit: int = PIT_STEPS) -> dict:
    """Walk the plan's route, then step back and forth between its two roll squares, until a
    step brings up a screen that is not the map.

    Before each forward key the party's square and facing are read from memory, and the key
    goes only when they are where the walk left the party and the square ahead is one of the
    plan's roll squares; otherwise the walk stops with nothing sent. Every key goes on a grab
    the map guard matched. Each move is read back from memory, and after each step the map must
    hold `STEP_SETTLE` seconds before the next key.
    """
    steps: list[dict] = []
    roll = {tuple(sq) for sq in fight_["roll_squares"]}
    x, y, facing = start["x"], start["y"], start["facing"]
    seen = memory.fix()
    require(seen == (x, y, facing), f"the party stands at {seen}, not the loaded {x},{y},{facing}")

    def until(want: tuple[int, int, int]) -> tuple[int, int, int] | None:
        end = screens.clock() + MOVE_LIMIT
        got = None
        while screens.clock() < end:
            got = memory.fix()
            if got == want:
                break
            screens.sleep(1.0)
        return got

    def settled() -> str | None:
        """None while the map holds for `STEP_SETTLE`; else the crop that showed another screen."""
        end = screens.clock() + STEP_SETTLE
        while screens.clock() < end:
            shown, shot = screens.look("step")
            # A grab that left no crop is no reading of the screen.
            if "world" not in shown and not pathlib.Path(shot).name.endswith("-raw.png"):
                screens.events.append({"met": shown, "shot": str(shot)})
                return str(shot)
            screens.sleep(2.0)
        return None

    headings = list(fight_["route"])
    back = (fight_["facing"] + 2) % 4
    for n in range(len(headings) + limit):
        heading = headings[n] if n < len(headings) else (
            fight_["facing"] if (n - len(headings)) % 2 == 0 else back)
        for key in TURN_KEYS.get((heading - facing) % 4, ()):
            facing = (facing + (1 if key == "NP6" else -1)) % 4
            screens.wait(("world",), 30, past=())
            screens.press(key, "world")
            got = until((x, y, facing))
            require(got == (x, y, facing), f"{key} left the party at {got}, not {x},{y},{facing}")
        screens.wait(("world",), 30, past=())
        seen = memory.fix()
        require(seen == (x, y, facing),
                f"the party stands at {seen}, not {x},{y},{facing}; no step was sent")
        dx, dy = STEP[heading]
        require((x + dx, y + dy) in roll,
                f"{x + dx},{y + dy} ahead of {x},{y} is not one of the plan's roll squares; "
                "no step was sent")
        x, y = x + dx, y + dy
        screens.press("NP8", "world")
        got = until((x, y, facing))
        met = settled()
        require(got == (x, y, facing) or met is not None,
                f"NP8 left the party at {got}, not {x},{y},{facing}")
        steps.append({"x": x, "y": y, "facing": facing})
        if met is not None:
            return {"steps": steps, "met": met}
    raise RouteError(f"{limit} steps between the two roll squares met no fight")


def reach_tavern(screens: Screens) -> None:
    """Wait for the PUNCH bar, answering the injuries question that comes first on a save
    whose brawl already happened with IGNORE THEM."""
    if screens.wait(("tavern", "injuries"), 60, past=("world", "continue")) == "injuries":
        screens.press("I", "injuries")
        screens.sleep(AFTER_KEY)
        screens.wait(("tavern",), 60, past=("world", "continue", "injuries"))


def _same(name: str) -> str:
    return name


@dataclasses.dataclass(frozen=True)
class FightRules:
    """What one title's fight loop recognises and answers."""

    #: The states told apart, in the order a grab's first match names it.
    known: tuple[str, ...]
    #: The key each answered screen gets.
    answers: dict[str, str]
    #: The record-in-turn fields each bar's log keeps.
    bar_fields: tuple[str, ...]
    #: Seconds the map, or a screen in `starting`, may show before the first bar.
    linger: float
    #: Screens still drawn while the fight starts, waited out for `linger`.
    starting: tuple[str, ...] = ()
    #: Screens that get a key only once a bar has shown.
    after_bars: dict[str, str] = dataclasses.field(default_factory=dict)
    #: Screens that mean the fight was won. When any are named, a fight that reaches the map
    #: without one of them stops the run instead of being taken as won.
    won: tuple[str, ...] = ()
    #: Screens that end the fight as lost at once: one with a key in `answers` gets that key,
    #: and nothing after it is waited for; the others get none.
    defeat: tuple[str, ...] = ()
    #: How a bar owner's name and a `--member` name are compared.
    name_key: Callable[[str], str] = _same


#: The tavern brawl: the PUNCH bar may still show as the brawl starts and gets LEAVE after it.
#: The script prints the "tossed outside" line after the fight whatever its result, so the
#: result is read from the game's own end-of-fight message (`/Curse 0x2D538`): THE PARTY HAS
#: WON for a win, and for a party all down the destroyed message, which the brawl's script
#: never stops by setting the spare flag `$7EE6`.
CURSE_FIGHT = FightRules(
    known=KNOWN, answers=FIGHT_ANSWERS,
    bar_fields=("control", "status", "quickfight", "hit_points"), linger=TAVERN_LINGER,
    starting=("tavern",), after_bars={"tavern": "L"}, defeat=("party_destroyed",),
    won=("party_won",))

#: The Pit's wandering fight: the map may still show while its monsters load, and the
#: encounter's own pages and the slugs' question come before the first bar. A destroyed party's
#: message gets RETURN and ends the fight as lost, with nothing after it waited for.
PIT_FIGHT = FightRules(
    known=PIT_KNOWN, answers=PIT_ANSWERS,
    bar_fields=("control", "status", "quickfight", "hit_points"), linger=PIT_LINGER,
    defeat=("party_destroyed",))


def _listed(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


def cast_spends(log: dict) -> list[dict]:
    """Each cast event's spend: the caster's count at the event's own bar read less his count
    at the first read after it, and every later drop before the next event's bar (that read
    included) as a cast the computer made for him. A spend no read has followed yet is None.

    Taken from the reads alone, so a receipt an earlier driver wrote replays the same way."""
    caster, reads = log["caster"], log["reads"]
    starts = [next((i for i, r in enumerate(reads) if r["when"] == f"bar {e['bar']} ({caster})"),
                   None) for e in log["events"]]
    out = []
    for n, (event, start) in enumerate(zip(log["events"], starts)):
        later = next((s for s in starts[n + 1:] if s is not None), len(reads) - 1)
        counts = ([] if start is None else
                  [(r["when"], r[caster]["spell_left"]) for r in reads[start + 1:later + 1]
                   if caster in r])
        if not counts:
            out.append({"spent": None, "left_after": None, "computer_casts": []})
            continue
        computer = [{"when": when, "spent": before - left}
                    for (_w, before), (when, left) in zip(counts, counts[1:]) if left < before]
        out.append({"spent": event["left_before"] - counts[0][1], "left_after": counts[0][1],
                    "computer_casts": computer})
    return out


class Captured(Exception):
    """`--capture` reached the aim menu and kept its frame; the fight goes no further."""


class Cast:
    """One caster's spell, cast on his own bars at one member, with another member watched.

    On the caster's bar, while the watched member has never held `LOWERING` and the caster
    still holds the spell, the bar gets CAST; while the watched member is confused it gets
    DONE instead; after that it gets QUICK, as every other bar does. The list gets CAST once
    every id on it is the spell; the aim menu, which the game shows straight after the list,
    gets NEXT until the target global holds the aim member's record, then TARGET. Every bar
    reads the watched member and the caster. A cast's spend is the drop in the caster's count
    from his bar to the first read after it (`cast_spends`); a later drop is logged as a cast the
    computer made for him. Every fight grab is checked for the watched member's messages, and
    polls his record alone in one request.

    With `capture`, a frame is kept for the list and one for the aim menu, and the aim menu's
    frame ends the fight with nothing pressed on it. Only the guarded list gets CAST; an
    unguarded frame never gets a key, because the list's ids stay in memory after the list
    closes and so cannot tell a fresh list from a stale one. An unguarded frame memory takes
    for the list is kept and ends the fight there.
    """

    def __init__(self, memory: Any, caster: str, spell: int, aim: str, watch: str, *,
                 capture: bool = False):
        self.memory, self.caster, self.spell = memory, caster, spell
        self.aim_at, self.watched = aim, watch
        self.capture = capture
        #: idle, chose (CAST on the bar), begun (CAST on the list) or aimed (TARGET).
        self.phase = "idle"
        self.events: list[dict] = []
        self.reads: list[dict] = []
        self.captures: list[dict] = []
        self.lowered = False
        self.left: int | None = None
        self.quick = False
        self._chose_at = 0.0
        self._list_digest: str | None = None
        #: Each change in the watched member's `WATCHED_FIELDS`, with the frame it was read at.
        self.changes: list[dict] = []
        self._last_seen: tuple | None = None
        #: Frames that showed one of the watched member's messages, and failed poll reads.
        self.messages: list[dict] = []
        self.poll_errors: list[dict] = []
        #: A poll read that outlived its limit and is still running; no poll starts beside it.
        self._poll_worker: threading.Thread | None = None
        self.polls_skipped = 0
        #: Polls made before any read gave the watched member's record address.
        self.polls_unaddressed = 0
        #: The watched member's record and effect-node addresses from the last read of him.
        self._watched_at: int | None = None
        self._nodes: list[int] = []

    def names(self) -> list[str]:
        return list(dict.fromkeys((self.watched, self.caster, self.aim_at)))

    def read(self, screens: Any, when: str) -> dict:
        rows = curseadd.bounded(lambda _h: self.memory.watch(self.names(), self.spell),
                                self.memory.holder, screens.left(READ_LIMIT))
        reading = {"when": when, **rows}
        self.reads.append(reading)
        screens.events.append({"watch": reading})
        self._watched_at = rows[self.watched]["address"]
        self._nodes = list(rows[self.watched].get("nodes", ()))
        self._note(screens, rows[self.watched], when)
        self._spends()
        return reading

    def _spends(self) -> None:
        """Write each cast event's spend and the computer's later casts, from the reads so far."""
        for event, spend in zip(self.events, cast_spends(self.log())):
            if spend["spent"] is not None:
                event.update(left_after=spend["left_after"], spent=spend["spent"],
                             computer_casts=spend["computer_casts"])

    def _note(self, screens: Any, row: dict, when: str, frame: int | None = None) -> None:
        """Log the watched member's row when any of `WATCHED_FIELDS` differs from the last.

        A poll that could not follow his whole effect list reads `effects` as None."""
        if set(row["effects"] or ()) & set(LOWERING):
            self.lowered = True
        seen = tuple(_listed(row[f]) for f in WATCHED_FIELDS)
        if seen == self._last_seen:
            return
        self._last_seen = seen
        change = {"frame": screens.count if frame is None else frame, "when": when,
                  **{f: (None if row[f] is None else list(row[f])) if f == "effects" else row[f]
                     for f in WATCHED_FIELDS}}
        self.changes.append(change)
        screens.events.append({"watch_change": change})

    def check_messages(self, screens: Any, shot: Any) -> None:
        """Record a frame showing one of the watched member's messages; reads no memory."""
        for message, guard in MESSAGE_GUARDS.get(self.watched, {}).items():
            if guard in screens.guards and screens.guards(guard, shot):
                self.messages.append({"frame": screens.count, "message": message,
                                      "shot": str(shot)})
                screens.events.append({"message": self.messages[-1]})

    def poll(self, screens: Any, shot: Any) -> float:
        """One fight poll: record a frame showing one of the watched member's messages, then
        read his record and the effect nodes the last read found, in one request, and log a
        change, returning the seconds the read took. Before any read has given his address no
        poll reads. A read that fails or outlives `POLL_READ_LIMIT` is logged and the fight goes
        on; while such a read is still running no poll reads, so two reads never overlap."""
        self.check_messages(screens, shot)
        if self._poll_worker is not None and self._poll_worker.is_alive():
            self.polls_skipped += 1
            return 0.0
        self._poll_worker = None
        if self._watched_at is None:
            self.polls_unaddressed += 1
            return 0.0
        began, frame = screens.clock(), screens.count
        address, nodes = self._watched_at, list(self._nodes)
        result: dict[str, Any] = {}

        def work() -> None:
            try:
                result["blocks"] = self.memory.record_and_nodes(address, nodes)
            except BaseException as exc:  # noqa: BLE001 - logged by the poll below
                result["error"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=work, name="cursefight-poll", daemon=True)
        worker.start()
        worker.join(screens.left(POLL_READ_LIMIT))
        error = None
        if worker.is_alive():
            self._poll_worker = worker
            error = f"no answer in {POLL_READ_LIMIT:.0f}s"
        elif "error" in result:
            error = result["error"]
        else:
            try:
                row, chain = poll_row(result["blocks"], address, nodes)
                require(row["name"] == self.watched,
                        f"the record at {address:#x} holds {row['name']!r}, not {self.watched}")
            except RouteError as exc:
                error = str(exc)
            else:
                self._nodes = chain
                self._note(screens, row, "poll", frame)
        if error is not None:
            self.poll_errors.append({"frame": frame, "error": error})
        return max(0.0, screens.clock() - began)

    def _settle(self, reading: dict) -> None:
        """Close a cast the caster's next bar or the fight's end finds unfinished, and take the
        caster's count from this reading."""
        if self.phase in ("chose", "begun"):
            self.events[-1]["outcome"] = "lost" if self.phase == "begun" else "no_list"
            self.phase = "idle"
        if self.phase == "aimed":
            self.phase = "idle"
        self.left = reading[self.caster]["spell_left"]

    def on_bar(self, owner: dict, screens: Any, bar: int) -> str:
        """The key for a bar: CAST, DONE or QUICK on the caster's, QUICK on everyone else's."""
        reading = self.read(screens, f"bar {bar} ({owner['name']})")
        if owner["name"] != self.caster:
            return "Q"
        self._settle(reading)
        if self.lowered or not self.left or self.quick:
            self.quick = True
            return "Q"
        if CONFUSED in reading[self.watched]["effects"]:
            return "D"
        self.events.append({"bar": bar, "left_before": self.left})
        self.phase, self._chose_at = "chose", screens.clock()
        return "C"

    def bar_again(self, owner: dict, screens: Any) -> bool:
        """Whether a caster's bar still showing just after CAST is that same bar, not a new one.

        A bar that outlasts `CAST_LINGER` is taken as CAST not having opened the list."""
        if self.phase != "chose" or owner["name"] != self.caster:
            return False
        require(screens.clock() - self._chose_at < CAST_LINGER,
                f"{self.caster}'s bar stayed {CAST_LINGER:.0f}s after CAST")
        return True

    def after(self, screens: Any) -> dict:
        """The read once the fight is over, closing any cast still open."""
        reading = self.read(screens, "after the fight")
        self._settle(reading)
        return reading

    def check_list(self, screens: Any, shot: Any) -> None:
        require(self.phase == "chose", f"the spell list showed with no CAST on the bar; {shot}")
        head, ids = curseadd.bounded(lambda _h: self.memory.spell_list(), self.memory.holder,
                                     screens.left(READ_LIMIT))
        require(head != 0 and bool(ids), f"the spell list reads empty in memory; {shot}")
        require(all(i == self.spell for i in ids),
                f"the spell list holds {ids}, not only {self.spell}; {shot}")
        self.events[-1]["listed"] = len(ids)

    def on_list(self, screens: Any, shot: Any) -> None:
        self.check_list(screens, shot)
        screens.press("C", "spell_list")
        self.phase = "begun"
        screens.sleep(AFTER_KEY)
        caster = self._address(self.caster, screens)
        self.events[-1]["casting_after_list"] = curseadd.bounded(
            lambda _h: self.memory.casting(caster), self.memory.holder, screens.left(READ_LIMIT))

    def _address(self, name: str, screens: Any) -> int:
        rows = [r for r in reversed(self.reads) if name in r]
        if not rows:
            self.read(screens, "address")
            rows = [self.reads[-1]]
        return rows[0][name]["address"]

    def _in_turn(self, screens: Any) -> tuple[int, int | None]:
        caster = self._address(self.caster, screens)
        pointer = curseadd.bounded(lambda _h: self.memory.turn_pointer(), self.memory.holder,
                                   screens.left(READ_LIMIT))
        casting = (curseadd.bounded(lambda _h: self.memory.casting(caster), self.memory.holder,
                                    screens.left(READ_LIMIT)) if pointer == caster else None)
        return pointer, casting

    def on_aim(self, screens: Any, shot: Any) -> None:
        """NEXT until the target global names the aim member's record, then TARGET.

        The menu comes straight after the list's CAST, with the caster in turn; a second menu
        for the same cast (aimed again when a deferred spell goes off) is answered the same way.
        """
        require(self.phase in ("begun", "aimed"),
                f"the aim menu showed with no spell chosen; {shot}")
        caster = self._address(self.caster, screens)
        pointer, casting = self._in_turn(screens)
        require(pointer == caster, f"the aim menu showed with {pointer:#x} in turn, not "
                                   f"{self.caster} ({caster:#x}); {shot}")
        want = self._address(self.aim_at, screens)
        target, count = curseadd.bounded(lambda _h: self.memory.aim(), self.memory.holder,
                                         screens.left(READ_LIMIT))
        event = self.events[-1]
        event["aims"] = event.get("aims", 0) + 1
        event.update(casting_at_aim=casting, aim_count=count, targets=[target])
        limit = count if 0 < count <= AIM_PRESSES else AIM_PRESSES
        presses = 0
        while target != want:
            require(presses < limit, f"{presses} NEXT presses never reached {self.aim_at} "
                                     f"({want:#x}): {[hex(t) for t in event['targets']]}")
            seen, now = screens.look("aim")
            require("aim" in seen, f"the aim menu went before TARGET; shot {now}")
            screens.press("N", "aim")
            presses += 1
            screens.sleep(AFTER_KEY)
            target, _count = curseadd.bounded(lambda _h: self.memory.aim(), self.memory.holder,
                                              screens.left(READ_LIMIT))
            require(target not in event["targets"],
                    f"NEXT came back to {target:#x} without reaching {self.aim_at} ({want:#x})")
            event["targets"].append(target)
        seen, now = screens.look("aim")
        require("aim" in seen, f"the aim menu went before TARGET; shot {now}")
        screens.press("T", "aim")
        event.update(outcome="aimed", next_presses=presses, target=target)
        self.phase = "aimed"
        screens.sleep(AFTER_KEY)
        event["casting_after_target"] = curseadd.bounded(
            lambda _h: self.memory.casting(caster), self.memory.holder, screens.left(READ_LIMIT))

    def keep_list(self, screens: Any, shot: Any) -> None:
        """With `capture`, keep the guarded list's frame before it gets CAST."""
        if self.capture:
            self.captures.append({"screen": "spell_list", "shot": str(shot)})
            screens.events.append({"capture": self.captures[-1]})
            self._list_digest = _digest(shot)

    def keep_aim(self, screens: Any, shot: Any) -> None:
        """Keep the aim menu's frame with the target globals, and end the fight there."""
        pointer, casting = self._in_turn(screens)
        target, count = curseadd.bounded(lambda _h: self.memory.aim(), self.memory.holder,
                                         screens.left(READ_LIMIT))
        self.captures.append({"screen": "aim", "shot": str(shot), "pointer": pointer,
                              "target": target, "count": count, "casting": casting})
        screens.events.append({"capture": self.captures[-1]})
        raise Captured(str(shot))

    def unguarded(self, screens: Any, shot: Any, digest: str | None, still_since: float) -> None:
        """With `capture`, keep a held unguarded frame memory takes for the list or the aim
        menu and end the fight there (`Captured`). Nothing is ever pressed on such a frame.

        In phase `chose` it is the list when the caster is in turn and a list reads in memory,
        which may be the last list's ids; in phase `begun`, entered only by CAST on the guarded
        list, it is the aim menu when the caster is in turn and the frame is not the list's."""
        if not self.capture or self.phase not in ("chose", "begun"):
            return
        if digest is None or screens.clock() - still_since < CAPTURE_STILL:
            return
        if self.phase == "chose":
            pointer, _casting = self._in_turn(screens)
            head, ids = curseadd.bounded(lambda _h: self.memory.spell_list(), self.memory.holder,
                                         screens.left(READ_LIMIT))
            if pointer != self._address(self.caster, screens) or not head or not ids:
                return
            self.captures.append({"screen": "spell_list", "shot": str(shot), "ids": ids,
                                  "guarded": False})
            screens.events.append({"capture": self.captures[-1]})
            raise Captured(str(shot))
        if digest == self._list_digest:
            return
        pointer, _casting = self._in_turn(screens)
        if pointer == self._address(self.caster, screens):
            self.keep_aim(screens, shot)

    def log(self) -> dict:
        return {"caster": self.caster, "spell": self.spell, "aim": self.aim_at,
                "watch": self.watched, "events": self.events, "reads": self.reads,
                "captures": self.captures, "lowered_seen": self.lowered, "quick": self.quick,
                "changes": self.changes, "messages": self.messages,
                "poll_errors": self.poll_errors, "polls_skipped": self.polls_skipped,
                "polls_unaddressed": self.polls_unaddressed}


def fight(screens: Screens, memory: Memory, members: list[str],
          rules: FightRules = CURSE_FIGHT, found: dict | None = None,
          cast: Cast | None = None) -> dict:
    """Answer every screen from the first bar to the map; log each bar with its owner.

    With `found`, its `bars` and `answered` are the lists the loop fills as it goes, so a
    caller still holds them when a stop inside the fight raises. With `cast`, each bar's key
    and the list, aim and abort screens are `cast`'s, every grab is a `cast.poll` of the
    watched member, and a `--capture` that reaches the aim menu ends the fight there as
    `captured`.
    """
    bars: list[dict] = []
    answered: list[dict] = []
    if found is not None:
        found.update(bars=bars, answered=answered)
    started = still_since = guided = screens.clock()
    settle_from = None
    lost = won = captured = False
    last: object = object()
    while True:
        require(screens.clock() - started < FIGHT_LIMIT,
                f"the fight was still going after {FIGHT_LIMIT:.0f}s")
        seen, shot = screens.look("fight")
        if cast is not None and screens.grabbed:
            # The poll's own time is no time the screen was watched, so no timer counts it.
            spent = cast.poll(screens, shot)
            started, still_since, guided = started + spent, still_since + spent, guided + spent
            settle_from = None if settle_from is None else settle_from + spent
        state = next((s for s in rules.known if s in seen), None)
        digest = _digest(shot)
        if state is not None:
            guided = screens.clock()
        # A grab with no crop counts as one more of the same, so a stuck one stops the run too.
        if digest != last:
            last, still_since = digest, screens.clock()
        # A fight the game ran without a command bar ends on the map after its won message.
        if state == "world" and (bars or won):
            settle_from = settle_from if settle_from is not None else screens.clock()
            if screens.clock() - settle_from >= MAP_SETTLE:
                break
            screens.sleep(2.0)
            continue
        settle_from = None
        if state == "world" and not bars and screens.clock() - started < rules.linger:
            # The map still showing while the fight starts.
            screens.sleep(1.5)
            continue
        if state in rules.defeat:
            key = rules.answers.get(state)
            if key is not None:
                screens.press(key, state)
            answered.append({"screen": state, "shot": str(shot),
                             **({"key": key} if key is not None else {})})
            lost = True
            break
        named = "a screen no guard knows" if state is None else f"the {state} screen"
        require(screens.clock() - still_since < FIGHT_STALL,
                f"{named} stayed {FIGHT_STALL:.0f}s unchanged mid-fight; shot {shot}")
        if state is None:
            try:
                if cast is not None:
                    cast.unguarded(screens, shot, digest, still_since)
            except Captured:
                captured = True
                break
            # An animated picture keeps changing the frame, so the digest above never trips;
            # the monster turns of a fight are such pictures, and the game's mode byte tells
            # them from a stalled bar.
            if memory.in_fight():
                guided = screens.clock()
            require(screens.clock() - guided < FIGHT_STALL,
                    f"{named} stayed {FIGHT_STALL:.0f}s with no guard matching and no key "
                    f"pressed outside a fight"
                    + (f" (mode read: {memory.mode_error})" if memory.mode_error else "")
                    + f"; shot {shot}")
            screens.sleep(1.5)
            continue
        key = rules.answers.get(state)
        if state == "combat_bar":
            owner = curseadd.bounded(lambda _h: memory.owner(), memory.holder,
                                     screens.left(READ_LIMIT))
            again, _ = screens.look("bar-again")
            require("combat_bar" in again, f"the command bar went before its owner was read; {shot}")
            require(owner is not None, f"a command bar with no record in turn; {shot}")
            if cast is not None and cast.bar_again(owner, screens):
                screens.sleep(1.5)
                continue
            bars.append({"owner": owner["name"], "address": owner["address"],
                         **{field: owner[field] for field in rules.bar_fields},
                         "shot": str(shot), "number": len(bars) + 1})
            screens.events.append({"bar": bars[-1]})
            if cast is not None:
                key = cast.on_bar(owner, screens, len(bars))
        elif cast is not None and state in ("spell_list", "aim", "abort_spell"):
            if state == "spell_list":
                cast.keep_list(screens, shot)
                cast.on_list(screens, shot)
            elif state == "aim" and cast.capture:
                answered.append({"screen": state, "shot": str(shot)})
                try:
                    cast.keep_aim(screens, shot)
                except Captured:
                    captured = True
                    break
            elif state == "aim":
                cast.on_aim(screens, shot)
            else:
                screens.press("N", state)
                screens.sleep(AFTER_KEY)
            answered.append({"screen": state, "shot": str(shot)})
            continue
        elif state in rules.after_bars and bars:
            key = rules.after_bars[state]
            screens.press(key, state)
            answered.append({"screen": state, "key": key, "shot": str(shot)})
            screens.sleep(AFTER_KEY)
            continue
        elif state in rules.starting:
            # The bar the fight began on, still drawn while it starts.
            require(screens.clock() - started < rules.linger,
                    f"the {state} bar stayed {rules.linger:.0f}s after the fight began; "
                    f"shot {shot}")
            screens.sleep(1.5)
            continue
        elif state not in rules.answers:
            raise RouteError(f"{state} showed mid-fight; shot {shot}")
        won = won or state in rules.won
        screens.press(key, state)
        answered.append({"screen": state, "key": key, "shot": str(shot)})
        screens.sleep(AFTER_KEY)
    if captured:
        return {"bars": bars, "answered": answered, "outcome": "captured"}
    require(lost or won or not rules.won,
            f"the fight reached the map without the {', '.join(rules.won)} screen, so its "
            f"result is unknown; shot {shot}")
    owners = {rules.name_key(bar["owner"]) for bar in bars}
    missing = [name for name in members if rules.name_key(name) not in owners]
    require(lost or not missing, f"{missing} had no command bar; bars went to {sorted(owners)}")
    return {"bars": bars, "answered": answered, "outcome": "lost" if lost else "won"}


def check_members(party: list[dict], manifest: dict, members: list[str]) -> dict:
    """Each named member is in the party with quickfight 1, still standing as loaded."""
    loaded = manifest["fight"]["members"]
    found = {}
    for name in members:
        rows = [m for m in party if m["name"] == name]
        require(len(rows) == 1, f"{name} is in the party {len(rows)} times after the fight")
        row = rows[0]
        require(row["quickfight"] == 1, f"{name} holds quickfight {row['quickfight']} after QUICK")
        require(row["control"] == loaded[name]["control"] and row["status"] == loaded[name]["status"]
                and row["hit_points"] > 0,
                f"{name} fell or changed in the fight: {row}, loaded as {loaded[name]}")
        found[name] = row
    return found


def destroyed(found: dict, rules: FightRules) -> bool:
    """Record in `found` whether the fight ended on one of `rules`' defeat screens."""
    found["destroyed"] = bool(found["answered"]) and (
        found["answered"][-1]["screen"] in rules.defeat)
    return found["destroyed"]


def drive(screens: Screens, manifest: dict, members: list[str], memory: Memory, *,
          save: bool, found: dict | None = None, no_fight: bool = False,
          cast: Cast | None = None) -> dict:
    """Load, begin, walk to the fight and take it; each reading goes into `found` as it is
    made, so a step that stops still leaves what came before it for the receipt. With
    `no_fight` the party camps and saves as loaded, with no walk and no fight. A destroyed
    party ends the drive at its message, saving nothing; after any other fight each member
    named must pass `check_members` before the save. With `cast` the fight is `cast`'s, its
    watched member is read once more after the fight, and a capture that reached the aim menu
    ends the drive there, saving nothing."""
    fight_ = manifest["fight"]
    pit = fight_.get("kind") == PIT
    found = {} if found is None else found
    screens.to_party_menu()
    screens.press("L", "title")
    screens.wait(("load_picker",), 60, past=("title",))
    screens.press(fight_["load"], "load_picker")
    errors = 0
    while screens.wait(("loaded_menu", "load_error"), 120, past=("load_picker",)) == "load_error":
        require(errors < LOAD_ERRORS, f"{LOAD_ERRORS} load errors and still no party menu")
        screens.press("RET", "load_error")
        errors += 1
        screens.sleep(AFTER_KEY + 1)
    found["load_errors"] = errors
    found["loaded"] = curseadd.bounded(lambda _h: memory.party(), memory.holder,
                                       screens.left(READ_LIMIT))
    names = [m["name"] for m in found["loaded"]]
    require(names == fight_["names"], f"the loaded party is {names}, not {fight_['names']}")
    screens.press("B", "loaded_menu")
    screens.wait(("world",), 90, past=("loaded_menu",))
    if no_fight:
        screens.sleep(AFTER_KEY)
        camp_save(screens, fight_["save"])
        return found
    if pit:
        found[LIVE_GATE] = curseadd.bounded(lambda _h: memory.variable(PIT_GATE), memory.holder,
                                            screens.left(READ_LIMIT))
        require(found[LIVE_GATE] == PIT_GATE_ON,
                f"the gate ${PIT_GATE:04X} reads {found[LIVE_GATE]} in the running game, "
                f"not {PIT_GATE_ON}; no step was sent")
        screens.sleep(AFTER_KEY)
        found["walk"] = pit_walk(screens, memory, fight_["place"], fight_)
        found.update(fight(screens, memory, members, PIT_FIGHT, found=found,
                           **({"cast": cast} if cast is not None else {})))
        found["first_bar"] = found["bars"][0] if found["bars"] else None
        if found.get("outcome") == "captured" or destroyed(found, PIT_FIGHT):
            return found
        found[GATE_AFTER] = curseadd.bounded(lambda _h: memory.variable(PIT_GATE),
                                             memory.holder, screens.left(READ_LIMIT))
    else:
        screens.sleep(AFTER_KEY)
        found["walk"] = walk(screens, memory, fight_["place"], fight_["route"])
        reach_tavern(screens)
        screens.press("P", "tavern")
        screens.sleep(AFTER_KEY)
        found.update(fight(screens, memory, members,
                           **({"cast": cast} if cast is not None else {})))
        if found.get("outcome") == "captured" or destroyed(found, CURSE_FIGHT):
            return found
    if cast is not None:
        found["watch_after"] = cast.after(screens)
    found["after"] = curseadd.bounded(lambda _h: memory.party(), memory.holder,
                                      screens.left(READ_LIMIT))
    found["members"] = check_members(found["after"], manifest, members)
    if not save:
        return found
    camp_save(screens, fight_["save"])
    return found


def camp_save(screens: Screens, letter: str) -> None:
    """From the map: camp, save to `letter`, and answer the exit question with NO."""
    screens.wait(("world",), 30, past=())
    screens.press("E", "world")
    screens.wait(("camp",), 60, past=("world",))
    screens.press("S", "camp")
    screens.wait(("camp_save_picker",), 60, past=("camp",))
    screens.press(letter, "camp_save_picker")
    screens.wait(("exit_game",), 120, past=("camp_save_picker",))
    screens.sleep(POST_WRITE_WAIT)
    screens.press("N", "exit_game")
    screens.wait(("camp",), 60, past=("exit_game",))


def read_back(disk_path: pathlib.Path, manifest: dict) -> dict:
    """The saved slot's members, and whether the loaded slot's file is still as staged."""
    fight_ = manifest["fight"]
    disk = amiga_adf.AmigaDisk.open(disk_path)
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    loaded_file = f"/SAVE/savgam{fight_['load']}.dat"
    saved = _slot(disk, fight_["save"])
    return {"letter": fight_["save"], "verify": disk.verify(),
            "loaded_slot_unchanged": disk.read_file(loaded_file) == staged.read_file(loaded_file),
            **({SAVED_GATE: gate_word(saved.data)} if fight_.get("kind") == PIT else {}),
            "members": [{"name": m.name, **member_fields(m.raw),
                         "creature_type": m.raw[CREATURE_TYPE],
                         "effects": [node[0] for node in m.effects]}
                        for m in saved.characters]}


def verdict(found: dict, manifest: dict, members: list[str], outcome: str = "won") -> list[str]:
    """Problems with a read-back: empty when each named member was saved QUICK, as loaded,
    and a Pit run's saved slot still holds the staged gate. After a lost fight the members
    never got a bar and some fell, so only their presence and control are checked; a fight does
    not change control. With no fight (`unfought`) nobody pressed QUICK, so quickfight is not
    checked. A member staged with his combat picture must be saved with the same one."""
    problems = []
    if manifest["fight"].get("kind") == PIT and found.get(SAVED_GATE) != PIT_GATE_ON:
        problems.append(f"the saved slot holds ${PIT_GATE:04X} = {found.get(SAVED_GATE)}, "
                        f"not the staged {PIT_GATE_ON}")
    if found["verify"]:
        problems.append(f"the fetched disk fails verification: {found['verify']}")
    if not found["loaded_slot_unchanged"]:
        problems.append(f"slot {manifest['fight']['load']} changed on the disk")
    names = [m["name"] for m in found["members"]]
    if names != manifest["fight"]["names"]:
        problems.append(f"the saved party is {names}, not {manifest['fight']['names']}")
    for name in members:
        rows = [m for m in found["members"] if m["name"] == name]
        if len(rows) != 1:
            problems.append(f"{name} is in the saved party {len(rows)} times")
            continue
        loaded = manifest["fight"]["members"][name]
        row = rows[0]
        if row["control"] != loaded["control"]:
            problems.append(f"{name} was saved as {row}, loaded as {loaded}")
        if "picture" in loaded and row.get("picture") != loaded["picture"]:
            problems.append(f"{name} was saved with picture {row.get('picture')}, "
                            f"staged with {loaded['picture']}")
        if outcome == "lost":
            continue
        if outcome == "won" and row["quickfight"] != 1:
            problems.append(f"{name} was saved with quickfight {row['quickfight']}")
        if row["status"] != loaded["status"]:
            problems.append(f"{name} was saved as {row}, loaded as {loaded}")
        if row["hit_points"] == 0:
            problems.append(f"{name} was saved at 0 hit points")
    return problems


def cast_verdict(log: dict, after: dict | None, saved: dict | None,
                 loaded: dict) -> tuple[str, list[str], list[str]]:
    """The cast run's verdict, the problems behind it, and notes on what the watch saw.

    The watched member's saved row decides the form (`saved`, his read-back row; `loaded`, his
    staged fields):

    * `pass`, the berserk form: saved control 0 and the loaded status, with a reading that
      held 137 or a frame that showed his berserk message; with neither it is `inconclusive`.
    * `fled`: saved control 0 and status 0, the run-away form that left the map.
    * `got_away`: saved status 0 with the loaded control: he left the map unlowered.
    * `refuted`: saved with the loaded control and status although a reading held 137 or 142
      or a frame showed his runs-away or berserk message.
    * `inconclusive`: no saved row, a member loaded with control 0, the loaded row with no
      lowering seen, or any other row.

    Problems: no cast, a cast that spent other than one copy (`cast_spends`), the live reading
    after the fight disagreeing with the form, a creature type other than the first read, 0 hit
    points, or effects 35, 137 or 142 still saved. The bar and poll readings and the message
    frames then confirm the form or leave a gap, each named in the notes; they never change it.
    """
    name = log["watch"]
    problems: list[str] = []
    notes: list[str] = []
    if not log["events"]:
        problems.append("no cast event")
    for number, (event, spend) in enumerate(zip(log["events"], cast_spends(log)), 1):
        if spend["spent"] != 1:
            problems.append(f"cast {number} ({event.get('outcome')}) spent {spend['spent']} "
                            f"of {log['spell']}, not 1")
        notes += [f"the computer cast {cast['spent']} of {log['spell']} for {log['caster']} "
                  f"before the read {cast['when']!r}" for cast in spend["computer_casts"]]
    seen = [r[name] for r in log["reads"] if name in r] + list(log.get("changes", []))
    held = {effect for r in seen for effect in (r["effects"] or ())}
    shown = {m["message"] for m in log.get("messages", [])}
    shown |= {"runs_away"} if log.get("runs_away_frames") else set()
    ran = RUNS_AWAY in held or "runs_away" in shown
    berserk = BERSERK in held or "berserk" in shown
    left_map = any(r["status"] == GOT_AWAY for r in seen)
    kind = seen[0]["creature_type"] if seen else None
    live = None if after is None else after.get(name)
    if saved is None:
        problems.append(f"no saved reading of {name} after the fight")
        return "inconclusive", problems, notes
    control, status = saved["control"], saved["status"]
    if loaded["control"] == 0:
        problems.append(f"{name} was loaded with control 0x00, so nothing could lower it")
        return "inconclusive", problems, notes
    if control == 0 and status == loaded["status"]:
        form, want = "pass", (0, loaded["status"])
    elif control == 0 and status == 0:
        form, want = "fled", (0, 0)
    elif control == loaded["control"] and status == 0:
        form, want = "got_away", (loaded["control"], 0)
    elif (control, status) == (loaded["control"], loaded["status"]):
        if ran or berserk:
            problems.append(f"{name} held {BERSERK} or {RUNS_AWAY}, or showed its message, and "
                            f"was saved with control {control:#04x} and status {status} as loaded")
            return "refuted", problems, notes
        problems.append(f"{name} never held {BERSERK} or {RUNS_AWAY} and was saved as loaded")
        return "inconclusive", problems, notes
    else:
        problems.append(f"{name} was saved with control {control:#04x} and status {status}, "
                        f"which is none of the forms")
        return "inconclusive", problems, notes
    if live is None:
        problems.append(f"no live reading of {name} after the fight")
    elif (live["control"], live["status"]) != want:
        problems.append(f"{name} reads control {live['control']:#04x}, status {live['status']} "
                        f"live after the fight, not {want[0]:#04x} and {want[1]} as saved")
    if kind is not None and saved["creature_type"] != kind:
        problems.append(f"{name} was saved with type {saved['creature_type']}, not {kind}")
    if kind is None:
        notes.append(f"no reading of {name} before the save gave his creature type")
    if saved["hit_points"] == 0:
        problems.append(f"{name} was saved at 0 hit points")
    if form == "pass" and left_map:
        problems.append(f"a reading caught {name} off the map (status {GOT_AWAY}), yet he was "
                        f"saved at status {status}")
    left = sorted(set(saved["effects"]) & {CONFUSED, *LOWERING})
    if left:
        problems.append(f"{name} was saved holding effects {left}")
    if form == "pass" and not berserk:
        problems.append(f"no reading held {BERSERK} and no frame showed {name} GOES BERSERK")
        form = "inconclusive"
    gaps = {
        "pass": [],
        "inconclusive": [],
        "fled": [(ran or berserk, f"no reading held {RUNS_AWAY} or {BERSERK} and no frame showed "
                                  f"{name} RUNS AWAY or GOES BERSERK"),
                 (left_map, f"no reading caught {name} off the map (status {GOT_AWAY})")],
        "got_away": [(left_map, f"no reading caught {name} off the map (status {GOT_AWAY})")],
    }[form]
    notes += [text for ok, text in gaps if not ok]
    if "forced_to_flee" in shown:
        notes.append(f"frames showed {name} IS FORCED TO FLEE")
    return form, problems, notes


def parse_cast(text: str) -> tuple[str, int]:
    """`CASTER:SPELL`, the spell by name (`SPELLS`) or as a number."""
    caster, sep, spell = text.partition(":")
    require(bool(sep) and bool(caster) and bool(spell), f"--cast {text!r} is not CASTER:SPELL")
    if spell.upper() in SPELLS:
        return caster, SPELLS[spell.upper()]
    try:
        number = int(spell, 0)
    except ValueError:
        raise RouteError(f"--cast spell {spell!r} is not one of {sorted(SPELLS)} or a number") from None
    require(0 < number < 0x80, f"--cast spell {number} is not 1 to 127")
    return caster, number


def run(args: argparse.Namespace, *, guest: Any = None, guards: Any = None,
        boot: Callable = acceptance.boot_lane, halt: Callable = acceptance.halt_lane,
        memory: Any = None, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """Boot a staged manifest, drive its route, save once unless told not to, read back."""
    require(0 <= args.wait_lane <= 1800, "lane wait exceeds 1800 seconds")
    require(0 < args.budget <= 3600, "budget must be at most 3600 seconds")
    require(not args.out.exists(), f"{args.out} already exists")
    no_fight = getattr(args, "no_fight", False)
    require(not (no_fight and args.no_save), "--no-fight saves; it cannot go with --no-save")
    manifest = json.loads(args.manifest.read_text())
    require("fight" in manifest and manifest.get("title") == "curse",
            "the manifest is not a cursefight.py stage")
    fight_ = manifest["fight"]
    pit = fight_.get("kind") == PIT
    cast_text = getattr(args, "cast", None)
    capture = getattr(args, "capture", False)
    aim, watched = getattr(args, "aim", None), getattr(args, "watch", None)
    require(not capture or cast_text is not None, "--capture needs --cast")
    require((cast_text is None) == (aim is None) == (watched is None),
            "--cast, --aim and --watch go together")
    require(bool(args.member) or cast_text is not None, "name at least one --member, or --cast")
    require(not (cast_text and no_fight), "--cast needs a fight; it cannot go with --no-fight")
    absent = [name for name in [*args.member, *([aim, watched] if aim else [])]
              if name not in fight_["names"]]
    if cast_text is not None:
        caster, spell = parse_cast(cast_text)
        absent += [caster] if caster not in fight_["names"] else []
    require(not absent, f"{absent} are not in slot {fight_['load']}: {fight_['names']}")
    if cast_text is not None:
        require("spells" in fight_, "the stage records no memorised spells; stage it again")
        held = fight_["spells"][caster]
        require(bool(held) and all(i == spell for i in held),
                f"{caster}'s staged list holds {held}; the run casts only from a list of "
                f"{spell} alone")
    rules = guard_rules()
    unguarded = [state for state in CAST_UNCAPTURED if state not in rules]
    require(cast_text is None or capture or not {"spell_list", "aim"} & set(unguarded),
            f"the guard map has no rule for {unguarded}; capture them with --capture first")
    for key, entry in (*manifest["disks"].items(), *manifest["registered"].items()):
        require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"the {key} disk hash differs")
    staged = amiga_adf.AmigaDisk.open(manifest["disks"]["save"]["path"])
    require(fight_["save"] not in curseadd.slot_letters(staged),
            f"slot {fight_['save']} is already on the staged disk")
    args.out.mkdir(parents=True)
    receipt: dict[str, Any] = {"started_utc": datetime.now(timezone.utc).isoformat(),
                               "manifest": str(args.manifest.resolve()), "holder": args.holder,
                               "members": list(args.member), "save": not args.no_save,
                               "fight": not no_fight,
                               "out": str(args.out.resolve()), "success": False, "cleanup": []}
    if pit:
        receipt["uncaptured"] = missing(rules)
    cast = None
    if cast_text is not None:
        receipt.update(cast_uncaptured=unguarded,
                       cast_args={"cast": cast_text, "aim": aim, "watch": watched},
                       capture=capture)
    guest = guest if guest is not None else WinGuest()
    memory = memory if memory is not None else Memory(args.holder)
    if cast_text is not None:
        cast = Cast(memory, caster, spell, aim, watched, capture=capture)
    save = not (args.no_save or capture)
    receipt["save"] = save
    command = [str(pathlib.Path(__file__)), "run", "--manifest", str(args.manifest),
               "--holder", args.holder, "--out", str(args.out),
               *(f"--member={name}" for name in args.member),
               *(["--no-save"] if args.no_save else []),
               *(["--no-fight"] if no_fight else []),
               *([f"--cast={cast_text}", f"--aim={aim}", f"--watch={watched}"]
                 if cast_text is not None else []),
               *(["--capture"] if capture else [])]
    booted = False
    found: dict[str, Any] = {}
    screens = None
    try:
        guard_file = args.out / "guards.json"
        write_json(guard_file, rules)
        guards = guards if guards is not None else PixelGuards(guard_file)
        proof = curseadd.mute(guest, args.out, timeout=60)
        receipt["boot"] = boot(args.manifest, manifest, route_curse.CURSE, guest=guest,
                               holder=args.holder, audio_proof=proof, wait_lane=args.wait_lane,
                               timeout=300, command=command)
        booted = True
        screens = ((CastPitScreens if pit else CastScreens) if cast is not None
                   else (PitScreens if pit else Screens))(
            guest, args.holder, args.out / "screens", guards, clock() + args.budget,
            clock=clock, sleep=sleep)
        receipt.update(drive(screens, manifest, list(args.member), memory,
                             save=save, found=found,
                             **({"no_fight": True} if no_fight else {}),
                             **({"cast": cast} if cast is not None else {})))
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for key, value in found.items():
            receipt.setdefault(key, value)
        if screens is not None:
            receipt["screens"] = screens.events
        if cast is not None:
            receipt["cast"] = cast.log()
        if booted:
            try:
                receipt["halt"] = halt(guest, args.holder, manifest_path=args.manifest,
                                       command=command)
            except Exception as exc:  # noqa: BLE001
                receipt["cleanup"].append({"halt_error": str(exc)})
        try:
            original = json.loads(args.manifest.read_text())
            for key, entry in (*original["disks"].items(), *original["registered"].items()):
                require(sha256(pathlib.Path(entry["path"])) == entry["sha256"], f"{key} changed")
            source = original["fight"]["source"]
            require(sha256(pathlib.Path(source["path"])) == source["sha256"],
                    "the source disk changed")
            receipt["source_hashes"] = "unchanged"
        except Exception as exc:  # noqa: BLE001
            receipt["cleanup"].append({"hash_error": str(exc)})
        fetched = (receipt.get("halt") or {}).get("fetched", {}).get("save")
        if "error" in receipt:
            pass
        elif receipt.get("destroyed"):
            receipt["problems"] = ["the party was destroyed, so nothing was saved"]
        elif capture:
            got = {c["screen"] for c in receipt["cast"]["captures"]}
            receipt["problems"] = [f"the capture kept no {state} frame"
                                   for state in ("spell_list", "aim") if state not in got]
        elif args.no_save:
            receipt["problems"] = []
        elif fetched:
            try:
                found = read_back(pathlib.Path(fetched["path"]), manifest)
                receipt["read_back"] = found
                receipt["problems"] = verdict(found, manifest, list(args.member),
                                              "unfought" if no_fight
                                              else receipt.get("outcome", "won"))
                if cast is not None:
                    rows = [m for m in found["members"] if m["name"] == watched]
                    kind, problems, notes = cast_verdict(
                        receipt["cast"], receipt.get("watch_after"),
                        rows[0] if len(rows) == 1 else None, fight_["members"][watched])
                    receipt["cast_verdict"] = kind
                    receipt["cast_problems"] = problems
                    receipt["cast_notes"] = notes
                    receipt["problems"] += [f"the cast verdict is {kind}"] if kind != "pass" else []
                    receipt["problems"] += problems
            except Exception as exc:  # noqa: BLE001
                receipt["problems"] = [f"read-back: {type(exc).__name__}: {exc}"]
        else:
            receipt["problems"] = ["no fetched save disk"]
        errors = [item for item in receipt["cleanup"] if any(k.endswith("error") for k in item)]
        receipt["success"] = ("error" not in receipt and not errors and "halt" in receipt
                              and receipt.get("problems") == [])
        if "outcome" in receipt:
            receipt["fight_won"] = receipt["outcome"] == "won"
        write_json(args.out / "receipt.json", receipt)
    if not receipt["success"]:
        raise RouteError(receipt.get("error") or f"problems: {receipt.get('problems')}; "
                         f"cleanup: {receipt['cleanup']}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stage", help="copy a fetched Curse save disk in as a prepare run's disk A")
    s.add_argument("--manifest", type=pathlib.Path, required=True,
                   help="an `acceptance.py prepare --title curse` prepare.json")
    s.add_argument("--source-disk", type=pathlib.Path, required=True,
                   help="a Curse disk A whose SAVE drawer holds the slot to load")
    s.add_argument("--load", required=True,
                   help="the slot the run loads, in Tilverton (area 1) or the Pit (area 17)")
    s.add_argument("--save", required=True, help="the free slot the run saves to")
    s.add_argument("--out", type=pathlib.Path, required=True)
    s.add_argument("--stage-record", action="append", default=[],
                   metavar="NAME:FIELD=VALUE[,FIELD=VALUE]",
                   help="write hp, hp_max or memorised0-memorised83 on one member of the loaded "
                        "slot; repeat for another member")
    g = sub.add_parser("run", help="boot a staged manifest in one muted WinUAE lane, take the "
                                   "tavern or Pit fight, save once, halt, fetch and read back")
    g.add_argument("--manifest", type=pathlib.Path, required=True, help="the stage's prepare.json")
    g.add_argument("--holder", required=True)
    g.add_argument("--out", type=pathlib.Path, required=True, help="a fresh folder for the run")
    g.add_argument("--member", action="append", default=[],
                   help="a member who must get a command bar, hold quickfight 1 after the fight "
                        "and still stand; repeat for several")
    g.add_argument("--no-save", action="store_true",
                   help="stop after the fight's checks, saving nothing")
    g.add_argument("--no-fight", action="store_true",
                   help="load the slot, begin, then camp and save at once, with no walk and no "
                        "fight, and read the save back")
    g.add_argument("--cast", metavar="CASTER:SPELL",
                   help="CASTER casts SPELL (CONFUSION or an id) on his bars until --watch holds "
                        "137 or 142 or the spell runs out; DONE while --watch is confused")
    g.add_argument("--aim", metavar="MEMBER", help="the member the cast is aimed at")
    g.add_argument("--watch", metavar="MEMBER",
                   help="the member read at every bar and after the fight, and judged")
    g.add_argument("--capture", action="store_true",
                   help="with --cast: take the spell list and aim menu from memory and a held "
                        "frame, stop at the aim menu, and save nothing")
    g.add_argument("--budget", type=float, default=2700)
    g.add_argument("--wait-lane", type=float, default=0, metavar="SECONDS")
    r = sub.add_parser("read", help="read a fetched Curse disk's saved slot against a manifest")
    r.add_argument("--manifest", type=pathlib.Path, required=True)
    r.add_argument("--disk", type=pathlib.Path, required=True)
    r.add_argument("--member", action="append", default=[])
    r.add_argument("--receipt", type=pathlib.Path,
                   help="the run's receipt.json, whose outcome the read-back is judged by")
    r.add_argument("--outcome", choices=("won", "lost", "unfought"),
                   help="the fight's outcome, when no receipt is given")
    args = parser.parse_args(argv)
    try:
        with terminating():
            if args.command == "stage":
                print(stage(args.manifest, args.source_disk, args.out, load=args.load,
                            save=args.save, records=args.stage_record))
                return 0
            if args.command == "run":
                receipt = run(args)
                print(json.dumps(receipt, indent=1, sort_keys=True))
                print(f"cursefight: fight outcome {receipt.get('outcome', 'unknown')}; "
                      + (f"cast verdict {receipt['cast_verdict']}; "
                         if "cast_verdict" in receipt else "")
                      + f"success {receipt['success']}")
                return 0
            require(bool(args.member), "name at least one --member")
            require((args.receipt is None) != (args.outcome is None),
                    "give one of --receipt and --outcome")
            outcome = (args.outcome if args.receipt is None
                       else json.loads(args.receipt.read_text()).get("outcome"))
            if args.receipt is not None and outcome is None and not json.loads(
                    args.receipt.read_text()).get("fight", True):
                outcome = "unfought"
            require(outcome in ("won", "lost", "unfought"),
                    f"the fight outcome is {outcome!r}, not won, lost or unfought")
            manifest = json.loads(args.manifest.read_text())
            found = read_back(args.disk, manifest)
            problems = verdict(found, manifest, args.member, outcome)
            print(json.dumps({"found": found, "problems": problems}, indent=1, sort_keys=True))
            return 0 if not problems else 1
    except (RouteError, OSError, ValueError, KeyError, amiga_adf.AmigaDiskError) as exc:
        print(f"cursefight: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
