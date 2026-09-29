#!/usr/bin/env python3
"""Drive a C64 Pool of Radiance party into the New Phlan tavern brawl and measure what POST.COM does after it.

The brawl (`ECL00 $A693`) is the one fight that sets both `$6DE3` (no item
experience) and `$6DE6` (mercy), and it puts 13 computer-run allies on the
party's side.  This tool walks a party onto a tavern square, answers the
script's menus until the brawl starts, then plays it to the end while stop
checkpoints inside `POST.COM` read what the game does with the result.

    tavernbrawl.py code [--disks DIR]
    POR_HEADLESS=1 tavernbrawl.py run --save SAVE.D64 --mode win|flee ...
    POR_HEADLESS=1 tavernbrawl.py run --save SAVE.D64 --mode win --budget 3600

The default `--budget` of 900 s is too short for the brawl.  A party turn
took about 19 s of wall time in `648-allycheck` (48 turns in 900 s), because
the 13 allies and the monsters act between them, and five monsters were
still standing when the budget ran out.  3600 s allows about 190 party
turns; that figure is an estimate, not a measured fight length.

`code` reads seven byte runs off the player's own disks and refuses if any
differs from what the driver was written against; `main` runs the same check
before it calls `run`, so a mismatch never claims a slot.  `run` boots an
emulator through the instance pool and writes `run.jsonl`, `readings.json`,
`screens.txt` and PNGs under `--out`.  The save is copied into the slot; the
player's disks are never written.

Exit codes: 0 finished; 1 refused before the trigger (area, arrival, byte
check, arguments); 2 an exception; 3 no brawl within `--max-entries`; 4 the
trap lost the monitor; 5 an unknown screen; 6 the charm slot already had a
charm row; 7 a bad `--stage-item`.  Pass conditions are judged from
`readings.json`, not from the exit code.  `code` itself exits 2 when a disk
file cannot be read.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from dataclasses import dataclass, fields

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.combat import Battle  # noqa: E402
from automap.paths import tool_disks  # noqa: E402
from automap.vice import read_screen  # noqa: E402
from goldbox import savegame  # noqa: E402
from goldbox.items import load_item_templates  # noqa: E402
from tools.c64 import runlog  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.hallmenu import area as resident_area  # noqa: E402
from tools.curse_of_the_azure_bonds.curseflee import _Watched  # noqa: E402
from tools.pool_of_radiance.fleedrive import (  # noqa: E402
    LINKER_BASE,
    MERCY,
    RESULT,
    ROSTER,
    RUNNING,
    Flight,
    Frames,
    Log,
    digest,
    overlay,
    rows_of,
    statuses,
)
from tools.pool_of_radiance.ohlowatch import square_now, step_on  # noqa: E402
from tools.registry import scratch  # noqa: E402
from tools.suite.testpartyrun import to_world  # noqa: E402

STRIDE = savegame.ROSTER_STRIDE     # $20, one combatant block

# -- live memory --------------------------------------------------------------

#: `ECL00 $A764` sets it to 1 for the brawl; `POST.COM $0A48` and `$15B1` read it.
NO_ITEMS = 0x6DE3
#: Non-zero once the party has arrived in New Phlan; the tavern entry needs it.
ARRIVED = 0x4AC5
#: Combatant n's block is at `COMBATANTS + $20 n`: +$00 status, +$01 bit 7 is
#: skipped by `POST.COM`'s count, +$0C the side byte (record `0x10C`), +$19 the
#: 16-bit current hit points.
COMBATANTS = ROSTER                 # $8300
BLOCKS = 64
SIDE, SKIP, HP_AT = 0x0C, 0x01, savegame.ROSTER_HP_CURRENT
#: `LIBRARY $4415`'s working copy of the acting combatant's block, and its index.
WORK, ACTING = 0x6C00, 0x6DB4
#: The effect rows, X = $00-$3F.
CHARM_ID_AT, CHARM_OWNER_AT = 0x4900, 0x4940
CHARM_DURATION_AT, CHARM_MAGNITUDE_AT = 0x4980, 0x4B80
ROWS = 0x40
CHARM = 0x0B
#: Effect magnitude and the side byte each charm form writes.
CHARM_FORMS = {"monster": (0x87, 0xC1), "party": (0x86, 0xC0)}
#: The master record per slot; byte 0 is the name byte the drop loop zeroes,
#: experience is 24-bit little-endian at +$E8, and `0x0B8` bit 7 halves a share.
MASTER, EXPERIENCE, HALF_SHARE = 0x4D00, 0xE8, 0xB8
#: The treasure pile of 16-byte items, its count, and the 24-bit experience
#: accumulator `POST.COM $0D9C` adds into.
PILE, PILE_COUNT, XP_TOTAL = 0x9900, 0x2B28, 0x2B0B
ITEM_BYTES = 16
PLUS_AT = 4
#: `$2B09 + X` standing, `$2B05 + X` running, `$2B07 + X` other down, X = side
#: byte AND $7F; `$2B06` is monsters running.  Read as one block.
COUNTERS_AT, COUNTERS_LEN = 0x2B05, 0x46
STANDING = 0x2B09
#: `COMBAT`'s standing counts, party side and monster side.
TALLIES = 0xA4FD
#: Route 2's roll (1 starts the brawl) and the flee destination index (0-4).
GAMBLE_ROLL, DESTINATION = 0x9803, 0x9802
#: The PC after `DUNGEON $17DA STA ($4C),Y`, the store every script `RANDOM` ends in.
RANDOM_STORE_NEXT = 0x17DC
#: The PC after `POST.COM $091A STA $6DC7`. It is the only store to `$6DC7`
#: found on the eight sides (`$18A7` skips the result), so a hit at any other PC
#: is not the fight's result.
RESULT_STORE_NEXT = 0x091D
#: How many ignored result-byte stores are logged in full; the rest are counted.
IGNORED_LOGGED = 3
#: How long `on_result` waits in all for the `POST.COM` stops, seconds.
POST_WAIT = 60.0
NEW_PHLAN = 0

#: (x, y, facing) placements.  Entering from outside steps east onto (15,14);
#: the two bounce placements step onto the neighbouring tavern squares.
TAVERN_OUTSIDE = (14, 14, 1)
TAVERN_BOUNCE = ((15, 13, 2), (15, 14, 0))
#: 14 entries miss a 28.8% chance under 1% of the time.
MAX_ENTRIES = 14
#: The brawl's 13 allies, logged beside the number found and never asserted.
ALLIES_EXPECTED = 13

# -- `POST.COM` addresses (base $0800) -----------------------------------------

ITEM_TALLY_CALL, ITEM_TALLY_BACK = 0x0A02, 0x0A05
SHARE, EMPTY_PILE, TREASURE = 0x0BD2, 0x0A48, 0x0A52
NO_ITEMS_SKIP, ITEM_LOOP = 0x15B1, 0x15B6
LINE_DRAWN, AFTER_DROP = 0x0930, 0x0933

#: What the driver was written against: (file, run-time address, bytes).
CODE_ROWS = (
    ("POST.COM", 0x091B, "C7 6D"),                         # operand of the result store at $091A
    ("POST.COM", LINE_DRAWN, "20 F8 0D A9 01 4C AC 14"),   # the flee arm: JSR $0DF8, then JMP $14AC
    ("POST.COM", ITEM_TALLY_CALL, "20 A7 15"),             # JSR $15A7, the item tally
    ("POST.COM", EMPTY_PILE, "AD E3 6D F0 05 A9 00 8D 28 2B"),   # $6DE3 empties the pile
    ("POST.COM", 0x0E0C, "A9 00 9D 00 49 F0 10"),          # the charm row is deleted and the slot dropped
    ("POST.COM", NO_ITEMS_SKIP, "AD E3 6D"),               # $6DE3 skips the tally loop
    ("DUNGEON", 0x17DA, "91 4C"),                          # STA ($4C),Y, the RANDOM store
)
#: Printed, not checked.
CODE_SHOWN = (("POST.COM", SHARE), ("POST.COM", ITEM_LOOP))

# -- screens ------------------------------------------------------------------

WORLD_HOLD_READS = 2            # reads of the world bar that mean "no incident"
ENTRY_SECONDS = 120.0
UNKNOWN_READS = 4               # reads of one unrecognised row before giving up


def clock() -> float:
    """`time.monotonic`, in one place so a test can move time."""
    return time.monotonic()


def pause(seconds: float) -> None:
    """`time.sleep`, in one place so a test can skip the waiting."""
    time.sleep(seconds)


class Unreadable(Exception):
    """A disk file the byte check needs could not be read."""


class Exit(Exception):
    """A run that ends with a specific exit code."""

    def __init__(self, code: int, why: str):
        super().__init__(why)
        self.code, self.why = code, why


# -- the byte check, with no emulator -----------------------------------------


def check_code(root: str, load=overlay, out=print) -> int:
    """Print `CODE_ROWS` as `root`'s disks hold them; 1 if any differs, 2 if a file cannot be read, else 0.

    `load(name, root)` returns `(disk, declared address, body)` as
    `fleedrive.overlay` does.  A body is indexed at `address - LINKER_BASE`
    because the PRG header's address is wrong for these overlays.
    """
    bad = 0
    bodies: dict[str, bytes] = {}

    def body_of(name: str) -> bytes:
        if name not in bodies:
            try:
                bodies[name] = load(name, root)[2]
            except (SystemExit, Exception) as exc:
                raise Unreadable(f"cannot read {name} under {root}: {exc}") from exc
        return bodies[name]

    try:
        for name, at, want in CODE_ROWS:
            wanted = bytes.fromhex(want)
            start = at - LINKER_BASE
            got = body_of(name)[start:start + len(wanted)]
            ok = got == wanted
            bad += not ok
            out(f"{name:9} ${at:04X}  {got.hex(' ')}  "
                f"{'ok' if ok else 'DIFFERS, expected ' + wanted.hex(' ')}")
        for name, at in CODE_SHOWN:
            start = at - LINKER_BASE
            out(f"{name:9} ${at:04X}  {body_of(name)[start:start + 8].hex(' ')}  (not checked)")
    except Unreadable as exc:
        out(str(exc))
        return 2
    return 1 if bad else 0


# -- pure readings of the combatant blocks ------------------------------------


def predicted_result(blocks: bytes) -> int:
    """What `POST.COM $0903` makes of the 64 combatant blocks.

    Combatants are counted by X = side byte AND $7F: below $80 is standing,
    `$86` is running, anything else is down.  Status 0 and a set `0x101` bit 7
    are skipped.  Standing at X = 0 is a win (0), raised to 1 when a monster
    ran (X = 1 running); otherwise `$81` if X = 0 ran and `$80` if not.
    """
    standing, running = {}, {}
    for n in range(BLOCKS - 1, -1, -1):
        block = blocks[n * STRIDE:(n + 1) * STRIDE]
        status = block[0]
        if status == 0 or block[SKIP] & 0x80:
            continue
        x = block[SIDE] & 0x7F
        if status < 0x80:
            standing[x] = standing.get(x, 0) + 1
        elif status == RUNNING:
            running[x] = running.get(x, 0) + 1
    if standing.get(0):
        return 1 if running.get(1) else 0
    return 0x81 if running.get(0) else 0x80


def allies_of(blocks: bytes) -> list[int]:
    """Combatants 8 and up that fight for the party and are standing: found by content."""
    return [n for n in range(8, BLOCKS)
            if 0 < blocks[n * STRIDE] < 0x80
            and blocks[n * STRIDE + SIDE] & 0x7F == 0]


def party_side(blocks: bytes) -> frozenset[int]:
    """Every occupied combatant whose side byte is the party's (X = 0), down or not."""
    return frozenset(n for n in range(BLOCKS)
                     if blocks[n * STRIDE] and blocks[n * STRIDE + SIDE] & 0x7F == 0)


def standing_by_side(blocks: bytes) -> dict[int, int]:
    """How many combatants stand on each side X, counted the way `predicted_result` counts."""
    out: dict[int, int] = {}
    for n in range(BLOCKS):
        block = blocks[n * STRIDE:(n + 1) * STRIDE]
        if 0 < block[0] < 0x80 and not block[SKIP] & 0x80:
            x = block[SIDE] & 0x7F
            out[x] = out.get(x, 0) + 1
    return out


@dataclass(frozen=True)
class SidedBattle(Battle):
    """A `Battle` whose enemies leave out combatants on the party's side.

    `automap.combat.Combatant.is_party` follows the side byte, so the brawl's
    13 allies at indices 41-53 are already off `enemies`; this is a second
    guard that also drops the ids found by `party_side`, so a step into an ally
    (which the game answers `ATTACK ALLY: YES NO`) stays unlikely if the reader
    ever regresses.
    """

    friends: frozenset[int] = frozenset()

    @classmethod
    def of(cls, battle: Battle, friends: frozenset[int]) -> "SidedBattle":
        return cls(**{f.name: getattr(battle, f.name) for f in fields(Battle)},
                   friends=friends)

    @property
    def enemies(self):
        return tuple(c for c in self.combatants
                     if not c.is_party and c.index not in self.friends)


def predicted_share(total: int, standing: int, flags: int) -> int | None:
    """One character's share of `total`: divided by `$2B09`, halved by `0x0B8` bit 7."""
    if not standing:
        return None
    share = total // standing
    return share // 2 if flags & 0x80 else share


def le24(data: bytes) -> int:
    return data[0] | data[1] << 8 | data[2] << 16


# -- writes to combatants -----------------------------------------------------


def write_combatant(m, n: int, offset: int, data: bytes, acting: int) -> None:
    """Write into combatant n's block, and into the working copy when n is acting.

    `LIBRARY $319A` copies `$6C00`-`$6C1F` back over the acting combatant's
    block, so a write to the block alone is undone.
    """
    m.write(COMBATANTS + STRIDE * n + offset, bytes(data))
    if acting == n:
        m.write(WORK + offset, bytes(data))


def wound(m, slots, acting: int, hp: int = 1) -> None:
    for n in slots:
        write_combatant(m, n, HP_AT, bytes([hp & 0xFF, hp >> 8]), acting)


def stage_charm(m, slot: int, form: str, acting: int) -> dict:
    """Give SLOT a charm row and the matching side byte; read both back.

    Refuses (`Exit` 6) when a `$0B` row owned by SLOT exists already, and
    otherwise takes the highest free row, as the game's own search does.
    """
    ids = m.read(CHARM_ID_AT, ROWS)
    owners = m.read(CHARM_OWNER_AT, ROWS)
    if any(ids[x] == CHARM and owners[x] == slot for x in range(ROWS)):
        raise Exit(6, f"slot {slot} already has a charm row")
    free = [x for x in range(ROWS - 1, -1, -1) if ids[x] == 0]
    if not free:
        raise Exit(6, "no free effect row")
    x = free[0]
    magnitude, side = CHARM_FORMS[form]
    m.write(CHARM_ID_AT + x, bytes([CHARM]))
    m.write(CHARM_OWNER_AT + x, bytes([slot]))
    m.write(CHARM_DURATION_AT + x, bytes([0]))
    m.write(CHARM_MAGNITUDE_AT + x, bytes([magnitude]))
    write_combatant(m, slot, SIDE, bytes([side]), acting)
    return {"row": x, **charm_state(m, slot, x)}


def charm_state(m, slot: int, row: int) -> dict:
    return {"id": m.peek(CHARM_ID_AT + row), "owner": m.peek(CHARM_OWNER_AT + row),
            "duration": m.peek(CHARM_DURATION_AT + row),
            "magnitude": m.peek(CHARM_MAGNITUDE_AT + row),
            "side": m.peek(COMBATANTS + STRIDE * slot + SIDE)}


def charm_rows(m) -> list[dict]:
    """Every `$0B` row owned by a party slot (0-7)."""
    ids = m.read(CHARM_ID_AT, ROWS)
    owners = m.read(CHARM_OWNER_AT, ROWS)
    return [{"row": x, "owner": owners[x]} for x in range(ROWS)
            if ids[x] == CHARM and owners[x] < 8]


def party_readings(m) -> list[dict]:
    """Status, name byte, experience and `0x0B8` for slots 0-7."""
    out = []
    for slot in range(8):
        base = MASTER + 0x100 * slot
        out.append({"slot": slot, "status": m.peek(COMBATANTS + STRIDE * slot),
                    "name_byte": m.peek(base),
                    "experience": le24(m.read(base + EXPERIENCE, 3)),
                    "flags": m.peek(base + HALF_SHARE)})
    return out


def counters_now(m) -> dict:
    return {"counters": m.read(COUNTERS_AT, COUNTERS_LEN).hex(),
            "tallies": list(m.read(TALLIES, 2)),
            "standing": m.peek(STANDING), "xp_total": le24(m.read(XP_TOTAL, 3))}


# -- the trap -----------------------------------------------------------------


class Stop:
    def __init__(self, name, address, handler, cp, once):
        self.name, self.address, self.handler = name, address, handler
        self.cp, self.once, self.hits = cp, once, 0


class Traps:
    """Stop checkpoints whose hits are handled by the next monitor connection.

    `curseflee.Trap`'s protocol: `sess.mon` is replaced by a wrapper whose
    every connection first asks whether a stop fired, and the machine, stopped
    at that point, is read and resumed on the same connection because VICE
    talks only to the connection that was open when it stopped.
    """

    def __init__(self, sess, log, out: pathlib.Path, args, item: bytes | None = None):
        self.sess, self.log, self.out, self.args, self.item = sess, log, out, args, item
        self.stops: list[Stop] = []
        self.counters: dict[str, int] = {}
        self.readings: dict[str, list] = {}
        self.pending_shots: list[str] = []
        self.degraded = False
        self.result_done = False
        self.ignored_stores = 0
        self.destination_at: float | None = None
        self.tap = None
        self._mon = None
        self._busy = False

    # -- installing -----------------------------------------------------------

    def install(self) -> None:
        self._mon = self.sess.mon
        self.sess.mon = self.mon

    def mon(self, timeout: float = 5.0):
        return _Watched(self, self._mon(timeout))

    def arm(self, name, address, handler, *, store=False, once=True, m=None) -> None:
        """A stop checkpoint at `address` (store or exec), handled by `handler(m)`.

        Once the trap has degraded nothing would handle a hit, so nothing is armed.
        """
        if self.degraded:
            self.log.emit("arm_skipped", name=name, address=address)
            return
        def go(mm):
            cp = mm.checkpoint_set(address, store=store, exec_=not store, stop=True)
            self.stops.append(Stop(name, address, handler, cp, once))
            return cp
        if m is not None:
            go(m)
            return
        with self._mon(10) as mm:
            go(mm)
            mm.resume()

    def arm_counter(self, name, address, m) -> None:
        self.counters[name] = m.checkpoint_set(address, exec_=True, stop=False)

    def drop(self, *names) -> None:
        with self._mon(10) as m:
            # A stop that fired just before this connection opened has not
            # been through `check` (this connection is raw); handle it first.
            self._scan(m, only=names)
            for s in [s for s in self.stops if s.name in names]:
                m.checkpoint_delete(s.cp)
                self.stops.remove(s)
            m.resume()

    # -- handling -------------------------------------------------------------

    def note(self, name: str, **fields) -> None:
        self.readings.setdefault(name, []).append(fields)
        self.log.emit("reading", name=name, **fields)

    def check(self, m) -> None:
        if not self.stops or self._busy or self.degraded:
            return
        self._busy = True
        try:
            fired = self._scan(m)
            if fired:
                m.resume()
        except Exception as exc:
            self._release(m, exc)
        finally:
            self._busy = False

    def _release(self, m, exc) -> None:
        """Give up: nothing is armed, the machine runs, and the run is marked incomplete.

        The machine may be stopped at the hit and no later connection will handle
        another one, so leave no checkpoint behind.
        """
        self.degraded = True
        self.log.emit("trap_failed", error=repr(exc))
        self.log.say(f"  the trap failed: {exc!r}; it makes no further reads")
        for step in (m.checkpoints_clear, m.resume):
            try:
                step()
            except Exception as again:
                self.log.emit("release_failed", error=repr(again))
        self.stops.clear()
        self.counters.clear()

    def _scan(self, m, only=None) -> bool:
        fired = False
        for s in list(self.stops):
            if only is not None and s.name not in only:
                continue
            hits = m.checkpoint_hits(s.cp)
            if hits <= s.hits:
                continue
            s.hits = hits
            fired = True
            if s.once:
                m.checkpoint_delete(s.cp)
                if s in self.stops:
                    self.stops.remove(s)
            s.handler(m)
        return fired

    # -- the trigger phase ----------------------------------------------------

    def arm_trigger(self) -> None:
        self.arm("mercy", MERCY, self.on_mercy, store=True, once=False)
        if self.args.force_roll:
            self.arm("gamble", GAMBLE_ROLL, self.on_gamble, store=True, once=False)

    def on_mercy(self, m) -> None:
        pc = m.registers().get(A.pc_register(m))
        fields = {"no_items": m.peek(NO_ITEMS), "mercy": m.peek(MERCY), "pc": pc}
        if self.args.stage_6de3 is not None:
            m.write(NO_ITEMS, bytes([self.args.stage_6de3]))
            fields["staged"] = self.args.stage_6de3
            fields["read_back"] = m.peek(NO_ITEMS)
        self.note("mercy_store", **fields)

    def on_gamble(self, m) -> None:
        pc = m.registers().get(A.pc_register(m))
        fields = {"value": m.peek(GAMBLE_ROLL), "pc": pc}
        if self.args.force_roll and pc == RANDOM_STORE_NEXT:
            m.write(GAMBLE_ROLL, bytes([1]))
            fields["forced"] = 1
        self.note("gamble_store", **fields)

    def brawl_started(self) -> None:
        self.drop("mercy", "gamble")

    # -- the result -----------------------------------------------------------

    def arm_result(self) -> None:
        self.arm("result", RESULT, self.on_result, store=True, once=False)

    def on_result(self, m) -> None:
        if self.result_done:
            return
        pc = m.registers().get(A.pc_register(m))
        if pc != RESULT_STORE_NEXT:
            self.ignored_stores += 1
            if self.ignored_stores <= IGNORED_LOGGED:
                self.note("result_store_ignored", pc=pc, value=m.peek(RESULT))
            return
        self.result_done = True
        for s in [s for s in self.stops if s.name == "result"]:
            m.checkpoint_delete(s.cp)
            self.stops.remove(s)
        if self.tap is not None:
            self.tap.active = True
        blocks = m.read(COMBATANTS, BLOCKS * STRIDE)
        fields = counters_now(m)
        fields.update(pc=pc, result=m.peek(RESULT), predicted=predicted_result(blocks),
                      no_items=m.peek(NO_ITEMS), mercy=m.peek(MERCY),
                      blocks_standing=[n for n in range(BLOCKS) if 0 < blocks[n * STRIDE] < 0x80])
        self.note("result", **fields)
        self.log.say(f"  result ${fields['result']:02X}, predicted "
                     f"${fields['predicted']:02X}")
        armed = self._arm_post(m)
        self.arm("destination", DESTINATION, self.on_destination, store=True,
                 once=False, m=m)
        deadline = clock() + POST_WAIT
        while armed:
            if clock() >= deadline:
                self.log.emit("stop_timeout", waiting=sorted(armed), why="deadline")
                break
            m.resume()
            pc = m.wait_stopped(15)
            if pc is None:
                self.log.emit("stop_timeout", waiting=sorted(armed), why="no stop")
                break
            hit = [s for s in self.stops if s.address == pc and s.name in armed]
            if not hit:
                self.log.emit("wrong_stop", pc=pc, waiting=sorted(armed))
                self._scan(m, only=("destination",))
                continue
            s = hit[0]
            s.hits = m.checkpoint_hits(s.cp)
            m.checkpoint_delete(s.cp)
            self.stops.remove(s)
            armed.discard(s.name)
            s.handler(m)

    def _arm_post(self, m) -> set[str]:
        """The `POST.COM` stops for this mode, armed only now: `COMBAT` runs at the same addresses."""
        names = set()
        if self.args.mode == "win":
            table = (("item_tally_call", ITEM_TALLY_CALL, self.on_item_tally_call),
                     ("item_tally_back", ITEM_TALLY_BACK, self.on_item_tally_back),
                     ("share", SHARE, self.on_share),
                     ("empty_pile", EMPTY_PILE, self.on_empty_pile),
                     ("treasure", TREASURE, self.on_treasure))
            self.arm_counter("no_items_skip", NO_ITEMS_SKIP, m)
            self.arm_counter("item_loop", ITEM_LOOP, m)
        else:
            table = (("line_drawn", LINE_DRAWN, self.on_line_drawn),
                     ("after_drop", AFTER_DROP, self.on_after_drop))
        for name, address, handler in table:
            self.arm(name, address, handler, m=m)
            names.add(name)
        return names

    def on_item_tally_call(self, m) -> None:
        count = m.peek(PILE_COUNT)
        fields = {"count": count, "xp_total": le24(m.read(XP_TOTAL, 3)),
                  "pile": m.read(PILE, ITEM_BYTES * count).hex() if count else ""}
        if self.item is not None:
            at = PILE + ITEM_BYTES * count
            fields["overwrote"] = m.read(at, ITEM_BYTES).hex()
            m.write(at, self.item)
            m.write(PILE_COUNT, bytes([count + 1]))
            fields["staged_at"] = at
            fields["read_back"] = m.read(at, ITEM_BYTES).hex()
            fields["count_after"] = m.peek(PILE_COUNT)
        self.note("item_tally_call", **fields)

    def on_item_tally_back(self, m) -> None:
        self.note("item_tally_back", xp_total=le24(m.read(XP_TOTAL, 3)))

    def on_share(self, m) -> None:
        self.note("share", standing=m.peek(STANDING),
                  xp_total=le24(m.read(XP_TOTAL, 3)))

    def on_empty_pile(self, m) -> None:
        self.note("empty_pile", count=m.peek(PILE_COUNT), no_items=m.peek(NO_ITEMS))

    def on_treasure(self, m) -> None:
        self.note("treasure", count=m.peek(PILE_COUNT))

    def _line_reading(self, m, name: str) -> None:
        rows = rows_of(read_screen(m))
        self.note(name, rows=rows, party=party_readings(m),
                  charm_rows=charm_rows(m), mercy=m.peek(MERCY),
                  **counters_now(m))
        self.pending_shots.append(name)

    def on_line_drawn(self, m) -> None:
        self._line_reading(m, "line_drawn")

    def on_after_drop(self, m) -> None:
        self._line_reading(m, "after_drop")

    def on_destination(self, m) -> None:
        pc = m.registers().get(A.pc_register(m))
        fields = {"value": m.peek(DESTINATION), "pc": pc}
        if self.args.force_destination is not None and pc == RANDOM_STORE_NEXT:
            m.write(DESTINATION, bytes([self.args.force_destination]))
            fields["forced"] = self.args.force_destination
            self.destination_at = time.monotonic()
            m.checkpoint_delete(next(s.cp for s in self.stops if s.name == "destination"))
            self.stops = [s for s in self.stops if s.name != "destination"]
        self.note("destination_store", **fields)

    # -- after the fight ------------------------------------------------------

    def retire_exec(self) -> None:
        """Read the hit counters and delete every `POST.COM` checkpoint left."""
        try:
            with self._mon(10) as m:
                try:
                    self._scan(m)
                    hits = {name: m.checkpoint_hits(cp) for name, cp in self.counters.items()}
                    self.note("counters", **hits)
                    for cp in self.counters.values():
                        m.checkpoint_delete(cp)
                    self.counters.clear()
                    for s in [s for s in self.stops
                              if s.name not in ("mercy", "gamble", "destination")]:
                        m.checkpoint_delete(s.cp)
                        self.stops.remove(s)
                    m.resume()
                except Exception as exc:
                    self.log.emit("retire_failed", error=repr(exc))
                    self._release(m, exc)
        except Exception as exc:
            self.degraded = True
            self.log.emit("retire_failed", error=repr(exc))

    def flush_shots(self) -> None:
        while self.pending_shots:
            label = self.pending_shots.pop(0)
            try:
                if not self.sess.kbd.screenshot(str(self.out / f"{label}.png")):
                    self.log.emit("shot_failed", label=label, error="no screenshot taken")
            except Exception as exc:
                self.log.emit("shot_failed", label=label, error=repr(exc))

    def finish(self) -> None:
        if self._mon is None:
            return
        self.sess.mon = self._mon
        try:
            with self._mon(10) as m:
                if self.ignored_stores > IGNORED_LOGGED:
                    self.note("result_store_ignored_total", count=self.ignored_stores)
                for name, cp in self.counters.items():
                    try:
                        self.note("counter_at_finish", name=name, hits=m.checkpoint_hits(cp))
                    except Exception as exc:
                        self.log.emit("hits_failed", name=name, error=repr(exc))
                m.checkpoints_clear()
                m.resume()
        except Exception as exc:
            self.log.emit("disarm_failed", error=repr(exc))


class ScreenTap:
    """Every screen read while active goes to `Frames`; each new one gets a PNG."""

    LIMIT = 40

    def __init__(self, sess, log, frames: Frames, out: pathlib.Path, traps: Traps):
        self.sess, self.log, self.frames, self.out, self.traps = sess, log, frames, out, traps
        self.active = False
        self.n = 0
        self._screen = sess.screen
        sess.screen = self.screen
        traps.tap = self

    def screen(self, *a, **k):
        s = self._screen(*a, **k)
        self.traps.flush_shots()
        if self.active and s is not None and self.frames.add(rows_of(s)) \
                and self.n < self.LIMIT:
            self.n += 1
            try:
                self.sess.kbd.screenshot(str(self.out / f"result-{self.n:02d}.png"))
            except Exception as exc:
                self.log.emit("shot_failed", label=f"result-{self.n:02d}", error=repr(exc))
        return s

    def restore(self) -> None:
        self.sess.screen = self._screen


# -- answering the tavern -----------------------------------------------------


def classify(row: str) -> str:
    """The action row 24 calls for: GRAB, NO, RUN, RETURN, MOVE, BLANK or UNKNOWN."""
    words = set(re.findall(r"[A-Z]+", row.upper()))
    if not row.strip():
        return "BLANK"
    if "GRAB" in words:
        return "GRAB"
    if {"YES", "NO"} <= words:
        return "NO"
    if {"STAY", "RUN"} <= words:
        return "RUN"
    if "PRESS" in words or "BUTTON" in words:
        return "RETURN"
    if "MOVE" in words or S.MOVE_SUBBAR in row:
        return "MOVE"
    return "UNKNOWN"


def watch_prompt_up(traps: "Traps", screen) -> bool:
    """True once the result is stored and the city watch's `STAY` `RUN` row is up.

    The world does not come back until that row is answered, so `Session.fight`
    would poll it for the whole budget; `after_fight` answers it.
    """
    return (traps.result_done and screen is not None
            and classify(screen.row(24)) == "RUN")


def answer_until(sess, log, out: pathlib.Path, label: str, *, stop_on_combat: bool,
                 quiet_reads: int = WORLD_HOLD_READS, quiet_seconds: float = 0.0,
                 timeout: float = ENTRY_SECONDS) -> dict:
    """Answer the game by row 24 alone until a brawl, a quiet world bar or the timeout.

    Returns `{"outcome": "brawl" | "quiet" | "timeout", "rows": [...]}`, rows
    being each distinct row 24 met in order.  An unrecognised row held for
    `UNKNOWN_READS` reads is photographed and raises `Exit(5)`.
    """
    rows: list[str] = []
    quiet, blind, unknown, last_unknown = 0, 0, 0, None
    quiet_since = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop_on_combat and sess.in_combat():
            return {"outcome": "brawl", "rows": rows}
        s = sess.screen()
        if s is None:
            # A picture leaves nothing to read; a continue prompt under it
            # still takes a Return.
            blind += 1
            if blind % 8 == 0:
                sess.press_kernal(0x0D)
            pause(0.4)
            continue
        blind = 0
        if sess.handle_prompt(s):
            continue
        row = s.row(24)
        action = classify(row)
        if not rows or rows[-1] != row.strip():
            if row.strip():
                rows.append(row.strip())
        if action == "MOVE":
            quiet += 1
            quiet_since = quiet_since or time.monotonic()
            if quiet >= quiet_reads and time.monotonic() - quiet_since >= quiet_seconds:
                return {"outcome": "quiet", "rows": rows}
            pause(0.5)
            continue
        quiet, quiet_since = 0, None
        if action == "BLANK":
            pause(0.4)
            continue
        if action == "UNKNOWN":
            unknown = unknown + 1 if row == last_unknown else 1
            last_unknown = row
            if unknown >= UNKNOWN_READS:
                try:
                    sess.kbd.screenshot(str(out / f"{label}-unknown.png"))
                except Exception as exc:
                    log.emit("shot_failed", label=f"{label}-unknown", error=repr(exc))
                log.emit("unknown_screen", row24=row)
                raise Exit(5, f"an unrecognised row 24: {row.strip()!r}")
            pause(0.4)
            continue
        unknown, last_unknown = 0, None
        if action == "RETURN":
            sess.press_kernal(0x0D)
            pause(1.0)
        else:
            sess.select_bar(action, timeout=10)
            pause(1.0)
    return {"outcome": "timeout", "rows": rows}


def placement(entry: int, outside_only: bool) -> tuple[int, int, int]:
    """Entry 1 and the fallback step in from outside; later entries bounce between squares."""
    if entry == 1 or outside_only:
        return TAVERN_OUTSIDE
    return TAVERN_BOUNCE[(entry - 2) % 2]


def tavern_seen(rows: list[str]) -> bool:
    """Whether any row met was a tavern screen rather than the world bar."""
    return any(classify(r) not in ("MOVE", "BLANK") for r in rows)


def trigger(sess, traps: Traps, log, out: pathlib.Path, args) -> int:
    """Step onto tavern squares until the brawl starts; return the entry that did."""
    outside_only, quiet_streak = False, 0
    for entry in range(1, args.max_entries + 1):
        where = placement(entry, outside_only)
        label = f"entry-{entry:02d}"
        stepped = step_on(sess, where, out, label)
        met = answer_until(sess, log, out, label, stop_on_combat=True)
        log.emit("entry", entry=entry, placed=list(where), square=stepped.get("square"),
                 rows=met["rows"], outcome=met["outcome"],
                 mercy_stops=len(traps.readings.get("mercy_store", [])))
        if met["outcome"] == "brawl":
            traps.brawl_started()
            return entry
        quiet_streak = 0 if tavern_seen(met["rows"]) else quiet_streak + 1
        if quiet_streak >= 2 and not outside_only:
            outside_only = True
            log.emit("placement_switch", entry=entry, to=list(TAVERN_OUTSIDE))
    raise Exit(3, f"no brawl in {args.max_entries} entries")


# -- the fight ----------------------------------------------------------------


class Tactic:
    """`Session.fight`'s tactic: stage on the first bar, then win or flee."""

    def __init__(self, sess, log, args, flight: Flight | None = None):
        self.sess, self.log, self.args = sess, log, args
        self.flight = flight
        self.calls = 0
        self.charm_row: int | None = None

    def __call__(self, sess, state) -> str:
        self.calls += 1
        with sess.mon(5) as m:
            page = m.read(ROSTER, 0x100)
            acting = m.peek(ACTING)
            if self.calls == 1:
                self.first(m, acting)
            elif self.charm_row is not None and self.calls <= 11:
                self.log.emit("charm_readback", call=self.calls,
                              **charm_state(m, self.args.charm, self.charm_row),
                              tallies=list(m.read(TALLIES, 2)))
            friends = (party_side(m.read(COMBATANTS, BLOCKS * STRIDE))
                       if self.args.mode == "win" else frozenset())
        self.log.emit("party_status", call=self.calls, status=statuses(page), acting=acting)
        if self.args.mode == "win":
            return self.melee(sess, state, friends)
        if acting in (self.args.stay, self.args.charm):
            return sess.combat_turn()
        return self.flight(sess, state)

    def melee(self, sess, state, friends: frozenset[int]) -> str:
        """`Session.melee_turn` against the monster side only; refuse an ally attack.

        `melee_turn` picks its target from `battle().enemies`, so `battle` is
        wrapped for the one call, as a second guard: `is_party` already follows
        the side byte.  `SidedBattle` makes a step into an ally
        unlikely, since `step_towards` treats every square but the target's as
        blocked; it does not rule one out.  If the game asks `ATTACK ALLY`,
        the NO answered here is what keeps the party from striking its own
        side.  The turn is then passed, so the same bar cannot come back to
        the same character with the same target.  If NO cannot be selected,
        the prompt is left for `Session.fight`, whose yes/no branch answers NO.
        """
        own = "battle" in vars(sess)
        real = sess.battle

        def sided():
            b = real()
            return None if b is None else SidedBattle.of(b, friends)

        sess.battle = sided
        try:
            chose = sess.melee_turn(state)
        finally:
            if own:
                sess.battle = real
            else:
                del sess.battle
        s = sess.screen()
        if s is not None and "ATTACK ALLY" in s.row(24):
            answered = bool(sess.combat_bar("NO", timeout=12))
            self.log.emit("attack_ally_refused", call=self.calls, answered=answered)
            if not answered:
                return ""
            if sess.await_bar((S.BAR_MOVE,), timeout=6) is not None:
                sess.press_kernal(0x0D)         # back out of move mode
            return sess.combat_turn()
        return chose

    def first(self, m, acting: int) -> None:
        blocks = m.read(COMBATANTS, BLOCKS * STRIDE)
        allies = allies_of(blocks)
        self.log.emit("allies", found=allies, count=len(allies), expected=ALLIES_EXPECTED)
        if self.args.wound_allies:
            wound(m, allies, acting)
        if self.args.stay is not None:
            wound(m, [self.args.stay], acting)
        if self.args.charm is not None:
            staged = stage_charm(m, self.args.charm, self.args.charm_form, acting)
            self.charm_row = staged["row"]
            self.log.emit("charm_staged", **staged)


# -- the run ------------------------------------------------------------------


def check_args(args) -> str | None:
    """Why these arguments are refused, or None."""
    if args.mode == "flee" and args.stay is None:
        return "--mode flee needs --stay"
    if args.mode == "win":
        for flag, given in (("--charm", args.charm is not None),
                            ("--wound-allies", args.wound_allies),
                            ("--stay", args.stay is not None)):
            if given:
                return f"{flag} is refused with --mode win"
    if args.mode == "flee":
        for flag, value in (("--stage-6de3", args.stage_6de3), ("--stage-item", args.stage_item)):
            if value is not None:
                return f"{flag} is refused with --mode flee"
    for flag, value in (("--charm", args.charm), ("--stay", args.stay)):
        if value is not None and not 0 <= value <= 5:
            return f"{flag} takes a slot from 0 to 5"
    if args.charm is not None and args.charm == args.stay:
        return "--charm and --stay must be different slots"
    if args.force_destination is not None and not 0 <= args.force_destination <= 4:
        return "--force-destination takes 0 to 4"
    return None


def resolve_item(name: str, disks: str) -> bytes:
    """The named item's 16 bytes, refusing (`Exit` 7) one whose plus is not 1-$7F."""
    try:
        templates = load_item_templates(str(pathlib.Path(disks) / "POOL1.D64"))
    except (SystemExit, Exception) as exc:
        raise Exit(7, f"cannot read the item templates under {disks}: {exc}") from exc
    record = templates.get(name)
    if record is None:
        raise Exit(7, f"no item called {name!r}")
    if len(record) != ITEM_BYTES:
        raise Exit(7, f"{name!r} is {len(record)} bytes, not {ITEM_BYTES}")
    if not 1 <= record[PLUS_AT] <= 0x7F:
        raise Exit(7, f"{name!r} has byte +{PLUS_AT} = {record[PLUS_AT]}, not 1 to 127")
    return bytes(record)


def timed_captures(sess, log, out: pathlib.Path, since: float, marks=(5, 60)) -> None:
    """A PNG, row 24 and the square at each mark after the destination was written."""
    for mark in marks:
        wait = since + mark - time.monotonic()
        if wait > 0:
            pause(wait)
        late = max(0.0, -wait)
        try:
            sess.kbd.screenshot(str(out / f"destination-{mark}s.png"))
        except Exception as exc:
            log.emit("shot_failed", label=f"destination-{mark}s", error=repr(exc))
        s = sess.screen()
        log.emit("destination_look", mark=mark, late=round(late, 1),
                 row24=None if s is None else s.row(24).strip(),
                 square=list(square_now(sess)))


#: Row-24 kinds that mean a party member's turn is still in progress.
TURN_BARS = (S.BAR_COMMAND, S.BAR_MOVE, S.BAR_DONE)


def after_fight(sess, traps: Traps, log, out: pathlib.Path, args, before: list) -> None:
    traps.retire_exec()
    with sess.mon(5) as m:
        after = party_readings(m)
    shares = traps.readings.get("share")
    share = shares[-1] if shares else {}
    if not shares:
        why = f"no share reading: POST.COM ${SHARE:04X} never ran"
    elif not share.get("standing"):
        why = f"standing ${STANDING:04X} was 0 at the share"
    else:
        why = None
    for b, a in zip(before, after):
        fields_ = {"predicted_why": why} if why else {}
        log.emit("experience_delta", slot=a["slot"], before=b["experience"],
                 after=a["experience"], delta=a["experience"] - b["experience"],
                 predicted=predicted_share(share.get("xp_total", 0),
                                           share.get("standing", 0), b["flags"]),
                 status=a["status"], name_byte=a["name_byte"], **fields_)
    if sess.in_combat():
        # A fight that ran out its budget is still on a turn's bars, which
        # `answer_until` does not know, and `$C04B`-`$C04D` is the world's
        # square only in the world.  The treasure bars also come up with
        # the mode byte at COMBAT, and `answer_until` walks those.
        s = sess.screen()
        bar = sess.combat_state(s)
        if bar.kind in TURN_BARS:
            log.emit("still_fighting", row24=bar.text, bar=bar.kind)
            return
    met = answer_until(sess, log, out, "after", stop_on_combat=False,
                       quiet_reads=6, quiet_seconds=3.0)
    log.emit("after_fight", outcome=met["outcome"], rows=met["rows"])
    x, y, facing = square_now(sess)
    if x >= 16 or y >= 16:
        log.emit("off_map", square=[x, y, facing])
    else:
        sess.kbd.screenshot(str(out / "panel.png"))
        slot = 0 if args.mode == "win" else args.stay
        lines = sess.character_sheet(slot, shot=str(out / f"sheet{slot}.png"))
        log.emit("sheet", slot=slot, lines=lines)
    if traps.destination_at is not None:
        timed_captures(sess, log, out, traps.destination_at)
        log.emit("forward_step",
                 **step_on(sess, square_now(sess), out, "after-destination"))


#: Seconds `record_stall` gives the screenshot, so a hung `import` cannot hold the slot.
STALL_SHOT_TIMEOUT = 20.0


def fight_end(sess, log, out: pathlib.Path, outcome: str) -> None:
    """A PNG, row 24 and the driver's prediction from the combatant blocks when the fight returns.

    It runs on every outcome, the budget included, because `on_result` only
    predicts when `POST.COM` stores the result.
    """
    shot = out / "fight-end.png"
    try:
        took = bool(sess.kbd.screenshot(str(shot), timeout=STALL_SHOT_TIMEOUT))
    except Exception as exc:
        log.emit("shot_failed", label="fight-end", error=repr(exc))
        took = False
    got: dict = {"outcome": outcome, "shot": str(shot) if took else None}
    try:
        s = sess.screen()
        got["row24"] = None if s is None else s.row(24).strip()
    except Exception as exc:
        got["row24"] = f"unreadable: {exc!r}"
    try:
        with sess.mon(5) as m:
            blocks = m.read(COMBATANTS, BLOCKS * STRIDE)
        got.update(predicted=predicted_result(blocks),
                   standing=standing_by_side(blocks))
    except Exception as exc:
        got.update(predicted=None, predicted_why=f"combatant blocks unreadable: {exc!r}")
    log.emit("fight_end", **got)


def record_stall(sess, log, out: pathlib.Path, step: str) -> None:
    """Log what the machine showed when a setup step gave up, and take a PNG.

    `Session.begin_adventuring` returns False after its wait with nothing on
    the console, so without this a failed step leaves no screen to read.
    Every reading is guarded: this runs on a path that is already failing.
    """
    rows: list[str] | str
    try:
        s = sess.screen()
        rows = ("no readable text screen" if s is None else
                [line.rstrip() for line in s.rows() if line.strip()])
    except Exception as exc:
        rows = f"unreadable: {exc!r}"
    try:
        stall = sess.stall_capture()
    except Exception as exc:
        stall = f"unreadable: {exc!r}"
    shot = out / f"{step}-failed.png"
    try:
        took = bool(sess.kbd.screenshot(str(shot), timeout=STALL_SHOT_TIMEOUT))
    except Exception as exc:
        log.emit("shot_failed", label=f"{step}-failed", error=repr(exc))
        took = False
    log.emit("step_failed", step=step, rows=rows, stall=stall,
             shot=str(shot) if took else None)
    log.say(f"{step} failed; screen: {rows}; {stall}")


def run(args) -> int:
    """Drive one run; every path closes the log."""
    out = scratch.ensure(pathlib.Path(args.out))
    log = Log(out, args.quiet)
    try:
        return _run(args, out, log)
    except Exit as exit_:
        log.emit("refused", why=exit_.why, code=exit_.code)
        log.say(exit_.why)
        return exit_.code
    except Exception as exc:
        import traceback
        log.emit("failed", error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        return 2
    finally:
        log.close()


def _run(args, out: pathlib.Path, log) -> int:
    started = time.time()
    frames = Frames()
    why = check_args(args)
    if why:
        raise Exit(1, why)
    disks = pathlib.Path(args.disks)
    item = resolve_item(args.stage_item, str(disks)) if args.stage_item else None
    save = pathlib.Path(args.save)
    log.emit("save_disk", when="original", sha256=digest(save))
    staging = out / "disks"
    staging.mkdir(parents=True, exist_ok=True)
    S.stage_writable(save, staging / "STAGED.D64")
    for i in range(1, 9):
        src = disks / f"POOL{i}.D64"
        link = staging / f"POOL{i}.D64"
        if src.exists() and not link.exists():
            link.symlink_to(src.resolve())
    slot = S.claim_slot(args.slot, f"tavernbrawl/{save.name}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    rc, sess, traps, tap = 0, None, None, None
    try:
        sess = S.Session(S.stage_disks(slot, staging, "STAGED.D64"), slot=slot)
        for step in ("boot", "load_save", "begin_adventuring"):
            if not getattr(sess, step)():
                record_stall(sess, log, out, step)
                raise RuntimeError(f"{step} failed")
        to_world(sess, log, timeout=60, need_square=True)
        log.emit("save_disk", when="staged", sha256=digest(sess.save_disk))
        area = resident_area(sess, log)
        with sess.mon(5) as m:
            arrived = m.peek(ARRIVED)
            before = party_readings(m)
        log.emit("start", area=area, arrived=arrived, party=before)
        if area != NEW_PHLAN or not arrived:
            log.say(f"area {area}, arrived {arrived}: not a New Phlan save; no step taken")
            return 1

        traps = Traps(sess, log, out, args, item)
        traps.install()
        tap = ScreenTap(sess, log, frames, out, traps)
        traps.arm_trigger()
        entry = trigger(sess, traps, log, out, args)
        log.emit("brawl", entry=entry)
        traps.arm_result()

        flight = Flight(log) if args.mode == "flee" else None
        tactic = Tactic(sess, log, args, flight)
        result = sess.fight(budget=args.budget, tactic=tactic, poll=0.12,
                            stop=lambda _sess, s: watch_prompt_up(traps, s))
        tap.active = False
        log.emit("fight_result", outcome=result.outcome, turns=result.turns,
                 seconds=result.seconds)
        fight_end(sess, log, out, result.outcome)
        traps.flush_shots()
        after_fight(sess, traps, log, out, args, before)
        if traps.degraded:
            rc = 4
    except Exit as exit_:
        log.emit("exit", code=exit_.code, why=exit_.why)
        log.say(exit_.why)
        rc = exit_.code
    except Exception as exc:
        import traceback
        log.emit("failed", error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
        rc = 2
    finally:
        if traps is not None:
            traps.finish()
        if tap is not None:
            tap.restore()
        try:
            frames.write(out / "screens.txt", started)
            (out / "readings.json").write_text(json.dumps(
                traps.readings if traps else {}, indent=1) + "\n")
            log.emit("save_disk", when="end", sha256=digest(sess.save_disk) if sess else None)
            log.emit("save_disk", when="original", sha256=digest(save))
        except Exception as exc:
            log.emit("cleanup_failed", step="records", error=repr(exc))
        try:
            if sess is not None:
                sess.terminate()
            else:
                slot.teardown()
        except Exception as exc:
            log.emit("cleanup_failed", step="terminate", error=repr(exc))
            try:
                slot.teardown()
            except Exception as again:
                log.emit("cleanup_failed", step="teardown", error=repr(again))
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="what", required=True)
    c = sub.add_parser("code", help="check the seven byte runs against the player's disks")
    c.add_argument("--disks", default=None, help="the directory of the player's disks")
    r = sub.add_parser("run", help="drive a party into the brawl")
    r.add_argument("--save", required=True, help="a save disk with the party in New Phlan")
    r.add_argument("--disks", default=None)
    r.add_argument("--slot", type=int, default=None)
    r.add_argument("--out", default=str(scratch.scratch_dir("tavernbrawl", "run")))
    r.add_argument("--quiet", action="store_true")
    r.add_argument("--mode", choices=("win", "flee"), default="win")
    r.add_argument("--budget", type=float, default=900.0)
    r.add_argument("--max-entries", type=int, default=MAX_ENTRIES)
    r.add_argument("--force-roll", action="store_true",
                   help="write 1 to $9803 so route 2 starts the brawl")
    r.add_argument("--stage-6de3", type=int, choices=(0,), default=None,
                   help="write $6DE3 = 0 when the brawl sets it")
    r.add_argument("--stage-item", default=None, metavar="NAME",
                   help="put this item in the treasure pile before the item tally")
    r.add_argument("--stay", type=int, default=None, help="a slot to leave wounded behind")
    r.add_argument("--charm", type=int, default=None, help="a slot to charm before the flight")
    r.add_argument("--charm-form", choices=tuple(CHARM_FORMS), default="monster")
    r.add_argument("--wound-allies", action="store_true")
    r.add_argument("--force-destination", type=int, default=None, metavar="0-4")
    args = p.parse_args(argv)

    found = tool_disks()
    disks = args.disks or (str(found) if found else None)
    if disks is None:
        raise SystemExit("No game disks found. Set $POR_DISKS.")
    if args.what == "code":
        return check_code(disks)
    args.disks = disks
    why = check_args(args)
    if why:
        print(why, file=sys.stderr)
        return 1
    lines: list[str] = []
    checked = check_code(disks, out=lines.append)
    if checked == 2:
        print(f"Cannot check the disks: {lines[-1]}", file=sys.stderr)
        return 1
    if checked:
        print("The disks' POST.COM or DUNGEON differs from what this tool was "
              "written against; run `tavernbrawl.py code`.", file=sys.stderr)
        return 1
    runlog.catch_signals()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
