#!/usr/bin/env python3
"""Every effect id the C64 engine asks a character about, logged from the running game.

`#252 (Does a C64 trait slot apply an item-granted effect id, or only the ones
its own READY routine wrote?)`. `tools/c64/traitquery.py` sweeps the call sites
that name their id with a literal, and `tools/c64/traitdrive.py` counts how often
the trait scan matches. Neither can see an id that arrives in a register from
a table, and the combat engine keeps exactly such tables: `SQRPACI01 $072E`
walks a zero-terminated list of ids under the I/O area at `$DB7A` and asks
`COMBAT $28A4` -- array, **then the ten trait slots** -- about each one,
dispatching the handler at `$DA63`/`$DAEE` (low, high, indexed by id) when
the answer is yes. That is `coab`'s `calc_affect_effect` per check type, and
the literal sweep is blind to all of it.

So this logs the asks themselves. VICE's text monitor has `trace`, a
checkpoint that prints the registers on every hit and lets the machine run,
and the id is in A at `LIBRARY $3FE4`, the entry every ask passes through:

    tools/c64/traitask.py --save PORSAVE13.D64 --item 0=CLOAK OF DISPLACEMENT \\
        --item 1=RING OF FIRE RESISTANCE --ready 0 --fight --out DIR

Phases, each logged to `traits.jsonl` as it happens and each read back off
the machine rather than assumed:

1. **stage** a copy of the save: `--item SLOT=NAME` puts that item template,
   readied, into the party slot's first empty item record; `--stage
   SLOT:INDEX=ID` writes an effect id into a trait slot; `--hp SLOT=N` sets
   the roster's current hit points. Nothing on the player's disks is written.
2. **load**: boot, load, begin adventuring, and read the live trait blocks at
   `$4D00`, which is what says whether the engine re-derives a slot from a
   readied item on load (it does not: `SPELLE04 $ADD4` is reached only from
   `CAMP $10C7`, the READY toggle).
3. **trace**: `tr exec` on `$3FE4` (the ask), `$402D` (fell through to the
   trait scan), `$403C` (a trait slot matched), `$AE0D` (a grant stored into a
   slot), `$AE27` (a revoke cleared one) and `$ADEF` (the block was full).
4. **ready**, with `--ready SLOT`: VIEW > the character, found **by name on
   the panel** (which is in marching order, not slot order) > ITEMS > READY
   on the bar > the staged item's row > Return, `--ready-times` over --
   un-ready, ready, un-ready -- reading the whole 256-byte record and the
   effect array before and after each, so what READY writes is a diff rather
   than a reading.
5. **fight**, with `--fight`: walk until the Slums ambush, read the check
   lists and handler tables out of RAM bank 1 while `COMBAT` is resident,
   drive the fight with `tools/c64/session.py`'s melee tactic reading the
   roster's hit points once a turn, and read the blocks again.
6. **save**, with `--save-game`: ENCAMP > SAVE and copy the disk out.

Everything lands under `--out`. The trace goes to `trace.log` raw, one line
per hit as VICE printed it, and `asks.json` is the parsed sequence: phase,
address, A, X. The disks are copied into the pool slot; the emulator is the
pool's, torn down at the end.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import re
import socket
import sys
import threading
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import items as I  # noqa: E402
from goldbox import traits  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools.c64 import session as S  # noqa: E402
from tools.c64.route_pool import (  # noqa: E402
    EFFECTS,
    ROSTER_HP,
    ROSTER_STRIDE,
    SELECT,
    Caster,
    diff_bytes,
    item_highlight,
    item_rows,
    leave_items,
    live_effects,
    live_record,
    open_items,
    roster_hp,
    sheet_rows,
    toggle_item,
)
from tools.c64.traitdrive import (  # noqa: E402
    SLOT_BASE,
    SLOT_STRIDE,
    Log,
    parse_stage,
    stage_traits,
    trait_blocks,
)
from tools.c64.traitquery import TRAIT_SLOT  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: `SAVEDGAME0` loads at `$4900`; the item area is `$5900 + slot * $100`.
SAVE0_LOAD = 0x4900


#: `LIBRARY`'s predicate, Pool of Radiance (`tools/c64/traitquery.py` derives it).
ASK = 0x3FE4          # STA $6E6E -- every ask passes here, id in A
TRAIT_SCAN = 0x402D   # LDX #$09 -- the array said no, try the ten slots
TRAIT_HIT = 0x403C    # SEC reached only from the trait scan's BEQ
#: `SPELLE04`, resident at `$A700` when an item power is applied.
GRANT_STORE = 0xAE0D  # STA $6BAD,X -- the id goes into a free slot
REVOKE_CLEAR = 0xAE27  # STA $6BAD,X with A = 0 -- the slot is cleared
GRANT_OVERFLOW = 0xADEF  # no free slot: the id goes to the array instead
TRACE = {ASK: "ask", TRAIT_SCAN: "scan", TRAIT_HIT: "hit",
         GRANT_STORE: "grant", REVOKE_CLEAR: "revoke",
         GRANT_OVERFLOW: "overflow"}

#: The combat effect tables, RAM under I/O (`SQRPACI01 $0791`, `$0797`,
#: `$0736`): handler low bytes, handler high bytes, then the check lists.
HANDLER_LO = 0xDA63
HANDLER_HI = 0xDAEE
LISTS = 0xDB7A
TABLES = (HANDLER_LO, 0x200)
NAMESPACE = 139

RE_TRACE = re.compile(
    r"\.C:([0-9a-f]{4}).*?A:([0-9a-f]{2}) X:([0-9a-f]{2}) Y:([0-9a-f]{2})",
    re.I)


# -- staging ----------------------------------------------------------------

def parse_items(text: str) -> list[tuple[int, str]]:
    """`0=CLOAK OF DISPLACEMENT,1=RING OF FIRE RESISTANCE`."""
    out = []
    for part in text.split(","):
        slot, _, name = part.partition("=")
        if not name:
            raise SystemExit("--item wants SLOT=NAME")
        out.append((int(slot, 0), name.strip().upper()))
    return out


def stage_items(path: pathlib.Path, game_disk: str,
                wanted: list[tuple[int, str]],
                repair: bool = False) -> list[dict]:
    """Put a readied item template into a party slot of a **copy** of a save.

    The record is the game's own template for that name, byte for byte, with
    the readied bit set -- so the item the engine sees is one it could have
    sold the party itself.

    With `repair`, `goldbox.items.repair_ring_of_fire_resistance` runs over
    the template first, which is what the character editor writes into a save
    for `#285 (The C64's Ring of Fire Resistance grants nothing, and Wish
    should repair it on conversion and on an editor save)`.  Nothing else in
    the record moves, so a run with the flag and a run without it differ by
    the two bytes under test and nothing more.
    """
    names = I.load_item_names(game_disk)
    templates = I.load_item_templates(game_disk, names)
    image = D64.open(str(path))
    addr, body = split_load_address(image.read_file("SAVEDGAME0"))
    body = bytearray(body)
    written = []
    for slot, name in wanted:
        if name not in templates:
            raise SystemExit(f"no item template called {name!r}")
        raw = bytearray(templates[name])
        if repair:
            raw = bytearray(I.repair_ring_of_fire_resistance(bytes(raw)))
        raw[6] |= I.READIED
        base = I.ITEM_AREA_BASE - SAVE0_LOAD + slot * I.ITEM_BLOCK_STRIDE
        for n in range(I.ITEMS_PER_CHARACTER):
            at = base + n * I.ITEM_SIZE
            if not any(body[at:at + I.ITEM_SIZE]):
                body[at:at + I.ITEM_SIZE] = raw
                written.append({"slot": slot, "item": n, "name": name,
                                "raw": raw.hex(), "effect": raw[14],
                                "power": raw[15]})
                break
        else:
            raise SystemExit(f"slot {slot} has no free item record")
    image.write_file_inplace("SAVEDGAME0",
                             addr.to_bytes(2, "little") + bytes(body))
    image.save(str(path))
    return written


def slot_name(path: pathlib.Path, slot: int) -> str:
    """The name in a save slot's record, as the party panel prints it."""
    image = D64.open(str(path))
    _, body = split_load_address(image.read_file("SAVEDGAME0"))
    at = SLOT_BASE - SAVE0_LOAD + slot * SLOT_STRIDE
    raw = body[at:at + 16]
    return raw.split(b"\0", 1)[0].decode("ascii", "replace").strip()


#: The memorised list at record `0x020`, the spellbook mask at `0x078` and
#: the castable nibbles at `0x0EE` (`goldbox/layout.py`, `goldbox/spells.py`).
MEMORISED = 0x020
SPELLBOOK = 0x078
CASTABLE = 0x0EE


def stage_spells(path: pathlib.Path, slot: int, ids: list[int],
                 castable: int | None) -> dict:
    """Memorise `ids` on a party slot of a **copy** of a save, and make sure
    the spellbook knows each; `castable` sets the first-level magic-user
    nibble so the list is offered in full."""
    image = D64.open(str(path))
    addr, body = split_load_address(image.read_file("SAVEDGAME0"))
    body = bytearray(body)
    base = SLOT_BASE - SAVE0_LOAD + slot * SLOT_STRIDE
    was = bytes(body[base + MEMORISED:base + MEMORISED + 8])
    body[base + MEMORISED:base + MEMORISED + len(ids) + 1] = bytes(ids) + b"\0"
    for i in ids:
        body[base + SPELLBOOK + (i >> 3)] |= 1 << (i & 7)
    if castable is not None:
        body[base + CASTABLE] = (body[base + CASTABLE] & 0xF0) | castable
    image.write_file_inplace("SAVEDGAME0",
                             addr.to_bytes(2, "little") + bytes(body))
    image.save(str(path))
    return {"slot": slot, "memorised_was": was.hex(), "now": ids,
            "castable": castable}


def stage_hp(path: pathlib.Path, wanted: list[tuple[int, int]]) -> list[dict]:
    """Set a party member's current hit points in the `SAVEDGAME1` roster."""
    image = D64.open(str(path))
    addr, body = split_load_address(image.read_file("SAVEDGAME1"))
    body = bytearray(body)
    out = []
    for slot, hp in wanted:
        at = slot * ROSTER_STRIDE + ROSTER_HP
        out.append({"slot": slot, "was": body[at], "now": hp})
        body[at] = hp
    image.write_file_inplace("SAVEDGAME1",
                             addr.to_bytes(2, "little") + bytes(body))
    image.save(str(path))
    return out


# -- the trace --------------------------------------------------------------

class Tracer:
    """VICE text-monitor tracepoints, read on a thread as they print.

    The text monitor takes a command only while the machine is stopped, so
    arming goes inside a binary-monitor block. Hits print to the same socket
    while the machine runs. `Session.attach` also talks on that socket and
    drains it, so the reader pauses around every attach and whatever printed
    during a disk swap is lost -- nothing asks about an effect while a side
    is loading.
    """

    def __init__(self, sess: S.Session, out: pathlib.Path, log: Log):
        self.sess = sess
        self.log = log
        self.file = open(out / "trace.log", "w")
        self.phase = "start"
        self.lines: list[tuple[str, str]] = []
        self.paused = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        inner = sess.attach

        def attach(path, unit=8):
            self.paused.set()
            time.sleep(0.2)
            try:
                inner(path, unit)
            finally:
                self.paused.clear()
        sess.attach = attach

    def arm(self, addresses: dict[int, str]) -> None:
        with self.sess.mon(5):
            for addr in addresses:
                self.sess.text.sendall(f"tr exec ${addr:04x}\n".encode())
                time.sleep(0.15)
            time.sleep(0.5)
            with contextlib.suppress(TimeoutError, socket.timeout):
                echo = self.sess.text.recv(65536).decode("latin-1")
            self.file.write(f"# armed: {echo!r}\n")
            self.file.flush()
        self.thread.start()

    def _reader(self) -> None:
        buf = ""
        sock = self.sess.text
        while not self.stop.is_set():
            if self.paused.is_set():
                time.sleep(0.05)
                continue
            try:
                sock.settimeout(0.3)
                chunk = sock.recv(65536)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("latin-1")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if line:
                    self.lines.append((self.phase, line))
                    self.file.write(f"{self.phase}\t{line}\n")
            self.file.flush()

    def asks(self) -> list[dict]:
        out = []
        for phase, line in self.lines:
            m = RE_TRACE.search(line)
            if not m:
                continue
            pc = int(m.group(1), 16)
            out.append({"phase": phase, "pc": pc, "what": TRACE.get(pc, "?"),
                        "a": int(m.group(2), 16), "x": int(m.group(3), 16),
                        "y": int(m.group(4), 16)})
        return out

    def close(self) -> None:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(2.0)
        self.file.close()


# -- reading the machine ----------------------------------------------------

def live_blocks(m) -> dict[int, list[int]]:
    live = m.read(SLOT_BASE, SLOT_STRIDE * 8)
    return {i: list(live[i * SLOT_STRIDE + TRAIT_SLOT:
                         i * SLOT_STRIDE + TRAIT_SLOT + 10]) for i in range(8)}


def live_tables(m) -> bytes:
    """`$DA63`-`$DC62` out of RAM bank 1, which is the RAM under I/O."""
    return m.read(TABLES[0], TABLES[1], bank=1)


def decode_tables(raw: bytes) -> dict:
    """The handler address per id, and the check lists as `SQRPACI01 $072E`
    counts them: list n is reached by skipping n zero-terminated lists."""
    handlers = {}
    for code in range(1, NAMESPACE):
        lo = raw[HANDLER_LO - TABLES[0] + code]
        hi = raw[HANDLER_HI - TABLES[0] + code]
        handlers[code] = lo | hi << 8
    lists: list[list[int]] = []
    cur: list[int] = []
    at = LISTS - TABLES[0]
    while at < len(raw) and len(lists) < 32:
        b = raw[at]
        at += 1
        if b == 0:
            lists.append(cur)
            cur = []
            if raw[at:at + 2] == b"\0\0":
                break
        else:
            cur.append(b)
    return {"handlers": handlers, "lists": lists}


# -- driving VIEW > ITEMS > READY -------------------------------------------


#: Candidate select keys for a list with a cursor on it, tried in order by
#: `--probe-keys`: XTEST names, or `kernal:XX` for the KERNAL buffer.
PROBE_KEYS = ["KP_0", "KP_Insert", "Return:0.6", "KP_5", "space:0.6",
              "Return", "kernal:0d", "KP_Enter", "kernal:8d", "Right",
              "Control_L", "Alt_L", "kernal:0a", "F1", "F7", "Home"]


def probe_keys(sess: S.Session, log: Log, label: str) -> str | None:
    """With the list's cursor on `label`, try each key until the row flips.

    Nothing in this project had selected a row on the item list before:
    XTEST Return and a KERNAL-buffer Return both left `YES CLOAK` as it was
    in runs 8 and 9, with the trace showing no revoke ran. This asks the game
    which key it wants, one boot instead of one boot a guess.
    """
    s = sess.screen()
    if s is None or item_highlight(s, item_rows(s)) is None:
        sess.select_bar("READY", timeout=10)
        time.sleep(0.8)
    for key in PROBE_KEYS:
        s = sess.screen()
        rows = item_rows(s)
        want = next((r for r in rows if label in s.row(r)), None)
        at = item_highlight(s, rows)
        for _ in range(8):
            if want is None or at is None or at == want:
                break
            sess.kbd.key("Down" if at < want else "Up", 0.15, 0.30)
            s = sess.screen()
            at = item_highlight(s, item_rows(s))
        was = s.row(want) if want is not None else ""
        if key.startswith("kernal:"):
            sess.press_kernal(int(key[7:], 16))
        else:
            name, _, hold = key.partition(":")
            sess.kbd.key(name, float(hold) if hold else 0.15, 0.30)
        time.sleep(1.2)
        s2 = sess.screen()
        rows2 = item_rows(s2) if s2 else []
        flipped = (s2 is not None and want is not None
                   and s2.row(want) != was)
        log.emit("probe", key=key, flipped=flipped,
                 rows={r: [s2.row(r).rstrip(),
                           s2.colours[r * 40:(r + 1) * 40].hex()]
                       for r in list(rows2)[:5] + [24]} if s2 else {})
        log.say(f"  key {key}: {'FLIPPED' if flipped else 'nothing'}; "
                f"row 24 {s2.row(24).strip() if s2 else '?'}")
        if flipped:
            return key
        sess.handle_prompt()
    return None


def report(out: pathlib.Path) -> None:
    """Per phase and id: how often it was asked, how often the ask reached
    the trait scan, and how often a trait slot matched."""
    asks = json.loads((out / "asks.json").read_text())
    per: dict[str, dict[int, list[int]]] = {}
    for i, a in enumerate(asks):
        if a["what"] != "ask":
            continue
        scanned = i + 1 < len(asks) and asks[i + 1]["what"] == "scan"
        hit = scanned and i + 2 < len(asks) and asks[i + 2]["what"] == "hit"
        row = per.setdefault(a["phase"], {}).setdefault(a["a"], [0, 0, 0])
        row[0] += 1
        row[1] += scanned
        row[2] += hit
    for phase, ids in per.items():
        print(f"== {phase}: asked / reached the trait scan / a slot matched")
        for code in sorted(ids):
            n, s, h = ids[code]
            print(f"  {code:3d} {traits.describe(code)[:44]:<44} "
                  f"{n:5d} {s:5d} {h:5d}")


# -- main --------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE13.D64")
    p.add_argument("--repair", action="store_true",
                   help="run the editor's Ring of Fire Resistance repair "
                        "over each staged template first (#285)")
    p.add_argument("--item", default=None, metavar="SLOT=NAME",
                   help="item templates to put in, readied; comma separated")
    p.add_argument("--stage", default=None, metavar="SLOT:INDEX=ID",
                   help="effect ids to write into trait slots")
    p.add_argument("--hp", default=None, metavar="SLOT=N",
                   help="current hit points to set in the roster")
    p.add_argument("--memorise", default=None, metavar="SLOT=ID,ID",
                   help="memorised spell ids to write, replacing the list")
    p.add_argument("--castable", type=int, default=None,
                   help="first-level magic-user slots to allow with --memorise")
    p.add_argument("--cast", default=None, metavar="CASTER:SPELL>TARGET",
                   help="casts to make in the fight, semicolon separated")
    p.add_argument("--ready", type=int, default=None, metavar="SLOT",
                   help="drive READY on that slot's first staged item")
    p.add_argument("--ready-times", type=int, default=3)
    p.add_argument("--probe-keys", action="store_true",
                   help="on the item list, try select keys until a row flips")
    p.add_argument("--joy", action="store_true",
                   help="give VICE a numpad joystick in port 2 (KP_0 fires)")
    p.add_argument("--select", default=None,
                   help="the key that picks a row on a cursor list; default "
                        "KP_0, the numpad joystick's fire, with --joy")
    p.add_argument("--label", default=None,
                   help="how the item list prints the item; default its noun, "
                        "since an unidentified magic item shows only that")
    p.add_argument("--fight", action="store_true",
                   help="walk into the Slums ambush and fight it")
    p.add_argument("--steps", type=int, default=40)
    p.add_argument("--walk", default="I")
    p.add_argument("--budget", type=float, default=420.0)
    p.add_argument("--save-game", action="store_true")
    p.add_argument("--slot", type=int, default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--report", default=None, metavar="DIR",
                   help="print the per-id table for an earlier run and stop")
    args = p.parse_args(argv)
    if args.report:
        report(pathlib.Path(args.report))
        return 0
    if args.select:
        SELECT["key"] = args.select

    found = gamedisks.find("pool-of-radiance")
    disks = pathlib.Path(found) if found else None
    if disks is None or not disks.is_dir():
        raise SystemExit("traitask.py: no Pool of Radiance disks")
    out = pathlib.Path(args.out) if args.out else (
        scratch.scratch_dir("traitask", "ask"))
    log = Log(out, args.quiet)

    staging_dir = out / "disks"
    staging_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        src, link = disks / f"POOL{i}.D64", staging_dir / f"POOL{i}.D64"
        if src.exists() and not link.exists():
            link.symlink_to(src.resolve())
    save = "STAGED.D64"
    src = pathlib.Path(args.save) if os.path.isabs(args.save) \
        else disks / args.save
    S.stage_writable(src, staging_dir / save)
    game_disk = str(disks / "POOL1.D64")

    staged_items: list[dict] = []
    if args.item:
        staged_items = stage_items(staging_dir / save, game_disk,
                                   parse_items(args.item), args.repair)
        log.emit("items", values=staged_items)
        for w in staged_items:
            log.say(f"staged slot {w['slot']} item {w['item']}: {w['name']} "
                    f"+14={w['effect']} +15=${w['power']:02X}")
    if args.stage:
        written = stage_traits(staging_dir / save, parse_stage(args.stage))
        log.emit("staged", values=written)
        for w in written:
            log.say(f"staged slot {w['slot']} trait {w['index']}: "
                    f"{w['was']} -> {w['now']} ({w['name']})")
    if args.hp:
        pairs = [(int(a, 0), int(b, 0)) for a, _, b in
                 (x.partition("=") for x in args.hp.split(","))]
        log.emit("hp", values=stage_hp(staging_dir / save, pairs))
    if args.memorise:
        who, _, ids = args.memorise.partition("=")
        done = stage_spells(staging_dir / save, int(who, 0),
                            [int(i, 0) for i in ids.split(",")], args.castable)
        log.emit("memorised", **done)
        log.say(f"memorised {done['now']} on slot {done['slot']} "
                f"(was {done['memorised_was']})")
    log.emit("blocks_before", blocks=trait_blocks(staging_dir / save))

    slot = S.claim_slot(args.slot, "traitask")
    log.say(f"pool slot {slot.n} display {slot.display}  out {out}")
    sess, tracer, rc = None, None, 0
    try:
        boot_disk = S.stage_disks(slot, staging_dir, save)
        if args.joy:
            # The slot's own vicerc, seeded from Donald's and never his:
            # a numpad joystick in port 2, in case the list reads fire.
            with open(slot.vicerc, "a") as f:
                f.write("JoyDevice2=1\n")
        sess = S.Session(boot_disk, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")

        with sess.mon(8) as m:
            blocks = live_blocks(m)
            effects = live_effects(m)
            tables = live_tables(m)
            hp = roster_hp(m)
            m.resume()
        log.emit("loaded", blocks=blocks, effects=effects.hex(), hp=hp)
        log.say("live trait blocks after load: " + "; ".join(
            f"{i}:{[b for b in v if b]}" for i, v in blocks.items()
            if any(v)) + f"; roster hp {hp[:6]}")
        (out / "tables-world.bin").write_bytes(tables)

        tracer = Tracer(sess, out, log)
        tracer.phase = "world"
        tracer.arm(TRACE)
        log.emit("armed", trace={f"${k:04X}": v for k, v in TRACE.items()})

        if args.ready is not None:
            label = next((w["name"] for w in staged_items
                          if w["slot"] == args.ready), None)
            if label is None:
                raise RuntimeError("--ready wants a slot given to --item")
            tracer.phase = "ready-open"
            who = slot_name(staging_dir / save, args.ready)
            # The list prints an unidentified magic item by its noun alone:
            # the staged CLOAK OF DISPLACEMENT is the row `YES CLOAK`.
            label = args.label or label.split()[0]
            if not open_items(sess, log, who, label, "ready"):
                raise RuntimeError("could not open the item list")
            if args.probe_keys:
                found = probe_keys(sess, log, label)
                log.emit("probed", key=found)
                log.say(f"select key: {found}")
                with sess.mon(8) as m:
                    blocks = live_blocks(m)
                    m.resume()
                log.emit("blocks_after_probe", blocks=blocks)
            for n in range(args.ready_times):
                tracer.phase = f"ready{n}"
                with sess.mon(8) as m:
                    rec0 = live_record(m, args.ready)
                    eff0 = live_effects(m)
                    m.resume()
                ok = toggle_item(sess, log, label, f"ready{n}")
                sess.settle(1)
                with sess.mon(8) as m:
                    rec1 = live_record(m, args.ready)
                    eff1 = live_effects(m)
                    blocks = live_blocks(m)
                    m.resume()
                base = SLOT_BASE + args.ready * SLOT_STRIDE
                rd = diff_bytes(rec0, rec1, base)
                ed = diff_bytes(eff0, eff1, EFFECTS[0])
                log.emit("ready", n=n, pressed=ok, record_diff=rd,
                         effects_diff=ed, blocks=blocks)
                log.say(f"READY #{n}: pressed={ok} record diff {rd} "
                        f"effects diff {ed} block {blocks[args.ready]}")
            tracer.phase = "ready-leave"
            leave_items(sess, log)
            sess.settle(1)

        if args.fight:
            tracer.phase = "walk"
            sess.walk_encounter = S.ENCOUNTER_FIGHT
            steps = 0
            while not sess.in_combat() and steps < args.steps:
                sess.walk_one(args.walk)
                sess.handle_prompt()
                steps += 1
            fighting = sess.in_combat()
            log.emit("walked", steps=steps, in_combat=bool(fighting))
            log.say(f"walked {steps} steps; in combat: {bool(fighting)}")
            if fighting:
                sess.settle(3)
                with sess.mon(8) as m:
                    tables = live_tables(m)
                    hp = roster_hp(m)
                    m.resume()
                (out / "tables-combat.bin").write_bytes(tables)
                decoded = decode_tables(tables)
                (out / "tables.json").write_text(json.dumps(decoded, indent=1))
                log.emit("tables", lists=decoded["lists"])
                for n, lst in enumerate(decoded["lists"]):
                    log.say(f"  list {n}: {lst}")
                log.emit("hp", turn=0, hp=hp)
                log.say(f"  hp at the start of the fight: {hp[:6]}")
                tracer.phase = "fight"
                turn = [0]

                def watched(sess_, state):
                    """The melee tactic, with the roster's hit points read
                    at every command bar -- which is once a turn."""
                    turn[0] += 1
                    with sess_.mon(8) as m:
                        now = roster_hp(m)
                        m.resume()
                    log.emit("hp", turn=turn[0], hp=now)
                    log.say(f"  turn {turn[0]}: hp {now[:6]}")
                    return S.Session.melee_turn(sess_, state)

                tactic = watched
                if args.cast:
                    queue = []
                    for part in args.cast.split(";"):
                        caster, _, rest = part.partition(":")
                        spell, _, target = rest.partition(">")
                        queue.append((caster.strip().upper(),
                                      spell.strip().upper(),
                                      target.strip().upper()))
                    tactic = Caster(log, queue)
                result = sess.fight(budget=args.budget, tactic=tactic)
                log.emit("fought", outcome=result.outcome, turns=result.turns,
                         seconds=round(result.seconds, 1),
                         lines=result.lines)
                log.say(f"fight: {result.outcome} after {result.turns} turns")
                tracer.phase = "after-fight"
                sess.settle(2)
                with sess.mon(8) as m:
                    blocks = live_blocks(m)
                    hp = roster_hp(m)
                    m.resume()
                log.emit("blocks_after_fight", blocks=blocks, hp=hp)
                log.say(f"  hp after the fight: {hp[:6]}")

        tracer.phase = "end"
        if args.save_game:
            if sess.save_game():
                S.copy_closed_disk(pathlib.Path(sess.save_disk), out / "saved.d64")
                log.emit("saved", blocks=trait_blocks(out / "saved.d64"))
                log.say("save written; trait blocks "
                        + str(trait_blocks(out / "saved.d64")))
        s = sess.screen()
        if s is not None:
            (out / "screen.txt").write_text(
                "\n".join(s.row(r) for r in range(25)) + "\n")
    except Exception as exc:
        log.emit("failed", error=repr(exc))
        log.say(f"failed: {exc!r}")
        if sess is not None:
            log.emit("screen", tag="failed", rows=sheet_rows(sess))
        rc = 1
    finally:
        if tracer is not None:
            tracer.close()
            asks = tracer.asks()
            (out / "asks.json").write_text(json.dumps(asks))
            events = [a for a in asks if a["what"] not in ("ask", "scan",
                                                             "hit")]
            log.emit("events", values=events)
            for e in events:
                log.say(f"  {e['phase']}: {e['what']} at ${e['pc']:04X} "
                        f"A={e['a']} X={e['x']}")
            if not args.quiet:
                report(out)
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
