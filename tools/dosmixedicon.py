#!/usr/bin/env python3
"""Find, or stage, a small DOS character wearing an option only the large list has.

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)` ends in a table whose rows are Donald's judgement, and nine of
those rows name a C64 option a **small** character's own lists do not hold:
six weapon rows and three head rows land at or above the small counts (28
weapons, 14 heads) against the large lists' 35 and 23.  A small character on
one of those rows is composed out of the large list instead, which is a
mixed-size icon -- something the game's own ICON menu reaches, because
`SPELLN64` never stores the size byte back, and something already on the
player's disks (HOGARTH's).

Whether such a figure *reads* as a whole figure on the screen is a look, and
a look needs a specimen.  This finds one or makes one.

    tools/dosmixedicon.py --census
    tools/dosmixedicon.py --stage work/issue130/mixedparty --slot J \\
        --from ~/dos_por_play/SAVE

`--census` reads every `.SAV` and `.CHA` under the DOS corpora and reports
every record whose `size` is 1 and whose row lands past a small list -- the
question "does one exist already?", asked of the whole machine rather than
of one party.

`--stage` copies a party into a directory of your own and rewrites the
`icon_head` `0x0BD` and `icon_body` `0x0BE` of its **small** characters so
that each wears one of the nine rows.  `size` `0x0C0` is left alone, because
it is the race's and changing it would move two things at once; the colours
are left alone too, so the only difference from the party it was copied from
is which figure a small character asks for.  Editing an *input* and watching
the game compute from it is the valid half of the distinction
`.claude/rules/testing.md` draws.

`tools/dosiconstage.py` is the neighbouring tool and a different job: it
gives a party of six identical figures six different ones, so that "each
character got his own" can be told from "all six got one".  This one is
about a single row of the table rather than about the party.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos  # noqa: E402
from goldbox.iconparts import dos_icon_tables  # noqa: E402

ICON_HEAD = 0x0BD
ICON_BODY = 0x0BE

#: Where DOS saves live on this machine.  Read only; `--stage` copies out.
CORPORA = (
    pathlib.Path.home() / "dos_por_play" / "SAVE",
    pathlib.Path.home() / "wish-specimens" / "por-dos",
    pathlib.Path.home() / "Downloads" / "fr-archives",
)

#: The C64's small lists, which are what a row has to clear to be composable
#: at a small character's own size.  Read off `SPELLE64` by
#: `goldbox.iconparts.IconParts.count`; repeated here only so `--census` can
#: run with no game disks attached, and checked against the file by
#: `tests/test_iconpackaging.py`.
SMALL_WEAPONS = 28
SMALL_HEADS = 14


def mixed_rows(tables=None) -> tuple[list[int], list[int]]:
    """The DOS bodies and heads whose rows only the large list can compose."""
    tables = tables or dos_icon_tables()
    return ([b for b, c in sorted(tables.weapons.items()) if c >= SMALL_WEAPONS],
            [h for h, c in sorted(tables.heads.items()) if c >= SMALL_HEADS])


def census(roots=CORPORA, tables=None) -> tuple[int, list[dict]]:
    """Every small record already wearing a large-only option, and how many read."""
    tables = tables or dos_icon_tables()
    read, hits = 0, []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.upper() not in (".SAV", ".CHA"):
                continue
            try:
                char = dos.read_character(path)
                head, body = char.get("icon_head"), char.get("icon_body")
                size = char.get("size")
            except Exception:
                continue
            read += 1
            if size != 1 or head not in tables.heads or body not in tables.weapons:
                continue
            weapon, c64_head = tables.weapons[body], tables.heads[head]
            if weapon >= SMALL_WEAPONS or c64_head >= SMALL_HEADS:
                hits.append({"path": str(path), "name": char.name,
                             "icon_head": head, "icon_body": body,
                             "c64_weapon": weapon, "c64_head": c64_head})
    return read, hits


def stage(source: pathlib.Path, slot: str, into: pathlib.Path,
          tables=None) -> list[dict]:
    """Copy the party and put a large-only row on every small character."""
    tables = tables or dos_icon_tables()
    bodies, heads = mixed_rows(tables)
    if not bodies or not heads:
        raise SystemExit("no row in the table lands past a small list")
    into.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if path.is_file():
            shutil.copy(path, into / path.name)
    written, n = [], 0
    for path in sorted(into.glob(f"CHRDAT{slot}?.SAV")):
        data = bytearray(path.read_bytes())
        char = dos.read_character(path)
        if char.get("size") != 1:
            continue
        data[ICON_BODY] = bodies[n % len(bodies)]
        data[ICON_HEAD] = heads[n % len(heads)]
        path.write_bytes(bytes(data))
        after = dos.read_character(path)
        written.append({"file": path.name, "name": after.name,
                        "icon_head": after.get("icon_head"),
                        "icon_body": after.get("icon_body"),
                        "size": after.get("size"),
                        "c64_weapon": tables.weapons[after.get("icon_body")],
                        "c64_head": tables.heads[after.get("icon_head")]})
        n += 1
    if not written:
        raise SystemExit(f"no small character in slot {slot} of {source}")
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--census", action="store_true",
                   help="report every small record already on a large-only row")
    p.add_argument("--stage", default=None,
                   help="the directory to copy the party into and edit")
    p.add_argument("--from", dest="source", default=None,
                   help="the DOS save directory to copy; read, never written")
    p.add_argument("--slot", default=None, help="the DOS save slot letter")
    args = p.parse_args(argv)

    tables = dos_icon_tables()
    bodies, heads = mixed_rows(tables)
    print(f"{len(bodies)} weapon rows land past the small list of "
          f"{SMALL_WEAPONS}: "
          + ", ".join(f"DOS body {b} -> C64 weapon {tables.weapons[b]}"
                      for b in bodies))
    print(f"{len(heads)} head rows land past the small list of {SMALL_HEADS}: "
          + ", ".join(f"DOS head {h} -> C64 head {tables.heads[h]}"
                      for h in heads))

    if args.census:
        read, hits = census(tables=tables)
        print(f"{read} DOS records read; {len(hits)} are small characters "
              f"already wearing a large-only option")
        for hit in hits:
            print(f"    {hit['name']:<14} head {hit['icon_head']:>2} "
                  f"body {hit['icon_body']:>2} -> C64 weapon "
                  f"{hit['c64_weapon']:>2} head {hit['c64_head']:>2}  "
                  f"{hit['path']}")
    if args.stage:
        if not args.source or not args.slot:
            p.error("--stage needs --from and --slot")
        for row in stage(pathlib.Path(args.source), args.slot,
                         pathlib.Path(args.stage), tables):
            print(f"{row['file']} {row['name']:<14} head {row['icon_head']:>2} "
                  f"body {row['icon_body']:>2} size {row['size']} -> "
                  f"C64 weapon {row['c64_weapon']:>2} head {row['c64_head']:>2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
