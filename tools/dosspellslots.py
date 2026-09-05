#!/usr/bin/env python3
"""Read a DOS Gold Box title's spell-slot block out of its own engine.

    tools/dosspellslots.py --game SECRET sites
    tools/dosspellslots.py --game SECRET census
    tools/dosspellslots.py --game SECRET refs
    tools/dosspellslots.py --path ".../Pools of Darkness/GAME/DARKNESS" --record 510 census

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
* `refs` -- every `es:[reg + disp]` instruction over the block's range,
  through `tools/dosfieldrefs.py`, with the same three caveats that tool
  carries: a count is an upper bound and a site is worth believing only
  when a disassembly corroborates it.

Block offsets come from `goldbox.dos_layout` (`spells_castable_cleric`).
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

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import capstone  # noqa: E402
import dosbox  # noqa: E402
import dosfieldrefs  # noqa: E402
import unexepack  # noqa: E402

from goldbox import dos_layout  # noqa: E402

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
    fields = {f.name: f for f in dos_layout.layout_for(size)}
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
    ap.add_argument("cmd", choices=("sites", "census", "refs"))
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
    a = ap.parse_args(argv)
    game = pathlib.Path(a.path) if a.path else dosbox.find_game(a.game)
    size = a.record or RECORD_SIZE[a.game]
    if a.spells is None:
        a.spells = dos_layout.shape_for(size).spellbook_spells
    ovr = (game / "GAME.OVR").read_bytes()
    image = image_of(game, a.exe)
    block, width = block_of(size)
    return {"sites": cmd_sites, "census": cmd_census, "refs": cmd_refs}[a.cmd](
        a, ovr, image, block, width) or 0


if __name__ == "__main__":
    sys.exit(main())
