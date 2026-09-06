#!/usr/bin/env python3
"""Put a saved game our own code wrote in front of Amiga Curse or Silver Blades.

`tools/porslot.py` does this for Amiga *Pool of Radiance*, whose party is six
`CHRDAT<slot><n>.sav` files beside a `savgam<slot>.dat`.  The two later Amiga
titles keep the whole party **inside** the saved game -- record, item nodes and
effect chain, one block a character, with nothing but the party-count word
saying how many there are (`docs/165-amiga-savegame.md`) -- so putting a party
in front of those games means rewriting the container itself, which is what
`tools/amigasavegame.py`'s `rebuild` does and this puts on a disk.

It exists because of the gap `#28 (Decode an Amiga saved game, not just a
character file)` closed last: the format was read out of the save and load
routines and every claim about it was file-internal, because **no Curse or
Silver Blades saved game this project wrote had ever been loaded by the
game**.  A slot written here, booted and drawn is what turns that into a
measurement.

    tools/amigalaterslot.py work/copy-of-curseA.adf --to B --out work/run.adf
    tools/amigalaterslot.py work/copy-of-curseA.adf --to C --out work/run.adf \\
        --keep 3 --rename 1=BJORNDAR --strip-items 2

Each edit is one visible thing, so a screenshot of the party panel says which
file the engine read:

* `--rename n=NAME` renames marching-order character *n* (0-based).  The
  panel draws the name, so a renamed character is the cheapest proof the
  engine loaded our bytes rather than the slot we copied from.
* `--keep n` keeps the first *n* characters, which moves the count word and
  every block boundary after it -- the structural test, since a loader that
  misreads a block length desynchronises the whole party.
* `--strip-items n` empties character *n*'s item chain, which is what makes
  the loader's `tst.l` on the chain head decide correctly.

The input image is opened read-only and `--out` is required.  Nothing here
starts an emulator.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import amigasavegame  # noqa: E402

#: The drawer both later titles keep their saved games in, and the two names
#: they use.  Curse writes `savgam<letter>.dat` and Silver Blades
#: `savgam<letter>.sav`; the picker asks for the letter and nothing else.
SAVE_DRAWER = "SAVE"
SUFFIXES = (".dat", ".sav")


def slot_path(disk: AmigaDisk, letter: str) -> str:
    """`/SAVE/savgam<letter>` with whichever suffix this disk's title uses."""
    for suffix in SUFFIXES:
        path = f"/{SAVE_DRAWER}/savgam{letter}{suffix}"
        try:
            disk.lookup(path)
        except Exception:
            continue
        return path
    raise SystemExit(
        f"no /{SAVE_DRAWER}/savgam{letter}{{{'|'.join(SUFFIXES)}}} on the disk")


def rename(char: amiga.AmigaCharacter, name: str) -> amiga.AmigaCharacter:
    """The same character under a new name, NUL-padded to the sixteen bytes.

    The Amiga name field is sixteen bytes terminated and padded with NUL
    where DOS spends a count byte and fifteen, so a shorter name has to clear
    what was under it -- otherwise the panel draws the tail of the old one.
    """
    encoded = name.encode("latin1")
    if len(encoded) >= amiga.AMIGA_NAME_SIZE:
        raise SystemExit(
            f"'{name}' needs {len(encoded)} bytes and the Amiga name field is "
            f"{amiga.AMIGA_NAME_SIZE} including its terminator")
    raw = bytearray(char.raw)
    raw[:amiga.AMIGA_NAME_SIZE] = encoded.ljust(amiga.AMIGA_NAME_SIZE, b"\0")
    return dataclasses.replace(char, raw=bytes(raw))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", help="an Amiga Curse or Silver Blades disk "
                                      "holding a saved game; opened read-only")
    parser.add_argument("--from", dest="source", default="A",
                        help="the slot letter to read (default A)")
    parser.add_argument("--to", required=True,
                        help="the slot letter to write")
    parser.add_argument("--out", required=True,
                        help="the disk image to write, never the input")
    parser.add_argument("--keep", type=int,
                        help="keep only the first N characters")
    parser.add_argument("--rename", action="append", default=[],
                        metavar="N=NAME",
                        help="rename marching-order character N (0-based)")
    parser.add_argument("--strip-items", type=int, action="append", default=[],
                        metavar="N", help="empty character N's item chain")
    args = parser.parse_args(argv)

    if pathlib.Path(args.out).resolve() == pathlib.Path(args.image).resolve():
        raise SystemExit("--out must not be the input image")

    disk = AmigaDisk.open(args.image)
    path = slot_path(disk, args.source)
    save = amigasavegame.parse(disk.read_file(path), source=path)
    print(f"{args.image}!{path}: {save.shape.title}, {len(save.data)} bytes, "
          f"{save.count} characters")

    party = list(save.characters)
    if args.keep is not None:
        party = party[:args.keep]
    for n in args.strip_items:
        party[n] = dataclasses.replace(party[n], items=())
    for spec in args.rename:
        index, _, name = spec.partition("=")
        party[int(index)] = rename(party[int(index)], name)

    data = amigasavegame.rebuild(save, party)
    out = amigasavegame.parse(data, save.shape, source="rebuilt")
    for claim, ok, detail in amigasavegame.check(out):
        print(f"  [{'ok' if ok else 'NO'}] {claim}: {detail}")
    bad = [claim for claim, ok, _ in amigasavegame.check(out) if not ok]

    target = f"/{SAVE_DRAWER}/savgam{args.to}{path[-4:]}"
    try:
        disk.lookup(target)
    except Exception:
        pass
    else:
        disk.remove_file(target)
    disk.write_file(target, data)
    problems = disk.verify()
    disk.save(args.out)
    print(f"wrote {target}, {len(data)} bytes, into {args.out}")
    for n, char in enumerate(out.characters):
        print(f"  {n}: {char.name:16s} {len(char.items)} items, "
              f"{len(char.effects)} effects")
    if problems:
        print("filesystem: " + "; ".join(problems))
    return 1 if bad or problems else 0


if __name__ == "__main__":
    sys.exit(main())
