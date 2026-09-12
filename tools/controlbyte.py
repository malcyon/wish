#!/usr/bin/env python3
"""The control byte on both ports: who the engine drives, and his morale.

One byte of the Gold Box character record decides whether the player commands
a character or the engine does: DOS `0x084` in Pool of Radiance (`0x0F7`,
`0x0FF`, `0x147` in the later titles) and C64 `0x0B8` in all six C64 titles.
Bit 7 is the flag; the low seven bits are a morale percentage stored halved,
which both ports double on the way out.

`tools/dosbyteimm.py` reads what the engines *store* there.  This asks what
the records on this machine actually *hold*, on both sides at once, because
the conversion's question is not what the byte means but what value a
converted companion should be given -- `#303 (The DOS record may hold the NPC
flag that the conversion reports as having nowhere to go)`.

    tools/controlbyte.py                     both ports
    tools/controlbyte.py --c64
    tools/controlbyte.py --dos
    tools/controlbyte.py --disk some.d64     one more C64 image, e.g. a
                                             save with companions in it

**Provenance is the whole caution and it is printed on every run.**  A save
found on a disk was not necessarily written by the game; `tests/gamedata.py`
and `.claude/rules/testing.md` say why.  The DOS half reuses
`tools/dostailcensus.py`'s finder, so it inherits that tool's exclusions --
records this project wrote, and an emulator instance's staged game tree.

Reads only.  Nothing here writes anything, on any disk.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_port as dl  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import dostailcensus, gamedisks  # noqa: E402

#: The C64 control byte, at the same record offset in every C64 title
#: (`#224 (0x0B9 and 0x0BA are documented both as an NPC marker and as the
#: dual-class slot)` censused it: 42 references in Pool of Radiance, 19 in
#: Curse, 23 in Silver Blades).
C64_CONTROL = 0x0B8

#: The C64 byte the treasure split reads for a character the engine drives --
#: `POST.COM $194F`, `LDA $6BFA / BEQ / AND #$03`, the only reference to it in
#: 589 Pool of Radiance files.
C64_SHARE = 0x0FA

#: Which C64 titles to sweep, by the key that finds their disks.
C64_DISKS = (
    ("pool-of-radiance", "*.[dD]64"),
    ("curse-of-the-azure-bonds", "*.[dD]64"),
    ("secret-of-the-silver-blades", "*.[dD]64"),
)


def dos_offsets(shape) -> tuple[int, int]:
    """(control, share) in one DOS title's own record.

    Derived from the shape rather than tabulated per title: the run
    `goldbox/dos_port.py` calls `field_83_87` is five bytes in Pool of
    Radiance and Curse and four in Silver Blades and Pools of Darkness, and
    it is the **first** byte that the later two dropped -- Curse's own Pool
    of Radiance importer copies `0x083`-`0x087` to `0x0F6`-`0x0FA` one for
    one (`docs/195-three-dos-record-bytes-named-from-the-overlays.md`).  So
    the control byte is the fourth from the end of the run in every title,
    which reproduces the four offsets `tools/dosbyteimm.py` finds the
    compares at: `0x084`, `0x0F7`, `0x0FF`, `0x147`.
    """
    field = dl.FIELDS_BY_NAME_FOR[shape.key]["field_83_87"]
    control = field.offset + field.size - 4
    return control, control + 1


def reading(value: int, port: str = "c64") -> str:
    """What the engine makes of one control byte.

    Bit 0 is named only for the C64, where `GEN $155D` sets it when a score
    is changed in the character-modification screen and restores the whole
    byte if the player leaves without keeping.  The DOS engine records the
    same thing in the *share* byte instead, so a DOS control byte's bit 0
    stands for nothing anybody has read.
    """
    if value < 0x80:
        if port == "c64":
            return f"player character (trainer bit {value & 1})"
        return "player character"
    morale = min((value & 0x7F) * 2, 100)
    tail = {0xB2: ", NPC_Berzerk", 0xB3: ", PC_Berzerk"}.get(value, "")
    return f"engine-driven, morale {morale}{tail}"


def c64_records(disks: list[pathlib.Path]):
    """Every C64 character record this machine can reach, and where from."""
    paths: list[tuple[str, pathlib.Path]] = []
    for key, glob in C64_DISKS:
        where = gamedisks.find(key)
        if where:
            paths += [(key, p) for p in sorted(pathlib.Path(where).glob(glob))]
    root = _specimen_root()
    if root is not None:
        paths += [("specimens", p)
                  for p in sorted(root.glob("*/WISH-SPEC-*.[dD]64"))]
    paths += [("--disk", p) for p in disks]
    for key, path in paths:
        try:
            disk = D64.open(str(path))
            game, sg0, _sg1 = load_save(disk)
        except Exception:
            continue                     # not every image carries a save
        for slot in sg0.slots:
            record = slot.record
            if record is None:
                continue
            yield key, path, game, slot.index, record


def _specimen_root():
    try:
        from tools import specimens
    except Exception:                                    # pragma: no cover
        return None
    root = specimens.tree_root()
    return pathlib.Path(root) if root and pathlib.Path(root).is_dir() else None


def census_c64(disks: list[pathlib.Path]) -> int:
    """Partition the C64 control byte; returns how many records were read."""
    rows = []
    for key, path, game, index, record in c64_records(disks):
        raw = record.to_bytes() if hasattr(record, "to_bytes") else None
        if raw is None:
            raw = bytes(record._data)                    # noqa: SLF001
        rows.append((key, path.name, index, game.title, record.name,
                     raw[C64_CONTROL], raw[C64_SHARE]))
    print(f"C64: {len(rows)} records, {C64_CONTROL:#05x} control, "
          f"{C64_SHARE:#05x} share")
    partition = collections.Counter(row[5] for row in rows)
    for value, count in sorted(partition.items()):
        print(f"  ${value:02X}  x{count:<4d}  {reading(value)}")
        if value:
            for row in rows:
                if row[5] == value:
                    print(f"        {row[4]:<18s} {row[3]:<28s} "
                          f"{row[1]}:{row[2]}  share {row[6]}")
    shares = collections.Counter(row[6] for row in rows if row[5] >= 0x80)
    print(f"  share byte of the {sum(shares.values())} engine-driven "
          f"records: {dict(sorted(shares.items()))}")
    return len(rows)


def census_dos(want_built: bool) -> int:
    """Partition the DOS control and share bytes per title."""
    roots = [r for r in (dostailcensus.archives(),
                         pathlib.Path(__file__).resolve().parent.parent / "work")
             if r is not None]
    specs, skipped = dostailcensus.collect(roots, want_built)
    print(f"\nDOS: {len(specs)} distinct records under "
          + ", ".join(str(r) for r in roots))
    for other, n in sorted(skipped.items()):
        print(f"  skipped {n} record(s) under {other}: the same record "
              f"size as a title read here, and not the same id space")
    by_title = collections.defaultdict(list)
    for spec in specs:
        by_title[spec.shape.title].append(spec)
    for title in sorted(by_title):
        specs = by_title[title]
        control, share = dos_offsets(specs[0].shape)
        print(f"\n  {title} -- control {control:#05x}, share {share:#05x}, "
              f"{len(specs)} records")
        partition = collections.Counter(s.data[control] for s in specs)
        for value, count in sorted(partition.items()):
            print(f"    ${value:02X}  x{count:<4d}  {reading(value, 'dos')}")
            if value:
                for spec in specs:
                    if spec.data[control] == value:
                        print(f"          {spec.who:<28s} {spec.path.name}"
                              f"  share {spec.data[share]}")
        shares = collections.Counter(s.data[share] for s in specs)
        print(f"    share: {dict(sorted(shares.items()))}")
    return sum(len(v) for v in by_title.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--c64", action="store_true", help="the C64 half only")
    ap.add_argument("--dos", action="store_true", help="the DOS half only")
    ap.add_argument("--disk", action="append", default=[],
                    help="another C64 disk image to include; repeatable")
    ap.add_argument("--built", action="store_true",
                    help="include the DOS records this project wrote")
    args = ap.parse_args(argv)

    both = not (args.c64 or args.dos)
    print("A record is evidence about the game only if we know who wrote it "
          "(.claude/rules/testing.md).")
    if both or args.c64:
        census_c64([pathlib.Path(d).expanduser() for d in args.disk])
    if both or args.dos:
        census_dos(args.built)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
