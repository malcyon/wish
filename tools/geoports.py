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
    tools/geoports.py blocks      every DOS `GEO<n>.DAX` block in the archives,
                                  its leading word and how it scores as a map

**Three ports, not two.** The C64 keeps one `GEO<id>` PRG per area on its
disks, the Amiga keeps them in `GEO.GLB` on disk B, and DOS keeps them in
`GEO<n>.DAX` -- 1026 bytes a block, two bytes the engine never reads in front
of the same 1024. So a byte the C64 and the Amiga disagree about has a third
opinion available, and two ports agreeing against one is the strongest thing a
diff of shipped data can say about which is the odd one out.

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
    map_evidence,
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

#: What the DOS engine itself asks of a `GEO<n>.DAX` block: that it unpacks to
#: **1026 bytes**, and nothing else. `Load3DMap` compares the byte count against
#: `0x402`, prints "Unable to load geo in Load3DMap." if it misses, and then
#: copies four 256-byte planes into the resident map buffer starting at
#: **offset 2** -- Pools of Darkness `GAME.OVR` file `0x3D7FE` (the compare) and
#: `0x3D836` (`mov word ptr [bp-8], 2`, the source offset), Treasures of the
#: Savage Frontier `0x48BEE`/`0x48C08`, Curse of the Azure Bonds
#: `0x3F333`/`0x3F368`. Bytes 0 and 1 are never loaded, compared or stored.
#:
#: So the trim is CONFIRMED and it is not the C64's load address that settles
#: it. Four of the six DOS titles in the archives do carry `00 04` there,
#: because their maps came from the same source as a C64 release; Treasures
#: opens `00 00` on all 41 blocks and Pools of Darkness opens `cc dd` on 26,
#: `01 11` on 5 and `00 04` on one, and the engine draws all of them.
#: Corroborated across ports: all 32 Pools of Darkness blocks are byte-identical
#: from byte 2 on to the Amiga `GEO.GLB` on its disk 3, and 249 to 834 bytes
#: away under the other trim (#466).
DOS_BLOCK_SIZE = GEO_SIZE + 2
DOS_SKIP = 2


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


def dos_geo_blocks(all_titles: bool = False):
    """Yield `(title, file name, block id, whole block)` for the archives.

    Every block of every `GEO<n>.DAX`, whatever shape it turns out to be, so a
    caller can count what it rejected instead of discovering a title is missing
    by its absence from a report. One walk, so `dos_maps` and the `blocks`
    census cannot disagree about what is there.
    """
    from goldbox import dos_savegame as dos
    root = gamedisks.find("dos-archives")
    if root is None:
        return
    folders = {folder: title for title, folder in TITLES}
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
            yield title, path.name, block_id, block


def dos_maps(all_titles: bool = False) -> dict[str, dict[str, bytes]]:
    """Every DOS `GEO<n>.DAX` library in the Forgotten Realms archives.

    Keyed by title, then `GEO{id:02X}`, and trimmed of the two bytes in front
    the way the engine trims them.

    **The membership test is the engine's own**: a block that unpacks to 1026
    bytes is a map, and one that does not is not. `Load3DMap` asks nothing else
    -- see `DOS_BLOCK_SIZE` for the three overlays that were read -- and asking
    more here throws away maps the game draws. `automap.area.looks_like_a_map`
    is the check that was tried instead and it rejects eight: the six wall-less
    wilderness blocks of Gateway to the Savage Frontier, whose barrier plane is
    passable everywhere inside a sealed border, and Treasures' `GEO35` and
    `GEO37`, ordinary walled maps that miss on `MAP_WALLED_EDGES` and
    `MAP_RECIPROCITY` by a little (#466). `blocks` prints the score for every
    block so nothing is hidden by not filtering on it.

    This used to require the C64 PRG's `00 04` in front as well, which cost 70
    of the archives' 73 later-title maps: Treasures of the Savage Frontier opens
    `00 00` and Pools of Darkness mostly `cc dd`, and neither has a C64 release
    for a load address to have come from.
    """
    found: dict[str, dict[str, bytes]] = {}
    for title, _name, block_id, block in dos_geo_blocks(all_titles):
        if len(block) != DOS_BLOCK_SIZE:
            continue
        found.setdefault(title, {})[f"GEO{block_id:02X}"] = block[DOS_SKIP:]
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

def report_blocks(out: io.TextIOBase, all_titles: bool = True) -> int:
    """Every DOS `GEO<n>.DAX` block in the archives, and what it looks like.

    The census that says whether the reader is dropping anything. One row a
    block: which file it came out of, the two bytes in front that the engine
    never reads, and the four quantities `automap.area.looks_like_a_map`
    measures -- printed rather than filtered on, because eight blocks the game
    itself draws do not clear them (#466).
    """
    rows: dict[str, list] = {}
    for title, name, block_id, block in dos_geo_blocks(all_titles):
        rows.setdefault(title, []).append((name, block_id, block))
    if not rows:
        print("no DOS archives found; set $FR_ARCHIVES", file=out)
        return 1
    for title, blocks in sorted(rows.items()):
        wrong = [b for _n, _i, b in blocks if len(b) != DOS_BLOCK_SIZE]
        heads: dict[bytes, int] = {}
        for _n, _i, block in blocks:
            heads[bytes(block[:DOS_SKIP])] = heads.get(
                bytes(block[:DOS_SKIP]), 0) + 1
        print(f"\n== {title}: {len(blocks)} blocks, "
              f"{len(blocks) - len(wrong)} of them {DOS_BLOCK_SIZE} bytes",
              file=out)
        print("   leading word: " + ", ".join(
            f"{head.hex(' ')} x{count}"
            for head, count in sorted(heads.items(), key=lambda kv: -kv[1])),
            file=out)
        print(f"   {'map':8s} {'file':12s} {'head':6s} {'recip':>6s} "
              f"{'walled':>7s} {'art':>6s} {'reuse':>7s}  plausible", file=out)
        implausible = 0
        for name, block_id, block in sorted(blocks, key=lambda r: r[1]):
            if len(block) != DOS_BLOCK_SIZE:
                print(f"   GEO{block_id:02X}    {name:12s} "
                      f"{len(block)} bytes, not a map", file=out)
                continue
            ev = map_evidence(Geo(block[DOS_SKIP:]))
            implausible += not ev.plausible
            print(f"   GEO{block_id:02X}    {name:12s} "
                  f"{block[:DOS_SKIP].hex():6s} {ev.reciprocity:6.3f} "
                  f"{ev.walled_edges:7d} {ev.art_agreement:6.3f} "
                  f"{ev.pair_reuse:7.2f}  {'yes' if ev.plausible else 'NO'}",
                  file=out)
        print(f"   {len(blocks) - len(wrong)} read as maps, "
              f"{implausible} of them below looks_like_a_map", file=out)
    return 0


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


def closest_within_sets(corpora: dict[str, dict[str, dict[str, bytes]]]
                        ) -> list[tuple[int, str, str, str]]:
    """`(distance, "Title Port", name, name)` for each candidate set, nearest
    pair first.

    A candidate set is one title on one port, because that is the only shape
    `ResidentGeo.verdict` is ever handed: the automapper's maps come from
    `automap.maps.load_maps`, which globs a single title's disks. Taking the
    minimum over the whole corpus instead would mix in cross-title pairs the
    tolerance can never be asked to tell apart.

    A set with fewer than two maps contributes nothing rather than a zero.
    """
    out = []
    for title, ports in sorted(corpora.items()):
        for port, maps in sorted(ports.items()):
            names = sorted(maps)
            pairs = [(_distance(maps[a], maps[b]), f"{title} {port}", a, b)
                     for a, b in itertools.combinations(names, 2)]
            if pairs:
                out.append(min(pairs))
    return sorted(out)


def report_closest(out: io.TextIOBase, show: int = 10,
                   all_titles: bool = False) -> int:
    """The distances `NEAR_ENOUGH` has to sit under, and the ones it need not.

    Three questions, and they are not the same one:

    * **the same area on two ports** -- how far apart the tolerance has to
      reach for a block loaded by one port to be recognised from the other
      port's copy;
    * **two different areas inside one candidate set** -- one title on one
      port, which is the only shape `ResidentGeo.verdict` is ever handed:
      `Automapper._maps` comes from `automap.maps.load_maps`, which globs one
      title's disks. This is the bound the constant is set from, and the rule
      is **under half of it**, because two maps both within `NEAR_ENOUGH` of
      one block are within twice that of each other;
    * **two different areas anywhere in the corpus**, including across titles
      -- looser, and what the constant's comment used to quote. It bounds the
      other half of `verdict`: a block that is somebody *else's* Gold Box map
      has to be further than the tolerance from every one of ours before
      `NOT_OURS` can fire.

    Non-zero when either bound is violated, so the re-derivation is a command
    rather than a reading (#447).

    **`--all-dos-titles` widens the corpus past what the automapper can hold,
    and the exit code does not follow it there.** Gateway, Treasures and Pools
    of Darkness have no entry in `goldbox.c64_port`, so `load_maps` can never glob
    one of their disks and `verdict` can never be handed their maps as a
    candidate set: a pair inside one of them cannot make today's constant
    ambiguous, however close it is. Those pairs are printed as `WATCH`, naming
    the title and what the constant would have to become if it ever arrived --
    Pools of Darkness' `GEO21`/`GEO31` at 18 would force it to 8. The bounds
    that decide the exit code are measured over the titles this project maps.
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

    print("\nthe closest two maps inside each candidate set "
          "(one title, one port):", file=out)
    within = closest_within_sets(corpora)
    for d, label, a, b in within:
        print(f"  {d:5d}  {label:28s} {a}/{b}", file=out)

    print(f"\nclosest {show} pairs that are different places, anywhere:",
          file=out)
    for d, la, lb in other_place[:show]:
        print(f"  {d:5d}  {la:40s} {lb}", file=out)
    if other_place:
        print(f"\nmedian over {len(other_place)} different-place pairs: "
              f"{statistics.median(d for d, _a, _b in other_place):.0f}",
              file=out)
        worst_drift = max((d for d, _a, _b in same_place), default=0)
        ours = {title for title, _folder in TITLES}
        held = [row for row in within if row[1].rsplit(" ", 1)[0] in ours]
        watch = [row for row in within if row not in held]
        touching = [row for row in other_place
                    if any(label.rsplit(" (", 1)[0].rsplit(" ", 1)[0] in ours
                           for label in row[1:])]
        nearest_wrong = (touching or other_place)[0][0]
        print(f"\nNEAR_ENOUGH = {NEAR_ENOUGH}", file=out)
        print(f"  must reach      {worst_drift:5d}   the widest gap between "
              f"two ports' copies of one area", file=out)
        bad = worst_drift > NEAR_ENOUGH
        if bad:
            print("  IT DOES NOT: one port's copy of an area is further from "
                  "the other's than the tolerance reaches", file=out)
        if held:
            gap, label, a, b = held[0]
            print(f"  must stay under {gap // 2:5d}   half the closest two "
                  f"maps in one candidate set, {label} {a}/{b} at {gap}",
                  file=out)
            if 2 * NEAR_ENOUGH >= gap:
                print("  IT DOES NOT: one block could be inside the tolerance "
                      "of both of them at once", file=out)
                bad = True
        for gap, label, a, b in watch[:1]:
            # `(gap - 1) // 2`, not `gap // 2`. The line above states a strict
            # bound -- "must stay under 40" is satisfied by 39 -- but this one
            # names the value the constant would *become*, and the check it is
            # answering is `2 * NEAR_ENOUGH >= gap`, which refuses equality. On
            # an even gap `gap // 2` is the first value that fails: 2 x 9 is 18
            # and Pools of Darkness' closest pair is 18 apart. Odd gaps hid it,
            # because floor division already lands one under the half.
            print(f"  WATCH           {(gap - 1) // 2:5d}   what it would have "
                  f"to become for {label} {a}/{b} at {gap}, a title "
                  f"`goldbox.c64_port` does not know", file=out)
        print(f"  and under       {nearest_wrong:5d}   the closest two "
              f"different places, one of them ours: "
              f"{(touching or other_place)[0][1]} and "
              f"{(touching or other_place)[0][2]}", file=out)
        if nearest_wrong <= NEAR_ENOUGH:
            print("  IT DOES NOT: two different places are within the "
                  "tolerance of each other", file=out)
            bad = True
        if bad:
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("diff", "closest", "blocks"))
    parser.add_argument("--show", type=int, default=10,
                        help="how many pairs `closest` names")
    parser.add_argument("--all-dos-titles", action="store_true",
                        help="take every DOS title in the archives, not only "
                             "the three this project maps")
    args = parser.parse_args(argv)
    if args.command == "diff":
        return report_diff(sys.stdout, args.all_dos_titles)
    if args.command == "blocks":
        return report_blocks(sys.stdout)
    return report_closest(sys.stdout, args.show, args.all_dos_titles)


if __name__ == "__main__":
    sys.exit(main())
