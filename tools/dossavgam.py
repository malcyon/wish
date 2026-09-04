#!/usr/bin/env python3
"""Survey the DOS saved-game containers of every Gold Box title on the machine.

    tools/dossavgam.py                 every container under $FR_ARCHIVES
    tools/dossavgam.py --regions       add the region map each shape declares
    tools/dossavgam.py --runs          add every run of nonzero bytes outside
                                       the party table, which is what the
                                       per-title region map was read from
    tools/dossavgam.py --scripts       the largest ECL block each title ships,
                                       against the 7680-byte staging buffer

This is the tool that answered #53's third question -- whether `SAVGAM?.DAT`
and its siblings have the same shape in all four titles.  It reads only, and
it reads the player's own archives; nothing it prints is committed.

The anchor is the party table: six length-prefixed `CHRDAT<letter><n>` names
41 bytes apart, which every title writes and which `--runs` finds without
being told where to look.  Everything else in `goldbox.dos_savegame`'s
`SAVE_SHAPES` is measured backwards from it.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_savegame as sg  # noqa: E402
from tools import gamedisks  # noqa: E402


def archive_roots() -> list[pathlib.Path]:
    """Where the Forgotten Realms Archives might be: `gamedisks.toml`'s own
    search list (#212), so a machine where the suite finds the archives is a
    machine where this tool finds them too."""
    return gamedisks.candidates("dos-archives")


def containers(roots=None) -> list[pathlib.Path]:
    """Every DOS saved game under the archives, each distinct file once.

    The archives ship two copies of most save directories -- `Default files/
    Saves` and `GAME/<title>/SAVE` -- and for three of the four titles they
    are byte-identical, so a survey that counted both would double every
    sample size it reported.  Deduplicate on the bytes, not on the path.
    """
    suffixes = {s.suffix.lower() for s in sg.SAVE_SHAPES}
    seen: dict[bytes, pathlib.Path] = {}
    for root in roots or archive_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("SAVGAM*")):
            if path.suffix.lower() not in suffixes or not path.is_file():
                continue
            if path.stat().st_size not in sg.SAVE_SHAPES_BY_SIZE:
                continue
            seen.setdefault(path.read_bytes(), path)
    return list(seen.values())


def nonzero_runs(data: bytes, end: int) -> list[tuple[int, bytes]]:
    """Every run of nonzero bytes in `data[:end]`."""
    out, i = [], 0
    while i < end:
        if data[i]:
            start = i
            while i < end and data[i]:
                i += 1
            out.append((start, data[start:i]))
        else:
            i += 1
    return out


def game_of(path: pathlib.Path) -> str:
    """The archive folder the file came from, which names the actual game."""
    for parent in path.parents:
        if parent.parent.name == "games":
            return parent.name
    return path.parent.name


def describe(path: pathlib.Path, *, regions: bool, runs: bool) -> None:
    data = path.read_bytes()
    shape = sg.save_shape_for(len(data))
    names = sg.character_files(data, shape)
    # The shape is named by the size, and Treasures of the Savage Frontier
    # writes the same 1364-byte container Pools of Darkness does -- so print
    # where the file came from, which is the only thing that says which game.
    print(f"{path.name}  {len(data)} bytes  {shape.title} shape  "
          f"[{game_of(path)}]")
    print(f"    Party of {sg.party_size(data, shape)}, "
          f"{len(names)} named files, first {names[0] if names else '-'}, "
          f"square {sg.position(data, shape)}")
    if shape.dax_bytes:
        print(f"    Container byte {sg.dax_number(data, shape)}, "
              f"$5012 {sg.word(data, sg.DISK, shape)}, "
              f"$503E {sg.word(data, sg.PARTY_SIZE, shape)}, "
              f"$49E6 {sg.word(data, sg.INDOORS, shape)}")
    if regions:
        for label, start, size in region_map(shape):
            print(f"    {start:>6}  {size:>6}  {label}")
    if runs:
        print("    Nonzero runs before the party table:")
        for at, run in nonzero_runs(data, shape.party_table):
            print(f"      {at:>6}  {run.hex(' ')}")


def region_map(shape) -> list[tuple[str, int, int]]:
    """`(what, offset, size)` for one shape, in file order."""
    out, at = [], 0
    for label, size in (("ECL variables, one byte each", shape.var_bytes),
                        ("Undecoded head", shape.head),
                        ("Container number", shape.dax_bytes),
                        ("ECL variables", 2 * shape.var_words),
                        ("Staged script", shape.script_bytes),
                        ("Unnamed", shape.unnamed),
                        ("Square and party size", shape.square_bytes),
                        ("Character slots",
                         sg.NAME_SLOTS * sg.PARTY_ENTRY)):
        if size:
            out.append((label, at, size))
            at += size
    return out


def scripts(roots=None) -> None:
    """The largest `ECL<n>.DAX` block per title, against the 7680 the Pool of
    Radiance save stages.

    Silver Blades and Pools of Darkness stage no script and their blocks are
    just as large -- 7678 and 7680 against Pool of Radiance's 7679 -- so the
    cap is not a consequence of the buffer.  It is not the whole engine
    family's either: Treasures of the Savage Frontier's largest block is
    13353 bytes."""
    for root in roots or archive_roots():
        if not root.is_dir():
            continue
        for game in sorted(p for p in root.glob("*/games/*") if p.is_dir()):
            blocks = []
            for path in sorted(game.rglob("ECL*.DAX")):
                try:
                    blocks += [(raw, path.name, bid) for bid, _, raw, _
                               in sg.dax_index(path.read_bytes(), path.name)]
                except sg.DaxError as e:
                    print(f"  {path.name}: {e}")
            if blocks:
                raw, name, bid = max(blocks)
                print(f"{game.name:34s} {len(blocks):3d} blocks, "
                      f"largest {raw} bytes ({name} block {bid})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--regions", action="store_true",
                    help="print the region map each shape declares")
    ap.add_argument("--runs", action="store_true",
                    help="print every nonzero run before the party table")
    ap.add_argument("--scripts", action="store_true",
                    help="print the largest ECL block each title ships")
    args = ap.parse_args()
    if args.scripts:
        scripts()
        return 0
    found = containers()
    if not found:
        print("No DOS saved game found; set FR_ARCHIVES to the archives.")
        return 1
    for path in found:
        describe(path, regions=args.regions, runs=args.runs)
    shapes = {sg.save_shape_for(p.stat().st_size).key for p in found}
    print(f"{len(found)} containers, {len(shapes)} shapes, "
          f"{len({game_of(p) for p in found})} game folders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
