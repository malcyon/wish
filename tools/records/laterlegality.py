#!/usr/bin/env python3
"""Which classes Curse and Silver Blades offer, at creation and at a class change.

`tools/records/classlegality.py` reads Pool of Radiance's creation menu.  The
two titles after it build the same menu from the same three tables and reach
them with different instructions, so that tool's pattern finds nothing here --
its C64 half looks for `LDA <race bits>,Y / AND <legality>,X`, and Curse and
Silver Blades put the race first:

    LDX <code>                    the class code being offered
    LDA <legality>,X              a bitmask of the races that may take it
    LDY <record 0x072>            the race
    AND <race bits>,Y             the race's own bit
    BEQ next                      clear: this race may not take this code

The same builder serves two menus.  The caller that draws the creation menu
passes `$FF`; `HUMAN CHANGE CLASS` passes a mask read out of a nine-entry
table indexed by the character's alignment at `0x0D8`, and the builder also
drops any code sharing a bit with the classes the character already holds
(`AND <record 0x0EB>`).  So the legal combinations of these two titles are
the creation menu **and** what the dual-class route leaves behind, and the
deepest caster either title can reach is a dual-classed human rather than
anything the creation screens draw.

Silver Blades' spell-slot rows are read here as well, out of `ECL65`, because
`goldbox/spells.py` carries Curse's and not that title's (`#572`).  The filler
is self-modifying: four nine-entry parameter tables give each class slot a
base, a first level, a row width and where in the castable array its row
lands, and one shared table holds every class's rows end to end.

    tools/records/laterlegality.py
    tools/records/laterlegality.py --game curse-of-the-azure-bonds

Reads the player's own disks through the registry and writes nothing.  With a
title's disks absent it says so for that title and carries on.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import gamedisks  # noqa: E402
from goldbox import classcode, levels  # noqa: E402
from goldbox import spells as spells_mod  # noqa: E402
from goldbox.c64_port import GAMES  # noqa: E402
from tools.c64 import coldread  # noqa: E402
from tools.c64.coldread import GEN_BASE  # noqa: E402

#: The two titles this reads.  Pool of Radiance is `classlegality.py`'s.
MEASURED = ("curse-of-the-azure-bonds", "secret-of-the-silver-blades")

#: `LIBRARY` is the one overlay whose payload does not start at `$0800`, and
#: the later titles put it here -- `tools/c64/c64clock.py`'s `LIBRARY_BASE_LATER`
#: plus the two bytes of PRG header it counts.
LIBRARY_BASE_LATER = 0x2DC6 + 2

#: Record offsets the builder and the class-change handler read.
RACE = 0x072
CLASS_BITS = 0x0EB
ALIGNMENT = 0x0D8

#: What each title's own tables held when this was last read off the disks.
#: Kept here so the generator and its tests need no disks, and checked against
#: the game by `tests/records/test_boundary_c64.py`.
#:
#: `legality` is one bitmask per menu entry; `class_bits` is what that entry
#: means in the shared class-bit order (`goldbox.classcode.CLASS_BIT_FOR_NAME`);
#: `race_bit` is indexed by the race code in the record, so a race's bit is
#: read out of it rather than computed -- Curse's table starts one byte before
#: the ladder and Silver Blades' starts on it, which is the whole difference
#: between `1 << (race - 1)` and `1 << race`.
READ_ON_DISK = {
    "curse-of-the-azure-bonds": {
        "legality_at": 0x0B60, "class_bits_at": 0x0B71, "race_bits_at": 0x0B81,
        "race_bits_in": "GEN", "codes": 17, "alignment_at": 0x23F3,
        "legality": (0x68, 0x00, 0x7F, 0x40, 0x40, 0x4A, 0x7F, 0x00, 0x28,
                     0x08, 0x08, 0x08, 0x20, 0x0A, 0x3F, 0x0A, 0x0A),
        "class_bits": (0x02, 0x10, 0x08, 0x40, 0x80, 0x01, 0x04, 0x20, 0x0A,
                       0x0B, 0x82, 0x03, 0x06, 0x09, 0x0C, 0x0D, 0x05),
        "race_bits": (0x05, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80),
    },
    "secret-of-the-silver-blades": {
        "legality_at": 0x0B41, "class_bits_at": 0x0B4F, "race_bits_at": 0x46E5,
        "race_bits_in": "LIBRARY", "codes": 14, "alignment_at": 0x1FDB,
        "legality": (0x47, 0x44, 0x7F, 0x7F, 0x40, 0x44, 0x04, 0x04, 0x04,
                     0x04, 0x07, 0x3F, 0x07, 0x07),
        "class_bits": (0x01, 0x02, 0x04, 0x08, 0x40, 0x80, 0x0A, 0x0B, 0x82,
                       0x03, 0x09, 0x0C, 0x0D, 0x05),
        "race_bits": (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x00),
    },
}

#: `GEN $23F3` in Curse and `$1FDB` in Silver Blades, byte for byte the same
#: nine: which classes a character of each alignment may change **to**.  Index
#: 0 is the one that differs, and it reads as the rules do -- a lawful good
#: character may become a paladin and may not become a thief -- while the two
#: rows carrying the ranger's bit, 3 and 6, are the two good alignments left.
ALIGNMENT_MASKS = (0xCB, 0x0F, 0x0F, 0x8F, 0x0F, 0x0F, 0x8F, 0x0F, 0x0F)

#: Silver Blades' `ECL65` spell-slot filler: its four parameter tables, one
#: entry per pass, and the shared rows they index.  `(class, base, first
#: level, row width, destination)`; the four passes with a first level of 100
#: -- the thief's, the fighter's and the two class-bit slots this title has no
#: class for -- are left out here rather than written down as classes with no
#: spells.  Read at `$88CD`, `$88D6`, `$88DF` and `$88E8`, all four found from
#: the self-modifying loader at `$888B` that copies them into its own
#: operands, with the rows at `$88F1`.
#:
#: **The ranger is two passes, and both are his.** Pass 7 puts his magic-user
#: row in the magic-user array from level 9 and pass 8 puts his druid row in
#: the druid array from level 8, both out of the same rows at `$88DF` -- the
#: split `goldbox.spells.capacity_by_class` already makes for Curse's ranger.
SILVER_SLOT_PARAMS = (
    ("magic-user", 0x00, 1, 7, 0),
    ("cleric", 0x69, 1, 6, 7),
    ("paladin", 0xC3, 9, 4, 7),
    ("ranger", 0xDF, 9, 2, 0),
    ("ranger", 0xDF, 8, 2, 14),
)
SILVER_ROWS_AT = 0x88F1
ECL65_BASE = 0x8000


def by_key(key: str):
    for game in GAMES:
        if game.key == key:
            return game
    raise SystemExit(f"No such game: {key}")


def _overlay(key: str, name: bytes) -> bytes:
    game = by_key(key)
    where = gamedisks.find(key)
    return coldread.overlay(game, name, str(where) if where else None)


# --- the menu builder --------------------------------------------------------

def menu_tables(gen: bytes, page: int, base: int = GEN_BASE) -> dict:
    """`{legality_at, class_bits_at, race_bits_at, codes}` off the builder.

    Found by the builder's own instructions: `LDA abs,X / LDY <race> / AND
    abs,Y / BEQ`, then the next `LDA abs,X` in the accepted branch (the class
    bitmask the code stands for), then the loop's own `CMP #imm / BCC`.
    Nothing here is a constant fitted by hand.
    """
    hits = []
    for i in range(len(gen) - 10):
        if (gen[i] == 0xBD and gen[i + 3] == 0xAC and gen[i + 4] == RACE
                and gen[i + 5] == page and gen[i + 6] == 0x39
                and gen[i + 9] == 0xF0):
            hits.append(i)
    if len(hits) != 1:
        raise LookupError(f"{len(hits)} candidate menu builders, wanted one")
    at = hits[0]
    legality = gen[at + 1] | gen[at + 2] << 8
    race_bits = gen[at + 7] | gen[at + 8] << 8
    class_bits = None
    for i in range(at + 10, min(at + 0x40, len(gen) - 3)):
        if gen[i] == 0xBD and (gen[i + 1] | gen[i + 2] << 8) != legality:
            class_bits = gen[i + 1] | gen[i + 2] << 8
            break
    codes = 0
    for i in range(at, min(at + 0x60, len(gen) - 3)):
        if gen[i] == 0xC9 and gen[i + 1] and gen[i + 2] == 0x90:
            codes = gen[i + 1]
            break
    if class_bits is None or not codes:
        raise LookupError("found the builder and not its other two tables")
    return {"at": at + base, "legality_at": legality,
            "class_bits_at": class_bits, "race_bits_at": race_bits,
            "codes": codes}


def alignment_table_at(gen: bytes, builder_at: int, page: int,
                       base: int = GEN_BASE) -> int:
    """Where `HUMAN CHANGE CLASS` reads its mask: `LDX <alignment> / LDA
    abs,X / JSR <inside the builder>`.  The JSR target is what ties this to
    the menu rather than to any other alignment-indexed table."""
    for i in range(len(gen) - 9):
        if (gen[i] == 0xAE and gen[i + 1] == ALIGNMENT and gen[i + 2] == page
                and gen[i + 3] == 0xBD and gen[i + 6] == 0x20):
            target = gen[i + 7] | gen[i + 8] << 8
            if abs(target - builder_at) <= 0x20:
                return gen[i + 4] | gen[i + 5] << 8
    raise LookupError("no alignment-indexed mask reaching the class menu")


def read_tables(key: str) -> dict:
    """Every table above, read off this title's own disks.

    The same keys as `READ_ON_DISK[key]`, so the two can be compared entry
    for entry.
    """
    game = by_key(key)
    gen = _overlay(key, b"GEN")
    page = coldread.staging(game) >> 8
    found = menu_tables(gen, page)
    codes = found["codes"]
    legality_at = found["legality_at"]
    class_bits_at = found["class_bits_at"]
    race_bits_at = found["race_bits_at"]
    if GEN_BASE <= race_bits_at < GEN_BASE + len(gen):
        race_source, body, race_base = "GEN", gen, GEN_BASE
    else:
        race_source = "LIBRARY"
        body, race_base = _overlay(key, b"LIBRARY"), LIBRARY_BASE_LATER
    alignment_at = alignment_table_at(gen, found["at"], page)

    def run(blob, blob_base, at, count):
        start = at - blob_base
        return tuple(blob[start:start + count])

    return {
        "legality_at": legality_at, "class_bits_at": class_bits_at,
        "race_bits_at": race_bits_at, "race_bits_in": race_source,
        "codes": codes, "alignment_at": alignment_at,
        "legality": run(gen, GEN_BASE, legality_at, codes),
        "class_bits": run(gen, GEN_BASE, class_bits_at, codes),
        "race_bits": run(body, race_base, race_bits_at, 9),
        "alignment": run(gen, GEN_BASE, alignment_at, 9),
    }


# --- what the tables mean ----------------------------------------------------

def races(key: str) -> tuple[tuple[int, str], ...]:
    """The race codes a player may pick, in the title's own numbering."""
    container = by_key(key)
    return tuple((code, name) for code, name in container.races
                 if name != "monster")


def offered(key: str, tables: dict | None = None
            ) -> dict[str, tuple[int, ...]]:
    """Race name -> the class bitmasks that race's creation menu offers."""
    table = tables or READ_ON_DISK[key]
    out = {}
    for code, name in races(key):
        bit = table["race_bits"][code]
        out[name] = tuple(mask for mask, legal
                          in zip(table["class_bits"], table["legality"])
                          if legal & bit)
    return out


def class_names(bits: int) -> tuple[str, ...]:
    """The classes a bitmask holds, in the shared bit order."""
    return tuple(name for name, bit in classcode.CLASS_BIT_FOR_NAME.items()
                 if bits & bit)


def at_their_ceilings(key: str, race: int, bits: int) -> dict[str, int]:
    """Every class in `bits` at the lowest of its class and racial ceiling.

    A class this race may not take at all is left out rather than given its
    class ceiling: `goldbox.levels.LevelTables.racial_limit` answers zero for
    that and None for "the title says nothing", and reading the two the same
    way would hand a dwarf a cleric level.  What comes back is therefore
    shorter than the bitmask exactly when the two tables disagree, which is
    what the sweep in `tests/records/test_boundary_c64.py` checks.
    """
    tables = levels.for_game(key)
    out = {}
    for name in class_names(bits):
        ceiling = tables.ceiling(name)
        if not ceiling:
            continue
        racial = tables.racial_limit(race, name)
        if racial is None:
            out[name] = ceiling
        elif racial:
            out[name] = min(ceiling, racial)
    return out


def dual_class_routes(key: str, tables: dict | None = None):
    """Every `(alignment, old, old level, new, new level)` the route allows.

    Human only (`GEN $2387` in Curse, `$1F7C` in Silver Blades), one change
    ever (`docs/176-changing-class-twice.md`), the old class left at 2 or
    better, and the old class back only once the new class passes the level
    it was left at -- `docs/192-curse-dual-class.md`'s `GEN $20A3`, which is
    what makes such a character hold two spell lists at once.
    """
    table = tables or READ_ON_DISK[key]
    level_tables = levels.for_game(key)
    human = [code for code, name in races(key) if name == "human"]
    if not human:
        return []
    bit = table["race_bits"][human[0]]
    singles = [mask for mask, legal in zip(table["class_bits"],
                                           table["legality"])
               if legal & bit and mask and not mask & (mask - 1)]
    out = []
    for alignment, allowed in enumerate(ALIGNMENT_MASKS):
        for old in singles:
            for new in singles:
                if new == old or not allowed & new:
                    continue
                old_name, = class_names(old)
                new_name, = class_names(new)
                old_ceiling = level_tables.ceiling(old_name) or 0
                new_ceiling = level_tables.ceiling(new_name) or 0
                for left_at in range(2, old_ceiling + 1):
                    if left_at >= new_ceiling:
                        continue
                    out.append((alignment, old_name, left_at, new_name,
                                new_ceiling))
    return out


# --- Silver Blades' spell slots ---------------------------------------------

def silver_slot_rows(ecl65: bytes | None = None
                     ) -> dict[tuple[str, int], dict[int, tuple]]:
    """Silver Blades' own rows, per pass and level, out of `ECL65`.

    Keyed `(class, destination array)` because the ranger has two passes
    writing two different arrays.  `#572` says nobody has read this title's
    progression; this is the half a boundary character needs, which is how
    many spells each class may hold at each level.  Read rather than
    transcribed: the rows themselves stay on the player's disk.
    """
    body = ecl65 if ecl65 is not None else _overlay(
        "secret-of-the-silver-blades", b"ECL65")
    rows_at = SILVER_ROWS_AT - ECL65_BASE
    tables = levels.for_game("secret-of-the-silver-blades")
    out: dict[tuple[str, int], dict[int, tuple]] = {}
    for name, base, first, width, dest in SILVER_SLOT_PARAMS:
        ceiling = tables.ceiling(name) or 0
        rows = {}
        for level in range(first, ceiling + 1):
            at = rows_at + base + (level - first) * width
            rows[level] = tuple(body[at:at + width])
        out[(name, dest)] = rows
    return out


def silver_capacity(class_levels: dict[str, int], wisdom: int = 18,
                    rows: dict | None = None) -> int:
    """How many spells such a Silver Blades character may memorise at once.

    The cleric's row takes the wisdom bonus, at a spell level the cleric can
    already reach -- `goldbox.spells.capacity_by_class`'s own rule, applied
    here because that function has no Silver Blades table to read.  A
    paladin's row is added into the cleric array and takes no bonus, which is
    the order the engine's own passes run in.
    """
    rows = rows if rows is not None else silver_slot_rows()
    bonus = levels.wisdom_bonus_spells(wisdom, "secret-of-the-silver-blades")
    total = 0
    for (name, _dest), by_level in rows.items():
        row = by_level.get(int(class_levels.get(name) or 0))
        if not row:
            continue
        if name == "cleric":
            row = tuple(v + (bonus[i] if v and i < len(bonus) else 0)
                        for i, v in enumerate(row))
        total += sum(row)
    return total


def capacity(key: str, class_levels: dict[str, int], wisdom: int = 18,
             rows: dict | None = None) -> int:
    """How many spells this character may memorise, in either title."""
    if key == "secret-of-the-silver-blades":
        return silver_capacity(class_levels, wisdom, rows)
    held = spells_mod.capacity_by_class(class_levels, wisdom, key)
    return sum(sum(row) for row in held.values())


def deepest_caster(key: str, wisdom: int = 18, rows: dict | None = None):
    """`(total, class levels, former levels)` for the deepest legal caster.

    Every creation combination at its own ceilings, and every dual-class
    route, measured by how many spells the character may hold at once.
    """
    best = (0, {}, {})
    table = READ_ON_DISK[key]
    for code, _name in races(key):
        bit = table["race_bits"][code]
        for mask, legal in zip(table["class_bits"], table["legality"]):
            if not legal & bit:
                continue
            held = at_their_ceilings(key, code, mask)
            total = capacity(key, held, wisdom, rows)
            if total > best[0]:
                best = (total, held, {})
    for _align, old, left_at, new, reached in dual_class_routes(key):
        held = {old: left_at, new: reached}
        total = capacity(key, held, wisdom, rows)
        if total > best[0]:
            best = (total, held, {old: left_at})
    return best


# --- reporting ---------------------------------------------------------------

def report(key: str, tables: dict) -> None:
    print(by_key(key).title)
    print(f"  legality ${tables['legality_at']:04X}, class bits "
          f"${tables['class_bits_at']:04X}, race bits "
          f"${tables['race_bits_at']:04X} in {tables.get('race_bits_in', '?')}"
          f", {tables['codes']} menu entries")
    for race, masks in offered(key, tables).items():
        names = ", ".join("/".join(class_names(m)) for m in masks)
        print(f"    {race:9s} {len(masks):2d}  {names}")
    routes = dual_class_routes(key, tables)
    print(f"  dual class: {len(routes)} (alignment, old, level, new, level) "
          f"routes")
    rows = (silver_slot_rows() if key == "secret-of-the-silver-blades"
            else None)
    total, held, former = deepest_caster(key, rows=rows)
    print(f"  deepest caster: {held} former {former} memorises {total}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", action="append", choices=MEASURED,
                    help="a title key; the default is both")
    ap.add_argument("--transcribed", action="store_true",
                    help="report from READ_ON_DISK instead of the disks")
    args = ap.parse_args(argv)
    for key in args.game or MEASURED:
        if args.transcribed:
            report(key, READ_ON_DISK[key])
            continue
        try:
            report(key, read_tables(key))
        except SystemExit as exc:
            print(f"{key}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
