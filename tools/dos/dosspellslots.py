#!/usr/bin/env python3
"""Read a DOS Gold Box title's spell-slot block out of its own engine.

    tools/dos/dosspellslots.py --game SECRET sites
    tools/dos/dosspellslots.py --game SECRET census
    tools/dos/dosspellslots.py --game SECRET refs
    tools/dos/dosspellslots.py --path ".../Pools of Darkness/GAME/DARKNESS" --record 510 census

The instrument behind `#222 (Silver Blades' fourth spell-slot array is zero
in every state anybody can create)`.  The character record's spell-slot
block is `array[class, level] of byte`, indexed `base - 1 + width * class +
level` with `class` the first byte and `level` the second of the title's
16-byte spell-table entry.  Which classes a title has, how wide the block
is, and what zeroes it are all in the code, and this reads them:

* `sites` -- every `add di, <block>` in `GAME.OVR`, which is how a Turbo
  Pascal `FillChar(record.slots, n, 0)` starts, with the `n` pushed after it.
  Three per title so far: the slot builder, character creation and
  dual-classing.
* `census` -- the class and level byte of every spell-table entry, and a
  count per class.  The table's data-segment offset is read off the slot
  builder itself (the `shl di, cl / add di, <table>` that walks it after the
  fill), and the data segment off the System unit's `mov dx, seg / mov ds,
  dx`, so nothing is hard-coded per title beyond the block's offset.
* `tables` -- the per-class **slot rows** the builder adds, accumulated out
  of the delta tables it reads.  One branch a class, and for each the level
  its rows start at, which record array each run lands in, and the running
  totals a character sheet would show.  This is `#548 (What do Curse's
  spell-slot arrays hold for a paladin, a ranger or a druid, which nothing
  on this machine can reach?)`: Curse's paladin gets cleric slots from level
  9 written into the **cleric** array, and its ranger gets druid slots from
  8 and magic-user slots from 9 out of one table split across two arrays.
  `tests/curse_of_the_azure_bonds/test_cursespellslots.py` reads all four back through this and
  checks `goldbox.spells`' committed rows against them.
* `refs` -- every `es:[reg + disp]` instruction over the block's range,
  through `tools/dos/dosfieldrefs.py`, with the same three caveats that tool
  carries: a count is an upper bound and a site is worth believing only
  when a disassembly corroborates it.

Block offsets come from `goldbox.dos_port` (`spells_castable_cleric`).
Prints offsets, counts and short instruction windows; the game's bytes stay
in the player's own directory.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys
from collections import Counter

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

import capstone  # noqa: E402

from goldbox import dos_port  # noqa: E402
from tools.dos import dosbox, dosfieldrefs, unexepack  # noqa: E402

#: The title's record size, by game directory stem, for `dos_layout`.
RECORD_SIZE = {
    "POOLRAD": 285, "CURSE": 422, "Gateway to the Savage Frontier": 422,
    "SECRET": 439, "Pools of Darkness": 510,
    "Treasures of the Savage Frontier": 510,
}


def image_of(game: pathlib.Path, exe: str | None) -> bytes:
    """The expanded load image of the title's executable."""
    if exe is None:
        exe = "START.EXE" if (game / "START.EXE").exists() else "GAME.EXE"
    raw = (game / exe).read_bytes()
    try:
        image, _ = unexepack.unpack(raw)
    except ValueError:
        header = struct.unpack_from("<H", raw, 8)[0] * 16
        image = raw[header:]
    return image


def data_segment(image: bytes) -> int:
    """The paragraph the System unit loads into `DS` at start-up.

    The entry point's first far call is `System.init`, which begins
    `mov dx, seg DATA / mov ds, dx`.
    """
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    for ip in range(0, 0x200):
        for ins in md.disasm(image[ip:ip + 64], ip):
            if ins.mnemonic == "lcall":
                seg, off = (int(x, 16) for x in ins.op_str.replace(" ", "").split(","))
                at = seg * 16 + off
                if image[at] == 0xBA and image[at + 3:at + 5] == b"\x8e\xda":
                    return struct.unpack_from("<H", image, at + 1)[0]
                break
    raise ValueError("no `mov dx, seg / mov ds, dx` behind the first far call")


def block_of(size: int) -> tuple[int, int]:
    """`(offset, width)` of the slot block in a record of `size` bytes."""
    fields = {f.name: f for f in dos_port.layout_for(size)}
    cleric = fields["spells_castable_cleric"]
    return cleric.offset, cleric.size


def fill_sites(ovr: bytes, block: int) -> list[tuple[int, int | None]]:
    """`(site, count)` for every `add di, block` and the `FillChar` count
    pushed after it, or `None` when no `mov ax, imm16 / push ax` follows."""
    out = []
    for m in re.finditer(re.escape(b"\x81\xc7" + struct.pack("<H", block)), ovr):
        p = m.end()
        count = None
        if ovr[p:p + 3] == b"\x06\x57\xb8" and ovr[p + 5] == 0x50:
            count = struct.unpack_from("<H", ovr, p + 3)[0]
        out.append((m.start(), count))
    return out


def table_offset(ovr: bytes, site: int, window: int = 0x400) -> int | None:
    """The spell table's `DS` offset, from the first `mov cl, 4 / shl di, cl
    / add di, imm16` after a fill site -- the builder walking the table."""
    m = re.search(rb"\xb1\x04\xd3\xe7\x81\xc7(..)", ovr[site:site + window], re.S)
    return struct.unpack_from("<H", m.group(1))[0] if m else None


# --- the per-class delta tables the builder adds, #548 -----------------------
# `sites` finds three `add di, <block>` sites and only one of them is the
# builder that rebuilds the block from a character's own class levels.  What
# tells them apart is the class loop: the builder walks the eight class slots
# with `inc byte ptr [bp-1]` and closes on `cmp byte ptr [bp-1], 7 / je / jmp`,
# and everything below is bounded by that.
#
# Inside it each class branch is `cmp al, <class> / je|jne`, and inside a
# branch:
#
# * `inc byte ptr es:[di + imm16]` is the level-1 base -- one slot, given to a
#   class before any row is added.  The cleric and the magic-user have one; the
#   paladin and the ranger do not;
# * `mov al, <level> / cmp al, [bp-0xf]` opens the loop over class levels, and
#   `<level>` is the first level whose row is added at all;
# * `mov byte ptr [bp-5], <s>` ... `cmp byte ptr [bp-5], <s> / jne` bound the
#   inner loop over the row's columns;
# * `mov dl, [di + imm16]` reads the table and `add byte ptr es:[di + imm16],
#   dl` says which record array it lands in, `di` being the column index;
# * `sub ax, imm16` between the two shifts that index, which is how the ranger
#   writes his columns 4 and 5 into the magic-user array's levels 1 and 2.
#
# Nothing here is hard-coded per title: the addresses in the docstrings above
# are Curse's and are named so a reader can check one, not so the code can use
# one.

#: The class loop's terminator, `cmp byte ptr [bp-1], 7 / je +3 / jmp`.
_CLASS_LOOP_END = rb"\x80\x7e\xff\x07\x74\x03\xe9"


#: The names of the arrays the block holds, in record order.
ARRAYS = ("cleric", "druid", "magic-user")


class SlotRun:
    """One inner loop: a run of one class's table row into one record array.

    The engine's own arithmetic, kept as it stands rather than reduced: the
    byte it reads for class level `L` and loop counter `s` is `table +
    width * L + s`, and the record byte it adds that to is `dest + s - shift`.
    """

    def __init__(self, table: int, dest: int, first: int, last: int,
                 shift: int):
        self.table, self.dest = table, dest
        self.first, self.last, self.shift = first, last, shift

    def cells(self, block: int):
        """`(s, index into the block)` for every column this run writes."""
        return [(s, self.dest + s - self.shift - block)
                for s in range(self.first, self.last + 1)]

    def __repr__(self) -> str:                                # pragma: no cover
        return (f"SlotRun(table=DS:{self.table:04X}, dest={self.dest:#05x}, "
                f"s={self.first}-{self.last}, shift={self.shift})")


class SlotClass:
    """One class branch of the builder: where its rows start and where they go.

    `base` is the block index a class is given unconditionally at level 1 --
    the `inc byte ptr es:[di + imm16]` the cleric and the magic-user branches
    open with, and which the paladin and the ranger do not have.
    """

    def __init__(self, number: int, from_level: int, base: int | None,
                 runs: list[SlotRun]):
        self.number, self.from_level = number, from_level
        self.base, self.runs = base, runs

    def __repr__(self) -> str:                                # pragma: no cover
        return (f"SlotClass({self.number}, from level {self.from_level}, "
                f"base={self.base}, {self.runs})")


def builder_site(ovr: bytes, block: int) -> int:
    """The one fill site that is the slot builder, by its class loop.

    Raises `LookupError` when none or more than one of the `add di, block`
    sites carries the loop -- either would mean this reading no longer holds,
    which is not something to guess past.
    """
    sites = fill_sites(ovr, block)
    found = [s for s, _ in sites
             if re.search(_CLASS_LOOP_END, ovr[s:s + 0x800])]
    if len(found) != 1:
        raise LookupError(
            f"{len(found)} of {len(sites)} `add di, {block:#x}` sites carry a "
            f"class loop; expected exactly one")
    return found[0]


def builder_classes(ovr: bytes, site: int) -> list[SlotClass]:
    """Every class branch of the builder at `site`, in the order it tests them.

    The numbers are the record's own class-slot numbers, which
    `goldbox.dos_codec.CLASS_LEVEL_SLOTS` names -- so a class with no branch
    here is a class the title gives no spell slots to, and Curse's druid
    (class 1) is one.
    """
    end = re.search(_CLASS_LOOP_END, ovr[site:site + 0x800])
    if end is None:
        raise LookupError(f"no class loop after {site:06X}")
    window = ovr[site:site + end.start()]
    marks = [(m.start(), m.group(1)[0])
             for m in re.finditer(rb"\x3c(.)[\x74\x75]", window, re.S)]
    out = []
    for i, (at, number) in enumerate(marks):
        body = window[at:marks[i + 1][0] if i + 1 < len(marks) else len(window)]
        head = re.search(rb"\xb0(.)\x3a\x46\xf1", body, re.S)
        if head is None:
            continue                       # a branch that adds no rows at all
        inc = re.search(rb"\x26\xfe\x85(..)", body, re.S)
        base = struct.unpack_from("<H", inc.group(1))[0] if inc else None
        # One `mov byte ptr [bp-5], <s>` opens each inner loop, so the byte
        # between two of them is one run and the shift cannot be picked up
        # from the run beside it.
        starts = [(m.start(), m.group(1)[0])
                  for m in re.finditer(rb"\xc6\x46\xfb(.)", body, re.S)]
        runs = []
        for j, (opens, first) in enumerate(starts):
            span = body[opens:starts[j + 1][0] if j + 1 < len(starts)
                        else len(body)]
            read = re.search(rb"\x8a\x95(..)", span, re.S)
            add = re.search(rb"\x26\x00\x95(..)", span, re.S)
            last = re.search(rb"\x80\x7e\xfb(.)\x75", span, re.S)
            if read is None or add is None or last is None:
                continue
            sub = re.search(rb"\x2d(.)\x00", span[:read.start()], re.S)
            runs.append(SlotRun(
                table=struct.unpack_from("<H", read.group(1))[0],
                dest=struct.unpack_from("<H", add.group(1))[0],
                first=first, last=last.group(1)[0],
                shift=sub.group(1)[0] if sub else 0))
        out.append(SlotClass(number, head.group(1)[0], base, runs))
    return out


def class_rows(image: bytes, ds: int, cls: SlotClass, block: int, width: int,
               ceiling: int) -> dict[str, list[tuple[int, ...]]]:
    """One class's **cumulative** rows, per record array, indexed by level - 1.

    The tables in the image are deltas -- one row a level, added on top of
    what the levels below already gave -- so what comes back is what a
    character sheet would show rather than what the bytes hold.  `ceiling` is
    the title's own maximum for the class, because that is the title's rule
    rather than the builder's; nothing above it is read.
    """
    block_total = [0] * (width * len(ARRAYS))
    touched = {i // width for run in cls.runs
               for _, i in run.cells(block)}
    if cls.base is not None:
        touched.add((cls.base - block) // width)
    out: dict[str, list[tuple[int, ...]]] = {ARRAYS[i]: [] for i in sorted(touched)}
    for level in range(1, ceiling + 1):
        if cls.base is not None and level == 1:
            block_total[cls.base - block] += 1
        if level >= cls.from_level:
            for run in cls.runs:
                at = ds * 16 + run.table + width * level
                for s, index in run.cells(block):
                    block_total[index] += image[at + s]
        for i in sorted(touched):
            out[ARRAYS[i]].append(tuple(block_total[i * width:(i + 1) * width]))
    return out


def slot_tables(ovr: bytes, image: bytes, block: int, width: int,
                ceilings: dict[int, int]) -> dict[int, dict[str, list]]:
    """Every class branch's cumulative rows, keyed by class-slot number.

    `ceilings` is `{class number: the title's own maximum level}`.
    """
    ds = data_segment(image)
    site = builder_site(ovr, block)
    return {cls.number: class_rows(image, ds, cls, block, width,
                                   ceilings.get(cls.number, 20))
            for cls in builder_classes(ovr, site)}


def cmd_tables(a, ovr, image, block, width):
    from goldbox import dos_codec

    names = dict((n, name) for n, name, _ in dos_codec.CLASS_LEVEL_SLOTS)
    ds = data_segment(image)
    site = builder_site(ovr, block)
    print(f"DS {ds:04X}, slot builder at {site:06X}")
    for cls in builder_classes(ovr, site):
        print(f"\nclass {cls.number} {names.get(cls.number, '?')}: rows from "
              f"level {cls.from_level}"
              + (f", one slot at block index {cls.base - block} from level 1"
                 if cls.base is not None else ", no level-1 base"))
        for run in cls.runs:
            print(f"    DS:{run.table:04X} columns {run.first}-{run.last} "
                  f"-> record {run.dest + run.first - run.shift:#05x}-"
                  f"{run.dest + run.last - run.shift:#05x}")
        rows = class_rows(image, ds, cls, block, width, a.ceiling)
        for which, table in rows.items():
            print(f"  {which}:")
            for level, row in enumerate(table, start=1):
                print(f"    {level:2d}  " + " ".join(str(v) for v in row))
    return 0


def cmd_sites(a, ovr, image, block, width):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    for site, count in fill_sites(ovr, block):
        shape = f"{count} = {count // width} x {width}" if count else "no count"
        print(f"{site:06X}  add di, {block:#x}; FillChar {shape}")
        for ins in md.disasm(ovr[site:site + 24], site):
            print(f"    {ins.address:06x} {ins.mnemonic} {ins.op_str}")
        t = table_offset(ovr, site)
        if t is not None:
            print(f"    walks a 16-byte table at DS:{t:04X}")


def cmd_census(a, ovr, image, block, width):
    ds = data_segment(image)
    table = a.table
    if table is None:
        for site, _ in fill_sites(ovr, block):
            table = table_offset(ovr, site)
            if table is not None:
                break
    if table is None:
        print("no spell table found behind any fill site; pass --table")
        return 1
    base = ds * 16 + table
    print(f"DS {ds:04X}, spell table at DS:{table:04X} = image {base:06X}, "
          f"{a.spells} entries")
    classes: Counter[int] = Counter()
    for sid in range(1, a.spells + 1):
        e = image[base + sid * 16:base + sid * 16 + 16]
        classes[e[0]] += 1
        if a.verbose:
            print(f"  {sid:3d} class {e[0]} level {e[1]}")
    for c in sorted(classes):
        lo = block + width * c
        print(f"class {c}: {classes[c]:3d} spells  -> slots {lo:#x}-{lo + width - 1:#x}")
    for c in range(max(classes) + 1):
        if c not in classes:
            lo = block + width * c
            print(f"class {c}:   0 spells  -> slots {lo:#x}-{lo + width - 1:#x} never indexed")
    return 0


def cmd_refs(a, ovr, image, block, width):
    span = range(block - 1, block + 4 * width + 1)
    for name, data in (("GAME.OVR", ovr), ("image", image)):
        for off in span:
            refs = dosfieldrefs.references(data, off)
            if refs:
                print(f"{name} {off:#05x}: " + "  ".join(
                    f"{r['linear']:06x}:{r['kind']}:{r['mnem'].split()[0]}" for r in refs))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("cmd", choices=("sites", "census", "refs", "tables"))
    ap.add_argument("--game", default="SECRET", help="game directory stem")
    ap.add_argument("--path", default=None,
                    help="the game directory itself, for a title whose executable "
                         "is not START.EXE and so is not found by stem")
    ap.add_argument("--exe", default=None, help="START.EXE or GAME.EXE; guessed")
    ap.add_argument("--record", type=int, default=None,
                    help="record size, when the stem is not in RECORD_SIZE")
    ap.add_argument("--table", type=lambda s: int(s, 0), default=None,
                    help="census: the spell table's DS offset, if not derived")
    ap.add_argument("--spells", type=int, default=None,
                    help="census: how many spell ids to read (default: the spellbook width)")
    ap.add_argument("--verbose", action="store_true", help="census: one line per spell")
    ap.add_argument("--ceiling", type=int, default=12,
                    help="tables: how many class levels to accumulate (default 12)")
    a = ap.parse_args(argv)
    game = pathlib.Path(a.path) if a.path else dosbox.find_game(a.game)
    size = a.record or RECORD_SIZE[a.game]
    if a.spells is None:
        a.spells = dos_port.deltas_for(size).spellbook_spells
    ovr = (game / "GAME.OVR").read_bytes()
    image = image_of(game, a.exe)
    block, width = block_of(size)
    return {"sites": cmd_sites, "census": cmd_census, "refs": cmd_refs,
            "tables": cmd_tables}[a.cmd](a, ovr, image, block, width) or 0


if __name__ == "__main__":
    sys.exit(main())
