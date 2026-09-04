#!/usr/bin/env python3
"""Pull the Amiga *Curse* and *Silver Blades* character specimens out of the disks.

The twenty-one records `#55 (Decode the Amiga Curse and Silver Blades
records)` rests on are not loose files on any machine.  They are inside
AmigaDOS disk images, in two shapes:

* **eleven `SAVE/*.guy` pregenerated characters** on Curse of the Azure Bonds
  disk 1 -- ARIEL, BJORN DARKSTONE, GALAIN, GWYDION, HOLLAND, IILANDA,
  KAROLYN, LIGHTMOON, STORMBRINGER, SUNDRA and TEUT HALF-ELFIN, 428 to 468
  bytes, each a 428-byte record followed by its effect nodes;
* **the party inside a saved game** -- four played characters in
  `SAVE/savgamA.dat` on Curse disk 1, carrying items, and the six shipped
  Silver Blades characters in `SAVE/savgamA.sav` on Silver Blades disk 1.

`tools/amigasaves.py` is the same idea for Amiga Pool of Radiance and does
not find these: it looks for files of exactly 288 bytes in a lowercase
`save/` drawer, and none of these is either.  The two are kept apart rather
than merged because what counts as a specimen is different in each -- a fixed
size there, a record signature here.

    tools/amigarecords.py -o work/amiga-later-saves

The disks are opened **read-only**; nothing is written anywhere but `--out`.
`tests/test_amiga.py` calls :func:`extract` itself when the environment names
no directory, so the corpus is never only in a scratch directory -- which is
what `#211 (103 tests skip on the machine that has the game files, and the
game files are not why)` was about.

Names, and why they are prefixed
--------------------------------
Two disks can hold `savgamA.dat`, so each file is written as
`<volume>-<name>` -- `CurseA-GALAIN.guy`, `Secret1-savgamA.sav`.  The saved
games are copied whole rather than cut into records, because the party is
found by scanning for the record signature and a caller should be able to
re-run that scan rather than trust the cut this tool made.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.amiga import (  # noqa: E402
    AMIGA_SHAPES,
    looks_like_amiga_record,
    party_in_savegame,
)
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools import amigasaves, gamedisks  # noqa: E402

#: The drawer both titles keep their saves in.  Uppercase on the game disks,
#: where Pool of Radiance uses a lowercase `save`.
SAVE_DRAWER = "save"

#: A saved game, either title's spelling of it.
SAVEGAME_SUFFIXES = (".dat", ".sav")


def _record_file(data: bytes) -> bool:
    """Whether a file is a character record with its tail, `.guy`-style."""
    return any(len(data) >= shape.record_size
               and looks_like_amiga_record(data, 0, shape)
               for shape in AMIGA_SHAPES)


def _savegame_party(data: bytes) -> int:
    """How many character blocks a saved game holds, across both shapes."""
    return max((len(party_in_savegame(data, shape))
                for shape in AMIGA_SHAPES), default=0)


def specimens(roots: list[pathlib.Path] | None = None):
    """Every Curse or Silver Blades specimen on those disks.

    Yields `(label, volume, name, data, what)`, where `what` is `"record"`
    for a `.guy`-style file and `"savegame"` for a saved game with a party
    in it.  `label` is where it came from, so a report can be checked.
    """
    for label, image in amigasaves.images(roots):
        try:
            disk = AmigaDisk(image)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            parts = path.strip("/").split("/")
            if len(parts) != 2 or parts[0].lower() != SAVE_DRAWER:
                continue
            try:
                data = disk.read_file(path)
            except AmigaDiskError:
                continue
            if _record_file(data):
                yield label, disk.volume_name, parts[1], data, "record"
            elif (parts[1].lower().endswith(SAVEGAME_SUFFIXES)
                  and _savegame_party(data)):
                yield label, disk.volume_name, parts[1], data, "savegame"


def extract(out: pathlib.Path,
            roots: list[pathlib.Path] | None = None,
            report: list[str] | None = None) -> list[pathlib.Path]:
    """Write every specimen under `out`, and return the paths written."""
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written: list[pathlib.Path] = []
    for label, volume, name, data, what in specimens(roots):
        here = out / f"{volume.replace(' ', '')}-{name}"
        # Three copies of each set are on this machine and their save
        # drawers are byte-identical.  A later write is a no-op; one that is
        # not is a specimen nobody has seen rather than something to
        # overwrite quietly.
        if here.exists() and here.read_bytes() != data:
            raise SystemExit(
                f"{here.name} differs between two images: {label} does not "
                f"agree with what is already there. Extract them to separate "
                f"directories and say which is which")
        here.write_bytes(data)
        written.append(here)
        if report is not None:
            extra = ("" if what == "record"
                     else f", {_savegame_party(data)} characters")
            report.append(f"{here.name:<28} {len(data):>6} bytes  "
                          f"{what}{extra}   {label}")
    return sorted(set(written))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--out", required=True,
                        help="the directory the specimens are written to")
    parser.add_argument("--disks", action="append", default=None,
                        help="a directory of Amiga disk images; repeatable. "
                             "Defaults to gamedisks.toml's `amiga` entry")
    args = parser.parse_args(argv)

    roots = ([pathlib.Path(d).expanduser() for d in args.disks]
             if args.disks else None)
    where = roots if roots is not None else gamedisks.candidates("amiga")
    if not where:
        raise SystemExit("No Amiga disks: set $AMIGA_DISKS or pass --disks")

    lines: list[str] = []
    found = extract(pathlib.Path(args.out), roots, lines)
    for line in lines:
        print(line)
    if not found:
        raise SystemExit(
            "No Curse or Silver Blades character records under "
            + ", ".join(str(p) for p in where))
    print(f"{len(found)} files into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
