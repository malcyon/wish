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

**The saved game around the party is built from the source save, not copied**
(#316).  A slot is one to six character files plus a `savgam<letter>.dat`, and
that container carries the map, the party's square, the clock and the quest
flags -- so a copied one would stand a converted party where SSI's party
stood.  All 13,141 bytes are written from the C64 or DOS save being converted,
with a declared reason for every byte it leaves zero; `--provenance` prints
the accounting.

The one thing that cannot come from the source is the **area's own script**,
7680 bytes of it, live on load.  The Amiga keeps every area's in a single
`ecl.dax` on disk 2, the `POOLDATA` volume, so **a conversion needs the
player's disk 2**: name it with `--data-disk`, or leave it out and the disk on
the command line is searched for an `ecl.dax` of its own.

`--container <letter>` is the old behaviour and is an experiment rather than a
conversion: it copies that slot's saved game off the disk on the command line,
so the party is ours and the place is somebody else's.  The run says so.

**`--save-disk` writes a save disk instead of a copy of the game disk**, which
is what a player is actually handed (#36):

    tools/toamigapor.py work/por2.adf --to B --save-disk work/poolsave.adf \\
        --c64 ~/wish-specimens/por-c64/WISH-SPEC-por-party-twin-pair.d64

That output is an 880K floppy named `POOLSAVE` with no game code on it at all
-- put it in any drive beside the game disk and answer `LOAD SAVED GAME`'s
`PATH FOR SAVE  RETURN = POOLSAVE:` with a bare RETURN.  The disk named on the
command line is read for one thing only, the area's script, so **disk 2 is
what a save disk needs** and the party's own disk 1 is not read at all.

**The input disk is opened read-only, and one of `--out` and `--save-disk` is
required.**  The player's own disks are never written to; work on a copy.
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


ECL_DAX = "/ecl.dax"


def read_ecl_dax(args) -> bytes:
    """The Amiga `ecl.dax`, off `--data-disk` or off the disk on the line.

    Named rather than searched for, because "the game's data disk" is a thing
    the player has in their hand and a wrong guess here is a party arriving in
    an area nobody chose.  A disk with no `ecl.dax` says which disk it needs.
    """
    where = args.data_disk or args.disk
    try:
        return AmigaDisk.open(where).read_file(ECL_DAX)
    except AmigaDiskError:
        raise SystemExit(
            f"{where} has no {ECL_DAX}, and the area's own script is the one "
            f"thing a converted saved game cannot be built without. It is on "
            f"Pool of Radiance disk 2, the POOLDATA volume; name it with "
            f"--data-disk") from None


def build_savegame(args, party_size: int, portraits: bool):
    """The 13,141-byte saved game, built from the save being converted."""
    from goldbox import games
    from goldbox.d64 import load_payload

    if args.c64:
        payload = load_payload(args.c64,
                               games.by_key("pool-of-radiance").save_file)
        state = amiga.por_state_from_c64(payload, args.c64)
    else:
        folder = pathlib.Path(args.dos)
        slot = args.dos_slot.upper()
        savgam = folder / f"SAVGAM{slot}.DAT"
        if not savgam.exists():
            raise SystemExit(f"{savgam} is not there, and the saved game is "
                             f"where the party's square and clock live")
        state = amiga.por_state_from_dos(savgam.read_bytes(), str(savgam))
    return amiga.new_por_savegame(state, args.target, party_size,
                                  read_ecl_dax(args), portraits=portraits)


def provenance_lines(report) -> list[str]:
    """One line per run of bytes sharing a provenance, in file order."""
    out: list[str] = []
    start = 0
    for i in range(1, report.total + 1):
        if (i == report.total
                or report.sources.get(i) != report.sources.get(start)):
            why = report.sources.get(start, "NOTHING WROTE THIS")
            out.append(f"{report.address(start)}: {i - start} bytes -- {why}")
            start = i
    return out


def _walk_names(disk) -> list[str]:
    """Every file on a disk, for the run's own report.

    `write_por_slot` returns the paths it wrote, which is the whole of a game
    disk's news but only most of a save disk's: the volume itself and
    `charlist.txt` came from `make_por_save_disk` and a player is entitled to
    see what is actually on the floppy they are handed.
    """
    return sorted(path for path, entry in disk.walk() if not entry.is_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("disk",
                        help="an Amiga Pool of Radiance disk: disk 2 for a "
                             "save disk, or the disk 1 being copied for --out")
    parser.add_argument("--to", dest="target", required=True,
                        help="the slot letter to write, A to J")
    parser.add_argument("--out",
                        help="where a copy of the input disk, with the slot "
                             "written into its save drawer, is put")
    parser.add_argument("--save-disk", dest="save_disk",
                        help="where a freshly formatted POOLSAVE save disk, "
                             "carrying the slot and no game code, is put")
    parser.add_argument("--data-disk", dest="data_disk",
                        help="the Amiga disk holding ecl.dax, which is disk 2 "
                             "(POOLDATA); defaults to the disk named above")
    parser.add_argument("--container",
                        help="an experiment, not a conversion: copy this "
                             "slot's saved game off the input disk instead of "
                             "building one, so the place is somebody else's")
    parser.add_argument("--provenance", action="store_true",
                        help="print where every byte of the saved game came "
                             "from, one line per run of bytes")
    parser.add_argument("--c64", help="a C64 Pool of Radiance save disk")
    parser.add_argument("--dos", help="a DOS Pool of Radiance save folder")
    parser.add_argument("--dos-slot", default="A",
                        help="which DOS slot to read (default A)")
    args = parser.parse_args(argv)

    if bool(args.c64) == bool(args.dos):
        raise SystemExit("give exactly one of --c64 and --dos")
    if bool(args.out) == bool(args.save_disk):
        raise SystemExit("give exactly one of --out and --save-disk")

    # "The input disk is opened read-only" is a promise this module's own
    # docstring makes, and writing the result back over the source is the one
    # way to break it.  The player keeps their disks somewhere this script is
    # pointed at by hand, so naming the same file twice is a typo away.
    # `tools/porslot.py` has refused it from the start; this one did not.
    written_to = args.out or args.save_disk
    if pathlib.Path(written_to).resolve() == pathlib.Path(args.disk).resolve():
        raise SystemExit(
            f"that is the input disk ({args.disk}); write somewhere else")

    if args.c64:
        party = read_c64_party(args.c64)
        source = args.c64
    else:
        party = read_dos_party(args.dos, args.dos_slot)
        source = f"{args.dos} slot {args.dos_slot}"
    if not party:
        raise SystemExit(f"{source} holds no characters")

    disk = AmigaDisk.open(args.disk)
    report = None
    if args.container:
        container = amiga.por_savegame_filename(args.container.upper())
        try:
            savegame = disk.read_file(f"/{amiga.POR_SAVE_DRAWER}/{container}")
        except AmigaDiskError:
            raise SystemExit(
                f"{args.disk} has no {container}; --container names a slot "
                f"the disk already has") from None
    else:
        savegame, report = build_savegame(
            args, party_size=len(party),
            portraits=any(char.get("portrait_head") for char in party))

    print(f"{source}: {len(party)} character(s)")
    for char in party:
        for line in char.dropped:
            print(f"    not converted: {line}")
        for line in char.warnings:
            print(f"    {line}")
    if report is None:
        print(f"  the saved game is {args.container.upper()}'s off "
              f"{args.disk}: the party is this one and the place, the clock "
              f"and the quest flags are that slot's")
    else:
        for line in report.converted:
            print(f"    {line}")
        print(f"    the saved game is built: "
              f"{len(report.sources)}/{report.total} bytes accounted for, "
              f"{len(report.unwritten)} left to nobody")
        if args.provenance:
            for line in provenance_lines(report):
                print(f"      {line}")

    if args.save_disk:
        # A save disk is not a copy of anything: it is formatted here, and the
        # only byte of the input that reaches it is the saved game read above.
        out_path, drawer = args.save_disk, ""
        disk = amiga.make_por_save_disk(args.target, party, savegame)
        written = [p for p in _walk_names(disk)]
    else:
        out_path, drawer = args.out, amiga.POR_SAVE_DRAWER
        written = amiga.write_por_slot(disk, args.target, party, savegame)
    problems = disk.verify()
    if problems:
        raise SystemExit("the new disk does not verify:\n  "
                         + "\n  ".join(problems))
    disk.save(out_path)
    for path in written:
        print(f"  wrote {path}")
    print(f"{out_path}: volume {disk.volume_name!r}, slot list "
          f"{amiga.read_slot_list(disk, drawer)}, "
          f"{disk.free_count()} blocks free")
    if args.save_disk:
        print("  put it in any drive and answer PATH FOR SAVE with RETURN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
