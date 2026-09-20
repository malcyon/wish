#!/usr/bin/env python3
"""Legal Curse and Silver Blades characters at their class and spell ceilings.

`tools/records/boundarychars.py` builds Pool of Radiance's extremes and says
in its own docstring why the two titles after it were left out: their creation
menus and their dual-class route had not been read.  They have been now --
`tools/records/laterlegality.py` reads both out of each title's own overlays --
so this builds what that tool says is legal, for `tests/records/test_boundary_c64.py`:

* **every class combination either creation menu offers**, at each class's own
  ceiling narrowed by the race's own limit, one character per race and entry;
* **every pair the dual-class route leaves**, the new class at its ceiling and
  the old at the deepest level it can be left at and still come back;
* **the deepest caster each title can reach**, memorising every spell its own
  slot tables give him at once -- which in both titles is a dual-classed human
  and not anything the creation screens draw.

Like `boundarywidths.py`'s characters these are read as though off a DOS
record, because that is the direction a conversion into the C64 runs.

    tools/records/laterchars.py

prints every combination and what the deepest caster holds.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from goldbox import classcode
from goldbox import levels as level_tables
from goldbox import spells as spells_mod
from goldbox.neutral import NeutralCharacter
from tools.records import boundarywidths, laterlegality

#: The two titles, in release order.
GAMES = laterlegality.MEASURED

#: The deepest caster each title can reach, and how many spells he may hold at
#: once.  `levels` is what the record's level array holds after the old class
#: comes back, `former` what `dual_class_slot` and `dual_class_level` name.
#:
#: Both are dual-classed humans at wisdom 18, which is the ability maximum the
#: creation screens roll to.  Kept here so the tests need no disks;
#: `tests/records/test_boundary_c64.py` re-derives both off the player's own
#: disks and skips when they are absent.  Curse's slot rows come from
#: `goldbox/spells.py`; Silver Blades' are read out of its `ECL65` by
#: `laterlegality.silver_slot_rows`, because `#572` left that title's
#: progression unread.
DEEPEST = {
    "curse-of-the-azure-bonds": {
        "levels": {"cleric": 10, "magic-user": 11},
        "former": {"cleric": 10},
        "memorised": 40,
    },
    "secret-of-the-silver-blades": {
        "levels": {"magic-user": 14, "cleric": 15},
        "former": {"magic-user": 14},
        "memorised": 64,
    },
}

#: What the creation screens roll an ability to.  18 for every race in Pool of
#: Radiance's own DOS table (`START.EXE 0x00F3E0`), and the wisdom bonus stops
#: climbing one slot past it anyway: `goldbox.levels.wisdom_bonus_spells`
#: answers (2, 2, 1, 1, 0) at 18 and (2, 2, 1, 1, 1) at 25 in both titles, so a
#: score no creation screen can roll would add one spell and no more.
ABILITY_MAXIMUM = 18


@dataclasses.dataclass(frozen=True)
class Combination:
    """One legal character: a race, the classes it holds, and at what level."""

    game: str
    race: int
    race_name: str
    bits: int
    levels: tuple[tuple[str, int], ...]
    former: tuple[tuple[str, int], ...]
    kind: str

    @property
    def class_levels(self) -> dict[str, int]:
        return dict(self.levels)

    @property
    def former_levels(self) -> dict[str, int]:
        return dict(self.former)

    @property
    def name(self) -> str:
        held = "/".join(f"{c} {n}" for c, n in self.levels)
        was = "".join(f", was {c} {n}" for c, n in self.former)
        return f"{self.race_name} {held}{was}"


def creation_combinations(game: str) -> list[Combination]:
    """Every race and class entry that title's creation menu offers."""
    out = []
    for race, race_name in laterlegality.races(game):
        for bits in laterlegality.offered(game)[race_name]:
            held = laterlegality.at_their_ceilings(game, race, bits)
            out.append(Combination(game, race, race_name, bits,
                                   tuple(sorted(held.items())), (),
                                   "creation"))
    return out


def dual_class_combinations(game: str) -> list[Combination]:
    """One character per class pair the dual-class route can leave.

    The new class at its own ceiling and the old at the deepest level it can
    be left at and still be regained, which is one below the new class's
    ceiling -- the route's own rule (`GEN $20A3`, `docs/192-curse-dual-
    class.md`).  A pair the ceilings cannot separate never appears, which is
    why no Curse character is a magic-user who became a cleric.
    """
    human = [code for code, name in laterlegality.races(game)
             if name == "human"]
    deepest: dict[tuple[str, str], Combination] = {}
    for _align, old, left_at, new, reached in laterlegality.dual_class_routes(
            game):
        key = (old, new)
        if key in deepest and dict(deepest[key].levels)[old] >= left_at:
            continue
        bits = (classcode.CLASS_BIT_FOR_NAME[old]
                | classcode.CLASS_BIT_FOR_NAME[new])
        deepest[key] = Combination(
            game, human[0], "human", bits,
            tuple(sorted({old: left_at, new: reached}.items())),
            ((old, left_at),), "dual class")
    return [deepest[k] for k in sorted(deepest)]


def combinations(game: str) -> list[Combination]:
    return creation_combinations(game) + dual_class_combinations(game)


def capacity(combo: Combination, wisdom: int = ABILITY_MAXIMUM):
    """The character's spell rows, where the title's own table is in the tree.

    Curse's rows are `goldbox/spells.py`'s; Silver Blades has none there
    (`#572`), so this answers an empty table for that title and the caster
    case below takes its count from `DEEPEST` instead.
    """
    return spells_mod.capacity_by_class(combo.class_levels, wisdom,
                                        combo.game)


def build(combo: Combination, memorised: int = 0) -> NeutralCharacter:
    """`combo` as a DOS record would hand it to `goldbox.c64_codec.write`.

    Every field not named here keeps `boundarywidths.base`'s own legal value,
    which is what makes a failure here a failure of the classes and levels
    rather than of something else.
    """
    char = boundarywidths.base(combo.game)
    levels = combo.class_levels
    char.set("name", combo.race_name.upper()[:20], "the combination's race")
    char.set("race", combo.race, "a race the creation menu offers")
    char.set("levels", levels, "each class at its own ceiling, narrowed by "
             "the race's own limit")
    char.set("class_bits", combo.bits, "the menu entry's own bitmask")
    code = classcode.code_for(combo.bits, levels, combo.former_levels,
                              combo.game)
    if code is not None:
        char.set("char_class", code, "the title's own code for these classes")
    if combo.former:
        char.set("former_levels", combo.former_levels,
                 "the class the dual-class route left, and its level")
    for ability in ("strength", "intelligence", "wisdom", "dexterity",
                    "constitution", "charisma"):
        char.set(ability, ABILITY_MAXIMUM, "the creation screens' own maximum")
    char.set("spells_known", [], "no spellbook unless the case sets one")
    char.set("spells_memorised", list(range(1, memorised + 1)),
             f"{memorised} distinct ids")
    char.set("spells_castable", {}, "recomputed by the engine: neither later "
             "title stores the array (C64Deltas spell_slots False)")
    return char


def caster(game: str) -> NeutralCharacter:
    """The deepest legal caster, memorising his whole capacity at once."""
    deepest = DEEPEST[game]
    levels = deepest["levels"]
    former = deepest["former"]
    bits = 0
    for name, level in levels.items():
        if level:
            bits |= classcode.CLASS_BIT_FOR_NAME[name]
    human = [code for code, name in laterlegality.races(game)
             if name == "human"]
    combo = Combination(game, human[0], "human", bits,
                        tuple(sorted(levels.items())),
                        tuple(sorted(former.items())), "dual class")
    char = build(combo, deepest["memorised"])
    char.set("name", "CASTER", "made up")
    char.set("spells_known",
             list(range(1, spells_mod.for_game(game).last_spellbook_spell + 1)),
             "every id this title's own mask has a bit for")
    return char


def main(argv=None) -> int:
    for game in GAMES:
        tables = level_tables.for_game(game)
        print(f"{tables.title}: ceilings {dict(tables.ceilings)}")
        for combo in combinations(game):
            print(f"  {combo.kind:10s} {combo.name}")
        deepest = DEEPEST[game]
        print(f"  deepest caster: {deepest['levels']} was "
              f"{deepest['former']}, memorises {deepest['memorised']} at "
              f"wisdom {ABILITY_MAXIMUM}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
