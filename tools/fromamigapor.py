#!/usr/bin/env python3
"""Build a C64 save disk from an Amiga Pool of Radiance save slot.

The mirror of `tools/toamigapor.py`, and the command-line form of what
`File ▸ Convert…`'s Amiga → Commodore 64 row does:
`#353 (Convert an Amiga Pool of Radiance save to the C64, so a party standing
in the Slums on the Amiga arrives there in VICE)`.  You save on the Amiga
standing in the Slums at 21:22 with half the quests done, and the party
arrives in the Slums at 21:22 with the same quests done -- not just the six
characters, which have crossed since 2026-08-26, but the game around them.

    tools/fromamigapor.py work/issue316/poolsave-c64-after-C.adf \\
        --slot C --out work/353/PORSAVEC.D64 --report --sheet

**Nothing is written from a template** (#118).  All 9216 bytes of
`SAVEDGAME0` and `SAVEDGAME1` come from two zeroed buffers, and
`goldbox.dos.new_save_from` raises rather than hand back a save with a byte
in it nobody sourced -- `--report` prints that accounting.

Two of those bytes cannot come from the Amiga save and are read off the
**player's own C64 game disks** at run time, which is Donald's ruling of
2026-08-27 -- *"We should never attempt to write a save file if we don't have
the game disks and we need them.  That would mean making up data, which we
will not do."*:

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
sys.path.insert(0, str(TOOLS))

import dosdisk  # noqa: E402

from automap.paths import find_disks  # noqa: E402
from goldbox import amiga, dos, games  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from goldbox.portraits import PortraitError, tables_from_disks  # noqa: E402

#: Where the player keeps the C64 game disks.  Read only.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")


def build(disk, slot: str, disks: pathlib.Path, out: pathlib.Path | None):
    """Convert one Amiga slot and write `out`.  Nothing else is touched.

    `goldbox.amiga.read_por_slot` reads the party straight off the `.adf`
    blocks and `read_por_state` the place and the clock; from there this is
    `goldbox.dos.new_save_from`, which is the same engine `File ▸ Import`
    has used for a DOS folder since #118.

    The creation menu's two tables (#57) come off the same `disks` directory
    the icon and `ANIMATE00` do.  Unlike those two a conversion does not
    refuse without them: `goldbox.dos.to_neutral` falls back on the stored
    menu, so a Pool of Radiance party arrives with every face its own
    whether or not `GEN` was anywhere to be read.
    """
    party, savgam = amiga.read_por_slot(disk, slot)
    state = amiga.read_por_state(
        savgam, source=f"{disk.volume_name} slot {slot.upper()}")
    icon, animate = dosdisk.game_files(disks)
    try:
        portraits = tables_from_disks(disks)
    except PortraitError:
        portraits = None
    save0, save1, report = dos.new_save_from(
        state, party, icon, animate, portraits=portraits,
        game=games.POOL_OF_RADIANCE)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(dos.save_disk(bytes(save0), bytes(save1)).data)
    return party, state, report


def _item_line(item) -> str:
    """One item as the ITEMS screen's own cached line, with its quantity.

    The line is the buffer the game last drew and is stale by construction
    (`goldbox.amiga.AmigaPorItem.display_line` says why), so it is printed
    to be read against the same stale line on the C64's own screen rather
    than as a claim about what the item is.
    """
    text = item.raw("text")[:item.get("text_length")].decode("ascii", "replace")
    return f"{text.strip()} x{item.get('quantity') or 1}"


def sheet(party, state) -> list[str]:
    """The Amiga party laid out the way the C64's VIEW screen shows it.

    `tools/dosdisk.py`'s `--sheet` for a DOS folder, over an Amiga slot: the
    records have been re-cut into the DOS shape by
    `goldbox.amiga.to_dos_character`, so the same reader and the same three
    display constants serve, imported from there rather than copied.
    """
    from goldbox.games import classes_to_names

    hour, minute = state.clock[3], state.clock[2] * 10 + state.clock[1]
    out = [f"Amiga {state.title}: "
           + ("outdoors" if state.outdoors else "indoors")
           + f", area {state.area}, resident map {state.geo}, "
             f"square {state.x},{state.y} facing {state.facing}, "
             f"clock {hour:02d}:{minute:02d}"]
    for index, char in enumerate(party):
        n = dos.to_neutral(char).fields

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
        fields = dos.to_neutral(char).fields
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
    p.add_argument("--out", default=None,
                   help="the .d64 to write (default "
                        "work/fromamigapor/PORSAVE<slot>.D64)")
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
    present = amiga.por_slots_present(disk)
    if not present:
        raise SystemExit(f"{args.adf} holds no Pool of Radiance save slot")
    slot = (args.slot or present[0]).upper()
    if slot not in present:
        raise SystemExit(f"{args.adf} has no slot {slot}; it holds "
                         f"{', '.join(present)}")

    out = None if args.no_write else pathlib.Path(
        args.out or ROOT / "work" / "fromamigapor" / f"PORSAVE{slot}.D64")
    party, state, report = build(disk, slot, pathlib.Path(args.disks), out)

    print(f"{args.adf} slot {slot}: {len(party)} character(s), "
          f"{', '.join(c.name for c in party)}")
    for line in report.messages:
        print(f"  {line}")
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
