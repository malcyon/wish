# Item tables

**Generated** — run `python3 tools/genitems.py` after changing
`por/items.py`. Both tables are read directly off a game disk, so the
spellings are the game's own.

An item record does not store a name. It stores three indices into the
**word table** below, at its bytes `+1`, `+2` and `+3`, and the game
prints them in the **opposite** order: `+3` is the noun, `+2` the
qualifier, `+1` the suffix, so `CLOAK` + `OF` + `DISPLACEMENT` and
`BANDED` + `MAIL` + `+1` are stored back to front. It also stores an
index into the **type table**, which is where damage, armour protection
and class restrictions come from.

## The word table (`ITEMNAMES`)

252 words, out of a 256-entry pointer table whose index 0 is
unused. Indices are **1-based** — the value an item record stores is the
key here, with no adjustment.

Indices 62, 63, 168 carry no name. They are real gaps in the pointer
table, not empty strings, and reading the file by splitting strings in
order instead of following its pointers closes them and shifts every
later name onto a wrong — but plausible — value.

| # | word | # | word | # | word | # | word |
|---|---|---|---|---|---|---|---|
| 1 | BATTLE AXE | 66 | RING | 129 | ROPE | 193 | FEAR |
| 2 | HAND AXE | 67 | ROD | 130 | RUG | 194 | DISAPPEARANCE |
| 3 | BARDICHE | 68 | STAVE | 131 | SAW | 195 | STATUETTE |
| 4 | BEC DE CORBIN | 69 | WAND | 132 | SCARAB | 196 | FUNGUS |
| 5 | BILL-GUISARME | 70 | JUG | 133 | SPADE | 197 | CHAIN(S) |
| 6 | BO STICK | 71 | AMULET | 134 | SPHERE | 198 | PENDANT |
| 7 | CLUB | 72 | APPARATUS | 135 | STONE | 199 | BROACH |
| 8 | DAGGER | 73 | BAG | 136 | TALISMAN | 200 | OF SEEKING |
| 9 | DART | 74 | BEAKER | 137 | TOME | 201 | -1 |
| 10 | FAUCHARD | 75 | BOAT | 138 | TRIDENT | 202 | -2 |
| 11 | FAUCHARD-FORK | 76 | BOOK | 139 | GRIMOIRE | 203 | -3 |
| 12 | FLAIL | 77 | BOOTS | 140 | WELL | 204 | LIGHTNING BOLT |
| 13 | MILITARY FORK | 78 | BOWL | 141 | WINGS | 205 | FIRE RESISTANCE |
| 14 | GLAIVE | 79 | BRACERS | 142 | VIAL | 206 | MAGIC MISSILES |
| 15 | GLAIVE-GUISARME | 80 | BRAZIER | 143 | LANTERN | 207 | SAVE |
| 16 | GUISARME | 81 | BROOCH | 144 | MIRROR | 208 | CLERICAL SCROLL |
| 17 | GUISARME-VOULGE | 82 | BROOM | 145 | FLASK OF OIL | 209 | MU SCROLL |
| 18 | HALBERD | 83 | PURSE | 146 | 10' POLE | 210 | WITH 1 SPELL |
| 19 | LUCERN HAMMER | 84 | CANDLE | 147 | 50' ROPE | 211 | WITH 2 SPELLS |
| 20 | HAMMER | 85 | CARPET | 148 | IRON | 212 | WITH 3 SPELLS |
| 21 | JAVELIN | 86 | CENSER | 149 | THIEVES' PICKS & TOOLS | 213 | PROTECTION SCROLL |
| 22 | JO STICK | 87 | CHIME | 150 | IRON RATIONS | 214 | JEWELRY |
| 23 | MACE | 88 | CLOAK | 151 | STANDARD RATIONS | 215 | FINE |
| 24 | MORNING STAR | 89 | CRYSTAL | 152 | HOLY SYMBOL | 216 | HUGE |
| 25 | PARTISAN | 90 | CUBE | 153 | VIAL OF HOLY WATER | 217 | BONE |
| 26 | MILITARY PICK | 91 | CUBIC | 154 | VIAL OF UNHOLY WATER | 218 | BRASS |
| 27 | AWL PIKE | 92 | FORTRESS | 155 | BARDING | 219 | KEY |
| 28 | QUARREL(S) | 93 | DECANTER | 156 | DRAGON | 220 | AC2 |
| 29 | RANSEUR | 94 | DECK | 157 | LIGHTNING | 221 | AC6 |
| 30 | SCIMITAR | 95 | DRUMS | 158 | SADDLE | 222 | AC4 |
| 31 | SPEAR | 96 | DUST | 159 | SMALL RAFT | 223 | AC3 |
| 32 | SPETUM | 97 | EYES | 160 | CART | 224 | OF PROTECTION |
| 33 | QUARTER STAFF | 98 | FIGURINE | 161 | WAGON | 225 | PARALYZATION |
| 34 | BASTARD SWORD | 99 | FLASK | 162 | +1 | 226 | OGRE POWER |
| 35 | BROAD SWORD | 100 | GAUNTLETS | 163 | +2 | 227 | INVISIBILITY |
| 36 | LONG SWORD | 101 | GEM | 164 | +3 | 228 | MISSILES |
| 37 | SHORT SWORD | 102 | GIRDLE | 165 | +4 | 229 | ELVENKIND |
| 38 | TWO-HANDED SWORD | 103 | HELM | 166 | +5 | 230 | ROTTING |
| 39 | TRIDENT | 104 | HORN | 167 | OF | 231 | COVERED |
| 40 | VOULGE | 105 | HORSESHOES | 169 | CLOAK | 232 | EFREETI |
| 41 | COMPOSITE LONG BOW | 106 | INCENSE | 170 | DISPLACEMENT | 233 | BOTTLE |
| 42 | COMPOSITE SHORT BOW | 107 | STONE | 171 | TORCH(ES) | 234 | MISSILE ATTRACTOR |
| 43 | LONG BOW | 108 | INSTRUMENT | 172 | OIL | 235 | OF MAGLUBIYET |
| 44 | SHORT BOW | 109 | JAVELIN | 173 | SPEED | 236 | SECR DOOR & TRAP DET |
| 45 | HEAVY CROSSBOW | 110 | JEWEL | 174 | TAPESTRY | 237 | GOOD DRAGON CONTROL |
| 46 | LIGHT CROSSBOW | 111 | OINTMENT | 175 | BODILY HEALTH | 238 | FEATHER FALLING |
| 47 | SLING | 112 | LIBRAM | 176 | COPPER | 239 | GIANT STRENGTH |
| 48 | MAIL | 113 | LYRE | 177 | SILVER | 240 | RESTORATION |
| 49 | ARMOR | 114 | MANUAL | 178 | ELECTRUM | 241 | ,FLAMETONGUE |
| 50 | LEATHER | 115 | MATTOCK | 179 | GOLD | 242 | FIREBALLS |
| 51 | PADDED | 116 | MAUL | 180 | PLATINUM | 243 | SPIRITUAL |
| 52 | STUDDED | 117 | MEDALLION | 181 | OINTMENT | 244 | BOULDER |
| 53 | RING | 118 | MIRROR | 182 | KEOGHTUM'S | 245 | DIAMOND |
| 54 | SCALE | 119 | NECKLACE | 183 | SHEET(S) | 246 | EMERALD |
| 55 | CHAIN | 120 | NET | 184 | STRENGTH | 247 | OPAL |
| 56 | SPLINT | 121 | PIGMENT | 185 | HEALING | 248 | SAPHIRE |
| 57 | BANDED | 122 | PEARL | 186 | HOLDING | 249 | OF TYR |
| 58 | PLATE | 123 | PERIAPT | 187 | EXTRA | 250 | OF TEMPUS |
| 59 | SHIELD | 124 | PHYLACTERY | 188 | GASEOUS FORM | 251 | OF SUNE |
| 60 | WOOD | 125 | PIPES | 189 | SLIPPERINESS | 252 | WOODEN |
| 61 | ARROW(S) | 126 | HOLE | 190 | JEWELLED | 253 | +3 VS UNDEAD |
| 64 | POTION | 127 | TOKEN | 191 | FLYING | 254 | PASS |
| 65 | SCROLL | 128 | ROBE | 192 | TREASURE FINDING | 255 | CURSED |

## The type table (`ITEMS`)

128 records of 16 bytes, loading at `$7B00` — not the `$7600` its PRG
header claims, which is the address `docs/125-bug-notes.md` R51 and
`docs/127-community-formats.md` are talking about. An item record's byte
`+0` indexes this table. Records that are 16 zero bytes are left out;
nothing here checks whether anything refers to the rest.

Layout, in the order the fields appear:

| Byte | Field |
|---|---|
| `+0` | location / slot the item occupies |
| `+1` | hands required |
| `+2`–`+4` | damage vs large: dice, sides, bonus |
| `+5` | rate of fire |
| `+6` | protection — see below |
| `+7` | damage type: `0` slashing, `1` piercing, `128` bludgeoning |
| `+8` | unknown; `0` or `128`, set on weapons and quarrels only |
| `+9`–`+11` | damage vs medium: dice, sides, bonus |
| `+12` | range |
| `+13` | class usage bitmask, same bits as `class_bits` |
| `+14` | weapon flags — see below |
| `+15` | zero throughout |

**Protection** (`+6`) is `0` for anything that does not affect armour
class. Bit 7 means it does, and the low **seven** bits carry the
family's `60 - value` bias: `60 - (byte & 0x7F)`, the same encoding
THAC0 and armour class use. Body armour stores a class that way (`$B9`
→ AC 3, plate; `$B4` → AC 8, leather); a shield and the magical
protective items store a small flat bonus instead (`$81` = +1), and the
two are told apart by magnitude. Reading this as `$B0` plus a `12 - AC`
nibble is the same arithmetic over a narrower range and agrees on every
armour the disks carry; the two diverge at AC 13, where `$AF` is 13
under the general rule and -3 under the nibble one.

**Weapon flags** (`+14`) are a bitfield, not a missile type: bit 0
needs arrows, bit 1 ranged, bit 2 adds the strength bonus, bit 3
multi-shot, bit 4 throwable, bit 7 needs bolts. `4` is a plain melee
weapon, `20` a thrown one, `11` a bow, `15` a composite bow, `138` a
crossbow, `26` a sling.

| # | vs large | vs medium | AC | damage type | flags | hands | rate | range | usable by |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 1d6 | 1d6 | — | slashing | arrows | 1 | — | — | fighter |
| 1 | 1d8 | 1d8 | — | piercing | strength | 1 | — | — | fighter |
| 2 | 1d4 | 1d6 | — | slashing | strength, thrown | 1 | 2 | 4 | fighter |
| 3 | 3d4 | 2d4 | — | slashing | strength | 2 | — | — | fighter |
| 4 | 1d6 | 1d8 | — | slashing | strength, thrown | 2 | — | — | fighter |
| 5 | 1d10 | 2d4 | — | slashing | arrows | 2 | — | — | fighter |
| 6 | 1d3 | 1d6 | — | bludgeoning | strength | 1 | — | — | fighter |
| 7 | 1d3 | 1d6 | — | bludgeoning | strength, thrown | 1 | 2 | 4 | cleric, thief, fighter |
| 8 | 1d3 | 1d4 | — | piercing | strength, thrown | 1 | 2 | 4 | magic-user, thief, fighter |
| 9 | 1d2 | 1d3 | — | piercing | ranged, multi-shot, thrown | 1 | 6 | 6 | magic-user, thief, fighter |
| 10 | 1d8 | 1d6 | — | slashing | strength | 2 | — | — | fighter |
| 11 | 1d10 | 1d8 | — | slashing | strength | 2 | — | — | fighter |
| 12 | 2d4 | 1d6+1 | — | bludgeoning | strength | 1 | — | — | cleric, fighter |
| 13 | 2d4 | 1d8 | — | slashing | strength | 2 | — | — | fighter |
| 14 | 1d10 | 1d6 | — | slashing | strength | 2 | — | — | fighter |
| 15 | 2d6 | 2d4 | — | slashing | strength | 2 | — | — | fighter |
| 16 | 1d8 | 2d4 | — | slashing | strength | 2 | — | — | fighter |
| 17 | 2d4 | 2d4 | — | slashing | — | 2 | — | — | fighter |
| 18 | 2d6 | 1d10 | — | slashing | strength | 2 | — | — | fighter |
| 19 | 1d6 | 2d4 | — | piercing | strength | 2 | — | — | fighter |
| 20 | 1d4 | 1d4+1 | — | bludgeoning | strength, thrown | 1 | 2 | 4 | cleric, fighter |
| 21 | 1d6 | 1d6 | — | piercing | ranged, multi-shot, thrown | 1 | 2 | 7 | fighter |
| 22 | 1d4 | 1d6 | — | bludgeoning | strength | 1 | — | — | fighter |
| 23 | 1d6 | 1d6+1 | — | bludgeoning | strength | 1 | — | — | cleric, fighter |
| 24 | 1d6+1 | 2d4 | — | bludgeoning | strength | 1 | — | — | fighter |
| 25 | 1d6+1 | 1d6 | — | slashing | strength | 2 | — | — | fighter |
| 26 | 2d4 | 1d6+1 | — | piercing | strength | 1 | — | — | fighter |
| 27 | 1d12 | 1d6 | — | piercing | strength | 2 | — | — | fighter |
| 28 | 1d4 | 1d4 | — | piercing | ranged, multi-shot, bolts | — | — | — | fighter |
| 29 | 2d4 | 2d4 | — | slashing | strength | 2 | — | — | fighter |
| 30 | 1d8 | 1d8 | — | slashing | strength | 1 | — | — | fighter |
| 31 | 1d8 | 1d6 | — | piercing | strength, thrown | 2 | 2 | 4 | fighter |
| 32 | 2d6 | 1d6+1 | — | slashing | strength | 2 | — | — | fighter |
| 33 | 1d6 | 1d6 | — | bludgeoning | strength | 2 | — | — | magic-user, cleric, fighter |
| 34 | 2d8 | 2d4 | — | slashing | strength | 2 | — | — | fighter |
| 35 | 1d6+1 | 2d4 | — | slashing | strength | 1 | — | — | thief, fighter |
| 36 | 1d12 | 1d8 | — | slashing | strength | 1 | — | — | thief, fighter |
| 37 | 1d8 | 1d6 | — | slashing | strength | 1 | — | — | thief, fighter |
| 38 | 3d6 | 1d10 | — | slashing | strength | 2 | — | — | fighter |
| 39 | 3d4 | 1d6+1 | — | slashing | strength | 1 | — | — | fighter |
| 40 | 2d4 | 2d4 | — | slashing | strength | 2 | — | — | fighter |
| 41 | 1d6 | 1d6 | — | piercing | arrows, ranged, multi-shot | 2 | 4 | 22 | fighter |
| 42 | 1d6 | 1d6 | — | piercing | arrows, ranged, multi-shot | 2 | 4 | 19 | fighter |
| 43 | 1d6 | 1d6 | — | piercing | arrows, ranged, multi-shot | 2 | 4 | 22 | fighter |
| 44 | 1d6 | 1d6 | — | piercing | arrows, ranged, multi-shot | 2 | 4 | 16 | fighter |
| 45 | 1d6 | 1d6 | — | piercing | arrows, ranged, strength, multi-shot | 2 | 4 | 20 | fighter |
| 46 | 1d4 | 1d4 | — | piercing | ranged, multi-shot, bolts | 2 | 2 | 19 | fighter |
| 47 | 1d6+1 | 1d4+1 | — | bludgeoning | ranged, multi-shot | 1 | 2 | 21 | thief, fighter |
| 50 | — | — | 8 | — | — | — | — | — | cleric, thief, fighter |
| 51 | — | — | 8 | — | — | — | — | — | cleric, fighter |
| 52 | — | — | 7 | — | — | — | — | — | cleric, fighter |
| 53 | — | — | 7 | — | — | — | — | — | cleric, fighter |
| 54 | — | — | 6 | — | — | — | — | — | cleric, fighter |
| 55 | — | — | 5 | — | — | — | — | — | cleric, fighter |
| 56 | — | — | 4 | — | — | — | — | — | cleric, fighter |
| 57 | — | — | 4 | — | — | — | — | — | cleric, fighter |
| 58 | — | — | 3 | — | — | — | — | — | cleric, fighter |
| 59 | — | — | +1 | — | — | 1 | — | — | cleric, fighter |
| 60 | — | — | — | — | — | 2 | — | — | magic-user, cleric, thief, fighter |
| 61 | — | — | — | — | — | 2 | — | — | magic-user |
| 62 | — | — | — | — | — | 2 | — | — | cleric |
| 63 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 64 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 65 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 66 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 67 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 68 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 69 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 70 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 71 | — | — | — | — | — | 1 | — | — | magic-user, cleric, thief, fighter |
| 72 | — | — | — | — | — | 2 | — | — | magic-user, cleric, thief, fighter |
| 73 | 1d6 | 1d6 | — | slashing | — | — | — | — | fighter |
| 74 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 75 | — | — | — | — | — | 1 | — | — | magic-user, cleric, thief, fighter |
| 76 | — | — | +0 | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 77 | — | — | 10 | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 78 | — | — | — | — | — | 1 | — | 90 | magic-user |
| 79 | — | — | — | — | — | 1 | — | — | magic-user, cleric, thief, fighter |
| 80 | — | — | — | — | — | 1 | — | — | magic-user, cleric, thief, fighter |
| 81 | — | — | — | — | — | 1 | — | — | magic-user, cleric, thief, fighter |
| 82 | — | — | — | — | — | 2 | — | — | magic-user, cleric, thief, fighter |
| 83 | — | — | — | — | — | 1 | — | — | — |
| 84 | — | — | — | — | — | 1 | — | — | fighter |
| 85 | 1d1+255 | 1d1+255 | — | slashing | ranged, multi-shot, thrown | 1 | 2 | 4 | magic-user, cleric, thief, fighter |
| 86 | 2d6 | 2d6 | — | slashing | ranged, multi-shot, thrown | 1 | 2 | 4 | magic-user, cleric, thief, fighter |
| 87 | 1d8+8 | 1d8+8 | — | bludgeoning | ranged, multi-shot, thrown | 2 | 2 | 10 | fighter |
| 88 | 1d12+8 | 1d12+8 | — | bludgeoning | ranged, multi-shot, thrown | 2 | 2 | 20 | — |
| 89 | 3d6 | 1d10 | — | slashing | strength | 2 | — | — | fighter |
| 90 | — | — | — | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 91 | — | — | 0 | — | — | — | — | — | — |
| 92 | — | — | +0 | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 93 | — | — | +0 | — | — | — | — | — | magic-user, cleric, thief, fighter |
| 94 | 1d6 | 1d6 | — | piercing | arrows, ranged, strength, multi-shot | 2 | 4 | 22 | fighter |
| 95 | 1d6 | 1d6 | — | piercing | arrows, ranged, strength, multi-shot | 2 | 4 | 22 | fighter |
| 96 | 1d6 | 1d6 | — | piercing | arrows, ranged, strength, multi-shot | 2 | 4 | 16 | fighter |
| 127 | 2d20 | 2d20 | 6 | piercing | ranged, multi-shot | 1 | 40 | 60 | magic-user, cleric, thief, fighter |

