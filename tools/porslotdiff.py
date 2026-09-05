#!/usr/bin/env python3
"""Diff two Amiga *Pool of Radiance* save slots, field by field.

The question this answers is the one a writer cannot answer about itself:
**which bytes does the engine change when it writes out a party we wrote?**
Put a slot on a disk with `tools/porslot.py`, boot it, load it, camp, save to
another slot, and then run this -- every difference is either a field the
engine derives or a field we got wrong, and there is no third kind.

    tools/porslotdiff.py work/109/por1-F-after-C.adf --from F --to C

That run is `docs/124-amiga-port.md` §1.12a: slot `F` was written by
`goldbox.amiga.write_por_slot` and slot `C` is the engine's own save of the
same six characters in the same session.  The answer was `item_chain`,
`heap_104`, `effect_chain` and five thief skills, and nothing else in 1728
bytes of record.

Every file is read; the disk is never written.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga, dos_layout  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402


def field_at(offset: int) -> str:
    """The DOS field name covering an Amiga record offset, or a pad's name.

    The shift map is the only translation, so a name here is the same name the
    writer's provenance lines and `goldbox.dos`'s declared tables use -- which
    is the point: a difference is worth reading only if it can be looked up.
    """
    for f in dos_layout.LAYOUT:
        try:
            at = amiga.amiga_por_offset(f.offset)
        except amiga.AmigaRecordError:
            continue
        if at <= offset < at + f.size:
            return f.name
    if offset == amiga.AMIGA_POR_PAD:
        return "pad 0x07F"
    if offset == amiga.AMIGA_POR_TAIL_PAD:
        return "pad 0x11F"
    return f"unmapped {offset:#05x}"


def slot_files(disk: AmigaDisk, slot: str, index: int,
               drawer: str = amiga.POR_SAVE_DRAWER) -> dict[str, bytes]:
    stem = amiga.por_save_path(amiga.por_filename(slot, index, ""), drawer)
    out = {}
    for suffix in (".sav", ".itm", ".spc"):
        try:
            out[suffix] = disk.read_file(stem + suffix)
        except AmigaDiskError:
            pass
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.
                                     RawDescriptionHelpFormatter)
    parser.add_argument("disk", help="an Amiga Pool of Radiance disk image")
    parser.add_argument("--from", dest="left", required=True,
                        help="the slot letter to compare from")
    parser.add_argument("--to", dest="right", required=True,
                        help="the slot letter to compare to")
    parser.add_argument("--drawer", default=amiga.POR_SAVE_DRAWER,
                        help="the drawer the slots sit in: 'save' on a game "
                             "disk, and empty for the root of a POOLSAVE save "
                             "disk (#36)")
    args = parser.parse_args(argv)

    disk = AmigaDisk.open(args.disk)
    counts: collections.Counter = collections.Counter()
    nodes = same_nodes = 0
    # The display line is the one field a writer cannot check against itself:
    # `write_por` leaves all 42 bytes NUL because the line is a cached render,
    # and whether the engine fills it in is a question about the engine.
    blank_left = blank_right = item_nodes = 0
    for index in range(1, amiga.POR_PARTY_MAX + 1):
        left = slot_files(disk, args.left, index, args.drawer)
        right = slot_files(disk, args.right, index, args.drawer)
        if not left or not right:
            continue
        a, b = left.get(".sav", b""), right.get(".sav", b"")
        differ = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
        names = sorted({field_at(i) for i in differ})
        print(f"character {index}: {len(differ)} record bytes differ"
              + (f" -- {', '.join(names)}" if names else ""))
        for i in differ:
            counts[field_at(i)] += 1
        for suffix, size in ((".itm", amiga.AMIGA_POR_ITEM_SIZE),
                             (".spc", amiga.AMIGA_POR_EFFECT_SIZE)):
            x, y = left.get(suffix), right.get(suffix)
            if x is None or y is None:
                continue
            if len(x) != len(y):
                print(f"  {suffix}: {len(x)} bytes against {len(y)}")
                continue
            for n in range(len(x) // size):
                nodes += 1
                p, q = x[n * size:(n + 1) * size], y[n * size:(n + 1) * size]
                if suffix == ".itm":
                    item_nodes += 1
                    text = amiga.AMIGA_POR_ITEM_TEXT
                    blank_left += p[:text] == bytes(text)
                    blank_right += q[:text] == bytes(text)
                if p == q:
                    same_nodes += 1
                    continue
                where = [hex(i) for i in range(size) if p[i] != q[i]]
                print(f"  {suffix} node {n}: {' '.join(where)}")
    print(f"\n{same_nodes} of {nodes} item and effect nodes identical")
    print(f"display line all NUL: {blank_left} of {item_nodes} in "
          f"{args.left.upper()}, {blank_right} of {item_nodes} in "
          f"{args.right.upper()}")
    print("record bytes by field:")
    for name, count in counts.most_common():
        print(f"  {count:>4}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
