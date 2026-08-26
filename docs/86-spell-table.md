# Spell table

**Generated** — run `python3 tools/genspells.py`. Read straight off a
game disk, so the spellings are the game's own.

A character's memorised spells are a packed list of these ids at record
offset `0x020`, highest spell level first. The file format is described
in `goldbox/spells.py`; the short version is that the strings **overlap** —
`CURE LIGHT WOUNDS` and `CAUSE LIGHT WOUNDS` share one copy of
` LIGHT WOUNDS` — so the table has to be read through its pointers.

The ids run cleric level 1, magic-user level 1, cleric level 2, and so
on. Each group is alphabetical, with a reversed spell following the one
it reverses. Every id seen in a real save falls in the group its
caster's class predicts.

## Cleric, level 1  (`1`–`8`)

| id | spell |
|---|---|
| 1 | BLESS |
| 2 | CURSE |
| 3 | CURE LIGHT WOUNDS |
| 4 | CAUSE LIGHT WOUNDS |
| 5 | DETECT MAGIC |
| 6 | PROTECTION FROM EVIL |
| 7 | PROTECTION FROM GOOD |
| 8 | RESIST COLD |

## Magic-user, level 1  (`9`–`21`)

| id | spell |
|---|---|
| 9 | BURNING HANDS |
| 10 | CHARM PERSON |
| 11 | DETECT MAGIC |
| 12 | ENLARGE |
| 13 | REDUCE |
| 14 | FRIENDS |
| 15 | MAGIC MISSILE |
| 16 | PROTECTION FROM EVIL |
| 17 | PROTECTION FROM GOOD |
| 18 | READ MAGIC |
| 19 | SHIELD |
| 20 | SHOCKING GRASP |
| 21 | SLEEP |

## Cleric, level 2  (`22`–`28`)

| id | spell |
|---|---|
| 22 | FIND TRAPS |
| 23 | HOLD PERSON |
| 24 | RESIST FIRE |
| 25 | SILENCE 15' RADIUS |
| 26 | SLOW POISON |
| 27 | SNAKE CHARM |
| 28 | SPIRITUAL HAMMER |

## Magic-user, level 2  (`29`–`35`)

| id | spell |
|---|---|
| 29 | DETECT INVISIBILITY |
| 30 | INVISIBILITY |
| 31 | KNOCK |
| 32 | MIRROR IMAGE |
| 33 | RAY OF ENFEEBLEMENT |
| 34 | STINKING CLOUD |
| 35 | STRENGTH |

## Cleric, level 3  (`36`–`44`)

| id | spell |
|---|---|
| 36 | ANIMATE DEAD |
| 37 | CURE BLINDNESS |
| 38 | CAUSE BLINDNESS |
| 39 | CURE DISEASE |
| 40 | CAUSE DISEASE |
| 41 | DISPEL MAGIC |
| 42 | PRAYER |
| 43 | REMOVE CURSE |
| 44 | BESTOW CURSE |

## Magic-user, level 3  (`45`–`55`)

| id | spell |
|---|---|
| 45 | BLINK |
| 46 | DISPEL MAGIC |
| 47 | FIREBALL |
| 48 | HASTE |
| 49 | HOLD PERSON |
| 50 | INVISIBILITY 10' RADIUS |
| 51 | LIGHTNING BOLT |
| 52 | PROTECTION FROM EVIL 10' RADIUS |
| 53 | PROTECTION FROM GOOD 10' RADIUS |
| 54 | PROTECTION FROM NORMAL MISSILES |
| 55 | SLOW |

## Outside the player's list

`56` is **RESTORATION**, a
cleric spell of far higher level than Pool of Radiance grants a player,
so it is presumably the temple's. Its level is not worth guessing.

From `57` the same table continues with **combat message
fragments** rather than spells — they share the mechanism and not the
meaning. `wish` refuses to write an id above
`56` into a spell list for that reason.

| id | text |
|---|---|
| 57 | IS CHARMED |
| 58 | IS WEAKENED |
| 59 | IS ANIMATED |
| 60 | IS BLINDED |
| 61 | IS DISEASED |
| 62 | IS POISONED |
| 63 | TURNS TO STONE |
| 64 | IS PARALYZED |
| 65 | FALLS ASLEEP |
| 66 | IS TURNED |
| 67 | IS HELD FAST |
| 68 | IS DRAINED |
| 69 | IS UNAFFECTED |
| 70 | IS NAUSEOUS |
| 71 | AGES |
| 72 | IS HIT FOR  |
| 73 | GAINS AN ITEM |
| 74 | IS INVISIBLE |
| 75 | IS CURSED |
| 76 | SUCKS SOME BLOOD |
| 77 | GAZES... |
| 78 | BREATHES... |
| 79 | GETS BACK UP |
| 80 | TURNS INTO GAS |
| 81 | AVOIDS IT |
| 82 | REFLECTS IT |
| 83 | POINTS OF DAMAGE |
| 84 | FROM FIRE |
| 85 | FROM COLD |
| 86 | FROM ELECTRICITY |
| 87 | FROM MAGIC |
| 88 | FROM ACID |
| 89 | IS AFFECTED |
| 90 | IS HEALED |
| 91 | IS CURED |
| 92 | USES AN ITEM |
| 93 | SPITS ACID |
| 94 | IS RESTORED |
| 95 | IS SILENCED |
| 96 | CASTS A SPELL |
| 97 | BEGINS CASTING |
| 98 | ATTACKS |
| 99 | AND MISSES... |
| 100 | AND HITS FOR  |
| 101 | GOES DOWN |
| 102 | AND IS DYING |
| 103 | IS KILLED |
| 104 | SWEEPS |
| 105 | LOST AN IMAGE |
| 106 | IS ENLARGED |
| 107 | IS REDUCED |
| 108 | IS SHIELDED |
| 109 | IS DUPLICATED |
| 110 | IS BLINKING |
| 111 | IS HASTED |
| 112 | IS SLOWED |
| 113 | IS STRONG |
| 114 | RAKES |
| 115 | IS PROTECTED |
| 116 | IS BLESSED |
| 117 | (HELPLESS) |
| 118 | READS |
| 119 | ROTS |
| 120 | SURRENDERS |

