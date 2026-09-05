#!/usr/bin/env python3
"""Name an Amiga Gold Box enumeration from the routine that draws it.

A ramp probe cannot find an enum -- a wrong index draws unrelated game text
rather than a number -- but the code can, because the routine that paints a
character sheet turns the record's byte into a string by indexing a table.
Finding that table names **every** value at once, and it names them in the
game's own words.

`#28 (Decode an Amiga saved game, not just a character file)` used this to
settle whether the later Amiga titles number their nine character states the
way DOS does.  They do: `/Secret` `0x196EA` indexes a nine-entry pointer table
with record byte `0x143`, and `/Curse` `0x1A38E` hands record byte `0x19A` to
a helper that fetches entry `status + 0x2C` of a text library.  The same three
subcommands found the race, class, sex and alignment tables on the way past.

    tools/amigaenum.py --file work/exe/secret sites
    tools/amigaenum.py --file work/exe/secret table 30fc --count 9
    tools/amigaenum.py --glib work/STRINGS.GLB --first 44 --count 9

**`sites` finds one shape of indexing and not all of them.**  It matches the
SAS/Lattice small-data idiom `move.b d16(An), d0; ext.w; ext.l; asl.l #2;
lea d16(a4), a0; move.l (a0, d0.l), -(a7)` -- a byte scaled to a longword and
read out of a `char *` table.  A title that fetches its strings from a library
instead, as `/Curse` does, has no such site; that is what `--glib` is for.

Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools.amiga68k import SMALL_DATA_BIAS, Executable, load  # noqa: E402

#: `move.b d16(An), d0` -- the record byte about to become an index.
_LOAD_BYTE = re.compile(rb"\x10[\x28\x2a\x2b\x2c\x2d\x2e\x29](..)$", re.S)
#: `ext.w d0; ext.l d0; asl.l #2, d0; lea d16(a4), a0; move.l (a0, d0.l), -(a7)`
_INDEX = re.compile(rb"\x48\x80\x48\xc0\xe5\x80\x41\xec(..)\x2f\x30\x08\x00",
                    re.S)

GLIB_MAGIC = b"GLIB"


def sites(exe: Executable) -> list[tuple[int, int | None, int]]:
    """`(file offset, record offset, table global)` for every indexing site.

    `record offset` is the displacement of the `move.b` immediately in front
    of the index, or `None` where the byte came from somewhere else -- a
    register, a local, a different addressing mode.
    """
    out = []
    for m in _INDEX.finditer(exe.data):
        d16 = struct.unpack(">h", m.group(1))[0]
        before = exe.data[m.start() - 4:m.start()]
        hit = _LOAD_BYTE.match(before)
        field = struct.unpack(">H", hit.group(1))[0] if hit else None
        out.append((m.start(), field, SMALL_DATA_BIAS + d16))
    return out


def table(exe: Executable, global_offset: int, count: int) -> list[str]:
    """The strings a `char *` table names, from its offset in the data hunk.

    Each entry is a longword with a `RELOC32` entry, so the value in the file
    is an offset into the hunk it points at and the linker's own relocation
    table is what turns it into a file offset.  An entry with no relocation --
    a NULL, or a longword that is not a pointer at all -- comes back as
    `(not a pointer)`, which is how a table's end shows itself.
    """
    data = exe.small_data
    if data is None:
        raise SystemExit("this executable is not a small-data program; its "
                         "tables are not addressed through a4")
    out = []
    for i in range(count):
        at = data.file_offset + global_offset + 4 * i
        resolved = exe.resolve_abs(at)
        if resolved is None:
            out.append("(not a pointer)")
            continue
        _hunk, _value, where = resolved
        out.append("(outside the file)" if where is None
                   else (exe.cstring(where, 128) or "(not a string)"))
    return out


def glib_blocks(data: bytes) -> list[bytes]:
    """Every block of a `GLIB` container, in order.

    The header is the magic, a `u32` total size, a `u16` block count, a `u16`,
    a four-byte tag naming what the blocks are (`TEXT` in `STRINGS.GLB`,
    `DATA` in the script libraries), then `count + 1` big-endian `u32`
    offsets, block *i* being `[off[i], off[i + 1])`.  In a text library each
    block is one NUL-terminated string, which is what makes an index into the
    library an index into an enumeration.
    """
    if data[:4] != GLIB_MAGIC:
        raise SystemExit(f"not a GLIB container: it opens {data[:4]!r}")
    count = struct.unpack(">H", data[8:10])[0]
    offsets = struct.unpack(f">{count + 1}I", data[16:16 + 4 * (count + 1)])
    return [data[offsets[i]:offsets[i + 1]] for i in range(count)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adf", help="a disk image holding the executable")
    parser.add_argument("--exe", help="the executable's path on the disk")
    parser.add_argument("--file", help="the executable as a loose file")
    parser.add_argument("--glib", help="a GLIB text library, as a loose file")
    parser.add_argument("--first", type=int, default=0,
                        help="the first block of a --glib library to print")
    parser.add_argument("--count", type=int, default=16,
                        help="how many entries to print")
    parser.add_argument("command", choices=("sites", "table", "glib"))
    parser.add_argument("where", nargs="?",
                        help="for `table`, the table's offset in the data "
                             "hunk, hex -- the g<nnnn> name amiga68k.py's "
                             "listing prints")
    args = parser.parse_args(argv)

    if args.command == "glib":
        if not args.glib:
            parser.error("`glib` needs --glib")
        blocks = glib_blocks(pathlib.Path(args.glib).read_bytes())
        for i in range(args.first, min(args.first + args.count, len(blocks))):
            print(f"{i:4d} 0x{i:02x}  {blocks[i].rstrip(bytes(1))!r}")
        return 0

    exe = Executable.parse(load(args))
    if args.command == "sites":
        for at, field, global_offset in sites(exe):
            where = "?" if field is None else f"{field:#05x}"
            print(f"{at:06x}  record {where:>7}  table g{global_offset:04x}")
        return 0

    if not args.where:
        parser.error("`table` needs the table's data-hunk offset, in hex")
    for i, s in enumerate(table(exe, int(args.where, 16), args.count)):
        print(f"{i:4d}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
