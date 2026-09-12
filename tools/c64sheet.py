#!/usr/bin/env python3
"""Print a C64 save's party the way a character sheet lays it out.

The mirror of `tools/dosdisk.py --sheet`, `tools/cursedisk.py --sheet` and
`tools/ssbdisk.py --sheet`, which all read a **DOS** folder.  This one reads
a `.d64`, so a C64 → DOS conversion can be checked the way
`.claude/rules/conversions.md` asks for -- every field on the destination's
own sheet against the source, read as words rather than as bytes.

    tools/c64sheet.py ~/wish-specimens/por-c64/WISH-SPEC-curse-trained-party.D64

Works for all three C64 titles: `goldbox.savegame.load_save` identifies the
title off the disk's own directory, and every field below comes through
`goldbox.c64_codec.read`, which is the same reader
`goldbox.dos.new_dos_save` uses -- so a difference between this and the DOS
sheet is the writer or the engine, never a second reading of the C64 bytes.

Nothing is written.  The disk is opened read only.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_codec  # noqa: E402
from goldbox.c64_port import classes_to_names, race_table  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.items import items_for_slot, load_item_names  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import gamedisks  # noqa: E402

#: Which registry entry holds each title's sides, for the item-name table.
#: The names live on the game disks rather than in the save, so a run with
#: no disks prints the item count and no names rather than failing.
DISK_ENTRY = {
    "pool-of-radiance": "pool-of-radiance",
    "curse-of-the-azure-bonds": "curse-of-the-azure-bonds",
    "secret-of-the-silver-blades": "secret-of-the-silver-blades",
}


def item_names(game, disks: str | None) -> dict[int, str] | None:
    """The title's item-name table off the player's own sides, or None.

    Read only, and never fatal: an item's name is a nicety beside the
    numbers, and a machine with no disks still has to be able to print a
    sheet.
    """
    where = pathlib.Path(disks).expanduser() if disks else \
        gamedisks.find(DISK_ENTRY.get(game.key, ""))
    if where is None:
        return None
    for side in sorted(pathlib.Path(where).glob("*.[dD]64")):
        try:
            return load_item_names(str(side), game)
        except Exception:
            continue
    return None

#: `60 - value`, the family's encoding for armour class and THAC0, as
#: `tools/cursedisk.py` has it.  The sheet shows the decoded number.
AC_BIAS = 60
SEXES = ("MALE", "FEMALE")
ALIGNMENTS = tuple(f"{law} {mood}"
                   for law in ("LAWFUL", "NEUTRAL", "CHAOTIC")
                   for mood in ("GOOD", "NEUTRAL", "EVIL"))


def party_lines(disk_path: pathlib.Path,
                disks: str | None = None) -> list[str]:
    """One block per character, in the C64 save's own slot order."""
    disk = D64.from_bytes(disk_path.read_bytes())
    game, sg0, sg1 = load_save(disk)
    payload = sg0.to_bytes()
    names = item_names(game, disks)
    out = [f"{disk_path.name}: {game.title}, "
           f"{len(sg0.characters)} characters"]
    for index, char_slot in enumerate(sg0.characters):
        block = sg1.roster(char_slot.index) if sg1 is not None else None
        carried = items_for_slot(payload, char_slot.index, names)
        inv = [i.raw for i in carried]
        char = c64_codec.read(char_slot.record, roster=block, inventory=inv,
                              game=game, source=f"C64 slot {char_slot.index}")
        n = char.fields

        def v(name, default=0):
            return n[name].value if name in n else default

        coins = " ".join(f"{kind.upper()} {v(kind)}" for kind in
                         ("platinum", "gold", "electrum", "silver", "copper",
                          "gems", "jewelry") if v(kind))
        levels = ", ".join(f"{name} {count}" for name, count
                           in (v("levels", {}) or {}).items() if count)
        memorised = [s for s in (v("spells_memorised", []) or []) if s]
        race = race_table(game).get(v("race"), f"race {v('race')}")
        out += [
            "",
            f"  {index + 1}. {v('name', '')}   (C64 slot {char_slot.index})",
            f"     {SEXES[v('sex') & 1]} {race.upper()} AGE {v('age')}"
            f"  {ALIGNMENTS[v('alignment')]}"
            f"  {'/'.join(classes_to_names(v('class_bits'), game)).upper()}",
            f"     STR {v('strength')}"
            + (f"({v('exceptional_strength')})"
               if v("exceptional_strength") else "")
            + f" INT {v('intelligence')} WIS {v('wisdom')} "
              f"DEX {v('dexterity')} CON {v('constitution')} "
              f"CHR {v('charisma')}",
            f"     LEVEL {levels}  EXP {v('experience')}",
            f"     HITPOINTS {v('hp_current')} of {v('hp_max')}  "
            f"AC {AC_BIAS - v('armour_class')}  "
            f"THAC0 {AC_BIAS - v('thac0_current')}  "
            f"MOVE {v('movement_current')}",
            "     SAVES paralysis " + str(v("save_paralysis"))
            + f" petrification {v('save_petrification')}"
            + f" wands {v('save_wands')} breath {v('save_breath')}"
            + f" spell {v('save_spell')}",
            f"     {coins or 'no money'}",
            f"     {len(v('inventory', []) or [])} items, "
            f"{len(memorised)} spells memorised",
        ]
        for item in carried:
            out.append(f"       - {item.name or '(no name table)'}"
                       f"  x{item.quantity}"
                       + ("  readied" if item.readied else ""))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("disk", help="the .d64 to read; never written")
    p.add_argument("--disks", default=None,
                   help="the player's sides for this title, for the "
                        "item-name table; read, never written. Defaults to "
                        "the gamedisks registry")
    args = p.parse_args(argv)
    for line in party_lines(pathlib.Path(args.disk).expanduser(), args.disks):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
