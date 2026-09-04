#!/usr/bin/env python3
"""Read the same regions off a C64 Ultimate and off VICE, and diff them.

Every C64 measurement this project has made came out of VICE.  The Ultimate is
an FPGA recreation rather than an emulator, so a reading taken off it is
independent -- and this tool is what makes the two comparable: one manifest of
regions, read the same way on both sides, written to a directory of `.bin`
files with a JSON sidecar, then diffed byte for byte.
`#240 (Drive Pool of Radiance on the C64 Ultimate, so a VICE reading can be
checked against hardware)` is the work; `docs/161-c64-ultimate.md` the write-up.

Three subcommands, and the order matters:

    tools/c64ucompare.py hw   -o work/c64u/240/hw-a     # twice, to find
    tools/c64ucompare.py hw   -o work/c64u/240/hw-b     # what free-runs
    tools/c64ucompare.py vice -o work/c64u/240/vice --save NEWSAVE6.D64
    tools/c64ucompare.py diff work/c64u/240/hw-a work/c64u/240/vice \
        --stable work/c64u/240/hw-b

**Taking the hardware reading twice is not belt and braces, it is the
exclusion list.**  The Ultimate cannot be paused here -- Donald is at the
machine -- so every read happens on a running CPU, and anything free-running
(the raster counter at `$D012`, the CIA timers, a keyboard scan) differs
between two hardware reads seconds apart.  `--stable` feeds those addresses in
as *known* moving parts, measured rather than assumed, so a difference against
VICE that is only a moving counter is never reported as a disagreement.

Two corrections the diff applies before it will call anything a difference:

* **VIC colour registers and colour RAM read back with the unused upper bits
  set on hardware** -- `$D020` gives `F0` where VICE gives `00`.  Those four
  bits are not implemented; `tools/c64u.mask_vic_colour` takes them off.
* **`$D011` bit 7 is raster bit 8** and moves with the beam, so the bit is
  masked out of that one register rather than the register being dropped:
  `party_fix` reads `$D011` for bit 5, and bit 5 is what has to be compared.

Nothing read off either machine is committed: the directories live under
`work/`, which is gitignored.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automap.screen import codes_to_text, screen_address  # noqa: E402
from automap.target import party_fix  # noqa: E402
from goldbox import games  # noqa: E402
from tools.c64u import NO_DEVICE, NotReachable, Ultimate  # noqa: E402

#: One region of the address space, read identically on both machines.
#:
#: `expect` is what this tool claims *before* the reading is taken, so a
#: surprise is visible as a surprise:
#:
#: * "same"    -- the two machines should agree byte for byte in the same
#:               game state, and a difference is a finding;
#: * "state"   -- should agree except where the game state has moved on
#:               (the clock, a counter), so a small count is expected;
#: * "moving"  -- free-running on hardware and stopped under VICE's monitor.
#:               Carried as a control: it proves the reads reached live I/O.
REGIONS = [
    # name, start, length, expect, note
    ("save-image", 0x4900, 0x1C00, "state",
     "the automapper's first poll block, and SAVEDGAME0 verbatim"),
    ("roster", 0x8300, 0x0100, "state",
     "the automapper's second poll block, eight 32-byte roster entries"),
    ("screen", None, 0x03E8, "same",
     "the text screen, at whatever address the VIC is pointed at"),
    ("colour-ram", 0xD800, 0x03E8, "same",
     "colour RAM, four bits wide -- masked before comparing"),
    ("vic", 0xD000, 0x002F, "moving",
     "the VIC registers, raster counter included"),
    ("cia1", 0xDC00, 0x0010, "moving",
     "CIA 1: keyboard scan and timers, a control for a live-I/O read"),
    ("cia2", 0xDD00, 0x0010, "moving",
     "CIA 2: the VIC bank select party_fix reads, plus timers"),
    ("live-position", 0xC040, 0x0020, "state",
     "the engine's live x,y,facing triple at $C04B, in its page"),
    ("dungeon-code", 0x0800, 0x1000, "same",
     "the DUNGEON overlay, resident while the party stands in one"),
    ("items-code", 0x6500, 0x1E00, "same",
     "SECSET at $6500, ITEMNAMES at $6F00, ITEMS at $7B00 -- all resident"),
    ("gdrive", 0xC000, 0x0400, "same",
     "the GDRIVE fast loader, which lives below the screen"),
    ("zero-page", 0x0000, 0x0100, "moving",
     "zero page: KERNAL scratch and the jiffy clock, a control"),
]

#: `$D011` bit 7 is raster bit 8 and moves with the beam.  Masking the bit
#: rather than dropping the register keeps bit 5 -- the bitmap flag
#: `party_fix` actually reads -- inside the comparison.
BIT_MASKS = {0xD011: 0x7F}

#: Addresses whose upper nybble floats high on hardware.  `$D020`-`$D02E` are
#: the border, background and sprite colour registers.
COLOUR_ADDRESSES = set(range(0xD020, 0xD02F)) | set(range(0xD800, 0xDC00))


def mask_byte(addr: int, value: int) -> int:
    if addr in COLOUR_ADDRESSES:
        return value & 0x0F
    return value & BIT_MASKS.get(addr, 0xFF)


# -- taking a reading -------------------------------------------------------


def take(read, out: pathlib.Path, source: str, note: str = "",
         game: games.Game | None = None) -> dict:
    """Read every region through `read(addr, length)` and write it out.

    The screen's address is *computed* on each machine rather than assumed:
    it is `$0400` at boot and `$CC00` once the game is running, and reading
    the address the other machine used would be reading whatever used to be
    the screen.
    """
    game = game or games.DEFAULT
    out.mkdir(parents=True, exist_ok=True)
    screen_at = screen_address(read)
    record = {
        "source": source,
        "taken": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "game": game.key,
        "screen_address": screen_at,
        "note": note,
        "regions": [],
    }
    for name, start, length, expect, why in REGIONS:
        at = screen_at if start is None else start
        data = read(at, length)
        (out / f"{name}.bin").write_bytes(data)
        record["regions"].append({
            "name": name, "start": at, "length": length,
            "expect": expect, "note": why,
        })
    fix = party_fix(read, game)
    record["party_fix"] = None if fix is None else {
        "x": fix.x, "y": fix.y, "facing": fix.facing,
        "source": fix.source, "clock": fix.clock, "outdoors": fix.outdoors,
    }
    record["status_line"] = status_line(read, screen_at)
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def status_line(read, screen_at: int) -> str:
    """Row 14 of the screen as text -- the game's own `E 11:50 10,8`."""
    return codes_to_text(read(screen_at + 14 * 40, 40)).rstrip()


# -- comparing two readings -------------------------------------------------


def load(directory: str | os.PathLike) -> tuple[dict, dict]:
    directory = pathlib.Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    blocks = {r["name"]: (directory / f"{r['name']}.bin").read_bytes()
              for r in manifest["regions"]}
    return manifest, blocks


def differences(a_manifest, a_blocks, b_blocks, name: str) -> list[int]:
    """Offsets where two readings of one region differ, after masking."""
    start = next(r["start"] for r in a_manifest["regions"] if r["name"] == name)
    left, right = a_blocks[name], b_blocks[name]
    return [i for i in range(min(len(left), len(right)))
            if mask_byte(start + i, left[i]) != mask_byte(start + i, right[i])]


def compare(first: str, second: str, stable: str | None = None) -> dict:
    """Diff two readings, with the moving addresses taken out.

    `stable` is a *second* reading from the same machine as `first`, taken
    seconds later.  Anything that differs between those two was moving while
    nothing was happening, so it cannot be evidence about the other machine
    and is excluded by address rather than by guesswork.
    """
    a_manifest, a_blocks = load(first)
    b_manifest, b_blocks = load(second)
    excluded: dict[str, list[int]] = {}
    if stable:
        _, s_blocks = load(stable)
        for r in a_manifest["regions"]:
            excluded[r["name"]] = differences(a_manifest, a_blocks, s_blocks,
                                              r["name"])
    report = {
        "first": {"dir": str(first), **{k: a_manifest[k] for k in
                                        ("source", "taken", "screen_address",
                                         "party_fix", "status_line")}},
        "second": {"dir": str(second), **{k: b_manifest[k] for k in
                                          ("source", "taken", "screen_address",
                                           "party_fix", "status_line")}},
        "stable": str(stable) if stable else None,
        "regions": [],
    }
    for r in a_manifest["regions"]:
        name = r["name"]
        skip = set(excluded.get(name, ()))
        raw = differences(a_manifest, a_blocks, b_blocks, name)
        kept = [i for i in raw if i not in skip]
        report["regions"].append({
            "name": name,
            "start": r["start"],
            "length": r["length"],
            "expect": r["expect"],
            "differences_raw": len(raw),
            "excluded_as_moving": len(skip),
            "differences": len(kept),
            "addresses": [r["start"] + i for i in kept[:64]],
            "bytes": [[r["start"] + i, a_blocks[name][i], b_blocks[name][i]]
                      for i in kept[:64]],
        })
    agreed = sum(r["length"] - r["excluded_as_moving"] for r in report["regions"])
    report["bytes_compared"] = agreed
    report["bytes_differing"] = sum(r["differences"] for r in report["regions"])
    return report


def print_report(report: dict) -> None:
    print(f"{'region':<15}{'start':>8}{'bytes':>8}{'expect':>9}"
          f"{'moving':>8}{'differ':>8}")
    for r in report["regions"]:
        print(f"{r['name']:<15}${r['start']:04X}   {r['length']:>7}"
              f"{r['expect']:>9}{r['excluded_as_moving']:>8}"
              f"{r['differences']:>8}")
    print(f"\n{report['bytes_differing']} bytes differ of "
          f"{report['bytes_compared']} compared "
          f"(moving addresses already excluded)")
    for r in report["regions"]:
        if r["bytes"]:
            print(f"\n{r['name']}:")
            for addr, x, y in r["bytes"]:
                print(f"  ${addr:04X}  first {x:02X}  second {y:02X}")


# -- the two backends -------------------------------------------------------


def hardware(out: pathlib.Path, host: str | None, note: str,
             game: games.Game | None) -> dict:
    dev = Ultimate(host=host)
    if not dev.available():
        raise NotReachable(
            "no C64 Ultimate answered -- check it is powered on, on the "
            "network, and that Web Remote Control is enabled in its menu")
    return take(dev.read_mem, out, "c64-ultimate", note, game)


#: Facing letter to (dx, dy) on the dungeon grid, as the status line reports
#: them.  A guess that is *checked*: `walk_to` records what each forward step
#: actually did and corrects the table from the game rather than trusting it.
STEPS = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}


def walk_to(sess, x: int, y: int, facing: int, clock: int | None = None,
            budget: int = 60, log=print) -> bool:
    """Walk a driven party to one square, facing, and optionally clock.

    The point is to take the *state* difference out of a hardware-versus-VICE
    comparison.  Two machines standing on different squares differ in the
    screen, the colour RAM and every engine variable derived from the square,
    and every one of those has then to be argued away one at a time; two
    machines standing on the same square either agree byte for byte or they do
    not, and that is a much shorter sentence.

    Greedy, and deliberately simple: turn towards the target, step, and if the
    step is refused try the other axis.  It has no map, so a wall it cannot go
    round defeats it -- which is a reported failure rather than a wrong answer,
    because the caller checks the square it actually reached.

    `clock` is the game clock in minutes, which advances with each step: after
    arriving, the party is walked in place (turn, step, step back) until the
    clock matches, because a clock that is fifteen minutes out is fifteen
    minutes of engine state that also differs.
    """
    steps = dict(STEPS)
    for _ in range(budget):
        at = sess.status()
        if at is None:
            log("no status line -- not in the world")
            return False
        if (at.x, at.y) == (x, y):
            break
        dx, dy = x - at.x, y - at.y
        wanted = [f for f, (sx, sy) in steps.items()
                  if (sx and sx * dx > 0) or (sy and sy * dy > 0)]
        if not wanted:
            log(f"at {at.x},{at.y}: no facing moves towards {x},{y}")
            return False
        moved = False
        for want in wanted:
            turn = (want - at.facing) % 4
            sess.walk("K" * turn if turn <= 2 else "J")
            before = sess.status()
            if before is None:
                return False
            if sess.walk_one("I") and (now := sess.status()) is not None \
                    and (now.x, now.y) != (before.x, before.y):
                steps[before.facing] = (now.x - before.x, now.y - before.y)
                moved = True
                break
        if not moved:
            log(f"blocked at {at.x},{at.y} heading for {x},{y}")
            return False
    at = sess.status()
    if at is None or (at.x, at.y) != (x, y):
        log(f"budget spent at {at and (at.x, at.y)}, wanted {x},{y}")
        return False
    log(f"arrived at {at.x},{at.y} facing {at.facing}, clock {at.minutes}")
    # Burning game time is a step out and a step back, so it can leave the
    # party a square away when the way back is refused.  Each round therefore
    # checks the square again rather than assuming it, and gives up on the
    # clock rather than on the square: the square is what the comparison
    # needs and the clock is two bytes of it.
    while clock is not None and at.minutes < clock:
        sess.walk("M")
        if not sess.walk_one("I"):
            log(f"cannot burn time at {at.x},{at.y}; clock stays {at.minutes}")
            break
        sess.walk("M")
        sess.walk_one("I")
        now = sess.status()
        if now is None or (now.x, now.y) != (x, y) or now.minutes <= at.minutes:
            log(f"time-burning wandered to {now and (now.x, now.y)}; stopping")
            break
        at = now
    at = sess.status()
    if at is None or (at.x, at.y) != (x, y):
        log(f"ended at {at and (at.x, at.y)}, wanted {x},{y}")
        return False
    turn = (facing - at.facing) % 4
    sess.walk("K" * turn if turn <= 2 else "J")
    at = sess.status()
    log(f"settled at {at.x},{at.y} facing {at.facing}, clock {at.minutes}")
    return (at.x, at.y, at.facing) == (x, y, facing)


def in_vice(out: pathlib.Path, save: str, note: str,
            game: games.Game | None, keep: bool,
            to: str | None = None, clock: str | None = None,
            move_mode: bool = False) -> dict:
    """Boot Pool of Radiance in a pooled VICE, load `save`, and read.

    Imported here rather than at the top because the hardware side must not
    need a pool slot, a display or an emulator to run at all.
    """
    from tools.c64u import disk_dir
    from tools.session import Session, claim_slot, stage_disks

    slot = claim_slot(note="c64ucompare: the VICE half of #240")
    sess = None
    try:
        disks = disk_dir(game)
        boot = stage_disks(slot, disks, save=save)
        sess = Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("the game did not reach the main menu")
        if not sess.load_save():
            raise RuntimeError("LOAD SAVED GAME did not finish")
        if not sess.begin_adventuring():
            raise RuntimeError("BEGIN ADVENTURING did not reach the world")
        sess.settle(4)
        if to:
            x, y, facing = (int(v) for v in to.split(","))
            minutes = None
            if clock:
                hh, mm = clock.split(":")
                minutes = int(hh) * 60 + int(mm)
            arrived = walk_to(sess, x, y, facing, minutes)
            note = (note + f" | walk_to {to}"
                    + (f" clock {clock}" if clock else "")
                    + (" arrived" if arrived else " NOT arrived")).strip(" |")
        if move_mode:
            # The hardware was left sitting in move mode -- row 24 reads
            # `I,J,K,M, RETURN OR BUTTON` -- and that is part of the state.
            sess.select_bar("MOVE", timeout=8)
            time.sleep(1.0)
        with sess.mon(10) as mon:
            record = take(mon.read, out, "vice",
                          note or f"booted from {save}", game)
            mon.resume()
        return record
    finally:
        if not keep and sess is not None:
            sess.terminate()
        if not keep:
            slot.release()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default=None, help="title key, default Pool of Radiance")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("hw", help="read the regions off the C64 Ultimate")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--host", default=None)
    p.add_argument("--note", default="")

    p = sub.add_parser("vice", help="boot, load a save, and read the same regions")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--save", required=True, help="save disk image, e.g. NEWSAVE6.D64")
    p.add_argument("--note", default="")
    p.add_argument("--keep", action="store_true",
                   help="leave the emulator up afterwards")
    p.add_argument("--to", default=None, metavar="X,Y,FACING",
                   help="walk the party here first, so the two machines are "
                        "in the same state and not merely on the same disk")
    p.add_argument("--clock", default=None, metavar="HH:MM",
                   help="and burn game time until the clock reads this")
    p.add_argument("--move-mode", action="store_true",
                   help="leave the party in move mode, as the hardware was")

    p = sub.add_parser("diff", help="compare two readings")
    p.add_argument("first")
    p.add_argument("second")
    p.add_argument("--stable", default=None,
                   help="a second reading from the same machine as `first`, "
                        "whose differences are the moving addresses")
    p.add_argument("-o", "--out", default=None, help="write the report as JSON")

    args = ap.parse_args(argv)
    game = games.by_key(args.game) if args.game else None
    try:
        if args.cmd == "hw":
            record = hardware(pathlib.Path(args.out), args.host, args.note, game)
        elif args.cmd == "vice":
            record = in_vice(pathlib.Path(args.out), args.save, args.note,
                             game, args.keep, args.to, args.clock,
                             args.move_mode)
        else:
            report = compare(args.first, args.second, args.stable)
            print_report(report)
            if args.out:
                pathlib.Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
            return 0
    except NotReachable as exc:
        print(f"c64ucompare: {exc}", file=sys.stderr)
        return NO_DEVICE
    print(f"{record['source']}: screen at ${record['screen_address']:04X}, "
          f"status line {record['status_line'].strip()!r}")
    print(f"party_fix: {record['party_fix']}")
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
