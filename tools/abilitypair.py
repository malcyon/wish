#!/usr/bin/env python3
"""Separate a later C64 title's two ability arrays and see which the game uses.

`#367 (What is the second ability array at 0x065 for, and which of the two
does the engine treat as current?)`.  Curse of the Azure Bonds and Secret of
the Silver Blades keep the seven ability scores twice -- at record `0x014` and
again at `0x065` -- and every specimen this project holds has the two byte for
byte identical, so no save on any disk can say which the engine reads.  The
way to find out is to **make them disagree and then make the engine use the
score**, which is what `stage` is for; `read` says what a disk holds
afterwards.

    tools/abilitypair.py read WISH-SPEC-curse-h-engine-resave.D64
    tools/abilitypair.py stage --base in.D64 --out work/x.D64 \\
        --set PHILIPPE:str=9/18 --set SHARA:str=18/9
    tools/abilitypair.py refs curse-of-the-azure-bonds

`--set NAME:ability=current/base` writes the first number to `0x014 + i` and
the second to `0x065 + i`.  **Both are inputs and neither proves anything on
its own** (`.claude/rules/testing.md`): the measurement is the sheet the game
draws afterwards and the bytes the engine writes back, never the value read
out of what we wrote.

`refs` is the static half -- how many absolute operands in the title's own
overlays name each array, and in which files.  It is a census of bytes rather
than a proof they are instructions, so read it as a shape: the lopsidedness is
the finding, not any single count.

Nothing here writes to the player's disks.  `stage` copies the image it is
given and writes the copy.
"""
from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import absrefsweep, gamedisks  # noqa: E402

#: The record's two ability arrays, and the seven scores in the order both
#: hold them -- `GEN $1E9C` copies `0x065`-`0x070` straight onto
#: `0x014`-`0x01F`, so index `i` means the same ability in both.
CURRENT = 0x014
BASE = 0x065
ABILITIES = ("str", "int", "wis", "dex", "con", "cha", "exstr")

#: Bytes the engine *derives* from the current array, which is why they are
#: printed beside it.  `LIBRARY $19EE` (`$3FB6` at `LIBRARY`'s own base)
#: computes `0x0E2` from `0x014` and `0x01A`; `COM.PREP $1740` indexes a table
#: with `0x017` and stores `0x0EC`.  `0x0FE` and `0x0FF` are Pool of
#: Radiance's portrait pair, and in Curse they are counters the ability
#: recompute subtracts -- `ECL65 $9166` is `LDA $7C14 / SEC / SBC $7CFF`.
DERIVED = ((0x0E2, "weight_index"), (0x0EC, "dex_index"),
           (0x0FE, "counter_0fe"), (0x0FF, "str_drain"))

#: The five exceptional-strength brackets the weight-allowance routine steps
#: through, read backwards from index 4.  Five numbers off `LIBRARY $3FE3` in
#: Curse of the Azure Bonds and `$3831` in Secret of the Silver Blades, whose
#: routines are otherwise instruction for instruction the same.  Their running
#: totals are 0, 51, 76, 91 and 100, which is AD&D's 18/01-50, 18/51-75,
#: 18/76-90, 18/91-99 and 18/00.
EXCEPTIONAL_BRACKETS = (9, 15, 25, 51, 0)


def weight_index(strength: int, exceptional: int) -> int:
    """The engine's own carrying-capacity index, `LIBRARY $19EE` in Curse.

    Below 18 the score itself; at 18, 18 plus however many of
    :data:`EXCEPTIONAL_BRACKETS` the percentile clears; above 18 the score
    plus five, capped at 30.  It is the byte at record `0x0E2`, and the
    encumbrance routine indexes its carrying-capacity table with it
    (`LIBRARY $102E` in Secret of the Silver Blades).

    **It is computed from `0x014`, never from `0x065`** -- which is why it is
    here: it is a number the engine writes into the record, so it says which
    array fed it rather than which array was drawn on a screen.
    """
    if strength < 18:
        return strength
    if strength > 18:
        return min(strength + 5, 30)
    if not exceptional:
        return 18
    out, left = 18, exceptional
    for bracket in reversed(EXCEPTIONAL_BRACKETS):
        left -= bracket
        if left < 0:
            break
        out += 1
    return out

#: `SAVEAZURE`'s geometry, the same numbers `tools/cursetrain.py` uses and for
#: the same reason: the eight character slots start `0x400` into the payload
#: and each keeps the record's first 256 bytes, which is where both arrays
#: are.
SLOT0 = 0x400
SLOT_SIZE = 0x100
NAMES = 0xC00
NAME_SIZE = 16
SLOTS = 8

#: The saved game each title's engine writes, by the file name on the disk.
#: Only these two keep a second array; Pool of Radiance writes `SAVEDGAME0`
#: and `SAVEDGAME1`, holds seven zeroes at `0x065`, and is refused here rather
#: than read as though it had a pair.
SAVE_FILES = (b"SAVEAZURE", b"SAVEDBASH")


def save_payload(image: bytes) -> tuple[bytes, int, bytes]:
    """The saved game's name, load address and payload out of a `.d64`."""
    disk = D64(image)
    have = {e.name.decode("latin1").rstrip("\xa0 ") for e in
            disk.iter_directory()}
    for name in SAVE_FILES:
        if name.decode("latin1") in have:
            raw = disk.read_file(name)
            return name, raw[0] | raw[1] << 8, raw[2:]
    raise SystemExit(f"no saved game on this disk; it holds {sorted(have)}")


def slot_names(payload: bytes) -> list[str]:
    out = []
    for n in range(SLOTS):
        blob = payload[NAMES + n * NAME_SIZE:NAMES + (n + 1) * NAME_SIZE]
        out.append(blob.split(b"\x00")[0].decode("latin1").strip())
    return out


def arrays(payload: bytes, n: int) -> tuple[list[int], list[int]]:
    """Slot `n`'s current and base arrays, seven bytes each."""
    base = SLOT0 + n * SLOT_SIZE
    return (list(payload[base + CURRENT:base + CURRENT + 7]),
            list(payload[base + BASE:base + BASE + 7]))


def read(args) -> int:
    image = pathlib.Path(args.disk).read_bytes()
    name, _, payload = save_payload(image)
    print(f"{pathlib.Path(args.disk).name}: {name.decode('latin1')}")
    for n, who in enumerate(slot_names(payload)):
        if not who:
            continue
        cur, bas = arrays(payload, n)
        slot = SLOT0 + n * SLOT_SIZE
        derived = "  ".join(
            f"{label} {payload[slot + off]}" for off, label in DERIVED)
        from_current = weight_index(cur[0], cur[6])
        from_base = weight_index(bas[0], bas[6])
        stored = payload[slot + 0x0E2]
        print(f"  {n} {who:10s} current @0x014 "
              + " ".join(f"{a}={v:3d}" for a, v in zip(ABILITIES, cur)))
        print(f"     {'':10s} base    @0x065 "
              + " ".join(f"{a}={v:3d}" for a, v in zip(ABILITIES, bas))
              + ("" if cur == bas else "   <-- the two disagree"))
        print(f"     {'':10s} derived {derived}")
        says = ("says nothing: the two arrays agree"
                if from_current == from_base else
                "names 0x014" if stored == from_current else
                "names 0x065" if stored == from_base else
                "matches neither array")
        print(f"     {'':10s} 0x0E2 {stored} against {from_current} from "
              f"0x014 and {from_base} from 0x065 -- {says}")
    return 0


def stage(args) -> int:
    image = pathlib.Path(args.base).read_bytes()
    name, load, payload = save_payload(image)
    names = slot_names(payload)
    upper = [x.upper() for x in names]
    body = bytearray(payload)
    for spec in args.set:
        who, _, fields = spec.partition(":")
        if who.upper() not in upper:
            raise SystemExit(f"no slot is called {who!r}; the disk has "
                             f"{[n for n in names if n]}")
        n = upper.index(who.upper())
        slot = SLOT0 + n * SLOT_SIZE
        for pair in fields.split(","):
            key, _, val = pair.partition("=")
            if key not in ABILITIES:
                raise SystemExit(f"unknown ability {key!r}; use one of "
                                 f"{', '.join(ABILITIES)}")
            first, _, second = val.partition("/")
            i = ABILITIES.index(key)
            if first:
                body[slot + CURRENT + i] = int(first) & 0xFF
            if second:
                body[slot + BASE + i] = int(second) & 0xFF
        cur, bas = arrays(bytes(body), n)
        print(f"  {names[n]:10s} slot {n}: current "
              + " ".join(str(v) for v in cur) + " | base "
              + " ".join(str(v) for v in bas))
    disk = D64(image)
    disk.write_file_inplace(name, load.to_bytes(2, "little") + bytes(body))
    pathlib.Path(args.out).write_bytes(disk.to_bytes())
    if args.repair:
        from tools.curseload import close_splat  # noqa: PLC0415

        for entry in close_splat(args.out):
            label = entry["name"]
            label = label.decode("latin1") if isinstance(label, bytes) \
                else label
            print(f"closed {label}: type {entry['type_was']} -> "
                  f"{entry['type_now']}, {entry['blocks_now']} blocks")
    print(f"wrote {args.out}")
    return 0


def census(root: str, game, lo: int, hi: int):
    """`(total, per-file counts, per-address counts)` for one window."""
    _, hits = absrefsweep.sweep(root, game, lo, hi)
    code = [h for h in hits if not absrefsweep.is_art(h.file)
            and not absrefsweep.is_script(h.file)]
    per_file: collections.Counter = collections.Counter(h.file for h in code)
    per_addr: collections.Counter = collections.Counter(
        h.address for h in code)
    return len(code), per_file, per_addr


def refs(args) -> int:
    game = next((g for g in games.GAMES
                 if g.key == args.title or g.title == args.title), None)
    if game is None:
        raise SystemExit(f"No such title: {args.title}")
    root = args.disks or str(gamedisks.find(game.key) or "")
    if not root or not os.path.isdir(root):
        raise SystemExit(f"No disks for {game.title}; pass --disks.")
    where = args.at
    print(f"{game.title}: the record stages at ${where:04X}")
    for label, off in (("current @0x014", CURRENT), ("base    @0x065", BASE)):
        lo = where + off
        total, per_file, per_addr = census(root, game, lo, lo + 6)
        print(f"  {label}  ${lo:04X}-${lo + 6:04X}  {total} references in "
              f"code files")
        print("      by file:    " + ", ".join(
            f"{f} {c}" for f, c in per_file.most_common()))
        print("      by address: " + ", ".join(
            f"${a:04X} {c}" for a, c in sorted(per_addr.items())))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    rd = sub.add_parser("read", help="print both arrays for every character")
    rd.add_argument("disk")
    rd.set_defaults(func=read)

    st = sub.add_parser("stage", help="write the two arrays apart")
    st.add_argument("--base", required=True, help="the save disk to copy")
    st.add_argument("--out", required=True, help="where the copy goes")
    st.add_argument("--set", action="append", default=[], metavar="SPEC",
                    help="NAME:ability=current/base, repeatable")
    st.add_argument("--repair", action="store_true",
                    help="close a saved game the drive never finished "
                         "writing, as tools/cursetrain.py stage does")
    st.set_defaults(func=stage)

    rf = sub.add_parser("refs", help="census both arrays across a title")
    rf.add_argument("title")
    rf.add_argument("--disks", help="where that title's sides are")
    rf.add_argument("--at", type=lambda s: int(s, 16), default=0x7C00,
                    metavar="HEX",
                    help="where the record stages (default: 7C00, which "
                         "GEN's own operands fix for both later titles)")
    rf.set_defaults(func=refs)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
