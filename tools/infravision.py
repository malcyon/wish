#!/usr/bin/env python3
"""Where a Gold Box character's infravision comes from, and what happens to it.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)` reports `infravision` as dropped on all three C64 → DOS rows, and
the reason on the ticket -- "the destination recomputes it from race" -- had
never been demonstrated.  This is the tool that answers it, in three modes:

    tools/infravision.py table                     the generator's own tables
    tools/infravision.py read work/x.d64           race and stored byte, per slot
    tools/infravision.py stage --source a.d64 --out b.d64

**`table`** reads the race-indexed table the C64 character generator writes
record `0x0D5` from, off the player's own `GEN` overlay, and disassembles the
five instructions that use it.  Pool of Radiance and Curse of the Azure Bonds
carry the same seven numbers; Secret of the Silver Blades has no such write.

**`read`** prints every occupied slot of a C64 save: name, race, the stored
`0x0D5`, and what the generator's table says that race should hold.  That is
how a staged disk is read back after the engine has saved over it.

**`stage`** copies a save disk and sets `0x0D5` to values the character's race
does *not* imply -- a dwarf to 0, a human to 6 -- so that a load-and-resave in
the running game can say whether the engine recomputes the byte or keeps what
it was given.  Staging a value the race would have produced anyway proves
nothing, which is why the defaults are chosen to contradict.

Nothing here writes to the player's disks: `stage` refuses to write over its
own source, and `table` and `read` only read.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import games, savegame  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import d6502, gamedisks  # noqa: E402

#: Where the record keeps it.  `goldbox/layout.py`'s `infravision`.
INFRAVISION = 0x0D5

#: Where the race code lives, for the report's own lookup.
RACE = 0x072

#: Per title: the disk-set key `tools/gamedisks.py` knows it by, the file the
#: character generator is in, the address the generator's table is indexed
#: from, and the address of the instruction that reads it.  Both addresses are
#: **as the overlay runs**, which is `$0800` whatever the file header says
#: (`docs/118-debug-mode.md`); the two are three bytes apart because the read
#: is `LDA <table>,X` with X holding the race code.
GENERATORS = {
    "pool-of-radiance": ("pool-of-radiance", "POOL3.D64", "GEN", 0x0E5C,
                         0x0952),
    "curse-of-the-azure-bonds": ("curse-of-the-azure-bonds", "CURSE_A.D64",
                                 "GEN", 0x0C4B, 0x0C11),
}

#: The overlay base every C64 file here is disassembled at.
OVERLAY_BASE = 0x0800


def _overlay(disks: pathlib.Path, image: str, name: str) -> bytes:
    """The payload of one overlay, with its two load-address bytes off."""
    _, payload = split_load_address(D64.open(disks / image).read_file(name))
    return payload


def race_table(key: str = "pool-of-radiance") -> list[int]:
    """The seven numbers the generator writes, races 1 to 7 in the title's
    own numbering.  Read off the player's own disk every time; nothing here
    is transcribed."""
    disks_key, image, name, table, _ = GENERATORS[key]
    where = gamedisks.find(disks_key)
    if where is None:
        raise SystemExit(f"no disks for {disks_key}; see tools/gamedisks.py")
    payload = _overlay(pathlib.Path(where), image, name)
    at = table - OVERLAY_BASE
    return list(payload[at + 1:at + 8])


def show_table() -> None:
    for key, (disks_key, image, name, table, site) in GENERATORS.items():
        game = games.BY_KEY[key]
        where = gamedisks.find(disks_key)
        if where is None:
            print(f"{game.title}: no disks ({disks_key})")
            continue
        payload = _overlay(pathlib.Path(where), image, name)
        print(f"== {game.title}: {image}:{name}, table ${table:04X}")
        for line in d6502.lines(payload, OVERLAY_BASE, site - 3, 4):
            print("   ", line)
        names = games.race_table(game)
        for code in range(1, 8):
            value = payload[table - OVERLAY_BASE + code]
            print(f"    race {code} {names.get(code, '?'):9s} "
                  f"0x0D5 = {value}  ({value * 10} feet)")
        print()


def show(disk: pathlib.Path) -> list[tuple[int, str, int, int]]:
    """One row per occupied slot: index, name, race code, stored byte."""
    image = D64.open(disk)
    game, sg0, _ = savegame.load_save(image)
    names = games.race_table(game)
    table = race_table(game.key) if game.key in GENERATORS else None
    rows = []
    print(f"== {disk.name} ({game.title})")
    for slot in sg0.slots:
        if not slot.occupied:
            continue
        window = slot.window
        name = window[:20].rstrip(b"\x00").decode("ascii", "replace")
        race, stored = window[RACE], window[INFRAVISION]
        expected = table[race - 1] if table and 1 <= race <= 7 else None
        mark = "" if expected is None or expected == stored else "  <- differs"
        print(f"   slot {slot.index} {name:18s} "
              f"race {race} {names.get(race, '?'):9s} "
              f"0x0D5 = {stored:3d}   generator writes "
              f"{'?' if expected is None else expected}{mark}")
        rows.append((slot.index, name, race, stored))
    return rows


def stage(source: pathlib.Path, out: pathlib.Path,
          sets: dict[int, int] | None = None) -> dict[int, int]:
    """Copy `source` to `out` and contradict the race of every slot it can.

    With no `--set`, the rule is: a character whose race gives him infravision
    gets 0, and a character whose race gives him none gets 6.  Either way the
    stored byte is a value his race does not imply, so a resave that agrees
    with the race is the engine recomputing and not a coincidence.
    """
    if source.resolve() == out.resolve():
        raise SystemExit("stage writes a copy; --out must differ from --source")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, out)
    image = D64.open(out)
    game, sg0, sg1 = savegame.load_save(image)
    table = race_table(game.key) if game.key in GENERATORS else None
    applied = {}
    for slot in sg0.slots:
        if not slot.occupied:
            continue
        window = bytearray(slot.window)
        race = window[RACE]
        if sets and slot.index in sets:
            value = sets[slot.index]
        elif table and 1 <= race <= 7:
            value = 0 if table[race - 1] else 6
        else:
            continue
        window[INFRAVISION] = value
        sg0.write_record(slot.index, bytes(window))
        applied[slot.index] = value
    savegame.store_save(image, sg0, sg1, game)
    image.save(out)
    print(f"staged {out}")
    show(out)
    return applied


def _pair(text: str) -> tuple[int, int]:
    slot, _, value = text.partition("=")
    return int(slot), int(value, 0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="mode", required=True)
    sub.add_parser("table", help="the generator's own race table")
    r = sub.add_parser("read", help="race and stored byte, per slot")
    r.add_argument("disk", type=pathlib.Path, nargs="+")
    s = sub.add_parser("stage", help="write a copy whose bytes contradict race")
    s.add_argument("--source", type=pathlib.Path, required=True)
    s.add_argument("--out", type=pathlib.Path, required=True)
    s.add_argument("--set", type=_pair, action="append", metavar="SLOT=VALUE",
                   help="an explicit value for one slot, instead of the "
                        "contradict-the-race rule")
    args = p.parse_args(argv)
    if args.mode == "table":
        show_table()
    elif args.mode == "read":
        for disk in args.disk:
            show(disk)
    else:
        stage(args.source, args.out, dict(args.set or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
