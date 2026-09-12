#!/usr/bin/env python3
"""Convert a C64 or DOS party into Amiga Curse or Silver Blades records.

`#384 (Write an Amiga Curse or Silver Blades character, so a C64 or DOS party
has an Amiga to arrive on)` built `goldbox.amiga.write_later`; this is the
driver that runs it over a whole party, and the harness for the thing that
would close that issue -- a converted party in front of the running game.

    tools/amigalaterwrite.py --source work/copy-of-ssb.d64
    tools/amigalaterwrite.py --source work/copy-of-ssb.d64 --report
    tools/amigalaterwrite.py --source work/copy-of-ssb.d64 \\
        --compare work/copy-of-secret-A.adf
    tools/amigalaterwrite.py --source work/copy-of-ssb.d64 \\
        --into work/copy-of-secret-A.adf --from A --to B --out work/run.adf

Four things it does, cheapest first:

* **convert**, and print one line a character: the block length the loader
  will compute, the item and effect counts, and how many drop lines the
  conversion produced;
* `--report`, the whole provenance summary for each character, which is the
  account that every byte of the block came from somewhere named;
* `--compare`, against an Amiga disk, a raw `savgam<L>.dat`/`.sav`, or a
  directory of either: for every converted character whose **name** matches
  one on the other side, print the fields that differ.  SSI shipped the same
  six people on the C64, DOS and the Amiga, so for Silver Blades this is the
  conversion marked against the answer;
* `--into ... --out`, which rebuilds a saved game on a copy of an Amiga disk
  with the converted party in it -- `tools/amigasavegame.py`'s `rebuild`,
  the same call `tools/amigalaterslot.py` makes when it edits a party that
  was already there.

The `--source` is read-only, `--into` is opened read-only, and `--out` is
required before anything is written.  Nothing here starts an emulator.

**DOS and the C64 both work**, and the two paths differ in one thing: a C64
source keeps the paladin's and the ranger's innate effect and
a DOS one does not, because `goldbox.dos.write` filtered it out on the way
into the DOS file -- #388.  So a party that has been round the C64-to-DOS
conversion arrives here already missing it.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import (  # noqa: E402
    amiga_later,
    amiga_port,
    c64_codec,
    dos_codec,
    items,
    neutral,
)
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import amigasavegame  # noqa: E402

#: The drawer both later titles keep their saved games in, and the two names
#: they use -- `tools/amigalaterslot.py`'s constants, not a second guess.
SAVE_DRAWER = "SAVE"
SUFFIXES = (".dat", ".sav")
#: The letters the slot picker offers, which is what a save is named after.
SLOT_LETTERS = "ABCDEFGHIJ"

#: The fields `--compare` prints, which are the ones a player reads off the
#: character sheet.  Everything else in the record is heap, art or state that
#: two saves of the same person are entitled to disagree about.
SHEET_FIELDS = ("race", "char_class", "alignment", "sex", "age",
                "class_levels", "hp_max", "copper", "silver", "electrum",
                "gold", "platinum", "gems", "jewelry", "armour_class",
                "thac0_base", "size", "level") + neutral.ABILITIES


def c64_party(path: pathlib.Path) -> list:
    """Every character on a C64 save disk, as neutral records."""
    disk = D64.open(str(path))
    game, save0, save1 = load_save(disk)
    out = []
    for slot in save0.characters:
        roster = save1.roster(slot.index) if save1 is not None else None
        inventory = [i.raw for i in
                     items.items_for_slot(save0.to_bytes(), slot.index)]
        out.append(c64_codec.read(slot.record, roster=roster,
                                  inventory=inventory, game=game,
                                  source=f"{path.name} slot {slot.index}"))
    return out


def dos_party(folder: pathlib.Path) -> list:
    """Every `CHRDAT*.SAV` in a DOS save directory, as neutral records."""
    out = []
    for path in sorted(folder.glob("CHRDAT*.SAV")):
        out.append(dos_codec.to_neutral(dos_codec.read_character(path)))
    return out


def party_from(source: pathlib.Path) -> list:
    """Whichever of the two the `--source` is, refused rather than guessed."""
    if source.is_dir():
        party = dos_party(source)
        if not party:
            raise SystemExit(f"{source}: no CHRDAT*.SAV in it")
        return party
    if source.suffix.lower() != ".d64":
        raise SystemExit(f"{source}: a C64 save is a .d64 and a DOS save is "
                         f"a directory of CHRDAT*.SAV")
    return c64_party(source)


def amiga_records(where: pathlib.Path) -> dict:
    """Every Amiga Curse or Silver Blades character in a file or directory.

    Keyed by the stripped, upper-cased name, which is what a comparison has
    to go by: nothing else in the two records is a stable identifier, and the
    Amiga's own copy of a name can carry a trailing space the C64's does not
    (#308).
    """
    paths: list[pathlib.Path] = []
    if where.is_dir():
        for suffix in SUFFIXES:
            paths.extend(sorted(where.glob(f"savgam*{suffix}")))
    else:
        paths.append(where)
    out: dict[str, amiga_later.AmigaCharacter] = {}
    for path in paths:
        data = path.read_bytes()
        if path.suffix.lower() == ".adf":
            try:
                disk = AmigaDisk(bytearray(data))
            except AmigaDiskError as bad:
                raise SystemExit(f"{path}: {bad}") from bad
            for letter in SLOT_LETTERS:
                for suffix in SUFFIXES:
                    try:
                        held = disk.read_file(
                            f"/{SAVE_DRAWER}/savgam{letter}{suffix}")
                    except AmigaDiskError:
                        continue
                    out.update(_records_in(held))
            continue
        out.update(_records_in(data))
    return out


def _records_in(data: bytes) -> dict:
    """The party in one saved game, read through **its own** title's shape.

    `amigasavegame.detect` is what says which, from where a record signature
    lands: Curse's party begins at 12825 and Silver Blades' at 5143.  Trying
    the shapes in turn instead finds a Silver Blades saved game as a Curse
    party and reads six characters of rubbish out of it, which is the trap
    this function exists to keep out of the comparison.
    """
    try:
        shape = amigasavegame.detect(data)
    except amigasavegame.AmigaSaveError:
        return {}
    if shape.record_shape is None:
        return {}
    party = amiga_later.party_in_savegame(data, shape.record_shape)
    return {c.name.strip().upper(): c for c in party}


def convert(party) -> list:
    """`(neutral, AmigaCharacter, report)` for every character."""
    out = []
    for char in party:
        built, report = amiga_later.write_later(char)
        out.append((char, built, report))
    return out


def describe(built: amiga_later.AmigaCharacter, report) -> str:
    block = built.block_bytes()
    return (f"{built.name:<16} {built.shape.title[:12]:<12} "
            f"{len(block):>5} bytes  items {len(built.items):>2}  "
            f"effects {len(built.effects)}  "
            f"chains {int(bool(built.item_chain))}/"
            f"{int(bool(built.effect_chain))}  "
            f"unexplained {len(report.unaccounted)}  "
            f"drops {len(report.dropped)}")


def compare(built: amiga_later.AmigaCharacter,
            twin: amiga_later.AmigaCharacter) -> list[str]:
    """The sheet fields where a converted record and a real one disagree."""
    lines = []
    for field in SHEET_FIELDS:
        try:
            ours, theirs = built.get(field), twin.get(field)
        except amiga_port.AmigaRecordError:
            continue
        if ours != theirs:
            lines.append(f"    {field:<24} ours {ours!r}  theirs {theirs!r}")
    ours = [node[0] for node in built.effects]
    theirs = [node[0] for node in twin.effects]
    if ours != theirs:
        lines.append(f"    {'effect ids':<24} ours {ours}  theirs {theirs}")
    return lines


def _slot_path(disk: AmigaDisk, letter: str) -> str:
    for suffix in SUFFIXES:
        path = f"/{SAVE_DRAWER}/savgam{letter}{suffix}"
        try:
            disk.read_file(path)
        except AmigaDiskError:
            continue
        return path
    raise SystemExit(f"no savgam{letter}.dat or .sav in /{SAVE_DRAWER}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, type=pathlib.Path,
                    help="a C64 .d64 or a DOS save directory")
    ap.add_argument("--report", action="store_true",
                    help="the whole provenance summary for each character")
    ap.add_argument("--compare", type=pathlib.Path,
                    help="an Amiga .adf, savgam file or directory to mark "
                         "the conversion against")
    ap.add_argument("--into", type=pathlib.Path,
                    help="an Amiga disk to put the converted party on")
    ap.add_argument("--from", dest="from_slot", default="A",
                    help="the slot on --into whose saved game is rebuilt")
    ap.add_argument("--to", dest="to_slot",
                    help="the slot the rebuilt saved game is written to; "
                         "defaults to --from")
    ap.add_argument("--out", type=pathlib.Path,
                    help="where the new disk image goes; required with "
                         "--into, and never the same file")
    args = ap.parse_args(argv)

    built = convert(party_from(args.source))
    for _char, character, report in built:
        print(describe(character, report))
        for line in report.dropped:
            print(f"    dropped: {line}")
        if args.report:
            print(report.summary())

    if args.compare:
        twins = amiga_records(args.compare)
        if not twins:
            raise SystemExit(f"{args.compare}: no Amiga Curse or Silver "
                             f"Blades record in it")
        print(f"\ncompared with {args.compare}")
        for _char, character, _report in built:
            twin = twins.get(character.name.strip().upper())
            if twin is None:
                print(f"  {character.name}: no record of that name")
                continue
            lines = compare(character, twin)
            print(f"  {character.name}: "
                  + ("agrees on every field" if not lines
                     else f"{len(lines)} differ"))
            for line in lines:
                print(line)

    if args.into:
        if args.out is None:
            raise SystemExit("--into needs --out; the input is read-only")
        if args.out.resolve() == args.into.resolve():
            raise SystemExit("--out must not be --into")
        disk = AmigaDisk(bytearray(args.into.read_bytes()))
        source = _slot_path(disk, args.from_slot.upper())
        save = amigasavegame.parse(disk.read_file(source), source=source)
        rebuilt = amigasavegame.rebuild(
            save, [character for _c, character, _r in built])
        letter = (args.to_slot or args.from_slot).upper()
        target = f"/{SAVE_DRAWER}/savgam{letter}{pathlib.Path(source).suffix}"
        try:
            disk.remove_file(target)
        except AmigaDiskError:
            pass
        disk.write_file(target, rebuilt)
        disk.save(args.out)
        print(f"\n{args.out}: {target}, {len(rebuilt)} bytes, "
              f"{len(built)} characters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
