#!/usr/bin/env python3
"""Print the src -> dest map a Gold Box Amiga unpacker routine writes.

Curse and Silver Blades keep their characters, monsters and items on disk in
the **DOS** layout and expand each into the Amiga one at load time, with a
routine that is a straight run of `movmem(packed + base + src, record + dest,
len)` calls and single-byte moves, followed by a byte-swap of every `u16` and
`u32`.  Reading that routine gives the whole shift map as instructions rather
than as an inference from specimens, which is what
`#55 (Decode the Amiga Curse and Silver Blades records)` needed and what
`docs/166-amiga-records-from-the-code.md` is written from.

    tools/amigaunpack.py --file work/exe/curse --size 0x1ac \\
        --shape curse-of-the-azure-bonds 270a6 273ea
    tools/amigaunpack.py --adf work/copy-of-curse-A.adf --exe /Curse \\
        --items --size 0x42 --shape curse-of-the-azure-bonds 26ef8 270a6

Each row is one copy the routine makes, and `swap` rows are the byte-order
fixes it applies afterwards.  The `dos` column is the field
`goldbox/dos_layout.py` puts at that source offset, when `--shape` names a
title, so a boundary that does not land on a field boundary is visible rather
than assumed.

A `gap` row is destination bytes no `movmem` writes, and it is **three
different things** -- read the routine before calling one an insertion:

* a genuine **alignment pad**, like Curse's `0x0FB` and `0x151`;
* a **pointer the loader rebuilds** rather than carrying, like Curse's effect
  chain at `0x0F2` and its item region at `0x151`-`0x189`;
* a region the routine copies with a **byte-at-a-time loop** instead of a
  `movmem`, which this reader does not follow.  Curse's `0x10A`+16 is the
  class-level pair and Silver Blades' `0x0AC` and `0x0B3` are the same.

Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_layout  # noqa: E402
from tools.amiga68k import Executable, disassemble, load  # noqa: E402

#: `move.w #$N, -(a7)` -- a length, or the value of a `setmem`.
_PUSH_IMM = re.compile(r"move\.w #\$([0-9a-f]+), -\(a7\)")
#: `lea.l $N(a2), a0` -- the destination of the copy about to be pushed.
_LEA_DEST = re.compile(r"lea\.l\s+\$([0-9a-f]+)\(a2\), a0")
#: `addi.w #$N, d0` -- the source offset inside the packed record.
_ADD_SRC = re.compile(r"addi\.w\s+#\$([0-9a-f]+), d0")
#: `move.b (a3, d1.l), $N(a2)` -- a one-byte copy, source in the `addi` above.
_MOVE_ONE = re.compile(r"move\.b\s+\(a3, d1\.l\), \$([0-9a-f]+)\(a2\)")
#: `move.w $N(a2), -(a7)` / `move.l $N(a2), -(a7)` -- a field about to be
#: handed to the byte swapper.
_SWAP_PUSH = re.compile(r"move\.(w|l)\s+\$([0-9a-f]+)\(a2\), -\(a7\)")
#: `clr.l $N(a2)` -- a pointer the unpacker rebuilds rather than carries.
_CLEAR = re.compile(r"clr\.l\s+\$([0-9a-f]+)\(a2\)")
#: `addq.w #$1, d0` -- the name, whose source is the count byte plus one.
_ADD_ONE = re.compile(r"addq\.w\s+#\$1, d0")


class Row:
    """One line of the map: a copy, a swap, a clear or a gap."""

    def __init__(self, kind: str, src, dest: int, size: int):
        self.kind, self.src, self.dest, self.size = kind, src, dest, size

    @property
    def shift(self):
        return None if self.src is None else self.dest - self.src


def read_map(exe: Executable, start: int, end: int,
             size: int | None = None) -> list[Row]:
    """Every copy, swap and clear the routine in `[start, end)` makes.

    `size` is the destination record's own length, which the routine's
    opening `setmem` pushes; naming it keeps that clear out of the copy map,
    where it would swallow every gap.
    """
    rows: list[Row] = []
    length = dest = src = None
    for line in disassemble(exe, start, end):
        body = line.split(": ", 1)[1].split("    ; ")[0]
        text = " ".join(body.split()[1:])
        m = _MOVE_ONE.search(text)
        if m and src is not None:
            rows.append(Row("copy", src, int(m.group(1), 16), 1))
            length = dest = src = None
            continue
        m = _CLEAR.search(text)
        if m:
            rows.append(Row("clear", None, int(m.group(1), 16), 4))
            continue
        m = _SWAP_PUSH.search(text)
        if m:
            rows.append(Row("swap", None, int(m.group(2), 16),
                            2 if m.group(1) == "w" else 4))
            continue
        m = _PUSH_IMM.search(text)
        if m:
            length = int(m.group(1), 16)
            dest = src = None
            continue
        m = _LEA_DEST.search(text)
        if m:
            dest = int(m.group(1), 16)
            continue
        m = _ADD_SRC.search(text)
        if m:
            src = int(m.group(1), 16)
            continue
        if _ADD_ONE.search(text):
            src = 1
            continue
        if text == "move.l a2, -(a7)":
            dest = 0                      # the whole record: name, or setmem
        if text.startswith("jsr") and length is not None \
                and dest is not None:
            kind = "setmem" if (src is None and dest == 0
                                and length == size) else "copy"
            rows.append(Row(kind, src, dest, length))
            length = dest = src = None
    return [r for r in rows if r.kind != "copy" or r.size]


def gaps(rows: list[Row], size: int | None) -> list[Row]:
    """Destination bytes no `movmem` writes: see this module's docstring."""
    written = set()
    for r in rows:
        if r.kind == "copy":
            written.update(range(r.dest, r.dest + r.size))
    if not written:
        return []
    top = size if size is not None else max(written) + 1
    out, run = [], []
    for at in range(min(written), top):
        if at in written:
            if run:
                out.append(Row("gap", None, run[0], len(run)))
                run = []
        else:
            run.append(at)
    if run:
        out.append(Row("gap", None, run[0], len(run)))
    return out


SHAPES = {s.key: s for s in (dos_layout.CURSE_OF_THE_AZURE_BONDS,
                             dos_layout.SECRET_OF_THE_SILVER_BLADES,
                             dos_layout.POOL_OF_RADIANCE,
                             dos_layout.POOLS_OF_DARKNESS)}


def _fields(shape_key: str | None, items: bool):
    if shape_key is None:
        return {}
    shape = SHAPES[shape_key]
    layout = dos_layout.ITEM_LAYOUT if items else dos_layout.layout_for(shape)
    return {f.offset: f.name for f in layout}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adf", help="a disk image holding the executable")
    parser.add_argument("--exe", help="the executable's path on the disk")
    parser.add_argument("--file", help="the executable as a loose file")
    parser.add_argument("--shape", choices=sorted(SHAPES),
                        help="name the DOS field at each source offset")
    parser.add_argument("--items", action="store_true",
                        help="the routine unpacks an item, not a record")
    parser.add_argument("--size", type=lambda s: int(s, 0),
                        help="the Amiga record size, to show the trailing pad")
    parser.add_argument("start", help="file offset of the routine, hex")
    parser.add_argument("end", help="file offset past its last instruction")
    args = parser.parse_args(argv)

    exe = Executable.parse(load(args))
    rows = read_map(exe, int(args.start, 16), int(args.end, 16), args.size)
    rows += gaps([r for r in rows], args.size)
    names = _fields(args.shape, args.items)
    print(f"{'kind':6s} {'dos':>5s} {'amiga':>5s} {'len':>4s} {'shift':>5s}  "
          f"field")
    for row in sorted(rows, key=lambda r: (r.dest, r.kind)):
        src = "-" if row.src is None else f"{row.src:#05x}"
        shift = "-" if row.shift is None else f"{row.shift:+d}"
        print(f"{row.kind:6s} {src:>5s} {row.dest:#05x} {row.size:4d} "
              f"{shift:>5s}  {names.get(row.src, '') if row.src is not None else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
