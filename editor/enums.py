"""Fields whose numbers have names, and the names the game itself uses.

The tables come from `goldbox/games.py`, re-exported through `goldbox/yaml_io.py`, so
the CLI and the editor cannot drift apart, and from the field notes in
`goldbox/layout.py` for the two it does not carry.

**Race and class are per-title and so are functions, not constants.** Silver
Blades moves human from 7 to 6, the Krynn titles use a different race list
altogether, and Curse's 6 is deliberately unnamed. `tables_for(game)` is what
the editor calls once it knows which save is open, and `race_labels` and
`class_bit_names` are what the roster calls for the same reason. **There is no
module-level default any more**: one existed, `editor/roster.py` used it, and
naming a Krynn party out of Pool of Radiance's tables was #78.

**`char_class` and `class_bits` are two separate dropdowns and are never
reconciled.** They say the same thing two ways -- `0x073` a single code,
`0x0EB` a bitmask -- and a losslessness bug came from making them agree. A
record is allowed to disagree with itself here, so each box edits its own byte
and nothing else.

Race 0 is worth knowing about: it is the commonest race in the game, carried by
75 of 135 monster records, and it is not evidence of tampering. The game prints
it as MONSTER, which is why PRINCESS FATIMA reads oddly.
"""

from __future__ import annotations

from goldbox.games import Game
from goldbox.yaml_io import ALIGNMENTS, SEXES, class_table, race_table


def race_labels(game: Game | None = None) -> dict[int, str]:
    """0x072. Race code -> name, in the table's own spelling, for one title.

    Empty when the title's list is unknown, and a code that list does not name
    is left out: the caller then prints the raw number, which is the honest
    answer where a name would be a guess. Curse's 6 is the case that matters --
    its own label table points both 6 and 7 at HUMAN, so `goldbox/games.py` names
    neither and a Pool of Radiance half-orc carried across shows as a bare 6.

    The sheet's dropdown wants these in capitals (`race_names`); the roster
    wants them as the tables spell them (`editor/roster.py`). One table, two
    renderings, so the two cannot name the same code differently (#78).
    """
    table = dict(race_table(game))
    # 0 and 8 belong to no generation menu, and only the Realms titles, which
    # are the ones that enumerate monster at 8, treat 0 the way Pool of
    # Radiance does. Silver Blades prints ELF for 0 and Krynn's 0 is a real
    # race, so neither gets these notes.
    if str(table.get(8, "")).lower() == "monster":
        # Both are named MONSTER and neither is annotated: Donald's wording,
        # approved 2026-08-24. The note that used to ride on each was three
        # times the width of the longest real race, and `Race` sets the
        # Character box's width -- which sets the header's, which is a floor
        # under the whole window (#41, #43).
        table.setdefault(0, "monster")
    return table


def race_names(game: Game | None = None) -> dict[int, str]:
    """`race_labels`, in the capitals the generation menu prints."""
    return {code: name.upper() for code, name in race_labels(game).items()}


def class_bit_names(game: Game | None = None) -> dict[int, str]:
    """0x0EB, the bitmask -- the field to prefer, and the one the game reads."""
    table = class_table(game)
    if not table:
        return {}
    out = {bits: "/".join(name for bit, name in table if bits & bit) or "none"
           for bits in range(16)}
    # The classic four multi-class freely, so every one of their 16 masks is a
    # real character. The classes above them do not -- a paladin, a ranger or a
    # Knight of Solamnia is single-class -- so each gets one entry rather than
    # multiplying the list by sixteen. Anything else still shows its raw number.
    for bit, name in table:
        if bit >= 0x10:
            out[bit] = name
    return out


# 0x073, the single class code. The multi-class codes above 7 are the 1989
# BASIC editor's table; 3, 4 and 5 rest on the Gold Box convention alone, and
# DRUID, PALADIN, RANGER and MONK appear in no character anywhere.
CHAR_CLASS = {
    0: "CLERIC", 1: "DRUID", 2: "FIGHTER", 3: "PALADIN", 4: "RANGER",
    5: "MAGIC-USER", 6: "THIEF", 7: "MONK",
    8: "cleric/fighter", 9: "cleric/fighter/magic-user",
    10: "cleric/magic-user", 11: "cleric/magic-user (again)",
    12: "cleric/thief", 13: "fighter/magic-user", 14: "fighter/thief",
    15: "fighter/magic-user/thief", 16: "magic-user/thief",
}

ALIGNMENT = {i: name.upper() for i, name in enumerate(ALIGNMENTS)}

SEX = dict(SEXES)

# Record 0x099. The game offers two sizes and no more -- its ALTER menu shows
# LARGE and SMALL -- so those are the words. Shown as a flag called "small" it
# said 1 for every human, which is the opposite of what it means.
# The dropdown prints the number itself, so these are names only.
SIZE = {0: "small", 1: "large"}


#: Which classes hold a spellbook, by the name the title's own class table
#: gives them. The mask itself is per title, because the *classes* are: Pool of
#: Radiance has only the classic four, and Curse, Silver Blades, Gateway and
#: the two Krynn titles add a paladin and a ranger above them (#86).
#:
#: * **magic-user and cleric** cast in every title, and are the whole of Pool
#:   of Radiance's answer. CONFIRMED.
#: * **the ranger** casts. CONFIRMED in Silver Blades, whose `GEN` carries a
#:   third grant routine entered on record `0x0D0` that hands out ids 77-80 at
#:   level 8 and the thirteen first-level magic-user spells at 9 -- AD&D 1st
#:   edition verbatim -- and whose shipped PAINE holds exactly those four
#:   (`tests/test_silverblades.py::test_the_ranger_grant_is_the_shipped_rangers_spellbook`).
#:   PROBABLE in Curse and the rest: Curse's `GEN` has exactly one grant loop
#:   and it is the cleric's (`tests/test_curse.py::test_curses_grant_tables_write_as_far_as_0x081`),
#:   but its magic-user's is missing from `GEN` too, so an absent loop is not
#:   evidence of an absent class -- and Curse's own spell table carries the
#:   druid group 77-80 that Silver Blades' ranger is granted.
#: * **the paladin does not.** Silver Blades' `GEN` has three grant routines
#:   and no fourth, and the shipped GUY DE VALOIS holds an empty mask.
#: * **the Knight of Solamnia does not.** Nobody has read Krynn's `GEN`; the
#:   knight is left out because a class nobody has evidence for is greyed, the
#:   way a race nobody has a name for shows its number.
CASTING_CLASSES = frozenset({"magic-user", "cleric", "ranger"})


def caster_bits(game: Game | None = None) -> int:
    """0x0EB. The class bits that can hold a spellbook, for one title.

    Zero for a title whose class list is unknown, which greys the box -- the
    same rule the tables above follow: show nothing rather than another game's
    answer.
    """
    return sum(bit for bit, name in class_table(game)
               if name in CASTING_CLASSES)


def tables_for(game: Game | None = None) -> dict[str, dict[int, str]]:
    """Which field each table belongs to, for one title.

    A `field_*` QComboBox on the form is filled from here by name, like every
    other binding.
    """
    return {
        "race": race_names(game),
        "char_class": CHAR_CLASS,
        "class_bits": class_bit_names(game),
        "alignment": ALIGNMENT,
        "sex": SEX,
        "size_small": SIZE,
    }


# `TABLES`, `RACE` and `CLASS_BIT_NAMES` used to sit here: Pool of Radiance's
# lists, for a caller with no `Game` in hand. `editor/roster.py` was the last
# one, and naming every title's characters out of Pool of Radiance's tables is
# exactly what #78 was. Nothing reads them now, so they are gone rather than
# left as a second answer to a question that has one -- `tables_for(game)`.
