#!/usr/bin/env python3
"""What a DOS Gold Box engine's *save* routine writes, region by region.

    tools/dossavewritemap.py                     # every title the archives hold
    tools/dossavewritemap.py --game CURSE
    tools/dossavewritemap.py --path /some/GAME.OVR --check

Each of the first three titles saves with one Turbo Pascal `BlockWrite` per
region, in file order, and the whole chain sits in one basic block.  So the
file map is not inferred from a specimen at all -- it is read off the calls:
the first `BlockWrite` starts at file offset 0 and each one after it starts
where the last ended.  That is what settled `#253`, where the square block's
first byte had been placed twelve bytes late.

The chain is found by its shape rather than by a hardcoded address.  A save
`BlockWrite` compiles to `xor ax, ax; push ax; push ax; lcall seg:off` -- the
`var Result` argument passed as `NIL` -- where the *load* side passes a real
`var` and so pushes `ss:di` instead.  The longest run of those calls whose
widths add up to one of `goldbox.dos_savegame`'s container sizes is the save
routine, and a title whose chain does not add up prints nothing rather than
a plausible map.

`--check` compares the map against `DosSaveShape` and exits non-zero on a
disagreement, which is what `tests/test_dossavewritemap.py` runs.

Prints file offsets, widths and the data-segment address each region is
copied from.  No game bytes are written anywhere and none are printed.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_savegame as sg  # noqa: E402
from tools import dosbox  # noqa: E402

#: `xor ax, ax; push ax; push ax; lcall` -- `BlockWrite(..., NIL)`.
WRITE_CALL = re.compile(rb"\x31\xc0\x50\x50\x9a....", re.DOTALL)
#: How far apart two calls may be and still count as one chain.  The widest
#: real gap is the character-name loop, about 260 bytes in Silver Blades.
CHAIN_GAP = 400

#: The titles this understands, as the stem `tools/dosbox.py` finds them by.
GAMES = ("POOLRAD", "CURSE", "SECRET")


class _Immediate:
    """`mov ax, 5` and `mov ax, 0x148` both, since capstone prints a small
    constant in decimal and a large one in hex."""

    _pat = re.compile(r"^(\w+), (0x[0-9a-f]+|\d+)$")

    def match(self, reg: str, op: str) -> bool:
        m = self._pat.match(op)
        return bool(m and m.group(1) == reg)

    def value(self, reg: str, op: str) -> int:
        m = self._pat.match(op)
        assert m and m.group(1) == reg
        return int(m.group(2), 0)


IMMEDIATE = _Immediate()


class Region:
    """One `BlockWrite`: where it lands, how wide, and what it copies."""

    def __init__(self, at: int, width: int, source: str, times: int = 1,
                 site: int = 0):
        self.at, self.width, self.source, self.times = at, width, source, times
        #: The `lcall`'s own file offset, which is how a loop's body is told
        #: from the calls around it.
        self.site = site

    @property
    def total(self) -> int:
        return self.width * self.times


def _chains(image: bytes) -> list[list[int]]:
    """Runs of save-side `BlockWrite` calls, by file offset of the `lcall`."""
    hits = [m.start() + 4 for m in WRITE_CALL.finditer(image)]
    out: list[list[int]] = []
    for off in hits:
        if out and off - out[-1][-1] <= CHAIN_GAP:
            out[-1].append(off)
        else:
            out.append([off])
    return out


def _decode(image: bytes, start: int, end: int):
    """Instructions from `start` to `end`, aligned so `start` is a boundary.

    An overlay has no entry point to walk from, so the alignment is chosen:
    back up until a decode puts an instruction boundary on `start`, exactly
    as `tools/dosdis16.py` does.
    """
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    begin = start
    for back in range(0, 64):
        if any(i.address == start
               for i in md.disasm(image[start - back:start + 8], start - back)):
            begin = start - back
    return list(md.disasm(image[begin:end + 16], begin))


def write_map(image: bytes, chain: list[int]) -> list[Region]:
    """The regions one chain of `BlockWrite` calls emits, in file order.

    Walks the instructions between the first and last call, tracking the
    source and count each call is about to be given, and multiplies a run
    that sits inside a counted loop by that loop's trip count.
    """
    body = _decode(image, chain[0] - 64, chain[-1] + 8)
    source, width, limit = "?", 0, None
    regions: list[Region] = []
    loops: list[tuple[int, int, int]] = []
    for ins in body:
        m, op = ins.mnemonic, ins.op_str
        if m == "mov" and IMMEDIATE.match("ax", op):
            width = IMMEDIATE.value("ax", op)
        elif m == "mov" and IMMEDIATE.match("di", op):
            source = f"DS:0x{IMMEDIATE.value('di', op):04X}"
        elif m == "add" and IMMEDIATE.match("di", op):
            source = f"DS:0x{IMMEDIATE.value('di', op):04X} + 4*i"
        elif m == "les" and "ptr [0x" in op:
            source = f"[DS:0x{int(op.split('ptr [0x')[1].rstrip(']'), 16):04X}]^"
        elif m == "lea" and op.startswith("di, [bp"):
            source = f"stack {op[4:]}"
        elif m == "cmp" and op.startswith("byte ptr [bp") and ", " in op:
            limit = int(op.rsplit(", ", 1)[1], 0)
        elif m == "jne" and int(op, 16) < ins.address and limit:
            loops.append((int(op, 16), ins.address, limit))
            limit = None
        elif ins.address in chain:
            regions.append(Region(0, width, source, site=ins.address))
            source, width = "?", 0

    # A counted loop runs its body once per value of the counter, which these
    # start at 1 and compare against the limit, so the limit is the trip
    # count.  Everything written inside it lands that many times.
    # Its calls interleave -- iteration 1 writes both, then iteration 2 -- so
    # the body's regions are one region of the summed width, not two apart.
    for back, end, trips in loops:
        inside = [r for r in regions if back <= r.site <= end]
        if not inside:
            continue
        merged = Region(0, sum(r.width for r in inside),
                        " + ".join(r.source for r in inside), trips,
                        site=inside[0].site)
        regions[regions.index(inside[0]):
                regions.index(inside[-1]) + 1] = [merged]
    run = 0
    for r in regions:
        r.at, run = run, run + r.total
    return regions


def square_region(regions: list[Region]) -> "Region | None":
    """The `BlockWrite` that emits x, y and the facing.

    Named by its place in the chain rather than by an index, because Silver
    Blades has one region fewer than the others: it is the first one written
    from a plain data-segment address after the last of the heap blocks the
    variable array and the staged script live in.
    """
    heap = [n for n, r in enumerate(regions) if r.source.endswith("]^")]
    if not heap:
        return None
    after = regions[heap[-1] + 1:]
    return after[0] if after else None


def title_of(regions: list[Region]) -> "sg.DosSaveShape | None":
    """The shape whose size the chain's widths add up to, or None."""
    total = sum(r.total for r in regions)
    return sg.SAVE_SHAPES_BY_SIZE.get(total)


def save_chain(image: bytes) -> tuple[list[Region], "sg.DosSaveShape | None"]:
    """The save routine's regions, picked out of every candidate chain."""
    best: list[Region] = []
    shape = None
    for chain in _chains(image):
        if len(chain) < 6:
            continue
        regions = write_map(image, chain)
        found = title_of(regions)
        if found and len(regions) > len(best):
            best, shape = regions, found
    return best, shape


def report(name: str, regions: list[Region],
           shape: "sg.DosSaveShape | None") -> list[str]:
    """The printed map, and the lines a `--check` disagreement produces."""
    print(f"=== {name}")
    if not shape:
        print("  no BlockWrite chain here adds up to a known container size")
        return [f"{name}: no save chain found"]
    print(f"  {shape.title}, {shape.size} bytes")
    print(f"  {'offset':>7}  {'bytes':>6}  source")
    for r in regions:
        times = f" x{r.times}" if r.times > 1 else ""
        print(f"  {r.at:>7}  {r.total:>6}  {r.source}{times}")
    block = square_region(regions)
    x = block.at if block else -1
    print(f"  x is written at file offset {x}; the shape says {shape.pos_x}")
    bad = []
    if x != shape.pos_x:
        bad.append(f"{shape.key}: the writer puts x at {x}, "
                   f"the shape says {shape.pos_x}")
    if regions[-1].at != shape.party_table:
        bad.append(f"{shape.key}: the writer puts the character table at "
                   f"{regions[-1].at}, the shape says {shape.party_table}")
    if regions[-2].at != shape.party_table - 1:
        bad.append(f"{shape.key}: the writer puts the party size at "
                   f"{regions[-2].at}, the shape says {shape.party_table - 1}")
    return bad


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", action="append",
                    help=f"a title stem; default all of {', '.join(GAMES)}")
    ap.add_argument("--path", help="a GAME.OVR to read instead")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if a map disagrees with its shape")
    args = ap.parse_args(argv)

    paths = []
    if args.path:
        paths.append(pathlib.Path(args.path))
    else:
        for stem in args.game or GAMES:
            try:
                paths.append(dosbox.find_game(stem) / "GAME.OVR")
            except FileNotFoundError as bad:
                print(f"=== {stem}\n  {bad}")
    bad: list[str] = []
    for path in paths:
        if not path.is_file():
            print(f"=== {path}\n  no such file")
            continue
        regions, shape = save_chain(path.read_bytes())
        bad += report(path.parent.name, regions, shape)
    for line in bad:
        print(f"MISMATCH {line}")
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
