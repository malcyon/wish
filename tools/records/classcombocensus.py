#!/usr/bin/env python3
"""Which class combinations the character corpus actually holds, per title and port.

Kept from `#345 (Draw a letter in each combat-map square saying what is standing
there, instead of the index the backend counts with)`, where a combat-map label
has to fit the longest class combination a character can carry. For every C64
save it can open and every DOS character record it finds, it reads the
characters' non-zero class levels and prints, per port and title, how many
records there are, how many carry a dual-class old level, and each combination
with its count.

    tools/records/classcombocensus.py [--c64-root DIR ...] [--dos-root DIR ...]

The roots searched by default are the specimen tree (`$WISH_SPECIMENS`,
`por-c64` and `por-dos`), the Pool of Radiance disks directory
(`automap.paths.find_disks()`), and the shipped archives' `games/*/GAME/*`
directories (`tools/gamedisks.py`'s `dos-archives`). `--c64-root` and
`--dos-root` add directories, which is how a scratch directory is counted.

**This counts what is there, and it is not evidence about the game**: a
directory nobody watched being written -- Donald's own play saves above all,
which `.claude/rules/testing.md` says to assume edited -- counts every edit as a
combination the game allows. Everything is opened read only.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import c64_codec, dos_codec, dos_port, items  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import gamedisks, specimens  # noqa: E402


def default_roots():
    tree = specimens.tree_root()
    c64 = [tree / "por-c64"]
    disks = find_disks()
    if disks is not None:
        c64.append(disks)
    dos = [tree / "por-dos"]
    archives = gamedisks.find("dos-archives")
    if archives is not None:
        dos += archives.glob("*/games/*/GAME/*")
    return c64, dos


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--c64-root", action="append", default=[],
                        type=pathlib.Path,
                        help="an extra directory of C64 disk images")
    parser.add_argument("--dos-root", action="append", default=[],
                        type=pathlib.Path,
                        help="an extra directory of DOS character records")
    args = parser.parse_args(argv)

    c64_roots, dos_roots = default_roots()
    c64_roots += args.c64_root
    dos_roots += args.dos_root

    combos = collections.defaultdict(collections.Counter)
    dual = collections.Counter()
    seen = collections.Counter()
    c64paths = []
    for r in c64_roots:
        if r.is_dir():
            c64paths += sorted(set(r.rglob("*.[dD]64"))
                               | set(r.rglob("*.d64.orig"))
                               | set(r.rglob("*.D64.orig")))
    for path in c64paths:
        try:
            game, sg0, sg1 = load_save(D64.open(str(path)))
        except Exception:
            continue
        title = (game.title if game else "?")
        for slot in sg0.characters:
            rec = bytes(slot.record.to_bytes())
            try:
                n = c64_codec.read(
                    slot.record,
                    roster=sg1.roster(slot.index) if sg1 else None,
                    inventory=[i.raw for i in items.items_for_slot(
                        sg0.to_bytes(), slot.index)],
                    game=game, source=path.name)
            except Exception:
                continue
            lv = {k: v for k, v in (n.get("levels") or {}).items() if v}
            combos["C64 " + title][frozenset(lv)] += 1
            seen["C64 " + title] += 1
            if rec[0x0BA]:
                dual["C64 " + title] += 1
    for r in dos_roots:
        if not r.is_dir():
            continue
        for path in sorted(r.rglob("*")):
            if (not path.is_file()
                    or path.stat().st_size not in dos_port.DELTAS_BY_SIZE):
                continue
            try:
                ch = dos_codec.read_character(path)
            except Exception:
                continue
            raw = ch.raw("class_levels")
            lv = {nm: raw[i] for i, nm in dos_codec.CLASS_BY_SLOT.items()
                  if i < len(raw) and raw[i]}
            key = "DOS " + ch.deltas.title
            combos[key][frozenset(lv)] += 1
            seen[key] += 1
            try:
                if ch.get("dual_class_level"):
                    dual[key] += 1
            except Exception:
                pass
    for key in sorted(combos):
        print(f"\n== {key}: {seen[key]} records, {dual[key]} with a "
              f"dual-class old level stored")
        for combo, n in combos[key].most_common():
            print(f"   {n:4d}  {'/'.join(sorted(combo)) or '(no class levels)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
