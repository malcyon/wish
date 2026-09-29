#!/usr/bin/env python3
"""Load a Wish-written DOS save in the running game, act, and read the engine's resave.

The DOS driver of `docs/235-destination-game-acceptance-runs.md` (D1), for
DOS Pool of Radiance, Curse of the Azure Bonds, Secret of the Silver Blades
and Pools of Darkness.  It stages a whole save this project wrote the way
`dossheetread.install_whole` does, boots DOSBox headless and silent on a
pooled slot, runs a step list, and decodes what the engine wrote back:

    tools/dos/acceptance.py --title pool --save DIR --slot A \\
        --steps load camp 'rest 5m' 'save D' read \\
        --expect BRUTUS:1:42:1 --issue 661 --run bless

    tools/dos/acceptance.py --title curse --fixture-row 3F=01:00:2F:05 \\
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

    tools/dos/acceptance.py --title darkness \\
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

`--convert PATH [--convert-slot L]` replaces `--save` for pool, curse and ssb:
a C64 `.D64` or Amiga `.adf` at `PATH`, whatever title or port it is (a C64
save, or an Amiga Curse, Silver Blades or Pool of Radiance one), is read at
slot `L` (default `A`) through `editor.convert.Source.detect` and converted by
Save As DOS the same way `--fixture-row` converts a staged C64 party, refusing
a source whose title does not match `--title`:

    tools/dos/acceptance.py --title ssb \\
        --convert $WISH_SPECIMENS/ssb-c64/WISH-SPEC-ssb-512-amigatoc64-walk-resave.D64 \\
        --steps load begin 'walk 1' camp 'save D' read --issue 639 --run ssb-share

| step | what it does |
|---|---|
| `load` | title screens, `LOAD SAVED GAME`, the `--slot` letter; Pool lands on the map, the other three on the party menu.  Pools of Darkness asks `LOAD FROM WHERE? POOLS SECRET EXIT` first and gets `P`.  Pool presses Return past each `PRESS <ENTER>/<RETURN> TO CONTINUE` bar first, when the loaded save is on an event square, so that screen is never recorded as the map (#701); a party that has not taken Rolf's opening tour meets eight (PROBABLE: one boot of one party), and the run stops at `POOL_LOAD_CONTINUE_ROUNDS` (#631) |
| `begin` | Curse, Silver Blades and Pools of Darkness: `BEGIN ADVENTURING`, through Silver Blades' intro bars and Pools of Darkness' journal question and `YES NO` bars (below), to the map; Pools of Darkness' map only by its measured bar |
| `camp` | `ENCAMP`; records the camp bar by `bar_signature` |
| `sheet N`, `items N` | Curse, Silver Blades and Pools of Darkness (`items` Pools of Darkness only; Pool's is the next row), in camp: roster line N (from 1) highlighted (`End` in Curse, `Down` in the other two), `VIEW`, the sheet's name checked against line N's, the bar read for `heal_offered` and `cure_offered` (`sheet_offers`), and for `items` its `ITEMS` list page by page with `NEXT`; back to camp |
| `heal N` | the same three, in camp: line N's sheet, `HEAL` (`LAY` in Pools of Darkness), `SELECT` at `HEAL WHOM?` on the member it opens on, and the sheet required back without the word; back to camp |
| `cure N` | Curse, in camp: line N's sheet, `CURE`, `SELECT` at `CURE WHOM?`, `YES` to `CURE ANYWAY` if asked, the sheet required back; back to camp |
| `change N CLASS` | Curse, at the party menu with the hall open (`--hall`): line N, `HUMAN CHANGE CLASSES`, the class list's row for CLASS as the engine's own test orders them (`class_choices`), checked against the rows the highlight reaches, `SELECT`, back to the party menu |
| `halve N I`, `join N I` | Pools of Darkness, in camp: member N's `ITEMS`, the highlight moved to row I (from 1, at most 18) with `Down`, `h` or `j` pressed once, and the rows counted before and after; `halve` must add a row and keep the highlight or the run stops before any save, `join` only records; back to camp |
| `memorize N` | Pools of Darkness, in camp: roster line N highlighted with `Down`, `MAGIC`, `MEMORIZE`; the grimoire's title checked against line N's name; every page shot and its eleven rows read, turning with `NEXT` until the bar stops offering it; `lists_126` says whether a page draws `MONSTER SUMMONING`, spell id 126; `EXIT` to the Magic bar and to camp.  Nothing is memorized |
| `view N` | At the party menu, before `begin`.  Pools of Darkness and Silver Blades: `VIEW CHARACTER`, line N at `PICK CHARACTER` with `Down`, `SELECT`.  Curse: `End` to line N on the party menu, then `v`.  The sheet is checked by its name as above (never by a bar), `EXIT` returns to the party menu, and only Pools of Darkness pages `ITEMS` |
| `items N` | Pool, in camp: member N's `ITEMS` list, first screen only, from `End` to the line, `v`, `i`, and `Escape` twice back to camp; refuses a sheet with no `ITEMS`; records `rows` and `marked`, the rows (from 1) drawn with the Detect Magic `* ` |
| `sheet N` | Pool: member N's sheet from the map (`End` to the line, `v`, `Escape`); needs either measured map bar of `POOL_MAP_BARS` back |
| `display` | Pool camp `MAGIC > DISPLAY`; captures six member rows, then returns through Magic to camp |
| `cast N SPELL [T]` | Pool, in camp: roster line N highlighted with `End`, `MAGIC`, `CAST`, the spell list's title checked against line N's name, the highlight moved with `End` to SPELL's row (`dosbox.PoolOfRadiance.CAST_SPELLS`: `BLESS`, and `CURE-LIGHT-WOUNDS`, which needs target line T), `CAST`, T picked with `End` and `Return` at `CAST SPELL ON WHOM`, and believed only when the list comes back one SPELL row shorter; `EXIT` twice to camp.  Any other screen stops the run with nothing more pressed, `LOSE IT` included |
| `rest 5m`, `rest 1h30m`, `rest 8d` | camp `REST`, the rest time zeroed and set by key, then rested; minutes in fives; Pool's `GO STAY` random event at the end is answered `GO` (see below); in Curse a message over the continue bar that ends the rest (Tilverton's Royal Guards) gets `Return`, the map bar is required, and the party camps again, logged as `ended_by_message` |
| `save X` | in camp, camp `SAVE` to slot X and decline the quit; at the party menu, `SAVE CURRENT GAME`; believed when `SAVGAMX.DAT` changes |
| `train N` | Curse: roster line N (from 1), `TRAIN CHARACTER`, `YES`, and `LEARN` for any spell the level brings, back to the party menu |
| `shot NAME` | one PNG and the screen digests, nothing pressed |
| `press KEY` | one X keysym (`Down`, `Return`, `t`), then a settle and a PNG; capture only, so only `press`, `shot` and `read` may come after it |
| `walk MI`, `walk 1` | Pool and Curse (`MI`): turn right twice at the map bar and step one square.  Silver Blades and Pools of Darkness (`1`): press MOVE, step one square turning right past a wall, and leave move mode (`e` in Silver Blades, `Escape` in Pools of Darkness) back to the map bar.  A step is believed only when the `x,y` on the status line changes (never the clock beside it), a blank line is never the starting reading, and a run with a walk fails unless `read` shows the last saved slot's place differs from the installed one |
| `turn N` | N from 1 to 4: the walk's control.  Silver Blades and Pools of Darkness press MOVE first and leave move mode after; N `Right` presses, each reading the `x,y` square, which a turn must leave alone (`lost-walk-turn`); the party stays on the map for `camp`, `save D` and `read`.  A run with `turn` and no `walk` fails unless `read` shows the saved place unchanged ("did not move") |
| `read` | copies `SAVE/` out and decodes every node, the clock, the place and each character's experience, installed slot against each saved one; for Pools of Darkness also each character's eight thief skills, item count, encumbrance, movement, current movement, record byte 0x130 (spell id 126's book byte, `book_0x130`) and items |

**Pools of Darkness' screens are read off its `GAME.EXE` strings, not off a
capture.**  Its party menu holds Silver Blades' thirteen entries in the same
order (`GAME.EXE` 0xAB4E-0xAC90 against Silver Blades' `START.EXE`
0xE207-0xE349), so it is driven as Silver Blades' highlight list at
`route_silver_blades`'s rows; the map bar is `Move Area Cast View Encamp Search Look`
(0xBC79), the camp bar `Save View Magic Rest Alter Fix Exit` (0xBEBE), the
rest menu Curse's (0xBB26), the sheet's bar `Items Spells Trade Deposit Drop
Lay Cure Exit` (0xBB4F).  The party menu, map bar, camp bar and sheet have
answered their keys in three complete foundation boots (load, view, begin,
walk or turn, camp save, items); the rest menu has not been reached and
stays PROBABLE.  A screen that does not answer its key stops the run with a
`lost-*.png`.

**The load route is read from the code.**  `LOAD SAVED GAME` (`GAME.OVR`
0x12887) asks `load from where?` over `Pools Secret Exit`: `Pools` is this
title's own `SAVGAM<L>.PTY`, `Secret` a Silver Blades save, `Exit` backs out.
It then lists `load which game: A B C D E F G H I J`, keeping only the letters
whose `SAVGAM<L>.PTY` exists, and loads the one picked.  The menu routine
(0x3A422) takes a word's capital as its key through `UpCase`, so `p` then the
slot letter.  The party menu after a load shows `Train Character` and `Human
Change Classes` only when byte 0x2F of the save's first 1,024 bytes is not
zero (0x14253), which moves `View`, `Save` and `Begin` down two rows.
Silver Blades does the same on the word at 0xD51 of `SAVGAM<L>.DAT`
(`route_silver_blades.menu_after`).

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
line N's effect file (`.SPC`, `.FX` or `.SFX`); `--stage-record
LINE:OFFSET=VALUE` sets one byte of line N's `CHRDAT` record below its length.

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
import sys
import time
import traceback

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_codec, world_state  # noqa: E402
from tools.dos import dosbox, dospod, route_silver_blades  # noqa: E402
from tools.dos.screens import (  # noqa: E402
    BLANK_NAME,
    CELL,
    POD_NAME_CELLS,
    POD_NAME_ROWS,
    POD_ROSTER,
    POD_SHEET_NAME,
    POOL_ITEMS_BAR,  # noqa: F401 -- the constant lives in screens, which reads it; tests and runs name it here
    STATUS_COLUMNS,
    bar_signature,
    item_highlight,
    item_rows,
    on_items_list,
    roster_line,
    roster_name,
    sheet_name,
    status_square,
)
from tools.dos.staging import (  # noqa: E402
    HALL_TITLES,
    HALL_WORD,
    containers_in,
    install,
    node_dict,
    slots_in,
    source_slot,
    stage_control,
    stage_hall,
    stage_node,
    stage_record,
    stage_xp,
)
from tools.registry import evidence, scratch  # noqa: E402

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
#: Pool's map command bars and its character sheet's bar `VIEW: TRADE DROP
#: EXIT`, by `bar_signature`, each measured off a real screen: `town` on the
#: runs that already used the map (#666's `ca4bbff4fa-dos-pool-sheet-live`,
#: for example), `overland` on #634's `ca4bbff4fa-dos-pool-rebuild`.  On the
#: map `End` moves the roster highlight a member on and wraps; `v` opens the
#: sheet, and `Escape` (never `d`, which the sheet's bar offers as DROP)
#: returns to the map with the highlight where it was.
POOL_MAP_BARS: dict[str, str] = {"town": "809e2e1cc9504b5b",
                                 "overland": "f379c606cadd4484"}
#: The character sheet's bar, by `bar_signature`, one entry per kind of sheet,
#: each measured off real screens: `no_items` is `VIEW:TRADE DROP EXIT`,
#: `items` is `VIEW:ITEMS TRADE DROP EXIT`, `caster` is `VIEW ITEMS SPELLS
#: TRADE DROP EXIT` (a cleric's sheet); which of the first two shows depends
#: on whether the sheet offers ITEMS, not on where the party stands.  An NPC's
#: sheet offers no TRADE or DROP: `npc_items` is `VIEW:ITEMS EXIT` (an NPC
#: fighter, several captures across DOSBox runs of the pooled `dosbox.conf`
#: on the town map) and `npc_caster` is `VIEW:ITEMS SPELLS EXIT` (an NPC
#: magic-user, one capture).  A caster carrying nothing
#: (`VIEW:SPELLS TRADE DROP EXIT`, presumably) is not measured and would
#: still stop a `sheet` step.
POOL_SHEET_BARS: dict[str, str] = {"no_items": "33ad531ed78cfa70",
                                   "items": "95afa0d95cd09ab7",
                                   "caster": "49958cda77bfdd82",
                                   "npc_caster": "740a10d0bc93a12a",
                                   "npc_items": "90b53c9e64947226"}
POOL_ROSTER_NEXT = "End"
#: Where Pool's `ITEMS` list draws the Detect Magic mark, `* ` between the
#: READY column and the name: text column 7 (x 56) of each row, from y 40, one
#: row per 8 pixels.  `POOL_ITEM_MARK` is the `*` glyph's signature there,
#: `Screen.glyphs` of one 8x8 cell, measured on 2 marked rows (both on the
#: highlighted row 1); a mark on another row or on a `NO` row is unmeasured.
POOL_ITEM_MARK_X = 56
POOL_ITEM_MARK = "4590f6541a365c32"
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

#: Silver Blades' party menu is a highlight list (`route_silver_blades.MENU_RECT`).
#: With no party it is `Create New Character`, `Add Character to Party`,
#: `Load Saved Game`, ...; `route_silver_blades.MENU_BEFORE` measured `Add` at row 1,
#: and `Load Saved Game` comes after it in `START.EXE`'s list, so row 2; the
#: Silver Blades foundation boots (`found-ssb-a`, `-b`, `-control`) and, as
#: `POD_LOAD_ROW`, the Pools of Darkness ones (`found-pod-a`, `-b2`,
#: `-control`) load a save through it.
SSB_LOAD_ROW = 2

#: Pools of Darkness' party menu, driven as Silver Blades' highlight list
#: because `GAME.EXE` holds the same entries in the same order.  The rows are
#: Silver Blades'; the load, view, save and begin rows have answered in three
#: complete foundation boots of this title.  The eleven-row height is an
#: unverified inference from Silver Blades' own measurement, not from this
#: title's own data: all sixteen captures behind the y=184 frame cutoff were
#: Silver Blades captures, and no Pools of Darkness capture has confirmed its
#: own frame sits at the same y.
POD_MENU_RECT = route_silver_blades.MENU_RECT
POD_LOAD_ROW = SSB_LOAD_ROW
POD_MENU_AFTER = route_silver_blades.MENU_AFTER
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

#: Curse's `PRESS <ENTER>/<RETURN> TO CONTINUE` bar (`Screen.glyphs(dosbox.BAR)`), the
#: one `route_silver_blades.BARS` measured; a party saved before BEGIN ADVENTURING
#: meets it on the world view.
CURSE_CONTINUE_BAR = next(k for k, v in route_silver_blades.BARS.items() if v == "continue")

#: Pool's `PRESS <ENTER>/<RETURN> TO CONTINUE` bar, the `press_return` row of
#: `dosbox.PoolOfRadiance.COMBAT_BARS`; a party saved on an event square meets
#: it on load, before the map is showing (#701).
POOL_CONTINUE_BAR = next(digest for width, digest, label in dosbox.PoolOfRadiance.COMBAT_BARS
                         if label == "press_return")

#: How many continue screens `press_continue_screens` answers for Curse's
#: BEGIN and rest before it gives up.
CONTINUE_ROUNDS = 3
#: How many Pool's load answers before it gives up.  A party that has never
#: taken Rolf's opening tour (clock zero at area 0, 15,1, as any party made in
#: the Amiga or C64 game is) loads into the whole tour: eight chained screens,
#: `GREETINGS, COURAGEOUS ONES` through `YOUR TOUR IS ENDED`, each a different
#: frame, and then the map at 0,4 (#631, run `dce274bcca-tour-count-cap25`).
#: PROBABLE: measured on one boot of one party, taken as a general figure.
#: Two more than the tour, so a stuck screen still stops the run.
POOL_LOAD_CONTINUE_ROUNDS = 10
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
#: The `ITEMS` list draws at most 18 rows, at y = 40 + 8k (all 37 Pools of
#: Darkness `ITEMS` captures of #650's runs).  `Next` pages past them, which
#: `halve` and `join` do not drive.
ITEM_ROWS = 18
#: `Down` moves the `ITEMS` highlight one row on (2 of 2 presses) and `Up` one
#: back (1 of 1); `End` and `Home` did nothing (1 press each), so
#: `dosbox.LIST_DOWN` is not this list's key.  Not measured: whether the
#: highlight wraps.
ITEM_NEXT_ROW = "Down"
#: `HALVE` and `JOIN` act at once and ask nothing: 7 rows became 8 and back to
#: 7, the highlight staying on row 1 (one press each, TURBO K's 50 arrows).
#: Not measured: a stack of 1, a full list, a list of 18 rows.
ITEM_HALVE = "h"
ITEM_JOIN = "j"

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
#: The keys that enter and leave move mode, by title key.  Silver Blades'
#: `m` is CONFIRMED (bar `EXIT` alone, ink `e61c9acccfc048ae`, three runs); its
#: `e` leaves it: runs with `--move-exit e` and the foundation boots came back
#: to the map bar, and `Escape` does not, since it leaves the move bar showing.
#: Curse has no move mode: `Up` steps at the map bar.
#: Pools of Darkness keeps `m` and `Escape`.
MOVE_KEYS = {"darkness": (POD_MOVE, POD_MOVE_EXIT), "ssb": ("m", "e")}
#: Curse's party-menu `bar_signature`, the loaded menu and the empty one alike:
#: CONFIRMED on 12 shots of 4 boots.  It does not tell a loaded menu from an
#: empty one, so `check_party_drawn` still reads the roster.
CURSE_PARTY_BAR = "31286bfc4a3695fc"
#: Silver Blades' `bar_signature` after `PICK CHARACTER`'s select key is the
#: sheet's own bar, and it depends on the member (`SPELLS EXIT` on a ranger,
#: PAINE, `ae25da8be0427b42`; `route_silver_blades.BARS` lists the `HEAL` sheets), so a
#: Silver Blades sheet is judged by its name and never by a bar.  Unmeasured:
#: the bar of any other member's sheet.
#: `Select`, the only word of the `PICK CHARACTER` prompt (`GAME.EXE` data
#: `DS:0x2859` over `DS:0x2B8D`), keyed by its first letter.  The prompt then
#: views the character the roster highlight is on (`AA:39`, 0x2452E).
POD_PICK = "s"
#: Roster-highlight moves tried per member before `pick_line` gives up.
POD_PICK_ROUNDS = 2

#: `Magic` on the camp bar, and `Memorize` on the Magic bar `CAST MEMORIZE
#: SCRIBE DISPLAY EXIT` it opens (`GAME.EXE` data 0xD13E lists a `Rest` the
#: screen does not draw).  The Magic bar by `bar_signature`, measured on 5
#: shots of the #509 probe boot `probe-memorize-live` (lines 1 and 5).
POD_MAGIC = "m"
POD_MEMORIZE = "m"
POD_MAGIC_BAR = "24a79a5ab06c2164"
#: The grimoire `<NAME>'S SPELLS IN GRIMOIRE` that `Memorize` opens for the
#: highlighted character.  Its bar is `CHOOSE SPELL:MEMORIZE` and then the
#: list words, `NEXT EXIT` on the first page, `NEXT PREV EXIT` between and
#: `PREV EXIT` on the last (`GAME.EXE` data 0xC64F and 0xCA79).  The head,
#: its first 21 cells, is the same on every page (6 shots, 2 characters); a
#: list of one page, `MEMORIZE EXIT`, is unmeasured, and the head is what
#: knows it.
POD_GRIMOIRE_HEAD = "524989d1c25436a9"
POD_GRIMOIRE_HEAD_CELLS = 21
#: The two whole-bar signatures that offer `NEXT`, first page and between;
#: the last page's is `47a21ea1ca2723b9`.  `Next` on the last page changes
#: nothing (7 presses over 2 characters) and the list does not wrap.
POD_GRIMOIRE_NEXT_BARS = frozenset({"37d28076a433f661", "41b0de522281a00d"})
POD_GRIMOIRE_NEXT = dosbox.LIST_PAGE_DOWN
#: Pages shot before the run gives up on reaching the last; HILDE's
#: magic-user book from level 1 to 9 is 7.
GRIMOIRE_PAGES = 16
#: The title's first cell, and the signature of the `'S` after the name in
#: it: the roster name's cells, then these two (HILDE and TROND AAGE L, 3
#: shots).
GRIMOIRE_TITLE = (8, 8)
GRIMOIRE_POSSESSIVE = "4ed3290842b823f9"
#: The list: eleven 8-pixel rows from y = 40.  A row is read from x = 8 over
#: 19 cells, which holds a level header and a spell name of 17 characters
#: after its two-cell indent; the game's mouse arrow sits at x 161-174 over
#: rows 7 to 9 and is left out.  A longer name is read by its first 17.
GRIMOIRE_ROWS_AT = (8, 40)
GRIMOIRE_ROW_COUNT = 11
GRIMOIRE_ROW_CELLS = 19
#: Rows by the signature `grimoire_rows` reads, measured on HILDE's last page
#: with the highlight on each of the four bottom rows in turn (the reading
#: is the same whichever row is lit).  The names are the last three entries
#: of `GAME.EXE`'s spell-name table (0x23 bytes each, `Bless` first, 126
#: entries), so `Monster Summoning` is id 126 and appears nowhere else.
NINTH_LEVEL_ROW = "5bb57d1d629bc1df"
GRIMOIRE_SPELLS = {"46508bd7a6ec4097": 124,     # METEOR SWARM
                   "e1ad523ef877d882": 125,     # POWER WORD KILL
                   "42b47c6c0a74f78d": 126}     # MONSTER SUMMONING
SPELL_126_ROW = next(k for k, v in GRIMOIRE_SPELLS.items() if v == 126)
#: The record byte that holds spell id 126: the last of the 126-byte book at
#: 0x0B3 (`goldbox/dos_port.py`'s Pools of Darkness `spellbook`).  The list
#: builder (`GAME.OVR` 0x2A80B) lists 126 when it is not zero.
POD_BOOK_126 = 0x130

#: The camp sheet's own words, read from each title's `GAME.OVR`.  Curse
#: builds its bar at 0x27C94-0x27DF4 from `Items Spells Trade Drop Heal Cure
#: Exit`, each word drawn only when its test passes: `Heal` when the gate at
#: 0x2A64D passes (a paladin, or a regained one, not in game mode 5, status
#: `0x195` zero, no node 140), `Cure` when 0x2A6B2 does (the same, and uses at
#: `0x191` above zero).  The menu routine (0x3C465) returns the capital pressed
#: and the loop calls the heal routine on `H` (0x27E75) and the cure on `C`
#: (0x27E87).  Silver Blades is the same loop (gate 0x2AE3B; `H` at 0x28147,
#: `C` at 0x2815F).  Pools of Darkness' bar is `Items Spells Trade Deposit Drop
#: Lay Cure Exit` (`GAME.EXE` 0xBB4F), `Lay` enabled at 0x2467D when the gate
#: 0x26ADA passes, and the loop dispatches word 5 (`Lay`) to the heal routine
#: 0x26BC3 and word 6 to the cure 0x26CE6; the menu keys each word by its
#: capital.
SHEET_KEYS = {"curse": {"heal": "h", "cure": "c"},
              "ssb": {"heal": "h", "cure": "c"},
              "darkness": {"heal": "l", "cure": "c"}}
#: The titles whose camp sheet `sheet N` and `heal N` drive.
CAMP_SHEETS = frozenset(SHEET_KEYS)
#: The titles `cure N` is driven in: the cure's prompts are read from Curse's
#: code for #649's runs; the other two titles' are the same strings, undriven.
CURES = frozenset({"curse"})
#: What moves the camp's current member on, by title.  Curse's camp, like its
#: party menu, hands `End` (scan code 0x4F) and `Home` (0x47) to the roster
#: handler at `GAME.OVR` 0x2A32C, which every menu that opens the sheet calls;
#: Silver Blades' handler (0x2AB0F) and Pools of Darkness' (0x2680C) take
#: `Down` (0x50) and `Up` (0x48).
CAMP_ROSTER_NEXT = {"curse": ROSTER_NEXT, "ssb": POD_ROSTER_NEXT,
                    "darkness": POD_ROSTER_NEXT}
#: `SELECT` at `HEAL WHOM?` and `CURE WHOM?`.  Curse's prompt (0x3A4C8) is the
#: prompt, `Select` and `Exit`; its loop ends on Return, Escape, `E` or `S`
#: (the set at 0x3A4A0), takes the member it is on for `S`, and opens on the
#: party's first member (`[0x6524]`).  `End` and `Home` move it.  Silver
#: Blades' `CURE WHOM? SELECT EXIT` took `S` in `ssbimport.py`'s run.
PICK_SELECT = "s"
#: `YES` to `<NAME> IS NOT DISEASED` / `CURE ANYWAY: YES NO`, which the cure
#: asks when nobody in the party has a disease (Curse 0x2A8C6-0x2A915: it
#: goes on only on `Y`).
CURE_ANYWAY = "y"
#: How long a sheet may take to come back after `SELECT`: the heal and the
#: cure print their message and wait `[0x4FC2]` tenths of a second, the
#: message speed, through `Delay` (`START.EXE` image 0x57F9), before the
#: sheet redraws; no key is asked for.
SHEET_BACK_SECONDS = 60.0

#: `HUMAN CHANGE CLASSES` on Curse's party menu, `H` (`GAME.OVR` 0x20486),
#: enabled at 0x20252 when the hall word `--hall` opens is set and the
#: current member may change.  It calls 0x3BB4D on the current member.
PARTY_CHANGE = "h"
#: The class list 0x3BB4D shows (the list menu 0x104:0x34 over text columns
#: 1-38 and rows 2-22): a `Pick New Class` header, then every class the member
#: qualifies for, in his race's table order; `S` takes the highlighted class.
#: The same list menu drives Curse's grimoire, where `End` moves the
#: highlight down and wraps (`dosbox.Camp.GRIMOIRE_LIST`).  The rectangle is
#: the list window clear of its border columns, not measured on this screen:
#: the step counts the rows it can reach and stops unless they are as many
#: as the classes the engine's own test allows.
CHANGE_LIST = (16, 16, 288, 168)
#: Rows a class list can hold: the eight classes of a human's table.
CHANGE_ROWS = 8

#: `START.EXE` data-segment tables 0x3BB4D and its test 0x3B99E read: class
#: names (27-byte Pascal strings), each race's class list (a count, then
#: class ids), each class's six ability minima, and each class's alignments
#: (a count, then up to nine).
CLASS_NAMES_AT, CLASS_NAME_SIZE = 0x0CB8, 27
RACE_CLASSES_AT, RACE_CLASSES_SIZE = 0x3FFA, 14
CLASS_MINIMA_AT, CLASS_MINIMA_SIZE = 0x4174, 6
CLASS_ALIGNMENTS_AT, CLASS_ALIGNMENTS_SIZE = 0x41DA, 10
#: 0x3BF66: the current class is `0x11`, none, for any race but 7, human.
HUMAN_RACE, NO_CLASS = 7, 0x11
#: 0x3B99E: a minimum of 9 or more marks an ability the change tests; the
#: class left must have each above 14 and the class taken each above 16.
REQUISITE, KEEP_ABOVE, TAKE_ABOVE = 9, 14, 16
#: The record fields the test reads (Curse `goldbox.dos_port`): the six
#: abilities (the first byte of each two), race, the class-level array and
#: alignment, at 0x10, 0x74, 0x109 and 0x11B in the code.
ABILITIES = ("strength", "intelligence", "wisdom", "dexterity", "constitution",
             "charisma")


def bar_words(screen: dosbox.Screen) -> list[list[str]]:
    """The command bar as words: runs of cells that are not flat, each cell
    `Screen.glyphs` against its own paper, so a word lit by the highlight
    block reads as the same word unlit."""
    x0, y, w, h = dosbox.BAR
    words: list[list[str]] = []
    word: list[str] = []
    for x in range(x0, x0 + w, CELL):
        rect = (x, y, CELL, h)
        if screen.flat(rect):
            if word:
                words.append(word)
            word = []
        else:
            word.append(screen.glyphs(rect))
    if word:
        words.append(word)
    return words


def sheet_offers(words: list[list[str]], title: str) -> dict[str, bool] | None:
    """Whether a sheet bar's words offer the heal and the cure, or None when
    the bar does not end in the four-letter `EXIT` every sheet bar ends in.

    Read by letter position, not by a measured digest, because which words
    a sheet shows varies with what the member carries and knows.  The last
    word's first cell is `E`.  Curse's and Silver Blades' `HEAL` is the one
    four-letter word with `E` second; `CURE` the one with `E` fourth
    (`DROP`, the other, has none); Pools of Darkness' `LAY` is its only
    three-letter word.  Checked against the one Curse paladin's sheet and the
    one Pools of Darkness paladin's sheet captured so far.
    """
    if not words or len(words[-1]) != 4:
        return None
    e = words[-1][0]
    rest = words[:-1]
    if title == "darkness":
        heal = any(len(w) == 3 for w in rest)
    else:
        heal = any(len(w) == 4 and w[1] == e for w in rest)
    cure = any(len(w) == 4 and w[3] == e and w[1] != e for w in rest)
    return {"heal": heal, "cure": cure}


def acted_word(words: list[list[str]], title: str, act: str) -> int | None:
    """The index of the `HEAL`/`LAY` or `CURE` word in a sheet bar's words.

    Shares `sheet_offers`'s guard against a bar that does not end in the
    four-letter `EXIT`, so the two cannot read a bar's shape differently.
    """
    if sheet_offers(words, title) is None:
        return None
    e = words[-1][0]
    for i, w in enumerate(words[:-1]):
        if act == "heal" and (len(w) == 3 if title == "darkness"
                              else len(w) == 4 and w[1] == e):
            return i
        if act == "cure" and len(w) == 4 and w[3] == e and w[1] != e:
            return i
    return None


def yes_no_words(words: list[list[str]]) -> bool:
    """A bar that ends `YES NO`: a three-letter word and a two-letter one."""
    return len(words) >= 2 and len(words[-2]) == 3 and len(words[-1]) == 2


def class_tables(start_exe: bytes) -> bytes:
    """The data segment of Curse's `START.EXE`, where 0x3BB4D's tables are."""
    from tools.dos import dosspellslots, unexepack
    try:
        image, _ = unexepack.unpack(start_exe)
    except ValueError:
        image = start_exe[int.from_bytes(start_exe[8:10], "little") * 16:]
    return image[dosspellslots.data_segment(image) * 16:]


def class_name(ds: bytes, cid: int) -> str:
    at = CLASS_NAMES_AT + CLASS_NAME_SIZE * cid
    return ds[at + 1:at + 1 + ds[at]].decode("latin-1").upper()


def class_choices(record: bytes, ds: bytes) -> list[tuple[int, str]]:
    """The classes 0x3BB4D lists for `record`, in the list's order, or none
    when the party menu does not offer it the command.

    The menu offers it (0x2022A-0x20252) only to a human (0xFE:0x3E, race 7)
    who has not changed class before (0xFE:0x43, the same reading as the
    current class over the former-class array, must find none).  The list is
    the race's table in order, keeping each class 0x3B99E passes: not the
    current class (0x3BF66, the first class level that is not zero, when it
    is above zero, for a human); every ability the current class's minima
    mark above `KEEP_ABOVE`; every ability the new class's mark above
    `TAKE_ABOVE`; and the member's alignment among the new class's.
    """
    from goldbox import dos_port
    fields = dos_port.FIELDS_BY_NAME_FOR["curse-of-the-azure-bonds"]
    race = record[fields["race"].offset]

    def first_class(field: str) -> int:
        at = fields[field].offset
        levels = record[at:at + 8]
        first = next((i for i in range(7) if levels[i]), 7)
        return first if 0 < levels[first] < 0x80 else NO_CLASS

    if race != HUMAN_RACE or first_class("former_class_levels") != NO_CLASS:
        return []
    abilities = [record[fields[a].offset] for a in ABILITIES]
    alignment = record[fields["alignment"].offset]
    current = first_class("class_levels")

    def meets(cid: int, above: int) -> bool:
        at = CLASS_MINIMA_AT + CLASS_MINIMA_SIZE * cid
        return all(ds[at + k] < REQUISITE or abilities[k] > above for k in range(6))

    table = RACE_CLASSES_AT + RACE_CLASSES_SIZE * race
    out = []
    for idx in range(1, ds[table] + 1 if ds[table] < 0x80 else 1):
        cid = ds[table + idx]
        aligned = CLASS_ALIGNMENTS_AT + CLASS_ALIGNMENTS_SIZE * cid
        allowed = ds[aligned + 1:aligned + 1 + ds[aligned]]
        if (cid != current and meets(current, KEEP_ABOVE) and meets(cid, TAKE_ABOVE)
                and alignment in allowed):
            out.append((cid, class_name(ds, cid)))
    return out


def status_column(title: str) -> int:
    """The pixel column `title`'s status token starts at, or a refusal."""
    try:
        return STATUS_COLUMNS[title]
    except KeyError:
        raise StepFailed(
            f"{title}'s status-line column is unmeasured (no DOS capture of it "
            "has been read), so its square cannot be read; the measuring boot "
            "of #679 package 7 supplies it") from None


def _cells(screen: dosbox.Screen, x: int, y: int, count: int,
           height: int = POD_NAME_ROWS) -> list[str]:
    """`count` character cells from `(x, y)`, each `Screen.glyphs` against its
    own paper, so a highlighted cell reads as the same letter unlit."""
    return [screen.glyphs((x + CELL * i, y, CELL, height)) for i in range(count)]


_BLANK_CELL = dosbox.Screen(CELL, POD_NAME_ROWS, bytes(CELL * POD_NAME_ROWS * 3)).glyphs()


def _cell_digest(cells: list[str]) -> str:
    return hashlib.sha1("".join(cells).encode()).hexdigest()[:16]


def roster_cells(screen: dosbox.Screen, line: int) -> list[str]:
    """Camp roster line `line`'s name, cell by cell, without trailing blanks."""
    x, y = POD_ROSTER["camp"]
    cells = _cells(screen, x, y + CELL * (line - 1), POD_NAME_CELLS)
    while cells and cells[-1] == _BLANK_CELL:
        cells.pop()
    return cells


def grimoire_is_for(screen: dosbox.Screen, name: list[str]) -> bool:
    """Whether the grimoire's title opens with `name` and then `'S`."""
    if not name:
        return False
    title = _cells(screen, *GRIMOIRE_TITLE, len(name) + 2)
    return (title[:len(name)] == name and hashlib.sha1(
        "".join(title[len(name):]).encode()).hexdigest()[:16] == GRIMOIRE_POSSESSIVE)


def on_grimoire(screen: dosbox.Screen) -> bool:
    return bar_signature(screen, POD_GRIMOIRE_HEAD_CELLS) == POD_GRIMOIRE_HEAD


def grimoire_rows(screen: dosbox.Screen) -> list[str]:
    """Each of the list's eleven rows as one signature of its cells, blind to
    the highlight, comparable with `NINTH_LEVEL_ROW` and `GRIMOIRE_SPELLS`."""
    x, y = GRIMOIRE_ROWS_AT
    return [hashlib.sha1("".join(_cells(screen, x, y + CELL * k, GRIMOIRE_ROW_CELLS,
                                        CELL)).encode()).hexdigest()[:16]
            for k in range(GRIMOIRE_ROW_COUNT)]


def ninth_level(rows: list[str]) -> list[int | str]:
    """The rows after the `9TH LEVEL` header, as spell ids where the row is
    one of `GRIMOIRE_SPELLS` and as its signature where it is not."""
    if NINTH_LEVEL_ROW not in rows:
        return []
    after = rows[rows.index(NINTH_LEVEL_ROW) + 1:]
    return [GRIMOIRE_SPELLS.get(r, r) for r in after]










#: The walk each title drives: `MI`, two turns and a step at the map bar (Pool,
#: Curse); `1`, a step in move mode (Silver Blades, Pools of Darkness).
WALKS = {"pool": "MI", "curse": "MI", "ssb": "1", "darkness": "1"}
#: The titles whose `turn N` control is driven: those with a walk to check.
TURNS = frozenset(WALKS)
#: The titles whose party menu `view N` opens a sheet from.
VIEWS = frozenset({"curse", "ssb", "darkness"})


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
    "pool": Title("pool", "POOLRAD", "map", True, False),
    "curse": Title("curse", "CURSE", "party", False, True),
    "ssb": Title("ssb", "SECRET", "party", False, False),
    # `Load Saved Game` is a party-menu entry here as in Curse and Silver
    # Blades, and both leave the party at that menu after a load, so this
    # title's `loads_to` is `party`, as the foundation boots show.  The
    # container names its own `CHRDAT` files and the engine loads those, not
    # the letter picked (`docs/141-dos-savegame.md`, 12809-13136), so a
    # renamed slot would load nothing.
    "darkness": Title("darkness", "DARKNESS", "party", False, False,
                      exe="START.BAT", suffix=".PTY"),
}

#: The C64 party `--fixture-row` stages into for each later title: an
#: engine-written save in `$WISH_SPECIMENS/por-c64/` (`docs/235` §4).  Pool
#: of Radiance uses the committed fixture party instead.
C64_BASES = {
    "curse": "WISH-SPEC-curse-h-engine-resave.D64",
    "ssb": "WISH-SPEC-ssb-d-engine-resave.D64",
}

#: The effect files of the three titles (`dos_codec.read_character`).
EFFECT_SUFFIXES = (".SPC", ".FX", ".SFX")


class StepFailed(RuntimeError):
    """A step did not reach the screen or the file it waits for."""


class DeadlineReached(TimeoutError):
    """The run's route window is over; what is left belongs to the cleanup."""


class Terminated(BaseException):
    """The wrapper's `timeout` sent SIGTERM.

    A `BaseException`, so that no `except Exception` on the way -- the failure
    capture's, a step's -- can swallow it and leave the run going with the
    signal already ignored.
    """


#: The run's whole budget, and the part of it kept for the cleanup (the
#: failure capture, the shots and the resave copied out, the emulator stopped).
#: The wrapper's own `timeout` is a backstop at least `WRAPPER_MARGIN` seconds
#: longer than the deadline, so the driver, not the wrapper, ends the run.
DEADLINE_SECONDS = 900.0
CLEANUP_SECONDS = 120.0
WRAPPER_MARGIN = 300.0
#: The longest single wait that is not cut to the route window: a settle's
#: `timeout=90.0`.  The cleanup and one such wait, begun just inside the route
#: window, must both fit in `WRAPPER_MARGIN`, or the wrapper's `timeout` ends the
#: run before the driver has written its summary.
LONGEST_UNBOUNDED_WAIT = 90.0
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
        if self.cleanup + LONGEST_UNBOUNDED_WAIT > WRAPPER_MARGIN:
            raise ValueError(
                f"a cleanup window of {self.cleanup:.0f} s and an unbounded wait "
                f"of {LONGEST_UNBOUNDED_WAIT:.0f} s exceed the {WRAPPER_MARGIN:.0f} s "
                "the wrapper's `timeout` is given beyond the deadline")
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
    row: int = 0


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


STEP_HELP = ("load, begin, 'walk MI', 'walk 1', 'turn 4', camp, display, 'rest 5m', 'save D', "
             "'train 1', 'change 2 FIGHTER', 'sheet 1', 'heal 1', 'cure 1', 'items 1', "
             "'halve 1 1', 'join 4 15', 'view 1', 'memorize 5', 'cast 2 BLESS', "
             "'cast 2 CURE-LIGHT-WOUNDS 4', 'shot NAME', "
             "'press KEY', read")
#: The class names `change N CLASS` takes: Curse's own (`START.EXE` data
#: 0x0CB8), upper case.
CHANGE_CLASSES = ("CLERIC", "DRUID", "FIGHTER", "PALADIN", "RANGER", "MAGIC-USER",
                  "THIEF", "MONK")


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
    if kind in ("train", "sheet", "items", "view", "memorize", "heal", "cure") and len(
            words) == 2 and re.fullmatch(r"[1-8]", words[1]):
        return Step(kind, text, line=int(words[1]))
    if kind == "cast" and len(words) in (3, 4) and re.fullmatch(r"[1-8]", words[1]) and (
            len(words) == 3 or re.fullmatch(r"[1-8]", words[3])):
        spell = words[2].upper()
        known = dosbox.PoolOfRadiance.CAST_SPELLS
        if spell not in known:
            raise ValueError(f"cast {words[2]!r} is refused: the spell is not one of "
                             f"{', '.join(known)}, the rows measured")
        target = int(words[3]) if len(words) == 4 else 0
        if known[spell][1] and not target:
            raise ValueError(f"cast {spell} needs a target line: {text!r}")
        if target and not known[spell][1]:
            raise ValueError(f"cast {spell} takes no target: {text!r}")
        return Step(kind, text, line=int(words[1]), name=spell, row=target)
    if kind == "change" and len(words) == 3 and re.fullmatch(r"[1-8]", words[1]):
        if words[2].upper() not in CHANGE_CLASSES:
            raise ValueError(f"change to {words[2]!r} is refused: the class is one "
                             f"of {', '.join(CHANGE_CLASSES)}")
        return Step(kind, text, line=int(words[1]), name=words[2].upper())
    if kind in ("halve", "join") and len(words) == 3 and re.fullmatch(
            r"[1-8]", words[1]) and re.fullmatch(r"\d+", words[2]):
        row = int(words[2])
        if not 1 <= row <= ITEM_ROWS:
            raise ValueError(f"{kind} row {row} is refused: the list shows rows 1 to "
                             f"{ITEM_ROWS} and the rows past them need Next, which "
                             "is not driven here")
        return Step(kind, text, line=int(words[1]), row=row)
    if kind == "walk" and len(words) == 2 and words[1].upper() in WALKS.values():
        return Step(kind, text, key=words[1].upper())
    if kind == "turn" and len(words) == 2 and re.fullmatch(r"[1-4]", words[1]):
        return Step(kind, text, line=int(words[1]))
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
                raise ValueError(f"walk is not driven in {title}")
            if step.key != WALKS[title]:
                raise ValueError(f"{title}'s walk is 'walk {WALKS[title]}', not "
                                 f"{step.text!r}")
            if where != "map":
                raise ValueError(f"walk needs the map: {step.text!r}")
        elif k == "turn":
            if title not in TURNS:
                raise ValueError(f"turn is not driven in {title}")
            if where != "map":
                raise ValueError(f"turn needs the map: {step.text!r}")
        elif k == "sheet" and title == "pool":
            if where != "map":
                raise ValueError(f"sheet needs the loaded map: {step.text!r}")
        elif k in ("sheet", "heal", "cure") and title in CAMP_SHEETS:
            if k == "cure" and title not in CURES:
                raise ValueError(f"cure is driven in {', '.join(sorted(CURES))} "
                                 f"only, not {title}")
            if where != "camp":
                raise ValueError(f"{k} needs camp first: {step.text!r}")
        elif k in ("heal", "cure"):
            raise ValueError(f"{k} is driven in "
                             f"{', '.join(sorted(CAMP_SHEETS if k == 'heal' else CURES))} "
                             f"only, not {title}")
        elif k == "change":
            if title != "curse":
                raise ValueError(f"change is driven in curse only, not {title}")
            if where != "party":
                raise ValueError(f"change needs the party menu, before begin: "
                                 f"{step.text!r}")
        elif k == "items" and title == "pool":
            if where != "camp":
                raise ValueError(f"items needs camp first: {step.text!r}")
        elif k in ("items", "halve", "join", "memorize"):
            if title != "darkness":
                raise ValueError(f"{k} is driven in darkness only, not {title}")
            if where != "camp":
                raise ValueError(f"{k} needs camp first: {step.text!r}")
        elif k == "view":
            if title not in VIEWS:
                raise ValueError("view is driven in curse, ssb and darkness only")
            if where != "party":
                raise ValueError(f"view needs the party menu, before begin: "
                                 f"{step.text!r}")
        elif k == "rest":
            if where != "camp":
                raise ValueError(f"rest needs camp first: {step.text!r}")
        elif k in ("display", "cast"):
            if title != "pool":
                raise ValueError(f"{k} is driven in pool only, not {title}")
            if where != "camp":
                raise ValueError(f"{k} needs camp first: {step.text!r}")
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


def parse_control(text: str) -> tuple[int, int, int | None]:
    """`LINE=CONTROL[:SHARE]`, numbers decimal or `0x` hex: roster line 1-8's
    field_83_87 control byte, and optionally the treasure-share byte after it."""
    line, sep, rest = text.partition("=")
    parts = rest.split(":")
    if not sep or not re.fullmatch(r"[1-8]", line.strip()) or len(parts) not in (1, 2):
        raise ValueError(f"not a control stage: {text!r} (LINE=CONTROL[:SHARE])")
    control = int(parts[0], 0)
    share = int(parts[1], 0) if len(parts) == 2 else None
    if not 0 <= control <= 0xFF or (share is not None and not 0 <= share <= 0xFF):
        raise ValueError(f"control or share out of range: {text!r}")
    return int(line), control, share


def parse_record_bytes(texts) -> list[tuple[int, int, int]]:
    """`LINE:OFFSET=VALUE`, numbers decimal or `0x` hex, comma-separated or
    repeated: one byte of roster line 1-8's `CHRDAT` record each.  Whether the
    offset lies inside the record is `check_staging`'s and `stage_record`'s
    to say, since the record's size is the installed title's."""
    out = []
    for text in texts:
        for item in text.split(","):
            where, sep, value = item.partition("=")
            parts = where.split(":")
            if not sep or len(parts) != 2 or not value.strip():
                raise ValueError(f"{item!r}: a record byte is LINE:OFFSET=VALUE")
            line, offset = (int(p, 0) for p in parts)
            byte = int(value, 0)
            if not 1 <= line <= 8 or offset < 0 or not 0 <= byte <= 0xFF:
                raise ValueError(f"{item!r}: the line is 1 to 8, the offset "
                                 "not negative, the value one byte")
            out.append((line, offset, byte))
    return out


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
    nodes, experience, thief skills, item count, encumbrance, movement, items,
    the record byte `POD_BOOK_126` (spell id 126's book byte), the three
    level-drain marks and the ready-to-train byte at 0x1EC, read through
    `world_state.pod_from_dos` and `dos_codec.read_party`."""
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
    vault_path = folder / f"VAULT{letter}.DAT"
    if vault_path.is_file():
        v = dos_codec.pod_vault_from_dos(vault_path.read_bytes())
        out["vault"] = {"platinum": v.platinum, "gems": v.gems,
                        "jewelry": v.jewelry,
                        "items": [item_dict(dos_codec.DosItem(r))
                                 for r in v.items]}
    for c in dos_codec.read_party(folder, letter):
        out["characters"].append({
            "name": c.name, "file": pathlib.Path(c.source).name,
            "experience": c.get("experience"),
            "nodes": [node_dict(e) for e in c.effects],
            "thief": {f: c.get(f) for f in THIEF_FIELDS},
            "item_count": c.get("item_count"),
            "encumbrance": c.get("encumbrance"),
            "movement": c.get("movement"),
            "movement_current": c.get("movement_current"),
            "book_0x130": c.to_bytes()[POD_BOOK_126],
            "highest_class_levels": list(c.raw("highest_class_levels")),
            "highest_experience": c.get("highest_experience"),
            "highest_hp_max": c.get("highest_hp_max"),
            "ready_to_train": c.get("ready_to_train"),
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
        control = treasure_share = None
        if "field_83_87" in c.fields:
            control_raw = c.raw("field_83_87")
            control_index = 1 if len(control_raw) == 5 else 0
            control = control_raw[control_index]
            treasure_share = control_raw[control_index + 1]
        # None, not 0, in a title that has not mapped the byte.
        own = {n: c.get(n) if n in c.fields else None
               for n in ("creature_type", "turn_class", "movement")}
        out["characters"].append({
            **own,
            "status_bytes": (list(c.raw("field_10c_10f"))
                             if "field_10c_10f" in c.fields else None),
            "name": c.name, "file": path.name,
            "experience": c.get("experience") if "experience" in c.fields else None,
            "control": control, "treasure_share": treasure_share,
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
MEMBER_FIELDS = ("thief", "item_count", "encumbrance", "movement",
                 "movement_current", "book_0x130", "items")


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


def compare_shares(before: dict, after: dict) -> list[dict]:
    """Each character's `control` and `treasure_share` bytes in `before` and
    `after`, matched by name.  A row with either byte unequal fails the run
    (`read_step`/`describe`)."""
    after_by = {c["name"]: c for c in after["characters"]}
    rows = []
    for c in before["characters"]:
        if c.get("control") is None and c.get("treasure_share") is None:
            continue
        now = after_by.get(c["name"])
        row = {"name": c["name"], "present": now is not None,
               "control_before": c.get("control"),
               "control_after": None if now is None else now.get("control"),
               "share_before": c.get("treasure_share"),
               "share_after": None if now is None else now.get("treasure_share")}
        row["matches"] = (now is not None
                          and row["control_before"] == row["control_after"]
                          and row["share_before"] == row["share_after"])
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


def parse_name(text: str) -> tuple[int, str]:
    """`POSITION=NAME` as `(position, name)`: the name the player would type
    into the Shorten window's box for the party member at that position."""
    position, sep, name = text.partition("=")
    if not sep or not re.fullmatch(r"\d+", position):
        raise ValueError(f"not POSITION=NAME: {text!r} (say 0=Wren)")
    if not name or any(not 0x20 <= ord(ch) <= 0x7E for ch in name):
        raise ValueError(f"--name {text!r}: a name is one or more printable "
                         "ASCII characters")
    return int(position), name


def parse_names(texts: list[str], title: str) -> dict[int, str]:
    """`--name` values as the `{position: name}` `prepare_save_as` takes,
    refusing a repeated position or a name over the DOS field's width."""
    from editor import saveplan
    width = saveplan.name_width("dos", CONVERT_TITLE_KEYS[title])
    names: dict[int, str] = {}
    for text in texts:
        position, name = parse_name(text)
        if position in names:
            raise ValueError(f"--name gives position {position} twice")
        if len(name) > width:
            raise ValueError(f"--name {text!r}: {len(name)} characters, over "
                             f"the {width} the DOS {title} name field holds")
        names[position] = name
    return names


def _save_as_dos(party, out: pathlib.Path, title: str, report: dict,
                 names: dict[int, str] | None = None) -> dict:
    """Save As DOS of `party` into `out/source`, filling in `report`.

    The route is the editor's own, `prepare_save_as` then `publish`, as
    `tests/convert/test_runningeffects.py`'s `_dos_plan` prepares it.
    `prepare_save_as` refuses a conversion that would drop a field, which is
    reported as `refused` and ends the run before any boot.  Shared by
    `build_source` (a staged C64 party) and `build_saveas_source` (any save
    `editor.convert.Source.detect` accepts): both build `party` and a `report`
    of their own and hand them here for the rest of the route.
    """
    from editor import saveplan
    from editor.convert import Source
    from tools.convert import convertdrops

    source = Source.of_snapshot(saveplan.prepare(party))
    assets = saveplan.resolve_assets(source, "dos",
                                     game_files=convertdrops.game_files,
                                     dos_folder=dosbox.find_game(TITLES[title].stem))
    dest = out / "source"
    if names and max(names) >= len(party.members):
        return {**report, "refused": f"--name position {max(names)} is not a "
                f"member of a party of {len(party.members)}"}
    try:
        plan = saveplan.prepare_save_as(party, "dos", dest, assets,
                                        **({"names": names} if names else {}))
    except saveplan.DroppedFields as e:
        return {**report, "refused": str(e)}
    except saveplan.NamesDoNotFit as e:
        return {**report, "refused": "no --name for " + "; ".join(
            f"position {p} ({n!r}, {e.width} fit)" for p, n in e.unfit)}
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


def build_source(rows: list[tuple[int, int, int, int, int]], out: pathlib.Path,
                 title: str = "pool", base: str | None = None) -> dict:
    """Stage `rows` into a C64 party and Save As DOS into `out/source`."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster
    from goldbox import effects
    from goldbox.c64_port import POOL_OF_RADIANCE
    from goldbox.savegame import SaveGame0, SaveGame1

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
    return _save_as_dos(party, out, title, report)


#: `Source.key` for a party staged from a C64 disk, one of the three titles
#: `--convert` accepts; the same map `staged_disk` uses for its own container.
CONVERT_TITLE_KEYS = {"pool": "pool-of-radiance",
                      "curse": "curse-of-the-azure-bonds",
                      "ssb": "secret-of-the-silver-blades"}


def build_saveas_source(path: str | pathlib.Path, slot: str, out: pathlib.Path,
                        title: str, names: dict[int, str] | None = None) -> dict:
    """Copy `path` into `out` and Save As DOS whatever save `Source.detect`
    finds there at `slot`, refusing a source whose title is not `title`.

    `path` is a C64 disk image or an Amiga `.adf` holding any save
    `editor.convert.Source.detect` reads -- a Curse or Silver Blades save from
    either port, or an Amiga Pool of Radiance one.  A Pools of Darkness source
    is refused: `--amiga-slot` converts it through the Convert window's own
    route.  `names` maps a party position to the name chosen for that member,
    as the Shorten window hands them to `prepare_save_as`; without one, a name
    too long for DOS raises `saveplan.NamesDoNotFit`.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from editor import roster
    from editor.convert import Source

    src = pathlib.Path(path)
    data = src.read_bytes()
    copy = out / ("source" + src.suffix.lower())
    copy.write_bytes(data)
    report: dict = {"source_path": str(src),
                    "source_sha256": hashlib.sha256(data).hexdigest(),
                    "convert_slot": slot, "disk": copy.name}
    key = CONVERT_TITLE_KEYS[title]
    source = Source.detect(copy, slot=slot)
    if source.key != key:
        return {**report, "refused": f"{path} holds {source.key!r}, not "
                f"{title}'s {key!r}"}
    party = roster.Party(source)
    return _save_as_dos(party, out, title, report, names)


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
    `route_silver_blades.BARS` already classifies.
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
        #: Silver Blades' party-menu rows once a save is loaded.
        self.ssb_rows = dict(route_silver_blades.MENU_AFTER)
        #: Each roster line's sheet digest, once shown: two lines must never
        #: show the same sheet.
        self.sheets: dict[int, str] = {}
        #: Curse's `START.EXE` data segment, read once for `change`.
        self._class_ds: bytes | None = None

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
    def ssb(self) -> route_silver_blades.Route:
        """`route_silver_blades`'s Silver Blades route, numbering its shots with ours."""
        if self._ssb is None:
            self._ssb = route_silver_blades.Route(self.s, self.note)
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

    def after_rest(self, timeout: float, in_step: str) -> str | None:
        """Wait out a rest: the camp bar, or Pool's `GO STAY` answered with GO.

        Nothing but `GO` is ever pressed at the event.  A third event, any
        screen that is neither the camp bar, the event nor (after an event)
        the map, or a text window that stops changing for `REST_STALL`
        seconds away from the camp bar, ends the run.  In Curse, a message
        over the one-button continue bar `CURSE_CONTINUE_BAR` ends the wait
        with nothing pressed and returns `"message"` (Tilverton's Royal
        Guards: `ECL01` entry 2 sets the rest interruption everywhere west of
        x 5 or north of y 13).
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
                if (self.title.key == "curse" and answered == 0
                        and screen.glyphs(dosbox.BAR) == CURSE_CONTINUE_BAR):
                    return "message"
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

    def press_continue_screens(self, screen, bar, label, rounds=None):
        """Return past `bar`'s `PRESS <ENTER>/<RETURN> TO CONTINUE` screens, one
        at a time, at most `rounds` (default `CONTINUE_ROUNDS`), shared by
        Curse's BEGIN and Pool's load.

        Nothing is pressed when `bar` is not showing, so a screen that has
        already advanced is untouched.  Each Return pressed is recorded in
        `events` as `press_continue`.  Returns the settled screen.
        """
        rounds = CONTINUE_ROUNDS if rounds is None else rounds
        for _ in range(rounds):
            if screen.glyphs(dosbox.BAR) != bar:
                return screen
            shot = self.shot(f"continue-{label}")
            self.s.key(POD_CONTINUE)
            screen = self.s.settle(quiet=1.0, timeout=60.0)
            event = {"kind": "press_continue", "step": label, "shot": f"{shot}.png",
                     "bar": bar, "answered": POD_CONTINUE}
            self.events.append(event)
            self.note(event="question", **event)
        if screen.glyphs(dosbox.BAR) == bar:
            raise self.fail(f"{label}-continue", "a continue screen is still showing "
                            f"after {rounds} were answered")
        return screen

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
            screen = self.press_continue_screens(self.s.capture(), POOL_CONTINUE_BAR, "load",
                                                 POOL_LOAD_CONTINUE_ROUNDS)
            self.record_world(screen)
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
        if bar_signature(screen) != CURSE_PARTY_BAR:
            self.shot("lost-load")
            raise self.fail("load", f"slot {self.slot} did not leave the party "
                            f"menu's bar ({CURSE_PARTY_BAR}) showing: "
                            f"{bar_signature(screen)}")
        self.check_party_drawn(screen)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig}

    def check_party_drawn(self, screen: dosbox.Screen) -> None:
        """A loaded party menu draws a highlighted name at the roster; the empty
        menu draws none, though its command bar is the same."""
        if (roster_line(screen, "party", self.party_size) is None
                or roster_name(screen, "party", 1) == BLANK_NAME):
            raise self.fail("load", f"slot {self.slot} loaded no party: the "
                            "party menu draws no roster")

    def _load_ssb(self) -> dict:
        path = self.save_path(self.slot)
        self.ssb_rows = route_silver_blades.menu_after(
            path.read_bytes() if path.is_file() else None)
        self.ssb.to_party_menu(deadline=self.deadline)
        self.ssb.menu(SSB_LOAD_ROW, "load")
        if not self.s.wait_for(lambda sc: self.ssb.bar(sc) != "party_menu", 20.0):
            raise self.fail("load", f"row {SSB_LOAD_ROW} of the party menu did "
                            "not open a slot list")
        self.s.settle(quiet=0.6, timeout=20.0)
        self.shot("load-which")
        if not self.press_screen_changes(self.slot.lower(), tries=1, wait=30.0):
            raise self.fail("load", f"slot {self.slot} never loaded")
        screen = self.ssb.wait_bar("party_menu", timeout=90.0, deadline=self.deadline)
        self.check_party_drawn(screen)
        self.party_sig = bar_signature(screen)
        self.shot("loaded")
        self.where = "party"
        return {"slot": self.slot, "party_menu": self.party_sig,
                "menu_rows": self.ssb_rows}

    def _load_pod(self) -> dict:
        """Past the titles to the party menu, `Load Saved Game`, then `POOLS`
        at `LOAD FROM WHERE?` and the slot letter, each pressed once and given
        30 seconds, so a key meant for one screen never lands on the next."""
        path = self.save_path(self.slot)
        self.pod_rows = pod_menu_after(path.read_bytes() if path.is_file() else None)
        answered = dospod.to_party_menu(self.s, deadline=self.deadline)
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
            self.ssb.menu(self.ssb_rows["begin"], "begin")
            self.ssb.intro(deadline=self.deadline)
        elif self.title.key == "darkness":
            self.pod_menu(self.pod_rows["begin"], "begin")
        elif not self.press_screen_changes(PARTY_BEGIN, tries=1, wait=30.0):
            raise self.fail("begin", "BEGIN ADVENTURING did not leave the party menu")
        screen = self.s.settle(quiet=1.0, timeout=60.0)
        if self.title.key == "curse":
            screen = self.press_continue_screens(screen, CURSE_CONTINUE_BAR, "begin")
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
        square = status_square(screen, status_column(self.title.key))
        screens.append({"shot": self.shot(label), "bar": bar_signature(screen),
                        "status": status, "square": square})
        return status, square

    def walk(self, route: str) -> dict:
        """From the loaded Pool or Curse map, turn around and step one square.

        A step is believed only when the `x,y` on the status line changes:
        the clock on the same line ticks on a wall's bump, and a line drawn
        for the first time differs from a blank one, so the whole strip says
        nothing about a step.  A blank line is never the starting reading.
        """
        if self.title.key in MOVE_KEYS and self.where == "map" and route == "1":
            return self._walk_one()
        if self.title.key not in ("pool", "curse") or self.where != "map" \
                or route != "MI":
            raise StepFailed("walk MI needs Pool's or Curse's map")

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

        The keys are `MOVE_KEYS`' for the title: Silver Blades leaves move mode
        with `e`, Pools of Darkness with `Escape`.

        The party is already facing as it was saved, so the first try is
        `Up`; past a wall it turns right and tries again, three turns at most.
        A step is believed only when the `x,y` on the status line changes,
        and a key that moved the roster highlight instead stops the run.
        """
        screens: list[dict] = []
        column = status_column(self.title.key)
        enter, leave = MOVE_KEYS[self.title.key]
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("walk-before", "the map bar is not showing")
        line = roster_line(map_screen, "camp", self.party_size)
        if line is None:
            raise self.fail("walk-roster", "no highlighted roster line on the "
                            "map to tell a roster move from a step")
        map_bar = self.world_sig
        try:
            self.s.key(enter)
            if not self.s.wait_while_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            settled = self.s.settle(quiet=0.6, timeout=30.0)
            if bar_signature(settled) == self.world_sig:
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            move_bar = bar_signature(settled)
            self.game.record_map(settled)
            origin = status_square(settled, column)
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
                square = status_square(screen, column)
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
            self.s.key(leave)
            if not self.s.wait_until_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-back", f"{leave} did not return "
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

    def turn(self, presses: int) -> dict:
        """Turn right `presses` times on the map and prove no square changed.

        The control of a walk: a turn moves the facing and never the square,
        so a run whose `read` then shows the saved place unchanged has shown
        that the walk's change was the step.  The party is left on the map, so
        `camp`, `save` and `read` may follow.
        """
        if self.where != "map":
            raise StepFailed("turn needs the loaded map")
        if self.title.key in ("pool", "curse"):
            return self._turn_pool(presses)
        if self.title.key in MOVE_KEYS:
            return self._turn_move(presses)
        raise StepFailed(f"turn is not driven in {self.title.key}")

    def _turn_pool(self, presses: int) -> dict:
        screens: list[dict] = []
        _, origin = self.map_status("turn-before", screens)
        if origin is None:
            raise self.fail("walk-status", "the status line is blank on the map, "
                            "so there is no starting square (a shop or an "
                            "arrival draws it later)")
        for n in range(1, presses + 1):
            label = f"walk-turn-{n}"
            self.check_deadline(label)
            if not self.game.turn_right():
                raise self.fail(label, "the map bar did not return after "
                                "turning (combat or an unknown screen)")
            _, square = self.map_status(label, screens)
            if square != origin:
                raise self.fail(label, "the square changed on a turn (or the "
                                "status line went blank)")
        return {"route": "turn", "turns": presses, "map_bar": self.world_sig,
                "square_before": origin, "square_after": origin,
                "screens": screens}

    def _turn_move(self, presses: int) -> dict:
        """Press MOVE, turn `presses` times, press EXIT (`MOVE_KEYS`' for the title).

        Move mode draws no status line on entry, so when it is blank the first
        turn's reading is the baseline and only the turns after it are
        compared; one turn alone then proves nothing and stops the run.
        """
        screens: list[dict] = []
        column = status_column(self.title.key)
        enter, leave = MOVE_KEYS[self.title.key]
        map_screen = self.s.capture()
        if not self.on_world(map_screen):
            raise self.fail("walk-before", "the map bar is not showing")
        line = roster_line(map_screen, "camp", self.party_size)
        if line is None:
            raise self.fail("walk-roster", "no highlighted roster line on the "
                            "map to tell a roster move from a turn")
        map_bar = self.world_sig
        try:
            self.s.key(enter)
            if not self.s.wait_while_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            settled = self.s.settle(quiet=0.6, timeout=30.0)
            if bar_signature(settled) == self.world_sig:
                raise self.fail("walk-move", f"the map bar did not change after "
                                f"{enter} (no move mode)")
            move_bar = bar_signature(settled)
            self.game.record_map(settled)
            origin = status_square(settled, column)
            screens.append({"shot": self.shot("walk-move"), "bar": move_bar,
                            "square": origin})
            compared = 0
            for n in range(1, presses + 1):
                label = f"walk-turn-{n}"
                self.check_deadline(label)
                if not self.game.turn_right():
                    raise self.fail(label, "the move bar did not return after "
                                    "turning")
                screen = self.s.settle(quiet=0.6, timeout=30.0)
                if bar_signature(screen) != move_bar:
                    raise self.fail(label, "the move bar did not return (combat "
                                    "or an unknown screen)")
                if roster_line(screen, "camp", self.party_size) != line:
                    raise self.fail("walk-roster", "the roster highlight moved: "
                                    "the key went to the roster selector")
                square = status_square(screen, column)
                screens.append({"shot": self.shot(label), "bar": move_bar,
                                "square": square})
                if square is None:
                    raise self.fail("walk-status", "the status line was blank "
                                    "after a turn")
                if origin is None:
                    origin = square
                elif square != origin:
                    raise self.fail(label, "the square changed on a turn")
                else:
                    compared += 1
            if not compared:
                raise self.fail("walk-status", "the status line was blank on "
                                "entering move mode, so one turn gives a starting "
                                "square and nothing to compare it with; ask for "
                                "two turns or more")
            if bar_signature(self.s.capture()) != move_bar:
                raise self.fail("walk-back", "not at the move bar to leave it")
            self.s.key(leave)
            if not self.s.wait_until_ink(dosbox.BAR, self.world_ink, 15.0):
                raise self.fail("walk-back", f"{leave} did not return "
                                "to the map bar")
            back = self.s.settle(quiet=0.6, timeout=30.0)
            screens.append({"shot": self.shot("walk-back"),
                            "bar": bar_signature(back)})
            return {"route": "turn", "turns": presses, "map_bar": map_bar,
                    "move_bar": move_bar, "square_before": origin,
                    "square_after": origin, "roster_line": line,
                    "screens": screens}
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
                raise self.fail(label, f"{presses} presses of {next_key} "
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

    def check_sheet(self, screen, line: int, want: str, label: str,
                    got: str | None = None) -> dict:
        """The sheet on `screen` is roster line `line`'s: its name cells match
        the roster's, and no other line's sheet has had this frame.  `got` is
        the sheet's name when the caller read it over fewer cells than
        `sheet_name` does."""
        if want == BLANK_NAME:
            raise self.fail(label, f"roster line {line} has no name drawn")
        got = sheet_name(screen) if got is None else got
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
        """Camp: roster line `line` highlighted, `VIEW`, and the sheet checked.

        The sheet's bar is read for whether it offers the heal and the cure
        (`sheet_offers`); the result and the `sheet` event carry both.
        """
        if self.title.key not in CAMP_SHEETS or self.camp_sig is None:
            raise StepFailed("sheet needs the camp of Curse, Silver Blades or "
                             "Pools of Darkness first")
        self.ensure_camp()
        moved = self.pick_line(line, "camp", f"select-{line}",
                               CAMP_ROSTER_NEXT[self.title.key])
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
        words = bar_words(screen)
        offers = sheet_offers(words, self.title.key)
        shot = self.shot(f"sheet-{line}")
        self.note(event="sheet", line=line, shot=f"{shot}.png",
                  words=[len(w) for w in words],
                  heal_offered=None if offers is None else offers["heal"],
                  cure_offered=None if offers is None else offers["cure"])
        return {"line": line, **moved, "sheet": shot, **checked,
                "words": [len(w) for w in words],
                "heal_offered": None if offers is None else offers["heal"],
                "cure_offered": None if offers is None else offers["cure"]}

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
        """Party menu, roster line `line`'s sheet, and back to the party menu.

        Pools of Darkness and Silver Blades open `PICK CHARACTER` first (`View
        Character`, then `Down` to the member and the select key); Curse picks
        with `End` on the party menu itself and `v` views.  Pools of Darkness
        pages `ITEMS`; neither of the others does, as neither's `ITEMS` key is
        measured in this driver.  Nothing here writes a file.
        """
        if self.where != "party" or self.title.key not in VIEWS:
            raise StepFailed("view is the party-menu command of Curse, Silver "
                             "Blades and Pools of Darkness")
        if self.party_sig is None:
            raise StepFailed("view needs the party menu learnt by load")
        if self.title.key == "curse":
            return self._view_curse(line)
        if self.title.key == "ssb":
            return self._view_ssb(line)
        return self._view_pod(line)

    def _view_curse(self, line: int) -> dict:
        """No menu first: `End` moves the party menu's highlight and `v` opens
        the sheet, one press each, in three foundation boots.  The
        key back, `e`, is `dossheetread`'s default and unmeasured here."""
        moved = self.pick_line(line, "party", f"view-{line}-select", ROSTER_NEXT)
        want = roster_name(self.s.capture(), "party", line)
        self.shot(f"view-line-{line}")
        if not self.press_screen_changes(VIEW, tries=1, wait=15.0):
            raise self.fail(f"view-{line}", "VIEW changed nothing on the party menu")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"view-{line}-name")
        sheet = self.shot(f"view-{line}-sheet")
        self.back_to_party(f"view-{line}-back")
        self.shot(f"view-{line}-back")
        return {"line": line, **moved, "sheet": sheet, **checked, "pages": []}

    def _view_ssb(self, line: int) -> dict:
        """`VIEW CHARACTER` (row 3, or 5 with training on the menu), `PICK
        CHARACTER` (`Down` moves its highlight),
        then `s`, both answered in three foundation boots; `Return` also opens
        the sheet, unmeasured.  The sheet is judged by its name: its bar is not
        in `route_silver_blades.BARS`, so nothing here waits for a sheet bar."""
        self.ssb.menu(self.ssb_rows["view"], f"view-{line}")
        self.ssb.wait_bar("pick_character", 20.0)
        pick = self.shot(f"pick-{line}")
        moved = self.pick_line(line, "party", f"pick-{line}-select", POD_ROSTER_NEXT)
        want = roster_name(self.s.capture(), "party", line)
        self.shot(f"view-line-{line}")
        if not self.press_screen_changes(POD_PICK, tries=2, wait=15.0):
            raise self.fail(f"view-{line}", "SELECT at PICK CHARACTER changed nothing")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        checked = self.check_sheet(screen, line, want, f"view-{line}-name")
        sheet = self.shot(f"view-{line}-sheet")
        self.back_to_party(f"view-{line}-back")
        self.shot(f"view-{line}-back")
        return {"line": line, "pick": pick, **moved, "sheet": sheet, **checked,
                "pages": []}

    def _view_pod(self, line: int) -> dict:
        """Pools of Darkness: `View Character`, `PICK CHARACTER` over the roster
        (`GAME.OVR` 0x14536 via 0x26E25); `Down` moves the highlight a member on
        and `S` views that character (0x2452E), whose `Exit` returns to the
        party menu."""
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
        start = bar_signature(self.s.capture())
        if start not in POOL_MAP_BARS.values():
            raise self.fail(f"sheet-{line}-map", "the map bar is not showing")
        map_kind = next(k for k, bar in POOL_MAP_BARS.items() if bar == start)
        moved = self.pick_line(line, "camp", f"sheet-{line}-select", POOL_ROSTER_NEXT)
        name = roster_cells(self.s.capture(), line)
        if not name:
            raise self.fail(f"sheet-{line}-name", f"roster line {line} has no name drawn")
        self.s.key(VIEW)
        if not self.s.wait_for(lambda sc: bar_signature(sc) in POOL_SHEET_BARS.values(), 15.0):
            raise self.fail(f"sheet-{line}-open", "VIEW did not open the sheet bar")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        # An NPC's sheet draws ` (NPC)` after the name, so the name is
        # compared over its own cells and the blank one after it.
        count = min(len(name) + 1, POD_NAME_CELLS)
        want = _cell_digest((name + [_BLANK_CELL])[:count])
        got = _cell_digest(_cells(screen, *POD_SHEET_NAME, count))
        checked = self.check_sheet(screen, line, want, f"sheet-{line}-name", got=got)
        sheet = self.shot(f"sheet-{line}")
        self.s.key("Escape")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == start, 15.0):
            raise self.fail(f"sheet-{line}-back", "the map bar did not return "
                            "after Escape")
        back = self.s.capture()
        if roster_line(back, "camp", self.party_size) != line:
            raise self.fail(f"sheet-{line}-back", "the highlight is not on the "
                            "member the sheet showed")
        self.shot(f"sheet-{line}-back")
        return {"line": line, "map_kind": map_kind, **moved, "sheet": sheet, **checked}

    def sheet(self, line: int) -> dict:
        """Roster line `line`'s sheet from camp, shot, and back to camp."""
        if self.title.key == "pool":
            return self.pool_sheet(line)
        got = self.open_sheet(line)
        self.back_to_camp(f"sheet-{line}-back")
        return got

    def heal(self, line: int) -> dict:
        """Roster line `line` lays on hands: `HEAL` (`LAY`) on his camp sheet,
        `SELECT` at `HEAL WHOM?`, and back to camp.

        The target is the member the prompt opens on (Curse's is the party's
        first).  The game adds the timer to the paladin whoever the target
        is.  The step is believed only when the sheet comes back without the
        word, which is the game's own reading that the use is spent.
        """
        return self._sheet_act(line, "heal")

    def cure(self, line: int) -> dict:
        """Roster line `line` cures disease: `CURE` on his camp sheet, `SELECT`
        at `CURE WHOM?`, `YES` to `CURE ANYWAY` if it is asked, and back to
        camp.  The sheet must come back, with or without `CURE` (it stays
        while uses are left)."""
        return self._sheet_act(line, "cure")

    def _sheet_act(self, line: int, act: str) -> dict:
        word = "LAY" if act == "heal" and self.title.key == "darkness" else act.upper()
        got = self.open_sheet(line)
        label = f"{act}-{line}"
        before = bar_words(self.s.capture())
        at = acted_word(before, self.title.key, act)
        if not got[f"{act}_offered"] or at is None:
            raise self.fail(label, f"roster line {line}'s sheet does not offer "
                            f"{word}, so it is not pressed")
        without = before[:at] + before[at + 1:]
        if not self.press_screen_changes(SHEET_KEYS[self.title.key][act], tries=1,
                                         wait=15.0):
            raise self.fail(label, f"{word} changed nothing on the sheet")
        prompt = self.s.settle(quiet=0.8, timeout=30.0)
        prompt_shot = self.shot(f"{label}-prompt")
        if bar_words(prompt) in (before, without):
            raise self.fail(label, f"{word} left a sheet bar showing, not the "
                            f"{word} WHOM? prompt")
        self.s.key(PICK_SELECT)
        answered: list[str] = []
        end = time.time() + self.bounded(SHEET_BACK_SECONDS, label)
        while True:
            self.check_deadline(label)
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            words = bar_words(screen)
            if words == without or (act == "cure" and words == before):
                break
            if act == "heal" and words == before:
                raise self.fail(label, f"the sheet came back still offering {word}: "
                                "SELECT did not spend the use")
            if act == "cure" and not answered and yes_no_words(words):
                self.shot(f"{label}-anyway")
                self.s.key(CURE_ANYWAY)
                answered.append(CURE_ANYWAY)
                continue
            if time.time() > end:
                raise self.fail(label, f"the sheet never came back after SELECT at "
                                f"{word} WHOM?")
            time.sleep(0.3)
        after = sheet_offers(words, self.title.key) or {}
        back = self.shot(f"{label}-sheet-after")
        self.back_to_camp(f"{label}-back")
        return {**got, "act": act, "prompt": prompt_shot, "answered": answered,
                "sheet_after": back, "words_after": [len(w) for w in words],
                "heal_offered_after": after.get("heal"),
                "cure_offered_after": after.get("cure")}

    def pool_items(self, line: int) -> dict:
        """Pool: roster line `line`'s `ITEMS` list from camp, and back to camp.

        `End` to the line, `v`, `i`, then `Escape` twice; never `e`, which on
        Pool's camp bar is Exit.  Only the list's first screen is read: Pool's
        paging key and row key are unmeasured, so a list that fills the
        readable rows stops the run instead of guessing.  `marked` is the
        rows (from 1) whose cell at `POOL_ITEM_MARK_X` is `POOL_ITEM_MARK`.
        """
        if self.title.key != "pool" or self.camp_sig is None:
            raise StepFailed("items needs Pool camp first")
        self.ensure_camp()
        label = f"items-{line}"
        moved = self.pick_line(line, "camp", f"{label}-select", POOL_ROSTER_NEXT)
        name = roster_cells(self.s.capture(), line)
        if not name:
            raise self.fail(f"{label}-name", f"roster line {line} has no name drawn")
        self.s.key(VIEW)
        if not self.s.wait_for(lambda sc: bar_signature(sc) in POOL_SHEET_BARS.values(), 15.0):
            raise self.fail(f"{label}-open", "VIEW did not open the sheet bar")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        count = min(len(name) + 1, POD_NAME_CELLS)
        want = _cell_digest((name + [_BLANK_CELL])[:count])
        got = _cell_digest(_cells(screen, *POD_SHEET_NAME, count))
        checked = self.check_sheet(screen, line, want, f"{label}-name", got=got)
        sheet_bar = bar_signature(screen)
        if sheet_bar == POOL_SHEET_BARS["no_items"]:
            raise self.fail(f"{label}-sheet", f"roster line {line}'s sheet offers no ITEMS")
        self.shot(f"{label}-sheet")
        self.s.key(SHEET_ITEMS)
        if not self.s.wait_for(on_items_list, 15.0):
            raise self.fail(f"{label}-list", "ITEMS did not open Pool's list bar")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        if not on_items_list(screen):
            raise self.fail(f"{label}-list", "the list bar did not stay")
        rows = item_rows(screen)
        if not rows or rows >= ITEM_ROWS:
            raise self.fail(f"{label}-rows", f"the list reads {rows} rows; one that "
                            f"fills {ITEM_ROWS} may have a next page, unmeasured")
        marked = [k + 1 for k in range(rows) if hashlib.sha1(screen.glyphs(
            (POOL_ITEM_MARK_X, 40 + CELL * k, CELL, CELL)).encode()
        ).hexdigest()[:16] == POOL_ITEM_MARK]
        list_shot = self.shot(f"{label}-list")
        self.s.key("Escape")
        if not self.s.wait_for(lambda sc: bar_signature(sc) == sheet_bar, 15.0):
            raise self.fail(f"{label}-sheet-back", "the sheet did not return after Escape")
        self.s.key("Escape")
        if not self.wait_camp(timeout=15.0):
            raise self.fail(f"{label}-back", "the camp bar did not return after the "
                            "second Escape")
        return {"line": line, **moved, **checked, "list_shot": list_shot, "rows": rows,
                "marked": marked}

    def items(self, line: int) -> dict:
        """Roster line `line`'s `ITEMS` from its sheet, every page shot.

        `Next` is pressed until it changes nothing or brings back the first
        page; `ITEMS_PAGES` pages that are all different stop the run.
        """
        if self.title.key == "pool":
            return self.pool_items(line)
        got = self.open_sheet(line)
        pages = self.item_pages(f"items-{line}")
        self.back_to_camp(f"items-{line}-back")
        return {**got, "pages": pages}

    def pick_item(self, row: int, label: str) -> dict:
        """Move the `ITEMS` highlight onto row `row` (from 1), from where it is.

        Read, never counted, as `pick_line` does: `item_highlight` after every
        `ITEM_NEXT_ROW`, and a press is believed only when it moves.  The
        list opens on row 1 (37 of 37 captures).  Only forward is pressed:
        whether the highlight wraps is unmeasured.  Two presses in a row that
        leave it where it was, or more than `2 * ITEM_ROWS` presses, stop the
        run.
        """
        rows = item_rows(self.s.capture())
        here = item_highlight(self.s.capture())
        if rows is None or here is None:
            raise self.fail(label, "no ITEMS row is drawn highlighted")
        if row > rows:
            raise self.fail(label, f"row {row} is past the list's {rows} rows")
        want = row - 1
        if here > want:
            raise self.fail(label, f"the highlight is on row {here + 1}, past "
                            f"row {row}, and only {ITEM_NEXT_ROW} is pressed")
        presses = still = 0
        while here != want:
            if presses >= 2 * ITEM_ROWS:
                raise self.fail(label, f"{presses} presses of {ITEM_NEXT_ROW} "
                                f"never brought the highlight to row {row}")
            self.s.key(ITEM_NEXT_ROW)
            presses += 1
            was = here
            self.s.wait_for(lambda sc, was=was: item_highlight(sc) != was, 5.0)
            here = item_highlight(self.s.capture())
            if here is None:
                raise self.fail(label, "the ITEMS highlight went away")
            still = still + 1 if here == was else 0
            if still >= 2:
                raise self.fail(label, f"{ITEM_NEXT_ROW} did not move the ITEMS "
                                f"highlight off row {here + 1}")
        return {"presses": presses}

    def _item_command(self, line: int, row: int, key: str, verb: str,
                      grow: int) -> dict:
        """Member `line`'s `ITEMS`, row `row` highlighted, `key` pressed once,
        and the rows counted before and after; back to camp.

        With `grow` (`halve`), a list under `ITEM_ROWS` rows must gain a row
        and keep its highlight, or the run stops on the `ITEMS` screen, before
        any save.  `join` only records: whether a scroll joins is what the run
        is for.
        """
        got = self.open_sheet(line)
        label = f"{verb}-{line}-{row}"
        if not self.press_screen_changes(SHEET_ITEMS, tries=1, wait=15.0):
            raise self.fail(label, "ITEMS changed nothing on the sheet")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        moved = self.pick_item(row, f"{label}-select")
        self.shot(f"{label}-before")
        rows_before = item_rows(self.s.capture())
        highlight_before = item_highlight(self.s.capture())
        if grow and rows_before == ITEM_ROWS:
            raise self.fail(f"{label}-rows", f"the list already draws {ITEM_ROWS} "
                            f"rows, and what {verb} does to a full list is not "
                            f"measured, so {key} is not pressed")
        self.s.key(key)
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        rows_after, highlight_after = item_rows(screen), item_highlight(screen)
        after = self.shot(f"{label}-after")
        if grow and rows_before < ITEM_ROWS and (
                rows_after != rows_before + grow
                or highlight_after != highlight_before):
            raise self.fail(f"{label}-rows", f"{verb} left {rows_after} rows with "
                            f"the highlight on {highlight_after}, from {rows_before} "
                            f"rows with it on {highlight_before}")
        self.back_to_camp(f"{label}-back")
        return {**got, "row": row, "presses": moved["presses"],
                "rows_before": rows_before, "rows_after": rows_after,
                "highlight_before": highlight_before,
                "highlight_after": highlight_after, "after": after}

    def halve(self, line: int, row: int) -> dict:
        """`HALVE` member `line`'s item `row`; a new row must appear after it."""
        return self._item_command(line, row, ITEM_HALVE, "halve", grow=1)

    def join(self, line: int, row: int) -> dict:
        """`JOIN` member `line`'s item `row`; the row counts are recorded.

        Measured: JOIN acts at once with no prompt, and the row counts before
        and after.  Not measured: which row JOIN merges the item with, so this
        does not check the pair; the live run records it.
        """
        return self._item_command(line, row, ITEM_JOIN, "join", grow=0)

    def memorize(self, line: int) -> dict:
        """Roster line `line`'s grimoire from camp, every page shot and read,
        and back to camp with nothing memorized.

        `Magic` is pressed a second time only while the camp bar is still
        showing, and `Memorize` once: a second one on the grimoire would
        memorize the highlighted spell.  `lists_126` is whether any page draws
        the `MONSTER SUMMONING` row, id 126, which the game lists only when
        record byte `POD_BOOK_126` is set.
        """
        if self.title.key != "darkness" or self.camp_sig is None:
            raise StepFailed("memorize needs Pools of Darkness' camp first")
        self.ensure_camp()
        label = f"memorize-{line}"
        moved = self.pick_line(line, "camp", f"{label}-select")
        name = roster_cells(self.s.capture(), line)
        self.shot(f"{label}-line")
        for _ in range(2):
            self.s.key(POD_MAGIC)
            if self.s.wait_for(lambda sc: bar_signature(sc) == POD_MAGIC_BAR, 15.0):
                break
            if not self.in_camp():
                raise self.fail(f"{label}-magic", "MAGIC opened a screen that is not "
                                "the Magic bar")
        else:
            raise self.fail(f"{label}-magic", "the camp bar is still showing after "
                            "MAGIC")
        magic = self.shot(f"{label}-magic")
        self.s.key(POD_MEMORIZE)
        if not self.s.wait_for(on_grimoire, 20.0):
            raise self.fail(f"{label}-open", "MEMORIZE did not open a grimoire (a "
                            "character with no spell to memorize, or a screen this "
                            "driver does not know)")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        if not grimoire_is_for(screen, name):
            raise self.fail(f"{label}-name", f"the grimoire's title is not roster "
                            f"line {line}'s name")
        pages = self.grimoire_pages(label, screen)
        self.back_from_magic(f"{label}-back")
        back = self.shot(f"{label}-back")
        rows = [r for p in pages for r in p["rows"]]
        return {"line": line, **moved, "magic": magic, "pages": pages, "back": back,
                "lists_126": SPELL_126_ROW in rows,
                "ninth_level": ninth_level(pages[-1]["rows"])}

    def grimoire_pages(self, label: str, screen) -> list[dict]:
        """Every page of the open grimoire, turned with `Next` until the bar
        stops offering it.

        A `Next` that changes nothing on a bar that offers `NEXT` is pressed
        once more, since a swallowed key would otherwise end the list early
        and hide the rows after it; a second one that changes nothing, a page
        that is not the grimoire, or `GRIMOIRE_PAGES` pages, stop the run.
        """
        pages: list[dict] = []
        while True:
            pages.append({"shot": self.shot(f"{label}-page-{len(pages) + 1}"),
                          "bar": bar_signature(screen), "digest": screen.digest(),
                          "rows": grimoire_rows(screen)})
            offers_next = bar_signature(screen) in POD_GRIMOIRE_NEXT_BARS
            if not offers_next:
                return pages
            if len(pages) >= GRIMOIRE_PAGES:
                raise self.fail(f"{label}-pages", f"{GRIMOIRE_PAGES} pages and the "
                                "bar still offers NEXT")
            before = screen.digest()
            for _ in range(2):
                self.s.key(POD_GRIMOIRE_NEXT)
                if self.s.wait_for(lambda sc: sc.digest() != before, 5.0):
                    break
            else:
                raise self.fail(f"{label}-next", "NEXT changed nothing on a page "
                                "whose bar offers it")
            screen = self.s.settle(quiet=0.8, timeout=30.0)
            if not on_grimoire(screen):
                raise self.fail(f"{label}-next", "NEXT left the grimoire")

    def back_from_magic(self, label: str, tries: int = 4) -> None:
        """`Exit` from the grimoire to the Magic bar and from there to camp,
        looking before every press: it is never pressed on the camp bar, which
        it would break, nor on any screen other than those two."""
        for _ in range(tries):
            screen = self.s.capture()
            if self.in_camp(screen):
                return
            bar = bar_signature(screen)
            if not (on_grimoire(screen) or bar == POD_MAGIC_BAR):
                raise self.fail(label, "a screen that is neither the grimoire, the "
                                "Magic bar nor camp")
            self.s.key(LEAVE)
            self.s.wait_for(lambda sc: bar_signature(sc) != bar, 10.0)
        if not self.wait_camp(timeout=15.0):
            raise self.fail(label, f"the camp bar never came back after {tries} "
                            "presses of Exit")

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
        """Rest for `minutes`, or until an event ends it early.

        When the returned `ended_by_message` is true, `"asked"` is the
        minutes requested, not how long the party actually rested -- that
        duration is in the clock of the next save, per `rest_message`.
        """
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
        ended = self.after_rest(60.0 + 2.0 * passes, f"rest {minutes}m")
        if ended == "message":
            self.rest_message()
        self.shot("rested")
        return {"asked": minutes, "zero_presses": zeroed, **presses,
                "left_camp": self.left_camp, "ended_by_message": ended == "message"}

    def rest_message(self) -> None:
        """Curse: `Return` past the continue screens that ended a rest, the map
        bar required, and `ENCAMP` again, so the step always ends in camp.  How
        long the party rested is in the clock of the next save, not here."""
        screen = self.press_continue_screens(self.s.capture(), CURSE_CONTINUE_BAR, "rest")
        if not (self.on_world(screen)
                or self.s.wait_for(self.on_world, self.bounded(30.0, "rest-map"))):
            raise self.fail("rest-map", "the map bar did not come back after the "
                            "message that ended the rest")
        self.camp()

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

    def cast(self, line: int, spell: str, target: int | None = None) -> dict:
        """Roster line `line` casts `spell` in Pool's camp, on roster line
        `target` when the spell asks for one, and the party is back in camp.

        The screens are `dosbox.PoolOfRadiance.cast`'s; any it does not know
        stops the run with a `lost-cast-*` shot and nothing more pressed.
        """
        if self.title.key != "pool" or self.camp_sig is None:
            raise StepFailed("cast needs Pool camp first")
        self.ensure_camp()
        label = f"cast-{line}"
        moved = self.pick_line(line, "camp", f"{label}-select", POOL_ROSTER_NEXT)
        name = roster_cells(self.s.capture(), line)
        self.shot(f"{label}-line")
        try:
            got = self.game.cast(spell, target or None, party_size=self.party_size,
                                 caster=name, shot=self.shot)
        except dosbox.WrongCaster:
            raise self.fail(label, f"the spell list's title is not roster line "
                                   f"{line}'s name") from None
        except TimeoutError as e:
            raise self.fail(label, str(e)) from None
        if not self.wait_camp(timeout=15.0):
            raise self.fail(f"{label}-back", "the camp bar did not stay after EXIT")
        return {"line": line, **moved, **got, "back": self.shot(f"{label}-back")}

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
            self.ssb.menu(self.ssb_rows["save"], "save")
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

    def class_segment(self) -> bytes:
        """Curse's `START.EXE` data segment, from the game this session runs."""
        if self._class_ds is None:
            self._class_ds = class_tables((self.s.source / "START.EXE").read_bytes())
        return self._class_ds

    def change(self, line: int, wanted: str) -> dict:
        """Roster line `line`'s `HUMAN CHANGE CLASSES` to `wanted`, back to the
        party menu.

        Which row holds `wanted` comes from the engine's own test run over
        his installed record and `START.EXE`'s tables (`class_choices`), and
        is checked on the screen before anything is taken: the rows `End`
        reaches from where the list opens must be exactly as many as the
        classes the test allows, or the run stops with the list showing.  The
        game then prints its message and returns to the party menu on its own
        (0x3BE60, a timed wait), with no `YES NO` in the routine.
        """
        if self.where != "party" or self.title.key != "curse":
            raise StepFailed("change is Curse's party-menu command")
        label = f"change-{line}"
        record = self.s.save_dir / f"CHRDAT{self.slot}{line}.SAV"
        if not record.is_file():
            raise StepFailed(f"line {line} has no {record.name} to read his classes from")
        choices = class_choices(record.read_bytes(), self.class_segment())
        names = [name for _, name in choices]
        self.note(event="class_choices", line=line, choices=names)
        if not names:
            raise StepFailed(f"line {line} is not offered HUMAN CHANGE CLASSES: he is "
                             "not human, has changed class before, or qualifies "
                             "for no class")
        if wanted not in names:
            raise StepFailed(f"line {line} may not change to {wanted}: the engine's "
                             f"test allows {', '.join(names)}")
        moved = self.pick_line(line, "party", f"{label}-select", ROSTER_NEXT)
        self.shot(f"{label}-line")
        if not self.press_screen_changes(PARTY_CHANGE, tries=1, wait=15.0):
            raise self.fail(label, f"HUMAN CHANGE CLASSES changed nothing for line "
                            f"{line} (the hall is shut: stage --hall)")
        screen = self.s.settle(quiet=0.8, timeout=30.0)
        base = screen.highlight_row(CHANGE_LIST)
        if base is None or self.on_party_menu(screen):
            raise self.fail(label, "no class list with a highlighted row opened")
        self.shot(f"{label}-list")
        rows, stuck = [base], 0
        while len(rows) <= CHANGE_ROWS:
            self.s.key(dosbox.LIST_DOWN)
            now = self.s.settle(quiet=0.5, timeout=20.0).highlight_row(CHANGE_LIST)
            if now == base:
                break
            if now is None or now == rows[-1]:
                stuck += 1
                if now is None or stuck >= 2:
                    break
                continue
            stuck = 0
            rows.append(now)
        if rows != list(range(base, base + len(rows))) or len(rows) != len(names):
            raise self.fail(label, f"the list's highlight reached rows {rows} from "
                            f"row {base}, not the {len(names)} consecutive rows of "
                            f"{', '.join(names)}")
        want = base + names.index(wanted)
        here = self.s.capture().highlight_row(CHANGE_LIST)
        key = dosbox.LIST_DOWN if here is not None and here <= want else dosbox.LIST_UP
        if self.s.walk_highlight(CHANGE_LIST, want, key=key) != want:
            raise self.fail(label, f"the list's highlight never reached row {want}")
        picked = self.shot(f"{label}-{wanted.lower()}")
        self.s.key(PICK_SELECT)
        if not self.wait_party_menu(60.0):
            raise self.fail(f"{label}-back", "the party menu never came back after "
                            f"SELECT on {wanted}")
        self.shot(f"{label}-back")
        return {"line": line, **moved, "class": wanted, "choices": names,
                "rows": rows, "row": want, "picked": picked}


@contextlib.contextmanager
def deferred_sigterm():
    """Hold SIGTERM back for the body; a signal that arrived is delivered after it."""
    if not hasattr(signal, "pthread_sigmask"):
        yield
        return
    old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


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
    git = evidence.git_state(REPO)
    title = TITLES[args.title]
    out = (pathlib.Path(args.out) if args.out
           else evidence.default_out(args.issue, args.run, git["sha"]))
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
    elif getattr(args, "convert", None):
        shutil.rmtree(out / "source", ignore_errors=True)
        chosen = parse_names(args.name, args.title) if args.name else None
        built = build_saveas_source(args.convert, args.convert_slot.upper(), out,
                                    args.title, chosen)
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
    if from_slot not in (None, letter):
        raise ValueError(f"{args.title} loads the party its SAVGAM{from_slot} "
                         f"names: pass --slot {from_slot}")
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
        # A SIGTERM between the lease and its release callback would leave the
        # slot leased: hold it back until the callback is registered.
        with deferred_sigterm():
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
            took = install(save, session.save_dir, letter, from_slot)
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
                elif step.kind == "turn":
                    r = d.turn(step.line)
                elif step.kind == "rest":
                    r = d.rest(step.minutes)
                elif step.kind == "display":
                    r = d.display()
                elif step.kind == "cast":
                    r = d.cast(step.line, step.name, step.row or None)
                elif step.kind == "save":
                    r = d.save(step.letter)
                    saved.append(step.letter)
                elif step.kind == "train":
                    r = d.train(step.line)
                elif step.kind == "change":
                    r = d.change(step.line, step.name)
                elif step.kind == "sheet":
                    r = d.sheet(step.line)
                elif step.kind == "heal":
                    r = d.heal(step.line)
                elif step.kind == "cure":
                    r = d.cure(step.line)
                elif step.kind == "items":
                    r = d.items(step.line)
                elif step.kind == "halve":
                    r = d.halve(step.line, step.row)
                elif step.kind == "join":
                    r = d.join(step.line, step.row)
                elif step.kind == "view":
                    r = d.view(step.line)
                elif step.kind == "memorize":
                    r = d.memorize(step.line)
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
            unproved = (walk_verdict(steps, summary.get("read"))
                       or share_verdict(summary.get("read")))
            if unproved:
                summary["lost"] = unproved
                note(event="lost", why=unproved)
            else:
                summary["completed"] = True
        except (StepFailed, route_silver_blades.RouteLost) as e:
            summary["lost"] = str(e)
            note(event="lost", why=str(e))
        except (KeyboardInterrupt, SystemExit) as e:
            # Recorded and passed on: the ExitStack still writes the summary.
            why = f"{type(e).__name__}({str(e)!r})"
            summary["lost"] = why
            note(event="lost", why=why)
            raise
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

    `--hall` is measured for the titles in `HALL_TITLES`
    (`docs/194-the-dos-training-ladder.md`); another title's `SAVGAM` is not
    known to hold the hall word at that offset.  `--xp` and `--add-node` need
    the line's own `CHRDAT` file.
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
    records = parse_record_bytes(getattr(args, "stage_record", []) or [])
    lines = ([parse_xp(t)[0] for t in getattr(args, "xp", []) or []]
             + [parse_node(t)[0] for t in getattr(args, "add_node", []) or []]
             + [parse_control(t)[0] for t in getattr(args, "stage_control", []) or []]
             + [r[0] for r in records])
    for line in lines:
        want = f"CHRDAT{from_slot}{line}.SAV"
        if want not in names:
            raise ValueError(f"line {line} has no {want} in {save}")
    for line, offset, _ in records:
        record = next(p for p in save.iterdir()
                      if p.name.upper() == f"CHRDAT{from_slot}{line}.SAV")
        if offset >= record.stat().st_size:
            raise ValueError(f"--stage-record offset {offset:#x} is outside "
                             f"{record.name}, which is {record.stat().st_size} bytes")


def stage(save_dir: pathlib.Path, letter: str, args) -> list[dict]:
    """The `--hall`, `--xp`, `--add-node`, `--stage-control` and `--stage-record`
    stages, in that order."""
    done = []
    if getattr(args, "hall", False):
        done.append(stage_hall(save_dir, letter))
    for text in getattr(args, "xp", []) or []:
        done.append(stage_xp(save_dir, letter, *parse_xp(text)))
    for text in getattr(args, "add_node", []) or []:
        done.append(stage_node(save_dir, letter, *parse_node(text)))
    for text in getattr(args, "stage_control", []) or []:
        done.append(stage_control(save_dir, letter, *parse_control(text)))
    for line, offset, value in parse_record_bytes(getattr(args, "stage_record", []) or []):
        done.append(stage_record(save_dir, letter, line, offset, value))
    return done


def place_changed(before: dict, after: dict) -> bool:
    """Whether the square or the map differs between two slots' places."""
    a, b = before.get("place") or {}, after.get("place") or {}
    keys = ("x", "y", "area") if "area" in a else ("x", "y", "dungeon_map")
    return any(a.get(k) != b.get(k) for k in keys)


def share_verdict(read: dict | None) -> str | None:
    """Why a saved character's control or treasure-share byte no longer
    matches what was installed, or None.

    `compare_shares` runs on every read step; this is what fails the run when
    either byte drifted between the installed slot and the engine-written one.
    """
    if read is None:
        return None
    for x, slot in (read.get("slots") or {}).items():
        for row in slot.get("shares", []):
            if row["present"] and not row["matches"]:
                return (f"{row['name']}'s control or treasure_share changed in "
                        f"slot {x}: control {row['control_before']} -> "
                        f"{row['control_after']}, share {row['share_before']} -> "
                        f"{row['share_after']}")
    return None


def walk_verdict(steps: list[Step], read: dict | None) -> str | None:
    """Why a run that asked for a walk or a turn has not shown it, or None.

    The proof is the place decoded from the game-written save, the same in
    every title: after a walk the last save the run made must not be at the
    square the installed one was; after `turn` steps alone, the control, it
    must be.  A place that was not computed proves nothing.
    """
    walked = any(s.kind == "walk" for s in steps)
    if not walked and not any(s.kind == "turn" for s in steps):
        return None
    asked = "a walk" if walked else "a turn"
    if read is None:
        return (f"{asked} was asked and no read step decoded a saved place, so "
                "nothing shows " + ("the party moved" if walked else "it did not move"))
    slots = read.get("slots") or {}
    order = [x for x in read.get("saved") or [] if x in slots] or list(slots)
    if not order:
        return (f"{asked} was asked and no saved slot was read, so nothing shows "
                + ("the party moved" if walked else "it did not move"))
    last = order[-1]
    slot = slots[last]
    if "place_changed" not in slot or "x" not in (slot.get("place") or {}):
        return (f"{asked} was asked and slot {last}'s place was not computed "
                f"({(slot.get('place') or {}).get('error', 'no place read')})")
    if walked and not slot["place_changed"]:
        return (f"the walk did not move the party: the game-written slot {last} "
                "is at the square the installed slot was")
    if not walked and slot["place_changed"]:
        return (f"the turn moved the party: the game-written slot {last} is not "
                "at the square the installed slot was")
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
            "shares": compare_shares(before, after),
        }
        if any(st.kind in ("walk", "turn") for st in steps):
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
                f"{row['movement']['after']}, moving "
                f"{row['movement_current']['after']}, byte 0x130 "
                f"{row['book_0x130']['after']}; "
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
    src.add_argument("--convert", default=None, metavar="PATH",
                     help="a C64 .D64 or Amiga .adf holding a pool, curse or "
                          "ssb save; convert it with Save As DOS first "
                          "(not darkness: use --amiga-slot)")
    ap.add_argument("--name", action="append", default=[], metavar="POSITION=NAME",
                    help="with --convert: the name for the party member at "
                         "POSITION (0 is the first), as the Shorten window "
                         "would give it; repeatable")
    ap.add_argument("--amiga-disk", default=None,
                    help="with --amiga-slot: an .adf path, or the end of one "
                         "Amiga disk label ('Pools Of Darkness.zip!Pools of "
                         "Darkness3.adf')")
    ap.add_argument("--convert-slot", default="A",
                    help="with --convert: the source's own save slot letter "
                         "(default A)")
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
    ap.add_argument("--stage-control", action="append", default=[],
                    metavar="LINE=CONTROL[:SHARE]",
                    help="stage roster line LINE's field_83_87 control byte, "
                         "and optionally the treasure-share byte after it, "
                         "before the boot")
    ap.add_argument("--stage-record", action="append", default=[],
                    metavar="LINE:OFFSET=VALUE",
                    help="stage one byte of roster line LINE's CHRDAT record "
                         "(decimal or 0x hex, comma-separated or repeated), "
                         "after --stage-control, before the boot")
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
                         f"`timeout -k 30` (a plain `timeout` sends SIGTERM only) "
                         f"set at least {WRAPPER_MARGIN:.0f} s longer")
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
        if args.convert:
            if args.title == "darkness":
                raise ValueError("--convert converts a pool, curse or ssb save: "
                                 "Pools of Darkness has none of those; use "
                                 "--amiga-slot")
            if not re.fullmatch(r"[A-Ja-j]", args.convert_slot):
                raise ValueError("--convert-slot is one letter, A to J")
            parse_names(args.name, args.title)
        elif args.name:
            raise ValueError("--name goes with --convert")
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
