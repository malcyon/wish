#!/usr/bin/env python3
"""Stage a C64 save, load it in the game, and read back what a conversion must preserve.

The C64 driver of `docs/235-destination-game-acceptance-runs.md` (D2).  It
writes effect rows, trait slots and item bytes into a **copy** of a save disk,
boots it on a pooled VICE slot, headless and silent, and runs a step list,
reading the screen and the machine as it goes:

    tools/c64/c64acceptance.py --title pool --save PORSAVE13.D64 \\
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
  is the bonus byte Detect Magic marks an item by.

SLOT is the save slot, 0 first.  Every option repeats, and each is logged in
bytes with what it replaced.

| step | what it does and reads |
|---|---|
| `load` | boot, `LOAD SAVED GAME`, `BEGIN ADVENTURING`; arms every `--checkpoint` |
| `camp-list [WHO]` | `ENCAMP > MAGIC > DISPLAY`, then each name the game offers (or WHO alone, which may be `THE WHOLE PARTY`): the spells it lists as in effect, page by page |
| `items WHO`, `view WHO` | `VIEW` and the ITEMS list, or the sheet alone, as text, with each item's Detect Magic mark |
| `rest 5m`, `rest 8h`, `rest 1h30m` | camp `REST` for exactly that long (`tools/c64/effectdrive.py`'s rest) |
| `walk MOVES` | I forward, J left, K right, M about, each judged by `position()` before and after (the status line holds the clock): `blocked` when a forward move left x,y alone, and a turn must leave the square and change the facing by its amount; a move that brings up a disk prompt, or lands anywhere but one square ahead, fails the walk |
| `fight [SECONDS]` | walk `--walk` until a fight starts, then fight it with `Session.melee_turn` for SECONDS (120) |
| `cast CASTER:SPELL>TARGET` | Curse only: `ENCAMP > MAGIC > CAST`, the one spell named, on TARGET; the target's row of the cured id before and after (`CURE BLINDNESS`) |
| `cure PALADIN>TARGET` | Curse only: `ENCAMP > VIEW > CURE` on TARGET (the paladin's cure of disease), the same before and after |
| `peek ADDR N` | N bytes of memory, ADDR in hex |
| `save` | the game's own `ENCAMP > SAVE`; the disk copied out once closed and decoded, with the place through `world_state.from_c64` against the staged one (`place_changed`, `facing_changed`) |

WHO is a name as the party panel draws it, or a number counting from 1 at
the top of the panel.  After every step the live effect rows, the clock and
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
import json
import pathlib
import re
import subprocess
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(REPO))

from automap.paths import tool_disks  # noqa: E402
from goldbox import c64_port, c64_save, effects, world_state  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from goldbox.geo import STEP  # noqa: E402
from goldbox.items import ITEM_SIZE, ITEMS_PER_CHARACTER  # noqa: E402
from tools.c64 import effectdrive, inventorycheck, traitdrive  # noqa: E402
from tools.c64 import savecheck as SC  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.traitquery import TRAIT_SLOT  # noqa: E402
from tools.registry import scratch  # noqa: E402

TITLES = {"pool": "pool-of-radiance", "curse": "curse-of-the-azure-bonds",
          "ssb": "secret-of-the-silver-blades"}

#: Ten trait slots per record; eight party slots in a save.
TRAIT_SLOTS = 10
PARTY_SLOTS = 8

#: The camp's own bar, `ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT` (Pool
#: `CAMP $0899`), and the MAGIC bar, `CAST MEMORIZE SCRIBE DISPLAY REST EXIT`
#: (`CAMP $14BB`).  Each pair of words is on that bar and on no other.
CAMP_BAR = "REST ALTER"
MAGIC_BAR = "SCRIBE"

#: The camp list's strings, `CAMP $2699` onward in Pool of Radiance and the
#: same text in the later titles.
WHOM = "DISPLAY SPELLS ON WHOM"
CAST_WHOM = "CAST SPELL ON WHOM"
PICK_SPELL = "PICK A SPELL"
AFFECTED = "IS AFFECTED BY:"
WHOLE_PARTY = "THE WHOLE PARTY"
CONTINUE = "PRESS ANY KEY TO CONTINUE"

#: The camp spells `cast` can use: the effect id each removes and the word the
#: camp list shows the character under, and the spell's own id in the
#: memorised list.  The paladin's `cure` removes disease, id 34.
CAMP_CURES = {"CURE BLINDNESS": (33, "BLIND")}
CAMP_SPELL_IDS = {"CURE BLINDNESS": 37}
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
    """`SLOT:INDEX=ID`, as `tools/c64/traitdrive.py` takes it."""
    out = []
    for text in texts:
        for slot, index, code in traitdrive.parse_stage(text):
            if not 0 <= slot < PARTY_SLOTS or not 0 <= index < TRAIT_SLOTS:
                raise ValueError(f"{text!r}: the slot is 0 to 7, the index 0 to 9")
            out.append((slot, index, _byte(str(code), "an id")))
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
         "cast": "must", "cure": "must", "walk": "must"}

#: How long a walk keeps watching for a disk prompt after a move (seconds).
LOOK_SECONDS = 2.0

#: The moves `walk` takes, the game's own letters: forward, left, right, about.
#: Each turn's change to the facing, which the C64 counts N 0, E 1, S 2, W 3.
TURNS = {"I": 0, "J": -1, "K": 1, "M": 2}


def parse_rest(arg: str) -> tuple[int, int]:
    """`8h`, `30m`, `1h30m` as `(minutes, hours)`, the two bytes of `CAMP`'s
    rest-time field that `effectdrive.rest` writes."""
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
                         f"K right, M about")
    return route


def parse_cast(arg: str) -> tuple[str, str, str]:
    """`CASTER:SPELL>TARGET` as its three names, the spell one `CAMP_CURES` knows."""
    m = re.fullmatch(r"([^:>]+):([^:>]+)>([^:>]+)", arg.strip())
    if m is None:
        raise ValueError(f"cast {arg!r}: say cast CASTER:SPELL>TARGET")
    caster, spell, target = (g.strip() for g in m.groups())
    if spell.upper() not in CAMP_CURES:
        raise ValueError(f"cast {arg!r}: the spells are " + ", ".join(CAMP_CURES))
    return caster, spell.upper(), target


def parse_cure(arg: str) -> tuple[str, str]:
    """`PALADIN>TARGET` as its two names."""
    m = re.fullmatch(r"([^:>]+)>([^:>]+)", arg.strip())
    if m is None:
        raise ValueError(f"cure {arg!r}: say cure PALADIN>TARGET")
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
        elif verb == "cast":
            parse_cast(arg)
        elif verb == "cure":
            parse_cure(arg)
        elif verb == "fight" and arg and not (arg.isdigit() and int(arg) > 0):
            raise ValueError(f"fight {arg!r}: seconds, more than zero")
        steps.append(Step(verb, arg))
    if not steps or steps[0].verb != "load":
        raise ValueError("the first step is load")
    if any(s.verb == "load" for s in steps[1:]):
        raise ValueError("one boot, one load")
    return steps


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


def stage(src: pathlib.Path, dest: pathlib.Path, title_key: str,
          rows=(), traits=(), items=()) -> dict:
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
    took: dict = {"title": game.key, "source": str(src), "staged": str(dest),
                  "rows": [], "traits": [], "items": []}
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
    image.write_file_inplace(game.save_file,
                             addr.to_bytes(2, "little") + bytes(payload))
    image.save(str(dest))
    took["effects"] = _effect_list(payload)
    took["magic_items"] = magic_items(payload, box)
    took["place"] = place_of(payload, game)
    return took


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
    clock = list(payload[box.clock:box.clock + 6])
    return {
        "effects": _effect_list(payload),
        "clock": clock,
        **place_verdict(staged.get("place"), place_of(payload, game)),
        "magic_items": magic_items(payload, box),
        "traits": [{**t, "saved": payload[t["offset"]]} for t in staged["traits"]],
        "items": [{**i, "saved": payload[i["offset"]]} for i in staged["items"]],
    }


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
    for text in inventorycheck.item_list(rows):
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


class Log(SC.Log):
    def __init__(self, out: pathlib.Path):
        super().__init__(out / "run.jsonl")


class PoolRun:
    """One booted Pool of Radiance session and the steps run on it."""

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

    # -- the screen ------------------------------------------------------------
    def rows(self) -> list[str]:
        s = self.sess.screen()
        return [] if s is None else [s.row(r) for r in range(25)]

    def bar(self) -> str:
        rows = self.rows()
        return rows[24] if rows else ""

    def capture(self, tag: str) -> list[str]:
        """The text screen and a PNG of it, both kept, named in order."""
        self.shots += 1
        stem = f"{self.shots:02d}-{re.sub(r'[^A-Za-z0-9]+', '-', tag).strip('-')}"
        rows = self.rows()
        (self.out / f"{stem}.txt").write_text(
            "\n".join(r.rstrip() for r in rows) + "\n" if rows else "(bitmap)\n",
            encoding="utf-8")
        self.sess.kbd.screenshot(str(self.out / f"{stem}.png"))
        self.log.emit("screen", tag=tag, stem=stem,
                      rows=[r.rstrip() for r in rows if r.strip()])
        return rows

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
        wanted = (who.upper(), inventorycheck.as_drawn(who).upper())
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
            counts = {k: effectdrive.checkpoint_hits(m, v)
                      for k, v in self.armed.items()}
            m.resume()
        return {"effects": _effect_list(head), "clock": clock, "counts": counts}

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
        return {"position": list(self.sess.position()),
                "checkpoints": {k: f"${v:04X}" for k, v in self.points.items()}}

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
            wanted = (target.upper(), inventorycheck.as_drawn(target).upper())
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
        rows = self.wait_rows(lambda r: S.SHEET_BAR in r[24] and r[1].strip(), 30)
        if rows is None:
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

    def rest(self, arg: str) -> dict:
        minutes, hours = parse_rest(arg)
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        got = effectdrive.rest(self.sess, self.log, minutes, hours, self.armed)
        self.capture(f"rested-{arg}")
        if "failed" in got:
            raise self.fail("rest", got["failed"])
        self.to_world()
        return {"asked": [minutes, hours], "before_clock": got["before"]["clock"],
                "after_clock": got["after"]["clock"]}

    def fight(self, arg: str, walk: str, steps: int) -> dict:
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        taken = 0
        while not self.sess.in_combat() and taken < steps:
            self.sess.walk_one(walk)
            self.sess.handle_prompt()
            taken += 1
        if not self.sess.in_combat():
            raise self.fail("fight", f"no fight in {taken} steps of {walk}")
        self.capture("fight-start")
        result = self.sess.fight(budget=float(arg or 120),
                                 tactic=S.Session.melee_turn)
        self.capture("fight-end")
        return {"walked": taken, "acted": result.acted,
                **dataclasses.asdict(result)}

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
        did not change, which is the control that a walk is not a turn.

        A disk prompt on the screen fails the walk and is never answered: a
        square's event asks for another disk, and answering would carry the
        walk into another area.  It is looked for before each move, after
        each key, for two seconds after each move and before the end is read,
        and `Session.walk_one` runs with `answer_prompts=False` so it does not
        answer one itself.  A forward move must also land on exactly the next
        square, or the walk fails as an exit or a teleport.  A move `walk_one`
        made on the travel grid is not re-sent.

        The one retry is judged by the screen just before the key against the
        screen 1.2 s after it (`Session.walk_screens`), resent only when they
        are identical, since text that `MOVE` put up changes the whole move's
        screen without the key having been read.  Each `move` record keeps
        the text rows the game showed at the key and whether a key was sent.
        """
        route = parse_walk(arg)
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        start = list(self.sess.position())
        facing = start[2]
        moves = []
        last = None
        for n, move in enumerate(route):
            self.budget(1, f"walk {route}")
            # A prompt that opened after the previous move's look would be
            # answered by this move's `select_bar`, so it is looked for first.
            self.refuse_prompt(route, last, "was up before the next move")
            before = list(self.sess.position())
            last = (n, move, before)
            before_rows = self.rows()
            status_moved = self.sess.walk_one(move, tries=1, answer_prompts=False)
            resent = False
            self.refuse_prompt(route, last, "ran the square's event")
            # Out on the travel grid a move is pressed once and never re-sent:
            # the status line lags and a turn does not exist there.
            screens = getattr(self.sess, "walk_screens", None)
            if screens is not None and screens[1] is not None:
                # Judge the key's own window: a text `MOVE` put up before the
                # key changes the whole move's screen, not the key's.
                took_nothing = screens[0] == screens[1]
            else:
                took_nothing = self.rows() == before_rows
            if (not status_moved and took_nothing
                    and not getattr(self.sess, "walked_outdoors", False)):
                # The one retry the contract allows: the game took nothing.
                resent = True
                status_moved = self.sess.walk_one(move, tries=1,
                                                  answer_prompts=False)
                self.refuse_prompt(route, last, "ran the square's event")
                screens = getattr(self.sess, "walk_screens", None)
            refused = getattr(self.sess, "walk_refused", None)
            if refused:
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
            after = list(self.sess.position())
            key_rows = screens[0] if screens else None
            text = (None if key_rows is None else
                    [r.strip() for r in key_rows[17:23]])
            self.log.emit("move", move=move, n=n, before=before, after=after,
                          resent=resent, row24=self.bar().strip(), text=text,
                          keyed=refused is None)
            if (move == "I" and after[:2] != before[:2]
                    and before[2] is not None):
                dx, dy = STEP[before[2]]
                if after[:2] != [before[0] + dx, before[1] + dy]:
                    raise self.fail(
                        "walk", f"walk {route}: move {n} moved from {before} "
                                f"to {after}, not one square ahead: an exit "
                                f"or a teleport")
            if facing is not None:
                facing = (facing + TURNS[move]) % 4
            moves.append({"move": move, "before": before, "after": after,
                          "blocked": move == "I" and before[:2] == after[:2],
                          "moved": before[:2] != after[:2],
                          "status_moved": status_moved, "resent": resent})
        self.refuse_prompt(route, last, "ran the square's event")
        end = list(self.sess.position())
        self.capture(f"walked-{route}")
        if "I" not in route and end[:2] != start[:2]:
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
        from tools.curse_of_the_azure_bonds import cursethac0

        _, payload = _payload(D64.open(str(staged_disk)), game)
        names = cursethac0.slot_names(payload)
        self.names = [n.upper() for n in names]
        self.attack_by = attack_by.upper()
        self.attack_owner = next((i for i, name in enumerate(names)
                                  if name.upper() == self.attack_by), None)
        self.attack_evidence = None
        self.quit_evidence = None
        self.first_effect_loss = None
        self.last_effect_row = None
        self.quit_nonattacking = quit_nonattacking
        self.disks = disks
        self.staged_disk = staged_disk

    def load(self) -> dict:
        from tools.curse_of_the_azure_bonds import curseload, cursewarp

        if not self.sess.boot():
            raise StepFailed(self.sess.boot_failure or "boot failed")
        outcome = curseload.load_saved_game(
            self.sess, note=lambda **kw: self.log.emit("curse-load", **kw),
            shot=lambda tag: self.capture(f"load-{tag}"))
        if outcome != "loaded":
            raise self.fail("load", f"Curse load ended at {outcome}")
        self.sess.patch_disk_prompt()
        addr = cursewarp.Addresses(self.game, self.disks)
        if not cursewarp.enter_world(self.sess, addr, timeout=240):
            raise self.fail("world", "Curse never reached the world bar")
        cursewarp.clear_messages(self.sess)
        with self.sess.mon(10) as m:
            for name, point in self.points.items():
                self.armed[name] = m.checkpoint_set(point, exec_=True, stop=False)
            m.resume()
        if self.attack_by:
            self.observe_curse("world")
        else:
            self.capture("world")
        return {"position": list(self.sess.position()),
                "attack_by": self.attack_by, "attack_owner": self.attack_owner,
                "checkpoints": {k: f"${v:04X}" for k, v in self.points.items()}}

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
        name = self.names[index] if 0 <= index < len(self.names) else ""
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

    def write_save(self) -> list[str]:
        """`SAVE`, `SAVE GAME`, then the write itself: `SAVING GAME` seen, gone,
        and the camp bar back.  A copy taken while it is still up finds the
        save file unclosed, which `copy_closed_disk` refuses; waiting for the
        bar is what keeps the run from having no save at all."""
        if not self.to_camp():
            raise self.fail("camp", "ENCAMP never put up the camp bar")
        for word in ("SAVE", "SAVE GAME"):
            if not self.sess.wait_bar(word, self.budget(45, word)):
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
    #: Whether the run gave VICE a numpad joystick, so that KP_0 is fire.
    joy = False
    names: list[str] = []
    #: Seconds each wait may take: a pick key's effect, the bar a cure is
    #: offered on, and the target question after CURE.
    pick_wait = 15
    bar_wait = 30
    whom_wait = 120

    def owner_of(self, name: str) -> int:
        """The party slot NAME holds, which is the owner its effect rows carry."""
        if name.isdigit():
            return int(name) - 1
        try:
            return self.names.index(name.upper())
        except ValueError:
            raise self.fail("owner", f"{name} is not in the save's party: "
                                     f"{self.names}") from None

    @staticmethod
    def _list_bar(bar: str) -> bool:
        # A list of one spell has no NEXT or PREV, and its bar is exactly
        # `CAST EXIT`; it is matched whole because the MAGIC bar also holds
        # both words.
        return bar.strip() == "CAST EXIT" or (
            "EXIT" in bar and any(w in bar for w in ("SPELL", "NEXT", "PREV")))

    def _send_pick(self, key: str) -> None:
        if key == "xtest-return":
            self.sess.kbd.key("Return")
        elif key == "kernal-return":
            self.sess.press_kernal(0x0D)
        else:
            self.sess.kbd.key("KP_0", 0.2, 0.30)

    def _pick_spell(self, listed: list[str]) -> str:
        """Pick the spell under the cursor, trying the keys one at a time and
        sending the next only while the screen is exactly as the list left it.

        Nothing is known of which key `LIBRARY $4A9A` takes off a list with a
        cursor: Return is what the target menu takes, and fire is what picked
        a combat spell in Pool.  A screen that changes to anything but the
        target question ends the step, so no further key is pressed at it.
        """
        keys = ["xtest-return", "kernal-return"] + (["joystick-fire"] if self.joy else [])
        for key in keys:
            self._send_pick(key)
            rows = self.wait_rows(
                lambda r: CAST_WHOM in r[24] or r != listed, self.pick_wait)
            if rows is None:
                continue
            if CAST_WHOM in rows[24]:
                return key
            raise self.fail("pick-changed",
                            f"{key} changed the spell list into something that is "
                            f"not the target question: {rows[24].strip()!r}")
        raise self.fail("pick", f"none of {', '.join(keys)} picked the spell")

    def _acknowledge(self, limit: int = 4) -> list[list[str]]:
        """Leave the question, then answer up to LIMIT `CONTINUE` pages, each
        kept as the text it showed."""
        rows = self.wait_rows(lambda r: CAST_WHOM not in r[24], 60)
        if rows is None:
            raise self.fail("whom-stuck", "the target question never went away")
        messages: list[list[str]] = []
        for n in range(1, limit + 1):
            if CONTINUE not in rows[24]:
                return messages
            self.sess.settle(0.6)
            shown = self.capture(f"cure-message-{n}")
            messages.append([t for t in (_inner(r) for r in shown[:24])
                             if t and not _is_frame(t)])
            self.sess.press_kernal(0x0D)
            rows = self.wait_rows(lambda r, was=shown: r != was, 30)
            if rows is None:
                raise self.fail("message", "the key at the end of a message did nothing")
        if CONTINUE in rows[24]:
            raise self.fail("message", f"more than {limit} pages after the cure")
        return messages

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

    def cast(self, arg: str) -> dict:
        caster, spell, target = parse_cast(arg)
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
        listed = self.wait_rows(lambda r: _has(r, PICK_SPELL), 10)
        if listed is None:
            raise self.fail("pick-prompt", f"{PICK_SPELL} never came up")
        key = self._pick_spell(listed)
        first = self.reading()
        if not self.pick(target, CAST_WHOM):
            raise self.fail("cast-whom", f"{target} could not be chosen")
        messages = self._acknowledge()
        last = self.reading()
        if self._list_bar(self.bar()):
            self.choose_bar("EXIT", timeout=15)
        return self._outcome("caster", caster, target, cure_id, word, first, last,
                             spell=spell, messages=messages, key=key)

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
        last = self.reading()
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
            arrived = route.goto(laterbattle.TAVERN, steps, geo=geo)
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
        return {"walked": walked, "area": str(area), "acted": result.acted,
                "named_attack": self.attack_evidence,
                "named_quit": self.quit_evidence,
                **dataclasses.asdict(result)}


class SilverRun(CurseRun):
    """Silver Blades on `ssbwarp.SSBSession`: Curse's camp, sheet and save routes,
    its own load, and no fight (its route to a fight is Curse's tavern)."""

    def __init__(self, sess, log, out, game, points, disks, staged_disk):
        PoolRun.__init__(self, sess, log, out, game, points)
        party = saved_characters(staged_disk)
        self.names = [n for n, _ in sorted(party.items(),
                                           key=lambda kv: kv[1]["owner"])]
        self.attack_by = ""
        self.attack_owner = None
        self.attack_evidence = self.quit_evidence = None
        self.first_effect_loss = self.last_effect_row = None
        self.quit_nonattacking = False
        self.disks = disks
        self.staged_disk = staged_disk

    def load(self) -> dict:
        from tools.secret_of_the_silver_blades import ssbwarp

        if not self.sess.boot():
            raise StepFailed(self.sess.boot_failure or "boot failed")
        if not ssbwarp.load_party(self.sess):
            raise self.fail("load", "the game did not load the party")
        addr = ssbwarp.Addresses(self.sess.game, self.disks)
        if not ssbwarp.enter_world(self.sess, addr, timeout=240):
            raise self.fail("world", "Silver Blades never reached the world")
        ssbwarp.clear_messages(self.sess)
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
        return {"position": list(self.sess.position()),
                "checkpoints": {k: f"${v:04X}" for k, v in self.points.items()}}


# --- the run ---------------------------------------------------------------------

def git_state() -> dict:
    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    dirty = [line[3:] for line in git("status", "--porcelain",
                                      "--untracked-files=no").splitlines()]
    return {"sha": git("rev-parse", "HEAD") or "unknown", "dirty": dirty}


def default_out(issue: str, run: str, sha: str) -> pathlib.Path:
    return scratch.cache_dir("acceptance", issue, f"{sha[:10]}-{run}")


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
    scratch.ensure(out)
    log = Log(out)
    git = git_state()
    title_key = TITLES[args.title]
    summary: dict = {"title": title_key, "source": str(source),
                     "steps": [s.text for s in steps], **git,
                     "argv": sys.argv[1:], "completed": False, "results": []}

    def write_summary():
        (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                          encoding="utf-8")

    staged_disk = out / "staged.D64"
    try:
        staged = stage(source, staged_disk, title_key,
                       rows=parse_rows(args.stage_row),
                       traits=parse_traits(args.stage_trait),
                       items=parse_items(args.stage_item))
    except ValueError as e:
        summary["lost"] = str(e)
        write_summary()
        log.say(f"not staged: {e}")
        return 1
    summary["staged"] = staged
    log.emit("staged", **staged)
    log.say(f"staged {staged_disk}: effects {staged['effects']}, "
            f"magic items {staged['magic_items']}")
    if args.stage_only:
        summary["completed"] = True
        write_summary()
        log.close()
        return 0

    game = c64_port.by_key(title_key)
    points = parse_checkpoints(args.checkpoint)
    SC.catch_signals()
    try:
        slot = S.claim_slot(args.pool, f"c64acceptance/{args.issue}/{args.run}")
    except BaseException:
        log.close()
        raise
    log.emit("slot", n=slot.n, display=slot.display, dir=str(slot.dir))
    log.say(f"pool slot {slot.n} display {slot.display}; evidence {out}")
    sess = pool = None
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
            from tools.c64 import curedrive
            from tools.secret_of_the_silver_blades import ssbwarp

            first = ssbwarp.stage(slot, args.disks, str(staged_disk))
            sess = curedrive._silver_session_class()(first, slot=slot)
            sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        else:
            first = S.stage_disks(slot, args.disks)
            S.stage_writable(staged_disk, pathlib.Path(slot.dir) / "SIDE0.D64")
            sess = S.Session(first, slot=slot)
        stack.enter_context(sess.watching_dialogs())
        pool = (CurseRun(sess, log, out, game, points, args.disks, staged_disk,
                         getattr(args, "attack_by", ""),
                         getattr(args, "quit_nonattacking", False)) if args.title == "curse"
                else SilverRun(sess, log, out, game, points, args.disks, staged_disk)
                if args.title == "ssb"
                else PoolRun(sess, log, out, game, points))
        pool.deadline, pool.clock = deadline, clock
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
            elif step.verb == "peek":
                got = pool.peek(step.arg)
            elif step.verb == "cast":
                got = pool.cast(step.arg)
            elif step.verb == "cure":
                got = pool.cure(step.arg)
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
        if any(s.verb in ("cast", "cure") for s in steps):
            kept = next((r["kept"] for r in reversed(summary["results"])
                         if r["verb"] == "save"), None)
            validate_curse_cures(summary["results"], kept)
        summary["completed"] = True
    except StepFailed as e:
        summary["lost"] = str(e)
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
        write_summary()
        try:
            stack.close()
            if sess is not None:
                sess.terminate()
        finally:
            try:
                slot.teardown()
            finally:
                log.close()
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
    ap.add_argument("--steps", nargs="*", default=[],
                    help="load, camp-list [WHO], 'items WHO', 'view WHO', "
                         "'rest 8h', 'walk I', 'fight [SECONDS]', 'peek ADDR N', "
                         "'cast CASTER:SPELL>TARGET', 'cure PALADIN>TARGET', save")
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
        parse_checkpoints(args.checkpoint)
    except ValueError as e:
        ap.error(str(e))
    if any(x.verb == "fight" for x in steps) and args.title == "ssb":
        ap.error("the fight step needs --title pool or curse")
    if args.attack_by and args.title != "curse":
        ap.error("--attack-by requires --title curse")
    if any(x.verb in ("cast", "cure") for x in steps) and args.title != "curse":
        ap.error("the cast and cure steps require --title curse")
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
    if not args.stage_only and args.disks is None:
        ap.error("no game disks found; set $POR_DISKS or pass --disks")
    out = (pathlib.Path(args.out) if args.out
           else default_out(args.issue, args.run, git_state()["sha"]))
    if out.exists() and any(out.iterdir()):
        ap.error(f"{out} already holds a run; name a new --run")
    return run(args, steps, out, source)


if __name__ == "__main__":
    raise SystemExit(main())
