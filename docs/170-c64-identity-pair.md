# The C64 side of the DOS identity byte: `0x0E6`-`0x0E7`, drawn at creation and never read

What the C64 keeps where DOS keeps its `0x0AB`, read out of the engine for
`#258 (The C64 side of 0x0AB is unnamed, so the conversion drops it with no
issue behind it)`. The DOS half is in
[50-experiments.md](50-experiments.md), "Two same-named characters and one
byte: `unnamed_0ab`", and in `goldbox/dos_layout.py`'s note on the field.

## The finding

**The C64 record's `0x0E6`-`0x0E7` is the same field as DOS `0x0AB`: two
bytes GEN draws from the random generator when it creates a character, per
character, stable through play -- and nothing in the game reads them.**
CONFIRMED from the code on all eight sides, and corroborated in the running
game by watchpoints that never fired.

The C64 needs no identity byte because its add screen refuses a duplicate by
**name alone**, and a save disk can hold only one character of a name in the
first place. So the DOS byte has no *consumer* on the C64, but it does have a
**home**: writing it into `0x0E6` costs nothing, changes nothing the C64 does,
and lets a C64 to DOS conversion give the byte back instead of inventing one.

| grade | claim | evidence |
|---|---|---|
| CONFIRMED | `0x0E6`-`0x0E7` are written by exactly one site, two raw calls to the generator | `GEN $0C01`-`$0C0A`; the boot disk's `POOLRE` is a copy of the same code |
| CONFIRMED | nothing reads them | census of 589 files: 0 reads absolute, 0 indirect (`LDY #$E6` then `(zp),Y`), 0 against any of the twelve party slots; in three boots the load watchpoint on `$6BE6`-`$6BE7` never moved except in step with the unreferenced `$6BE4`-`$6BE5` beside it (block copies), while the experience control moved alone |
| CONFIRMED | the add screen tests the name and nothing else | `GEN $1897`, read in full below; in the running game a different character under a party member's name was starred and refused, and a party member's own record under a new name was let in |
| CONFIRMED | the pair is Pool of Radiance's alone | Curse's and Silver Blades' GEN never write it and nothing in either title reads it (412 and 349 files); SSI's own Curse party reads `00 00` in 6 of 6 and a Silver Blades party in 4 of 4 |
| PROBABLE | one save disk holds one character of a name | the save routine at `GEN $19B4` hands the drive `S0:\x01NAME` -- the scratch command -- before the write at `$3039`; `$3039` itself was not read |

## What writes it

`GEN` runs at `$0800`. Inside the creation sequence that also sets level 1,
one attack, AC 10 and movement 12:

```
$0BFC  LDA #$0C / STA $6B9F     ; movement 12
$0C01  JSR $2D88                ; LIBRARY's generator (147-combat-rolls.md)
$0C04  STA $6BE6                ; record 0x0E6
$0C07  JSR $2D88
$0C0A  STA $6BE7                ; record 0x0E7
$0C0D  LDX #$01 / STX $6C00     ; roster_in_use
```

No bound, no arithmetic: the same shape as the DOS write site, `call random;
mov es:[di+0ABh], al`, one byte there and two here. On the fourteen save
disks the pair is distinct for every one of the ten names and identical for a
name on every disk it appears on (MALCYON `E6 C3` on all fourteen), which is
what a value drawn once and never rewritten looks like.

## What reads it: nothing

`tools/recordsweep.py`, record at `$6B00`, every PRG on every side:

| census | files | references to `+0x0E6`/`+0x0E7` |
|---|---|---|
| absolute mode | 589 | 2, the GEN stores above (and the `POOLRE` copy) |
| `LDY/LDX #$E6`/`#$E7` then an indirect-indexed opcode within ten bytes | 589 | 1, inside `PIC02`: picture data |
| absolute mode against each party slot `$4D00 + n*$100`, n = 0..11 | 589 | 0 code; two hits inside `PIC1E` and `POOLRA` data |
| Curse of the Azure Bonds, record at `$7C00` | 412 | 0 |
| Secret of the Silver Blades, record at `$7C00` | 349 | 0 |

For scale, `0x0E3` next door is referenced by `GEN` and `LIBRARY` and `0x0E8`
(experience) by dozens of sites.

## The add screen, read in full

`ADD CHARACTER TO PARTY` is `GEN $18D4`-`$196A`:

* `$18E3`-`$18FD` walks the eight roster blocks (`LIBRARY $3189`, 32 bytes
  each into `$6C00`), counts player characters by bit 7 of `flags_0b8`, and
  keeps the lowest free slot; none free -> string `$37` `THE PARTY IS FULL`.
* `$190E` and `$1915` build the directory list (`$16F1`) and take a pick
  (`$1760`).
* `$192B` loads the picked `\x01NAME` file to `$6B00`. The only byte of the
  candidate the handler then reads is `$6BB8`: an NPC skips the count, a
  seventh player character -> string `$38` `TOO MANY PLAYER CHARACTERS`.
* `$195B` copies the record into the free slot (`LIBRARY $441E`, then `$3173`
  for 256 + 256 bytes) and stars the list entry.

**The duplicate test is in the list builder.** As each directory entry closes
its quote (`$1847`), `$1897` loads every occupied party slot into `$6B00`
(`LIBRARY $315A`) and compares the entry's name with the record's:

```
$18B6  LDY $2B4C           ; the entry's length, clamped to 15
$18B9  LDA ($9E),Y         ; entry byte Y
$18BB  CMP $6AFF,Y         ; record name byte Y-1
$18BE  BNE next slot
$18C0  DEY / BNE $18B9
$18C3  LDA #$2A / STA ($9E),Y   ; all matched: '*' in front of the entry
```

Nothing after the `CMP`. The picker at `$17F2` returns non-zero for a starred
entry and the handler loops back to the list (`$191A BNE $1915`), so a starred
name cannot be picked and nothing is drawn -- the same silence as DOS, without
the tiebreak.

## In the running game

`tools/c64addchar.py`, one boot per run on a pool slot, off a copy of
`PORSAVE.D64` edited in two ways: the `\x01MALCYON` export rewritten to hold
BRUTUS's record under MALCYON's name (same name as a party member, a
different character, pair `57 D1` against the party's `E6 C3`), and a new
`\x01TWIN` holding MALCYON's own record under a new name (pair `E6 C3`, the
same as the party member's). Three load watchpoints that do not stop the
machine: `$6BE4`-`$6BE5` (nothing references them), `$6BE6`-`$6BE7`, and
`$6BE8`-`$6BE9` (experience). A block copy reads all three alike; a field
read shows on one.

Run 1, party of six already loaded:

| stage | `$6BE4`-`5` | `$6BE6`-`7` | `$6BE8`-`9` | screen |
|---|---|---|---|---|
| main menu, LOAD SAVED GAME | 0 | 0 | 0 | six in the party |
| ADD CHARACTER TO PARTY, list built | 0 | 0 | 0 | `*` on all six names, TWIN unstarred |
| pick the starred `MALCYON` (BRUTUS's record) | 0 | 0 | 0 | list unchanged: refused, nothing drawn |
| pick `TWIN` | 0 | 0 | 0 | list unchanged: `TOO MANY PLAYER CHARACTERS` went by, six already in |
| VIEW CHARACTER, BRUTUS's sheet | 0 | 0 | **2** | `EXP 0` drawn: the control fires and the pair does not |

The MALCYON entry was starred although the record behind it was BRUTUS's --
the name is the whole test.

Run 3, after REMOVE CHARACTER FROM PARTY for LADY KATHERINE and SILAS (run 2
was the same drive mis-steered, and its counts agree):

| stage | `$6BE4`-`5` | `$6BE6`-`7` | `$6BE8`-`9` | screen |
|---|---|---|---|---|
| loaded | 0 | 0 | 0 | six in the party |
| two removed | 12 | 12 | 12 | the export of each is written, which reads the whole record |
| ADD list built | 12 | 12 | 12 | `*` on BRUTUS, MAGNUS, **MALCYON**, ROLAND; SILAS, LADY KATHERINE and TWIN plain |
| pick the starred `MALCYON` | 12 | 12 | 12 | list unchanged, and no read at all: a starred pick is refused before the file is opened |
| pick `TWIN` | 14 | 14 | 14 | `*TWIN`: added; the copy into the slot reads each byte once |
| pick `LADY KATHERINE` | 16 | 16 | 16 | `*LADY KATHERINE`: added |
| VIEW, TWIN's sheet | 16 | 16 | **18** | `TWIN`, `MALE ELF AGE 176`, `MAGIC-USER`, `EXP 0`: MALCYON's sheet under the new name |
| SAVE CURRENT GAME, read back | 16 | 16 | 18 | `MALCYON E6 C3` and `TWIN E6 C3` both in the party |

Every count on the pair moves only when the count beside it moves, by the
same amount, and the control moves alone when experience is drawn. The
engine-written save with two members sharing a pair is specimen
`por-party-twin-pair` under `$WISH_SPECIMENS`.

## Two things found on the way

**`0x0E3` is the strength-adjustment flag, and the C64 writer leaves it
zero.** `GEN $0B79` writes `LDA #$01 / STA $6BE3` at creation (Curse's GEN at
`$0C31` does the same at `$7CE3`), and the only reader is the roster
recompute in `LIBRARY`:

```
$375C  LDX $6BE3        ; 0x0E3
$375F  BEQ $3764        ; zero: index 0, no adjustment
$3761  LDX $6BE2        ; else index by strength_index
$3764  LDA $3651,X      ; to-hit adjustment
$376A  LDA $3670,X      ; damage adjustment
```

`$3651` and `$3670` are AD&D's strength table (index 18 -> +1/+2, 21 -> +2/+4,
23 -> +3/+6). Every engine-made player character on the C64 disks of all three
titles reads `01` there; `goldbox.c64_codec.write` sets `strength_index` and
leaves `0x0E3` at zero, so BAKSHI (18/90) converts with no strength bonus.
DOS keeps the same flag as `0x0AA`, `strength_bonus`. Filed as
`#277 (A DOS character converted to the C64 loses the strength bonus to hit
and damage, because 0x0E3 is written zero)`.

**`0x0E4`-`0x0E5` are referenced by nothing** in 589 files and read `00 00` in
every player character. Unattributed, and with no reader there is nothing to
attribute them to.

## What the conversion should do

The specification `#258 (The C64 side of 0x0AB is unnamed, so the conversion drops it with no issue behind it)` asks for, in the shape a `junior-dev` can build:

* **DOS to C64:** write neutral `unnamed_0ab` into C64 `0x0E6`; `0x0E7` gets
  zero. Both values are measured harmless -- no reader -- and the field stops
  being a drop. The layout names `0x0E6`-`0x0E7` (one field, two bytes: the
  identity pair) and `0x0E3` (the strength flag), leaving `0x0E4`-`0x0E5`
  in `region_0e3` as unattributed.
* **C64 to DOS:** `0x0AB` from `0x0E6` when the source is a Pool of Radiance
  record, and `goldbox.dos.identity_byte`'s digest for Curse and Silver
  Blades, whose GEN never writes the pair (`00 00` in every party of theirs).
  `#216 (Every converted DOS character carries the same identity byte at
  0x0AB)` asked for exactly this if the pair turned out to be the same field:
  stable where the digest moves with experience, and distinct within every
  party the engine ever made.
* **The test:** convert a shipped DOS record to C64 and back, and assert
  `0x0AB` round-trips; convert the six `PORSAVE.D64` exports to DOS and assert
  their `0x0AB` values are the six `0x0E6` bytes, distinct.

## The ruling: written for all three titles, and never reported

Donald, 2026-09-05: *"Yes, write the identity byte. No, don't tell the user
about it."* The measurement above still stands -- Curse's and Silver Blades'
own GEN never draws the pair, and their shipped parties hold `00 00` there --
but `0x0E6`-`0x0E7` are part of every title's 580-byte layout, and nothing on
the C64 reads them in any of the three. So `goldbox.c64_codec.write` now puts
DOS's `unnamed_0ab` into `0x0E6` for Curse and Silver Blades exactly as it
already did for Pool of Radiance, changes nothing either game does, and says
nothing about it: the "nowhere on the C64 to put it" drop line this file
previously specified for the other two titles is gone.

**This is the write direction alone, and the round trip is not yet
finished.** `read` still asks `RecordShape.identity_pair` -- False for Curse
and Silver Blades -- before trusting a stored `0x0E6` as the pair GEN drew, so
a Curse or Silver Blades character converted to the C64 and back to DOS today
still gets `goldbox.dos.identity_byte`'s digest, the same as before this
change. What this change buys is a home for the byte on the C64 side and the
gone drop line; teaching `read` to trust `0x0E6` for these two titles once it
is *our own* writer's value there, and telling that apart from a shipped
record's untouched `00 00`, is left for whoever finishes the round trip.

Under `.claude/rules/conversions.md`'s three reasons this was "the destination
has no such field", and reading the layout turned it into a field with a home.
