#!/usr/bin/env python3
"""Read the chips while a party stands on Pool of Radiance's travel grid.

Measurement B of `docs/217-drawing-the-wilderness.md`, for
`#11 (Draw the wilderness on the automapper)`.  Everything the wilderness
renderer needs and no file on the disks can say: the three shared multicolour
registers, the character base, how big the game's own travel view is, and
whether the tile attribute's high nibble ever reaches colour RAM.

**Not a new driver.**  It boots one outdoor save the way
`tools/c64outdoor.py` and `tools/outdoorstep.py` do -- pool slot, staged
copies of the player's disks, `Session` -- and then reads memory instead of
writing a save.  The player's disks are read and never written.

## What it reads, and what each reading settles

| bytes | what it settles |
|---|---|
| `$D011`, `$D016`, `$D018`, `$DD00` | multicolour on, and where the VIC is fetching characters from |
| `$D020`-`$D023` | the border and the three colours a multicolour cell shares with the whole screen |
| screen matrix and `$D800` | the pane's size and position, by matching every 3 x 3 block of screen codes against the window's own 120 tiles -- no camera assumption at all -- and whether the attribute's high nibble reaches the chip |
| `$037E` | the camera the combat engine keeps, against the pane the match found |
| `$6E13`-`$6E2B`, `$49C5` | the live loaded-files cache: slot 3 the `SECSET` and slot 4 the `SQRDATA`, PROBABLE until read on the grid |
| `$8C00`-`$8E87` | the resident window against the disk's own `SQRDATA0n` |
| `$033D` after each of the digits `1`-`8` | which value of the heading byte is which compass direction |

    tools/worldregisters.py --disk work/p190/C64OUT1.D64
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import screen as SCR  # noqa: E402
from automap import vice as V  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from goldbox import world as W  # noqa: E402
from tools import session as S  # noqa: E402
from tools import worldtiles as WT  # noqa: E402

#: The eight-way travel heading (`docs/137-wilderness-automap.md`), page 3 and
#: so outside every saved game.
HEADING = 0x033D

#: The combat engine's camera -- the top-left square of the view
#: (`automap/combat.py`).  Read here to see whether the travel view keeps it.
CAMERA = 0x037E

#: The live loaded-files cache, `$6E13,X` (`docs/140-loaded-files-cache.md`).
CACHE = 0x6E13
CACHE_LEN = 0x19

#: Where the window the party is standing on is resident (`docs/113`).
RESIDENT = 0x8C00


def read_all(sess) -> dict:
    """Every reading, in one monitor block, so they are one snapshot."""
    out: dict = {}
    with sess.mon(10) as m:
        banks = V.banked(m)
        if banks is None:
            raise RuntimeError("this VICE will not answer the chips")
        out["vic"] = banks.io(0xD000, 0x30).hex()
        out["d011"] = banks.io(0xD011, 1)[0]
        out["d016"] = banks.io(0xD016, 1)[0]
        out["d018"] = banks.io(0xD018, 1)[0]
        out["dd00"] = banks.io(0xDD00, 1)[0]
        out["border"] = banks.io(0xD020, 1)[0]
        out["shared"] = list(banks.io(0xD021, 3))
        out["screen_address"] = SCR.screen_address(banks)
        out["matrix"] = banks.ram(out["screen_address"], 1000).hex()
        out["colour"] = banks.io(0xD800, 1000).hex()
        out["camera"] = list(banks.ram(CAMERA, 2))
        out["page3"] = banks.ram(0x0330, 0x60).hex()
        out["cache"] = banks.ram(CACHE, CACHE_LEN).hex()
        out["save_cache"] = banks.ram(0x4BC0, CACHE_LEN).hex()
        out["geo"] = banks.ram(0x49C5, 1)[0]
        out["travel"] = list(banks.ram(0x49C3, 2))
        out["indoors"] = banks.ram(0x49E6, 1)[0]
        out["heading"] = banks.ram(HEADING, 1)[0]
        out["resident"] = banks.ram(RESIDENT, W.GRID_SIZE).hex()
    return out


def distance(a: bytes, b: bytes) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def match_windows(resident: bytes, world: W.World) -> list[dict]:
    """How far the resident block is from each disk window."""
    return [{"window": W.WINDOW_NAMES[i],
             "differs": distance(resident, w.to_bytes()[:W.GRID_SIZE])}
            for i, w in enumerate(world.windows)]


def find_pane(matrix: bytes, window: W.Window) -> dict:
    """Where on the screen the map pane is, and which squares are in it.

    Every 3 x 3 block of screen codes is looked up in a table of the window's
    own 120 tiles.  Nothing here assumes a camera, a pane size or a pane
    position: what comes back is whichever screen cells the window's own art
    accounts for.
    """
    by_codes: dict[tuple, list[tuple[int, int]]] = collections.defaultdict(list)
    for y in range(W.ROWS):
        for x in range(W.STRIDE):
            by_codes[tuple(window.tile_at(x, y).screen_codes)].append((x, y))
    hits = {}
    for row in range(SCR.SCREEN_ROWS - 2):
        for col in range(SCR.SCREEN_COLS - 2):
            block = []
            for j in range(3):
                at = (row + j) * SCR.SCREEN_COLS + col
                block.extend(matrix[at + i] for i in range(3))
            found = by_codes.get(tuple(block))
            if found:
                hits[(row, col)] = found
    if not hits:
        return {"tiles": 0}
    rows = sorted({r for r, _ in hits})
    cols = sorted({c for _, c in hits})
    # A tile lands on a 3-cell pitch, so the pane's own origin is the smallest
    # hit whose row and column are both three apart from the next one along.
    grid = {(r, c): v for (r, c), v in hits.items()
            if (r - rows[0]) % 3 == 0 and (c - cols[0]) % 3 == 0}
    across = len({c for _, c in grid})
    down = len({r for r, _ in grid})
    return {
        "tiles": len(grid),
        "origin": [rows[0], cols[0]],
        "across": across,
        "down": down,
        "squares": {f"{r},{c}": v for (r, c), v in sorted(grid.items())},
        "unaligned": len(hits) - len(grid),
    }


def compare_colours(matrix: bytes, colour: bytes, window: W.Window,
                    pane: dict) -> dict:
    """The pane's colour RAM against the window's own attribute bytes."""
    if not pane.get("tiles"):
        return {}
    low_agree = low_differ = high_present = cells = 0
    examples = []
    for key, squares in pane["squares"].items():
        if len(squares) != 1:
            continue                      # ambiguous square: not evidence
        row, col = (int(v) for v in key.split(","))
        x, y = squares[0]
        tile = window.tile_at(x, y)
        for j in range(3):
            for i in range(3):
                at = (row + j) * SCR.SCREEN_COLS + col + i
                want = tile.attributes[j * 3 + i]
                got = colour[at]
                cells += 1
                if got & 0x0F == want & 0x0F:
                    low_agree += 1
                else:
                    low_differ += 1
                    if len(examples) < 8:
                        examples.append({"cell": [row + j, col + i],
                                         "want": want, "got": got})
                if got >> 4:
                    high_present += 1
    return {"cells": cells, "low_agree": low_agree, "low_differ": low_differ,
            "colour_ram_high_nibble_set": high_present, "examples": examples}


def compass(sess, log) -> list[dict]:
    """`$033D` after each of the eight digits, with the square either side."""
    out = []
    for digit in "12345678":
        with sess.mon(5) as m:
            before = list(m.read(0x49C3, 2)) + [m.read(HEADING, 1)[0]]
        moved = sess.walk_outdoors(digit)
        with sess.mon(5) as m:
            after = list(m.read(0x49C3, 2)) + [m.read(HEADING, 1)[0]]
        sess.handle_prompt()
        rec = {"digit": digit, "moved": moved,
               "before": {"x": before[0], "y": before[1], "heading": before[2]},
               "after": {"x": after[0], "y": after[1], "heading": after[2]}}
        out.append(rec)
        log(f"  {digit}: moved={moved} ({before[0]},{before[1]})->"
            f"({after[0]},{after[1]}) heading {before[2]}->{after[2]}")
    return out


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"disk": args.disk}

    def log(line: str) -> None:
        print(line, flush=True)

    slot = S.claim_slot(args.slot, f"worldregisters/{pathlib.Path(args.disk).name}")
    log(f"slot {slot.n} display {slot.display}")
    sess = None
    rc = 0
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks))
        S.stage_writable(args.disk, pathlib.Path(slot.dir) / "SIDE0.D64")
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("the game did not list the save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        if not sess.wait_for_world(args.arrive):
            sess.kbd.screenshot(str(out / "stuck.png"))
            raise RuntimeError(f"no world bar {args.arrive:.0f}s after BEGIN")
        sess.settle(4)
        sess.kbd.screenshot(str(out / "arrived.png"))

        readings = read_all(sess)
        report["readings"] = readings
        log(f"$D011={readings['d011']:02X} $D016={readings['d016']:02X} "
            f"$D018={readings['d018']:02X} $DD00={readings['dd00']:02X}")
        log(f"border={readings['border']} "
            f"$D021-$D023={[f'{c:02X}' for c in readings['shared']]}")
        log(f"screen at ${readings['screen_address']:04X}, "
            f"travel {readings['travel']}, geo {readings['geo']}, "
            f"heading {readings['heading']}, camera {readings['camera']}")
        log(f"cache {readings['cache']}")

        disks = WT.images(pathlib.Path(args.disks))
        world = W.World.from_disks(disks)
        resident = bytes.fromhex(readings["resident"])
        report["windows"] = match_windows(resident, world)
        log(f"resident block against the disks: {report['windows']}")
        index = min(range(3),
                    key=lambda i: report["windows"][i]["differs"])
        window = world.windows[index]
        report["window_index"] = index
        matrix = bytes.fromhex(readings["matrix"])
        colour = bytes.fromhex(readings["colour"])
        report["pane"] = find_pane(matrix, window)
        log(f"pane: {json.dumps(report['pane'])[:600]}")
        report["colours"] = compare_colours(matrix, colour, window,
                                            report["pane"])
        log(f"colour RAM against the tile attributes: {report['colours']}")

        if args.compass:
            report["compass"] = compass(sess, log)
        sess.kbd.screenshot(str(out / "after.png"))
    except Exception as exc:                     # noqa: BLE001 -- reported
        import traceback
        traceback.print_exc()
        report["failed"] = repr(exc)
        try:
            if sess is not None:
                sess.kbd.screenshot(str(out / "failure.png"))
        except Exception:
            pass
        rc = 1
    finally:
        for what, step in (("session close", lambda: sess and sess.terminate()),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:             # noqa: BLE001 -- reported
                print(f"Cleanup failed at {what}: {exc!r}", flush=True)
                rc = rc or 1
    (out / f"{args.name}.json").write_text(json.dumps(report, indent=2))
    print(f"wrote {out / (args.name + '.json')}", flush=True)
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", default="work/p190/C64OUT1.D64",
                   help="an outdoor save disk to boot")
    p.add_argument("--disks", default=str(find_disks() or ""),
                   help="the player's game disks, read only")
    p.add_argument("--out", default="work/issue11", help="where the report goes")
    p.add_argument("--name", default="registers", help="stem for the report")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--arrive", type=float, default=300.0,
                   help="seconds to wait for the world bar")
    p.add_argument("--compass", action="store_true",
                   help="press each of 1-8 and read the heading byte")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

