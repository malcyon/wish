#!/usr/bin/env python3
"""Put an Amiga *Pool of Radiance* party in front of New Phlan's harbour master.

The only reason this exists is that **no Amiga saved game made outdoors had
ever been read** (`#321 (An Amiga Pool of Radiance conversion refuses a party
standing on the travel grid, because no outdoor Amiga saved game has ever been
read)`), and the only way to get one is to make the game's own engine sail a
party onto the travel grid and save there.

Walking the whole way is not available.  Every route from the shipped slot's
square to the harbour crosses an event square, and one of them runs
`NEWECL 8`, which teleports the party into Phlan City Hall.  So this edits the
**input** and lets the engine compute the output, which is the experiment
`.claude/rules/testing.md` allows: the engine does not care how a byte got
there, and every byte the run is *about* is one the engine writes for itself
afterwards.

## What the script does, and why only these two values are staged

`ECL00`'s square dispatch is `$9B4C ONGOTO [$9800], 28, ...`, indexed by the
square's own script id out of the `GEO`.  Entry 2 is the harbour master at
`$9C43` and entry 1 is the boat at `$9BA6`.  In `GEO00` the only square with
id 2 is `(11, 1)` and the only one with id 1 is `(15, 1)`; the Amiga's
`geo.dax` block 0 is byte for byte the C64's `GEO00` past its two-byte header,
1024 of 1024, so the same two squares are the harbour on both ports.

* **The party goes to `(11, 2)` facing north**, one square south of the
  harbour master, because `$9C43` opens `COMPARE [$C04D], 0 / IF<> / EXIT` --
  it only speaks to a party that arrived heading north -- and `(11, 1)` has no
  passable north edge, so north is the only way onto it.
* **`$4AA7` goes to 255.**  `$9C5C COMPARE [$4AA7], 254 / IF< / GOTO [$9D54]`
  sends a party below 254 to the branch that writes `$4AC4 = 0`, and `$4AC4`
  of 0 is the free ferry to Sokol Keep rather than a passage to the coast.
  254 and 255 are this script's own "set" values (`$AB8A SAVE 254, [$4AB8]`,
  `$AB90 SAVE 255, [$4AC8]`).
* **Nothing else, and in particular not `$4AC4`.**  Staging the destination
  looks like it should work and does not: the area's own entry-4 prologue
  opens `$9AF2 SAVE 0, [$4AC4]`, so the engine zeroes it the moment New Phlan
  loads.  Measured -- a run staged with `$4AC4 = 2` boarded the boat and the
  game answered *"THE BOAT DISEMBARKS YOU AT SOKAL KEEP"*, which is the
  `$4AC4 = 0` arm.  The passage has to be bought from the harbour master in
  the same visit.

The square's wall byte and square property go to zero with it.  Both are
`fn(x, y, facing)` the step routine recomputes, and
`docs/196-the-amiga-saved-game-built.md` §4 measured the engine's own resave
holding zero in both.

    tools/porboat.py work/321/por1.adf --out work/321/por1-harbour.adf
    tools/porboat.py work/321/por1.adf --report

Then, in the running game: step forward once for the harbour master, buy any
passage but the first and the last, turn east, and walk `(11,1)` to `(15,1)`.

The input image is opened read-only and `--out` is required to write one.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from goldbox import amiga_por  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402

#: The square south of the harbour master, and the facing that steps onto him.
#: `goldbox.geo`'s numbering -- 0 north, 1 east, 2 south, 3 west -- and the
#: saved game stores it doubled.
HARBOUR_APPROACH = (11, 2)
HARBOUR_SQUARE = (11, 1)
BOAT_SQUARE = (15, 1)
FACING_NORTH = 0

#: `ECL00 $9C5C` sends a party holding less than 254 to the branch that writes
#: the free Sokol Keep ferry into `$4AC4` instead of offering the four coastal
#: passages.
HARBOUR_OFFERS = 0x4AA7
HARBOUR_OFFERS_SET = 255
#: `$9BA6` exits when this is zero, so a party the harbour master has never
#: spoken to cannot board.  He sets it himself at `$9D29`; it is here so a
#: report can show it.
HARBOUR_SPOKEN = 0x4A01
#: The destination he sold, `$9BE3`-`$9C40`: 0 Sokol Keep, 1 area 27 at
#: (9,29), 2 area 26 at (7,29), 3 area 26 at (13,27).  **Not staged** -- the
#: area prologue zeroes it on entry.
PASSAGE = 0x4AC4
#: The square property's own VM word; byte 12804 is its low byte.
SQUARE_PROPERTY_WORD = 0x5200


def report(save: bytes) -> list[str]:
    """The values this tool reads or writes, as they stand."""
    x, y, facing = (save[amiga_por.POR_POS_X], save[amiga_por.POR_POS_Y],
                    save[amiga_por.POR_POS_FACING])
    return [
        f"square           ({x},{y}) facing {facing} (doubled)",
        f"wall in front    {save[amiga_por.POR_WALL_BYTE]}",
        f"square property  {save[amiga_por.POR_SQUARE_PROPERTY]}",
        f"view type        {save[amiga_por.POR_VIEW_TYPE]}",
        f"$4AA7            {amiga_por.por_word(save, HARBOUR_OFFERS)}",
        f"$4A01            {amiga_por.por_word(save, HARBOUR_SPOKEN)}",
        f"$4AC4            {amiga_por.por_word(save, PASSAGE)}",
        f"$5200            {amiga_por.por_word(save, SQUARE_PROPERTY_WORD)}",
    ]


def stage(save: bytes,
          square: tuple[int, int] = HARBOUR_APPROACH,
          facing: int = FACING_NORTH) -> bytes:
    """The same saved game, with the party about to meet the harbour master."""
    if len(save) != amiga_por.POR_SAVEGAME_SIZE:
        raise SystemExit(f"an Amiga Pool of Radiance saved game is "
                         f"{amiga_por.POR_SAVEGAME_SIZE} bytes, got {len(save)}")
    out = bytearray(save)
    out[amiga_por.POR_POS_X], out[amiga_por.POR_POS_Y] = square
    out[amiga_por.POR_POS_FACING] = facing * 2
    out[amiga_por.POR_WALL_BYTE] = 0
    out[amiga_por.POR_SQUARE_PROPERTY] = 0
    amiga_por.por_put_word(out, SQUARE_PROPERTY_WORD, 0)
    amiga_por.por_put_word(out, HARBOUR_OFFERS, HARBOUR_OFFERS_SET)
    return bytes(out)


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("disk", help="an Amiga Pool of Radiance disk 1 image")
    parser.add_argument("--slot", default="A", help="the save slot (default A)")
    parser.add_argument("--out", help="where to write the edited image")
    parser.add_argument("--report", action="store_true",
                        help="print the slot's values and change nothing")
    args = parser.parse_args(argv)

    disk = AmigaDisk(pathlib.Path(args.disk).read_bytes())
    drawer = amiga_por.por_save_drawer(disk)
    path = amiga_por.por_save_path(
        amiga_por.por_savegame_filename(args.slot.upper()), drawer)
    save = disk.read_file(path)

    print(f"{args.disk} {disk.volume_name!r} {path}")
    for line in report(save):
        print("  before  " + line)
    if args.report:
        return 0
    if not args.out:
        raise SystemExit("--out names the image to write, or --report to look")

    staged = stage(save)
    for line in report(staged):
        print("  after   " + line)
    print(f"  step north onto {HARBOUR_SQUARE} for the harbour master, then "
          f"east to {BOAT_SQUARE} for the boat")
    disk.write_file(path, staged)
    problems = disk.verify()
    if problems:
        raise SystemExit("the edited image does not verify:\n  "
                         + "\n  ".join(problems))
    pathlib.Path(args.out).write_bytes(disk.to_bytes())
    print(f"  wrote {args.out}, verified clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
