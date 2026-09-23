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

## The later titles' ability effects, and which byte of the DOS pair they touch

**CONFIRMED, and it replaces this page's "the complete modifier crosswalk is
UNKNOWN":** Curse and Silver Blades keep the permanent score at record `0x065`
and the score in force at `0x014`, and rebuild the second from the first plus
the running effects ([201-the-two-ability-arrays.md](201-the-two-ability-arrays.md),
the recompute at Curse `ECL65 $9160` and Silver Blades `$9637`). So the
magnitude says **how much the effect adds**, where Pool's says what score to
put back. Every cast packs it the same way -- the bonus **one less than
itself** in the upper nibble, the caster's level in the low one, bit 7 set
(Curse `ECL65 $8241`, Silver Blades `$828A`) -- and the recompute reads
`(magnitude & $7F) >> 4` (Curse `$9797`, Silver Blades `$99EA`) and applies one
more step than it finds.

| Effect | DOS data | C64 magnitude | Code evidence |
|---|---|---|---|
| Strength 38 | `100 + steps`, the class die's roll | `$80 \| (steps - 1) << 4 \| level` | DOS cast Curse `0x30C8A`-`0x30DAB`, Silver Blades `0x2F5D2`-`0x2F5F1`, both `add ax, 0x64` before `add_affect(38, …, flag 1)`; C64 Curse `ECL65 $828D`, Silver Blades `$82D6`; the recompute's step loop Curse `$9175`-`$91B8`, Silver Blades `$9647`-`$968A` |
| Friends 14 | `2d4`, the bonus itself | `$80 \| (bonus - 1) << 4 \| level` | DOS cast Curse `0x30199`, Silver Blades `0x2E9DF`; C64 Curse `$8231`, Silver Blades `$827A`; the charisma recompute adds `nibble + 1` at Curse `$9733`-`$9741`, Silver Blades `$9990`-`$999E` |
| Enlarge 12 | the **enlarged score**, in the one-byte score encoding below | `$80 \| level`, level capped at 10 | DOS cast Curse `0x2FFBB`-`0x300A5`, Silver Blades `0x2E7FA`-`0x2E8FA`: the ladder's own target score goes to `0xE3:0x75`/`0x145:0x75`, which hands back that score encoded; C64 Curse `$8214`, read at `$91D1` as `magnitude & $0F` capped at 10 |

**CONFIRMED: both ports enlarge to the same ten scores.** The C64 table at
Curse `ECL65 $9223`/`$922F` and Silver Blades `$96E9`/`$96F5` reads `18/00,
18/01, 18/51, 18/76, 18/91, 18/100, 19, 20, 21, 22` (and two more, 23 and 24, a
cast cannot reach), and the DOS ladder of `cmp al, <level>` tests at Curse
`0x2FFCD`-`0x3004B` writes the same ten. So the level a converted Enlarge needs
reads off its own node's score, decoded: a DOS node exists only where the spell
actually raised the score (`0x30068` skips `add_affect` when it did not).

### The DOS record holds the base, so nothing is walked back down

**CONFIRMED in both engines, and it replaces this page's "a DOS record holds
one set of abilities -- the boosted one":** a later DOS record keeps the
permanent score and the score in force side by side, exactly as the C64 does --
permanent at `0x010`, `0x012` … and in force at `0x011`, `0x013` …, with the
percentile the other way round
([204-the-dos-ability-pair.md](204-the-dos-ability-pair.md)) -- and **no ability
cast writes either byte.** What changed is reading the three casts to their
`retf` rather than reading the routine they call by its name.

| what was read | Curse | Silver Blades |
|---|---|---|
| Strength, Enlarge and Friends casts: stores through `es:di` into the record | 0 in `0x30C10`-`0x30DC1`, `0x2FFBA`-`0x300DD`, `0x3018F`-`0x301D4` | 0 in `0x2F477`-`0x2F607`, `0x2E7FA`-`0x2E92F`, `0x2E9D4`-`0x2EA25` |
| the routine every cast calls first, and its only store | `0x3674A`, one store, through its caller's own local at `[bp + 6]` (`0x36781`) | `0x372FC`, one store, `[bp + 6]` (`0x37333`) |
| what that routine compares, which is why it is a question and not a setter | `cmp al, es:[di + 0x10]` `0x36756`, `cmp al, es:[di + 0x1d]` `0x36768` | `0x37308`, `0x3731A` |
| the recompute each cast ends by calling, with the ability index | `lcall 0xe3, 0x8e` = `0x368FB`; index 0 at `0x30DB9` and `0x300B3`, index 5 at `0x301CC` | `lcall 0x145, 0x8e` = `0x374A8`; `0x2F5FF`, `0x2E8FA`, `0x2EA1D` |
| the recompute's seed | `es:[di + 0x10 + 2 * index]` `0x3692F`, `es:[di + 0x1d]` `0x36939` | `0x374D9`, `0x374E3` |
| every record byte the recompute writes | `0x11`, `0x13`, `0x15`, `0x17`, `0x19`, `0x1B`, `0x1C`, and hit points `0x78` and flag `0x1A4`: 14 stores, none permanent | the same seven, with `0x70` and `0x1B5` |

**CONFIRMED, and it closes this page's earlier "UNREAD: what DOS Curse restores
when a Strength node expires":** the removal routine recomputes. After
unlinking the node it tests the removed id and calls the same recompute --
charisma for id 14 (`cmp byte ptr [bp + 0xa], 0xe` at `0x35244`, `mov al, 5`,
`call 0x368fb`) and strength for 12, 38 and 146 (`0x35257`, `0x3525D`,
`0x35263`, then `mov al, 0` and `call 0x368fb` at `0x3526F`-`0x35273`). Silver
Blades is the same code at `0x35F91`-`0x35FC0` with 113 for 146. So nothing is
put back at expiry: the in-force byte is rebuilt from the permanent one with
the node gone, and id 38's empty mode-1 stub at `0x1024E` is the right handler
rather than a gap. No driven run is needed to say what a DOS player sees.

**So the 18/100 case does not exist, and `goldbox.effects.lower_strength` is
deleted.** The DOS cast does clamp its arrival percentile to 100 (`cmp byte ptr
[bp - 5], 0x64` at Curse `0x30D57`, Silver Blades `0x2F59D`) and its node does
keep `100 + the die roll` rather than the steps the clamp let through
(`0x30D87`, `0x2F5CD`), so a boosted score still says nothing about the base --
34 of the ladder's 176 base-and-boost pairs arrive at 18/100. That is now a
statement about a score rather than a loss, because the base is in the record's
own `0x010` and no writer has to reconstruct it. A converted character's C64
`0x065` comes from `abilities_second`, which `dos_codec.to_neutral` already
reads and `c64_codec.write` already copies.

**CONFIRMED: one byte carries a whole score, and both node encodings go through
it.** The engines' encoder and decoder are Curse `0x366D2`/`0x366FB` and Silver
Blades `0x37282`/`0x372AB`: `data = strength + 100`, or `percentile + 1` at
strength 18; decoding reads `data & $7F` of 101 or less as `18/(data - 1)` and
anything larger as `data - 100`. The recompute **adds** a Strength node's
decoded value to the seed (Curse `0x36B7D`-`0x36B8B`, Silver Blades
`0x37734`-`0x37742`), which is what makes `100 + roll` an increment; it does
**not** add an Enlarge node's, which goes straight to the "keep the larger
score" merge (Curse `0x36793`, Silver Blades `0x37345`), which is what makes
that node an absolute score. The ten Enlarge levels encode to `$01`, `$02`,
`$34`, `$4D`, `$5C`, `$65`, `$77`, `$78`, `$79`, `$7A` and decode back exactly.
`tools/c64/effectcrosswalk.py`'s `later_node_score`, `later_node_data`,
`record_stores` and `confirm_later_ability_pair` are the readings, with the
five-site mutation check in `tests/records/test_effectcrosswalk.py`.

`goldbox/effects.py` holds the C64 arithmetic -- `later_ability_magnitude`,
`later_ability_bonus`, `raise_strength`, `enlarge_level`, `mirror_image_count`.
`tests/records/test_effects.py` pins each against the byte it produces, written
out (`later_ability_magnitude(4, 6)` is `$B6`, and each of the ten Enlarge
levels is its own case), and separately against the operands the tool reads off
the disks: the cast's own `DEX` before the packer, the recompute's ladder step
and self-modified loop count, the DOS cast's closed form and its clamp, and the
ten entries of the DOS Enlarge ladder decoded from its `cmp al, <level>` tests
rather than the first of them. `enlarge_level`'s own docstring still says the
level reads off the record's strength; the finding above makes it the node's
decoded score, and the sentence is one line in a function this page's stage did
not own.

**PROBABLE, a DOS defect a player can reach: a Strength spell that rolls a 1
gives 18/100.** The cast rolls `1d4`, `1d6` or `1d8` by class (Curse `0x30C44`,
`0x30C8C`, `0x30CBD`, through `dice(count, sides)` at `0x363A3`, which returns
`random(sides) + 1` per die) and stores `100 + roll`. A roll of 1 makes the byte
101, which the decoder above reads as 18/100 rather than as one step, so the
recompute hands the target the maximum exceptional strength for the spell's
duration -- and a magic-user reaches it too, because the merge takes the
decoded percentile when the class ladder refuses the exceptional path. It is
PROBABLE rather than CONFIRMED because it is an argument from two routines and
nobody has cast the spell: casting Strength on a fighter at 15 under DOSBox
until a 1 comes up and reading the sheet settles it. Encoding a strength of 1
gives the same 101, which is the one collision in the byte.

**PROBABLE, and it is why a converted character's percentile may not match:**
the recompute's exceptional-strength arithmetic reads the **in-force**
percentile it is about to overwrite, `mov al, byte ptr es:[di + 0x1c]` at Curse
`0x36BE8` (Silver Blades `0x3779F`), rather than the permanent `0x1D` it seeded
from. With a live Strength node on a character at permanent 18/xx, each of the
recompute's 25 call sites in Curse pushes `0x1C` up by ten per step until the
clamp at `0x36BF3` holds it at 100. The C64's recompute climbs its ladder from
the permanent array, so the two ports disagree about a running boost's
percentile; the fields themselves convert exactly and the destination's own
recompute is what a player then sees.

**CONFIRMED, a difference between the ports at high caster level: the DOS
Enlarge ladder's last test is `cmp al, 0xb`, so levels 10 and 11 share the 22
entry and a level of 12 or more matches none of the ten tests, where the C64
clamps the level at 10 and gives 22 (`$91D6`: `CMP #$0A`).** What that fall-out
case actually stores or shows is **NOT ESTABLISHED**, and this page used to
read it as "the 18/00 the cast started with" -- `docs/50-experiments.md` and
commit dc6e1de6 (Show the DOS ability cast writes the in-force byte only, so
the capped 18/100 case is not a conversion loss, #600 (The neutral record has
no field for an effect's remaining duration or a paladin's cure-disease uses,
so a converted character loses both)) since found, in a
separate part of this same ability system, that the DOS ability record keeps a
**permanent** score and an **in-force** one as distinct bytes, and that at
least one cast writes only the in-force half. Enlarge's own recompute has not
been re-read in light of that split: whether the level-12-or-more case reads
the permanent score, the in-force one, writes neither and leaves the prior
in-force value standing, or does something else, is unread. It changes nothing
about a conversion, because the level a converted Enlarge needs is read back
off its own node's score rather than from the caster, and both ports then
agree on what that score is once written.

**Which title a player can meet it in: Silver Blades only, and the ladder's top
rung says why.** This reachability question was resolved by reading each
title's own experience table, in the loader image where the trainer indexes
it -- a run of `u32` thresholds ended by `0xFFFFFFFF`:

| title | magic-user thresholds in `START.EXE` | last level | C64 `GEN` class ceiling |
|---|---|---|---|
| Pool of Radiance | `0x1097B`, 2,501 to 40,001 | 6 | 6 (`$1E5C`) |
| Curse of the Azure Bonds | `0xF06A`, 2,501 to 375,001 | **11** | 11 (`$15A1`) |
| Secret of the Silver Blades | `0x13233`, 2,501 to 1,875,001 | **15** | 15 (`$17D0`) |

So the ladder's last test, level 11, is exactly Curse's magic-user ceiling: the
cast was written to cover every level a Curse caster can hold, and no Curse
party can fall out the bottom of it. Silver Blades raised the class to 15 and
shipped the ladder unchanged, which is where the fall-through becomes something
a player can reach. A human magic-user has no racial limit below the class
ceiling in either title (`goldbox/levels.py`, `racial_limits`), so nothing
else stands in the way. **CONFIRMED** from the two ports' own tables that a
Silver Blades party can reach a caster level the ladder does not cover; what
is not measured is whether a Silver Blades playthrough accumulates the 750,001
experience level 12 asks for, and the highest magic-user among the 86 DOS
Silver Blades records on this machine is level 8 -- all of them ours or the
archives' early-game shipped party, so that is a statement about our records
rather than about the game.

**This finding used to sit in `goldbox-bugs.md` as entry 18, "A DOS
magic-user of level 12 or higher who casts Enlarge gives the target the
weakest Strength the spell can give, not the strongest", marked CONFIRMED.**
It moved out this session: the reachability half above still holds, but the
entry's claim about the actual displayed outcome does not meet
`goldbox-bugs.md`'s bar of a confirmed, player-visible result, given the
permanent/in-force split above. **Next step, not yet taken:** read Enlarge's
own recompute call at DOS Silver Blades `0x2E80D`-`0x2E88B` and its caller,
asking specifically which half of the ability pair it reads and writes for a
caster past level 11 -- the permanent byte, the in-force byte, both, or
neither -- before restating any claim about what a player would see on the
character sheet.

## Which slot a converted effect takes, and who owns it

**CONFIRMED from all three engines, which share one allocator:** Pool of
Radiance `LIBRARY $3FE4`, Curse `$409F` and Silver Blades `$3854` are the same
code. It takes an id in A and an owner in X, walks **slot 63 down to 0**, and
matches the first slot whose id is the one asked for and whose owner is either
the one asked for or negative; `$4005`/`$40C0`/`$3875` return carry clear for
no match. Each cast calls it twice (Pool `SPELLE04 $A7F1` and `$A80E`, the
later titles `ECL65 $813E` and `$815A`): once for the pair it is about to
write, then with id 0 and owner `$FF` for a free slot.

| | what the engine does |
|---|---|
| slot | the **highest-numbered** slot whose id is zero; with none free the cast silently does nothing (`$A811`, `$815D`) |
| owner | the party slot for a per-character effect, `$FF` for one the party carries; **any** owner with bit 7 set answers every query, because the test is a `BMI` (`$3FFB`, `$40B6`, `$386B`) |
| duplicates | a **cast** writes at most one slot per (id, owner) pair -- Pool expires the old slot through `CAMP $131F` and takes a fresh one, the later titles overwrite it in place. The arrays themselves hold as many rows of one id as a writer puts in them |
| which of two | the four tests below |
| a zero value | never reaches a magnitude: the writer substitutes the caster's level for a value byte of zero (Pool `$A825`, the later titles `$8171`) |

**CONFIRMED, and it replaces this page's "the numerically larger duration byte
wins":** that is the rule for two nonzero bytes, and the two zero cases go
opposite ways. Pool `SPELLE04 $A7F6`-`$A805` and the later titles' `ECL65
$8143`-`$8154` are the same four tests, and each branch's target is read here
rather than assumed.

| the two duration bytes | what happens |
|---|---|
| the new one is zero | the new cast takes the slot -- a permanent effect always writes |
| the old one is zero and the new one is not | the old slot is kept and the cast does nothing |
| the old one is larger | the old slot is kept, magnitude and all |
| equal, or the new one is larger | the new cast takes the slot |

The comparison is on the byte, so `$41` beats `$3F` and lasts a tenth as long.
`goldbox.effects.free_slot`, `slot_for` and `replaces_slot` are those walks,
and `tools/c64/effectcrosswalk.py`'s `confirm_slot_rule` and `slot_compare`
read the operands and the branch targets back off the player's disks for all
three titles.

**Negative result, CONFIRMED:** no saved specimen corroborates the allocation
order. All 32 `SAVEDGAME0` images on this machine's registered C64 disks carry
a zero id in all 64 slots, so the rule rests on the code alone. Casting one
spell in a driven session and reading which slot it lands in would corroborate
it; the existing `tools/c64/effectdrive.py` stages slots rather than casting.
`tests/records/test_effects.py` re-takes that census on whatever disks the
machine running it has, rather than trusting the count.

## Pool expires one slot at a time, for that slot's own owner

**CONFIRMED from the bytecode, and it withdraws this page's earlier claim that
two overlapping strength boosts are a thing C64 Pool cannot hold:** the cast is
the only part of the engine that refuses a second node. Everything that ages,
expires and restores works a slot at a time.

| where | what it does |
|---|---|
| `CAMP $1299` | walks slot 63 down to 0, skipping a slot whose id (`$4900,X`) or duration (`$4980,X`) is zero, ages the byte at `$12BE`, stores it back, and calls `$131F` for each slot whose byte reached zero |
| `CAMP $131F` | takes **that slot's** id into `$6E6E` and zeroes it, reads **that slot's** magnitude (`$4B80,X`) and returns at `$133E` unless bit 7 is set, then reads **that slot's** owner (`$4940,X`) |
| `CAMP $0FC8` | stores the owner in `$6DB4` and loads that character (`JSR $4415`) unless it is negative, so the restore lands on the slot's own owner |
| `CAMP $12F8` | finds the id in a 24-entry table and calls its handler with the magnitude in A. The table is immediately after `ECL65`'s 469-byte spell rows: ids at `$9AD5`, handler low bytes at `$9AEE`, high at `$9B06` |
| `SPELLE04 $AD0B` | the restore itself: `AND #$7F`, and a value below 101 is the percentile at strength 18 while 101 or more is `value - 100` with percentile 0. It reads no other slot |

**Ids 38 and 12 both point at `$AD0B`**, read off the player's own `ECL65`. So
a converted character can carry two strength restores with their own expiry
times, and where both reach zero in one camp call the sweep runs the
higher-numbered slot first, which puts the later-expiring node in the
lower-numbered slot. Neither Prayer id is in that table at all: an effect with
nothing to put back expires with no handler call.

PROBABLE that a staged pair behaves that way in the running game -- no save on
this machine carries a nonzero effect id, so nothing corroborates it from a
specimen. One driven run settles it, with no new driver: `POR_HEADLESS=1
tools/c64/effectdrive.py --steps 0 --rest 5 --stage
62=26:02:01:E2,61=0C:02:05:F3` on a copy of the registered `PORSAVE13.D64`,
one ENCAMP, then the abilities and the four arrays. Slot 62 expires first and
must leave strength 18/98 with slot 61 still present and still counting; a
second camp must leave 15. A restore from the wrong slot, or one expiry
clearing the other, refutes it.

## The later titles' caster-level ids

**CONFIRMED from both ports' code, for Curse and Silver Blades alike:** for
the ids below, a running DOS node's data byte converts to the C64 magnitude
unchanged, a node per row, owned by that character's party slot.

| Title | Ids |
|---|---|
| Curse of the Azure Bonds | 1, 5, 8, 9, 10, 16, 17, 19, 20, 24, 37, 41, 45, 46, 63, 69 |
| Secret of the Silver Blades | 1, 5, 8, 9, 10, 16, 17, 19, 20, 24, 37, 41, 45, 46, 57, 63, 69 |

An id is in the table when all four of these hold:

* **The C64 writes the caster's level.** Every C64 spell row naming the id
  (`ECL65 $97CB` in Curse, `$9307` in Silver Blades, seven bytes a row) goes
  to `$819C`, the single-target writer, or `$81A2`, which writes one row for
  each party slot present, 7 down to 0. Both end in `$80EE`. That code is the
  same in both titles, with only the globals moved. The id is row byte 3, the
  owner is the target's party index (`$2C61`; `$2AD4` in Silver Blades), and
  the magnitude is the override byte `$2BFC` (`$2A6F`), or the level `$2BFB`
  (`$2A6E`) when the override is zero (`$8171`). `CAMP $1566` zeroes the
  override before each camp cast. `CAMP $16E2` sets the level from row byte
  2, bits 2-3: 0 selects the magic-user level, max(MU, ranger − 8); 1 the
  cleric level, max(cleric, paladin − 8); 2 the druid level, ranger − 7
  (`CAMP $1660`; the record's levels run MU, cleric, … paladin `0x0CF`,
  ranger `0x0D0`).
* **DOS writes the caster's level.** Every DOS spell naming the id is a
  wrapper that pushes a level override of zero into the shared routine
  (Curse `GAME.OVR:0x2EF34`, Silver Blades `0x2D691`). Bless filters its
  target list first (`0x2FC55`, `0x2E4A3`) and then does the same. With no
  override, the level comes from the **caster's** record (Curse `0x39F14`,
  Silver Blades `0x3AFD7`). By the spell row's class byte: cleric is
  max(cleric, paladin − 8), druid is ranger − 7, and magic-user (2 in Curse,
  3 in Silver Blades) is max(MU, ranger − 8). A dual-classed caster adds his
  former levels in that class when `0x3C031` allows it. A caster with no
  spell class gets 6, as does any cast while the flag at `0x757D` (`0x8D99`)
  is set. Class 3 (Silver Blades 4) gets 12. `add_affect` (`0x36412`) stores
  the level at node byte 3 unchanged.
* **The two rows match.** DOS and C64 rows paired by id agree on class, spell
  level and duration formula: per-level count DOS row byte 5 against C64 row
  byte 1, fixed count byte 4 against byte 0. So Shield is DOS spell 19 and
  C64 row 14, both magic-user level 1 at 5 minutes a level. Protection from
  Evil 10' Radius is DOS spells 52 and 69 and C64 rows 33 and 43: magic-user
  level 3 at 2 minutes a level, and cleric level 4 at 10.
* **Only Dispel Magic reads the value, on either port.** DOS `VALUE_READ`
  (`tests/dos/test_dosaffectreads.py`) holds none of these ids. On the C64,
  all 21 absolute-mode reads of the magnitude array `$4D80` in Curse, and all
  20 in Silver Blades, are either Dispel's own read (Curse `COMBAT $18E0`,
  Silver Blades `$1CA4`) or one of three kinds:
  * writers: the cast, the combat writer, `COM.PREP`'s monster rows and a
    Silver Blades `DUNGEON` Enlarge;
  * the camp and combat expiry sweeps, which call a handler only when bit 7
    is set (Curse `CAMP $14D8`, `COMBAT $132F`);
  * code for ids outside the table: the Enlarge read and the bonus-nibble
    helper, whose callers pass 12, 14, 38, 146 and 113, and the combat
    handlers of 28, 32, 35, 39 and 49. Three Curse reads sit after the
    handler entries of 139 and 144, which is how they were attributed.

  A read through a pointer rather than an absolute operand would not show
  in that count.

  Dispel reads the low nibble as the effect's level on both ports, skips
  `$FF`, and uses the same odds: 50%, plus 5% for each level the dispeller
  is above it, minus 2% for each level below (DOS Curse `0x31215`-`0x31270`;
  C64 per `tools/c64/dispelread.py`).

Pool of Radiance's list has 25 and lacks 63 and 69. In the later titles, id
25 also has a row with its own handler (Curse row 55 `$84BA`, Silver Blades
`$851D`) and a DOS spell with its own routine (Silver Blades 116), so it is
not in the table. Prayer, 49, uses the generic writer on the C64 but is in
both ports' read lists.

**PROBABLE, why the only later-title nodes on this machine hold `0A` and
`0B` on level-5 characters: somebody else cast them.** The Archives'
shipped Curse `Default files/Saves` slot B, and the specimen party made
from it, hold these nodes:

* FLORENTZ: Protection from Evil 10' Radius (45) with 47 minutes left and
  data `0A`, and Shield (17) with 2 minutes left and data `0B`;
* BRYTWYN: Shield with 2 minutes left and data `0B`.

The level routine gives no member of that party 10 or 11. FLORENTZ is cleric
5, BRYTWYN magic-user 5 and ORATISI magic-user 3; nobody has a paladin or
ranger level of 9 or more, and every former-level array is zero. At levels 10
and 11 the two spells last 100 and 55 minutes, so both were cast 53 minutes
before the save. At the party's own level 5 they would have been cast 3 and 23
minutes before. That both arrive at 53 is the evidence that the byte is the
casting level and that the duration was computed from it. It rests on one
party. Nothing in a DOS node records who cast it, and the conversion does not
need to know.

## Negative results and remaining work

| Finding or gap | Grade and next bounded check |
|---|---|
| A raw DOS data byte is not a C64 magnitude | **CONFIRMED:** exceptional strength differs by one, and Prayer uses a different allegiance bit and polarity. |
| One minutes-only value does not encode every C64 duration | **CONFIRMED:** it omits clock phase, and 64 minutes at phase 0 has no exact candidate among all 252 nonzero-count bytes. A conversion policy is still required. |
| Pool overlapping Enlarge/Strength nodes do not have independent equivalent magnitudes | **CONFIRMED:** DOS `0x2C0D3` finds the active low-bit node, `0x2C129/0x2C12F` parks the displaced boost with bit 7, and expiry `0xF173–0xF227` selects the strongest remaining boost and moves the baseline into it. C64 `SPELLE04 $A8F4/$A8FA` updates current strength, then `$A8FD/$A904` searches ids 38/12 and `$A902/$A909` returns at `$A911` if either exists, retaining its earlier timer. A future writer needs the entire DOS chain, including permanent item nodes, and a timeline policy; translating the bytes independently is insufficient. |
| Pool overlapping nodes are **unconverted work**, not a limit of the destination | **CONFIRMED that the destination holds them:** the cast refuses a second strength node (`SPELLE04 $A8FD`/`$A904`, returning at `$A911`), and that is all it proves, because a writer is not the cast. Every sweep is per slot -- see the section above -- so two staged slots expire at their own times and each restores its own score. A converted pair therefore reproduces the intermediate step, with the later-expiring node in the lower-numbered slot. What it needs is a value **recomputed from the DOS chain's timeline** rather than each node's byte translated on its own, and three concurrent boosts on one character still have nowhere to go: only ids 38 and 12 reach the restore handler. |
| Pool Prayer can retain individual character ownership | **CONFIRMED combat route:** `LIBRARY $3FEF/$3FF8/$3FFD` compares id and owner; `$4000` accepts the matching party slot. `COMBAT $28A4`, base `$0800`, supplies that slot; `SQRPACI01 $077A/$0791/$0797`, base `$0400`, reaches id 49's handler. Preserve a DOS character's id 49 with its corresponding C64 party slot; no merge is required to reach the equivalent handler. |
| A global Prayer row is not proved equivalent to those individual rows | **CONFIRMED distinction:** camp spell 42's flag `$80` takes `SPELLE04 $A704` to `$A710`'s owner `$FF`; `CAMP $1415` and `SPELLE04 $A81C` store it with id 35. The predicate accepts a negative owner for any queried combatant (`LIBRARY $3FFB`). Combat check lists 10/12 ask id 49; none of the 20 lists asks 35. Merging per-character id 49 rows into `$FF`/35 is unsupported. |
| Id 13 is not a proven strength mapping | **CONFIRMED negative:** the C64 combat dispatch shares id 14's charisma handler; DOS points it at the empty handler `0x11DF6`. Do not infer its value rule from the name Reduce. |
| Later Strength, Enlarge and Friends data | **CONFIRMED, and this row used to read UNKNOWN:** the C64 magnitude is a modifier for Strength and Friends and a caster level for Enlarge, and the two ports encode it differently, so Pool's restore rule must not be copied there. The table above has each id's rule and the code behind it; what changed is reading the three casts and the recompute rather than only the combat handlers, which return immediately (DOS Curse `0x1024E`, `0x1029C`; Silver Blades `0x1126E`, `0x11297`) because nothing in a fight has to do the work twice. |
| A later DOS record has to be walked back down to its base | **CONFIRMED negative:** it holds the base already, at `0x010`, and no cast writes either half of the pair -- 0 record stores in six cast routines across the two engines, and the recompute writes only the in-force bytes. `lower_strength` was written for the mechanism this refutes and is gone. |
| All ids not listed as a measured mapping | **UNKNOWN:** neither a shared number nor a shared spell name proves the data encoding. The later titles' caster-level ids are now measured (section above), which is why this row no longer covers Curse's 17 and 45. |

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
| Curse, Mirror Image 28 | C64 count = DOS data >> 4, the same rule as Silver Blades | The cast at DOS `0x30703`-`0x30715` rolls `1d4` and shifts it up four before ORing the caster's level in; `0x10638/0x1063A` reads that nibble back for the selection roll. C64 `ECL65 $8282` writes a bare `1d4` and `COMBAT $20DF/$20F2` counts it down whole |

For example, Silver Blades data `$4F` means four images, so its C64 magnitude
is `$04`, not `$4F`. The lower nibble is the caster's level and is not part of
the image count.

**CONFIRMED, and it is the one Mirror Image node with no C64 magnitude:** a
DOS Curse node whose count nibble has run down to zero -- `$0F` is a
fifteenth-level caster's spent spell, which its own raw decrement produces --
converts to a count of zero, and zero is not a magnitude the C64 can hold. The
cast substitutes the caster's level for a value byte of zero on its way into
the array, and a slot that did hold zero would absorb nothing and never
expire: the handler asks `random(0..count)` for the image that takes the hit
(`COMBAT $20DF`-`$20E5` through `LIBRARY $2F46`, Silver Blades `$25FB`
through `$2E05`), a zero answer costs no image, and only the decrement that a
nonzero answer triggers ever removes the slot. What a spent Mirror Image
should convert to is a writer's decision nobody has taken;
`goldbox.effects.mirror_image_count` reports the zero and does not invent a
count.

**Curse's raw decrement is a defect in its own handler, not a second meaning
for the byte, and this page used to call the mapping UNKNOWN for that reason.**
What settled it is the cast: both later titles build the byte the same way
(Curse `GAME.OVR:0x30700`, Silver Blades `0x2EF6E`, `dice(1,4)` then `shl 4`),
so the count is the upper nibble in both. Silver Blades then decrements that
nibble and puts the low one back (`0x117D7`-`0x1181E`); Curse decrements the
whole byte at `0x1067F` and removes the effect only when the byte reaches zero.
So in Curse an image is lost on the first absorbed hit and then only on every
sixteenth, and four images absorb up to 64 attacks. That is a bug in DOS Curse
a player can reach by casting the spell -- it is not our misreading, because
its own sibling engine decrements the nibble at the equivalent address -- and
it says nothing about what the byte holds at the moment a save is converted:
the images a player has are what the selection roll reads, `data >> 4`.

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

**What the C64 writer converts, and what it still waits on.** The writer is
built: `goldbox.effects.c64_row` turns a running node into a row of the save's
shared arrays for Pool of Radiance's caster-level ids
(`POOL_CASTER_LEVEL_IDS`) and for each later title's
(`LATER_CASTER_LEVEL_IDS`), and reports any other id by number as unconverted.
`tools/c64/effectcrosswalk.py`'s `later_caster_level_ids` re-reads the later
titles' tuples from the C64 spell rows, the DOS spell rows and the DOS
handlers that read a data byte, and `tests/records/test_effectcrosswalk.py`
pins the constants to it. Still waiting: a timeline conversion for Pool's
overlapping strength nodes, which the destination does hold; the later
titles' Strength, Enlarge and Friends; what a spent Mirror Image converts to;
Prayer, including Pool's party-wide row; Curse's and Silver Blades' id 25,
which has its own row and handler; the ids with no C64 spell row; and the two
ageing routes the camp formula does not describe.

Reproduce the static readings with `.venv/bin/python
tools/c64/effectcrosswalk.py`; a later title's run prints its caster-level ids.
Two of that derivation's four conditions, the DOS override of zero and the
`$4D80` read census, are read by hand and recorded above rather than re-read by
the tool. Select either later title with `--title`.
Use `--clock-minutes` for the duration census at a particular phase. The tool
finds each title's C64 disks through the registry/path helper and its DOS
engine through the archives registry. It reports missing files; the tests
skip without the player's disks. Mutation checks reject changed owner tests,
Strength branches, Prayer polarity, Haste markers and Mirror Image shifts.
