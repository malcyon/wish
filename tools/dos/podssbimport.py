#!/usr/bin/env python3
"""Which Silver Blades field lands in which Pools of Darkness field when DOS
Pools of Darkness imports a character, read from the importer's own `Move`
calls in `GAME.OVR`.

    tools/dos/podssbimport.py            # the copies, and every misaligned byte
    tools/dos/podssbimport.py --census   # plus same-named records on this machine

The importer reads a 439-byte (`0x1B7`) Silver Blades record into a heap
buffer with `BlockRead`, then copies it into the Pools of Darkness record with
a run of `Move(buffer + a, record + b, n)` calls, each argument an immediate.
This script finds the `BlockRead` by its count, collects every `Move` up to
the `FreeMem` of the same size, and walks each copy byte by byte through both
titles' layouts in `goldbox/dos_port.py`.  A destination byte whose source
field has a different name is printed: that is where the importer carries one
field into another, as with Silver Blades' `attack_level` landing in spell
id 118's byte.

Everything is found by instruction structure rather than a committed address.
Archives are opened read only.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import dos_port  # noqa: E402
from tools.dos import dosbox, dospod  # noqa: E402

SSB_RECORD = 0x1B7
POD_RECORD = 0x1FE

#: `mov ax, 0x1b7 ; push ax ; lcall` -- the count pushed for the `BlockRead`
#: and, later, for the `FreeMem` of the same buffer.
_COUNT = re.compile(rb"\xb8\xb7\x01\x50\x9a", re.S)

#: `les di,[bp-X]` (the buffer) with an optional `add di,a`, `push es:di`,
#: then `les di,[bp+Y]` (the record) with an optional `add di,b`, `push es:di`,
#: `mov ax,n ; push ax ; lcall seg:off`.
_MOVE = re.compile(
    rb"\xc4\xbe..(?:\x81\xc7(..))?\x06\x57"
    rb"\xc4\x7e.(?:\x81\xc7(..))?\x06\x57"
    rb"\xb8(..)\x50\x9a(....)", re.S)


def importer_moves(ovr: bytes) -> list[tuple[int, int, int, int]]:
    """`(site, source offset, destination offset, count)` for each copy."""
    counts = [m.start() for m in _COUNT.finditer(ovr)]
    for start, end in zip(counts, counts[1:]):
        if end - start > 0x400:
            continue
        moves = []
        for m in _MOVE.finditer(ovr, start, end):
            src = struct.unpack("<H", m.group(1))[0] if m.group(1) else 0
            dst = struct.unpack("<H", m.group(2))[0] if m.group(2) else 0
            moves.append((m.start(), src, dst,
                          struct.unpack("<H", m.group(3))[0]))
        if len(moves) >= 5:
            return moves
    raise SystemExit("no Silver Blades importer found: no pair of 0x1B7 "
                     "counts with five Move calls between them")


def field_at(layout, offset: int) -> tuple[str, int]:
    """The field holding `offset`, and the byte's index inside it."""
    for f in layout:
        if f.offset <= offset < f.offset + f.size:
            return f.name, offset - f.offset
    return "?", 0


def misaligned(moves):
    """Destination bytes whose source is a differently named field."""
    ssb = dos_port.layout_for(dos_port.SECRET_OF_THE_SILVER_BLADES)
    pod = dos_port.layout_for(dos_port.POOLS_OF_DARKNESS)
    for _site, src, dst, count in moves:
        for i in range(count):
            s, si = field_at(ssb, src + i)
            d, di = field_at(pod, dst + i)
            if s != d and not (s.startswith("gap_") and d.startswith("gap_")):
                yield src + i, s, si, dst + i, d, di


def records(root: pathlib.Path, folder: str, size: int) -> dict[str, bytes]:
    """The first record of `size` bytes per character name under `folder`."""
    found: dict[str, bytes] = {}
    for path in sorted(root.glob(f"*/games/{folder}/**/CHRDAT*.SAV")):
        data = path.read_bytes()
        if len(data) == size:
            found.setdefault(data[1:1 + data[0]].decode("latin-1"), data)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--census", action="store_true",
                    help="compare same-named Silver Blades and Pools records")
    args = ap.parse_args(argv)
    ovr = (dospod.find_game() / "GAME.OVR").read_bytes()
    moves = importer_moves(ovr)
    print("GAME.OVR Move(ssb+a, pod+b, n):")
    for site, src, dst, count in moves:
        print(f"  0x{site:06X}  ssb 0x{src:03X}-0x{src + count - 1:03X}"
              f"  ->  pod 0x{dst:03X}-0x{dst + count - 1:03X}  ({count})")
    rows = list(misaligned(moves))
    print("\nbytes copied into a differently named field:")
    for s_off, s, si, d_off, d, di in rows:
        print(f"  ssb 0x{s_off:03X} {s}[{si}]  ->  pod 0x{d_off:03X} {d}[{di}]")
    if args.census:
        ssb = records(dosbox.ARCHIVES, "SECRET", SSB_RECORD)
        pod = records(dosbox.ARCHIVES, "Pools of Darkness", POD_RECORD)
        print("\nsame-named records (read only; no chain of custody):")
        for name in sorted(set(ssb) & set(pod)):
            cells = " ".join(f"0x{d_off:03X}:{ssb[name][s_off]}->"
                             f"{pod[name][d_off]}"
                             for s_off, _s, _si, d_off, _d, _di in rows)
            print(f"  {name:16} {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
