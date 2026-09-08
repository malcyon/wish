#!/usr/bin/env python3
"""Read a running Amiga Gold Box title: where the party is, and its map.

`automap/amiga.py` is the backend; this is the command line that drives it and
the thing to reach for when an address stops answering.  Four commands:

    tools/amigatarget.py --holder wish37 verify --adf work/issue37/ssb-A.adf
    tools/amigatarget.py --holder wish37 locate
    tools/amigatarget.py --holder wish37 fix
    tools/amigatarget.py --holder wish37 geo --out work/issue37/geo.bin \\
        --library work/issue37/GEO.GLB

**`verify` needs no emulator at all**, and it is the one to run first: it opens
the title's executable on the player's own disk and checks that
`automap.amiga.LAYOUTS` still describes it -- that the anchor string is where
the table says, that it appears exactly once, and that the party globals and
the `GEO` pointer are inside the data hunk the loader allocates.  A release
this project has not seen fails there rather than silently reading the wrong
bytes on a live machine.

The other three need WinUAE running the title with a party in the world, and a
lane claim.  **Take the claim yourself and release it at the end** --

    winvm ssh 'powershell -NoProfile -ExecutionPolicy Bypass -File
        C:\\Amiga\\winuae.ps1 claim -Holder wish37'

-- because a claim that ends with the process that took it cannot be handed
between the several runs one experiment needs.  `tools/amigadrive.py` made the
same choice for the same reason.

Every command that reads the machine **measures the data hunk's address first**
and prints it.  Nothing is assumed: AmigaDOS relocates on every `LoadSeg`, so
an address written down on Monday is wrong on Tuesday.

Nothing here writes to the player's disks.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from automap import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from tools.amiga68k import Executable  # noqa: E402

#: The small-data base SAS/Lattice links these two titles with: `a4` is the
#: data hunk plus this.  `tools/amiga68k.py` has it as `SMALL_DATA_BIAS`; it is
#: repeated in the printout rather than imported into `automap/`, which must
#: not depend on `tools/`.
A4_BIAS = 0x7FFE


def executable(adf: pathlib.Path, layout: amiga.AmigaLayout) -> bytes:
    return AmigaDisk.open(str(adf)).read_file(layout.executable)


def verify(layout: amiga.AmigaLayout, adf: pathlib.Path) -> list[str]:
    """Check the table against the executable.  Returns the failures.

    Empty means every claim in the row is true of this build.  This is the
    check that catches a different release, which is the failure mode a live
    reading cannot tell from a game that is merely between areas.
    """
    exe = Executable.parse(executable(adf, layout))
    data = [h for h in exe.hunks if h.kind == "DATA"]
    bad: list[str] = []
    if len(data) != 1:
        return [f"{len(data)} data hunks, so there is no single small-data "
                "base and this layout does not describe this build"]
    hunk = data[0]
    blob = exe.data[hunk.file_offset:hunk.file_offset + hunk.size]
    hits = [i for i in range(len(blob))
            if blob.startswith(layout.anchor, i)]
    if hits != [layout.anchor_offset]:
        bad.append(f"{layout.anchor!r} is at "
                   + (", ".join(f"{h:#x}" for h in hits) or "no offset")
                   + f" in the data hunk, not {layout.anchor_offset:#x}")
    for name in ("party_x", "party_y", "party_facing", "geo_pointer"):
        offset = getattr(layout, name)
        if not 0 <= offset < hunk.allocated:
            bad.append(f"{name} {offset:#x} is outside the {hunk.allocated:#x} "
                       "bytes the loader allocates for this hunk")
        elif offset < hunk.size:
            bad.append(f"{name} {offset:#x} is in the hunk's *initialised* "
                       f"bytes (below {hunk.size:#x}); these globals are BSS")
    return bad


def connect(holder: str, layout: amiga.AmigaLayout,
            timeout: float | None) -> amiga.AmigaTarget:
    debugger = amiga.WinuaeDebugger(holder, timeout=timeout)
    target = amiga.AmigaTarget(debugger, layout)
    started = time.monotonic()
    base = target.locate()
    print(f"Data hunk  {base:#010x}   a4 {base + A4_BIAS:#010x}   "
          f"({time.monotonic() - started:.1f}s)")
    return target


def geo_library(path: pathlib.Path) -> dict[int, bytes]:
    """`GEO.GLB` as `{id: 1024 bytes}`.

    Block 0 is the index -- a `u16be` count and then that many `(id, block)`
    pairs -- and the rest are the maps.  `tools/amigaenum.py`'s `glib_blocks`
    parses the container; the index is this library's own shape.
    """
    from tools.amigaenum import glib_blocks
    blocks = glib_blocks(path.read_bytes())
    index = blocks[0]
    count = int.from_bytes(index[:2], "big")
    out = {}
    for i in range(count):
        at = 2 + 4 * i
        ident = int.from_bytes(index[at:at + 2], "big")
        block = int.from_bytes(index[at + 2:at + 4], "big")
        if block < len(blocks):
            out[ident] = blocks[block]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--holder", help="the winuae.ps1 lane claim this run "
                                         "holds; every live command needs one")
    parser.add_argument("--title", default="secret-of-the-silver-blades",
                        choices=sorted(amiga.LAYOUTS),
                        help="which title is running")
    parser.add_argument("--timeout", type=float, default=None,
                        help="seconds to wait for one guest round trip")
    parser.add_argument("--json", help="write the reading here as well")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify", help="check the table against a disk")
    check.add_argument("--adf", required=True)
    sub.add_parser("locate", help="measure the data hunk's load address")
    sub.add_parser("fix", help="where the party is standing")
    dump = sub.add_parser("geo", help="the resident 1024-byte map")
    dump.add_argument("--out", help="write the block here")
    dump.add_argument("--library", help="a GEO.GLB to identify it against")
    args = parser.parse_args(argv)

    layout = amiga.LAYOUTS[args.title]
    if args.command == "verify":
        bad = verify(layout, pathlib.Path(args.adf))
        for line in bad:
            print(f"MISMATCH  {line}")
        if not bad:
            print(f"{layout.title}: the table describes this build -- "
                  f"{layout.anchor!r} at {layout.anchor_offset:#x}, "
                  f"party at {layout.party_x:#x}, "
                  f"GEO pointer at {layout.geo_pointer:#x}")
        return 1 if bad else 0

    if not args.holder:
        raise SystemExit("--holder is required for anything that reads the "
                         "machine: take the winuae.ps1 claim first")
    target = connect(args.holder, layout, args.timeout)
    reading: dict = {"title": args.title, "data_base": target.data_base}

    if args.command == "fix":
        fix = target.fix()
        reading["fix"] = None if fix is None else {
            "x": fix.x, "y": fix.y, "facing": fix.facing}
        print("No fix: the party is not standing on a square the engine "
              "recognises (a menu, camp, or a load in flight)" if fix is None
              else f"Party {fix.x},{fix.y} facing {fix.facing} "
                   f"({'NESW'[fix.facing]})")
    elif args.command == "geo":
        addr = target.resident_geo_address()
        reading["geo_address"] = addr
        if addr is None:
            print("No map is resident: the GEO pointer holds no address")
        else:
            block = target.read(addr, 0x400)
            print(f"Resident map at {addr:#010x}, {len(block)} bytes")
            if args.out:
                pathlib.Path(args.out).write_bytes(block)
                print(f"Written to {args.out}")
            if args.library:
                library = geo_library(pathlib.Path(args.library))
                same = [i for i, b in library.items() if b == block]
                reading["geo_id"] = same[0] if len(same) == 1 else None
                print(f"Identified as GEO id {same[0]} ({same[0]:#x})"
                      if len(same) == 1 else
                      f"Matches {len(same)} of {len(library)} library blocks")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(reading, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
