"""Fields whose numbers have names, and the names the game itself uses.

The tables come from `por/games.py`, re-exported through `por/yaml_io.py`, so
the CLI and the editor cannot drift apart, and from the field notes in
`por/layout.py` for the two it does not carry.

**Race and class are per-title and so are functions, not constants.** Silver
Blades moves human from 7 to 6, the Krynn titles use a different race list
altogether, and Curse's 6 is deliberately unnamed. `tables_for(game)` is what
the editor calls once it knows which save is open; the module-level `TABLES` is
Pool of Radiance's, for a caller with no `Game` in hand.

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

from por.games import Game
from por.yaml_io import ALIGNMENTS, SEXES, class_table, race_table


def race_names(game: Game | None = None) -> dict[int, str]:
    """0x072. Race code -> label, for one title.

    Empty when the title's list is unknown, and a code that list does not name
    is left out: the combo then prints the raw number, which is the honest
    answer where a name would be a guess. Curse's 6 is the case that matters --
    its own label table points both 6 and 7 at HUMAN, so `por/games.py` names
    neither and a Pool of Radiance half-orc carried across shows as a bare 6.
    """
    table = {code: name.upper() for code, name in race_table(game).items()}
    # 0 and 8 belong to no generation menu, and only the Realms titles, which
    # are the ones that enumerate MONSTER at 8, treat 0 the way Pool of
    # Radiance does. Silver Blades prints ELF for 0 and Krynn's 0 is a real
    # race, so neither gets these notes.
    if table.get(8) == "MONSTER":
        # Both are named MONSTER and neither is annotated: Donald's wording,
        # approved 2026-08-24. The note that used to ride on each was three
        # times the width of the longest real race, and `Race` sets the
        # Character box's width -- which sets the header's, which is a floor
        # under the whole window (#41, #43).
        table.setdefault(0, "MONSTER")
    return table


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


#: Pool of Radiance's, for a caller with no `Game` in hand. `editor/roster.py`
#: is one: it names a class for the roster strip without a `Game` to hand.
TABLES = tables_for()
RACE = TABLES["race"]
CLASS_BIT_NAMES = TABLES["class_bits"]
