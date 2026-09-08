#!/usr/bin/env python3
"""Run a Pool of Radiance party away from a fight, and read what the game prints.

`tools/session.py` classified two of the engine's three fight outcomes.  The
third -- the party running away -- had never been read off a screen, so a
driven fight that ended in flight came back as `ended` (`#445`).  This drives
it, through the game's own FLEE.

    tools/fleedrive.py code
    POR_HEADLESS=1 tools/fleedrive.py drive --out work/issue445/run1

**`code` needs no emulator.**  It reads each C64 title's own `POST.COM` off
the player's disks and prints the three end-of-fight lines, the base the
pointer table implies rather than the one the PRG header claims, and the
branch that picks the fleeing one -- so "the wording is the same on all three
titles" is a reading of three binaries rather than a guess from one screen.

**`drive` uses the game's own FLEE and patches nothing until the game has
already recorded a flight.**  A character flees in this engine by walking off
the edge of the combat map: `COMBAT $0E6E` puts up `FLEE: YES NO` when the
step leaves the map, and `$16FA` decides -- nobody adjacent, or the
character's own movement against the fastest thing on the other side -- and
writes `$86 RUNNING` into the record at `$1719` with the message `GOT AWAY`.
So the tactic here walks each character to the nearest edge and steps off it.

The outcome the message needs is not "everybody ran": `POST.COM $0903` prints
`THE PARTY RUNS AWAY` when **nobody on the party's side is standing and at
least one character is `RUNNING`**.  So once the game has written the first
`$86` -- and not before -- the run puts whoever is still standing on one hit
point through the monitor and passes their turns while the monsters finish
them, which is `tools/defeatdrive.py`'s patch and nothing more (`#128`).
Every flight in the run is the game's, the hit points are the only thing this
writes, and they are written after the outcome has already been decided.
**`--no-wound` turns even that off**, and the run that read the line used it:
by the time anybody got away two characters were already `$84 DYING` and the
rest were on two or three hit points.

**The line is up for under half a second.**  The fleeing arm calls no message
delay where the losing one calls the game's own combat speed, so the endgame
is polled at `--endgame-poll` -- a tenth of `--poll` -- from the moment the
first `$86` appears, and the photograph is taken inside the branch that reads
the line rather than after the loop returns.  A one-second poll read the frame
either side of it and saw neither.

Everything goes to `--out`: `run.jsonl` one event per line, `screens.txt` the
distinct screens in order, `after.json` the program-counter samples taken once
the outcome line is up, and `outcome-line.png`.  Nothing here writes to the
player's disks -- `stage_disks` copies the sides and the save into the pool
slot, and `Session.attach` refuses a path outside it.

Written for `#445 (The game's third fight outcome, THE PARTY RUNS AWAY, has
never been seen on a screen)`.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from goldbox import savegame  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import savecheck as SC  # noqa: E402
from tools import session as S  # noqa: E402

#: The player's disks: `$POR_DISKS`, then the search every other tool does.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: `SAVEDGAME1`'s roster page, live.  Eight blocks of `$20`, one per save
#: slot; the fields inside one are `goldbox/savegame.py`'s.
ROSTER = savegame.SAVE1_LOAD_ADDRESS                            # $8300
ROSTER_BYTES = savegame.ROSTER_STRIDE * savegame.ROSTER_COUNT   # $100
STATUS = 0x00                       # record 0x100, the status byte
HP = savegame.ROSTER_HP_CURRENT     # 0x19, the 16-bit current hit points

#: `$86`, which `LIBRARY $38BE` draws as `RUNNING`.  `COMBAT $1719` writes it
#: to a character who got away and `POST.COM $08C6` counts it.
RUNNING = 0x86

#: The result byte `POST.COM $091A` writes and the ECL scripts read:
#: 0 and 1 won, `$80` lost, `$81` ran away.
RESULT = 0x6DC7

#: `POST.COM $0957`, the jump-to-itself the **losing** branch reaches
#: (`#128`).  Sampled here as a control: the fleeing branch at `$0929` ends
#: `JMP $14AC`, so a run that ends in flight should never be caught here.
SPIN = 0x0957

#: What the low three bits of record `0x100` name, from `LIBRARY $38BE`.
STATUS_WORDS = {0: "(empty)", 1: "OK", 2: "GONE", 3: "DEAD", 4: "DYING",
                5: "UNCONSIOUS", 6: "RUNNING", 7: "STONED"}

#: The three lines `POST.COM` can print when a fight ends, entries 2, 3 and 4
#: of its own pointer table -- `tools/session.py`'s, because a second copy of
#: three strings is a second copy to correct.  `code` re-derives all three off
#: the player's own disks and needs none of them.
OUTCOME_LINES = S.OUTCOME_LINES

#: What `COMBAT`'s own message table says when a flee attempt resolves --
#: entries 5 and 6 of the table at `$0BF6`/`$0C0B`, printed by `$0B07`.
GOT_AWAY, FAILED = "GOT AWAY", "FAILED"


def describe(value: int) -> str:
    """`$86 RUNNING` -- the byte and the word `LIBRARY $38BE` would draw."""
    return f"${value:02X} {STATUS_WORDS.get(value & 7, '?')}" + (
        " (down)" if value & 0x80 else "")


# -- reading the code, with no emulator --------------------------------------

#: Where `LINKER` puts an overlay it calls.  The PRG headers say `$1000`,
#: `$3000` and `$1220` for the three `POST.COM`s and are wrong every time.
LINKER_BASE = 0x0800

#: Which entry of that table `THE PARTY RUNS AWAY` is, with `THE PARTY HAS
#: LOST` and `THE PARTY HAS WON !` next to it (`#128`).
RAN_INDEX = 2

#: Where each C64 title's disks are, by the name `tools/gamedisks.py` uses.
TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
          "secret-of-the-silver-blades")


def overlay(name: str, root: str) -> tuple[str, int, bytes]:
    """`(disk, declared load address, body)` for a file on any disk in `root`.

    `tools/overlay.py` does this for Pool of Radiance and finds its disks by
    the `POOL*` glob, which is no use for the other two titles' names; this
    takes a directory and reads every image in it.
    """
    for path in sorted(glob.glob(os.path.join(root, "*.[dD]64"))):
        try:
            image = D64(pathlib.Path(path).read_bytes())
        except Exception:
            continue
        for entry in image.directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == name:
                declared, body = split_load_address(image.read_file(entry))
                return os.path.basename(path), declared, body
    raise SystemExit(f"No file called {name} on any disk under {root}")


def outcome_table(body: bytes) -> tuple[int, int, int, int] | None:
    """Find the split pointer table the three outcome lines sit in.

    Returns `(base, lo, hi, index)` -- the address the overlay runs at, the
    file offsets of the table's low and high halves, and the index of
    `THE PARTY RUNS AWAY` in it.  All four are **derived from the file**: the three
    strings are consecutive, so their pointers are three consecutive entries,
    and the base is whatever makes the entries point at the strings.  Nothing
    here believes the PRG header, which says `$1000` for Pool of Radiance,
    `$3000` for Curse and `$1220` for Silver Blades and is wrong every time.

    None when the three strings are not all there, or no table points at them.
    """
    where = [body.find(line.encode() + b"\x00")
             for line in ("THE PARTY RUNS AWAY", "THE PARTY HAS LOST",
                          "THE PARTY HAS WON !")]
    if any(at < 0 for at in where):
        return None
    ran, lost, won = where
    # The low bytes of three pointers differ by the same amounts as the
    # strings do, whatever the base is, so the low half can be found before
    # the base is known.
    d1, d2 = (lost - ran) & 0xFF, (won - lost) & 0xFF
    for lo in range(len(body) - 2):
        if (body[lo + 1] - body[lo]) & 0xFF != d1:
            continue
        if (body[lo + 2] - body[lo + 1]) & 0xFF != d2:
            continue
        for stride in range(8, 0x80):
            if lo + stride + 2 >= len(body):
                break
            base = (body[lo] | body[lo + stride] << 8) - ran
            if not 0 < base < 0x10000:
                continue
            ok = all((body[lo + n] | body[lo + stride + n] << 8) - at == base
                     for n, at in enumerate((ran, lost, won)))
            # `$0800` is where LINKER puts an overlay it calls, and it is
            # the answer for all three titles; a table that only works at
            # some other base is left unreported rather than believed.
            if ok and base == LINKER_BASE:
                # `lo` is the fleeing line's own entry, and the caller wants
                # the table it sits in: the three lines are entries 2, 3 and
                # 4 (`#128`), so the table starts two entries earlier.
                return base, lo - RAN_INDEX, lo + stride - RAN_INDEX, RAN_INDEX
    return None


#: The branch `POST.COM` takes when the result byte is `$81`: compare, skip
#: the losing arm, load the message index, load the row, print.
FLEE_BRANCH = bytes((0xC9, 0x81, 0xD0))


def flee_branch(body: bytes) -> tuple[int, int, int] | None:
    """`(offset, message index, row)` of the arm that prints the fleeing line.

    Found by shape rather than by address, so it answers on a title nobody
    has mapped: `CMP #$81 / BNE <lost> / LDX #<index> / LDA #<row> / JSR`.
    """
    at = -1
    while True:
        at = body.find(FLEE_BRANCH, at + 1)
        if at < 0:
            return None
        tail = body[at + 3:at + 11]
        if len(tail) < 8:
            return None
        if tail[1] == 0xA2 and tail[3] == 0xA9 and tail[5] == 0x20:
            return at, tail[2], tail[4]


def read_code(roots: dict[str, str]) -> int:
    """Print what each title's own `POST.COM` says, and compare the three."""
    seen = []
    for title, root in roots.items():
        if not root or not os.path.isdir(root):
            print(f"{title}: no disks")
            continue
        disk, declared, body = overlay("POST.COM", root)
        table = outcome_table(body)
        branch = flee_branch(body)
        print(f"== {title}   {disk}   POST.COM, "
              f"PRG header says ${declared:04X}")
        if table is None:
            print("   no table points at all three lines")
            continue
        base, lo, hi, index = table
        print(f"   table: lo ${lo + base:04X}  hi ${hi + base:04X}  "
              f"base ${base:04X} (derived, not the header's)")
        for n, name in ((index, "ran"), (index + 1, "lost"),
                        (index + 2, "won")):
            addr = body[lo + n] | body[hi + n] << 8
            end = body.index(b"\x00", addr - base)
            text = body[addr - base:end].decode("latin1")
            print(f"   {n}  ${addr:04X}  {text!r}   ({name})")
        if branch is None:
            print("   no `CMP #$81` arm found")
            continue
        at, msg, row = branch
        print("   $%04X  %s   -> message %d at row %d"
              % (at + base, body[at:at + 11].hex(" "), msg, row))
        seen.append((title, msg == index, row))
    if len(seen) > 1:
        agree = all(same and row == seen[0][2] for _, same, row in seen)
        print("\nAll three print the same table entry on the same row: "
              + ("yes" if agree else "NO"))
    return 0


# -- driving --------------------------------------------------------------


class Log(SC.Log):
    """`tools/savecheck.py`'s log, with a `quiet` flag."""

    def __init__(self, out: pathlib.Path, quiet: bool = False):
        self.quiet = quiet
        super().__init__(out / "run.jsonl")

    def say(self, *a) -> None:
        if not self.quiet:
            super().say(*a)


class Frames:
    """Distinct screens, in order, deduplicated against the one before."""

    def __init__(self):
        self.seen: list[tuple[list[str], int, float]] = []

    def add(self, rows: list[str]) -> bool:
        if self.seen and self.seen[-1][0] == rows:
            self.seen[-1] = (rows, self.seen[-1][1] + 1, self.seen[-1][2])
            return False
        self.seen.append((rows, 1, time.time()))
        return True

    def write(self, path: pathlib.Path, started: float) -> None:
        out = []
        for rows, count, when in self.seen:
            out.append(f"--- +{when - started:6.1f}s, {count} reading(s) ---")
            out += [f"{i:2d} |{r}|" for i, r in enumerate(rows) if r.strip()]
        path.write_text("\n".join(out) + "\n")


def rows_of(s) -> list[str]:
    return [s.row(r).rstrip() for r in range(25)]


def roster_page(sess) -> bytes:
    with sess.mon(5) as m:
        return m.read(ROSTER, ROSTER_BYTES)


def statuses(page: bytes) -> list[int]:
    return [page[i * savegame.ROSTER_STRIDE + STATUS]
            for i in range(savegame.ROSTER_COUNT)]


def hitpoints(page: bytes) -> list[int]:
    out = []
    for i in range(savegame.ROSTER_COUNT):
        at = i * savegame.ROSTER_STRIDE + HP
        out.append(page[at] | page[at + 1] << 8)
    return out


def wound(sess, slots: list[int], to: int) -> None:
    """Set the named slots' current hit points, and touch nothing else."""
    with sess.mon(5) as m:
        for i in slots:
            at = ROSTER + i * savegame.ROSTER_STRIDE + HP
            m.write(at, bytes([to & 0xFF, to >> 8]))


def digest(path: str | os.PathLike) -> str | None:
    p = pathlib.Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


#: The four ways off a combat map, and the key that takes each of them.
#: Diagonals are deliberately not used: a diagonal off a corner is two edges
#: at once and the game's own handler is easier to reason about square by
#: square.
OUTWARD = {(0, -1): "KP_8", (0, 1): "KP_2",
           (-1, 0): "KP_4", (1, 0): "KP_6"}


def edges_of(shape, me) -> list[tuple[int, int]]:
    """The outward directions that leave the map from where `me` stands."""
    out = []
    if me.y == 0:
        out.append((0, -1))
    if me.y == shape.height - 1:
        out.append((0, 1))
    if me.x == 0:
        out.append((-1, 0))
    if me.x == shape.width - 1:
        out.append((1, 0))
    return out


def step_to_edge(battle, me, avoid=()) -> str | None:
    """The key that takes `me` one square nearer the map's edge, or None.

    Breadth-first **from every edge square at once**, which is the same shape
    as `Session.step_towards` and answers a different question: that one walks
    at a combatant, this one walks at the way out.  Rock and every other
    combatant are blocked; the character's own square never is, so a path can
    start.
    """
    shape = battle.shape
    blocked = {(x, y)
               for y in range(shape.height) for x in range(shape.width)
               if battle.square(x, y)}
    for c in battle.combatants:
        if shape.holds(c.x, c.y) and (c.x, c.y) != (me.x, me.y):
            blocked.add((c.x, c.y))
    dist: dict[tuple[int, int], int] = {}
    frontier: list[tuple[int, int]] = []
    for x in range(shape.width):
        for y in (0, shape.height - 1):
            if (x, y) not in blocked:
                dist[(x, y)] = 0
                frontier.append((x, y))
    for y in range(shape.height):
        for x in (0, shape.width - 1):
            if (x, y) not in blocked and (x, y) not in dist:
                dist[(x, y)] = 0
                frontier.append((x, y))
    while frontier:
        nxt = []
        for at in frontier:
            for dx, dy in S.STEP_KEYS:
                sq = (at[0] + dx, at[1] + dy)
                if sq in dist or not shape.holds(*sq) or sq in blocked:
                    continue
                dist[sq] = dist[at] + 1
                nxt.append(sq)
        frontier = nxt
    here = dist.get((me.x, me.y))
    best = None
    for (dx, dy), key in S.STEP_KEYS.items():
        if key in avoid:
            continue
        sq = (me.x + dx, me.y + dy)
        if not shape.holds(*sq) or sq in blocked:
            continue
        d = dist.get(sq)
        if d is None:
            continue
        if best is None or d < best[0]:
            best = (d, key)
    if best is None or (here is not None and best[0] >= here):
        return None
    return best[1]


class Flight:
    """The tactic: walk to the edge of the combat map and step off it.

    One instance per run, so it can keep what it has learnt about a character
    between turns -- which is only ever "this key spent nothing", the same
    thing `melee_turn` keeps within one turn.
    """

    def __init__(self, log: Log):
        self.log = log
        self.attempts = 0
        self.got_away: dict[str, int] = {}
        self.failed: collections.Counter = collections.Counter()

    def band(self, sess) -> str:
        s = sess.screen()
        return "" if s is None else "\n".join(rows_of(s)).upper()

    def answer_flee(self, sess, who: str) -> str:
        """Answer `FLEE: YES NO` with YES and say what the game replied.

        `GOT AWAY` and `FAILED` are `COMBAT`'s own messages 5 and 6, printed
        by `$0B07` from the table at `$0BF6`/`$0C0B`.
        """
        self.attempts += 1
        if not sess.combat_bar("YES", timeout=12):
            self.log.emit("flee", who=who, answered=False)
            return ""
        deadline = time.time() + 8
        while time.time() < deadline:
            text = self.band(sess)
            if GOT_AWAY in text:
                self.got_away[who] = self.got_away.get(who, 0) + 1
                self.log.emit("flee", who=who, result=GOT_AWAY)
                self.log.say(f"    {who}: {GOT_AWAY}")
                return GOT_AWAY
            if FAILED in text:
                self.failed[who] += 1
                self.log.emit("flee", who=who, result=FAILED)
                self.log.say(f"    {who}: {FAILED}")
                return FAILED
            time.sleep(0.3)
        self.log.emit("flee", who=who, result="no message")
        return ""

    def __call__(self, sess, state) -> str:
        b = sess.battle()
        me = sess.acting(b)
        if b is None or me is None:
            return sess.combat_turn()
        who = me.name.strip() or f"#{me.index}"
        index = me.index
        if not sess.combat_bar("MOVE", timeout=15):
            return sess.combat_turn()
        if sess.await_bar((S.BAR_MOVE,), timeout=8) is None:
            return ""
        avoid: set[str] = set()
        for _ in range(24):
            b = sess.battle()
            if b is None:
                break
            me = next((c for c in b.combatants if c.index == index), None)
            if me is None or not me.on_map:
                break
            out = edges_of(b.shape, me)
            if out:
                # Standing on the edge: the step that leaves the map is what
                # puts the game's own `FLEE: YES NO` up (`COMBAT $0E6E`).
                key = OUTWARD[out[0]]
                was = (me.x, me.y)
                self.log.emit("step_off", who=who, at=list(was),
                              key=key, edge=list(out[0]))
                sess.kbd.key(key, 0.15, 0.30)
                bar = sess.await_bar((S.BAR_YESNO,) + S.AFTER_MOVE, timeout=6)
                if bar is not None and bar.kind == S.BAR_YESNO \
                        and "FLEE" in bar.text.upper():
                    if self.answer_flee(sess, who) == GOT_AWAY:
                        return "FLEE"
                    break
                if bar is not None and bar.kind == S.BAR_MOVE:
                    continue            # the step was refused; try another
                break
            key = step_to_edge(b, me, avoid)
            if key is None:
                break
            was, before = (me.x, me.y), sess.combat_state().moves_left
            sess.kbd.key(key, 0.15, 0.30)
            moved, moving = sess.await_step(index, was, before)
            if moving is None:
                return "MOVE"           # the turn is over: spent, or dead
            if not moved:
                avoid.add(key)
        if sess.combat_state().kind == S.BAR_MOVE:
            sess.press_kernal(0x0D)     # back out of move mode
        return sess.combat_turn()


def drive(sess, log: Log, frames: Frames, flight: Flight, args) -> str | None:
    """Drive the fight until one of the three outcome lines shows.

    `Session.fight`'s loop with three differences, all of them the point: it
    records every distinct screen, it answers `FLEE: YES NO` with **YES**
    where `fight` answers every unrecognised yes/no bar with NO, and it
    watches the roster for the first `$86` so the hit points are never touched
    before the game has recorded a flight of its own.
    """
    end = time.time() + args.budget
    outcome = None
    wounded = False
    ran: list[int] = []
    turns = 0
    while time.time() < end:
        turns += 1
        s = sess.screen()
        text = ""
        if s is not None:
            rows = rows_of(s)
            if frames.add(rows):
                log.emit("screen", rows=rows)
            text = "\n".join(rows)
            for name, line in OUTCOME_LINES:
                if line in text:
                    log.emit("outcome_line", outcome=name, line=line)
                    log.say(f"  outcome line on screen: {line!r}")
                    # **Photograph it here, not after the loop.**  The
                    # fleeing arm has no message delay in it at all --
                    # `POST.COM $0930` goes straight on to `$0DF8` -- so the
                    # line is on the screen for well under a second, and the
                    # first run of this tool read the screen 1.1 s apart and
                    # got the frame before and the frame after (`#445`).
                    try:
                        sess.kbd.screenshot(str(log.dir / "outcome-line.png"))
                    except Exception as exc:
                        log.emit("shot_failed", error=repr(exc))
                    return name
        if sess.mode() == S.DUNGEON and S.parse_status(text) is not None:
            # Back in the world with no line seen.  Say so rather than
            # spending the rest of the budget looking for a message that has
            # already been drawn over.
            log.emit("back_in_the_world", outcome=outcome)
            log.say("  back in the world, and no outcome line was read")
            return outcome
        if ran and turns % 20:
            # In the endgame there is nothing left to decide from the roster
            # and everything to lose by reading it: the line this run exists
            # to read is up for a fraction of a second, so the loop spends
            # its time on the screen instead.
            here = []
        else:
            page = roster_page(sess)
            here = statuses(page)
        now = [i for i, v in enumerate(here) if v == RUNNING]
        if here and now != ran:
            ran = now
            log.emit("running", slots=ran, status=here, hp=hitpoints(page))
            log.say("  RUNNING: " + (", ".join(str(i) for i in ran) or "none"))
        if ran and args.wound and not wounded:
            # The game has already written a `$86`, so the outcome byte can
            # no longer be `$80`: `POST.COM $090C` reaches `THE PARTY RUNS
            # AWAY` as soon as nobody is standing.  Everybody still standing
            # is put on one hit point so the monsters can finish the fight,
            # which is `tools/defeatdrive.py`'s patch and nothing more.
            standing = [i for i, v in enumerate(here) if v and not v & 0x80]
            if standing:
                wound(sess, standing, args.hp)
                wounded = True
                log.emit("wounded", slots=standing, hp=args.hp,
                         after_flight_of=ran)
                log.say(f"  wounded {len(standing)} still standing to "
                        f"{args.hp} hit point(s), after the first flight")
        state = sess.combat_state(s)
        if state.kind == S.BAR_COMMAND:
            if wounded:
                sess.combat_turn()      # nothing left to do but let them fall
            else:
                flight(sess, state)
        elif state.kind == S.BAR_YESNO and "FLEE" in state.text.upper():
            flight.answer_flee(sess, "?")
        elif state.kind == S.BAR_YESNO:
            sess.combat_bar("NO", timeout=12.0)
        elif state.kind == S.BAR_CONTINUE:
            # `CONTINUE BATTLE : YES NO`.  `YES`: answering `NO` walks the
            # party out of the fight with everybody still standing, which the
            # engine counts as a win and is not what running away is.
            sess.combat_bar("YES", timeout=12.0)
        elif state.kind == S.BAR_DONE:
            sess.end_turn()
        elif state.kind == S.BAR_MOVE:
            sess.press_kernal(0x0D)
        elif state.kind == S.BAR_DISK:
            sess.handle_prompt(s)
        elif state.kind == S.BAR_PRESS:
            sess.press_kernal(0x0D)
            sess.await_change(state.text, timeout=4.0)
        else:
            sess.idle(args.endgame_poll if ran else args.poll)
    return outcome


def watch_after(sess, log: Log, frames: Frames, seconds: float,
                poll: float) -> list[int]:
    """Sample the screen and the program counter after the outcome line.

    The losing branch ends at `POST.COM $0957`, a jump to itself, and a
    player who loses has to reset the machine (`#128`).  The fleeing branch
    reads `JMP $14AC` instead, so what this is looking for is a program
    counter that **moves** and a game that carries on.
    """
    pcs: list[int] = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            with sess.mon(5) as m:
                pc = m.registers().get(A.pc_register(m))
                mode = m.read(S.MODE, 1)[0]
                result = m.read(RESULT, 1)[0]
        except Exception as exc:
            log.emit("sample_failed", error=repr(exc))
            time.sleep(poll)
            continue
        if pc is not None:
            pcs.append(pc)
        s = sess.screen()
        if s is not None and frames.add(rows_of(s)):
            log.emit("screen", rows=rows_of(s))
        log.emit("after", pc=pc, mode=mode, result=result)
        state = sess.combat_state(s)
        if state.kind == S.BAR_PRESS:
            sess.press_kernal(0x0D)
            sess.await_change(state.text, timeout=4.0)
        elif state.kind in (S.BAR_EXIT, S.BAR_LEAVE):
            sess.combat_bar("LEAVE" if state.kind == S.BAR_LEAVE else "EXIT",
                            timeout=8.0)
        time.sleep(poll)
    return pcs


def run(args) -> int:
    out = pathlib.Path(args.out)
    log = Log(out, args.quiet)
    frames = Frames()
    flight = Flight(log)
    started = time.time()
    slot = S.claim_slot(args.slot, f"fleedrive/{args.save}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    rc, sess = 0, None
    try:
        sess = S.Session(S.stage_disks(slot, pathlib.Path(args.disks),
                                       args.save), slot=slot)
        before_disk = digest(sess.save_disk)
        log.emit("save_disk", when="staged", sha256=before_disk)
        for step, what in ((sess.boot, "boot"),
                           (sess.load_save, "load_save"),
                           (sess.begin_adventuring, "begin_adventuring")):
            if not step():
                raise RuntimeError(f"{what} failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")
        page = roster_page(sess)
        before = statuses(page)
        occupied = [i for i, v in enumerate(before) if v]
        log.emit("roster", when="in the world", status=before,
                 hp=hitpoints(page), occupied=occupied)
        log.say("  before: " + "  ".join(
            f"{i}:{describe(before[i])}" for i in occupied))

        steps = 0
        while not sess.in_combat():
            if steps > args.steps:
                raise RuntimeError("route exhausted with no fight")
            sess.walk_one(args.walk)
            sess.handle_prompt()
            steps += 1
        log.say(f"ambushed after {steps} steps")
        log.emit("fight_start", steps=steps)
        sess.settle(2)
        b = sess.battle()
        if b is not None:
            log.emit("map", width=b.shape.width, height=b.shape.height,
                     party=[[c.index, c.name.strip(), c.x, c.y, c.movement]
                            for c in b.party],
                     enemies=[[c.index, c.x, c.y, c.movement]
                              for c in b.enemies])
            log.say(f"  the map is {b.shape.width} x {b.shape.height}")
            for c in b.party:
                log.say(f"    {c.name.strip():<12} at {c.x},{c.y}  "
                        f"move {c.movement}")

        outcome = drive(sess, log, frames, flight, args)
        log.say(f"fight ended: {outcome or 'no outcome line seen'}")

        page = roster_page(sess)
        after = statuses(page)
        log.emit("roster", when="outcome", status=after, hp=hitpoints(page))
        log.say("  after:  " + "  ".join(
            f"{i}:{describe(after[i])}" for i in occupied))
        with sess.mon(5) as m:
            result = m.read(RESULT, 1)[0]
        log.emit("result", byte=result, attempts=flight.attempts,
                 got_away=flight.got_away, failed=dict(flight.failed))
        log.say(f"  $6DC7 = ${result:02X}   flee attempts "
                f"{flight.attempts}, got away {flight.got_away}, "
                f"failed {dict(flight.failed)}")
        after_disk = digest(sess.save_disk)
        log.emit("save_disk", when="outcome", sha256=after_disk,
                 changed=after_disk != before_disk)
        log.say("  the save disk "
                + ("CHANGED" if after_disk != before_disk
                   else "was not written"))
        if sess.save_disk and pathlib.Path(sess.save_disk).exists():
            shutil.copy(sess.save_disk, out / "save-after.d64")
        frames.write(out / "screens.txt", started)
        try:
            sess.kbd.screenshot(str(out / "outcome.png"))
        except Exception as exc:
            log.emit("shot_failed", error=repr(exc))

        pcs = watch_after(sess, log, frames, args.after, args.poll)
        (out / "after.json").write_text(json.dumps(
            {"samples": len(pcs), "at_spin": sum(1 for p in pcs if p == SPIN),
             "spin": SPIN, "pcs": [f"${p:04X}" for p in pcs]}, indent=1) + "\n")
        log.say(f"  program counter: {sum(1 for p in pcs if p == SPIN)} of "
                f"{len(pcs)} readings at ${SPIN:04X} (the losing spin)")
        frames.write(out / "screens.txt", started)
        log.say(f"  {len(frames.seen)} distinct screens -> "
                + str(out / "screens.txt"))
        last = digest(sess.save_disk)
        log.emit("save_disk", when="end", sha256=last,
                 changed=last != before_disk)
    except Exception as exc:
        import traceback
        try:
            s = sess and sess.screen()
            screen = rows_of(s) if s else []
        except Exception:
            screen = []
        if screen:
            (out / "failed-screen.txt").write_text("\n".join(screen) + "\n")
            log.say("\n".join(ln for ln in screen if ln.strip()))
        log.emit("failed", error=repr(exc), screen=screen,
                 traceback=traceback.format_exc())
        traceback.print_exc()
        rc = 1
    finally:
        try:
            frames.write(out / "screens.txt", started)
        except Exception:
            pass
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                log.emit("cleanup_failed", step=what, error=repr(exc))
                log.say(f"Cleanup failed at {what}: {exc!r}")
                rc = rc or 1
        log.close()
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="what", required=True)

    c = sub.add_parser("code", help="read the three C64 titles' POST.COM")
    c.add_argument("--disks", action="append", default=[], metavar="DIR",
                   help="a directory of disk images; repeatable. The default "
                        "asks tools/gamedisks.py for all three titles")

    d = sub.add_parser("drive", help="drive a fight to a flight")
    d.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to load, inside --disks")
    d.add_argument("--disks", default=str(DISKS),
                   help="where the player's disks are; read, never written")
    d.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    d.add_argument("--budget", type=float, default=900.0,
                   help="seconds to give the fight")
    d.add_argument("--after", type=float, default=60.0,
                   help="seconds to watch after the outcome line appears")
    d.add_argument("--poll", type=float, default=1.0,
                   help="seconds between readings")
    d.add_argument("--endgame-poll", type=float, default=0.12,
                   help="seconds between readings once a character has got "
                        "away, which is the window the outcome line can "
                        "appear in. The fleeing arm has no message delay in "
                        "it, so the line is up for well under a second")
    d.add_argument("--hp", type=int, default=1,
                   help="hit points to leave the characters still standing "
                        "on, once one of them has got away (default 1)")
    d.add_argument("--no-wound", dest="wound", action="store_false",
                   help="never write a hit point: the whole party has to get "
                        "away on its own")
    d.add_argument("--walk", default="I",
                   help="the move to repeat while looking for a fight")
    d.add_argument("--steps", type=int, default=400,
                   help="give up after this many steps with no fight")
    d.add_argument("--out", default=str(ROOT / "work" / "issue445" / "run"),
                   help="run directory")
    d.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.what == "code":
        roots = {}
        if args.disks:
            roots = {os.path.basename(str(x).rstrip("/")): x
                     for x in args.disks}
        else:
            from tools import gamedisks
            for title in TITLES:
                found = gamedisks.find(title)
                roots[title] = str(found) if found else ""
        return read_code(roots)

    SC.catch_signals()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
