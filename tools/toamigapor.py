#!/usr/bin/env python3
"""Write a C64 or DOS Pool of Radiance party into a slot on an Amiga disk.

`tools/porslot.py` copies an Amiga slot into another Amiga slot, so the only
party our code has ever put in front of the Amiga picker came off an Amiga
disk to begin with.  This is the other direction -- the one
`#105 (Write an Amiga Pool of Radiance character, not just a Pools of
Darkness one)` exists for -- and it is what puts a C64 or DOS party on an
Amiga disk the game will load.

    tools/toamigapor.py work/por1.adf --to B --out work/por1-B.adf \\
        --c64 ~/wish-specimens/por-c64/WISH-SPEC-por-party-twin-pair.d64
    tools/toamigapor.py work/por1-B.adf --to D --out work/por1-BD.adf \\
        --dos ~/wish-specimens/por-dos/WISH-SPEC-por-item-granted --dos-slot D

Both readers go through `goldbox/neutral.py`'s `NeutralCharacter` and out
through `goldbox.amiga.write_por`, so this shares every field table, every
declared unsourced list and every drop line with the writers the test suite
already measures.  What cannot be converted is printed rather than dropped
quietly.

**The saved game around the party is the destination disk's own.**  A slot is
six character files plus a `savgam<letter>.dat`, and that container carries
the map, the party's square and the clock -- none of which a character record
holds and none of which crosses a port.  `--container` names the slot whose
saved game is copied and pointed at the new slot's files; it defaults to `A`,
the slot the game ships.  So the party is ours and the place is the disk's,
and a run says so rather than leaving a reader to work it out.

**The input disk is opened read-only and `--out` is required.**  The player's
own disks are never written to; work on a copy.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402


def read_c64_party(path: str) -> list:
    """Every character of a C64 save disk, as neutral records."""
    from goldbox import c64_codec
    from goldbox.d64 import D64
    from goldbox.savegame import load_save

    image = D64.open(str(path))
    game, sg0, sg1 = load_save(image)
    if game.key != "pool-of-radiance":
        raise SystemExit(
            f"{path} is {game.title}, and an Amiga Pool of Radiance slot "
            f"takes a Pool of Radiance party")
    out = []
    for slot in sg0.characters:
        out.append(c64_codec.read(
            slot.record,
            roster=sg1.roster(slot.index) if sg1 is not None else None,
            game=game, source=str(path)))
    return out


def read_dos_party(folder: str, slot: str) -> list:
    """Every character of a DOS saved game's slot, as neutral records.

    The title is checked before any conversion work, the way
    `read_c64_party` checks it.  Without that, pointing this at a DOS Curse
    or Silver Blades folder printed a full report that looked like a working
    conversion and then died several calls down in `write_por` with `a DOS
    Pool of Radiance record is 285 bytes, got 422` -- a traceback naming a
    size rather than the thing that was actually wrong.  A conversion is
    between two ports of the same title
    (`.claude/rules/conversions.md`), and an Amiga Pool of Radiance slot
    takes a Pool of Radiance party.
    """
    from goldbox import dos

    party = dos.read_party(folder, slot)
    shape = party[0].shape
    if shape.key != "pool-of-radiance":
        raise SystemExit(
            f"{folder} slot {slot} is {shape.title}, and an Amiga Pool of "
            f"Radiance slot takes a Pool of Radiance party")
    return [dos.to_neutral(char) for char in party]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("disk", help="an Amiga Pool of Radiance disk 1 image")
    parser.add_argument("--to", dest="target", required=True,
                        help="the slot letter to write, A to J")
    parser.add_argument("--out", required=True,
                        help="where the new image is written")
    parser.add_argument("--container", default="A",
                        help="the slot whose saved game is copied around the "
                             "party (default A)")
    parser.add_argument("--c64", help="a C64 Pool of Radiance save disk")
    parser.add_argument("--dos", help="a DOS Pool of Radiance save folder")
    parser.add_argument("--dos-slot", default="A",
                        help="which DOS slot to read (default A)")
    args = parser.parse_args(argv)

    if bool(args.c64) == bool(args.dos):
        raise SystemExit("give exactly one of --c64 and --dos")

    if args.c64:
        party = read_c64_party(args.c64)
        source = args.c64
    else:
        party = read_dos_party(args.dos, args.dos_slot)
        source = f"{args.dos} slot {args.dos_slot}"
    if not party:
        raise SystemExit(f"{source} holds no characters")

    disk = AmigaDisk.open(args.disk)
    container = amiga.por_savegame_filename(args.container.upper())
    try:
        savegame = disk.read_file(f"/{amiga.POR_SAVE_DRAWER}/{container}")
    except AmigaDiskError:
        raise SystemExit(
            f"{args.disk} has no {container}; --container names a slot the "
            f"disk already has") from None

    print(f"{source}: {len(party)} character(s)")
    for char in party:
        for line in char.dropped:
            print(f"    not converted: {line}")
        for line in char.warnings:
            print(f"    {line}")

    written = amiga.write_por_slot(disk, args.target, party, savegame)
    problems = disk.verify()
    if problems:
        raise SystemExit("the new disk does not verify:\n  "
                         + "\n  ".join(problems))
    disk.save(args.out)
    for path in written:
        print(f"  wrote {path}")
    print(f"{args.out}: slot list {amiga.read_slot_list(disk)}, "
          f"{disk.free_count()} blocks free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
