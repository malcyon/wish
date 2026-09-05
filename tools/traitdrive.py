#!/usr/bin/env python3
"""Put an effect id in a C64 character's trait slot and watch the engine read it.

`#252 (Does a C64 trait slot apply an item-granted effect id, or only the ones
its own READY routine wrote?)`. `tools/traitquery.py` answers the question from
the overlays: the ten trait slots at record `0x0AD` are the **second** place the
engine looks when it asks "has this character got effect N?", and the three
instructions that look there test the value and nothing else -- there is no
byte saying which routine wrote it. This is the other half of that claim,
taken in the running machine.

    tools/traitdrive.py --save PORSAVE13.D64 --stage 0:9=21
    tools/traitdrive.py --save PORSAVE13.D64            # the control

The measurement is a **hit count on one instruction**. `LIBRARY $403C` is the
`SEC` a trait slot's match falls through to, and nothing else reaches it: the
array half of the predicate returns from `$402C`, and a scan that runs out
returns from `$403B`. So a run where `$403C` executes is a run where the engine
matched a byte in the trait block, and the two runs differ by that byte alone.

The checkpoints are armed **not to stop** -- VICE counts the hits and the game
keeps running, so the party can be walked into a fight by the ordinary
`tools/session.py` machinery while the count builds. A stopping breakpoint
freezes the machine between `walk_one`'s screen polls, which is not a run.

Pool of Radiance's dungeon surprise check is what makes the count move without
a spell being cast: `DUNGEON $1D5F` and `$1D77` ask the predicate about 25
(invisible) and 21 (Silence, 15' Radius) once per party member as an encounter
begins. Stage either into a free slot and the fight that starts three steps
into the Slums is enough.

Everything lands under `--out`: `traits.jsonl` one line per event as it
happens, `screen.txt` the screen at the end, and `saved.d64` if `--save-game`
asked for one. Nothing here writes to the player's disks -- the save is copied
into the pool slot's own directory first, exactly as `tools/statusdrive.py`
does it.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import struct
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

from automap.paths import find_disks  # noqa: E402
from goldbox import games, traits  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools import session as S  # noqa: E402
from tools.absrefsweep import files  # noqa: E402
from tools.traitquery import TRAIT_SLOT, find_predicate, staging  # noqa: E402

#: The player's disks: `$POR_DISKS`, then the search every other tool does.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: `SAVEDGAME0` loads at `$4900` and the twelve character slots start at
#: `$4D00`, so a slot's record begins `0x400 + N * 0x100` bytes into the file.
#: `docs/30-savegame-layout.md`.
SAVE0_LOAD = 0x4900
SLOT_BASE = 0x4D00
SLOT_STRIDE = 0x100

#: `$6B00`, the page an overlay copies the working character into. The trait
#: scan reads it and not the save slot, so this is what the predicate saw.
STAGING_PAGE = staging(next(g for g in games.GAMES
                            if g.key == "pool-of-radiance"))

#: Where the surprise check leaves its answers while `DUNGEON` is resident:
#: ranger, not-invisible, moved-silently, silenced. `$1D97` reads the first
#: and `$1D9E` adds the other three. Sampled rather than trusted -- they are
#: only meaningful just after that loop has run.
SURPRISE = 0x6E83


def record_offset(slot: int) -> int:
    return SLOT_BASE - SAVE0_LOAD + slot * SLOT_STRIDE


def parse_stage(text: str) -> list[tuple[int, int, int]]:
    """`0:9=21,3:8=25` -- save slot, trait slot index, effect id."""
    out: list[tuple[int, int, int]] = []
    for item in text.split(","):
        where, _, value = item.partition("=")
        slot, _, index = where.partition(":")
        if not value or not index:
            raise SystemExit("--stage wants slot:index=id, e.g. 0:9=21")
        out.append((int(slot, 0), int(index, 0), int(value, 0)))
    return out


def stage_traits(path: pathlib.Path,
                 wanted: list[tuple[int, int, int]]) -> list[dict]:
    """Write effect ids into trait slots of a **copy** of a save disk.

    Editing an input and then watching the engine compute from it is what
    `.claude/rules/testing.md` calls a valid experiment: the three
    instructions that read the block cannot tell how the byte got there, which
    is the whole question. What this must never be used for is reading a value
    back out and calling it the game's arithmetic.
    """
    image = D64.open(str(path))
    addr, body = split_load_address(image.read_file("SAVEDGAME0"))
    body = bytearray(body)
    written: list[dict] = []
    for slot, index, code in wanted:
        at = record_offset(slot) + TRAIT_SLOT + index
        was = body[at]
        body[at] = code & 0xFF
        written.append({"slot": slot, "index": index, "was": was,
                        "now": body[at], "name": traits.describe(code)})
    image.write_file_inplace("SAVEDGAME0",
                             addr.to_bytes(2, "little") + bytes(body))
    image.save(str(path))
    return written


def trait_blocks(path: pathlib.Path) -> dict[int, list[int]]:
    """The ten trait slots of every occupied save slot, off a `.d64`."""
    image = D64.open(str(path))
    _, body = split_load_address(image.read_file("SAVEDGAME0"))
    out: dict[int, list[int]] = {}
    for slot in range(8):
        at = record_offset(slot)
        record = body[at:at + SLOT_STRIDE]
        if not any(record):
            continue
        out[slot] = list(record[TRAIT_SLOT:TRAIT_SLOT + 10])
    return out


def predicate_for(title: str, disks: str):
    """The three addresses this run watches, read off the title's own disks."""
    game = next(g for g in games.GAMES if g.key == title)
    for _disk, name, body in files(disks, game):
        if name != "LIBRARY":
            continue
        found = find_predicate(name, body, staging(game))
        if found is not None:
            return found
    raise SystemExit("traitdrive.py: no trait predicate in LIBRARY")


def checkpoint_hits(mon, number: int) -> int:
    """How many times a checkpoint has been hit, without stopping the machine.

    `automap/vice.py` sets and deletes checkpoints and does not read one back,
    and it belongs to another part of the tree, so the four bytes are unpacked
    here. VICE's `CHECKPOINT_RESPONSE` is number(4), currently-hit(1),
    start(2), end(2), stop-when-hit(1), enabled(1), operation(1),
    temporary(1), **hit count(4)**, ignore count(4), condition(1), memspace(1).
    """
    body = mon.command(0x11, struct.pack("<I", number))
    return struct.unpack("<I", body[13:17])[0]


class Log:
    """One JSON line per event, written as it happens.

    A run that is killed on its budget never reaches its own summary, so
    anything worth reporting is written at the moment it is measured.
    """

    def __init__(self, out: pathlib.Path, quiet: bool = False):
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "traits.jsonl", "w")
        self.quiet = quiet

    def emit(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()

    def say(self, *a) -> None:
        if not self.quiet:
            print(*a, flush=True)

    def close(self) -> None:
        self.file.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to load, inside --disks")
    p.add_argument("--stage", default=None, metavar="SLOT:INDEX=ID",
                   help="effect ids to write into trait slots of the copy")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's disks are; read, never written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--steps", type=int, default=40,
                   help="give up looking for a fight after this many steps")
    p.add_argument("--walk", default="I", help="the move to repeat")
    p.add_argument("--save-game", action="store_true",
                   help="ENCAMP > SAVE at the end and read the disk back")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = pathlib.Path(args.disks)
    tag = "staged" if args.stage else "control"
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "work" / "issue252" / tag)
    log = Log(out, args.quiet)

    where = gamedisks.find("pool-of-radiance") or str(disks)
    pred = predicate_for("pool-of-radiance", str(where))
    log.emit("predicate", library_base=pred.base, entry=pred.entry,
             array=pred.array, trait_scan=pred.trait_scan)
    log.say(f"LIBRARY at ${pred.base:04X}; predicate ${pred.entry:04X}, "
            f"trait scan ${pred.trait_scan:04X}")
    #: `$403C` is the `SEC` reached only from the trait scan's `BEQ`.
    matched = pred.trait_scan + 0x0F
    entered = pred.trait_scan
    asked = pred.entry

    staging_dir = out / "disks"
    staging_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        src, link = disks / f"POOL{i}.D64", staging_dir / f"POOL{i}.D64"
        if src.exists() and not link.exists():
            link.symlink_to(src.resolve())
    save = "STAGED.D64"
    shutil.copy(disks / args.save if not os.path.isabs(args.save)
                else args.save, staging_dir / save)
    if args.stage:
        written = stage_traits(staging_dir / save, parse_stage(args.stage))
        log.emit("staged", values=written)
        for w in written:
            log.say(f"staged slot {w['slot']} trait {w['index']}: "
                    f"{w['was']} -> {w['now']} ({w['name']})")
    log.emit("blocks_before", blocks=trait_blocks(staging_dir / save))

    slot = S.claim_slot(args.slot, f"traitdrive/{tag}")
    log.say(f"pool slot {slot.n} display {slot.display}  out {out}")
    sess, rc = None, 0
    try:
        sess = S.Session(S.stage_disks(slot, staging_dir, save), slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("load_save failed")
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        log.say(f"in the world at {sess.position()}")

        with sess.mon(8) as m:
            live = m.read(SLOT_BASE, SLOT_STRIDE * 8)
            blocks = {i: list(live[i * SLOT_STRIDE + TRAIT_SLOT:
                                   i * SLOT_STRIDE + TRAIT_SLOT + 10])
                      for i in range(8)}
            log.emit("blocks_live", blocks=blocks)
            log.say("live trait blocks: " + "; ".join(
                f"{i}:{[b for b in v if b]}" for i, v in blocks.items()
                if any(v)))
            cp = {
                "asked": m.checkpoint_set(asked, exec_=True, stop=False),
                "entered": m.checkpoint_set(entered, exec_=True, stop=False),
                "matched": m.checkpoint_set(matched, exec_=True, stop=False),
            }
            m.resume()
        log.emit("armed", checkpoints=cp, asked=asked, entered=entered,
                 matched=matched)

        steps = 0
        while not sess.in_combat() and steps < args.steps:
            sess.walk_one(args.walk)
            sess.handle_prompt()
            steps += 1
            if steps % 5 == 0:
                with sess.mon(8) as m:
                    counts = {k: checkpoint_hits(m, v) for k, v in cp.items()}
                    m.resume()
                log.emit("counts", steps=steps, **counts)
                log.say(f"  step {steps}: " + " ".join(
                    f"{k}={v}" for k, v in counts.items()))
        fighting = sess.in_combat()
        log.emit("walked", steps=steps, in_combat=bool(fighting))
        log.say(f"walked {steps} steps; in combat: {bool(fighting)}")
        if fighting:
            sess.settle(3)

        with sess.mon(8) as m:
            counts = {k: checkpoint_hits(m, v) for k, v in cp.items()}
            surprise = list(m.read(SURPRISE, 4))
            block = list(m.read(STAGING_PAGE + TRAIT_SLOT, 10))
            m.resume()
        log.emit("final", steps=steps, in_combat=bool(fighting),
                 surprise=surprise, staging_block=block, **counts)
        log.say("counts: " + " ".join(f"{k}={v}" for k, v in counts.items()))
        log.say(f"$6E83-$6E86 = {surprise}; staging trait block = {block}")

        s = sess.screen()
        if s is not None:
            (out / "screen.txt").write_text(
                "\n".join(s.row(r) for r in range(25)) + "\n")

        if args.save_game:
            if sess.save_game():
                written = pathlib.Path(sess.save_disk)
                shutil.copy(written, out / "saved.d64")
                log.emit("saved", blocks=trait_blocks(out / "saved.d64"))
                log.say("save written; trait blocks "
                        + str(trait_blocks(out / "saved.d64")))
    except Exception as exc:
        log.emit("failed", error=repr(exc))
        log.say(f"failed: {exc!r}")
        rc = 1
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
