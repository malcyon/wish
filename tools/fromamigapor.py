#!/usr/bin/env python3
"""Build a C64 save disk or a DOS save folder from an Amiga Pool of Radiance
save slot.

The mirror of `tools/toamigapor.py`, and the command-line form of what
`File ▸ Convert…`'s two Amiga rows do:
`#353 (Convert an Amiga Pool of Radiance save to the C64, so a party standing
in the Slums on the Amiga arrives there in VICE)` and
`#354 (Convert an Amiga Pool of Radiance save to DOS, so a party standing in
the Slums on the Amiga arrives there under DOSBox)`.  You save on the Amiga
standing in the Slums at 21:22 with half the quests done, and the party
arrives in the Slums at 21:22 with the same quests done -- not just the six
characters, which have crossed since 2026-08-26, but the game around them.

    tools/fromamigapor.py work/issue316/poolsave-c64-after-C.adf \\
        --slot C --out work/353/PORSAVEC.D64 --report --sheet
    tools/fromamigapor.py work/issue316/poolsave-c64-after-C.adf \\
        --slot C --to dos --out work/354/save --report

**Nothing is written from a template** (#118).  Whichever destination is
asked for, every byte comes from a zeroed buffer, and `goldbox.dos_codec.
new_save_from` and `goldbox.dos_codec.new_dos_save_from` each raise rather than
hand back a save with a byte in it nobody sourced -- `--report` prints that
accounting.

**A DOS destination reads the player's own DOS game folder** and no C64 disk
at all: the party's area script is lifted out of `ECL<n>.DAX` there, and a
conversion that could not read it would have to invent the area the party is
standing in.  `--game` says where; with none, `tools.dosbox.find_game()`
finds it the way every other DOS tool here does.  The combat figure needs no
disk in this direction -- an Amiga record already stores `icon_head`,
`icon_body` and `icon_colours` at the DOS offsets -- and the sheet portrait
crosses off the stored creation menu.

The two paragraphs below are the **C64** destination's own two exceptions,
which are read off the player's own C64 game disks at run time.  That is
Donald's ruling of 2026-08-27 -- *"We should never attempt to write a save
file if we don't have the game disks and we need them.  That would mean
making up data, which we will not do."*:

* the combat icon each character's own record becomes, composed by
  `goldbox.iconparts.IconParts.dos_icon` off `SPELLE64`/`SPELLN64` (#130) --
  and the Amiga record holds `icon_head`, `icon_body` and `icon_colours` at
  the DOS offsets, so an Amiga party gets its own figures rather than six
  identical ones;
* `ANIMATE00`'s 852 payload bytes, which sit at `$8400` in `SAVEDGAME1`.

The disks are found the way every other tool here finds them -- `$POR_DISKS`,
then `automap.paths.find_disks()` -- and are read and never written.  The
`.adf` is opened read-only.

`--sheet` prints the **Amiga** party the way the C64's own VIEW screen lays
it out, which is what a person compares the running game against.  Bytes
matching is necessary and not sufficient (`.claude/rules/conversions.md`):
an AC of 9 displayed as 51, a dropped combat tail and a garbage weapon line
are three faults this project has shipped that passed every byte-level check
that existed.  `tools/c64sheet.py` prints the same shape off the `.d64` this
writes, so the two can be read side by side.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import amiga_por, c64_port, dos_codec  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from goldbox.portraits import PortraitError, tables_from_disks  # noqa: E402
from tools import dosdisk  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


def read_slot(disk, slot: str):
    """One Amiga slot as the pair both destinations take.

    `goldbox.amiga_por.read_por_slot` reads the party straight off the `.adf`
    blocks and `read_por_state` the place and the clock.  Both destinations
    below start here, which is the whole of what they share.
    """
    party, savgam = amiga_por.read_por_slot(disk, slot)
    state = amiga_por.read_por_state(
        savgam, source=f"{disk.volume_name} slot {slot.upper()}")
    return party, state


def build(disk, slot: str, disks: pathlib.Path, out: pathlib.Path | None):
    """Convert one Amiga slot into a C64 `.d64` at `out`.  Nothing else is
    touched.

    From :func:`read_slot` this is `goldbox.dos_codec.new_save_from`, which is the
    same engine `File ▸ Import` has used for a DOS folder since #118.

    The creation menu's two tables (#57) come off the same `disks` directory
    the icon and `ANIMATE00` do.  Unlike those two a conversion does not
    refuse without them: `goldbox.dos_codec.to_neutral` falls back on the stored
    menu, so a Pool of Radiance party arrives with every face its own
    whether or not `GEN` was anywhere to be read.
    """
    party, state = read_slot(disk, slot)
    icon, animate = dosdisk.game_files(disks)
    try:
        portraits = tables_from_disks(disks)
    except PortraitError:
        portraits = None
    save0, save1, report = dos_codec.new_save_from(
        state, party, icon, animate, portraits=portraits,
        game=c64_port.POOL_OF_RADIANCE)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(dos_codec.save_disk(bytes(save0), bytes(save1)).data)
    return party, state, report


def build_dos(disk, slot: str, game: pathlib.Path,
              out: pathlib.Path | None, dos_slot: str = "A"):
    """Convert one Amiga slot into a DOS save folder at `out` (#354).

    The library call behind `File ▸ Convert…`'s Amiga → DOS row, and the
    same three steps that row takes: :func:`read_slot`, the party through
    `goldbox.dos_codec.to_neutral` -- the Amiga file order **is** the DOS file
    order, so nothing is reversed here -- and
    `goldbox.dos_codec.new_dos_save_from`, which raises rather than write a save
    with a byte in it nobody sourced.

    `editor.convert.amiga_combat_icon` is what keeps each character's own
    combat figure: the neutral record has nowhere to put `icon_head`,
    `icon_body` and `icon_colours`, and an Amiga record holds all three at
    the DOS offsets already.

    `game` is the DOS game directory holding `ECL<n>.DAX`, read and never
    written; there is no default here for the same reason `new_dos_save`
    has none.  With `out` as `None` nothing is written and the conversion
    still runs in a scratch directory, so `--no-write --report` says what
    the save would account for.
    """
    from editor.convert import amiga_combat_icon

    party, state = read_slot(disk, slot)
    characters = [dos_codec.to_neutral(c) for c in party]
    icons = [amiga_combat_icon(c) for c in party]
    if out is None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="fromamigapor-") as scratch:
            report = dos_codec.new_dos_save_from(state, characters,
                                           pathlib.Path(scratch), dos_slot,
                                           game, icons=icons)
        return party, state, report
    report = dos_codec.new_dos_save_from(state, characters, out, dos_slot, game,
                                   icons=icons)
    return party, state, report


def _item_line(item) -> str:
    """One item as the ITEMS screen's own cached line, with its quantity.

    The line is the buffer the game last drew and is stale by construction
    (`goldbox.amiga_por.AmigaPorItem.display_line` says why), so it is printed
    to be read against the same stale line on the C64's own screen rather
    than as a claim about what the item is.
    """
    text = item.raw("text")[:item.get("text_length")].decode("ascii", "replace")
    return f"{text.strip()} x{item.get('quantity') or 1}"


def sheet(party, state) -> list[str]:
    """The Amiga party laid out the way the C64's VIEW screen shows it.

    `tools/dosdisk.py`'s `--sheet` for a DOS folder, over an Amiga slot: the
    records have been re-cut into the DOS shape by
    `goldbox.amiga_por.to_dos_character`, so the same reader and the same three
    display constants serve, imported from there rather than copied.
    """
    from goldbox.c64_port import classes_to_names

    hour, minute = state.clock[3], state.clock[2] * 10 + state.clock[1]
    out = [f"Amiga {state.title}: "
           + ("outdoors" if state.outdoors else "indoors")
           + f", area {state.area}, resident map {state.geo}, "
             f"square {state.x},{state.y} facing {state.facing}, "
             f"clock {hour:02d}:{minute:02d}"]
    for index, char in enumerate(party):
        n = dos_codec.to_neutral(char).fields

        def v(name, default=0):
            return n[name].value if name in n else default

        coins = " ".join(f"{kind.upper()} {v(kind)}" for kind in
                         ("platinum", "gold", "electrum", "silver", "copper",
                          "gems", "jewelry") if v(kind))
        levels = ", ".join(f"{name} {count}" for name, count
                           in (v("levels", {}) or {}).items() if count)
        out += [
            "",
            f"  {index + 1}. {v('name', '')}",
            f"     {dosdisk.SEXES[v('sex') & 1]} "
            f"{char.shape.race_numbers[v('race')].upper()} AGE {v('age')}"
            f"  {dosdisk.ALIGNMENTS[v('alignment')]}"
            f"  {'/'.join(classes_to_names(v('class_bits'))).upper()}",
            f"     STR {v('strength')}"
            + (f"({v('exceptional_strength')})"
               if v("exceptional_strength") else "")
            + f" INT {v('intelligence')} WIS {v('wisdom')} "
              f"DEX {v('dexterity')} CON {v('constitution')} "
              f"CHR {v('charisma')}",
            f"     LEVEL {levels}  EXP {v('experience')}",
            f"     HITPOINTS {v('hp_current')} of {v('hp_max')}  "
            f"AC {dosdisk.AC_BIAS - v('armour_class')}  "
            f"THAC0 {dosdisk.AC_BIAS - v('thac0_current')}  "
            f"MOVE {v('movement_current')}",
            f"     {coins or 'no money'}",
            f"     {len(char.items)} items"
            + (": " + ", ".join(_item_line(i) for i in char.items)
               if char.items else ""),
            f"     combat figure head {char.get('icon_head')} "
            f"body {char.get('icon_body')} "
            f"colours {list(char.raw('icon_colours'))} "
            f"size {char.get('size')}",
        ]
    return out


#: What a `VIEW` sheet draws that an Amiga record also holds, as
#: `(name on the sheet, name in the neutral record)`.  Every one is a number
#: a person reads off the screen, which is what
#: `.claude/rules/conversions.md` means by proving a conversion rather than
#: diffing it: an AC of 9 displayed as 51 is a byte-identical save with a
#: wrong sheet.
SHEET_NUMBERS: "tuple[tuple[str, str], ...]" = (
    (r"AGE (\d+)", "age"),
    (r"HITPOINTS (\d+)", "hp_current"),
    (r"EXP (\d+)", "experience"),
    (r"STR (\d+)", "strength"),
    (r"INT (\d+)", "intelligence"),
    (r"WIS (\d+)", "wisdom"),
    (r"DEX (\d+)", "dexterity"),
    (r"CON (\d+)", "constitution"),
    (r"CHR (\d+)", "charisma"),
)


def _sheet_left_column(lines: "list[str]") -> str:
    """The sheet's own left pane, without the portrait panel beside it.

    The `VIEW` screen draws the character to the left of a panel of screen
    codes, and both are inside one `$`-delimited row -- so the name row reads
    `$GARWAN                    $@ABCDEFGHIJ$` and a reader that takes the
    whole row gets the panel with it.  A party whose sheet portrait is off
    has no panel and the naive read happens to work there, which is exactly
    the kind of difference that makes a comparison pass on one specimen and
    silently misread the next.
    """
    out = []
    for line in lines:
        parts = line.strip("@").split("$")
        out.append(parts[1] if len(parts) > 1 else "")
    return "\n".join(out)


def compare_sheets(party, events) -> "tuple[int, list[str]]":
    """The Amiga records against the C64 sheets a `savecheck.py` run read.

    `events` is the parsed `savecheck.jsonl`, whose `sheet` records carry
    the `VIEW` screen verbatim.  Returns how many values were compared and
    one line per disagreement, so a run can say "66 of 66" rather than "it
    looked right".
    """
    import re

    sheets = {}
    for event in events:
        if event.get("kind") != "sheet":
            continue
        left = _sheet_left_column(event["lines"])
        rows = left.splitlines()
        sheets[rows[1].strip() if len(rows) > 1 else ""] = left

    compared, wrong = 0, []
    for char in party:
        fields = dos_codec.to_neutral(char).fields
        name = fields["name"].value
        left = sheets.get(name)
        if left is None:
            wrong.append(f"{name}: no VIEW sheet was read for this character")
            continue
        pairs = list(SHEET_NUMBERS) + [
            (r"AC (\d+)", None), (r"STR \d+\((\d+)\)", None)]
        for pattern, field in pairs:
            found = re.search(pattern, left)
            if field is None:
                # Armour class is stored `60 - value` and exceptional
                # strength is absent from the sheet when it is zero, so
                # neither reads straight off the field table.
                if pattern.startswith("AC"):
                    want = dosdisk.AC_BIAS - char.get("armour_class")
                else:
                    want = char.get("exceptional_strength")
                    if not want:
                        continue
            else:
                want = fields[field].value
            compared += 1
            got = int(found.group(1)) if found else None
            if got != want:
                wrong.append(f"{name}: {pattern} reads {got}, the Amiga "
                             f"record holds {want}")
    return compared, wrong


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("adf", help="an Amiga Pool of Radiance disk 1 or POOLSAVE "
                               "save disk; opened read-only")
    p.add_argument("--slot", default=None,
                   help="the Amiga save slot letter (default: the first the "
                        "disk holds files for)")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's C64 disks are; read, never "
                        "written")
    p.add_argument("--to", default="c64", choices=("c64", "dos"),
                   help="the destination port (default: c64)")
    p.add_argument("--game", default=None,
                   help="--to dos: the DOS game folder ECL<n>.DAX lives in; "
                        "read, never written (default: "
                        "tools.dosbox.find_game())")
    p.add_argument("--dos-slot", default="A",
                   help="--to dos: the DOS slot letter to write as "
                        "(default: A)")
    p.add_argument("--out", default=None,
                   help="the .d64 to write, or the DOS save folder for "
                        "--to dos (default work/fromamigapor/"
                        "PORSAVE<slot>.D64, or work/fromamigapor/dos-<slot>)")
    p.add_argument("--report", action="store_true",
                   help="print the conversion's provenance summary")
    p.add_argument("--sheet", action="store_true",
                   help="print the Amiga party the way the C64 VIEW screen "
                        "lays it out, to read against the running game")
    p.add_argument("--no-write", action="store_true",
                   help="print only; build no disk")
    p.add_argument("--against", default=None,
                   help="a tools/savecheck.py log of the disk this writes; "
                        "every VIEW sheet in it is compared with the Amiga "
                        "record, value by value")
    args = p.parse_args(argv)

    disk = AmigaDisk.open(args.adf)
    present = amiga_por.por_slots_present(disk)
    if not present:
        raise SystemExit(f"{args.adf} holds no Pool of Radiance save slot")
    slot = (args.slot or present[0]).upper()
    if slot not in present:
        raise SystemExit(f"{args.adf} has no slot {slot}; it holds "
                         f"{', '.join(present)}")

    if args.to == "dos":
        # `tools.dosbox` is imported only here: it is the DOS harness, and a
        # C64 conversion has no business loading it.
        if args.game:
            game = pathlib.Path(args.game)
        else:
            from tools.dosbox import find_game

            game = pathlib.Path(find_game())
        out = None if args.no_write else pathlib.Path(
            args.out or ROOT / "work" / "fromamigapor" / f"dos-{slot}")
        party, state, report = build_dos(disk, slot, game, out,
                                         args.dos_slot.upper())
    else:
        out = None if args.no_write else pathlib.Path(
            args.out or ROOT / "work" / "fromamigapor" / f"PORSAVE{slot}.D64")
        party, state, report = build(disk, slot, pathlib.Path(args.disks), out)

    print(f"{args.adf} slot {slot}: {len(party)} character(s), "
          f"{', '.join(c.name for c in party)}")
    # The C64 writer's report calls them `messages` and the DOS writer's
    # `converted`; both are the same thing -- what the conversion did.  An
    # ordinary conversion's list is empty, so this has to check which
    # attribute exists rather than which one is truthy (#376's own run hit
    # `AttributeError: 'C64SaveReport' object has no attribute 'converted'`
    # on a report with an empty `messages`).
    for line in (report.messages if hasattr(report, "messages")
                 else report.converted):
        print(f"  {line}")
    for line in report.warnings:
        print(f"  warning: {line}")
    for line in report.dropped:
        print(f"  not converted: {line}")
    print(f"  {len(report.sources)}/{report.total} bytes accounted for, "
          f"{len(report.unwritten)} left to nobody")
    if args.sheet:
        print()
        print("\n".join(sheet(party, state)))
    if args.report:
        print()
        print(report.summary() if hasattr(report, "summary") else "")
    if args.against:
        if args.to != "c64":
            raise SystemExit("--against reads a tools/savecheck.py log, "
                             "which is the C64 run's; a DOS run's sheets are "
                             "tools/dossheetread.py's screenshots")
        import json

        events = []
        for line in pathlib.Path(args.against).read_text().splitlines():
            line = line.strip()
            if line.startswith("{"):
                events.append(json.loads(line))
        compared, wrong = compare_sheets(party, events)
        print(f"\n{compared} values read off the C64's own VIEW sheets "
              f"against the Amiga records, {len(wrong)} disagreeing")
        for line in wrong:
            print(f"  {line}")
        if wrong:
            return 1
    if out is not None:
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
