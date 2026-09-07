#!/usr/bin/env python3
"""Does the editor's Class combo show what a conversion writes?

`#393 (A dual-classed Curse character may show one class in the editor and
convert as another, and no specimen exists to tell)`.  Two parts of Wish
answer "what class is this character", and they ask the question differently:

* `editor/window.py`'s `_char_class_shown` -- what the Class combo draws --
  calls `goldbox.classcode.repair(raw, class_bits, game=...)`, the mask alone;
* the conversion reads the record through `goldbox.c64_codec.read`, whose own
  call to `repair` passes `levels` and `former_levels` too, so a **dual-classed**
  character is read off the level array instead of off the mask.

For a character who trained out of one class into another those two can differ,
and this walks a corpus asking whether they ever do.  It calls the shipped
functions -- `editor.window._char_class_shown` and `goldbox.c64_codec.read` --
rather than re-deriving either rule, so a change to either side moves what this
prints.

    tools/classcombocheck.py                          # the specimen tree
    tools/classcombocheck.py --c64 work/issue393      # a directory or a .d64
    tools/classcombocheck.py --dos ~/wish-specimens/coab-dos --dual-only

It also prints, per C64 record, the bitmask the **level array** implies beside
the stored `class_bits`.  Those two being equal is why the two paths agree:
Curse's `GEN $20A3` writes the old class's level back into the array and ORs
its bit into the mask in the same routine, under one test, so a C64 record is
never caught between the two states (`docs/192-curse-dual-class.md`).

Exit status is 1 when any record's two answers disagree, so this can be run as
a check.  Nothing here writes anything; every disk and record is opened read
only.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

# The tool imports `editor/window.py` to use the real combo rule rather than a
# copy of it, and that pulls in Qt.  Nothing here builds a widget, but an
# assignment (not a `setdefault`) is what keeps a window off Donald's desktop
# whatever the caller's environment says.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from editor.window import _char_class_shown  # noqa: E402
from goldbox import c64_codec, dos, dos_layout, games, items  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402

#: Class name -> its bit, in the neutral order every port's mask uses once
#: `goldbox.dos.neutral_class_bits` has folded DOS's paladin and ranger back.
#: The same table `tools/classcodecensus.py` carries, for the same reason: the
#: bitmask a level array implies is not a field any record stores.
BIT_FOR_CLASS = {"magic-user": 0x01, "cleric": 0x02, "thief": 0x04,
                 "fighter": 0x08, "knight": 0x10, "paladin": 0x40,
                 "ranger": 0x80}


def bits_from_levels(levels: dict | None) -> int:
    """The bitmask of the classes a character currently holds levels in."""
    out = 0
    for name, level in (levels or {}).items():
        if level:
            out |= BIT_FOR_CLASS.get(name, 0)
    return out


def c64_rows(root: pathlib.Path):
    """One row per character in every C64 save under `root`."""
    paths = sorted(root.rglob("*.[dD]64")) if root.is_dir() else [root]
    for path in paths:
        try:
            game, sg0, sg1 = load_save(D64.open(str(path)))
        except Exception as exc:                      # noqa: BLE001
            print(f"  skipped {path.name}: {exc}")
            continue
        for slot in sg0.characters:
            record = slot.record
            block = sg1.roster(slot.index) if sg1 is not None else None
            inv = [i.raw for i in items.items_for_slot(sg0.to_bytes(),
                                                       slot.index)]
            neutral = c64_codec.read(record, roster=block, inventory=inv,
                                     game=game, source=path.name)
            stored = record.get("char_class")
            bits = record.get("class_bits") or 0
            levels = {k: v for k, v in (neutral.get("levels") or {}).items()
                      if v}
            former = {k: v for k, v in
                      (neutral.get("former_levels") or {}).items() if v}
            yield {"where": f"{path.name}#{slot.index}",
                   "who": record.name.strip(),
                   "title": game.title if game else "?",
                   "port": "c64", "stored": stored, "bits": bits,
                   "level_bits": bits_from_levels(levels),
                   "levels": levels, "former": former,
                   "combo": _char_class_shown(stored, record, game),
                   "converted": neutral.get("char_class")}


def dos_rows(root: pathlib.Path):
    """The same for every DOS character record under `root`, **converted
    first**.

    `editor/roster.py`'s `Party` opens a `.d64` and nothing else, so a DOS
    record only ever reaches the Class combo after `File > Import` has turned
    it into a C64 one.  Measuring the combo rule against a raw DOS record
    would be measuring a call that cannot happen -- and it reads wrong, since
    DOS gives the paladin and the ranger one bit between them where the
    neutral order gives the ranger bit 7 (`goldbox.dos.neutral_class_bits`).
    So this walks the same road the player does: `goldbox.dos.to_neutral`
    then `goldbox.c64_codec.write`, and asks the two questions of the C64
    record that comes out.
    """
    paths = sorted(root.rglob("*")) if root.is_dir() else [root]
    for path in paths:
        if not path.is_file():
            continue
        if path.stat().st_size not in dos_layout.SHAPES_BY_SIZE:
            continue
        if not path.name.upper().startswith("CHRDAT"):
            continue
        try:
            char = dos.read_character(path)
            imported, _rep = c64_codec.write(dos.to_neutral(char))
        except Exception as exc:                      # noqa: BLE001
            print(f"  skipped {path.parent.name}/{path.name}: {exc}")
            continue
        game = games.by_title(char.shape.title)
        back = c64_codec.read(imported, game=game, source=path.name)
        stored = imported.get("char_class")
        bits = imported.get("class_bits") or 0
        levels = {k: v for k, v in (back.get("levels") or {}).items() if v}
        former = {k: v for k, v in (back.get("former_levels") or {}).items()
                  if v}
        yield {"where": f"{path.parent.name}/{path.name}",
               "who": imported.name.strip(), "title": char.shape.title,
               "port": "dos->c64", "stored": stored, "bits": bits,
               "level_bits": bits_from_levels(levels),
               "levels": levels, "former": former,
               "combo": _char_class_shown(stored, imported, game),
               "converted": back.get("char_class")}


def report(rows, dual_only: bool = False, quiet: bool = False) -> int:
    """Print one line per record and a count per title.  Returns the number
    of records whose two answers disagree."""
    seen: collections.Counter = collections.Counter()
    dual: collections.Counter = collections.Counter()
    bad: collections.Counter = collections.Counter()
    split: collections.Counter = collections.Counter()
    for row in rows:
        key = f"{row['port']} {row['title']}"
        seen[key] += 1
        is_dual = bool(row["former"])
        dual[key] += 1 if is_dual else 0
        if row["port"] == "c64" and row["bits"] != row["level_bits"]:
            split[key] += 1
        disagrees = row["combo"] != row["converted"]
        bad[key] += 1 if disagrees else 0
        if dual_only and not is_dual:
            continue
        if quiet and not disagrees:
            continue
        mark = "DISAGREE" if disagrees else "agree"
        print(f"  {row['where']:<52} {row['who']:<10} "
              f"stored={row['stored']} bits={row['bits']:#04x} "
              f"level_bits={row['level_bits']:#04x} "
              f"levels={row['levels']} former={row['former']} "
              f"-> combo {row['combo']}, converted {row['converted']}  "
              f"{mark}")
    for key in sorted(seen):
        print(f"{key}: {seen[key]} records, {dual[key]} dual-classed, "
              f"{bad[key]} where the combo and the conversion disagree, "
              f"{split[key]} whose stored mask differs from the one their "
              f"level array implies")
    return sum(bad.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--c64", action="append", default=[],
                    help="a directory or a .d64 of C64 saves, repeatable")
    ap.add_argument("--dos", action="append", default=[],
                    help="a directory of DOS records, repeatable")
    ap.add_argument("--dual-only", action="store_true",
                    help="print only the dual-classed records")
    ap.add_argument("--quiet", action="store_true",
                    help="print only the disagreements and the counts")
    args = ap.parse_args(argv)

    c64 = [pathlib.Path(p).expanduser() for p in args.c64]
    dosr = [pathlib.Path(p).expanduser() for p in args.dos]
    if not c64 and not dosr:
        tree = pathlib.Path(os.environ.get("WISH_SPECIMENS")
                            or pathlib.Path.home() / "wish-specimens")
        c64 = [d for d in sorted(tree.glob("*-c64")) if d.is_dir()]
        dosr = [d for d in sorted(tree.glob("*-dos")) if d.is_dir()]
        if not c64 and not dosr:
            print(f"no specimen tree at {tree}")
            return 0

    bad = 0
    for root in c64:
        print(f"== C64: {root}")
        bad += report(c64_rows(root), args.dual_only, args.quiet)
    for root in dosr:
        print(f"== DOS: {root}")
        bad += report(dos_rows(root), args.dual_only, args.quiet)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
