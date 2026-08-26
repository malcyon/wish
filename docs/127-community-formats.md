# The community format spreadsheets

A worker in the Gold Box community has published two workbooks —
`GB_FileFormat.xlsx` and `GB_Extract.xlsx` — documenting the file formats of
all ten Gold Box titles. Donald has them; they are **not** in this repository
and nothing below reproduces them. What follows is the comparison against our
own tables and what the comparison changed.

**Every sheet in both workbooks describes the DOS/PC port. None describes the
Commodore 64.** That is established in §1 and it is the fact that decides how
much of the material is usable. Even so the DOS record turned out to be a
usable *lens* on the C64 one, because the two share a field order for most of
their length.

Source: `GB_FileFormat.xlsx` / `GB_Extract.xlsx`, community-published,
undated, author not named in the files. Cite it as a **third-party document**:
PROBABLE evidence, never CONFIRMED on its own.

---

## What changed our understanding

Six things, in order of value.

### 1. Saving throws are solved

`goldbox/levels.py` says in its own docstring that the saving-throw columns are
"transcribed, not verified, and nothing should assert them against a record
until the modifiers are understood". The modifier is understood.

> **A C64 character's five stored saves are the class table row for its level,
> taking the best number in each column across every class it holds, minus the
> AD&D constitution bonus when the character is a dwarf, gnome or halfling.**

**78 of 79 distinct C64 records** on this machine satisfy that exactly. The one
miss is MAD MAN, a level-8 NPC in `npc_party.d64` whose stored saves are the
level-1 fighter row — a hand-authored or stale record, not a rule.

Provenance matters here, because `npc_party.d64` is the hacked save whose
*values* `docs/90-specimens.md` calls worthless. Take it out and the rule still
stands on clean data: SSI's own shipped demo party in `POOL1`'s `SAVEDGAME0`,
Donald's six-character party, and every save disk. What `npc_party.d64` adds is
the only evidence above level 1 — and that seven of its eight records satisfy a
rule derived without them is itself an argument that its derived fields were
written by the game. `tests/test_communityformats.py` asserts the rule on the
fixtures alone.

The multi-class rule is visible on its own: LADY KATHERINE (magic-user 1 /
thief 1) reads `13 12 11 15 12`, which is neither class's row but the
column-wise minimum of magic-user `14 13 11 15 12` and thief `13 12 14 16 15`.

The constitution bonus is the published AD&D 1e one — `+1` per 3½ points of
constitution — applied only to the three "sturdy" races:

| character | race | CON | adjustment |
|---|---|---|---|
| MAGNUS | dwarf | 13 | −3 |
| HOGARTH | dwarf | 15 | −4 |
| GRON | dwarf | 18 | −5 |
| NYX | gnome | 13 | −3 |
| DAX | halfling | 12 | −3 |

Only the `+3`/`+4`/`+5` bands are exercised; `+1` and `+2` need a character
with constitution below 11. **CONFIRMED** for the mechanism, with those two
bands PROBABLE.

The class table itself is the DOS one, which the spreadsheet's `EXE_Offset`
sheet told us to look for: eight classes × nine levels × five saves. It is not
at the offset the sheet gives (§6) but it is exactly the shape the sheet gives,
and every row matches `goldbox/levels.py`'s transcription.

### 2. `spells_castable` promoted to CONFIRMED

`0x0EE`–`0x0F0`, one byte per spell level, **cleric in the high nibble,
magic-user in the low**. The project had this at PROBABLE on two agreeing
readings. Three new lines settle it:

* **Multi-class specimens set both nibbles at once.** TANARAKIS — cleric 1 /
  magic-user 1, on **SSI's own shipped demo party in `POOL1`'s `SAVEDGAME0`** —
  reads `$31`. No single-class specimen could distinguish the packing from two
  separate bytes and every earlier specimen was single-class. DELILIA (cleric 1
  / fighter 1 / magic-user 1) agrees on one of Donald's save disks.
* **The wisdom bonus is exact at level 6.** DIRTEN, cleric 6, wisdom 16, reads
  `5/5/2` — the AD&D `3/3/2` plus `+2/+2/+0`. SIMON, cleric 6, wisdom 18, reads
  `5/5/3` — plus `+2/+2/+1`. Both of those are `npc_party.d64`, so read them as
  corroboration of a rule the clean specimens already carry rather than as its
  basis. Fifteen casters, one exception (DELILIA, wisdom 13,
  three first-level slots where the rule gives two — consistent with the field
  being a cache that is not recomputed when an ability score changes, which is
  how armour class behaves too).
* **The DOS record carries the same six quantities as six separate bytes** —
  `SPL_Count_CL_1..3`, `SPL_Count_MU_1..3` at DOS `0x0B2`–`0x0B7`, in the
  position the C64's `0x0EE` aligns to. Checked on 66 real DOS records: ROLAND
  reads `[4,3,0,0,0,0]`, GILES `[0,0,0,2,1,0]`, BAKSHI `[3,0,0,1,0,0]`.

`0x0F1`–`0x0F3` (spell levels 4–6) are zero in all 79 C64 records, as expected
for a game that stops at third-level spells.

### 3. The `ITEMS` type table is the same file on both ports

`ITEMS` on a POOL disk and `ITEMS` in the DOS game folder are **126 of 128
16-byte records byte-identical**, and the DOS file even carries the same
`$7600` load address in its first two bytes. So the spreadsheet's `ITM_BAS`
field names apply to our table verbatim, and three of our names improve:

| byte | our name (`docs/85`) | theirs | verdict |
|---|---|---|---|
| `+7` | weapon class | `DamageType` — 0 slashing, 1 piercing, 128 bludgeoning | **theirs**. The C64 table holds exactly `{0, 1, 128}` and nothing else |
| `+8` | melee usable | `Unknown_08`, "set on weapons and quarrels only" | draw. C64 holds only `{0, 128}`, so it is bit 7, not a count |
| `+14` | missile type | `WeaponFlagArray` bitfield | **theirs**, decisively — see below |
| `+6` | protection, `$B0` + `12 − AC` | `10 − (60 − (AC & 127))` | **ours**; theirs is wrong, see below |

`+14` as a bitfield: bit 0 launch-arrow, 1 ranged, 2 strength bonus, 3
multi-fire, 4 thrown, 7 launch-bolt. Every value in the C64 table decodes:
`4` melee, `20` thrown melee (dagger, hand axe, spear), `11` bow, `15`
composite bow — the strength bonus bit set, which is exactly the AD&D rule for
composite bows — `138` crossbow, `26` sling.

**Their armour formula is wrong and our data proves it.** For the nine armour
types (`ITEMS` entries 50–58, leather through plate) `60 − (byte & 0x7F)` gives
8, 8, 7, 7, 6, 5, 4, 4, 3 — the AD&D armour-class list, in order. Their
`10 − (60 − (byte & 0x7F))` gives 2, 2, 3, 3, 4, 5, 6, 6, 7, which is that list
reversed and makes leather better than plate. The correct statement is the
project's, and it is simpler than either: **`60 − (byte & 0x7F)`, the same bias
as THAC0 and armour class everywhere else**, with bit 7 alone (`$80 | n`)
meaning "n is a bonus, not a class".

The two records that *do* differ are both about thrown weapons, and the C64 is
the better of the two: item type 8 (dagger) has rate of fire 2, range 4 and the
thrown flag on the C64 and rate of fire 0, range 1 and no thrown flag on DOS;
item type 9 (dart) is multi-fire ranged on the C64 and thrown-only on DOS. The
spreadsheet notices the DOS dagger independently ("Dagger in 1 … is set to 1 …
doesn't have IsThrown flag set so probably ignored"). **A DOS Pool of Radiance
player cannot throw a dagger and a C64 player can** — that belongs to whoever
owns `docs/125-bug-notes.md`; it is a DOS defect, not ours to log here.

### 4. `AC_Back` — an open question closed on the DOS side

`work/reports/dos-saves.md` §10 asks which of DOS `0x111` / `0x112` is base
armour class and which is current. **Neither.** The spreadsheet names them
`AC_Current` and `AC_Back`, and rear armour class is worse than front in
**66 of 66** DOS records. CONFIRMED, for DOS.

**It does not transfer, and the attempt to make it transfer is worth recording
as a near miss.** The C64 roster's `+0x0F` / `+0x10` pair sits where DOS's
`AC_Current` / `AC_Back` sits, and rear ≥ front holds in 20 of 20 roster
blocks — but that inequality is worthless as evidence, because it is true of
*any* second armour-class-shaped byte once the first includes dexterity and a
shield. `docs/30-savegame-layout.md` already reads `+0x10` as **the armour's
own contribution, `48 + bonus`**, and that reading was measured the right way,
by putting armour on: none 48, leather 50, banded mail 54, which are exactly
the AD&D bonuses 0, 2 and 6. Read as `60 − AC` the same bytes give 12, 10 and 6,
two worse than each armour's real class, which means nothing.

So the two ports differ here: DOS spends the byte on rear armour class, the C64
on the armour bonus. **Our measurement wins and `goldbox/savegame.py` is right.**

### 5. `spells_memorised` is probably 21 bytes, not 16

DOS Pool of Radiance allots **21** memorised-spell slots (`0x017`–`0x02B`, one
byte per memorised instance, an index into the 56-spell list). 21 is also the
C64 ceiling: a cleric 6 with wisdom 18 gets 13 slots and a magic-user 6 gets 8,
and one character can be both. `goldbox/layout.py` declares 16 at `0x020`.

The C64 array packs **forward** from `0x020` in descending spell id, where DOS
fills its 21 in reverse. Verified against `spells_castable` on three
high-level casters, and every id lands in the right class's range:

| character | slots | memorised ids | check |
|---|---|---|---|
| SIMON, cleric 6 | 5/5/3 | 44 42 41 · 25 23 23 23 23 · 3 3 3 3 1 | 3 third-level, 5 second, 5 first — all in the cleric ranges 36–44, 22–28, 1–8 |
| DIRTEN, cleric 6 | 5/5/2 | 43 39 · 23 23 23 23 · 6 6 5 5 1 | 2 third, 4 of 5 second, 5 first |
| XAVIER, magic-user 6 | 4/2/2 | 51 47 · 32 31 · 21 21 15 10 | 2 third, 2 second, 4 first — all in the magic-user ranges 45–55, 29–35, 9–21 |

The declared 16 is not contradicted by anything we hold (the most seen in use
is 13) but it is five short of what the format allows. **PROBABLE.** What would
settle it: a cleric/magic-user with more than sixteen spells memorised.

### 6. The thief per-level table, and where it stops

`EXE_Offset` names a `ThiefSkillPerLevel` table of 9 records × 8 bytes and a
`ThiefSkillModifierRace` of 7 × 8 immediately after it. Both are in the DOS
executable and both check out against the AD&D 1e Players Handbook — the six
racial rows are the published adjustments exactly (dwarf `open locks +10,
find traps +15, climb walls −10, read languages −5`, and so on).

Against the C64 the table is **half confirmed**. HOGARTH — a dwarf thief 1 on
SSI's own shipped demo party, the cleanest specimen in the project — matches
base plus the dwarf racial row in all eight columns, including the signed `−5`
stored as `$FB`. LADY KATHERINE (half-elf), NYX (gnome) and DAX (halfling) do
not, and no dexterity adjustment reconciles them — HOGARTH has dexterity 17 and
takes no adjustment at all.

So: **the C64's thief-skill progression is the DOS one**, and how it applies
racial modifiers is **UNKNOWN**. The C64's own copy of the table, wherever it
lives on the disks, would settle it in one read.

---

## 1. Which sheet describes which port

All of them describe DOS. Three independent reasons:

* the sheets name DOS filenames throughout — `MON1CHA.DAX`, `<NAME>.CHA`,
  `CHRDAT[A-J]#.SAV`, `SAVGAM[A-J].DAT`, `ITEMS.DAT`, `MONST.GLB`;
* `EXE_Offset` gives offsets into "the GOG/WizWorks versions" of each game's
  executable, and its `Versions` row names DOS build numbers;
* the record lengths match the DOS files in `/home/donald/Downloads/fr-archives/`
  exactly and the C64's 580 not at all.

`CHR_01`…`CHR_10` are **ten titles, not ten revisions**. The `Misc` sheet gives
the mapping and the record lengths confirm it independently:

| sheet | title | last offset | size | our measurement (`dos-saves.md` §9) |
|---|---|---|---|---|
| `CHR_01` | Pool of Radiance | 284 | 285 | **285** ✓ |
| `CHR_02` | Curse of the Azure Bonds | 421 | 422 | **422** ✓ |
| `CHR_03` | Secret of the Silver Blades | 438 | 439 | **439** ✓ |
| `CHR_04` | Pools of Darkness | 509 | 510 | **510** ✓ |
| `CHR_05` | Champions of Krynn | 408 | 409 | — |
| `CHR_06` | Death Knights of Krynn | 215 | 216 | — |
| `CHR_07` | The Dark Queen of Krynn | 416 | 417 | — |
| `CHR_08` | Gateway to the Savage Frontier | 421 | 422 | **422** ✓ |
| `CHR_09` | Treasures of the Savage Frontier | 509 | 510 | **510** ✓ |
| `CHR_10` | Unlimited Adventures | 449 | 450 | — |

Six sizes we measured ourselves; six agree. Death Knights is short because it
moves the spell data into separate `.WIZ` files, which the `Misc` sheet says
and the `WIZ_06` sheet documents.

The other sheets: `ITM_BAS` the base-item table (our `ITEMS`), `ITM_DAX` the
per-item record, `SPL` the spell table, `SFX_DAX` the effect record, `VLT` the
vault, `Enum` thirty enumerations, `EXE_Offset` executable offsets,
`CHR_Flags` / `ITM_Properties` / `SFX_Modifier` / `SFX_List` / `SFX_Filter`
lookup tables, `EnumExport` a flattened dump of `Enum`. `GB_Extract.xlsx` is
extracted content — monsters, inventories, items — not format.

Two files in the same download are **out of scope for this repository**:
`GB_CopyProtection.xlsx`, which belongs with the private protection research,
and `GB_UA_SCRIPT.xlsx` / `SCRIPT.GLB`, which are Unlimited Adventures content.

---

## 2. Their DOS table against ours

`work/reports/dos-saves.md` established the DOS Pool of Radiance record from 24
specimens. `CHR_01` covers all 285 bytes. **Every field we claimed, they name at
the same offset. Nothing contradicts.**

| our offset | our name | their name | verdict |
|---|---|---|---|
| `0x000` | name, length-prefixed | `Name_Length` + `Name[15]` | confirm |
| `0x010`–`0x016` | STR INT WIS DEX CON CHA, exceptional STR | `*_Current` | confirm |
| `0x01C`–`0x02B` (GUESS) | spells memorised, 16 | `SPL_Memorized_001..021` at **`0x017`–`0x02B`**, filled in reverse | **theirs**; ours was four bytes short and started too late |
| — | — | `Unknown_02C`, always 0 | add |
| `0x02D` | THAC0 base, `60 −` | `THAC0_Base` | confirm |
| `0x02E` / `0x02F` | race / class | `Race` / `Class` | confirm |
| `0x030` | age, `u16` | `Age`, `u16` | confirm; settles our "PROBABLE as 2 bytes" |
| `0x032` | hit points maximum | `HP_Max` | confirm |
| `0x033`–`0x06A` | spellbook, 56 bytes | `SPL_Known_001..056` | confirm |
| `0x06B` (GUESS) | "hit dice / fighting level" | `LVL_Sweep` | **theirs**, and it names what our C64 `attack_level` is |
| — | — | `ICO_Dimension` at `0x06C` (1 = 1×1) | add; 1 in all 66 DOS records |
| `0x06D`–`0x071` | saving throws | `SAV_1..SAV_5` | confirm |
| — | — | `MOV_Base` at `0x072` | add |
| `0x073` | level | `LVL_Current_PreDrain` | theirs is sharper |
| — | — | `LVL_Drained`, `HP_Drained`, `MON_UndeadLevel` at `0x074`–`0x076` | add — and these are our C64 `0x0A1`/`0x0A2`/`0x0A3` |
| `0x077`–`0x07E` | thief skills | `TH_1..TH_8`, same order | confirm |
| — | — | `ADDR_Effect` `u32` at `0x07F`; `Morale`, `TreasureShare` at `0x084`/`0x085` | add |
| `0x088`–`0x095` | money, 7 × `u16` | `MNY_*` | confirm |
| `0x096`–`0x09D` | per-class levels | `LVL_CL/DR/FT/PD/RA/MU/TH/MK_Current` | confirm, **with the order spelled out** |
| `0x09E` | sex | `GenderID` | confirm |
| — | — | `MON_Type` at `0x09F`, `Alignment` at `0x0A0` | add |
| `0x0A1` | attacks per round, halves | `ATK_1_Count_Base`, first of eight | theirs — see §3 |
| — | — | `AC_Base` at `0x0A9` | add |
| `0x0AC` | experience, `u24` | `XP_Current`, `u32` | theirs; no conflict, our fourth byte was unclaimed |
| `0x0B0` | class bitmask | `ITM_Allowed`, `ClassRestrictionArray` | same bits, better name — it is what the item table checks |
| `0x0B1` | hit points rolled | `HP_Base` | confirm |
| — | — | `SPL_Count_*` `0x0B2`–`0x0B7`, `XP_Award_*` `0x0B8`–`0x0BA`, portraits, icon colours | add |
| `0x0BF` | party order | `Party_Position` | confirm |
| `0x0C0` | size, 1 small 2 medium | `ICO_Size` | confirm |
| `0x0C7` | item count | `ITM_Count` | confirm |
| `0x0C1`–`0x0D7` "heap pointers" | — | `ADDR_Item` + 13 equipment pointers, `0x0C8`–`0x10B` | theirs; our range started seven bytes early |
| `0x102` | encumbrance, `u16` | `ITM_Weight`, `u16` | confirm |
| — | — | `Status`, `IsActive`, `IsHostile`, `IsQuickFight` at `0x10C`–`0x10F` | add; 0, 1, 0, 0 in all 66 records |
| `0x110` | THAC0 current | `THAC0_Current` | confirm |
| `0x111` / `0x112` | "two AC fields, which is which unsettled" | `AC_Current` / `AC_Back` | **theirs**, for DOS — see §4 above |
| — | — | eight `ATK_*_Current` bytes at `0x113`–`0x11A` | add |
| `0x11B` | hit points current | `HP_Current` | confirm |
| — | — | `MOV_Current` at `0x11C` | add |

**Count: 22 fields confirmed, 4 corrected in their favour, 1 corrected in ours
(none in this table — the correction is the item AC formula in §3), about 30
added.**

The thirteen equipment pointers are worth keeping for their *order*, which is
the engine's equipment-slot enumeration and is not port-specific: weapon,
shield, armour, gauntlet, helm, belt, robe, cloak, boot, ring 1, ring 2, arrow,
bolt.

---

## 3. Their DOS table against the C64 record

The DOS record is not the C64's — 285 bytes against 580 — but for most of its
length the two hold the **same fields in the same order**, with the C64 leaving
more room. Anchoring on fields both ports have CONFIRMED gives a piecewise
offset map, and the DOS names then say what the C64's unnamed bytes are.

| C64 | DOS | delta | what it tells us |
|---|---|---|---|
| `0x014` abilities | `0x010` | +4 | the C64 name field is 20 bytes, DOS's 16 |
| `0x071` THAC0 base … `0x078` spellbook | `0x02D` … `0x033` | +`0x44` | |
| `0x098` `attack_level` | `0x06B` `LVL_Sweep` | +`0x2D` | our name is right; theirs says what it is *for* |
| `0x099` `size_small` | `0x06C` `ICO_Dimension` | +`0x2D` | position matches `ICO_Dimension`, meaning matches `ICO_Size` — see below |
| `0x09A`–`0x09E` saves | `0x06D`–`0x071` | +`0x2D` | |
| `0x09F` movement | `0x072` `MOV_Base` | +`0x2D` | |
| `0x0A0`–`0x0A3` level, drain, turn class | `0x073`–`0x076` | +`0x2D` | |
| `0x0A4` `turn_power` | — | — | **the C64 has one field DOS does not**: the cleric's turning level. Everything after shifts by one |
| `0x0A5`–`0x0AC` thief skills | `0x077`–`0x07E` | +`0x2E` | |
| `0x0BB`–`0x0D0` money, per-class levels | `0x088`–`0x09D` | +`0x33` | |
| `0x0D6` sex, `0x0D7` ?, `0x0D8` alignment | `0x09E`, `0x09F` `MON_Type`, `0x0A0` | +`0x38` | **`gap_0d7` is `MON_Type`** — 0 in all 79 C64 records, as a monster type must be for a player |
| `0x0D9`–`0x0E0` `attack_forms` | `0x0A1`–`0x0A8` | +`0x38` | independent corroboration of our reading — see below |
| `0x0E1` `armour_class_base` | `0x0A9` `AC_Base` | +`0x38` | |
| `0x0E6`–`0x0E7` (in `region_0e3`) | `0x0AB` `MON_Index` | — | both are a high-entropy per-character value sitting immediately before experience. DOS uses one byte, the C64 two |
| `0x0ED` `hp_rolled` | `0x0B1` `HP_Base` | +`0x3C` | |
| `0x0EE`–`0x0F0` `spells_castable` | `0x0B2`–`0x0B7` six `SPL_Count_*` | — | the C64 nibble-packs what DOS spends six bytes on |
| `0x0F7`–`0x0F9` (in `gap_0f4`) | `0x0B8`–`0x0BA` `XP_Award_Base` `u16` + `XP_Award_Bonus` | — | **already ours**: `goldbox/monster.py` has these as `XP_BASE` and `XP_PER_HP`, proven from `POST.COM $09BB`. The spreadsheet corroborates and adds nothing. What it does explain is why the five NPC records in `npc_party.d64` carry them and no player character does — an NPC who joins the party gets a record copied from its monster record, award fields included |
| `0x10E`/`0x10F` roster THAC0/AC | `0x110`/`0x111` | −2 | |
| `0x110` roster (`roster_tail[0]`) | `0x112` `AC_Back` | −2 | **the correspondence fails**: the C64 byte is the armour bonus, `48 + bonus`, measured by equipping armour. See §4 |
| `0x111`–`0x118` (`roster_tail[1..8]`) | `0x113`–`0x11A` eight `ATK_*_Current` | −2 | the nine-byte `roster_tail` is rear AC plus the eight current attack bytes |
| `0x119` hp current, `0x11B` movement | `0x11B`, `0x11C` | −2, −1 | the C64's hit points are two bytes where DOS's are one |

**`attack_forms`.** `goldbox/layout.py` reads `0x0D9` as four parallel two-entry
arrays — attacks doubled, dice, die, modifier — proved from `COMBAT $0CAD`'s
stride-2 indexing. The spreadsheet spells the DOS eight bytes out in exactly
that order: `ATK_1_Count_Base`, `ATK_2_Count_Base`, `ATK_1_Rolls_Base`,
`ATK_2_Rolls_Base`, `ATK_1_Dice_Base`, `ATK_2_Dice_Base`, `ATK_1_Modifier_Base`,
`ATK_2_Modifier_Base`. Every C64 player character reads `2 0 1 0 2 0 0 0` — one
attack, 1d2 unarmed. Two independent derivations, same answer.

**`size_small` at `0x099`.** The DOS record has *two* size fields:
`ICO_Dimension` at `0x06C` (1 = 1×1, for monsters that occupy more than one
square) and `ICO_Size` at `0x0C0` (1 small, 2 medium). The C64's `0x099` sits at
`ICO_Dimension`'s offset and carries `ICO_Size`'s meaning, one lower: 0 for
every dwarf, gnome and halfling and 1 for every elf, half-elf and human, in all
79 records. Our note is already better than theirs; no change.

### The per-class level array: they contradict us, and we win

Their DOS array at `0x096` is indexed by the **class number** — cleric 0, druid
1, fighter 2, paladin 3, ranger 4, magic-user 5, thief 6, monk 7. The C64's
array at `0x0C9` is not. Six specimens settle it, each with the class byte to
say what they are:

| character | class byte | meaning | non-zero slot |
|---|---|---|---|
| MALCYON | 5 | magic-user | 0 |
| ROLAND | 0 | cleric | 1 |
| LADY KATHERINE | 16 | magic-user/thief | 0 and 2 |
| BRUTUS | 2 | fighter | 3 |

**The C64 array is indexed by the `class_bits` bit number** — magic-user 0,
cleric 1, thief 2, fighter 3 — not by the class enum. `goldbox/layout.py` already
says so and is right; the spreadsheet's order is a DOS fact only.

One thing does transfer. The spreadsheet's `ClassRestrictionArray` names all
eight bits: 0 magic-user, 1 cleric, 2 thief, 3 fighter, **4 druid, 5 monk,
6 paladin, 7 ranger**. Slots 6 and 7 are our CONFIRMED `level_paladin` and
`level_ranger`, which is a strong check on the whole scheme, and it makes slot
4 **druid** rather than the `level_knight` the Death Knights editor calls it —
Krynn's knights presumably reuse the druid slot in a world with no druids.
The note in `goldbox/layout.py` now records both readings.

### `0x100` — the STATUS question is not settled

The spreadsheet has a `CharacterStatus` enum: 0 Okay, 1 Animated, 2 tempgone,
3 Running, 4 Unconscious, 5 Dying, 6 Dead, 7 Stoned, 8 Gone. It places it at
DOS `0x10C`, which under the roster alignment above is C64 `0x10A`, **not**
`0x100`. Its numbering is 0-based and does not match the 1-based cycle the
three "sir" editors use.

So a fourth, genuinely independent source **weakens** rather than strengthens
the case for `0x100` being STATUS. `roster_in_use` stays PROBABLE and keeps its
name. What would settle it: one C64 specimen where `0x100` reads other than 1.

---

## 4. What they add that we do not have at all

Recorded here as leads, at the confidence a third-party document earns.

| what | where | value | confidence |
|---|---|---|---|
| **256 effect names** indexed by effect id | `Enum` → `EffectName` | our `work/reports/effects.md` names about 30; theirs names about 130, and the twenty ids we both hold agree exactly (1 blessed, 2 cursed, 4 manual, 8/9 protection from evil/good, 10 resist cold, 11 charmed, 12 enlarged, 13 reduced, 14 friends, 16 read magic, 17 shield, 19 find traps, 20 resist fire, 21 silenced, 22 slow poison, 23 spiritual hammer). **The effect id space is shared between the ports.** | PROBABLE, and each name promotable one at a time |
| **effect Modifier byte semantics** | `SFX_Modifier` | the byte usually holds the caster's level, `255` means permanent, and named exceptions pack two things into nibbles: Mirror Image is caster level in bits 0–4 and images remaining in 5–7; Haste and Prayer put the caster level in the low nibble and a flag above it | PROBABLE |
| **item `Property1`/`2`/`3` semantics** | `ITM_Properties` | a dispatch on `Property1`: 128 equipment with an effect id in `Property2`, scrolls with spell ids in all three, and about fifteen special cases keyed by value | PROBABLE |
| **the spell record**, 16 bytes | `SPL` | class, level, range base and per-level modifier, duration base and modifier, combat area, camp target, save action, save type, effect id, camp/combat type, casting time, AI priority, target-enemy flag, AI minimum targets. **Pool of Radiance has 67 of them.** We have spell *names* and ids; we have none of this | PROBABLE |
| **the effect record**, 9 bytes | `SFX_DAX` | effect id, `u16` rounds remaining (0 = permanent), modifier, is-item-effect flag, `u32` next-effect pointer. Our C64 effect list is inline in the record at `0x0AD`, so only the first five bytes can transfer | PROBABLE |
| **the executable tables that exist** | `EXE_Offset` | 43 named tables per title — class ability minima, alignment restrictions, saves per level, hit dice, THAC0 per level, XP per level, spell slots per level, race ability limits, race/class permission, thief skills, turn-undead levels, the string tables | the *shapes* are CONFIRMED where checked; the offsets are not — see below |
| **per-title spell counts** | `CHR_0n` | Pool of Radiance 56, Curse 100, Silver Blades 117, Champions 107, Pools of Darkness 126 | see below |
| the `CharacterFlagArray` | `CHR_Flags` | a 16-bit creature-flag word present from Curse onwards and absent from Pool of Radiance: vulnerable to dispel, giant, dragon, reptile, immune to death magic / poison / decapitation / confusion, and the to-hit bonuses dwarves and gnomes get against particular monsters | PROBABLE |

**`EXE_Offset` is a map, not an address book.** Its offsets are into the
GOG/WizWorks builds; Donald's Steam archives carry different builds and none of
the offsets land. But the *shape* it gives — name, record count, record length —
is enough to find each table by content in one search, and two found that way
checked out perfectly (§1, §6). Treat the sheet as "these tables exist, in this
shape, in this file" and find them yourself. That is still the most valuable
thing in the workbook after `CHR_01`.

**The spell counts answer the `spells_known` width question.** `goldbox/layout.py`
declares seven bytes at `0x078` and notes that Silver Blades and Death Knights
casters write past it. Seven bytes is 56 bits and Pool of Radiance has exactly
56 spells — no C64 record in our corpus of 79 sets any of `0x07F`–`0x097`. If
each title's C64 spell list matches its DOS one, the mask needs ⌈N/8⌉ bytes:
**Curse 13, Champions 14, Silver Blades 15, Pools of Darkness 16**. That
predicts the observed "at least eight" and says how much more. It is a
prediction, not a measurement: the C64 ports may cut spells. **PROBABLE**, and
one Curse caster's spellbook read against `COMBAT2`'s spell-name table would
settle it.

---

## 5. Where they are wrong

Two places, both caught by our own data.

1. **The item armour formula** (§3 above). `10 − (60 − (AC & 127))` inverts the
   armour-class list. It should be `60 − (AC & 127)`. Since the `ITEMS` file is
   byte-identical between the two ports, the correction applies to their DOS
   documentation as much as to ours.
2. **`ThiefSkillModifierRace` count.** The sheet says 7 records of 8 bytes; only
   six are table (dwarf, elf, gnome, half-elf, halfling, half-orc, all matching
   the Players Handbook exactly). The seventh reads as code. Human, whose
   adjustments are all zero, is presumably implicit.

One place where they disagree with us and the answer is "different ports":
their DOS `0x0AA` is `STR_Bonus`, a boolean, and it reads 1 in all 66 DOS
records. The C64's `0x0E2` at the aligned offset is `strength_index` and holds
15–22 — the exceptional-strength bands collapsed to one number. Two different
fields; our name stands.

---

## 6. What this cost and what it is worth

The workbook confirmed 22 DOS fields, corrected 4 of ours, was corrected by us
in 3 places, and added roughly 30 DOS fields plus five whole record formats we
had never seen. On the **C64** side its direct value is smaller — it names no
C64 offset — but used as a lens it named `gap_0d7`, corroborated `attack_forms`
and `armour_class_base`, said what the eight bytes after `roster_tail[0]` are,
and pointed at the two executable tables that closed the saving-throw question
and half of the thief-skill one.

It also produced one near miss worth remembering. The DOS record's `AC_Back`
lines up with a C64 roster byte the project reads as an armour bonus, the
alignment is exact, and the "rear is worse than front" prediction holds in
every block — and it is still wrong, because the prediction is true of any
second armour-shaped byte and the project's reading was measured by putting
armour on. **An alignment is a hypothesis and a measurement is evidence**, and
a document that agrees with an alignment has not turned it into one.

The single most valuable thing in it is `EXE_Offset`: not the offsets, which
are wrong for our builds, but the **list of tables the engine carries and the
shape of each**. Every one of them is findable by content search in seconds
once you know what you are looking for, and two of them settled questions this
project had left open for months.

## What is still open

| question | what would settle it |
|---|---|
| how the C64 applies racial modifiers to thief skills | find the C64's own `ThiefSkillModifier*` tables on the POOL disks |
| whether `spells_memorised` is 21 bytes | a cleric/magic-user with more than sixteen spells memorised |
| the C64 spell counts for Curse, and hence the `spells_known` width | read a Curse caster's spellbook against `COMBAT2`'s name table |
| whether `0x100` is a STATUS enum | one specimen reading other than 1 |
| the constitution save bonus below CON 11 | a character with constitution under 11 of a sturdy race |
