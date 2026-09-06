# Secret of the Silver Blades — running the Gold Box skill

**Status: phases 0 to 5 are done.** Phases 0-2 were a cold read of the disks
with `goldbox/geo.py`, `goldbox/record.py` and `goldbox/savegame.py` **unmodified**;
phases 3-5 were one driven session; the account of it, `work/reports/p9-ssb-live.md`,
is lost. `tests/test_ssblive.py` carries what a machine with the disks
can check again without an emulator.

Three results from the run are worth reading first. **The Curse import changes
three bytes** for a plain character, against fifteen for Pool of Radiance into
Curse — because the Curse record is already in the successor engine's shape,
and what is left is only what is per-*title*: the race code and the starting
purse. **`spells_known` is sixteen bytes**, `0x078`-`0x087`, spell ids 0-127,
read out of `GEN`'s own clear loop at `$09DC`. And **the live party position is
at `$C04B`, not `$4BC0`** — the header copy is stale during play, and so is the
on-screen status line.

A fourth, added by #31 (Cold-read Curse and Silver Blades for the fields the editor shows): **`GEN` and `CAMP` run at `$0800`**, and every Silver
Blades overlay address this document and `goldbox/spells.py` carried was
computed at the PRG header's `$4000` instead. §4.3 lists the seven corrected
addresses across three titles.

The title is *Secret* of the Silver Blades, singular, which is what the disks
say.

## 1. The disks

`SILVER-1.D64` ... `SILVER-6.D64` — three double-sided disks, sides 1 to 6,
with no gap and no error-byte rip among them. `goldbox/d64.py` opens all six.
The full inventory was in `work/reports/goldbox-inventory.md`, which is lost;
the per-title base addresses it established are asserted in
`tests/test_curse.py::test_the_addresses_are_the_ones_measured`.

**How the tests find them.** `tests/test_silverblades.py` looks behind an
`SSB_DISKS` environment variable and then at a candidate list, in the same
shape as `COAB_DISKS` in `tests/gamedata.py` — but *in the test module*, not in
`gamedata.py`, because that module was another agent's while this was written.
If a fourth title needs the same lookup it should move into `gamedata.py`
rather than be copied a second time.

Nothing about the disks may be committed. `tests/test_repository_contents.py`
enforces that and **its allowlist must not grow**.

**What phases 3-5 needed and now have:** a save disk written by the game, and a
Curse of the Azure Bonds party imported into Silver Blades and exported again.
`SAVEDBASH` on side 6 is the shipped demo party, not a save disk; the save disk
the run made lives in its slot directory and is not committed. The export load
address and marker byte were UNKNOWN and are now `$7C00` and **`\x05`**.

### A note on the skill

The decoding checklist -- `skills/goldbox` then, `docs/144-decoding-a-new-title.md`
now -- did **not exist** when this was written. The phases
below are derived from `docs/60-goldbox-field-checklist.md` and
`docs/116-second-game.md`, which is what the skill was distilled from, so they
should align; whoever runs the rest should read the skill first and reorder to
match it rather than the other way round.

## 2. Ordering

Silver Blades is the direct sequel, shares the most with Pool of Radiance and
Curse, and **is the only remaining title that imports a Curse party** — the
lever that produced the 15-bytes-of-580 result in `docs/116-second-game.md`.
Gateway and the Krynn titles start fresh parties and cannot offer it. That
argument is why it was worth waiting for the disks, and they are here.

What remains, in order:

1. **Finish Curse** — `docs/120-curse-testing.md`. Tiers 1, 2 and 5.1 are done;
   what is left needs the emulator.
2. ~~**Phases 3-5 here.**~~ Done — one driven session, write-up lost.
   Phase 4, the Curse-to-Silver-Blades import diff, was the single strongest
   experiment available in this project and it is spent.
3. Gateway to the Savage Frontier and the two Krynn titles are on disk and are
   read statically (write-up lost). They are a fourth
   target, not a third.

## 3. What was expected to transfer, and what did

Curse shares the 580-byte record with Pool of Radiance *at every offset*, and
that is not a diff of two specimens — it is the game's own import arithmetic.
The predictions below inherited their confidence from that. The outcome column
is the cold read of the disks (`tests/test_silverblades.py`)
for the first fourteen rows and the driven
session (`tests/test_ssblive.py`) for the last
six.

| | Prediction | Outcome |
|---|---|---|
| character record size 580 bytes | same | **held** |
| every field in `goldbox/layout.py`, same offset, same width | same | **held** — six shipped characters decode and round-trip byte-identically |
| save slot = first 256 bytes of the record, `$100` stride | same | **held** |
| roster block = record `0x100`–`0x11F`, last page of the payload | same | **held**, at `$6700` |
| `60 - value` encoding for THAC0, AC, damage bonus | same | **held** — `armour_class_base` decodes to 10 for all six |
| `GEO`: 1024 bytes, four 16×16 planes, `goldbox/geo.py` unmodified | same | **held** — 17 files, barrier reciprocity mean 0.982, worst `GEO40` 0.923; wall-art reciprocity **1.000 on every file** |
| `ITEMS` 128 × 16; `ITEMNAMES` 256 low + 256 high + strings | same shape | **held** — `ITEMS` 2048 bytes |
| second ability array at `0x065`, fighting level at `0x098` | present, as in Curse | **held** |
| spell ids 1–56 unchanged, more added above | as Curse did | **held**, and it is the strongest new result — see below |
| save file **count and names** | assume neither game's | **name differs** (`SAVEDBASH`), count does not: one file, like every title after Pool of Radiance |
| save load address and header base | a third value expected | **contradicted, in our favour.** `$4B00`, slots `$4F00`, items `$5B00`, roster `$6700` — byte for byte Curse's |
| file stems (`GEO`, `ECL`, `ITEMS`, …) | may be renamed wholesale | **contradicted, in our favour.** 30 of 34 stems are Pool of Radiance's; the one real rename is `ITEMFILE` → `ITEM` |
| fewer `GEO` files, no wilderness | fewer expected | 17, against Curse's 16 and Pool of Radiance's 29. No `SQRDATA`/`SQRPACI`/`WALLS` on any side |
| export load address and marker byte | a third pair expected | **half held.** Load address `$7C00`, Curse's exactly; marker byte **`\x05`**, where Pool of Radiance uses `\x01` and Curse `\x02`. So it is an identifier out of some list, not a sequence number |
| `ITEMNAMES` resident base | a third | **not settled** |
| `LIBRARY` `GEO` stem table address | a third | **not settled** |
| live party x/y/facing address | a third | **contradicted, and not in our favour.** `$4BC0` is the save's copy and is *stale while the party walks*; the live triple is at **`$C04B`**, found by intersecting two 64K snapshots |
| resident `GEO` left at `$0400` | must be re-verified | **held** — `GEO10`'s 1024 bytes appear verbatim at `$0400`, all four planes in order |
| status-line row and format on screen | unverified anywhere else | **held** — row 14, `E 0:12 2,0`, Pool of Radiance's format and `RE_STATUS` unchanged. But it is redrawn late: it read `2,0` when every memory copy said `(3,0)` |

**The rule the table encodes still stands, with one correction:** *structure*
transfers, *addresses* do not — except that the **save container's** addresses
did, exactly. Silver Blades and Gateway both reuse Curse's `$4B00`; the two
Krynn titles moved the block down `$B00` to `$4000`. So the save geometry is a
per-title constant with only three values across six games, and `goldbox/games.py`
is where they live. Every *other* absolute number is still a Pool of Radiance
constant that must be re-measured.

**A new regularity, worth more than any single address.** Silver Blades' `GEO`
ids are sparse — `$10` to `$62`, no `GEO00` — and **the high nibble is the disk
side the file sits on**, without exception: `GEO2x` on side 2, `GEO3x` on side
3. Champions and Death Knights do the same. That is a free area-to-side index,
and it is asserted in `tests/test_silverblades.py`.

### What being a sequel changed

| Difference | What came of it |
|---|---|
| **Party is imported from Curse, not rolled** | **Done, and it is the best result here.** Seven characters imported through `ADD CHARACTER TO PARTY → CURSE`: three bytes change for a plain character, twelve for a demi-human thief. §4.1 |
| **Higher level range** | The shipped party is level 8-9 with 100000-200000 experience. `goldbox/levels.py`'s caps are Pool of Radiance's and are still unmeasured for this title |
| **Higher spell levels than Curse** | **The gift arrived twice.** The cold read showed DOMINIC setting `0x07F = 0x04` — spell id 58 — so the mask was at least eight bytes. The driven session settled it outright: `GEN` clears **sixteen** bytes at `$7C78` and a second loop reads sixteen, so `spells_known` is `0x078`-`0x087`, spell ids 0-127. Usage stops at `0x083` (MORGAINE, id 94). `docs/116`'s prediction of 13 was low, and `gap_07f` is the mask's tail plus sixteen unexplained bytes, not one field |
| **Dual- and multi-classed characters common at this level** | Weakly held: one of six, MALACHITE, thief 8 / fighter 7 |
| **No city-block/wilderness structure** | Held at the file level — no `SQRDATA`, `SQRPACI` or `WALLS` on any side, in this or any title after Pool of Radiance. Whether the save's wilderness travel bytes are dead is not answerable statically |
| **A different race table** | Not predicted at all, and real. Silver Blades drops half-orc and re-orders the rest, so **human is 6, not 7**. `goldbox/games.py` now carries a per-title race table for exactly this |

## 4. The phases

| # | Phase | Emulator | State |
|---|---|---|---|
| 0 | **Obtain and place the disks** | no | **done** — six sides, all readable, found behind `SSB_DISKS` |
| 1 | **Cold read** — stem inventory, every `GEO` decoded, `ITEMS` shape | no | **done** — `tests/test_silverblades.py` |
| 2 | **A character record** | no | **done** — the shipped `SAVEDBASH` party, six characters, decoded and byte-identical on round trip |
| 3 | **Save geometry** | yes, for the header fields | **done.** Every header field at Pool of Radiance's payload offset: `0x0C0`-`0x0C2` x/y/facing, `0x0C5` the live area, `0x0C7`-`0x0C9` the clock, `0x0F0`/`0x0F1` the previous square, `0x2C2` the area in the save. Two saves one step apart differ in one byte, the clock |
| 4 | **The import diff** | yes | **done.** `ADD FROM: SECRET CURSE EXIT` — Curse is the only foreign source, there is no `POOL`. §4.1 |
| 5 | **Live addresses and the automapper run** | yes, exclusively | **done.** Live base `$4B00`, resident `GEO` at `$0400`, live party triple at `$C04B`. Nine steps and three refusals against `GEO10`, no contradictions. §5 |
| 6 | **Tests** | no | **done** — `tests/test_silverblades.py` for the cold read and `tests/test_ssblive.py` for the run, with Pool of Radiance as the control where there is one and a clean skip when the disks are absent |
| 7 | **Constants become a table** | no | **done** — `goldbox/games.py`, all six titles, threaded through `goldbox/savegame.py`, `goldbox/yaml_io.py` and `editor/` |

Phase 7 was planned last on the argument that two games can share code by
accident and three cannot. That held: it was the six-title inventory that
showed the seam is the save container's base address and nothing else, and
`goldbox/games.py` is three numbers wide because of it.

### What phase 2 corrected in its own pass criterion

Phase 2's criterion was "`class_bits` is exactly one bit per non-zero slot of
the array at `0x0C9`". The report, `work/reports/goldbox-inventory.md` §3.3(a)
(now lost), read it
**failing** on PAINE (`0x80`) and GUY DE VALOIS (`0x40`), and concluded the
criterion covers only the low four bits. The correction below is repeated as
an assertion in
`tests/test_silverblades.py::test_class_bits_is_one_bit_per_slot_of_the_eight_wide_level_array`.

**That is wrong, and the criterion holds unchanged.** The report read the array
at `0x0C9` as four bytes. It is eight — `goldbox/layout.py` names them
`level_magic_user`, `level_cleric`, `level_thief`, `level_fighter`,
`level_knight`, a gap, `level_paladin`, `level_ranger`. PAINE's level 8 sits in
slot 7 and GUY DE VALOIS's in slot 6, which is exactly what bits `0x80` and
`0x40` claim. Checked over every shipped party this machine holds, the
invariant `class_bits == sum(1 << i for non-zero slot i)` holds for **all six
titles**, the Krynn knights included: Champions' STRONGSWORD and Death Knights'
SIR DRYDEN carry `0x10` with slot 4 set. `tests/test_silverblades.py` asserts
it for Silver Blades and `tests/test_curse.py` for Curse.

### 4.1 The import diff, byte by byte

Seven specimens: the Curse export already in `work/curse/`, plus the six
pre-generated characters SSI ships inside Curse's own `SAVEAZURE`, reassembled
into 580-byte records and written onto a save disk as `\x02NAME` files. The
assembly was checked against a real Curse export first and reproduces it byte
for byte, so what the importer read was a genuine Curse export in everything but
authorship. Each result was read back both from live memory and — for one of
them — out of the file Silver Blades itself exported; the two agree.

| offset | field | before → after | what explains it |
|---|---|---|---|
| `0x072` | `race` | 7 → 6, 4 → 2, 2 → 1 | **Silver Blades' own race table.** Each pair is the same race under this title's numbering: `goldbox/games.py`'s two tables confirmed by the game's arithmetic instead of by inference |
| `0x0A5`–`0x0AC` | thief skills | re-derived | the same behaviour the Pool → Curse import showed. Only the thief has them |
| `0x0AD` | racial trait | 124 → 18 (half-elf), 107 → 95 (elf) | `GEN` seeds this from a per-race table indexed by the race byte; the import re-seeds it from **Silver Blades'** table using the **new** code — an independent corroboration of the remap |
| `0x0B6` | trait, slot 9 | ranger 134 → 105; paladin 45 unchanged | Silver Blades' own pregens carry exactly those two numbers |
| `0x0C3`–`0x0C4` | `platinum` | 300 → 0 | the Curse starting purse is taken away; the opening scene then hands the party 20 gems |
| `0x0D5` | `infravision` | 6 → 0 for elf and half-elf | Silver Blades records none, not even for its own dwarf |
| `0x0EC` | unknown | 0 → 1, 2 or 3 by class | **UNKNOWN.** Every native pregen carries `0xFB` here, which the import does not produce |

Per specimen: 3 bytes for BRUTUS, 4 for the paladin, cleric and human mage, 5
for the ranger, 6 for the elf mage, 12 for the half-elf thief/fighter.

**Untouched on all seven:** name, both ability arrays, age, hit points, saving
throws, level, experience, the per-class level array, class bits, alignment,
sex, the whole sixteen-byte spellbook, and the 36-byte combat icon. The roster
block at `0x100`–`0x11F` is identical too — armour class is not even
recomputed, because there is nothing to recompute.

**Why three where Pool → Curse was fifteen.** Twelve of those fifteen were
Curse bringing a Pool of Radiance record up to the later engine's shape. A
Curse record already has all of it. What is left is exactly what is per-*title*
rather than per-engine — the race table and the starting money — plus what is
race- or class-seeded. That is a stronger statement of "the record transfers"
than the fifteen was.

**Not exercised:** no specimen carried an item or any coin but platinum, so the
256-byte item block and the other six purses are untested across the import.

### 4.2 The export format

`REMOVE CHARACTER FROM PARTY` writes the character out and drops it.

| | Pool of Radiance | Curse | **Silver Blades** |
|---|---|---|---|
| marker byte | `\x01` | `\x02` | **`\x05`** |
| load address | `$6B00` | `$7C00` | **`$7C00`** |
| size | 582 | 582 | **582** |

The load address is Curse's and the marker is not — and it is `5`, not `3`, so
the marker is an identifier out of some list rather than a count of sequels.

### 4.3 The cold read of `GEN`, and an overlay base this document got wrong

Done for `#31 (Cold-read Curse and Silver Blades for the fields the editor
shows)`, with no emulator. `tools/coldread.py` reads all of it again in three
commands and `tests/test_coldread.py` keeps it true.

**`GEN` and `CAMP` run at `$0800`, not at the `$4000` their PRG headers claim.**
Every Silver Blades `GEN` address this project had written down was `$3800` too
high, and the same fault put Curse's at `$2800` and `$1A00` too high and Pool of
Radiance's at `$0800` too high — seven citations in `goldbox/layout.py`,
`goldbox/spells.py`, `docs/20-character-record.md` and two test docstrings. The
findings they carried were all correct; only the addresses were wrong, and
**five** of the seven named bytes **outside the overlay altogether**, so anyone
checking one with `tools/overlay.py` — whose `--base` is `$0800` — would have
been told the address is not in the file.

Five rather than four, corrected 2026-09-02 by measuring each overlay's real
extent rather than counting by eye: Curse's `GEN $2D4A` (file ends `$2CEE`),
Curse's `CAMP $5225` (`$2C6E`), and all three Silver Blades addresses
(`$2AE0`). The two that stayed inside are Pool of Radiance's `GEN $296B` and
Curse's `GEN $2C2F`, the two whose header-base error was smallest.

The base is settled by the operands, which cannot move: `GEN $18C9` reads its
own scratch at `$1BFD` and its ceiling table at `$17D0`, and `CAMP $2871` calls
`$1478` and stores to `$2862`. Every one of those is inside the file at `$0800`
and outside it at `$4000`.

| cited as | is really |
|---|---|
| Silver Blades `GEN $41DC`, the sixteen-byte clear | `GEN $09DC` |
| Silver Blades `GEN $50C9`, the sixteen-byte walk | `GEN $18C9` |
| Silver Blades `CAMP $6071`, the memorise loop | `CAMP $2871` |
| Curse `CAMP $5225`, the same loop | `CAMP $2A25` |
| Curse `GEN $2D4A`, the druid spells | `GEN $232A` |
| Curse `GEN $2C2F`, the 32-byte copy | `GEN $220F` |
| Pool of Radiance `GEN $296B`, the same copy | `GEN $216B` |

**The trait seeds.** `GEN $0C4B` clears all ten slots and seeds two of them
from tables at `$0C5B` and `$0C62`, indexed by the race byte — which is why the
shipped dwarf carries two entries where the Curse import wrote one. `GEN $0FF0`
then removes any class trait and writes 45 for a paladin or 105 for a ranger.

| race | seeded with |
|---|---|
| elf 1 | 95 |
| half-elf 2 | 18 |
| dwarf 3 | 26, 47 |
| gnome 4 | 48, 7 |
| halfling 5 | 92 |
| human 6 | nothing |

| class | seeded with |
|---|---|
| paladin | 45, where Curse `GEN $2515` also writes 45 |
| ranger | 105, where Curse writes 134 |

**The codes are not Pool of Radiance's, and that was a defect a player could
see.** Curse's seeds all land on the race their Pool of Radiance name demands;
Silver Blades' elf 95 and half-elf 18 read as "fights on from -6 to 0 hit
points" and a gnome's bonus against kobolds. Four ids agree — 26, 47, the
gnome's 48 and the paladin's 45 — and five do not, so it is a reassignment
rather than an offset.
`#186 (The character sheet gives a Silver Blades elf a Pool of Radiance
ability)` gave this title its own table in `goldbox/traits.py`: six of the nine
seeded codes now carry Pool of Radiance's own wording pointed at this title's
numbers — 18, 26, 45, 47, 48 and 95 — and 7, 92 and 105 show their number,
because nobody has established what they mean and a wrong sentence is worse
than a number.

**The reassignment reaches past the racial codes**, which is why that table is
this title's own rather than Pool of Radiance's with six entries changed. A
census of the 69 `MON*` records on these six sides against the 108 on the eight
Pool of Radiance sides: PHASE SPIDER carries 37 and 139 there and 37 and **86**
here, the same creature with one code moved and 86 being Pool of Radiance's
two-level drain; FROST GIANT carries 98, its "regenerates 3 hit points a
round"; GARGOYLE and MARGOYLE carry 103, its "can assume gaseous form"; GIANT
SLUG carries 90, a dwarf's and a halfling's constitution bonus to saves; and 24
is on 36 of the 48 records here that carry anything, against one of Pool of
Radiance's 59. What each of those means in Silver Blades is unread, and every code the
seed tables do not establish shows its number.

**The level tables**, all at base `$0800`: experience `$162D` (6 rows x 19
entries x 3 bytes big-endian), class ceilings `$17D0`, racial class limits
`$17E0`, THAC0 `$106F` / `$107F` / `$108F` with the fighter group computed
`21 - fighting level` at `$1045`, hit dice `$1845` / `$184D` / `$1855`, level-1
saving throws `$1148` with a two-bit-per-level improvement mask at `$115C`, the
constitution hit-point bonus `$0E80`, and thief skills `$126D`. The full table
is in `docs/139-per-title-validation.md`'s A6 and A7 rows, both now `V`;
`goldbox/levels.py:SECRET_OF_THE_SILVER_BLADES` is the `LevelTables` built
from it (`#187 (Silver Blades characters are shown Pool of Radiance's level
progression)`). The trainer's own inputs -- the thief-skill racial
adjustment, the constitution hit-point bonus, the wisdom bonus spells, the
turning table -- stay unread or unattributed, so `levels.trainer_measured`
and `goldbox/levelup.py` still refuse the title.

Three of those are worth reading even if the rest is a lookup table.

**The experience rows are Curse's, carried on** — all 61 thresholds the two
share are identical. That includes the Curse fighter's eleventh, 749937 where
750001 is expected, which `goldbox/levels.py` recorded as possibly bit rot in
the one Curse rip that carries `GEN`. A second rip, of a different game, cracked
by a different group, holds the same number. It is SSI's.

**The saving-throw rule is Silver Blades' own.** Fill five columns with 20,
subtract a two-bit improvement per level per column, keep the best across every
class held, take 2 off every column for a paladin (`$11C0`), and take
`constitution * 2 / 7` off columns 0, 2 and 4 for **race 3 alone** — the dwarf,
where Pool of Radiance gives that bonus to the dwarf, the gnome and the halfling
and to all five columns. It reproduces all six shipped characters' stored saves.

**And the dwarf-only rule has now been watched, not only read** (`#344 (A
converted Silver Blades dwarf, gnome or halfling keeps DOS's saving throws,
because that title's racial bonus has never been watched in the game)`,
2026-09-06, `tools/ssbtrain.py`). The training hall opens here the way Curse's
does -- the party-menu builder is `$12AF` moved to `GEN $0991` and still reads
`$7EA8` -- so MALACHITE, thief 8 / fighter 7 at constitution 17, was raised to
thief 9 five times on one boot with only the race byte poked between presses,
and the five stored saves poked to 14 first so each row is a write:

| race byte | what `GEN` wrote at `0x09A`-`0x09E` | `levels.saving_throws` |
|---|---|---|
| 3, dwarf (twice) | 6 10 6 12 7 | 6 10 6 12 7 |
| 4, gnome | 10 10 10 12 11 | 10 10 10 12 11 |
| 5, halfling | 10 10 10 12 11 | 10 10 10 12 11 |
| 6, human | 10 10 10 12 11 | 10 10 10 12 11 |

25 of 25 columns. So the title is in `levels.RACIAL_SAVE_BONUS_MEASURED` and a
converted Silver Blades dwarf gets the C64's own row rather than DOS's. Two
things from the same session that are not the answer: **the sheet is drawn
before the arithmetic runs** -- a record read the moment `YOU ARE NOW A LEVEL
9 THIEF` appears still holds the old saves, and a second or two later holds
the new ones -- and **the training cost nothing and clamped nothing**: 3,000
platinum and 124,000 experience were the same after five presses, where Curse
takes 1,000 gp a class and lowers the experience to one under the next
threshold. The thief skills were rewritten from a dexterity the engine read
(`0x0A5`-`0x0AC` all moved), which is the input `goldbox/levelup.py` still
refuses this title for; the pairs are in `work/issue344/` for whoever reads
`$126D` next. The engine's own save of the trained party is
`~/wish-specimens/por-c64/WISH-SPEC-ssb-malachite-trained.D64`.

**The racial limits are a third independent source for the race table.** The
routine at `$178A` refuses to look one up for race 6 or above — the human rule —
and the five rows below it are AD&D's elf, half-elf, dwarf, gnome and halfling
in exactly the order `goldbox/games.py:RACES_SILVER_BLADES` already had from the
label pool and from the import's own arithmetic.

**And the item type table decodes.** 42 of 43 of Silver Blades' own named items
come out at their AD&D 1st edition damage or armour class through
`goldbox/items.py` unmodified. The exception is the hammer, which does 1d4+1
against large opponents here and 1d4 in the rulebook and in both earlier titles.
The type *indices* are renumbered — 54 is scale mail in the earlier two and the
CANARY here — so only a title's own `ITEM<nn>` lists say what its indices mean.

### What is left, and what blocks it

| left | blocked on |
|---|---|
| items and coins across the import | no specimen carried either; a Curse party with an inventory settles the 256-byte item block |
| `0x0EC` | class-shaped after an import, `0xFB` in every native pregen. UNKNOWN |
| ~~Silver Blades' per-race trait table at `0x0AD`~~ **read** (#31 (Cold-read Curse and Silver Blades for the fields the editor shows)) | `GEN $0C4B` seeds **two** slots from `$0C5B` and `$0C62`, which is why the shipped dwarf carries two entries where the import wrote one. Elf 95, half-elf 18, dwarf 26 and 47, gnome 48 and 7, halfling 92, human none; `GEN $0FF0` then writes 45 for a paladin and 105 for a ranger. §4.3 |
| the area byte across a boundary | the run never left `GEO10`, so `Fingerprint`'s narrowing is untested here |
| ~~whether the sixteen-byte spellbook is also Curse's~~ **it is not** (#31 (Cold-read Curse and Silver Blades for the fields the editor shows)) | Curse reads thirteen bytes: `CAMP $2A25` walks spell ids to 100 and indexes the mask at byte 12. Gateway is still unread |
| `ITEMNAMES` and `LIBRARY` resident bases | fittable statically, not done here |
| ~~`goldbox/levels.py`'s caps for this title~~ **built** (#31 (Cold-read Curse and Silver Blades for the fields the editor shows), #187 (Silver Blades characters are shown Pool of Radiance's level progression)) | every table is read off `GEO`'s neighbour `GEN` and written into `goldbox/levels.py:SECRET_OF_THE_SILVER_BLADES`; the character sheet shows it through `automap/live.py:_classes`. The trainer's own inputs stay unread, so `goldbox/levelup.py` still refuses to level the title |

**The loader's mode flag is `$7F11` (#29 (The live reader uses Pool of Radiance's addresses on every title)).** `LINKER` is 149 bytes on
`SILVER-1.D64`, is resident at `$2D00` byte-identical to the disk copy, and
begins `LDA $7F11` — the operand is absolute, so it names the flag without
anyone having to fit the load address. The overlay name table at `$2D42` is
Pool of Radiance's entry for entry, so `2` is COMBAT here too. Sampled live
across the whole of one session: `3` `INIT` on the credits, `0` `GEN` at the
roster menu, `1` `DUNGEON` in the world, `5` `POST.COM` on the treasure bar
after the opening fight, `1` again, and finally `4` `COM.PREP` → `2` `COMBAT`
when a wandering encounter fired 228 steps later. CONFIRMED, every value in the
table's used range but `8` `FINAL`.

**A real six-character Silver Blades party reads and heals through the shipped
code.** `actions.read_party` at `$4B00` gave GUY DE VALOIS, EPONA, PAINE,
DOMINIC, MALACHITE and MORGAINE with their records at `$4F00`+`n·$100` and hit
point maxima matching the game's own panel; `HealParty` wrote `$6719` and
`$6739` — the roster page at `$6700` — and MORGAINE and MALACHITE came back to
35/35 and 58/58. That is `docs/139` C12 and C16 measured on this title rather
than inferred.

**And the gate was exercised in a real fight.** 228 driven steps out of New
Verdigris reached a wandering encounter; the flag went `1` `DUNGEON` → `4`
`COM.PREP` → `2` `COMBAT`, with `MOVE VIEW AIM TURN QUICK DONE` on the command
bar. `actions.in_combat` answered True, `heal` stayed legal, and `identify`,
`store-spells` and `restore-spells` each refused with "refused during a fight
(`$7F11` is 2)". The roster read correctly *during* the fight too. `4` had
never been sampled live in any title before this.

**One hazard found while doing it:** while a full-screen picture is on the
screen, the roster page at `$6700` holds something else entirely and reads as
graphics data. Character *names* still come out right, because those are read
from the record slots, so a reader that sanity-checks the party will pass and
then show nonsense hit points. Issue #82 (The live roster reads graphics data while a full-screen picture is up on Silver Blades).

Phases 1, 2 and 6 needed no emulator, which is the whole reason they were
ordered first — and phases 3 to 5 then cost one session between them because
the artefacts they needed were already on disk.

## 5. The automapper validation run — what it found

The phase where "the live data is not where we think it is" gets caught instead
of being quietly wrong. It was, twice.

| source | in Pool of Radiance | in Silver Blades |
|---|---|---|
| the on-screen status line | row 14, `RE_STATUS` = `([NESW]) +(\d+):(\d+) +(\d+),(\d+)` | **the same row, the same regex, unchanged** — and *it lags*. It read `2,0` when every memory copy and the clock said the party had reached `(3,0)` |
| the memory copy | `$49C0`/`$49C1`/`$49C2`, lagging a move | `$4BC0` is the *save's* copy and did not move across six steps and two turns. **The live triple is `$C04B`/`$C04C`/`$C04D`** |
| the map itself | `ResidentGeo` at `$0400` | `$0400`, confirmed — `GEO10`'s 1024 bytes verbatim, all four planes in order |

**How the live triple was found**, and it is the recipe working exactly as the
skill describes it: two full 64K snapshots either side of one step south, and
**one** address in the whole machine held `03 03 02` before and `03 04 02`
after. A turn then moved the third byte and nothing else.

**The corpus.** Nine completed steps and three refusals in `GEO10`, which
decodes at 480/480 barrier reciprocity. Every completed step crosses an edge
the decoded map calls passable; every refusal meets one it calls impassable; no
contradictions. It is `WALK` in `tests/test_ssblive.py`. The three refusals are
the valuable half — `GEO10` has 480 edges and few are shut, so one refusal
identifies the map where a dozen successful steps would not.

**Costs, measured.** A move is one minute, a turn is free, and **a refused move
is free** — four bumps at `(3,3)` facing east left the clock at `0:05`.
`automap.state`'s `_refused` infers a one-minute cost and says in its docstring
that it is inferred; on this title it would never fire.

**Not done.** The party never left `GEO10`, so no area boundary was crossed and
`Fingerprint`'s narrowing across one is untested here.

**Hazards, all of them already paid for once —
see `docs/70-driving-the-game.md`.**

| | |
|---|---|
| **Never leave a checkpoint armed when the socket closes** | VICE re-enters the monitor on a connection that is gone, freezes, and reads nothing new. Only a `pkill` recovers it. Delete every checkpoint at the end of every experiment |
| **One binary-monitor client at a time** | A second connection is accepted and then never answered. `automap` and `tools/session.py` cannot both be live |
| **Connecting stops the machine; resuming costs ~14.3 ms of extra emulated time** | Per `resume()`, not per byte. Batch a poll into one resume; the interval is a speed dial |
| **Match responses by request id** | VICE interleaves unsolicited `STOPPED` events; a naive reader silently returns the *previous* request's data |
| **RAM under I/O needs the `ram` bank** | Query `BANKS_AVAILABLE`; on this build `ram` is bank 1 |
| **Overlays make every address conditional** | Read and check bytes before every write. Patching blind has corrupted a live routine here before |
| **The game polls the CIA matrix directly** | Keydown / hold / keyup / gap, 0.10s/0.14s in menus and 0.15s/0.28s for text. The first burst after a screen change is usually swallowed — verify by effect |
| **Type names lowercase** | `xdotool key W` arrives as `$D7` and the name prompt silently re-prompts on any byte ≥ `$5B` |
| **Disk swapping goes through the text monitor** | Open the binary monitor first, open the text socket once and never close it, never send `x` on it |

One agent runs this phase, alone, and says so in its brief. One did.

**One hazard the list did not carry, and it cost the first hour.** A D64 written
by a driven session must be **flushed** — attach something else, or tear the
session down cleanly — before it is read back. Otherwise the last file written
reads as a `*PRG` with a zero block count, which our own reader is perfectly
happy with and the 1541 will not open: the first import attempt answered
`CHARACTER NOT FOUND` for exactly that reason.

## 6. What the run feeds back into the checklist

The point of running the decoding checklist against a new title is not the
title. It is the checklist. **A finding is not closed until `docs/144-decoding-a-new-title.md` reads
differently, or has been deliberately left alone with a line in
`docs/50-experiments.md` saying why.**

| What the run showed | The edit |
|---|---|
| a prediction held | promote its confidence and name Silver Blades as the second corroboration. "Two games" becomes "three", which is the difference between a pattern and a coincidence |
| a prediction failed | the advice becomes *check, do not assume*, with the Silver Blades counterexample cited by offset. This is the most valuable outcome and should be treated as a success |
| a step cost far more or less than budgeted | reorder the phases. The order of attack is the skill's main claim; a phase that keeps running last should be documented last |
| a step needed something the skill does not mention | name the tool, the file and the invocation. A subagent starts cold; "you will need a save disk" belongs in the skill, not in someone's memory |
| a constant differed | it goes in `goldbox/games.py`, which is where the per-title constants live now that the skill's reference tables are gone. That table is the skill's most reusable artefact and Silver Blades is what makes it a table rather than a pair |

`docs/116-second-game.md` §7 is the model: it ends by listing every place the
earlier plan was wrong, *including where it was wrong in our favour*. Do the same
here, against the skill.

**What the cold read has already fed back.** Three edits the skill and its
references now carry, all from phases 1 and 2:

* **Enumerate maps by directory scan, never by range.** Silver Blades,
  Champions and Death Knights have no `GEO00` and start at `$10` or `$20`.
  `goldbox/areas.py` says so at the top of its module docstring.
* **The save container's geometry is a per-title constant with three values,
  not six.** `goldbox/games.py` is the table.
* **`spells_known` is at least eight bytes in the later titles.** Recorded in
  `goldbox/layout.py` against the field itself, where anyone reading the record
  will see it.

**What phases 3-5 owe the skill.** These are the edits the run earns;
The checklist was another agent's file while this was written, so
they are listed here rather than made.

| what the run showed | the edit it earns |
|---|---|
| **"Prefer the value the game displays over the value you believe it stores" does not survive.** On Silver Blades the display lagged and `$C04B` was right every time | weaken the rule to *find which copy is live on this title by moving and watching, and do not assume it is the one that reaches the disk* — with the `$49C0` lesson kept as the Pool of Radiance case and this as the counterexample |
| **The address the save writes need not be the address the game reads.** `$4BC0` did not move across six steps and two turns | say so where the `$49C0` lag is described. "Lags a move" is the mild version of this failure; "does not move at all" is the severe one, and both look identical for the first step |
| **The resident `GEO` is at `$0400` in a third title** | promote it: two games was a pattern, three is the rule. The loader does not relocate the map block |
| **The save-image search worked in one step, exactly as written** | promote it too. Comparing the live region against a save the game had just written gave the base with 25 bytes of difference, all of them the loaded-file cache |
| **A refused move costs no time here** | the skill says the cost of a bump is unmeasured. It is measured now, for one title: zero. Keep the "unmeasured" wording for the others |
| **A D64 written by a driven session must be flushed before it is read** | a new hazard row. It is not in the list, it looks exactly like a corrupt file, and it made a working import answer `CHARACTER NOT FOUND` |
| **`spells_known` is sixteen bytes on this engine** | the per-game constants table gains a row, and `goldbox/layout.py`'s note that "nothing proves it stops at eight" can be replaced by the `GEN` clear loop |
| **The disk prompts and the side letters are per-title** | `INSERT SIDE A` is a letter here where Pool of Radiance uses a digit, and the import and export prompts name the *other* game. A driver that matches Pool of Radiance's wordings answers none of them |

## 7. Out of scope

* **The game's start-up check.** Not discussed, not documented, not in this
  repository in any form.
* **Committing any part of Silver Blades** — code, art, music, manuals, maps,
  scripts, data files, disassembly listings, or a slice of any of them dressed
  as a test fixture. Disks live in `work/`; tests read the player's own.
* **A full `ECL` decode.** Pool of Radiance's took the whole project. Silver
  Blades needs it only if quest flags are ever wanted.
* **An editor UI for Silver Blades.** Phases 2 to 4 have now proven the record,
  so the bar this bullet set is cleared; whether to build one is a separate
  decision and not this document's.
* **Save conversion.** `docs/117-save-conversion.md` is DOS → C64 for Pool of
  Radiance, one direction, and stays that way.
* **The Krynn and Buck Rogers titles.** Different rules sets, separate work.
* **Any second binary-monitor client**, for any reason.
