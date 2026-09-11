# The later C64 titles' two ability arrays: `0x065` is the base, `0x014` is what is in force

What the second copy of the seven ability scores is for in *Curse of the Azure
Bonds* and *Secret of the Silver Blades*, and which of the two the engine
treats as a character's current score. Written for
`#367 (What is the second ability array at 0x065 for, and which of the two
does the engine treat as current?)`, which Donald opened because the project
had been calling the field "a second copy the game keeps for no reason" and
that phrasing was an assumption rather than a measurement.

## The finding

**`0x065`-`0x06B` is the character's permanent score, the number a player
would call "my strength". `0x014`-`0x01A` is the score in force right now,
and the engine *derives* it: current := base, then the drains, then the items
and spells.** Everything in play reads `0x014` -- the sheet, the carrying
allowance, combat, spells. Two things read `0x065`: character generation,
which rolls into it and clamps it against the racial minimum and maximum, and
the training hall, which takes the prime-requisite bonus for a demihuman's
level limit from it.

So it *is* a `(current, base)` pair, and the order is **`0x014` first**.

| grade | claim | evidence |
|---|---|---|
| CONFIRMED | `0x065` is where generation puts the rolled score, and `0x014` is a copy of it | `GEN $0CCF` `STA $7C65,X`; `GEN $1E9C` `LDX #$0B / LDA $7C65,X / STA $7C14,X` at the end of it |
| CONFIRMED | the racial minimum and maximum clamp `0x065` | `GEN $1E56`-`$1E9B`, against the per-race tables at `$0D45` and `$0D1B` |
| CONFIRMED | `0x014` is rebuilt from `0x065` whenever what is in force changes | the recompute at `ECL65 $913B`: `LDA $7C65,X / STA $7C14,X` and then a six-entry jump table, one handler an ability. Twelve callers, all in `ECL65`; the same routine is linked into `SPELLE65` and `COMBAT2`, and `COMBAT $2A0E`/`$2A13`/`$2A18` enter it with X = 3, 0 and 1 |
| CONFIRMED | the strength handler is base minus drain plus items | `ECL65 $9160`: `LDA $7C6B / STA $7C1A`, `LDA $7C14 / SEC / SBC $7CFF / STA $7C14`, then effect `$88`, item `$26`, and effect `$85` through a twelve-entry table at `$9223`/`$922F` holding `18/00, 18/01, 18/33, 18/4C, 18/5B, 18/64, 19, 20, 21, 22, 23, 24` |
| CONFIRMED | the sheet draws `0x014` | `LIBRARY $36D7`-`$3718` walks `$7C00,X` from `$14` to `$19` and appends `(nn)` from `$7C1A`; in the running game six characters staged with the arrays crossed drew the `0x014` number, 6 of 6 |
| CONFIRMED | the carrying allowance at `0x0E2` comes from `0x014` | `LIBRARY $19EE` (`$3FB6` at that overlay's own base `$2DC8`); in the running game the engine wrote 9 for a character holding 9 at `0x014` against 18 at `0x065`, and 18 for one holding 18 against 9 |
| CONFIRMED | the training hall's racial level cap comes from `0x065` | `GEN $156B`: `LDY $1599,X / BMI skip / LDA $7C65,Y / CMP #$12 / BCS skip / INC $B0 / CMP #$11 / BCS skip / INC $B0`, then `LDA $15A9,X / SEC / SBC $B0` |
| CONFIRMED | Silver Blades' sheet **marks** an ability whose two halves disagree | `LIBRARY $30F8`: `LDA $7C14,X / CMP $7C65,X / BNE`, and for strength `LDA $7C1A / CMP $7C6B / BEQ`, falling into `LDA #$2B / LDY #$0C / STY $03CC / JSR $3C18` -- a `+` in colour 12 |
| CONFIRMED | the training hall does **not** resynchronise the pair | two trainings in the running game left both arrays exactly as staged, and the engine's own `SAVE CURRENT GAME` wrote all six records back still disagreeing |
| PROBABLE | Silver Blades works the same way throughout | its census has the same shape (94 references to `$7C14`-`$7C1A` against 44 to `$7C65`-`$7C6B`, 19 of the 26 at `$7C65` in `GEN`), the recompute dispatcher and strength handler are the same instructions, and `GEN $1F0A` is Curse's copy loop with `LDX #$06` -- but no Silver Blades party has been driven with the arrays crossed |

## Where the record is, so the addresses mean something

Both later titles stage the working record at **`$7C00`**, so `0x014` is
`$7C14` and `0x065` is `$7C65`. Two fields fix that base independently:
`$7CC9` is the per-class level array at `0x0C9` and `$7CEB` is `class_bits` at
`0x0EB`. The party's roster copies are at `$4F00 + slot * $100` in Curse,
which is where `SAVEAZURE` loads plus its `0x400` slot offset.

`tools/abilitypair.py` is the tool: `refs` for the census, `stage` to write
the two arrays apart, `read` to say what a disk holds.

## The census, which is what makes the answer visible at a glance

`tools/absrefsweep.py` over 412 distinct Curse files, counting absolute
operands that name each byte:

| window | in code files | where |
|---|---|---|
| `$7C14`-`$7C1A` | **129** | `ECL65` 39, `COMBAT2` 37, `SPELLE65` 34, `GEN` 6, `LIBRARY` 5, `CAMP` 2, `COMBAT` 2, `COM.PREP` 1, `DUNGEON` 1, `SECSET64` 1, `SPELLE20` 1 |
| `$7C65`-`$7C6B` | **38** | `GEN` **25**, `ECL65` 4, `SPELLE20` 3, `SPELLE65` 3, `COMBAT2` 2, `POST.COM` 1 |

Two thirds of the second array's references are in the generation and
training overlay, and the first array's are spread across every overlay that
does anything with a character. Silver Blades: 94 against 44 over its 347
files, 19 of the 26 at `$7C65` in `GEN`.

`0x06C`-`0x070` and `0x01B`-`0x01F` -- the five bytes past exceptional
strength that `GEN $1E9C`'s twelve-byte copy also moves -- have **zero**
references in either title. Nothing but the copy touches them.

## The drain counter at `0x0FF`, which is not a portrait in these titles

`goldbox/layout.py` names `0x0FE` and `0x0FF` portrait head and body, which
is Pool of Radiance's reading. In Curse they are counters: `ECL65 $8578` is
the strength-drain script,

    LDX #$46 / JSR $818C          ; the message
    LDA $7C65 / SEC / SBC $7CFF   ; the **base** less the drain so far
    CMP #$04 / BCC (the character is finished)
    LDX #$04 / JSR $80CD
    INC $7CFF                     ; one more point of drain
    LDX #$00 / JMP $913B          ; and recompute strength

and `ECL65 $9166` is where it is applied: `LDA $7C14 / SEC / SBC $7CFF /
STA $7C14`, immediately after the dispatcher has copied the base over. So the
drain is stored once and re-applied on every recompute, which is exactly why
the base has to be kept somewhere.

The corroboration is the import. `SPELLE20 $0D64` reads a Pool of Radiance
character into a Curse record with `LDX #$0B / LDA $7C14,X / STA $7C65,X` --
the copy the other way, because a Pool record has only one array -- and then
`STA $7CFE / STA $7CFF` with A zero, because a Pool record's bytes there are
a portrait and would otherwise read as fifty-odd points of drain.
`docs/116-second-game.md` section 4 lists exactly those three offsets among
the fifteen bytes the import changes, and this is why.

## The running-game measurement

`WISH-SPEC-curse-h-engine-resave.D64` staged apart by
`tools/abilitypair.py stage`, three abilities, each crossed both ways, one
boot on a pooled VICE instance on 2026-09-07:

| who | ability | `0x014` | `0x065` | the sheet drew |
|---|---|---|---|---|
| PHILIPPE | strength | 9 | 18 | STR 9 |
| SHARA | strength | 18 | 9 | STR 18 |
| LEDERA | intelligence | 7 | 16 | INT 7 |
| TRAVIS | intelligence | 16 | 7 | INT 16 |
| MARK | constitution | 8 | 17 | CON 8 |
| MATHEW | constitution | 17 | 8 | CON 17 |

Six of six, and the load recomputed nothing: read out of memory straight
after `LOAD SAVED GAME`, all twelve arrays held what was staged.

A sheet is a screenshot, so the measurement that carries the finding is the
one the engine wrote down. PHILIPPE and SHARA were trained a level in Curse's
own hall, which ends in `JSR $3FB6`:

| | `0x014` strength | `0x065` strength | `0x0E2` before | `0x0E2` after |
|---|---|---|---|---|
| PHILIPPE, magic-user 5 -> 6 | 9 | 18 | 18 | **9** |
| SHARA, cleric 5 -> 6 | 18 | 9 | 17 | **18** |

Each moved to that character's own `0x014`. Neither stayed put, so "it was
not recomputed" is excluded, and they moved in opposite directions, so a
coincidence is excluded.

`WISH-SPEC-curse-367-crossed-abilities-resave.D64` is that party saved back
by the game itself -- the only Curse save anywhere whose two arrays differ and
which the engine wrote. Its `provenance.toml` now reads `edited_afterwards =
true`, because two bytes of the D64's **directory entry** -- not the record
above -- were closed on 2026-09-08 by `#298 (A save disk copied out of an
emulator slot before the drive closes the file cannot be loaded by the
game)`: the disk had been copied out of its pool slot before the emulated
drive finished writing it, and would not load until the repair. The record
above is what the engine wrote and nothing in it moved -- every file on the
disk reads back byte for byte identical either side of that repair.
`tests/test_abilitypair.py` reads it.

### The formula, and the five numbers behind it

`LIBRARY $19EE` in Curse and `$3804` in Silver Blades are the same
instructions: the score itself below 18; the score plus 5, capped at 30, above
it; and at exactly 18, 18 plus however many brackets the percentile clears.
The bracket table is `09 0F 19 33 00` at `LIBRARY $3FE3` in Curse and `$3831`
in Silver Blades, and the loop walks it **backwards** from index 4, so the
running totals are 0, 51, 76, 91 and 100 -- AD&D's 18/01-50, 18/51-75,
18/76-90, 18/91-99 and 18/00.

Reproduced on **84 of 84** records across fourteen Curse and Silver Blades
C64 specimen disks. Read the table forwards instead and 34 of the 84 come out
wrong, which is what makes the agreement a reading rather than a coincidence.

## Two corrections this settles

**`docs/116-second-game.md` section 9.2 and `docs/125-bug-notes.md` say the
racial level-limit routine *subtracts* the prime-requisite bonus rather than
adding it, so that "a strong fighter would be capped lower than a weak one".
That is our misreading, and the game is right.** `$B0` accumulates a
**penalty**, not a bonus: `INC $B0` fires when the score is *below* 18 and
again when it is below 17, so an 18 pays nothing, a 17 pays one and anything
lower pays two. The table at `GEN $15A9` therefore holds the limit **for an 18
prime requisite**, and the subtraction brings a weaker character down to the
Players Handbook's own number.

The fighter column of that table reads 9, 7, 6, 8, 6, 10, 99 for dwarf, elf,
gnome, half-elf, halfling, half-orc and human, which is AD&D 1st edition's
maximum-with-18-strength row exactly -- dwarf 7/8/9, elf 5/6/7, half-elf
6/7/8, halfling 4/5/6, half-orc 8/9/10 by strength. Nothing here is a defect.

**And it reads the prime requisite from `0x065`**, which is the right array
for it: a strength drain must not lower a permanent level limit.

## What it means for a conversion

The C64 pair maps onto the DOS pair, and `goldbox.dos_codec`'s reader already puts
the first DOS byte into the neutral ability and the second into
`abilities_second`, which `goldbox.c64_codec` writes to `0x014` and `0x065`.
What this settles is the **meaning**, so three things follow.

* A source with one copy of each score -- Pool of Radiance, or any character
  with nothing altering an ability -- goes into both halves, and that is
  right rather than a guess. The engine's own import does the same thing
  (`SPELLE20 $0D64`).
* A character carrying a drain or a strength-raising item has two genuinely
  different numbers, and **the base is the one to preserve**: `0x014` is
  rebuilt from `0x065` at the next recompute, so a conversion that got the
  base wrong would silently move the character's real score, while one that
  got the current wrong would be corrected by the game itself.
* `0x0FF` is a strength-drain counter in these two titles and a portrait id in
  Pool of Radiance. A conversion that treats it as a portrait for Curse or
  Silver Blades is writing a drain.

## What is not established

* **Silver Blades has not been driven with the arrays crossed.** Its code is
  the same routine at a different address and its `LIBRARY $30F8` even marks
  the difference on the sheet with a `+`, which nobody has yet seen drawn.
  The experiment is `tools/abilitypair.py stage` against a Silver Blades save
  disk and one boot.
* **`0x0EC`, the dexterity index, was never seen written.** `COM.PREP $1740`
  is the only writer reached in play and it runs at the start of a fight; the
  staged party never fought, and the byte read 0 throughout. Crossing a
  character's dexterity and starting a fight would add a third ability to the
  running-game half.
* **What the marker `$2B` looks like on a Silver Blades sheet**, and whether
  it is drawn for a lowered score as well as a raised one. The branch is
  `BNE`, so it should be both.
* **`0x0FE`.** `ECL65 $8562` increments it beside code that compares `0x076`
  against `0x119`, so it is a second per-character counter of some kind and
  not a portrait, but nothing here names it.
