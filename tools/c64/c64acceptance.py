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
| `fight [SECONDS]` | walk `--walk` until a fight starts, then fight it with `Session.melee_turn` for SECONDS (120) |
| `peek ADDR N` | N bytes of memory, ADDR in hex |
| `save` | the game's own `ENCAMP > SAVE`; the disk copied out once closed and decoded |

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

Only Pool of Radiance is driven so far.  The later titles stage and
`--stage-only` works for them; booting one is refused until their load, camp
and fight are ported from `tools/c64/curedrive.py` and
`tools/c64/laterbattle.py`.

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
from goldbox import c64_port, c64_save, effects  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from goldbox.items import ITEM_SIZE, ITEMS_PER_CHARACTER  # noqa: E402
from tools.c64 import effectdrive, inventorycheck, traitdrive  # noqa: E402
from tools.c64 import savecheck as SC  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.traitquery import TRAIT_SLOT  # noqa: E402
from tools.registry import scratch  # noqa: E402

TITLES = {"pool": "pool-of-radiance", "curse": "curse-of-the-azure-bonds",
          "ssb": "secret-of-the-silver-blades"}

#: The titles this driver boots.  The others stage only.
DRIVEN = frozenset({"pool", "curse"})

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
AFFECTED = "IS AFFECTED BY:"
WHOLE_PARTY = "THE WHOLE PARTY"
CONTINUE = "PRESS ANY KEY TO CONTINUE"

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
         "rest": "must", "fight": "may", "peek": "must", "save": "never"}


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
    return took


def decode_save(path: pathlib.Path, staged: dict) -> dict:
    """The effect rows, the magic items and every staged byte, off a disk."""
    image = D64.open(str(path))
    game = c64_port.detect(image)
    box = c64_save.CONTAINERS[game.key]
    _, payload = _payload(image, game)
    clock = list(payload[box.clock:box.clock + 6])
    return {
        "effects": _effect_list(payload),
        "clock": clock,
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


def whom_entries(rows: list[str]) -> list[str]:
    """The names the whom menu offers, `THE WHOLE PARTY` last, `EXIT` left off.

    The menu is the party panel itself: the question goes on row 24 and
    `THE WHOLE PARTY` and `EXIT` are drawn under the names, in the panel's
    name field (captured on PORSAVE13).
    """
    if len(rows) < 25 or WHOM not in rows[24]:
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

    def wait_rows(self, ok, timeout: float) -> list[str] | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            rows = self.rows()
            if rows and ok(rows):
                return rows
            self.sess.handle_prompt()
            time.sleep(0.4)
        return None

    def fail(self, tag: str, why: str) -> StepFailed:
        self.capture(f"lost-{tag}")
        return StepFailed(why)

    def choose_bar(self, word: str, timeout: float) -> bool:
        return self.sess.select_bar(word, timeout=timeout)

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
        targets = [who] if who else offered or [WHOLE_PARTY]
        lists: dict[str, list[str]] = {}
        for target in targets:
            if not self.pick(target):
                raise self.fail("whom", f"{target} could not be chosen")
            lists[target] = self._pages(target)
        self.to_world()
        return {"offered": offered, "lists": lists}

    def pick(self, target: str) -> bool:
        """Choose TARGET on the whom menu, which is the party panel: the
        highlight is walked there by `Session.select_party`, since the panel's
        heading is drawn in the highlight colour too, and Return chooses."""
        rows = self.wait_rows(lambda r: WHOM in r[24], 30)
        if rows is None:
            return False
        entries = whom_entries(rows) + ["EXIT"]
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

    def peek(self, arg: str) -> dict:
        addr, n = parse_peek(arg)
        with self.sess.mon(10) as m:
            data = bytes(m.read(addr, n))
            m.resume()
        return {"address": f"${addr:04X}", "bytes": data.hex(" ")}

    def save(self, staged: dict) -> dict:
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        if not self.sess.save_game():
            raise self.fail("save", "ENCAMP > SAVE did not complete")
        # `save_game` gives the write a fixed fourteen seconds, which a slow
        # pooled slot can overrun.  A bar coming back can precede the end of
        # the write (the world bar shows early), so this wait does not prove
        # the write finished: `copy_closed_disk` below is what guards the
        # copy, by refusing a disk whose directory is still open.
        back = self.wait_rows(
            lambda r: any(w in r[24] for w in (CAMP_BAR, SAVE_BAR, SAVE_ERROR))
            or self.at_world(r[24]), SAVE_WAIT)
        if back is None:
            raise self.fail("save", "no bar came back after SAVE GAME")
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
                 attack_by=""):
        super().__init__(sess, log, out, game, points)
        from tools.curse_of_the_azure_bonds import cursethac0

        _, payload = _payload(D64.open(str(staged_disk)), game)
        names = cursethac0.slot_names(payload)
        self.attack_by = attack_by.upper()
        self.attack_owner = next((i for i, name in enumerate(names)
                                  if name.upper() == self.attack_by), None)
        self.attack_evidence = None
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
        self.capture("world")
        return {"position": list(self.sess.position()),
                "attack_by": self.attack_by, "attack_owner": self.attack_owner,
                "checkpoints": {k: f"${v:04X}" for k, v in self.points.items()}}

    def to_world(self, tries: int = 10) -> bool:
        ok = self.sess.to_world_bar(timeout=tries * 9)
        if not ok:
            self.capture("lost-world-route")
        return ok

    def choose_bar(self, word: str, timeout: float) -> bool:
        return self.sess.press_bar(word, timeout=timeout)

    def _id25_row(self) -> list[int] | None:
        return next((row for row in self.reading()["effects"]
                     if row[1] == 25 and row[2] == self.attack_owner), None)

    def _named_melee(self, sess, state):
        actor = sess.acting(sess.battle())
        name = "" if actor is None else actor.name.strip()
        if self.attack_evidence is not None or name.upper() != self.attack_by:
            return S.Session.melee_turn(sess, state)
        before = self._id25_row()
        self.capture(f"attack-before-{name}")
        chosen = S.Session.melee_turn(sess, state)
        if chosen == S.ATTACK:
            after = self._id25_row()
            self.capture(f"attack-after-{name}")
            self.attack_evidence = {"actor": name, "index": actor.index,
                                    "owner": self.attack_owner,
                                    "bar": state.text, "chosen": chosen,
                                    "before": before, "after": after}
            self.log.emit("named-attack", **self.attack_evidence)
        return chosen

    def await_combat(self) -> bool:
        """Answer one unreadable brawl acknowledgement while combat loads."""
        answered_blank = False
        for _ in range(30):
            if self.sess.in_combat():
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
        return self.sess.in_combat()

    def fight(self, arg: str, walk: str, steps: int) -> dict:
        from tools.c64 import laterbattle
        from tools.curse_of_the_azure_bonds import cursethac0

        if self.attack_by and self.attack_owner is None:
            raise self.fail("fighter", f"{self.attack_by} is absent from save slots")
        if not self.to_world():
            raise self.fail("world", "the world bar never came back")
        area, geo = cursethac0.area_geo(str(self.staged_disk), self.disks)
        if geo is None:
            raise self.fail("geo", f"{area} was absent from the Curse disks")
        route = laterbattle.Battle(self.out, True)
        try:
            route.sess = self.sess
            arrived = route.goto(laterbattle.TAVERN, steps, geo=geo)
            walked = route.last_goto_steps
        finally:
            route.file.close()
        self.capture("tavern")
        if not arrived:
            raise self.fail("fight", f"TAVERN was not reached in {walked} steps")
        if not self.sess.in_combat() and not self.sess.press_bar(
                laterbattle.PUNCH, timeout=20):
            raise self.fail("fight", "PUNCH BARKEEP was not selectable")
        if not self.await_combat():
            raise self.fail("fight", "Curse never entered combat mode")
        self.capture("fight-start")
        result = self.sess.fight(budget=float(arg or 120), tactic=self._named_melee)
        self.capture("fight-end")
        return {"walked": walked, "area": str(area), "acted": result.acted,
                "named_attack": self.attack_evidence,
                **dataclasses.asdict(result)}


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
            sess = curserun.CurseSession(first, slot=slot)
            sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        else:
            first = S.stage_disks(slot, args.disks)
            S.stage_writable(staged_disk, pathlib.Path(slot.dir) / "SIDE0.D64")
            sess = S.Session(first, slot=slot)
        stack.enter_context(sess.watching_dialogs())
        pool = (CurseRun(sess, log, out, game, points, args.disks, staged_disk,
                         getattr(args, "attack_by", "")) if args.title == "curse"
                else PoolRun(sess, log, out, game, points))
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
            elif step.verb == "fight":
                got = pool.fight(step.arg, args.walk, args.walk_steps)
            elif step.verb == "peek":
                got = pool.peek(step.arg)
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
            validate_curse_attack(summary["results"], attack, args.attack_by)
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
                         "'rest 8h', 'fight [SECONDS]', 'peek ADDR N', save")
    ap.add_argument("--checkpoint", action="append", default=[],
                    metavar="ADDR[=NAME]",
                    help="hex; a non-stopping exec checkpoint armed after the "
                         "load and counted after every step")
    ap.add_argument("--walk", default="I", help="the move `fight` repeats")
    ap.add_argument("--attack-by", default="",
                    help="record the named fighter's first confirmed melee attack")
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
    if args.title not in DRIVEN and not args.stage_only:
        ap.error(f"--title {args.title} stages but does not boot yet; "
                 f"pass --stage-only, or drive Pool of Radiance or Curse")
    if args.attack_by and args.title != "curse":
        ap.error("--attack-by requires --title curse")
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
