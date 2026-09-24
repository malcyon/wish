#!/usr/bin/env python3
"""Load a Wish-written DOS save in the running game, act, and read the engine's resave.

The DOS driver of `docs/235-destination-game-acceptance-runs.md` (D1), for
DOS Pool of Radiance, Curse of the Azure Bonds, Secret of the Silver Blades
and Pools of Darkness.  It stages a whole save this project wrote the way
`dossheetread.install_whole` does, boots DOSBox headless and silent on a
pooled slot, runs a step list, and decodes what the engine wrote back:

    tools/dos/dosacceptance.py --title pool --save DIR --slot A \\
        --steps load camp 'rest 5m' 'save D' read \\
        --expect BRUTUS:1:42:1 --issue 661 --run bless

    tools/dos/dosacceptance.py --title curse --fixture-row 3F=01:00:2F:05 \\
        --steps load begin camp 'rest 5m' 'save D' read \\
        --expect PHILIPPE:1:42:5 --issue 661 --run curse-bless

`--fixture-row SLOT=ID:OWNER:DURATION:MAGNITUDE` (hex, repeatable) replaces
`--save`: a C64 party gets those effect rows and is converted by Save As DOS
(`editor.saveplan.prepare_save_as` and `publish`) into `<out>/source/` before
the boot, with the SHA, the file list, the converted nodes and the report's
`dropped` and `losses` in the log.  The party is the committed fixture for
Pool of Radiance and the title's engine-written specimen under
`$WISH_SPECIMENS/por-c64/` for the other two (`C64_BASES`), or `--c64-save`.
With no `--steps` only that conversion runs.

    tools/dos/dosacceptance.py --title darkness \\
        --amiga-disk 'Pools Of Darkness.zip!Pools of Darkness3.adf' \\
        --amiga-slot SavGamA.pty \\
        --steps load begin camp 'sheet 4' 'items 4' 'save D' read \\
        --issue 650 --run scrolls

`--amiga-slot` (with `--amiga-disk`, a path to an `.adf` or the end of a
`tools/amiga/amigasaves.py` label) replaces `--save` for Pools of Darkness:
the Amiga saved game is converted by the Convert window's own route,
`editor.convert.PodAmigaToDos` with `WISH_EXPERIMENTAL_POD_CONVERT` set for
this process, into `<out>/source/` as DOS slot A, with the disk's label and
SHA-256, the report's `dropped` and `losses` and every warning the
conversion logged.

| step | what it does |
|---|---|
| `load` | title screens, `LOAD SAVED GAME`, the `--slot` letter; Pool lands on the map, the other three on the party menu |
| `begin` | Curse, Silver Blades and Pools of Darkness: `BEGIN ADVENTURING`, through Silver Blades' intro bars, to the map |
| `camp` | `ENCAMP`; records the camp bar by `bar_signature` |
| `sheet N`, `items N` | Pools of Darkness, in camp: roster line N (from 1), `VIEW`, and for `items` its `ITEMS` list page by page with `NEXT`; back to camp |
| `display` | Pool camp `MAGIC > DISPLAY`; captures six member rows, then returns through Magic to camp |
| `rest 5m`, `rest 1h30m`, `rest 8d` | camp `REST`, the rest time zeroed and set by key, then rested; minutes in fives; Pool's `GO STAY` random event at the end is answered `GO` (see below) |
| `save X` | in camp, camp `SAVE` to slot X and decline the quit; at the party menu, `SAVE CURRENT GAME`; believed when `SAVGAMX.DAT` changes |
| `train N` | Curse: roster line N (from 1), `TRAIN CHARACTER`, `YES`, and `LEARN` for any spell the level brings, back to the party menu |
| `shot NAME` | one PNG and the screen digests, nothing pressed |
| `press KEY` | one X keysym (`Down`, `Return`, `t`), then a settle and a PNG; capture only, so only `press`, `shot` and `read` may come after it |
| `walk MI`, `walk 1` | Pool: turn around and step one square.  Pools of Darkness: step one square, turning right past a wall |
| `read` | copies `SAVE/` out and decodes every node, the clock, the place and each character's experience, installed slot against each saved one; for Pools of Darkness also each character's eight thief skills, item count, encumbrance, movement and items |

**Pools of Darkness' screens are read off its `GAME.EXE` strings, not off a
capture.**  Its party menu holds Silver Blades' thirteen entries in the same
order (`GAME.EXE` 0xAB4E-0xAC90 against Silver Blades' `START.EXE`
0xE207-0xE349), so it is driven as Silver Blades' highlight list at
`ssbimport`'s rows; the map bar is `Move Area Cast View Encamp Search Look`
(0xBC79), the camp bar `Save View Magic Rest Alter Fix Exit` (0xBEBE), the
rest menu Curse's (0xBB26), the sheet's bar `Items Spells Trade Deposit Drop
Lay Cure Exit` (0xBB4F).  Each is PROBABLE until a run has reached it; a
screen that does not answer its key stops the run with a `lost-*.png`.

Staging, written into the installed copy before the boot and logged in
bytes (`.claude/rules/testing.md`, "Poke a field before the boot"):
`--hall` sets the word at `SAVGAM+0xD51` to `0x00FF`, which puts `TRAIN
CHARACTER` in the party menu wherever the party stands for every class
(`docs/194-the-dos-training-ladder.md`); `--xp N=VALUE` sets roster line N's
experience; `--add-node N=ID:MINUTES:DATA:FLAG` appends one effect node to
line N's effect file (`.SPC`, `.FX` or `.SFX`).

**The rest-time keys are read from each title's `GAME.OVR`**, because nobody
had captured the screen.  Pool of Radiance's rest menu is `Rest daYs Hours
Mins Inc Dec Exit` (key loop `0x244ED`); Curse's and Silver Blades' is `Rest
Days Hours Mins Add Subtract Exit` (Curse `0x2B4A7`, Silver Blades
`0x2BD63`).  The three loops are one routine with different letters: the
menu opens on the minutes field; the days, hours and minutes keys select a
field; the add key adds one day or hour, or **five** minutes; the subtract
key takes the same away, borrowing, and **clamps at zero**: with nothing
above the field to borrow from, the whole time is zeroed (Pool `0x24246`,
Curse `0x2B1F5`, Silver Blades `0x2BAB2`).  `R` and `Return` rest.  The
camp's `REST` presets hours and minutes to the longest memorisation the party
has queued (Pool `0x17FAB`, Curse `0x19730`), so the time is zeroed from the
days field before it is set.  A rest takes five minutes off the time and adds
five to the clock per pass (Pool `0x24A66`, Curse `0x2BB59`-`0x2BB84`), so
the clock in the resave is the check that the time was set right.  **Any key
pressed while resting asks `Stop Resting?`**, so nothing is pressed until the
camp bar is back.

**A Pool rest can end in a random event instead of the camp bar**: the city
watch rousts the party and asks `GO STAY`.  The clock has already moved on
and the effects have aged by then.  The driver presses `G` and waits for the
map bar; the party is then out of camp, so the next `rest` or `save` presses
`ENCAMP` again.  `S` is never pressed, since STAY would start a fight.  At
most two such events are answered in one rest; a third, a fight or any other
screen stops the run with a `lost-*.png`, and so does a screen under the
viewport that stops changing for `REST_STALL` seconds without being the camp
bar -- a rest redraws its time every five passes, so a still screen is a
message, a fight, or the game having stopped.  Each event is logged as
`event: random` in `run.jsonl` and listed in the summary's `events`.

Each key in the rest menu is believed only when the text window under the
viewport changes, and is pressed a second time at most; a key that changes
nothing twice stops the run with a PNG rather than being counted.

Evidence goes to `~/.cache/wish/acceptance/<issue>/<sha>-<run>/`: `run.jsonl`,
`summary.json`, `shots/`, `installed/` (the save as booted) and `resave/`
(the engine's `SAVE`).  Nothing is committed and the archives are read only.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_codec, world_state  # noqa: E402
from tools.dos import dosbox, dospod, ssbimport  # noqa: E402
from tools.registry import scratch  # noqa: E402

# The camp bar is `Save View Magic Rest Alter Exit` in Pool of Radiance and
# `Save View Magic Rest Alter Fix Exit` in the other two (`START.EXE`).
# Pool's `Exit` is exit to DOS, so `e` is never pressed in camp.
ENCAMP = "e"
CAMP_SAVE = "s"
CAMP_REST = "r"
QUIT_NO = "n"
# Pool's measured camp Magic and Display bars.
POOL_MAGIC_BAR = "062aa229ea7afd11"
POOL_DISPLAY_BAR = "98286ceaa33edc12"
# Names start at x=8; effect lines are indented to x=17. Count the left
# character cell across the page, allowing row spacing to change by effect.
POOL_DISPLAY_NAME_ROWS = range(32, 184, 8)

# Pool's rest menu is `Rest daYs Hours Mins Inc Dec Exit` (`GAME.OVR` 0x244A5).
REST_DAYS = "y"
REST_HOURS = "h"
REST_MINS = "m"
REST_INC = "i"
REST_DEC = "d"
REST_GO = "r"
#: What one add or subtract moves the minutes field by (Pool `GAME.OVR`
#: 0x245CB, Curse 0x2B585, Silver Blades 0x2BE41).
REST_STEP = 5
#: The days field's ceiling (Pool `GAME.OVR` 0x24192, Curse 0x2B148).
REST_DAYS_MAX = 99
#: Seconds the text window may stay still during a rest before the run stops.
REST_STALL = 90.0

#: The `GO STAY` command bar of Pool's city watch random event, by
#: `bar_signature`, measured off the screen of a live Bless run.
WATCH_BAR = "4aaded0229f46861"
WATCH_GO = "g"
#: Random events answered in one rest before the run gives up.
MAX_EVENTS = 2

#: The text window under the viewport and the command bar below it, where
#: the rest time is drawn (text row 17) and every rest-menu key shows.  The
#: viewport's picture is left out so nothing it draws reads as a keypress.
TEXT_WINDOW = (0, 120, 320, 80)

#: One character cell of the command bar.
CELL = 8

#: Curse's party menu takes a letter per command, `C D M T H V A R L S B E J`
#: (`START.EXE`): `LOAD SAVED GAME`, `SAVE CURRENT GAME`, `BEGIN ADVENTURING`
#: and `TRAIN CHARACTER`.
PARTY_LOAD = "l"
PARTY_SAVE = "s"
PARTY_BEGIN = "b"
PARTY_TRAIN = "t"
#: `DO YOU WISH TO TRAIN? YES NO` (`docs/194-the-dos-training-ladder.md`).
TRAIN_YES = "y"
#: Moves the roster highlight down a line and wraps from the last to the first.
ROSTER_NEXT = "End"
#: Pressed in turn until the party menu is back after a training: `LEARN` at
#: `<NAME>'S SPELLS TO CHOOSE FROM`, then whatever message is left.
AFTER_TRAIN = ("l", "l", "Return", "Escape")

#: Silver Blades' party menu is a highlight list (`ssbimport.MENU_RECT`).
#: With no party it is `Create New Character`, `Add Character to Party`,
#: `Load Saved Game`, ...; `ssbimport.MENU_BEFORE` measured `Add` at row 1,
#: and `Load Saved Game` comes after it in `START.EXE`'s list, so row 2 is
#: PROBABLE and unread on a capture.
SSB_LOAD_ROW = 2

#: Pools of Darkness' party menu, driven as Silver Blades' highlight list
#: because `GAME.EXE` holds the same entries in the same order.  The rows are
#: Silver Blades' and PROBABLE here until a capture of this title reads them.
POD_MENU_RECT = ssbimport.MENU_RECT
POD_LOAD_ROW = SSB_LOAD_ROW
POD_MENU_AFTER = ssbimport.MENU_AFTER
#: `View` on the map and camp bars; `Items` and `Exit` on the sheet's bar
#: `Items Spells Trade Deposit Drop Lay Cure Exit` (`GAME.EXE` 0xBB4F).  The
#: `ITEMS` list turns its page with `Next` (0xA6AF), the list protocol's `n`.
VIEW = "v"
SHEET_ITEMS = "i"
LEAVE = "e"
ITEMS_NEXT = dosbox.LIST_PAGE_DOWN
#: Pages of `ITEMS` captured before the run gives up on reaching the last.
ITEMS_PAGES = 6
#: The walk each title drives: Pool's turn-around, Pools of Darkness' step.
WALKS = {"pool": "MI", "darkness": "1"}


@dataclasses.dataclass(frozen=True)
class RestKeys:
    days: str
    hours: str
    mins: str
    inc: str
    dec: str
    go: str


#: Curse's and Silver Blades' rest menu, `Rest Days Hours Mins Add Subtract
#: Exit` (Curse `GAME.OVR` 0x2B461, Silver Blades 0x2BD1D).
LATER_REST = RestKeys("d", "h", "m", "a", "s", "r")


@dataclasses.dataclass(frozen=True)
class Title:
    """What differs between the three titles in the steps this driver runs."""

    key: str
    #: The game directory stem `dosbox.find_game` looks for.
    stem: str
    #: `map` when `LOAD SAVED GAME` puts the party on the map, `party` when it
    #: leaves it at the party menu with `BEGIN ADVENTURING` still to press.
    loads_to: str
    #: Pool's city watch `GO STAY` event can end a rest.
    watch: bool
    #: Silver Blades will not load a save installed under a letter other than
    #: the one it was written as (`tools/c64/dualclassagain.py`, twice of two).
    same_letter: bool
    #: `train N` is driven; Silver Blades' training keys are unread.
    trains: bool
    #: What the DOSBox autoexec runs.
    exe: str = "START.EXE"
    #: The saved game's suffix: `SAVGAM<slot>.DAT`, or Pools of Darkness'
    #: `SAVGAM<slot>.PTY` with a `VAULT<slot>.DAT` beside it.
    suffix: str = ".DAT"

    def rest_keys(self) -> RestKeys:
        if self.key == "pool":
            return RestKeys(REST_DAYS, REST_HOURS, REST_MINS, REST_INC,
                            REST_DEC, REST_GO)
        return LATER_REST

    def find_game(self) -> pathlib.Path:
        """The title's directory in the archives, found by its launcher."""
        if self.exe == "START.BAT":
            return dospod.find_game(self.stem)
        return dosbox.find_game(self.stem)


TITLES = {
    "pool": Title("pool", "POOLRAD", "map", True, False, False),
    "curse": Title("curse", "CURSE", "party", False, False, True),
    "ssb": Title("ssb", "SECRET", "party", False, True, False),
    # `Load Saved Game` is a party-menu entry here as in Curse and Silver
    # Blades, and both leave the party at that menu after a load, so this
    # title's `loads_to` is `party`: PROBABLE, not yet captured.  The
    # container names its own `CHRDAT` files and the engine loads those, not
    # the letter picked (`docs/141-dos-savegame.md`, 12809-13136), so a
    # renamed slot would load nothing.
    "darkness": Title("darkness", "DARKNESS", "party", False, True, False,
                      exe="START.BAT", suffix=".PTY"),
}

#: The C64 party `--fixture-row` stages into for each later title: an
#: engine-written save in `$WISH_SPECIMENS/por-c64/` (`docs/235` §4).  Pool
#: of Radiance uses the committed fixture party instead.
C64_BASES = {
    "curse": "WISH-SPEC-curse-h-engine-resave.D64",
    "ssb": "WISH-SPEC-ssb-d-engine-resave.D64",
}

#: `SAVGAM<slot>.DAT`'s training-hall word and the value `--hall` writes:
#: every class bit, so every character's school is open
#: (`tools/curse_of_the_azure_bonds/curseregain.py`, `EVERY_CLASS`).
HALL_WORD = 0xD51
HALL_OPEN = 0x00FF
#: The titles whose training hall word is documented at `HALL_WORD`.
HALL_TITLES = frozenset({"pool", "curse"})

#: The effect files of the three titles (`dos_codec.read_character`).
EFFECT_SUFFIXES = (".SPC", ".FX", ".SFX")


class StepFailed(RuntimeError):
    """A step did not reach the screen or the file it waits for."""


# --------------------------------------------------------------------------
# Pure parts: steps, durations, screens, staging, and reading a save
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Step:
    kind: str
    text: str
    minutes: int = 0
    letter: str = ""
    name: str = ""
    line: int = 0
    key: str = ""


_DURATION = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$")


def parse_duration(text: str) -> int:
    """`5m`, `8h`, `2d` or a run of them such as `1h30m`, in minutes."""
    m = _DURATION.match(text.strip().lower())
    if not text.strip() or m is None or not any(m.groups()):
        raise ValueError(f"not a duration: {text!r} (say 5m, 8h, 2d or 1h30m)")
    d, h, mins = (int(g or 0) for g in m.groups())
    return (d * 24 + h) * 60 + mins


def rest_presses(minutes: int) -> tuple[int, int, int]:
    """(days, hours, five-minute presses) that set a rest of `minutes`."""
    if minutes <= 0:
        raise ValueError("a rest must be longer than no time at all")
    if minutes % REST_STEP:
        raise ValueError(f"the rest menu sets minutes in fives; {minutes} is not one")
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days > REST_DAYS_MAX:
        raise ValueError(f"the rest menu holds at most {REST_DAYS_MAX} days")
    return days, hours, mins // REST_STEP


STEP_HELP = ("load, begin, 'walk MI', 'walk 1', camp, display, 'rest 5m', 'save D', "
             "'train 1', 'sheet 1', 'items 1', 'shot NAME', 'press KEY', read")


def parse_step(text: str) -> Step:
    words = text.split()
    if not words:
        raise ValueError("an empty step")
    kind = words[0].lower()
    if kind in ("load", "begin", "camp", "display", "read") and len(words) == 1:
        return Step(kind, text)
    if kind == "rest" and len(words) == 2:
        minutes = parse_duration(words[1])
        rest_presses(minutes)
        return Step(kind, text, minutes=minutes)
    if kind == "save" and len(words) == 2 and re.fullmatch(r"[A-Ja-j]", words[1]):
        return Step(kind, text, letter=words[1].upper())
    if kind in ("train", "sheet", "items") and len(words) == 2 and re.fullmatch(
            r"[1-8]", words[1]):
        return Step(kind, text, line=int(words[1]))
    if kind == "walk" and len(words) == 2 and words[1].upper() in WALKS.values():
        return Step(kind, text, key=words[1].upper())
    if kind == "shot" and len(words) == 2 and re.fullmatch(r"[\w-]+", words[1]):
        return Step(kind, text, name=words[1])
    if kind == "press" and len(words) == 2 and re.fullmatch(r"\w+", words[1]):
        if words[1].lower() in ("e", "escape"):
            raise ValueError(f"press {words[1]} is refused: E is exit to DOS at "
                             "Curse's party menu and Escape backs out of a prompt")
        return Step(kind, text, key=words[1])
    raise ValueError(f"not a step: {text!r} ({STEP_HELP})")


def validate_steps(steps: list[Step], title: str = "pool") -> None:
    """Refuse an order the driver would only find out after booting DOSBox.

    The party is somewhere at each step -- not yet loaded, on the map, at the
    party menu or in camp -- and each step needs one of those.  `shot` and
    `read` need nothing.  After a `press` nobody knows where the party is,
    so only more `press`, `shot` and `read` may come after it.
    """
    t = TITLES[title]
    where = "boot"
    for step in steps:
        k = step.kind
        if k in ("shot", "read"):
            continue
        if where == "pressed" and k != "press":
            raise ValueError(f"only press, shot and read may come after a press: "
                             f"{step.text!r}")
        if where == "boot" and k != "load":
            raise ValueError(f"{k} needs load first: {step.text!r}")
        if k == "press":
            where = "pressed"
            continue
        if k == "load":
            if where != "boot":
                raise ValueError("load is one step, the first")
            where = t.loads_to
        elif k == "begin":
            if t.loads_to == "map":
                raise ValueError(f"{title}'s load puts the party on the map; "
                                 "begin is for the titles that load to the "
                                 "party menu")
            if where != "party":
                raise ValueError(f"begin needs the party menu: {step.text!r}")
            where = "map"
        elif k == "camp":
            if where == "party":
                raise ValueError(f"camp needs begin first: {step.text!r}")
            if where == "camp":
                raise ValueError(f"already camped: {step.text!r}")
            where = "camp"
        elif k == "walk":
            if title not in WALKS:
                raise ValueError(f"walk MI is driven in pool only and walk 1 in "
                                 f"darkness only, not {title}")
            if step.key != WALKS[title]:
                raise ValueError(f"{title}'s walk is 'walk {WALKS[title]}', not "
                                 f"{step.text!r}")
            if where != "map":
                raise ValueError(f"walk needs the map: {step.text!r}")
        elif k in ("sheet", "items"):
            if title != "darkness":
                raise ValueError(f"{k} is driven in darkness only, not {title}")
            if where != "camp":
                raise ValueError(f"{k} needs camp first: {step.text!r}")
        elif k == "rest":
            if where != "camp":
                raise ValueError(f"rest needs camp first: {step.text!r}")
        elif k == "display":
            if title != "pool":
                raise ValueError(f"display is driven in pool only, not {title}")
            if where != "camp":
                raise ValueError(f"display needs camp first: {step.text!r}")
        elif k == "save":
            if where not in ("camp", "party"):
                raise ValueError(f"save needs camp first: {step.text!r}")
        elif k == "train":
            if not t.trains:
                raise ValueError(f"train is driven in curse only; {title}'s "
                                 "training keys are unread")
            if where != "party":
                raise ValueError(f"train needs the party menu, before begin: "
                                 f"{step.text!r}")


@dataclasses.dataclass(frozen=True)
class Expect:
    name: str
    id: int
    minutes: int
    data: int | None = None


def parse_expect(text: str) -> Expect:
    """`NAME:ID:MINUTES[:DATA]`, numbers decimal or `0x` hex."""
    parts = text.split(":")
    if len(parts) not in (3, 4) or not parts[0]:
        raise ValueError(f"not an expectation: {text!r} (NAME:ID:MINUTES[:DATA])")
    nums = [int(p, 0) for p in parts[1:]]
    return Expect(parts[0].upper(), nums[0], nums[1],
                  nums[2] if len(nums) == 3 else None)


def parse_row(text: str) -> tuple[int, int, int, int, int]:
    """`SLOT=ID:OWNER:DURATION:MAGNITUDE`, all hex, for `effects.write_effect`."""
    slot, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or len(parts) != 4:
        raise ValueError(f"not a row: {text!r} (SLOT=ID:OWNER:DURATION:MAGNITUDE, hex)")
    values = [int(slot, 16)] + [int(p, 16) for p in parts]
    if not 0 <= values[0] < 64 or any(not 0 <= v <= 0xFF for v in values[1:]):
        raise ValueError(f"row out of range: {text!r}")
    return tuple(values)  # type: ignore[return-value]


def parse_xp(text: str) -> tuple[int, int]:
    """`LINE=VALUE`: roster line 1-8 and the experience to stage."""
    line, sep, value = text.partition("=")
    if not sep or not re.fullmatch(r"[1-8]", line.strip()):
        raise ValueError(f"not an experience stage: {text!r} (LINE=VALUE)")
    xp = int(value, 0)
    if not 0 <= xp <= 0xFFFFFFFF:
        raise ValueError(f"experience out of range: {text!r}")
    return int(line), xp


def parse_node(text: str) -> tuple[int, bytes]:
    """`LINE=ID:MINUTES:DATA:FLAG`, numbers decimal or `0x` hex: a node's five bytes."""
    line, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or not re.fullmatch(r"[1-8]", line.strip()) or len(parts) != 4:
        raise ValueError(f"not a node: {text!r} (LINE=ID:MINUTES:DATA:FLAG)")
    eid, minutes, data, flag = (int(p, 0) for p in parts)
    if not (0 <= eid <= 0xFF and 0 <= minutes <= 0xFFFF and 0 <= data <= 0xFF
            and 0 <= flag <= 0xFF):
        raise ValueError(f"node out of range: {text!r}")
    return int(line), bytes((eid, minutes & 0xFF, minutes >> 8, data, flag))


def bar_signature(screen: dosbox.Screen) -> str:
    """The command bar's words, blind to which word is highlighted.

    `Screen.glyphs` over the whole bar changes when the game moves its
    highlight block from one word to another, because the block's paper
    differs from the bar's.  Taken **one character cell at a time**, each
    cell measures its own paper, so a letter knocked out of the block and
    the same letter lit on black give the same bits.
    """
    x0, y, w, h = dosbox.BAR
    sha = hashlib.sha1()
    for x in range(x0, x0 + w, CELL):
        sha.update(screen.glyphs((x, y, CELL, h)).encode())
    return sha.hexdigest()[:16]


def node_dict(node: bytes) -> dict:
    return {"id": node[0], "minutes": node[1] | node[2] << 8,
            "data": node[3], "flag": node[4], "raw": node[:5].hex()}


def clock_total(digits: tuple[int, ...]) -> int:
    """Minutes from the clock digits: sub-minute, units, tens, hour, day, month.

    Months are counted as 30 days, the digit's own limit, so a difference of
    two readings is exact within a year.
    """
    _, units, tens, hour, day, month = digits[:6]
    return (((month * 30) + day) * 24 + hour) * 60 + tens * 10 + units


def read_place(savgam: bytes) -> dict:
    """Area, square, facing and whether the party has set out, or the error."""
    try:
        s = world_state.from_dos(savgam)
    except Exception as e:  # noqa: BLE001 -- reported, the clock still reads
        return {"error": f"{type(e).__name__}: {e}"}
    return {"area": s.area, "x": s.x, "y": s.y, "facing": s.facing,
            "set_out": s.set_out}


#: The eight thief skills in the order the record holds them.
THIEF_FIELDS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
                "thief_move_silently", "thief_hide_in_shadows",
                "thief_hear_noise", "thief_climb_walls", "thief_read_languages")


def item_dict(item) -> dict:
    """One item as `read` reports it; a scroll's three spell ids are in
    `charges`, `effect` and `power` (`amiga_pod.unbundle`)."""
    return {"type_index": item.get("type_index"),
            "spells": [item.get("charges"), item.get("effect"), item.get("power")],
            "readied": item.get("readied"), "quantity": item.get("quantity"),
            "weight": item.get("weight")}


def read_pod_slot(folder: pathlib.Path, letter: str) -> dict:
    """A Pools of Darkness slot: the clock, the square, and every character's
    nodes, experience, thief skills, item count, encumbrance, movement and
    items, read through `world_state.pod_from_dos` and `dos_codec.read_party`."""
    savgam = (folder / f"SAVGAM{letter}.PTY").read_bytes()
    state = world_state.pod_from_dos(savgam, source=str(folder))
    out = {"slot": letter, "clock": list(state.clock),
           "clock_minutes": clock_total(state.clock),
           "place": {"x": state.x, "y": state.y, "facing": state.facing,
                     "in_dungeon": state.in_dungeon,
                     "dungeon_map": state.dungeon_map, "mode": state.mode},
           "vault_bytes": ((folder / f"VAULT{letter}.DAT").stat().st_size
                           if (folder / f"VAULT{letter}.DAT").is_file() else None),
           "characters": []}
    for c in dos_codec.read_party(folder, letter):
        out["characters"].append({
            "name": c.name, "file": pathlib.Path(c.source).name,
            "experience": c.get("experience"),
            "nodes": [node_dict(e) for e in c.effects],
            "thief": {f: c.get(f) for f in THIEF_FIELDS},
            "item_count": c.get("item_count"),
            "encumbrance": c.get("encumbrance"),
            "movement": c.get("movement"),
            "items": [item_dict(i) for i in c.items]})
    return out


def read_slot(folder: pathlib.Path, letter: str) -> dict:
    """The clock, the place and every character's nodes and experience in one slot.

    A folder holding `SAVGAM<letter>.PTY` is Pools of Darkness and is read by
    `read_pod_slot`.
    """
    if (folder / f"SAVGAM{letter}.PTY").is_file():
        return read_pod_slot(folder, letter)
    savgam = (folder / f"SAVGAM{letter}.DAT").read_bytes()
    digits = world_state.from_dos(savgam).clock
    out = {"slot": letter, "clock": list(digits),
           "clock_minutes": clock_total(digits), "place": read_place(savgam),
           "characters": []}
    for n in range(1, 9):
        path = folder / f"CHRDAT{letter}{n}.SAV"
        if not path.is_file():
            continue
        c = dos_codec.read_character(path)
        out["characters"].append({
            "name": c.name, "file": path.name,
            "experience": c.get("experience") if "experience" in c.fields else None,
            "nodes": [node_dict(e) for e in c.effects]})
    return out


def compare_nodes(before: dict, after: dict) -> list[dict]:
    """Each node of `before`, matched by character name and id in `after`.

    Two nodes of one id on one character are matched in file order.  A node
    only `after` holds is listed with `before` None.
    """
    rows = []
    after_by = {c["name"]: list(c["nodes"]) for c in after["characters"]}
    for c in before["characters"]:
        left = after_by.get(c["name"])
        for node in c["nodes"]:
            match = None
            if left is not None:
                for i, cand in enumerate(left):
                    if cand["id"] == node["id"]:
                        match = left.pop(i)
                        break
            rows.append({
                "name": c["name"], "id": node["id"],
                "before": node["minutes"], "data_before": node["data"],
                "after": None if match is None else match["minutes"],
                "data_after": None if match is None else match["data"],
                "lost": None if match is None else node["minutes"] - match["minutes"],
                "character_present": left is not None,
            })
    for name, nodes in after_by.items():
        for node in nodes:
            rows.append({"name": name, "id": node["id"], "before": None,
                         "data_before": None, "after": node["minutes"],
                         "data_after": node["data"], "lost": None,
                         "character_present": True})
    return rows


def compare_experience(before: dict, after: dict) -> list[dict]:
    """Each character's experience in `before` and `after`, matched by name."""
    after_by = {c["name"]: c.get("experience") for c in after["characters"]}
    rows = []
    for c in before["characters"]:
        was, now = c.get("experience"), after_by.get(c["name"])
        rows.append({"name": c["name"], "before": was, "after": now,
                     "gained": None if was is None or now is None else now - was})
    return rows


#: What `compare_members` sets side by side for each Pools of Darkness character.
MEMBER_FIELDS = ("thief", "item_count", "encumbrance", "movement", "items")


def compare_members(before: dict, after: dict) -> list[dict]:
    """Each character's `MEMBER_FIELDS` in `before` and `after`, matched by name,
    with the names of the fields that differ.  Empty for a title whose
    reading has none of them."""
    after_by = {c["name"]: c for c in after["characters"]}
    rows = []
    for c in before["characters"]:
        if "thief" not in c:
            continue
        now = after_by.get(c["name"])
        row = {"name": c["name"], "present": now is not None, "changed": []}
        for f in MEMBER_FIELDS:
            row[f] = {"before": c[f], "after": None if now is None else now.get(f)}
            if now is not None and now.get(f) != c[f]:
                row["changed"].append(f)
        rows.append(row)
    return rows


def judge(expect: Expect, after: dict) -> dict:
    """Whether `after` holds the node `expect` names, with its minutes and data."""
    who = [c for c in after["characters"] if c["name"].upper() == expect.name]
    base = {"expect": dataclasses.asdict(expect)}
    if not who:
        return {**base, "verdict": "refutes", "why": f"no {expect.name} in the resave"}
    nodes = [n for n in who[0]["nodes"] if n["id"] == expect.id]
    if not nodes:
        return {**base, "verdict": "refutes",
                "why": f"{expect.name} holds no node with id {expect.id}"}
    for n in nodes:
        if n["minutes"] == expect.minutes and (
                expect.data is None or n["data"] == expect.data):
            return {**base, "verdict": "accepts", "found": n}
    return {**base, "verdict": "refutes", "found": nodes,
            "why": f"{expect.name}'s id {expect.id} node holds "
                   + ", ".join(f"{n['minutes']} minutes data {n['data']:02X}"
                               for n in nodes)}


_SAVGAM = re.compile(r"SAVGAM([A-J])(\.DAT|\.PTY)")


def containers_in(save: pathlib.Path) -> dict[str, str]:
    """Slot letter -> saved-game suffix, `.DAT` or Pools of Darkness' `.PTY`,
    for every `SAVGAM?` file in `save`, whatever the case."""
    out: dict[str, str] = {}
    for p in save.iterdir():
        m = _SAVGAM.fullmatch(p.name.upper())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def slots_in(save: pathlib.Path) -> list[str]:
    """The slot letters `save` holds a `SAVGAM?.DAT` or `.PTY` for."""
    return sorted(containers_in(save))


def source_slot(save: pathlib.Path, wanted: str | None = None) -> str:
    """The one slot of `save` to install: `wanted`, or the only one there is."""
    slots = slots_in(save)
    if wanted:
        if wanted.upper() not in slots:
            raise FileNotFoundError(f"{save} holds no SAVGAM{wanted.upper()} saved "
                                    f"game (it holds {', '.join(slots) or 'none'})")
        return wanted.upper()
    if len(slots) != 1:
        raise FileNotFoundError(
            f"{save} holds {len(slots)} SAVGAM?.DAT or .PTY files; one is wanted "
            "(name it with --from-slot)")
    return slots[0]


def install(save: pathlib.Path, save_dir: pathlib.Path, letter: str,
            source: str | None = None, same_letter: bool = False) -> dict:
    """Empty `save_dir` and put slot `source` of `save` into it as `letter`.

    The staged tree's own `SAVE` is the archives' copy, which is the edited
    play directory (`.claude/rules/testing.md`), so none of it is kept.
    `same_letter` refuses a rename, which Silver Blades will not load.  A
    Pools of Darkness slot is its `SAVGAM<slot>.PTY`, its `VAULT<slot>.DAT`
    and its `CHRDAT` files, which is what `dos_codec.new_pod_save_from` writes.
    """
    source = source_slot(save, source)
    suffix = containers_in(save)[source]
    letter = letter.upper()
    if same_letter and source != letter:
        raise ValueError(f"this title loads a slot only under the letter it was "
                         f"written as; install {source} as {source}, not {letter}")
    for old in save_dir.glob("*"):
        if old.is_file():
            old.unlink()
    took = {"from_slot": source, "as_slot": letter, "files": []}
    for p in sorted(save.iterdir()):
        name = p.name.upper()
        if name == f"SAVGAM{source}{suffix}":
            dest = f"SAVGAM{letter}{suffix}"
        elif suffix == ".PTY" and name == f"VAULT{source}.DAT":
            dest = f"VAULT{letter}.DAT"
        elif name.startswith(f"CHRDAT{source}"):
            dest = f"CHRDAT{letter}{name[7:]}"
        else:
            continue
        (save_dir / dest).write_bytes(p.read_bytes())
        took["files"].append(dest)
    return took


def stage_hall(save_dir: pathlib.Path, letter: str) -> dict:
    """Open every school: the word at `SAVGAM+0xD51` becomes `0x00FF`."""
    path = save_dir / f"SAVGAM{letter.upper()}.DAT"
    data = bytearray(path.read_bytes())
    if len(data) < HALL_WORD + 2:
        # A slice assignment past the end of a bytearray appends.
        raise ValueError(f"{path.name} is {len(data)} bytes, too short for the "
                         f"hall word at {HALL_WORD:#x}")
    before = bytes(data[HALL_WORD:HALL_WORD + 2])
    data[HALL_WORD:HALL_WORD + 2] = HALL_OPEN.to_bytes(2, "little")
    path.write_bytes(bytes(data))
    return {"stage": "hall", "file": path.name, "offset": hex(HALL_WORD),
            "before": before.hex(), "after": data[HALL_WORD:HALL_WORD + 2].hex()}


def stage_xp(save_dir: pathlib.Path, letter: str, line: int, xp: int) -> dict:
    """Write `xp` into roster line `line`'s `experience` field."""
    path = save_dir / f"CHRDAT{letter.upper()}{line}.SAV"
    c = dos_codec.read_character(path)
    f = c.fields["experience"]
    data = bytearray(path.read_bytes())
    before = bytes(data[f.offset:f.offset + f.size])
    data[f.offset:f.offset + f.size] = xp.to_bytes(f.size, "little")
    path.write_bytes(bytes(data))
    return {"stage": "xp", "file": path.name, "name": c.name,
            "offset": hex(f.offset), "before": before.hex(),
            "after": data[f.offset:f.offset + f.size].hex()}


def stage_node(save_dir: pathlib.Path, letter: str, line: int, node: bytes) -> dict:
    """Append one effect node, its five bytes and a NULL next pointer, to line `line`."""
    record = save_dir / f"CHRDAT{letter.upper()}{line}.SAV"
    c = dos_codec.read_character(record)
    path = record.with_suffix(dos_codec.deltas_for(len(record.read_bytes()))
                              .effect_suffix)
    was = path.read_bytes() if path.is_file() else b""
    full = node[:5] + bytes(dos_codec.EFFECT_SIZE - 5)
    path.write_bytes(was + full)
    return {"stage": "node", "file": path.name, "name": c.name,
            "at": len(was), "bytes": full.hex(), "node": node_dict(full)}


def default_out(issue: str, run: str, sha: str) -> pathlib.Path:
    return scratch.cache_dir("acceptance", issue, f"{sha[:10]}-{run}")


def git_state() -> dict:
    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    dirty = [line[3:] for line in git("status", "--porcelain",
                                      "--untracked-files=no").splitlines()]
    return {"sha": git("rev-parse", "HEAD") or "unknown", "dirty": dirty}


# --------------------------------------------------------------------------
# The conversion: a C64 party, staged, through Save As DOS
# --------------------------------------------------------------------------


def c64_base(title: str, override: str | None = None) -> pathlib.Path | None:
    """The C64 disk `--fixture-row` stages into; None means the committed fixture."""
    if override:
        return pathlib.Path(override)
    if title not in C64_BASES:
        return None
    from tools.registry import specimens
    return specimens.tree_root() / "por-c64" / C64_BASES[title]


def staged_disk(base: pathlib.Path, title: str,
                rows: list[tuple[int, int, int, int, int]]) -> tuple[bytes, dict]:
    """`base` with `rows` written into its save payload, and what was staged.

    Each row's minutes left are read at the save's own clock
    (`effects.remaining_minutes`), which is what the conversion turns into a
    node's minutes.
    """
    from goldbox import c64_save, dos_savegame, effects
    from goldbox.d64 import D64, attach_load_address, split_load_address
    container = {"curse": c64_save.CURSE_OF_THE_AZURE_BONDS,
                 "ssb": c64_save.SECRET_OF_THE_SILVER_BLADES,
                 "pool": c64_save.POOL_OF_RADIANCE}[title]
    image = D64.open(str(base))
    load, body = split_load_address(image.read_file(container.save_file))
    body = bytearray(body)
    clock = tuple(body[container.clock + i] for i in range(dos_savegame.CLOCK_DIGITS))
    minutes = effects.clock_minutes(clock)
    for row in rows:
        effects.write_effect(body, *row)
    image.write_file_inplace(container.save_file, attach_load_address(load, bytes(body)))
    return image.to_bytes(), {
        "base": str(base), "clock": list(clock), "clock_minutes": minutes,
        "minutes_left": [effects.remaining_minutes(r[3], minutes) for r in rows]}


def build_source(rows: list[tuple[int, int, int, int, int]], out: pathlib.Path,
                 title: str = "pool", base: str | None = None) -> dict:
    """Stage `rows` into a C64 party and Save As DOS into `out/source`.

    The route is the editor's own, `prepare_save_as` then `publish`, as
    `tests/convert/test_runningeffects.py`'s `_dos_plan` prepares it.
    `prepare_save_as` refuses a conversion that would drop a field, which is
    reported as `refused` and ends the run before any boot.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster, saveplan
    from editor.convert import Source
    from goldbox import effects
    from goldbox.c64_port import POOL_OF_RADIANCE
    from goldbox.savegame import SaveGame0, SaveGame1
    from tools.convert import convertdrops

    disk = out / "source.d64"
    report: dict = {"rows": [list(r) for r in rows], "disk": disk.name}
    where = c64_base(title, base)
    if where is None:
        fixtures = REPO / "tests" / "fixtures"
        payload = bytearray(SaveGame0.from_prg(
            (fixtures / "savedgame0.bin").read_bytes()).to_bytes())
        save1 = SaveGame1.from_prg((fixtures / "savedgame1.bin").read_bytes()).to_bytes()
        for row in rows:
            effects.write_effect(payload, *row)
        disk.write_bytes(dos_codec.save_disk(bytes(payload), save1,
                                             POOL_OF_RADIANCE).to_bytes())
        report["base"] = "tests/fixtures/savedgame0.bin"
    else:
        data, staged = staged_disk(where, title, rows)
        disk.write_bytes(data)
        report.update(staged)
    party = roster.Party(str(disk))
    source = Source.of_snapshot(saveplan.prepare(party))
    assets = saveplan.resolve_assets(source, "dos",
                                     game_files=convertdrops.game_files,
                                     dos_folder=dosbox.find_game(TITLES[title].stem))
    dest = out / "source"
    try:
        plan = saveplan.prepare_save_as(party, "dos", dest, assets)
    except saveplan.DroppedFields as e:
        return {**report, "refused": str(e)}
    report["dropped"] = list(plan.report.dropped)
    report["losses"] = list(plan.report.losses)
    saveplan.publish(plan, party)
    report["files"] = sorted(p.name for p in dest.iterdir())
    report["nodes"] = {
        p.name: [node_dict(p.read_bytes()[i:i + dos_codec.EFFECT_SIZE])
                 for i in range(0, p.stat().st_size - dos_codec.EFFECT_SIZE + 1,
                                dos_codec.EFFECT_SIZE)]
        for p in sorted(dest.iterdir())
        if p.suffix.upper() in EFFECT_SUFFIXES and p.stat().st_size}
    report["read"] = {x: read_slot(dest, x) for x in slots_in(dest)}
    return report


# --------------------------------------------------------------------------
# The conversion: an Amiga Pools of Darkness saved game, through Convert
# --------------------------------------------------------------------------


def parse_amiga_slot(text: str) -> str:
    """`SavGamA.pty`, `savgama.pty` or `A`: the Amiga slot letter."""
    m = re.fullmatch(r"(?:savgam)?([a-j])(?:\.pty)?", text.strip(), re.IGNORECASE)
    if m is None:
        raise ValueError(f"not an Amiga Pools of Darkness slot: {text!r} "
                         "(say SavGamA.pty or A)")
    return m.group(1).upper()


def amiga_image(disk: str) -> tuple[str, bytes]:
    """`disk` as `(label, bytes)`: a path to an `.adf`, or the end of exactly
    one `tools/amiga/amigasaves.py` label, such as
    `Pools Of Darkness.zip!Pools of Darkness3.adf`.  Read only."""
    path = pathlib.Path(disk)
    if path.is_file():
        return str(path), path.read_bytes()
    from tools.amiga import amigasaves
    hits = [(label, data) for label, data in amigasaves.images()
            if label.endswith(disk)]
    if len(hits) != 1:
        raise FileNotFoundError(
            f"{len(hits)} Amiga disk images end with {disk!r}; one is wanted"
            + (": " + ", ".join(label for label, _ in hits) if hits else
               " (set $AMIGA_DISKS or pass a path)"))
    return hits[0]


@contextlib.contextmanager
def flag_on(name: str):
    """`name` set to `1` for the block, and put back as it was afterwards."""
    was = os.environ.get(name)
    os.environ[name] = "1"
    try:
        yield
    finally:
        if was is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = was


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.name}: {record.getMessage()}")


def build_amiga_source(disk: str, slot: str, out: pathlib.Path) -> dict:
    """Convert Amiga slot `slot` of `disk` to a DOS save folder in `out/source`.

    The route is the Convert window's: `Source.detect` on the disk, the one
    DOS direction `destinations_for` offers with `WISH_EXPERIMENTAL_POD_CONVERT`
    set, `saveplan.rehearse`, then the direction's `write` into the folder.
    The disk is copied to `out/source.adf` and never written.  A warning the
    conversion logs (a spell id the DOS book does not hold, say) is listed in
    `warnings`, since it reaches neither `dropped` nor `losses`.  A conversion
    that raises is reported as `refused`.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import convert, saveplan

    letter = parse_amiga_slot(slot)
    label, data = amiga_image(disk)
    adf = out / "source.adf"
    adf.write_bytes(data)
    report: dict = {"disk": label, "adf_sha256": hashlib.sha256(data).hexdigest(),
                    "amiga_slot": f"SavGam{letter}.pty",
                    "flag": f"{convert.POD_CONVERT_ENV}=1"}
    collect = _Collect()
    wish_log = logging.getLogger("wish")
    # The GUI's debug log parks this logger above CRITICAL while it is off,
    # and a level filters before any handler, so lower it for the run.
    was_level = wish_log.level
    if not was_level or was_level > logging.WARNING:
        wish_log.setLevel(logging.WARNING)
    wish_log.addHandler(collect)
    try:
        with flag_on(convert.POD_CONVERT_ENV):
            source = convert.Source.detect(adf, slot=letter)
            if source.key != "pools-of-darkness" or letter not in (
                    source.available_slots or [source.slot]):
                return {**report, "refused": f"{label} holds no Pools of Darkness "
                        f"slot {letter} (it holds {source.available_slots})"}
            directions = [d for d in convert.destinations_for(source)
                          if d.destination_port == "dos"]
            if len(directions) != 1:
                return {**report, "refused": f"{len(directions)} DOS directions "
                        "are offered for this disk; one is wanted"}
            rehearsal, wrote = saveplan.rehearse(directions[0], source,
                                                 saveplan.Assets())
            dest = out / "source"
            dest.mkdir(parents=True, exist_ok=True)
            directions[0].write(rehearsal, dest)
    except Exception as e:  # noqa: BLE001 -- recorded, and the run stops before a boot
        return {**report, "refused": f"{type(e).__name__}: {e}",
                "warnings": collect.lines}
    finally:
        wish_log.removeHandler(collect)
        wish_log.setLevel(was_level)
    report["direction"] = type(directions[0]).__name__
    report["dos_slot"] = wrote
    report["dropped"] = list(rehearsal.report.dropped)
    report["losses"] = list(rehearsal.report.losses)
    # The writer runs twice, rehearsing and then writing, so each line is
    # listed once.
    report["warnings"] = list(dict.fromkeys(collect.lines))
    report["files"] = sorted(p.name for p in dest.iterdir())
    report["read"] = {wrote: read_slot(dest, wrote)}
    return report


# --------------------------------------------------------------------------
# The driven part
# --------------------------------------------------------------------------


class Driver:
    """The steps, on one booted session of a DOS Gold Box title.

    Every screen the driver waits at is logged with its `bar_signature`,
    `Screen.glyphs(BAR)` and whole-frame digest beside a PNG, which is what a
    later classifier row is written from.  The party menu, the map and the
    camp bar are learnt off the screen when they are reached, not compared
    with digests measured elsewhere, except for Silver Blades, whose screens
    `ssbimport.BARS` already classifies.
    """

    def __init__(self, session, note, slot: str, title: str = "pool",
                 party_size: int = 6):
        self.s = session
        self.note = note
        self.slot = slot
        self.title = TITLES[title]
        self.keys = self.title.rest_keys()
        self.game = dosbox.PoolOfRadiance(session)
        self.camp_sig: str | None = None
        self.world_ink: str | None = None
        self.world_sig: str | None = None
        self.party_sig: str | None = None
        #: The party's place: `boot`, `map`, `party` or `camp`.
        self.where = "boot"
        #: The roster line the party menu's highlight is on, counted from 1.
        self.line = 1
        self.party_size = max(1, party_size)
        #: True after a random event's `GO`: the party is on the map, not in camp.
        self.left_camp = False
        #: Every random event answered, in order; the summary lists them.
        self.events: list[dict] = []
        self.n = 0
        self._ssb = None

    # -- evidence ----------------------------------------------------------

    def shot(self, label: str) -> str:
        self.n += 1
        name = f"{self.n:03d}-{label}"
        self.s.shot(name, allow_blank=True)
        screen = self.s.capture()
        self.note(event="screen", shot=f"{name}.png", bar=bar_signature(screen),
                  glyphs=screen.glyphs(dosbox.BAR), digest=screen.digest())
        return name

    def fail(self, label: str, why: str) -> StepFailed:
        name = self.shot(f"lost-{label}")
        return StepFailed(f"{why}; see {name}.png")

    # -- helpers -----------------------------------------------------------

    @property
    def ssb(self) -> ssbimport.Driver:
        """`ssbimport`'s Silver Blades route, numbering its shots with ours."""
        if self._ssb is None:
            self._ssb = ssbimport.Driver(self.s, self.note)
            self._ssb.shot = self.shot
        return self._ssb

    def text(self, quiet: float = 0.5) -> str:
        return self.s.settle(quiet=quiet, timeout=20.0).digest(TEXT_WINDOW)

    def press_changes(self, key: str, tries: int = 2, wait: float = 5.0) -> bool:
        """Press `key` until the text window changes, at most `tries` times.

        Each press is given `wait` seconds to show before the next, so a key
        the game was merely slow to draw is not pressed twice.
        """
        before = self.text()
        for _ in range(tries):
            self.s.key(key)
            if self.s.wait_for(lambda sc: sc.digest(TEXT_WINDOW) != before, wait):
                self.text()
                return True
        return False

    def press_screen_changes(self, key: str, tries: int = 2,
                             wait: float = 10.0) -> bool:
        """Press `key` until the whole frame differs from before the first press.

        For the party menu and the prompts it opens, which do not animate.  A
        slot letter is pressed once only (`tries=1`): a second one landing on
        the party menu would be a command there -- `E` is exit to DOS in Curse.
        """
        before = self.s.capture().digest()
        for _ in range(tries):
            self.s.key(key)
            if self.s.wait_for(lambda sc: sc.digest() != before, wait):
                return True
        return False

    def save_path(self, letter: str) -> pathlib.Path:
        """The saved game a `save` step is believed by, in this title's suffix."""
        if self.title.suffix == ".DAT":
            return self.s.save_file(letter)
        return self.s.save_dir / f"SAVGAM{letter.upper()}{self.title.suffix}"

    def pod_menu(self, row: int, label: str) -> None:
        """Pools of Darkness' party menu: highlight `row`, pick it, and see
        the screen change."""
        before = self.s.capture().digest()
        got = self.s.walk_highlight(POD_MENU_RECT, row, key="Down")
        if got != row:
            raise self.fail(f"menu-{label}", f"the party menu's highlight reached "
                            f"row {got}, not {row}")
        self.s.key("Return")
        if not self.s.wait_for(lambda sc: sc.digest() != before, 20.0):
            raise self.fail(f"menu-{label}", f"row {row} of the party menu "
                            "changed nothing")

    def on_party_menu(self, screen=None) -> bool:
        screen = screen if screen is not None else self.s.capture()
        return self.party_sig is not None and bar_signature(screen) == self.party_sig

    def wait_party_menu(self, timeout: float) -> bool:
        return self.s.wait_for(self.on_party_menu, timeout)

    def in_camp(self, screen=None) -> bool:
        screen = screen if screen is not None else self.s.capture()
        return self.camp_sig is not None and bar_signature(screen) == self.camp_sig

    def wait_camp(self, timeout: float, hold: float = 1.0) -> bool:
        """Wait for the camp bar, and for it to still be there `hold` later."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.in_camp():
                time.sleep(hold)
                if self.in_camp():
                    return True
            time.sleep(0.3)
        return False

    def on_world(self, screen=None) -> bool:
        screen = screen if screen is not None else self.s.capture()
        return self.world_ink is not None and screen.ink(dosbox.BAR) == self.world_ink

    def wait_file(self, path: pathlib.Path, was: bytes | None, label: str) -> None:
        deadline = time.time() + 60.0
        while not (path.is_file() and path.read_bytes() != was):
            if time.time() > deadline:
                raise self.fail(label, f"{path.name} never changed")
            time.sleep(0.3)
        dosbox.settle_files(self.s.save_dir, quiet=1.0, timeout=30.0)

    def after_rest(self, timeout: float, in_step: str) -> None:
        """Wait out a rest: the camp bar, or Pool's `GO STAY` answered with GO.

        Nothing but `GO` is ever pressed at the event.  A third event, any
        screen that is neither the camp bar, the event nor (after an event)
        the map, or a text window that stops changing for `REST_STALL`
        seconds away from the camp bar, ends the run.
        """
        answered = 0
        while True:
            deadline = time.time() + timeout
            screen = None
            last_text, changed = None, time.time()
            while time.time() < deadline:
                screen = self.s.capture()
                if answered == 0 and self.in_camp(screen):
                    time.sleep(1.0)
                    if self.in_camp():
                        return
                elif answered and self.on_world(screen):
                    time.sleep(1.0)
                    if self.on_world():
                        self.left_camp = True
                        return
                if self.title.watch and bar_signature(screen) == WATCH_BAR:
                    break
                text, now = screen.digest(TEXT_WINDOW), time.time()
                if text != last_text:
                    last_text, changed = text, now
                elif now - changed > REST_STALL:
                    raise self.fail(
                        "rest-end", f"nothing under the viewport changed for "
                        f"{REST_STALL:.0f} seconds and the camp bar is not back "
                        "(a message, a fight, or the game stopped)")
                time.sleep(0.3)
            else:
                raise self.fail(
                    "rest-end", "the camp bar never came back after resting "
                    "(interrupted, or a screen this driver does not know)")
            if answered >= MAX_EVENTS:
                raise self.fail("rest-events", f"another random event after "
                                f"{MAX_EVENTS} were answered")
            shot = self.shot(f"event-{answered + 1}")
            event = {"kind": "go_stay", "step": in_step, "shot": f"{shot}.png",
                     "bar": WATCH_BAR, "text": screen.digest(TEXT_WINDOW),
                     "answered": WATCH_GO.upper()}
            self.events.append(event)
            self.note(event="random", **event)
            self.s.key(WATCH_GO)
            answered += 1
            timeout = 60.0

    def ensure_camp(self) -> None:
        """Camp again when a random event's GO left the party on the map."""
        if self.left_camp:
            self.camp()

    def record_world(self, screen) -> None:
        self.game.record_map(screen)
        self.world_sig = bar_signature(screen)
        self.world_ink = screen.ink(dosbox.BAR)

    # -- the steps ---------------------------------------------------------

    def load(self) -> dict:
        if self.title.key == "ssb":
            return self._load_ssb()
        if self.title.key == "darkness":
            return self._load_pod()
        self.game.to_main_menu()
        self.shot("menu")
        if self.title.key == "pool":
            try:
                self.game.load_game(self.slot)
            except TimeoutError as e:
                raise self.fail("load", str(e)) from None
            self.record_world(self.s.capture())
            self.shot("loaded")
            self.where = "map"
            return {"slot": self.slot, "status": self.game.status(),
                    "map_bar": self.world_sig}
        self.s.settle(quiet=0.6, timeout=20.0)
        if not self.press_screen_changes(PARTY_LOAD):
            raise self.fail("load", "LOAD SAVED GAME did not open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.s.settle(quiet=1.0, timeout=90.0)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig}

    def _load_ssb(self) -> dict:
        self.ssb.to_party_menu()
        self.ssb.menu(SSB_LOAD_ROW, "load")
        if not self.s.wait_for(lambda sc: self.ssb.bar(sc) != "party_menu", 20.0):
            raise self.fail("load", f"row {SSB_LOAD_ROW} of the party menu did "
                            "not open a slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.ssb.wait_bar("party_menu", timeout=90.0)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig}

    def _load_pod(self) -> dict:
        """Past the titles and the copy-protection question to the party
        menu, `Load Saved Game`, and the slot letter pressed once."""
        answered = dospod.to_party_menu(self.s)
        self.shot("menu")
        self.pod_menu(POD_LOAD_ROW, "load")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.s.settle(quiet=1.0, timeout=90.0)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig,
                "questions_answered": len(answered)}

    def begin(self) -> dict:
        if self.where != "party":
            raise StepFailed("begin needs the party menu")
        if self.title.key == "ssb":
            self.ssb.menu(ssbimport.MENU_AFTER["begin"], "begin")
            self.ssb.intro()
        elif self.title.key == "darkness":
            self.pod_menu(POD_MENU_AFTER["begin"], "begin")
        elif not self.press_screen_changes(PARTY_BEGIN, tries=1, wait=30.0):
            raise self.fail("begin", "BEGIN ADVENTURING did not leave the party menu")
        screen = self.s.settle(quiet=1.0, timeout=60.0)
        if self.on_party_menu(screen):
            raise self.fail("begin", "the party menu is still showing")
        self.record_world(screen)
        self.shot("map")
        self.where = "map"
        return {"map_bar": self.world_sig}

    def camp(self) -> dict:
        # `E` at Curse's party menu is exit to DOS, so it is never pressed there.
        if self.on_party_menu():
            raise self.fail("camp", "the party menu is showing, not the map")
        world = self.game.world_bar or self.game.bar()
        for _ in range(2):
            self.s.key(ENCAMP)
            if not self.s.wait_while_ink(dosbox.BAR, world, 30.0):
                raise self.fail("camp", "ENCAMP did not change the command bar")
            screen = self.s.settle(quiet=1.5, timeout=30.0)
            if self.world_sig is None or bar_signature(screen) != self.world_sig:
                break
        else:
            raise self.fail("camp", "the map's own bar is still showing after ENCAMP")
        self.camp_sig = bar_signature(screen)
        self.world_ink = world
        self.left_camp = False
        self.where = "camp"
        self.shot("camp")
        return {"camp_bar": self.camp_sig}

    def map_status(self, label: str, screens: list[dict]) -> str:
        """The settled map's status line, with a shot, appended to `screens`;
        a screen that is not the map stops the run."""
        screen = self.s.settle(quiet=0.6, timeout=30.0)
        if not self.on_world(screen):
            raise self.fail(label, "the map bar did not return (combat or "
                            "an unknown screen)")
        status = self.game.status()
        screens.append({"shot": self.shot(label), "bar": bar_signature(screen),
                        "status": status})
        return status

    def walk(self, route: str) -> dict:
        """From the loaded Pool map, turn around and step one square."""
        if self.title.key == "darkness" and self.where == "map" and route == "1":
            return self._walk_one()
        if self.title.key != "pool" or self.where != "map" or route != "MI":
            raise StepFailed("walk MI needs Pool's loaded map")

        screens: list[dict] = []

        def record(label: str) -> str:
            return self.map_status(label, screens)

        before = record("walk-before")
        for n in (1, 2):
            if not self.game.turn_right():
                raise self.fail(f"walk-turn-{n}", "the map bar did not return "
                                "after turning (combat or an unknown screen)")
            turned = record(f"walk-turn-{n}")
        if not self.game.step():
            raise self.fail("walk-step", "the map bar did not return after the "
                            "step (combat or an unknown screen)")
        after = record("walk-step")
        if after == turned:
            raise self.fail("walk-blocked", "the settled status did not change "
                            "after Up (a blocked step)")
        return {"route": route, "map_bar": self.world_sig,
                "status_before": before, "status_after": after,
                "screens": screens}

    def _walk_one(self) -> dict:
        """One square forward; past a wall, turn right and try again, at most
        once per facing.  The step is believed when the settled status line
        changes, which the square and facing on it make it do."""
        screens: list[dict] = []
        before = first = self.map_status("walk-before", screens)
        for turns in range(4):
            if not self.game.step():
                raise self.fail(f"walk-step-{turns + 1}", "the map bar did not "
                                "return after the step (combat or an unknown "
                                "screen)")
            after = self.map_status(f"walk-step-{turns + 1}", screens)
            if after != before:
                return {"route": "1", "map_bar": self.world_sig, "turns": turns,
                        "status_before": first, "status_after": after,
                        "screens": screens}
            if not self.game.turn_right():
                raise self.fail(f"walk-turn-{turns + 1}", "the map bar did not "
                                "return after turning")
            before = self.map_status(f"walk-turn-{turns + 1}", screens)
        raise self.fail("walk-blocked", "no facing let the party step (the "
                        "settled status never changed after Up)")

    def select(self, line: int) -> None:
        """Move the roster highlight to line `line`, counted from 1.

        `End` moves it a line and wraps, and it stays where the last command
        left it, as at Curse's party menu; each press must change the screen.
        """
        for _ in range((line - self.line) % self.party_size):
            if not self.s.press_until_change(ROSTER_NEXT):
                raise self.fail(f"select-{line}", "End did not move the roster "
                                "highlight")
        self.line = line

    def open_sheet(self, line: int) -> dict:
        if self.title.key != "darkness" or self.camp_sig is None:
            raise StepFailed("sheet and items need Pools of Darkness' camp first")
        self.ensure_camp()
        self.select(line)
        self.shot(f"line-{line}")
        if not self.press_screen_changes(VIEW, tries=1, wait=15.0):
            raise self.fail(f"sheet-{line}", "VIEW changed nothing")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        if self.in_camp(screen):
            raise self.fail(f"sheet-{line}", "the camp bar is still showing "
                            "after VIEW")
        return {"line": line, "sheet": self.shot(f"sheet-{line}"),
                "sheet_bar": bar_signature(screen), "digest": screen.digest()}

    def back_to_camp(self, label: str, tries: int = 3) -> None:
        """`Exit` until the camp bar is back, looking before every press:
        `Exit` on the camp bar itself breaks camp."""
        for _ in range(tries):
            if self.in_camp(self.s.settle(quiet=0.6, timeout=20.0)):
                return
            self.s.key(LEAVE)
        if not self.wait_camp(timeout=15.0):
            raise self.fail(label, f"the camp bar never came back after "
                            f"{tries} presses of Exit")

    def sheet(self, line: int) -> dict:
        """Roster line `line`'s sheet from camp, shot, and back to camp."""
        got = self.open_sheet(line)
        self.back_to_camp(f"sheet-{line}-back")
        return got

    def items(self, line: int) -> dict:
        """Roster line `line`'s `ITEMS` from its sheet, every page shot.

        `Next` is pressed until it changes nothing or brings back the first
        page; `ITEMS_PAGES` pages that are all different stop the run.
        """
        got = self.open_sheet(line)
        if not self.press_screen_changes(SHEET_ITEMS, tries=1, wait=15.0):
            raise self.fail(f"items-{line}", "ITEMS changed nothing on the sheet")
        pages: list[dict] = []
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        first = screen.digest()
        while True:
            pages.append({"shot": self.shot(f"items-{line}-{len(pages) + 1}"),
                          "bar": bar_signature(screen), "digest": screen.digest()})
            if len(pages) >= ITEMS_PAGES:
                raise self.fail(f"items-{line}-pages", f"{ITEMS_PAGES} pages and "
                                "Next still turns another")
            before = screen.digest()
            self.s.key(ITEMS_NEXT)
            if not self.s.wait_for(lambda sc: sc.digest() != before, 5.0):
                break
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            if screen.digest() == first:
                break
        self.back_to_camp(f"items-{line}-back")
        return {**got, "pages": pages}

    def zero_rest_time(self, limit: int = 120) -> int:
        """Select days and press subtract until three presses change nothing.

        With days at zero the first subtract zeroes the whole time; with days
        above it each press takes one off and the next zeroes the rest.
        Three quiet presses in a row, not one, so a swallowed key is not
        read as the time having reached zero.
        """
        if not self.press_changes(self.keys.days):
            raise self.fail("rest-days", "the days field did not take the highlight")
        before, still, presses = self.text(), 0, 0
        while still < 3:
            if presses >= limit:
                raise self.fail("rest-zero", f"{limit} presses of Dec never settled")
            self.s.key(self.keys.dec)
            presses += 1
            now = self.text()
            still = still + 1 if now == before else 0
            before = now
        return presses

    def set_rest_time(self, minutes: int) -> dict:
        """From the days field at zero: days, then hours, then fives of minutes."""
        days, hours, fives = rest_presses(minutes)
        for _ in range(days):
            if not self.press_changes(self.keys.inc):
                raise self.fail("rest-inc-days", "Inc on days changed nothing")
        if not self.press_changes(self.keys.hours):
            raise self.fail("rest-hours", "the hours field did not take the highlight")
        for _ in range(hours):
            if not self.press_changes(self.keys.inc):
                raise self.fail("rest-inc-hours", "Inc on hours changed nothing")
        if not self.press_changes(self.keys.mins):
            raise self.fail("rest-mins", "the minutes field did not take the highlight")
        for _ in range(fives):
            if not self.press_changes(self.keys.inc):
                raise self.fail("rest-inc-mins", "Inc on minutes changed nothing")
        return {"days": days, "hours": hours, "fives": fives}

    def rest(self, minutes: int) -> dict:
        if self.camp_sig is None:
            raise StepFailed("rest needs camp first")
        self.ensure_camp()
        if not self.press_changes(CAMP_REST, wait=10.0):
            raise self.fail("rest-menu", "REST did not open the rest menu")
        self.shot("rest-menu")
        zeroed = self.zero_rest_time()
        self.shot("rest-zero")
        presses = self.set_rest_time(minutes)
        self.shot("rest-set")
        self.s.key(self.keys.go)
        passes = minutes // REST_STEP
        self.after_rest(60.0 + 2.0 * passes, f"rest {minutes}m")
        self.shot("rested")
        return {"asked": minutes, "zero_presses": zeroed, **presses,
                "left_camp": self.left_camp}

    def display(self) -> dict:
        """Capture Pool's single six-member Magic display page and return to camp."""
        if self.title.key != "pool" or self.camp_sig is None:
            raise StepFailed("display needs Pool camp first")
        self.ensure_camp()
        self.s.key("m")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POOL_MAGIC_BAR, 15.0):
            raise self.fail("display-magic", "MAGIC bar did not open")
        magic = self.shot("display-magic")
        self.s.key("d")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POOL_DISPLAY_BAR, 15.0):
            raise self.fail("display-page", "DISPLAY page did not open")
        screen = self.s.settle(quiet=0.6, timeout=20.0)
        if bar_signature(screen) != POOL_DISPLAY_BAR:
            raise self.fail("display-page", "DISPLAY page changed unexpectedly")
        visible = sum(not screen.flat((8, y, 8, 8)) for y in POOL_DISPLAY_NAME_ROWS)
        if visible != 6:
            raise self.fail("display-members", f"DISPLAY showed {visible} member rows, not six")
        page = self.shot("display-page")
        self.s.key("Return")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POOL_MAGIC_BAR, 15.0):
            raise self.fail("display-back-magic", "Magic bar did not return after DISPLAY")
        self.shot("display-back-magic")
        self.s.key("e")
        if not self.wait_camp(timeout=15.0):
            raise self.fail("display-back-camp", "camp bar did not return after Magic")
        camp = self.shot("display-back-camp")
        return {"magic_shot": magic, "display_shot": page, "camp_shot": camp,
                "visible_members": visible, "back_in_camp": True}

    def save(self, letter: str) -> dict:
        if self.where == "party":
            return self.party_save(letter)
        if self.camp_sig is None:
            raise StepFailed("save needs camp first")
        self.ensure_camp()
        path = self.save_path(letter)
        was = path.read_bytes() if path.is_file() else None
        camp_ink = self.s.capture().ink(dosbox.BAR)
        self.s.key(CAMP_SAVE)
        if not self.s.wait_while_ink(dosbox.BAR, camp_ink, 30.0):
            raise self.fail("save-which", "SAVE did not open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("save-which")
        self.s.key(letter.lower())
        self.wait_file(path, was, "save-file")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("saved")
        self.s.key(QUIT_NO)
        back = self.wait_camp(timeout=15.0)
        self.shot("after-save")
        return {"slot": letter, "file": path.name, "size": path.stat().st_size,
                "back_in_camp": back}

    def party_save(self, letter: str) -> dict:
        """`SAVE CURRENT GAME` at the party menu, back to the party menu.

        A `QUIT TO DOS` question after it, if Curse asks one, is declined:
        `n` is none of Curse's party-menu letters.
        """
        path = self.save_path(letter)
        was = path.read_bytes() if path.is_file() else None
        if self.title.key == "ssb":
            self.ssb.menu(ssbimport.MENU_AFTER["save"], "save")
            self.ssb.wait_bar("save_which")
        elif self.title.key == "darkness":
            self.pod_menu(POD_MENU_AFTER["save"], "save")
        elif not self.press_screen_changes(PARTY_SAVE):
            raise self.fail("save-which", "SAVE CURRENT GAME did not open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("save-which")
        self.s.key(letter.lower())
        self.wait_file(path, was, "save-file")
        back = self.wait_party_menu(15.0)
        if not back and self.title.key != "ssb":
            self.shot("after-save-question")
            self.s.key(QUIT_NO)
            back = self.wait_party_menu(15.0)
        self.shot("saved")
        if not back:
            raise self.fail("save-back", "the party menu never came back after saving")
        return {"slot": letter, "file": path.name, "size": path.stat().st_size,
                "at": "party menu"}

    def press(self, key: str) -> dict:
        """One key, pressed blind for a capture: the PNG is the reading."""
        self.s.key(key)
        self.s.settle(quiet=0.8, timeout=30.0)
        self.where = "pressed"
        return {"key": key, "shot": self.shot(f"press-{key}")}

    def train(self, line: int) -> dict:
        """Roster line `line`'s `TRAIN CHARACTER`, accepted, back to the party menu.

        `End` wraps, and the highlight stays where the last command left it,
        so the presses are `(line - here) % party size`
        (`docs/194-the-dos-training-ladder.md`).  A `t` that leaves the screen
        as it was is the school refusing; there is no message to read.
        """
        if self.where != "party" or self.title.key != "curse":
            raise StepFailed("train is Curse's party-menu command")
        for _ in range((line - self.line) % self.party_size):
            if not self.s.press_until_change(ROSTER_NEXT):
                raise self.fail("train-line", "End did not move the roster highlight")
        self.line = line
        self.shot(f"train-line-{line}")
        before = self.s.settle(quiet=0.6, timeout=20.0).digest()
        offered = False
        for _ in range(2):
            self.s.key(PARTY_TRAIN)
            if self.s.settle(quiet=0.8, timeout=20.0).digest() != before:
                offered = True
                break
        if not offered:
            raise self.fail("train-refused", f"TRAIN CHARACTER changed nothing for "
                            f"line {line} (the school refuses him, or the hall "
                            "is shut: stage --hall)")
        self.shot("train-offer")
        self.s.key(TRAIN_YES)
        self.s.settle(quiet=0.8, timeout=30.0)
        self.shot("trained")
        pressed = []
        for i in range(8):
            if self.on_party_menu(self.s.settle(quiet=0.8, timeout=30.0)):
                return {"line": line, "after": pressed}
            key = AFTER_TRAIN[i % len(AFTER_TRAIN)]
            self.s.key(key)
            pressed.append(key)
            self.shot(f"after-train-{key}")
        raise self.fail("train-back", "the party menu never came back after training")


def run(args) -> int:
    """`_run`, with the evidence log closed on every way out, including an early raise."""
    with contextlib.ExitStack() as outer:
        return _run(args, outer)


def _run(args, outer: contextlib.ExitStack) -> int:
    git = git_state()
    title = TITLES[args.title]
    out = pathlib.Path(args.out) if args.out else default_out(args.issue, args.run,
                                                              git["sha"])
    scratch.ensure(out)
    log = outer.enter_context((out / "run.jsonl").open("a"))

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    steps = [parse_step(s) for s in args.steps]
    expects = [parse_expect(e) for e in args.expect]
    summary: dict = {"title": args.title, "slot": args.slot.upper(),
                     "steps": args.steps, **git, "completed": False}
    note(event="start", out=str(out), **summary)

    def write_summary():
        (out / "summary.json").write_text(json.dumps(summary, indent=2))

    save = pathlib.Path(args.save) if args.save else None
    if args.fixture_row:
        shutil.rmtree(out / "source", ignore_errors=True)
        built = build_source([parse_row(r) for r in args.fixture_row], out,
                             args.title, getattr(args, "c64_save", None))
        summary["source"] = built
        note(event="converted", **{k: v for k, v in built.items() if k != "read"})
        if "refused" in built or built["dropped"] or built["losses"]:
            summary["lost"] = "the conversion dropped or lost a field"
            write_summary()
            return 1
        save = out / "source"
    elif getattr(args, "amiga_slot", None):
        shutil.rmtree(out / "source", ignore_errors=True)
        built = build_amiga_source(args.amiga_disk, args.amiga_slot, out)
        summary["source"] = built
        note(event="converted", **{k: v for k, v in built.items() if k != "read"})
        if "refused" in built or built["dropped"] or built["losses"]:
            summary["lost"] = "the conversion refused, dropped or lost something"
            write_summary()
            return 1
        save = out / "source"
    if not steps:
        summary["completed"] = True
        write_summary()
        return 0

    letter = args.slot.upper()
    from_slot = (source_slot(save, getattr(args, "from_slot", None))
                 if save is not None else None)
    if title.same_letter and from_slot not in (None, letter):
        raise ValueError(f"{args.title} loads a slot only under the letter it was "
                         f"written as: pass --slot {from_slot}")
    if save is not None and containers_in(save)[from_slot] != title.suffix:
        raise ValueError(f"{save} holds SAVGAM{from_slot}"
                         f"{containers_in(save)[from_slot]}, not the "
                         f"SAVGAM{from_slot}{title.suffix} {args.title} loads")
    if save is not None:
        check_staging(args, save, from_slot)
    saved: list[str] = []
    with contextlib.ExitStack() as stack:
        # Every callback runs even when an earlier one raises: a failed close
        # must not leave a slot leased.
        game = title.find_game()
        slot = dosbox.claim(args.note)
        stack.callback(slot.release)
        # `START.EXE` is `Session`'s own default, so only another launcher
        # is named.
        session = (dosbox.Session(slot, game) if title.exe == "START.EXE"
                   else dosbox.Session(slot, game, exe=title.exe))
        stack.callback(session.close)

        def keep_evidence():
            write_summary()
            try:
                kept = out / "shots"
                kept.mkdir(exist_ok=True)
                for png in sorted((session.dir / "shots").glob("*.png")):
                    shutil.copy(png, kept / png.name)
                if saved and "read" not in summary:
                    resave = out / "resave"
                    shutil.rmtree(resave, ignore_errors=True)
                    shutil.copytree(session.save_dir, resave)
            except OSError as e:
                print(f"could not keep the evidence: {e}", file=sys.stderr)
            write_summary()

        stack.callback(keep_evidence)
        d: Driver | None = None
        try:
            session.stage(fresh=True)
            shots = session.dir / "shots"
            shutil.rmtree(shots, ignore_errors=True)
            shots.mkdir(parents=True)
            took = install(save, session.save_dir, letter, from_slot,
                           title.same_letter)
            staged = stage(session.save_dir, letter, args)
            installed = out / "installed"
            shutil.rmtree(installed, ignore_errors=True)
            shutil.copytree(session.save_dir, installed)
            summary["installed"] = took
            summary["staged"] = staged
            note(event="staged", **took, stages=staged)
            session.boot(fresh=False)
            size = sum(1 for f in took.get("files", []) if f.endswith(".SAV")) or 6
            d = Driver(session, note, letter, args.title, party_size=size)
            summary["events"] = getattr(d, "events", [])
            results = []
            for step in steps:
                note(event="step", step=step.text)
                if step.kind == "load":
                    r = d.load()
                elif step.kind == "begin":
                    r = d.begin()
                elif step.kind == "camp":
                    r = d.camp()
                elif step.kind == "walk":
                    r = d.walk(step.key)
                elif step.kind == "rest":
                    r = d.rest(step.minutes)
                elif step.kind == "display":
                    r = d.display()
                elif step.kind == "save":
                    r = d.save(step.letter)
                    saved.append(step.letter)
                elif step.kind == "train":
                    r = d.train(step.line)
                elif step.kind == "sheet":
                    r = d.sheet(step.line)
                elif step.kind == "items":
                    r = d.items(step.line)
                elif step.kind == "shot":
                    r = {"shot": d.shot(step.name)}
                elif step.kind == "press":
                    r = d.press(step.key)
                else:
                    r = read_step(session.save_dir, out, letter, saved, steps, expects)
                    summary["read"] = r
                results.append({"step": step.text, **r})
                note(event="done", step=step.text,
                     **{k: v for k, v in r.items() if k != "slots"})
            summary["results"] = results
            summary["completed"] = True
        except (StepFailed, ssbimport.RouteLost) as e:
            summary["lost"] = str(e)
            note(event="lost", why=str(e))
        except (TimeoutError, dosbox.DosboxUnavailable, dosbox.BlankCapture) as e:
            why = f"{type(e).__name__}: {e}"
            if d is not None:
                try:
                    why = str(d.fail("timeout", why))
                except Exception:  # noqa: BLE001 -- the capture may be what failed
                    pass
            summary["lost"] = why
            note(event="lost", why=why)
    return 0 if summary["completed"] else 1


def check_staging(args, save: pathlib.Path, from_slot: str | None) -> None:
    """Refuse a stage the installed save cannot take, before a slot is claimed.

    `--hall` is a Pool and Curse field (`docs/194-the-dos-training-ladder.md`);
    another title's `SAVGAM` is not known to hold the hall word at that
    offset.  `--xp` and `--add-node` need the line's own `CHRDAT` file.
    """
    if getattr(args, "hall", False) and args.title not in HALL_TITLES:
        raise ValueError(f"--hall is measured for {', '.join(sorted(HALL_TITLES))} "
                         f"only, not {args.title}")
    if getattr(args, "hall", False):
        word = save / f"SAVGAM{from_slot}.DAT"
        if word.is_file() and word.stat().st_size < HALL_WORD + 2:
            raise ValueError(f"{word.name} is {word.stat().st_size} bytes, too "
                             f"short for the hall word at {HALL_WORD:#x}")
    names = {p.name.upper() for p in save.iterdir()}
    lines = ([parse_xp(t)[0] for t in getattr(args, "xp", []) or []]
             + [parse_node(t)[0] for t in getattr(args, "add_node", []) or []])
    for line in lines:
        want = f"CHRDAT{from_slot}{line}.SAV"
        if want not in names:
            raise ValueError(f"line {line} has no {want} in {save}")


def stage(save_dir: pathlib.Path, letter: str, args) -> list[dict]:
    """The `--hall`, `--xp` and `--add-node` stages, in that order."""
    done = []
    if getattr(args, "hall", False):
        done.append(stage_hall(save_dir, letter))
    for text in getattr(args, "xp", []) or []:
        done.append(stage_xp(save_dir, letter, *parse_xp(text)))
    for text in getattr(args, "add_node", []) or []:
        done.append(stage_node(save_dir, letter, *parse_node(text)))
    return done


def read_step(save_dir: pathlib.Path, out: pathlib.Path, letter: str,
              saved: list[str], steps: list[Step], expects: list[Expect]) -> dict:
    """Copy `SAVE/` out and decode the installed slot against each saved one."""
    resave = out / "resave"
    shutil.rmtree(resave, ignore_errors=True)
    shutil.copytree(save_dir, resave)
    before = read_slot(out / "installed", letter)
    asked = sum(s.minutes for s in steps if s.kind == "rest")
    result: dict = {"installed": before, "rested_minutes": asked, "slots": {}}
    previous = before
    for x in saved:
        after = read_slot(resave, x)
        result["slots"][x] = {
            **after,
            "clock_advanced": after["clock_minutes"] - before["clock_minutes"],
            "clock_since_previous": after["clock_minutes"] - previous["clock_minutes"],
            "compare": compare_nodes(before, after),
            "experience": compare_experience(before, after),
            "members": compare_members(before, after),
        }
        previous = after
    if saved and expects:
        result["verdicts"] = [judge(e, result["slots"][saved[-1]]) for e in expects]
    for line in describe(result):
        print(line, flush=True)
    return result


def describe(result: dict) -> list[str]:
    """The reading, one line per fact, for the terminal."""
    lines = []
    for x, s in result["slots"].items():
        lines.append(f"slot {x}: clock advanced {s['clock_advanced']} minutes "
                     f"(rested {result['rested_minutes']}), "
                     f"{s.get('clock_since_previous', s['clock_advanced'])} since "
                     "the save before it")
        place = s.get("place") or {}
        if "area" in place:
            lines.append(f"  area {place['area']} at {place['x']},{place['y']} "
                         f"facing {place['facing']}, set out {place['set_out']}")
        elif "dungeon_map" in place:
            lines.append(f"  map {place['dungeon_map']} at {place['x']},{place['y']} "
                         f"facing {place['facing']}, in a dungeon {place['in_dungeon']}")
        for row in s.get("members", []):
            if not row["present"]:
                lines.append(f"  {row['name']}: not in the resave")
                continue
            lines.append(
                f"  {row['name']}: pick pockets {row['thief']['after']['thief_pick_pockets']}"
                f", {row['item_count']['after']} items ({len(row['items']['after'])} "
                f"read), encumbrance {row['encumbrance']['after']}, movement "
                f"{row['movement']['after']}; "
                + ("unchanged" if not row["changed"] else
                   "changed: " + ", ".join(row["changed"])))
        for row in s["compare"]:
            if row["before"] is None:
                lines.append(f"  {row['name']} id {row['id']}: new node, "
                             f"{row['after']} minutes")
            elif row["after"] is None:
                lines.append(f"  {row['name']} id {row['id']}: {row['before']} "
                             f"minutes before, no node after")
            else:
                lines.append(f"  {row['name']} id {row['id']}: {row['before']} -> "
                             f"{row['after']} minutes (lost {row['lost']}), data "
                             f"{row['data_before']:02X} -> {row['data_after']:02X}")
        for row in s.get("experience", []):
            if row["gained"]:
                lines.append(f"  {row['name']} experience {row['before']} -> "
                             f"{row['after']} ({row['gained']:+d})")
    for v in result.get("verdicts", []):
        e = v["expect"]
        lines.append(f"expect {e['name']} id {e['id']} at {e['minutes']} minutes: "
                     f"{v['verdict']}" + (f" ({v['why']})" if "why" in v else ""))
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), default="pool")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--save", help="a DOS save folder Wish wrote, a SAVGAM?.DAT "
                                    "(or .PTY and VAULT?.DAT) and its CHRDAT files")
    src.add_argument("--fixture-row", action="append", default=[],
                     metavar="SLOT=ID:OWNER:DURATION:MAGNITUDE",
                     help="hex; stage this effect row into a C64 party and "
                          "convert it with Save As DOS first (repeatable)")
    src.add_argument("--amiga-slot", default=None, metavar="SavGamA.pty",
                     help="darkness: convert this slot of --amiga-disk to DOS "
                          "through the Convert window's route first")
    ap.add_argument("--amiga-disk", default=None,
                    help="with --amiga-slot: an .adf path, or the end of one "
                         "Amiga disk label ('Pools Of Darkness.zip!Pools of "
                         "Darkness3.adf')")
    ap.add_argument("--c64-save", default=None,
                    help="with --fixture-row: the C64 disk to stage into, "
                         "instead of the title's own (C64_BASES)")
    ap.add_argument("--from-slot", default=None,
                    help="with --save: which slot of the folder to install, "
                         "when it holds more than one")
    ap.add_argument("--slot", default="A", help="the letter to install and load as")
    ap.add_argument("--steps", nargs="*", default=[], help=STEP_HELP)
    ap.add_argument("--hall", action="store_true",
                    help="open every school: SAVGAM+0xD51 = 0x00FF before the boot")
    ap.add_argument("--xp", action="append", default=[], metavar="LINE=VALUE",
                    help="stage roster line LINE's experience before the boot")
    ap.add_argument("--add-node", action="append", default=[],
                    metavar="LINE=ID:MINUTES:DATA:FLAG",
                    help="append an effect node to roster line LINE before the boot")
    ap.add_argument("--expect", action="append", default=[],
                    metavar="NAME:ID:MINUTES[:DATA]",
                    help="a node the last saved slot must hold (repeatable)")
    ap.add_argument("--issue", default="661")
    ap.add_argument("--run", default="run", help="the run's name in the evidence path")
    ap.add_argument("--out", default=None,
                    help="evidence directory (default ~/.cache/wish/acceptance/"
                         "<issue>/<sha>-<run>)")
    ap.add_argument("--note", default="dosacceptance")
    args = ap.parse_args(argv)
    try:
        for s in args.steps:
            parse_step(s)
        for e in args.expect:
            parse_expect(e)
        for r in args.fixture_row:
            parse_row(r)
        for x in args.xp:
            parse_xp(x)
        for n in args.add_node:
            parse_node(n)
        validate_steps([parse_step(s) for s in args.steps], args.title)
        if args.hall and args.title not in HALL_TITLES:
            raise ValueError(f"--hall is measured for {', '.join(sorted(HALL_TITLES))} "
                             f"only, not {args.title}")
        if args.fixture_row and args.title == "darkness":
            raise ValueError("--fixture-row converts a C64 party, and Pools of "
                             "Darkness has no C64 port: use --amiga-slot")
        if args.amiga_slot:
            if args.title != "darkness":
                raise ValueError("--amiga-slot converts a Pools of Darkness save: "
                                 "pass --title darkness")
            if not args.amiga_disk:
                raise ValueError("--amiga-slot needs --amiga-disk")
            parse_amiga_slot(args.amiga_slot)
    except ValueError as e:
        ap.error(str(e))
    if not re.fullmatch(r"[A-Ja-j]", args.slot):
        ap.error("--slot is one letter, A to J")
    if args.from_slot and not re.fullmatch(r"[A-Ja-j]", args.from_slot):
        ap.error("--from-slot is one letter, A to J")
    if not re.fullmatch(r"[\w-]+", args.run) or not re.fullmatch(r"[\w-]+", args.issue):
        ap.error("--issue and --run are simple names")
    try:
        return run(args)
    except ValueError as e:
        ap.error(str(e))


if __name__ == "__main__":
    raise SystemExit(main())
