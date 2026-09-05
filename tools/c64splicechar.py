#!/usr/bin/env python3
"""Put one DOS character into a C64 save disk's slot, so it can be converted back.

`#243 (Write a converted gnome's four innate effect records, now that the
engine has been watched writing them)` needs a **converted gnome** to load in
DOS, and no C64 save disk on this machine holds a gnome -- twenty disks, races
1, 2, 4 and 7 only.  What this project does hold is three gnomes rolled in DOS
Pool of Radiance's own creation screens under `#84 (Roll a gnome in DOS and
read the two innate effect ids nobody has seen)`, kept as specimens.  So the
gnome that goes into the C64 side is one the DOS engine itself wrote, and the
run measures a round trip rather than a character somebody invented.

    tools/c64splicechar.py --cha ~/wish-specimens/por-dos/WISH-SPEC-gnomf1/halfelf-GNOMF1.CHA \
        --c64 PORSAVE13.D64 --slot 5 --out work/issue243/GNOME.D64

The four per-slot regions are the ones `goldbox.dos.convert_save` writes for a
whole party, at the same offsets and out of the same 580-byte record:

| region | record bytes | where in `SAVEDGAME0`/`1` |
|---|---|---|
| the character record | `[:0x100]` | `$4D00 + 0x100 * slot` |
| the roster block -- AC, THAC0, current hit points, movement | `[0x100:0x120]` | `SAVEDGAME1 + 0x20 * slot` |
| the sixteen item slots | `[0x120:0x220]` | `$5900 + 0x100 * slot` |
| the combat icon | `[0x220:0x244]` | `$4BE0 + 0x24 * slot` |

**The icon is left as the disk already had it.**  A C64 combat icon is 18
`CHARPIC00` screen codes and 18 colours; DOS has no equivalent and
`goldbox.dos.write` does not carry one back, so composing a new one would
change a byte the experiment does not read.  `--icon default` composes one
from the player's own game disk instead, for a slot that was empty.

**The player's disks are read and never written.**  `--out` is where the
modified image goes, and it must not be inside the disk directory.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos  # noqa: E402
from goldbox.d64 import D64, attach_load_address, split_load_address  # noqa: E402
from goldbox.games import POOL_OF_RADIANCE as GAME  # noqa: E402
from goldbox.savegame import SaveGame0, SaveGame1  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent


def find_disk(name: str) -> pathlib.Path:
    """A save disk by name, or by name within the player's disk directory."""
    path = pathlib.Path(name).expanduser()
    if path.exists():
        return path
    from automap.paths import find_disks
    disks = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")
    found = disks / name
    if not found.exists():
        raise SystemExit(f"no such disk: {name} (nor {found})")
    return found


def default_icon() -> bytes:
    """The icon the game's own character creation composes, off the disks.

    The tables are on `POOL3`, so this walks the directory rather than naming
    a side -- the same shape as `tools/dosdisk.py`'s `game_files`.
    """
    from automap.paths import find_disks
    from goldbox.iconparts import IconParts
    disks = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")
    for path in sorted(disks.glob("*.[dD]64")):
        try:
            return IconParts.load(str(path)).default_icon()
        except Exception:
            continue
    raise SystemExit(f"no disk under {disks} carries the icon tables")


def splice(cha: pathlib.Path, disk: pathlib.Path, slot: int,
           out: pathlib.Path, icon: str = "keep") -> dict:
    """Write the DOS character at `cha` into `slot` of a copy of `disk`."""
    if not 0 <= slot < dos.SLOT_COUNT:
        raise SystemExit(f"a C64 save has slots 0..{dos.SLOT_COUNT - 1}")
    image = D64.from_bytes(disk.read_bytes())
    load0, save0 = split_load_address(image.read_file(GAME.save_file))
    load1, save1 = split_load_address(image.read_file(GAME.roster_file))
    save0, save1 = bytearray(save0), bytearray(save1)

    char = dos.read_character(cha)
    rec, report = dos.to_c64_record(
        char, icon=default_icon() if icon == "default" else None)
    # `party_order` in a C64 record is the slot the record lands in, not the
    # marching position -- `goldbox/layout.py` 0x10D, identity in every
    # engine-written save read, and what `dos.convert_save` sets.
    rec.set("party_order", slot)
    raw = rec.to_bytes()

    before = SaveGame0.from_bytes(bytes(save0), GAME).slot(slot)
    was = before.record.name if before.occupied else None

    at = dos.SLOT_AREA - dos.SAVE0_BASE + slot * dos.SLOT_STRIDE
    save0[at:at + dos.SLOT_STRIDE] = raw[:dos.SLOT_STRIDE]
    at = dos.ITEM_AREA - dos.SAVE0_BASE + slot * dos.SLOT_STRIDE
    save0[at:at + dos.SLOT_STRIDE] = raw[0x120:0x220]
    if icon == "default":
        at = dos.ICON_TABLE - dos.SAVE0_BASE + slot * dos.ICON_SIZE
        save0[at:at + dos.ICON_SIZE] = raw[0x220:0x244]
    at = slot * dos.ROSTER_STRIDE
    save1[at:at + dos.ROSTER_STRIDE] = raw[0x100:0x120]

    image.write_file_inplace(GAME.save_file,
                             attach_load_address(load0, bytes(save0)))
    image.write_file_inplace(GAME.roster_file,
                             attach_load_address(load1, bytes(save1)))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)

    check = SaveGame0.from_bytes(bytes(save0), GAME)
    block = SaveGame1(bytes(save1), GAME).roster(slot)
    return {
        "cha": str(cha),
        "disk": str(disk),
        "out": str(out),
        "slot": slot,
        "replaced": was,
        "party": [f"{s.index}:{s.record.name}={s.record.race}"
                  for s in check.characters],
        "roster": {"armour_class": block.armour_class, "thac0": block.thac0,
                   "hit_points": block.hit_points,
                   "movement": block.movement},
        "dropped": report.dropped,
        "warnings": report.warnings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cha", required=True,
                    help="The DOS character record to splice in")
    ap.add_argument("--c64", required=True,
                    help="The C64 save disk to copy (read only)")
    ap.add_argument("--slot", type=int, default=5,
                    help="Which C64 slot to overwrite; 5 becomes CHRDAT<x>1")
    ap.add_argument("--out", required=True, help="Where the new .D64 goes")
    ap.add_argument("--icon", choices=("keep", "default"), default="keep",
                    help="Leave the slot's combat icon, or compose the "
                         "game's own default from the player's disks")
    args = ap.parse_args(argv)

    out = pathlib.Path(args.out).expanduser()
    disk = find_disk(args.c64)
    if out.resolve().parent == disk.resolve().parent:
        raise SystemExit("--out would write beside the player's own disks")
    print(json.dumps(splice(pathlib.Path(args.cha).expanduser(), disk,
                            args.slot, out, args.icon), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
