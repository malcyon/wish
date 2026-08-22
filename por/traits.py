"""The ten trait slots at `0x0AD`, and what the codes mean. No Qt, no I/O.

This is where racial abilities, spell effects and monster specials live. It is
one namespace, 1-139 on the C64, shared with the DOS port: Stephen S. Lee's
Pool of Radiance guide (section 12.2.3) enumerates ids 1-127 for the DOS build
and every id our own census of the player's disks turned up lands on the
creature that id's meaning demands. `docs/128-guide-and-scripting.md` is the
write-up.

**The names below are transcribed from a third-party document and then checked
against the player's own disks.** 44 are CONFIRMED, because a `MON*` record or
a saved item carries the code on exactly the creature or item the meaning
requires -- the anhkheg carries 121 "anhkheg acid squirt", the troll carries
100 and 101, the ghoul carries the paralysis that spares elves, the wight
carries "silver or magic" and the wraith the "silver does half" variant, which
is the *Monster Manual* distinction between them. The rest are PROBABLE: the
guide names them, nothing on the C64 exercises them, and a third-party document
on its own is never CONFIRMED.

Three codes are ours rather than theirs. **139** is past the end of their table
and PHASE SPIDER carries it. **92** they call unused and TYRANITHRAXUS carries
it. **255** is the byte after the last used slot in a `MON*` record, not a code
at all.

`GEN $0BF3` seeds the list per race from `[1, 0, 107, 0, 124, 0, 0, 0]`,
**indexed by the race byte itself**, which is 1-based: elf is race 2 and is born
with 107, half-elf is race 4 and is born with 124, and the leading 1 sits at
index 0, which no created character reaches. That kills the old reading of it
as a dwarf's seed -- MAGNUS, a dwarf, carries an empty trait block.

Not to be confused with item byte `+14`, which shares these slots and only
sometimes shares their meaning. **Item byte `+15` bit 7 is the discriminator**:
a passive item's `+14` is an effect id and `SPELLE04 $ADD4` copies it verbatim
into a free slot, while a consumable's `+14` is a spell id. In the player's own
saves CLOAK OF DISPLACEMENT reads `+14` 89 / `+15` $85 and TWO-HANDED SWORD +1
+3 VS UNDEAD reads 3 / $88 -- displaced and undead-slaying, the guide's names
for both. POTION OF HEALING reads 85 / $00 and is a potion, not a level drain.

Lives in `por/` rather than in the editor because the combat view names the same
codes on a monster's tooltip, and one table cannot be allowed to become two.
"""

from __future__ import annotations

from dataclasses import dataclass

SLOTS = 10                     # 0x0AD-0x0B6; three overlays loop LDX #$09
FIRST = 0x0AD

# code -> (what it does, how sure we are).
#
# CONFIRMED means a record on the player's disks carries the code and the
# carrier is what the name demands -- checked against the AD&D 1st edition
# Monster Manual, which is the external rule this project promotes on. The
# carriers are named in the trailing comments and come from a census of 116
# `MON*` records across the eight POOL disks plus the save fixtures.
#
# PROBABLE means the guide names it and no C64 record exercises it. Every
# spell effect (1-63, bar the four below) is in that state and will stay there
# until a character is caught carrying one: a save taken mid-spell would
# promote a dozen at once.
NAMES: dict[int, tuple[str, str]] = {
    1: ("Bless", "PROBABLE"),
    2: ("Curse", "PROBABLE"),
    # The player's own TWO-HANDED SWORD +1 +3 VS UNDEAD carries 3 as a passive
    # item power (+14 = 3, +15 = $88).
    3: ("wielding an undead-slaying weapon", "CONFIRMED"),
    4: ("starting to train with a Manual of Bodily Health", "PROBABLE"),
    5: ("Detect Magic", "PROBABLE"),
    6: ("wielding a Flame Tongue", "PROBABLE"),
    7: ("training with a Manual of Bodily Health", "PROBABLE"),
    8: ("Protection from Evil", "PROBABLE"),
    9: ("Protection from Good", "PROBABLE"),
    10: ("Resist Cold", "PROBABLE"),
    11: ("charmed", "PROBABLE"),
    12: ("Enlarge", "PROBABLE"),
    13: ("Reduce", "PROBABLE"),
    14: ("Friends", "PROBABLE"),
    15: ("Slow Poison, damage", "PROBABLE"),
    16: ("Read Magic", "PROBABLE"),
    17: ("Shield", "PROBABLE"),
    18: ("gnome THAC0 bonus against kobolds and goblins", "PROBABLE"),
    19: ("Find Traps", "PROBABLE"),
    20: ("Resist Fire", "PROBABLE"),
    21: ("Silence, 15' Radius", "PROBABLE"),
    22: ("Slow Poison, expiry", "PROBABLE"),
    23: ("Spiritual Hammer", "PROBABLE"),
    24: ("sees invisible creatures", "PROBABLE"),          # TYRANITHRAXUS
    25: ("invisible", "PROBABLE"),
    26: ("dwarf THAC0 bonus against orcs, half-orcs, goblins and hobgoblins",
         "PROBABLE"),
    27: ("feather falling", "PROBABLE"),
    28: ("Mirror Image", "PROBABLE"),
    29: ("Ray of Enfeeblement", "PROBABLE"),
    30: ("coughing in a Stinking Cloud", "PROBABLE"),
    31: ("helpless", "PROBABLE"),
    32: ("Animate Dead", "PROBABLE"),
    33: ("blind", "PROBABLE"),
    34: ("diseased", "PROBABLE"),
    35: ("under an allied Prayer", "PROBABLE"),
    36: ("Bestow Curse", "PROBABLE"),
    37: ("blinking", "CONFIRMED"),                         # PHASE SPIDER
    # por/items.py has the gauntlets carrying 38, derived before the guide was
    # read; two independent lines on one id.
    38: ("extra strength", "CONFIRMED"),
    39: ("hasted", "PROBABLE"),
    40: ("cast Stinking Cloud", "PROBABLE"),
    41: ("Protection from Normal Missiles", "PROBABLE"),
    42: ("slowed", "PROBABLE"),
    43: ("diseased: strength drain", "PROBABLE"),
    44: ("diseased: hit-point drain", "PROBABLE"),
    45: ("Protection from Evil, 10' Radius", "PROBABLE"),
    46: ("Protection from Good, 10' Radius", "PROBABLE"),
    47: ("dwarf/gnome AC bonus against ogres, trolls, ogre magi, giants and "
         "titans", "PROBABLE"),
    48: ("gnome AC bonus against gnolls and bugbears", "PROBABLE"),
    49: ("Prayer", "PROBABLE"),
    50: ("mummy rot, blocking healing", "PROBABLE"),
    51: ("Snake Charm", "PROBABLE"),
    52: ("held or paralysed", "PROBABLE"),
    53: ("sleeping", "PROBABLE"),
    54: ("repulsed (bronze dragon; the handler is unimplemented)", "PROBABLE"),
    55: ("poisoned", "PROBABLE"),
    56: ("wearing a Ring of Invisibility", "PROBABLE"),
    57: ("mummy rot, degenerating", "PROBABLE"),
    58: ("immobile", "PROBABLE"),
    59: ("gains regeneration when this expires", "PROBABLE"),
    60: ("unused", "PROBABLE"),
    # por/items.py has the ring carrying 61, again derived independently.
    61: ("wearing a Ring of Fire Resistance", "CONFIRMED"),
    62: ("regeneration from constitution 20 or better", "PROBABLE"),
    63: ("unimplemented -- no handler exists", "PROBABLE"),
    # 64-66 and 67-70 are two graded families: poison and paralysis, each
    # spread over its saving-throw modifier. The C64 census exercises one of
    # each grade and the carriers are the poisoners and the paralysers.
    64: ("melee poison, no save modifier", "CONFIRMED"),   # SNAKE, SCORPION...
    65: ("melee poison, +4 to save", "CONFIRMED"),         # POISONOUS FROG
    66: ("melee poison, +2 to save", "CONFIRMED"),         # LARGE SCORPION
    67: ("melee paralysis, 2d8 minutes", "CONFIRMED"),     # THRI-KREEN
    68: ("melee paralysis, elves immune", "CONFIRMED"),    # GHOUL
    # DRIDER carries 69. The guide reads it as paralysis and flags its -2 as
    # doubtful; the Monster Manual gives the drider a poison bite, so which of
    # the two families this id belongs to is not settled.
    69: ("melee paralysis, -2 to save", "PROBABLE"),
    70: ("melee poison, -2 to save", "PROBABLE"),
    71: ("invisible from dust -- detect invisibility does not find it",
         "PROBABLE"),
    72: ("camouflaged by a Cloak of Elvenkind", "PROBABLE"),
    73: ("rear claw rake", "CONFIRMED"),                   # TIGER
    74: ("bite and hold, in progress", "PROBABLE"),
    75: ("blood being drained", "PROBABLE"),
    76: ("melee blood drain, attaching", "CONFIRMED"),     # STIRGE
    77: ("melee bite and hold", "CONFIRMED"),              # GIANT MANTIS
    78: ("healed out of unconsciousness during combat", "PROBABLE"),
    79: ("melee fire touch, 2d10", "CONFIRMED"),           # TYRANITHRAXUS
    80: ("melee acid attack, 1d4", "CONFIRMED"),           # AHNKHEG
    81: ("dragon fear aura", "CONFIRMED"),                 # TYRANITHRAXUS
    82: ("mummy fear aura", "CONFIRMED"),                  # MUMMY
    83: ("petrifying gaze", "CONFIRMED"),                  # BASILISK, MEDUSA
    84: ("charming gaze", "PROBABLE"),
    85: ("melee level drain, one level", "CONFIRMED"),     # WIGHT, WRAITH
    86: ("melee level drain, two levels", "CONFIRMED"),    # SPECTRE, VAMPIRE
    87: ("melee mummy rot", "CONFIRMED"),                  # MUMMY
    88: ("electrical breath weapon", "PROBABLE"),
    # TYRANITHRAXUS carries it, and so does the player's own CLOAK OF
    # DISPLACEMENT as a passive item power.
    89: ("displaced", "CONFIRMED"),
    90: ("dwarf/halfling constitution bonus to poison and death saves",
         "PROBABLE"),
    91: ("immune to electricity and Magic Missile", "CONFIRMED"),  # JUJU ZOMBIE
    # The guide has 92 unused. TYRANITHRAXUS carries it, so the C64 uses an id
    # DOS does not, or the guide missed a handler. Either way it is not named.
    92: ("not named -- the guide has this id unused", "UNKNOWN"),
    93: ("half damage from fire", "CONFIRMED"),            # JUJU ZOMBIE
    94: ("half damage from blunt or piercing weapons", "CONFIRMED"),
    95: ("fights on from -6 to 0 hit points", "PROBABLE"),
    96: ("hit only by silver or magical weapons", "CONFIRMED"),    # WIGHT
    97: ("dwarf/gnome/halfling constitution bonus to spell and wand saves",
         "PROBABLE"),
    98: ("regenerates 3 hit points a round", "CONFIRMED"),         # VAMPIRE
    99: ("keeps fighting once unconscious", "CONFIRMED"),          # WILD BOAR
    100: ("troll: vulnerable to fire and acid, else returns from death",
          "CONFIRMED"),                                            # TROLL
    101: ("troll: regeneration", "CONFIRMED"),                     # TROLL
    102: ("troll: getting back up", "PROBABLE"),
    103: ("can assume gaseous form", "PROBABLE"),
    104: ("missile evasion, 60%", "CONFIRMED"),                    # THRI-KREEN
    105: ("50% magic resistance (unused)", "PROBABLE"),
    106: ("85% magic resistance", "PROBABLE"),             # TYRANITHRAXUS
    107: ("elf: 90% resistance to sleep and charm", "CONFIRMED"),
    108: ("immune to sleep and charm", "CONFIRMED"),
    # 109 and 111 are carried by exactly the same four undead, so the census
    # cannot tell them apart; both names are the guide's alone.
    109: ("immune to paralysis, from Hold Person and wands only", "PROBABLE"),
    110: ("immune to cold", "CONFIRMED"),                  # all eight undead
    111: ("immune to paralysis and poison", "PROBABLE"),
    112: ("immune to fire", "CONFIRMED"),                  # FIRE GIANT
    113: ("efreeti fire resistance, -1 a damage die", "CONFIRMED"),  # EFREETI
    114: ("half damage from electricity", "PROBABLE"),
    115: ("half damage from piercing or slashing weapons", "CONFIRMED"),
    116: ("half damage from magical weapons", "CONFIRMED"),          # MUMMY
    # Every undead in the game carries 117 -- which is equally what "undead,
    # and so turnable" predicted, the reading this table used to give it. The
    # population cannot separate the two; the guide's decode is the tiebreak.
    117: ("vulnerable to holy water", "PROBABLE"),
    118: ("half damage from cold", "PROBABLE"),
    119: ("immune to non-magical weapons", "CONFIRMED"),
    # Carried by FIRE GIANT and HILL GIANT, which is also what the old reading
    # "hurls boulders" predicted. Hurling is an attack form and lives at
    # 0x0D9, which is the argument for the guide's reading, not proof of it.
    120: ("boulder evasion, 50%", "PROBABLE"),
    121: ("acid squirt, 8d4 at range 3", "CONFIRMED"),     # AHNKHEG
    122: ("mummy: vulnerable to fire", "CONFIRMED"),       # MUMMY
    123: ("hit only by magical weapons; silver does half", "CONFIRMED"),
    124: ("half-elf: 30% resistance to sleep and charm", "CONFIRMED"),
    125: ("immune to sleep, charm, paralysis and poison", "CONFIRMED"),
    126: ("gaze attack, avoidable", "PROBABLE"),           # VAMPIRE
    127: ("gaze attack, reflectable", "CONFIRMED"),        # BASILISK, MEDUSA
    # Past the end of the guide's table, so this one is entirely ours.
    139: ("phasing", "PROBABLE"),                          # PHASE SPIDER
    # 255 is the byte after the last used slot in a MON* record, not a code.
    255: ("fill, not a code", "PROBABLE"),
}

# The byte after the last used slot in a MON* record. Not a trait, and a live
# ORC carries it, so the combat tooltip drops it rather than printing "fill".
FILL = 255

# The highest id the guide's table reaches. Anything above it is this project's
# own and has no third-party name to lean on.
LAST_DOCUMENTED = 127

EMPTY = "—"


def describe(code: int) -> str:
    """What a slot says. An unnamed code is visibly unnamed, never blank.

    An unnamed code keeps its **number**: two slots we cannot name still have
    to be told apart, and the number is what somebody takes away to look it up.
    """
    if not code:
        return EMPTY
    named = NAMES.get(code)
    return named[0] if named else f"trait {code}"


def confidence(code: int) -> str:
    """How sure the name is. `UNNAMED` codes have no confidence to report."""
    named = NAMES.get(code)
    return named[1] if named else ""


@dataclass(frozen=True)
class Trait:
    """One occupied slot, named if we can and numbered either way."""

    slot: int
    code: int

    @property
    def named(self) -> bool:
        return self.code in NAMES

    @property
    def is_fill(self) -> bool:
        return self.code == FILL

    @property
    def label(self) -> str:
        """`petrifying gaze` for a code we know, `trait 91` for one we do not.

        The number is what makes a new code visible rather than silently
        dropped, which is how the census grew in the first place.
        """
        return describe(self.code) if self.named else f"trait {self.code}"

    @property
    def detail(self) -> str:
        where = f"0x{FIRST + self.slot:03X}"
        if not self.named:
            return f"{where} holds {self.code}, which the census does not name"
        return f"{where}: {describe(self.code)} ({confidence(self.code)})"


def traits(raw: bytes) -> tuple[Trait, ...]:
    """The occupied slots of one ten-byte trait block."""
    return tuple(Trait(i, code) for i, code in enumerate(raw[:SLOTS]) if code)
