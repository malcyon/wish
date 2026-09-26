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
| `load` | title screens, `LOAD SAVED GAME`, the `--slot` letter; Pool lands on the map, the other three on the party menu.  Pools of Darkness asks `LOAD FROM WHERE? POOLS SECRET EXIT` first and gets `P` |
| `begin` | Curse, Silver Blades and Pools of Darkness: `BEGIN ADVENTURING`, through Silver Blades' intro bars and Pools of Darkness' journal question and `YES NO` bars (below), to the map; Pools of Darkness' map only by its measured bar |
| `camp` | `ENCAMP`; records the camp bar by `bar_signature` |
| `sheet N`, `items N` | Pools of Darkness, in camp: roster line N (from 1) highlighted with `Down`, `VIEW`, the sheet's name checked against line N's, and for `items` its `ITEMS` list page by page with `NEXT`; back to camp |
| `view N` | Pools of Darkness, at the party menu: `VIEW CHARACTER`, line N at `PICK CHARACTER` with `Down`, `SELECT`, the sheet checked as above, every `ITEMS` page, and `EXIT` back to the party menu |
| `sheet N` | Pool: member N's sheet from the map (`End` to the line, `v`, `Escape`); needs the map bar back |
| `display` | Pool camp `MAGIC > DISPLAY`; captures six member rows, then returns through Magic to camp |
| `rest 5m`, `rest 1h30m`, `rest 8d` | camp `REST`, the rest time zeroed and set by key, then rested; minutes in fives; Pool's `GO STAY` random event at the end is answered `GO` (see below) |
| `save X` | in camp, camp `SAVE` to slot X and decline the quit; at the party menu, `SAVE CURRENT GAME`; believed when `SAVGAMX.DAT` changes |
| `train N` | Curse: roster line N (from 1), `TRAIN CHARACTER`, `YES`, and `LEARN` for any spell the level brings, back to the party menu |
| `shot NAME` | one PNG and the screen digests, nothing pressed |
| `press KEY` | one X keysym (`Down`, `Return`, `t`), then a settle and a PNG; capture only, so only `press`, `shot` and `read` may come after it |
| `walk MI`, `walk 1` | Pool: turn around and step one square.  Pools of Darkness: press MOVE, step one square turning right past a wall, and press EXIT back to the map bar.  A step is believed only when the `x,y` on the status line changes (never the clock beside it), a blank line is never the starting reading, and a run with a walk fails unless `read` shows the last saved slot's place differs from the installed one |
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

**The load route is read from the code.**  `LOAD SAVED GAME` (`GAME.OVR`
0x12887) asks `load from where?` over `Pools Secret Exit`: `Pools` is this
title's own `SAVGAM<L>.PTY`, `Secret` a Silver Blades save, `Exit` backs out.
It then lists `load which game: A B C D E F G H I J`, keeping only the letters
whose `SAVGAM<L>.PTY` exists, and loads the one picked.  The menu routine
(0x3A422) takes a word's capital as its key through `UpCase`, so `p` then the
slot letter.  The party menu after a load shows `Train Character` and `Human
Change Classes` only when byte 0x2F of the save's first 1,024 bytes is not
zero (0x14253), which moves `View`, `Save` and `Begin` down two rows.

**Pools of Darkness asks a journal copy-protection question between `Begin
Adventuring` and the map**, and the archives' build passes any answer
(`dospod.answer_journal` has the code).  `dospod.journal_question` knows the
screen by two glyph digests, never by its words; the driver looks for it
before every step and inside `begin`, shoots it, types `x` and `Return`, and
lists it in `events` as `journal`.  Nothing else is ever typed into it: a step
that finds it where it would press `Exit` answers it and stops the run.

**After the journal question the arrival may ask a `YES NO` question**, over
a portrait and story text.  The driver knows the bar by `POD_YES_NO_BAR`, a
`bar_signature` digest of the bar row only, and declines with `N`: the menu
routine keys each word by its first capital and returns at once (the
constants have the offsets).  It does so inside `begin` and before every
step, at most `POD_YES_NO_ROUNDS` in a row, and lists each in `events` as
`yes_no`.  `begin` then calls a screen the map only when its bar is
one of the `POD_MAP_BARS`, each measured from a capture of a real map, and
logs which kind it took (`map_bar` in `run.jsonl`); any other screen stops at
once with a `lost-begin-screen.png`, and anything else after the answer stops
the run in the same way rather than being typed into.  Journal, `YES NO` and
continue screens are counted one screen at a time, at most `POD_INTERSTITIALS`
in `begin`.  A party saved in a town begins at the services bar
`POD_TOWN_BAR`; `begin` shoots it as `town-screen` and stops with
`lost-begin-screen`, pressing nothing, because the driver does not leave a town.
Use the party-menu steps (`load 'view 1' 'save D' read`) for a town party.

**Pools of Darkness picks a character by its roster highlight, read off the
screen.**  The current character's name is the one roster line drawn in
white; `Down` moves it a member on and wraps (`POD_ROSTER_NEXT` has the
code), and `End` does nothing.  The camp's `VIEW` and the party menu's
`PICK CHARACTER` both view the highlighted character.  Each sheet is
believed only when the name cells at its top left carry the same glyphs as
roster line N's (`name_signature`), and a sheet frame two lines share stops
the run.  `ITEMS` is left with `Exit` to the sheet and the sheet with `Exit`
to where `VIEW` was pressed (`GAME.OVR` 0x2452E ends its loop on word 7,
`Exit`, or `Escape`); the driver looks before each `Exit` and never presses
one on the camp bar or the party menu.

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
import signal
import subprocess
import sys
import time
import traceback

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
#: Pool's map command bar and its character sheet's bar `VIEW: TRADE DROP
#: EXIT`, by `bar_signature`, measured on Pool DOS.  On the map `End` moves
#: the roster highlight a member on and wraps; `v` opens the sheet, and
#: `Escape` (never `d`, which the sheet's bar offers as DROP) returns to the
#: map with the highlight where it was.
POOL_MAP_BAR = "809e2e1cc9504b5b"
POOL_SHEET_BAR = "33ad531ed78cfa70"
POOL_ROSTER_NEXT = "End"
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
#: `POOLS` at `LOAD FROM WHERE? POOLS SECRET EXIT` (`GAME.EXE` data 0x2E1B,
#: asked at `GAME.OVR` 0x12901): this title's own `SAVGAM<L>.PTY`.  `S` would
#: read a Silver Blades save instead.
POD_LOAD_FROM = "p"
#: The save byte whose non-zero value puts `Train Character` and `Human Change
#: Classes` on the party menu (`GAME.OVR` 0x14253, read from the first 1,024
#: bytes the load puts at `[0x87F8]`), two rows above `View`.
POD_TRAIN_BYTE = 0x2F
#: A `YES NO` bar with nothing else on the bar row, by `bar_signature`.
#: Measured on the arrival dialog `Begin` led to in run `75e0c741ac-run0-control`
#: of #650 (shots 006 and 007, one screen); none of the 17 other shots of the
#: three runs has it (7 other signatures).  The words are never kept.
POD_YES_NO_BAR = "02af736347597b37"
#: `No` on that bar.  The menu routine (`GAME.OVR` 0x3A422) keys each word by
#: its first character in the set 0-9, A-Z (0x3A220, the set at 0x3A200),
#: puts the key pressed through `UpCase` (0x3A90F), returns the index of the
#: word it keys (0x3A376) and does so at once, without `Return` (0x3A954).
#: The engine's own yes-or-no question (0x3B66D) asks it over `Yes No`
#: (`GAME.EXE` data 0x2B64) and returns 1 for `No`.
POD_DECLINE = "n"
#: `YES NO` bars declined one after another before the run gives up.
POD_YES_NO_ROUNDS = 3
#: A story dialog whose bottom row reads `PRESS BUTTON OR ENTER TO CONTINUE`,
#: by `bar_signature` of that row alone.  Measured on the screen after `No` on
#: the arrival question; the words are never kept.
POD_CONTINUE_BAR = "7a286012361f96ae"
#: What the bar says continues it.
POD_CONTINUE = "Return"
#: Continue screens answered one after another before the run gives up.
POD_CONTINUE_ROUNDS = 5
#: Journal, `YES NO` and continue screens `begin` answers in all, counted one
#: screen at a time, before it gives up, so that no mix of them can loop.
POD_INTERSTITIALS = 12
#: The map command bars, by `bar_signature`, which `begin` accepts as the map
#: after the arrival screens, each measured off a real screen: `dungeon` (the
#: bar `MOVE AREA CAST VIEW ENCAMP SEARCH LOOK`) on the control run
#: `e38a1bb514-run0-control` of #650, and `overland` (`MOVE ENCAMP`) on the
#: Amiga cleric party's run `840311866e-run1-cleric`.  Any other bar stops
#: `begin`; an empty mapping makes it stop at every screen.
POD_MAP_BARS: dict[str, str] = {"dungeon": "0409f26b63f9c492",
                                "overland": "8ce27036e9d49c83"}
#: The town services bar `HEAL TRAIN STORAGE REST MOVE ON`, by `bar_signature`,
#: measured on the Amiga thief party's run `88eac43064-run2-thief` of #650
#: (`lost-begin-screen`, the party saved standing in a town); its glyph
#: signature there was `53b2db87f794e8bb`.  It is not a map.  The destination
#: menu after MOVE ON is bar `151b806b9b9fe327`, unmeasured and deliberately
#: not entered, so no key is ever pressed on this bar.
POD_TOWN_BAR = "f8c32c677c85b2d4"

#: `View` on the map and camp bars; `Items` and `Exit` on the sheet's bar
#: `Items Spells Trade Deposit Drop Lay Cure Exit` (`GAME.EXE` 0xBB4F).  The
#: `ITEMS` list turns its page with `Next` (0xA6AF), the list protocol's `n`.
VIEW = "v"
SHEET_ITEMS = "i"
LEAVE = "e"
ITEMS_NEXT = dosbox.LIST_PAGE_DOWN
#: Pages of `ITEMS` captured before the run gives up on reaching the last.
ITEMS_PAGES = 6

#: Pools of Darkness' roster selector (`GAME.OVR` 0x2680C, far entry `AA:4D`)
#: moves the current character to the next member on scancode 0x50 and to
#: the one before on 0x48, wrapping at both ends, and ignores every other
#: key, `End` (0x4F) included.  The camp loop (0x105F1) and the party menu's
#: `PICK CHARACTER` prompt (0x26E4E) hand it each special key their menu
#: returns; the menu routine (0x3A422) returns an arrow as its scancode, and
#: `2` and `8` as 0x50 and 0x48 through the table at `DS:0x5364`.
POD_ROSTER_NEXT = "Down"
#: The map bar's first word, `Move`, keyed by its capital as every Pools of
#: Darkness bar is.  Until it is pressed the arrows go to the roster
#: selector; pressed, the bar is `EXIT` alone and the arrows move the party.
#: Silver Blades' `dossheetread.walk` does the same; unmeasured in this title.
POD_MOVE = "m"
#: What leaves move mode, `dossheetread`'s `--move-exit` default.
POD_MOVE_EXIT = "Escape"
#: Text column 17, where the status line's text starts; the cell at x 128 is
#: the viewport's frame.
STATUS_TEXT_X = 136
#: `Select`, the only word of the `PICK CHARACTER` prompt (`GAME.EXE` data
#: `DS:0x2859` over `DS:0x2B8D`), keyed by its first letter.  The prompt then
#: views the character the roster highlight is on (`AA:39`, 0x2452E).
POD_PICK = "s"
#: Where the roster's first name is drawn: text column 1 at the party menu
#: and its prompts, 17 in camp, from text row 4, one row per member
#: (0x34825).  The current character's name is drawn in colour 15, white,
#: and every other name in 11, 12, 13 or 14 by its status (0x35AC0), so the
#: one near-white line is the highlight.  Measured on #650's captures: 5 party
#: menus and 7 camp screens, each read with the highlight on line 1.
POD_ROSTER = {"party": (8, 32), "camp": (136, 32)}
#: Where the sheet draws the character's name: text column 1, row 1.  On 5
#: sheets of two parties (#650 runs `88eac43064-run1-cleric` and
#: `840311866e-run0-control`) its signature equals roster line 1's and no
#: other line's.
POD_SHEET_NAME = (8, 8)
#: A name's cells: 15 characters, 7 pixel rows of ink in each.
POD_NAME_CELLS = 15
POD_NAME_ROWS = 7
#: Roster-highlight moves tried per member before `pick_line` gives up.
POD_PICK_ROUNDS = 2


def name_signature(screen: dosbox.Screen, x: int, y: int) -> str:
    """The name drawn at `(x, y)`, one character cell at a time.

    Each cell is `Screen.glyphs` against its own paper, as `bar_signature`
    reads the bar, so the white of the current character and the cyan of
    the others give the same bits for the same letters.
    """
    sha = hashlib.sha1()
    for i in range(POD_NAME_CELLS):
        sha.update(screen.glyphs((x + CELL * i, y, CELL, POD_NAME_ROWS)).encode())
    return sha.hexdigest()[:16]


def status_square(screen: dosbox.Screen) -> str | None:
    """The `x,y` token that opens the status line, or None while it is blank.

    Read cell by cell from `STATUS_TEXT_X` up to the first blank cell, so the
    facing letter and the clock after it never enter the value.
    """
    x0, y, w, h = dosbox.STATUS
    sha = hashlib.sha1()
    cells = 0
    for x in range(STATUS_TEXT_X, x0 + w, CELL):
        cell = (x, y, CELL, h)
        if screen.flat(cell):
            break
        sha.update(screen.glyphs(cell).encode())
        cells += 1
    return sha.hexdigest()[:16] if cells else None


def roster_name(screen: dosbox.Screen, where: str, line: int) -> str:
    """Roster line `line`'s name (from 1), at the party menu or in camp."""
    x, y = POD_ROSTER[where]
    return name_signature(screen, x, y + CELL * (line - 1))


def roster_line(screen: dosbox.Screen, where: str, size: int) -> int | None:
    """The roster line drawn highlighted, from 1, or None if none is."""
    x, y = POD_ROSTER[where]
    row = screen.highlight_row((x, y, CELL * POD_NAME_CELLS, CELL * size))
    return None if row is None else row + 1


def sheet_name(screen: dosbox.Screen) -> str:
    """The name on a character sheet, comparable with `roster_name`."""
    return name_signature(screen, *POD_SHEET_NAME)


#: The signature of fifteen empty cells: a roster line with nobody on it.
BLANK_NAME = hashlib.sha1(
    dosbox.Screen(CELL, POD_NAME_ROWS, bytes(CELL * POD_NAME_ROWS * 3)).glyphs().encode()
    * POD_NAME_CELLS).hexdigest()[:16]
#: The walk each title drives: Pool's turn-around, Pools of Darkness' step.
WALKS = {"pool": "MI", "darkness": "1"}


def pod_menu_after(savgam: bytes | None) -> dict[str, int]:
    """The party menu's `view`, `save` and `begin` rows after loading `savgam`.

    With a party loaded the enabled entries are, in order, Create, Drop,
    Modify, [Train, Human Change], View, Add, Remove, Save, Begin, Exit; the
    bracketed two only when `POD_TRAIN_BYTE` is set.  A missing save gives
    the rows without them.
    """
    shift = 2 if savgam and len(savgam) > POD_TRAIN_BYTE and savgam[POD_TRAIN_BYTE] else 0
    return {k: v + shift for k, v in POD_MENU_AFTER.items()}


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


class DeadlineReached(TimeoutError):
    """The run's route window is over; what is left belongs to the cleanup."""


class Terminated(RuntimeError):
    """The wrapper's `timeout` sent SIGTERM."""


#: The run's whole budget, and the part of it kept for the cleanup (the
#: failure capture, the shots and the resave copied out, the emulator stopped).
#: The wrapper's own `timeout` is a backstop at least `WRAPPER_MARGIN` seconds
#: longer than the deadline, so the driver, not the wrapper, ends the run.
DEADLINE_SECONDS = 900.0
CLEANUP_SECONDS = 120.0
WRAPPER_MARGIN = 300.0
#: The longest one capture or key press takes, with room to spare: a wait with
#: less than this left does not start another.
ACTION_SECONDS = 5.0


class Deadline:
    """The route window of a run: `seconds` from the start less `cleanup`.

    The cleanup is never more than half the budget.  `clock` is injectable so
    a test can pass the deadline without waiting.
    """

    def __init__(self, clock, seconds: float, cleanup: float = CLEANUP_SECONDS):
        self.clock, self.seconds = clock, float(seconds)
        self.cleanup = min(float(cleanup), self.seconds / 2)
        self.begun = clock()
        self.route_end = self.begun + self.seconds - self.cleanup

    def left(self) -> float:
        return self.route_end - self.clock()

    def check(self, label: str) -> None:
        """Stop the route when less than one action's time is left."""
        if self.left() < ACTION_SECONDS:
            raise DeadlineReached(
                f"the route window of {self.seconds - self.cleanup:.0f} s is over "
                f"during {label} (the deadline is {self.seconds:.0f} s, "
                f"{self.cleanup:.0f} s of it for the cleanup)")

    def bound(self, wait: float, label: str) -> float:
        """`wait`, cut to the route time left; never a remainder shorter than an action."""
        self.check(label)
        return min(wait, self.left())


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
             "'train 1', 'sheet 1', 'items 1', 'view 1', 'shot NAME', 'press KEY', "
             "read")


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
    if kind in ("train", "sheet", "items", "view") and len(words) == 2 and re.fullmatch(
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
        elif k == "sheet" and title == "pool":
            if where != "map":
                raise ValueError(f"sheet needs the loaded map: {step.text!r}")
        elif k in ("sheet", "items"):
            if title != "darkness":
                raise ValueError(f"{k} is driven in darkness only, not {title}")
            if where != "camp":
                raise ValueError(f"{k} needs camp first: {step.text!r}")
        elif k == "view":
            if title != "darkness":
                raise ValueError(f"view is driven in darkness only, not {title}")
            if where != "party":
                raise ValueError(f"view needs the party menu, before begin: "
                                 f"{step.text!r}")
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
                 party_size: int = 6, deadline: Deadline | None = None):
        self.s = session
        #: The run's route window, or None: nothing then limits a wait.
        self.deadline = deadline
        #: Why the last failure capture failed, or None.
        self.capture_error: str | None = None
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
        #: Pools of Darkness' party-menu rows once a save is loaded.
        self.pod_rows = dict(POD_MENU_AFTER)
        #: Each roster line's sheet digest, once shown: two lines must never
        #: show the same sheet.
        self.sheets: dict[int, str] = {}

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
        """The failure `why`, with a shot of the screen it happened at.

        The capture cannot raise: one that fails is recorded beside the reason
        and never replaces it.
        """
        try:
            name = self.shot(f"lost-{label}")
        except Exception as e:  # noqa: BLE001 -- the reason is what must survive
            self.capture_error = f"{type(e).__name__}: {e}"
            try:
                self.note(event="failure_capture_error", label=label,
                          error=self.capture_error)
            except Exception:  # noqa: BLE001
                pass
            return StepFailed(f"{why}; no failure capture ({self.capture_error})")
        return StepFailed(f"{why}; see {name}.png")

    def check_deadline(self, label: str) -> None:
        if self.deadline is not None:
            self.deadline.check(label)

    def bounded(self, wait: float, label: str) -> float:
        """`wait`, cut to what the route window has left."""
        if self.deadline is None:
            return wait
        return self.deadline.bound(wait, label)

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
            self.check_deadline("wait-camp")
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
            self.check_deadline(label)
            time.sleep(0.3)
        dosbox.settle_files(self.s.save_dir, quiet=1.0,
                            timeout=self.bounded(30.0, label))

    def after_rest(self, timeout: float, in_step: str) -> None:
        """Wait out a rest: the camp bar, or Pool's `GO STAY` answered with GO.

        Nothing but `GO` is ever pressed at the event.  A third event, any
        screen that is neither the camp bar, the event nor (after an event)
        the map, or a text window that stops changing for `REST_STALL`
        seconds away from the camp bar, ends the run.
        """
        answered = 0
        while True:
            deadline = time.time() + self.bounded(timeout, "rest-end")
            screen = None
            last_text, changed = None, time.time()
            while time.time() < deadline:
                self.check_deadline("rest-end")
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

    def journal(self, label: str) -> bool:
        """Answer Pools of Darkness' journal question if it is showing.

        Shot first, answered by `dospod.answer_journal`, and listed in the
        summary's `events` as `journal`.  A question still showing after its
        answers stops the run with a `lost-journal-*.png`.  Other titles, and
        any other screen, get nothing pressed.
        """
        if self.title.key != "darkness" or not dospod.journal_question(self.s.capture()):
            return False
        shot = self.shot(f"journal-{label}")
        try:
            dospod.answer_journal(self.s)
        except TimeoutError as e:
            raise self.fail(f"journal-{label}", str(e)) from None
        event = {"kind": "journal", "step": label, "shot": f"{shot}.png",
                 "answered": dospod.JOURNAL_ANSWER.upper()}
        self.events.append(event)
        self.note(event="question", **event)
        return True

    def yes_no(self, label: str, limit: int | None = None) -> int:
        """Decline every Pools of Darkness `YES NO` bar showing, in turn.

        Each is shot, gets `POD_DECLINE` (pressed a second time only if the
        text window did not change), is waited out, and is listed in `events` as
        `yes_no`.  A bar still showing after `POD_YES_NO_ROUNDS` (or `limit`),
        or one `N` does not change, stops the run; a second `N` goes out only if
        the same bar and text are still showing when the first has had its 10
        seconds.  `Y` is never pressed.  Other titles get nothing pressed.  Returns how many were declined.
        """
        if self.title.key != "darkness":
            return 0
        declined = 0
        cap = POD_YES_NO_ROUNDS if limit is None else min(POD_YES_NO_ROUNDS, limit)
        while bar_signature(self.s.capture()) == POD_YES_NO_BAR:
            if declined >= cap:
                if cap < POD_YES_NO_ROUNDS:
                    raise self.fail("begin-interstitials", f"a YES NO bar is "
                                    f"showing after {POD_INTERSTITIALS} screens "
                                    "were answered")
                raise self.fail(f"yes-no-{label}", f"a YES NO bar is still showing "
                                f"after {declined} were declined")
            shot = self.shot(f"yes-no-{label}")
            # The text window and bar, not the whole frame, which a portrait
            # may animate.  The next question's text differs from this one's
            # even where its bar and highlight are the same.
            before = self.s.capture().digest(TEXT_WINDOW)
            for attempt in range(2):
                if attempt:
                    # A slow redraw must not get a second `N` it was not
                    # meant for: it would decline the next dialog unseen, or
                    # land on the map as a command key.
                    now = self.s.capture()
                    if (bar_signature(now) != POD_YES_NO_BAR
                            or now.digest(TEXT_WINDOW) != before):
                        break
                self.s.key(POD_DECLINE)
                if self.s.wait_for(lambda sc: sc.digest(TEXT_WINDOW) != before, 10.0):
                    break
            else:
                raise self.fail(f"yes-no-{label}", "NO changed nothing on the "
                                "YES NO bar")
            self.s.settle(quiet=1.0, timeout=60.0)
            event = {"kind": "yes_no", "step": label, "shot": f"{shot}.png",
                     "bar": POD_YES_NO_BAR, "answered": POD_DECLINE.upper()}
            self.events.append(event)
            self.note(event="question", **event)
            declined += 1
        return declined

    def press_continue(self, label: str, limit: int | None = None) -> int:
        """Continue past every Pools of Darkness story dialog showing, in turn.

        Each is shot, gets `POD_CONTINUE`, is waited out, and is listed in
        `events` as `press_continue`.  A sixth in a row, `limit` of them, or one
        `Return` does not change, stops the run.  A second `Return` goes out
        only if the same screen is still showing when the first has had its 10
        seconds; anything else is left to the caller's loop.  Other titles get
        nothing pressed.  Returns how many were answered.
        """
        if self.title.key != "darkness":
            return 0
        answered = 0
        cap = POD_CONTINUE_ROUNDS if limit is None else min(POD_CONTINUE_ROUNDS, limit)
        while bar_signature(self.s.capture()) == POD_CONTINUE_BAR:
            if answered >= cap:
                if cap < POD_CONTINUE_ROUNDS:
                    raise self.fail("begin-interstitials", f"a continue screen "
                                    f"is showing after {POD_INTERSTITIALS} "
                                    "screens were answered")
                raise self.fail(f"continue-{label}", f"a continue screen is still "
                                f"showing after {answered} were answered")
            shot = self.shot(f"continue-{label}")
            before = self.s.capture().digest(TEXT_WINDOW)
            for attempt in range(2):
                if attempt:
                    # A slow redraw, or a next screen whose text window has
                    # the same digest, must not get a key it was not meant for.
                    now = self.s.capture()
                    if (bar_signature(now) != POD_CONTINUE_BAR
                            or now.digest(TEXT_WINDOW) != before):
                        break
                self.s.key(POD_CONTINUE)
                if self.s.wait_for(lambda sc: sc.digest(TEXT_WINDOW) != before, 10.0):
                    break
            else:
                raise self.fail(f"continue-{label}", "Return changed nothing on "
                                "the continue screen")
            self.s.settle(quiet=1.0, timeout=60.0)
            event = {"kind": "press_continue", "step": label, "shot": f"{shot}.png",
                     "bar": POD_CONTINUE_BAR, "answered": POD_CONTINUE}
            self.events.append(event)
            self.note(event="question", **event)
            answered += 1
        return answered

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
        """Past the titles to the party menu, `Load Saved Game`, then `POOLS`
        at `LOAD FROM WHERE?` and the slot letter, each pressed once and given
        30 seconds, so a key meant for one screen never lands on the next."""
        path = self.save_path(self.slot)
        self.pod_rows = pod_menu_after(path.read_bytes() if path.is_file() else None)
        answered = dospod.to_party_menu(self.s)
        self.shot("menu")
        self.pod_menu(POD_LOAD_ROW, "load")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-from")
        if not self.press_screen_changes(POD_LOAD_FROM, tries=1, wait=30.0):
            raise self.fail("load-from", "POOLS at LOAD FROM WHERE? did not "
                            "open the slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.s.settle(quiet=1.0, timeout=90.0)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig,
                "questions_answered": len(answered), "menu_rows": self.pod_rows}

    def begin(self) -> dict:
        if self.where != "party":
            raise StepFailed("begin needs the party menu")
        if self.title.key == "ssb":
            self.ssb.menu(ssbimport.MENU_AFTER["begin"], "begin")
            self.ssb.intro()
        elif self.title.key == "darkness":
            self.pod_menu(self.pod_rows["begin"], "begin")
        elif not self.press_screen_changes(PARTY_BEGIN, tries=1, wait=30.0):
            raise self.fail("begin", "BEGIN ADVENTURING did not leave the party menu")
        screen = self.s.settle(quiet=1.0, timeout=60.0)
        # Pools of Darkness asks its journal question between the party menu
        # and the map, every time the party begins, and its arrival may ask a
        # YES NO question after that.
        answered = 0

        def interstitials(screen):
            nonlocal answered
            while True:
                # The bound is on screens, so each helper gets what is left of it.
                if POD_INTERSTITIALS > answered:
                    got = int(self.journal("begin"))
                else:
                    got = 0
                got += self.yes_no("begin", POD_INTERSTITIALS - answered - got)
                got += self.press_continue("begin", POD_INTERSTITIALS - answered - got)
                if not got:
                    return screen
                answered += got
                screen = self.s.settle(quiet=1.0, timeout=60.0)

        screen = interstitials(screen)
        if (self.title.key == "darkness"
                and bar_signature(screen) == POD_TOWN_BAR):
            # The destination menu behind MOVE ON is unmeasured, so a town
            # start is recognised and stopped at, with nothing pressed.
            self.shot("town-screen")
            raise self.fail("begin-screen", "the party starts in a town "
                            "services screen, which this driver does not "
                            "leave; use the party-menu steps "
                            "(load 'view 1' 'save D' read) for a town party")
        if self.on_party_menu(screen):
            raise self.fail("begin", "the party menu is still showing")
        kind = None
        if self.title.key == "darkness":
            kind = next((k for k, bar in POD_MAP_BARS.items()
                         if bar_signature(screen) == bar), None)
            if kind is None:
                if not POD_MAP_BARS:
                    raise self.fail("begin-screen", "no Pools of Darkness map bar "
                                    "has been measured yet (POD_MAP_BARS), so the "
                                    "screen Begin reached is not taken for the map")
                raise self.fail("begin-screen", "the screen Begin reached is not "
                                "a measured map bar of POD_MAP_BARS (a story "
                                "screen or a message this driver does not know)")
            self.note(event="map_bar", map=kind, bar=POD_MAP_BARS[kind])
        self.record_world(screen)
        self.shot("map")
        self.where = "map"
        return {"map_bar": self.world_sig, "map_kind": kind}

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

    def map_status(self, label: str, screens: list[dict]) -> tuple[str, str | None]:
        """The settled map's status line and its `x,y` square, with a shot,
        appended to `screens`; a screen that is not the map stops the run."""
        screen = self.s.settle(quiet=0.6, timeout=30.0)
        if not self.on_world(screen):
            raise self.fail(label, "the map bar did not return (combat or "
                            "an unknown screen)")
        status = self.game.status()
        square = status_square(screen)
        screens.append({"shot": self.shot(label), "bar": bar_signature(screen),
                        "status": status, "square": square})
        return status, square

    def walk(self, route: str) -> dict:
        """From the loaded Pool map, turn around and step one square.

        A step is believed only when the `x,y` on the status line changes:
        the clock on the same line ticks on a wall's bump, and a line drawn
        for the first time differs from a blank one, so the whole strip says
        nothing about a step.  A blank line is never the starting reading.
        """
        if self.title.key == "darkness" and self.where == "map" and route == "1":
            return self._walk_one()
        if self.title.key != "pool" or self.where != "map" or route != "MI":
            raise StepFailed("walk MI needs Pool's loaded map")

        screens: list[dict] = []

        def record(label: str) -> tuple[str, str | None]:
            return self.map_status(label, screens)

        before, origin = record("walk-before")
        if origin is None:
            raise self.fail("walk-status", "the status line is blank on the map, "
                            "so there is no starting square (a shop or an "
                            "arrival draws it later)")
        for n in (1, 2):
            if not self.game.turn_right():
                raise self.fail(f"walk-turn-{n}", "the map bar did not return "
                                "after turning (combat or an unknown screen)")
            _, square = record(f"walk-turn-{n}")
            if square != origin:
                raise self.fail(f"walk-turn-{n}", "the square changed on a turn "
                                "(or the status line went blank)")
        if not self.game.step():
            raise self.fail("walk-step", "the map bar did not return after the "
                            "step (combat or an unknown screen)")
        after, square = record("walk-step")
        if square is None:
            raise self.fail("walk-status", "the status line was blank after the step")
        if square == origin:
            raise self.fail("walk-blocked", "the settled status did not change "
                            "after Up: the x,y square is the same (a blocked "
                            "step; a clock tick is not a step)")
        return {"route": route, "map_bar": self.world_sig,
                "status_before": before, "status_after": after,
                "square_before": origin, "square_after": square,
                "screens": screens}

    def _walk_one(self) -> dict:
        """Press MOVE, step one square forward, and press EXIT back to the map.

        The party is already facing as it was saved, so the first try is
        `Up`; past a wall it turns right and tries again, three turns at most.
        A step is believed only when the `x,y` on the status line changes,
        and a key that moved the roster highlight instead stops the run.
        """
        screens: list[dict] = []
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("walk-before", "the map bar is not showing")
        line = roster_line(map_screen, "camp", self.party_size)
        if line is None:
            raise self.fail("walk-roster", "no highlighted roster line on the "
                            "map to tell a roster move from a step")
        map_bar = self.world_sig
        try:
            self.s.key(POD_MOVE)
            if not self.s.wait_while_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{POD_MOVE} (no move mode)")
            settled = self.s.settle(quiet=0.6, timeout=30.0)
            if bar_signature(settled) == self.world_sig:
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{POD_MOVE} (no move mode)")
            move_bar = bar_signature(settled)
            self.game.record_map(settled)
            origin = status_square(settled)
            screens.append({"shot": self.shot("walk-move"), "bar": move_bar,
                            "square": origin})

            def settle(label: str) -> str | None:
                screen = self.s.settle(quiet=0.6, timeout=30.0)
                if bar_signature(screen) != move_bar:
                    raise self.fail(label, "the move bar did not return (combat "
                                    "or an unknown screen)")
                if roster_line(screen, "camp", self.party_size) != line:
                    raise self.fail("walk-roster", "the roster highlight moved: "
                                    "the key went to the roster selector")
                square = status_square(screen)
                screens.append({"shot": self.shot(label), "bar": move_bar,
                                "square": square})
                return square

            if origin is None:
                # Move mode draws no status line on entry; the first turn
                # does, and four turns bring the party back to its facing.
                for n in range(1, 5):
                    label = f"walk-circle-{n}"
                    if not self.game.turn_right():
                        raise self.fail(label, "the move bar did not return "
                                        "after turning")
                    square = settle(label)
                    if square is None:
                        raise self.fail("walk-status", "the status line stayed "
                                        "blank after a turn")
                    if origin is None:
                        origin = square
                    elif square != origin:
                        raise self.fail(label, "the square changed on a turn")

            turns = 0
            for attempt in range(4):
                label = f"walk-step-{attempt + 1}"
                if not self.game.step():
                    raise self.fail(label, "the move bar did not return after "
                                    "the step (combat or an unknown screen)")
                square = settle(label)
                if square is None:
                    raise self.fail("walk-status", "the status line was blank "
                                    "after the step")
                if square != origin:
                    break
                if attempt == 3:
                    raise self.fail("walk-blocked", "no facing let the party "
                                    "step (the square never changed)")
                label = f"walk-turn-{attempt + 1}"
                if not self.game.turn_right():
                    raise self.fail(label, "the move bar did not return after "
                                    "turning")
                if settle(label) != origin:
                    raise self.fail(label, "the square changed on a turn")
                turns += 1
            if bar_signature(self.s.capture()) != move_bar:
                raise self.fail("walk-back", "not at the move bar to leave it")
            self.s.key(POD_MOVE_EXIT)
            if not self.s.wait_until_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-back", f"{POD_MOVE_EXIT} did not return "
                                "to the map bar")
            back = self.s.settle(quiet=0.6, timeout=30.0)
            screens.append({"shot": self.shot("walk-back"),
                            "bar": bar_signature(back)})
            return {"route": "1", "map_bar": map_bar, "move_bar": move_bar,
                    "turns": turns, "square_before": origin,
                    "square_after": square,
                    "status_before": map_screen.ink(dosbox.STATUS),
                    "status_after": back.ink(dosbox.STATUS),
                    "roster_line": line, "screens": screens}
        finally:
            self.game.record_map(map_screen)

    def pick_line(self, line: int, where: str, label: str,
                  next_key: str = POD_ROSTER_NEXT) -> dict:
        """Move Pools of Darkness' roster highlight onto line `line`, from 1.

        Read, never counted: the highlight is the white roster line
        (`roster_line`), and `POD_ROSTER_NEXT` moves it one member on and
        wraps.  A press is believed only when the white line moves; a
        whole-frame digest is not enough, because the camp picture animates
        by itself.  Two presses in a row that leave it where it was, or more
        than `POD_PICK_ROUNDS` presses a member, stop the run.
        """
        size = self.party_size
        if not 1 <= line <= size:
            raise StepFailed(f"line {line} is not in a party of {size}")
        here = roster_line(self.s.capture(), where, size)
        if here is None:
            raise self.fail(label, "no roster line is drawn highlighted")
        presses = still = 0
        while here != line:
            if presses >= POD_PICK_ROUNDS * size:
                raise self.fail(label, f"{presses} presses of {POD_ROSTER_NEXT} "
                                f"never brought the highlight to line {line}")
            self.s.key(next_key)
            presses += 1
            was = here
            self.s.wait_for(lambda sc, was=was: roster_line(sc, where, size) != was,
                            5.0)
            here = roster_line(self.s.capture(), where, size)
            if here is None:
                raise self.fail(label, "the roster highlight went away")
            still = still + 1 if here == was else 0
            if still >= 2:
                raise self.fail(label, f"{next_key} did not move the "
                                f"roster highlight off line {here}")
        self.line = line
        return {"presses": presses}

    def check_sheet(self, screen, line: int, want: str, label: str) -> dict:
        """The sheet on `screen` is roster line `line`'s: its name cells match
        the roster's, and no other line's sheet has had this frame."""
        if want == BLANK_NAME:
            raise self.fail(label, f"roster line {line} has no name drawn")
        got = sheet_name(screen)
        if got != want:
            raise self.fail(label, f"the sheet's name is not roster line {line}'s "
                            f"(sheet {got}, roster {want})")
        digest = screen.digest()
        other = next((n for n, d in self.sheets.items() if d == digest and n != line),
                     None)
        if other is not None:
            raise self.fail(label, f"line {line}'s sheet is the same frame as "
                            f"line {other}'s")
        self.sheets[line] = digest
        return {"name": want, "digest": digest, "sheet_bar": bar_signature(screen)}

    def open_sheet(self, line: int) -> dict:
        """Camp: roster line `line` highlighted, `VIEW`, and the sheet checked."""
        if self.title.key != "darkness" or self.camp_sig is None:
            raise StepFailed("sheet and items need Pools of Darkness' camp first")
        self.ensure_camp()
        moved = self.pick_line(line, "camp", f"select-{line}")
        want = roster_name(self.s.capture(), "camp", line)
        self.shot(f"line-{line}")
        # `V` is keyed by nothing on the sheet's bar, so a second one is inert.
        for _ in range(2):
            self.s.key(VIEW)
            if self.s.wait_for(lambda sc: not self.in_camp(sc), 15.0):
                break
        else:
            raise self.fail(f"sheet-{line}", "the camp bar is still showing "
                            "after VIEW")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"sheet-{line}-name")
        return {"line": line, **moved, "sheet": self.shot(f"sheet-{line}"),
                **checked}

    def item_pages(self, label: str) -> list[dict]:
        """From a sheet: `ITEMS`, then every page shot, turning with `Next`
        until it changes nothing or brings back the first page;
        `ITEMS_PAGES` pages that are all different stop the run."""
        if not self.press_screen_changes(SHEET_ITEMS, tries=1, wait=15.0):
            raise self.fail(label, "ITEMS changed nothing on the sheet (the "
                            "sheet offers ITEMS only to a character carrying "
                            "something, GAME.OVR 0x245D6)")
        pages: list[dict] = []
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        first = screen.digest()
        while True:
            pages.append({"shot": self.shot(f"{label}-{len(pages) + 1}"),
                          "bar": bar_signature(screen), "digest": screen.digest()})
            if len(pages) >= ITEMS_PAGES:
                raise self.fail(f"{label}-pages", f"{ITEMS_PAGES} pages and "
                                "Next still turns another")
            before = screen.digest()
            self.s.key(ITEMS_NEXT)
            if not self.s.wait_for(lambda sc: sc.digest() != before, 5.0):
                break
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            if screen.digest() == first:
                break
        return pages

    def back_to_party(self, label: str, tries: int = 3) -> None:
        """`Exit` until the party menu is back, looking before every press,
        so that no `E` ever lands on the party menu itself."""
        for _ in range(tries):
            if self.on_party_menu(self.s.settle(quiet=0.6, timeout=20.0)):
                return
            self.s.key(LEAVE)
        if not self.wait_party_menu(15.0):
            raise self.fail(label, f"the party menu never came back after "
                            f"{tries} presses of Exit")

    def view(self, line: int) -> dict:
        """Party menu `View Character`, roster line `line`, its sheet and its
        `ITEMS` pages, and back to the party menu.

        `View` opens `PICK CHARACTER` over the roster (`GAME.OVR` 0x14536 via
        0x26E25); `Down` moves the highlight a member on and `S` views that
        character (0x2452E), whose `Exit` returns to the party menu.  Nothing
        else is pressed, and nothing here writes a file.
        """
        if self.title.key != "darkness" or self.where != "party":
            raise StepFailed("view is Pools of Darkness' party-menu command")
        if self.party_sig is None:
            raise StepFailed("view needs the party menu learnt by load")
        self.pod_menu(self.pod_rows["view"], f"view-{line}")
        screen = self.s.settle(quiet=0.6, timeout=20.0)
        if self.on_party_menu(screen):
            raise self.fail(f"pick-{line}", "View Character left the party menu "
                            "showing")
        if roster_line(screen, "party", self.party_size) is None:
            raise self.fail(f"pick-{line}", "View Character did not open a roster "
                            "with a highlighted line (PICK CHARACTER)")
        pick = self.shot(f"pick-{line}")
        moved = self.pick_line(line, "party", f"pick-{line}-select")
        want = roster_name(self.s.capture(), "party", line)
        self.shot(f"view-line-{line}")
        # A second `S` goes out only if the first changed nothing in its 15
        # seconds, since the first key after a redraw can be dropped; on a
        # sheet it would open SPELLS, which the name check below stops at.
        if not self.press_screen_changes(POD_PICK, tries=2, wait=15.0):
            raise self.fail(f"view-{line}", "SELECT at PICK CHARACTER changed nothing")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"view-{line}-name")
        sheet = self.shot(f"view-{line}-sheet")
        pages = self.item_pages(f"view-{line}-items")
        self.back_to_party(f"view-{line}-back")
        self.shot(f"view-{line}-back")
        return {"line": line, "pick": pick, **moved, "sheet": sheet, **checked,
                "pages": pages}

    def back_to_camp(self, label: str, tries: int = 3) -> None:
        """`Exit` until the camp bar is back, looking before every press:
        `Exit` on the camp bar itself breaks camp, and on the journal
        question it would be typed as an answer."""
        for _ in range(tries):
            if self.in_camp(self.s.settle(quiet=0.6, timeout=20.0)):
                return
            if self.journal(label):
                raise self.fail(label, "the journal question interrupted the "
                                "step and was answered; the party is out of camp")
            self.s.key(LEAVE)
        if not self.wait_camp(timeout=15.0):
            raise self.fail(label, f"the camp bar never came back after "
                            f"{tries} presses of Exit")

    def pool_sheet(self, line: int) -> dict:
        """Pool: roster line `line`'s sheet from the map, shot, and back on the
        map bar.  Only `End`, `v` and `Escape` are pressed, and the highlight
        is read on the map alone, where `roster_line` is right."""
        if self.title.key != "pool" or self.where != "map":
            raise StepFailed("sheet needs Pool's loaded map")
        if bar_signature(self.s.capture()) != POOL_MAP_BAR:
            raise self.fail(f"sheet-{line}-map", "the map bar is not showing")
        moved = self.pick_line(line, "camp", f"sheet-{line}-select", POOL_ROSTER_NEXT)
        want = roster_name(self.s.capture(), "camp", line)
        self.s.key(VIEW)
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POOL_SHEET_BAR, 15.0):
            raise self.fail(f"sheet-{line}-open", "VIEW did not open the sheet bar")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"sheet-{line}-name")
        sheet = self.shot(f"sheet-{line}")
        self.s.key("Escape")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == POOL_MAP_BAR, 15.0):
            raise self.fail(f"sheet-{line}-back", "the map bar did not return "
                            "after Escape")
        back = self.s.capture()
        if roster_line(back, "camp", self.party_size) != line:
            raise self.fail(f"sheet-{line}-back", "the highlight is not on the "
                            "member the sheet showed")
        self.shot(f"sheet-{line}-back")
        return {"line": line, **moved, "sheet": sheet, **checked}

    def sheet(self, line: int) -> dict:
        """Roster line `line`'s sheet from camp, shot, and back to camp."""
        if self.title.key == "pool":
            return self.pool_sheet(line)
        got = self.open_sheet(line)
        self.back_to_camp(f"sheet-{line}-back")
        return got

    def items(self, line: int) -> dict:
        """Roster line `line`'s `ITEMS` from its sheet, every page shot.

        `Next` is pressed until it changes nothing or brings back the first
        page; `ITEMS_PAGES` pages that are all different stop the run.
        """
        got = self.open_sheet(line)
        pages = self.item_pages(f"items-{line}")
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
            self.pod_menu(self.pod_rows["save"], "save")
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


def run(args, clock=time.monotonic) -> int:
    """`_run`, with the evidence log closed on every way out, including an early raise.

    The wrapper's SIGTERM is turned into `Terminated` for the length of the
    run, so the evidence is kept where the default action would end the
    process without it.  A second signal is ignored: the cleanup is what the
    first one asked for.
    """
    def on_term(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise Terminated(f"signal {signum}")

    try:
        previous = signal.signal(signal.SIGTERM, on_term)
    except ValueError:      # not the main thread: nothing to install
        previous = None
    try:
        with contextlib.ExitStack() as outer:
            return _run(args, outer, clock)
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _run(args, outer: contextlib.ExitStack, clock=time.monotonic) -> int:
    deadline = Deadline(clock, getattr(args, "deadline", None) or DEADLINE_SECONDS)
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
        summary["elapsed_seconds"] = round(clock() - deadline.begun, 1)
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
            d = Driver(session, note, letter, args.title, party_size=size,
                       deadline=deadline)
            summary["events"] = getattr(d, "events", [])
            results = []
            for step in steps:
                deadline.check(step.text)
                note(event="step", step=step.text)
                # Before every step but a capture of what `press` left.
                if d.where != "pressed":
                    d.journal(re.sub(r"\W+", "-", step.text))
                    d.yes_no(re.sub(r"\W+", "-", step.text))
                    d.press_continue(re.sub(r"\W+", "-", step.text))
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
                elif step.kind == "view":
                    r = d.view(step.line)
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
            unproved = walk_verdict(steps, summary.get("read"))
            if unproved:
                summary["lost"] = unproved
                note(event="lost", why=unproved)
            else:
                summary["completed"] = True
        except (StepFailed, ssbimport.RouteLost) as e:
            summary["lost"] = str(e)
            note(event="lost", why=str(e))
        except (TimeoutError, dosbox.DosboxUnavailable, dosbox.BlankCapture,
                Terminated) as e:
            why = f"{type(e).__name__}: {e}"
            if isinstance(e, Terminated):
                why = f"Terminated({str(e)!r})"
            if d is not None:
                why = str(d.fail("timeout", why))
            summary["lost"] = why
            note(event="lost", why=why)
        except Exception as e:  # noqa: BLE001 -- a harness crash still ends with `lost`
            traceback.print_exc()
            why = f"{type(e).__name__}: {e}"
            if d is not None:
                why = str(d.fail("error", why))
            summary["lost"] = why
            note(event="lost", why=why)
        if d is not None and getattr(d, "capture_error", None):
            summary["failure_capture_error"] = d.capture_error
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


def place_changed(before: dict, after: dict) -> bool:
    """Whether the square or the map differs between two slots' places."""
    a, b = before.get("place") or {}, after.get("place") or {}
    keys = ("x", "y", "area") if "area" in a else ("x", "y", "dungeon_map")
    return any(a.get(k) != b.get(k) for k in keys)


def walk_verdict(steps: list[Step], read: dict | None) -> str | None:
    """Why a run that asked for a walk has not shown one, or None.

    The proof is the place decoded from the game-written save, the same in
    every title: the last save the run made must not be at the square the
    installed one was.  A place that was not computed proves nothing.
    """
    if not any(s.kind == "walk" for s in steps):
        return None
    if read is None:
        return ("a walk was asked and no read step decoded a saved place, so "
                "nothing shows the party moved")
    slots = read.get("slots") or {}
    order = [x for x in read.get("saved") or [] if x in slots] or list(slots)
    if not order:
        return "a walk was asked and no saved slot was read, so nothing shows the party moved"
    last = order[-1]
    slot = slots[last]
    if "place_changed" not in slot or "x" not in (slot.get("place") or {}):
        return (f"a walk was asked and slot {last}'s place was not computed "
                f"({(slot.get('place') or {}).get('error', 'no place read')})")
    if not slot["place_changed"]:
        return (f"the walk did not move the party: the game-written slot {last} "
                "is at the square the installed slot was")
    return None


def read_step(save_dir: pathlib.Path, out: pathlib.Path, letter: str,
              saved: list[str], steps: list[Step], expects: list[Expect]) -> dict:
    """Copy `SAVE/` out and decode the installed slot against each saved one."""
    resave = out / "resave"
    shutil.rmtree(resave, ignore_errors=True)
    shutil.copytree(save_dir, resave)
    before = read_slot(out / "installed", letter)
    asked = sum(s.minutes for s in steps if s.kind == "rest")
    result: dict = {"installed": before, "rested_minutes": asked, "slots": {},
                    "saved": list(saved)}
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
        if any(st.kind == "walk" for st in steps):
            result["slots"][x]["place_changed"] = place_changed(before, after)
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
        if "place_changed" in s:
            was = (result.get("installed") or {}).get("place") or {}
            lines.append(f"  moved from {was.get('x')},{was.get('y')} to "
                         f"{place.get('x')},{place.get('y')}"
                         if s["place_changed"] else "  did not move")
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
    ap.add_argument("--deadline", type=float, default=DEADLINE_SECONDS,
                    help=f"seconds the whole run may take, {CLEANUP_SECONDS:.0f} "
                         "of them kept for the cleanup; wrap the command in "
                         f"`timeout` at least {WRAPPER_MARGIN:.0f} s longer")
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
