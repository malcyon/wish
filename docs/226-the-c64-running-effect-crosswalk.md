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

**CONFIRMED for Pool's camp clock:** for a nonzero count, the remaining time
is `count * unit_minutes - (clock_minutes % unit_minutes)`. Counts decrease
at clock boundaries, as measured by the two rests in
[133-active-effects.md](133-active-effects.md#the-duration-byte).
Walking defers expiry and combat treats coarse units differently; this
formula describes camp-clock expiry only. A whole zero byte never expires;
nonzero bytes with zero count remain unmeasured.

Thus 64 minutes at clock phase 0 has no exact byte. At phase 6, `$47` expires
after exactly 64 minutes. `$46` expires after 60 or 54 minutes respectively.
The tool enumerates every exact candidate rather than calling truncation
lossless. DOS's unit and removal test are independently established in
[162-spc-permanence.md](162-spc-permanence.md).

## Pool of Radiance ids and values

**CONFIRMED scope:** DOS Pool version 1.3 `GAME.OVR` and unpacked `START.EXE`,
compared with C64 Pool `ECL65`, `CAMP`, `SPELLE04`, `SPELLE01` and `SPELLE65`.
The value rules below have not been established for the two later titles.

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
| Overlapping Enlarge/Strength nodes cannot use the isolated-node rule without further work | **CONFIRMED gap:** DOS `0xF11E` skips restoration for data above 127; `0x2C046` transfers displaced strength between nodes. C64 `SPELLE04 $A8FD/$A904` tests existing ids 38/12. Read that replacement path and both node orders before specifying a writer. |
| Prayer's owner/global representation is not settled | **UNKNOWN:** camp writes a party-wide id 35; the combat handler uses id 49. Compare DOS per-character Prayer records with the C64 predicate and combat initialization before deciding whether to merge rows or preserve per-character ownership. |
| Id 13 is not a proven strength mapping | **CONFIRMED negative:** the C64 combat dispatch shares id 14's charisma handler; DOS points it at the empty handler `0x11DF6`. Do not infer its value rule from the name Reduce. |
| Other ids and the later titles' data encodings | **UNKNOWN:** their spell tables and handlers need their own reading; the tool reports only the later titles' duration packing. |

The next builder can use the measured operands and the isolated Pool rules,
but a complete C64 writer still needs the three unresolved mappings above
and a duration policy. No new emulator driver was built and no emulator was
started for these measurements.

One existing bounded live check can corroborate the exceptional-strength
translation: run `effectdrive.py` with `--steps 0 --rest 0 --rest-hours 0
--stage 0=0C:02:01:E2`, through its pool, headless and silent. It copies the
registered `PORSAVE13.D64`, captures slot 2's abilities and the effect arrays,
enters camp once, and captures them again. Stop after that camp entry or the
driver's boot timeout. Expected: id 12 expires, slot 2 becomes strength
18/98, and the other character slots are unchanged. A different strength or
changed non-owner refutes the conversion. Save the resulting observations
outside the repository before releasing the slot.

Reproduce the static readings with `.venv/bin/python
tools/c64/effectcrosswalk.py`; select either later title with `--title`.
The tool finds C64 disks through `$POR_DISKS` and the normal disk finder,
and DOS through the archives registry. It reports missing files; the tests
skip without the player's disks.
