# The C64 rebuilds a character's THAC0 when a fight starts

**Status: settled, in the code and in the running game.** `thac0_current` at
record offset `0x10E` -- the roster block's `+0x0E` -- is an **output** of the
engine's arithmetic and never an input to it. The fight rebuilds it from
`thac0_base` at `0x071` plus the AD&D strength tables before any command bar
is drawn, so whatever the byte held beforehand makes no difference to a single
attack roll.

This is `#368 (Does the C64 Curse engine read thac0_current in a fight, since
the training hall overwrites it with the base and loses the strength bonus?)`.
The answer is that it does not. The hall's own overwrite turns out not to be
a loss either: it writes `thac0_base` **plus** the strength bonus, gated on
`0x0E3`, and the specimens that opened the ticket had lost the bonus to
`#277 (A DOS character converted to the C64 loses the strength bonus to hit
and damage, because 0x0E3 is written zero)` before they ever reached a
trainer.

## The routine, in Curse and in Pool of Radiance

`LIBRARY` is resident at `$2DC8` in Curse and Silver Blades and at `$2C48` in
Pool of Radiance, and the character being worked on is staged at `$7C00` in
the later titles and `$6B00` in Pool of Radiance, with its roster block on the
page above.

| | Curse | Pool of Radiance |
|---|---|---|
| the rebuild's entry | `$3918` | `$3729` |
| `thac0_base` over `thac0_current` | `$393C` | `$374D` |
| the strength gate | `$394B` | `$375C` |
| to-hit table | `$3840` | `$3651` |
| damage table | `$385F` | `$3670` |
| the same numbers again for a readied weapon | `$387E` | `$368F` |
| the sheet's own read | `$3758` | -- |

The rebuild copies `attack_forms` (`0x0DB`-`0x0E0`) into the roster's
`+0x13`-`+0x18`, `armour_class_base` (`0x0E1`) into `+0x0F`, `movement`
(`0x09F`) into `+0x1B`, and then

```
$393C  LDA $7C71      ; thac0_base, record 0x071
$393F  STA $7D0E      ; thac0_current, record 0x10E
...
$394B  LDX $7CE3      ; strength_bonus_flag, record 0x0E3
$394E  BEQ $3953      ; clear: the index stays 0, and row 0 is no bonus
$3950  LDX $7CE2      ; else strength_index, record 0x0E2
$3953  LDA $3840,X    ; the to-hit row
```

so the strength bonus reaches the roster only through the gate at `0x0E3`.
That is the whole of `#277 (A DOS character converted to the C64 loses the
strength bonus to hit and damage, because 0x0E3 is written zero)`, and the
tables at `$3840`/`$385F` are byte for byte Pool of Radiance's over all
thirty-one rows.

**Nothing in a fight names `$7D0E`.** `COMBAT`, `COMBAT2` and `COM.PREP` hold
no absolute-mode instruction whose operand is that address, over Curse's 412
files; `LIBRARY` holds fourteen, seven of them stores, and `DUNGEON` one. The
one read outside the rebuild is the character sheet.

**`JSR $3918` is called 51 times across the title** -- `POST.COM` x10, `GEN`
x6, `CAMP` x5, `SPELLE20` x5, `DUNGEON` x4, `ECL64` x4, `COMBAT` x3, `ECL65`
x3. Pool of Radiance's `$3729` has 44 callers in the same shape.

## What the running game did

`tools/cursethac0.py`, pool slot 2, `work/issue368/run5`, `run6` and `run7`
-- three boots, three tavern brawls, the same numbers each time. Two of six
characters had their stored roster THAC0 replaced with `0x0A` -- THAC0 50,
which nothing the engine computes can reach, since the worst row of the
game's own THAC0 table is 39, a level-1 magic-user or thief, and the largest
strength penalty is 3 -- and one of the two had
`strength_bonus_flag` forced to 1.

Two execution checkpoints counted `LIBRARY $3918` and `$394B` without
stopping the machine.

| stage | MARK, gate 1 | MATHEW, gate 0 | `$3918` | `$394B` |
|---|---|---|---|---|
| after `LOAD SAVED GAME` | 10 | 10 | 0 | 0 |
| after two `VIEW` sheets | 10 | 10 | 0 | 0 |
| in the world | 10 | 10 | 0 | 0 |
| after twelve steps through Tilverton | 10 | 10 | 0 | 0 |
| on the combat floor | **46** | **45** | **16** | **16** |
| after two quickfight turns | 46 | 45 | 29 | 29 |

46 is MARK's `thac0_base` of 44 plus `$3840[20]` = 2, his 18(51-75); 45 is
MATHEW's own base plus `$3840[0]` = 0, because his gate is shut. The other
four characters, untouched, held their own base plus nothing throughout: 18
roster blocks over the three runs, all 18 agreeing with what the two tables
give for that character's own `thac0_base` and gate.

**Two things a run has to say and this one can.** The rebuild had run zero
times before the fight and sixteen times by the first reading on the combat
floor, which puts it inside the fight's own setup rather than anywhere
earlier; and the two spoiled characters landed on *different* numbers, so the
reading is the engine's arithmetic rather than a constant.

**What was not caught.** No combat message naming a landed blow was
photographed: Curse draws `X ATTACKS Y AND HITS` for about a second and the
screen was read between turns rather than during one, so all three runs came
back with the panel's `HIT POINTS` line and no attack text. The party losing
hit points -- MARK 51 to 33 to 16 across two quickfight turns -- says blows
landed, and says nothing about whose. `VIEW` pressed on the combat command
bar drew no sheet either, so the number the fight is using was read off the
roster page and the checkpoints, not off a screen.

## The sheet draws the stored byte and derives nothing

`LIBRARY $3758 LDA $7D0E / JSR $3BF0` prints THACO, between the armour class
it prints from `$7D0F` and the damage dice it prints from `$7D13`. In the
same run the game drew

* `AC 7   THACO  50    ENCUMBRANCE 1800` for MATHEW,
* `HP 51  DAMAGE 1D2+3` for MARK,

with `thac0_base` reading 45 and 44 in the two records. 50 is a THAC0 no
table in the game produces; it is the staged byte, printed.

## The training hall does not lose the strength bonus

`#368 (Does the C64 Curse engine read thac0_current in a fight, since the
training hall overwrites it with the base and loses the strength bonus?)` was
opened on a pair of specimens in which five characters walked out of Curse's
hall holding `thac0_base` exactly, with no strength bonus in it. That is real
and the hall is not the reason.

Watched, `work/issue368/hall1`: MARK's roster THAC0 spoiled to `0x0A`, his
gate at `0x0E3` forced to 1, his experience set to 46,000 so the hall would
take him, and `GEN $12CA`'s hall gate at `$7EA8` opened from the monitor. One
press of `TRAIN CHARACTER` ▸ `MARK`:

| | `thac0_base` | roster `+0x0E` | `$3918` hits |
|---|---|---|---|
| after the load | 44 | 10 | 0 |
| after the training | 45 | **47** | 1 |
| MATHEW, the untrained control in the same boot | 45 | 10 | 1 |

47 is paladin 6's stored 45 plus `$3840[20]` = 2, and MARK's hit points went
51 to 58 in the same press. The rebuild fired once, for the character
trained.

**The five in the specimen lost the bonus because all six of their records
hold `strength_bonus_flag` = 0**, which is `#277 (A DOS character converted to
the C64 loses the strength bonus to hit and damage, because 0x0E3 is written
zero)`: they were converted from DOS before that was fixed, and `$394B` reads
a zero gate as index 0. The hall gave them what their own records entitled
them to.

## What a player sees, and when

So the sequence a player lives through, for a character the game itself made:

1. He trains. `GEN` reaches `LIBRARY $3918`, which recomputes `thac0_base`
   for the new level and writes it into the roster block **with the strength
   bonus added**.
2. His sheet is right, and stays right.

**Nothing he swings at is ever affected either**, because the rebuild also
runs before the first attack roll of every fight.

The staleness this page opens with is reachable only by putting a value in
the byte that the engine did not: a save edited from outside, or a conversion
that copies a stored THAC0 from another port. Then the sheet shows that
number until the character's next fight, and the fight itself is unaffected.
`#405 (A converted character's THAC0 on the C64 sheet is the source save's
stored byte, and the engine only corrects it at his first fight)` is where
that lands.

## What this settles for a conversion

`thac0_current` is derived on both ports: the DOS sheet works THAC0 out from
`thac0_base` and strength and ignores the stored byte, and the C64 rebuilds it
at every fight. So a converter can recompute it on the way out without losing
anything a player has, and copying it across is equally harmless in a fight
and shows a stale number on the destination's sheet until the first fight
there.

The byte that does matter is `0x0E3`. A record whose gate is zero fights at no
strength bonus for ever, and looks right on the sheet until it does.

## Where the numbers came from

* `tools/recordsweep.py --game curse --offset 0x10E` and
  `tools/absrefsweep.py curse-of-the-azure-bonds 7D00 7D1F`, over 412 files;
* `tools/absrefsweep.py curse-of-the-azure-bonds 3918 3918` and its Pool of
  Radiance twin at `$3729`;
* `tools/cursethac0.py stage` and `run`, whose readings are in
  `work/issue368/run5/thac0.jsonl` for the fight and
  `work/issue368/hall1/thac0.jsonl` for the training;
* `tests/test_cursethac0.py` re-derives the three instructions and the five
  table rows off the player's own disks, so the citations above are checked
  rather than remembered.

The specimen staged was `WISH-SPEC-curse-trained-party.D64`, which the engine
itself wrote after five trainings; its bytes are an **input** here and the
measurement is what the engine did with them. **Its own `0x0E3` is zero in
all six records**, which is why the party in it looks as though the hall took
its strength bonus away, and is why the training run above had to force that
byte before it could ask the question.
