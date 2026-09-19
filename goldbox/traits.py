"""The ten trait slots at `0x0AD`, and what the codes mean. No Qt, no I/O.

This is where racial abilities, spell effects and monster specials live. It is
one namespace, 1-139 on the C64, shared with the DOS port: Stephen S. Lee's
Pool of Radiance guide (section 12.2.3) enumerates ids 1-127 for the DOS build
and every id our own census of the player's disks turned up lands on the
creature that id's meaning demands. `docs/128-guide-and-scripting.md` is the
write-up.

**The names below are transcribed from a third-party document and then checked
against the player's own disks.** 67 are CONFIRMED that way. Most were settled
by the census: a `MON*` record or an item template carries the code on exactly
the creature or item the meaning requires -- the anhkheg carries 121 "anhkheg
acid squirt", the troll carries 100 and 101, the ghoul carries the paralysis
that spares elves, the wight carries "silver or magic" and the wraith the
"silver does half" variant, which is the *Monster Manual* distinction between
them. **Seventeen more were settled by playing**: `P3-EFFECTS.D64` was saved
with 26 spells running, and each one named the code it had just written -- 1
Bless, 25 invisible, 39 hasted and the rest, `docs/90-specimens.md`. **One more
was settled by a live fight**: 53 sleeping, five Sleep-struck orcs in one slums
ambush all naming it. **Two more, 90 and 97, were settled by reading
`GAME.OVR` itself rather than by any census** -- reading the shipped overlay
is stronger evidence than a census of saves, since it names the instruction
that decides the question instead of a population that happens to agree with
it; `#247 (Nobody knows whether innate effect 97 is racial or the constitution
bonus)` and `docs/189-effect-97-from-the-code.md` have the chain. 59 are
PROBABLE: the guide names them, nothing on the C64 exercises them and no
overlay code has been read for them, and a third-party document on its own is
never CONFIRMED.

The census is 108 `MON*` records across the eight `POOL` disks and the 163
item templates in the `ITEMFILE*` lists. **52 of the 129 codes are carried by
something**; the other 77 have no C64 carrier at all and cannot be promoted by
any amount of looking. Only four item templates carry a passive power, and all
four were already confirmed -- the item side of this table is exhausted.

**Four were promoted on the vampire's block** (P55): 103 gaseous form, 114 and
118 the half damage from electricity and cold, 126 the avoidable gaze. The
vampire is the only creature on the disks carrying any of them, and together
with the four the census had already confirmed on it the block reads as the
*Monster Manual*'s vampire entry line for line.

**Two that look promotable are not.** 117 lands on all nine undead and nothing
else -- but so would "undead, and therefore turnable", which is what this table
used to call it, and the population cannot separate the two readings. 120 lands
on both giants and nothing else -- but so would "hurls boulders", and hurling
is an attack form at `0x0D9`. Both stay PROBABLE until something other than the
carrier set decides them.

Three codes are ours rather than theirs. **139** is past the end of their table
and PHASE SPIDER carries it -- which is why it stays PROBABLE, since the carrier
is also where the name came from and one observation cannot corroborate itself.
**92** they call unused and TYRANITHRAXUS carries it. **255** is a fill byte in
the last slot: 38 of the 108 records carry it, every one of them in slot 9, and
no record has a real code after one.

`GEN $0BF3` seeds the list per race from `[1, 0, 107, 0, 124, 0, 0, 0]`,
**indexed by the race byte itself**, which is 1-based: elf is race 2 and is born
with 107, half-elf is race 4 and is born with 124, and the leading 1 sits at
index 0, which no created character reaches. That kills the old reading of it
as a dwarf's seed -- MAGNUS, a dwarf, carries an empty trait block.

Not to be confused with item byte `+14`, which shares these slots and only
sometimes shares their meaning. **Item byte `+15` bit 7 is the discriminator**:
a passive item's `+14` is an effect id and `SPELLE04 $ADD4` copies it verbatim
into a free slot, while a consumable's `+14` is a spell id. Four item templates
on the disks set bit 7 and only four: CLOAK OF DISPLACEMENT reads `+14` 89 /
`+15` $85 and TWO-HANDED SWORD +1 +3 VS UNDEAD reads 3 / $88 -- displaced and
undead-slaying, the guide's names for both. GAUNTLETS OF OGRE POWER reads 38 /
$83. The fourth, LONG SWORD +3 at $84, is **not** evidence about any code:
`$84` is the alignment-locked sword and its `+14` is two nibbles, not an id.
POTION OF HEALING reads 85 / $00 and is a potion, not a level drain.

**The table below is Pool of Radiance's, and Curse of the Azure Bonds shares
it. Secret of the Silver Blades does not** -- it gives an elf 95 where Pool of
Radiance gives 107, and five of the nine codes its character generation seeds
mean something else here. `NAMES_SILVER_BLADES` below is that title's own, and
:func:`for_game` is how a caller asks for the right one; the evidence for the
split is in the comment above the table.

Lives in `goldbox/` rather than in the editor because the combat view names the same
codes on a monster's tooltip, and one table cannot be allowed to become two.
"""

from __future__ import annotations

from dataclasses import dataclass

SLOTS = 10                     # 0x0AD-0x0B6; three overlays loop LDX #$09
FIRST = 0x0AD

# code -> (what it does, how sure we are).
#
# CONFIRMED means either a record on the player's disks carries the code and
# the carrier is what the name demands -- checked against the AD&D 1st
# edition Monster Manual, which is the external rule this project promotes
# on, with the carriers named in the trailing comments and coming from a
# census of 116 `MON*` records across the eight POOL disks plus the save
# fixtures -- or the DOS overlay's own code was read and settles it without
# any specimen, as for 90 and 97 (#247, docs/189-effect-97-from-the-code.md).
#
# PROBABLE means the guide names it and no C64 record exercises it. Every
# spell effect (1-63, bar the four below) is in that state and will stay there
# until a character is caught carrying one: a save taken mid-spell would
# promote a dozen at once.
NAMES: dict[int, tuple[str, str]] = {
    1: ("Bless", "CONFIRMED"),
    2: ("Curse", "PROBABLE"),
    # The player's own TWO-HANDED SWORD +1 +3 VS UNDEAD carries 3 as a passive
    # item power (+14 = 3, +15 = $88).
    3: ("wielding an undead-slaying weapon", "CONFIRMED"),
    4: ("starting to train with a Manual of Bodily Health", "PROBABLE"),
    5: ("Detect Magic", "CONFIRMED"),
    6: ("wielding a Flame Tongue", "PROBABLE"),
    7: ("training with a Manual of Bodily Health", "PROBABLE"),
    8: ("Protection from Evil", "CONFIRMED"),
    9: ("Protection from Good", "CONFIRMED"),
    10: ("Resist Cold", "CONFIRMED"),
    11: ("charmed", "PROBABLE"),
    12: ("Enlarge", "CONFIRMED"),
    13: ("Reduce", "PROBABLE"),
    14: ("Friends", "CONFIRMED"),
    15: ("Slow Poison, damage", "PROBABLE"),
    16: ("Read Magic", "CONFIRMED"),
    17: ("Shield", "CONFIRMED"),
    18: ("gnome THAC0 bonus against kobolds and goblins", "PROBABLE"),
    19: ("Find Traps", "CONFIRMED"),
    20: ("Resist Fire", "CONFIRMED"),
    21: ("Silence, 15' Radius", "PROBABLE"),
    22: ("Slow Poison, expiry", "PROBABLE"),
    23: ("Spiritual Hammer", "PROBABLE"),
    24: ("sees invisible creatures", "CONFIRMED"),          # TYRANITHRAXUS
    25: ("invisible", "CONFIRMED"),
    26: ("dwarf THAC0 bonus against orcs, half-orcs, goblins and hobgoblins",
         "PROBABLE"),
    27: ("feather falling", "PROBABLE"),
    28: ("Mirror Image", "CONFIRMED"),
    29: ("Ray of Enfeeblement", "PROBABLE"),
    30: ("coughing in a Stinking Cloud", "PROBABLE"),
    31: ("helpless", "PROBABLE"),
    32: ("Animate Dead", "PROBABLE"),
    33: ("blind", "PROBABLE"),
    34: ("diseased", "PROBABLE"),
    35: ("under an allied Prayer", "CONFIRMED"),
    36: ("Bestow Curse", "PROBABLE"),
    37: ("blinking", "CONFIRMED"),                         # PHASE SPIDER
    # goldbox/items.py has the gauntlets carrying 38, derived before the guide was
    # read; two independent lines on one id.
    38: ("extra strength", "CONFIRMED"),
    39: ("hasted", "CONFIRMED"),
    40: ("cast Stinking Cloud", "PROBABLE"),
    41: ("Protection from Normal Missiles", "CONFIRMED"),
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
    # A Sleep cast on a slums orc ambush wrote 53 on all five sleeping orcs --
    # not 31, which `automap/combat.py` had wrongly used as the sole trigger.
    53: ("sleeping", "CONFIRMED"),
    54: ("repulsed (bronze dragon; the handler is unimplemented)", "PROBABLE"),
    55: ("poisoned", "PROBABLE"),
    56: ("wearing a Ring of Invisibility", "PROBABLE"),
    57: ("mummy rot, degenerating", "PROBABLE"),
    58: ("immobile", "PROBABLE"),
    59: ("gains regeneration when this expires", "PROBABLE"),
    60: ("unused", "PROBABLE"),
    # goldbox/items.py has the ring carrying 61, again derived independently.
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
    # DOS's own handler, GAME.OVR:0x11134, reads the character's constitution
    # at the moment a paralysis/poison/death save is rolled and adds a band
    # bonus never stored in the record; written by race alone at creation.
    # CONFIRMED from the overlay, #247, docs/189-effect-97-from-the-code.md.
    90: ("dwarf/halfling constitution bonus to paralysis, poison and death "
         "saves", "CONFIRMED"),
    91: ("immune to electricity and Magic Missile", "CONFIRMED"),  # JUJU ZOMBIE
    # The guide has 92 unused. TYRANITHRAXUS carries it, so the C64 uses an id
    # DOS does not, or the guide missed a handler. Either way it is not named.
    92: ("not named -- the guide has this id unused", "UNKNOWN"),
    93: ("half damage from fire", "CONFIRMED"),            # JUJU ZOMBIE
    94: ("half damage from blunt or piercing weapons", "CONFIRMED"),
    95: ("fights on from -6 to 0 hit points", "PROBABLE"),
    96: ("hit only by silver or magical weapons", "CONFIRMED"),    # WIGHT
    # DOS's own handler, GAME.OVR:0x112E5, reads the character's constitution
    # at the moment a wand or spell save is rolled and adds a band bonus
    # never stored in the record; written by race alone at creation, so a
    # low-constitution character gets the id and a bonus of zero rather than
    # a bonus he did not earn. CONFIRMED from the overlay, #247,
    # docs/189-effect-97-from-the-code.md.
    97: ("dwarf/gnome/halfling constitution bonus to wand and spell saves",
         "CONFIRMED"),
    98: ("regenerates 3 hit points a round", "CONFIRMED"),         # VAMPIRE
    99: ("keeps fighting once unconscious", "CONFIRMED"),          # WILD BOAR
    100: ("troll: vulnerable to fire and acid, else returns from death",
          "CONFIRMED"),                                            # TROLL
    101: ("troll: regeneration", "CONFIRMED"),                     # TROLL
    102: ("troll: getting back up", "PROBABLE"),
    # 103, 114, 118 and 126 are the vampire's, and the vampire is the only
    # creature on the disks that carries any of them. Read together with the
    # six the census had already confirmed on it -- 86, 98, 119, 125 -- the
    # block is the Monster Manual's vampire entry line for line: two levels
    # drained, 3 hit points a round regenerated, hit only by magic, immune to
    # sleep/charm/paralysis/poison, **half damage from cold and electrical
    # attacks**, a charming gaze, and gaseous form. A coincidence would have
    # to put both halves of one Monster Manual sentence on the one creature
    # the sentence is about.
    103: ("can assume gaseous form", "CONFIRMED"),                 # VAMPIRE
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
    114: ("half damage from electricity", "CONFIRMED"),            # VAMPIRE
    115: ("half damage from piercing or slashing weapons", "CONFIRMED"),
    116: ("half damage from magical weapons", "CONFIRMED"),          # MUMMY
    # Every undead in the game carries 117 -- which is equally what "undead,
    # and so turnable" predicted, the reading this table used to give it. The
    # population cannot separate the two; the guide's decode is the tiebreak.
    117: ("vulnerable to holy water", "PROBABLE"),
    118: ("half damage from cold", "CONFIRMED"),                   # VAMPIRE
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
    # The pair splits the way the Monster Manual splits it: a basilisk's and
    # a medusa's gaze are turned back by a mirror, a vampire's charm gaze is
    # only avoided by not meeting its eyes. 127 is on both gorgons and
    # neither of them carries 126.
    126: ("gaze attack, avoidable", "CONFIRMED"),          # VAMPIRE
    127: ("gaze attack, reflectable", "CONFIRMED"),        # BASILISK, MEDUSA
    # Past the end of the guide's table, so this one is entirely ours.
    139: ("phasing", "PROBABLE"),                          # PHASE SPIDER
    # Measured, not assumed: across the 108 `MON*` records on the eight disks
    # 255 occurs 38 times and **every one of them is slot 9**, the last of
    # the ten. Slot 9 is 0 in the other 70 and no record has a code after a
    # 255. So it is a fill byte in the last slot, not an effect.
    255: ("fill, not a code", "CONFIRMED"),
}

# Fill in the last slot of a `MON*` trait block -- 38 of 108 records, slot 9
# every time. Not a trait, and a live ORC carries it, so the combat tooltip
# drops it rather than printing "fill".
FILL = 255

# The highest id the guide's table reaches. Anything above it is this project's
# own and has no third-party name to lean on.
LAST_DOCUMENTED = 127

EMPTY = "—"


# ---------------------------------------------------------------------------
# The table is Pool of Radiance's, and one title does not share it
# ---------------------------------------------------------------------------
# Curse of the Azure Bonds uses the same numbers for the same things. Its
# `GEN $24EA` seeds three trait slots per race from `$24FF`, `$2506` and
# `$250D`, and every code it writes lands on the race this table's name is
# about: dwarf 26, 47, 97; gnome 18, 48, 97; elf 107; half-elf 124; paladin 45;
# ranger 134. Read off the player's own disks by `tools/c64/coldread.py traits
# curse-of-the-azure-bonds`, and asserted in `tests/test_coldread.py`.
#
# **That argument covers the nine codes `GEN` seeds and not the other 137, and
# eight of those are wrong.** Curse's own per-spell table, `COMBAT2 +2732`,
# gives 3 to STICKS TO SNAKES, 4 to DISPEL EVIL, 7 to FAERIE FIRE, 27 to
# FUMBLE, 35 to CONFUSION, 63 to MINOR GLOBE OF INVULNERABILITY, 68 to
# FEEBLEMIND and 69 to INVISIBILITY TO ANIMALS -- spells Pool of Radiance has
# not got, on codes it was already using. `tools/c64/traitquery.py
# curse-of-the-azure-bonds --spells` is the run and #561 is the ticket; it is
# left as it stands here because #497 was about Silver Blades.
#
# **Secret of the Silver Blades does not.** Its `GEN $0C4B` seeds two slots
# from `$0C5B` and `$0C62`, seven bytes each, indexed by the race byte:
#
#     $0C5B: 95 95 18 26 48 0 0     races 0-6, 0 also being an elf
#     $0C62:  0  0  0 47  7 92 0
#
# so elf 95, half-elf 18, dwarf 26 and 47, gnome 48 and 7, halfling 92, human
# nothing -- and `GEN $0FF0` writes 45 for a paladin and 105 for a ranger.
# Five of those nine codes mean something else in Pool of Radiance, so a
# Silver Blades elf read through the table above says "fights on from -6 to 0
# hit points" (#186).
#
# **The reassignment is not confined to the racial codes**, which is why this
# title gets a table of its own rather than Pool of Radiance's with a few
# entries changed. A census of the 69 `MON*` records on the six Silver Blades
# sides against the 108 on the eight Pool of Radiance sides:
#
# * PHASE SPIDER carries 37 and 139 in Pool of Radiance and 37 and **86** in
#   Silver Blades -- the same creature, one code moved, and 86 is Pool of
#   Radiance's two-level drain, which a spider does not have;
# * FROST GIANT carries 98, Pool of Radiance's "regenerates 3 hit points a
#   round", and GARGOYLE and MARGOYLE carry 103, its "can assume gaseous
#   form";
# * GIANT SLUG carries 90, which in Pool of Radiance is a dwarf's and a
#   halfling's constitution bonus to saves;
# * 24 is on 36 of the 48 Silver Blades records that carry anything at all,
#   against one of Pool of Radiance's 59.
#
# So this title gets a table earned the way the other two were, code by code,
# and every code no route reaches falls back to `trait <n>`, which is the
# honest answer: this is a table of what has been read, not of what a reader
# might like to see.
#
# ---------------------------------------------------------------------------
# The routes that filled the table below, and what each one is worth
# ---------------------------------------------------------------------------
# Donald ruled on 2026-09-15 that the picker should offer this title's ids
# named properly, rather than staying at six or borrowing another title's
# names unmarked (#497). **90 ids do something in a trait slot here** --
# 80 on the engine's own check lists and ten more named by an instruction --
# and the routes below name all 90. `tools/c64/traitquery.py` takes every
# measurement off the player's disks and `docs/171-c64-trait-slots.md` has
# the runs.
#
# **The handler the id dispatches, read. CONFIRMED.** The combat ask
# dispatches a matched id through `LDX $7F6E / LDA $EF90,X / LDA $F001,X`,
# so the table index is the id itself and the address is a routine in
# `COMBAT` at `$0800`. `tools/c64/traitquery.py --handlers` prints each one.
# Reading them is what named the 35 ids no spell writes and no check-list
# agreement reached, and it corrected two names the other routes had
# offered: 93 zeroes fire damage rather than halving it, and 96 cancels
# sleep and charm rather than anything to do with silver. The anchors every
# reading rests on: `$A904` is the damage type (bit 0 fire, 1 cold, 2
# electricity, 3 magic, 4 acid -- the bit picks the "FROM FIRE" .. "FROM
# ACID" message at `COMBAT $107A` -- bit 5 a breath weapon, bit 6 a spell),
# `$945F` the damage, `$A903` the saving-throw d20 (list 12 is walked from
# inside the roll, so a list-12 handler that increments it is a save
# bonus), `$A915` the attack d20, `$7C00` the staged record with the ten
# slots at `$7CAD`, and `$14EF` the routine that zeroes both the damage and
# the effect being applied, which is what an immunity is. Where a creature,
# an item or a spell routine carries the id as well, the comment says so.
#
# **The spell that writes it. CONFIRMED.** `COMBAT2 +2937` is this title's
# per-spell record, nine bytes each, one per spell id 1-117, and byte 0 is
# the effect id the spell writes. So the game's own data says PROTECTION FROM
# EVIL writes 8 and BARKSKIN writes 13, and the spell's name names the code.
# Four things hold the reading up, and no two of them share a source: Pool of
# Radiance's copy of the same table (`ECL65 +0`, seven bytes a record,
# `goldbox/effects.py` reads it for durations and `CAMP $1429` indexes it)
# reproduces forty-odd spell-to-code pairs including six this project had
# already confirmed elsewhere -- BLESS 1, SLEEP 53, INVISIBILITY 25, HASTE
# 39, STRENGTH 38 and DETECT MAGIC 5; Curse of the Azure Bonds keeps the same
# nine-byte table at `COMBAT2 +2732` and agrees with this one on 54 of the
# first 56 spells; all 117 of this title's values fall inside its own 113-code
# namespace; and byte 1 is a message index into the same string table
# `goldbox/spells.py` reads, where 59 is `IS BLESSED` in all three titles.
#
# **The same code in the same numbered check list as Curse. PROBABLE.** The
# walker takes a list *number*, so list 12 is "target, saving throw" whichever
# title is running and a code on it in two titles is being asked the same
# question about the same thing. 46 of the 90 agree with Curse that way.
# It is positional agreement rather than a read of a handler, and the spell
# table above **caught it being wrong three times in twenty-eight** -- 4, 27
# and 35, where the later titles gave a Pool of Radiance code to a new spell.
# So a name is taken from this route only when the check the list performs
# makes sense of it: 31 "helpless" on list 7 with hold, sleep and snake charm
# does, and 50 "mummy rot, blocking healing" on the two saving-throw lists
# does not.
#
# **The same routine asking about the same code in two titles. PROBABLE.**
# 43 and 44 are asked fifteen bytes apart in `ECL65` in Curse and again
# fifteen bytes apart in `ECL65` here, in the same order; 96 is asked at
# `COMBAT $1194` in Curse and `COMBAT $1191` here.
#
# **The creature carrying it. PROBABLE.** The route Pool of Radiance's own
# table was built on, over the 71 `MON*` records on the six sides. It
# **named** three -- 64 lands on this title's eight poisoners, the same
# creature set that carries it in Pool of Radiance, and BASILISK, MEDUSA and
# SARGATHA carry the pair 58/59 where Pool of Radiance's basilisk and medusa
# carry 83/127, with the one of the pair on list 14 matching the one of Pool
# of Radiance's pair on list 14. It also **refused** four that positional
# agreement had offered, which is the more useful half: 60 "unused" (an IRON
# GOLEM carries it), 65 "melee poison, +4 to save" (a COCKATRICE, which has
# no poison), 83 "petrifying gaze" (two dragons, while this title's basilisk
# and medusa carry 58 and 59 instead) and 73 "rear claw rake" (four dragons).
#
# **A spell row is not evidence until its name is its own**, and 73 is the
# worked example -- it reads like the spell route's 45th id and it is not.
# `COMBAT2`'s name table gives one string to a spell granted at two levels, so
# a shared pointer is ordinary: DETECT MAGIC covers spells 5, 11 and 77 and
# all three write 5. Fifteen names are shared between rows here and eleven
# have every row writing the same id; each of the other four holds a row that
# is in no spell group at all, and spell rows 95 and 96 are one of them --
# both point at `$E471`, `CHARM PERSON OR MAMMAL`, and 95 writes 73 with the
# message `IS PROTECTED` while 96 writes 11 with `IS CHARMED`. Four things
# say 96 is the spell and 95 the row whose pointer was never set:
# `goldbox/spells.py`'s own
# group table puts 96 in druid level 2 and **95 in no group at all**; 11 is
# already this table's "charmed" from CHARM PERSON at spell 10; Curse's row 95
# writes the same 73 and the same message under a pointer to `$E000`, the
# first string in its table and its unused-slot marker; and ANCIENT DRAGON,
# RED DRAGON, RED HATCHLING and WHITE DRAGON carry 73 innately, on list 6,
# which is where a resistance to spell damage is asked about. **So 73 stays
# unnamed.** The same reading is why 39 is taken from HASTE at spell 48 rather
# than from row 57, which shares CURE SERIOUS WOUNDS' pointer and writes 39
# too, and why 25 comes from INVISIBILITY rather than from row 97.

#: Secret of the Silver Blades' effect codes. Each entry carries its grade and
#: the route that earned it in the comment above it; `docs/171-c64-trait-slots.md`
#: has the evidence and `tools/c64/traitquery.py --spells`, `--compare` and
#: `--lists` re-take the measurements.
#:
#: **A string that is `NAMES[n][0]` is Pool of Radiance's own, pointed at the
#: number this title uses for the same thing** -- the pattern the first six
#: entries here were written with. A literal string is one no code in the
#: shared table stands for, and it is the game's own spell name, spelled the
#: way this table already spells BLESS, ENLARGE and SILENCE 15' RADIUS.
NAMES_SILVER_BLADES: dict[int, tuple[str, str]] = {
    # -- the spell that writes it (CONFIRMED) ------------------------------
    1: (NAMES[1][0], "CONFIRMED"),                     # BLESS
    2: (NAMES[2][0], "CONFIRMED"),                     # CURSE
    # 3, 4, 13, 27, 35, 63, 68 and 69 are codes the shared table names for
    # something else. This title spent them on spells Pool of Radiance does
    # not have, and its own table is what says so.
    3: ("Sticks to Snakes", "CONFIRMED"),              # STICKS TO SNAKES
    4: ("Dispel Evil", "CONFIRMED"),                   # DISPEL EVIL
    5: (NAMES[5][0], "CONFIRMED"),                     # DETECT MAGIC
    8: (NAMES[8][0], "CONFIRMED"),                     # PROTECTION FROM EVIL
    9: (NAMES[9][0], "CONFIRMED"),                     # PROTECTION FROM GOOD
    10: (NAMES[10][0], "CONFIRMED"),                   # RESIST COLD
    11: (NAMES[11][0], "CONFIRMED"),                   # CHARM PERSON
    12: (NAMES[12][0], "CONFIRMED"),                   # ENLARGE
    # REDUCE writes nothing here, where it writes 13 in the other two, and
    # BARKSKIN has the code instead. Lists 11 and 12 -- to hit and saving
    # throw -- are where an armour-class spell belongs.
    13: ("Barkskin", "CONFIRMED"),                     # BARKSKIN
    17: (NAMES[17][0], "CONFIRMED"),                   # SHIELD
    20: (NAMES[20][0], "CONFIRMED"),                   # RESIST FIRE
    21: (NAMES[21][0], "CONFIRMED"),                   # SILENCE 15' RADIUS
    23: (NAMES[23][0], "CONFIRMED"),                   # SPIRITUAL HAMMER
    24: (NAMES[24][0], "CONFIRMED"),                   # DETECT INVISIBILITY
    25: (NAMES[25][0], "CONFIRMED"),                   # INVISIBILITY
    27: ("Fumble", "CONFIRMED"),                       # FUMBLE
    28: (NAMES[28][0], "CONFIRMED"),                   # MIRROR IMAGE
    29: (NAMES[29][0], "CONFIRMED"),                   # RAY OF ENFEEBLEMENT
    30: (NAMES[30][0], "CONFIRMED"),                   # STINKING CLOUD
    33: (NAMES[33][0], "CONFIRMED"),                   # CAUSE BLINDNESS
    34: (NAMES[34][0], "CONFIRMED"),                   # CAUSE DISEASE
    35: ("Confusion", "CONFIRMED"),                    # CONFUSION
    36: (NAMES[36][0], "CONFIRMED"),                   # BESTOW CURSE
    37: (NAMES[37][0], "CONFIRMED"),                   # BLINK
    39: (NAMES[39][0], "CONFIRMED"),                   # HASTE
    41: (NAMES[41][0], "CONFIRMED"),          # PROTECTION FROM NORMAL MISSILES
    42: (NAMES[42][0], "CONFIRMED"),                   # SLOW
    # 43 and 44 are asked about by no list and by one instruction each,
    # fifteen bytes apart in `ECL65` in this title and fifteen bytes apart in
    # `ECL65` in Curse, in the same order. PROBABLE, on that agreement.
    43: (NAMES[43][0], "PROBABLE"),
    44: (NAMES[44][0], "PROBABLE"),
    45: (NAMES[45][0], "CONFIRMED"),          # PROTECTION FROM EVIL 10' RADIUS
    46: (NAMES[46][0], "CONFIRMED"),          # PROTECTION FROM GOOD 10' RADIUS
    # PRAYER writes 49 here and in Curse, and 35 in Pool of Radiance, whose
    # 49 the shared table already calls Prayer -- so the pair swapped roles
    # and the string is right for this number.
    49: (NAMES[49][0], "CONFIRMED"),                   # PRAYER
    51: (NAMES[51][0], "CONFIRMED"),                   # SNAKE CHARM
    52: (NAMES[52][0], "CONFIRMED"),                   # HOLD PERSON
    53: (NAMES[53][0], "CONFIRMED"),                   # SLEEP
    55: (NAMES[55][0], "CONFIRMED"),                   # POISON, CLOUD KILL
    # The two globes are also the two ids `COMBAT` asks about by instruction,
    # seventeen bytes apart at `$15DC` and `$15ED`.
    57: ("Globe of Invulnerability", "CONFIRMED"),     # GLOBE OF INVULNERABLITY
    63: ("Minor Globe of Invulnerability", "CONFIRMED"),
    68: ("Feeblemind", "CONFIRMED"),                   # FEEBLEMIND
    69: ("Invisibility to Animals", "CONFIRMED"),      # INVISIBILITY TO ANIMALS
    # Curse gives FAERIE FIRE 7 and this title gives it 71, which is why the
    # gnome's second seed, 7, stays unnamed below. List 11 is "target, to
    # hit", which is what faerie fire is for.
    71: ("Faerie Fire", "CONFIRMED"),                  # FAERIE FIRE
    # One code for three spells, which is why it is named by all three rather
    # than by a state nobody has read. Curse spends 136 on ENTANGLE alone.
    106: ("Entangle, Trip or Power Word Stun", "CONFIRMED"),
    111: ("Fear", "CONFIRMED"),                        # FEAR
    112: ("Fire Shield", "CONFIRMED"),                 # FIRE SHIELD

    # -- offered by the same numbered check list as Curse, then settled by
    # -- the handler (CONFIRMED where the handler says so) ------------------
    # 26, 47 and 48 are also what `GEN` seeds a dwarf and a gnome. The
    # handlers read the *other* combatant's creature-type bytes, record
    # `$D4`/`$D5`: 26 is `INC $A915` (+1 on the attack d20) when the target
    # has `$D4` bit 7; 47 and 48 add 4 to the target's working AC when the
    # attacker has `$D4` bit 2 (every giant and the OGRE in the census) or
    # bit 5 (those plus the BUGBEAR).
    26: (NAMES[26][0], "CONFIRMED"),                   # list 10, $25E4
    # $27D4 sets the lose-your-actions flag and clears movement and attacks,
    # the same handler hold, sleep and snake charm dispatch.
    31: (NAMES[31][0], "CONFIRMED"),                   # list 7, $27D4
    47: (NAMES[47][0], "CONFIRMED"),                   # list 11, $2796
    48: (NAMES[48][0], "CONFIRMED"),                   # list 11, $27A5
    # $2828: on fire, one point per die off twice and +2 on the save twice,
    # which is the AD&D ring to the letter. The RING OF FIRE RESISTANCE
    # template carries 61 at +14 with +15 = $80.
    61: (NAMES[61][0], "CONFIRMED"),         # lists 6 and 12, spell damage
    89: (NAMES[89][0], "PROBABLE"),                    # list 16, miss chance
    # Agreement offered "half damage from fire" and the handler refuses it:
    # $290E is `LDA #$01 / AND $A904 / BEQ / JSR $14EF`, which zeroes the
    # damage on fire and halves nothing. FIRE GIANT and DREADLORD carry it,
    # and a fire giant is immune. The string is Pool of Radiance's 112.
    93: (NAMES[112][0], "CONFIRMED"),                  # list 6, $290E

    # -- once "the same routine asking in two titles"; the handler says
    # -- otherwise (CONFIRMED) ---------------------------------------------
    # The call at `COMBAT $1191` is `LDA $A902 / LDX $945D / JSR $3854` --
    # the effect being applied, not a literal 96 -- so that evidence was an
    # artefact of decoding backwards. $291D cancels 53 and 11 outright:
    # immune to sleep and charm, which is the DREADLORD's. 95 and 18 are the
    # same routine behind a 90% and a 30% roll.
    96: (NAMES[108][0], "CONFIRMED"),                  # list 9, $291D

    # -- the creature carrying it, then the handler (CONFIRMED) ------------
    # BASILISK, MEDUSA and SARGATHA carry 58 and 59 where Pool of Radiance's
    # basilisk and medusa carry 83 and 127. $16C5 is the gaze: range 4,
    # "GAZES...", ranged form 4 whose message is "TURNS TO STONE" -- and
    # before it fires, if the gazer has 59 and the target has 72, "REFLECTS
    # IT" and the gazer becomes its own target.
    58: (NAMES[83][0], "CONFIRMED"),
    59: (NAMES[127][0], "CONFIRMED"),
    # 64 lands on GIANT SNAKE, GIANT SPIDER, MEDUSA, WYVERN, PURPLE WORM,
    # CENTIPEDE, FIRE KNIFE and SARGATHA. $181D: a save on the poison column
    # with no modifier, "IS POISONED", and on a failure hit points to zero
    # with "IS KILLED" -- save or die.
    64: (NAMES[64][0], "CONFIRMED"),

    # -- what `GEN` seeds by race, then the handler (CONFIRMED) ------------
    # `GEN $0C5B` gives a half-elf 18 and an elf 95. $2912 and $2916 are one
    # routine entered with 30 and 90: roll d100, and under that number cancel
    # a sleep (53) or a charm (11) being applied.
    18: (NAMES[124][0], "CONFIRMED"),
    95: (NAMES[107][0], "CONFIRMED"),

    # -- the handler it dispatches, read (CONFIRMED) -----------------------
    # Damage-type immunities: `LDA #bit / AND $A904 / BEQ / JSR $14EF`.
    # STORM GIANT and DREADLORD carry 6; FROST GIANT and DREADLORD 98; the
    # four dragons (ANCIENT, RED, RED HATCHLING, WHITE) 73, bit 5 being the
    # bit both breath handlers set.
    6: ("immune to electricity", "CONFIRMED"),                     # $2927
    73: ("immune to breath weapons", "CONFIRMED"),                 # $292C
    98: (NAMES[110][0], "CONFIRMED"),                              # $2930
    # $27DC and $27E2 are one routine with fire and cold swapped: the one
    # element doubles the damage, the other halves it and adds 2 on the
    # save. No shipped creature or spell carries either.
    50: ("vulnerable to fire, resistant to cold", "CONFIRMED"),    # $27DC
    54: ("vulnerable to cold, resistant to fire", "CONFIRMED"),    # $27E2
    # Weapons. $23C9 is the attacker's best weapon plus; 60 zeroes the damage
    # under +3 (IRON GOLEM) and 103 at +0 (GARGOYLE, MARGOYLE, DREADLORD).
    # 90 stages the weapon's `ITEMS` type entry and zeroes the damage when
    # byte +7 has bit 7 -- set on the mace, hammer, morning star, staff,
    # flail and sling types -- and a GIANT SLUG carries it.
    60: ("hit only by +3 or better weapons", "CONFIRMED"),         # $2819
    90: ("immune to blunt weapons", "CONFIRMED"),                  # $28F1
    103: (NAMES[119][0], "CONFIRMED"),                             # $294F
    # Effect immunities, `LDA #id / JSR $14EA` for each: 76 cancels 34; 92
    # cancels 29, 68 and 111; 99 cancels 55, 30, 31 and 52. The PERIAPT OF
    # HEALTH template carries 76 at +14. DREADLORD carries 92 and 99, and
    # `GEN $0C62` seeds a halfling 92 as well.
    76: ("immune to disease (Periapt of Health)", "CONFIRMED"),    # $2861
    92: ("immune to Ray of Enfeeblement, Feeblemind and Fear",
         "CONFIRMED"),                                             # $28FF
    99: (NAMES[111][0], "CONFIRMED"),                              # $293B
    # Melee specials, lists 2 and 3. 65 is the gaze's tail entered without
    # the range or mirror checks (COCKATRICE). 86 is 64's poison with the
    # save byte $C1, whose top three bits are a -2 (PHASE SPIDER). 88 is a
    # save on the paralysis column or 52, held, for the fight (DREADLORD,
    # DRIDER).
    65: ("petrifying touch", "CONFIRMED"),                         # $1705
    86: (NAMES[70][0], "CONFIRMED"),                               # $1810
    88: ("melee paralysis", "CONFIRMED"),                          # $184D
    # Weapon-damage specials, list 4. 66 reads the attack d20 `ECL64 $84F9`
    # stored and on a 20 sets the damage to the target's hit points plus
    # ten, "IS SWALLOWED!" (REMORHAZ). 75 is +1 on the attack d20 and 1d12+1
    # damage when the target has `$D5` bit 0, which every giant has; the
    # LONG SWORD VS. GIANTS template carries it at +14. 105 adds the ranger
    # level at record `$D0` to melee damage when the target has `$D4` bit 3
    # -- giants, ogre, ettin, bugbear -- and is the ranger's seed.
    66: ("swallows whole on a natural 20", "CONFIRMED"),           # $170B
    75: ("wielding a giant-slaying weapon", "CONFIRMED"),          # $2849
    105: ("ranger: +1 damage per level against giant-class creatures",
          "CONFIRMED"),                                            # $2957
    # Ranged forms, list 14, chosen by the monster's turn in `SECSET64`.
    # 67 fires form 0, "BREATHES...", 8 fire, at range 3 on every attack up
    # to the head count (12HD PYROHYDRA). 80 fires form 1, 7 fire, at range
    # 2 half the time (HELL HOUND). 70 is "GAZES..." and form 2, whose
    # message is "IS CONFUSED" and whose effect is 35 (UMBER HULK). 81 is
    # "SPITS A STREAM OF ACID", 4d8 at range 7, hitting 50% plus 10% a
    # square under six (GIANT SLUG). 83 and 104 are the breath cone with
    # `$A904` = $A2 and $A1: the target's hit points, save vs. breath for
    # half, cold at range 8 (WHITE DRAGON, the 10HD ANCIENT DRAGON) and fire
    # at range 9 (RED DRAGON, RED HATCHLING, the 15HD ANCIENT DRAGON).
    67: ("pyrohydra: breathes fire with each head", "CONFIRMED"),  # $1726
    70: ("confusing gaze", "CONFIRMED"),                           # $173F
    80: ("hell hound: breathes fire", "CONFIRMED"),                # $1755
    81: ("spits a stream of acid", "CONFIRMED"),                   # $176E
    83: ("cold breath weapon", "CONFIRMED"),                       # $17D5
    104: ("fire breath weapon", "CONFIRMED"),                      # $186B
    # $28B0, IRON GOLEM's second id: on a spell (`$A904` bit 6), fire heals
    # the damage instead, electricity applies 42 with "IS SLOWED", and every
    # spell's damage and effect are then zeroed.
    79: ("iron golem: healed by fire, slowed by electricity, immune to "
         "other spells", "CONFIRMED"),                             # $28B0
    # Start of combat, list 8. 56 and 108 both apply 25 to the carrier
    # through `$1113`; 56 with a duration of 12 and the RING OF
    # INVISIBILITY template carrying it at +14, 108 silently with none.
    # 82 walks combatants 0-7 and marks every living one below level 5 as
    # afraid with "IS TERRIFIED BY A LICH"; no shipped MON record carries it.
    56: (NAMES[56][0], "CONFIRMED"),                               # $2810
    82: ("fear aura: terrifies characters below level 5",
         "CONFIRMED"),                                             # $17A2
    108: ("invisible at the start of combat", "CONFIRMED"),        # $2970
    # Turn start, list 15. $286B prints raw message 59, "IS BERSERKING",
    # then finds the nearest creature on its own side, makes it the target
    # and moves the carrier to the other side with the changed-side bits
    # set; 107 is the same routine without the message, and CONFUSION's
    # handler at $26E8 writes it on a 50-69 roll of d100 beside 27, 111 and
    # 11. On expiry both restore the side, the way charm does.
    77: ("berserk, attacking the nearest ally", "CONFIRMED"),      # $286B
    107: ("confused, attacking the nearest creature", "CONFIRMED"),   # $2866
    # Movement, list 18: $2840 doubles the movement being computed, the
    # same `ASL $A91E` as haste. BOOTS OF SPEED carry it at +14.
    74: ("moves at double speed (Boots of Speed)", "CONFIRMED"),   # $2840
    # Saving throws, list 12, which is walked with the d20 in `$A903`:
    # $249B is `INC $A903`. STONE OF GOOD LUCK carries it at +14.
    78: ("+1 to saving throws (Stone of Good Luck)", "CONFIRMED"), # $249B
    # Asked by name at $16E0 inside the gaze handler and nowhere else: a
    # target carrying 72 turns a reflectable gaze back on the gazer. The
    # MIRROR and the SILVER SHIELD +5 carry it at +14.
    72: ("carrying a mirror (reflects gaze attacks)", "CONFIRMED"),   # 58's
    # The gnome's second seed. $2469 is `INC $A915` when the target has
    # `$D5` bit 2, which in the census only the BUGBEAR has -- this title's
    # stand-in for the kobolds and goblins the ability is named for.
    7: (NAMES[18][0], "CONFIRMED"),                                # $2469
    # DISPEL EVIL's own routine at $1F96 writes 32 to the caster beside 4.
    # $263D: against a target with `$D4` bit 0 (the HELL HOUND, from the
    # lower planes) the hit becomes ranged form 5, "DISAPPEARS!", and the
    # caster's 4 ends. The same routine then removes 35 rather than 32, so
    # the touch outlives the protection until its own duration runs out.
    32: ("Dispel Evil, dismissal touch", "CONFIRMED"),             # $263D
    # Asked by name in camp only, `ECL65 $8730`, by the paladin's cure
    # disease: after the cure it is put on the paladin with duration $C7 and
    # his uses at record `$012` (`GEN $0C6E`: one per five levels) go down
    # one; when it expires the camp's own table at `ECL65 $9496` sends it to
    # $8657, which recomputes the uses. 109 is lay on hands' twin, with $C1
    # and record `$013`. The combat handler, shared with 15, 34, 43 and 44,
    # only re-instates the effect at expiry.
    110: ("paladin: cure disease uses return when this expires",
          "CONFIRMED"),                                            # $24EE
}
# **All 90 ids the engine honours in a trait slot are named, 87 CONFIRMED and
# 3 PROBABLE** (43, 44 and 89, whose handlers were not read: the first two
# share the camp-condition handler with 110, and 89's sets a field nobody has
# named). Four more entries -- 11, 12, 34 and 111 -- are on no list and
# asked by no instruction, so they do nothing in a slot and are named for the
# active-effects panel, which shares this table.
#
# Nine ids that positional agreement offered a name for were refused in the
# first pass and then read in the third, which is where a reader is most
# likely to want the reasoning:
#
# * **50** and **54** were offered "mummy rot, blocking healing" and a bronze
#   dragon's repulsion; the handlers are a matched pair of fire/cold
#   vulnerability and resistance.
# * **56** was offered "wearing a Ring of Invisibility" and the refusal was
#   wrong: the handler applies invisibility at the start of combat and the
#   ring's own template carries 56 at +14. The DREADLORD carries it too.
# * **60** was offered "unused" and is the iron golem's +3 weapon immunity;
#   **65** was offered "melee poison, +4 to save" and is the cockatrice's
#   petrifying touch.
# * **73** was offered "rear claw rake" and is immunity to breath weapons;
#   **83** was offered "petrifying gaze" and is the cold breath weapon. 73
#   is also the one id the spell route appears to reach and does not: spell
#   row 95 writes it, but that row's name is spell 96's -- the two share a
#   name pointer, 96 is the druid CHARM PERSON OR MAMMAL and writes 11, and
#   95 is in no spell group at all. The paragraph above the table has the
#   four strands.
# * **75** and **77** sat in the same lists as Curse's and in different ones
#   from Pool of Radiance's; they are the giant-slaying sword and berserking.
#
# The three seeds that were unnamed are the gnome's kobold-and-goblin bonus
# (7), the halfling's immunity to Ray of Enfeeblement, Feeblemind and Fear
# (92 -- read off the handler, and an odd thing to give a halfling; the
# DREADLORD carries it as well) and the ranger's damage bonus against
# giant-class creatures (105).
#
# Five named ids have no shipped carrier at all -- 50, 54, 77, 82 and 108 --
# so their names rest on the handler alone. The experiment that would add a
# second line to any of them is `tools/c64/traitask.py`'s: write the id into a
# slot on a copy of a save and watch the fight.

#: Curse of the Azure Bonds seeds the same racial codes as Pool of Radiance
#: (`GEN $24EA`: dwarf 26/47/97, gnome 18/48/97, elf 107, half-elf 124,
#: paladin 45, ranger 134), so `NAMES` served it for a while -- but Curse's
#: forty-four extra spells spent free code numbers on their own effects,
#: including numbers Pool of Radiance was already using, and `NAMES` never
#: gave those a table of its own. `#561 (A Curse of the Azure Bonds
#: character's traits are named from Pool of Radiance's table, which
#: disagrees with Curse's own data about eight codes)` is where the census
#: -- `tools/traitnames.py curse-of-the-azure-bonds` and its `--monsters` and
#: `--records` flags -- read Curse's own `COMBAT2 +2732` spell table (100
#: nine-byte records, byte 0 the effect code) and its 70 `MON*` templates
#: against `NAMES`.
#:
#: **Thirteen codes CONFIRMED wrong or unnamed by Curse's own spell table**:
#: 3, 4, 7, 27, 35, 63, 68, 69 (Pool of Radiance's name is a different
#: effect), 105 (Pool of Radiance's "(unused)" is wrong -- five dark elf
#: records carry it), and 136, 142, 143 (Pool of Radiance names nothing
#: there at all). 60 is CONFIRMED wrong by its own handler, read the same way
#: `NAMES_SILVER_BLADES` reads 60, though the exact rule is PROBABLE.
#:
#: **Eighteen codes are omitted rather than mis-named.** Twelve of them are
#: Pool of Radiance names landing on a Curse creature that cannot have them
#: -- 57, 60's Pool of Radiance wording, 63's, 81, 82, 84, 85, 86, 87, 90, 96,
#: 103 -- of which 60 and 63 are replaced above and the other ten
#: (57, 81, 82, 84, 85, 86, 87, 90, 96, 103) are simply refuted, with no
#: right answer read yet. And eight of Curse's own codes above `NAMES`'s
#: reach are carried by a Curse creature `NAMES` never named at all -- 128,
#: 129, 130, 131, 132, 133, 135, 138. Every one of the eighteen is left out
#: of this table so `describe()` falls back to "trait {code}" (unnamed)
#: rather than a name the game's own data contradicts.
#:
#: **71, 73 and 109 keep Pool of Radiance's wording on purpose.** Their only
#: Curse evidence is a spell row whose name pointer was never set (it reads
#: as the table's first string, BLESS) and no Curse creature carries them,
#: so nothing here contradicts Pool of Radiance for these three -- unlike
#: Silver Blades' 71, which Curse's own FAERIE FIRE at 7 does contradict.
#:
#: **Everything else transfers unchanged from `NAMES`.** Most of the shared
#: namespace agrees between the two titles (54 of the first 56 spell codes,
#: and thirteen monster-carried codes on the same creature in both), so this
#: is written as a full table rather than a sparse one of overrides only --
#: a sparse table would leave hundreds of correctly-named codes unnamed for
#: Curse.
_CURSE_UNNAMED = (
    57, 81, 82, 84, 85, 86, 87, 90, 96, 103,           # refuted, not replaced
    128, 129, 130, 131, 132, 133, 135, 138,            # Curse-only, unnamed
)
_CURSE_REPLACED = {
    3: ("Sticks to Snakes", "CONFIRMED"),
    4: ("Dispel Evil", "CONFIRMED"),
    7: ("Faerie Fire", "CONFIRMED"),
    27: ("Fumble", "CONFIRMED"),
    35: ("Confusion", "CONFIRMED"),
    60: ("damage reduced by the weapon's plus", "PROBABLE"),
    63: ("Minor Globe of Invulnerability", "CONFIRMED"),
    68: ("Feeblemind", "CONFIRMED"),
    69: ("Invisibility to Animals", "CONFIRMED"),
    105: ("50% magic resistance", "CONFIRMED"),
    136: ("Entangle", "CONFIRMED"),
    142: ("Fear", "CONFIRMED"),
    143: ("Fire Shield", "CONFIRMED"),
}
NAMES_CURSE: dict[int, tuple[str, str]] = {
    **{code: value for code, value in NAMES.items()
       if code not in _CURSE_UNNAMED and code not in _CURSE_REPLACED},
    **_CURSE_REPLACED,
    # 71, 73, 109: refuted for nothing else, so Pool of Radiance's wording
    # stands until Curse's own data says otherwise.
    71: (NAMES[71][0], "PROBABLE"),
    73: (NAMES[73][0], "CONFIRMED"),
    109: (NAMES[109][0], "PROBABLE"),
}

#: Code table per title key. A title that is not here gets Pool of Radiance's,
#: which is what every caller written before this table existed means.
TABLES: dict[str, dict[int, tuple[str, str]]] = {
    "pool-of-radiance": NAMES,
    "curse-of-the-azure-bonds": NAMES_CURSE,
    "secret-of-the-silver-blades": NAMES_SILVER_BLADES,
}

#: What a caller gets when it says nothing.
DEFAULT_NAMES = NAMES


def for_game(game=None) -> dict[int, tuple[str, str]]:
    """The code table for a title.

    Takes a `goldbox.c64_port.C64Container`, a game key, a table, or None. Duck-typed on
    `.key` rather than importing `goldbox.c64_port`, which is what
    `goldbox/spells.py:for_game` does and for the same reason: a whole module
    of coupling for one string.

    An unrecognised title gets Pool of Radiance's -- the Krynn pair and Gateway
    have never had their seeds read, and this is the behaviour they have always
    had.
    """
    if isinstance(game, dict):
        return game
    return TABLES.get(getattr(game, "key", game), DEFAULT_NAMES)


def describe(code: int, game=None) -> str:
    """What a slot says. An unnamed code is visibly unnamed, never blank.

    An unnamed code keeps its **number**: two slots we cannot name still have
    to be told apart, and the number is what somebody takes away to look it up.
    """
    if not code:
        return EMPTY
    named = for_game(game).get(code)
    return named[0] if named else f"trait {code}"


def confidence(code: int, game=None) -> str:
    """How sure the name is. `UNNAMED` codes have no confidence to report."""
    named = for_game(game).get(code)
    return named[1] if named else ""


@dataclass(frozen=True)
class Trait:
    """One occupied slot, named if we can and numbered either way.

    `game` is whatever :func:`for_game` takes, and None means Pool of
    Radiance's table -- which is what every caller written before the second
    title means.
    """

    slot: int
    code: int
    game: object | None = None

    @property
    def names(self) -> dict[int, tuple[str, str]]:
        return for_game(self.game)

    @property
    def named(self) -> bool:
        return self.code in self.names

    @property
    def is_fill(self) -> bool:
        return self.code == FILL

    @property
    def label(self) -> str:
        """`petrifying gaze` for a code we know, `trait 91` for one we do not.

        The number is what makes a new code visible rather than silently
        dropped, which is how the census grew in the first place.
        """
        return (describe(self.code, self.game) if self.named
                else f"trait {self.code}")

    @property
    def detail(self) -> str:
        where = f"0x{FIRST + self.slot:03X}"
        if not self.named:
            return f"{where} holds {self.code}, which the census does not name"
        return (f"{where}: {describe(self.code, self.game)} "
                f"({confidence(self.code, self.game)})")


def traits(raw: bytes, game=None) -> tuple[Trait, ...]:
    """The occupied slots of one ten-byte trait block."""
    return tuple(Trait(i, code, game)
                 for i, code in enumerate(raw[:SLOTS]) if code)
