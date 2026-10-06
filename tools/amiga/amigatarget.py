#!/usr/bin/env python3
"""Read a running Amiga Gold Box title: where the party is, and its map.

`automap/amiga.py` is the backend; this is the command line that drives it and
the thing to reach for when an address stops answering.  Five commands
(`party`, `pool`, `poke` and `select` are below):

    tools/amiga/amigatarget.py --holder wish37 verify --adf SSB-A.adf
    tools/amiga/amigatarget.py --holder wish37 locate
    tools/amiga/amigatarget.py --holder wish37 fix
    tools/amiga/amigatarget.py --holder wish37 geo --out geo.bin \\
        --library GEO.GLB
    tools/amiga/amigatarget.py --holder wish37 automap --out DIR \\
        --polls 6 --walk 'NP8 NP4 NP8'

`party`, `pool` and `poke --at ADDR --hex BYTES` go over WinUAE's own pipe
(`automap.amiga.WinuaePipe`) and print one JSON row, as the FS-UAE `session`
verbs of the same names do.

`select MEMBER` moves the game's own highlight to a member, by name or 1-based
party line, with the key the party menu and the camp both read (`NEXT_MEMBER`),
and reads the current-member pointer back after every press; `V` then shows
that member's sheet:

    tools/amiga/amigatarget.py --holder wish1 select EPONA
    tools/amiga/amigadrive.py --holder wish1 keys V

**`automap` is the one that answers this ticket**: it builds the shipped
`automap.state.Automapper` over this backend, hands it the title's own maps
off the player's Amiga disk, polls it, presses the keypad between polls and
writes the map the shipped renderer draws.  Nothing in it re-derives a
position, an area or a wall -- a pass says the automapper works on an Amiga,
not that this file can read one.

**`verify` needs no emulator at all**, and it is the one to run first: it opens
the title's executable on the player's own disk and checks that
`automap.amiga.MACHINES` still describes it -- that the anchor string is where
the table says, that it appears exactly once, and that the party globals and
the `GEO` pointer are inside the data hunk the loader allocates.  A release
this project has not seen fails there rather than silently reading the wrong
bytes on a live machine.

The other three need WinUAE running the title with a party in the world, and a
lane claim.  **Take the claim yourself and release it at the end** --

    winvm ssh 'powershell -NoProfile -ExecutionPolicy Bypass -File
        C:\\Amiga\\winuae.ps1 claim -Holder wish37'

-- because a claim that ends with the process that took it cannot be handed
between the several runs one experiment needs.  `tools/amiga/amigadrive.py` made the
same choice for the same reason.

Every command that reads the machine **measures the data hunk's address first**
and prints it.  Nothing is assumed: AmigaDOS relocates on every `LoadSeg`, so
an address written down on Monday is wrong on Tuesday.

Nothing here writes to the player's disks.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from automap import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from tools.amiga.amiga68k import Executable  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: The small-data base SAS/Lattice links these two titles with: `a4` is the
#: data hunk plus this.  `tools/amiga/amiga68k.py` has it as `SMALL_DATA_BIAS`; it is
#: repeated in the printout rather than imported into `automap/`, which must
#: not depend on `tools/`.
A4_BIAS = 0x7FFE


def executable(adf: pathlib.Path, layout: amiga.AmigaMachine) -> bytes:
    return AmigaDisk.open(str(adf)).read_file(layout.executable)


def verify(layout: amiga.AmigaMachine, adf: pathlib.Path) -> list[str]:
    """Check the table against the executable.  Returns the failures.

    Empty means every claim in the row is true of this build.  This is the
    check that catches a different release, which is the failure mode a live
    reading cannot tell from a game that is merely between areas.

    It covers only the fields that are offsets into a hunk. Fields reached
    through a pointer at run time (a travel-grid block's x, y and indoors word,
    `overland_flag`) are not in the file and are not checked here.
    """
    exe = Executable.parse(executable(adf, layout))
    if layout.segments is not None:
        return _verify_segments(layout, exe)
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


def _verify_segments(layout: amiga.AmigaMachine, exe: Executable) -> list[str]:
    """`verify` for a many-hunk build: the anchor in one hunk, the data in
    another, and the code reaching the data through absolute relocations."""
    seg = layout.segments
    bad: list[str] = []
    try:
        anchor_hunk = exe.by_number(seg.anchor_hunk)
        data_hunk = exe.by_number(seg.data_hunk)
    except KeyError as exc:
        return [f"the executable has no hunk {exc.args[0]}"]
    if seg.data_hunk <= seg.anchor_hunk:
        bad.append(f"hunk {seg.data_hunk} does not come after hunk "
                   f"{seg.anchor_hunk}")
    for hunk, size in ((anchor_hunk, seg.anchor_size),
                       (data_hunk, seg.data_size)):
        if hunk.allocated != size:
            bad.append(f"hunk {hunk.number} allocates {hunk.allocated:#x} "
                       f"bytes, not {size:#x}")
    if anchor_hunk.file_offset is None:
        bad.append(f"hunk {seg.anchor_hunk} has no bytes to hold the anchor")
    else:
        found = [i for i in range(len(exe.data))
                 if exe.data.startswith(layout.anchor, i)]
        want = anchor_hunk.file_offset + layout.anchor_offset
        if found != [want]:
            bad.append(f"{layout.anchor!r} is at "
                       + (", ".join(f"{h:#x}" for h in found) or "no offset")
                       + f" in the file, not {want:#x} (hunk {seg.anchor_hunk}"
                       f" + {layout.anchor_offset:#x})")
    # A BSS hunk has no initialised bytes: every global in it is zero-filled.
    initialised = 0 if data_hunk.kind == "BSS" else data_hunk.size
    offsets = {name: getattr(layout, name) for name in
               ("party_x", "party_y", "party_facing", "geo_pointer")}
    grid = layout.travel_grid
    if grid is not None:
        offsets.update(view=grid.view, area=grid.area,
                       block_pointer=grid.block_pointer)
    for name, offset in offsets.items():
        if not 0 <= offset < data_hunk.allocated:
            bad.append(f"{name} {offset:#x} is outside the "
                       f"{data_hunk.allocated:#x} bytes the loader allocates "
                       f"for hunk {seg.data_hunk}")
        elif offset < initialised:
            bad.append(f"{name} {offset:#x} is in the hunk's *initialised* "
                       f"bytes (below {initialised:#x}); these globals are BSS")
    pointed = [(number, at) for (number, at), target in exe.relocs.items()
               if target == seg.data_hunk
               and exe.by_number(number).kind == "CODE"
               and int.from_bytes(exe.data[exe.by_number(number).file_offset
                                           + at:][:4], "big")
               == layout.geo_pointer]
    if not pointed:
        bad.append(f"no code hunk relocates a longword to hunk "
                   f"{seg.data_hunk} + {layout.geo_pointer:#x}")
    return bad


def connect(holder: str, layout: amiga.AmigaMachine,
            timeout: float | None) -> amiga.AmigaTarget:
    return _located(amiga.AmigaTarget(
        amiga.WinuaeDebugger(holder, timeout=timeout), layout))


def connect_pipe(holder: str, layout: amiga.AmigaMachine) -> amiga.AmigaTarget:
    """A located target over WinUAE's own pipe: it stops nothing, and a write
    goes through `AmigaTarget.write`.  The data hunk line goes to stderr so
    stdout is the JSON row alone.

    The machine's own memory regions are measured first and swept and checked
    against, as the automap does: a WinUAE machine with fast RAM and no slow
    RAM holds the game outside `amiga.MEMORY`."""
    target = amiga.AmigaTarget(amiga.WinuaePipe(holder=holder), layout)
    target.memory = amiga.memory_regions(target.read)
    return _located(target, sys.stderr)


def _located(target: amiga.AmigaTarget, out=None) -> amiga.AmigaTarget:
    started = time.monotonic()
    base = target.locate()
    print(f"Data hunk  {base:#010x}   a4 {base + A4_BIAS:#010x}   "
          f"({time.monotonic() - started:.1f}s)", file=out or sys.stdout)
    return target


#: The most a `poke` writes in one call, the same limit as the FS-UAE verb.
POKE_LIMIT = 64


def poke_ranges(target: amiga.AmigaTarget,
                layout: amiga.AmigaMachine) -> list[tuple[int, int]]:
    """The `(start, end)` address ranges a poke may touch: each party record
    and the effect-node pool, both read from the running game."""
    from automap import amigaeffects, amigaparty
    from tools.amiga import fsuaegdb

    key = fsuaegdb.machine_key(layout)
    row = amigaparty.ROWS[key]
    ranges = [(m.address, m.address + row.record_size)
              for m in amigaparty.walk(target, row, target.data_base)
              if m.in_party]
    if key in amigaeffects.POOLS:
        # A descriptor that is not the title's pool narrows the range to the
        # party records rather than widening it to wherever it points.
        count, size, base, _ = amigaeffects.read_pool(target, key)
        try:
            amigaeffects.check_pool(target, key, count, size, base)
        except amigaeffects.EffectError:
            pass
        else:
            ranges.append((base, base + count * size))
    return ranges


def poke_journal(holder: str) -> pathlib.Path:
    """Where `holder`'s pokes are recorded, one JSON line each."""
    return scratch.cache_dir("amigatarget", f"poke-{holder}.jsonl")


def poke(target: amiga.AmigaTarget, layout: amiga.AmigaMachine, holder: str,
         address: int, data: bytes) -> dict:
    """Write `data` at `address` and say what was there and what is now.

    The row is the FS-UAE `poke` verb's: `address`, `old` and `new` as hex.
    An address outside the party and effect-pool records is an error row and
    nothing is written.  The address and old bytes reach the journal and
    stderr before the write, so a write that fails or was a mistake can be
    reversed; a failed write's row still carries the old bytes.
    """
    if not data:
        raise ValueError("poke wants at least one byte")
    if len(data) > POKE_LIMIT:
        raise ValueError(f"poke of {len(data)} bytes is over the "
                         f"{POKE_LIMIT}-byte limit")
    end = address + len(data)
    if not any(lo <= address and end <= hi
               for lo, hi in poke_ranges(target, layout)):
        return {"address": address,
                "error": f"{address:#x}..{end:#x} is outside every party "
                         "record and the effect pool"}
    old = target.read(address, len(data))
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "address": address,
             "old": old.hex(), "new": data.hex()}
    path = poke_journal(holder)
    scratch.ensure(path.parent)
    with path.open("a", encoding="utf-8") as journal:
        journal.write(json.dumps(entry) + "\n")
        journal.flush()
        os.fsync(journal.fileno())
    print(f"poke {json.dumps(entry)}", file=sys.stderr, flush=True)
    row = {"address": address, "old": old.hex()}
    try:
        target.write(address, data)
        new = target.read(address, len(data))
    except amiga.GuestError as exc:
        return {**row, "error": f"{type(exc).__name__}: {exc}"}
    row["new"] = new.hex()
    if new != data:
        row["error"] = "the bytes read back are not the ones written"
    return row


#: The key that moves the highlighted member to the next one on the party list,
#: wrapping from the last to the first. It is keypad 1, which the key reader
#: turns into `$105`. The party menu's key callback (file offsets of its
#: compares: `/Secret` `017B4C`, `/Curse` `0172F2`, `/Pools of Darkness`
#: `017820`) hands `$105` to the highlight mover as `$85` (next) and `$107`
#: (keypad 7) as `$87` (previous).
#: Only Pools of Darkness also takes `$104`, which cursor down and keypad 2 give,
#: so NP2 does not move the party menu's highlight in Silver Blades. Every camp
#: screen takes NP1 as well (`tools/amiga/route_camp.py`).
NEXT_MEMBER = "NP1"


def select(target: amiga.AmigaTarget, layout: amiga.AmigaMachine, want: str,
           press: Callable[[str], object], reads: int = 3,
           wait: Callable[[], object] = lambda: time.sleep(1.0)) -> dict:
    """Move the game's highlight to the member `want` with its own keys.

    `want` is a name (any case) or a 1-based party line. The highlight is the
    title's current-member pointer; from where it is, `NEXT_MEMBER` is pressed
    until the pointer names that member, and the pointer is read back after
    each press, up to `reads` times with `wait` between. A press that leaves
    it anywhere but on the next member stops the run with an error row:
    that screen does not move the highlight with this key.
    """
    from automap import amigaparty
    from tools.amiga import fsuaegdb

    row = amigaparty.ROWS[fsuaegdb.machine_key(layout)]
    members = [m for m in amigaparty.walk(target, row, target.data_base)
               if m.in_party]
    names = [m.name.strip() for m in members]
    if not members:
        return {"member": want, "error": "the party list is empty"}
    if want.isdigit():
        index = int(want) - 1 if 0 < int(want) <= len(members) else None
    else:
        folded = [n.casefold() for n in names]
        index = (folded.index(want.strip().casefold())
                 if want.strip().casefold() in folded else None)
    if index is None:
        return {"member": want, "error": f"no party member is {want!r}; "
                                         f"the party is {', '.join(names)}"}
    addresses = [m.address for m in members]

    def highlighted() -> int | None:
        raw = target.read(target.data_base + row.current, 4)
        address = int.from_bytes(raw, "big")
        return addresses.index(address) if address in addresses else None

    at = highlighted()
    if at is None:
        return {"member": names[index],
                "error": "the highlight is on no party member's record"}
    result = {"member": names[index], "line": index + 1,
              "address": hex(addresses[index]), "from": names[at], "presses": 0}
    while at != index:
        expected = (at + 1) % len(members)
        press(NEXT_MEMBER)
        result["presses"] += 1
        now = highlighted()
        for _ in range(reads - 1):
            if now != at:
                break
            wait()
            now = highlighted()
        if now != expected:
            where = "no party member" if now is None else names[now]
            return {**result, "error": f"after {NEXT_MEMBER} the highlight is "
                                       f"on {where}, not {names[expected]}: "
                                       f"this screen does not move it with "
                                       f"{NEXT_MEMBER}"}
        at = now
    return result


def geo_library(path: pathlib.Path) -> dict[int, bytes]:
    """A loose `GEO.GLB` as `{id: 1024 bytes}`.

    `automap.amiga.geo_library` is the parse; this only opens the file.  The
    tool and the shipped backend must not disagree about what a block id is,
    so there is one reader and this is a caller of it.
    """
    return amiga.geo_library(path.read_bytes())


def _titled_maps(folder: pathlib.Path) -> dict:
    """Maps kept in `geo.dax` rather than `GEO.GLB`, as Pool of Radiance does."""
    from automap import maps as automap_maps
    return automap_maps.load_maps_titled(str(folder))[0]


def find_maps(layout: amiga.AmigaMachine,
              where: str | None = None) -> tuple[dict, pathlib.Path | None]:
    """The title's maps, off a disk image the player already has.

    `where` is a disk image, a folder of them, or None -- in which case every
    directory `automap/gamedisks.py` lists for the Amiga is searched for an
    image whose name carries the title's own word.  The maps come back keyed
    `GEO{id:02X}`, which is the C64's own filename for the same area, so an
    Amiga run draws on the same sheet and reads the same notes.
    """
    if where:
        path = pathlib.Path(where)
        if path.is_dir():
            maps, image = amiga.load_maps_in(path)
            return (maps, image) if maps else (_titled_maps(path), None)
        return amiga.load_maps(path), path
    from automap import gamedisks
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
    # function rather than at import, which is `tools/gui/livecheck.py`'s rule and
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
            from tools.amiga import amigadrive
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
                        choices=sorted(amiga.MACHINES),
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
    sub.add_parser("party", help="every party member's record, as JSON "
                                 "(over WinUAE's pipe)")
    sub.add_parser("pool", help="the effect-node pool descriptor, as JSON "
                                "(over WinUAE's pipe)")
    poked = sub.add_parser("poke", help="write bytes into the running game "
                                        "(over WinUAE's pipe)")
    poked.add_argument("--at", required=True, type=lambda s: int(s, 0),
                       help="an absolute address")
    poked.add_argument("--hex", required=True, dest="digits",
                       help="the bytes to write, in hex")
    chosen = sub.add_parser("select", help="move the game's highlight to a "
                                           "member with its own keys (over "
                                           "WinUAE's pipe)")
    chosen.add_argument("member", help="a name, or a 1-based party line")
    chosen.add_argument("--settle", type=float, default=1.5,
                        help="seconds to wait after each key (default 1.5)")
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

    layout = amiga.MACHINES[args.title]
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
    if args.command in ("party", "pool", "poke", "select"):
        from automap import amigaeffects  # noqa: PLC0415
        from tools.amiga import fsuaegdb  # noqa: PLC0415

        target = connect_pipe(args.holder, layout)
        if args.command == "select":
            from tools.amiga import amigadrive  # noqa: PLC0415
            try:
                row = select(target, layout, args.member,
                             lambda key: amigadrive.press(args.holder, key,
                                                          args.settle))
            except (SystemExit, OSError, amiga.GuestError) as exc:
                row = {"member": args.member,
                       "error": f"{type(exc).__name__}: {exc}"}
        elif args.command == "poke":
            try:
                row = poke(target, layout, args.holder, args.at,
                           bytes.fromhex(args.digits))
            except (ValueError, OSError, amiga.GuestError,
                    amigaeffects.EffectError) as exc:
                row = {"address": args.at,
                       "error": f"{type(exc).__name__}: {exc}"}
        else:
            row = (fsuaegdb.party_row if args.command == "party"
                   else fsuaegdb.pool_row)(target, layout)
        print(json.dumps(row))
        return 1 if "error" in row else 0
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
