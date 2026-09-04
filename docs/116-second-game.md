# Curse of the Azure Bonds — how much of it is the same game

**Status: researched, and now supported.** `goldbox/games.py` carries Curse's save
file name, load address, geometry, race table, class bits and item-name base, so
`wish` opens a Curse save disk, decodes its party and round-trips it
byte-identically. What is *not* built is anything needing a running Curse — the
live addresses, an automapper, an edit confirmed in game. Those are
[`120-curse-testing.md`](120-curse-testing.md).

The question was whether Curse of the Azure Bonds (C64) uses a different
character record from Pool of Radiance. It does not.

**Pool of Radiance's own exported character, imported into Curse and exported
again, comes back with 15 of its 580 bytes changed.** Everything else — name,
abilities, race, age, hit points, spellbook, saving throws, level, experience,
per-class levels, class bitmask, alignment, the 36-byte combat icon — survives
byte for byte at the same offsets. The record is 580 bytes in both games.

That is the strongest statement this project can make about the two formats,
because it is the game's own arithmetic rather than a diff of two specimens.

---

## 1. What is the same

| | Pool of Radiance | Curse of the Azure Bonds | Confidence |
|---|---|---|---|
| character record size | 580 bytes | 580 bytes | CONFIRMED |
| every named field in `goldbox/layout.py` | — | same offset, same width | CONFIRMED |
| save slot | first 256 bytes of the record | first 256 bytes of the record | CONFIRMED |
| roster block | record `0x100`–`0x11F` | record `0x100`–`0x11F`, byte-identical structure | CONFIRMED |
| `60 - value` encoding for THAC0, AC, damage | yes | yes | CONFIRMED |
| disk container | D64 | D64 | CONFIRMED |
| map files | `GEO`, 1024 bytes, four 16×16 planes | identical | CONFIRMED |
| item word table | `ITEMNAMES`, 256 low + 256 high + strings | identical shape | CONFIRMED |
| item type table | `ITEMS`, 128 × 16 | identical shape | CONFIRMED |
| spell ids 1–56 | as `goldbox/spells.py` has them | identical | CONFIRMED (research) |

`goldbox/geo.py` decodes all sixteen Curse `GEO` files with no change at all.
Reciprocity — the fraction of wall edges that agree from both sides, which
collapses if a plane is misassigned — is **15114/15360 (98.4%)** across Curse's
sixteen, against **28540/28800 (99.1%)** across Pool of Radiance's thirty. Same
distribution, same decoder.

`goldbox.record.CharacterRecord` parses a Curse export and round-trips it
byte-identically today, with no code change.

## 2. What differs

### 2.1 Constants

| Where | Pool of Radiance | Curse |
|---|---|---|
| exported character, load address | `$6B00` | `$7C00` |
| exported character, filename marker byte | `$01` | `$02` |
| save image, load address | `$4900` | `$4B00` |
| `ITEMNAMES` resident base | `$6F00` | `$9E00` |
| `LIBRARY` resident base | `$2C48` | `$2DC8` |
| `LIBRARY` `GEO` stem table | `$24B4` | `$2714` |
| `GEN` resident base | `$0800` | `$0800` |
| class-level ceiling table | `$1E5C` | `$15A1` |
| racial class-limit table | `$1E60`, 4 wide | `$15A9`, 8 wide |
| experience thresholds | `$1DB5`, split low/mid/high | `$136E`, 3-byte big-endian |
| spell names | `SPELLN00` at `$B000` | `COMBAT2` at `$E000` |

Nothing else in the record moves.

**Both `ITEMNAMES` bases are the literal operand of an instruction**, not a
fit: `LIBRARY` reads the name table with `LDA $6F00,X / STA $07` in Pool of
Radiance and `LDA $9E00,X / STA $07` in Curse. `tests/test_titletables.py`
asserts both, and the same test re-fits `LIBRARY`'s own base — `$2C48` wins
215 to 66 in Pool of Radiance and `$2DC8` wins 228 to 57 in Curse, scoring how
many `JSR`/`JMP` targets land on the byte after an `RTS`, an `RTI` or a `JMP`.

### 2.2 Two fields Curse uses that Pool of Radiance leaves at zero

Both fall inside regions `goldbox/layout.py` marks UNKNOWN, so neither displaces
anything.

| Offset | What | Evidence |
|---|---|---|
| `0x065`–`0x06B` | a **second copy of the seven ability scores** — STR, INT, WIS, DEX, CON, CHA, exceptional STR, mirroring `0x014`–`0x01A` | CONFIRMED. All six of SSI's pre-generated Curse characters carry it; the import writes it; every Pool of Radiance specimen holds seven zeroes |
| `0x098` | **fighting level** — the level the attack tables are indexed by. 5 for the level-5 paladin and ranger, 4 for the level-5 fighter/thief, 0 for pure casters, 1 for an imported level-1 fighter | CONFIRMED. Zero in every Pool of Radiance specimen. Matches DOS `attackLevel` (`0x6B` in DOS PoR, `0x0DD` in DOS Curse) at the cluster's Δ+`0x2D` |

The DOS record keeps the seven abilities as *(original, current)* byte pairs.
The C64 keeps them as two parallel seven-byte arrays instead, one at `0x014`
and one at `0x065`. Which of the two the game treats as "current" is not
established: in every specimen held they are equal.

### 2.3 Classes

Paladin and ranger are **slots 6 and 7 of the existing eight-byte per-class
level array at `0x0C9`**, and bits 6 and 7 of `class_bits` at `0x0EB`. Nothing
moves; Pool of Radiance simply leaves `0x0CD`–`0x0D0` zero. CONFIRMED from
SSI's own pre-generated party, where the paladin has `0x0CF = 5` / `class_bits
= 64` and the ranger `0x0D0 = 5` / `class_bits = 128`.

`char_class` at `0x073` is **zero in every Curse record examined** — SSI's six
pre-generated characters and all three imported ones. The import explicitly
zeroes it. `class_bits` is the field to read, which is what
`docs/40-memory-map.md` already says for Pool of Radiance.

### 2.4 Two more bytes worth naming

| Offset | Observation | Confidence |
|---|---|---|
| `0x0A4` | the **caster's** half of turning: non-zero only for characters who turn undead — 6 for Curse's level-5 cleric, 3 for its level-5 paladin, 1 for Pool of Radiance's level-1 cleric ROLAND, 0 for everyone else in both games. The *value* is not the cleric's level: three of Pool of Radiance's level-5 clerics read 1, 4 and 6, and its 7TH LVL CLERIC reads 0 | PROBABLE for the population; the value is a guess |
| `0x0B6` | non-zero **only** for Curse's paladin (45) and ranger (134); zero in every Pool of Radiance specimen held and in Curse's other four. A class-specific counter of some kind | GUESS |

**An earlier version of this table said `0x0A4` displaced `goldbox/layout.py`'s
`turn_class` at `0x0A3`, because `0x0A3` is zero in every specimen of either
game. It is — every *player* specimen, and no player character is undead.**
Across Pool of Radiance's 121 distinct `MON*` records the two bytes are
disjoint: `0x0A3` is non-zero on twelve records, every one undead, matching the
AD&D 1e turning table (skeleton 1, zombie 2, ghoul 3, wight 5, wraith 7, mummy
8, spectre 9, vampire 10); `0x0A4` is non-zero on eight records, every one a
cleric; nothing sets both. They are the two sides of the same rule, not two
readings of one field, and `0x0A3` keeps its CONFIRMED.

## 3. The save game

**Curse's save disk holds one file, not two.** It is called `SAVEAZURE` — the
same name as the pre-generated party shipped on game side B3 — and it
is a verbatim memory image of `$4B00`–`$67FF`: 7424 bytes of payload behind the
usual two-byte PRG load address.

| | Pool of Radiance | Curse |
|---|---|---|
| files | `SAVEDGAME0` `$4900`–`$64FF`, `SAVEDGAME1` `$8300`–`$8AFF` | `SAVEAZURE` `$4B00`–`$67FF` |
| header | `$4900`–`$4CFF` (`$400`) | `$4B00`–`$4EFF` (`$400`) |
| party x, y, facing | `$49C0`, `$49C1`, `$49C2` | `$4BC0`, `$4BC1`, `$4BC2` |
| game clock | `$49C7` | `$4BC7` |
| loaded-file cache | `$4BC0`, 25 entries, dirty bit `$80` | `$4DC0`, same |
| area id | `$4BC2` | `$4DC2` |
| combat icons | `$4BE0`, 8 × 36 | `$4DE0`, 8 × 36 |
| character slots | `$4D00`, `$100` each | `$4F00`, `$100` each |
| name table | — | `$5700`, 16 bytes per character |
| item area | `$5900`–`$64FF` | `$5B00`–`$66FF` (PROBABLE) |
| roster, 8 × 32 bytes | `$8300`, in `SAVEDGAME1` | `$6700`, in the same file |

**Everything before the slots is Pool of Radiance's layout plus `$200`**, and it
was confirmed by diffing two real saves: standing at 7,13 facing south put
`07 0d 02` at `$4BC0` and turned `$4DC2` from `$FF` to `$81` — area 1 with the
dirty bit set.

SSI confirms the same three bytes independently. **There are two files called
`SAVEAZURE`**: the 7424-byte pre-generated party on side B3, and a **2030-byte
truncated image on side A2** which loads at the same `$4B00`, ends mid-slot at
`$52EE`, and holds the four level-8-to-10 characters the attract-mode demo
plays — ALEXANDRA, GAMBLER, CLERYE II, TSICUS. Its `$4BC0`-`$4BC2` read
`14, 6, 1`: a sane square, facing east. Anything reading Curse's disks must
take the longer file, which is what `tests/gamedata.py` does.

Two things do not simply shift.

**The roster moved into the same file.** Pool of Radiance splits it into
`SAVEDGAME1` at `$8300`; Curse keeps it at `$6700`, one page past the item
area, and the file ends there. The block layout is unchanged: `+0x00` and
`+0x13` structural 1, `+0x0D` slot index, `+0x0E` THAC0, `+0x0F` AC, `+0x15`
readied count, `+0x17` damage bonus, `+0x19` current HP, `+0x1B` movement.
`goldbox/savegame.py`'s `RosterBlock` reads it without a single field change.

**There is a name table at `$5700`** — sixteen bytes per character, NUL-padded,
in slot order. Pool of Radiance has nothing there; `$5700` is exactly where
Curse's slot 8 would begin, so Curse's slot array cannot be twelve wide the way
Pool of Radiance's is. How many combat slots Curse keeps, and where, is NOT
FOUND: `$5800`–`$5AFF` was zero in both saves taken.

The **item area is not confirmed**. `$5B00` is the position that makes the
geometry close — twelve `$100` blocks ending exactly where the roster begins —
and the region above `$6300` did change between two saves, which is what slots
8–11 would do. But the party used had no inventory, so no item record has ever
been seen in Curse. PROBABLE, not CONFIRMED.

## 4. The import routine, which is the real answer

Curse imports through **ADD CHARACTER TO PARTY → POOL**, reading Pool of
Radiance's own `\x01NAME` export files off a Pool of Radiance save disk. It
loads one at its own `$6B00` and builds the Curse record at `$7C00`.

Three Pool of Radiance characters were imported, the party saved, and one
exported again as `\x02BRUTUS`. Against its source file, **15 of 580 bytes
differ**:

| Offset | Field | Change |
|---|---|---|
| `0x065`–`0x06B` | second ability array | written from `0x014`–`0x01A` |
| `0x073` | `char_class` | zeroed |
| `0x098` | fighting level | set |
| `0x0C1` | gold | zeroed |
| `0x0C3` | platinum | set to **300** |
| `0x0FE`, `0x0FF` | portrait head, body | zeroed |
| `0x10F` | roster armour class | recomputed |

Across all three characters the pattern is the same, plus recomputation where
the character had something to recompute: the fighter's saving throws changed
where an item bonus had been baked in, and the magic-user/thief's **thief
skills were re-derived rather than copied**.

What it does **not** touch is the interesting half: **experience, level, the
per-class level array, class bits, hit points maximum and rolled, the
spellbook, race, age, alignment, sex, and the 36-byte combat icon at `0x220`
all pass through byte for byte.** There is no silent re-levelling — the DOS
`SilentTrainPlayer` call is on the Hillsfar path, not the Pool one.

The 300 platinum is the same constant the DOS reimplementation carries as
`player.Money.SetCoins(Money.Platinum, 300)`, and it is what every one of SSI's
pre-generated Curse characters ships with. Two independent artefacts agreeing
on an arbitrary number is as close to proof as this work gets.

**Not tested on the C64:** the DOS importer deletes ANIMATE DEAD (spell id 36)
from the imported spellbook. No character imported here knew it, so whether the
C64 build does the same is NOT FOUND.

## 5. What matters to an editor

| | |
|---|---|
| **Classes** | Two more: paladin at array index 6 / bit 6, ranger at index 7 / bit 7. No new offsets, no new widths. The class-name table entries 13/14/15 are fighter/mage, fighter/thief, fighter/mage/thief in both games — not paladin and ranger |
| **Levels** | Measured — §9. The ceiling is **11 / 10 / 12 / 12 / 11 / 11** for magic-user, cleric, thief, fighter, paladin, ranger, against Pool of Radiance's 6 / 6 / 9 / 8, and the experience table is the full AD&D 1st edition progression to level 13. `goldbox/levels.py`'s existing rows are Curse's rows exactly where the two overlap; what it needs is the missing levels and two more classes, not a different `Level` |
| **Items** | `ITEMS` byte `+13` is the class-usage bitmask. Curse sets **bit 7 (ranger) wherever Pool of Radiance sets bit 6 (paladin)** — 95 of the 128 records differ in that byte, against at most 9 in any other. `goldbox/items.py`'s `CLASS_USAGE_BITS` names only the low four bits, so bit 6 already reads as nothing in Pool of Radiance |
| **Item names** | 253 named entries against Pool of Radiance's 252, sharing 252 indices of which **217 are the identical string**. Curse fills the gap at 168 and replaces 35 entries Pool of Radiance never used. One constant (`$9E00`) and `goldbox/items.py` reads it |
| **Spells** | 169 named ids where Pool of Radiance has 120, and the **first 56 are the same spell in the same order** — §10. Curse has **no `SPELLN00`**; it ships `SPELLN64`, and so does Pool of Radiance, and that file is not a spell-name table in either game: its payload is the `ALTER`/icon menu strings (`SIZE`, `SMALL`, `LARGE`, `WEAPON`, `HEAD`, `SHIELD`), 1878 bytes in both. The names and their pointer table are in `COMBAT2`, resident at `$E000`. The spellbook bitmask is at `0x078` in both; no Curse specimen writes past `0x07D`, so its width is unproven here — but Silver Blades and Death Knights casters set `0x07D`–`0x07F`, so on the later engine the mask is **at least 8 bytes** (write-up lost, `work/reports/goldbox-inventory.md`) |
| **Status** | `0x100` reads 1 in every occupied Curse record, exactly as Pool of Radiance's `roster_in_use` does. The C64 Curse editor labels `0x100` `STATUS` with a seven-value enum — 1 OK, 2 GONE, 3 DEAD, 4 DYING, 5 UNCONSCIOUS, 6 RUNNING, 7 STONED — and the same author's Silver Blades and Death Knights editors carry it unchanged. It disagrees with the DOS enum, and no specimen reads anything but 1, so it stays a lead; the one observation that fits is the combat research watching the byte go `$01` → `$84`, and `$84 & 0x0F = 4 = DYING`. **A fourth source has since made it weaker, not stronger**: the DOS format workbooks place `CharacterStatus` at DOS `0x10C`, which under the roster alignment is C64 `0x10A` and not `0x100` at all, and their enum is 0-based where the three "sir" editors' is 1-based. `roster_in_use` keeps its name. One specimen reading other than 1 settles it |

## 6. Still unknown

| Question | Status |
|---|---|
| Where the item area really is, and whether the 16-byte item record changed | PROBABLE `$5B00`; no Curse item record has been seen |
| How wide the memorised-spell list at `0x020` is | NOT FOUND |
| How wide the spellbook bitmask at `0x078` is | NOT FOUND in Curse — `0x078`–`0x07D` observed, 13 bytes predicted. **At least 8 bytes** on the later engine: Silver Blades and Death Knights casters set `0x07D`–`0x07F`, four of them holding `0x07F = 0x04`. The 13 is `⌈100/8⌉` from the DOS per-title spell counts (Pool of Radiance 56, Curse 100, Silver Blades 117, Pools of Darkness 126), so it is a prediction that assumes the C64 cut no spells — reading one Curse caster's spellbook against `COMBAT2`'s name table settles it. See `docs/127` §4 |
| Where `paladinCuresLeft` and the dual-class array live | NOT FOUND. **HUMAN CHANGE CLASS is on the C64 party menu**, so the dual-class array is reachable by experiment; the one character tried was refused |
| Where the azure-bond state lives | NOT FOUND. It is not in the character record on DOS either |
| Which of `0x014` and `0x065` is "current" and which "original" | NOT FOUND — equal in every specimen |
| How many combat slots Curse keeps, and where | NOT FOUND — `$5800`–`$5AFF` zero in both saves |
| Which class and level each new spell id 57–100 belongs to | PROBABLE from AD&D — §10 — but no code assigns them here |
| Why the racial limit subtracts the prime-requisite bonus rather than adding it | NOT UNDERSTOOD — §9 |

## 7. Corrections to the original plan (`work/reports/coab-plan.md`, lost)

That plan was written before any of this and several of its open questions are
now settled, some against its guesses.

| Plan | Correction |
|---|---|
| §5.1 "Does a Curse save disk hold one file or two, and what are they called?" | **One**, `SAVEAZURE`, `$4B00`–`$67FF`, 7424 bytes, roster inside it at `$6700`. It does not split like Pool of Radiance |
| §5.4 "Record total size — Curse is at least `0x11C`, probably more" | **580 bytes, the same as Pool of Radiance.** Export files are 582 raw at load address `$7C00`, marker byte `$02` not `$01` |
| §3 "`SAVE0_LOAD_ADDRESS` `$4B00` — verify against a real save disk" | Verified |
| §5.3 "the area id … `$4DC2` is the shifted guess and nothing more" | Confirmed at `$4DC2`; party position at `$4BC0`/`$4BC1`/`$4BC2` |
| §4.1 "the tables agree on ~30 offsets and will diverge on the rest" | Not supported. They agree on **every** offset found so far, and Curse's two extra fields land in regions Pool of Radiance marks UNKNOWN. A second table is still a reasonable choice, but not for that reason |
| §3.3 of the research: `SAVEAZURE` "on disk B3" | Right about the party, but side A2 carries **a different 2030-byte file of the same name** — see §3. A reader that takes the first match gets the wrong one |
| §7 "`0x100` status byte … rests on one hobbyist editor" | It reads 1 in every occupied record, like Pool of Radiance's `roster_in_use`. The editor's enum remains unsupported |
| §7 "the `SAVEDGAME1` roster block **is** record bytes `0x100`–`0x11F`" | Confirmed in Curse: the roster block and record bytes `0x100`–`0x11F` are byte-identical for the same character |

One practical note that is not in the plan, **and it has since been fixed.**
`CURSE4.D64` in the `with_docs` set is 175531 bytes — 35 tracks plus error bytes
— and `goldbox/d64.py` refused it, because the reader took plain 174848-byte images
only. It now reads **six** variants, that one included; the error bytes are
exposed through `D64.error_code` and acted on by nothing, and every variant but
the plain image is read-only. See [`10-disk-format.md`](10-disk-format.md).

## 8. The test that pins it

`tests/test_second_game.py`. It runs the *same* invariant checks over Pool of
Radiance's own saved games and over Curse's `SAVEAZURE`, through the same
`goldbox.record`, `goldbox.geo`, `goldbox.items` and `goldbox.savegame` code paths:

* a record decodes at Pool of Radiance's offsets and round-trips byte-identically;
* `class_bits` is exactly one bit per non-zero slot of the eight-byte array at
  `0x0C9` — the assertion that fails if the array is ever narrowed back to four;
* Curse uses index 6 and index 7, which Pool of Radiance never does;
* the roster block equals record bytes `0x100`–`0x11F`;
* the save geometry is Pool of Radiance's constants plus `$200`;
* every `GEO` decodes with reciprocity above 92% — Curse's worst is 93.5%;
* `ITEMS` is 128 × 16 and Curse's class-usage byte is a bit-superset of Pool of
  Radiance's.

A change made for one game that moved a field, narrowed a region or shifted a
base would fail on the other side. The Curse half skips when the disks are
absent, like every other test that needs game data.

Curse disks are found the same way Pool of Radiance's are: `$COAB_DISKS` first,
then the usual home-directory names, then `work/` — which `AGENTS.md` already
names as where disk images belong.

## 9. Levels, ceilings and experience

All four tables are in `GEN` — the overlay that carries both character
generation and the training hall — and `GEN` is **resident at `$0800`**, not at
the `$1220` its PRG header claims. The base is fixed by a decimal-place table
(`1, 10, 100, 200, 1000`) landing exactly on its own file offset there, and
corroborated by the instructions three bytes away that index it. Pool of
Radiance's `GEN` declares `$1000` and also runs at `$0800`.

### 9.1 The class ceiling — CONFIRMED

Eight bytes in **class-bit order**, so the index is the same number as the bit
in `0x0EB` and the slot in the per-class level array at `0x0C9`.

| | magic-user | cleric | thief | fighter | 4 | 5 | paladin | ranger |
|---|---|---|---|---|---|---|---|---|
| Pool of Radiance, `$1E5C` | 6 | 6 | 9 | 8 | 0 | 0 | 0 | 0 |
| Curse, `$15A1` | 11 | 10 | 12 | 12 | 0 | 0 | 11 | 11 |

CONFIRMED, and the confirmation is the instruction rather than the shape of the
numbers: Curse's training routine reads `LDA $7CC9,X / CMP $15A1,X` — the
character record's own per-class level array against this table — and Pool of
Radiance's does the same at `$1E5C`. That promotes what
`docs/119-test-party.md` calls a PROBABLE ceiling ("the tables end at those
rows; no routine enforcing them has been cited"); the routine is now cited.

Bits 4 and 5 are zero in both. Curse has no knight; the Krynn titles do, at bit
4, and that is where their ceiling would appear.

### 9.2 The racial limit — CONFIRMED against AD&D

A second ceiling, indexed `race * 4` in Pool of Radiance and `(race - 1) * 8`
in Curse, taking the same class number as the column. `99` means no limit.
Races 7 (human) and above skip the check entirely.

| race | Pool of Radiance mu/cl/th/fi | Curse mu/cl/th/fi + pal/rng |
|---|---|---|
| 1 dwarf | 0 / 8 / 99 / 9 | 0 / **0** / 99 / 9 |
| 2 elf | 11 / 7 / 99 / 7 | 11 / **0** / 99 / 7 |
| 3 gnome | 0 / 7 / 99 / 6 | 0 / **0** / 99 / 6 |
| 4 half-elf | 8 / 5 / 99 / 8 | 8 / 5 / 99 / 8, ranger 8 |
| 5 halfling | 0 / 0 / 99 / 6 | 0 / 0 / 99 / 6 |
| 6 half-orc | 0 / 4 / 8 / 10 | 0 / 4 / 8 / 10 |
| 7 human | 99 / 99 / 99 / 99 | 99 all six |

Half-orc `0/4/8/10` and half-elf `8/5/99/8` are AD&D 1st edition exactly, and
they are the two rows no other reading of the table would produce, which is
what makes this CONFIRMED rather than a plausible parse.

**The one real change is the cleric column.** Curse zeroes it for dwarf, elf
and gnome where Pool of Radiance carried 8, 7 and 7. Those three numbers are
the *Dungeon Master's Guide* NPC limits; the *Players Handbook* does not let a
player be a dwarf, elf or gnome cleric at all. So Curse is the stricter reading
of the same rule. PROBABLE that the effect in play is "cannot advance as a
cleric" — the byte is 0 and the comparison is `level >= limit`, but no dwarf
cleric has been trained in the emulator to watch it refuse.

One thing is **not understood**: the routine looks up the prime-requisite
bonus (+1 at 17, +2 at 18, read from the *second* ability array at `0x065`,
which is the one Curse fills) and then **subtracts** it from the racial limit
rather than adding it. Written out, a strong fighter would be capped lower.
Either the sign is a bug, or `$B0` is being accumulated in a way this reading
misses.

### 9.3 Experience — CONFIRMED

Curse's thresholds are six rows of thirteen, 39 bytes a row, at `$136E`, in
class order magic-user, cleric, thief, fighter, paladin, ranger — class bits 6
and 7 fold down to rows 4 and 5, because bits 4 and 5 have no class. Each entry
is **three bytes big-endian**, which is the one place in this family a
multi-byte number is not little-endian; the reader walks the entry backwards
from `level * 3 + 2`, which is what puts the high byte last.

Entry `n` is the total needed to leave level `n`, so entry 0 is 0 and entry 12
is the last threshold the table holds.

Every value is the AD&D 1st edition number **plus one** — 2001 to reach fighter
2, 125001 to reach fighter 8 — with exactly one exception: the ranger's first
threshold is a bare 2250. Pool of Radiance's own table, at `$1DB5` and split
into parallel low, mid and high arrays nine entries wide, holds the same
numbers with the same +1, so `goldbox/levels.py` already agrees with Curse for
every level the two share. `tests/test_titletables.py` asserts that agreement
row by row.

The hit-dice tables sit beside it, three more eight-byte arrays in class-bit
order: the die (`$161E`: d4, d8, d6, d10, —, —, d10, d8), the level after which
hit dice stop being rolled (`$1626`), and the flat hit points a level adds from
then on (`$162E`: 1, 2, 2, 3, —, —, 3, 2). Pool of Radiance needs no such rule
because it stops before any class reaches it.

## 10. The spell table

**Curse's spell names are the first 2011 bytes of `COMBAT2`, resident at
`$E000`, followed by their own pointer table**: 170 high bytes at payload
`0x7DB`, then 170 low bytes at `0x885`. Spell id *n* is table index *n - 1*.

The base needs no fitting — the pointer for index 0 is `$E000` and the text is
`$E000`–`$E7DA`, which is exactly the range of high bytes the array holds.

**The pointers are not optional.** The strings overlap the same way Pool of
Radiance's do, and more of them: `SHIELD` is the last six bytes of
`FIRE SHIELD`, `INVISIBILITY` the tail of `DETECT INVISIBILITY`, and the
magic-user `DETECT MAGIC`, `HOLD PERSON` and `DISPEL MAGIC` share one copy each
with their cleric namesakes. Splitting the block on NULs yields 150 strings
where the table has 169 names, and every id above 10 comes out wrong.

**Ids 1–56 are Pool of Radiance's, spell for spell.** That is now read off
Curse's own table rather than inferred from the item tables, and it is what
makes an imported spellbook mean what it said: bit 20 is `SHOCKING GRASP` in
both games.

Ids 57–100 are Curse's new spells, with a handful of combat messages mixed in
among them (57 `IS DISTRACTED BY VERMIN. SPELL ABORTED`, 59 `IS BERSERKING`,
61 and 62 both `THROWS A LIGHTNING BOLT`), and 63–65 and 95–97 unused — an
unused slot points at `$E000`, so it reads back as `BLESS`. From 101 the table
is the combat-message tail Pool of Radiance starts at 57.

The grouping below is PROBABLE: it is AD&D's spell levels, not a table in the
game.

| ids | probably |
|---|---|
| 58, 66–70 | cleric 4 — cure/cause serious wounds, neutralize poison and its reverse, protection from evil 10' radius, sticks to snakes |
| 71–76 | cleric 5 — cure/cause critical wounds, dispel evil, flame strike, raise dead, slay living |
| 77–80 | druid 1 — detect magic, entangle, faerie fire, invisibility to animals; the ranger's list |
| 81–90 | magic-user 4 — charm monsters through animate dead |
| 91–94 | magic-user 5 — cloud kill, cone of cold, feeblemind, hold monsters |

`ECL65` carries a second copy of the strings. Whether it carries a second
pointer table has not been checked, and nothing needs it to.
