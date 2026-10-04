# Spell table

**Generated** — run `python3 tools/generate/genspells.py`. Read straight off a
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
so it is presumably the temple's. Its level is left unguessed.

From `57` the same table continues with **combat message
fragments** rather than spells — they share the mechanism and not the
meaning. `wish` will not write an id above
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

## Where each port keeps the names

`goldbox/spell_names.py` reads all of them at run time:
`spell_names(title, "c64" | "dos" | "amiga", where)`. Every table is found
from the instruction that indexes it, never from a stored address; the
addresses below are what that search finds on the builds here, for checking.

**The id is the table index on every port.** Each table's slot 0 is the id-0
slot no spell uses, so no DOS or Amiga build numbers a spell differently from
the C64: id for id, after dropping case and punctuation, the DOS names match
the C64's on all 56 Pool of Radiance spells, all but 2 of Curse's and all but
5 of Silver Blades', and the Amiga's match DOS on every spell of Pool of
Radiance and Curse. The exceptions are wording, and
`tests/records/test_spell_names.py` lists each id.

| title | DOS (`DS` offset, stride) | Amiga |
|---|---|---|
| Pool of Radiance | `START.EXE` `DS:28E9`, 41 (`String[40]`) | `/program` hunk 31 `+0x27CB`, `char[41]` cells |
| Curse of the Azure Bonds | `START.EXE` `DS:27BF`, 41 | `/Curse` small data `0x1D5A` (`-$62A4(a4)`), a pointer an id |
| Secret of the Silver Blades | `START.EXE` `DS:348B`, 35 (`String[34]`) | `/Secret` small data `0x253C` (`-$5AC2(a4)`) |
| Pools of Darkness | `GAME.EXE` `DS:53CD`, 35 | `/Pools of Darkness` small data `0x250A` (`-$5AF4(a4)`) |

* **DOS.** The launcher is EXEPACK-packed (`goldbox/exepack.py` expands it);
  `DS` comes from the entry's far call into `System`'s initialiser
  (`0C7C`, `0ABE`, `0DE2`, `09E7`). `GAME.OVR` indexes the table as
  `mov dx, stride / mul dx / mov di, ax / add di, base` at five or six sites
  per title. Each slot is a Pascal string, zero-padded. The slots run from
  id 1 to exactly the last spell (56, 100, 117, 126) and the next slot is the
  start of the class-and-level table, which is how the names are told from
  the other tables indexed the same way.
* **Amiga Pool of Radiance** multiplies the id by 41 (`moveq #$29, d1` and a
  library multiply) and adds a relocated `lea $27cb.l, a0`; the `Spell:` line
  at `/program` `0x3982A` is one reader.
* **Amiga Curse, Silver Blades and Pools of Darkness** index a pointer array
  in the small-data hunk: the id shifted left twice (`asl.l`), then `lea d16(a4), a0 /
  move.l (a0, d0.l), -(a7)`, read by the `Spell:%s` and `%s%s` lines
  (`/Secret` `0x37BAC`, `/Pools of Darkness` `0x3479A`). Pools of Darkness'
  pointers run on past id 126 into eleven item names; the reader stops at 126.

What a non-spell id holds differs by port: empty in DOS and Amiga Curse,
`spell N` in DOS Silver Blades, an item that casts the spell in DOS Pools of
Darkness (57 `Potion Of Speed`), and the engine's own internal name on Amiga
Silver Blades, which also names its spells that way (`CLERIC DETECT MAGIC`,
`SHIELD SPELL`, `PROT NORM MISSILES`). **Silver Blades' id 109 is not a
named spell on either later port**: DOS calls it `spell 109` and the Amiga
`RESERVED`, where the C64 repeats `DEATH SPELL` -- the same id Pools of
Darkness' engine makes a druid spell.

**One Amiga build is not read:** the `[a]` release of Pools of Darkness disk 1
carries `/Pools of Darkness` crunched with StoneCracker 4.04 (`S404` at file
offset 512, a 76-byte stub hunk), and the loader raises `SpellNameError`
saying so. The other Pools of Darkness disk-1 images here hold three
uncrunched programs that differ by hash, and all three read the same names.

