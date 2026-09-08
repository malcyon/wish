#!/usr/bin/env python3
"""What a DOS Gold Box record holds once a dual-classed human regains his old
class -- read out of the engine's own recompute, and checked against every
record on the machine.

`#408 (What does a DOS record hold once a dual-classed character regains his
old class, since our conversion writes his old level into both arrays)` asked
which array carries which level at that moment.  The answer is that **no array
moves at all**: `class_levels[old]` is zeroed at the change and stays zero for
good, `former_class_levels[old]` keeps the level he left, and everything the
regained class is worth is *derived* from those two plus one comparison.

The routine is Curse's `GAME.OVR:0x3B119`, inside the record recompute the
trainer calls when it has finished:

    class_bits = 0
    for slot in 0..7:
        if class_levels[slot] > 0:                       0x3B131  jg
            add CLASS_BIT[slot]
        elif former_class_levels[slot] > 0                0x3B142  jle skip
             and former_class_levels[slot] < level:      0x3B15B  jge skip
            add CLASS_BIT[slot]                          0x3B16F

`level` is itself the running maximum of the current array (`0x3B09F`), so
`former < level` is "the new class has passed the level he left the old one
at" -- the same test the helper at `0x3C031` spells out, and the same test
the C64's `GEN $20A3` uses before it *stores* the old level back.  The two
ports differ in where the answer lives, not in what it is.

Two commands, neither of which needs an emulator:

* **`code`** finds the derive in each of the six DOS Gold Box overlays on this
  machine and prints whether it consults the former array.  Pool of Radiance
  is the control: it has no former array and its one clear site does not.
* **`census`** predicts `class_bits` for every DOS record it can find from the
  rule above and compares it with the byte the record stores.  A record that
  disagrees is either a record somebody edited or a defect in this reading,
  and either way it is named.

    tools/dualclassregain.py code
    tools/dualclassregain.py code --title curse-of-the-azure-bonds --window 90
    tools/dualclassregain.py census
    tools/dualclassregain.py census --dual-only ~/wish-specimens

The archives are the player's and are read only, found the way
`tools/dosbox.py` finds them.  With no archives `code` prints nothing and
exits 0, the way the tests skip.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos, dos_layout  # noqa: E402
from tools import dosbox  # noqa: E402
from tools.dualclassdos import (  # noqa: E402
    OVERLAYS,
    disassemble,
    find_overlay,
    read_records,
    source_title,
)

#: `mov byte ptr es:[di+<offset>], 0` -- the instruction that starts every
#: rebuild of `class_bits`.  Three titles have three such sites and the
#: 510-byte pair have four; only one of them in each is the recompute.
_CLEAR = (0x26, 0xC6, 0x85)

#: `cmp byte ptr es:[di+<offset>], 0` -- the former array's own test.
_CMP_ZERO = (0x26, 0x80, 0xBD)

#: `cmp al, byte ptr es:[di+<offset>]` -- the former level against `level`.
_CMP_LEVEL = (0x26, 0x3A, 0x85)

#: How far past the clear to look for the two tests.  The whole loop body is
#: 93 bytes in Curse; 120 leaves room and is still inside the routine.
WINDOW = 120


def _pattern(head: tuple[int, ...], offset: int,
             tail: tuple[int, ...] = ()) -> bytes:
    return bytes([*head, offset & 0xFF, offset >> 8, *tail])


def derive_sites(image: bytes, shape_key: str) -> list[dict]:
    """Every rebuild of `class_bits`, and whether it reads the former array.

    A displacement match is not proof of an instruction --
    `tools/dosfieldrefs.py`'s caveat applies here too -- so what makes this
    sound is that the site that answers True is the *only* one in each
    overlay, and `--window` disassembles it for a reader to check.
    """
    fields = {f.name: f for f in dos_layout.layout_for(shape_key)}
    bits = fields["class_bits"].offset
    former = fields.get("former_class_levels")
    level = fields["level"].offset
    clear = _pattern(_CLEAR, bits, (0x00,))
    out = []
    for at in range(len(image) - len(clear)):
        if image[at:at + len(clear)] != clear:
            continue
        window = image[at:at + WINDOW]
        row = {"at": at, "former": False, "level": False}
        if former is not None:
            row["former"] = _pattern(_CMP_ZERO, former.offset,
                                     (0x00,)) in window
            row["level"] = _pattern(_CMP_LEVEL, level) in window
        out.append(row)
    return out


def regained(char) -> dict[int, int]:
    """The old classes this record has got back, slot -> the level he left.

    Empty for a record with no former array, for one that has never
    dual-classed, and for one that has not passed the threshold yet.  The
    test is the engine's: the former entry is non-zero and **strictly** less
    than `level`.  Treasures of the Savage Frontier's OUGO sits exactly on
    it -- former 8 against level 8 -- and is the reason the strictness is
    not a detail.
    """
    if "former_class_levels" not in char.fields:
        return {}
    level = char.get("level")
    return {n: v for n, v in enumerate(char.raw("former_class_levels"))
            if v and v < level}


def predict_bits(char) -> int:
    """`class_bits` as `GAME.OVR:0x3B119` would rebuild it for this record."""
    slots = {n for n, v in enumerate(char.raw("class_levels")) if v}
    slots |= set(regained(char))
    bits = 0
    for slot in slots:
        bits |= dos.CLASS_BIT_FOR_SLOT.get(slot, 0)
    return bits


def code(args: argparse.Namespace) -> int:
    if not dosbox.ARCHIVES.is_dir():
        print("no DOS archives on this machine; set $FR_ARCHIVES")
        return 0
    for key, stem, shape_key in OVERLAYS:
        if args.title and key != args.title:
            continue
        path = find_overlay(stem)
        if path is None:
            print(f"{key}: no GAME.OVR here")
            continue
        image = path.read_bytes()
        rows = derive_sites(image, shape_key)
        borrowed = "" if shape_key == key else f", read as {shape_key}"
        print(f"=== {key}{borrowed}")
        for row in rows:
            what = ("the recompute: reads the former array and compares it "
                    "with level" if row["former"] and row["level"]
                    else "current array only")
            print(f"  clears class_bits at {row['at']:#07x} -- {what}")
        hits = [r for r in rows if r["former"] and r["level"]]
        if len(hits) == 1 and args.window:
            for line in disassemble(image, hits[0]["at"], args.window):
                print(line)
        print()
    return 0


def census(args: argparse.Namespace) -> int:
    records = read_records(args.paths, not args.no_archives)
    if not records:
        print("no DOS character records under those roots; set $FR_ARCHIVES")
        return 0
    dual = agree = 0
    for shape, char, paths in sorted(records, key=lambda r: r[1].name):
        if "former_class_levels" not in char.fields:
            continue
        former = {n: v for n, v in
                  enumerate(char.raw("former_class_levels")) if v}
        if args.dual_only and not former:
            continue
        stored = char.get("class_bits")
        want = predict_bits(char)
        ok = stored == want
        agree += ok
        dual += 1
        back = regained(char)
        mark = "" if ok else "   <<< disagrees"
        if former or not args.dual_only:
            print(f"{char.name:<16} {shape.title[:26]:<26} "
                  f"level={char.get('level'):<3} "
                  f"levels={list(char.raw('class_levels'))} "
                  f"former={list(char.raw('former_class_levels'))} "
                  f"regained={back or '-'} "
                  f"class_bits stored={stored:#04x} rule={want:#04x}{mark}")
            if not ok:
                print(f"    {source_title(paths[0])}: {paths[0]}")
    print(f"\n{agree} of {dual} records match the engine's rule")
    return 0 if agree == dual else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("code", help="find the derive in each overlay")
    c.add_argument("--title", default=None, help="one shape key only")
    c.add_argument("--window", type=int, default=0,
                   help="bytes of listing past the clear; 0 for none")
    c.set_defaults(func=code)

    d = sub.add_parser("census", help="the rule against every stored byte")
    d.add_argument("paths", nargs="*", help="extra directories to sweep")
    d.add_argument("--dual-only", action="store_true",
                   help="print only records whose former array is set")
    d.add_argument("--no-archives", action="store_true",
                   help="sweep only the paths given, so a count has a scope")
    d.set_defaults(func=census)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
