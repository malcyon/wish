#!/usr/bin/env python3
"""The later DOS titles' THAC0 tables, and everything that writes the byte.

`tools/thac0census.py` reads Pool of Radiance's DOS table by anchoring on the
eight class bits that sit immediately after it -- `02 20 08 40 80 01 04 10`.
**Curse and Silver Blades do not carry that run at all**, so that tool cannot
read either of them: it exits with "the class-bit anchor occurs 0 times".
Their class-bit arrays are a different permutation, `02 10 08 40 40 01 04 20`,
because those titles number druid, monk, paladin and ranger differently.

This locates the table without knowing a single THAC0 number, from three
things the engine and our own record layout already say:

* the **stride and the DS offset** come from the engine, out of
  `mov dx, <stride> / mul dx / mov di, ax / add di, cx / mov al, [di + <off>]`
  in `GAME.OVR`, which `tools/thac0census.py --code` prints;
* the **row count** is the width of `class_levels` in
  `goldbox/dos_layout.py`, because the loop walks that array once a class --
  and it is 7 rather than 8 for Silver Blades, which drops the monk;
* the **block** is the one maximal run of bytes in 30..70 whose length is
  exactly `rows * stride`. In each image there is exactly one.

Two independent checks then say the block is the right one, and both are
arithmetic rather than judgement: `block - DS_offset` must be a paragraph
boundary, which fixes DS; and the class-bit array must follow the block,
which is what the loop reads four instructions after the THAC0 lookup.

    tools/laterthac0.py table --title curse-of-the-azure-bonds
    tools/laterthac0.py compare --title secret-of-the-silver-blades
    tools/laterthac0.py records --title curse-of-the-azure-bonds
    tools/laterthac0.py writers --title curse-of-the-azure-bonds

`writers` is the half that settles what a stored byte means: it prints every
instruction in `GAME.OVR` that touches `thac0_base`, with the immediate where
there is one. Every engine stores a flat **40** into it from a block of
new-character defaults -- once in Pool of Radiance and Silver Blades, twice in
Curse, where creation and the class change each got a copy -- and **nothing in
any of the three compares the field against a constant**, which
`constant_compares` checks for separately. So a record holding 40 where the
table says 39 is a value nothing has refreshed rather than a clamp.
`#318 (DOS gives a low-level magic-user or thief THAC0 20 where the C64 gives
21, and our table holds only the C64's)`.

Two of the three loops that build the byte clear it first and walk
`class_levels`; the third walks `former_class_levels` and does not clear,
because it is putting a regained class back --
`docs/209-the-regained-dual-class-on-dos.md`. All three keep the best row and
none of them looks at a bound.

Reads the player's own files and writes nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

from goldbox import dos_port, levels  # noqa: E402
from tools import thac0census  # noqa: E402

#: The DOS class numbers, in the order `class_levels` stores them and the
#: order the THAC0 table's rows are in.  Silver Blades stops at the thief.
CLASS_ORDER = ("cleric", "druid", "fighter", "paladin", "ranger",
               "magic-user", "thief", "monk")

#: Title key -> the game directory stem `tools/dosbox.py` finds it by.  Pools
#: of Darkness is not here: it keeps its root in `GAME.EXE` rather than
#: `START.EXE`, so neither this nor `tools/thac0census.py` reaches its data
#: segment, and it has no C64 port for its table to disagree with.
STEMS = {"pool-of-radiance": "POOLRAD",
         "curse-of-the-azure-bonds": "CURSE",
         "secret-of-the-silver-blades": "SECRET"}

#: The widest and narrowest a stored `60 - THAC0` can be.  A THAC0 of 30 would
#: be off the bottom of every published table and one of -10 off the top, so
#: this brackets the whole family without naming a number any title ships.
LOW, HIGH = 30, 70


def _field(title: str, name: str):
    """One field of a title's DOS record, by name."""
    for field in dos_port.layout_for(title):
        if field.name == name:
            return field
    raise KeyError(f"{title} has no {name}")


class Located:
    """A title's THAC0 table and the evidence that this is it."""

    def __init__(self, title: str, image: bytes, base: int, stride: int,
                 rows: int, ds_offset: int, class_bits: bytes):
        self.title = title
        self.image = image
        self.base = base
        self.stride = stride
        self.rows = rows
        self.ds_offset = ds_offset
        self.class_bits = class_bits

    @property
    def data_segment(self) -> int:
        return (self.base - self.ds_offset) // 16

    def table(self) -> dict[str, list[int]]:
        """Class name -> THAC0 by level, level 1 first.

        Entry 0 of each row is the unused one -- the engine indexes
        `class * stride + level` with a level that is 1 or more -- so it is
        dropped here rather than reported as a level.
        """
        out = {}
        for index in range(self.rows):
            at = self.base + index * self.stride
            row = self.image[at + 1:at + self.stride]
            out[CLASS_ORDER[index]] = [60 - b for b in row]
        return out


def locate(title: str) -> Located:
    """Find `title`'s DOS THAC0 table, or say which check failed."""
    image = thac0census.dos_image(title)
    rows = _field(title, "class_levels").size
    candidates = _lookup_sites(title, rows)
    if not candidates:
        raise SystemExit(f"{title}: no table lookup in GAME.OVR reaches a "
                         f"{rows}-row block of plausible THAC0 bytes")
    stride, ds_offset = candidates[0]
    blocks = [start for start, length in _runs(image)
              if length == rows * stride]
    if len(blocks) != 1:
        raise SystemExit(f"{title}: {len(blocks)} runs of {rows * stride} "
                         "bytes in range, so the block is not located")
    base = blocks[0]
    if (base - ds_offset) % 16:
        raise SystemExit(f"{title}: {base:#x} - {ds_offset:#x} is not a "
                         "paragraph boundary, so DS cannot be that")
    bits = _class_bits(image, base + rows * stride, rows)
    if bits is None:
        raise SystemExit(f"{title}: no class-bit array follows the block")
    return Located(title, image, base, stride, rows, ds_offset, bits)


def _lookup_sites(title: str, rows: int) -> list[tuple[int, int]]:
    """`(stride, DS offset)` for every lookup whose block could be the table.

    The engine reaches several strided tables through the same idiom, so this
    keeps the ones whose row width times `rows` matches a run in the image.
    """
    image = thac0census.dos_image(title)
    lengths = {length for _, length in _runs(image)}
    seen, out = set(), []
    for _, stride, ds_offset in thac0census.dos_table_code(title):
        if (stride, ds_offset) in seen or rows * stride not in lengths:
            continue
        seen.add((stride, ds_offset))
        out.append((stride, ds_offset))
    return out


def _runs(image: bytes) -> list[tuple[int, int]]:
    """`(start, length)` of every maximal run of bytes in `LOW..HIGH`."""
    out, start = [], None
    for index, byte in enumerate(image):
        if LOW <= byte <= HIGH:
            if start is None:
                start = index
        elif start is not None:
            out.append((start, index - start))
            start = None
    if start is not None:
        out.append((start, len(image) - start))
    return out


def _class_bits(image: bytes, at: int, rows: int) -> bytes | None:
    """The class-bit array that follows the table, allowing a pad byte.

    One byte a class, every one a power of two -- the engine adds them into
    the record's class-bits field in the same loop that reads the table.
    """
    for pad in (0, 1, 2):
        run = image[at + pad:at + pad + rows]
        if len(run) == rows and all(b and not b & (b - 1) for b in run):
            return run
    return None


# ---------------------------------------------------------------------------
# What writes the byte
# ---------------------------------------------------------------------------
def writers(title: str) -> list[tuple[int, str, int | None]]:
    """Every `GAME.OVR` instruction touching `thac0_base`, in file order.

    `(offset, what, immediate)`.  The four shapes are all the compiler emits
    for a `char` field at a `disp8` displacement off `es:di`, which is how
    every one of these titles addresses the record.
    """
    from tools import dosbox

    offset = _field(title, "thac0_base").offset
    raw = (dosbox.find_game(STEMS[title]) / "GAME.OVR").read_bytes()
    disp = bytes([offset])
    shapes = (("stores a constant", rb"\x26\xc6\x45" + disp + rb"(.)"),
              ("stores a value", rb"\x26\x88\x45" + disp),
              ("reads it", rb"\x26\x8a\x45" + disp),
              ("compares against it", rb"\x26\x3a\x45" + disp))
    out = []
    for what, pattern in shapes:
        for match in re.finditer(pattern, raw):
            imm = match.group(1)[0] if match.groups() else None
            out.append((match.start(), what, imm))
    return sorted(out)


def constant_compares(title: str) -> list[tuple[int, int]]:
    """`(offset, immediate)` for every `cmp thac0_base, <constant>`.

    A clamp would have to be one of these, and there is not one in any of the
    three engines: the only compares any of them make are `cmp al, es:[di +
    thac0_base]`, which is the rebuild loop keeping the better row.
    """
    from tools import dosbox

    offset = _field(title, "thac0_base").offset
    raw = (dosbox.find_game(STEMS[title]) / "GAME.OVR").read_bytes()
    pattern = rb"\x26\x80\x7d" + bytes([offset]) + rb"(.)"
    return [(m.start(), m.group(1)[0]) for m in re.finditer(pattern, raw)]


# ---------------------------------------------------------------------------
# Against the C64
# ---------------------------------------------------------------------------
def disagreements(title: str) -> list[tuple[str, int, int, int]]:
    """`(class, level, DOS THAC0, C64 THAC0)` wherever the two ports differ.

    The C64 side is `goldbox/levels.py`, which reads its rows off the player's
    own `GEN`; the DOS side is the table located above.  Only levels the C64
    side reaches are compared, because a DOS row runs past this title's C64
    ceiling and there is nothing to disagree with up there.
    """
    dos = locate(title).table()
    tables = levels.for_game(title)
    out = []
    for name in sorted(tables.tables):
        row = dos.get(name)
        if row is None:
            continue
        for entry in tables.table(name):
            if entry.level <= len(row) and row[entry.level - 1] != entry.thac0:
                out.append((name, entry.level, row[entry.level - 1],
                            entry.thac0))
    return out


# ---------------------------------------------------------------------------
# The records
# ---------------------------------------------------------------------------
def records(title: str):
    """`(source, name, class levels, stored THAC0)` for every DOS record.

    The specimen tree and the player's archives, the same two places
    `tools/thac0census.py` sweeps.  That tool's own reader cannot be used for
    Silver Blades: `goldbox.dos.DosCharacter.class_levels` walks all eight
    `CLASS_LEVEL_SLOTS` and that title's array is **seven** wide, so it raises
    `IndexError` on every record -- `#423 (Reading a Silver Blades or Pools of
    Darkness DOS character's class levels raises IndexError, because the array
    is seven slots and the reader walks eight)`.  This reads the array a slot
    at a time instead, so a seven-slot title sweeps.
    """
    import glob
    import os

    from goldbox import dos_codec

    tree = pathlib.Path(os.environ.get(
        "WISH_SPECIMENS", pathlib.Path.home() / "wish-specimens"))
    from tools import dosbox

    files: list[str] = []
    for folder in sorted(tree.glob("*/WISH-SPEC-*")):
        files += glob.glob(str(folder) + "/CHRDAT*.SAV")
        files += glob.glob(str(folder) + "/*.CHA")
    if dosbox.ARCHIVES.is_dir():
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.SAV", recursive=True)
        files += glob.glob(str(dosbox.ARCHIVES) + "/**/*.CHA", recursive=True)
    for path in sorted(set(files)):
        try:
            char = dos_codec.read_character(path)
        except Exception:
            continue
        if char.shape.key != title:
            continue
        raw = char.raw("class_levels")
        held = {name: raw[slot]
                for slot, name, _ in dos_codec.CLASS_LEVEL_SLOTS
                if slot < len(raw) and raw[slot]}
        here = pathlib.Path(path)
        yield (f"{here.parent.name}/{here.name}", char.name, held,
               60 - char.get("thac0_base"))


def sweep(title: str) -> tuple[int, int, list[str]]:
    """`(agreeing, total, lines)` for every record against the table."""
    table = locate(title).table()
    agree = total = 0
    lines = []
    for source, name, held, stored in records(title):
        want = _best(table, held)
        if want is None:
            continue
        total += 1
        if want == stored:
            agree += 1
        else:
            classes = ", ".join(f"{k} {v}" for k, v in sorted(held.items()))
            lines.append(f"MISMATCH {source:<44} {name:<14} {classes:<28} "
                         f"stored={stored:<3} table={want}")
    return agree, total, lines


def _best(table: dict[str, list[int]], class_levels) -> int | None:
    """The best row among the classes the character has a level in.

    The engine's own rule: clear the byte, walk the class slots, keep the row
    that beats what is there -- so no strength, no weapon and no clamp.
    """
    best = None
    for name, level in dict(class_levels or {}).items():
        row = table.get(name)
        if not row or not level:
            continue
        got = row[max(0, min(int(level), len(row)) - 1)]
        best = got if best is None else min(best, got)
    return best


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------
def _print_table(title: str) -> None:
    found = locate(title)
    print(f"{title}: {found.rows} rows of {found.stride} at image "
          f"{found.base:#x}, DS:{found.ds_offset:#06x}, so DS is "
          f"{found.data_segment:#05x}")
    print("  class bits after it: "
          + " ".join(f"{b:02x}" for b in found.class_bits))
    width = len(next(iter(found.table().values())))
    print(f"  {'class':<12} " + " ".join(f"{n:2d}" for n in
                                         range(1, width + 1)))
    for name, row in found.table().items():
        print(f"  {name:<12} " + " ".join(f"{v:2d}" for v in row))


def _print_compare(title: str) -> None:
    rows = disagreements(title)
    print(f"{title}: {len(rows)} level(s) where the DOS table and the C64 "
          "rules differ")
    for name, level, dos_codec, c64 in rows:
        print(f"  {name:<12} level {level:<3} DOS {dos_codec:2d}  C64 {c64:2d}")


def _print_records(title: str, quiet: bool) -> int:
    agree, total, lines = sweep(title)
    if not quiet:
        for line in lines:
            print(line)
    print(f"DOS {title}: {agree} of {total} agree")
    return total - agree


def _print_writers(title: str) -> None:
    offset = _field(title, "thac0_base").offset
    print(f"{title}: GAME.OVR, thac0_base at record {offset:#05x}")
    for at, what, imm in writers(title):
        extra = "" if imm is None else f" = {imm}"
        print(f"  {at:#08x}  {what}{extra}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("table", "compare", "records",
                                     "writers"))
    ap.add_argument("--title", default="curse-of-the-azure-bonds",
                    choices=sorted(STEMS))
    ap.add_argument("--quiet", action="store_true",
                    help="counts only, no per-record lines")
    args = ap.parse_args(argv)

    if args.what == "table":
        _print_table(args.title)
    elif args.what == "compare":
        _print_compare(args.title)
    elif args.what == "writers":
        _print_writers(args.title)
    else:
        return 1 if _print_records(args.title, args.quiet) else 0
    return 0


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(main())
