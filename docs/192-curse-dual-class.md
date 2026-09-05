# Curse's trainer, the second session: dual-classing, and the divide

`docs/172-curse-trainer.md` is the first driven Curse session, 2026-09-05, and
ends with three things open. This page is the second session the same day, for
`#18 (Measure Curse's trainer so Level Up works there)`, and closes all three.

**In one line: `goldbox/levelup.py` no longer refuses a dual-classed character,
because all four routines that make one different have been watched running;
and `GEN $11AB`'s round-up is not the rule this project has been implementing.**

## What a player gets out of it

A Curse player who used `HUMAN CHANGE CLASS` -- the party menu's tenth item,
which needs no training hall -- could not use Level Up at all, on any title.
Now the rules are known, and what they cost him is worth saying in his own
terms: **he gains no hit points at all for as many levels as his old class
had**, he pays 1000 gp for each of them, and the class he left never trains
again however much experience he piles up. That is the game's design and not a
defect; what was ours was refusing to model it.

## The four dual-class routines, watched

PHILIPPE is the human magic-user 6 who took `HUMAN CHANGE CLASS` to FIGHTER in
the first session -- `dual_class_slot` 0, `dual_class_level` 6,
`level_magic_user` cleared, `class_bits` `$08`. She was trained eight times
from fighter 1 in one VICE session on pool slot 3. The only thing written
between presses was her experience, poked back to 150,000 in the roster slot at
`$4FE8`; everything read back is the engine's.

| press | fighter | experience after | `hp_rolled` | `hp_max` | `level_magic_user` | `class_bits` | platinum |
|---|---|---|---|---|---|---|---|
| start | 1 | 150,000 | 21 | 33 | 0 | `$08` | 1800 |
| 1 | 2 | **4,000** | 21 | 33 | 0 | `$08` | 1600 |
| 2 | 3 | 8,000 | 21 | 33 | 0 | `$08` | 1400 |
| 3 | 4 | 18,000 | 21 | 33 | 0 | `$08` | 1200 |
| 4 | 5 | 35,000 | 21 | 33 | 0 | `$08` | 1000 |
| 5 | 6 | 70,000 | 21 | 33 | 0 | `$08` | 800 |
| 6 | **7** | 125,000 | **25** | **39** | **6** | **`$09`** | 600 |
| 7 | 8 | 150,000 | **33** | **49** | 6 | `$09` | 400 |
| 8 | 8 | 150,000 | 33 | 49 | 6 | `$09` | 400 |

**`GEN $15E7` -- no hit die until the new class passes the old level.
CONFIRMED, five levels of it.** `hp_rolled` is flat at 21 across fighter 2, 3,
4, 5 and 6, moves by 4 at fighter 7 and by 8 at fighter 8, both inside a d10.

**`GEN $20A3` -- the old class comes back at the same press. CONFIRMED.** The
test is `dual_class_level < level`, so a level of 6 against an old level of 6
is not enough and 7 is.

**`GEN $124F` -- the old class keeps its own hit-point term, once. CONFIRMED,
7 of 7.** The rule is `min(dual_class_level, roll_to[old slot]) * bonus` added
outside the per-slot loop, and each slot in the loop then contributes
`max(0, min(level, roll_to) - dual_class_level)`; `$18E4` leaves the old slot
out of the class count. Constitution 16 reads `02` at `GEN $11D7`, and
`roll_to` at `$1282` is `0B 09 0A 09 00 00 09 0A`.

| state | old-class term | new-class term | total | `hp_rolled` | `hp_max` |
|---|---|---|---|---|---|
| fighter 2-6, magic-user 0 | `6 x 2 = 12` | 0 | 12 | 21 | 33 |
| fighter 7, magic-user 6 | 12 | `(7-6) x 2 = 2` | 14 | 25 | 39 |
| fighter 8, magic-user 6 | 12 | `(8-6) x 2 = 4` | 16 | 33 | 49 |

**`GEN $1321` -- the old class is never eligible. CONFIRMED.** Press 8 was
refused with `UNABLE TO ADVANCE` while she held 150,000 experience and a
restored magic-user 6, which is 15,000 more than the magic-user's ninth level
asks for. The refusal cost nothing: platinum read 400 before and after.

**`GEN $1470` -- and it is out of the experience clamp. CONFIRMED, from a
staged input.** With the levels poked to magic-user 10 / fighter 1,
`dual_class_level` 10 and 400,000 experience, one press wrote **4,000**, the
fighter's `clamp_threshold(2) - 1`. Had the old class been in the maximum it
would have written the magic-user's 375,000. That character could not exist in
play; it exists to make the branch discriminate.

## The experience clamp, lowering a number at last

`docs/172-curse-trainer.md` lists this as open -- *"All five kept their
experience, because each one's next-but-one threshold was above what it
held."* **CONFIRMED, 6 of 6**, and every value is
`levels.clamp_threshold("fighter", n) - 1` exactly: 4,000, 8,000, 18,000,
35,000, 70,000, 125,000. Press 7 left 150,000 alone, because the clamp only
writes when it lowers.

## The money, from the other end

A second, independent reading of the 1000 gp per class and of `GEN $2160`'s
`1 pp = 5 gp`: TRAVIS, thief and fighter, was trained four times from 1600
platinum and the fifth press said **`NEED 1000 GP TO TRAIN`**. 1600 pp is 8000
gp; four presses at two classes and 1000 gp a class is 8000 gp.

## `GEN $11AB`: the round-up is not what we implement

This is the PROBABLE `#18 (Measure Curse's trainer so Level Up works there)`
carried for two days, and it turned out to be settleable by reading rather than
by counting.

### The random routine is in `LIBRARY`, and both bases are now fixed

`goldbox/levelup.py` said the roll's range was unreadable because "both random
routines are resident and outside `GEN`". They are in `LIBRARY`. Reading 96
bytes at `$2F20` out of a live Curse session and searching for them in
`LIBRARY`'s payload puts them at offset `0x158`, so **Curse's `LIBRARY` runs at
`$2DC8`** -- and `$2DC8 + 7480 = $4B00`, exactly where `SAVEAZURE` loads.
Aligning Pool of Radiance's copy of the same routine puts **its `LIBRARY` at
`$2C48`**, and `$2C48 + 7348 = $48FC`, four bytes below the `$4900` that title's
saved-game header sits at. Two arithmetic checks, and the second needed no
emulator.

`LIBRARY $2F46` (Curse) and `$2DBC` (Pool of Radiance) find the highest set bit
of `Y`, mask a random byte with `01 03 07 0F 1F 3F 7F FF` indexed by it, and
**retry while the result exceeds `Y`**, so they return a uniform `0..Y`. Two
entry points sit above, one byte apart:

```
$2F6A  88         DEY            <- 1..Y
$2F6B  20 46 2F   JSR $2F46      <- 1..Y+1
       E8 / EE C8 03 / AD C8 03 / 60
```

**Both titles' divides reach `1..class_count`.** Curse's
`$11BE LDY $2C9C / DEY / JSR $2F6B` is Pool of Radiance's
`$2090 LDY $AB / JSR $2DE0` written the long way round, so the earlier guess
that Curse rolls `0..class_count-1` is **refuted**.

### So the difference is one branch

| | Pool of Radiance `$2095` | Curse `$11C5` |
|---|---|---|
| | `CMP $6E3F / BEQ inc / BCS out / INC` | `CMP $7F3F / BCS out / INC` |
| rounds up when | roll **<=** remainder | roll **<** remainder |
| chance | `r / n` | `max(0, r - 1) / n` |
| two classes, remainder 1 | 1 in 2 | **never** |

A two-class character's remainder is only ever 0 or 1, so **Curse's divide is
not probabilistic at all in the commonest case**.

### And it was measured as well

`GEN $1235` puts the **constitution total** through the same `$11AB` as the hit
die, and unlike the die that total is fixed by the record -- so
`hp_max - hp_rolled` after a training is one clean sample. Constitution was set
to 15, whose row entry at `GEN $11D7` is `01`, making the total the plain sum of
the class levels so its remainder could be chosen.

| classes | total | remainder | Curse's rule | our `divide_between_classes` | observed |
|---|---|---|---|---|---|
| 2 (thief/fighter) | 13, 15, 17, 19 | 1 | never | 1 in 2 | **0 up in 14** |
| 3 (cleric/thief/fighter) | 16 | 1 | never | 1 in 3 | **0 up in 12** |
| 3 (cleric/thief/fighter) | 17 | 2 | **1 in 3** | 2 in 3 | **5 up in 14** |

Against our rule: `p = 6.1e-05`, `p = 0.0077`, `p = 0.017`. Against Curse's, the
third row predicts a mean of 4.67 and got 5 -- and it is the one that matters,
because it is a *positive* prediction rather than another run of zeroes. 40
valid samples; two more were discarded because the press landed on the wrong
character, which `$7C00`'s name bytes caught.

The three-class characters are not legal parties: LEDERA was given cleric,
thief and fighter bits, and `GEN $1553` then refused to raise her cleric
because an elf cannot be one -- which is why her cleric level is constant in
every row, and does not affect `$18E4`'s count of non-zero levels.

## What is in the tree

| file | what |
|---|---|
| `goldbox/levelup.py` | `dual_class_old`; the four rules; the refusal gone; `divide_between_classes`' docstring corrected with what it still needs |
| `tests/test_cursedualtrain.py` | 8 tests replaying the eight presses against the specimen pair |
| `tools/cursetrain.py` | `stage --repair` and eight more `--give` fields; the driven recipe, including the roster address |
| `docs/192-curse-dual-class.md` | this page |

**Each of the four rules was mutated on its own and the matching test went
red**: dropping the `$15E7` suppression, restoring on `<=` instead of `<`,
dropping the eligibility skip, dropping the clamp skip. Reverting the whole
file turns five of the eight red on the refusal alone.

## The specimens

| specimen | what |
|---|---|
| `curse-dual-classed` | PHILIPPE one `HUMAN CHANGE CLASS` after magic-user 6: fighter 1, no experience |
| `curse-dualclass-trained` | the engine's own `SAVE CURRENT GAME` after the seven trainings; the other five slots byte for byte unchanged |

Both came off the pool slot with `SAVEAZURE` unclosed --
`#298 (A save disk copied out of an emulator slot before the drive closes the
file cannot be loaded by the game)` reproduces every time -- so the second was
repaired before anything read it, which `tools/cursetrain.py stage --repair`
now does in one flag.

## What still stands between this and Level Up for Curse

Three changes, in two files this session did not own.

1. **`goldbox/levels.py` gains a field for the divide's comparison**, beside
   `hit_die_divide_floor`: Pool of Radiance rounds up when the roll is at or
   below the remainder, Curse only when it is below. Without it
   `divide_between_classes` gives a Curse two-class character an extra hit
   point half the time it should give none.
2. **`goldbox/levels.py` gains a field for "one press raises every ready
   class"**, and `goldbox/levelup.py` a loop over `ready_classes` in slot order
   -- `docs/172-curse-trainer.md` §1. The arithmetic underneath needs no
   change; 75 of 75 fields and 5 of 5 spellbooks already reproduce when the
   classes are chained by hand.
3. **`goldbox/spells.py`'s `not_granted` for Curse gains id 90**, the
   magic-user ANIMATE DEAD, which `GEN $273F` marks 9.

Then `TRAINER_MEASURED` gains Curse. And two lines in `goldbox/levels.py` are
already out of date and should go with it: its module docstring still grades
the racial saving-throw bonus at `$0F19` PROBABLE with *"no dwarf, gnome or
halfling Curse character exists to check it against"*, and TRAVIS is one.

## Silver Blades shares nearly all of it

Read off `SILVER*.D64`'s `GEN` with no emulator, and recorded in full on
`#89 (Silver Blades' trainer grants spells from a table, and goldbox/levelup.py
offers them from a menu)`: the one-press-raises-every-class loop (`$156F`), the
hall gate `$7EA8` with the same `AND #$F7` and the same `$7F`/`$A1` menu masks
(`$0991`), refusal message 27, the two-dice hit die (`$1808`) and the divide
(`$0D96`) -- the last two instruction for instruction with Curse's, so Silver
Blades has the same `<` and, like Curse, guarantees no minimum result. It never stores
spell capacity either: 0 code references to `$7CEE`-`$7CF3` across 347 files.

**The one thing that is Silver Blades' alone: its `GEN` trainer takes no
money.** Curse charges 1000 gp a class inside the loop; Silver Blades' loop has
no such call, and the whole of its `GEN` names the ten money bytes once, in
what looks like character creation. Whether an area script charges before
opening the menu is UNKNOWN.

**So the lever that made this session cheap is already paid for in Silver
Blades**: poke `$7EA8` and the hall opens wherever the party stands.
