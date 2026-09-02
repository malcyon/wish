# What Fast Travel skips on the way out

`FastTravel` enters `NEWECL` at its tail, `$2034`, which is past everything the
departing area's script would have run first ([`118`](118-debug-mode.md)). This
page is the list of what that is, for all thirty scripts, and which entries of
it cost anything.

It was written for `#159 (Nobody has read what Fast Travel skips in the other
twenty-nine scripts)`, after `#156 (Warping from the Slums to New Phlan draws
New Phlan with the Slums' walls)` was found by a player hitting it and its
mechanism turned out not to be specific to that pair.

**Regenerate it with `tools/eclwalk.py exits`.** Nothing here is transcribed by
hand.

## What a departing prologue is

The statements from the start of the `NEWECL`'s basic block up to and including
the `NEWECL`. A block starts after anything that does not fall through -- `EXIT`,
`GOTO`, `RETURN`, another `NEWECL` -- and at anything something jumps to or
enters at.

Conditions do not end a block. A false `IF` skips the one statement after it,
and a fast travel skips the condition as well as what it guards, so the honest
answer to "what did not happen" keeps the guards in it.

**A `NEWECL` that something jumps to has more than one prologue**, because
which statements ran depends on the route in. `ECL06 $9B95` is the example that
matters: two blocks reach it, and only one of them clears the wall-slot pins.
`tools/eclwalk.py` prints one level of those inbound blocks under
`-- and, arriving from $xxxx:`.

## The corpus

| | |
|---|---|
| area scripts | 30 -- `ECL00`-`ECL1E`, no `ECL0C`, and `ECL1E` is the attract-mode demo |
| bytes | 178035 |
| statements the walk reaches | 98.0% of those bytes; the rest is the data tables opcode `$2A` indexes |
| `NEWECL` statements | **79** |
| exits with at least one statement before them | **78** |

A raw scan for the bytes `20 00 nn` finds 77, of which three are inside another
statement and one is inside a data table, and it misses the two `NEWECL`s whose
operand is a variable rather than an immediate. Read the scripts; do not grep
them.

## What the prologues write, and what it costs

**236 statements run before those seventy-nine `NEWECL`s, and 154 of them are
`SAVE`** -- so the useful question is which addresses they write and whether a
fast travel puts them right some other way. `newecl_writes` in
`automap/actions.py` is the list of what a fast travel does write. The rest of
the 236 is 18 `GOSUB`, 15 `CALL`, 10 printed messages, 8 `LOADFILES`, 8 table
reads and a handful of tests.

| written in the block that runs into the `NEWECL` | exits | reproduced? | grade |
|---|---|---|---|
| `$6E12`, the `POOL` side the target lives on | 32 | yes -- `FASTTRAVEL_DISK`, from the area table | harmless |
| `$C04B`-`$C04D`, the live square and facing | 19 | yes when the area has a known arrival square -- but the *area's* square, not this exit's | harmless: a different legal square, not a wrong one |
| `$49C3`/`$49C4`, the overland square | 10 | **no** | **visible** -- see below |
| `$4A20`+, a persistent quest flag | 9 | no | **not a defect**: the party did not take that route, so the flag should not move |
| `$49E6`, indoors or on the travel grid | 6 | no | harmless: all six are same-area restarts `FastTravel.legality` refuses, and `ECL19`, `ECL1A` and `ECL1B` set it themselves in entry 4 |
| `$6DC9`, cancel the move in flight | 5 | no | harmless -- settled below |
| `$49FD`/`$49FE`, the wall colours | 3 | no | harmless: the arriving area writes its own. 23 of the thirty scripts write `$49FD` and 27 write `$49FE` -- `goldbox/memory.py` says every script writes both, which is close and is not what the bytecode says |
| `$6E22`-`$6E27`, the `WALLSET` and `WALLDEF` cache slots | 3 | no | harmless **for us**: all three sites are the same same-area restarts |
| `$49E7`/`$49E8`, wall slot pinned | 2, and `ECL06`'s one jump further back | **no** | **visible** -- see below |
| `$49FB` | 2 | no, but 22 of the thirty scripts write it on the straight path out of entry 4 | harmless |
| `$4A00`-`$4A1F`, per-script scratch | 1 | yes -- `NEWECL` wipes all 32 bytes and so does a fast travel | harmless |
| `$6DE1` | 1 | no | latent: `DUNGEON` never writes it and four places read it, but 22 of the thirty scripts do. Whether a stale value survives the arriving area's first step is unmeasured |
| `$6B00`/`$6C00` and a `LOADCHAR`, the party's own membership | 1 | no | **latent, and not understood** -- see below |
| `$6E79`-`$6E7E`, `$49EB`, `$6DC6`, `$6DCB` | — | no | the VM's own working registers and per-fight values; nothing carries them across an area change |

**The framing that decides most of the rows.** A prologue is what the game
would have done had the party *walked out that way*. A fast travel is not that
journey, so a skipped quest flag is the right answer rather than a fault: the
party did not open that door, so the door is not open. What matters is the
narrower set of statements that are about **the machine** rather than about the
story -- the loader's cache, the wall tables, the party's position -- because
the arriving area assumes those and nobody has told it otherwise. `#156
(Warping from the Slums to New Phlan draws New Phlan with the Slums' walls)`
was one of those, and there are two more.

## Visible: the overland square is whatever the party last stood on

**What the player sees.** You are in Sokol Keep and you use Fast Travel to go
to the wilderness. You arrive on the travel grid standing on whatever overland
square the party was last on -- which may be days of play ago, in a different
window, or the square the save was made on. Walking out of Sokol Keep instead
puts you on the square its exit names.

**Why.** Indoors the party's position is `$C04B`-`$C04D` and `newecl_writes`
writes it. On the travel grid it is `$49C3`/`$49C4`, which ten exits across six
scripts write on the way out. A fast travel writes neither, **and no arriving
script repairs them**: the straight path out of entry 4 was walked for all
thirty scripts and not one of them writes `$49C3` or `$49C4`. [`140`](140-loaded-files-cache.md) already
records the same thing from the other side -- a fasttravel carrying `(0,0)`
came up at `(0,0)` and one carrying `(5,2)` came up at `(5,2)`.

`FastTravel.warnings` says an arrival square is pointless outdoors, which is
true and is not the same as saying the party lands somewhere arbitrary.

Filed as `#178 (Fast Travel to the wilderness leaves the party on whatever
overland square it last stood on)`.

## Visible: three areas leave two wall slots pinned

**What the player sees.** You are in Valhingen Graveyard, Valjevo Castle's
south-west quarter, or the castle's Inner Tower. You use Fast Travel to go
anywhere else. The area you arrive in draws its walls from the wrong screen
codes -- the same class of damage as `#156 (Warping from the Slums to New
Phlan draws New Phlan with the Slums' walls)`, from a different byte.

**Why.** `$49E7`, `$49E8` and `$49E9` are one flag per wall piece, and
`DUNGEON $14CB` reads `$49E7,X` before unpacking piece `X`: non-zero means "the
screen codes in this piece are already right, do not relocate them". Exactly
three scripts touch them at all, and each clears them on the way out:

| script | area | sets them to 1 | clears them on the way out |
|---|---|---|---|
| `ECL06` | 6, Valjevo Castle south-west | `$9C5A`, `$9C60`, in entry 4 | `$9B7F`, `$9B85`, leaving to area 9 |
| `ECL07` | 7, the Inner Tower | never -- it inherits them from area 6 | `$A8DA`, `$A8E0`, leaving to New Phlan |
| `ECL0A` | 10, Valhingen Graveyard | `$9A72`, `$9A78`, which *is* entry 4 | `$9932`, `$9938`, leaving to the travel grid |

Nothing else in the thirty scripts writes them, no `DUNGEON` code writes them,
and they are saved in `SAVEDGAME0`, so a value left at 1 persists -- across the
rest of the session and into a save.

**The game's own handling is deliberate and not a bug.** `ECL06` has two exits
and clears the pins on only one of them: leaving south goes to area 9 with the
pins cleared, and leaving any other way goes to area 3, which is another
quarter of the same castle and wants the same wall art. It is an optimisation
between areas that share a wall set, and a fast travel takes neither branch.

**Grade: CONFIRMED**, in the emulator on 2026-09-02 by `tools/wallpins.py`.
This said PROBABLE until then, on the grounds that nobody had warped out of one
of the three and looked. Three arrivals at Podol Plaza's own arrival square,
one party, one session, `$ED50`-`$FF97` read through the monitor's `ram` bank:

| how the party reached Podol Plaza | `$49E7`-`$49E9` there | against the control |
|---|---|---|
| warped from the Slums -- the control | `0 0 0` | — |
| warped out of the graveyard, the `$49E7` write dropped | `1 1 0` | **545 of 4680 bytes differ** |
| warped out of the graveyard, the whole of `newecl_writes` | `0 0 0` | 0 of 4680 |

The wall pieces at `$6500`, the cache at `$6E13` and the resident `GEO` are
byte-identical across all three, so the loader wanted and got the right files.

**Unrelocated, not inherited.** All 545 differing bytes differ by the same
constant: the pinned piece holds Podol Plaza's own wall data with every screen
code 50 (`$32`) below where it belongs. The arriving area's `LOADPIECES` does
load and unpack its own file; it is the relocation `$49E7,X` turns off.

**Only one of the two pinned pieces came out wrong, and that is not
explained.** Both `$49E7` and `$49E8` read 1, and the whole difference is in
`$F05C`-`$F367`; `$ED50`-`$F05B` matches the control byte for byte. A piece
whose relocation delta is zero could not show the fault, but the deltas have
not been measured.

**A warp *into* the graveyard sets the pins too**, so the route in does not
matter: `ECL0A` entry 4 opens with its two `SAVE 1` unconditionally, before
its own `LOADFILES`. Watched -- the fast travel writes `$49E7`-`$49E9` as zero
immediately before jumping to `$2034`, and the capture taken once the game is
idle reads `1 1 0`.

**Do not compare the two routes at the travel grid**, which is what this
section used to propose. `ECL1A` entry 4 issues no `LOADPIECES` at all, so the
wilderness never unpacks a wall piece and neither arrival touches `$ED50`:
measured, the graveyard capture and the capture after one step west on to the
travel grid differ in 0 of 4680 bytes. The damage appears at the next area that
does unpack pieces.

**The game's own clearing was watched as well.** One step west off the
graveyard's west edge runs `ECL0A $9932`/`$9938` and `NEWECL 26`, and
`$49E7`-`$49E9` go from `1 1 0` to `0 0 0` across it -- twice, in two sessions.
That is the statement a fast travel enters past.

Filed as `#179 (Warping out of Valhingen Graveyard or Valjevo Castle leaves
two wall pieces unrelocated)`, and fixed there: `newecl_writes` writes
`$49E7`-`$49E9` as zero on every fast travel.

## Latent, and not understood: the Kobold Caves and the party's own membership

`ECL0D $9A9D`, the exit from the Kobold Caves (area 13) to the wilderness east
window, ends:

```
$9A84  SAVE 0, [$6B00]
$9A8A  SAVE 0, [$6C00]
$9A90  ADD 128, [$6E7A], [$6E7A]
$9A99  LOADCHAR [$6E7A]
$9A9D  NEWECL 27
```

It is reached from a loop over the party's slots that stops on a record whose
`$6BB8` is `>= 128` and whose roster byte `$6C00` is `> 127` -- an NPC -- and it
prints seventy-two bytes of text first. `$6B00` is the resident character
record and `$6C00` the resident roster block ([`41`](41-memory-regions.md)), and
the DOS guide's note on `LOADCHAR` is that an index of 128 or more puts a
monster on the party's side and that zeroing those two afterwards takes it away
again ([`128`](128-guide-and-scripting.md)).

So this exit does something to who is in the party, and a fast travel out of
the Kobold Caves does not do it. **What exactly, nobody here knows**, and the
order -- zero, then load -- is not the order the guide describes.

Filed as `#180 (What the Kobold Caves exit does to an NPC in the party is not
understood, and Fast Travel skips it)`.

## Settled: `SAVE 255, [$6DC9]` costs nothing

`#159 (Nobody has read what Fast Travel skips in the other twenty-nine
scripts)` listed this as the one known-skipped statement whose cost was
unmeasured. It is settled by reading, with no emulator.

`$6DC9` is a per-step flag: non-zero means "cancel the move the party was
making", and `255` additionally means "and do not ask about it" -- `DUNGEON
$0E67` returns at once on `BMI`. `DUNGEON` touches it in eight places -- five
writes and three reads -- and **every read is downstream of a zeroing write in
the same step**:

| | |
|---|---|
| `$0AFA` | writes 0 at the top of the move routine |
| `$19CC` | writes 0 immediately before running the script from `$9900` |
| `$0EF5` | writes 0 |
| `$0E6E`, `$0E7C` | write 1 and 0, inside `$0E64` and after its own read |
| `$09A1` reads it | reached only through `$0993 JSR $19CA` |
| `$0B0B` reads it | reached only through `$0B08 JSR $19CA`, after `$0AFA` |
| `$0E68` reads it | inside `$0E64`, called only from `$099E`, which is after that same `$19CA` |

And **no script ever reads it**: 52 writes across the thirty scripts, all
`SAVE 255, [$6DC9]` or `SAVE 0, [$6DC9]`, and not one operand naming `$6DC9` in
a read position.

`NEWECL`'s tail reloads the stack pointer from `$03BF` and jumps to `$0809`, so
the move the flag would have cancelled is abandoned anyway. The scripts write
it as belt-and-braces for a path that returns; on the path that reaches
`NEWECL` it is dead.

## What this does not cover

* **`ECL1E`, the attract-mode demo, has no `NEWECL` at all** and nothing
  fasttravels to it. It decodes at 89%; the remainder is data.
* **The two `NEWECL`s whose target is computed** -- `ECL03 $9AA2` and
  `ECL1D $9947` -- read the target out of a table with opcode `$2A` and the
  walk cannot say which areas they reach without running them.
* **Only one level of inbound blocks is reported** for a `NEWECL` something
  jumps to. A route two jumps back may run statements this page does not list.
* **Nothing here has been watched in the running game.** Every claim is read
  off the bytecode and off `DUNGEON`; the two graded visible carry the
  experiment that would confirm them.
