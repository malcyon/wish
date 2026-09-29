#!/usr/bin/env python3
"""Stage a C64 save, load it in the game, and read back what a conversion must preserve.

The C64 driver of `docs/235-destination-game-acceptance-runs.md` (D2).  It
writes effect rows, trait slots and item bytes into a **copy** of a save disk,
boots it on a pooled VICE slot, headless and silent, and runs a step list,
reading the screen and the machine as it goes:

    tools/c64/acceptance.py --title pool --save PORSAVE13.D64 \\
        --stage-row 63=05:FF:0A:03 --stage-item 1:2:4=1 \\
        --checkpoint 408F=detect-matched \\
        --steps load camp-list 'items LADY KATHERINE' 'rest 8h' save \\
        --issue N --run party-row

Staging is an input, written before the boot and never after the load:

* `--stage-row SLOT=ID:OWNER:DURATION:MAGNITUDE`, hex, the four effect arrays
  through `goldbox.effects.write_effect` (the same payload offsets in all
  three titles);
* `--stage-trait SLOT:INDEX=ID`, the ten trait slots at record `0x0AD`, as
  `tools/c64/traitdrive.py` writes them;
* `--stage-item SLOT:ITEM:OFFSET=VALUE`, one byte of one item record; `+4`
  is the bonus byte Detect Magic marks an item by;
* `--stage-record SLOT:OFFSET=VALUE`, one byte below `0x100` in a party record;
* `--stage-status SLOT=BYTE`, the roster status byte in the roster file or
  embedded roster, according to the title.

SLOT is the save slot, 0 first.  Every option repeats, and each is logged in
bytes with what it replaced.

| step | what it does and reads |
|---|---|
| `load` | boot, `LOAD SAVED GAME`, `BEGIN ADVENTURING`; arms every `--checkpoint` |
| `camp-list [WHO]` | `ENCAMP > MAGIC > DISPLAY`, then each name the game offers (or WHO alone, which may be `THE WHOLE PARTY`): the spells it lists as in effect, page by page |
| `items WHO`, `view WHO` | `VIEW` and the ITEMS list, or the sheet alone, as text, with each item's Detect Magic mark |
| `rest 5m`, `rest 8h`, `rest 1h30m` | camp `REST` for exactly that long (`tools/c64/route_pool.py`'s rest) |
| `walk MOVES` | I forward, J left, K right, M turns about and tries the edge behind the original facing -- one square back keeping that facing where the edge carries no wall art, or held turned about where it does -- each judged by `position()` before and after (Pool's status line holds the clock; Curse's and Silver Blades' lags a step, so they are judged by the live triple `$C04B`-`$C04D`, and their one retry too): `blocked` when a forward move left x,y alone, a turn (`J`/`K`) must leave the square and change the facing by its amount, and `M` must leave the square either where it started or one square behind, facing either as it started or exactly reversed; a move that brings up a disk prompt, or lands anywhere else, fails the walk |
| `fight [SECONDS]` | walk `--walk` until a fight starts, then fight it with `Session.melee_turn` for at most SECONDS (120); a fight still going when SECONDS end, or one the party loses, fails the step (the run cannot continue from it), and the checkpoint counts read at that point are kept as `lost_reading` in the summary |
| `cast CASTER:SPELL>TARGET` | Curse: `ENCAMP > MAGIC > CAST`, the one spell named, on TARGET; the target's row of the cured id before and after (`CURE BLINDNESS`) |
| `cast CASTER:ANIMATE DEAD` | Pool: camp cast without a target prompt; every party slot's roster status, trait slots, creature byte `0xD7`, and the effect arrays before and after |
| `cast CASTER:DISPEL MAGIC>TARGET` | Pool: checks the named caster, animated target and its eligible id-32 row at index 63 before input; captures the target prompt, all party and effect-row bytes before and after, and checks the game-written save. `--preserve-specimen --issue 700` registers that save or a matched no-cast BRUTUS view control before teardown |
| `cure PALADIN>TARGET` | Curse only: `ENCAMP > VIEW > CURE` on TARGET (the paladin's cure of disease), the same before and after |
| `ready WHO>LABEL` | Pool only: `ENCAMP > VIEW WHO > ITEMS`, press READY once for LABEL, and read every party record, effect row and item block before and after. `screen_changed` describes the item row; `memory_changed` describes bytes in those three ranges; legacy `flipped` keeps its screen-only meaning. `--capture-ready` saves three bounded in-list checkpoints for BAKSHI and registers the game-written save before teardown |
| `walk-fight MOVES[/NO]` | Pool only: `walk`'s moves, but an encounter menu is answered COMBAT (never FLEE), the fight is fought out with `Session.melee_turn` (900 s each), and the route resumes from the square the fight left the party on, an `I` that did not complete being sent once more; a forward move must land on the next square, else the step fails as blocked or as an exit or a teleport. A `YES NO` is answered NO only on the last key, and only when `/NO` is given; anywhere else it fails the step with nothing pressed. With a `save` after it, the summary's `drain` says whether some character's level fell by 1 or 2 with `levels_drained` equal to the fall, `hp_lost_to_drain` not zero, one class level down by the same amount and `hp_max` down by `hp_lost_to_drain`; nobody drained is recorded, not a failure |
| `warp AREA` | Pool only: fast-travel the loaded party into area AREA (the writes and jump of `automap.actions.FastTravel`, no arrival square), wait for the key-wait loop, and fail unless the live facing byte `$C04D` is the one the area's arrival script sets (area 10: 1, east); returns the writes and the triple `$C04B`-`$C04D` |
| `peek ADDR N` | N bytes of memory, ADDR in hex |
| `save` | the game's own `ENCAMP > SAVE`; the disk copied out once closed and decoded, with the place through `world_state.from_c64` against the staged one (`place_changed`, `facing_changed`); Curse and Silver Blades record row 18, row 24, every key and every attach with their times as `save-watch`, `save-key` and `save-attach` events, and a `SAVE GAME` bar that never comes is watched on to the camp bar, the disk copied to `lost-saved.D64`, then lost |

WHO is a name as the party panel draws it, or a number counting from 1 at
the top of the panel.  After every step all live effect rows, the clock and
each checkpoint's hit count are logged.

**What the screens say, and where it was read.**  The camp list is
`CAMP $16C3`-`$1797` in Pool of Radiance: the whom menu is the party panel,
with `THE WHOLE PARTY` and `EXIT` under the names and the question on row 24;
a character's list asks the effect query with that
character as the owner, so a row owned by the whole party is listed for every
member; each page ends in `PRESS ANY KEY TO CONTINUE` on row 24, and the whom
menu comes back after the last.  The later titles carry the same strings.  In
the ITEMS list `LIBRARY $39B7`-`$39C3` prints `*` before the name of an item
whose bonus byte is not zero when `$6DD9` is set, and choosing ITEMS sets
`$6DD9` from the query at `$4081`, which asks for Detect Magic (id 5) with the
owner `$FF` and so matches only a row owned by the whole party.  Its hit is
`$408F`, the checkpoint in the example above.

Pool of Radiance, Curse and Silver Blades are driven; Silver Blades has no
`fight`.  Curse and Silver Blades `view` and `save` take the routes
`tools/c64/curedrive.py` measured: the sheet is `VIEW` from camp with `EXIT` on
row 24 and the member's name on row 1, and a save waits for `SAVING GAME` to
come up and go and the camp bar to return.  Pool's save keeps
`Session.save_game`'s fixed wait, because its own progress text is not
measured.

A run with a `walk` fails, exit 1, unless a `save` after it shows the asked
result: a forward move changed the saved square from the staged one, turns
alone did not, and the saved square and facing are the ones the screen showed.
Every wait ends at the run's own deadline (`--max-seconds`), with the screen
kept; only the boot and load, inside `Session`, cannot be cut short.

`--compare A B` reads two runs' `summary.json` and lists the item rows and
camp lists that differ, saying whether an item row differs only by the mark.

Evidence goes to `~/.cache/wish/acceptance/<issue>/<sha>-<run>/`:
`run.jsonl`, `summary.json`, `staged.D64` (the save as booted), a text file
and a PNG for every screen read, and `saved.D64` (the game's own resave).  A
directory that already holds a run is refused.  Nothing is committed and the
player's disks are only read.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import pathlib
import re
import shlex
import struct
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(REPO))

from automap import actions as auto_actions  # noqa: E402
from automap import fasttravel  # noqa: E402
from automap.paths import tool_disks  # noqa: E402
from goldbox import (  # noqa: E402
    c64_codec,
    c64_port,
    c64_save,
    effects,
    traits,
    world_state,
)
from goldbox.d64 import D64, split_load_address  # noqa: E402
from goldbox.geo import STEP  # noqa: E402
from goldbox.items import (  # noqa: E402
    ITEM_AREA_BASE,
    ITEM_BLOCK_STRIDE,
    ITEM_SIZE,
    ITEMS_PER_CHARACTER,
)
from goldbox.record import RECORD_SIZE, CharacterRecord  # noqa: E402
from goldbox.savegame import ROSTER_COMBAT_SIDE, ROSTER_HP_CURRENT  # noqa: E402
from tools.c64 import (  # noqa: E402
    route_pool,
    runlog,  # noqa: E402
    screens,
)
from tools.c64 import session as S  # noqa: E402
from tools.pool_of_radiance.koboldnpc import SessTarget  # noqa: E402
from tools.registry import evidence, scratch, specimens  # noqa: E402

TITLES = {"pool": "pool-of-radiance", "curse": "curse-of-the-azure-bonds",
          "ssb": "secret-of-the-silver-blades"}

#: Ten trait slots per record from `goldbox.traits`; eight party slots in a save.
TRAIT_SLOT = traits.FIRST
TRAIT_SLOTS = traits.SLOTS
PARTY_SLOTS = 8
CREATURE_TYPE_OFFSET = 0x0D7
READY_PNG_TIMEOUT = 10.0
READY_SPECIMEN_ISSUE = (
    "#703 (A C64 acceptance driver's read step can report a garbled diff "
    "after a save step, because it reads from a disk-transfer staging address "
    "a preceding save's disk swaps leave stale)")
POOL_SPECIMEN_ISSUE = (
    "#700 (Converting a Pool of Radiance C64 party holding a camp-cast "
    "Animate Dead zombie needs more than fixing the refusal that blocks it)")
TEMPLE_SOURCE_SHA256 = (
    "7834be122f8a30c03f029d96b8ba39d0961545b998837e089e965e06a20edbe9")
TEMPLE_ROUTE = (
    ("K", (0x14, 15, 4, 3), (0x14, 15, 4, 0)),
    ("K", (0x14, 15, 4, 0), (0x14, 15, 4, 1)),
    ("I", (0x14, 15, 4, 1), (0, 0, 4, 1)),
    ("I", (0, 0, 4, 1), (0, 1, 4, 1)),
    ("J", (0, 1, 4, 1), (0, 1, 4, 0)),
    ("I", (0, 1, 4, 0), (0, 1, 3, 0)),
)

#: The route entry whose expected area differs from its before area (the
#: only move allowed a side-3 disk prompt), and the route's last entry
#: (temple arrival), computed from `TEMPLE_ROUTE` so a route-length change
#: cannot silently strand these guards on a stale index. The assertion below
#: makes a route with zero or two-or-more crossings fail import with a
#: specific message, rather than a bare `StopIteration` or a second crossing
#: silently misrouted as an unexpected disk prompt.
_TEMPLE_CROSSINGS = [
    i for i, (_, before, expected) in enumerate(TEMPLE_ROUTE)
    if before[0] != expected[0]]
assert len(_TEMPLE_CROSSINGS) == 1, (
    "TEMPLE_ROUTE must cross exactly one area boundary, found "
    f"{len(_TEMPLE_CROSSINGS)}")
TEMPLE_CROSSING_INDEX = _TEMPLE_CROSSINGS[0]
TEMPLE_LAST_INDEX = len(TEMPLE_ROUTE) - 1

#: `$6E11` at the temple arrival screen, read live at `572b9ca0ee-temple-
#: route-d` frame 10 (`docs/121-silver-blades.md`'s overlay name table calls
#: 5 `POST.COM`, PROBABLE from one sample). The transition otherwise only
#: accepts `S.DUNGEON`; this is the one screen where the game runs a
#: different overlay while still standing at the expected place.
TEMPLE_ARRIVAL_MODE = 5

#: The camp's own bar, `ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT` (Pool
#: `CAMP $0899`), and the MAGIC bar, `CAST MEMORIZE SCRIBE DISPLAY REST EXIT`
#: (`CAMP $14BB`).  Each pair of words is on that bar and on no other.
CAMP_BAR = "REST ALTER"
MAGIC_BAR = "SCRIBE"

#: The camp list's strings, `CAMP $2699` onward in Pool of Radiance and the
#: same text in the later titles.
WHOM = "DISPLAY SPELLS ON WHOM"
CAST_WHOM = "CAST SPELL ON WHOM"
PICK_SPELL = "PICK A SPELL TO CAST"
AFFECTED = "IS AFFECTED BY:"
WHOLE_PARTY = "THE WHOLE PARTY"
CONTINUE = "PRESS ANY KEY TO CONTINUE"

#: The camp spells `cast` can use: the effect id each removes and the word the
#: camp list shows the character under, and the spell's own id in the
#: memorised list.  The paladin's `cure` removes disease, id 34.
CAMP_CURES = {"CURE BLINDNESS": (33, "BLIND")}
CAMP_SPELL_IDS = {"CURE BLINDNESS": 37}
CAMP_PARTY_SPELLS = {"ANIMATE DEAD": 36}
#: `ECL65 $9A18` holds cleric spell 41 with target flag $02 and camp handler
#: `$AA5B`; magic-user id 46 has the same handler but is not driven here.
POOL_TARGET_SPELLS = {"DISPEL MAGIC": 41}
DISEASE_CURE = (34, "DISEASE")

#: The paladin's cure timer that a `cure` starts, as the effect id of its row.
CURE_TIMER_ID = 141

#: What Detect Magic prints before a magic item's name, `LIBRARY $39C1`.
DETECT_MARK = "*"

#: The item list's own bar, `READY TRADE DROP EXIT`.
ITEM_BAR = "READY"

#: Seconds a save may take to write before the step is lost, and the bars
#: that can follow it: `SAVE GAME  EXIT` (`CAMP $0D94`), or the save error's
#: `TRY AGAIN: YES NO` (`CAMP $0DA5`).
SAVE_WAIT = 300
MAX_SECONDS = 1500
SAVE_BAR = "SAVE GAME"
SAVE_ERROR = "TRY AGAIN"

#: The effect query Detect Magic's mark rests on, in `LIBRARY`: asked at
#: `$4086`, matched at `$408F`, and the mark drawn at `$39C1`.
DETECT_POINTS = {"detect-asked": 0x4086, "detect-matched": 0x408F,
                 "mark-drawn": 0x39C1}


# --- parsing -------------------------------------------------------------------

def _byte(text: str, what: str, base: int = 0) -> int:
    value = int(text, base)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{what} must be a byte, got {text!r}")
    return value


def parse_rows(texts) -> list[tuple[int, int, int, int, int]]:
    """`SLOT=ID:OWNER:DURATION:MAGNITUDE`, hex, comma separated or repeated."""
    out = []
    for text in texts:
        for item in text.split(","):
            where, _, rest = item.partition("=")
            parts = rest.split(":")
            if len(parts) != 4:
                raise ValueError(f"{item!r}: a row is SLOT=ID:OWNER:DURATION:MAGNITUDE")
            slot = int(where, 0)
            if not 0 <= slot < effects.EFFECT_SLOTS:
                raise ValueError(f"{item!r}: the slot is 0 to 63")
            out.append((slot, *(_byte(p, "a row byte", 16) for p in parts)))
    return out


def parse_traits(texts) -> list[tuple[int, int, int]]:
    """`SLOT:INDEX=ID`, comma separated or repeated."""
    out = []
    for text in texts:
        for item in text.split(","):
            where, _, value = item.partition("=")
            parts = where.split(":")
            if len(parts) != 2 or not value:
                raise ValueError(f"{item!r}: a trait is SLOT:INDEX=ID")
            slot, index = (int(p, 0) for p in parts)
            if not 0 <= slot < PARTY_SLOTS or not 0 <= index < TRAIT_SLOTS:
                raise ValueError(f"{item!r}: the slot is 0 to 7, the index 0 to 9")
            out.append((slot, index, _byte(value, "an id", 0)))
    return out


def parse_items(texts) -> list[tuple[int, int, int, int]]:
    """`SLOT:ITEM:OFFSET=VALUE`, each a Python integer."""
    out = []
    for text in texts:
        for item in text.split(","):
            where, _, value = item.partition("=")
            parts = where.split(":")
            if len(parts) != 3 or not value:
                raise ValueError(f"{item!r}: an item byte is SLOT:ITEM:OFFSET=VALUE")
            slot, n, offset = (int(p, 0) for p in parts)
            if not (0 <= slot < PARTY_SLOTS and 0 <= n < ITEMS_PER_CHARACTER
                    and 0 <= offset < ITEM_SIZE):
                raise ValueError(f"{item!r}: the slot is 0 to 7, the item 0 to 15, "
                                 f"the offset 0 to 15")
            out.append((slot, n, offset, _byte(value, "the value", 0)))
    return out


def parse_record_bytes(texts) -> list[tuple[int, int, int]]:
    """`SLOT:OFFSET=VALUE`, one record byte below `0x100` each."""
    out = []
    for text in texts:
        for item in text.split(","):
            where, sep, value = item.partition("=")
            parts = where.split(":")
            if not sep or len(parts) != 2 or not value:
                raise ValueError(f"{item!r}: a record byte is SLOT:OFFSET=VALUE")
            slot, offset = (int(p, 0) for p in parts)
            if not 0 <= slot < PARTY_SLOTS or not 0 <= offset < 0x100:
                raise ValueError(f"{item!r}: the slot is 0 to 7, "
                                 "the offset 0 to 0xFF")
            out.append((slot, offset, _byte(value, "the value")))
    return out


def parse_statuses(texts) -> list[tuple[int, int]]:
    """`SLOT=BYTE`, one roster status per slot."""
    out = []
    for text in texts:
        for item in text.split(","):
            slot, sep, value = item.partition("=")
            if not sep or not value:
                raise ValueError(f"{item!r}: a roster status is SLOT=BYTE")
            index = int(slot, 0)
            if not 0 <= index < PARTY_SLOTS:
                raise ValueError(f"{item!r}: the slot is 0 to 7")
            out.append((index, _byte(value, "the status")))
    return out


@dataclasses.dataclass(frozen=True)
class Step:
    verb: str
    arg: str = ""

    @property
    def text(self) -> str:
        return f"{self.verb} {self.arg}".strip()


#: Each step and whether it takes an argument: never, optionally, always.
VERBS = {"load": "never", "camp-list": "may", "items": "must", "view": "must",
         "rest": "must", "fight": "may", "peek": "must", "save": "never",
         "cast": "must", "cure": "must", "walk": "must", "ready": "must",
         "temple-probe": "must", "warp": "must",
         "walk-fight": "must"}

#: How long a walk keeps watching for a disk prompt after a move (seconds).
LOOK_SECONDS = 2.0

#: The moves `walk` takes, the game's own letters: forward, left, right, about.
#: `J` and `K`'s change to the facing, which the C64 counts N 0, E 1, S 2, W 3,
#: is fixed; `I`'s is zero, it never turns. `M`'s own key set (`_walk` reads it
#: from the square) is here only so `parse_walk` accepts the letter (#708: `M`
#: turns about and tries the edge behind the original facing -- it lands one
#: square back keeping that facing where there is no wall art there, or stays
#: turned about, stepping through an open door or holding at a solid or locked
#: one, where there is).
TURNS = {"I": 0, "J": -1, "K": 1, "M": None}


def parse_rest(arg: str) -> tuple[int, int]:
    """`8h`, `30m`, `1h30m` as `(minutes, hours)`, the two bytes of `CAMP`'s
    rest-time field that `route_pool.rest` writes."""
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", arg.strip())
    if not arg.strip() or m is None:
        raise ValueError(f"rest {arg!r}: say 5m, 8h or 1h30m")
    hours, minutes = int(m.group(1) or 0), int(m.group(2) or 0)
    if minutes > 59 or hours > 255 or not (hours or minutes):
        raise ValueError(f"rest {arg!r}: minutes under 60, hours under 256, not zero")
    return minutes, hours


def parse_peek(arg: str) -> tuple[int, int]:
    parts = arg.split()
    if len(parts) != 2:
        raise ValueError(f"peek {arg!r}: say peek ADDR N")
    addr = int(parts[0].lstrip("$"), 16)
    n = int(parts[1])
    if not (0 <= addr <= 0xFFFF and 1 <= n <= 0x1000 and addr + n <= 0x10000):
        raise ValueError(f"peek {arg!r}: out of range")
    return addr, n


def parse_walk(arg: str) -> str:
    """`I`, `K`, `IIK`: the moves in order, upper-cased."""
    route = arg.strip().upper()
    if not route or any(c not in TURNS for c in route):
        raise ValueError(f"walk {arg!r}: the moves are I forward, J left, "
                         f"K right, M about-turn")
    return route


def parse_walk_fight(arg: str) -> tuple[str, str | None]:
    """`IIK` or `IIK/NO`: the moves, and the one answer a `YES NO` on the last
    square may be given.  NO is the only answer the step will press."""
    keys, sep, answer = arg.strip().partition("/")
    route = parse_walk(keys)
    if sep and answer.strip().upper() != "NO":
        raise ValueError(f"walk-fight {arg!r}: the only answer after / is NO")
    return route, "NO" if sep else None


def parse_cast(arg: str) -> tuple[str, str, str | None]:
    """A target for a cure, names for Pool dispel, or no party-spell target."""
    m = re.fullmatch(r"([^:>]+):([^:>]+)(?:>([^:>]+))?", arg.strip())
    if m is None:
        raise ValueError(f"cast {arg!r}: say cast CASTER:SPELL[>TARGET]")
    caster, spell, target = m.groups()
    caster, spell = caster.strip(), spell.strip().upper()
    target = target.strip() if target is not None else None
    if not caster or not spell or target == "":
        raise ValueError(f"cast {arg!r}: say cast CASTER:SPELL[>TARGET]")
    if target is None and spell not in CAMP_PARTY_SPELLS:
        raise ValueError(f"cast {arg!r}: {spell} needs a target")
    if target is not None and spell not in CAMP_CURES | POOL_TARGET_SPELLS:
        raise ValueError(f"cast {arg!r}: {spell} has no target prompt")
    if spell in POOL_TARGET_SPELLS and (caster.isdigit() or target.isdigit()):
        raise ValueError(f"cast {arg!r}: Dispel Magic needs a named caster and target")
    return caster, spell, target


def parse_cure(arg: str) -> tuple[str, str]:
    """`PALADIN>TARGET` as its two names."""
    m = re.fullmatch(r"([^:>]+)>([^:>]+)", arg.strip())
    if m is None:
        raise ValueError(f"cure {arg!r}: say cure PALADIN>TARGET")
    return m.group(1).strip(), m.group(2).strip()


def parse_ready(arg: str) -> tuple[str, str]:
    """`WHO>LABEL`, the same shape `cure` parses -- a name can hold a space."""
    m = re.fullmatch(r"([^:>]+)>([^:>]+)", arg.strip())
    if m is None:
        raise ValueError(f"ready {arg!r}: say ready WHO>LABEL")
    return m.group(1).strip(), m.group(2).strip()


def parse_steps(texts) -> list[Step]:
    """The step list, checked whole before anything is staged or booted."""
    steps = []
    for text in texts:
        verb, _, arg = text.strip().partition(" ")
        arg = arg.strip()
        if verb not in VERBS:
            raise ValueError(f"{text!r} is not a step; the steps are "
                             + ", ".join(VERBS))
        takes = VERBS[verb]
        if takes == "never" and arg:
            raise ValueError(f"{verb} takes nothing, got {text!r}")
        if takes == "must" and not arg:
            raise ValueError(f"{verb} needs an argument")
        if verb == "rest":
            parse_rest(arg)
        elif verb == "peek":
            parse_peek(arg)
        elif verb == "walk":
            parse_walk(arg)
        elif verb == "walk-fight":
            parse_walk_fight(arg)
        elif verb == "cast":
            parse_cast(arg)
        elif verb == "cure":
            parse_cure(arg)
        elif verb == "ready":
            parse_ready(arg)
        elif verb == "temple-probe" and arg != "BRUTUS":
            raise ValueError("temple-probe requires BRUTUS")
        elif verb == "warp":
            parse_warp(arg)
        elif verb == "fight" and arg and not (arg.isdigit() and int(arg) > 0):
            raise ValueError(f"fight {arg!r}: seconds, more than zero")
        steps.append(Step(verb, arg))
    if not steps or steps[0].verb != "load":
        raise ValueError("the first step is load")
    if any(s.verb == "load" for s in steps[1:]):
        raise ValueError("one boot, one load")
    return steps


#: The facing `$C04D` an area's arrival script writes over any arrival square
#: (`ECL0A` entry 4 writes `0, 4, 1` at `$C04B`-`$C04D` on every arrival), read
#: after a warp.  Pool of Radiance only; an area not listed is not checked.
ARRIVAL_FACING = {10: 1}

#: How many `PRESS ... TO CONTINUE` pages a walk answers before its first key,
#: and how long it waits for each to give way.
ARRIVAL_PRESSES = 3
ARRIVAL_PAGE_SECONDS = 8.0

#: The budget for each fight a `walk-fight` takes; the run's own
#: `--max-seconds` still bounds the whole.
WALK_FIGHT_SECONDS = 900.0

#: How long `walk-fight` waits for a fight to open after it has answered an
#: encounter menu or a `YES NO`.
FIGHT_OPENS_SECONDS = 60.0

#: How long a warp waits for the engine to settle into its key-wait loop.
WARP_IDLE_SECONDS = 300.0


def parse_warp(arg: str) -> int:
    """The area id a `warp` names: a decimal integer whose arrival is checked."""
    if not re.fullmatch(r"[0-9]+", arg):
        raise ValueError(f"warp {arg!r}: an area id, a decimal integer")
    area = int(arg)
    if area not in ARRIVAL_FACING:
        raise ValueError(f"warp {arg!r}: the step checks its arrival only for "
                         "area " + ", ".join(map(str, sorted(ARRIVAL_FACING))))
    return area


def temple_source_guard(source: pathlib.Path) -> str:
    """Require the exact registered, unchanged animated BRUTUS source."""
    source = source.resolve()
    digest = specimens.sha256_file(source)
    if digest != TEMPLE_SOURCE_SHA256:
        raise ValueError(f"temple source SHA-256 {digest} is not "
                         f"{TEMPLE_SOURCE_SHA256}")
    for entry in specimens.list_specimens():
        if (entry.get("platform") == "c64"
                and entry.get("title") == "Pool of Radiance"
                and any(path.resolve() == source for path in entry.get("_files", []))
                and entry.get("sha256", {}).get(source.name) == digest):
            return digest
    raise ValueError(f"{source} is not a registered Pool C64 specimen")


def guard_temple_input(sess, clock, deadline):
    """Stop boot, load and probe inputs with 100 seconds left for teardown."""
    def check(what):
        if clock() >= deadline:
            raise StepFailed(f"temple input deadline before {what}")

    keyboard = sess.kbd
    press_kernal = sess.press_kernal
    handle_prompt = sess.handle_prompt

    class Keyboard:
        def key(self, *args, **kwargs):
            check("keyboard key")
            return keyboard.key(*args, **kwargs)

        def text(self, *args, **kwargs):
            check("keyboard text")
            return keyboard.text(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(keyboard, name)

    def guarded_press(*args, **kwargs):
        check("KERNAL key")
        return press_kernal(*args, **kwargs)

    def guarded_prompt(*args, **kwargs):
        check("disk prompt")
        return handle_prompt(*args, **kwargs)

    sess.kbd = Keyboard()
    sess.press_kernal = guarded_press
    sess.handle_prompt = guarded_prompt

    def restore():
        sess.kbd = keyboard
        sess.press_kernal = press_kernal
        sess.handle_prompt = handle_prompt

    return restore


def ready_capture_order(steps: list[Step]) -> bool:
    """One BAKSHI READY must finish before the sole saved diagnostic disk."""
    saves = [n for n, step in enumerate(steps) if step.verb == "save"]
    if len(saves) != 1:
        return False
    ready = [(n, parse_ready(step.arg)[0]) for n, step in enumerate(steps)
             if step.verb == "ready"]
    return bool(ready) and all(who == "BAKSHI" for _, who in ready) and any(
        n < saves[0] for n, _ in ready)


def pool_specimen_mode(steps: list[Step]) -> str | None:
    """Classify one #700 save as a BRUTUS Dispel run or its no-cast control."""
    verbs = [step.verb for step in steps]
    if (verbs == ["load", "view", "save"]
            and steps[1].arg.upper() == "BRUTUS"):
        return "control"
    if (verbs == ["load", "view", "cast", "view", "save"]
            and steps[1].arg.upper() == "BRUTUS"
            and steps[3].arg.upper() == "BRUTUS"):
        _, spell, target = parse_cast(steps[2].arg)
        if spell == "DISPEL MAGIC" and target.upper() == "BRUTUS":
            return "dispel"
    return None


def parse_checkpoints(texts) -> dict[str, int]:
    """`ADDR[=NAME]`, hex; the name defaults to the address."""
    out = {}
    for text in texts:
        addr, _, name = text.partition("=")
        value = int(addr.lstrip("$"), 16)
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"checkpoint {text!r}: out of range")
        out[name or f"${value:04X}"] = value
    return out


# --- staging -------------------------------------------------------------------

def _payload(image: D64, game) -> tuple[bytes, bytearray]:
    addr, body = split_load_address(image.read_file(game.save_file))
    return addr, bytearray(body)


def magic_items(payload: bytes, box) -> dict[str, list[int]]:
    """Per occupied save slot, the items whose bonus byte `+4` is not zero:
    the ones Detect Magic marks (`LIBRARY $39BC`)."""
    out: dict[str, list[int]] = {}
    for slot in range(PARTY_SLOTS):
        if not any(payload[box.slot(slot):box.slot(slot) + box.slot_stride]):
            continue
        base = box.items(slot)
        found = [n for n in range(ITEMS_PER_CHARACTER)
                 if any(payload[base + n * ITEM_SIZE:base + (n + 1) * ITEM_SIZE])
                 and payload[base + n * ITEM_SIZE + 4]]
        if found:
            out[str(slot)] = found
    return out


def _effect_list(payload: bytes) -> list[list[int]]:
    return [[e.slot, e.id, e.owner, e.duration, e.magnitude]
            for e in effects.active_effects(payload)]


def _effect_rows(payload: bytes) -> list[list[int]]:
    """Keep inactive rows too: clearing an id need not clear its other bytes."""
    arrays = (effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
              effects.EFFECT_DURATION_OFFSET, effects.EFFECT_MAGNITUDE_OFFSET)
    return [[slot, *(payload[offset + slot] for offset in arrays)]
            for slot in range(effects.EFFECT_SLOTS)]


def stage(src: pathlib.Path, dest: pathlib.Path, title_key: str,
          rows=(), traits=(), items=(), record_bytes=(), statuses=()) -> dict:
    """Copy `src` to `dest` and write the named bytes into the copy's payload.

    Editing an input and then watching the engine compute from it is the
    experiment: the game reads these bytes and cannot tell who wrote them.
    Reading a value this wrote back out and calling it the game's is not.
    """
    src, dest = pathlib.Path(src), pathlib.Path(dest)
    S.stage_writable(src, dest)
    image = D64.open(str(dest))
    game = c64_port.detect(image)
    if game is None:
        raise ValueError(f"{src}: no Gold Box save on this disk")
    if game.key != title_key:
        raise ValueError(f"{src} is a {game.title} save, not "
                         f"{c64_port.by_key(title_key).title}")
    box = c64_save.CONTAINERS[game.key]
    addr, payload = _payload(image, game)
    if box.roster_file is None:
        roster_addr, roster = addr, payload
    else:
        roster_addr, body = split_load_address(image.read_file(box.roster_file))
        roster = bytearray(body)
    took: dict = {"title": game.key, "source": str(src), "staged": str(dest),
                  "rows": [], "traits": [], "items": [],
                  "record_bytes": [], "statuses": []}
    arrays = (effects.EFFECT_ID_OFFSET, effects.EFFECT_OWNER_OFFSET,
              effects.EFFECT_DURATION_OFFSET, effects.EFFECT_MAGNITUDE_OFFSET)
    for slot, eid, owner, duration, magnitude in rows:
        was = [payload[a + slot] for a in arrays]
        effects.write_effect(payload, slot, eid, owner, duration, magnitude)
        took["rows"].append({"slot": slot, "was": was,
                             "now": [eid, owner, duration, magnitude]})
    for slot, index, code in traits:
        at = box.slot(slot) + TRAIT_SLOT + index
        took["traits"].append({"slot": slot, "index": index, "offset": at,
                               "was": payload[at], "now": code})
        payload[at] = code
    for slot, n, offset, value in items:
        at = box.items(slot) + n * ITEM_SIZE + offset
        took["items"].append({"slot": slot, "item": n, "byte": offset,
                              "offset": at, "was": payload[at], "now": value})
        payload[at] = value
    for slot, offset, value in record_bytes:
        at = box.slot(slot) + offset
        took["record_bytes"].append({"slot": slot, "byte": offset,
                                     "offset": at, "was": payload[at],
                                     "now": value})
        payload[at] = value
    for slot, value in statuses:
        at = box.roster_offset + slot * box.roster_stride
        took["statuses"].append({"slot": slot,
                                 "file": (box.roster_file or game.save_file).decode(
                                     "latin1"),
                                 "offset": at, "was": roster[at], "now": value})
        roster[at] = value
    image.write_file_inplace(game.save_file,
                             addr.to_bytes(2, "little") + bytes(payload))
    if box.roster_file is not None and statuses:
        image.write_file_inplace(box.roster_file,
                                 roster_addr.to_bytes(2, "little") + bytes(roster))
    image.save(str(dest))
    took["effects"] = _effect_list(payload)
    took["magic_items"] = magic_items(payload, box)
    took["place"] = place_of(payload, game)
    if game.key == "pool-of-radiance":
        took["drain_fields"] = drain_fields(
            [bytes(payload[box.slot(slot):box.slot(slot) + box.slot_stride])
             for slot in range(PARTY_SLOTS)])
    return took


def _party_reading(records: list[bytes], roster: bytes, stride: int) -> list[dict]:
    """Name and raw fields for every Pool member, from live RAM or a save."""
    party = []
    for slot, record in enumerate(records):
        rec = CharacterRecord(bytes(record).ljust(RECORD_SIZE, b"\0"),
                              stored_size=len(record))
        roster_at = slot * stride
        raw = (0xA3, 0xA4, 0xB6, 0xB8, 0xD7, 0xEC)
        party.append({
            "slot": slot, "name": rec.name,
            "status": roster[roster_at],
            "side": roster[roster_at + ROSTER_COMBAT_SIDE],
            "hp_current": roster[roster_at + ROSTER_HP_CURRENT],
            "memorised": [n for n in c64_codec.get_memorised(
                rec, c64_port.POOL_OF_RADIANCE) if n],
            "cleric_level": record[0xCA], "fighter_level": record[0xCC],
            "movement": record[0x9F],
            "traits": list(record[TRAIT_SLOT:TRAIT_SLOT + TRAIT_SLOTS]),
            "creature_type": record[CREATURE_TYPE_OFFSET],
            "record_bytes": {f"0x{offset:02X}": record[offset] for offset in raw},
        })
    return party


def _record_sha256(records: list[bytes]) -> list[str]:
    """Digest each complete 256-byte Pool record for saved/live comparison."""
    return [hashlib.sha256(record).hexdigest() for record in records]


def place_of(payload: bytes, game) -> dict:
    """The area, the square and the facing (0 to 3) a save payload holds,
    through the reader every conversion uses."""
    state = world_state.from_c64(bytes(payload), game)
    return {"area": state.area, "x": state.x, "y": state.y,
            "facing": state.facing}


def place_verdict(before: dict | None, after: dict) -> dict:
    """Whether the square, the area or the facing differs between two places.

    `place_changed` is the square and the area only: a turn changes the
    facing and leaves the party where it stood, and that is the control a
    walk is judged against.
    """
    if before is None:
        return {"place_before": None, "place_after": after,
                "place_changed": None, "facing_changed": None}
    return {"place_before": before, "place_after": after,
            "place_changed": (before["area"], before["x"], before["y"])
            != (after["area"], after["x"], after["y"]),
            "facing_changed": before["facing"] != after["facing"]}


def decode_save(path: pathlib.Path, staged: dict) -> dict:
    """The effect rows, the place, the magic items and every staged byte, off a disk."""
    image = D64.open(str(path))
    game = c64_port.detect(image)
    box = c64_save.CONTAINERS[game.key]
    _, payload = _payload(image, game)
    if box.roster_file is None:
        roster = payload
    else:
        _, roster = split_load_address(image.read_file(box.roster_file))
    clock = list(payload[box.clock:box.clock + 6])
    out = {
        "effects": _effect_list(payload),
        "effect_rows": _effect_rows(payload),
        "clock": clock,
        **place_verdict(staged.get("place"), place_of(payload, game)),
        "magic_items": magic_items(payload, box),
        "traits": [{**t, "saved": payload[t["offset"]]} for t in staged["traits"]],
        "items": [{**i, "saved": payload[i["offset"]]} for i in staged["items"]],
        "record_bytes": [{**r, "saved": payload[r["offset"]]}
                         for r in staged.get("record_bytes", [])],
        "statuses": [{**s, "saved": roster[s["offset"]]}
                     for s in staged.get("statuses", [])],
    }
    if game.key == "pool-of-radiance":
        records = [payload[box.slot(slot):box.slot(slot) + box.slot_stride]
                   for slot in range(PARTY_SLOTS)]
        out["party"] = _party_reading(records, roster[box.roster_offset:],
                                      box.roster_stride)
        out["record_sha256"] = _record_sha256(records)
        out["drain_fields"] = drain_fields(records)
    return out


#: The per-class level array: eight slots at `0x0C9`, indexed by class bit.
CLASS_LEVELS = (0x0C9, 0x0D1)


def drain_fields(records: list[bytes]) -> list[dict]:
    """What a level drain changes, read off each occupied Pool record."""
    out = []
    for slot, record in enumerate(records):
        rec = CharacterRecord(bytes(record).ljust(RECORD_SIZE, b"\0"),
                              stored_size=len(record))
        if not rec.name:
            continue
        out.append({"slot": slot, "name": rec.name,
                    "level": rec.get("level"),
                    "levels_drained": rec.get("levels_drained"),
                    "hp_lost_to_drain": rec.get("hp_lost_to_drain"),
                    "hp_max": rec.get("hp_max"),
                    "class_levels": list(bytes(record)[CLASS_LEVELS[0]:CLASS_LEVELS[1]])})
    return out


def drain_verdict(before: list[dict] | None, after: list[dict]) -> dict:
    """Whether some character was drained one or two levels, and consistently.

    A character passes when exactly one entry of its per-class level array
    fell, by 1 or 2, `levels_drained` (`0x0A1`) equals that fall,
    `hp_lost_to_drain` (`0x0A2`) is not zero and `hp_max` fell by
    `hp_lost_to_drain`.  `level` (`0x0A0`) is the highest class level, so it
    must fall, by at least 1 and at most the drain, only when the drained class
    was the single highest one; a multi-class character drained in a lower
    class, or in one of two equal classes, keeps its `level`.  The `hp_max` and
    `hp_lost_to_drain` rule rests on the SPELLE02 reading in
    `goldbox/layout.py`, not on a save the game drained, and is what this run
    is meant to test.  A run in which nobody passes is a result to record, not
    a driver failure, so this returns and never raises.
    """
    if not before:
        return {"passed": None, "characters": [],
                "why": "the staged disk holds no records to compare"}
    was = {c["slot"]: c for c in before}
    characters = []
    for now in after:
        old = was.get(now["slot"])
        if old is None or old["name"] != now["name"]:
            continue
        classes = [a - b for a, b in zip(old["class_levels"], now["class_levels"])]
        fell = [c for c in classes if c]
        drop = fell[0] if len(fell) == 1 else 0
        level_drop = old["level"] - now["level"]
        problems = []
        if len(fell) != 1 or drop not in (1, 2):
            problems.append(f"class levels fell by {classes}, not exactly one "
                            f"entry by 1 or 2")
        if now["levels_drained"] != drop:
            problems.append(f"levels_drained is {now['levels_drained']}, "
                            f"the drained class fell by {drop}")
        if not now["hp_lost_to_drain"]:
            problems.append("hp_lost_to_drain is zero")
        if old["hp_max"] - now["hp_max"] != now["hp_lost_to_drain"]:
            problems.append(f"hp_max fell by {old['hp_max'] - now['hp_max']}, "
                            f"hp_lost_to_drain is {now['hp_lost_to_drain']}")
        if drop:
            top = max(old["class_levels"])
            single_top = (old["class_levels"][classes.index(drop)] == top
                          and old["class_levels"].count(top) == 1)
            if single_top and not 1 <= level_drop <= drop:
                problems.append(f"the drained class was the highest and level "
                                f"fell by {level_drop}, not 1 to {drop}")
        characters.append({"slot": now["slot"], "name": now["name"],
                           "level_drop": level_drop,
                           "levels_drained": now["levels_drained"],
                           "hp_lost_to_drain": now["hp_lost_to_drain"],
                           "class_drops": classes,
                           "hp_max_drop": old["hp_max"] - now["hp_max"],
                           "passed": not problems, "problems": problems})
    return {"passed": any(c["passed"] for c in characters),
            "characters": characters}


def drain_summary(results: list[dict], staged: dict) -> dict:
    """The drain verdict for the first `save` after the last `walk-fight`, or
    `passed: None` with the reason when the run has none."""
    fought = max(i for i, r in enumerate(results) if r["verb"] == "walk-fight")
    saved = next((r for r in results[fought + 1:] if r["verb"] == "save"), None)
    if saved is None:
        return {"passed": None, "characters": [],
                "why": "no save step after the last walk-fight"}
    return drain_verdict(staged.get("drain_fields"), saved["drain_fields"])


# --- the screens ---------------------------------------------------------------

def _inner(row: str) -> str:
    """A row inside the text window, without the frame at columns 0 and 39."""
    return row[1:39].strip()


def _is_frame(text: str) -> bool:
    return len(text) > 3 and len(set(text)) == 1


def _has(rows: list[str], needle: str) -> bool:
    return any(needle in r for r in rows)


@dataclasses.dataclass(frozen=True)
class CampPage:
    who: str
    spells: list[str]
    more: bool


def camp_list_page(rows: list[str]) -> CampPage | None:
    """One page of the camp list of spells in effect, or None.

    The header is `<NAME> IS AFFECTED BY:`, one spell name to a row follows,
    and row 24 holds `PRESS ANY KEY TO CONTINUE` once the page is drawn.
    """
    if len(rows) < 25:
        return None
    head = next((i for i, r in enumerate(rows[:24]) if AFFECTED in r), None)
    if head is None:
        return None
    who = _inner(rows[head]).split(AFFECTED)[0].strip()
    spells = [t for t in (_inner(r) for r in rows[head + 1:24])
              if t and not _is_frame(t)]
    return CampPage(who, spells, CONTINUE in rows[24])


def whom_entries(rows: list[str], question: str = WHOM) -> list[str]:
    """The names the whom menu offers, `THE WHOLE PARTY` last, `EXIT` left off.

    The menu is the party panel itself: the question goes on row 24 and
    `THE WHOLE PARTY` and `EXIT` are drawn under the names, in the panel's
    name field (captured on PORSAVE13).
    """
    if len(rows) < 25 or question not in rows[24]:
        return []
    head = next((i for i, r in enumerate(rows[:24])
                 if S.PARTY_HEADER in r[S.PARTY_COLUMN:]), None)
    if head is None:
        return []
    width = rows[head][S.PARTY_COLUMN:].index(S.PARTY_HEADER)
    out: list[str] = []
    for r in rows[head + 1:24]:
        name = r[S.PARTY_COLUMN:S.PARTY_COLUMN + width].strip()
        if not name:
            if out:
                break
            continue
        if name == "EXIT":
            break
        out.append(name)
    return out


def item_entries(rows: list[str]) -> list[dict]:
    """The item list's rows: readied or not, the rest of the row, and whether
    Detect Magic marked it."""
    out = []
    for text in screens.item_list(rows):
        m = re.match(r"(YES|NO)\s+(.*)", text)
        rest = m.group(2) if m else text
        out.append({"row": text, "readied": bool(m and m.group(1) == "YES"),
                    "text": rest, "marked": DETECT_MARK in rest})
    return out


def compare(a: pathlib.Path, b: pathlib.Path) -> dict:
    """The item rows and camp lists that differ between two runs."""
    def load(where):
        return json.loads((pathlib.Path(where) / "summary.json")
                          .read_text(encoding="utf-8")).get("results", [])

    ra, rb = load(a), load(b)
    items, lists = [], []
    for sa in (r for r in ra if r.get("verb") == "items"):
        sb = next((r for r in rb if r.get("verb") == "items"
                   and r.get("who") == sa.get("who")), None)
        if sb is None:
            continue
        ea, eb = sa.get("entries", []), sb.get("entries", [])
        for n in range(max(len(ea), len(eb))):
            x = ea[n]["row"] if n < len(ea) else None
            y = eb[n]["row"] if n < len(eb) else None
            if x != y:
                items.append({"who": sa["who"], "row": n, "a": x, "b": y,
                              "only_the_mark": x is not None and y is not None
                              and x.replace(DETECT_MARK, "") == y.replace(DETECT_MARK, "")})
    la = {k: v for r in ra if r.get("verb") == "camp-list"
          for k, v in r.get("lists", {}).items()}
    lb = {k: v for r in rb if r.get("verb") == "camp-list"
          for k, v in r.get("lists", {}).items()}
    for who in sorted(set(la) & set(lb)):
        only_a = [s for s in la[who] if s not in lb[who]]
        only_b = [s for s in lb[who] if s not in la[who]]
        if only_a or only_b:
            lists.append({"who": who, "only_a": only_a, "only_b": only_b})
    return {"a": str(a), "b": str(b), "items": items, "camp_list": lists}


# --- the driven part -------------------------------------------------------------

class StepFailed(RuntimeError):
    pass


class _SavingChosen(Exception):
    """`SAVING GAME` was on row 24 while `write_save` waited for `SAVE GAME`."""


class Log(runlog.Log):
    def __init__(self, out: pathlib.Path):
        super().__init__(out / "run.jsonl")


@dataclasses.dataclass(frozen=True)
class TempleSample:
    """One paused instant: the PC, the screen and the dungeon triple, read
    together so a place is never judged from a screen and a memory read
    taken across two separate monitor pauses (#715)."""
    monotonic: float
    pc: int | None
    screen: object
    state: dict


class PoolRun:
    """One booted Pool of Radiance session and the steps run on it."""

    #: Cast-list key probes and waits; Curse may enable joystick fire.
    joy = False
    capture_ready = False
    pick_wait = 15
    whom_wait = 120

    #: The run's own deadline on `clock`, and the clock; `run` sets both.  A
    #: wait that would outlast the deadline ends there, with the screen kept,
    #: rather than at whatever moment an outer `timeout` kills the process.
    deadline: float | None = None
    clock = staticmethod(time.monotonic)

    def __init__(self, sess, log: Log, out: pathlib.Path, game, points: dict):
        self.sess = sess
        self.log = log
        self.out = out
        self.game = game
        self.box = c64_save.CONTAINERS[game.key]
        self.points = points
        self.armed: dict[str, int] = {}
        self.shots = 0
        self.ready_captures: list[dict] = []
        self.ready_sample_errors: list[dict] = []
        self.temple_checkpoints: list[dict] = []
        self.temple_input_deadline: float | None = None
        self.temple_pc_id: int | None = None

    # -- the screen ------------------------------------------------------------
    def rows(self) -> list[str]:
        s = self.sess.screen()
        return [] if s is None else [s.row(r) for r in range(25)]

    def bar(self) -> str:
        rows = self.rows()
        return rows[24] if rows else ""

    def capture(self, tag: str, rows: list[str] | None = None) -> list[str]:
        """The text screen and a PNG of it, both kept, named in order.  ROWS,
        when the caller already has them, are written without reading again."""
        self.shots += 1
        stem = f"{self.shots:02d}-{re.sub(r'[^A-Za-z0-9]+', '-', tag).strip('-')}"
        if rows is None:
            rows = self.rows()
        (self.out / f"{stem}.txt").write_text(
            "\n".join(r.rstrip() for r in rows) + "\n" if rows else "(bitmap)\n",
            encoding="utf-8")
        self.sess.kbd.screenshot(str(self.out / f"{stem}.png"))
        self.log.emit("screen", tag=tag, stem=stem,
                      rows=[r.rstrip() for r in rows if r.strip()])
        return rows

    def sample_ready(self, stage: str | None, predicate) -> object | None:
        """Read a READY screen, and retain a selected screen and live RAM
        while one binary-monitor connection keeps the CPU stopped.

        The PNG comes from the X window during that same pause. Its displayed
        frame may lag the RAM screen by a video refresh; it is not an atomic
        read of the VIC and CPU memories.
        """
        self.budget(READY_PNG_TIMEOUT, "READY screenshot")
        try:
            with self.sess.mon(8) as m:
                try:
                    screen = None if S.is_bitmap(m) else S.read_screen(m)
                    if stage is not None and predicate(screen):
                        self.shots += 1
                        stem = f"{self.shots:02d}-ready-{stage}"
                        rows = [] if screen is None else screen.rows()
                        try:
                            (self.out / f"{stem}.txt").write_text(
                                "\n".join(row.rstrip() for row in rows) + "\n"
                                if rows else "(bitmap)\n", encoding="utf-8")
                        except OSError as exc:
                            raise StepFailed(
                                f"READY {stage} text capture failed: {exc}") from exc
                        snapshot = {
                            "stage": stage,
                            "monotonic": self.clock(),
                            "screen_address": None if screen is None else
                                              f"${screen.address:04X}",
                            "screen_codes": None if screen is None else
                                            screen.codes.hex(),
                            "colours": None if screen is None else
                                       screen.colours.hex(),
                            "effects": bytes(m.read(0x4900, 0x300)).hex(),
                            "record": bytes(m.read(0x5100, 0x100)).hex(),
                            "items": bytes(m.read(0x5D00, 0x100)).hex(),
                        }
                        timeout = READY_PNG_TIMEOUT
                        if self.deadline is not None:
                            timeout = max(0.1, min(timeout,
                                                   self.deadline - self.clock()))
                        snapshot["png_captured"] = self.sess.kbd.screenshot(
                            str(self.out / f"{stem}.png"), timeout=timeout)
                        try:
                            (self.out / f"{stem}.json").write_text(
                                json.dumps(snapshot, indent=2) + "\n",
                                encoding="utf-8")
                        except OSError as exc:
                            raise StepFailed(
                                f"READY {stage} JSON capture failed: {exc}") from exc
                        capture = {"stage": stage, "stem": stem,
                                   "monotonic": snapshot["monotonic"]}
                        self.ready_captures.append(capture)
                        try:
                            self.log.emit("ready_capture", **capture,
                                          png_captured=snapshot["png_captured"])
                        except OSError as exc:
                            raise StepFailed(
                                f"READY {stage} log capture failed: {exc}") from exc
                        if not snapshot["png_captured"]:
                            raise StepFailed(f"READY {stage} PNG capture failed")
                except (StepFailed, OSError, S.MonitorError):
                    with contextlib.suppress(OSError, S.MonitorError):
                        m.resume()
                    raise
                else:
                    m.resume()
        except (OSError, S.MonitorError) as exc:
            error = {"stage": stage, "error": repr(exc),
                     "monotonic": self.clock()}
            self.ready_sample_errors.append(error)
            self.log.emit("ready_sample_error", **error)
            return None
        return screen

    def spent(self) -> bool:
        return self.deadline is not None and self.clock() >= self.deadline

    def budget(self, timeout: float, what: str) -> float:
        """TIMEOUT, or what is left of the run when that is less; none left
        is a lost step, so a long wait is never begun past the deadline."""
        if self.deadline is None:
            return timeout
        left = self.deadline - self.clock()
        if left <= 0:
            raise self.fail("deadline", f"before {what}")
        return min(timeout, left)

    def wait_rows(self, ok, timeout: float, what: str = "a screen") -> list[str] | None:
        limit = self.clock() + timeout
        while self.clock() < limit:
            if self.spent():
                raise self.fail("deadline", f"waiting for {what}")
            rows = self.rows()
            if rows and ok(rows):
                return rows
            self.sess.handle_prompt()
            time.sleep(0.4)
        if self.spent():
            raise self.fail("deadline", f"waiting for {what}")
        return None

    def fail(self, tag: str, why: str) -> StepFailed:
        if self.spent():
            why = f"the run's seconds were spent, {why}"
            tag = "deadline"
        self.capture(f"lost-{tag}")
        return StepFailed(why)

    def choose_bar(self, word: str, timeout: float) -> bool:
        return self.sess.select_bar(word, timeout=self.budget(timeout, word))

    # -- where the party is ------------------------------------------------------
    @staticmethod
    def at_world(bar: str) -> bool:
        return "ENCAMP" in bar and "ENCAMP:" not in bar

    def to_world(self, tries: int = 10) -> bool:
        """Back to the world bar from whichever screen a step left up."""
        for _ in range(tries):
            rows = self.rows()
            bar = rows[24] if rows else ""
            if self.at_world(bar):
                return True
            if WHOM in bar:
                self.pick("EXIT")
            elif CONTINUE in bar:
                self.sess.press_kernal(0x0D)
            elif S.SHEET_BAR in bar:
                self.sess.leave_sheet()
            elif S.MOVE_SUBBAR in bar:
                self.sess.leave_move()
            elif "EXIT" in bar:
                self.choose_bar("EXIT", timeout=10)
            self.sess.settle(1.5)
        return self.at_world(self.bar())

    def to_camp(self) -> bool:
        if CAMP_BAR in self.bar():
            return True
        if not self.to_world() or not self.choose_bar("ENCAMP", timeout=20):
            return False
        return self.wait_rows(lambda r: CAMP_BAR in r[24], 60) is not None

    def panel_index(self, who: str) -> int:
        """Which panel row WHO is: a number counts from 1, a name is matched
        as the panel draws it."""
        if who.isdigit():
            return int(who) - 1
        s = self.sess.screen()
        names = [] if s is None else [
            s.row(r)[S.PARTY_COLUMN:].upper() for r in self.sess.stable_party_rows()]
        wanted = (who.upper(), screens.as_drawn(who).upper())
        for i, text in enumerate(names):
            if any(text.startswith(w) for w in wanted):
                return i
        raise self.fail("panel", f"{who} is not on the party panel: {names}")

    # -- readings after every step ---------------------------------------------
    def reading(self) -> dict:
        base = self.box.save_load_address
        with self.sess.mon(10) as m:
            head = bytes(m.read(base, effects.EFFECT_MAGNITUDE_OFFSET
                                + effects.EFFECT_SLOTS))
            clock = list(m.read(base + self.box.clock, 6))
            counts = {k: m.checkpoint_hits(v)
                      for k, v in self.armed.items()}
            if self.game.key == "pool-of-radiance":
                records = [bytes(route_pool.live_record(m, slot))
                           for slot in range(PARTY_SLOTS)]
                roster = bytes(m.read(self.box.roster_base,
                                      self.box.roster_stride * PARTY_SLOTS))
            m.resume()
        out = {"effects": _effect_list(head), "effect_rows": _effect_rows(head),
               "clock": clock, "counts": counts}
        if self.game.key == "pool-of-radiance":
            out["party"] = _party_reading(records, roster, self.box.roster_stride)
            out["record_sha256"] = _record_sha256(records)
        return out

    # -- the steps ---------------------------------------------------------------
    def load(self) -> dict:
        if not self.sess.boot():
            raise StepFailed(self.sess.boot_failure or "boot failed")
        if not self.sess.load_save():
            raise self.fail("load", "the game did not load the save")
        if not self.sess.begin_adventuring():
            raise self.fail("begin", "BEGIN ADVENTURING never reached the world")
        self.sess.settle(3)
        with self.sess.mon(10) as m:
            for name, addr in self.points.items():
                self.armed[name] = m.checkpoint_set(addr, exec_=True, stop=False)
            m.resume()
        self.capture("world")
        return {"position": self.position(),
                "checkpoints": {k: f"${v:04X}" for k, v in self.points.items()}}

    # -- one bounded New Phlan temple observation ------------------------------
    def temple_sample(self) -> TempleSample:
        """Read the PC, the screen and the live dungeon triple in one paused
        instant (#715): every temple guard reads through this, so a place is
        never judged from a screen and a memory read taken across two
        separate monitor pauses."""
        try:
            with self.sess.mon(8) as m:
                try:
                    if self.temple_pc_id is None:
                        self.temple_pc_id = S._pc_id_of(m, 0)
                    try:
                        pc = S._pc_of(m, 0, self.temple_pc_id)
                    except (S.MonitorError, IndexError, struct.error):
                        pc = None
                    try:
                        screen = None if S.is_bitmap(m) else S.read_screen(m)
                    except S.ScreenUnreadable as exc:
                        self.log.emit("temple-screen-unreadable",
                                      error=repr(exc))
                        screen = None
                    area = bytes(m.read(0x6E1B, 1))
                    mode = bytes(m.read(0x6E11, 1))
                    inside = bytes(m.read(0x49E6, 1))
                    saved_position = bytes(m.read(0x49C0, 3))
                    position = bytes(m.read(0xC04B, 3))
                finally:
                    m.resume()
                if (len(area) != 1 or len(mode) != 1 or len(inside) != 1
                        or len(saved_position) != 3 or len(position) != 3):
                    raise ValueError("short monitor read")
                if not inside[0] or position[2] > 3:
                    raise ValueError(f"outside or invalid facing: "
                                     f"{inside.hex()} {position.hex()}")
                state = {"area": area[0] & 0x7F, "mode": mode[0],
                         "area_pending": bool(area[0] & 0x80),
                         "indoors": inside[0], "x": position[0],
                         "y": position[1], "facing": position[2],
                         "save_copy": list(saved_position)}
                return TempleSample(monotonic=self.clock(), pc=pc,
                                    screen=screen, state=state)
        except (OSError, S.MonitorError, ValueError, IndexError) as exc:
            raise StepFailed(f"temple state unreadable: {exc}") from exc

    @staticmethod
    def _temple_place(state: dict) -> tuple[int, int, int, int]:
        return state["area"], state["x"], state["y"], state["facing"]

    @staticmethod
    def _temple_agrees(a: TempleSample | None, b: TempleSample | None) -> bool:
        """Two samples agree when their place, mode and area-pending flag
        match; screen text is not part of it (#715)."""
        if a is None or b is None:
            return False
        return (PoolRun._temple_place(a.state) == PoolRun._temple_place(b.state)
                and a.state["mode"] == b.state["mode"]
                and a.state["area_pending"] == b.state["area_pending"])

    def _temple_steady(self, what: str,
                       seconds: float = S.STEADY_SECONDS) -> TempleSample:
        """Sample every 0.25 s until two consecutive samples agree, and
        return the second; stop if none agree within SECONDS, capped at the
        run's input deadline (#715)."""
        limit = min(self.clock() + seconds, self.temple_input_deadline)
        prior = None
        while self.clock() < limit:
            sample = self.temple_sample()
            if self._temple_agrees(prior, sample):
                return sample
            prior = sample
            time.sleep(S.STEADY_POLL)
        self._temple_stop("unsteady", f"place unsteady {what}", prior)

    def temple_checkpoint(self, tag: str, sample: TempleSample | None = None
                          ) -> dict:
        """Keep the whole screen, paused place and existing party/effect
        read, from the SAMPLE the caller judged rather than a fresh re-read
        (#715). The reading and its PNG still come from after the judged
        pause, not from it. With no SAMPLE, one is taken here and recorded
        as unjudged."""
        judged = sample is not None
        if sample is None:
            sample = self.temple_sample()
        screen = sample.screen
        if screen is None:
            raise StepFailed(f"temple {tag}: text screen unreadable")
        rows = [screen.row(r) for r in range(25)]
        self.capture(f"temple-{tag}", rows)
        stem = f"{self.shots:02d}-temple-{re.sub(r'[^A-Za-z0-9]+', '-', tag).strip('-')}"
        if not (self.out / f"{stem}.png").is_file():
            raise StepFailed(f"temple {tag}: PNG capture failed")
        reading = self.reading()
        reading_monotonic = self.clock()
        checkpoint = {"tag": tag, "stem": stem, "state": sample.state,
                      "reading": reading, "monotonic": self.clock(),
                      "judged": judged,
                      "pc": None if sample.pc is None else f"${sample.pc:04X}",
                      "sampled": sample.monotonic,
                      "reading_monotonic": reading_monotonic}
        (self.out / f"{stem}.json").write_text(
            json.dumps(checkpoint, indent=2), encoding="utf-8")
        self.temple_checkpoints.append(checkpoint)
        self.log.emit("temple-checkpoint", **checkpoint)
        return checkpoint

    def _temple_stop(self, tag: str, why: str,
                     sample: TempleSample | None = None):
        with contextlib.suppress(Exception):
            self.temple_checkpoint(f"lost-{tag}", sample)
        raise StepFailed(why)

    def _temple_input_budget(self, what: str) -> None:
        if (self.temple_input_deadline is None
                or self.clock() >= self.temple_input_deadline):
            self._temple_stop("deadline", f"temple input deadline before {what}")

    @staticmethod
    def _temple_is_world(screen) -> bool:
        bar = screen.row(24)
        return (S.word_column(bar, "MOVE") >= 0
                and S.word_column(bar, "ENCAMP") >= 0
                and "ENCAMP:" not in bar)

    @staticmethod
    def _temple_is_move(screen) -> bool:
        return S.MOVE_SUBBAR in screen.row(24)

    @staticmethod
    def _temple_is_quiet(screen) -> bool:
        """Row 24 and the message window (rows 17-23) hold no letter or digit.

        Pool draws this between the crossing key and `INSERT SIDE # 3`: the
        command bar is cleared while the drive reads track 18, and the prompt
        follows (`temple-route-b`, `05-temple-lost-event`). Nothing on it asks
        for input, so the transition waits on it rather than stopping. A
        quiet screen is the special case of a blank bar with an empty
        window: see `_temple_bar_blank`."""
        return not any(re.search(r"[A-Z0-9]", screen.row(r).upper())
                       for r in range(17, 25))

    @staticmethod
    def _temple_bar_blank(screen) -> bool:
        """Row 24 alone holds no letter or digit.

        Pool types each square's arrival text into the message window one
        character at a time and draws the command bar on row 24 only when
        typing ends (`temple-route-c`, `YOU ARE B` with row 24 blank). Nothing
        on a blank bar asks for input, so the transition waits on it rather
        than stopping, whether or not the window above it holds text."""
        return not re.search(r"[A-Z0-9]", screen.row(24).upper())

    @staticmethod
    def _temple_is_greeting(screen) -> bool:
        """The temple arrival screen.

        Frame 10 of `572b9ca0ee-temple-route-d` shows no greeting text and
        no status line (rows 17-23 empty); only its command bar -- `HEAL
        VIEW POOL APPRAISE EXIT` -- identifies it. The DOS-script text this
        used to look for never appears on the C64."""
        bar = screen.row(24)
        return (S.word_column(bar, "HEAL") >= 0
                and S.word_column(bar, "APPRAISE") >= 0)

    @staticmethod
    def _temple_continuation(screen) -> bool:
        bar = screen.row(24).upper().strip(" |.")
        return bar in ("PRESS BUTTON OR RETURN TO CONTINUE",
                       "PRESS ANY KEY TO CONTINUE")

    @staticmethod
    def _temple_disk(screen) -> bool:
        text = screen.text().upper()
        return bool(S.RE_GAME_SIDE.search(text) or S.SAVE_PROMPT in text
                    or re.search(r"\bINSERT\b.*\b(?:DISK|SIDE)\b", text,
                                 re.DOTALL))

    @staticmethod
    def _temple_side3(screen) -> bool:
        text = screen.text().upper()
        return ("INSERT SIDE # 3" in text
                and S.RE_GAME_SIDE.findall(text) == ["3"]
                and S.SAVE_PROMPT not in text)

    @staticmethod
    def _temple_heal_question(screen) -> bool:
        """The temple door's healing question, with YES and NO on row 24.

        `ECL00 +$1113` is ` DO YOU SEEK HEALING?`; its `HORIZMENU` at
        `+$155A` offers `YES` and `NO`."""
        text = screen.text().upper()
        bar = screen.row(24)
        return ("SEEK HEALING" in text
                and S.word_column(bar, "YES") >= 0
                and S.word_column(bar, "NO") >= 0)

    def _temple_select_bar(self, word: str, kind: str) -> None:
        """Select one guarded word; never answer prompts inside a selector."""
        first = self.temple_sample()
        screen = first.screen
        if screen is None:
            self._temple_stop("menu", f"{kind} bar unreadable", first)
        bar = screen.row(24)
        if S.word_column(bar, word) < 0:
            self._temple_stop("menu", f"{word} absent from {kind} bar", first)
        for _ in range(8):
            sample = self.temple_sample()
            screen = sample.screen
            if (screen is None or screen.row(24) != bar
                    or self._temple_disk(screen)
                    or self._temple_continuation(screen)
                    or (kind != "question"
                        and re.search(r"\bYES\b.*\bNO\b", screen.text(),
                                      re.DOTALL))
                    or re.search(r"\bPRESS\b", screen.text())
                    or (kind == "world" and not self._temple_is_world(screen))
                    or (kind == "temple" and not self._temple_is_greeting(screen))
                    or (kind == "question"
                        and not self._temple_heal_question(screen))):
                self._temple_stop("menu", f"{kind} bar changed before {word}",
                                  sample)
            span = S.span_in(screen, 24)
            col = S.word_column(bar, word)
            if span is None or col < 0:
                self._temple_stop("menu", f"{kind} highlight unreadable", sample)
            self._temple_input_budget(f"selecting {word}")
            if span[0] == col:
                self.sess.confirm_bar(24, bar)
                return
            self.sess.kbd.key("Right" if span[0] < col else "Left")
            limit = min(self.clock() + 5, self.temple_input_deadline)
            while self.clock() < limit:
                newer = self.temple_sample()
                newer_screen = newer.screen
                if newer_screen is None or newer_screen.row(24) != bar:
                    self._temple_stop("menu", f"{kind} bar changed after arrow",
                                      newer)
                newer_span = S.span_in(newer_screen, 24)
                if newer_span is not None and newer_span[0] != span[0]:
                    break
                time.sleep(0.25)
            else:
                self._temple_stop("menu", f"{word} highlight did not move")
        self._temple_stop("menu", f"{word} highlight never reached")

    def _temple_move(self, move: str, before: tuple[int, ...]) -> None:
        sample = self._temple_steady(f"before {move}")
        screen = sample.screen
        if screen is None:
            self._temple_stop("move", f"screen unreadable before {move}",
                              sample)
        if (sample.state["area_pending"] or sample.state["mode"] != S.DUNGEON
                or self._temple_place(sample.state) != before):
            self._temple_stop("move", f"wrong place before {move}", sample)
        if (self._temple_disk(screen) or self._temple_continuation(screen)
                or re.search(r"\bYES\b.*\bNO\b", screen.text(), re.DOTALL)
                or re.search(r"\bPRESS\b", screen.text())):
            self._temple_stop("move", f"unsafe screen before {move}", sample)
        if self._temple_is_world(screen):
            self._temple_select_bar("MOVE", "world")
            limit = min(self.clock() + 10, self.temple_input_deadline)
            while self.clock() < limit:
                polled = self.temple_sample()
                screen = polled.screen
                if screen is not None and self._temple_is_move(screen):
                    break
                if screen is not None and self._temple_disk(screen):
                    self._temple_stop("move", "disk prompt before movement",
                                      polled)
                time.sleep(0.25)
        sample = self._temple_steady(f"before {move}")
        screen = sample.screen
        if screen is None or not self._temple_is_move(screen):
            self._temple_stop("move", f"no move bar before {move}", sample)
        if (self._temple_disk(screen) or self._temple_continuation(screen)
                or re.search(r"\bYES\b.*\bNO\b", screen.text(), re.DOTALL)
                or re.search(r"\bPRESS\b", screen.text())):
            self._temple_stop("move", f"unsafe screen before {move}", sample)
        if (sample.state["area_pending"] or sample.state["mode"] != S.DUNGEON
                or self._temple_place(sample.state) != before):
            self._temple_stop("move", f"place changed before {move}", sample)
        self._temple_input_budget(f"movement {move}")
        self.sess.move_key(move)
        self.log.emit("temple-move", move=move, before=before)

    def _temple_transition(self, n: int, before: tuple[int, ...],
                           expected: tuple[int, ...], counters: dict) -> dict:
        limit = min(self.clock() + 90, self.temple_input_deadline)
        disk_visible = continuation_visible = question_visible = False
        question_since = None
        seen_kinds: set = set()
        prior = last = None
        while self.clock() < limit:
            sample = self.temple_sample()
            prior, last = last, sample
            screen = sample.screen
            if screen is None:
                time.sleep(0.3)
                continue
            text = screen.text().upper()
            if re.search(r"\bYES\b.*\bNO\b", text, re.DOTALL):
                if question_visible:
                    time.sleep(0.3)
                    continue
                if not (n == TEMPLE_LAST_INDEX and counters["questions"] == 0
                        and self._temple_heal_question(screen)):
                    self._temple_stop("yes-no", "unapproved YES/NO prompt",
                                      sample)
                if question_since is None:
                    question_since = self.clock()
                # A live run can show the healing question on screen before
                # the memory read of the arrival place catches up, the same
                # one-poll lag `_temple_transition` already tolerates for a
                # crossed area edge; wait for two agreeing samples rather
                # than stop on the first mismatch.
                if (self._temple_place(sample.state) != expected
                        or sample.state["mode"] != S.DUNGEON
                        or sample.state["area_pending"]
                        or not self._temple_agrees(prior, sample)):
                    if self.clock() - question_since >= 5:
                        self._temple_stop("yes-no", "healing question at the "
                                          "wrong place", sample)
                    time.sleep(0.25)
                    continue
                question_since = None
                self.temple_checkpoint("temple-question-before-answer", sample)
                self._temple_input_budget("healing question")
                self._temple_select_bar("YES", "question")
                counters["questions"] += 1
                question_visible = True
                continue
            question_visible = False
            question_since = None
            if self._temple_disk(screen):
                if disk_visible:
                    time.sleep(0.3)
                    continue
                if not (n == TEMPLE_CROSSING_INDEX and not counters["disk"]
                        and self._temple_side3(screen)):
                    self._temple_stop("disk", "unexpected or repeated disk prompt",
                                      sample)
                self.temple_checkpoint("boundary-side3-before-answer", sample)
                self._temple_input_budget("side 3 prompt")
                if not self.sess.handle_prompt(screen):
                    self._temple_stop("disk", "side 3 prompt was not answered",
                                      sample)
                counters["disk"] += 1
                disk_visible = True
                continue
            disk_visible = False
            if self._temple_continuation(screen):
                if continuation_visible:
                    time.sleep(0.3)
                    continue
                if counters["continuations"] >= 2:
                    self._temple_stop("continuation", "third continuation",
                                      sample)
                self.temple_checkpoint("continuation-before-answer", sample)
                self._temple_input_budget("continuation")
                self.sess.press_kernal(0x0D)
                counters["continuations"] += 1
                continuation_visible = True
                continue
            continuation_visible = False
            if re.search(r"\bPRESS\b", text):
                self._temple_stop("prompt", "unapproved PRESS prompt", sample)
            place = self._temple_place(sample.state)
            if sample.state["mode"] == S.COMBAT:
                self._temple_stop("encounter", "encounter after movement", sample)
            if (place in (before, expected)
                    and self._temple_bar_blank(screen)):
                kind = ("temple-quiet-screen" if self._temple_is_quiet(screen)
                        else "temple-text-screen")
                if kind not in seen_kinds:
                    self.log.emit(kind, move=n + 1, place=place)
                    seen_kinds.add(kind)
                time.sleep(0.3)
                continue
            if place == expected:
                mode_ok = (sample.state["mode"] == S.DUNGEON
                           or (n == TEMPLE_LAST_INDEX
                               and sample.state["mode"] == TEMPLE_ARRIVAL_MODE))
                if sample.state["area_pending"] or not mode_ok:
                    time.sleep(0.3)
                    continue
                if n == TEMPLE_LAST_INDEX and self._temple_is_greeting(screen):
                    if S.word_column(screen.row(24), "HEAL") < 0:
                        self._temple_stop("menu", "HEAL absent from temple bar",
                                          sample)
                elif n == TEMPLE_LAST_INDEX:
                    if not (self._temple_is_world(screen)
                            or self._temple_is_move(screen)):
                        self._temple_stop("event", "unexpected temple arrival",
                                          sample)
                    time.sleep(0.3)
                    continue
                elif not (self._temple_is_world(screen)
                          or self._temple_is_move(screen)):
                    self._temple_stop("event", "unexpected screen after movement",
                                      sample)
                status = S.parse_status(screen.text())
                greeting = (n == TEMPLE_LAST_INDEX
                            and self._temple_is_greeting(screen))
                if status is None:
                    # A menu or picture screen (the temple greeting) can
                    # replace the status line; only settling there proceeds
                    # with no status line to check.
                    if not greeting:
                        time.sleep(0.3)
                        continue
                elif (status.x, status.y, status.facing) != expected[1:]:
                    time.sleep(0.3)
                    continue
                if (self._temple_agrees(prior, sample) and prior.screen is not None
                        and prior.screen.text() == screen.text()):
                    tag = ("temple-arrival" if n == TEMPLE_LAST_INDEX
                           else f"move-{n + 1}-settled")
                    return self.temple_checkpoint(tag, sample)
            elif place != before:
                if self._temple_agrees(prior, sample):
                    self._temple_stop("place", f"movement {n + 1} reached "
                                      f"{place}, expected {expected}", sample)
                time.sleep(0.3)
                continue
            elif not (self._temple_is_world(screen)
                      or self._temple_is_move(screen)):
                self._temple_stop("event", "unexpected screen during movement",
                                  sample)
            time.sleep(0.4)
        self._temple_stop("transition", f"movement {n + 1} did not settle "
                          "within 90 seconds")

    def temple_probe(self, who: str) -> dict:
        """Capture the temple arrival screen and stop; go no further.

        The HEAL service list beyond arrival -- its text, its bar, whether
        RAISE DEAD appears, and the resident byte there -- has never been
        seen live (#700). Recognising it would be a guess, so the route
        ends here: reaching and capturing the arrival screen is itself the
        result this probe exists to produce."""
        if who != "BRUTUS" or self.game.key != "pool-of-radiance":
            raise StepFailed("temple probe requires Pool BRUTUS")
        initial = self.temple_checkpoint(
            "loaded-source", self._temple_steady("in the loaded source"))
        place = self._temple_place(initial["state"])
        if (place != TEMPLE_ROUTE[0][1]
                or initial["state"]["mode"] != S.DUNGEON
                or initial["state"]["area_pending"]):
            self._temple_stop("source-place", f"loaded place {place} is not "
                              f"{TEMPLE_ROUTE[0][1]}")
        reading = initial["reading"]
        party = reading.get("party", [])
        named = [p for p in party if p.get("name") == "BRUTUS"]
        member = named[0] if len(named) == 1 else None
        traits = [] if member is None else member.get("traits", [])
        effect_rows = reading.get("effect_rows", [])
        if (member is None or member.get("slot") != 5
                or member.get("status") != 0x03
                or len(traits) != 10 or traits[9] != 32
                or member.get("creature_type") != 4
                or member.get("record_bytes", {}).get("0xA3") != 2
                or len(effect_rows) != 64
                or effect_rows[63] != [63, 32, 5, 0, 5]):
            self._temple_stop("source-identity", "loaded BRUTUS or row 63 "
                              "does not match the registered animated source")
        counters = {"disk": 0, "continuations": 0, "questions": 0}
        arrival = None
        for n, (move, before, expected) in enumerate(TEMPLE_ROUTE):
            self._temple_move(move, before)
            arrival = self._temple_transition(n, before, expected, counters)
        return {"route": "KKIIJI", "movement_keys": 6,
                "side3_prompts": counters["disk"],
                "continuations": counters["continuations"],
                "questions": counters["questions"],
                "arrival": arrival["stem"],
                "checkpoints": len(self.temple_checkpoints)}

    @staticmethod
    def _list_bar(bar: str) -> bool:
        # A list of one spell has no NEXT or PREV, and its bar is exactly
        # `CAST EXIT`; the MAGIC bar also holds CAST and EXIT.
        return bar.strip() == "CAST EXIT" or (
            "EXIT" in bar and any(w in bar for w in ("SPELL", "NEXT", "PREV")))

    def _send_pick(self, key: str) -> None:
        if key == "xtest-return":
            self.sess.kbd.key("Return")
        elif key == "kernal-return":
            self.sess.press_kernal(0x0D)
        else:
            self.sess.kbd.key("KP_0", 0.2, 0.30)

    def _pick_spell(self, listed: list[str], *, needs_target: bool = True) -> str:
        """Pick the spell under the cursor and wait past the list redraw.

        A targeted Curse cure waits for its whom prompt. Pool's whole-party
        Animate Dead row instead runs immediately after the pick.
        """
        keys = ["xtest-return", "kernal-return"] + (["joystick-fire"] if self.joy else [])
        for key in keys:
            self._send_pick(key)
            rows = self.wait_rows(
                lambda r: CAST_WHOM in r[24] or (
                    r != listed and (needs_target or PICK_SPELL not in r[24])),
                self.pick_wait)
            if rows is None:
                continue
            if needs_target:
                if CAST_WHOM not in rows[24]:
                    rows = self.wait_rows(lambda r: CAST_WHOM in r[24],
                                          self.whom_wait)
                if rows is None:
                    raise self.fail("pick-no-whom",
                                    f"{key} changed the spell list but "
                                    f"{CAST_WHOM} never came up")
            elif CAST_WHOM in rows[24]:
                raise self.fail("cast-whom-unexpected",
                                f"{CAST_WHOM} came up for a whole-party spell")
            return key
        raise self.fail("pick", f"none of {', '.join(keys)} picked the spell")

    def _acknowledge(self, limit: int = 4, *, label: str = "cure",
                     until: float | None = None) -> list[list[str]]:
        """Answer up to LIMIT continuation pages and keep their text."""
        def timeout(seconds: float) -> float:
            return seconds if until is None else max(0, min(seconds,
                                                             until - self.clock()))

        rows = self.wait_rows(lambda r: CAST_WHOM not in r[24], timeout(60))
        if rows is None:
            raise self.fail("whom-stuck", "the target question never went away")
        messages: list[list[str]] = []
        for n in range(1, limit + 1):
            if CONTINUE not in rows[24]:
                return messages
            self.sess.settle(0.6)
            shown = self.capture(f"{label}-message-{n}")
            messages.append([t for t in (_inner(r) for r in shown[:24])
                             if t and not _is_frame(t)])
            if until is not None and self.clock() >= until:
                raise self.fail("message-deadline",
                                "Dispel observation deadline before continuation key")
            self.sess.press_kernal(0x0D)
            rows = self.wait_rows(lambda r, was=shown: r != was, timeout(30))
            if rows is None:
                raise self.fail("message", "the key at the end of a message did nothing")
        if CONTINUE in rows[24]:
            raise self.fail("message", f"more than {limit} pages after the cure")
        return messages

    def _observe_dispel(self, before: dict, caster: str) -> list[list[str]]:
        """Wait for a completed Pool Dispel without guessing a blank-page key."""
        start = self.clock()
        until = min(start + 60, self.deadline if self.deadline is not None
                    else float("inf"))
        caster_slot = next(p["slot"] for p in before["party"] if
                           p.get("name", "").upper() == caster.upper())
        messages: list[list[str]] = []

        def stalled() -> StepFailed:
            pc = self.sess.stall_capture()
            self.log.emit("dispel-stall", elapsed=self.clock() - start, pc=pc)
            return self.fail("dispel-pending", "Dispel Magic remained pending "
                             f"for {self.clock() - start:.1f} seconds; {pc}")

        for mark in (0, 2, 10, 30, 60):
            target = min(start + mark, until)
            while self.clock() < target:
                time.sleep(min(0.4, target - self.clock()))
            if self.spent():
                raise stalled()
            rows = self.capture(f"dispel-observe-{mark}")
            reading = self.reading()
            self.log.emit("dispel-observe", elapsed=self.clock() - start,
                          screen=rows, reading=reading)
            bar = rows[24] if rows else ""
            if CONTINUE in bar:
                if self.clock() >= until:
                    raise stalled()
                try:
                    messages.extend(self._acknowledge(label="dispel", until=until))
                except StepFailed:
                    if self.clock() >= until:
                        raise stalled() from None
                    raise
                rows = self.capture("dispel-after-continue")
                reading = self.reading()
                self.log.emit("dispel-observe", elapsed=self.clock() - start,
                              screen=rows, reading=reading)
                bar = rows[24] if rows else ""
            if (self._list_bar(bar) or MAGIC_BAR in bar or CAMP_BAR in bar):
                caster_after = next(p for p in reading["party"] if
                                    p["slot"] == caster_slot)
                consumed = caster_after["memorised"] == []
                if not consumed:
                    continue
                self.log.emit("dispel-outcome", result="menu-consumed",
                              elapsed=self.clock() - start,
                              row=reading["effect_rows"][63])
                return messages
        raise stalled()

    def _dispel_guard(self, before: dict, caster: str, target: str) -> int:
        """Refuse a cast unless its live members and row are the intended ones."""
        party = before.get("party", [])
        def named(name: str) -> list[dict]:
            return [p for p in party if p.get("name", "").upper() == name.upper()]

        casters, targets = named(caster), named(target)
        if len(casters) != 1 or casters[0]["status"] != 1:
            raise self.fail("dispel-caster", f"{caster} is not one living party member")
        if casters[0]["cleric_level"] < 5 or casters[0]["memorised"] != [41]:
            raise self.fail("dispel-caster", f"{caster} needs cleric level 5 and only "
                            "Dispel Magic id 41 memorised")
        if len(targets) != 1:
            raise self.fail("dispel-target", f"{target} is not one named party member")
        victim = targets[0]
        if (victim["status"] != 3 or 32 not in victim["traits"]
                or victim["creature_type"] != 4):
            raise self.fail("dispel-target", f"{target} is not the animated member")
        slot = victim["slot"]
        rows = before.get("effect_rows", [])
        if len(rows) != effects.EFFECT_SLOTS or rows[63][:3] != [63, 32, slot]:
            raise self.fail("dispel-row", f"{target} has no id-32 row at index 63")
        if rows[63][4] == 0xFF or rows[63][4] & 0x0F > casters[0]["cleric_level"]:
            raise self.fail("dispel-resistance", f"{target}'s row is not eligible "
                            "for this Dispel Magic cast")
        return slot

    def _dispel_result(self, before: dict, after: dict, slot: int) -> None:
        """Check the game cleared only the expected array id for this cast."""
        earlier, later = before["effect_rows"], after.get("effect_rows", [])
        expected = [row.copy() for row in earlier]
        expected[63][1] = 0
        if later != expected:
            raise self.fail("dispel-row", "Dispel Magic did not clear only "
                            "row 63's id")
        old = next(p for p in before["party"] if p["slot"] == slot)
        new = next((p for p in after.get("party", []) if p["slot"] == slot), None)
        if new != old:
            raise self.fail("dispel-member", "Dispel Magic changed the named "
                            "member's zombie fields")

    def cast(self, arg: str) -> dict:
        caster, spell, target = parse_cast(arg)
        dispel = spell in POOL_TARGET_SPELLS
        if dispel:
            before = self.reading()
            self.log.emit("dispel-before", reading=before)
            slot = self._dispel_guard(before, caster, target)
        elif target is not None:
            cure_id, word = CAMP_CURES[spell]
            self.owner_of(target)
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        if not self.sess.select_party(self.panel_index(caster)):
            raise self.fail("panel", f"the panel highlight would not go onto {caster}")
        if not self.choose_bar("MAGIC", timeout=20) or self.wait_rows(
                lambda r: MAGIC_BAR in r[24], 30) is None:
            raise self.fail("magic", "MAGIC never put up its bar")
        if not self.choose_bar("CAST", timeout=20):
            raise self.fail("cast", "CAST could not be chosen")
        if self.wait_rows(lambda r: self._list_bar(r[24]), 30) is None:
            raise self.fail("cast-list", "the spell list never came up")
        self.sess.settle(1)
        self.capture("cast-list")
        if not self.choose_bar("CAST", timeout=20):
            raise self.fail("cast-again", "CAST could not be chosen on the spell list")
        if self.wait_rows(lambda r: PICK_SPELL in r[24], 10) is None:
            raise self.fail("pick-prompt", f"{PICK_SPELL} never came up")
        # A key sent before the game polls its input routine is thrown away.
        self.sess.settle(1)
        listed = self.capture("pick-list")
        if dispel and sum(spell in _inner(row) for row in listed[3:24]) != 1:
            raise self.fail("dispel-spell", f"{spell} was not the single shown spell")
        if target is None:
            before = self.reading()
        key = self._pick_spell(listed, needs_target=target is not None)
        if target is None:
            self.capture("cast-result")
            messages = self._acknowledge(label="cast")
            if self._list_bar(self.bar()):
                self.choose_bar("EXIT", timeout=15)
            after = self.reading()
            return {"caster": caster, "spell": spell,
                    "spell_id": CAMP_PARTY_SPELLS[spell],
                    "party_before": before["party"], "party_after": after["party"],
                    "effects_before": before["effects"],
                    "effects_after": after["effects"],
                    "messages": messages, "key": key}

        first = self.reading() if not dispel else before
        if not self.pick(target, CAST_WHOM):
            raise self.fail("cast-whom", f"{target} could not be chosen")
        if dispel:
            self.capture("dispel-result")
            messages = self._observe_dispel(before, caster)
        else:
            messages = self._acknowledge(label="cure")
        # The cured row clears only after the spell list is exited.
        if self._list_bar(self.bar()):
            self.choose_bar("EXIT", timeout=15)
        if dispel:
            after = self.reading()
            self.log.emit("dispel-after", reading=after)
            if after["effect_rows"] == before["effect_rows"]:
                self.log.emit("dispel-outcome", result="unsuccessful-roll",
                              row=after["effect_rows"][63])
                raise self.fail("dispel-roll", "Dispel Magic completed an "
                                "unsuccessful roll; row 63 stayed unchanged")
            self._dispel_result(before, after, slot)
            return {"caster": caster, "spell": spell, "spell_id": 41,
                    "target": target, "slot": slot,
                    "row_before": before["effect_rows"][63],
                    "row_after": after["effect_rows"][63],
                    "party_before": before["party"], "party_after": after["party"],
                    "effects_before": before["effects"],
                    "effects_after": after["effects"],
                    "effect_rows_before": before["effect_rows"],
                    "effect_rows_after": after["effect_rows"],
                    "messages": messages, "key": key}
        last = self._settle_row(cure_id, self.owner_of(target), self.reading())
        return self._outcome("caster", caster, target, cure_id, word, first, last,
                             spell=spell, messages=messages, key=key)

    def camp_list(self, who: str) -> dict:
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        if not self.choose_bar("MAGIC", timeout=20) or self.wait_rows(
                lambda r: MAGIC_BAR in r[24], 30) is None:
            raise self.fail("magic", "MAGIC never put up its bar")
        if not self.choose_bar("DISPLAY", timeout=20) or self.wait_rows(
                lambda r: WHOM in r[24], 30) is None:
            raise self.fail("display", "DISPLAY never asked on whom")
        self.sess.settle(1)
        offered = whom_entries(self.capture("camp-whom"))
        named = [n.strip() for n in who.split(",") if n.strip()]
        targets = named or offered or [WHOLE_PARTY]
        lists: dict[str, list[str]] = {}
        for target in targets:
            if not self.pick(target):
                raise self.fail("whom", f"{target} could not be chosen")
            lists[target] = self._pages(target)
        if not self.to_world():
            raise self.fail("world", "the world bar never came back after the camp list")
        return {"offered": offered, "lists": lists}

    def pick(self, target: str, question: str = WHOM) -> bool:
        """Choose TARGET on the whom menu, which is the party panel: the
        highlight is walked there by `Session.select_party`, since the panel's
        heading is drawn in the highlight colour too, and Return chooses.
        QUESTION is the one on row 24: the camp list's or `CAST_WHOM`."""
        rows = self.wait_rows(lambda r: question in r[24], 30)
        if rows is None:
            return False
        entries = whom_entries(rows, question) + ["EXIT"]
        if target.isdigit():
            at = int(target) - 1
        else:
            wanted = (target.upper(), screens.as_drawn(target).upper())
            at = next((i for i, e in enumerate(entries) if e.upper() in wanted), None)
        if at is None or not 0 <= at < len(entries):
            self.log.say(f"  {target} is not on the whom menu: {entries}")
            return False
        if not self.sess.select_party(at):
            return False
        self.sess.kbd.key("Return")
        return True

    def _pages(self, target: str, limit: int = 8) -> list[str]:
        spells: list[str] = []
        for n in range(1, limit + 1):
            rows = self.wait_rows(lambda r: _has(r, AFFECTED) and CONTINUE in r[24], 30)
            if rows is None:
                raise self.fail("camp-list", f"no page of {target}'s list came up")
            self.sess.settle(0.6)
            rows = self.capture(f"camp-list-{target}-{n}")
            page = camp_list_page(rows)
            spells += page.spells if page else []
            self.sess.press_kernal(0x0D)
            after = self.wait_rows(
                lambda r, was=rows: r != was and (
                    WHOM in r[24] or (_has(r, AFFECTED) and CONTINUE in r[24])), 30)
            if after is None:
                raise self.fail("camp-list", "the key at the end of a page did nothing")
            if WHOM in after[24]:
                return spells
        raise self.fail("camp-list", f"more than {limit} pages")

    def open_sheet(self, who: str) -> list[str]:
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        if not self.sess.select_party(self.panel_index(who)):
            raise self.fail("panel", f"the panel highlight would not go onto {who}")
        if not self.choose_bar("VIEW", timeout=20):
            raise self.fail("view", "VIEW could not be chosen")
        # `wait_rows` calls `handle_prompt`, which answers a sheet's own
        # portrait disk prompt with the side it names -- the side already in
        # the drive when the character's art is not on it, so the load fails
        # and the prompt loops forever (#694). `route_pool.wait_sheet_bar`
        # answers that one prompt with `PORTRAIT_SIDE` instead.
        if not route_pool.wait_sheet_bar(
                self.sess, self.budget(90, "a character sheet")):
            raise self.fail("view", "no character sheet came up")
        self.sess.settle(0.8)
        return self.capture(f"sheet-{who}")

    def view(self, who: str) -> dict:
        rows = self.open_sheet(who)
        self.to_world()
        return {"who": who, "sheet": [r.rstrip() for r in rows if r.strip()]}

    def items(self, who: str) -> dict:
        sheet = self.open_sheet(who)
        if not self.choose_bar("ITEMS", timeout=15) or self.wait_rows(
                lambda r: ITEM_BAR in r[24] and S.SHEET_BAR not in r[24], 20) is None:
            raise self.fail("items", "ITEMS never put up the item list")
        self.sess.settle(1)
        entries = item_entries(self.capture(f"items-{who}"))
        self.to_world()
        return {"who": who, "sheet": [r.rstrip() for r in sheet if r.strip()],
                "entries": entries,
                "marked": [e["row"] for e in entries if e["marked"]]}

    def ready(self, arg: str) -> dict:
        """`ready WHO>LABEL`: toggle one item and read every party record and
        the effect and item arrays before and after, Pool of Radiance only.

        Reaches the item list through camp, not the world's `VIEW`: a
        magical item's READY toggle (`LIBRARY $4630`) is refused with `NOT
        HERE` unless `$6DE4` is set, which only camp sets (#694).
        `tools/c64/route_pool.py`'s `SLOT_BASE`, `SLOT_STRIDE` and `EFFECTS`
        are Pool's own layout, the same one `traitask.stage_items` and
        `route_pool.toggle_item` already drive; `main` refuses this step for
        Curse and Silver Blades.
        """
        who, label = parse_ready(arg)
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        if not route_pool.open_items(self.sess, self.log, who, label, "ready"):
            raise self.fail("items", "ITEMS never put up the item list")
        with self.sess.mon(8) as m:
            before_records = [bytes(route_pool.live_record(m, slot))
                              for slot in range(PARTY_SLOTS)]
            before_effects = bytes(route_pool.live_effects(m))
            before_items = [bytes(m.read(ITEM_AREA_BASE + slot * ITEM_BLOCK_STRIDE,
                                         ITEM_BLOCK_STRIDE))
                            for slot in range(PARTY_SLOTS)]
            m.resume()
        if self.capture_ready:
            self.ready_captures = []
            self.ready_sample_errors = []
            screen_changed = route_pool.toggle_item(
                self.sess, self.log, label, "ready", sample=self.sample_ready)
        else:
            screen_changed = route_pool.toggle_item(self.sess, self.log, label, "ready")
        self.sess.settle(1)
        with self.sess.mon(8) as m:
            after_records = [bytes(route_pool.live_record(m, slot))
                             for slot in range(PARTY_SLOTS)]
            after_effects = bytes(route_pool.live_effects(m))
            after_items = [bytes(m.read(ITEM_AREA_BASE + slot * ITEM_BLOCK_STRIDE,
                                        ITEM_BLOCK_STRIDE))
                           for slot in range(PARTY_SLOTS)]
            m.resume()
        record_diff = {
            slot: route_pool.diff_bytes(
                before_records[slot], after_records[slot],
                route_pool.SLOT_BASE + slot * route_pool.SLOT_STRIDE)
            for slot in range(PARTY_SLOTS)}
        effects_diff = route_pool.diff_bytes(before_effects, after_effects,
                                             route_pool.EFFECTS[0])
        item_diff = {
            slot: route_pool.diff_bytes(
                before_items[slot], after_items[slot],
                ITEM_AREA_BASE + slot * ITEM_BLOCK_STRIDE)
            for slot in range(PARTY_SLOTS)}
        memory_changed = (any(record_diff.values()) or bool(effects_diff)
                          or any(item_diff.values()))
        route_pool.leave_items(self.sess, self.log)
        self.to_world()
        result = {"who": who, "label": label,
                  "screen_changed": screen_changed, "flipped": screen_changed,
                  "memory_changed": memory_changed,
                  "record_diff": record_diff, "effects_diff": effects_diff,
                  "item_diff": item_diff}
        if self.capture_ready:
            result["ready_captures"] = self.ready_captures
            result["ready_sample_errors"] = self.ready_sample_errors
        return result

    def rest(self, arg: str) -> dict:
        minutes, hours = parse_rest(arg)
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        got = route_pool.rest(self.sess, self.log, minutes, hours, self.armed)
        self.capture(f"rested-{arg}")
        if "failed" in got:
            raise self.fail("rest", got["failed"])
        self.to_world()
        return {"asked": [minutes, hours], "before_clock": got["before"]["clock"],
                "after_clock": got["after"]["clock"]}

    def fight_over_budget(self, arg: str, result) -> StepFailed:
        """The failure for a fight that ran out of SECONDS.

        A run cannot continue from an unfinished fight, so the step is lost;
        the checkpoint counts are read first and kept as `lost_reading`, so
        the evidence of a deliberately short skirmish is not lost with it."""
        self.keep_fight_reading()
        return self.fail("fight", f"the fight ran out of its {arg or 120} "
                                  f"second budget after {result.turns} turns")

    def fight_lost(self, result) -> StepFailed:
        """The failure for a fight the party lost.

        The game leaves the world after a defeat, so a later step would fail
        on the wrong cause; the checkpoint counts are kept as `lost_reading`."""
        self.keep_fight_reading()
        return self.fail("fight", f"the party lost the fight after "
                                  f"{result.turns} turns")

    def keep_fight_reading(self) -> None:
        with contextlib.suppress(Exception):
            self.lost_reading = {"step": "fight", "after": self.reading()}

    def fight(self, arg: str, walk: str, steps: int) -> dict:
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        taken = 0
        # An encounter that opens on a menu is answered with the fight.
        self.sess.walk_encounter = S.ENCOUNTER_FIGHT
        try:
            while not self.sess.in_combat() and taken < steps:
                self.sess.walk_one(walk)
                self.sess.handle_prompt()
                taken += 1
        finally:
            self.sess.walk_encounter = None
        if not self.sess.in_combat():
            raise self.fail("fight", f"no fight in {taken} steps of {walk}")
        self.capture("fight-start")
        result = self.sess.fight(budget=float(arg or 120),
                                 tactic=S.Session.melee_turn)
        self.capture("fight-end")
        if result.outcome == S.BUDGET:
            raise self.fight_over_budget(arg, result)
        if result.outcome == S.LOST:
            raise self.fight_lost(result)
        return {"walked": taken, "acted": result.acted,
                **dataclasses.asdict(result)}

    def _wait_idle(self, need: int = 6) -> bool:
        """Wait until the engine is back in its key-wait loop and stays there.

        A fixed settle would measure the floppy, and a read taken while the
        arriving area is still loading sees it half loaded.  Unlike
        `tools/areas/wallpins.py`'s `wait_idle`, it fails the step instead of
        returning False, and the run's deadline bounds it.
        """
        idle_ranges = (fasttravel.POOL_OF_RADIANCE.key_wait,
                       fasttravel.POOL_OF_RADIANCE.key_fetch)
        inloop = 0
        limit = self.clock() + WARP_IDLE_SECONDS
        while self.clock() < limit:
            self.sess.settle(2)
            try:
                with self.sess.mon(5) as m:
                    pc = m.registers().get(auto_actions.pc_register(m))
            except Exception:                   # noqa: BLE001
                pc = None
            idle = pc is not None and any(lo <= pc < hi for lo, hi in idle_ranges)
            inloop = inloop + 1 if idle else 0
            if inloop >= need:
                return True
            self.budget(1, "the key-wait loop after a warp")
        raise self.fail("warp", "the engine never went back to its key-wait loop")

    def warp(self, arg: str) -> dict:
        area = parse_warp(arg)
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        target = SessTarget(self.sess)
        ft = auto_actions.FastTravel()
        row = auto_actions.area_by_id(area)
        verdict = ft.legality(target, row)
        if not verdict.ok:
            raise self.fail("warp", verdict.reason)
        writes = auto_actions.newecl_writes(ft.current_area(target) or 0, area,
                                            getattr(row, "disk", None), None)
        listing = [f"${a:04X}={bytes(d).hex()}" for a, d in writes]
        self.log.say("  writes: " + ", ".join(listing))
        auto_actions._write_all(target, writes)
        if not auto_actions.jump(target, fasttravel.POOL_OF_RADIANCE.tail):
            raise self.fail("warp", "the program counter could not be set")
        self._wait_idle()
        self.sess.settle(4)
        with self.sess.mon(5) as m:
            triple = list(bytes(m.read(0xC04B, 3)))
        want = ARRIVAL_FACING.get(area)
        if want is not None and triple[2] != want:
            raise self.fail("warp", f"$C04D read {triple[2]} after the warp, "
                                    f"not {want} (triple {triple})")
        self.capture(f"warped-{area}")
        return {"area": area, "writes": listing, "triple": triple,
                "position": self.position()}

    def refuse_prompt(self, route: str, last, why: str) -> None:
        """Fail the walk when a disk prompt is on the screen, answering nothing."""
        screen = self.sess.screen()
        if screen is None or not self.sess.wanted_disk(screen):
            return
        row = screen.row(24).strip()
        if last is None:
            raise self.fail("walk", f"walk {route}: a disk prompt was up "
                                    f"before the first move: {row}")
        n, move, before = last
        raise self.fail(
            "walk", f"walk {route}: move {n} ({move}) from {before} {why}, "
                    f"not a step: {row}")

    def walk(self, arg: str) -> dict:
        """The moves in ARG, each judged by the square before and after.

        The status line holds the clock, so `Session.walk_one`'s answer is
        recorded and never believed: a bump advances the clock and the line
        still changes.  A forward move is blocked when x,y did not change; a
        turn is right when the facing is the one it asks for and the square
        did not change, which is the control that a walk is not a turn.  `M`
        is not a turn: the engine turns about and tries the edge behind the
        original facing (#708), and the two outcomes are paired -- it either
        steps back one square exactly behind that facing, the same
        exit-or-teleport check `I` gets, with the facing kept, or it stays on
        the square with the facing exactly reversed; no other combination of
        movement and facing is possible.

        A disk prompt on the screen fails the walk and is never answered: a
        square's event asks for another disk, and answering would carry the
        walk into another area.  It is looked for before each move, after
        each key, for two seconds after each move and before the end is read,
        and `Session.walk_one` runs with `answer_prompts=False` so it does not
        answer one itself.  A forward move must also land on exactly the next
        square, or the walk fails as an exit or a teleport.  A move `walk_one`
        made on the travel grid is not re-sent.

        A bump is retried like any unread key: a wall leaves the triple
        unchanged, so the key goes twice, each press polled by `walk_one` for
        up to 12 s, and the walk still fails as blocked (about 12 s extra).

        Curse and Silver Blades are judged by the live triple `$C04B`-`$C04D`
        because their status line stays a step behind; their one retry is
        judged by it as well, since move mode changes row 24 on any first key.

        The one retry is judged by the screen just before the key against the
        screen 1.2 s after it (`Session.walk_screens`), resent only when they
        are identical, since text that `MOVE` put up changes the whole move's
        screen without the key having been read.  Each `move` record keeps
        the text rows the game showed at the key and whether a key was sent.
        """
        route = parse_walk(arg)
        # `Session.walk_one` stops waiting for the sub-bar at the run's deadline.
        self.sess.walk_expired = self.spent
        try:
            return self._walk(route)
        finally:
            self.sess.walk_expired = None

    def position(self) -> list:
        """Where the party stands: the status line's x, y and facing."""
        return list(self.sess.position())

    def steady_position(self) -> list | None:
        """`position`, or None when a read the title cannot settle did not."""
        return self.position()

    def took_nothing(self, before, before_rows, screens) -> bool:
        """Whether the key just sent was not read by the game."""
        if screens is not None and screens[1] is not None:
            # Judge the key's own window: a text `MOVE` put up before the
            # key changes the whole move's screen, not the key's.
            return screens[0] == screens[1]
        return self.rows() == before_rows

    def _judge_about_turn(self, route: str, n: int, before, after) -> None:
        """Fail an `M` whose square and facing are not one of the two outcomes.

        `M` turns about and tries the edge behind the original facing.  No wall
        art there: one square back, facing kept.  An open door there: one
        square back, facing reversed.  A solid wall there: no move, facing
        reversed.
        """
        moved = after[:2] != before[:2]
        reversed_facing = (before[2] + 2) % 4
        if moved:
            dx, dy = STEP[reversed_facing]
            if after[:2] != [before[0] + dx, before[1] + dy]:
                raise self.fail(
                    "walk", f"walk {route}: move {n} moved from {before} "
                            f"to {after}, not one square behind: an exit "
                            f"or a teleport")
            if after[2] is not None and after[2] not in (
                    before[2], reversed_facing):
                raise self.fail(
                    "walk", f"walk {route}: move {n} (M) stepped back "
                            f"from {before} to {after} so should face "
                            f"{before[2]} or {reversed_facing}, it "
                            f"faces {after[2]}")
        elif after[2] is not None and after[2] != reversed_facing:
            raise self.fail(
                "walk", f"walk {route}: move {n} (M) stayed at "
                        f"{before} so should reverse facing to "
                        f"{reversed_facing}, it faces {after[2]}")

    def leave_arrival(self, step: str) -> None:
        """Answer the `PRESS ... TO CONTINUE` bar a warp's arrival text leaves.

        Each page gets one Return, then row 24 is read until it changes; a
        move key sent at the bar would be taken as the answer to it.  Some
        arrivals show more than one page, so up to `ARRIVAL_PRESSES` are
        answered, and a bar that outlasts them fails the step naming its text.
        Any other bar returns, for `to_world` to wait out.
        """
        for _ in range(ARRIVAL_PRESSES):
            screen = self.sess.screen()
            if screen is None:
                return
            state = self.sess.combat_state(screen)
            if state.kind != S.BAR_PRESS:
                return
            self.sess.press_kernal(0x0D)
            until = self.clock() + ARRIVAL_PAGE_SECONDS
            while self.bar().strip() == state.text and self.clock() < until:
                self.budget(1, f"{step} arrival")
                time.sleep(0.4)
        screen = self.sess.screen()
        if screen is not None and self.sess.combat_state(screen).kind == S.BAR_PRESS:
            raise self.fail("world", f"{step}: the world bar never came back, "
                                     f"row 24 still reads "
                                     f"{self.bar().strip()!r}")

    def _walk(self, route: str) -> dict:
        self.leave_arrival(f"walk {route}")
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        self.leave_arrival(f"walk {route}")
        start = self.position()
        facing = start[2]
        moves = []
        last = None
        for n, move in enumerate(route):
            self.budget(1, f"walk {route}")
            # A prompt that opened after the previous move's look would be
            # answered by this move's `select_bar`, so it is looked for first.
            self.refuse_prompt(route, last, "was up before the next move")
            before = self.position()
            last = (n, move, before)
            before_rows = self.rows()
            status_moved = self.sess.walk_one(move, tries=1, answer_prompts=False)
            resent = False
            self.refuse_prompt(route, last, "ran the square's event")
            # Out on the travel grid a move is pressed once and never re-sent:
            # the status line lags and a turn does not exist there.
            screens = getattr(self.sess, "walk_screens", None)
            if (not status_moved and self.took_nothing(before, before_rows, screens)
                    and not getattr(self.sess, "walked_outdoors", False)):
                # The one retry the contract allows: the game took nothing.
                resent = True
                status_moved = self.sess.walk_one(move, tries=1,
                                                  answer_prompts=False)
                self.refuse_prompt(route, last, "ran the square's event")
                screens = getattr(self.sess, "walk_screens", None)
            refused = getattr(self.sess, "walk_refused", None)
            if refused:
                self.log.emit("move", move=move, n=n, before=before,
                              after=self.steady_position(), resent=resent,
                              row24=self.bar().strip(), text=None, keyed=False)
                raise self.fail("walk", f"walk {route}: {refused}")
            # A square's event may put up a disk prompt after the key has been
            # read; answering it would carry the walk into another area.
            look_until = self.clock() + LOOK_SECONDS
            while True:
                self.budget(1, f"walk {route}")
                self.refuse_prompt(route, last, "ran the square's event")
                if self.clock() >= look_until:
                    break
                time.sleep(0.3)
            # A step whose question is typed after `walk_one` returns leaves
            # the status line stale; the screen is what says it is up.
            stopped = self.sess.walk_stop(wait=12.0)
            if stopped is not None:
                key_rows = screens[0] if screens else None
                self.log.emit(
                    "move", move=move, n=n, before=before,
                    after=self.steady_position(), resent=resent,
                    row24=self.bar().strip(),
                    text=(None if key_rows is None else
                          [r.strip() for r in key_rows[17:23]]),
                    keyed=True, stop_screen=[r.strip() for r in stopped])
                raise self.fail(
                    "walk", f"walk {route}: move {n} ({move}) from {before} "
                            f"ended on a screen a walk does not answer: "
                            f"{stopped[24].strip()}")
            after = self.position()
            key_rows = screens[0] if screens else None
            text = (None if key_rows is None else
                    [r.strip() for r in key_rows[17:23]])
            m_outcome = None
            if move == "M" and before[2] is not None:
                # Recorded so a door case can be told from a plain step back
                # in the evidence files; `_walk` judges it below.
                if after[:2] == before[:2]:
                    m_outcome = "turned"
                elif after[2] == before[2]:
                    m_outcome = "back-kept"
                elif after[2] == (before[2] + 2) % 4:
                    m_outcome = "back-reversed"
                else:
                    m_outcome = "back-other"
            extra = {} if m_outcome is None else {"m_outcome": m_outcome}
            self.log.emit("move", move=move, n=n, before=before, after=after,
                          resent=resent, row24=self.bar().strip(), text=text,
                          keyed=True, **extra)
            if (move == "I" and after[:2] != before[:2]
                    and before[2] is not None):
                dx, dy = STEP[before[2]]
                if after[:2] != [before[0] + dx, before[1] + dy]:
                    raise self.fail(
                        "walk", f"walk {route}: move {n} moved from {before} "
                                f"to {after}, not one square ahead: an exit "
                                f"or a teleport")
            if move == "M" and before[2] is not None:
                self._judge_about_turn(route, n, before, after)
                if after[2] is not None:
                    facing = after[2]
            elif facing is not None:
                facing = (facing + TURNS[move]) % 4
            moves.append({"move": move, "before": before, "after": after,
                          "blocked": move == "I" and before[:2] == after[:2],
                          "moved": before[:2] != after[:2],
                          "status_moved": status_moved, "resent": resent})
        self.refuse_prompt(route, last, "ran the square's event")
        end = self.position()
        self.capture(f"walked-{route}")
        if not ("I" in route or "M" in route) and end[:2] != start[:2]:
            raise self.fail("walk", f"walk {route} has no forward move and the "
                                    f"square went from {start[:2]} to {end[:2]}")
        if facing is not None and end[2] is not None and end[2] != facing:
            raise self.fail("walk", f"walk {route} should leave the party facing "
                                    f"{facing}, it faces {end[2]}")
        return {"route": route, "start": start, "position": end, "moves": moves,
                "asked_forward": route.count("I"),
                "squares_moved": sum(m["moved"] for m in moves),
                "blocked": [i for i, m in enumerate(moves) if m["blocked"]],
                "expected_facing": facing}

    def walk_fight(self, arg: str) -> dict:
        """Walk a route, fighting every encounter the route meets, and resume.

        An encounter menu is answered COMBAT and never FLEE, which would
        teleport the party off its route.  Each fight is fought out with
        `Session.melee_turn`, and the next key is judged from the square the
        fight left the party on.  An `I` that left the party where it stood is
        sent once more; a `YES NO` is answered NO on the route's last key when
        `/NO` was given and fails the step anywhere else, with nothing pressed.
        """
        route, answer = parse_walk_fight(arg)
        self.leave_arrival(f"walk-fight {route}")
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        self.leave_arrival(f"walk-fight {route}")
        # `Session._stop_walk` answers an encounter menu with this word and
        # presses nothing else; `walk_expired` bounds its waits by the run.
        self.sess.walk_encounter = S.ENCOUNTER_FIGHT
        self.sess.walk_expired = self.spent
        try:
            return self._walk_fight(route, answer)
        finally:
            self.sess.walk_encounter = None
            self.sess.walk_expired = None

    def _walk_fight(self, route: str, answer: str | None) -> dict:
        moves, fights = [], []
        for n, move in enumerate(route):
            self.budget(1, f"walk-fight {route}")
            last = (n, move, self.position())
            self.refuse_prompt(route, last, "was up before the next move")
            before = last[2]
            resent = False
            for attempt in (0, 1):
                # A key is sent again only when the party is where it was and
                # either a fight took the key or the game read nothing: the
                # position can lag a real move, and a second key would then
                # take a second step.
                again = self._walk_fight_key(
                    route, n, move, before, last,
                    answer if n == len(route) - 1 else None, fights)
                after = self.position()
                if after == before and again and attempt == 0:
                    resent = True
                    continue
                break
            self._judge_walk_fight(route, n, move, before, after, resent)
            self.log.emit("move", move=move, n=n, before=before, after=after,
                          resent=resent, row24=self.bar().strip())
            moves.append({"move": move, "before": before, "after": after,
                          "moved": before[:2] != after[:2], "resent": resent})
        self.refuse_prompt(route, (len(route) - 1, route[-1], self.position()),
                           "ran the square's event")
        self.capture(f"walked-{route}")
        return {"route": route, "answer": answer, "position": self.position(),
                "fights": fights, "moves": moves}

    def _walk_fight_key(self, route, n, move, before, last, answer, fights) -> bool:
        """One key, then whatever it started: an encounter menu, a `YES NO`,
        a fight.  A fight is fought out and the world bar waited for.

        Returns whether the key may be sent again if the party is still where
        it was: a fight was fought, or `walk_one` reported no move and the
        screen agrees the game read nothing (the test `walk` uses)."""
        sess = self.sess
        before_rows = self.rows()
        moved = sess.walk_one(move, tries=1, answer_prompts=False)
        screens = getattr(sess, "walk_screens", None)
        unread = (not moved and self.took_nothing(before, before_rows, screens)
                  and not getattr(sess, "walked_outdoors", False))
        self.refuse_prompt(route, last, "ran the square's event")
        stop = getattr(sess, "walk_stop_screen", None)
        refused = getattr(sess, "walk_refused", None)
        if refused and stop is None:
            raise self.fail("walk-fight", f"walk-fight {route}: {refused}")
        pressed = stop is not None
        if stop is None:
            look_until = self.clock() + LOOK_SECONDS
            while not sess.in_combat():
                self.budget(1, f"walk-fight {route}")
                self.refuse_prompt(route, last, "ran the square's event")
                if self.clock() >= look_until:
                    break
                time.sleep(0.3)
            if not sess.in_combat():
                stop = sess.walk_stop(wait=12.0)
        if stop is not None:
            self._answer_stop(route, n, move, before, stop, pressed, answer)
            if not self._fight_opens():
                raise self.fail(
                    "walk-fight", f"walk-fight {route}: move {n} ({move}) from "
                                  f"{before} answered {stop[24].strip()!r} and "
                                  f"no fight opened in "
                                  f"{int(FIGHT_OPENS_SECONDS)} seconds")
        if not sess.in_combat():
            return unread
        number = len(fights)
        self.capture(f"fight-{number}-start")
        result = sess.fight(budget=WALK_FIGHT_SECONDS, tactic=S.Session.melee_turn)
        self.capture(f"fight-{number}-end")
        if result.outcome == S.LOST:
            raise self.fight_lost(result)
        if result.outcome == S.BUDGET:
            raise self.fight_over_budget(str(int(WALK_FIGHT_SECONDS)), result)
        self.to_world()
        fights.append({"at_move": n, "square": self.position(),
                       **dataclasses.asdict(result)})
        return True

    def _answer_stop(self, route, n, move, before, rows, pressed, answer) -> None:
        """Answer a screen a walk stops at, or fail the step pressing nothing.

        COMBAT is the only encounter answer.  `pressed` is true when
        `walk_one` has already taken it."""
        row = rows[24]
        if S.word_column(row, "YES") >= 0 and S.word_column(row, "NO") >= 0:
            if answer != "NO":
                raise self.fail(
                    "walk-fight", f"walk-fight {route}: move {n} ({move}) from "
                                  f"{before} reached a question, "
                                  f"{row.strip()!r}, and only NO on the last "
                                  f"key is allowed; nothing was pressed")
            self.sess.select_bar("NO", timeout=8)
        elif S.word_column(row, S.ENCOUNTER_FIGHT) >= 0:
            if not pressed:
                self.sess.select_bar(S.ENCOUNTER_FIGHT, timeout=8)
        else:
            raise self.fail(
                "walk-fight", f"walk-fight {route}: move {n} ({move}) from "
                              f"{before} ended on a screen the step does not "
                              f"answer: {row.strip()}")

    def _fight_opens(self) -> bool:
        limit = self.clock() + FIGHT_OPENS_SECONDS
        while not self.sess.in_combat():
            if self.clock() >= limit:
                return False
            self.budget(1, "a fight to open")
            time.sleep(0.5)
        return True

    def _judge_walk_fight(self, route, n, move, before, after,
                          resent: bool = False) -> None:
        if before[2] is None or after[2] is None:
            raise self.fail("walk-fight", f"walk-fight {route}: move {n} ({move}) "
                                          f"cannot be judged, the facing was not "
                                          f"read: {before} to {after}")
        if move == "I":
            dx, dy = STEP[before[2]]
            if after[:2] == [before[0] + dx, before[1] + dy]:
                return
            if after[:2] == before[:2]:
                raise self.fail("walk-fight", f"walk-fight {route}: move {n} (I) "
                                              f"left the party on {before} "
                                              f"after it was sent "
                                              f"{'twice' if resent else 'once'}")
            raise self.fail(
                "walk-fight", f"walk-fight {route}: move {n} moved from {before} "
                              f"to {after}, not one square ahead: an exit or a "
                              f"teleport")
        if move == "M":
            self._judge_about_turn(route, n, before, after)
        elif (after[:2] != before[:2]
              or after[2] != (before[2] + TURNS[move]) % 4):
            raise self.fail("walk-fight", f"walk-fight {route}: move {n} "
                                          f"({move}) took {before} to {after}, "
                                          f"not a turn on the square")

    def peek(self, arg: str) -> dict:
        addr, n = parse_peek(arg)
        with self.sess.mon(10) as m:
            data = bytes(m.read(addr, n))
            m.resume()
        return {"address": f"${addr:04X}", "bytes": data.hex(" ")}

    def write_save(self) -> list[str]:
        """Pool's `ENCAMP > SAVE`, and the screen it ends on.

        `Session.save_game` gives the write a fixed fourteen seconds, which a
        slow pooled slot can overrun, and Pool's own progress text is not
        measured here (`SAVING GAME` is, in Curse and Silver Blades: see
        `CurseRun.write_save`).  A bar coming back can precede the end of the
        write, so this wait does not prove it finished: `copy_closed_disk` is
        what guards the copy, by refusing a disk whose directory is open.
        """
        if not self.sess.save_game():
            raise self.fail("save", "ENCAMP > SAVE did not complete")
        back = self.wait_rows(
            lambda r: any(w in r[24] for w in (CAMP_BAR, SAVE_BAR, SAVE_ERROR))
            or self.at_world(r[24]), SAVE_WAIT, "a bar after SAVE GAME")
        if back is None:
            raise self.fail("save", "no bar came back after SAVE GAME")
        return back

    def save(self, staged: dict) -> dict:
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        back = self.write_save()
        if SAVE_ERROR in back[24]:
            raise self.fail("save", f"the game could not save: {back[24].strip()}")
        self.capture("saved")
        self.to_world()
        kept = self.out / "saved.D64"
        try:
            S.copy_closed_disk(pathlib.Path(self.sess.save_disk), kept,
                               attempts=30, backoff=1.0)
        except RuntimeError as e:
            raise self.fail("save", str(e)) from e
        return {"kept": str(kept), **decode_save(kept, staged)}


class CurseRun(PoolRun):
    """Read Curse's effects with the shared reader and drive its measured fight route."""

    def __init__(self, sess, log, out, game, points, disks, staged_disk,
                 attack_by="", quit_nonattacking=False):
        super().__init__(sess, log, out, game, points)
        # The save's name table is a scratch buffer, so the party comes from the
        # records; `names[i]` is the character in slot i, empty for a gap.
        party = saved_characters(staged_disk)
        owners = {name: info["owner"] for name, info in party.items()}
        self.names = [""] * (max(owners.values(), default=-1) + 1)
        for name, owner in owners.items():
            self.names[owner] = name.upper()
        self.panel = marching_names(staged_disk)
        self.attack_by = attack_by.upper()
        self.attack_owner = owners.get(self.attack_by)
        self.attack_evidence = None
        self.quit_evidence = None
        self.first_effect_loss = None
        self.last_effect_row = None
        self.quit_nonattacking = quit_nonattacking
        self.disks = disks
        self.staged_disk = staged_disk

    def load(self) -> dict:
        from tools.curse_of_the_azure_bonds import curseload

        if not self.sess.boot():
            raise StepFailed(self.sess.boot_failure or "boot failed")
        outcome = curseload.load_saved_game(
            self.sess, note=lambda **kw: self.log.emit("curse-load", **kw),
            shot=lambda tag: self.capture(f"load-{tag}"))
        if outcome != "loaded":
            raise self.fail("load", f"Curse load ended at {outcome}")
        self.sess.patch_disk_prompt()
        addr = curseload.Addresses(self.game, self.disks)
        if not curseload.enter_world(self.sess, addr, timeout=240):
            raise self.fail("world", "Curse never reached the world bar")
        curseload.clear_messages(self.sess)
        with self.sess.mon(10) as m:
            for name, point in self.points.items():
                self.armed[name] = m.checkpoint_set(point, exec_=True, stop=False)
            m.resume()
        if self.attack_by:
            self.observe_curse("world")
        else:
            self.capture("world")
        return {"position": self.position(),
                "attack_by": self.attack_by, "attack_owner": self.attack_owner,
                "checkpoints": {k: f"${v:04X}" for k, v in self.points.items()}}

    def steady_position(self) -> list | None:
        """The live triple `$C04B`-`$C04D`: the status line of these titles
        stays a step behind the party until the next move; read as
        `steady_triple`, because the game moves it while it draws.  None when
        it never settled."""
        steady = self.sess.steady_triple()
        return None if steady is None else list(steady)

    def position(self) -> list:
        """`steady_position`, failing with the screen kept when it never
        settled."""
        got = self.steady_position()
        if got is None:
            raise self.fail("square", "the party's square did not settle")
        return got

    def took_nothing(self, before, before_rows, screens) -> bool:
        """Move mode changes row 24 on the first key whether or not it was
        read, so only the party's own square says the key was lost.  A square
        that will not settle says nothing, so the key is not called lost."""
        now = self.steady_position()
        return now is not None and now == before

    def to_world(self, tries: int = 10) -> bool:
        for _ in range(tries):
            bar = self.bar()
            if self.at_world(bar):
                return True
            if WHOM in bar:
                route = "whom"
            elif MAGIC_BAR in bar and "EXIT" in bar:
                route = "magic"
            elif CAMP_BAR in bar and "EXIT" in bar:
                route = "camp"
            elif "EXIT" in bar:
                if getattr(self, "attack_by", ""):
                    self.observe_curse("lost-world-route")
                else:
                    self.capture("lost-world-route")
                return False
            else:
                route = None
            if route is not None:
                reached = super().to_world(tries=1)
                if getattr(self, "attack_by", ""):
                    self.observe_curse(f"exit-{route}")
                else:
                    self.capture(f"exit-{route}")
                if reached:
                    return True
            elif self.sess.to_world_bar(timeout=9):
                return True
        if getattr(self, "attack_by", ""):
            self.observe_curse("lost-world-route")
        else:
            self.capture("lost-world-route")
        return False

    def choose_bar(self, word: str, timeout: float) -> bool:
        return self.sess.press_bar(word, timeout=self.budget(timeout, word))

    # -- the sheet and the save, on the routes `curedrive.py` measured ---------------
    def open_sheet(self, who: str) -> list[str]:
        """`VIEW` from camp, waited for as `EXIT` on row 24 with the member's
        name on row 1: Curse's and Silver Blades' sheet bar is not Pool's."""
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        index = self.panel_index(who)
        if not self.sess.select_party(index):
            raise self.fail("panel", f"the panel highlight would not go onto {who}")
        if not self.choose_bar("VIEW", timeout=20):
            raise self.fail("view", "VIEW could not be chosen")
        # `as_drawn` yields only glyphs (a lower-case letter becomes a symbol
        # below `@`), so it never needs upper-casing to match row 1.
        name = (screens.as_drawn(self.panel[index])
                if 0 <= index < len(self.panel) else "")
        rows = self.wait_rows(
            lambda r: "EXIT" in r[24] and CAMP_BAR not in r[24]
            and name in r[1].upper() and bool(r[1].strip()),
            self.budget(30, "the sheet"), f"{name or who}'s sheet")
        if rows is None:
            raise self.fail("view", f"no sheet naming {name or who} came up")
        self.sess.settle(0.8)
        return self.capture(f"sheet-{who}")

    def close_sheet(self) -> None:
        bar = self.bar()
        if "EXIT" in bar and CAMP_BAR not in bar:
            self.choose_bar("EXIT", timeout=15)
        if not self.sess.wait_bar(CAMP_BAR, self.budget(20, "the camp bar")):
            raise self.fail("view-exit", "the camp bar never came back after the sheet")

    def view(self, who: str) -> dict:
        rows = self.open_sheet(who)
        self.close_sheet()
        self.to_world()
        return {"who": who, "sheet": [r.rstrip() for r in rows if r.strip()]}

    SAVING = "SAVING GAME"

    #: While `write_save` waits for `SAVE GAME`, a `SAVING GAME` on row 24 is
    #: the game having chosen the save itself, so the watch ends the wait.
    _saving_is_proof = False

    @contextlib.contextmanager
    def _watching_save(self):
        """Record row 18 and row 24 on every change, and every key and attach,
        for as long as the save step runs; observes only, and puts the
        session's own methods back afterwards."""
        sess, kbd = self.sess, self.sess.kbd
        orig_screen, orig_key = sess.screen, kbd.key
        orig_kernal, orig_attach = sess.press_kernal, sess.attach
        state = {"n": 0, "last": None, "busy": False}

        def watch(*a, **k):
            s = orig_screen(*a, **k)
            if s is None or state["busy"]:
                return s
            pair = (s.row(18).rstrip(), s.row(24).rstrip())
            if pair == state["last"]:
                return s
            state["last"] = pair
            state["busy"] = True
            try:
                state["n"] += 1
                began = self.clock()
                self.capture(f"save-watch-{state['n']}",
                             rows=[s.row(r) for r in range(25)])
                self.log.emit("save-watch", n=state["n"], row18=pair[0],
                              row24=pair[1], stem=f"{self.shots:02d}",
                              png_ms=round((self.clock() - began) * 1000))
            finally:
                state["busy"] = False
            return s

        def screen(*a, **k):
            s = watch(*a, **k)
            if (s is not None and self._saving_is_proof
                    and self.SAVING in s.row(24)):
                self._saving_is_proof = False
                raise _SavingChosen()
            return s

        def key(name, *a, **k):
            self.log.emit("save-key", via="xtest", key=str(name))
            return orig_key(name, *a, **k)

        def press_kernal(code, *a, **k):
            self.log.emit("save-key", via="kernal", key=f"${code:02X}")
            return orig_kernal(code, *a, **k)

        def attach(path, *a, **k):
            self.log.emit("save-attach", image=pathlib.PurePath(str(path)).name)
            return orig_attach(path, *a, **k)

        wrapped = [(sess, "screen", screen), (kbd, "key", key),
                   (sess, "press_kernal", press_kernal), (sess, "attach", attach)]
        saved = [(o, n, n in vars(o), vars(o).get(n)) for o, n, _ in wrapped]
        try:
            for o, n, f in wrapped:
                setattr(o, n, f)
            yield
        finally:
            for o, n, had, prev in saved:
                if had:
                    setattr(o, n, prev)
                else:
                    vars(o).pop(n, None)

    def _watch_lost_write(self) -> None:
        """No `SAVE GAME` bar was seen: keep watching to the camp bar, and keep
        the disk if it comes back, before the step is lost as it always was."""
        try:
            back = self.sess.wait_bar(CAMP_BAR, self.budget(SAVE_WAIT, "the write"))
        except StepFailed:
            return
        if not back:
            return
        try:
            S.copy_closed_disk(pathlib.Path(self.sess.save_disk),
                               self.out / "lost-saved.D64", attempts=30, backoff=1.0)
        except (RuntimeError, OSError) as e:
            self.log.emit("lost-copy", error=type(e).__name__, why=str(e))

    def write_save(self) -> list[str]:
        """`SAVE`, `SAVE GAME`, then the write itself: `SAVING GAME` seen, gone,
        and the camp bar back.  A copy taken while it is still up finds the
        save file unclosed, which `copy_closed_disk` refuses; waiting for the
        bar is what keeps the run from having no save at all."""
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        with self._watching_save():
            for word in ("SAVE", "SAVE GAME"):
                self._saving_is_proof = word == "SAVE GAME"
                try:
                    found = self.sess.wait_bar(word, self.budget(45, word))
                except _SavingChosen:
                    # Silver Blades' write can start with no `SAVE GAME` bar
                    # drawn, or with one this driver never saw.
                    self.log.emit("save-chosen-by-game")
                    break
                finally:
                    self._saving_is_proof = False
                if not found:
                    if word == "SAVE GAME":
                        self._watch_lost_write()
                    raise self.fail("save", f"{word} never appeared on row 24")
                if word == "SAVE GAME":
                    self.sess.attach(self.sess.save_disk)
                if not self.choose_bar(word, timeout=30):
                    raise self.fail("save", f"{word} could not be chosen")
            if self.sess.wait_text(self.SAVING, self.budget(30, self.SAVING))[0] is None:
                raise self.fail("save", f"{self.SAVING} never came up")
            if not self.sess.wait_bar(CAMP_BAR, self.budget(SAVE_WAIT, "the write")):
                raise self.fail("save", "the camp bar never came back after the write")
            self.sess.settle(4)
            back = self.rows()
            if _has(back, self.SAVING):
                raise self.fail("save", f"{self.SAVING} was still up when the camp bar returned")
        return back

    # -- the camp cures ------------------------------------------------------------
    names: list[str] = []
    #: The party in the order the panel draws it, taken from the save's
    #: marching order.  Whether the C64 panel follows marching order after a
    #: party is reordered in the game has not been measured.
    panel: list[str] = []
    #: Seconds each wait may take: a pick key's effect, the bar a cure is
    #: offered on, and the target question after CURE.
    bar_wait = 30

    def owner_of(self, name: str) -> int:
        """The party slot NAME holds, which is the owner its effect rows carry."""
        if name.isdigit():
            return int(name) - 1
        try:
            return self.names.index(name.upper())
        except ValueError:
            raise self.fail("owner", f"{name} is not in the save's party: "
                                     f"{self.names}") from None

    def _outcome(self, kind: str, who: str, target: str, cure_id: int, word: str,
                 first: dict, last: dict, **extra) -> dict:
        owner = self.owner_of(target)

        def row(reading):
            return next((r for r in reading["effects"]
                         if r[1] == cure_id and r[2] == owner), None)

        return {kind: who, "caster_owner": self.owner_of(who), "target": target,
                "owner": owner, "id": cure_id, "word": word,
                "row_before": row(first), "row_after": row(last),
                "effects_before": first["effects"], "effects_after": last["effects"],
                **extra}

    def _settle_row(self, cure_id: int, owner: int, reading: dict,
                     tries: int = 5, pause: float = 0.3, present: bool = False) -> dict:
        """The live effect row can lag the screen by a reading or two,
        whether waiting for a cured id to clear (`present=False`) or for a
        cure's own new row to show up (`present=True`) -- poll briefly for
        the wanted state rather than trust the first reading; a reading that
        still disagrees once the bound is spent is a real failure, not a
        stale read."""
        for _ in range(tries - 1):
            found = any(r[1] == cure_id and r[2] == owner for r in reading["effects"])
            if found == present:
                return reading
            if self.spent():
                break
            time.sleep(pause)
            reading = self.reading()
        return reading

    def cure(self, arg: str) -> dict:
        paladin, target = parse_cure(arg)
        cure_id, word = DISEASE_CURE
        self.owner_of(target)
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        if not self.sess.select_party(self.panel_index(paladin)):
            raise self.fail("panel", f"the panel highlight would not go onto {paladin}")
        if not self.choose_bar("VIEW", timeout=20):
            raise self.fail("view", "VIEW could not be chosen")
        if self.wait_rows(lambda r: re.search(r"\bCURE\b", r[24]) is not None,
                          self.bar_wait) is None:
            raise self.fail("cure-not-offered", f"{paladin}'s sheet offers no CURE")
        if not self.choose_bar("CURE", timeout=20) or self.wait_rows(
                lambda r: CAST_WHOM in r[24], self.whom_wait) is None:
            raise self.fail("cure-whom", f"CURE never asked {CAST_WHOM}")
        first = self.reading()
        if not self.pick(target, CAST_WHOM):
            raise self.fail("cure-target", f"{target} could not be chosen")
        messages = self._acknowledge()
        # The cure's own new effect row can take a reading or two longer to
        # show up in live memory than the message it just showed on screen.
        last = self._settle_row(CURE_TIMER_ID, self.owner_of(paladin), self.reading(),
                                present=True)
        for _ in range(3):
            if CAMP_BAR in self.bar():
                break
            self.choose_bar("EXIT", timeout=15)
            self.sess.settle(1.5)
        if CAMP_BAR not in self.bar():
            raise self.fail("cure-exit", "the camp bar never came back after the cure")
        return self._outcome("paladin", paladin, target, cure_id, word, first, last,
                             messages=messages)

    def _id25_row(self) -> list[int] | None:
        return next((row for row in self.reading()["effects"]
                     if row[1] == 25 and row[2] == self.attack_owner), None)

    def observe_curse(self, phase: str, *, actor=None, **extra) -> dict:
        """Keep each screen beside its effect rows and the first row loss."""
        reading = self.reading()
        screen = self.capture(phase)
        row = next((r for r in reading["effects"]
                    if r[1] == 25 and r[2] == self.attack_owner), None)
        if row is None and getattr(self, "last_effect_row", None) is not None \
                and getattr(self, "first_effect_loss", None) is None:
            self.first_effect_loss = {"phase": phase,
                                      "last_present": self.last_effect_row}
        if row is not None:
            self.last_effect_row = row
        sess = getattr(self, "sess", None)
        mode = sess.mode() if sess is not None and hasattr(sess, "mode") else None
        if actor is None and sess is not None and hasattr(sess, "battle"):
            battle = sess.battle() if mode == 2 else None
            actor = sess.acting(battle) if battle is not None else None
        who = None if actor is None else {
            "name": actor.name.strip(), "index": actor.index,
            "position": [getattr(actor, "x", None), getattr(actor, "y", None)],
            "hp": getattr(actor, "hp", None)}
        live = {}
        if sess is not None and hasattr(sess, "mon"):
            with sess.mon(10) as m:
                live = {name: m.read(addr, 1)[0] for name, addr in {
                    "attacker": 0x945C, "target": 0x945D,
                    "record_owner": 0x7EB4, "guard": 0x93E8}.items()}
                m.resume()
        event = {"phase": phase, "row": row, "reading": reading,
                 "screen": screen, "mode": mode, "actor": who,
                 "owner": self.attack_owner,
                 "first_effect_loss": getattr(self, "first_effect_loss", None),
                 **live, **extra}
        self.log.emit("curse-observation", **event)
        return event

    def stop_at_first_loss(self) -> None:
        if self.first_effect_loss is not None:
            raise StepFailed("id 25 first disappeared at "
                             + self.first_effect_loss["phase"])

    def probe_one_step(self) -> None:
        """Take one empty-square step, identified from the live battle map."""
        battle = self.sess.battle()
        actor = self.sess.acting(battle) if battle is not None else None
        if actor is None:
            raise StepFailed("no actor at the first command bar")
        step = next(((delta, key) for delta, key in S.STEP_KEYS.items()
                     if battle.shape.holds(actor.x + delta[0],
                                           actor.y + delta[1])
                     and not battle.square(actor.x + delta[0],
                                           actor.y + delta[1])
                     and battle.at(actor.x + delta[0],
                                   actor.y + delta[1]) is None),
                    None)
        if step is None:
            raise StepFailed("no empty adjacent square for one-step control")
        delta, key = step
        self.observe_curse("one-step-before", actor=actor, key=key,
                           from_position=[actor.x, actor.y])
        if not self.sess.combat_bar("MOVE", timeout=15):
            raise StepFailed("MOVE was not selectable for one-step control")
        if self.sess.await_bar((S.BAR_MOVE,), timeout=8) is None:
            raise StepFailed("MOVE did not open its movement bar")
        self.sess.kbd.key(key, 0.15, 0.30)
        self.sess.settle(1.2)
        fresh = self.sess.battle()
        moved = None if fresh is None else next(
            (c for c in fresh.combatants if c.index == actor.index), None)
        self.observe_curse("one-step-after", actor=moved, key=key,
                           expected_position=[actor.x + delta[0],
                                              actor.y + delta[1]])
        if moved is None or (moved.x, moved.y) != (actor.x + delta[0],
                                                   actor.y + delta[1]):
            raise StepFailed("one-step control did not reach its empty square")

    def first_command_bar(self) -> None:
        if self.sess.await_bar((S.BAR_COMMAND,), timeout=60, interval=2.0) is None:
            self.capture("lost-first-command-bar")
            raise StepFailed("the first command bar did not appear")
        self.observe_curse("first-command-bar")
        self.stop_at_first_loss()
        self.sess.settle(1.0)
        self.observe_curse("first-command-no-input")
        self.stop_at_first_loss()
        if getattr(self, "probe_step", False):
            self.probe_one_step()
            self.stop_at_first_loss()

    def observed_fight(self, budget: float):
        """Observe DONE handling that Session.fight performs outside a tactic."""
        sess = self.sess
        original = sess.end_turn
        had_override = "end_turn" in vars(sess)

        def observed_end_turn():
            battle = sess.battle()
            actor = sess.acting(battle) if battle is not None else None
            self.observe_curse("done-before", actor=actor)
            chosen = original()
            self.observe_curse("done-after", actor=actor, chosen=chosen)
            return chosen

        sess.end_turn = observed_end_turn
        try:
            return sess.fight(budget=budget, tactic=self._named_melee)
        finally:
            if had_override:
                sess.end_turn = original
            else:
                del sess.end_turn

    def _named_melee(self, sess, state):
        actor = sess.acting(sess.battle())
        name = "" if actor is None else actor.name.strip()
        before = self.observe_curse("tactic-before", actor=actor,
                                    bar=state.text)["row"]
        prior_loss = getattr(self, "first_effect_loss", None)
        if self.attack_evidence is None and name.upper() == self.attack_by:
            self.capture(f"attack-before-{name}")
        if (getattr(self, "quit_nonattacking", False)
                and name.upper() == self.attack_by
                and self.attack_evidence is None):
            chosen = self._quit_turn(sess)
        else:
            chosen = S.Session.melee_turn(sess, state)
        after = self.observe_curse("tactic-after", actor=actor, chosen=chosen,
                                   bar=state.text)["row"]
        if self.attack_evidence is not None or name.upper() != self.attack_by:
            return chosen
        if chosen == S.ATTACK:
            self.capture(f"attack-after-{name}")
            candidate = {"actor": name, "index": actor.index,
                         "owner": self.attack_owner, "bar": state.text,
                         "chosen": chosen, "before": before, "after": after}
            self.log.emit("named-attack", **candidate)
            if prior_loss is None and before is not None:
                self.attack_evidence = candidate
        elif (chosen == "QUIT" and getattr(self, "quit_nonattacking", False)
              and self.quit_evidence is None):
            advanced = self._confirm_quit_advanced(actor)
            if advanced is None:
                self.log.emit("named-quit-unconfirmed", actor=name,
                              before=before, after_send=after)
            else:
                self.quit_evidence = {"actor": name, "index": actor.index,
                                      "owner": self.attack_owner,
                                      "chosen": chosen, "before": before,
                                      "after": advanced["row"],
                                      "advanced_to": advanced["advanced_to"],
                                      "persisted": before is not None
                                      and advanced["row"] is not None}
                self.log.emit("named-quit", **self.quit_evidence)
        return chosen

    def _confirm_quit_advanced(self, previous):
        """A sent QUIT counts only after another actor or the world appears."""
        for _ in range(8):
            mode = self.sess.mode()
            battle = self.sess.battle() if mode == 2 else None
            actor = self.sess.acting(battle) if battle is not None else None
            bar = self.sess.combat_state().text
            self.observe_curse("quit-await", actor=actor, bar=bar)
            advanced_to = None
            if mode == S.DUNGEON:
                advanced_to = "combat-ended"
            elif actor is not None and actor.index != previous.index:
                advanced_to = actor.name.strip()
            if advanced_to is not None:
                return {**self.observe_curse("quit-confirmed", actor=actor,
                                             bar=bar, advanced_to=advanced_to),
                        "advanced_to": advanced_to}
            self.sess.settle(0.5)
        return None

    @staticmethod
    def _quit_turn(sess) -> str:
        if not sess.combat_bar("DONE", timeout=12):
            return ""
        if sess.await_bar((S.BAR_DONE,), timeout=6) is None:
            return "DONE"
        if "QUIT" not in sess.combat_state().text:
            return ""
        return "QUIT" if sess.combat_bar("QUIT", timeout=8) else ""

    def await_combat(self) -> bool:
        """Answer one unreadable brawl acknowledgement while combat loads."""
        answered_blank = False
        for _ in range(30):
            if self.sess.in_combat():
                if getattr(self, "attack_by", ""):
                    self.observe_curse("first-combat-mode")
                return True
            screen = self.sess.screen()
            if screen is None:
                if not answered_blank:
                    self.capture("brawl-unreadable")
                    self.sess.press_kernal(0x0D)
                    answered_blank = True
            else:
                answered_blank = False
                if self.sess.combat_state(screen).kind == S.BAR_PRESS:
                    self.sess.press_kernal(0x0D)
            self.sess.settle(4)
        entered = self.sess.in_combat()
        if entered and getattr(self, "attack_by", ""):
            self.observe_curse("first-combat-mode")
        return entered

    def warp(self, arg: str) -> dict:
        raise self.fail("warp", "Pool of Radiance only")

    def walk_fight(self, arg: str) -> dict:
        raise self.fail("walk-fight", "Pool of Radiance only")

    def fight(self, arg: str, walk: str, steps: int) -> dict:
        from tools.c64 import laterbattle
        from tools.curse_of_the_azure_bonds import cursethac0

        if self.attack_by and self.attack_owner is None:
            raise self.fail("fighter", f"{self.attack_by} is absent from save slots")
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        diagnostic = bool(self.attack_by)
        if diagnostic:
            self.stop_at_first_loss()
        area, geo = cursethac0.area_geo(str(self.staged_disk), self.disks)
        if geo is None:
            raise self.fail("geo", f"{area} was absent from the Curse disks")
        route_type = laterbattle.Battle
        if diagnostic:
            owner = self

            class ObservedRoute(laterbattle.Battle):
                def log(self, kind, **kw):
                    super().log(kind, **kw)
                    if kind in ("step", "dismissed"):
                        owner.observe_curse(f"route-{kind}", route=kw)
                        owner.stop_at_first_loss()

            route_type = ObservedRoute
            self.observe_curse("route-before")
            self.stop_at_first_loss()
        route = route_type(self.out, True)
        try:
            route.sess = self.sess
            try:
                arrived = route.goto(laterbattle.TAVERN, steps, geo=geo)
            except cursethac0.Unsettled:
                raise self.fail("square", "the party's square did not settle")
            walked = route.last_goto_steps
        finally:
            route.file.close()
        if diagnostic:
            self.observe_curse("route-after")
            self.stop_at_first_loss()
        self.capture("tavern")
        if not arrived:
            raise self.fail("fight", f"TAVERN was not reached in {walked} steps")
        if diagnostic:
            self.observe_curse("before-punch")
            self.stop_at_first_loss()
        if not self.sess.in_combat():
            pressed = self.sess.press_bar(laterbattle.PUNCH, timeout=20)
            if diagnostic:
                self.observe_curse("after-punch", chosen=laterbattle.PUNCH,
                                   pressed=pressed)
                self.stop_at_first_loss()
            if not pressed:
                raise self.fail("fight", "PUNCH BARKEEP was not selectable")
        if not self.await_combat():
            raise self.fail("fight", "Curse never entered combat mode")
        if diagnostic:
            self.stop_at_first_loss()
        self.capture("fight-start")
        if diagnostic:
            self.first_command_bar()
            result = self.observed_fight(float(arg or 120))
        else:
            self.sess.await_bar((S.BAR_COMMAND,), timeout=60, interval=2.0)
            result = self.sess.fight(budget=float(arg or 120),
                                     tactic=S.Session.melee_turn)
        self.capture("fight-end")
        if result.outcome == S.BUDGET:
            raise self.fight_over_budget(arg, result)
        if result.outcome == S.LOST:
            raise self.fight_lost(result)
        return {"walked": walked, "area": str(area), "acted": result.acted,
                "named_attack": self.attack_evidence,
                "named_quit": self.quit_evidence,
                **dataclasses.asdict(result)}


class SilverRun(CurseRun):
    """Silver Blades on `ssbsession.SSBSession`: Curse's camp, sheet and save routes,
    its own load, and no fight (its route to a fight is Curse's tavern)."""

    def __init__(self, sess, log, out, game, points, disks, staged_disk):
        PoolRun.__init__(self, sess, log, out, game, points)
        party = saved_characters(staged_disk)
        self.names = [n for n, _ in sorted(party.items(),
                                           key=lambda kv: kv[1]["owner"])]
        self.panel = marching_names(staged_disk)
        self.attack_by = ""
        self.attack_owner = None
        self.attack_evidence = self.quit_evidence = None
        self.first_effect_loss = self.last_effect_row = None
        self.quit_nonattacking = False
        self.disks = disks
        self.staged_disk = staged_disk

    def load(self) -> dict:
        from tools.secret_of_the_silver_blades import ssbsession

        if not self.sess.boot():
            raise StepFailed(self.sess.boot_failure or "boot failed")
        if not ssbsession.load_party(self.sess):
            raise self.fail("load", "the game did not load the party")
        addr = ssbsession.Addresses(self.sess.game, self.disks)
        if not ssbsession.enter_world(self.sess, addr, timeout=240):
            raise self.fail("world", "Silver Blades never reached the world")
        ssbsession.clear_messages(self.sess)
        # A loaded party can arrive on the starting-treasure bar or a sheet it
        # opens, and `to_world_bar` answers neither (`curedrive._enter_silver`).
        for _ in range(12):
            bar = self.bar()
            if "ENCAMP" in bar:
                break
            if "LEAVE TREASURE" in bar:
                self.sess.press_bar("LEAVE TREASURE")
            elif "EXIT" in bar.split():
                self.sess.press_bar("EXIT")
            elif not self.sess.to_world_bar(timeout=20):
                continue
            time.sleep(1.5)
        else:
            raise self.fail("world-bar", f"the world bar never came back: {self.bar()!r}")
        with self.sess.mon(10) as m:
            for name, point in self.points.items():
                self.armed[name] = m.checkpoint_set(point, exec_=True, stop=False)
            m.resume()
        self.capture("world")
        return {"position": self.position(),
                "checkpoints": {k: f"${v:04X}" for k, v in self.points.items()}}


# --- the run ---------------------------------------------------------------------


def validate_curse_attack(results: list[dict], attack: dict | None,
                          who: str) -> None:
    """Require the screen and engine save to corroborate the named blow."""
    if attack is None:
        raise StepFailed(f"{who} never made a confirmed melee attack")
    if attack["before"] is None:
        raise StepFailed(f"id 25 was already absent before {who} attacked")
    if attack["after"] is not None:
        raise StepFailed(f"id 25 remained after {who} attacked")

    fights = [i for i, result in enumerate(results) if result["verb"] == "fight"]
    if len(fights) != 1:
        raise StepFailed("the named attack needs one recorded fight")
    fight_at = fights[0]

    def status(result: dict) -> list[str] | None:
        if result["verb"] != "camp-list":
            return None
        return next((spells for name, spells in result["lists"].items()
                     if name.upper() == who.upper()), None)

    before = [status(r) for r in results[:fight_at]]
    after = [status(r) for r in results[fight_at + 1:]]
    before = [spells for spells in before if spells is not None]
    after = [spells for spells in after if spells is not None]
    if not before or "INVISIBILITY" not in before[-1]:
        raise StepFailed(f"the camp list did not show {who} under INVISIBILITY before the fight")
    if not after:
        raise StepFailed(f"no camp list for {who} was recorded after the fight")
    if "INVISIBILITY" in after[0]:
        raise StepFailed(f"the camp list still showed {who} under INVISIBILITY after the fight")

    saved = [r for r in results[fight_at + 1:] if r["verb"] == "save"]
    if not saved:
        raise StepFailed("no engine-written save was recorded after the fight")
    owner = attack["owner"]
    if any(row[1] == 25 and row[2] == owner for row in saved[-1]["effects"]):
        raise StepFailed(f"the engine-written save still held {who}'s id-25 row")


def validate_curse_quit(control: dict | None, who: str) -> None:
    """Require a named QUIT that leaves the effect row present."""
    if (control is None or control["chosen"] != "QUIT"
            or not control.get("advanced_to")):
        raise StepFailed(f"no confirmed QUIT by {who}")
    if control["before"] is None:
        raise StepFailed(f"id 25 was absent before {who} quit")
    if control["after"] is None:
        raise StepFailed(f"id 25 was absent after {who} quit")


def marching_names(path) -> list[str]:
    """The party's names in the order the C64 panel lists them, case kept."""
    from goldbox.savegame import load_save

    _, sg0, _ = load_save(D64.open(str(path)))
    return [slot.record.name for slot in sg0.marching_order]


def saved_characters(path: pathlib.Path) -> dict[str, dict]:
    """Per character of a game-written save, upper-case name: the party slot
    and the spells in its memorised list."""
    from goldbox import c64_codec
    from goldbox.savegame import load_save

    game, sg0, _ = load_save(D64.open(str(path)))
    out = {}
    for slot in sg0.characters:
        rec = slot.record
        out[rec.name.upper()] = {
            "owner": slot.index,
            "memorised": [b for b in c64_codec.get_memorised(rec, game) if b]}
    return out


def validate_curse_cures(results: list[dict], saved_path,
                         characters=saved_characters) -> None:
    """Require each camp cure to have taken its row away, and nothing else,
    on the screen, in the live rows and in the game-written save.

    A row already absent before its action proves nothing; a row still there
    after an action that reached the target question refutes the fix.
    """
    acts = [(i, r) for i, r in enumerate(results) if r["verb"] in ("cast", "cure")]
    if not acts:
        raise StepFailed("no cast or cure step was recorded")

    def status(result: dict, who: str) -> list[str] | None:
        return next((spells for name, spells in result.get("lists", {}).items()
                     if name.upper() == who.upper()), None)

    def lists(part, who):
        return [s for s in (status(r, who) for r in part
                            if r["verb"] == "camp-list") if s is not None]

    first, last = acts[0][0], acts[-1][0]
    for _, act in acts:
        who, word, target = act.get("caster") or act["paladin"], act["word"], act["target"]
        label = f"{who}'s {act['verb']} on {target}"
        before = lists(results[:first], target)
        if not before or not any(word in s for s in before[-1]):
            raise StepFailed(f"the camp list did not show {target} under {word} "
                             f"before the first cure")
        if act["row_before"] is None:
            raise StepFailed(f"inconclusive: id {act['id']} was already absent "
                             f"before {label}")
        if act["row_before"][3] != 0:
            raise StepFailed(f"id {act['id']} on {target} had duration "
                             f"{act['row_before'][3]} before {label}")
        if act["row_after"] is not None:
            raise StepFailed(f"refuted: id {act['id']} was still on {target} "
                             f"after {label}")
        was, now = act["effects_before"], act["effects_after"]
        lost = [r for r in was if r not in now and r != act["row_before"]]
        if lost:
            raise StepFailed(f"{label} also took away {lost}")
        new = [r for r in now if r not in was]
        if act["verb"] == "cast" and new:
            raise StepFailed(f"{label} added {new}")
        if act["verb"] == "cure" and not (
                len(new) == 1 and new[0][1] == CURE_TIMER_ID
                and new[0][2] == act["caster_owner"]):
            raise StepFailed(f"{label} should add one id-{CURE_TIMER_ID} row owned "
                             f"by {who}, added {new}")
    for _, act in acts:
        target = act["target"]
        after = lists(results[last + 1:], target)
        if not after:
            raise StepFailed(f"no camp list for {target} was recorded after the cures")
        if any(act["word"] in s for s in after[0]):
            raise StepFailed(f"the camp list still showed {target} under {act['word']}")

    saved = [r for r in results[last + 1:] if r["verb"] == "save"]
    if not saved:
        raise StepFailed("no engine-written save was recorded after the cures")
    held = saved[-1]["effects"]
    for _, act in acts:
        if any(r[1] == act["id"] and r[2] == act["owner"] for r in held):
            raise StepFailed(f"the engine-written save still held {act['target']}'s "
                             f"id-{act['id']} row")
        if act["verb"] == "cure" and not any(
                r[1] == CURE_TIMER_ID and r[2] == act["caster_owner"] for r in held):
            raise StepFailed(f"the engine-written save lost {act['paladin']}'s "
                             f"id-{CURE_TIMER_ID} row")
    party = characters(saved_path)
    for _, act in acts:
        if act["verb"] != "cast":
            continue
        who = party.get(act["caster"].upper())
        if who is None:
            raise StepFailed(f"the engine-written save has no {act['caster']}")
        if CAMP_SPELL_IDS[act["spell"]] in who["memorised"]:
            raise StepFailed(f"{act['caster']} still had spell "
                             f"{CAMP_SPELL_IDS[act['spell']]} memorised in the saved game")


def validate_pool_party_spells(results: list[dict]) -> None:
    """Require a camp Animate Dead to change one dead member and reach a save."""
    acts = [(i, r) for i, r in enumerate(results)
            if r["verb"] == "cast" and r.get("spell") in CAMP_PARTY_SPELLS]
    if not acts:
        raise StepFailed("no Pool party spell cast was recorded")

    def require_zombie(party: list[dict], slot: int, where: str) -> None:
        member = next((p for p in party if p["slot"] == slot), None)
        if member is None or member["status"] != 0x03:
            raise StepFailed(f"{where}: slot {slot} has no animated status $03")
        if 32 not in member["traits"]:
            raise StepFailed(f"{where}: slot {slot} has no Animate Dead trait 32")
        if member["creature_type"] != 4:
            raise StepFailed(f"{where}: slot {slot} has creature type "
                             f"{member['creature_type']}, not 4")

    for at, act in acts:
        before = act.get("party_before", [])
        victims = [p for p in before if p["status"] == 0x83]
        if len(victims) != 1:
            raise StepFailed("Animate Dead needs exactly one dead victim "
                             f"before the cast, found {len(victims)}")
        victim = victims[0]
        slot = victim["slot"]
        if 32 in victim["traits"]:
            raise StepFailed(f"slot {slot} already held trait 32 before the cast")
        require_zombie(act.get("party_after", []), slot, "live after cast")
        saved = next((r for r in results[at + 1:] if r["verb"] == "save"), None)
        if saved is None:
            raise StepFailed("no game-written save followed Animate Dead")
        require_zombie(saved.get("party", []), slot, "game-written save")


def validate_pool_dispel(results: list[dict]) -> None:
    """Require the live Dispel result to survive a later game-written save."""
    for at, act in enumerate(results):
        if act["verb"] != "cast" or act.get("spell") not in POOL_TARGET_SPELLS:
            continue
        saved = next((r for r in results[at + 1:] if r["verb"] == "save"), None)
        if saved is None:
            raise StepFailed("no game-written save followed Dispel Magic")
        slot = act["slot"]
        rows = saved.get("effect_rows", [])
        if (len(rows) != effects.EFFECT_SLOTS
                or rows[63] != act["row_after"]
                or any(row[1:3] == [32, slot] for row in rows)):
            raise StepFailed("game-written save changed the Dispel Magic row "
                             "or restored an owned id-32 row")
        live = next(p for p in act["party_after"] if p["slot"] == slot)
        held = next((p for p in saved.get("party", []) if p["slot"] == slot), None)
        if held != live:
            raise StepFailed(f"game-written save changed {act['target']}'s "
                             "post-dispel fields")


def validate_pool_control(results: list[dict]) -> None:
    """Require the no-cast control to retain BRUTUS and his effect row."""
    if [r["verb"] for r in results] != ["load", "view", "save"]:
        raise StepFailed("control did not complete load, view, save")
    observed = []
    for where, state in (("loaded", results[0].get("after", {})),
                         ("saved", results[-1])):
        party = [p for p in state.get("party", [])
                 if p.get("name", "").upper() == "BRUTUS"]
        if len(party) != 1:
            raise StepFailed(f"control {where}: expected one BRUTUS")
        brutus = party[0]
        if (brutus.get("status") != 0x03
                or 32 not in brutus.get("traits", [])
                or brutus.get("creature_type") != 4):
            raise StepFailed(f"control {where}: BRUTUS is not animated "
                             "with trait 32 and creature type 4")
        rows = state.get("effect_rows", [])
        if (len(rows) != effects.EFFECT_SLOTS
                or rows[63][:3] != [63, 32, brutus["slot"]]):
            raise StepFailed(f"control {where}: row 63 is not BRUTUS's id 32")
        digests = state.get("record_sha256", [])
        if len(digests) != PARTY_SLOTS:
            raise StepFailed(f"control {where}: no complete party record digests")
        observed.append((brutus, rows[63], digests[brutus["slot"]]))
    if observed[0] != observed[1]:
        raise StepFailed("control saved BRUTUS or his complete row 63 "
                         "differently from the loaded state")


def validate_walks(results: list[dict]) -> None:
    """Require the game-written save to agree with the walks asked.

    A forward move asked must have changed the saved square from the staged
    one; walks of turns alone must not have; and the saved square and facing
    must be the ones the screen showed after the last walk, unless a fight
    moved the party since.  The screen's answer alone is never enough: the
    status line holds the clock.
    """
    walks = [(i, r) for i, r in enumerate(results) if r["verb"] == "walk"]
    if not walks:
        return
    last = walks[-1][0]
    saved = [r for r in results[last + 1:] if r["verb"] == "save"]
    if not saved:
        raise StepFailed("a walk was asked and no save was read after it")
    got = saved[-1]
    if got.get("place_changed") is None:
        raise StepFailed("a walk was asked and the staged disk has no place to compare")
    asked = sum(r["asked_forward"] for _, r in walks)
    # A route that ends where it began leaves the saved square unchanged
    # though the party walked; it passes when the screen saw squares change
    # and the game-written save agrees with the last reading.
    seen_end = walks[-1][1]["position"][:2]
    returned = (sum(r.get("squares_moved", 0) for _, r in walks) > 0
                and seen_end == [got["place_after"]["x"], got["place_after"]["y"]])
    if asked and not got["place_changed"] and not returned:
        blocked = [b for _, r in walks for b in r["blocked"]]
        raise StepFailed(f"did not move: {asked} forward move(s) asked, the saved "
                         f"square is still {got['place_after']['x']},"
                         f"{got['place_after']['y']} (blocked at moves {blocked})")
    if not asked and got["place_changed"]:
        raise StepFailed("only turns were asked and the saved square changed from "
                         f"{got['place_before']} to {got['place_after']}")
    if any(r["verb"] == "fight" for r in results[last + 1:]):
        return
    seen = walks[-1][1]["position"]
    after = got["place_after"]
    if seen[2] is None:
        if seen[:2] != [after["x"], after["y"]]:
            raise StepFailed(f"the screen showed {seen[:2]}, the game-written save "
                             f"holds {[after['x'], after['y']]}")
    elif seen != [after["x"], after["y"], after["facing"]]:
        raise StepFailed(f"the screen showed {seen}, the game-written save holds "
                         f"{[after['x'], after['y'], after['facing']]}")


def give_joystick(vicerc: pathlib.Path) -> None:
    """Set `JoyDevice2=1` inside the `[C64SC]` section of the slot's vicerc.

    Written to a neighbour and renamed over it, so a reader never sees half a file.
    """
    lines = vicerc.read_text(encoding="utf-8").splitlines() if vicerc.is_file() else []
    out: list[str] = []
    section = ""
    done = False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if section == "C64SC" and not done:
                out.append("JoyDevice2=1")
                done = True
            section = s.strip("[]")
            out.append(line)
        elif section == "C64SC" and s.split("=", 1)[0].strip() == "JoyDevice2":
            if not done:
                out.append("JoyDevice2=1")
                done = True
        else:
            out.append(line)
    if not done:
        if section != "C64SC":
            out.append("[C64SC]")
        out.append("JoyDevice2=1")
    tmp = vicerc.with_name(vicerc.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(vicerc)


def run(args, steps: list[Step], out: pathlib.Path, source: pathlib.Path,
        clock=time.monotonic) -> int:
    deadline = clock() + args.max_seconds
    temple_mode = any(step.verb == "temple-probe" for step in steps)
    if temple_mode:
        temple_source_guard(source)
    scratch.ensure(out)
    log = Log(out)
    git = evidence.git_state(REPO)
    title_key = TITLES[args.title]
    summary: dict = {"title": title_key, "source": str(source),
                     "steps": [s.text for s in steps], **git,
                     "argv": sys.argv[1:], "completed": False, "results": []}
    if temple_mode:
        summary["command"] = getattr(args, "command", shlex.join(
            [sys.executable, str(pathlib.Path(__file__).resolve()), *sys.argv[1:]]))
        summary["source_sha256"] = specimens.sha256_file(source)

    def write_summary():
        (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                          encoding="utf-8")

    staged_disk = out / "staged.D64"
    try:
        staged = stage(source, staged_disk, title_key,
                       rows=parse_rows(args.stage_row),
                       traits=parse_traits(args.stage_trait),
                       items=parse_items(args.stage_item),
                       record_bytes=parse_record_bytes(getattr(args, "stage_record", [])),
                       statuses=parse_statuses(getattr(args, "stage_status", [])))
    except ValueError as e:
        summary["lost"] = str(e)
        write_summary()
        log.say(f"not staged: {e}")
        return 1
    summary["staged"] = staged
    if temple_mode:
        summary["staged_sha256"] = specimens.sha256_file(staged_disk)
        if summary["staged_sha256"] != summary["source_sha256"]:
            summary["lost"] = "temple staging changed the source bytes"
            write_summary()
            log.close()
            return 1
    log.emit("staged", **staged)
    log.say(f"staged {staged_disk}: effects {staged['effects']}, "
            f"magic items {staged['magic_items']}")
    if args.stage_only:
        summary["completed"] = True
        write_summary()
        log.close()
        return 0
    if temple_mode and clock() >= deadline - 100:
        summary["lost"] = "temple input deadline before emulator claim"
        write_summary()
        log.close()
        return 1

    game = c64_port.by_key(title_key)
    points = parse_checkpoints(args.checkpoint)
    runlog.catch_signals()
    try:
        slot = S.claim_slot(args.pool, f"c64acceptance/{args.issue}/{args.run}")
    except BaseException:
        log.close()
        raise
    log.emit("slot", n=slot.n, display=slot.display, dir=str(slot.dir))
    log.say(f"pool slot {slot.n} display {slot.display}; evidence {out}")
    sess = pool = restore_input = None
    stack = contextlib.ExitStack()
    try:
        if args.title == "curse":
            from tools.curse_of_the_azure_bonds import curserun

            first = curserun.stage(slot, args.disks, str(staged_disk))
            if getattr(args, "joy", False):
                # After stage, which reseeds the file from Donald's template:
                # a numpad joystick in port 2, where KP_0 is fire.
                give_joystick(pathlib.Path(slot.vicerc))
            sess = curserun.CurseSession(first, slot=slot)
            sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        elif args.title == "ssb":
            from tools.secret_of_the_silver_blades import ssbsession

            first = ssbsession.stage(slot, args.disks, str(staged_disk))
            sess = ssbsession.silver_session_class()(first, slot=slot)
            sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        else:
            first = S.stage_disks(slot, args.disks)
            S.stage_writable(staged_disk, pathlib.Path(slot.dir) / "SIDE0.D64")
            sess = S.Session(first, slot=slot)
        if temple_mode:
            restore_input = guard_temple_input(sess, clock, deadline - 100)
        stack.enter_context(sess.watching_dialogs())
        pool = (CurseRun(sess, log, out, game, points, args.disks, staged_disk,
                         getattr(args, "attack_by", ""),
                         getattr(args, "quit_nonattacking", False)) if args.title == "curse"
                else SilverRun(sess, log, out, game, points, args.disks, staged_disk)
                if args.title == "ssb"
                else PoolRun(sess, log, out, game, points))
        pool.deadline, pool.clock = deadline, clock
        if temple_mode:
            pool.temple_input_deadline = deadline - 100
        if args.title == "pool":
            pool.capture_ready = getattr(args, "capture_ready", False)
        if args.title == "curse":
            pool.probe_step = getattr(args, "probe_step", False)
            pool.joy = getattr(args, "joy", False)
        for step in steps:
            if clock() >= deadline:
                raise StepFailed(f"the run's {args.max_seconds:g} seconds were "
                                 f"spent before '{step.text}'")
            log.emit("step", step=step.text)
            log.say(f"-- {step.text}")
            if step.verb == "load":
                if temple_mode and clock() >= deadline - 100:
                    raise StepFailed("temple input deadline before boot")
                got = pool.load()
            elif step.verb == "camp-list":
                got = pool.camp_list(step.arg)
            elif step.verb == "items":
                got = pool.items(step.arg)
            elif step.verb == "view":
                got = pool.view(step.arg)
            elif step.verb == "rest":
                got = pool.rest(step.arg)
            elif step.verb == "walk":
                got = pool.walk(step.arg)
            elif step.verb == "fight":
                got = pool.fight(step.arg, args.walk, args.walk_steps)
            elif step.verb == "warp":
                got = pool.warp(step.arg)
            elif step.verb == "walk-fight":
                got = pool.walk_fight(step.arg)
            elif step.verb == "peek":
                got = pool.peek(step.arg)
            elif step.verb == "cast":
                got = pool.cast(step.arg)
            elif step.verb == "cure":
                got = pool.cure(step.arg)
            elif step.verb == "ready":
                got = pool.ready(step.arg)
            elif step.verb == "temple-probe":
                got = pool.temple_probe(step.arg)
            else:
                got = pool.save(staged)
            got = {"step": step.text, "verb": step.verb, **got,
                   "after": pool.reading()}
            summary["results"].append(got)
            log.emit("done", **got)
            write_summary()
        if args.title == "curse" and getattr(args, "attack_by", ""):
            attack = pool.attack_evidence
            summary["named_attack"] = attack
            summary["first_effect_loss"] = getattr(pool, "first_effect_loss", None)
            if getattr(args, "quit_nonattacking", False):
                control = pool.quit_evidence
                summary["named_quit"] = control
                validate_curse_quit(control, args.attack_by)
            else:
                if getattr(pool, "first_effect_loss", None) is not None and attack is None:
                    raise StepFailed("id 25 first disappeared at "
                                     + pool.first_effect_loss["phase"])
                validate_curse_attack(summary["results"], attack, args.attack_by)
        validate_walks(summary["results"])
        if any(s.verb == "walk-fight" for s in steps):
            summary["drain"] = drain_summary(summary["results"], staged)
        if args.title == "pool" and any(s.verb == "cast" for s in steps):
            if any(r.get("spell") in CAMP_PARTY_SPELLS for r in summary["results"]):
                validate_pool_party_spells(summary["results"])
            validate_pool_dispel(summary["results"])
        if (args.title == "pool" and getattr(args, "preserve_specimen", False)
                and pool_specimen_mode(steps) == "control"):
            validate_pool_control(summary["results"])
        if args.title == "curse" and any(s.verb in ("cast", "cure") for s in steps):
            kept = next((r["kept"] for r in reversed(summary["results"])
                         if r["verb"] == "save"), None)
            validate_curse_cures(summary["results"], kept)
        summary["completed"] = True
    except StepFailed as e:
        summary["lost"] = str(e)
        if getattr(pool, "lost_reading", None):
            summary["lost_reading"] = pool.lost_reading
        log.emit("lost", why=str(e))
        log.say(f"lost: {e}")
    except Exception as e:                          # noqa: BLE001
        summary["lost"] = repr(e)
        log.emit("failed", error=repr(e))
        log.say(f"failed: {e!r}")
        if sess is not None:
            with contextlib.suppress(Exception):
                pool.capture("lost-error")
    finally:
        if temple_mode and pool is not None:
            summary["temple_checkpoints"] = pool.temple_checkpoints
        capture_ready = getattr(args, "capture_ready", False)
        preserve_specimen = getattr(args, "preserve_specimen", False)
        if capture_ready or preserve_specimen:
            kept = out / "saved.D64"
            completed_save = bool(summary["results"] and
                                  summary["results"][-1].get("verb") == "save" and
                                  summary["results"][-1].get("kept") == str(kept))
            mode = ("ready" if capture_ready and ready_capture_order(steps)
                    else pool_specimen_mode(steps) if preserve_specimen else None)
            valid = ((capture_ready and not preserve_specimen and mode == "ready"
                      and args.issue == "703" and args.title == "pool")
                     or (preserve_specimen and not capture_ready
                         and mode in ("dispel", "control")
                         and args.issue == "700" and args.title == "pool"
                         and completed_save))
            if not valid:
                summary["completed"] = False
                earlier = summary.get("lost")
                if capture_ready and preserve_specimen:
                    reason = "capture-ready and preserve-specimen cannot be combined"
                elif capture_ready:
                    reason = "BAKSHI READY did not precede the sole save"
                elif (mode not in ("dispel", "control") or args.issue != "700"
                      or args.title != "pool"):
                    reason = "no validated #700 Dispel or control sequence preceded the sole save"
                else:
                    reason = "no completed save from this #700 run"
                summary["lost"] = f"{earlier}; {reason}" if earlier else reason
                summary["specimen_registration"] = "skipped: " + reason
            elif kept.is_file():
                summary["specimen_mode"] = mode
                if preserve_specimen:
                    summary["specimen_validation"] = (
                        "passed" if summary["completed"] else "failed")
                try:
                    failed_suffix = ("-failed" if preserve_specimen
                                     and not summary["completed"] else "")
                    name = (f"por-703-{git['sha'][:10]}-{args.run}"
                            if mode == "ready" else
                            f"por-700-{mode}{failed_suffix}-{git['sha'][:10]}-"
                            f"{args.run}").lower()
                    what = (f"Game-written save after BAKSHI READY diagnostic "
                            f"{args.run}; evidence {out}" if mode == "ready" else
                            f"Game-written Pool of Radiance {mode} save from "
                            f"run {args.run}; validation "
                            f"{summary['specimen_validation']}"
                            f"{': ' + summary['lost'] if not summary['completed'] else ''}; "
                            f"source {source}; evidence {out}")
                    registered = specimens.add(
                        "c64", name, [kept], title=game.title,
                        issue=(READY_SPECIMEN_ISSUE if mode == "ready"
                               else POOL_SPECIMEN_ISSUE),
                        made_by="tools/c64/acceptance.py through pooled VICE",
                        what=what,
                        command=shlex.join([sys.executable, *sys.argv]))
                    summary["registered_specimen"] = str(registered)
                    log.emit("specimen-added", path=str(registered))
                    problems = specimens.check_specimens()
                    if problems:
                        raise StepFailed("specimen check failed: "
                                         + "; ".join(problems[:3]))
                    log.emit("specimen-checked", path=str(registered))
                except Exception as e:  # noqa: BLE001
                    summary["completed"] = False
                    earlier = summary.get("lost")
                    summary["lost"] = (f"{earlier}; specimen registration: {e}"
                                       if earlier else f"specimen registration: {e}")
                    log.emit("specimen-failed", why=str(e))
            else:
                summary["specimen_registration"] = "no saved.D64 was produced"
                if summary["completed"]:
                    summary["completed"] = False
                    summary["lost"] = "preserved run produced no saved.D64 to register"
        write_summary()
        cleanup: dict = {}
        cleanup_errors: list[BaseException] = []

        def attempt_cleanup(name, action, success=None):
            try:
                action()
            except BaseException as exc:
                cleanup[f"{name}_error"] = repr(exc)
                cleanup_errors.append(exc)
            else:
                if success is not None:
                    cleanup[name] = success

        if restore_input is not None:
            attempt_cleanup("restore_input", restore_input)
        attempt_cleanup("watchers", stack.close, "closed")
        if sess is not None:
            attempt_cleanup("session", sess.terminate, "terminated")
        attempt_cleanup("slot", slot.teardown, "released")
        attempt_cleanup("log", log.close)
        if temple_mode or cleanup_errors:
            summary["cleanup"] = cleanup
            if cleanup_errors:
                summary["completed"] = False
                reason = "cleanup: " + "; ".join(repr(e) for e in cleanup_errors)
                earlier = summary.get("lost")
                summary["lost"] = f"{earlier}; {reason}" if earlier else reason
            write_summary()
        if cleanup_errors:
            raise cleanup_errors[0]
    return 0 if summary["completed"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", choices=sorted(TITLES), default="pool")
    ap.add_argument("--save", help="the save disk: a path, or a name inside --disks")
    ap.add_argument("--disks", default=None,
                    help="the player's disks; read, never written")
    ap.add_argument("--stage-row", action="append", default=[],
                    metavar="SLOT=ID:OWNER:DURATION:MAGNITUDE")
    ap.add_argument("--stage-trait", action="append", default=[],
                    metavar="SLOT:INDEX=ID")
    ap.add_argument("--stage-item", action="append", default=[],
                    metavar="SLOT:ITEM:OFFSET=VALUE")
    ap.add_argument("--stage-record", action="append", default=[],
                    metavar="SLOT:OFFSET=VALUE")
    ap.add_argument("--stage-status", action="append", default=[],
                    metavar="SLOT=BYTE")
    ap.add_argument("--steps", nargs="*", default=[],
                    help="load, camp-list [WHO], 'items WHO', 'view WHO', "
                         "'rest 8h', 'walk I', 'fight [SECONDS]', 'peek ADDR N', "
                         "'cast CASTER:SPELL[>TARGET]', 'cure PALADIN>TARGET', "
                         "'ready WHO>LABEL' (Pool only), "
                         "'temple-probe BRUTUS' (bounded Pool observation), save")
    ap.add_argument("--checkpoint", action="append", default=[],
                    metavar="ADDR[=NAME]",
                    help="hex; a non-stopping exec checkpoint armed after the "
                         "load and counted after every step")
    ap.add_argument("--walk", default="I", help="the move `fight` repeats")
    ap.add_argument("--attack-by", default="",
                    help="record the named fighter's first confirmed melee attack")
    ap.add_argument("--quit-nonattacking", action="store_true",
                    help="end the named fighter's turn with DONE then QUIT")
    ap.add_argument("--joy", action="store_true",
                    help="give VICE a numpad joystick in port 2 (KP_0 fires), "
                         "as one more key for `cast` to try")
    ap.add_argument("--capture-ready", action="store_true",
                    help="for Pool BAKSHI READY, save paused screen, colour, "
                         "PNG and live $4900/$5100/$5D00 ranges before fire, "
                         "at first row change, and at stable return or timeout")
    ap.add_argument("--preserve-specimen", action="store_true",
                    help="register and check the game-written save from a #700 "
                         "Pool Dispel or no-cast control run before slot teardown")
    ap.add_argument("--probe-step", action="store_true",
                    help="take one empty-square step after the first command bar")
    ap.add_argument("--walk-steps", type=int, default=40,
                    help="how far `fight` walks looking for one")
    ap.add_argument("--pool", type=int, default=None, help="demand this pool slot")
    ap.add_argument("--max-seconds", type=float, default=MAX_SECONDS,
                    help="the whole run's budget; a step not begun by then is lost")
    ap.add_argument("--issue", default="none")
    ap.add_argument("--run", default="run", help="the run's name in the evidence path")
    ap.add_argument("--out", default=None,
                    help="evidence directory (default ~/.cache/wish/acceptance/"
                         "<issue>/<sha>-<run>)")
    ap.add_argument("--stage-only", action="store_true",
                    help="stage and write the summary, and boot nothing")
    ap.add_argument("--compare", nargs=2, metavar="RUN", default=None,
                    help="two evidence directories: print what their readings differ in")
    args = ap.parse_args(argv)
    if args.compare:
        print(json.dumps(compare(*map(pathlib.Path, args.compare)), indent=2))
        return 0
    if not args.save:
        ap.error("--save is required")
    try:
        steps = parse_steps(args.steps)
        parse_rows(args.stage_row)
        parse_traits(args.stage_trait)
        parse_items(args.stage_item)
        parse_record_bytes(args.stage_record)
        parse_statuses(args.stage_status)
        parse_checkpoints(args.checkpoint)
    except ValueError as e:
        ap.error(str(e))
    if any(x.verb == "warp" for x in steps) and args.title != "pool":
        ap.error("the warp step: Pool of Radiance only")
    if any(x.verb == "walk-fight" for x in steps) and args.title != "pool":
        ap.error("the walk-fight step: Pool of Radiance only")
    if any(x.verb == "fight" for x in steps) and args.title == "ssb":
        ap.error("the fight step needs --title pool or curse")
    temple_mode = any(step.verb == "temple-probe" for step in steps)
    if temple_mode:
        if (steps != [Step("load"), Step("temple-probe", "BRUTUS")]
                or args.title != "pool" or args.issue != "700"
                or any((args.stage_row, args.stage_trait, args.stage_item,
                        args.stage_record, args.stage_status, args.checkpoint))
                or args.stage_only or args.preserve_specimen or args.capture_ready
                or args.probe_step or args.joy or args.pool is not None
                or args.attack_by or args.quit_nonattacking
                or args.walk != "I" or args.walk_steps != 40
                or not 100 < args.max_seconds <= 1500):
            ap.error("temple-probe requires exactly --title pool --issue 700 "
                     "--steps load 'temple-probe BRUTUS', no staging, saving, "
                     "checkpoint or other probe options, and a 1500-second "
                     "maximum with 100 seconds reserved for cleanup")
    if args.capture_ready and args.preserve_specimen:
        ap.error("--capture-ready and --preserve-specimen are separate run modes")
    if args.capture_ready and (args.issue != "703" or args.title != "pool"
                               or not ready_capture_order(steps)):
        ap.error("--capture-ready requires --issue 703, Pool ready "
                 "BAKSHI>LABEL before the sole save step")
    if args.preserve_specimen and (args.issue != "700" or args.title != "pool"
                                   or pool_specimen_mode(steps) is None):
        ap.error("--preserve-specimen requires --issue 700, Pool, and exactly "
                 "load/view BRUTUS/save or load/view BRUTUS/"
                 "cast CASTER:DISPEL MAGIC>BRUTUS/view BRUTUS/save")
    if args.attack_by and args.title != "curse":
        ap.error("--attack-by requires --title curse")
    if any(x.verb == "cure" for x in steps) and args.title != "curse":
        ap.error("the cure step requires --title curse")
    for step in (s for s in steps if s.verb == "cast"):
        try:
            _, spell, target = parse_cast(step.arg)
        except ValueError as e:
            ap.error(str(e))
        if args.title == "pool" and not (
                (target is None and spell in CAMP_PARTY_SPELLS)
                or (target is not None and spell in POOL_TARGET_SPELLS)):
            ap.error("Pool cast supports CASTER:ANIMATE DEAD or "
                     "CASTER:DISPEL MAGIC>TARGET")
        if args.title == "curse" and (target is None or spell not in CAMP_CURES):
            ap.error("Curse cast requires CASTER:CURE BLINDNESS>TARGET")
        if args.title == "ssb":
            ap.error("the cast step requires --title pool or curse")
    if any(x.verb == "ready" for x in steps) and args.title != "pool":
        ap.error("the ready step requires --title pool")
    if args.quit_nonattacking and not args.attack_by:
        ap.error("--quit-nonattacking requires --attack-by")
    if args.probe_step and not args.attack_by:
        ap.error("--probe-step requires --attack-by")
    if not re.fullmatch(r"[\w-]+", args.run) or not re.fullmatch(r"[\w-]+", args.issue):
        ap.error("--issue and --run are simple names")
    if args.disks is None and args.title == "pool":
        args.disks = tool_disks()
    source = pathlib.Path(args.save)
    if not source.is_absolute() and not source.exists() and args.disks:
        source = pathlib.Path(args.disks) / args.save
    if not source.is_file():
        ap.error(f"no save disk at {source}")
    if temple_mode:
        try:
            temple_source_guard(source)
        except ValueError as exc:
            ap.error(str(exc))
    if not args.stage_only and args.disks is None:
        ap.error("no game disks found; set $POR_DISKS or pass --disks")
    out = (pathlib.Path(args.out) if args.out
           else evidence.default_out(args.issue, args.run,
                                     evidence.git_state(REPO)["sha"]))
    if out.exists() and any(out.iterdir()):
        ap.error(f"{out} already holds a run; name a new --run")
    args.command = shlex.join([sys.executable, str(pathlib.Path(__file__).resolve()),
                               *(argv if argv is not None else sys.argv[1:])])
    return run(args, steps, out, source)


if __name__ == "__main__":
    raise SystemExit(main())
