# The C64 running-effect crosswalk

A character converted while Enlarge is running must regain the same strength
when it expires. Copying DOS's effect data into the C64 magnitude restores the
wrong exceptional strength. Longer spells also need a duration policy: one
C64 byte cannot represent every DOS minute count at the destination clock.

These are measurements for
#600 (The neutral record has no field for an effect's remaining duration or a paladin's cure-disease uses, so a converted character loses both).
No conversion writer is changed. The reader is
[`tools/c64/effectcrosswalk.py`](../tools/c64/effectcrosswalk.py); its checks are
[`tests/records/test_effectcrosswalk.py`](../tests/records/test_effectcrosswalk.py).
Both read the player's engine files; neither reads a saved character as
evidence nor writes game data.

## Duration packing

**CONFIRMED from all three C64 engines:** bits 0–5 hold the count and bits 6–7
select minutes, ten minutes, hours or days. At cast time, a count of 64 or
more is divided by the ratio to the next unit, discarding the remainder,
until it fits. The quotient is combined with `$00`, `$40`, `$80` or `$C0`.

| Title | Packing code and actual load base | Ratio table | Integer division | Id, owner, duration, magnitude arrays |
|---|---|---|---|---|
| Pool of Radiance | `SPELLE04 $A7C9`, base `$A700` | `$A83C`: 1, 10, 6, 24 | `LIBRARY $3F04`, base `$2C48` | `$4900`, `$4940`, `$4980`, `$4B80` |
| Curse of the Azure Bonds | `ECL65 $8116`, base `$8000` | `$8184`: 1, 10, 6, 24 | `LIBRARY $3FE8`, base `$2DC8` | `$4B00`, `$4B40`, `$4B80`, `$4D80` |
| Secret of the Silver Blades | `ECL65 $8116`, base `$8000` | `$8184`: 1, 10, 6, 24 | `LIBRARY $2E93`, base `$2DC8` | `$4B00`, `$4B40`, `$4B80`, `$4D80` |

The stores independently confirm save-payload offsets `0x000`, `0x040`,
`0x080` and `0x280`. The division routine returns the quotient from `$4C/$4D`;
the remainder is separate. The tool reads the table addresses from the
instructions. PRG headers are not the load bases.

**CONFIRMED arithmetic, not a selected conversion policy:** extending that
promotion rule to DOS's 16-bit minutes gives these results. The engine's own
cast starts with a byte count in the spell's unit; the tool applies the same
division rule to the larger DOS input.

| DOS minutes | Packed byte | Count and unit | Maximum minutes |
|---|---|---|---|
| 63 | `$3F` | 63 minutes | 63 |
| 64 | `$46` | 6 ten-minute units | 60 |
| 639 | `$7F` | 63 ten-minute units | 630 |
| 640 | `$8A` | 10 hours | 600 |
| 3839 | `$BF` | 63 hours | 3780 |
| 3840 | `$C2` | 2 days | 2880 |
| 65535 | `$ED` | 45 days | 64800 |

**CONFIRMED for all three titles' camp clock:** for a nonzero count, the
remaining time is `count * unit_minutes - (clock_minutes % unit_minutes)`.
The three camp ageing routines are the same code at three sets of addresses,
all at load base `$0800` except Silver Blades' clock tick, which its
`LIBRARY` holds at base `$2DC8`. The entry stores the elapsed minutes, ticks
the clock a minute at a time and ORs a bit into a wrapped-digit mask; the
sweep skips a slot whose id or duration byte is zero; the per-slot rule takes
the whole elapsed minutes off a unit-`00` count and one off a coarser count
whose digit wrapped. The claim used to be graded on Pool alone, from the two
rests in [133-active-effects.md](133-active-effects.md#the-duration-byte);
what upgraded it is reading the other two engines.

| Title | Camp entry | Clock tick | Per-slot rule | Sweep | Expiry call | Radix table | Digit-bit table |
|---|---|---|---|---|---|---|---|
| Pool of Radiance | `CAMP $1283` | `CAMP $124A` | `$12BE` | `$1299` | `$131F` | `$127E`: 10, 6, 24, 30, 12 | `$165A`: 01 02 04 08 10 20 40 80 |
| Curse of the Azure Bonds | `CAMP $1432` | `CAMP $13F9` | `$146D` | `$1448` | `$14CD` | `$142D`: the same five | `$18AF`: the same eight |
| Secret of the Silver Blades | `CAMP $126B` | `LIBRARY $46B6` | `$12A6` | `$1281` | `$1306` | `$46DF`: the same five | `$46E5`: the same eight |

The radix table is what makes the arithmetic exact: the minute-units digit
wraps at 10 and the tens digit at 6, so the digit one coarser than a unit
wraps on every multiple of that unit in minutes since midnight. The formula
holds while no one camp call passes two boundaries of one digit, which is all
a bitmask can record; rest passes five minutes a call (`CAMP $1D7A`).

**CONFIRMED, and it replaces this page's earlier "remains unmeasured":** a
nonzero byte with a zero count does not expire, it drops a unit. `$12BE`
takes the count into X and `$12D6`'s `DEX` on zero gives `$FF`, so `$12D9`
decrements the whole byte and `$40` becomes `$3F`. A `$40` slot lives for the
time to the next ten-minute boundary and then 63 minutes. A whole zero byte
is still skipped by every ageing routine and never expires.

**CONFIRMED: how much time one byte has left depends on the route, not only on
the byte.** A combat round ages unit `00` and nothing else, on every title --
`COMBAT $221E`, `COMBAT2 $FA72` and `COMBAT2 $F747`, base `$E000` for the
later two, each testing `CMP #$40 / BCS` first -- so an hour-unit effect does
not age in a fight however long it lasts. Walking ages one unit a minute in
Pool and Curse (`DUNGEON $0E0D`, `DUNGEON $0D70`, the same code), the one
matching the coarsest digit that advanced, so a minute-count is skipped in the
minute a ten-minute boundary is crossed and 63 minutes of unit `00` take 70
minutes of walking. Silver Blades' walking rule is not that one: `DUNGEON
$0D95` ages every slot whose unit is the advanced digit's or finer, and a
table at `$0DE5` (60, 6) supplies a larger amount to a caller passing coarser
time, which its walking call at `$0DEA` does not. The source side has no such
split: DOS subtracts the elapsed minutes from an exact `u16` in every route
(`GAME.OVR:0x23F83`, [162-spc-permanence.md](162-spc-permanence.md)).

`goldbox/effects.py` holds the arithmetic -- `remaining_minutes`,
`exact_durations`, `closest_duration` and `longest_duration_within` --
and `tests/records/test_effects.py` checks the closed form against a
minute-by-minute run of the engine's own rule, for every minute and
ten-minute byte at six times of day, and against both driven rests.

Thus 64 minutes at clock phase 0 has no exact byte. At phase 6, `$47` expires
after exactly 64 minutes. `$46` expires after 60 or 54 minutes respectively.
The tool enumerates every exact candidate rather than calling truncation
lossless. DOS's unit and removal test are independently established in
[162-spc-permanence.md](162-spc-permanence.md).

**CONFIRMED arithmetic:** among the 65,535 positive DOS minute values, a fixed
camp-clock phase represents only 213–216 exactly. All values 1–63 fit; a
larger value `m` fits unit `u` only when `m + clock % u` is divisible by `u`
and the quotient is 1–63. Exhausting all 1,440 minute phases gives:

| Exactly representable DOS values | Number of clock phases |
|---|---|
| 213 | 21 |
| 214 | 276 |
| 215 | 702 |
| 216 | 441 |

**DECIDED, function written, no writer calls it yet:** at the destination's
actual camp clock, give a running effect the byte whose camp-clock time left is
nearest the DOS duration, in either direction, so a converted effect may
outlast its source slightly. A tie goes to the shorter time left and then to
the smaller unit. Keep the existing clock and never turn a running effect into
duration zero. Every exact case is preserved and the others are wrong by at most
**720 minutes** at any phase, and by less until the day unit is the only choice
(table below). At midnight 64 minutes becomes 63 (`$3F`), and 3,840 becomes
3,780 (`$BF`); copying the cast-time promotion instead gives 60 and 2,880. `goldbox.effects.closest_duration` is the choice.
`goldbox.effects.longest_duration_within`, the greatest time left that does not
outlast the source, is kept as the measurement of the never-lengthen
alternative, which was not adopted; `duration_census()` reports that
alternative's bound of 1,439 minutes. This concerns camp-clock expiry;
combat and deferred walking expiry still need their own live checks.

**CONFIRMED, and it is what the choice actually costs:** the error is bounded
by the finest unit that can reach the source's remaining time, not by the day
unit, and the day unit is out of reach of the game's own spell rows.

| DOS minutes left | The most the closest byte is wrong by | The most the longest-within byte falls short |
|---|---|---|
| 1 to 63 | nothing, at every time of day | nothing |
| 64 to 630 | 9 minutes | 9 minutes |
| 631 to 3,780 | 59 minutes | 59 minutes |
| above 3,780 | 720 minutes | 1,439 minutes |

Measured over every duration to 4,200 minutes and a stride of 37 above it, at
all 1,440 times of day, in `tests/records/test_effects.py`, which also asserts
that each figure is reached. **The bottom row
needs a duration the three titles' own spell tables cannot produce.** Each
seven-byte spell row holds its duration in the same packed byte the save
does (`CAMP $1430` copies the row; the cast reads its count and unit at
`SPELLE04 $A7B5`), and the tables are at `ECL65 $9900` in Pool, `$97CB` in
Curse and `$9307` in Silver Blades. Their rows use the minute, ten-minute and
hour units; the longest fixed row is Pool's 24 hours, and a level-scaled
count reaches the day unit only past 63 hours, which needs a caster level in
the sixties. What is UNMEASURED is whether an area script can write a longer
duration than a cast can, which the DOS word allows to 45 days: reading the
`ECL` opcode that adds an effect would settle it.

The six `CHRDATJ` records on this machine hold a Bless with two minutes left,
which is the top row: exact at every time of day under either rule.

## Pool of Radiance ids and values

**CONFIRMED scope:** DOS Pool version 1.3 `GAME.OVR` and unpacked `START.EXE`,
compared with C64 Pool `ECL65`, `CAMP`, `SPELLE04`, `SPELLE01` and `SPELLE65`.
The separate later-title measurements below replace the earlier blanket
unknown; Pool's rules are not their defaults.

`CAMP $1430` indexes seven-byte spell rows at `ECL65 $9900`.
DOS `GAME.OVR:0x27A4C` reads the effect id at `DS:$3204 + spell*16`, with
`DS=$0C7C`. Across spell positions 1–56, **55 effect ids agree, including
zero-effect rows**. Prayer, spell 42, has DOS id 49 at unpacked image
`0xFC64` and C64 camp id 35 at `ECL65` payload `0x122`.

| Effect | Confirmed value relationship | Code evidence |
|---|---|---|
| Generic caster-level effects: 1, 5, 8, 9, 10, 16, 17, 19, 20, 24, 25, 37, 41, 45, 46 | The spell-table ids agree; the ordinary cast writes the caster's level as data/magnitude | DOS `0x2791B`, `0x27920`, `0x27A5A`, `0x2BDE6`; C64 `SPELLE04 $A825–$A82D`; camp handlers `$A858` and `$A85E` |
| Enlarge 12 and Strength 38, one unstacked restore node | DOS data 1–101 becomes C64 low bits `data - 1`; data 102–127 is unchanged | DOS encoder `0x2BFCE`, decoder `0x2BFF7`; C64 `SPELLE04 $AD0B` and combat `SPELLE01 $A823` |
| Friends 14 | Old charisma is the value on both ports | DOS handler `0xF231`; C64 `SPELLE04 $AD27`, combat `$A83F` |
| Mirror Image 28 | The remaining image count is the value on both ports | DOS `0xF627`, decrement `0xF670`; C64 `SPELLE01 $A8FD`, decrement `$A915` |
| Haste 39 | Preserve data bit 4: it means the character has already aged | DOS `0xF8B3`, `0xF8C2`, `0xF8EF`; C64 `SPELLE01 $A981`, `$A986`, `$A98B` |
| Prayer 49 in combat | C64 magnitude bit 6 is **one minus** DOS data bit 4 for the equivalent allegiance test | DOS `0xFF1A`, equality bonus and inequality penalty at `0xFF30`; C64 `SPELLE01 $A9BF–$A9CF`, opposite comparison |
| Removal flag | DOS node byte 4 is separate; C64 magnitude bit 7 enables the expiry handler | DOS `0x2AF70`; C64 `CAMP $132A/$132D` |

Every row is **CONFIRMED from code for the named value or branch**, not a
claim that every possible record of that id converts independently. For the
measured seven-bit values, a separate DOS boolean becomes
`magnitude = value | (flag << 7)`; it must not erase Haste's existing bit 4.

DOS encodes 18/98 as data 99, while C64 encodes it as low bits 98. With the
restore flag, the C64 magnitude is `$E2`, corroborated by the earlier live
Enlarge measurement. The boundary matters: DOS data 101 means 18/100,
while C64 low bits 101 mean ordinary strength 1. Ordinary strength 15 uses
115 on both ports, then `$F3` with the restore flag.

## Negative results and remaining work

| Finding or gap | Grade and next bounded check |
|---|---|
| A raw DOS data byte is not a C64 magnitude | **CONFIRMED:** exceptional strength differs by one, and Prayer uses a different allegiance bit and polarity. |
| One minutes-only value does not encode every C64 duration | **CONFIRMED:** it omits clock phase, and 64 minutes at phase 0 has no exact candidate among all 252 nonzero-count bytes. A conversion policy is still required. |
| Pool overlapping Enlarge/Strength nodes do not have independent equivalent magnitudes | **CONFIRMED:** DOS `0x2C0D3` finds the active low-bit node, `0x2C129/0x2C12F` parks the displaced boost with bit 7, and expiry `0xF173–0xF227` selects the strongest remaining boost and moves the baseline into it. C64 `SPELLE04 $A8F4/$A8FA` updates current strength, then `$A8FD/$A904` searches ids 38/12 and `$A902/$A909` returns at `$A911` if either exists, retaining its earlier timer. A future writer needs the entire DOS chain, including permanent item nodes, and a timeline policy; translating the bytes independently is insufficient. |
| Pool Prayer can retain individual character ownership | **CONFIRMED combat route:** `LIBRARY $3FEF/$3FF8/$3FFD` compares id and owner; `$4000` accepts the matching party slot. `COMBAT $28A4`, base `$0800`, supplies that slot; `SQRPACI01 $077A/$0791/$0797`, base `$0400`, reaches id 49's handler. Preserve a DOS character's id 49 with its corresponding C64 party slot; no merge is required to reach the equivalent handler. |
| A global Prayer row is not proved equivalent to those individual rows | **CONFIRMED distinction:** camp spell 42's flag `$80` takes `SPELLE04 $A704` to `$A710`'s owner `$FF`; `CAMP $1415` and `SPELLE04 $A81C` store it with id 35. The predicate accepts a negative owner for any queried combatant (`LIBRARY $3FFB`). Combat check lists 10/12 ask id 49; none of the 20 lists asks 35. Merging per-character id 49 rows into `$FF`/35 is unsupported. |
| Id 13 is not a proven strength mapping | **CONFIRMED negative:** the C64 combat dispatch shares id 14's charisma handler; DOS points it at the empty handler `0x11DF6`. Do not infer its value rule from the name Reduce. |
| Later Strength, Enlarge and Friends data | **CONFIRMED reason not to copy Pool's restore rule:** DOS Curse's id 12/38 handler at `0x1024E` and id 14 at `0x1029C` immediately return; Silver Blades' corresponding handlers are `0x1126E` and `0x11297`. C64 recomputes abilities from the base and active modifiers: Curse `ECL65 $913B/$9160`, Silver Blades `$9612/$9637`, base `$8000`. The complete modifier crosswalk is **UNKNOWN**; see [201-the-two-ability-arrays.md](201-the-two-ability-arrays.md). |
| All ids not listed as a measured mapping | **UNKNOWN:** neither a shared number nor a shared spell name proves the data encoding. |

## Later-title value rules

**CONFIRMED, the named value or branch only:** the tool follows the DOS
handler-table pointer separately for each title and checks each C64 pointer
in `COMBAT2`, loaded at `$E000`. Curse's low/high tables are `$EE2A/$EEBC`;
Silver Blades' are `$EF90/$F001`. Their handlers run in `COMBAT` at `$0800`.

| Title and effect | Value relationship | DOS `GAME.OVR` / C64 `COMBAT` evidence |
|---|---|---|
| Curse, Haste 39 | Preserve bit 4, the already-aged marker | Test/set/age `0x10A99/0x10AA8/0x10AD5`; `$220B/$2210/$2215` |
| Silver Blades, Haste 39 | Preserve bit 4 | `0x11CE0/0x11CEF/0x11D23`; `$275C/$2761/$2766` |
| Curse, Prayer 49 | C64 bit 6 = DOS bit 4, **without Pool's inversion** | DOS equality bonus, `0x110BD–0x110F3`; C64 equality bonus, `$226A–$227A`, `BEQ $225D` |
| Silver Blades, Prayer 49 | C64 bit 6 = DOS bit 4 | `0x122C8–0x12302`; `$27C3–$27D3`, `BEQ $27B6` |
| Silver Blades, Mirror Image 28 | C64 count = DOS data >> 4 | DOS `0x117D7/0x117DA` extracts the upper nibble, `0x117DF` decrements it, `0x11816/0x11818` preserves the lower nibble; C64 `$25FB/$260E` reads/decrements the whole magnitude |
| Curse, Mirror Image 28 | **UNKNOWN mapping; CONFIRMED mismatch** | DOS `0x10638/0x1063A` divides data by 16 for selection but `0x1067F/0x10686` decrements/tests the raw byte. C64 `$20DF/$20F2` uses one whole-byte count. Mapping the upper nibble preserves selection but not the decrement; copying the byte preserves the decrement but not selection. |

For example, Silver Blades data `$4F` means four images, so its C64 magnitude
is `$04`, not `$4F`. The lower nibble is retained by the DOS decrement but is
not part of the image count. Curse's discrepancy is a mapping failure to
resolve, not a claim here that an ordinary cast reaches a game defect.

## Next bounded experiment

**The next owner is an emulator-runner for the existing Pool driver, then a
senior analyst for the Strength timeline design.** No emulator was started
and no new driver was written for this stage. To test the candidate "clear
the restore flag on a dormant node", run `effectdrive.py` pooled, headless
and silent, with `--save PORSAVE13.D64 --steps 0 --rest 0 --rest-hours 0
--stage 0=0C:02:01:F3,1=26:02:20:75`. The driver copies the registered disk.
At its `camped` capture, require id 12 to have expired and id 38 still to be
present. Expected: slot 2 has strength 15, whereas DOS would activate the
dormant 17 encoded by `$F5`. Capture every effect array, STR/percentile,
clock and expiry-handler hit counts. If the two expiry preconditions do not
hold, the run is inconclusive. Stop after that camp entry or the existing
boot timeout; preserve outputs outside the repository. This tests one
independent-node translation, not a timeline converter.

**Prayer's global-row equivalence needs a new combat driver.** Stage id 49
on one party slot only, one minute left, magnitude `$40` for DOS side 0;
stage a second otherwise identical run with owner `$FF`, and a third with
id 35/owner `$FF`. Through the Pool combat harness, observe the first id-49
predicate query for the staged party member, a different party member, and
an enemy, at `LIBRARY $3FE4` and its return. Capture requested id `$6E6E`,
chosen effect slot
`$6E78`, owner array, target slot `$6DB4`, side `$6C0C`, and bonus accumulators
`$2AFE/$2B10` before/after `$A9B9` when the predicate succeeds; a rejected
query is itself a result. Stop at those three observations or after
one combat round, with a five-minute wall-clock cap. Until that driver is
specified and built, preserve individual ownership and leave merging unknown.

Reproduce the static readings with `.venv/bin/python
tools/c64/effectcrosswalk.py`; select either later title with `--title`.
Use `--clock-minutes` for the duration census at a particular phase. The tool
finds each title's C64 disks through the registry/path helper and its DOS
engine through the archives registry. It reports missing files; the tests
skip without the player's disks. Mutation checks reject changed owner tests,
Strength branches, Prayer polarity, Haste markers and Mirror Image shifts.
