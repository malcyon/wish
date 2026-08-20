"""Fields whose numbers have names, and the names the game itself uses.

The tables come from `por/yaml_io.py` where it already has them, so the CLI and
the editor cannot drift apart, and from the field notes in `por/layout.py` for
the two it does not carry.

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

from por.yaml_io import ALIGNMENTS, CLASS_BITS, RACES, SEXES

# 0x072. RACES starts at 1; 0 and 8 both need saying out loud.
RACE = {0: "0 — none (the game prints MONSTER)"}
RACE.update({k: v.upper() for k, v in RACES.items()})
RACE[8] = "MONSTER (enumerated, never used)"

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

# 0x0EB, the bitmask -- the field to prefer, and the one the game reads.
CLASS_BIT_NAMES = {
    bits: "/".join(name for bit, name in CLASS_BITS if bits & bit) or "none"
    for bits in range(16)
}

ALIGNMENT = {i: name.upper() for i, name in enumerate(ALIGNMENTS)}

SEX = dict(SEXES)

# Record 0x099. Stored the way it reads here: 0 is a small character, 1 a
# medium one. Shown as a flag called "small" it said 1 for every human, which
# is the opposite of what it means.
# The dropdown prints the number itself, so these are names only.
SIZE = {0: "small", 1: "medium"}

# Which field each table belongs to. A `field_*` QComboBox on the form is
# filled from here by name, like every other binding.
TABLES = {
    "race": RACE,
    "char_class": CHAR_CLASS,
    "class_bits": CLASS_BIT_NAMES,
    "alignment": ALIGNMENT,
    "sex": SEX,
    "size_small": SIZE,
}
