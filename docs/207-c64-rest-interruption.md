# What interrupts a C64 rest, and where it never can

The Commodore 64 rest loop lives in the `CAMP` overlay and checks for an
interruption exactly the way the DOS one does — `docs/163-dos-vm-address-map.md`
read the DOS routine at `GAME.OVR:0x24A66` for
`#218 (Three live regions of the DOS saved game are named but not understood)`,
and this is its C64 twin, plus the census of which areas can interrupt a rest
at all, plus the measurement in the running game that settles
`#250 (Does a C64 party resting in the Slums ever get interrupted without the
murder flag?)`.

**The short answer.** A C64 rest is checked for interruption only where the
area script leaves a non-zero value in `$6DD2`, and the engine zeroes that byte
on the way into camp, so the script is the only thing that can open the gate.
In the Slums the script opens it only when `$4A0B`, the fortune teller's murder
penalty, is 255. Thirty-seven two-hour rests in the Slums with the flag clear
— 74 game-hours — made **no check at all**; the same party with the flag at
255 was checked on every rest, 13 of 13 in the run with the tightest
instrument, and interrupted in both runs.

`tools/c64restinterrupt.py` regenerates everything here: `code all` for the
tables, `drive` for the measurement.

## The gate

`CAMP` runs at `$0800` like every overlay `LINKER` dispatches to
(`docs/118-debug-mode.md`), and it is `LINKER` id 9. One pass of the rest loop
is five minutes of game time: `$1CC9` takes five off the rest-time field
`$2898`/`$2899`/`$289A` — minutes in steps of five, hours, days — at the top of
every pass, and the loop ends when all three read zero.

```
$1E0F  AD D2 6D   LDA $6DD2      ; passes between checks
$1E12  F0 20      BEQ $1E34      ; zero: no check is made, ever
$1E14  CE DC 28   DEC $28DC      ; passes since the last one
$1E17  D0 1B      BNE $1E34
$1E19  8D DC 28   STA $28DC      ; reload the counter from $6DD2
$1E1C  A0 64      LDY #$64
$1E1E  20 E0 2D   JSR $2DE0      ; d100 into X
$1E21  CA         DEX
$1E22  EC D3 6D   CPX $6DD3      ; roll-1 >= the chance: nothing happens
$1E25  B0 0D      BCS $1E34
$1E27  A9 FF      LDA #$FF
$1E29  8D D3 6D   STA $6DD3      ; the "interrupted" marker
```

`$28DC` is seeded from `$6DD2` at `CAMP $081E`, on entry to camp. The `$FF` is
read in three places: `CAMP $0886` and `CAMP $151C`, which break out of the
camp menu and its sub-menus, and `DUNGEON $19D9`, which runs the area script's
**entry 3, "camp interrupted"**. The message is `CAMP`'s number `$1C`, `YOUR
REST IS RUDELY INTERRUPTED!`.

The DOS routine increments a counter and compares it; the C64 one decrements to
zero. Same arithmetic, and the same two bytes decide it. CONFIRMED — the bytes
are on the player's own disks and `tools/c64restinterrupt.py code` checks them
there on every run.

## `$6DD2` has one non-zero source, and it is the area script

A sweep of `$6DD2`-`$6DD3` over all 564 distinct files of the eight sides
(`tools/absrefsweep.py pool-of-radiance 0x6DD2 0x6DD3 --sites 0x6DD2 0x6DD3`)
finds 13 absolute references in code files and none in art or in script
bytecode. Every engine-side **write** stores zero:

| file | at | what it does |
|---|---|---|
| `DUNGEON` | `$10A6` | `LDA #$00 / STA $6DD2 / STA $6DD3`, on ENCAMP |
| `INIT` | `$094B` | zeroes both beside `$49F2`, at start-up |
| `POST.COM` | `$14C6` | zeroes both with `$6E70`-`$6E72`, `$6DE2`/`$6DE3`, `$6DE6` |

The two reads are `CAMP $081E` and `CAMP $1E0F`. So no 6502 instruction
anywhere in the game stores a non-zero value into `$6DD2`, and the only writer
that can is the ECL VM's own indirect store, driven by a script's `SAVE`.

## The ENCAMP handler zeroes the pair and then runs entry 2

`DUNGEON $10A1` is the only place in any of the 564 files that stores `9` into
the overlay selector `$6E11`, so it is the only way into `CAMP`:

```
$10A1  LDA #$01 / STA $6DAB
$10A6  LDA #$00 / STA $6DD2 / STA $6DD3
$10AE  JSR $19F5              ; the script's entry 2
$10B1  LDA #$09 / STA $6E11   ; load CAMP
```

`$19F5` is `LDX #$01 / JMP $19FC`, and `$19FC` builds the entry address out of
the tables at `$1A0B` and `$1A0F` — `$9904 $9908 $990C $9910`, the second
through fifth of the five `GOTO`s at the head of every script. X = 1 is
therefore entry 2, "before camping". X = 2, reached from `$19ED` when `$6DD3`
is negative, is entry 3, "camp interrupted"; X = 3 from `$19DF` and X = 0 from
`$19FA`.

That ordering is what makes each area's entry 2 the whole of the answer: the
engine has just zeroed the pair, and nothing else writes it before the rest
loop reads it.

## Which areas can interrupt a rest

`tools/c64restinterrupt.py code all` walks every area script **from entry 2**
rather than sweeping it, so a conditional pair is reported as the values each
arm reaches rather than whichever came first in address order.

| shape | scripts |
|---|---|
| never checked — entry 2 leaves `$6DD2` at 0 on every path | `ECL07`, `ECL0F`, `ECL10`, `ECL13`, `ECL17`, `ECL1E` |
| always checked — no path leaves it at 0 | `ECL0D` (1 or 96), `ECL18` (1 or 4) |
| conditional | the other twenty-two, `ECL14` among them |

The four pairs `docs/163-dos-vm-address-map.md` measured over 21 DOS
containers are all here: New Phlan `ECL00 $9A79` (1, 101), the Slums
`ECL14 $9A3C` (24, 24), Sokol Keep `ECL15 $9A34` (2, 1), the overland
`ECL1A $B0F3` (96, 10).

## The Slums, and the two tests that decide nothing

`ECL14` entry 2, at `$9A0E`, walked from entry 2:

```
$9A0E  COMPARE [$4A0B], 255 / IF= / GOTO [$9A3C]
$9A19  COMPARE [$4ABB], 254 / IF>= / GOTO [$9A2F]
$9A24  COMPARE [$6E82], 0   / IF<> / GOTO [$9A2F]
$9A2F  SAVE 0, [$6DD2] / SAVE 0, [$6DD3] / EXIT
$9A3C  SAVE 24, [$6DD2] / SAVE 24, [$6DD3] / EXIT
```

Only the first test does anything. The second jumps to `$9A2F` and falling
through it reaches `$9A2F` as well; the third jumps to `$9A2F` and falling
through it reaches `$9A2F` too, because `$9A2F` is the next statement. Both are
conditionals whose two arms are the same instruction.

**Two of two, against nought in the other twenty-nine scripts.**
`tools/c64restinterrupt.py code all` walks both arms of every conditional in
every area's entry 2 through the statements that leave no trace — `COMPARE`,
`IF`, `GOTO` — and asks where each arm first does something. Across all thirty
scripts exactly three conditionals have both arms reaching the same set of
statements, and only in `ECL14` is that set a single statement:

| script | at | both arms arrive at | decides nothing |
|---|---|---|---|
| `ECL14` | `$9A1F` | `$9A2F` | yes |
| `ECL14` | `$9A2A` | `$9A2A` → `$9A2F` | yes |
| `ECL1C` | `$B628` | `$B638`, `$B65B`, `$B668` | no — tests further down pick a different one on each arm |

So a camping block with a conditional that cannot matter is not how these
scripts are written; it happens twice, in one script, in the two statements
the DOS build has differently.

**That conclusion does not depend on which way round the `IF` opcodes read.**
`docs/163-dos-vm-address-map.md` settles the polarity from the DOS/C64 diff —
the next statement runs when the comparison holds — but here it does not
matter: swap both arms of both tests and the block still reaches `$9A2F` on
every path below `$9A19`. So the only live route to (24, 24) is `$4A0B` = 255.
CONFIRMED from the bytecode.

**The DOS build's copy of the same script differs in exactly ten bytes, and
two of them are these two tests.** Unpacked from `ECL2.DAX` block 20 with
`tools/daxls.py --dump 20` — the block carries a two-byte length word in front
of the script, after which both are 7677 bytes and line up address for address:

| at | C64 | DOS |
|---|---|---|
| `$9A2A` | `17` (`IF<>`) | `16` (`IF=`) |
| `$9A2D` | `2F` (`GOTO $9A2F`) | `3C` (`GOTO $9A3C`) |
| `$9C41`, `$A39E`, `$A4B8`, `$AB3C`, `$AB3E`, `$AD0F`, `$B274`, `$B6FC` | eight more, elsewhere in the script | |

With those two the DOS Slums gets (24, 24) on an ordinary square and (0, 0) on
a special one, so the third test becomes live and the second becomes an
endgame guard; every DOS Slums specimen holds (24, 24) with `$4A0B` clear,
which is what
`#218 (Three live regions of the DOS saved game are named but not understood)`
measured over 21 containers. The change to the second test is not one of the
ten: it reads the same in both builds and is inert on the C64 only because the
byte at `$9A2D` sends the arm below it to the same place. `goldbox-bugs.md` 13
is the entry for what a player sees.

## Driven

Two pool-slot runs, headless, from `PORSAVE13.D64` — Donald's own save one step
inside the Slums at `(15, 4)`, `$4A0B` = 0, `$4ABB` = 3 — the same disk
`docs/50-experiments.md`'s murder run used. Before anything was counted, the
resident script's entry 2 was compared byte for byte against `ECL14` on the
side: 64 bytes at `$9A0E`, identical, so the area is the Slums rather than
something that looks like it.

Each trial is a whole `ENCAMP > REST` of two hours, which is 24 five-minute
passes and so exactly one check's worth when the pair is (24, 24). The
duration is written into `CAMP`'s own `$2898`-`$289A` and read back rather than
driven with INCREASE, whose step grows while the key is held. Three
non-stopping VICE checkpoints count `$1E0F` (a pass), `$1E1C` (a check about to
roll) and `$1E27` (the roll won), and the game's own clock at `$49C6`-`$49CB`
is read either side of every rest, so the pass count has a witness that is not
the checkpoint.

| run | camp session | `$4A0B` | pair | rests | passes | game time | checks | interruptions |
|---|---|---|---|---|---|---|---|---|
| 1 | flag clear | 0 | (0, 0) | 24 | 575 | 47 h 55 m | **0** | 0 |
| 1 | flag set, chance held at 0 | 255 | (24, 24) | 24 | 575 | 47 h 55 m | 23 | 0 |
| 1 | flag set, chance as written | 255 | (24, 24) | 2 | 48 | 4 h | 2 | **1** |
| 2 | flag clear | 0 | (0, 0) | 13 | 312 | 26 h | **0** | 0 |
| 2 | flag set, chance held at 0 | 255 | (24, 24) | 13 | 312 | 26 h | 13 | 0 |
| 2 | flag set, chance as written | 255 | (24, 24) | 1 | 24 | 2 h | 1 | **1** |

`work/issue250/run1` and `run2`. **With the flag clear the d100 is never
rolled**, so neither run is an unlucky one: `$1E12` takes the branch and skips
the block. Seventy-four game-hours of resting in the Slums over 37 rests, and
not one check. The middle session of each run holds `$6DD3` at 0 after entry 2
has run, so `$1E22`'s compare can never succeed and the checks can be counted
without the first interruption ending the session: **13 of 13 rests made a
check** in run 2. The last session of each leaves the chance as the script
wrote it, and both were interrupted — `$6DD3` went to 255 at `$1E29` and the
screen said `YOUR REST IS RUDELY INTERRUPTED!`, which
`work/issue250/run1/flag-set-interrupted.png` caught. Camp then ended and the
party was back in the dungeon view. Whether the wandering fight `ECL14` entry 3
sets up follows was not established here: run 2's screen ten seconds later was
the dungeon view with no combat on it, and this run does not measure that.

**Run 2 is the one to quote, because run 1 missed a pass in each of its
24-rest sessions and the miss was the instrument.** The same rest in both,
number 12, the one ending 24 game-hours after camp was pitched: on that pass
`$1E09` calls `$1FB6`, whose tail is `$0F96` — `LDA $49FC / JSR $2E1F`, a wait
as long as the game-speed setting — and it runs *before* the pass reaches
`$1E0F`. Run 1 allowed four seconds of stillness before calling a rest
finished, read that pause as the end of one, and took its last reading a pass
early; in the middle session that also swallows the check that pass would have
made, which is why the count is 23 rather than 24. Run 2 waits ten seconds and
reads the game's own clock at `$49C6`-`$49CB` either side of every rest:
**26 of 26 rests moved the clock exactly 120 minutes while the checkpoint
counted exactly 24 passes**, so the pass count has a witness that is not the
checkpoint and nothing is missing from it.

**How the flag was staged.** `$4A0B` was written into live memory before
ENCAMP and read back; the engine's own `ECL14` entry 2 then computed the pair
from it. That is editing an **input** and watching the game compute from it,
which is the experiment `.claude/rules/testing.md` allows. The murder itself
writes the same byte — `docs/50-experiments.md`'s murder run watched
`$4A0B` go 251 → 255 on `ATTACK`.

## What was not established

* **The Amiga.** `ecl.dax` is on side 2 of the Amiga disks and the file name is
  in the directory, but its container index is not the DOS one
  `tools/daxls.py` reads — every block it reports comes out with a nonsense
  offset — and the scripts inside are packed, so a byte search for the Slums
  camping block finds nothing. Reading the Amiga's `ECL14` wants an unpacker
  this project does not have yet. The bugs entry says "very likely" for that
  reason.
* **What follows an interruption.** `ECL14` entry 3 is `SAVE 200, [$4A1F] /
  SAVE 0, [$6DCB] / OP$1D [$9808] / GOTO $9B68`, which looks like the
  wandering-monster setup, but the screen ten seconds after the interruption
  was the dungeon view with no fight on it. Nothing here measures whether a
  fight follows, or how often.
* **Whether any other area's condition is inert the same way.** Twenty-two
  scripts are conditional and only `ECL14`'s condition was read statement by
  statement. `tools/c64restinterrupt.py code all --verbose` prints the rest;
  a second one with identical arms would be a second bug.

## What this does not touch

Nothing in `goldbox/` reads `$6DD2` or `$6DD3`. They appear once each as prose
in the named-word tables — `goldbox/dos_codec.py` at file word `0x4FD2` and
`goldbox/amiga_codec.py` at the same — and no conversion, editor field or automap
reading depends on them. This is a finding about the game and there is nothing
in Wish to change for it.
