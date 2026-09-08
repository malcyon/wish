#!/usr/bin/env python3
"""Re-take the measurement behind `automap.area.looks_like_a_map` (#436).

The check that decides whether 1024 bytes are a Gold Box map at all carries
four thresholds, and every one of them is a claim about two corpora:

* the **maps** the games ship -- `GEO*` on a C64 disk, `GEO.GLB` on an Amiga
  one -- which must all pass;
* every **other** 1024-byte window of every other file on the same disks,
  which must all fail.

A threshold set against a corpus nobody can re-take is a threshold that drifts.
`MAP_WALL_AGREEMENT = 0.5` was fitted to Pool of Radiance and Curse before
Silver Blades or the Amiga were in the project, and by 2026-09-08 it was
throwing out 31 of the 95 maps on this machine.

    tools/geoplausible.py maps          one row per map, every corpus found
    tools/geoplausible.py sweep         every non-map window, and what reaches
                                        the gate
    tools/geoplausible.py thresholds    the worst map and the best non-map for
                                        each threshold, which is the number
                                        that justifies it

**Two traps this tool exists to remember.**

*Excluding maps by filename is not enough.* `/SAVE/spindisk` on both Amiga
disk As holds all sixteen Curse maps verbatim, 1024 bytes apart from offset
154. A window stepped through it is a slice of two adjacent real maps and
scores like one, so a sweep that trusts the name tightens its thresholds
against real map data. `sweep` drops any window overlapping a verbatim copy of
a map found anywhere.

*Sweeping the raw disk image does not work.* It catches sector-shifted
fragments of maps, and they cannot be excluded the same way -- a 64-byte run of
a map is mostly zeros and matches all over the disk. Sweep the files.

The quantities come from `automap.area.map_evidence` rather than being
recomputed here, so this tool cannot quietly disagree with the code it is
measuring.
"""

from __future__ import annotations

import argparse
import glob
import io
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from automap.area import (  # noqa: E402
    MAP_RECIPROCITY,
    MAP_WALL_ART_AGREEMENT,
    MAP_WALL_PAIR_REUSE,
    MAP_WALLED_EDGES,
    map_evidence,
)
from goldbox.geo import GEO_SIZE, Geo  # noqa: E402
from tools import gamedisks  # noqa: E402

#: The C64 titles whose disks `gamedisks.toml` knows how to find, and the glob
#: that picks out their game disks rather than a save disk sitting beside them.
C64_TITLES = (("Pool of Radiance C64", "pool-of-radiance", "POOL*.[dD]64"),
              ("Curse C64", "curse-of-the-azure-bonds", "CURSE*.[dD]64"),
              ("Silver Blades C64", "secret-of-the-silver-blades",
               "SILVER*.[dD]64"))

#: Where each Amiga title keeps its map library. The disk is found by matching
#: the first element against the image's filename, the way `tests/test_amiga.py`
#: does it.
AMIGA_TITLES = (("Curse Amiga", "curse", "/DISKB/GEO.GLB"),
                ("Silver Blades Amiga", "silver", "/DISK2/GEO.GLB"))

#: Below this, a window is not worth measuring further. Lower than
#: `MAP_RECIPROCITY` on purpose: the point of the sweep is to show what gets
#: *close* to the gate, not only what clears it.
SWEEP_FLOOR = 0.90


# --- the maps -----------------------------------------------------------------

def c64_maps() -> dict[str, dict[str, bytes]]:
    """Every `GEO` file on every C64 title whose disks are on this machine."""
    from goldbox.d64 import D64
    found: dict[str, dict[str, bytes]] = {}
    for label, key, pattern in C64_TITLES:
        where = gamedisks.find(key)
        if where is None:
            continue
        maps: dict[str, bytes] = {}
        for path in sorted(glob.glob(str(where / pattern))):
            try:
                disk = D64.open(path)
            except Exception:
                continue
            for entry in disk.directory():
                name = bytes(entry.name).decode("latin1")
                if not name.startswith("GEO"):
                    continue
                try:
                    payload = disk.read_file(entry)
                except Exception:
                    continue
                if len(payload) in (GEO_SIZE, GEO_SIZE + 2):
                    maps.setdefault(name, Geo.from_bytes(payload).to_bytes())
        if maps:
            found[label] = maps
    return found


def amiga_images(gold_box_only: bool = True) -> list[pathlib.Path]:
    """Every Amiga disk image on this machine, one per filename.

    `$AMIGA_DISKS` and `~/Downloads/amiga` hold the same images on this
    machine, so a sweep that took both would count every window twice and
    report a corpus half again as big as the one it measured. Keyed by
    filename.

    `gold_box_only` is the default because the thresholds in `automap/area.py`
    are fitted against Gold Box data and the counts quoted there are of Gold
    Box data. `--include-other-games` widens it, and the answer is measured:
    across `Bubble Bobble.adf`'s 6275 windows this check admits 6 and the one
    it replaced admitted 9. Neither is an oracle against arbitrary tile
    graphics, and saying so is the point of having the flag.
    """
    seen: dict[str, pathlib.Path] = {}
    for root in gamedisks.candidates("amiga"):
        if not root.is_dir():
            continue
        for image in sorted(root.rglob("*.adf")):
            if gold_box_only and not any(
                    want in image.name.lower().replace("_", "")
                    for _label, want, _where in AMIGA_TITLES):
                continue
            seen.setdefault(image.name, image)
    return list(seen.values())


def _geo_library(data: bytes) -> dict[int, bytes]:
    """`GEO.GLB` as `{id: 1024 bytes}`. Block 0 is the index."""
    from tools.amigaenum import glib_blocks
    blocks = glib_blocks(data)
    index = blocks[0]
    count = int.from_bytes(index[:2], "big")
    out = {}
    for i in range(count):
        at = 2 + 4 * i
        ident = int.from_bytes(index[at:at + 2], "big")
        block = int.from_bytes(index[at + 2:at + 4], "big")
        if block < len(blocks) and len(blocks[block]) == GEO_SIZE:
            out[ident] = blocks[block]
    return out


def amiga_maps() -> dict[str, dict[str, bytes]]:
    """Every `GEO.GLB` library on every Amiga disk on this machine."""
    from goldbox.amiga_adf import AmigaDisk
    found: dict[str, dict[str, bytes]] = {}
    for label, want, where in AMIGA_TITLES:
        for image in amiga_images():
            if want not in image.name.lower().replace("_", ""):
                continue
            try:
                data = AmigaDisk.open(image).read_file(where)
            except Exception:
                continue
            library = _geo_library(data)
            if library:
                found[label] = {f"id{i}": b for i, b in sorted(library.items())}
                break
    return found


def every_map() -> dict[str, dict[str, bytes]]:
    return {**c64_maps(), **amiga_maps()}


# --- everything that is not a map ---------------------------------------------

def other_files(gold_box_only: bool = True):
    """`(name, bytes)` for every file on every disk that is not a map library."""
    from goldbox.d64 import D64
    for _label, key, pattern in C64_TITLES:
        where = gamedisks.find(key)
        if where is None:
            continue
        for path in sorted(glob.glob(str(where / pattern))):
            try:
                disk = D64.open(path)
            except Exception:
                continue
            for entry in disk.directory():
                name = bytes(entry.name).decode("latin1")
                if name.startswith("GEO"):
                    continue
                try:
                    # past the two-byte PRG load address, so a window lands
                    # where the game would have it in memory
                    yield f"{pathlib.Path(path).name}:{name}", \
                        disk.read_file(entry)[2:]
                except Exception:
                    continue
    from goldbox.amiga_adf import AmigaDisk
    for image in amiga_images(gold_box_only):
        try:
            disk = AmigaDisk.open(image)
        except Exception:
            continue
        for path, _entry in disk.walk():
            if path.upper().endswith("GEO.GLB"):
                continue
            try:
                yield f"{image.name}:{path}", disk.read_file(path)
            except Exception:
                continue


def windows(body: bytes, known: list[bytes], step: int):
    """Every window of `body`, minus the ones holding a verbatim map.

    Yields `(offset, block)`, and `(offset, None)` for a window dropped, so the
    caller can count what was excluded rather than have it vanish.
    """
    marks = bytearray(len(body))
    for raw in known:
        at = body.find(raw)
        while at != -1:
            marks[at:at + GEO_SIZE] = b"\1" * GEO_SIZE
            at = body.find(raw, at + 1)
    for at in range(0, len(body) - GEO_SIZE + 1, step):
        if 1 in marks[at:at + GEO_SIZE]:
            yield at, None
        else:
            yield at, body[at:at + GEO_SIZE]


# --- the reports ---------------------------------------------------------------

def _row(name: str, ev) -> str:
    mark = "pass" if ev.plausible else "REJECT"
    return (f"{name:26s} {ev.reciprocity:8.3f} {ev.walled_edges:8d} "
            f"{ev.art_agreement:8.3f} {ev.pair_reuse:9.2f}  {mark}")


HEAD = (f'{"block":26s} {"recip":>8s} {"walled":>8s} {"art":>8s} '
        f'{"reuse":>9s}')


def report_maps(out: io.TextIOBase) -> int:
    corpora = every_map()
    if not corpora:
        print("no disks found; set $POR_DISKS, $COAB_DISKS, $SSB_DISKS "
              "or $AMIGA_DISKS", file=out)
        return 1
    rejected = 0
    total = 0
    seen: dict[bytes, str] = {}
    duplicated = 0
    for label, maps in corpora.items():
        print(f"\n== {label}: {len(maps)} maps", file=out)
        print(HEAD, file=out)
        for name, raw in maps.items():
            total += 1
            if raw in seen:
                duplicated += 1
            else:
                seen[raw] = f"{label}:{name}"
            ev = map_evidence(Geo(raw))
            rejected += not ev.plausible
            print(_row(name, ev), file=out)
    print(f"\n{total} maps over {len(corpora)} corpora, "
          f"{len(seen)} of them distinct "
          f"({duplicated} repeated across ports), {rejected} rejected",
          file=out)
    for label, maps in corpora.items():
        for key, extract in (("reciprocity", lambda e: e.reciprocity),
                             ("art agreement", lambda e: e.art_agreement),
                             ("pair reuse", lambda e: e.pair_reuse)):
            vals = sorted(extract(map_evidence(Geo(r))) for r in maps.values())
            print(f"{label:22s} {key:14s} min {vals[0]:8.3f}  "
                  f"med {statistics.median(vals):8.3f}  max {vals[-1]:8.3f}",
                  file=out)
    return 1 if rejected else 0


def report_sweep(out: io.TextIOBase, step: int, show: int,
                 gold_box_only: bool = True) -> int:
    known = [raw for maps in every_map().values() for raw in maps.values()]
    if not known:
        print("no disks found", file=out)
        return 1
    swept = dropped = near = admitted = 0
    worst: list[tuple[float, float, str]] = []
    for name, body in other_files(gold_box_only):
        for at, block in windows(body, known, step):
            swept += 1
            if block is None:
                dropped += 1
                continue
            ev = map_evidence(Geo(block))
            if ev.reciprocity < SWEEP_FLOOR or ev.walled_edges < MAP_WALLED_EDGES:
                continue
            near += 1
            worst.append((ev.art_agreement, ev.pair_reuse, f"{name}+{at}"))
            if ev.plausible:
                admitted += 1
                print(f"ADMITTED  {_row(f'{name}+{at}', ev)}", file=out)
    print(f"\n{swept} windows at {step}-byte steps; {dropped} dropped for "
          f"holding a verbatim copy of a map", file=out)
    print(f"{near} reach reciprocity {SWEEP_FLOOR} with "
          f"{MAP_WALLED_EDGES} walled edges; {admitted} pass the whole check",
          file=out)
    print(f"\nclosest {show} by wall-art agreement:", file=out)
    for a, p, name in sorted(worst, reverse=True)[:show]:
        print(f"  {name[:58]:58s} art {a:.3f}  reuse {p:6.2f}", file=out)
    print(f"\nclosest {show} by pair reuse:", file=out)
    for a, p, name in sorted(worst, key=lambda t: -t[1])[:show]:
        print(f"  {name[:58]:58s} art {a:.3f}  reuse {p:6.2f}", file=out)
    return 1 if admitted else 0


def report_thresholds(out: io.TextIOBase, step: int,
                      gold_box_only: bool = True) -> int:
    """The worst map and the best non-map beside each threshold."""
    corpora = every_map()
    known = [raw for maps in corpora.values() for raw in maps.values()]
    if not known:
        print("no disks found", file=out)
        return 1
    maps = [(f"{label}:{name}", map_evidence(Geo(raw)))
            for label, ms in corpora.items() for name, raw in ms.items()]
    fields = (("MAP_RECIPROCITY", MAP_RECIPROCITY, lambda e: e.reciprocity),
              ("MAP_WALLED_EDGES", MAP_WALLED_EDGES,
               lambda e: e.walled_edges),
              ("MAP_WALL_ART_AGREEMENT", MAP_WALL_ART_AGREEMENT,
               lambda e: e.art_agreement),
              ("MAP_WALL_PAIR_REUSE", MAP_WALL_PAIR_REUSE,
               lambda e: e.pair_reuse))

    def failures(ev) -> int:
        return sum(1 for _lab, t, extract in fields if extract(ev) < t)

    # Keep every block that misses at most one clause. Pre-filtering on
    # reciprocity here -- which `sweep` does, and which is right there -- would
    # make the first two rows below circular: a corpus already cut at
    # `MAP_RECIPROCITY` can never name a block that reciprocity is what turns
    # away.
    others = []
    for name, body in other_files(gold_box_only):
        for at, block in windows(body, known, step):
            if block is None:
                continue
            ev = map_evidence(Geo(block))
            if failures(ev) <= 1:
                others.append((f"{name}+{at}", ev))
    for label, threshold, extract in fields:
        worst_map = min(maps, key=lambda t: extract(t[1]))
        # the best non-map that clears every *other* clause, which is the one
        # this threshold has to hold off on its own
        rivals = [(n, e) for n, e in others
                  if all(extract2(e) >= t2
                         for lab2, t2, extract2 in fields if lab2 != label)]
        best = max(rivals, key=lambda t: extract(t[1])) if rivals else None
        print(f"{label} = {threshold}", file=out)
        print(f"    worst map      {extract(worst_map[1]):8.3f}  "
              f"{worst_map[0]}", file=out)
        if best is None:
            print("    best non-map   none clears the other three clauses",
                  file=out)
        else:
            print(f"    best non-map   {extract(best[1]):8.3f}  {best[0]}",
                  file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("maps", "sweep", "thresholds"))
    parser.add_argument("--step", type=int, default=64,
                        help="how far apart the sweep's windows are")
    parser.add_argument("--show", type=int, default=8,
                        help="how many near misses to name")
    parser.add_argument("--include-other-games", action="store_true",
                        help="sweep every Amiga disk image, not only the Gold "
                             "Box ones; see `amiga_images`")
    args = parser.parse_args(argv)
    if args.command == "maps":
        return report_maps(sys.stdout)
    if args.command == "sweep":
        return report_sweep(sys.stdout, args.step, args.show,
                            not args.include_other_games)
    return report_thresholds(sys.stdout, args.step,
                             not args.include_other_games)


if __name__ == "__main__":
    sys.exit(main())
