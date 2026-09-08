#!/usr/bin/env python3
"""Diff the same Gold Box map between the ports that shipped it (#443).

`tools/geoplausible.py maps` counts how many of the maps on this machine are
distinct and reports that three of Curse of the Azure Bonds' sixteen are not
byte-identical between the C64 disks and the Amiga disks, while all seventeen
of Secret of the Silver Blades' are. It does not say **which** three, or what
changed in them. This does.

    tools/geoports.py diff        every title, every port pairing, and the
                                  decoded meaning of each differing byte
    tools/geoports.py closest     the distance measurements `NEAR_ENOUGH` in
                                  `automap/area.py` rests on

**Three ports, not two.** The C64 keeps one `GEO<id>` PRG per area on its
disks, the Amiga keeps them in `GEO.GLB` on disk B, and DOS keeps them in
`GEO<n>.DAX` -- 1026 bytes a block, a `00 04` load address in front of the same
1024. So a byte the C64 and the Amiga disagree about has a third opinion
available, and two ports agreeing against one is the strongest thing a diff of
shipped data can say about which is the odd one out.

**The three containers name the same area differently and this tool does not.**
The C64's filename is `GEO15`, the Amiga library's id is 21 and the DOS block
id is 21 as well; all three are area `$15`, and everything here is keyed
`GEO{id:02X}` the way the rest of the project spells it.

`_distance` and `looks_like_a_map` are imported from `automap.area` rather than
reimplemented, so this tool cannot quietly disagree with the check it is
measuring -- the same rule `tools/geoplausible.py` follows.
"""

from __future__ import annotations

import argparse
import io
import itertools
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.area import (  # noqa: E402
    NEAR_ENOUGH,
    _distance,
    looks_like_a_map,
)
from goldbox.geo import (  # noqa: E402
    ATTRIBUTES,
    BARRIER_NAMES,
    BARRIERS,
    DIRECTION_NAMES,
    GEO_SIZE,
    GRID,
    INDOOR,
    SCRIPT_ID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)
from tools import gamedisks  # noqa: E402
from tools.geoplausible import amiga_maps, c64_maps  # noqa: E402

#: The three titles this project maps, and the directory name the DOS release
#: installs each under. `--all-dos-titles` widens the DOS side to whatever else
#: is in the archives -- Gateway, Treasures and Pools of Darkness ship
#: `GEO*.DAX` too -- which is a bigger corpus for `closest` and nothing the
#: automapper would ever hold.
TITLES = (("Pool of Radiance", "POOLRAD"),
          ("Curse", "CURSE"),
          ("Silver Blades", "SECRET"))

#: Which plane each offset falls in, for the report.
PLANES = ((WALLS_NORTH_EAST, "walls N/E"), (WALLS_SOUTH_WEST, "walls S/W"),
          (ATTRIBUTES, "attributes"), (BARRIERS, "barriers"))

#: The DOS block is the C64 PRG: a two-byte little-endian `$0400` load address
#: in front of the 1024. CONFIRMED -- every one of the 62 blocks read here is
#: 1026 bytes opening `00 04`, and 57 of them are byte-identical from byte 2 on
#: to the C64 file of the same name.
DOS_LOAD_ADDRESS = b"\x00\x04"


# --- loading each port --------------------------------------------------------

def _by_title(corpora: dict[str, dict[str, bytes]], suffix: str
              ) -> dict[str, dict[str, bytes]]:
    """`geoplausible`'s `"Curse C64"` keys, re-split into title and port."""
    out: dict[str, dict[str, bytes]] = {}
    for label, maps in corpora.items():
        if label.endswith(" " + suffix):
            out[label[:-len(suffix) - 1]] = maps
    return out


def _amiga_named(maps: dict[str, bytes]) -> dict[str, bytes]:
    """`{"id21": ...}` as `{"GEO15": ...}`, which is how the project spells it."""
    return {f"GEO{int(name[2:]):02X}": raw for name, raw in maps.items()}


def dos_maps(all_titles: bool = False) -> dict[str, dict[str, bytes]]:
    """Every DOS `GEO<n>.DAX` library in the Forgotten Realms archives.

    Keyed by title, then `GEO{id:02X}`. A block that is not 1026 bytes opening
    with the `$0400` load address is skipped and counted rather than trusted:
    the DAX index says what it unpacks to and a block of another shape is not a
    map, whatever file it came out of.
    """
    from goldbox import dos_savegame as dos
    root = gamedisks.find("dos-archives")
    if root is None:
        return {}
    folders = {folder: title for title, folder in TITLES}
    found: dict[str, dict[str, bytes]] = {}
    for path in sorted(root.rglob("GEO*.DAX")):
        folder = path.parent.name.upper()
        title = folders.get(folder)
        if title is None:
            if not all_titles:
                continue
            title = f"DOS {path.parent.name}"
        try:
            data = path.read_bytes()
            index = dos.dax_index(data, path.name)
        except Exception:
            continue
        for block_id, *_rest in index:
            try:
                block = dos.dax_block(data, block_id, path.name)
            except Exception:
                continue
            if len(block) != GEO_SIZE + 2 or not block.startswith(
                    DOS_LOAD_ADDRESS):
                continue
            found.setdefault(title, {})[f"GEO{block_id:02X}"] = block[2:]
    return found


def every_port(all_titles: bool = False
               ) -> dict[str, dict[str, dict[str, bytes]]]:
    """`{title: {port: {map name: 1024 bytes}}}` for every disk on this machine."""
    c64 = _by_title(c64_maps(), "C64")
    amiga = {t: _amiga_named(m) for t, m in _by_title(amiga_maps(),
                                                      "Amiga").items()}
    dos = dos_maps(all_titles)
    out: dict[str, dict[str, dict[str, bytes]]] = {}
    for port, corpora in (("C64", c64), ("Amiga", amiga), ("DOS", dos)):
        for title, maps in corpora.items():
            out.setdefault(title, {})[port] = maps
    return out


# --- what one differing byte means --------------------------------------------

def plane_of(offset: int) -> tuple[int, str]:
    base = offset & 0xF00
    return base, dict(PLANES)[base]


def square_of(offset: int) -> tuple[int, int]:
    within = offset & 0xFF
    return within % GRID, within // GRID


def describe(offset: int, left: bytes, right: bytes,
             left_name: str, right_name: str) -> list[str]:
    """One line for the byte, then what the two ports disagree about in it."""
    base, plane = plane_of(offset)
    x, y = square_of(offset)
    a, b = left[offset], right[offset]
    lines = [f"    ${offset:03X}  {plane:11s} ({x:2d},{y:2d})  "
             f"{left_name} ${a:02X}  {right_name} ${b:02X}"]
    if base == ATTRIBUTES:
        if (a & INDOOR) != (b & INDOOR):
            lines.append(f"        roofed: {left_name} {bool(a & INDOOR)}, "
                         f"{right_name} {bool(b & INDOOR)}")
        if (a & SCRIPT_ID) != (b & SCRIPT_ID):
            lines.append(f"        script id: {left_name} {a & SCRIPT_ID}, "
                         f"{right_name} {b & SCRIPT_ID}")
    elif base == BARRIERS:
        for direction in range(4):
            pa = (a >> (2 * direction)) & 3
            pb = (b >> (2 * direction)) & 3
            if pa == pb:
                continue
            lines.append(
                f"        {DIRECTION_NAMES[direction]:5s}: "
                f"{left_name} {BARRIER_NAMES[pa]}, "
                f"{right_name} {BARRIER_NAMES[pb]}   "
                f"(wall art {Geo(left).wall(x, y, direction)} and "
                f"{Geo(right).wall(x, y, direction)})")
    else:
        first, second = ("north", "east") if base == WALLS_NORTH_EAST \
            else ("south", "west")
        if a >> 4 != b >> 4:
            lines.append(f"        {first} wall art: {left_name} {a >> 4}, "
                         f"{right_name} {b >> 4}")
        if a & 0x0F != b & 0x0F:
            lines.append(f"        {second} wall art: {left_name} {a & 0x0F}, "
                         f"{right_name} {b & 0x0F}")
    return lines


def per_plane(left: bytes, right: bytes) -> dict[str, int]:
    offsets = [i for i in range(GEO_SIZE) if left[i] != right[i]]
    return {name: sum(1 for i in offsets if i & 0xF00 == base)
            for base, name in PLANES}


# --- the reports --------------------------------------------------------------

def report_diff(out: io.TextIOBase, all_titles: bool = False) -> int:
    corpora = every_port(all_titles)
    if not corpora:
        print("no disks found; set $POR_DISKS, $COAB_DISKS, $SSB_DISKS, "
              "$AMIGA_DISKS or $FR_ARCHIVES", file=out)
        return 1
    differing = 0
    for title, ports in sorted(corpora.items()):
        names = sorted({n for maps in ports.values() for n in maps})
        print(f"\n== {title}: {len(names)} areas over "
              f"{', '.join(sorted(ports))}", file=out)
        pairs = list(itertools.combinations(sorted(ports), 2))
        widths = [max(11, len(a) + len(b) + 1) for a, b in pairs]
        print(f"{'map':8s}" + "".join(
            f"{a + '/' + b:>{w}s}" for (a, b), w in zip(pairs, widths)),
            file=out)
        for name in names:
            row = []
            for (a, b), width in zip(pairs, widths):
                left, right = ports[a].get(name), ports[b].get(name)
                cell = ("-" if left is None or right is None
                        else str(_distance(left, right)))
                row.append(f"{cell:>{width}s}")
            print(f"{name:8s}" + "".join(row), file=out)
        for name in names:
            for a, b in pairs:
                left, right = ports[a].get(name), ports[b].get(name)
                if left is None or right is None or left == right:
                    continue
                differing += 1
                print(f"\n  {title} {name}: {a} against {b}, "
                      f"{_distance(left, right)} of {GEO_SIZE} bytes  "
                      f"{per_plane(left, right)}", file=out)
                for offset in range(GEO_SIZE):
                    if left[offset] != right[offset]:
                        for line in describe(offset, left, right, a, b):
                            print(line, file=out)
                for label, raw in ((a, left), (b, right)):
                    agree, total = Geo(raw).reciprocity()
                    print(f"    {label} barrier reciprocity {agree}/{total}, "
                          f"plausible as a map: "
                          f"{looks_like_a_map(Geo(raw))}", file=out)
    print(f"\n{differing} port pairings differ", file=out)
    return 0


def report_closest(out: io.TextIOBase, show: int = 10,
                   all_titles: bool = False) -> int:
    """The distances `NEAR_ENOUGH` has to sit under, and the ones it need not.

    Two questions, and they are not the same one:

    * **the same area on two ports** -- how far apart the tolerance has to
      reach for a block loaded by one port to be recognised from the other
      port's copy;
    * **two different areas** -- how close the tolerance may come to naming the
      wrong place, which is what the constant's own comment quotes.
    """
    corpora = every_port(all_titles)
    flat = [(f"{title}:{port}:{name}", title, name, raw)
            for title, ports in corpora.items()
            for port, maps in ports.items() for name, raw in maps.items()]
    if not flat:
        print("no disks found", file=out)
        return 1
    distinct: dict[bytes, list[str]] = {}
    for label, _t, _n, raw in flat:
        distinct.setdefault(raw, []).append(label)
    print(f"{len(flat)} maps over "
          f"{sum(len(p) for p in corpora.values())} corpora, "
          f"{len(distinct)} of them distinct", file=out)

    # Every pairing of two ports' copies of one area that they disagree about,
    # over the whole corpus, and then every pairing of two *different places*
    # over the distinct blocks only -- listing the second over the raw corpus
    # instead prints the same underlying pair once per port that ships it.
    same_place = sorted((_distance(ra, rb), la, lb)
                        for (la, ta, na, ra), (lb, tb, nb, rb)
                        in itertools.combinations(flat, 2)
                        if ra != rb and (ta, na) == (tb, nb))
    named = [(raw, f"{labels[0].split(':')[0]} "
                   f"{labels[0].rsplit(':', 1)[1]} "
                   f"({', '.join(sorted(lab.split(':')[1] for lab in labels))})")
             for raw, labels in distinct.items()]
    other_place = sorted((_distance(ra, rb), la, lb)
                         for (ra, la), (rb, lb)
                         in itertools.combinations(named, 2)
                         if la.rsplit(" (", 1)[0] != lb.rsplit(" (", 1)[0])

    print(f"\nthe same area on two ports, where the ports disagree "
          f"({len(same_place)} pairings):", file=out)
    for d, la, lb in same_place[:show]:
        print(f"  {d:5d}  {la:34s} {lb}", file=out)
    print(f"\nclosest {show} pairs that are different places:", file=out)
    for d, la, lb in other_place[:show]:
        print(f"  {d:5d}  {la:40s} {lb}", file=out)
    if other_place:
        print(f"\nmedian over {len(other_place)} different-place pairs: "
              f"{statistics.median(d for d, _a, _b in other_place):.0f}",
              file=out)
        worst_drift = max((d for d, _a, _b in same_place), default=0)
        nearest_wrong = other_place[0][0]
        print(f"\nNEAR_ENOUGH = {NEAR_ENOUGH}", file=out)
        print(f"  must reach      {worst_drift:5d}   the widest gap between "
              f"two ports' copies of one area", file=out)
        print(f"  must stay under {nearest_wrong:5d}   the closest two "
              f"different places, {other_place[0][1]} and "
              f"{other_place[0][2]}", file=out)
        if nearest_wrong <= NEAR_ENOUGH:
            print("  IT DOES NOT: two different places are within the "
                  "tolerance of each other", file=out)
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("diff", "closest"))
    parser.add_argument("--show", type=int, default=10,
                        help="how many pairs `closest` names")
    parser.add_argument("--all-dos-titles", action="store_true",
                        help="take every DOS title in the archives, not only "
                             "the three this project maps")
    args = parser.parse_args(argv)
    if args.command == "diff":
        return report_diff(sys.stdout, args.all_dos_titles)
    return report_closest(sys.stdout, args.show, args.all_dos_titles)


if __name__ == "__main__":
    sys.exit(main())
