# Curse of the Azure Bonds — how much of it is the same game

**Status: researched. Nothing built beyond one test that pins the answer.**

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
| every named field in `por/layout.py` | — | same offset, same width | CONFIRMED |
| save slot | first 256 bytes of the record | first 256 bytes of the record | CONFIRMED |
| roster block | record `0x100`–`0x11F` | record `0x100`–`0x11F`, byte-identical structure | CONFIRMED |
| `60 - value` encoding for THAC0, AC, damage | yes | yes | CONFIRMED |
| disk container | D64 | D64 | CONFIRMED |
| map files | `GEO`, 1024 bytes, four 16×16 planes | identical | CONFIRMED |
| item word table | `ITEMNAMES`, 256 low + 256 high + strings | identical shape | CONFIRMED |
| item type table | `ITEMS`, 128 × 16 | identical shape | CONFIRMED |
| spell ids 1–56 | as `por/spells.py` has them | identical | CONFIRMED (research) |

`por/geo.py` decodes all sixteen Curse `GEO` files with no change at all.
Reciprocity — the fraction of wall edges that agree from both sides, which
collapses if a plane is misassigned — is **15114/15360 (98.4%)** across Curse's
sixteen, against **28540/28800 (99.1%)** across Pool of Radiance's thirty. Same
distribution, same decoder.

`por.record.CharacterRecord` parses a Curse export and round-trips it
byte-identically today, with no code change.

## 2. What differs

### 2.1 Constants

| Where | Pool of Radiance | Curse |
|---|---|---|
| exported character, load address | `$6B00` | `$7C00` |
| exported character, filename marker byte | `$01` | `$02` |
| save image, load address | `$4900` | `$4B00` |
| `ITEMNAMES` resident base | `$6F00` | `$9E00` |
| `LIBRARY` `GEO` stem table | `$24B4` | `$2714` |

Nothing else in the record moves.

### 2.2 Two fields Curse uses that Pool of Radiance leaves at zero

Both fall inside regions `por/layout.py` marks UNKNOWN, so neither displaces
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

**An earlier version of this table said `0x0A4` displaced `por/layout.py`'s
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
`por/savegame.py`'s `RosterBlock` reads it without a single field change.

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
| **Levels** | `por/levels.py` already carries paladin, ranger and monk rows "because the tables list them". Curse makes two of them real and raises the caps. Table data; the shape of `Level` does not change. Not measured this pass |
| **Items** | `ITEMS` byte `+13` is the class-usage bitmask. Curse sets **bit 7 (ranger) wherever Pool of Radiance sets bit 6 (paladin)** — 95 of the 128 records differ in that byte, against at most 9 in any other. `por/items.py`'s `CLASS_USAGE_BITS` names only the low four bits, so bit 6 already reads as nothing in Pool of Radiance |
| **Item names** | 253 named entries against Pool of Radiance's 252, sharing 252 indices of which **217 are the identical string**. Curse fills the gap at 168 and replaces 35 entries Pool of Radiance never used. One constant (`$9E00`) and `por/items.py` reads it |
| **Spells** | 100 ids where Pool of Radiance has 56, and the **first 56 are unchanged**. Curse has **no `SPELLN00`** — it does ship `SPELLN64`, on side A, and so does Pool of Radiance, but that file is not a spell-name table in either game: its payload is the `ALTER`/icon menu strings (`SIZE`, `SMALL`, `LARGE`, `WEAPON`, `HEAD`, `SHIELD`), 1878 bytes in both. The spell names live in `COMBAT2` and again in `ECL65`, and the pointer table that resolves an id to a name has not been located. The spellbook bitmask is at `0x078` in both; no Curse specimen writes past `0x07D`, so its width is unproven here — but Silver Blades and Death Knights casters set `0x07D`–`0x07F`, so on the later engine the mask is **at least 8 bytes** (`work/reports/goldbox-inventory.md`) |
| **Status** | `0x100` reads 1 in every occupied Curse record, exactly as Pool of Radiance's `roster_in_use` does. The C64 Curse editor labels `0x100` `STATUS` with a seven-value enum — 1 OK, 2 GONE, 3 DEAD, 4 DYING, 5 UNCONSCIOUS, 6 RUNNING, 7 STONED — and the same author's Silver Blades and Death Knights editors carry it unchanged. It disagrees with the DOS enum, and no specimen reads anything but 1, so it stays a lead; the one observation that fits is the combat research watching the byte go `$01` → `$84`, and `$84 & 0x0F = 4 = DYING` |

## 6. Still unknown

| Question | Status |
|---|---|
| Where the item area really is, and whether the 16-byte item record changed | PROBABLE `$5B00`; no Curse item record has been seen |
| How wide the memorised-spell list at `0x020` is | NOT FOUND |
| How wide the spellbook bitmask at `0x078` is | NOT FOUND in Curse — `0x078`–`0x07D` observed, 13 bytes predicted. **At least 8 bytes** on the later engine: Silver Blades and Death Knights casters set `0x07D`–`0x07F`, four of them holding `0x07F = 0x04` |
| Where `paladinCuresLeft` and the dual-class array live | NOT FOUND. **HUMAN CHANGE CLASS is on the C64 party menu**, so the dual-class array is reachable by experiment; the one character tried was refused |
| Where the azure-bond state lives | NOT FOUND. It is not in the character record on DOS either |
| Which of `0x014` and `0x065` is "current" and which "original" | NOT FOUND — equal in every specimen |
| The spell-name pointer table | NOT FOUND |
| How many combat slots Curse keeps, and where | NOT FOUND — `$5800`–`$5AFF` zero in both saves |

## 7. Corrections to `work/reports/coab-plan.md`

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

One practical note that is not in the plan: `por/d64.py` refuses one of the
three rips. `CURSE4.D64` in the `with_docs` set is 175531 bytes — 35 tracks
plus error bytes — and the reader accepts only plain 174848-byte images.

## 8. The test that pins it

`tests/test_second_game.py`. It runs the *same* invariant checks over Pool of
Radiance's own saved games and over Curse's `SAVEAZURE`, through the same
`por.record`, `por.geo`, `por.items` and `por.savegame` code paths:

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
then the usual home-directory names, then `work/` — which `CLAUDE.md` already
names as where disk images belong.
