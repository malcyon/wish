#!/usr/bin/env python3
"""Does a Curse fight read the stored THAC0, or work it out again?

`#368 (Does the C64 Curse engine read thac0_current in a fight, since the
training hall overwrites it with the base and loses the strength bonus?)`.
Curse's training hall leaves a character's `thac0_current` -- the roster
block's `+0x0E`, record offset `0x10E` -- equal to `thac0_base`, and the
question is whether anything in a fight cares.

**The method is to spoil the byte and watch.**  `0x0A` is THAC0 50, and the
lowest number the game's own THAC0 table can produce is 39 -- THAC0 21, a
level-1 magic-user or thief -- before a strength penalty of at most -3, so
nothing the engine computes for anybody reaches it.  A roster block still
reading `0x0A` on the combat floor is a stored value the fight is using; one
reading `thac0_base` plus the strength bonus is the engine's own arithmetic
and the stored byte is dead.  `tools/c64strength.py` spoils Pool of Radiance's
roster the same way for `#277 (A DOS character converted to the C64 loses the
strength bonus to hit and damage, because 0x0E3 is written zero)`, and picked
the same 0x0A.

Two characters carry the spoiled byte, differing in one thing:
`strength_bonus_flag` at `0x0E3`, which `LIBRARY $394B` indexes the strength
tables through.  With it zero the rebuild adds nothing; with it one it adds
`$3840[strength_index]`.  So the pair separates "the engine rebuilt this" from
"the engine rebuilt it and the gate decided what it was worth", in one fight.

    tools/cursethac0.py stage --base WISH-SPEC-curse-trained-party.D64 \
        --out work/issue368/spoiled.D64 --spoil MATHEW --spoil MARK:gate=1

    tools/cursethac0.py run --pool 2 --save work/issue368/spoiled.D64 \
        --out work/issue368/run5 --goto 6,10 --quick 6

And the other half of the question, which is what the **training hall** writes
rather than what the fight does.  The hall refuses a character who cannot
advance, so it takes an experience total as a third input:

    tools/cursethac0.py stage --base <same> --out work/issue368/hall.D64 \
        --spoil MARK:gate=1,xp=46000 --spoil MATHEW:gate=1

    tools/cursethac0.py run --pool 2 --save work/issue368/hall.D64 \
        --out work/issue368/hall1 --train MARK --steps 0 --punch "" --wait 0

`run` claims a pooled VICE slot, stages the six Curse sides beside the spoiled
save, boots, loads the party through the game's own `LOAD SAVED GAME`, and
reads the roster page at `$6700` and the resident record at `$7C00` at every
stage -- after the load, after a training, after a `VIEW` sheet, on the combat
floor and after the fight.  Every reading goes to `thac0.jsonl` as it is
taken, because a run that dies half way still has to have said what it saw.

Nothing is written outside `--out` and the pool slot's own directory; the
player's disks are opened read only and `POR_HEADLESS` keeps the window off
the desktop.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import struct
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS as GAME  # noqa: E402
from goldbox.d64 import D64, attach_load_address, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools import session as S  # noqa: E402

#: Where `SAVEAZURE` loads, and the two regions inside it this asks about.
#: The eight 256-byte character slots start `$400` in and the eight 32-byte
#: roster blocks `$1C00` in, which is `goldbox.games`' own geometry.
SAVE_LOAD = 0x4B00
SLOT0 = 0x400
SLOT_STRIDE = 0x100
NAMES_AT = 0xC00
#: Curse's name table entry, which is **not** `goldbox.layout.NAME_SIZE`:
#: the record head holds twenty bytes and this table sixteen.
NAME_SIZE = 16
ROSTER_AT = 0x1C00
ROSTER_STRIDE = 0x20
SLOTS = 8

#: The same two regions as the running machine holds them.
ROSTER_LIVE = SAVE_LOAD + ROSTER_AT              # $6700
SLOTS_LIVE = SAVE_LOAD + SLOT0                   # $4F00

#: Where `GEN`, `DUNGEON` and `COMBAT` stage the character whose turn it is,
#: and the roster block that follows it.  `tools/cursetrain.py` fixed the
#: first from `GEN $151D`; the second is `$7C00 + 0x100`.
RECORD_LIVE = 0x7C00
RESIDENT_ROSTER = 0x7D00

#: Record and roster offsets this tool reads or writes.
THAC0_BASE = 0x071
STRENGTH_INDEX = 0x0E2
STRENGTH_GATE_BYTE = 0x0E3
ROSTER_THAC0 = 0x0E
ROSTER_AC = 0x0F
ROSTER_DAMAGE_BONUS = 0x17
EXPERIENCE = 0x0E8
COMBAT_BIAS = 60

#: `GEN $12CA`'s gate on the party menu's `TRAIN CHARACTER`, and what the
#: area scripts themselves write into it (`tools/cursetrain.py`, `#18
#: (Measure Curse's trainer so Level Up works there)`).  Writing it from the
#: monitor opens the hall wherever the party stands, which saves walking to
#: one -- `docs/70-driving-the-game.md`'s "open the gate rather than walk to
#: it".
HALL_GATE = 0x7EA8
HALL_OPEN = 0x7F

#: What goes into a spoiled roster block: THAC0 50, which no class, level or
#: strength in Curse's tables can produce.
SPOIL_THAC0 = 0x0A

#: `LIBRARY` is resident at `$2DC8` in Curse and Silver Blades alike.
#: `$3918` is the roster rebuild -- `$393C LDA $7C71 / STA $7D0E` -- and
#: `$394B` its strength gate, `LDX $7CE3 / BEQ / LDX $7CE2`.
REBUILD = 0x3918
STRENGTH_GATE = 0x394B

#: The live x, y, facing triple, unrelocated in all three titles.
POSITION = 0xC04B

#: Move keys as PETSCII codes: Curse reads them from the KERNAL buffer only.
MOVE = {"I": 0x49, "J": 0x4A, "K": 0x4B, "M": 0x4D}

#: Words that appear on a combat command bar and on no other bar in Curse.
COMBAT_WORDS = ("DONE", "GUARD")

#: Row 24 when the game is waiting for a direction, and the world bar's own
#: two words.  Neither is a script bar and neither should be dismissed.
MOVE_SUBBAR = "I,J,K,M"
WORLD_WORDS = ("MOVE", "ENCAMP")

#: What answers a script bar without doing anything: the locked door's
#: `BASH PICKLOCK QUIT`, a shopkeeper's `YES NO`, a room's `... LEAVE`.
DISMISS = ("QUIT", "LEAVE", "NO")

RE_THACO = re.compile(r"THACO\s+(\d+)")
RE_DAMAGE = re.compile(r"DAMAGE\s+(\S+)")


# -- the offline half ------------------------------------------------------

def payload(image: D64) -> tuple[int, bytearray]:
    load, body = split_load_address(image.read_file(GAME.save_file))
    return load, bytearray(body)


def slot_names(body: bytes) -> list[str]:
    out = []
    for i in range(SLOTS):
        at = NAMES_AT + i * NAME_SIZE
        out.append(body[at:at + NAME_SIZE].split(b"\0")[0].decode("latin1"))
    return out


def read_block(body: bytes, slot: int) -> dict:
    """What one slot holds, record and roster block together."""
    rec = body[SLOT0 + slot * SLOT_STRIDE:SLOT0 + (slot + 1) * SLOT_STRIDE]
    ros = body[ROSTER_AT + slot * ROSTER_STRIDE:
               ROSTER_AT + (slot + 1) * ROSTER_STRIDE]
    return {"slot": slot,
            "thac0_base": rec[THAC0_BASE],
            "strength_index": rec[STRENGTH_INDEX],
            "strength_gate": rec[STRENGTH_GATE_BYTE],
            "roster_thac0": ros[ROSTER_THAC0],
            "roster_ac": ros[ROSTER_AC],
            "roster_damage_bonus": ros[ROSTER_DAMAGE_BONUS]}


def spoil(body: bytearray, slot: int, gate: int | None = None,
          xp: int | None = None) -> dict:
    """Put `SPOIL_THAC0` in one slot's roster block, and nothing else.

    The gate is a second, separate input: `strength_bonus_flag` at `0x0E3`
    decides whether the rebuild adds a strength bonus at all, so forcing it
    on one character and leaving it on another is what tells a rebuild that
    happened from a rebuild that happened *and* found the gate open.

    `xp` is a third, and is only for the training-hall half of the question:
    a character the hall refuses cannot show what the hall writes.  All three
    are **inputs**; the measurement is what the engine does with them.
    """
    before = read_block(body, slot)
    body[ROSTER_AT + slot * ROSTER_STRIDE + ROSTER_THAC0] = SPOIL_THAC0
    if gate is not None:
        body[SLOT0 + slot * SLOT_STRIDE + STRENGTH_GATE_BYTE] = gate
    if xp is not None:
        at = SLOT0 + slot * SLOT_STRIDE + EXPERIENCE
        body[at:at + 3] = int(xp).to_bytes(3, "little")
    return {"slot": slot, "before": before, "after": read_block(body, slot)}


def parse_spoil(want: str) -> tuple[str, int | None, int | None]:
    """`NAME`, or `NAME:gate=N`, or `NAME:gate=N,xp=M`."""
    name, _, rest = want.partition(":")
    gate = xp = None
    for bit in filter(None, rest.split(",")):
        key, _, value = bit.partition("=")
        if key == "gate":
            gate = int(value, 0)
        elif key == "xp":
            xp = int(value, 0)
        else:
            raise SystemExit(f"--spoil takes gate=N and xp=M, not {bit!r}")
    return name, gate, xp


def stage(args) -> int:
    """Copy a Curse save disk and spoil the named characters' roster THAC0."""
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(args.base, out)
    # A specimen is read-only in the tree; the copy has to be writable.
    out.chmod(0o644)
    image = D64.from_bytes(out.read_bytes())
    load, body = payload(image)
    names = slot_names(body)

    made = []
    for want in args.spoil:
        name, gate, xp = parse_spoil(want)
        if name.upper() not in [n.upper() for n in names]:
            raise SystemExit(f"{args.base} holds no {name!r}: {names}")
        slot = [n.upper() for n in names].index(name.upper())
        made.append({"name": names[slot], **spoil(body, slot, gate, xp)})

    image.write_file_inplace(GAME.save_file,
                             attach_load_address(load, bytes(body)))
    out.write_bytes(image.to_bytes())
    # Every image copied out of a pool slot after `SAVE CURRENT GAME` has a
    # `SAVEAZURE` the drive never closed, and the game refuses one with
    # `60, WRITE FILE OPEN` (`tools/curseload.py`, `#298`).
    from tools import curseload  # noqa: PLC0415
    closed = curseload.close_splat(str(out))
    print(json.dumps({"staged": str(out), "spoiled": made,
                      "closed": closed}, indent=2))
    return 0


def show(args) -> int:
    """Print the two regions of a Curse save disk, with no emulator."""
    image = D64.from_bytes(pathlib.Path(args.disk).read_bytes())
    _, body = payload(image)
    names = slot_names(body)
    for slot in range(SLOTS):
        block = read_block(body, slot)
        if not names[slot]:
            continue
        print(f"{slot} {names[slot]:16s} "
              f"base {block['thac0_base']:3d} "
              f"(THAC0 {COMBAT_BIAS - block['thac0_base']:2d})  "
              f"roster {block['roster_thac0']:3d} "
              f"(THAC0 {COMBAT_BIAS - block['roster_thac0']:2d})  "
              f"str index {block['strength_index']:2d}  "
              f"gate {block['strength_gate']}")
    return 0


# -- the driven half -------------------------------------------------------

def checkpoint_hits(mon, number: int) -> int:
    """How many times a checkpoint has fired: bytes 13-16 of the response."""
    body = mon.command(0x11, struct.pack("<I", number))
    return struct.unpack("<I", body[13:17])[0]


class Run:
    """One driven session, logging every reading as it is taken."""

    def __init__(self, out: pathlib.Path, quiet: bool):
        out.mkdir(parents=True, exist_ok=True)
        self.out = out
        self.file = (out / "thac0.jsonl").open("w")
        self.quiet = quiet
        self.sess = None
        self.shots = 0
        self.checks: dict[str, int] = {}

    def log(self, kind: str, **kw) -> None:
        kw["kind"], kw["t"] = kind, round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()
        if not self.quiet:
            print(kind, {k: v for k, v in kw.items()
                         if k not in ("kind", "t")}, flush=True)

    # -- reading the machine ----------------------------------------------

    def peek(self, addr: int, length: int) -> bytes:
        with self.sess.mon(8) as m:
            data = m.read(addr, length)
            m.resume()
        return data

    def arm(self) -> None:
        """Count the rebuild and its strength gate, without stopping."""
        with self.sess.mon(8) as m:
            self.checks["rebuild"] = m.checkpoint_set(
                REBUILD, REBUILD, exec_=True, stop=False)
            self.checks["gate"] = m.checkpoint_set(
                STRENGTH_GATE, STRENGTH_GATE, exec_=True, stop=False)
            m.resume()
        self.log("armed", rebuild=hex(REBUILD), gate=hex(STRENGTH_GATE),
                 numbers=dict(self.checks))

    def counts(self) -> dict:
        if not self.checks:
            return {}
        with self.sess.mon(8) as m:
            got = {k: checkpoint_hits(m, n) for k, n in self.checks.items()}
            m.resume()
        return got

    def reading(self, stage: str) -> dict:
        """Both regions of the machine, plus the checkpoint counts."""
        roster = self.peek(ROSTER_LIVE, SLOTS * ROSTER_STRIDE)
        slots = self.peek(SLOTS_LIVE, SLOTS * SLOT_STRIDE)
        resident = self.peek(RECORD_LIVE, 0x120)
        blocks = []
        for slot in range(SLOTS):
            ros = roster[slot * ROSTER_STRIDE:(slot + 1) * ROSTER_STRIDE]
            rec = slots[slot * SLOT_STRIDE:(slot + 1) * SLOT_STRIDE]
            if not ros[0]:
                continue
            blocks.append({"slot": slot,
                           "thac0_base": rec[THAC0_BASE],
                           "strength_index": rec[STRENGTH_INDEX],
                           "strength_gate": rec[STRENGTH_GATE_BYTE],
                           "roster_thac0": ros[ROSTER_THAC0],
                           "roster_ac": ros[ROSTER_AC],
                           "roster_damage_bonus": ros[ROSTER_DAMAGE_BONUS]})
        out = {"blocks": blocks,
               "resident_thac0_base": resident[THAC0_BASE],
               "resident_strength_gate": resident[STRENGTH_GATE_BYTE],
               "resident_roster_thac0": resident[0x100 + ROSTER_THAC0],
               "checkpoints": self.counts()}
        self.log("reading", stage=stage, **out)
        return out

    def dump(self, tag: str) -> list[str]:
        s = self.sess.screen()
        rows = ["(bitmap)"] if s is None else [s.row(r) for r in range(25)]
        self.shots += 1
        stem = self.out / f"{self.shots:02d}-{tag}"
        stem.with_suffix(".txt").write_text("\n".join(rows) + "\n")
        self.sess.kbd.screenshot(str(stem.with_suffix(".png")))
        return rows

    # -- driving ----------------------------------------------------------

    def triple(self) -> tuple[int, int, int]:
        return tuple(self.peek(POSITION, 3))          # type: ignore[return-value]

    def press(self, key: str) -> bool:
        """One move key, through the driver that knows Curse's move sub-bar.

        A raw `press_kernal(0x49)` on the world bar does nothing at all:
        `MOVE` has to be chosen first, and the game then sits on
        `I,J,K,M, RETURN OR BUTTON` until something takes it away.  The first
        run of this tool sent sixty of them at the world bar and the triple
        never moved once (`work/issue368/run1`), which reads exactly like a
        party walled in on every side.  `CurseSession.walk_one` enters and
        keeps that state and judges the step in memory.
        """
        return bool(self.sess.walk_one(key))

    def row24(self) -> str:
        s = self.sess.screen()
        return "" if s is None else s.row(24).strip()

    def in_combat(self) -> bool:
        return any(w in self.row24() for w in COMBAT_WORDS)

    def clear_bar(self) -> str | None:
        """Answer a script bar that is eating the move keys, and say which.

        Walking a Curse street puts a bar in front of the party every few
        squares, and while one is up `enter_move` cannot get back to
        `I,J,K,M` -- so every following step is refused and the run looks
        like a party walled in.  The locked door north of `7,12` in Tilverton
        is the one that stopped `work/issue368/run4`: `BASH PICKLOCK QUIT`,
        for twenty-five seconds a step until the budget was gone.

        Each of these words leaves the party where it is with nothing else
        changed, which is what a walker wants and what `BASH` is not.
        """
        row = self.row24()
        if not row or MOVE_SUBBAR in row or self.in_combat():
            return None
        if all(w in row for w in WORLD_WORDS):
            return None
        for word in DISMISS:
            if word in row.split():
                self.sess.press_bar(word, timeout=10)
                self.log("dismissed", word=word, was=row, now=self.row24())
                return word
        return None

    def quickfight(self, turns: int) -> None:
        """Let the game resolve turns with its own `QUICK`, and read the rolls.

        **One landed blow is the whole proof.**  A character whose roster
        THAC0 is the staged 50 needs 44 on a twenty-sided die to hit anything
        in a tavern brawl, so he can never hit at all; a line saying he did
        is a single observation that rules the staged byte out, where the
        miss stream would need counting.  `QUICK` is per character and per
        turn rather than a mode, so each press resolves one combatant.
        """
        for turn in range(turns):
            if not self.in_combat():
                self.log("fight-over", turn=turn, row24=self.row24())
                return
            rows = [r.rstrip() for r in self.dump(f"turn-{turn:02d}")]
            said = [r.strip() for r in rows
                    if "HIT" in r or "MISS" in r or "DAMAGE" in r]
            pressed = self.sess.press_bar("QUICK", timeout=15.0)
            self.sess.settle(3.0)
            after = [r.strip() for r in self.sess_rows()
                     if "HIT" in r or "MISS" in r or "DAMAGE" in r]
            self.log("quick", turn=turn, pressed=pressed, before=said,
                     after=after, row24=self.row24())
        self.log("quick-budget", turns=turns)

    def sess_rows(self) -> list[str]:
        s = self.sess.screen()
        return [] if s is None else [s.row(r) for r in range(25)]

    def turn_to(self, want: int, tries: int = 6) -> int:
        """Turn until the facing byte says so, reading it after every press.

        **Not a computed number of presses.**  Counting `(want - facing) % 4`
        put the party the wrong way round in `work/issue368/run2` -- it wanted
        north, pressed three times and ended facing west -- and a walk that
        thinks it is facing north while it is facing west oscillates between
        two squares until the budget is gone, which is what that run spent
        thirty-six of its forty steps doing.  The triple is the answer to
        which way the party is pointing; the key count is a guess about it.
        """
        for _ in range(tries):
            facing = self.triple()[2]
            if facing == want:
                return facing
            self.press("K")
        return self.triple()[2]

    def goto(self, target: tuple[int, int], budget: int = 60,
             geo=None) -> bool:
        """Walk to a square, following the area's own map where there is one.

        **A greedy walk cannot get there.**  From `5,13` in Tilverton the
        square north of `6,12` is solid and the door north of `7,12` is
        locked -- `BASH PICKLOCK QUIT` -- so a walker that steers by which
        axis is furthest out spends its budget at that door, which is what
        `work/issue368/run3` did with eight steps.  The route round it is six
        squares and the map says so: `GEO01`'s own passability, breadth
        first.

        A step that goes nowhere bans that edge and the route is planned
        again, which is how the locked door is discovered rather than
        assumed -- the map cannot tell a locked door from an open one.
        """
        banned: set[tuple[int, int, int]] = set()
        came_from: tuple[int, int] | None = None
        for _ in range(budget):
            if self.in_combat():
                return True
            self.clear_bar()
            if self.in_combat():
                return True
            x, y, facing = self.triple()
            if (x, y) == target:
                return True
            route = plan(geo, (x, y), target, banned) if geo else []
            if route:
                want = route[0]
            else:
                wants = [d for d, ok in ((0, y > target[1]), (2, y < target[1]),
                                         (1, x < target[0]), (3, x > target[0]))
                         if ok]
                wants += [d for d in range(4) if d not in wants]
                ahead = {0: (x, y - 1), 1: (x + 1, y), 2: (x, y + 1),
                         3: (x - 1, y)}
                fresh = [d for d in wants if (x, y, d) not in banned
                         and ahead[d] != came_from]
                want = (fresh or [d for d in wants if (x, y, d) not in banned]
                        or wants)[0]
            self.turn_to(want)
            before = self.triple()
            moved = self.press("I")
            after = self.triple()
            if before[:2] == after[:2]:
                banned.add((x, y, want))
            else:
                came_from = before[:2]
            self.log("step", before=list(before), after=list(after),
                     want=want, moved=moved, planned=route,
                     banned=len(banned), row24=self.row24())
        return self.in_combat() or self.triple()[:2] == target


#: Which way each facing moves the party.  `NESW` = 0..3, as
#: `automap.state.facing_letter` and `goldbox.areas` both read it.
STEP = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}


def area_geo(disk: str, disks: str):
    """The `GEO` the staged save's own area byte names, off the Curse sides.

    The save says where the party is; the map says how to get anywhere from
    there. Reading the area out of the file rather than looking it up in a
    table is what stops a route being planned on the wrong floor plan.
    """
    from goldbox.geo import Geo  # noqa: PLC0415
    from goldbox.savegame import load_save  # noqa: PLC0415

    _, save0, _ = load_save(D64.open(disk))
    name = save0.area_file
    for side in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        image = D64.open(side)
        entry = image.find(name.encode() if isinstance(name, str) else name)
        if entry is not None:
            return name, Geo.from_bytes(image.read_file(entry))
    return name, None


def plan(geo, start: tuple[int, int], target: tuple[int, int],
         banned=()) -> list[int]:
    """The shortest run of facings from `start` to `target`, or `[]`."""
    import collections  # noqa: PLC0415

    previous = {start: None}
    queue = collections.deque([start])
    while queue:
        x, y = queue.popleft()
        for facing, (dx, dy) in STEP.items():
            if (x, y, facing) in banned or not geo.is_passable(x, y, facing):
                continue
            nxt = (x + dx, y + dy)
            if not (0 <= nxt[0] < 16 and 0 <= nxt[1] < 16) or nxt in previous:
                continue
            previous[nxt] = ((x, y), facing)
            queue.append(nxt)
    if target not in previous:
        return []
    route, here = [], target
    while previous[here]:
        square, facing = previous[here]
        route.append(facing)
        here = square
    return list(reversed(route))


def sheet_numbers(lines) -> dict:
    text = "\n".join(lines)
    thaco, damage = RE_THACO.search(text), RE_DAMAGE.search(text)
    return {"thaco": int(thaco.group(1)) if thaco else None,
            "damage": damage.group(1) if damage else None}


def drive(args) -> int:
    from tools import curseload, curserun  # noqa: PLC0415

    out = pathlib.Path(args.out)
    run = Run(out, args.quiet)
    disks = args.disks or gamedisks.find("curse-of-the-azure-bonds")
    if not disks:
        raise SystemExit("no Curse disks; pass --disks")

    area, geo = area_geo(args.save, str(disks))
    slot = S.claim_slot(args.slot, "cursethac0/368")
    run.log("slot", n=slot.n, display=slot.display, dir=slot.dir,
            save=args.save, disks=str(disks), area=str(area),
            map_read=geo is not None)
    rc = 1
    try:
        boot = curserun.stage(slot, str(disks), args.save)
        sess = curserun.CurseSession(boot, slot=slot)
        run.sess = sess
        sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        if not sess.boot():
            run.log("boot", reached_menu=False)
            return 1
        run.log("boot", reached_menu=True)
        run.dump("party-menu")

        outcome = curseload.load_saved_game(
            sess, note=lambda **kw: run.log("load", **kw),
            shot=lambda tag: run.dump(tag))
        run.log("loaded", outcome=outcome)
        if outcome != "loaded":
            return 1
        run.arm()
        run.reading("after-load")

        # The training hall, if this run is the one asking what it writes.
        # `GEN $12CA` gates `TRAIN CHARACTER` on `$7EA8`, and the area
        # scripts write 127 there themselves, so opening it from the monitor
        # saves walking to a hall and changes nothing else.  Any trip through
        # the menu rebuilds it, which is what `VIEW CHARACTER` then `EXIT` is
        # for.
        if args.train:
            with sess.mon(8) as m:
                m.write(HALL_GATE, bytes([HALL_OPEN]))
                m.resume()
            run.log("hall", opened=hex(HALL_GATE), value=HALL_OPEN)
            sess.select_row("VIEW CHARACTER", timeout=25.0)
            sess.settle(3.0)
            sess.select_row("EXIT", timeout=15.0)
            sess.settle(3.0)
            picked = sess.select_row("TRAIN CHARACTER", timeout=25.0)
            sess.settle(3.0)
            run.dump("train-list")
            # **One press and no Return.**  A Return after the name starts a
            # second training, which is how a character gained two levels
            # nobody asked for on `#18 (Measure Curse's trainer so Level Up
            # works there)`.
            trained = sess.select_row(args.train, timeout=25.0)
            sess.settle(8.0)
            rows = run.dump("trained")
            run.log("trained", who=args.train, reached_hall=picked,
                    pressed=trained,
                    said=[r.strip() for r in rows if r.strip()][:6])
            run.reading("after-training")

        # The sheet before anything has had a chance to rebuild.  The engine
        # draws THACO from the roster block, so a spoiled byte shows here if
        # nothing has recomputed yet.
        for name in args.sheet:
            if sess.select_row("VIEW CHARACTER", timeout=25.0):
                sess.settle(3.0)
                sess.select_row(name, timeout=25.0)
                sess.settle(4.0)
                rows = run.dump(f"sheet-{name}-before")
                run.log("sheet", when="before", name=name,
                        **sheet_numbers([r.strip() for r in rows if r.strip()]))
                sess.leave_sheet()
                sess.settle(2.0)
                s = sess.screen()
                if s is not None and s.contains("VIEW WHICH"):
                    sess.select_row("EXIT", timeout=10.0)
                    sess.settle(2.0)
        run.reading("after-sheets")

        if not sess.begin_adventuring():
            run.log("world", entered=False)
            return 1
        sess.wait_for_world(240)
        run.dump("world")
        run.reading("in-the-world")

        target = tuple(int(n) for n in args.goto.split(","))
        arrived = run.goto(target, args.steps, geo=geo)
        run.log("goto", target=list(target), arrived=arrived,
                triple=list(run.triple()), row24=run.row24())
        run.dump("arrived")
        run.reading("arrived")

        # The tavern's script draws a **bar**, not a menu of rows:
        # `PUNCH BARKEEP  HAVE A DRINK  LEAVE`.  `CurseSession.press_bar`
        # walks the highlight and presses whichever Return the screen reads.
        if args.punch and not run.in_combat():
            for word in args.punch.split("/"):
                pressed = sess.press_bar(word, timeout=20.0)
                sess.settle(3.0)
                run.log("script", word=word, pressed=pressed,
                        row24=run.row24())
                run.dump(f"script-{word.replace(' ', '-')}")
                if run.in_combat():
                    break
        run.reading("script-answered")

        # The combat screen takes several seconds to draw and reads as a
        # blank row 24 while it does, so the wait is for the bar rather than
        # for a fixed number of settles.
        for _ in range(args.wait):
            if run.in_combat():
                break
            sess.settle(4.0)
        run.dump("combat-floor")
        run.log("combat", on_the_floor=run.in_combat(), row24=run.row24())
        run.reading("combat-floor")
        rc = 0 if run.in_combat() else 2

        # `VIEW` on the combat bar draws the acting character's own sheet, so
        # the number the fight is using can be read as a person reads it and
        # not only off the roster page.
        if run.in_combat() and args.view_in_fight:
            pressed = sess.press_bar("VIEW", timeout=20.0)
            sess.settle(4.0)
            rows = run.dump("sheet-in-the-fight")
            run.log("sheet", when="in-the-fight", pressed=pressed,
                    who=rows[2].strip(" $*<>|").strip(),
                    **sheet_numbers([r.strip() for r in rows if r.strip()]))
            sess.press_bar("EXIT", timeout=15.0)
            sess.settle(3.0)

        if run.in_combat() and args.quick:
            run.quickfight(args.quick)
            run.dump("after-fight")
            run.reading("after-fight")
    finally:
        run.log("done")
        if run.sess is not None:
            try:
                with run.sess.mon(8) as m:
                    m.checkpoints_clear()
                    m.resume()
            except Exception as exc:
                run.log("checkpoints", cleared=False, why=str(exc))
            run.sess.terminate()
        slot.teardown()
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="what", required=True)

    st = sub.add_parser("stage", help="spoil a roster THAC0 in a copy")
    st.add_argument("--base", required=True, help="the save disk to copy")
    st.add_argument("--out", required=True, help="where the copy goes")
    st.add_argument("--spoil", action="append", default=[], metavar="NAME[:gate=N]",
                    help="whose roster THAC0 to spoil, and optionally what "
                         "to force into strength_bonus_flag at 0x0E3")
    st.set_defaults(func=stage)

    sh = sub.add_parser("show", help="print both regions of a save disk")
    sh.add_argument("disk")
    sh.set_defaults(func=show)

    rn = sub.add_parser("run", help="boot, load, walk into a fight, read")
    rn.add_argument("--save", required=True, help="the staged save disk")
    rn.add_argument("--disks", default=None, help="the Curse sides")
    rn.add_argument("--pool", dest="slot", type=int, default=None,
                    help="demand this pool slot")
    rn.add_argument("--out", default="work/issue368/run", help="run directory")
    rn.add_argument("--goto", default="6,10",
                    help="the square to walk to: Tilverton's tavern by default")
    rn.add_argument("--steps", type=int, default=60, help="walk budget")
    rn.add_argument("--train", default="",
                    help="open the training hall from the monitor and train "
                         "this character, which is the other half of the "
                         "question: what the hall itself writes")
    rn.add_argument("--sheet", action="append", default=[],
                    help="read this character's sheet before the fight")
    rn.add_argument("--punch", default="PUNCH BARKEEP",
                    help="script menu words to press on arrival, / separated")
    rn.add_argument("--wait", type=int, default=6,
                    help="how many settles to give the fight to start")
    rn.add_argument("--view-in-fight", action="store_true",
                    help="press VIEW on the combat bar and read the acting "
                         "character's THACO off the game's own sheet")
    rn.add_argument("--quick", type=int, default=0,
                    help="resolve this many combatant turns with the game's "
                         "own QUICK, reading the hit and miss lines")
    rn.add_argument("--quiet", action="store_true")
    rn.set_defaults(func=drive)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
