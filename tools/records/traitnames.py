#!/usr/bin/env python3
"""What a title's own shipped data says an effect code means, beside our name.

`goldbox/traits.py` names the ten trait slots' codes, and a title that has no
table of its own is given Pool of Radiance's. That is right for the racial
seeds and wrong wherever a later title spent a free code number on a spell
Pool of Radiance has not got. `#561` is Curse of the Azure Bonds' case;
`#497` was Secret of the Silver Blades'.

Two of the routes `docs/171-c64-trait-slots.md` grades are censuses of shipped
data rather than reads of code, and this puts each one beside the table:

    tools/records/traitnames.py curse-of-the-azure-bonds              # the spell table
    tools/records/traitnames.py curse-of-the-azure-bonds --monsters   # the MON* records
    tools/records/traitnames.py curse-of-the-azure-bonds --records    # one row a monster
    tools/records/traitnames.py secret-of-the-silver-blades --monsters

**The spell audit** reads the per-spell record through
`tools.c64.traitquery.spell_effects` -- `ECL65 +0` at seven bytes a record in Pool
of Radiance, `COMBAT2 +2732` and `+2937` at nine in the later two -- and prints
every code one of the title's own spells writes, the spells that write it, the
combat message beside it, and what `goldbox/traits.py` calls that code today.

**It prints the spell group beside every row, and a row in no group is not
evidence.** `COMBAT2`'s name table gives one string to a spell granted at two
levels, so a shared name is ordinary; what is not ordinary is a row whose
pointer was never set, which reads as the table's first string and writes an
id that has nothing to do with it. Curse has fourteen such rows and Silver
Blades twenty, and `docs/171-c64-trait-slots.md`'s "A spell row is not evidence
until its name is its own" is the rule: **a row names a code only when the
row's own message fits the name and the row is in a spell group.** The
`group` column is what a reader applies it with, and `--all-rows` shows the
ungrouped rows rather than folding them away.

**The monster census** reads the ten bytes at record `0x0AD` out of every
`MON<hex>` template on the title's sides and reports which codes are carried
and by what. A code landing on exactly the creature its name demands is the
route most of `NAMES` was built on; a code landing on a creature the name
cannot describe is a refusal, and a code no record carries is neither.

Neither route names a code that no spell writes and no creature carries.
`tools/c64/traitquery.py --handlers` is the one that does, by reading the routine
the code dispatches, and it is the tie-breaker when these two disagree.

Nothing here needs an emulator or a save: the disks are opened read-only
through `automap/gamedisks.py`, and nothing the game ships is written anywhere.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import spells, traits  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools.c64 import traitquery  # noqa: E402

#: The ten trait slots, at C64 record offset 0x0AD -- `docs/171-c64-trait-slots.md`.
#: `tools/c64/traitquery.py` locates the engine's own `LDX #$09` scan over the same
#: ten bytes of the staged record, in each title, which is what says the offset
#: holds for a title other than Pool of Radiance.
TRAIT_SLOTS = 0x0AD
TRAIT_COUNT = 10

#: The record's name, for a monster template that has no `CharacterRecord`
#: around it. High bits are set on the C64's screen codes.
NAME_BYTES = 16


def unnamed(table: dict[int, tuple[str, str]], code: int) -> tuple[str, str]:
    return table.get(code, ("-- no name in this title's table --", ""))


# ---------------------------------------------------------------------------
# The per-spell record
# ---------------------------------------------------------------------------


def spell_rows(root: str, game):
    """`{code: [(spell id, spell name, group or None, message)]}`.

    Every row of the title's own per-spell table that writes a non-zero effect
    code, grouped by the code it writes.
    """
    out: dict[int, list] = collections.defaultdict(list)
    for spell, (name, code, message) in sorted(
            traitquery.spell_effects(root, game).items()):
        if not code:
            continue
        out[code].append((spell, name, spells.spell_group(spell, game.key),
                          message))
    return out


def report_spells(root: str, game, all_rows: bool) -> int:
    rows = spell_rows(root, game)
    _lists, honoured = traitquery.measure(root, game)
    table = traits.for_game(game.key)
    where = traitquery.SPELL_EFFECTS[game.key]
    print(f"{game.title}: {where[0]} +{where[1]}, {where[2]} bytes a record, "
          f"{spells.for_game(game.key).last_spell} spells")
    print(f"  the table naming these codes today is "
          f"{'this title\'s own' if table is not traits.NAMES else 'Pool of Radiance\'s'}"
          f", {len(table)} entries\n")
    print(f"{'code':>4} {'ask':>3} {'grp':>3}  {'the spells that write it':<44} "
          f"{'message':<24} what our table calls it")
    grouped = ungrouped = 0
    for code in sorted(rows):
        here = rows[code]
        named = [r for r in here if r[2]]
        if named:
            grouped += 1
        else:
            ungrouped += 1
        shown = "; ".join(f"{n}" for _s, n, _g, _m in (named or here))
        messages = ",".join(sorted({m for *_x, m in (named or here)}))
        name, grade = unnamed(table, code)
        print(f"{code:>4} {('yes' if code in honoured else 'no'):>3} "
              f"{(str(len(named)) if named else '--'):>3}  {shown[:44]:<44} "
              f"{messages[:24]:<24} {name[:44]} "
              f"{('[' + grade + ']') if grade else ''}")
        if all_rows or not named:
            for spell, name_, group, message in here:
                mark = f"{group[0]} {group[1]}" if group else "NO GROUP"
                print(f"       row {spell:>3}  {name_[:40]:<40} "
                      f"{mark:<14} {message}")
    print(f"\n  {len(rows)} codes are written by a spell; "
          f"{grouped} by at least one row that is in a spell group and "
          f"{ungrouped} only by a row that is in none")
    missing = sorted(c for c in rows if c not in table)
    print(f"  {len([c for c in rows if c in honoured])} of the {len(rows)} are "
          f"asked about in a trait slot; {len(missing)} have no name at all in "
          f"the table above: " + (", ".join(str(c) for c in missing) or "none"))
    return 0


# ---------------------------------------------------------------------------
# The MON* templates
# ---------------------------------------------------------------------------


def monster_blocks(title: str, given: str | None = None):
    """`{file: (name, the ten trait bytes)}` for every `MON<hex>` template.

    A `MON*` file is a PRG whose body is a character record at offset 0
    (`tools/records/fieldcensus.py`'s `monsters` corpus reads the same files), so the
    trait block is at `TRAIT_SLOTS` in the body with the load address off.
    The first copy of a name wins, since the same template ships on several
    sides.
    """
    root = pathlib.Path(given) if given else gamedisks.find(title)
    if root is None:
        raise SystemExit(f"traitnames.py: no disks for {title}; pass --disks.")
    out: dict[str, tuple[str, bytes]] = {}
    for path in sorted(root.glob("*.[dD]64")):
        try:
            disk = D64.open(str(path))
            entries = list(disk.directory())
        except Exception as exc:  # noqa: BLE001 - a disk we cannot read
            print(f"  skipped {path.parent.name}/{path.name}: {exc}")
            continue
        for entry in entries:
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if not name.startswith("MON") or name in out:
                continue
            try:
                body = disk.read_file(entry.name)[2:]
            except Exception as exc:  # noqa: BLE001 - a file we cannot read
                print(f"  skipped {path.name}/{name}: {exc}")
                continue
            if len(body) < TRAIT_SLOTS + TRAIT_COUNT:
                continue
            text = bytes(c & 0x7F for c in body[:NAME_BYTES])
            out[name] = (text.split(b"\x00")[0].decode("latin1",
                                                       "replace").strip(),
                         body[TRAIT_SLOTS:TRAIT_SLOTS + TRAIT_COUNT])
    return out


def carriers_of(title: str, given: str | None = None):
    """`{code: {creature name}}` over one title's `MON*` templates."""
    out: dict[int, set[str]] = collections.defaultdict(set)
    for _file, (name, block) in monster_blocks(title, given).items():
        for value in block:
            if value:
                out[value].add(name)
    return out


def report_monsters(title: str, given: str | None, per_record: bool,
                    against: str | None = None,
                    against_disks: str | None = None) -> int:
    blocks = monster_blocks(title, given)
    game = traitquery.title_named(title)
    table = traits.for_game(game.key)
    try:
        _lists, honoured = traitquery.measure(traitquery.disks_for(game,
                                                                   given),
                                              game)
    except SystemExit:
        honoured = set()

    if per_record:
        print(f"{game.title}: {len(blocks)} MON* templates, the ten bytes at "
              f"record ${TRAIT_SLOTS:03X}\n")
        for file, (name, block) in sorted(blocks.items()):
            codes = " ".join(f"{v:>3}" for v in block)
            gap = "  <- a zero before a code" if any(
                block[i] == 0 for i in range(max((i for i, v in
                                                  enumerate(block) if v),
                                                 default=0))) else ""
            print(f"  {file:<8} {name[:18]:<18} {codes}{gap}")
        return 0

    carriers: dict[int, list[tuple[str, str]]] = collections.defaultdict(list)
    for file, (name, block) in sorted(blocks.items()):
        for value in block:
            if value:
                carriers[value].append((file, name))
    other = carriers_of(against, against_disks) if against else None
    print(f"{game.title}: {len(blocks)} MON* templates carry {len(carriers)} "
          f"distinct codes between them\n")
    head = (f"{'code':>4} {'n':>3} {'ask':>3}  "
            f"{'the creatures carrying it':<48} ")
    if other is not None:
        head += f"{'and in ' + against:<40} "
    print(head + "what our table calls it")
    for code in sorted(carriers):
        rows = carriers[code]
        who = "; ".join(sorted({n for _f, n in rows}))
        name, grade = unnamed(table, code)
        line = (f"{code:>4} {len(rows):>3} "
                f"{('yes' if code in honoured else 'no'):>3}  {who[:48]:<48} ")
        if other is not None:
            there = "; ".join(sorted(other.get(code, ()))) or "(nothing)"
            line += f"{there[:40]:<40} "
        print(line + f"{name[:40]} {('[' + grade + ']') if grade else ''}")
    missing = sorted(c for c in carriers if c not in table)
    print(f"\n  {len(missing)} of the {len(carriers)} have no name at all in "
          f"the table above: " + (", ".join(str(c) for c in missing) or "none"))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title")
    parser.add_argument("--disks", help="where that title's sides are")
    parser.add_argument("--monsters", action="store_true",
                        help="census the MON* templates instead of the spells")
    parser.add_argument("--records", action="store_true",
                        help="with --monsters, one row per template")
    parser.add_argument("--all-rows", action="store_true",
                        help="show every spell row, not just the ungrouped")
    parser.add_argument("--against", metavar="TITLE",
                        help="with --monsters, the creatures carrying the "
                             "same code in TITLE")
    parser.add_argument("--against-disks", help="where TITLE's sides are")
    args = parser.parse_args(argv)

    game = traitquery.title_named(args.title)
    if args.monsters or args.records:
        against = (traitquery.title_named(args.against).key
                   if args.against else None)
        return report_monsters(game.key, args.disks, args.records, against,
                               args.against_disks)
    return report_spells(traitquery.disks_for(game, args.disks), game,
                         args.all_rows)


if __name__ == "__main__":
    raise SystemExit(main())
