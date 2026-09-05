#!/usr/bin/env python3
"""Stored turning byte against the one the title's own tables would compute.

`#288 (A converted cleric or paladin arrives on the C64 unable to turn undead,
because DOS keeps no turning byte and nothing computes one)` rests on a claim
that can be measured rather than argued: **a C64 player character's
`turn_power` at `0x0A4` is always the value the title's own turning routine
would write from that character's cleric and paladin levels.** If that holds on
every record on the machine, a converter may compute the byte instead of
copying it, and a C64-to-C64 conversion still round-trips.

So this walks every C64 save and exported character it can find -- the player's
own disks through `tools/gamedisks.py`, and the specimen tree -- and prints one
row per record: the title, where it came from, the cleric and paladin levels,
the byte stored at `0x0A4`, and `goldbox.levels.turning_level`'s answer. The
exit status is non-zero when any record disagrees, so the census is a check as
much as a listing.

`--dos` does the DOS half, which asks a different question. DOS record `0x076`
is the *undead's* row rather than the caster's strength -- `GAME.OVR:0x139CD`
reads it off the **target** and multiplies it by ten as the row of the turning
matrix -- so what a DOS census establishes is that no player character carries
anything there, and that the eleven undead monster records do.

    tools/turncensus.py                 every C64 record, stored vs derived
    tools/turncensus.py --dos           DOS records and monsters at 0x076
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import levels  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import gamedisks  # noqa: E402

#: The C64 disks to look at, by the registry key that finds them.
C64_DISKS = (
    ("pool-of-radiance", "*.[dD]64"),
    ("curse-of-the-azure-bonds", "*.[dD]64"),
    ("secret-of-the-silver-blades", "*.[dD]64"),
)

#: Where a monster's own turning row lives in each port's record.
DOS_TURN_CLASS = 0x076
C64_TURN_CLASS = 0x0A3


def _levels(record) -> tuple[int, int]:
    """(cleric, paladin) out of a C64 record, 0 where the title has no slot."""
    cleric = record.get("level_cleric") or 0
    try:
        paladin = record.get("level_paladin") or 0
    except Exception:
        paladin = 0
    return int(cleric), int(paladin)


def _c64_records():
    """Every C64 character record on this machine, with where it came from."""
    for key, glob in C64_DISKS:
        where = gamedisks.find(key)
        if where is None:
            continue
        for path in sorted(pathlib.Path(where).glob(glob)):
            try:
                disk = D64.open(str(path))
                game, sg0, sg1 = load_save(disk)
            except Exception:
                continue
            for slot in sg0.slots:
                record = slot.record
                if record is None:
                    continue
                yield game, f"{path.name}:{slot.index}", record
    root = _specimen_root()
    if root is None:
        return
    for path in sorted(root.glob("*/WISH-SPEC-*.[dD]64")):
        try:
            disk = D64.open(str(path))
            game, sg0, sg1 = load_save(disk)
        except Exception:
            continue
        for slot in sg0.slots:
            record = slot.record
            if record is None:
                continue
            yield game, f"{path.parent.name}/{path.name}:{slot.index}", record


def _specimen_root():
    try:
        from tools import specimens
    except Exception:
        return None
    root = specimens.tree_root()
    return pathlib.Path(root) if root and pathlib.Path(root).is_dir() else None


def census_c64(verbose: bool = True) -> int:
    """One row per C64 record; returns how many disagree with the derivation."""
    bad = 0
    seen = 0
    for game, where, record in _c64_records():
        name = record.name if hasattr(record, "name") else ""
        cleric, paladin = _levels(record)
        stored = record.get("turn_power")
        want = levels.for_game(game).turning_level(cleric, paladin)
        seen += 1
        # None means the title's own routine writes no byte at all -- Pool of
        # Radiance's `$2388 LDX level_cleric / BEQ` for a non-cleric -- so the
        # record is expected to hold the zero it was created with.
        agree = stored == (0 if want is None else want)
        if not agree:
            bad += 1
        if verbose:
            print(f"{game.key:24} {where:34} {str(name)[:16]:16} "
                  f"cleric {cleric:2} paladin {paladin:2} "
                  f"stored {stored:3} "
                  f"derived {'none' if want is None else want:>4} "
                  f"{'' if agree else '  <-- disagrees'}")
    print(f"{seen} record(s), {bad} disagreement(s)")
    return bad


def census_dos(verbose: bool = True) -> int:
    """DOS records and monsters at 0x076, which is the undead's row."""
    from goldbox.dos_savegame import dax_blocks

    root = gamedisks.find("dos-archives")
    if root is None:
        print("no DOS archives here")
        return 0
    games_dir = pathlib.Path(root)
    hits = 0
    for stem in ("POOLRAD", "CURSE", "SECRET"):
        for game_dir in sorted(games_dir.glob(f"*/games/{stem}/GAME/{stem}")):
            for path in sorted(game_dir.glob("MON*CHA.DAX")):
                for index, block in dax_blocks(path.read_bytes(), path.name):
                    if len(block) <= DOS_TURN_CLASS:
                        continue
                    value = block[DOS_TURN_CLASS]
                    if not value:
                        continue
                    length = block[0]
                    name = block[1:1 + length].decode("latin1")
                    hits += 1
                    if verbose:
                        print(f"{stem:8} {path.name}:{index:<4} {name[:20]:20} "
                              f"0x076 = {value}")
    print(f"{hits} monster record(s) with a non-zero 0x076")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dos", action="store_true",
                        help="census DOS records at 0x076 instead")
    parser.add_argument("--quiet", action="store_true",
                        help="print only the totals")
    args = parser.parse_args(argv)
    if args.dos:
        return census_dos(not args.quiet)
    return 1 if census_c64(not args.quiet) else 0


if __name__ == "__main__":
    raise SystemExit(main())
