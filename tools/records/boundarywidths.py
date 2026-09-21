#!/usr/bin/env python3
"""Boundary characters and field widths for the C64 writer, for `tests/records/test_boundary_c64.py`.

`tools/records/boundarychars.py` builds four characters at Pool of Radiance's
reachable extremes for the DOS writer.  This is the same idea for
`goldbox.c64_codec.write`, where the ceilings are the C64 record's own:
every scalar field's width, the twenty-byte name, the memorised-spell list
(a different width in each title), the spellbook mask, sixteen item slots and
ten trait slots.  A scalar's range comes from its `goldbox/layout.py` kind and
size.  Each array's ceiling comes from somewhere other than the writer's own
row for it -- the engine's count for the memorised list, the item page and the
trait block for the other two -- so narrowing the writer moves it away from
the number the test expects instead of taking the expectation with it.

The characters are read as though off a DOS record (`port="DOS"`), because
that is the direction a conversion into the C64 runs, and it is the port that
makes the writer recompute `spells_castable`.  They are player characters
(`npc` false), so `read` hands back the drain bytes rather than the NPC
template's zeroes.

    tools/records/boundarywidths.py

prints every scalar's lowest and highest value for each title.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import c64_codec, layout, traits
from goldbox import items as items_mod
from goldbox import levels as level_tables
from goldbox import spells as spells_mod
from goldbox.layout import Kind
from goldbox.neutral import NeutralCharacter
from tools.records import boundarychars

#: The three titles `goldbox.c64_codec` has a measured record for.
GAMES = tuple(c64_codec.DELTAS_BY_KEY)

#: What a name field holds.  The writer's `petscii.encode_record_name` folds
#: to capitals and refuses anything that is not printable ASCII, so this
#: is a length and never a character set.
NAME_WIDTH = layout.NAME_SIZE


@dataclasses.dataclass(frozen=True)
class Scalar:
    """One neutral field the C64 writer copies into a single numeric field."""

    neutral: str
    c64: str
    low: int
    high: int


def value_range(kind: Kind, size: int) -> tuple[int, int] | None:
    """`(lowest, highest)` a field of this kind and width can hold, or None
    for a kind that is not a number."""
    if kind is Kind.I8:
        return -128, 127
    if kind in (Kind.U8, Kind.U16LE, Kind.UINT_LE):
        return 0, (1 << (8 * size)) - 1
    return None


def scalars() -> list[Scalar]:
    """Every `c64_codec.DIRECT` pair, with the range of the field it lands in.

    Read from the layout rather than typed, so a field whose width the layout
    changes moves here with it.
    """
    out = []
    for neutral, c64 in c64_codec.DIRECT:
        f = layout.FIELDS_BY_NAME[c64]
        span = value_range(f.kind, f.size)
        if span is None:
            raise ValueError(f"{c64} is {f.kind}, not a number")
        out.append(Scalar(neutral, c64, *span))
    return out


def recomputed_on_write(game: str, levels: dict[str, int] | None = None
                        ) -> dict[str, str]:
    """Scalars `c64_codec.write` works out again instead of copying, with why.

    A value set on one of these never reaches its byte, so neither a round
    trip nor a refusal at one past its width says anything about it.  The
    reasons are the writer's own, named where it states them.  The eight
    thief percentages are recomputed only for a character with a thief level,
    so `levels` is asked for them.
    """
    out = {
        "thac0_base": "rebuilt from the class levels through the title's "
                      "own table (GEN $1EF3)",
        "thac0_current": "rebuilt from thac0_base and the strength to-hit "
                         "bonus (LIBRARY $3918)",
    }
    if level_tables.racial_save_bonus_measured(game):
        for _, name in c64_codec._SAVE_COLUMNS:
            out[name] = ("the class row less the constitution bonus, "
                         "where the racial bonus is measured")
    if (levels or {}).get("thief") and (
            level_tables.thief_skill_race_differs_by_port(game)
            or level_tables.thief_skill_dos_storage_inflated(game)):
        for _, name in c64_codec._THIEF_SKILL_COLUMNS:
            out[name] = ("the title's own thief table for race, level and "
                         "dexterity, for a character with a thief level")
    return out


def dos_sourced(char: NeutralCharacter, game: str | None = None
                ) -> NeutralCharacter:
    """`char` as a DOS record would hand it to the C64 writer.

    Same values, `port="DOS"`, a player character.  `boundarychars` sets `npc`
    and a control byte because the DOS writer wanted them; here a control byte
    with `npc` false is reported rather than written, and an NPC's drain bytes
    read back as zero, so both come off.
    """
    out = NeutralCharacter("DOS", source=char.source,
                           game=game or char.game)
    out.fields = dict(char.fields)
    out.set("npc", False, "a player character")
    out.fields.pop("npc_control_byte", None)
    return out


def case(name: str) -> NeutralCharacter:
    """One of `boundarychars.CASES`, as the C64 writer receives it."""
    return dos_sourced(boundarychars.CASES[name]())


def base(game: str) -> NeutralCharacter:
    """An unremarkable character in `game`, every copied scalar set."""
    return dos_sourced(boundarychars._base(game), game)


def at_extreme(game: str, high: bool) -> NeutralCharacter:
    """Every scalar at the highest (or lowest) value its C64 field holds.

    `levels` goes with them: seven bytes in the per-class array, all at the
    same end.  The recomputed scalars are set too -- the writer ignores them,
    which is the point of setting them.
    """
    char = base(game)
    for s in scalars():
        char.set(s.neutral, s.high if high else s.low, "boundary")
    top = 255 if high else 0
    char.set("levels", {name: top for name in c64_codec.LEVEL_FIELDS},
             "boundary: every class slot")
    return char


#: How many memorised-spell slots each title's own `CAMP` walks: the immediate
#: of the count-down loop plus one, `LDX #$50` (Pool of Radiance), `#$44`
#: (Curse) and `#$49` (Silver Blades).  `tools/c64/memorisedwidth.py` reads
#: the same numbers off the player's disks, and the test that does so is what
#: keeps this table honest.
ENGINE_MEMORISED = {
    "pool-of-radiance": 0x50 + 1,
    "curse-of-the-azure-bonds": 0x44 + 1,
    "secret-of-the-silver-blades": 0x49 + 1,
}


@dataclasses.dataclass(frozen=True)
class Ceilings:
    """How many of each thing this title's C64 record has room for."""

    memorised: int
    spellbook: int
    items: int
    traits: int


def ceilings(game: str) -> Ceilings:
    """The array ceilings for one title.

    The memorised width is the engine's, not `c64_codec.memorised_span`'s: that
    is the writer's row, and the point is to compare against it.
    """
    return Ceilings(
        memorised=ENGINE_MEMORISED[game],
        spellbook=spells_mod.for_game(game).last_spellbook_spell,
        items=items_mod.ITEMS_PER_CHARACTER,
        traits=traits.SLOTS)


#: What the boundary is for every neutral field the C64 writer takes that is
#: not a plain scalar, one sentence each.  `tests/records/test_boundary_c64.py`
#: fails on a field `c64_codec.field_disposition()` names that is in neither
#: this table nor `scalars()`, so a field added to the writer has to say what
#: its extreme is.
STRUCTURED: dict[str, str] = {
    "name": "0, 20 and 21 characters: the record's NUL-padded name field",
    "levels": "the seven class slots, each 0 and 255, and 256 refused",
    "former_levels": "the one class a dual-classed human left, a byte",
    "spells_known": "every id the title's mask has a bit for, and one past",
    "spells_memorised": "the title's own slot count, and one past",
    "spells_castable": "three packed nibbles, a count per level, 0 to 15",
    "abilities_second": "seven bytes, in the two titles that keep the array",
    "size_small": "a byte",
    "attack_forms": "exactly eight bytes, and seven or nine refused",
    "innate_effects": "ten trait slots, and one past",
    "granted_effects": "the trait slots the racial ids leave, and one past",
    "inventory": "sixteen item slots, and one past",
    "roster_tail": "exactly nine bytes, and eight or ten refused",
    "treasure_share": "0 to 3 as the C64 masks it; bit 2 refused (#303)",
    "npc": "a flag, no width",
    "npc_control_byte": "a byte, written whole when npc is true",
    "status": "the seven C64 states; an unnamed one is reported",
    "active": "a flag, no width",
    "hostile": "a flag, no width",
    "quickfight": "a flag, no width",
    "portrait_head": "a byte, the art's own id",
    "portrait_body": "a byte, the art's own id",
    "unnamed_0ab": "a byte, the first of the identity pair",
    "turn_power": "computed from the levels, never copied",
}


def main(argv=None) -> int:
    for game in GAMES:
        c = ceilings(game)
        print(f"{game}: memorised {c.memorised}, spellbook ids 1-{c.spellbook}, "
              f"items {c.items}, trait slots {c.traits}, name {NAME_WIDTH}")
        skipped = recomputed_on_write(game)
        for s in scalars():
            note = f"  (recomputed: {skipped[s.neutral]})" \
                if s.neutral in skipped else ""
            print(f"  {s.neutral:26} {s.low:>7} .. {s.high:<9}{note}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
