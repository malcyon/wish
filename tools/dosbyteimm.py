#!/usr/bin/env python3
"""Which constants a DOS overlay ever stores into, or compares against, one
character-record byte.

`tools/dosfieldrefs.py` counts the instructions that touch a record offset and
says which of them write.  It does not say *what value* they write, and that is
the question that names a field.  A byte the engine sets to `0Ah`, `0Ch` and
`0FFh` and compares against 8 is not a marching position in a six-character
party, whatever the six records on a disk happen to hold; a byte the engine
sets to `0B2h` and `0B3h` and compares against `80h` and `7Fh` is a bitfield
with a flag in the top bit.  Both readings came out of this scan
(`#305 (Two DOS record bytes have one name from Pool of Radiance and another
from the Curse decompilation)`).

    tools/dosbyteimm.py <POOLRAD/GAME.OVR> --offset 0x0BF
    tools/dosbyteimm.py <CURSE/GAME.OVR> --offset 0x143 --sites

**It inherits every limit of `tools/dosfieldrefs.py`, and adds none of its
own.**  The image is scanned as an undifferentiated byte stream, so a match may
land in data; a displacement match does not prove the pointer is a character
record; and an offset reached without a matching displacement is invisible
here.  So a count is an upper bound and an empty result is evidence rather than
proof.  What raises a single site to a finding is the *shape* of the set of
immediates -- a loop that stores 0, compares 8 and increments is an allocation
whatever else is in the image -- or a second source agreeing.

The immediate lives after the ModRM displacement, so its position depends on
the encoding: `mod=01` puts it at opcode+3 and `mod=10` at opcode+4.  Reading
it from the wrong one is how a scan reports the high half of a displacement as
a stored value.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from dosfieldrefs import references  # noqa: E402

#: Opcodes carrying an immediate after the ModRM displacement, and its width.
#: `0x83` is a byte immediate sign-extended to a word, which is why it is 1
#: here and not 2.
IMMEDIATE_WIDTH = {0xC6: 1, 0xC7: 2, 0x80: 1, 0x81: 2, 0x83: 1,
                   0xF6: 1, 0xF7: 2}


def immediates(image: bytes, offset: int) -> list[dict]:
    """Every `references()` hit, with the constant it carries where it has one.

    A hit with no immediate -- `mov al, es:[di+0BFh]` -- comes back with
    `imm` `None` rather than being dropped, because "read 21 times and stored
    from a register 4 times" is half of what the caller wants to know.
    """
    out = []
    for hit in references(image, offset):
        at = hit["linear"]
        # `references()` reports the address of the prefix, and every hit it
        # returns is ES-prefixed, so the opcode is one byte along.
        op = image[at + 1]
        width = IMMEDIATE_WIDTH.get(op)
        hit = dict(hit)
        hit["op"] = op
        if width is None:
            hit["imm"] = None
        else:
            first = at + 2 + 1 + (2 if hit["disp"] == "word" else 1)
            if width == 1:
                hit["imm"] = image[first]
            else:
                hit["imm"] = image[first] | (image[first + 1] << 8)
        out.append(hit)
    return out


def report(images: dict[str, bytes], offset: int, sites: bool) -> None:
    hits: dict[int, dict] = {}
    for _, image in images.items():
        for hit in immediates(image, offset):
            hits.setdefault(hit["linear"], hit)
    print(f"record +{offset:#05x}: {len(hits)} site(s) across "
          f"{len(images)} image(s)")
    by_mnem: dict[str, collections.Counter] = {}
    for hit in hits.values():
        by_mnem.setdefault(hit["mnem"], collections.Counter())[hit["imm"]] += 1
    for mnem in sorted(by_mnem):
        counts = by_mnem[mnem]
        total = sum(counts.values())
        if list(counts) == [None]:
            print(f"    {total:3d}  {mnem}")
            continue
        values = ", ".join(
            f"{value:#04x} x{n}" for value, n in
            sorted(counts.items(), key=lambda kv: (kv[0] is None, kv[0])))
        print(f"    {total:3d}  {mnem:16s} {values}")
    if sites:
        for at in sorted(hits):
            hit = hits[at]
            imm = "" if hit["imm"] is None else f" {hit['imm']:#04x}"
            print(f"      {at:06X}  {hit['kind']:2s} {hit['mnem']:16s}"
                  f" {hit['seg']}[{hit['rm']}+{offset:#x}]{imm}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("images", nargs="+", help="overlays or memory images")
    ap.add_argument("--offset", required=True, action="append",
                    help="a record offset, e.g. 0x0BF; repeatable")
    ap.add_argument("--sites", action="store_true",
                    help="list every site, not just the histogram")
    args = ap.parse_args(argv)
    images = {p: pathlib.Path(p).read_bytes() for p in args.images}
    for name in images:
        print(f"# {name}")
    print()
    for text in args.offset:
        report(images, int(text, 0), args.sites)
    return 0


if __name__ == "__main__":
    sys.exit(main())
