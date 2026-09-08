#!/usr/bin/env python3
"""Read a running Amiga Gold Box title: where the party is, and its map.

`automap/amiga.py` is the backend; this is the command line that drives it and
the thing to reach for when an address stops answering.  Five commands:

    tools/amigatarget.py --holder wish37 verify --adf work/issue37/ssb-A.adf
    tools/amigatarget.py --holder wish37 locate
    tools/amigatarget.py --holder wish37 fix
    tools/amigatarget.py --holder wish37 geo --out work/issue37/geo.bin \\
        --library work/issue37/GEO.GLB
    tools/amigatarget.py --holder wish37 automap --out work/issue37/run \\
        --polls 6 --walk 'NP8 NP4 NP8'

**`automap` is the one that answers this ticket**: it builds the shipped
`automap.state.Automapper` over this backend, hands it the title's own maps
off the player's Amiga disk, polls it, presses the keypad between polls and
writes the map the shipped renderer draws.  Nothing in it re-derives a
position, an area or a wall -- a pass says the automapper works on an Amiga,
not that this file can read one.

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
    """A loose `GEO.GLB` as `{id: 1024 bytes}`.

    `automap.amiga.geo_library` is the parse; this only opens the file.  The
    tool and the shipped backend must not disagree about what a block id is,
    so there is one reader and this is a caller of it.
    """
    return amiga.geo_library(path.read_bytes())


def find_maps(layout: amiga.AmigaLayout,
              where: str | None = None) -> tuple[dict, pathlib.Path | None]:
    """The title's maps, off a disk image the player already has.

    `where` is a disk image, a folder of them, or None -- in which case every
    directory `tools/gamedisks.py` lists for the Amiga is searched for an
    image whose name carries the title's own word.  The maps come back keyed
    `GEO{id:02X}`, which is the C64's own filename for the same area, so an
    Amiga run draws on the same sheet and reads the same notes.
    """
    if where:
        path = pathlib.Path(where)
        if path.is_dir():
            return amiga.load_maps_in(path)
        return amiga.load_maps(path), path
    from tools import gamedisks
    want = layout.title.split()[-1].lower()          # "blades", "bonds"
    for root in gamedisks.candidates("amiga"):
        if not root.is_dir():
            continue
        for image in sorted(root.rglob("*.adf")):
            if want not in image.name.lower().replace("_", ""):
                continue
            try:
                maps = amiga.load_maps(image)
            except Exception:
                continue
            if maps:
                return maps, image
    return {}, None


def draw(target, layout, args) -> int:
    """Run the shipped automapper against this machine, and draw what it draws.

    **The point is that nothing here re-derives anything.**
    `automap.state.Automapper.poll()` is what moves the marker,
    `automap.area.ResidentGeo` is what names the area, and
    `automap.render.to_svg` is what paints it -- the same three the window
    runs on a C64.  This file supplies the target, the maps and the keystrokes
    and reads the answer back out of the mapper's own state, so a run that
    passes says the shipped code works on an Amiga rather than that this tool
    can read an Amiga.

    One JSON line per poll as it happens, because a driven run that dies
    half-way must still say what it had measured -- and a WinUAE poll is
    fifteen to twenty-two seconds, so a run of ten is long enough to be
    interrupted.
    """
    from automap import state as mapstate

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # The player's own notes and explored squares live in `automap.paths.
    # data_dir()`; a driven run must not write into them. Rebound here in the
    # function rather than at import, which is `tools/livecheck.py`'s rule and
    # `#428`'s incident: a test that imports this module would otherwise
    # import the rebinding with it -- and put back on the way out, because a
    # test that *calls* this would otherwise leave every later test in the
    # same worker reading one shared notes directory, which is the other half
    # of that same incident (`tests/conftest.py` fails a test that does).
    was = mapstate._data_dir                            # noqa: SLF001
    mapstate._data_dir = lambda: out / "data"           # noqa: SLF001
    try:
        return _draw(target, layout, args, out)
    finally:
        mapstate._data_dir = was                        # noqa: SLF001


def _draw(target, layout, args, out: pathlib.Path) -> int:
    """`draw`'s body, with the notes directory already redirected."""
    from automap import render
    from automap.state import Automapper

    maps, image = find_maps(layout, args.maps)
    if not maps:
        raise SystemExit("no Amiga disk image carrying GEO.GLB for "
                         f"{layout.title}; pass --maps")
    print(f"Maps       {len(maps)} from {image}")

    log = (out / "automap.jsonl").open("a", encoding="utf-8")

    def note(**payload) -> None:
        payload["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(payload) + "\n")
        log.flush()

    note(event="start", title=layout.title, data_base=target.data_base,
         maps=sorted(maps), image=str(image))
    mapper = Automapper(target, maps, title=layout.title)
    walk = [k for k in (args.walk or "").replace(",", " ").split() if k]
    steps = 0

    for i in range(args.polls):
        started = time.monotonic()
        changed = mapper.poll()
        st = mapper.state
        row = dict(event="poll", i=i, seconds=round(time.monotonic() - started, 1),
                   changed=changed, area=st.area, x=st.x, y=st.y,
                   facing=st.facing, source=st.source, title=mapper.title_check,
                   candidates=str(st.candidates) if st.candidates else None,
                   seen=len(st.exploration.seen))
        note(**row)
        print(f"poll {i:2d}  {row['seconds']:5.1f}s  {st.area or '-':6} "
              f"{st.x},{st.y} {'NESW'[st.facing] if st.facing is not None else '?'}"
              f"  seen {row['seen']:3d}  {row['candidates']}")
        if st.geo is not None:
            seen = set(st.exploration.seen)
            svg = render.to_svg(
                st.geo, visible=(lambda x, y: (x, y) in seen) if seen else None,
                party=(st.x, st.y, st.facing or 0), notes=st.notes or None)
            (out / f"poll{i:02d}.svg").write_text(svg, encoding="utf-8")
        if args.globals:
            blob = target.read(target.data_base + args.globals_at, args.globals)
            (out / f"globals{i:02d}.bin").write_bytes(blob)
        if steps < len(walk):
            key = walk[steps]
            from tools import amigadrive
            amigadrive.press(args.holder, key, args.settle)
            note(event="key", i=i, key=key)
            print(f"          pressed {key}")
            steps += 1

    log.close()
    return 0


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
    raw = sub.add_parser("dump", help="any range of the running machine")
    raw.add_argument("--at", required=True, type=lambda s: int(s, 0),
                     help="an absolute address")
    raw.add_argument("--relative", action="store_true",
                     help="--at is a data-hunk offset instead")
    raw.add_argument("--length", required=True, type=lambda s: int(s, 0))
    raw.add_argument("--out", required=True, help="write the bytes here")
    mapped = sub.add_parser("automap",
                            help="run the shipped automapper and draw its map")
    mapped.add_argument("--out", required=True,
                        help="a directory for the SVGs, the log and the notes")
    mapped.add_argument("--maps", help="an .adf, or a folder of them; by "
                                       "default the Amiga disks are searched")
    mapped.add_argument("--polls", type=int, default=3,
                        help="how many times to poll (default 3)")
    mapped.add_argument("--walk", default="",
                        help="keys to press between polls, e.g. 'NP8 NP4 NP8'")
    mapped.add_argument("--settle", type=float, default=2.0,
                        help="seconds to wait after each key")
    mapped.add_argument("--globals", type=int, default=0,
                        help="also dump this many bytes of the data hunk each "
                             "poll, for a differential against the next")
    mapped.add_argument("--globals-at", type=lambda s: int(s, 0), default=0,
                        help="where that dump starts, as a data-hunk offset")
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

    if args.command == "automap":
        return draw(target, layout, args)

    if args.command == "dump":
        at = target.data_base + args.at if args.relative else args.at
        blob = target.read(at, args.length)
        pathlib.Path(args.out).write_bytes(blob)
        print(f"{len(blob)} bytes from {at:#010x} to {args.out}")
        return 0

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
