#!/usr/bin/env python3
"""Put a converted Amiga Curse or Silver Blades party in front of the engine.

`tools/amiga/amigalaterwrite.py` builds the party and writes a disk;
`goldbox.amiga_later.write_later` is what it calls.  What neither of them can do is
the last step of
`#384 (Write an Amiga Curse or Silver Blades character, so a C64 or DOS party
has an Amiga to arrive on)` -- boot the disk and read the engine's answer back
off it.  This is the two halves of that run:

    tools/amiga/amigalaterproof.py build --source party.d64 --into disk1.adf \\
        --from A --to B --first 'Guy de Valois' --out run.adf
    tools/amiga/amigalaterproof.py diff --ours run.adf --ours-slot B \\
        --theirs resave.sav

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
lists the writers **declare** (`goldbox.amiga_later.LATER_WRITE_UNSOURCED`,
`LATER_WRITE_DERIVED`, `LATER_ITEM_WRITE_UNSOURCED`,
`LATER_EFFECT_WRITE_UNSOURCED` and `goldbox.dos_codec`'s six, mapped through the
title's shift map) and never by whatever happened to differ, which is
`.claude/rules/conversions.md`'s rule and the reason a new difference is a
failure rather than a wider mask.  `LATER_WRITE_DERIVED` is the one the
engine itself recomputes on load -- `#402 (Amiga Curse recomputes
thac0_current and a roster_tail byte on load, and no declared list says
so)` is the run that put `thac0_current` and one `roster_tail` byte there.

`tools/amiga/porslotdiff.py` is the Pool of Radiance equivalent and does not fit
these two, whose party lives inside the saved game rather than in `CHRDAT`
files beside it.  Every input is opened read-only and `--out` is required.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import (  # noqa: E402
    amiga_later,
    amiga_port,
    amiga_savegame,
    dos_codec,
    dos_port,
    dos_savegame,
)
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from goldbox.classcode import CLASS_BIT_FOR_NAME, CLASS_CODE_TABLE  # noqa: E402
from tools.amiga import amigalaterwrite  # noqa: E402

SAVE_DRAWER = amigalaterwrite.SAVE_DRAWER
SUFFIXES = amigalaterwrite.SUFFIXES


# ---------------------------------------------------------------------------
# The mask, built from what the writers declare
# ---------------------------------------------------------------------------

#: The DOS writer's own tables, by name rather than by offset, so that a new
#: entry in one of them shows up here instead of quietly widening the mask.
#: `tests/amiga/test_amigalaterwrite.py` builds the same set for the round trip.
_DOS_TABLES = ("WRITE_UNSOURCED", "WRITE_UNSOURCED_LATER", "WRITE_DERIVED",
               "WRITE_DERIVED_LATER", "WRITE_CONSTANTS", "WRITE_DEFAULTS")


def declared_record_mask(deltas: amiga_port.AmigaDeltas) -> set[int]:
    """Amiga record offsets the two sides are allowed to disagree in."""
    names: set[str] = set()
    for table in _DOS_TABLES:
        for row in getattr(dos_codec, table):
            names.add(row[0])
    out: set[int] = set()
    for field in dos_port.layout_for(deltas.dos):
        if field.name not in names:
            continue
        try:
            at = deltas.offset(field.offset)
        except amiga_port.AmigaRecordError:
            continue
        out.update(range(at, at + field.size))
    for at, size, _why in amiga_later.LATER_WRITE_UNSOURCED[deltas.key]:
        out.update(range(at, at + size))
    for at, size, _why in amiga_later.LATER_WRITE_DERIVED[deltas.key]:
        out.update(range(at, at + size))
    # `field_83_87` is on `WRITE_CONSTANTS` for the control byte the writer
    # patches over it, but the control and share bytes it carries
    # (`goldbox.dos_codec.to_neutral`'s `control_index`/`share_index`) are
    # exact, sourced values now, not a constant -- take their offsets back out
    # so an engine resave is actually compared at both (#529).
    f83 = next((f for f in dos_port.layout_for(deltas.dos)
                if f.name == "field_83_87"), None)
    if f83 is not None:
        try:
            f83_at = deltas.offset(f83.offset)
        except amiga_port.AmigaRecordError:
            f83_at = None
        if f83_at is not None:
            control_index = 1 if f83.size == 5 else 0
            out.discard(f83_at + control_index)
            out.discard(f83_at + control_index + 1)
    return out


def declared_block_mask(char: amiga_later.AmigaCharacter) -> set[int]:
    """The same over a whole block: record, then item nodes, then effects."""
    deltas = char.deltas
    out = declared_record_mask(deltas)
    at = deltas.record_size
    for _ in char.items:
        for offset, size, _why in amiga_later.LATER_ITEM_WRITE_UNSOURCED:
            out.update(range(at + offset, at + offset + size))
        at += deltas.item_size
    for _ in char.effects:
        for offset, size, _why in amiga_later.LATER_EFFECT_WRITE_UNSOURCED:
            out.update(range(at + offset, at + offset + size))
        at += deltas.effect_size
    return out


def field_at(deltas: amiga_port.AmigaDeltas, offset: int) -> str:
    """Which field of the record an Amiga offset lands in, for a diff line."""
    for field in dos_port.layout_for(deltas.dos):
        try:
            at = deltas.offset(field.offset)
        except amiga_port.AmigaRecordError:
            continue
        if at <= offset < at + field.size:
            return f"{field.name}+{offset - at}"
    if deltas.spellbook_bytes is not None:
        book = amiga_later.AMIGA_SSB_SPELLBOOK_AT
        if book <= offset < book + deltas.spellbook_bytes:
            return f"spellbook+{offset - book}"
    return "-"


def part_at(char: amiga_later.AmigaCharacter, offset: int) -> str:
    """Which part of a block an offset is in: the record, a node, or past it."""
    deltas = char.deltas
    if offset < deltas.record_size:
        return f"record {field_at(deltas, offset)}"
    at = offset - deltas.record_size
    if at < len(char.items) * deltas.item_size:
        return f"item {at // deltas.item_size} +0x{at % deltas.item_size:03x}"
    at -= len(char.items) * deltas.item_size
    return f"effect {at // deltas.effect_size} +0x{at % deltas.effect_size:03x}"


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


def save_of(data: bytes, source: str) -> amiga_savegame.AmigaSavegame:
    save = amiga_savegame.parse(data, source=source)
    if save.container.party != "records":
        raise SystemExit(f"{source}: {save.container.title} keeps its party in "
                         f"files beside the saved game")
    return save


def party_of(data: bytes, source: str) -> list[amiga_later.AmigaCharacter]:
    return list(save_of(data, source).characters)


def clock_minutes(save: amiga_savegame.AmigaSavegame) -> int:
    """The saved game's clock in minutes, from the six digit words at
    `dos_savegame.CLOCK` (sub-minute, minute units, minute tens, hour, day,
    month; limits 10 10 6 24 30 12)."""
    _sub, units, tens, hour, day, month = (
        save.word(dos_savegame.CLOCK + i)
        for i in range(dos_savegame.CLOCK_DIGITS))
    return units + 10 * tens + 60 * (hour + 24 * (day + 30 * month))


# ---------------------------------------------------------------------------
# The opening scene's award
# ---------------------------------------------------------------------------

#: Silver Blades' opening scene pools 20 gems at 250 and 12 items with plus
#: values summing to 25 at 400 (`ecllist.py secret-of-the-silver-blades ECL10`);
#: this is the sum, shared out by party size.
OPENING_POOL = 20 * 250 + 25 * 400
#: A single-class member whose every prime requisite exceeds this gets +10%.
PRIME_BONUS_ABOVE = 15
#: Prime requisites by class bit (AD&D 1e, as `coab-source` `ovr006.cs` uses
#: them); the project has no other table of them.  The paladin and ranger rows
#: come from the Curse DOS reconstruction and are unread for Silver Blades
#: (the Pool of Radiance code gives them no bonus, and Pool has neither class).
PRIME_REQUISITES = {
    CLASS_BIT_FOR_NAME["fighter"]: ("strength",),
    CLASS_BIT_FOR_NAME["paladin"]: ("strength", "wisdom"),
    CLASS_BIT_FOR_NAME["ranger"]: ("strength", "intelligence", "wisdom"),
    CLASS_BIT_FOR_NAME["cleric"]: ("wisdom",),
    CLASS_BIT_FOR_NAME["magic-user"]: ("intelligence",),
    CLASS_BIT_FOR_NAME["thief"]: ("dexterity",),
}


def opening_award(char: amiga_later.AmigaCharacter,
                  party_size: int) -> int | None:
    """The experience the opening scene gives one member, from `coab-source`
    `ovr006.cs`'s after-combat rule: an even share of `OPENING_POOL`, +10%
    for a single-class member meeting `PRIME_BONUS_ABOVE`, divided by the
    class count.  `party_size` assumes every member is present and none is
    animated.  An out-of-range class code returns None: no award predicted."""
    code = char.get("char_class")
    if code >= len(CLASS_CODE_TABLE):
        return None
    bits = CLASS_CODE_TABLE[code]
    classes = [bit for bit in PRIME_REQUISITES if bits & bit]
    share = OPENING_POOL // party_size
    if len(classes) == 1:
        score = dict(zip(amiga_later.ABILITY_KEYS, char.abilities))
        if all(score[k] > PRIME_BONUS_ABOVE
               for k in PRIME_REQUISITES[classes[0]]):
            share += share // 10
    return share // max(len(classes), 1)


def _experience_at(char: amiga_later.AmigaCharacter) -> range:
    """The record offsets of the four experience bytes."""
    f = char.deltas.dos_field("experience")
    at = char.deltas.offset(f.offset)
    return range(at, at + f.size)


# ---------------------------------------------------------------------------
# Effects, compared as effects rather than as bytes
# ---------------------------------------------------------------------------

_EFFECT_DURATION = slice(2, 4)      # u16 big-endian


def _effect_duration(node: bytes) -> int:
    return int.from_bytes(node[_EFFECT_DURATION], "big")


def _effect_masked() -> set[int]:
    out: set[int] = set()
    for offset, size, _why in amiga_later.LATER_EFFECT_WRITE_UNSOURCED:
        out.update(range(offset, offset + size))
    return out


def compare_effects(name: str, ours: tuple[bytes, ...],
                    theirs: tuple[bytes, ...], elapsed: int
                    ) -> tuple[list[str], list[str], int]:
    """One member's effect list against the engine's, `elapsed` minutes on.

    A duration-0 effect must survive unchanged, one with more than `elapsed`
    minutes left must survive with exactly `elapsed` fewer, and one with
    `elapsed` or fewer must be gone, the effects after it moved up.  Returns
    (undeclared lines, expired lines, byte differences the declared lists
    cover).
    """
    bad: list[str] = []
    expired: list[str] = []
    declared = 0
    j = 0
    mask = _effect_masked()
    for n, mine in enumerate(ours):
        left = _effect_duration(mine)
        label = f"effect {n} (id {mine[0]}, {left} minutes left)"
        if 0 < left <= elapsed:
            expired.append(f"{name}: effect id {mine[0]}, {left} minutes left, "
                           f"expired ({elapsed} minutes elapsed)")
            if j < len(theirs) and theirs[j][0] == mine[0]:
                bad.append(f"{name}: {label} was kept by the engine; it "
                           f"should have run out")
                j += 1
            continue
        want = bytearray(mine)
        if left:
            want[_EFFECT_DURATION] = (left - elapsed).to_bytes(2, "big")
        if j >= len(theirs):
            bad.append(f"{name}: {label} is missing from the engine's list")
            continue
        got = theirs[j]
        wrong = [at for at in range(min(len(want), len(got)))
                 if want[at] != got[at] and at not in mask]
        if len(want) != len(got) or wrong:
            bad.append(f"{name}: {label} should read "
                       f"{bytes(want)[:6].hex(' ')} and reads "
                       f"{got[:6].hex(' ')}")
            if got[0] == mine[0]:
                j += 1
            continue
        declared += sum(1 for at in range(len(want))
                        if want[at] != got[at])
        j += 1
    for extra in theirs[j:]:
        bad.append(f"{name}: the engine's list has an effect ours does not "
                   f"(id {extra[0]}, {_effect_duration(extra)} minutes left)")
    return bad, expired, declared


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
    save = amiga_savegame.parse(disk.read_file(source), source=source)
    rebuilt = amiga_savegame.rebuild(
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
    ours_save = save_of(ours_data, ours_where)
    theirs_save = save_of(theirs_data, theirs_where)
    ours, theirs = list(ours_save.characters), list(theirs_save.characters)
    if args.opening_award and ours and (
            ours[0].deltas.key != amiga_port.SILVER_BLADES_DELTAS.key):
        raise SystemExit(f"--opening-award {args.opening_award} is the Silver "
                         f"Blades opening scene; {ours_where} is another title")
    elapsed = clock_minutes(theirs_save) - clock_minutes(ours_save)
    print(f"ours   {ours_where}: {len(ours)} characters")
    print(f"theirs {theirs_where}: {len(theirs)} characters")
    print(f"clock  {elapsed} minutes from ours to theirs")
    if elapsed < 0:
        print("  their clock is earlier than ours; effect durations are not "
              "compared")
    if [c.name for c in ours] != [c.name for c in theirs]:
        print("  the two parties are not the same people in the same order:")
        print(f"    ours   {[c.name.strip() for c in ours]}")
        print(f"    theirs {[c.name.strip() for c in theirs]}")

    by_name = {c.name.strip().upper(): c for c in theirs}
    undeclared = 1 if elapsed < 0 else 0
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
        # The effect nodes are compared as effects below; only the record and
        # the items in front of them are compared byte by byte.
        a_end = len(a) - len(mine.effects) * mine.deltas.effect_size
        b_end = len(b) - len(twin.effects) * twin.deltas.effect_size
        if a_end != b_end:
            print("  the record and items are different lengths; "
                  "comparing the shorter")
            undeclared += 1
        a, b = a[:a_end], b[:b_end]
        mask = declared_block_mask(mine)
        declared, loose = 0, []
        for at in range(min(len(a), len(b))):
            if a[at] == b[at]:
                continue
            if at in mask:
                declared += 1
            else:
                loose.append(at)
        if args.opening_award:
            xp = _experience_at(mine)
            rise = (int.from_bytes(b[xp.start:xp.stop], "big")
                    - int.from_bytes(a[xp.start:xp.stop], "big"))
            award = opening_award(mine, len(ours))
            if rise == award and any(at in xp for at in loose):
                print(f"  experience rose {rise}, the opening scene's award")
                loose = [at for at in loose if at not in xp]
        print(f"  {declared} bytes differ inside the declared lists, "
              f"{len(loose)} outside them")
        for at in loose[:40]:
            print(f"    0x{at:04x}  {part_at(mine, at):<28} "
                  f"ours {a[at]:#04x}  theirs {b[at]:#04x}")
        if len(loose) > 40:
            print(f"    ... and {len(loose) - 40} more")
        undeclared += len(loose)

        if elapsed < 0:
            continue
        bad, expired, in_lists = compare_effects(
            mine.name.strip(), mine.effects, twin.effects, elapsed)
        for line in expired:
            print(f"  {line}")
        for line in bad:
            print(f"  {line}")
        print(f"  {in_lists} effect bytes differ inside the declared lists, "
              f"{len(bad)} effect differences outside them")
        undeclared += len(bad)

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
    diff.add_argument("--opening-award", choices=("ssb",),
                      help="accept each member's experience rise when it "
                           "equals the Silver Blades opening scene's award")

    args = ap.parse_args(argv)
    return do_build(args) if args.command == "build" else do_diff(args)


if __name__ == "__main__":
    raise SystemExit(main())
