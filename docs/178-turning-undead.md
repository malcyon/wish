# Turning undead, and the byte only one port keeps

Where each port keeps a cleric's power to turn undead, why a converted cleric
arrived on the C64 unable to use it, and what the C64 writer computes instead.

`#288 (A converted cleric or paladin arrives on the C64 unable to turn undead,
because DOS keeps no turning byte and nothing computes one)`.

## What the player saw

Convert a party to the C64, walk it into a fight, and take the cleric's turn.
His command bar reads

    MOVE VIEW AIM USE CAST QUICK DONE

There is no `TURN` on it. The command is not greyed out, not refused with a
message: it is not on the bar at all, and the only way to notice is to know it
should be there. Pool of Radiance's first dungeons are full of skeletons and
zombies, so this is a cleric who cannot do the thing his class is for.

## The gate: one byte, one bit of a menu mask

`COMBAT` builds the combat bar from a mask that starts as `$FF` and loses one
bit per command the character may not take.

    $09CF  LDA #$FF / STA $48F8      every command allowed
    $09D9  LDA $6BA4                 turn_power, record 0x0A4
    $09DC  BNE $09E3                 non-zero: leave TURN alone
    $09DE  LDA #$DF                  zero: clear bit 5
    $09E0  JSR $133D                 AND $48F8 / STA $48F8

`$0A24` hands the finished mask to the bar builder together with the word
table at `$1344`, whose count byte is 8 and whose words are

| bit | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| word | MOVE | VIEW | AIM | USE | CAST | **TURN** | QUICK | DONE |

`$DF` is `%11011111`, so the bit it clears is 5, and bit 5 is `TURN`.
**CONFIRMED**, from the bytes and from the running game below. The same shape
is in both later titles, in `ECL64` rather than `COMBAT`: Curse at payload
`+0x1048` (`LDA $7CA4 / BEQ`, then `LDA #$DF`) with its own eight-word table
at `+0x18A6`, and Silver Blades at `+0x1040` with the words in `COMBAT2`,
which `ECL64` names by pointer (`LDX #$A8 / LDY #$F8`). Each title adds one
further condition of its own past the byte -- Curse a table read at `$95E8,X`,
Silver Blades a byte at `$7D1D` -- and neither can reach the command with a
zero at `0x0A4`.

## Watched in the running game

One save, one byte, two boots, on VICE pool slots 0 and 2 with `PORSAVE13.D64`
staged into the instance's own directory and the party walked into the Slums
ambush. `tools/turndrive.py` reads the acting character's name and `$6BA4` out
of the working record at `$6B00` in one monitor stop and photographs row 24, so
every line pairs the byte the engine read with the bar it drew.

| boot | character | class | `0x0A4` | his bar |
|---|---|---|---|---|
| 1 | ROLAND | cleric 1 | 1, as the game wrote it | `MOVE VIEW AIM USE CAST TURN QUICK DONE` |
| 2 | ROLAND | cleric 1 | 0, as the conversion wrote it | `MOVE VIEW AIM USE CAST QUICK DONE` |
| 2 | BRUTUS | fighter, no cleric level at all | 9, staged | `MOVE VIEW AIM USE TURN QUICK DONE` |

Every other character holds 0 in both boots and never sees `TURN`; that is ten
readings of five characters. The third row is what makes it the byte rather
than the class: **BRUTUS is a fighter and the game offers him the command**,
because `$09D9` reads `$6BA4` and nothing else. The two halves of the second
boot were one fight, so they share a disk, a route and a tactic.

## Where each port keeps it

**The C64 stores the value and never recomputes it.** `GEN` writes `0x0A4` in
exactly two places -- at creation, from a table indexed by the *class* number
(`$0BDB LDY $6B73 / LDA $100C,Y`, which gives a new cleric 1 and everyone else
0), and at every training, from the turning table. Nothing runs on load. Two
engine-written specimens prove that end of it: `WISH-SPEC-curse-h-engine-resave`
and `WISH-SPEC-ssb-d-engine-resave` are converted parties the game itself
re-saved, and their clerics still hold 0.

**DOS stores nothing of the kind.** `GAME.OVR:0x139CD`, the turn-undead
routine, reads the cleric level out of `class_levels[0]` at record `0x096`
when the player presses the command, bands it -- 1 to 8 as it stands, 9 to 13
as 9, otherwise 10 -- and uses that as the column of the turning matrix at
`DS:0x447`. The row is `es:[di+0x76]` **of the target**. Its own menu builder
at `GAME.OVR:0x9F8C` offers the word `Turn ` on `cmp byte ptr es:[di+0x96], 0
/ jle`, which is again the cleric level. So there is no caster-side byte in a
DOS record for a converter to copy.

### The DOS byte at `0x076` is the undead's row, not the caster's

`goldbox/dos_layout.py` names DOS `0x076` `turn_power` at PROBABLE, with a
note saying the two C64 turning bytes cannot be told apart from a party with
no undead in it. They can be told apart from the code and from the monster
files, and the answer is the other one:

* the turning routine reads `0x076` **off the target** and multiplies it by
  ten as the matrix row (`0x13A2A`);
* eleven of the 103 distinct DOS Pool of Radiance monster records carry a
  non-zero `0x076`, every one undead, and the values are the published AD&D
  rows -- skeleton 1, zombie 2, ghoul 3, wight 5, wraith 7, giant skeleton 8,
  mummy 8, juju zombie 9, spectre 9, vampire 10, plus FERRAN MARTINEZ at 9;
* every player character in either port reads 0 there.

That is the same population, value for value, that the C64 keeps at `0x0A3`
and `goldbox/layout.py` calls `turn_class`. **CONFIRMED**: DOS `0x076` is the
C64's `0x0A3`, and DOS has no counterpart to `0x0A4` at all.
`tools/turncensus.py --dos` re-runs the monster half.

## The tables

All three C64 engines reach the same fourteen numbers by three mechanisms.

| | where | how |
|---|---|---|
| Pool of Radiance | `GEN $2388`, table at `$2399` | `LDX level_cleric / BEQ` -- **no byte at all for a non-cleric** -- `CPX #$0E` clamp, `LDA $2399,X` |
| Curse of the Azure Bonds | `GEN $113F` | arithmetic, and an unconditional `STA $7CA4`, so a character who turns nothing stores 0 |
| Secret of the Silver Blades | `GEN $13A5` | Curse's arithmetic with one branch more |

Silver Blades' routine, read here for the first time --
`#89 (Silver Blades' trainer grants spells from a table, and
goldbox/levelup.py offers them from a menu)` had left it as one of that
title's unread trainer inputs:

    $13A5  LDA $7CCF / SEC / SBC #$02      the paladin, two levels back
    $13AB  BCS +2 / LDA #$00               never below zero
    $13AF  CMP $7CCA / BCS +3 / LDA $7CCA  the better of that and the cleric
    $13B7  BEQ store                       turns nothing: store zero
    $13B9  CMP #$04 / BCC store            1, 2 and 3 as they stand
    $13BD  ADC #$00                        + 1 from 4 up
    $13BF  CMP #$0A / BCC store
    $13C3  CMP #$0F / BCC $13CB            10 for 10 up to 14
    $13C7  LDA #$0C                        12 from 15
    $13CD  STA $7CA4

Expanded over a cleric's whole range that is `1 2 3 5 6 7 8 9 10 10 10 10 10
12` -- Pool of Radiance's `$2399` entry for entry, which is why
`goldbox/levels.py` carries the same fourteen numbers three times rather than
sharing one tuple. A paladin turns as a cleric two levels weaker in both later
titles and Pool of Radiance has no paladin at all. The routine is reached from
the recompute sequence at `$0FD2`, alongside the saving throws and the thief
skills.

**CONFIRMED**, on four engine-written records: Silver Blades ships DOMINIC, a
cleric 8, holding 9, and GUY DE VALOIS, a paladin 8, holding 7; and Curse's
own training hall wrote 7 for SHARA at cleric 6 and 5 for MATHEW at paladin 6
during `#18 (Measure Curse's trainer so Level Up works there)`.

## The census

`tools/turncensus.py` compares every C64 record on this machine against the
derivation.

| | records | agree | disagree |
|---|---|---|---|
| the player's save disks and the shipped parties | 132 | 132 | 0 |
| the specimen tree | 78 | 55 | 23 |
| **total** | **210** | **187** | **23** |

**Every one of the 23 is a converted party this project itself wrote**, and
every one of them is a cleric or paladin holding 0. The clearest single disk
is `WISH-SPEC-curse-trained-party`, where SHARA (cleric 6) and MATHEW (paladin
6) carry the trainer's own 7 and 5 while MARK, a paladin 5 the hall did not
train, is still on the conversion's zero -- the bug and its proof on one disk,
written by the engine in one session.

## What the conversion does now

`goldbox/c64_codec.py` **computes** `turn_power` rather than copying it, from
the character's own cleric and paladin levels through
`goldbox.derive.turn_power`. The neutral field is still consumed, so a source
that refuses it is still reported; what changes is that the byte written is
the one this title's own `GEN` would write.

Copying and computing differ only where the source was wrong. No engine-written
player record on this machine disagrees with the derivation, so nothing that
was right before is lost. The exceptions are in the monster files rather than
in any save: `MON*` holds NPC clerics whose bytes are off the table (MACE, a
cleric 4, holds 4 where the table gives 5, and 7TH LVL CLERIC holds 0), and a
monster record is not something the converter converts.

## Still open

**The C64-to-DOS direction writes the wrong field.** `goldbox/dos.py` copies
neutral `turn_power` straight into DOS `0x076`, which the section above shows
is the undead's row. Converting Curse's shipped CLERIC to DOS therefore gives
him a 6 there, the wight and wraith row. That predates this work -- the C64
reader has always put `0x0A4` into the neutral field -- and it is
`#297 (A cleric converted from the C64 to DOS is given an undead's turning
row, because the DOS writer puts turn_power in the undead's byte)`.

**Nobody has watched a converted cleric turn actual undead.** The bar is the
gate and the bar is measured; the roll that follows is not. `GAME.OVR:0x13A38`
reads the matrix at `DS:0x447 + turn_class * 10 + band` and compares a 1d20
against it, and the C64's own resolution has not been read at all. What would
settle it: convert a cleric, fight the skeletons in Sokol Keep, press `TURN`,
and photograph what the game prints.

## Where the pieces are

| | |
|---|---|
| the derivation | `goldbox/derive.py:turn_power` |
| the tables | `goldbox/levels.py`, `_TURN_POWER_POOL`, `_TURN_POWER_CURSE`, `_TURN_POWER_SILVER` |
| the writer | `goldbox/c64_codec.py`, the turning block of `write` |
| the census | `tools/turncensus.py` |
| the running-game run | `tools/turndrive.py` |
| the tests | `tests/test_turning.py` |
