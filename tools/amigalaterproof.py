#!/usr/bin/env python3
"""Put a converted Amiga Curse or Silver Blades party in front of the engine.

`tools/amigalaterwrite.py` builds the party and writes a disk;
`goldbox.amiga.write_later` is what it calls.  What neither of them can do is
the last step of
`#384 (Write an Amiga Curse or Silver Blades character, so a C64 or DOS party
has an Amiga to arrive on)` -- boot the disk and read the engine's answer back
off it.  This is the two halves of that run:

    tools/amigalaterproof.py build --source party.d64 --into disk1.adf \\
        --from A --to B --first 'Guy de Valois' --out work/384/run.adf
    tools/amigalaterproof.py diff --ours work/384/run.adf --ours-slot B \\
        --theirs work/384/resave.sav

**`--first` is the whole reason this is not `amigalaterwrite.py --into`.**
The writer's highest-risk choice is that it writes a **boolean** chain head --
1 or 0 according to whether a node follows -- where `write_por` writes NULL,
because the later titles' loaders `tst.l` the head and read a node only when
it is non-zero.  A head that is wrong does not spoil one character: the
loader's file position desynchronises and **everything after that character
is read out of the wrong bytes**.  So the character with the items has to be
put in front of the others rather than behind them, and the C64 save this
converts from happens to keep its only item-carrying character last.

`diff` is the other half.  The engine loads what we wrote, the player camps
and saves, and the two parties are compared block by block -- masked by the
lists the writers **declare** (`goldbox.amiga.LATER_WRITE_UNSOURCED`,
`LATER_WRITE_DERIVED`, `LATER_ITEM_WRITE_UNSOURCED`,
`LATER_EFFECT_WRITE_UNSOURCED` and `goldbox.dos`'s six, mapped through the
title's shift map) and never by whatever happened to differ, which is
`.claude/rules/conversions.md`'s rule and the reason a new difference is a
failure rather than a wider mask.  `LATER_WRITE_DERIVED` is the one the
engine itself recomputes on load -- `#402 (Amiga Curse recomputes
thac0_current and a roster_tail byte on load, and no declared list says
so)` is the run that put `thac0_current` and one `roster_tail` byte there.

`tools/porslotdiff.py` is the Pool of Radiance equivalent and does not fit
these two, whose party lives inside the saved game rather than in `CHRDAT`
files beside it.  Every input is opened read-only and `--out` is required.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga, dos, dos_layout  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools import amigalaterwrite, amigasavegame  # noqa: E402

SAVE_DRAWER = amigalaterwrite.SAVE_DRAWER
SUFFIXES = amigalaterwrite.SUFFIXES


# ---------------------------------------------------------------------------
# The mask, built from what the writers declare
# ---------------------------------------------------------------------------

#: The DOS writer's own tables, by name rather than by offset, so that a new
#: entry in one of them shows up here instead of quietly widening the mask.
#: `tests/test_amigalaterwrite.py` builds the same set for the round trip.
_DOS_TABLES = ("WRITE_UNSOURCED", "WRITE_UNSOURCED_LATER", "WRITE_DERIVED",
               "WRITE_DERIVED_LATER", "WRITE_CONSTANTS", "WRITE_DEFAULTS")


def declared_record_mask(shape: amiga.AmigaDeltas) -> set[int]:
    """Amiga record offsets the two sides are allowed to disagree in."""
    names: set[str] = set()
    for table in _DOS_TABLES:
        for row in getattr(dos, table):
            names.add(row[0])
    out: set[int] = set()
    for field in dos_layout.layout_for(shape.dos):
        if field.name not in names:
            continue
        try:
            at = shape.offset(field.offset)
        except amiga.AmigaRecordError:
            continue
        out.update(range(at, at + field.size))
    for at, size, _why in amiga.LATER_WRITE_UNSOURCED[shape.key]:
        out.update(range(at, at + size))
    for at, size, _why in amiga.LATER_WRITE_DERIVED[shape.key]:
        out.update(range(at, at + size))
    return out


def declared_block_mask(char: amiga.AmigaCharacter) -> set[int]:
    """The same over a whole block: record, then item nodes, then effects."""
    shape = char.shape
    out = declared_record_mask(shape)
    at = shape.record_size
    for _ in char.items:
        for offset, size, _why in amiga.LATER_ITEM_WRITE_UNSOURCED:
            out.update(range(at + offset, at + offset + size))
        at += shape.item_size
    for _ in char.effects:
        for offset, size, _why in amiga.LATER_EFFECT_WRITE_UNSOURCED:
            out.update(range(at + offset, at + offset + size))
        at += shape.effect_size
    return out


def field_at(shape: amiga.AmigaDeltas, offset: int) -> str:
    """Which field of the record an Amiga offset lands in, for a diff line."""
    for field in dos_layout.layout_for(shape.dos):
        try:
            at = shape.offset(field.offset)
        except amiga.AmigaRecordError:
            continue
        if at <= offset < at + field.size:
            return f"{field.name}+{offset - at}"
    if shape.spellbook_bytes is not None:
        book = amiga.AMIGA_SSB_SPELLBOOK_AT
        if book <= offset < book + shape.spellbook_bytes:
            return f"spellbook+{offset - book}"
    return "-"


def part_at(char: amiga.AmigaCharacter, offset: int) -> str:
    """Which part of a block an offset is in: the record, a node, or past it."""
    shape = char.shape
    if offset < shape.record_size:
        return f"record {field_at(shape, offset)}"
    at = offset - shape.record_size
    if at < len(char.items) * shape.item_size:
        return f"item {at // shape.item_size} +0x{at % shape.item_size:03x}"
    at -= len(char.items) * shape.item_size
    return f"effect {at // shape.effect_size} +0x{at % shape.effect_size:03x}"


# ---------------------------------------------------------------------------
# Reading a party out of whatever it was handed
# ---------------------------------------------------------------------------

def slot_path(disk: AmigaDisk, letter: str) -> str:
    """Where a slot's saved game is on this disk, `.dat` or `.sav`.

    The suffix is the title's, not the caller's: Curse writes `savgamA.dat`
    and Silver Blades `savgamA.sav`, and a slot written under the other
    title's name is one the picker never offers.
    """
    for suffix in SUFFIXES:
        where = f"/{SAVE_DRAWER}/savgam{letter}{suffix}"
        try:
            disk.read_file(where)
        except AmigaDiskError:
            continue
        return where
    raise SystemExit(f"no savgam{letter}.dat or .sav in /{SAVE_DRAWER}")


def slot_bytes(path: pathlib.Path, letter: str | None) -> tuple[bytes, str]:
    """One saved game, out of an `.adf` slot or a raw `savgam` file."""
    if path.suffix.lower() != ".adf":
        return path.read_bytes(), str(path)
    disk = AmigaDisk(bytearray(path.read_bytes()))
    letters = [letter.upper()] if letter else list(amigalaterwrite.SLOT_LETTERS)
    for one in letters:
        for suffix in SUFFIXES:
            where = f"/{SAVE_DRAWER}/savgam{one}{suffix}"
            try:
                return disk.read_file(where), f"{path}!{where}"
            except AmigaDiskError:
                continue
    raise SystemExit(f"{path}: no savgam{letter or '*'} in /{SAVE_DRAWER}")


def party_of(data: bytes, source: str) -> list[amiga.AmigaCharacter]:
    save = amigasavegame.parse(data, source=source)
    if save.shape.record_shape is None:
        raise SystemExit(f"{source}: {save.shape.title} keeps its party in "
                         f"files beside the saved game")
    return list(amiga.party_in_savegame(data, save.shape.record_shape))


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def reorder(built: list, first: str | None) -> list:
    """The converted party with one character moved to the front."""
    if first is None:
        return built
    want = first.strip().upper()
    for n, (_char, character, _report) in enumerate(built):
        if character.name.strip().upper() == want:
            return [built[n]] + built[:n] + built[n + 1:]
    names = ", ".join(c.name.strip() for _a, c, _b in built)
    raise SystemExit(f"--first {first!r}: no such character; the party is "
                     f"{names}")


def do_build(args) -> int:
    built = amigalaterwrite.convert(
        amigalaterwrite.party_from(args.source))
    built = reorder(built, args.first)
    for _char, character, report in built:
        print(amigalaterwrite.describe(character, report))
        if report.unaccounted:
            raise SystemExit(f"{character.name}: {len(report.unaccounted)} "
                             f"bytes nobody sourced; refusing to write")

    if args.out.resolve() == args.into.resolve():
        raise SystemExit("--out must not be --into; the input is read-only")
    disk = AmigaDisk(bytearray(args.into.read_bytes()))
    source = slot_path(disk, args.from_slot.upper())
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
    for n, (_c, character, _r) in enumerate(built):
        print(f"  {n + 1}. {character.name.strip():<16} "
              f"items {len(character.items):>2}  "
              f"effects {len(character.effects)}  "
              f"item chain head {int(bool(character.item_chain))}  "
              f"effect chain head {int(bool(character.effect_chain))}")
    return 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def do_diff(args) -> int:
    ours_data, ours_where = slot_bytes(args.ours, args.ours_slot)
    theirs_data, theirs_where = slot_bytes(args.theirs, args.theirs_slot)
    ours = party_of(ours_data, ours_where)
    theirs = party_of(theirs_data, theirs_where)
    print(f"ours   {ours_where}: {len(ours)} characters")
    print(f"theirs {theirs_where}: {len(theirs)} characters")
    if [c.name for c in ours] != [c.name for c in theirs]:
        print("  the two parties are not the same people in the same order:")
        print(f"    ours   {[c.name.strip() for c in ours]}")
        print(f"    theirs {[c.name.strip() for c in theirs]}")

    by_name = {c.name.strip().upper(): c for c in theirs}
    undeclared = 0
    for mine in ours:
        twin = by_name.get(mine.name.strip().upper())
        if twin is None:
            print(f"\n{mine.name.strip()}: not in the engine's party at all")
            undeclared += 1
            continue
        a, b = mine.block_bytes(), twin.block_bytes()
        print(f"\n{mine.name.strip()}: ours {len(a)} bytes, "
              f"theirs {len(b)} bytes, "
              f"items {len(mine.items)}/{len(twin.items)}, "
              f"effects {len(mine.effects)}/{len(twin.effects)}")
        if len(a) != len(b):
            print("  the blocks are different lengths; comparing the shorter")
            undeclared += 1
        mask = declared_block_mask(mine)
        declared, loose = 0, []
        for at in range(min(len(a), len(b))):
            if a[at] == b[at]:
                continue
            if at in mask:
                declared += 1
            else:
                loose.append(at)
        print(f"  {declared} bytes differ inside the declared lists, "
              f"{len(loose)} outside them")
        for at in loose[:40]:
            print(f"    0x{at:04x}  {part_at(mine, at):<28} "
                  f"ours {a[at]:#04x}  theirs {b[at]:#04x}")
        if len(loose) > 40:
            print(f"    ... and {len(loose) - 40} more")
        undeclared += len(loose)

    print(f"\n{undeclared} differences outside the declared lists")
    return 1 if undeclared else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="a run disk, with the party ordered")
    build.add_argument("--source", required=True, type=pathlib.Path,
                       help="a C64 .d64 or a DOS save directory")
    build.add_argument("--into", required=True, type=pathlib.Path,
                       help="the Amiga disk the saved game is rebuilt on")
    build.add_argument("--from", dest="from_slot", default="A",
                       help="the slot whose saved game is rebuilt")
    build.add_argument("--to", dest="to_slot",
                       help="the slot to write; defaults to --from")
    build.add_argument("--first",
                       help="a character to move to the front of the party")
    build.add_argument("--out", required=True, type=pathlib.Path)

    diff = sub.add_parser("diff", help="our party against the engine's resave")
    diff.add_argument("--ours", required=True, type=pathlib.Path)
    diff.add_argument("--ours-slot")
    diff.add_argument("--theirs", required=True, type=pathlib.Path)
    diff.add_argument("--theirs-slot")

    args = ap.parse_args(argv)
    return do_build(args) if args.command == "build" else do_diff(args)


if __name__ == "__main__":
    raise SystemExit(main())
