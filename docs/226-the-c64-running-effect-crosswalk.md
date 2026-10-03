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
alternative, which was not adopted; `duration_sweep()` reports that
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

**The flag byte each DOS cast writes, by static read of the push order into
the generic cast.** Enlarge 12: Pool 1 (`0x282BD`), Curse 1 (`0x2FFBA`), Silver
Blades 0 (`0x2E8C9`, into the apply routine `0x37EB0`). Friends 14: 1 in all
three (`0x28430`, `0x301A5`, `0x2E9EB`). Mirror Image 28: 0 in all three
(`0x28AB8`, `0x3072F`, `0x2EF94`). Strength 38: 1 in all three (`0x28F59` and
`0x29EFD`, `0x30C10`, `0x2F477`). The later titles do not read the flag of 12,
14 or 38: their handlers are empty (Curse `0x1024E` and `0x1029C`, Silver Blades
`0x1126E` and `0x11297`), and Curse's `remove_affect` tests it at `0x3518D` only
to skip the handler call before it recomputes by id at `0x35244`-`0x35273`. Pool
item power `0x83` writes a granted 38 (`26 00 00 xx 01`), not a running one.

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
18/01, 18/51, 18/76, 18/91, 18/100, 19, 20, 21, 22` (and two more, 23 and 24;
the DOS cast reaches 23 in Silver Blades only), and the DOS ladder of `cmp al, <level>` tests at Curse
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

**A running Strength converts with its roll, at the destination's own score.**
Data 101 to 108 converts both ways, a roll of 1 included. The byte a DOS cast leaves on a target whose only classes are paladin or ranger (`0x02` in Curse, `0xFC` in Silver Blades) converts as a roll of 8, the most a C64 row holds, with the node's duration and low nibble, and returns as 108. The score in force is
not copied: a DOS source arrives on the C64 at
`effects.raise_strength(permanent, roll)`, the score the C64's recompute gives
and never changes; a C64 source arrives on DOS or the Amiga at
`effects.dos_later_strength(permanent, permanent, data, warrior)`, the score a
cast of that roll gives, from which the destination's own recompute then climbs
a warrior's percentile; an Amiga source arrives on the C64 at the C64's score
the same way. Amiga Curse and Pool of Radiance recompute as DOS does. Amiga
Silver Blades differs in one test: a former fighter, paladin or ranger counts
only above `former_level`, which no record we write satisfies, so there only a
current level makes a warrior, and a dual-classed ex-fighter gets 18/0 where
DOS climbs by tens. A DOS source arrives at
`effects.c64_later_strength_rebuild`, the C64's own merge of its first Strength
row, first Enlarge row, first Giant Strength row and readied items, whatever
other strength sources the character holds; a C64 source with such a source
arrives at the DOS merge of the same nodes, and with a readied strength item or
a granted strength source the score is copied. A score a single Strength node
does not explain (a drain, gauntlets) is copied. C64 to DOS
writes the low nibble a DOS cast carries, so the C64 caster's level is lost.
`confirm_later_strength_arm` pins the DOS arm the model rests on.

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
entry; the C64 clamps the level at 10 and gives 22 (`$91D6`: `CMP #$0A`).**
Past level 11 the two DOS titles differ. Curse's ladder has no arm after its
last test (`0x3004B`, then `0x30050`), so the 18/00 the cast started with
stands, and no Curse caster reaches level 12. Silver Blades' default arm at
`0x2E892` writes 23, which this page had not read and so called NOT
ESTABLISHED. The C64's most is 22, so `effects.c64_row` converts Silver Blades' 23
(data `0x7B`) to the ordinary Enlarge row at 22: the fighter is one point
weaker on the C64 and returns as 22. The other ten scores convert
in both directions, because the level a converted Enlarge needs is read back
off its own node's score rather than from the caster.

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
party can fall out the bottom of it. Silver Blades raised the class to 15, and
its ladder ends with a default arm (`0x2E887 cmp al, 0xb / jne 0x2E892`, then
`0x2E892 mov byte ptr [0x64d8], 0x17`), so a caster of level 12 or more
enlarges to **23** and the node's data is `0x7B`. A human magic-user has no
racial limit below the class ceiling in either title (`goldbox/levels.py`,
`racial_limits`), so nothing else stands in the way. **CONFIRMED** from code
that a Silver Blades party can reach it; what is not measured is whether a
Silver Blades playthrough accumulates the 750,001 experience level 12 asks for,
and the highest magic-user among the 86 DOS Silver Blades records on this
machine is level 8 -- all of them ours or the archives' early-game shipped
party, so that is a statement about our records rather than about the game.

**This finding used to sit in `goldbox-bugs.md` as entry 18, "A DOS
magic-user of level 12 or higher who casts Enlarge gives the target the
weakest Strength the spell can give, not the strongest", marked CONFIRMED.**
It moved out because its claim about the displayed outcome did not meet
`goldbox-bugs.md`'s bar, given the permanent/in-force split above. The read of
Silver Blades' ladder settles it: the ladder ends in a default arm, so a caster
of level 12 or more enlarges to 23, not to the weakest score.

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
| a zero value | never reaches a magnitude: the writer substitutes the caster's level for a value byte of zero (Pool `$A825`, the later titles `$8171`). C64 Pool's camp writer takes `$2879` when it is not 0 and no code clears it within one camp visit, so a camp spell cast after Enlarge, Friends, 26, Mirror Image, 48 or 56 is written with that spell's value (CONFIRMED in a game-written save, see "Pool's stale `$2879`"); Curse (`CAMP $1566`) and Silver Blades (`CAMP $13A2`) zero the override before every cast |

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
`tests/records/test_effects.py` re-takes that sweep on whatever disks the
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
  ranger `0x0D0`). **The party index is `$FF` for some rows, which this
  bullet used to leave out:** `CAMP $158B`/`$1590` store the target selector
  `ECL65 $8037`'s answer in `$2C61`, and target mode 0 (row byte 2 `AND #$03`)
  returns `$FF` at `$805A`, which `$819C` keeps. That covers Detect Magic
  (rows 3, 7 and 47, id 5) and Prayer (row 27, id 49) in both titles, and the
  C64 asks for id 5 only with owner `$FF` (Curse `LIBRARY $4141`, Silver
  Blades `$3899`), so for id 5 the "owned by that character's party slot"
  above gives a row neither game reads -- the defect #668 (A DOS Pool of
  Radiance party under Detect Magic reaches the C64 with a row the game never
  reads, because the converted row belongs to one character and the C64 asks
  only for a party-wide one) describes for Pool.
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
not in the camp-derived table; `effects.LATER_INVISIBLE_ID` adds it, because
that row's handler only sets a duration and then jumps to the level writer. Prayer, 49,
uses the generic writer on the C64 but is in
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

## Combat-cast ids and their rules

**CONFIRMED from both ports' code**, by reading each DOS writer's pushes and
each C64 cast down to its row writer. Static reads only; none has been booted.

| Rule | Titles and ids | DOS node | C64 row | Code |
|---|---|---|---|---|
| magnitude = data, flag 0 | all: 2, 52, 53, 71 | `(id, minutes, level, 0)` | `level & $0F` from the generic combat writer | 2: the Bless area routine into the generic cast, Pool `GAME.OVR:0x28013`, Curse `0x2FD01`, Silver Blades `0x2E54F`; C64 `SPELLE00 $A8A1`, `COMBAT $15E7`, `$188B`. 52: Hold Person's own apply, Pool `0x287DD` (level from `START:0x3262`), Curse `0x2FC41`, Silver Blades `0x2E48F`; C64 `$AA45`, `$17E7`, `$1B84`. 53: spell 21 into the generic cast; C64 `$A9F8`, `$177C`, `$1AF8`. 71: Pool and Curse spell 63 and Silver Blades spell 79; Silver Blades casts 79 through the shared custom cast `0x2E313`, which tests for spell 79 at `0x2E3CA`; C64 Pool `SPELLE00 $AD54` and Curse `COMBAT $1A71` double the level first, and Silver Blades' `COMBAT2` row `04 1C 00 47 41 BF 1F`, Curse's id-7 row with the id changed, runs `COMBAT $1FBF` |
| magnitude = data, flag 0 | Curse and Silver Blades: 3; Curse: 7, 73, 109, 145; Silver Blades: 32, 73, 106 | the same | the same (73: `COMBAT $2283` writes the level through `$1223`) | 3: spell 70, handler reads data as a counter it drains (Curse `0xFFC3`); C64 `$1A85`, `$1F6D`. 7: Curse spell 79, Faerie Fire ("is highlighted"), through the shared custom cast `0x2FAD9`, which tests for spell 79 at `0x2FB92` and holds 52's apply call; C64 `COMBAT2` row `04 1C 00 07 41 EC 1A` runs `COMBAT $1AEC`. 73: Silver Blades spell 95; C64 `COMBAT2` row `00 F0 00 49 3A 83 22` runs `$2283`, which loads `LDX #$49`. 145 and Silver Blades' 32: Dispel Evil (spell 73), below. 106: Silver Blades' Power Word Stun (spell 117, `0x327DC`, data from the level routine `0x3AFD7`); C64 `COMBAT $2389` rolls the same 4, 2 or 1 d4 by hit points and jumps to the generic writer `$0F70` |
| magnitude = data \| `$80`, flag 1 | all: 23, 34 | `(id, minutes, level, 1)` | `level \| $80` | 23 Spiritual Hammer: generic cast flag 1, Pool `0x28A01`; C64 `SPELLE00 $AABF`, `COMBAT $1845`, `$1BF4`. 34 Cause Disease: generic cast flag 1, Pool `0x2938A`; C64 `$ABB9`, `$18A8`, `$1C63` |
| `(0xFF, 1)` = `$FF` | Pool: 4, 7, 62 | `(4, 1440, FF, 1)`, `(7, 43200, FF, 1)`, `(62, 60, FF, 1)` | `$FF` | DOS spell 67 (generic cast `0x2A0E0`, data `FF`, flag 1), then handlers 4 (`0xEE13`) and 7 (`0xEED8`); C64 camp row 67 `SPELLE04 $ACC6`, expiry `$ACCE` and `$ACD7` through `$ADF3` |
| magnitude = data, 0 allowed, flag 0 | Curse: 4, 35, 136; Silver Blades: 4, 35 | `(id, minutes, 0, 0)` | the caster's level | 4: Dispel Evil's node on its caster, spell 73's own apply (Curse `0x32462`, Silver Blades `0x30C3F`); C64 camp row 45 (`ECL65 $83EE`, `$8463`) and `COMBAT $1AB8`, `$1F96`. 35: Confusion, spell 82 (`0x328CB`, `0x30FF7`); C64 `COMBAT $1B81`, `$204D` into the generic writer. 136: Curse spell 78 (`0x3270C`, 10 minutes); C64 `$1AD7` into `$0F9B` |
| magnitude = data \| flag << 7 | Curse and Silver Blades: 27 | `(27, minutes, 0, 0)` or `(27, minutes, level, 1)` | the level (Fumble), or `level \| $80` (Confusion) | Fumble, below |
| `(0xFF, 0)` = 0 | all: 30, 31 | `(30, 1, FF, 0)`, `(31, 1d4 + 1, FF, 0)` | 0 | Stinking Cloud, below |

The custom cast takes the id from the spell's row in the data segment, byte
`0x37E6 + 16 × spell` in Curse (`0x2FC19`) and `0x44A7 + 16 × spell` in Silver
Blades (`0x2E45C`); Pool's row keeps it at `0x3204 + 16 × spell`. Spell 79's
row names 7 in Curse and 71 in Silver Blades, spell 95's names 73 in both,
spell 63's names 71 in Pool and Curse and 0 in Silver Blades, and spell 70's
names 3 in both later titles. The second row used to list the Silver Blades
cast at `0x2E313` and `$1FBF` as "Silver Blades 71" among its evidence for
Silver Blades' 73; both write 71, which belongs to the first row, and Silver
Blades' 73 comes from spell 95. This table used to sit split in two by that
paragraph, which left its last two rows outside it.

The C64 handler for each of these ids reads no magnitude, and neither does the
DOS handler except 3's counter and Pool 62's, which copies the byte into the
node it re-adds every hour (`0x1014F`), so Dispel Magic's low nibble is the
only reader of the value, the same on both ports. A converted row therefore behaves as the
destination's own cast of the same spell. Where the engines differ, as when
C64 Pool and Curse clear 52 and 53 at the end of a fight and DOS does not, the
difference is each engine's own rule. Silver Blades' C64 id-32 handler is the
one exception on the C64 side: it copies the low nibble into `COMBAT2 $F2C9`
for the banishing roll (`COMBAT $263D`-`$2645`), which copying the DOS level
feeds as the C64's own cast does.

**Dispel Evil (spell 73), CONFIRMED from both ports' code.** DOS puts `(4,
level minutes, 0, 0)` on the caster through its own apply and then the
generic cast puts the spell row's id on the targets: 145 in Curse (row byte
10 `0x91`), 32 in Silver Blades (`0x20`). The C64's combat cast writes both
rows on the caster with the level and a duration of the level (Curse `COMBAT
$1AB8`: `LDX #$91`, then `LDX #$04`; Silver Blades `$1F96`: `LDX #$20`, then
`LDX #$04`). So 145 and Silver Blades' 32 do have C64 rows, which #667 (A DOS
party under Prayer, the strength and charisma spells, Mirror Image or an
effect with no C64 spell row is still refused when saved as a C64 save,
because only the ordinary caster-level spells convert) had said they lack: the
combat table names id 4 for spell 73, and the handler writes the second row
itself. The id-145 and id-32 handlers on both ports banish an attacker of the
flagged kind on a failed save and then remove 4 and themselves; the id-4
handlers read no value.

**PROBABLE, a C64 Silver Blades quirk:** the camp cast (row 45, `ECL65 $8463`)
writes 4 and then **145**, Curse's id, not 32 (`LDA #$91 / STA $2AC0`). Silver
Blades' combat handler table has 113 entries, so nothing there answers for 145.
What would settle it: list every constant id Silver Blades' combat check lists
(`COMBAT2 $EF4F` and its neighbours) ask for; no 145 confirms that a camp Dispel
Evil protects only through id 4 on the C64. Coming back to DOS, that row has no
rule (Silver Blades' DOS has no id-145 handler), which is reverse-direction
work on #661 (A C64 party under a running spell loses it on the way to DOS or
the Amiga with no line anywhere, because the C64 reader reads only the
paladin's rows out of the effect arrays).

**Confusion (35), CONFIRMED from both ports' code.** Spell 82 writes `(35,
minutes, 0, 0)` and nothing else; the handler rolls each round and reads no
node byte (Curse `0x108C0`, Silver Blades `0x11AB8`). Its outcomes are other
nodes: 1-10 removes 35 and adds Fear-like `(142, 10, 0, 1)` (Silver Blades 111)
with the record changes Fear makes, 61-80 adds `(137, 1, the side, 1)` (Silver
Blades 107). The C64 handler (`COMBAT $2134`, `$2685`) copies the row's
magnitude with bit 7 set into the override and writes 27, 137 or 142 (Silver
Blades 27, 107, 111) for one round or ten minutes; the ids it derives read no
magnitude, so the value is still only a Dispel level. An earlier reading
that said the C64 "reuses the magnitude as the level of a retaliation cast" and
that DOS takes it from the record misread both: the record byte DOS uses is
the side, and it goes into the id-137 node. A DOS character holding 35 has
no Confusion byte in the record; the record changes belong to the 142 and 137
nodes; 142 converts with its record bytes and 137 is refused. Silver Blades also writes Confusion from its id-70
gaze as `(35, 1d10 + 2, the monster's side, 1)` (`GAME.OVR:0x130CF`). Its
handler returns at once in remove mode (`0x11AC4` to `0x11C7E`), so the flag
does nothing there, and on the C64 bit 7 would run the Confusion roll a second
time at expiry; the converted row keeps the data byte and not the flag, and
comes back with flag 0. That byte is the one this rule does not round-trip.

**Fumble (spell 86, Curse and Silver Blades), CONFIRMED in Curse, the Silver
Blades call sites the same.** The spell rolls a save: a failure applies `(27,
level minutes, 0, 0)`, a success `(42, level minutes, 0, 0)` (Curse `0x32E04`,
`0x32E65`; Silver Blades `0x3142B`, `0x31496`). It then calls the generic cast
with data 0 and flag 1 (`0x32EB8`, `0x314C8`), which rolls a **second** save
for the target and on a failure applies the row's id, 27, as `(27, minutes,
level, 1)`. Curse's apply finds an existing node of the id and removes it
before adding (`0x37364`-`0x373B0`); Silver Blades' only raises the old node's
duration (`0x37F10`-`0x37F48`). So a DOS target ends with `(27, m, 0, 0)`,
`(27, m, level, 1)` (Curse, both saves failed), `(42, m, 0, 0)`, or `(42, m,
0, 0)` together with `(27, m, level, 1)`. The C64 writes one row, 27 or 42
with the level, and skips the 42 for a hasted target (`COMBAT $1CC9`-`$1CEC`).
Both ports' id-27 handlers take the turn away (DOS `0x39E89` clears the combat
record's action bytes; C64 `$2C4E` and Silver Blades `$FD2A` clear four combat
arrays), read no value, and run again at removal when the flag or bit 7 is
set; neither title's camp expiry list holds 27. So 27 converts as `data |
flag << 7` and back, and the slowed rule takes data 0 in these two titles.

**Stinking Cloud (30, 31), CONFIRMED from both ports' code.** The cloud check
writes `(30, 1, FF, 0)` for a save made and `(31, 1d4 + 1, FF, 0)` for one
failed, the same in all three DOS engines (Pool `0x2BACB`, `0x2BB1A`; Curse
`0x35F9F`, `0x3605B`; Silver Blades `0x36B5A`, `0x36C13`). The C64 casts (Pool
`SPELLE00 $AAD3`, Curse `COMBAT $1859`, Silver Blades `$1C08`) pick 30 or 31 on
the same save and write through the row writer with the override the cast
entry cleared (Curse `$0DD9`, Pool `ECL64 $991F`), so the magnitude is 0. No
handler reads either byte. They differ in one thing a player could see: DOS's
`FF` is proof against Dispel Magic, and the C64 dispels its own cloud rows as
level 0 (all three C64 Dispels try 30 and 31). The conversion keeps each
engine's own byte, so a converted party behaves as the destination's own
cloud would. The two duration-0 `(31, 0, FF, 0)` records from handlers 43 and
44 are granted effects and take the other route.

### Charm and Fear keep part of their state in the record

**CONFIRMED from both ports' code.** Charm converts in both directions, and the
conversion has not been run in the game. The C64 then playing him as a charmed
party member is PROBABLE (fight-start placement below; `0x0B8` in `docs/232`).
A DOS Pool of Radiance charm node, granted or running, whichever side charmed
whom, on a player character or a companion, writes the C64's shared effect row
`(0x0B, slot, 0, magnitude)` with bit 7 set and the charmer's side in bit 0.
The record's `0x10C` is quickfight in bit 7 and the character's own side in bit
0, bits 5 and 6 clear, so the C64's handler builds `$C0 | own << 5 | charmer`
at his first event (`effects.pool_charm_row`, `c64_codec.write`). A second node
is the same charm, because both engines replace one. Pool has no Fear row, so
bit 6 never comes with a charm row there. A C64 charm row reads back as the DOS
node: the charmer from the magnitude's bit 0, never from `0x10C`; the own side
from `0x10C` bit 5 when bit 6 is set and from bit 0 otherwise; `$06` and `$07`
(the vampire's gaze, no bit 7) as `$86` and `$87` with flag 1, as DOS's own node
for that ability has (`effects.pool_charm_record`). A row with bit 5 of `0x10C`
set and bit 6 clear, or a node with data bit 5 clear, data bit 4 set or a flag
other than 1, is a state no game writes and stays a loss. **Fear converts**, in both directions: its record state is DOS's own
"player character taken over" control byte (`0xB3`, `docs/195`) and C64 record
`0x10C` bit 6, and `goldbox/c64_codec.py` converts the row and those bytes
together (`FEAR_IDS`).

| Effect | DOS | C64 |
|---|---|---|
| Charm, 11, Curse and Silver Blades | Silver Blades spells 10 and 96 write `(11, 60 + 60 a level, charmer's side << 7 \| level, 1)` (`0x2E75A`-`0x2E799`). The handler's first call adds `0x20` and the target's own side `<< 6`, sets the side byte `0x1A8` to bit 7, the quickfight byte `0x1A9` to 1 and the control byte `0xFF` to `0xB3`; remove mode puts back the side from bit 6 (`0x11183`-`0x1126B`). Curse writes the node with duration 0 (spell 10's row, bytes 4-5 zero), so only Silver Blades holds a running one | the cast writes `$80 \| level` (`COMBAT $1A67`) and sets record `0x10C` to the charmer's side in bit 0, the target's own side in bit 1, and bits 2, 6 and 7 (`$1A87`-`$1A9E`, `ORA #$C4`; Curse `$171B`). The handler's expiry path puts bit 0 back from bit 1 when bit 2 is set (`$24B8`, Curse `$1EE4`) |
| Charm, 11, Pool of Radiance | spell 10 writes `(11, 0, 0, charmer's side << 7 \| count, 1)`. The handler (`0xF05B`) sets data bit 5 on its first call and keeps the target's own side in bit 6, and sets the side byte `0x10E` to the charmer's side, the quickfight byte `0x10F` to 1 and the control byte `0x084` to `0xB3` (`0xF0EF`). Remove mode (`0xF064`-`0xF08F`) puts back the side from bit 6 and writes control 0 (`0xF089`), leaving quickfight at 1 | spell 10's combat row (`SPELLE65 $D86C`) sends the cast to `SPELLE00 $A934`, which sets the magnitude to `$80 \| $06 \| (caster's 0x10C & $0F)`, `$86` from a party caster, and hands it to the generic combat writer (`COMBAT $29F7`, `ECL64 $99D1`, stores `$9A31`-`$9A46`): id 11, owner the target's combatant index (`$A4F5`), duration 0. The cast does not touch `0x10C`. The handler (`SPELLE01 $A7DA`) does, whenever it is called with bit 7 of A clear: if bit 6 is clear it moves bit 0 to bit 5 and sets bit 6, then ORs in the magnitude, masks `$61` and sets bit 7. For an ally charmed by his own party that is `$C0`, and later calls keep it. Its expiry path writes `$80 \| (bit 5 → bit 0)` |
| Fear, Curse 142, Silver Blades 111 | spell 84 writes `(id, level minutes, 0, 1)` and sets the quickfight byte (`0x198`, `0x1A9`) to 1 and the control byte (`0xF7`, `0xFF`) to `0xB3` (Curse `0x32B51`-`0x32B89`); Confusion's 1-10 does the same with `(id, 10, 0, 1)`. Remove mode clears both (`0x12819`, `0x144A0`) | the cast writes `level \| $80` and sets record `0x10C` bits 6 and 7 and the combat flee flag (`COMBAT $21C7`, Silver Blades `$2718`); the expiry handler clears bit 6 and the flee flag (`$2911`, `$297F`) |

A DOS node is five bytes: the id, the duration in two bytes, the value and
the flag. The Curse and Silver Blades entries above write it as the 4-tuple
`(id, duration, value, flag)`, with the duration as one number; Pool's entry
writes the same node as the 5-tuple `(id, 0, 0, value, flag)`, with the two
duration bytes shown, both zero.

In the later titles the node and the row map one to one for both (Charm: C64
`$80 | (data & $0F)` and bit 7 for the flag; Fear: `data | $80`). Pool's
charm row does not: its magnitude holds the charmer's side in bit 0 and a
constant `$06`, where DOS holds a count, so C64 Dispel Magic tries it as a
sixth- or seventh-level effect. What Charm's row alone does not carry is the
record: the C64 reader takes `0x10C` bit 0 as `hostile` and bit 7 as
`quickfight` and logs bits 1-6 as not converted, and the writer sets only
bits 0 and 7 (and bit 6 with a Fear row), so in the later titles a converted charmed
character would lose the side the C64 puts back at expiry. `goldbox/layout.py` used to call `0x10C` bits 1-6 unused by every
writer seen; the later titles' Charm, Fear and Confusion writers above set
bits 1, 2 and 6, and `COM.PREP`, `POST.COM $31A2` and `ECL64 $3DD6` read them
as part of the side. Pool's charm handler uses bits 5 and 6 instead;
whether another Pool handler (Confusion's effect 107) also sets them is not
known (SPECULATIVE, it needs a disassembly read). In the later
titles, converting Charm needs the record's side, quickfight and control bytes
mapped together with the row, in both codecs; Pool leaves the side byte at
`$80` (the section opening above).

**C64 Pool of Radiance's charm, CONFIRMED from code except where graded.**
Static reads; nothing was booted. `tools/c64/overlay.py` and
`tools/dos/dosaffectreads.py` reproduce its addresses.

* **Two writers, one row writer.** Spell 10 above, and the monster ability
  id 84, whose handler `SPELLE02 $A77F` writes the same row through the same
  writer with magnitude `$06 | $A4E2`. `$A4E2` is the acting combatant's
  side, `LDA 0x10C / AND #$01` at `COMBAT $2477`, stored at `$0939` at the
  start of every turn, flipped by `EOR #$01` at `$14C5` and put back at
  `$1181` and `$1533`. It is always 0 or 1, and nothing on the row's path
  (`SPELLE02 $A77F` through `$A724`, `ECL64 $9974` and `$99D1`) ORs in bit 7,
  so the monster's row never has bit 7 set. CONFIRMED from code; a read of
  every step made the earlier PROBABLE for this call unnecessary. Charm Person's camp row routes to `CAMP $1467`, the routine
  Burning Hands' camp row names too, so it is not a camp spell (PROBABLE). No
  other `COMBAT`, `SPELLE00`, `SPELLE01` or `SPELLE04` store names id 11.
  `SPELLE01 $AB53`, which stores `$0B` into `$6C1C` and `$6C1E`, is id 76's
  handler, not a charm writer: those are roster bytes `0x11C` and `0x11E` of
  the loaded combatant, and it grants ids 75 and 58 through `ECL64 $9ACD`.
* **When the handler runs.** The combat handler table (`SPELLE65`, loaded at
  `$D60A`: address halves `$DA63`/`$DAEE`, overlay number `$DC13`) sends id 11
  to `SPELLE01 $A7DA`. Nothing calls it at the cast. It runs from the event
  lists at `$DB7A` that hold 11: event 15 at the start of the holder's own turn
  (`COMBAT $0925`, `$09D6`), event 17 (`$2147`), and event 19, for every
  combatant at the start of every round (`$0C34`, after the round's ageing).
  So `0x10C` changes at the next round or at his own turn, not at the cast.
* **Who commands him.** `COMBAT $093C`, right after event 15, gives the turn to
  the player when `0x10C` bit 7 is clear and to the computer when it is set.
  Bit 7 alone decides, but a charm row sets it again at every event 15 and 19,
  so a charmed party member is never commanded while his row stands.
* **What ends it.** A duration of 0 is never aged (`COMBAT $221E` skips it).
  The combat removal `SQRPACI01 $07E4` runs the handler's expiry path when
  magnitude bit 7 is set, and a combatant who goes out of the fight has every
  row not on a twenty-id exception list removed that way (`COMBAT $0DC7` →
  `$29C4`; 11 is not on the list). **Fleeing does not reach it (CONFIRMED
  from code):** `COMBAT $1719` → `$1732` stores `$86` and ends `JMP $181F`.
  `JSR $29C4` exists only at `COMBAT $0DC7`, which is reached from `COMBAT`
  and `SPELLE01 $AC57`. Going down through `COMBAT`'s damage path removes the
  row; the status writes at `$2113`, `$2A78`, `$24E7`, `$0C4B` and `$2161` do
  not go through `$0DC7`, and whether any of them can happen to a charmed
  party member is SPECULATIVE. A charmed member cannot become `$86`
  (PROBABLE): the only `$86` writers are the player's FLEE YES, gaseous form
  (id 103) and `COM.PREP`'s unplaced combatants. The earlier reading that every
  way of going down or fleeing reaches `$0DC7` changed because the code shows
  the flee path skips it. The monster's row, bit 7 clear, is removed
  without the expiry path, so its target keeps `$C1`. CONFIRMED from code: bit
  7 is the computer commanding him, bit 6 the charm being set up, bit 5 = 0
  his own side being the party's, and bit 0 = 1 his now fighting for the
  monsters; the removal calls the handler only when magnitude bit 7 is set
  (`SQRPACI01 $07E4`), and the earlier PROBABLE rested on the row's bit 7
  being unread. A party member charmed by that monster and then knocked out
  is taken for a slain enemy after a win, because `0x10C & $7F` is not 0.
  Both addresses cited for that removal are right: `POST.COM $09AB` is the
  side test (`0x10C & $7F`, skipped if 0) and `$09EB` the slot-below-8 test of
  the same loop, and `$09EF`-`$09F7` then zero the status and the name byte
  (the loop also needs `$6C00` bit 7 set and not `$86`, and `$6C01` bit 7
  clear). A monster the party has charmed has `$A4E2` = 0, so if it uses id 84
  the magnitude is `$06` and its target keeps `$C0`, which the won path also
  takes for an enemy. A party re-charm on an id-84 target leaves him at `$C1`
  while the new row stands: the old row goes without expiry and the apply path
  ORs bit 0 in rather than replacing it, and the new row's expiry then gives
  `$80`. The camp removal
  `CAMP $131F`, which C64 Dispel Magic uses out of combat (`SPELLE04 $AA7A`),
  dispatches only the ids at `ECL65 $9AD5`; 11 is not one of them, so a camp
  dispel deletes the row and leaves `0x10C` as it was. `POST.COM $14FB`
  deletes each occupied roster slot's charm row and sets `0x10C` to 0 at the
  end of a fight, without the handler; it does nothing to a slot with no row.
  The later titles' copy of this loop runs on every outcome; that Pool's does
  is PROBABLE.
* **CONFIRMED from code, not run: fight start with a stored charm.**
  `COM.PREP` places combatants in groups by `0x10C & $7F`. The first pass
  (`$0E78`-`$0EA7`) places every value-0 combatant at the party's edge. The
  second (`$0F54`-`$0F92`) places every combatant whose value is not 0 at the
  opposite edge, going on to the next after each placement (`$0F84 BCS
  $0F8A`). Only a failure, with no position left, reaches `$0F86 JSR $0F0B`
  and returns. A party member saved with `$C0` (value `$40`) is therefore
  placed at the head of the monsters' formation, being combatant 0-7, and the
  monsters are placed after him as usual. With `$80` (value 0) he is placed
  with the party, and the handler's first event 19 then writes `$C0`. What
  would settle it: in VICE, stage a copy of a C64 Pool save with a charm row
  (`0B`, owner the slot, duration 0, magnitude `$86`) and `0x10C` = `$C0` on one
  member, walk into a fight and screenshot the first command prompt; repeat
  with `$80` as the control. Confirmed if he stands at the head of the
  monsters' formation and every monster is placed; refuted if he stands with
  the party or a monster is missing. Evidence:
  https://github.com/malcyon/wish/issues/667#issuecomment-5881008971.

**Monster charmers, CONFIRMED from bytes.** Every copy of every `MON*` file on
the eight sides (116 names) was read, with the offsets checked against BASILISK
and MEDUSA, which hold id 83. No record carries id 84, so the id-84 path and the
hazard below are unreachable in Pool play: no player can reach them. The only
Pool monster that casts Charm Person is `MON59` (5TH LVL MU, `POOL2`,
memorised twice). It fights at Stojanow Gate, `ECL09 $A29E`, where mercy is off.
Whether its AI aims the spell at a party member is SPECULATIVE. Its row's
magnitude is `$87` (PROBABLE: `SPELLE00 $A937` gives `$80 OR (($06 OR caster
0x10C) AND $0F)`, and a hostile caster's `0x10C` was not read here). The
brawl's monsters carry no trait id and no memorised spell.

**The player's aim for Charm Person.** The aim path (`SPELLE00 $A700` →
`$A798` → `COMBAT $0F61`) reads only the spell row's range and target kind
(byte 3 = `$04`, one target, the same as Cure Light Wounds), so it offers an
ally: PROBABLE, since the candidate-list builder behind `COMBAT $0F61` was not
read. The target gets a saving throw: row byte 4 = `$11`, save index 4, the
spell save (CONFIRMED from code, `ECL64 $9974`-`$99C8`).

**The id-84 hazard.** A party member charmed by the monster ability id 84 and
then knocked out keeps `0x10C` = `$C1`, and `POST.COM`
takes him for a slain enemy after a win (both CONFIRMED from code, above). That is the C64 game's own behaviour and
Wish does not write it: the charm conversion writes only the party cast's
`$86` form, whose removal runs the expiry. Wish's one exposure is a C64 save
holding `$C1` on a party member with no charm row, which `read` would take for
an enemy-side member and DOS would drop after his next fight. By the reads so
far no save holds it: after a win he is removed (`POST.COM $09AB`, `$09EB`),
and Pool's fled loop `POST.COM $0DF8` walks roster slots 7 to 0, and for a
slot with a charm row deletes the row (`$0E0E`) and jumps to `$0E23`, where the
status `$6C00` and the name byte `$6B00` are zeroed and written back
(`$4418`, `$441E`). It removes the character from the party whatever his
`0x10C` or `0x0B8`, and never writes `0x10C`. A slot with no row and status
`$86` or `$81` gets status 1 (`$0E36`), and anyone else is removed unless `$6DE6` is
non-zero. CONFIRMED from code; it is Curse's `$0DF2`. It runs when the outcome
`$6DC7` is `$81` (`$0930`), and `$81` as the flee outcome is CONFIRMED from
code: `$6DC7` is built at `$0903`-`$091A` from `$2B09`, `$2B05` and `$2B06`,
and their only writers are the `INC abs,X` in `POST.COM $088E`-`$0900`, indexed
by X = `0x10C AND $7F`. A charmed member is `$C0` (X = `$40`) or `$C1`
(X = `$41`), so he is in neither the standing tally nor the running one. The
earlier grade rested on those writers not having been traced. The loss case is
an inference from the game's rules, not a read. A charmed ally a player
converts from DOS Pool is removed from the party if the player flees his first
C64 fight, but the clause is usually not why. He is `$C0`, so the fight does
not end when the rest flee, and the computer goes on fighting him for the
party. If he falls through `$0DC7`, his row expires and he is dropped as an
ordinary left-behind character (kept with mercy). The clause drops him only
if the monsters are all beaten first while everyone else on the party's side
is down or ran. The sentence changed because the fight-end count and the
outcome count differ in what they take as the party's side
(`docs/110-combat-log.md`). What DOS Pool does to a party-side charmed ally in
the same flight is UNKNOWN, because `0x5C2B`-`0x5C68` was read only for a
monster's charm.

**Which saves can hold a charm on a party member.** A player can save only
between fights, so this is a question about what survives the end of one.

| Title and port | Answer | Grade |
|---|---|---|
| DOS Silver Blades | No. The end-of-fight strip and the removal when the holder leaves combat both take 11 off | CONFIRMED from code; the demo skip below PROBABLE |
| DOS Curse | No, for the same reasons | CONFIRMED from code; the same caveat |
| DOS Pool | Yes, by one route: a party caster charms another party member, whose side stays the party's under computer control (quickfight 1, control `0xB3`), and the party wins. Nothing removes the duration-0 node until he leaves a later fight or is dispelled. A monster's charm cannot reach a save: while its target stands the other side is never empty (resident `0x2F7B`), knocking him out removes the node (`0x2BDF0`), and fleeing leaves him behind (`0x5C2B`-`0x5C68`) | PROBABLE: nobody has read whether spell 10's target picker offers an ally |
| C64, all three | No. Curse and Silver Blades sweep every combatant at the end of combat, and Pool's `POST.COM $14FB` deletes the row of every occupied roster slot | CONFIRMED for the sweeps' content. CONFIRMED for Curse and Silver Blades that every way a fight ends reaches them: win, wipe-out, all members fled and CONTINUE BATTLE answered no each pass the fight-over test (Curse COMBAT2 `$F962`-`$F96A`, Silver Blades `$F605`-`$F60D`) before the title's one store to `$7F11`; COMBAT, COMBAT2, ECL64 and POST.COM hold no save or load code. Pool's `POST.COM $14FB` half is PROBABLE |

**A second charm on a charmed target, and a charm with no free row.**
CONFIRMED from code unless graded; static reads, nothing booted. Evidence:
https://github.com/malcyon/wish/issues/667#issuecomment-5877901386.

| Engine | Second charm | No free row |
|---|---|---|
| C64 Pool | Replaced. `ECL64 $9A13` finds the target's row with the same id, and a new duration of 0 takes `$9A1B` to `$9A29`, which removes the old row through `$07E4` (with the expiry if its bit 7 is set). The new row goes in a free row (`$9A53`) and the handler rebuilds `0x10C` at the next event | No row, no message, `0x10C` untouched, so the charm has no effect (`$9A53` asks `LIBRARY $3FE4` for id 0, which matches any owner, and returns through `BCC $9A49`). A re-charm cannot fail this way, because it frees the old row first |
| DOS Pool | Replaced. Apply (`0x2C540`) finds the existing node, and when the new duration is 0 or the old node's is shorter removes it through `remove_affect` (`0x2AF10`, remove mode: side back, `0xB3` to 0) and adds the new one (`0x2BD3C`). Both writers then run the handler in mode 0 on the first id-11 node, the new one: spell 10 at `0x2828B`-`0x282A8`, id 84 at `0x10C35`-`0x10C52`. Neither leaves two nodes | No such case: `add_affect` allocates 9 bytes from the heap (`0x2BD42`) and appends to the list at record `0x7F` with no count limit |
| DOS Curse | Stacked. Apply (`0x3737F`) removes an existing node only when its duration is non-zero, and Curse's charm nodes have duration 0, so a second is added (`0x373B0`). PROBABLE that spell 10 uses this routine (the same structure as Pool's; the call chain was not traced). Unreachable in a save, because both DOS strips remove id 11 | As DOS Pool |
| DOS Silver Blades | Extended. Apply (`0x37F2B`) keeps the existing node and raises its duration if the new one is longer (`0x37F44`); it adds no second node and leaves the data, so the first charmer's side stays | As DOS Pool |
| C64 Curse, Silver Blades | The cast (`COMBAT $170C`, `$1A87`) sees `0x10C` bit 2 already set, keeps the byte and replaces only bit 0 with the new charmer's side; his own side (bit 1) survives from the first charm. The row writer's handling is UNKNOWN: not read | UNKNOWN: not read (the counterpart of Pool's `ECL64 $99D1`; Curse's cast entry clears its override at `$0DD9`) |

**The DOS handler's effect on the control byte.** CONFIRMED from code. Apply
mode (Pool `0xF092`-`0xF10C`, Curse `0x101CB`-`0x10245`, Silver Blades
`0x111D1`-`0x11263`) runs when node data bit 5 is clear; remove mode (Pool
`0xF064`-`0xF08F`, Curse `0x1019D`-`0x101C8`, Silver Blades `0x1118C`-`0x111CE`)
runs otherwise.

| | Apply | Remove |
|---|---|---|
| Data byte | `+ 0x20 + (current side << 6)`, an add and not an OR | not changed |
| Side | becomes `data >> 7`, the charmer's | comes back from data bit 6 |
| Quickfight | becomes 1 | Silver Blades sets it to 0 in the branch that clears `0xB3`; Pool and Curse leave it at 1 |
| Control byte | becomes `0xB3` only if it is at most `0x7F`, so a companion (`0x80`-`0xFF`) keeps his own | becomes 0 only if it reads `0xB3`, whoever set it |
| Runtime combat block | its two target words (through record `0x108`, Curse `0x18D`, Silver Blades `0x1A1`) are cleared; PROBABLE that this block is not saved | not changed |

What follows:

* **A charmed companion** keeps his control byte (`0x80 | morale`) while his
  side, quickfight and node change; when the charm ends his side comes back and
  quickfight stays 1, in all three titles. CONFIRMED from code.
* **A player character is always taken over at once** in Pool, because both
  DOS Pool writers call the handler right after the add, so no game-written
  save holds a Pool charm node with bit 5 clear. CONFIRMED from code.
* **A charmed Animate Dead zombie** (id 32's spell writes `0xB3`, `0x29195`)
  is let go by the charm, and remove mode then writes 0, so the zombie would be
  the player's to command. PROBABLE: only the id-32 handler (`0xF776`) around
  its own remove mode (`0xF7E7`-`0xF7F2`) was read, and another write of
  `0xB3` is not ruled out.
* **C64 Pool** touches `0x10C` only, so a companion and a player character are
  treated alike; `POST.COM $14FB` sets `0x10C` to 0 for a slot that still holds
  a charm row.
* **SPECULATIVE: a DOS companion whose stored control byte is exactly `0xB3`**
  (morale 51) would become a player character when a charm on him ends. A sweep
  of the DOS Pool monster files and saves for control `0xB3` with no id-11 or
  id-32 node (`tools/records/controlbyte.py`) settles it: a hit confirms such a
  record exists, and none leaves it unreachable from the data we have.

**The DOS Pool charm count.** CONFIRMED from code, one flag PROBABLE. Spell 10
(`0x281F5`) stores `(caster's 0x10E << 7) + START:0x3262(spell 10)`. `0x3262`
reads the spell table's class byte (`ds:0x31FA + 16 x spell`); spell 10's is 1,
so it returns record `0x9B`, the magic-user entry of `class_levels` at `0x096`,
and returns 6 instead when `[0x6DBF]` is non-zero and the class is not 2 (that
`[0x6DBF]` marks a cast from an item is PROBABLE: its writers were not read).
The monster ability id 84 (`0x10BD8`-`0x10BEE`) always stores
`(side << 7) + 12`, and sets the current spell to 10 first. The handler adds
`0x20` and the own side `<< 6` and never touches bits 0-4. Only Dispel Magic
reads them, as the level (`data & 0x0F`), on both ports. The C64 row keeps the
count in its magnitude, `$80 | (count & $0E) | charmer | ((count ^ charmer) &
1) << 4`, and DOS gets it back as `(mag & $0F) ^ (mag >> 4 & 1)`: a wand or
scroll charm is the C64's own `$86`, `$86` and `$87` (and `$06`, `$07`) read as
6 and 7, and a DOS to C64 to DOS round trip returns the count exactly. PROBABLE
until a run confirms that nothing reads the row's bit 4 or the count bits
beyond the readers found (the settling run: stage `(0B, owner, 0, $92)` on a
copy, set a read watchpoint on the row's magnitude, fight, camp and Dispel
against a `$86` control); if another reader turns up the row falls back to
`$86` and the count is open work again. The C64 dispels at the DOS level
whenever the count's low bit equals the charmer bit, and one level easier
otherwise, because bit 0 is the charmer's side.

**Where the later titles keep a charm, and how it ends.** CONFIRMED from code;
Curse and Silver Blades DOS addresses as in the table above.

| | DOS Curse | DOS Silver Blades |
|---|---|---|
| Node | `(11, 0, 0, side << 7 \| level, 1)` | `(11, 60 + 60 a level, side << 7 \| level, 1)` |
| Handler | `0x10194` | `0x11183` |
| Side, quickfight, control offsets | `0x197`, `0x198`, `0xF7` | `0x1A8`, `0x1A9`, `0xFF` |
| What ends it | leaving combat, and the end of every fight | the same, and its duration |

| | C64 Curse | C64 Silver Blades |
|---|---|---|
| Row | id 11, magnitude `$80 \| level` (`COMBAT $16EF`-`$16F4`, level `$A90A`) | `$1A6A`-`$1A6F` |
| `0x10C` at the cast | `$170C`-`$1723`: `(($C4 \| own side << 1) & $FE) \| charmer's side`; the charmer's side is a self-modified immediate at `$1722`, set at `$1700`-`$1708`; if bit 2 is already set the old byte is kept except bit 0 | `$1A87`-`$1A9E`, immediate at `$1A9D` |
| Handler, apply | `$1EE4` `BPL` to `$1F02`: nothing to `0x10C` | `$24B8`, the same |
| Expiry | `$1EE6`-`$1EF5`: if bit 2 is set, `$80 \| own side` | `$24BA`-`$24C9`, the same; then `$241C` clears bit 7 if his own side is 0 and `0x0B8` bit 7 is clear |
| End-of-fight sweep | `$1268`-`$126D`, `AND #$BF` | `$1261`-`$1266`, `AND #$9F`, then `$24BA` again |
| `0x0B8` | read only (`COMBAT $0CD3`) | read only (`$0CB0`, `$2420`) |

A player character charmed in a C64 fight leaves it with `0x10C` = `$80` in
Curse and `$00` in Silver Blades. Reachability is unchanged: no game-written
save of either title, on either port, holds a charm on a party member.

**DOS Pool outside combat.** Dispel Magic (`GAME.OVR:0x2939D`) walks every
node of each target and passes over only a byte 3 of `0xFF`, so it tries the
charm node at the level in its data's low nibble and, on success, takes it off
through `remove_affect` (`0x2AF10`), which runs remove mode because byte 4 is
1: the side comes back and control goes to 0. CONFIRMED from code. Castable in
camp PROBABLE, from the C64 camp row of both Dispel Magic spells (41 and 46,
`SPELLE04 $AA5B`). No temple service or other routine ends it: none of the 35
`remove_affect` calls in `GAME.OVR` pushes a constant 11, the id lists they
walk hold 11 only in the leaving-combat list, and the only constant writes of
0 to the control byte are the remove modes of the charm handler and of id 32's
(`0xF7F2`). PROBABLE rather than confirmed, because the nine callers of the
id-parameter remover at `0x2C540`, the computed-id calls at `0x11B61` and
`0x297F7`, and three routines that store a computed control byte (`0x38C4`,
`0x7F47`, `0xD8B2`) were not attributed.

**What removes a charm at the end of a DOS fight.** Two routines remove id 11,
and both run the handler's remove mode:

| Routine | Silver Blades | Curse | Pool |
|---|---|---|---|
| the holder leaves combat (knocked out, killed, fled), then the list | `0x370CD`, `0x371D1`: 14 ids at ds:`0xA9A` -- 03 0B 15 17 1B 1E 1F 33 34 35 5B 6A 6B 6F | `0x364C9`, `0x365CD`: 19 ids at ds:`0xA32` -- 07 0B 0D 15 17 1E 1F 20 33 34 35 3A 3B 5F 62 88 89 8B 90 | `0x2BDF0`, `0x2BEF4`: 16 ids at ds:`0xC14` -- 07 0B 1E 1F 20 33 34 35 36 3A 3B 5F 62 89 4A 4B |
| end of every fight, every party member whatever his status | `0x6F90`, loop `0x711D`-`0x7147`: 11 ids at ds:`0x1B42` -- 03 0B 15 17 1B 23 28 1F 33 34 35 | `0x61D3`, loop `0x6369`-`0x6393`: 19 ids at ds:`0x2AA` -- 03 0B 0D 15 17 1B 23 28 33 34 35 3A 5B 88 89 8B 8E 90 1F | none: `0x5A47` calls no `remove_affect` |
| end of every fight, every combatant, party included, whatever his status | the combat loop's teardown: `0xB508` leaves only through `0xB5F2`, which calls `0xB3EB` with no condition; `0xB461`-`0xB4CD` walks the list from `[0x7D3C]` in steps of `0x19D` and calls `0x371D1` for every record (`0xB4B8`), so the leaving-combat list above, 6F among it | not read | not read |

`0x371D1` is therefore not only the leaving-combat remover in Silver Blades:
the teardown row above is a second call site, found on #733 (A character still
frightened when a DOS Curse or Silver Blades fight ends starts his next C64
fight among the monsters) after this table had listed the routine for a member
leaving combat alone. CONFIRMED from code.

The end-of-fight routine runs before the experience award and before fled
members are handled. It is skipped when `[0xA4BA]` and `[0x67E9]` are both
non-zero in Silver Blades (`0x7079`-`0x7087`; Curse `0x62C5`-`0x62D3`), which
the Curse reimplementation names the combat type and the demo flag; PROBABLE
that both are never set in a game a player saves.

**The DOS end-of-fight strip removes one node of each listed id, not every
node.** It calls `remove_affect` with a null node, and with a null node that
routine removes only the first node of the id (Curse `0x3513E`-`0x3517D`,
Silver Blades `0x35E8E`, the same). `add_affect` appends without checking for
a duplicate (Curse `0x36412`-`0x364C6`). A character holding two nodes of one
listed id when the fight ends keeps the second into the save. CONFIRMED from
code.

**At the end of a C64 fight in the later titles**, the round scheduler's
fight-over branch (Curse `COMBAT2 $F962`/`$F9D7`, Silver Blades `$F605`/
`$F66C`, both at `$E000`) sweeps every combatant and removes a fixed list of
combat-only ids, charm and fear among them, running each flagged row's expiry
handler, before `POST.COM` loads. `POST.COM`'s own charm clear (Curse `$1533`,
Silver Blades `$15BE`) then finds nothing.

**Fear, corrected.** The Fear build's reachability assumed the C64 keeps its
own fear past a fight, from `effectcrosswalk.c64_row_sweep`, which is a
different list. It does not: both later-title sweeps list fear (Curse `0x8E`,
Silver Blades `0x6F`), run its expiry handler, and clear `0x10C` bit 6, so no
C64 save holds a fear row on a party member and the C64 → DOS direction has no
game-written source. No DOS save of either title holds one either. DOS Curse
removes 142 at the end of every fight through its strip (`0x61D3`). DOS Silver
Blades removes 111 through the combat loop's teardown, which runs `0x371D1` on
every combatant whatever way the fight ends (the table above), and remove mode
clears the control byte and quickfight with it (`0x144A0`). This paragraph used
to say that Silver Blades keeps `(111, m, 0, 1)`, control `0xB3` and
quickfight 1 into the save; that rested on reading `0x371D1` as the
leaving-combat remover only. CONFIRMED from code, and in the running game: a
Silver Blades party member staged with `(111, 600, 0, 1)`, control `0xB3` and
quickfight 1 came out of a fight in the game-written save with control 0,
quickfight 0 and no 111 node
(https://github.com/malcyon/wish/issues/733#issuecomment-5901943377).

The one-node removal (previous paragraph) is enough for fear, because no fear
writer leaves two nodes. Silver Blades' writers, spell 84 (`0x3113A`) and
Confusion's 1-10 (`0x11B53`), both call apply `0x37EB0`, which finds the id
(`0x37F1F`), raises an existing node's duration (`0x37F2B`-`0x37F44`) and adds
a node (`0x3701D`) only when none exists. CONFIRMED from code. Curse's writer
(`0x32B4C`) calls apply `0x37303`; the Charm table above reads its `0x3737F` as
removing an existing node of non-zero duration before adding, and a later
plan (https://github.com/malcyon/wish/issues/733#issuecomment-5901996729)
reads it as raising the duration. Either leaves one node, since both fear
writes carry a non-zero duration (level minutes, and 10). PROBABLE: the two
readings of `0x3737F` disagree, and the Amiga Curse apply (below) removes and
re-adds.

Wish's Fear block (`c64_codec.write`, `FEAR_IDS`) therefore converts only a
save somebody edited by hand. The conversion rule stands; a converted fear row
is removed by the C64 at the end of its next fight. Confusion (`0x23`) and
Fumble (`0x1B`) are on every end-of-fight list of both later titles on both
ports, so a single node of either does not survive to a save on the C64. On
DOS a second node of the same id does (previous paragraphs).

**Fear at the end of an Amiga fight.** Neither Amiga port keeps fear past a
fight, so no game-written save on any port holds a fear node on a party
member. Static reads of `/Secret` on `SecretOfTheSilverBlades_A.adf` and
`/Curse` on `CurseOfTheAzureBonds_A.adf` (a cracked build, the only one on this
machine), at file offsets into the executable as `tools/amiga/amiga68k.py`
prints them; `gNNNN` is a small-data global as `tools/amiga/amigaglobal.py`
names it. Nothing was booted.

| | Amiga Silver Blades | Amiga Curse |
|---|---|---|
| Fear id; control, quickfight | 111; `0x9A` set to `0xB3`, `0x146` set to 1 | 142; `0xF7` set to `0xB3`, `0x19D` set to 1 |
| The combat loop | `0x3BAE`, one caller (`0x1F640`). Its only exit is `0x3CAA`, taken when the done flag is set before the first round or by the end-of-round check (`0x42D6`); it calls the teardown `0x3730` with no condition | `0x2A66`, one caller (`0x1F176`). Its only exit is `0x2AF6` → `0x29E8`, which frees lists and removes no node; `0x1F17A`-`0x1F17E` then run `0x2CF58` and `0x2DDE2` with no condition |
| What removes fear at the end of every fight | the teardown walks the record chain every party member is on (head `g5168`, link `0x13A`) and calls `0x12EFC` for every record: `remove_affect` (`0x11E46`) with a null node for 13 ids at `g0FC8` -- 03 0B 15 17 1B 1E 1F 33 34 35 6A 6B 6F. `0x12EFC` is also the leaving-combat remover (status change `0x11E16`, going down `0x8266`, swallowed `0x154D8`) | `0x2DDE2` calls the strip `0x2D24E` unless the demo flag `g3E33` is set (`0x2DDF6`); the strip walks the chain (head `g3CF8`, link `0x18E`) and, for each record before the first monster, calls `remove_affect` (`0xE274`) for 20 ids at `g1D32` -- 03 0B 0D 15 17 1B 23 28 33 34 35 3A 5B 88 89 8B 8E 90 1F 00. The leaving-combat list (`0xF2C6`, 19 ids at `g0E58`) lacks 142, as on DOS |
| Remove mode | handler `0x16AA8`: control `0xB3` to 0 and quickfight to 0 | handler `0x1269A`: the same on `0xF7` and `0x19D` |
| A second fear application | apply `0x13B98` finds the id and only raises a non-zero duration (`0x13C08`-`0x13C20`); it adds (`0x13C42`) only when none exists. Every constant-111 write goes through it: Confusion's "runs away" `0x14962`, id 82's "is terrified" `0x1605E` (skipped for a member already holding 111), spell 84 `0x365C6` | apply `0xFF70` removes an existing node of non-zero duration (`0xFFD8`-`0xFFEE`) and always adds (`0x10012`), so only a duration-0 node could stack. Both 142 writers use it with a non-zero duration: Confusion's "runs away" `0x10B04` (10) and spell 84 `0x33236` (caster level x 1 + 0, spell-table row at `g1EDE`) |

Grades. Silver Blades: CONFIRMED from code for the loop, the teardown, the list
and apply. Curse: CONFIRMED from code for the loop, the strip, its list and
apply, and that `g3E33` is set only by answering D at the title menu's "Play
Demo Transfer Quit" (`0x13F6A`-`0x13F76`). PROBABLE for three Curse details:
that every party member precedes the first monster in the chain (combat set-up
marks each record past the party count with combat byte `0x15` = 1 at
`0x4B66`; monsters and the duel copy are appended at the chain's end,
`0x1DF9E` and `0xDC0E`; the only reordering routines, `0xF56` and `0xFDA`,
belong to the Party Order menu); that the combat block `0x192` the handler
reads is still allocated at the strip (it is freed at `0x2DC40`, after it,
but not every callee of `0x2CF58` was read); and that no caster computes a
level of 0 for spell 84. Silver Blades' handler resets control only while the
combat block `0x13E` is set, which it is at the teardown (it is freed in
`0x30718`, called from the post-combat `0x30D1E`); PROBABLE on the same
grounds.

SPECULATIVE, on both Amiga ports: one route adds a node without the apply
check. Readying an item whose item-node byte `0x40` (DOS's effect byte `0x3D`, by the
Amiga item shift map) names an effect adds that id at duration 0 (Silver Blades `0x23578`, power byte `0x41` & `0x7F`
= 0, → item handler `0x16B88`; Curse `0x124CA`), and unreadying removes one. An
item naming 111 or 142 would give a frightened party member between fights.
A sweep of each title's item templates and the saves we have for effect byte
111 (Silver Blades) or 142 (Curse) with that power settles it: none found
leaves fear unreachable, a hit names the item. Whether either Amiga port offers
a save during a fight was not read: `/Secret`'s save routine (`0x2798E`) is
called at `0x181F0` and `0x21772`, neither traced to the combat menu.

**Fear's record state is simpler, because it is one byte each way, and it is
built.** DOS's control byte is not the side: it is `0xB3`, the engine's own
value for a player character it has taken over (`docs/195`), and the same byte
every DOS and Amiga reader delivers whenever `npc` reads true from `0x0B8` bit
7 clear plus a stored control byte -- there is nothing Fear-specific about
reading it. What is specific is the write: neither C64 title ever turns a
companion back into a player character (`docs/232`), so a converted feared
player character must write as a player character (`0x0B8` = 0, whether or not
its Fear row also converts) rather than as a companion the control byte would
otherwise make it. `c64_codec.write` does this for Curse and Silver Blades
through `DOS_PC_TAKEN_OVER`, and for a charmed Pool character (above). #720 (A Pool of Radiance player character the engine has taken
over converts between DOS and the C64 as a companion, because both readers take
the control byte's bit 7 for a companion) has no build of its own: its work sits
in #667 (A DOS party under Prayer, the strength and charisma spells, Mirror
Image or an effect with no C64 spell row is still refused when saved as a C64
save, because only the ordinary caster-level spells convert) Step C for Charm
and in #700 (Converting a Pool of Radiance C64 party holding a camp-cast
Animate Dead zombie needs more than fixing the refusal that blocks it) for
Animate Dead. Bit 6 of `0x10C`
goes with the row: written
when a Fear row is written, and read back as `npc` true with control `0xB3`
when a player character's row converted. The writer absorbs bit 6 without a
drop line when a Fear row or a Pool charm row converted. Bits 1-5, and bit 6
with neither a Fear row nor a Pool charm row, are still not converted anywhere
and are logged rather than masked away.

**Silver Blades' 65 is never a running node. CONFIRMED from a survey of
every writer.** Spell 114's row names 65, but its routine (`GAME.OVR:0x32323`) rolls
a save and calls the death routine without adding any node, and no constant
`add_affect` or apply names 65. The C64's spell 114 row names no id. A writer
that picks the id at run time would not show in that survey.

**PROBABLE, a DOS Silver Blades defect: Power Word Stun on a target of 91 hit
points or more writes a node that never ends.** Spell 117 picks 4d4, 2d4 or
1d4 by hit points and 0 above 90 (`0x3274B`-`0x3279B`), and applies `(106,
that roll, level, 0)` whatever the roll; the apply adds a duration-0 node
(`0x37F4A`), which never expires, and the id-106 handler takes the turn away
(`0x142E4`). The C64 cast returns without a row above 90 (`COMBAT $23A0`). What
would settle it: a DOSBox-X run in which a Silver Blades magic-user casts
Power Word Stun on a monster of more than 90 hit points, and the monster then
loses every turn for the rest of the fight. On a party member the node takes
the never-expiring route of #671 (A DOS character under Invisibility,
blindness or another spell that never runs out reaches the C64 with it in a
trait slot, where an attack or a combat cure cannot end it).

### The DOS duration routine gives six spells a time the row does not

Every DOS spell cast takes its minutes from one routine (Pool
`GAME.OVR:0x277EE`, Curse `0x2EE47`, Silver Blades `0x2D5E2`), and it
special-cases spells before falling back to row byte 4 plus row byte 5 per
level:

| Spell | Pool | Curse | Silver Blades |
|---|---|---|---|
| 26 | row | row | 3,780 minutes |
| 40 | 1d6 × 10 | 1d6 × 10 | 1d6 × 10 |
| 57, 61 | 5d4 | 5d4 | 5d4 |
| 59 | 1d4 × 10 + 40 | 1d4 × 10 + 40 | 1d4 × 10 + 40 |
| 63 | 2d10 × 10 in a fight, (1d10 + 10) × 10 outside | the same | row |
| 67 | 1,440 | row | row |

So a row whose bytes 4 and 5 are zero does not by itself mean a node that
never expires. Cause Disease (34, spell 40), 71 (Pool and Curse spell 63),
Haste from spell 57, held from spell 61 and Pool's 4 are all running nodes.

## A row whose owner has left the party

**A row owned by an empty party slot (owner 0 to 7) converts to nothing, and
it is not a loss.** A slot counts as empty when the save has no character in
it and its roster status is 0, which is what the C64's flight drop leaves: the
engine clears the member's status and name and keeps the rest, rows included.
DOS and the Amiga free a departed member's effects with him and have no store
for an effect owned by somebody outside the party, so the destination game
holds the same state after the same play. `goldbox.dos_codec.c64_party` skips
such a row and logs it at debug level. A slot with a nonzero roster status that
the reader cannot read as a character is not empty, so its row keeps the drop
line. A monster's row (owner 8 to `$7F`) and a party-wide row (bit 7 set) keep
their own rules above.

**Evidence, from #666 (A C64 party under a camp Prayer loses it on the way to
DOS or the Amiga, because nothing converts the save's party-wide effect
rows).** The rule rests on game-written saves after a flight in Pool of
Radiance and Silver Blades (`WISH-SPEC-por-666-e1-flee-orphan-rows` and
`WISH-SPEC-ssb-666-e1-flee-orphan-rows`): the orphan rows survive with their
owners unchanged, no remaining member lists them after a reload, and the party
is not closed up (Pool's survivors keep slots 0, 1, 3 and 5). The DOS and
Amiga side is the static read of comment 5914964343. **Unmeasured:** a script
dismissal of an NPC on any title, and a flight on Curse, which has no such
save yet.

## Negative results and remaining work

| Finding or gap | Grade and next bounded check |
|---|---|
| A raw DOS data byte is not a C64 magnitude | **CONFIRMED:** exceptional strength differs by one, and Prayer uses a different allegiance bit and polarity. |
| One minutes-only value does not encode every C64 duration | **CONFIRMED:** it omits clock phase, and 64 minutes at phase 0 has no exact candidate among all 252 nonzero-count bytes. A conversion policy is still required. |
| Pool overlapping Enlarge/Strength nodes do not have independent equivalent magnitudes | **CONFIRMED:** DOS `0x2C0D3` finds the active low-bit node, `0x2C129/0x2C12F` parks the displaced boost with bit 7, and expiry `0xF173–0xF227` selects the strongest remaining boost and moves the baseline into it. C64 `SPELLE04 $A8F4/$A8FA` updates current strength, then `$A8FD/$A904` searches ids 38/12 and `$A902/$A909` returns at `$A911` if either exists, retaining its earlier timer. `effects.pool_strength_chain_rows` writes two running strength nodes, a Strength with an Enlarge or two Strengths, as two rows timed from that chain, and `effects.pool_strength_chain_nodes` reads them back, keyed by row slot because two rows can share an id; a third running node is still refused, because the timeline then needs the whole chain. A granted strength node beside one running node converts as the granted node alone (`effects.pool_gauntlets_over_spell_row`): the C64 never holds both, and the gauntlets' row restores the base, so the spell's remaining time is the one loss, written to the debug log and not to the drop list. |
| Pool overlapping nodes: two running strength nodes convert, and the gauntlets beside one convert as the gauntlets alone | **CONFIRMED that the destination holds them:** the cast refuses a second strength node (`SPELLE04 $A8FD`/`$A904`, returning at `$A911`), and that is all it proves, because a writer is not the cast. Every sweep is per slot -- see the section above -- so two staged slots expire at their own times and each restores its own score. A converted pair therefore reproduces the intermediate step, with the later-expiring node in the lower-numbered slot. For two running strength nodes, a Strength with an Enlarge or two Strengths, that value is written by `effects.pool_strength_chain_rows`, with equal expiry, or minutes that share a duration byte, ordered parked node first so the active node's base is the only restore whatever order the C64 sweeps its slots in; the rest need a value **recomputed from the DOS chain's timeline** rather than each node's byte translated on its own, and three concurrent boosts on one character still have nowhere to go: only ids 38 and 12 reach the restore handler. |
| Prayer converts as one party-wide row, not as a row owned by one slot | **CONFIRMED from code:** on the C64 a row owned by one slot reaches only that character, and every C64 Prayer cast writes owner `$FF` (#666 (A C64 party under a camp Prayer loses it on the way to DOS or the Amiga, because nothing converts the save's party-wide effect rows)). DOS asks for id 49 for every combatant through the check-list routine, which gives one member's node to the whole party out of combat and to every combatant within range 6 in a fight (Pool `GAME.OVR:0x2B04A`, Curse `0x3529C`, Silver Blades `0x3606F`). So a DOS id-49 node is one `$FF` row on the C64, and coming back the row is one node on every member. An earlier reading kept the row owned by the caster's slot; it came from the owner's own query alone and had not read the routine that asks for id 49. |
| Pool's camp Prayer row, `$FF`/35, does nothing on the C64 | **CONFIRMED from code, and it replaces "not proved equivalent":** camp spell 42's flag `$80` takes `SPELLE04 $A704` to `$A710`'s owner `$FF`, and `SPELLE04 $A816`/`$A81C` store it with id 35 (row byte 3 is `$A3`). No constant-id query, none of the 20 check lists, the camp expiry table `ECL65 $9AD5` or ECL `CHECKPARTY` (whose only effect queries ask for 19) asks for 35. Its combat handler `SPELLE01 $A9B2` (+1 to `$2AFE` and `$2B10`) is called only from `SQRPACI01 $078B`, which a camp Prayer never reaches. What does read the row: the camp list of spells in effect (`CAMP $16C3`-`$1797`, which names it), Dispel Magic (`SPELLE04 $AA5B`, `SPELLE00 $ABCE`), and, PROBABLE, the cleanup when a combatant falls (`COMBAT $29C4`), whose query for the fallen combatant also matches owner `$FF`. DOS Pool's camp Prayer is one id-49 node on the caster (`GAME.OVR:0x27AA9`, row byte 7 = 1), but the check-list routine gives the whole party the +1. DOS Pool's Magic > Display names an id-35 node "Prayer" (`GAME.OVR:0x189E1`) and nothing else reads it. So the C64 row converts to an id-35 node on every member. The earlier "the two ports differ" came from not having read the routine that asks for id 49. Curse and Silver Blades write their camp Prayer as `$FF`/49 (row 27), which is why Pool's 35 reads as a slip in its own row 42. Evidence and addresses: #666 (A C64 party under a camp Prayer loses it on the way to DOS or the Amiga, because nothing converts the save's party-wide effect rows), Part B. |
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

**CONFIRMED from code: a spent Mirror Image converts to C64 magnitude 0.** A
DOS Curse node whose count nibble has run down to zero -- `$0F` is a
fifteenth-level caster's spent spell, which its own raw decrement produces --
absorbs nothing on either port. DOS Curse's handler rolls `dice(1, (data >> 4)
+ 1)` (`0x10638`-`0x1063E`) and absorbs only on a result above 1 (`0x10643`), so
a count of zero always rolls 1. The C64's handler asks `random(0..count)` for
the image that takes the hit (`COMBAT $20DF`-`$20E5` through `LIBRARY $2F46`,
Silver Blades `$25FB` through `$2E05`), and a zero answer costs no image. The
C64's camp sweep and combat round skip a slot only when its id or its duration
is 0, so a magnitude-0 row still expires on its duration, as the DOS node does,
and only a Dispel Magic removes either early. This page used to say the row
would "never expire"; that was wrong about the second half, because ageing
never reads the magnitude. Pool (`0xF670`-`0xF68D`) and Silver Blades
(`0x117DF`-`0x117FB`) remove the node when the count reaches 0, so only a Curse
player reaches the state. `goldbox.effects.mirror_image_count` returns the zero
and the writer stores it.

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

Prayer's conversion is checked by the two acceptance runs on #667 (A DOS party under Prayer, the strength and charisma spells, Mirror Image or an effect with no C64 spell row is still refused when saved as a C64 save, because only the ordinary caster-level spells convert), one on DOS Pool and one on Curse.

**What the C64 writer converts, and what it still waits on.** The writer is
built: `goldbox.effects.c64_row` turns a running node into a row of the save's
shared arrays for Pool of Radiance's caster-level ids
(`POOL_CASTER_LEVEL_IDS`) and for each later title's
(`LATER_CASTER_LEVEL_IDS`), and reports any other id by number as unconverted.
`tools/c64/effectcrosswalk.py`'s `later_caster_level_ids` re-reads the later
titles' tuples from the C64 spell rows, the DOS spell rows and the DOS
handlers that read a data byte, and `tests/records/test_effectcrosswalk.py`
pins the constants to it. The C64 reader converts the same ids back through
`goldbox.effects.dos_record`, with the time left from `remaining_minutes`.
Party-wide Detect Magic (id 5) converts both ways in all three titles: the
writer gives every running id-5 node one C64 row owned by the whole party
(`effects.PARTY_WIDE`) that lasts as long as the longest node, and the reader
turns a party-wide id-5 row into one DOS node on the lowest occupied slot (with
several such rows, the longest; a row that never expires becomes the
never-expiring record `05 00 00 mm 00` on that slot, which the writer turns
back into a duration-0 row that replaces any finite one; a Detect Magic node
with any flag byte converts, because no engine reads the flag for id 5). Pool's item grant of id 5 would be `05 00 00 0C 00`, the same bytes as a magnitude-12 row, and takes the party row; no Pool item grants id 5, so no save a game wrote holds it, and the conversion that keeps both (one `05 00 00 0C 00` per readied item with byte `0x3D` = 5, to a trait slot) is not built. Each title's DOS engine asks every party
member for id 5, so the two forms give the player the same thing. Prayer
converts both ways in all three titles: Pool's 35 is copied unchanged, Pool's
49 has its side bit inverted, and Curse's and Silver Blades' 49 keeps it.
Going to DOS the row becomes one node on every member; coming back the nodes
become one `$FF` row with the longest time left. A duration-0 Prayer row
becomes the granted record `id 00 00 data 00` on every member, on DOS and the
Amiga, which keep and honour a duration-0 node; the writer turns such records
back into one duration-0 `$FF` row, the higher data byte winning when members
differ. Detect Magic's duration-0 record sits on the lowest slot only.
Enlarge (12), Friends (14), Mirror Image (28) and Strength (38) convert both
ways in all three titles through `effects.c64_row` and `effects.dos_record`, each title's value rule as
tabled above: Pool's restore-flag encoding, the later titles' bonus and level
nibbles, the later Enlarge score read back off its own node, and a Mirror Image
count in both. The flag byte each DOS cast writes is fixed by title and id
(`effects.LATER_CAST_FLAGS`), which the later engines do not read. Still
waiting: rows no party member owns (party-wide, monster and orphaned rows, now
reported by name; converting them is #666 (A C64 party under a camp Prayer
loses it on the way to DOS or the Amiga, because nothing converts the save's
party-wide effect rows)); a timeline conversion for Pool's overlapping strength
nodes, which the destination does hold (a second strength node on one
character, running or granted, is refused by `strength_nodes`); the later
titles' Strength beside another strength source; a Curse or Silver Blades id-25 node of data `0xFF` (ids 138 and 108),
which needs its own read; a Giant Strength magnitude (Curse id 146, Silver Blades id 113) other than `$BC`
(strength 23); the ids with no C64 spell row that still need a read; and the
two ageing routes the camp formula does not describe.

Haste (39) converts both ways in all three titles by copying the byte for data
`0x00`-`0x1F` with flag 0: both ports keep the level in the low nibble, which
Dispel Magic reads as the caster's level and a combat cast sets to
`(2 x level) & $0F`, and the already-aged mark in bit 4, and set nothing else. Curse's and
Silver Blades' id 25 converts by the caster-level rule for data `0x01`-`0x7F`.
Silence 15' Radius (21), Ray of Enfeeblement (29) and Bestow Curse (36) convert
by the caster-level rule in all three titles; the camp-row derivations above
missed them because their C64 casts are combat-only
(`effects.COMBAT_CASTER_LEVEL_IDS`). The Giant Strength id (Curse 146, Silver Blades 113) converts as DOS
`(113, minutes, 0x79, 1)` and C64 magnitude `$BC`, the pair each engine writes
for its own cast of spell 59 (read 1); Curse's Potion of Giant Strength writes
the same pair under id 146 (`GAME.OVR:0x31FB8`, an immediate), and converts the
same way. Fire Shield (spell 85) writes two nodes, the shield (Curse 143, Silver
Blades 112) and the 50 or 54 that names its damage type, each `(id, minutes, 0,
0)` on DOS and each the caster's level with bit 7 clear on the C64
(`COMBAT $1C6C`, camp `ECL65 $8460`); they convert by the zero-level rule
(`effects.ZERO_LEVEL_IDS`), each row on its own. Id 13 is refused in Pool and Curse with a reason of
its own. In Pool no save a game wrote reaches it: DOS Reduce (spell 13) removes
an id-12 node and writes no id-13 node in any title (read 3c). In Curse a C64
save reaches it only when a fight has engulfed a party member (`COMBAT $1F40`)
and its row is still on the character at the save; a DOS or Amiga Curse save
never holds one. Silver Blades' id 13 is Barkskin and converts as a
caster-level id: a C64 row becomes `(13, remaining minutes, magnitude, 0)`, and
a node Wish wrote converts back. DOS and the Amiga never write that node
themselves, because their Barkskin (spell 90) runs the Heal routine
(`GAME.OVR:0x2F699`, shared with spell 36), and both engines' id-13 handler
gives the C64's -1 to the attacker's roll and +1 to saves. The camp writer is
row 26 at `ECL65 $93B6`, which goes to `$819C` with the generic level
magnitude and count `4 + level`; `POST.COM` does not strip it. Curse's C64
id 13 is the engulf countdown, whose magnitude is a combatant index, so it
stays refused. Dispel Evil (4
and Curse's 145 or Silver Blades' 32), Confusion (35), Fumble (27, and 42 with
data 0), Stinking Cloud (30, 31), Curse's 136 and Silver Blades' Power Word
Stun (106) convert both ways by the rules in "Combat-cast ids and their
rules". Fear (Curse 142, Silver Blades 111) converts both ways, its row and
its record byte together (`effects.FEAR_IDS`, `c64_codec.DOS_PC_TAKEN_OVER`).
Charm (11) converts both ways for every DOS Pool charm node, granted or
running, on a player character or a companion, and not yet run in the game;
the count is kept in the row's magnitude (PROBABLE, above). A node with data
bit 5 clear, data bit 4 set or a flag other than 1 is one no DOS Pool route
writes and stays a loss. Only DOS
Pool's duration-0 node reaches a save (PROBABLE: nobody has read whether spell
10's target picker offers an ally; the Charm and Fear section). Silver Blades'
65 is never a running node.

Slow Poison (22) and its companion damage node (15) convert both ways in all
three titles (`effects.SLOW_POISON_ID`, `SLOW_POISON_DAMAGE_ID`). DOS writes
`(22, 60 x level minutes, 0xFF, 1)` (Silver Blades: a fixed 3780 minutes) and
`(15, 10, 0xFF, 1)`, and Dispel skips data `0xFF`. The C64 camp cast writes row
15 with magnitude `$FF` and row 22 with `level | $80` (Pool `SPELLE04 $AD2F`;
Curse `$8519`; Silver Blades `$85A9`). Pool's Dispel skips magnitude `$FF`;
Curse's and Silver Blades' Dispel lists leave out 22. So both DOS nodes become
rows with magnitude `$FF`, which keeps the DOS node's immunity, and a `$FF` row
reads back as the same node. Pool's own `level | $80` row reads back as
`(level, 1, ...)` and stays dispellable at that level; in Curse and Silver
Blades any row with bit 7 set reads back as `(22, m, 0xFF, 1)`. Any other
node or magnitude stays a loss. Not yet run in the game on either port, and
that the C64 reads `$83`, the state 22 stores when 55 is present, as dead is
PROBABLE.

Silver Blades is the exception to the `$FF` rule. DOS guards both handlers in
mode 0 (`GAME.OVR 0x1144B`), and the live run of a staged DOS survivor showed HP
unchanged over 60 minutes and STATUS OKAY at expiry (CONFIRMED). The C64's camp
dispatch runs a row's handler only when magnitude bit 7 is set (`CAMP $1314`,
read). Handler 15 (`$858E`) drains 1 HP per 10 minutes of rest while HP is 2 or
more, and handler 22 (`$85A9`) sets HP 0 and status `$83` when 55 is held. So a
DOS `(0xFF, 1)` node for id 15 or 22 in Silver Blades becomes magnitude `$7F`
(`effects.SLOW_POISON_BLADES_C64`), a value no C64 routine writes for these ids
and whose clear bit 7 should keep both handlers from running. That the C64 then
leaves the survivor alone is PROBABLE: only the camp dispatch was read, not the
combat expiry or the other readers of the magnitude, and no C64 run of a
converted save exists. A C64 rest past the spell's expiry would settle it.
Reading back, `$7F` gives `(0xFF, 1)` for those ids, as do the C64's own `$FF`
(15) and `level | $80` (22); Curse's `(22, $7F)` stays a loss. Pool and Curse
keep `$FF` because both of their ports kill when the spell ends. C64 to DOS is
unchanged: a C64 survivor of the C64's own cast converts to the DOS node and
keeps his life.

Reproduce the static readings with `.venv/bin/python
tools/c64/effectcrosswalk.py`; a later title's run prints its caster-level ids.
Two of that derivation's four conditions, the DOS override of zero and the
`$4D80` read sweep, are read by hand and recorded above rather than re-read by
the tool. Select either later title with `--title`.
Use `--clock-minutes` for the duration sweep at a particular phase. The tool
finds each title's C64 disks through the registry/path helper and its DOS
engine through the archives registry. It reports missing files; the tests
skip without the player's disks. Mutation checks reject changed owner tests,
Strength branches, Prayer polarity, Haste markers and Mirror Image shifts.

## C64 effect-row sweep

A party can save after a spell cast in camp or combat with a row Wish has no
DOS rule for. **CONFIRMED table inventory, not a claim that every handler
writes:** `c64_row_sweep(title)` reads each title's spell records and checks
the four array-store operands of its generic camp and combat writers.

| Title | Camp records / nonzero | Combat records / nonzero | Distinct ids | Proven generic camp rows | Unresolved nonzero handler pointers |
|---|---:|---:|---:|---:|---:|
| Pool of Radiance | 67 / 46 | 67 / 45 | 42 | 20 | 71 |
| Curse of the Azure Bonds | 56 / 38 | 100 / 61 | 54 | 24 | 75 |
| Secret of the Silver Blades | 56 / 39 | 117 / 64 | 51 | 27 | 76 |

**CONFIRMED generic camp formula:** Pool handlers `$A858/$A85E` reach
`SPELLE04 $A79F`; the later handlers `$819C/$81A2` reach `ECL65 $80EE`.
The count is `(row fixed & $3F) + row per-level × caster level`, promoted
at 64 through the duration units above. The magnitude is a nonzero override
(`$2879`, `$2BFC`, `$2A6F` by title) or the caster level (`$2878`, `$2BFB`,
`$2A6E`). The single-target handler uses the selected owner, including
`$FF` for a party-wide target, and the other visits occupied party slots.
`unresolved_pointer_rows` gives the spell number, row address, id and handler
for every remaining nonzero table entry. No value or owner formula is
assigned to those handlers.

**CONFIRMED combat-row durations, read at `+1` (fixed) and `+2` (per level)
for every title:** Pool's id-51 row (spell 27) is 0 and 0, matching the
"duration 0" that `POOL_UNWRITTEN_ROW_IDS` records, and its id 13 row is 0 and
10. Curse's item-spell rows for ids 73 and 109 (spells 95 and 96, handlers
`$1DA9`, `$1DC2`) are 0 and 0 as well, so the table gives them no duration; the
minutes come from the handlers' own dice (2d4 + 4 for 73; 10 x (1d4 + 1) for
109), and their magnitude is the fixed item level 6, not the caster's level.

**CONFIRMED additional writers:** All three `POST.COM` files create id 5,
owner `$FF`, with the caller's duration and the free slot's unchanged
magnitude (Pool `$18E3`, Curse `$18AC`, Silver Blades `$192F`). Both later
`COM.PREP` files create id 45 with duration 0, magnitude `$FF` and owner
`$7EB4`. Silver Blades `DUNGEON $1618` creates id 12 with magnitude `$81`,
duration 1 and owner `$7EB4`. Curse `COMBAT $1F40`, `$1F53` and `$25D2`
select ids 13, 58 and 144 for its writer. The two-entry id tables at Curse
`COMBAT $2197` and Silver Blades `$26E8` select 27/137 and 27/107 for
their generic writers, with duration 1. The triggers are the engulf routine
`$1F13` (monster trait 57), the grab routine `$25A5` (trait 96) and
Confusion's outcome. The end-of-fight sweep (`$124F` in Curse, `$1242` in
Silver Blades) removes Curse 13, 58, 137 and 144, and the engulfer's 139 row
with 13, so no save holds one of them. Whether a
monster carrying trait 57 or 96 meets the party was not traced to a monster
record.

**CONFIRMED post-combat cleanup:** Pool `POST.COM $212E` strips ids 21, 29,
30, 51–54, 58–60 and 95. Curse `$2142` strips 21, 29–31, 51–53 and 58.
Silver Blades' `$21C1` sweep has no id strip. All three also clear rows with
a nonnegative combatant owner of 8 or more. The disk-backed test pins the
record counts, literal ids and strip-list sizes; it names each missing title
when it skips.

**CONFIRMED set difference as an upper bound:** the following ids occur in a
camp table record, a combat table record not stripped by `POST.COM`, or a
literal path, and `dos_record` says "no rule yet" for a sample running row
owned by one character. The post-combat strip applies only to combat-table
candidates: a camp cast can be saved before combat, and a literal writer has
its own path. An unresolved handler may write nothing, and a combat owner may
be a monster. Each id is listed with why its sample row has no rule.

| Title | Id | Why the sample row has no rule |
|---|---|---|
| Pool of Radiance | 11 | Charm converts through `pool_charm_record` in `c64_codec`, not `dos_record`. |
| Pool of Radiance | 13 | No DOS Pool engine writes a running id-13 node, and no C64 cast writes a running id-13 row. |
| Pool of Radiance | 32 | A table entry whose handler is not followed to a row write, and no DOS writer is read for it. |
| Pool of Radiance | 33, 51 | A duration-0 row converts as a granted record; no C64 cast writes a running row. |
| Pool of Radiance | 35, 49 | Prayer converts only as a party-wide row; an owned row has no rule. |
| Curse of the Azure Bonds | 13 | The engulf countdown, whose magnitude is a combatant index. Written on the attacked combatant by COMBAT `$1F40`, inside the trait-57 handler `$1F13`. The end-of-fight sweep COMBAT `$124F` (list `$1273`) removes it, so no save holds one. |
| Curse of the Azure Bonds | 128 | No C64 writer. Camp row 51 (ECL65 `$9929`) has handler `$82E9`, which never reaches the camp writer `$80EE` (callers `$819F`, `$81AF`, `$834C`), and no combat row or immediate writes 128. |
| Curse of the Azure Bonds | 68 | Feeblemind's duration-0 row converts as a granted record; the C64 holds INT at 3 and WIS at its permanent score, and DOS and the Amiga hold both at 3. A timed row has no rule, because no C64 cast writes one. |
| Curse of the Azure Bonds | 33 | A duration-0 row converts as a granted record; a running row has no rule. |
| Curse of the Azure Bonds | 49 | Prayer converts only as a party-wide row; an owned row has no rule. |
| Curse of the Azure Bonds | 58, 144 | 58 is the "already held" lock, written by engulf (COMBAT `$1F53`, duration 9) and grab (`$25CF`, duration 0), each only when the target holds no 58. 144 is the grabber's hold, written on the attacker by the grab routine `$25A5` (the trait-96 handler, COMBAT `$25D2`) at duration 0. Both are on the sweep list `$1273`, and POST.COM `$2142` also strips 58, so no save holds one. |
| Curse of the Azure Bonds | 137 | Confusion's outcome node, written at duration 1 by COMBAT `$2191` through the generic writer, whose `$118E` keeps one row per id and owner. The sweep list `$1273` removes it, so no save holds one; its record changes are not converted. |
| Secret of the Silver Blades | 33, 51 | A duration-0 row converts as a granted record; a running row has no rule. |
| Secret of the Silver Blades | 49 | Prayer converts only as a party-wide row; an owned row has no rule. |
| Secret of the Silver Blades | 55 | No C64 writer leaves a running row. The writer `$11FD` gets duration 0 (X = 0 at `$1827`) and `$183A` removes the row; only `$13AC`, with all ten trait slots full, writes `(55, owner, 0, $7F)`, at duration 0. |
| Secret of the Silver Blades | 68 | Feeblemind's duration-0 row converts as a granted record; the C64, DOS and the Amiga hold INT and WIS at 3. A timed row has no rule, because no C64 cast writes one. |
| Secret of the Silver Blades | 107 | Confusion's outcome node, written at duration 1 by COMBAT `$26E2` through the generic writer, with the one-per-owner check `$118B`. COMBAT `$1242` (list COMBAT2 `$F296`) removes it from `$F60D`, before the fight's only exit `$F619`, so no save holds one; its record changes are not converted. |
| Secret of the Silver Blades | 128 | No C64 writer. Camp row 51 (ECL65 `$9465`) has handler `$8337`, which never reaches the camp writer `$80EE` (callers `$819F`, `$81AF`, `$839A`), and no combat row or immediate writes 128. |

**Feeblemind (68), Curse and Silver Blades.** The C64 writes `level | $80` at
duration 0 (`COMBAT $1D61`, Silver Blades `$2227`) and lowers the scores in
force by title: Silver Blades stores 3 into INT and WIS (`COMBAT
$2262`-`$2267`), and Curse lowers INT only (`COMBAT2 $F2A2`, `$F825`). A live
Curse cast left INT 3 and WIS at its permanent score through the fight, a camp
save, a reload and a rest. DOS writes flag 0 (`0x2F0B7`) and keeps the effect
in INT and WIS in force. The recompute tests an override that a 68 node sets to
`0xFF`, not the score, so it always lands on 3 (Curse `0x36E5C`, Silver Blades
`0x379EC`-`0x379FC`, and the Amiga titles' equivalents); Silver Blades' cast
stores 3 and Curse's stores 7, which the next recompute replaces. A C64 source
therefore writes 3 into both DOS and Amiga in-force bytes, keeping the C64
score as the permanent one, and computes the cleric spell array from that 3,
so a feebleminded Curse cleric gets no wisdom bonus slots that DOS's load
rebuild would take away. A DOS or Amiga source writes
`effects.c64_feeblemind_scores` into the C64 record: 3 for each score the
title lowers and the permanent score for the other. When the 68 lands nowhere,
because every effect row is full, the permanent scores are written and the
character arrives without the spell. `effects.NEVER_EXPIRING_C64_BITS` holds
the bit 7 each C64 cast writes, apart from the DOS flag.

| Case | Sweep evidence and limit |
|---|---|
| Curse id 13 | **CONFIRMED combat path:** `COMBAT $1F40` sets id 13 and `$1F50` calls the row writer with a roll and bit 7. Cleanup does not strip 13. Survival of its target to save is unmeasured. |
| Later 12 without bit 7 | **CONFIRMED unwritten:** the combat Enlarge handler (Curse `COMBAT $172A`, Silver Blades `$1AA5`) sets bit 7 on the row it writes. |
| Later 14, 38 | **CONFIRMED unwritten:** the combat spell table has no row whose id is 14 or 38, so no combat cast writes them. |
| Later Mirror Image above 4 | **CONFIRMED unwritten:** the Mirror Image cast (Curse `COMBAT $184F` through `$2F6A`, Silver Blades `COMBAT $1BFE`) stores a `1d4` roll as the count, as at line 1233. |
| Pool Mirror Image with bit 7 | **CONFIRMED unwritten:** the Mirror Image cast stores a `1d4` roll as the count, in camp (`SPELLE04 $A96B`) and in combat (`SPELLE00 $AAC9`), as at line 1233. |
| Pool's stale `$2879` | **Bless CONFIRMED written and converted:** a Pool camp Enlarge followed by a Bless in the same camp visit saves six Bless rows with magnitude `$80` (the game-written `por-wish7-camp-enlarge-then-bless`). Pool's `POOL_CASTER_LEVEL_IDS` convert the byte whole (`1..$FF` to DOS data, flag 0). Invisibility keeping `$80`-`$FE` as its granted record is INFERRED from the writer code and the synthetic tests; no game-written Invisibility save with a leftover override exists. The readers: the Bless handler (`SPELLE01 $A73F`) reads nothing from the row, Dispel Magic (`SPELLE04 $AA5B`, `SPELLE00 $ABCE`) skips `$FF` and takes the low nibble, camp expiry (`CAMP $131F`) has no handler for these ids, and DOS reads the byte the same way (`tests/dos/test_dosaffectreads.py`). Curse and Silver Blades clear the override before each cast, so they never store it. |
| The Giant Strength id (Curse 146, Silver Blades 113) other than `$BC` | **CONFIRMED unwritten:** the Giant Strength cast writes only the fixed `$BC`, in camp (`ECL65 $83C2`) and in combat (`COMBAT $1EEA`). |
| Slowed outside level 1–15 or 63 minutes | **PROBABLE:** the duration is 3 plus the level in minutes, and the level runs 1–15. |
| Haste `$00`–`$1F` | **CONFIRMED written and converted:** a level-8 combat cast writes 0 (Curse `COMBAT $0FAE`–`$0FB3`, `$11CD`–`$11D0`; Silver Blades `COMBAT $1EE4`), levels 9–11 write 2, 4 and 6, and an item cast writes `$0C` (`COMBAT $08A1`, Silver Blades `$08A5`). Each converts as DOS data equal to the magnitude, flag 0. Only two things read the byte: the attack handler tests bit 4 (Curse `COMBAT $2207`–`$2215`, `GAME.OVR:0x10A95`–`0x10AD5`), and Dispel Magic reads the low nibble as the caster's level (`COMBAT $18E0`–`$190B`, `GAME.OVR:0x3120B`–`0x31268`). |
| Haste above `$1F` | **CONFIRMED unwritten:** the camp maximum is level 15 `\| $10` = `$1F` and the combat maximum is `$0E`. |

Combat rows are nine bytes: the fixed minutes at `+1`, the minutes per level
at `+2`, the id at `+5` and the handler at `+7`. **CONFIRMED** the later
titles' tables start at `COMBAT2 $EAA7` (Curse) and `$EB74` (Silver Blades),
Curse `COMBAT $0DFC`-`$0E16` building the pointer as `$EAA7 + 9 x (spell - 1)`.
Pool's 65 rows start at `SPELLE65 $D81B`; the two nine-byte steps after them
are the handler table at `$DA63`, not spells. Later camp ids use the whole row
byte: Curse camp row 39 writes 146 and row 49 writes 143, and row 51's `$80`
reaches no row writer (UNVERIFIED by disassembly: the row's handlers are Curse
`$82E9` and Silver Blades `$8337`, and neither is in `LATER_CAST_HANDLERS`).
Curse `COMBAT $11C4` stores the owner inside the writer
at `$11AE`; Pool `COMBAT $29F7` starts combat setup, while the combat row
stores are at `ECL64 $9A34`-`$9A46`.
