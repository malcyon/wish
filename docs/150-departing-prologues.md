# What Fast Travel skips on the way out

`FastTravel` enters `NEWECL` at its tail, `$2034`, which is past everything the
departing area's script would have run first ([`118`](118-debug-mode.md)). This
page is the list of what that is, for all thirty Pool of Radiance scripts, and
which entries of it cost anything; the rule Fast Travel applies in every title,
and the short list of departures it reproduces, are in [How Fast Travel leaves
an area](#how-fast-travel-leaves-an-area).

It was written for `#159 (Nobody has read what Fast Travel skips in the other
twenty-nine scripts)`, after `#156 (Warping from the Slums to New Phlan draws
New Phlan with the Slums' walls)` was found by a player hitting it and its
mechanism turned out not to be specific to that pair.

**Regenerate it with `tools/areas/eclwalk.py exits`.** Nothing here is transcribed by
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
`tools/areas/eclwalk.py` prints one level of those inbound blocks under
`-- and, arriving from $xxxx:`.

## The specimens

| | |
|---|---|
| area scripts | 30 -- `ECL00`-`ECL1E`, no `ECL0C`, and `ECL1E` is the attract-mode demo |
| bytes | 178035 |
| statements the walk reaches | 98.0% of those bytes; the rest is the data tables opcode `$2A` indexes |
| `NEWECL` statements | **79** |
| exits with at least one statement before them | **78** -- counting the inbound block a jump arrives through. 68 have a statement in their own block; the one exit with nothing on either count is `ECL0D $9A20`, the Kobold Caves' ordinary exit |

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
| `$6E12`, the `POOL` side the target lives on | 32 | yes -- the `disk` field of the title's row in `automap/fasttravel.py`, from the area table. `LIBRARY $43A4` reads `$6E12` and prompts if that disk is not in the drive | harmless |
| `$C04B`-`$C04D`, the live square and facing | 19 | yes when the area has a known arrival square -- but the *area's* square, not this exit's | harmless: a different legal square, not a wrong one |
| `$49C3`/`$49C4`, the overland square | 10 | **no** | **visible** -- see below |
| `$4A20`+, a persistent quest flag | 9 | no | **not a defect**: the party did not take that route, so the flag should not move |
| `$49E6`, indoors or on the travel grid | 6 | no | harmless: all six are same-area restarts `FastTravel.legality` blocks, and `ECL19`, `ECL1A` and `ECL1B` set it themselves in entry 4 |
| `$6DC9`, cancel the move in flight | 5 | no | harmless -- settled below |
| `$49FD`/`$49FE`, the wall colours | 3 | no | harmless: the arriving area writes its own. 23 of the thirty scripts write `$49FD` and 27 write `$49FE` -- `goldbox/memory.py` says every script writes both, which is close and is not what the bytecode says |
| `$6E22`-`$6E27`, the `WALLSET` and `WALLDEF` cache slots | 3 | no | harmless **for us**: all three sites are the same same-area restarts |
| `$49E7`/`$49E8`, wall slot pinned | 2, and `ECL06`'s one jump further back | **no** | **visible** -- see below |
| `$49FB` | 2 | no, but 22 of the thirty scripts write it on the straight path out of entry 4 | harmless |
| `$4A00`-`$4A1F`, per-script scratch | 1 | yes -- `NEWECL` wipes all 32 bytes and so does a fast travel | harmless |
| `$6DE1` | 1 | no | latent: `DUNGEON` never writes it and four places read it, but 22 of the thirty scripts do. Whether a stale value survives the arriving area's first step is unmeasured |
| `$6B00`/`$6C00` and a `LOADCHAR`, the party's own membership | 1 | no | **visible** -- see below |
| `$6E79`-`$6E7E`, `$49EB`, `$6DC6`, `$6DCB` | — | no | the VM's own working registers and per-fight values; nothing carries them across an area change |

**The framing that decides most of the rows.** A prologue is what the game
would have done had the party *walked out that way*. A fast travel is not that
journey, so a skipped quest flag is the right answer rather than a fault: the
party did not open that door, so the door is not open. What matters is the
narrower set of statements that are about **the machine** rather than about the
story -- the loader's cache, the wall tables, the party's position -- because
the arriving area assumes those and nobody has told it otherwise. `#156 (Warping
from the Slums to New Phlan draws New Phlan with the Slums' walls)` was one of
those, and there are two more.

**The party's own membership does not fit that split.** Losing an NPC at the
caves' mouth is story, by the framing above, and a fast travel keeping her is
still wrong -- she is on the panel for the rest of the game and in the save,
and no other script can take her off it. This page used to settle that row
"and every future row like it" by running the exit's own handler before every
trip; that rule walked parties through unrelated areas and fight squares, and
it is replaced by the one below, under which this row is one of a few
departures shown to be needed.

## How Fast Travel leaves an area

**Fast Travel goes straight to the destination** in all four titles, on every
port that offers it. The C64 enters `NEWECL` at its tail with
`newecl_writes`; the Amiga writes the trip's own `SAVE` and `NEWECL`
statements past the loaded script ([`96`](96-live-memory-automapper.md), "Fast
Travel and Return without the program counter"). DOS has no Fast Travel.

**A departure runs only where skipping it is shown to break game state** --
party membership, quest state, cleanup the game needs. An area having an exit
script is not evidence, nor is a script lying on some route, nor an ordinary
exit changing some bytes. The test each row passes: every walked, non-fight way
out of the area makes the change, so the state a skipped departure leaves is
one no walking party can reach. An unknown case is research and defaults to
straight.

**`automap/departures.py` is the only list of departures a trip reproduces.**
Its rows are keyed by title and departing area, never by area id alone (area 16
is a Pool of Radiance cave and a Silver Blades town). A row's guards are the
tests the departing script makes; it reproduces the departure either by walking
out through `EXIT_ROUTES[(area, route_to)]`, so the game's own handler runs, or
by writing what the script writes before its `NEWECL`. On the C64 a write is a
memory byte; on the Amiga it is a guarded `SAVE` the trip's prologue puts ahead
of its own statements. A row with `enabled=False` is built and tested and
`find` skips it. A guard byte or party that cannot be read starts no trip and
writes nothing.

**Why this changed.** Under the earlier rule Fast Travel chose a door by
distance through the area graph and walked out of it. A C64 party in New Phlan
going to Podol Plaza went through Phlan City Hall first; other trips crossed
Mendor's Library, Cadorna Textile House, the Temple of Bane, a Pyramid level,
the New Phlan dock and boat (with `EXIT_PRESETS` writing the harbour master's
two scratch bytes first), or the Stojanow Gate guards (raising the castle
alarm), or stood the party on a fight square at the Buccaneer Base, the Zhentil
Keep Outpost or Valjevo's Pool. On the Amiga the same door rule greyed Fast
Travel out of eight Pool areas. Donald set the straight-by-default rule for
`WISH-313 (Fast Travel goes straight to the destination and runs a departure
sequence only where skipping it is shown to break game state)`, comment
b9a92d71. The door chooser, the direct-door-first rule, `EXIT_PRESETS` and
`EVERY_DOOR_FIGHTS` are gone; the dock's `$4AC6` has no reader, so a trip from
New Phlan to a window is an ordinary tail jump. `EXIT_ROUTES` stays as the
generated door list, read only through a `route_to` row. The four surveys
behind the table are WISH-313 comments 2f35d502 (Pool), 60ebad03 (Curse),
68de904c (Silver Blades) and b7604d0f (Pools of Darkness); the exact guards and
the every-exit check are comment 58caa381.

### The departures

"Live" is the check against the running game under the current code; a row's
consequence is what a player meets when the departure is skipped.

| row | leaving | guard, then what the trip does | if skipped | evidence | enabled |
|---|---|---|---|---|---|
| P1 | Pool, Kobold Caves (13) | `PRINCESS FATIMA` in a slot: Fast Travel does not leave area 13; Return walks out through `(13, 27)` | she stays in the party and the save; no other script removes her | CONFIRMED live under the earlier code ([below](#visible-fast-travelling-out-of-the-kobold-caves-keeps-an-npc-the-game-meant-to-take-away)); live check L2 under the current code not run | C64, Amiga |
| P2 | Pool, Lizardman Keep (16) | `$4A5D` >= 40 and `$4AB5` != 255: `$4AB5` = 254 (`ECL10 $9CBD`-`$9CCF`) | the City Hall clerk does not pay the lizardmen commission until the party walks back in and out | CONFIRMED (bytecode); Amiga trip 16 to 0 writes it, 3 of 3 guard cases | C64, Amiga |
| P3 | Pool, Buccaneer Base (1) | `$4AA9` == 1: `$4AA9` = 254 (`ECL01 $9936`-`$993D`) | the Bivant heir reward is not paid until the party walks back in and out by the edge | CONFIRMED (bytecode); Amiga trips 1 to 0 and 1 to 25 write it, a walked control writes the same 0xFE, and a game-written save holds it | C64, Amiga |
| P4 | Pool, Nomad Camp (17) | `$4A7C` & 5 non-zero and `$4AB7` != 255: `$4AB7` = 254 (`ECL11 $A1B9`-`$A1ED`) | the "nomads stopped" commission is not paid until the party walks back in and off an edge | CONFIRMED (bytecode); Amiga trip 17 to 0, 5 of 5 guard cases | C64, Amiga |
| P5 | Pool, Zhentil Keep Outpost (28) | none: `$4AB4` = 253 (`ECL1C $993C`, `$B4F9`-`$B5EE`) | Cadorna's diplomatic mission is not paid until the party walks back out | CONFIRMED (bytecode); Amiga trips 28 to 0 and 28 to 25 write it | C64, Amiga |
| P6 | Pool, a cave in window 25, 26 or 27 | `$4A9E` == 255: `$4A9E` = 0 | the next arrival in any window starts inside a cave, not on the grid | CONFIRMED live on the C64 (`WISH-307 (C64 Fast Travel out of a wilderness cave probably leaves the cave flag set, so the next visit to that window may start in the cave)`); Amiga not run | C64, Amiga |
| D11 | Pools of Darkness, overland 17, 25, 51 or 80, to an area that is not an overland | `SAVE 0,[$24]`, `SAVE 1,[$22]`, `CLEAR BOX`, as all four exit subroutines do | SPECULATIVE: on DOS `LOADFILES` skips the map while `$22` is 0; the Amiga handler is not read | CONFIRMED that every overland-to-3D exit writes both (bytecode), and live: a trip from overland 17 to Zhentil Keep (19) wrote `$22` 0 to 1 and `$24` 1 to 0, landed at (8,15) N with the gate guard's toll question, and a step moved the party to (8,14) (`WISH-338 (Amiga Pools of Darkness Fast Travel cannot start from an overland, and Fast Travel Back fails, because the area lookup returns nothing for that title)`, comment 5f95b787) | Amiga |
| S2 | Silver Blades, New Verdigris (`$10`) | `$4CD9` == 1: `$4CD9` = `$FF` (`ECL10 $84F7`-`$84FE`, `$9A25`-`$9A2C`) | PROBABLE: the throne-room celebration plays on every town visit, and the mines, temple and castle keep their post-victory branches | CONFIRMED that both exits write it and that town, mine, temple and castle scripts read 1 (bytecode); nothing seen | no, until L6 |
| S3 | Silver Blades, `$50`-`$52`, to anywhere outside the group | `$C059` = 9, `$C05A` = 12 (`GOSUB $9BE2` / `$9BBA`) | PROBABLE: later areas are drawn in the Crevasse colours | CONFIRMED that every exit of the group writes them and `GDRIVE01` reads them (bytecode); that they are colours is PROBABLE | no, until L6 |
| C1 | Curse, Pit of Moander (`$11`) | `$4C5B` != 255, `$4C2D` 128 or 255, `$4C2E` != 0: drop `ALIAS` and `DRAGONBAIT`, `$4C5B` = 255 (`ECL11 $82E1`-`$84F3`) | both stay in the party; a later return to the Pit plays the mid-chapter arrival | CONFIRMED (bytecode) | no, until L7 |
| C2 | Curse, Haptooth (`$31`-`$33`), to outside `$30`-`$33` | drop `AKABAR BEL AKAS`, then the game's `$40` for item types 94, 96 and 97 through a stub (`ECL30` entry 4, `$8014`-`$8098`) | Akabar and the items stay; what the item types are is UNKNOWN | CONFIRMED (bytecode) | no, until L10 |
| C3 | Curse, `$22`, `$25`, `$35` | the game's `$40` for the listed item types | the items stay; their identity UNKNOWN | CONFIRMED (bytecode) | no, until L11 |
| S1 | Silver Blades, the Compound (`$44`) | drop the first `SIR DERIC` (`ECL44 $82A4`-`$8360`, `$98CB`) | he stays until the party returns and walks out; no reader beyond membership found | CONFIRMED (bytecode, three ports identical) | no, until L8 |

**S2 and S3 are switched off until a live check shows what a player meets.**
Each has a confirmed write and a confirmed reader, but nobody has watched what
skipping it does, and the rule asks for that. L6 settles both: a C64 Silver
Blades town save with `$4CD9` staged to 1, Fast Travel out and back, with
screenshots of the town arrival and a mine level against a walked control; and
a party in `$50` Fast Travelling to `$10`, read `$C059`/`$C05A` and screenshot,
against a walk out of the Crevasses. Both rows are built and tested, so turning
one on is a change to `enabled` once its check passes.

**The four commission rows leave the reward recoverable**: a party that walks
back into the area and out on foot gets the write then. The clerk's payment
after a departure write has not been watched: in the one clerk check, the trip
arm and the walked arm heard the same five pages and the same closing line,
but the save used holds no earned commission, so neither arm was paid
([the Amiga Buccaneer Base and Zhentil Keep Outpost
runs](50-experiments.md#leaving-the-buccaneer-base-and-the-zhentil-keep-outpost-by-fast-travel-on-the-amiga-wish-313)).
To settle it: the same check from a save with `$4AA9` = 0xFE (the walked arm)
and from a trip out of area 1 with `$4AA9` staged to 1 (the trip arm), then the
clerk on City Hall's (5,5); expect the Bivant heir payment in both.

### The companion question

**Where a departure that drops a companion is proven necessary, the trip keeps
the game's own question.** Answering yes continues the trip and the companion
leaves as on foot; answering no cancels the trip and leaves the party where it
is, with nothing written. This holds only for a departure proven necessary, not
for every exit script, and it does not justify a row where another ordinary
route keeps the companion. Donald approved it in WISH-313 comment e6784958.

Princess Fatima is the one row it applies to today: the trip walks the caves'
own exit, so the player sees `DO YOU WANT TO LEAVE?`, and a `NO` lets the hop
expire with nothing written (unit tests on both ports). The live yes path is
L2, not run: `npc_party.d64`, trip 13 to 0 answering yes, expecting
`areas_seen` [13, 27, 0] and seven names after a game-written save and reload,
against a trip without her that goes [13, 0] with no question.

### Curse, Silver Blades and Pools of Darkness

**Curse of the Azure Bonds** (60ebad03). Needed: C1, C2 and C3 above, all
disabled. Not needed (seven exits, N1-N7): the rest write only the square, the
area-file byte, the per-step cancel, the sound flag and the wall pins the C64
trip zeroes itself, or a byte nothing reads. Curse on the Amiga runs the same
scripts (PROBABLE, 654a690a) and has no rows until the C64 rows pass. The C64
has no Curse re-entry addresses, so a `route_to` row cannot run there.

**Secret of the Silver Blades** (68de904c). Needed: S1, S2 and S3, all
disabled. Not needed (eleven exits, N1-N11), among them the Ruins' `$4CFF`
write (one of eleven exits makes it), the wall pins and the cancel byte. The
Amiga does not offer Fast Travel for this title, and whether DOS and the Amiga
store `$C059`/`$C05A` at all is unread.

**Pools of Darkness** (b7604d0f, revised by 77050ad9 and 6191dd8c). Needed:
D11 above. The story companion rows D1-D10 are not built. On the English
release the game removes Shal leaving area 70 (D1), Silk leaving 68 (D2),
Traned leaving 35 or 69 (D3, D4), Raizel leaving 34 (D5) and Storm leaving 82
or 83 (D6, D7); on the German `[a]` release also Priam (50), Vala (37) and
Nacacia (66), D8-D10. Silk is not needed, because other walked exits keep her
and reach everywhere; D1, D3, D4 and D7 matter only for destinations outside
each keeping reach; D5 and D6 are the only way out; D8-D10 exist only on a
release Wish does not attach to, so no player meets them. Not needed: variable
`$0E` before about fifty `NEWECL`s (only area 1's developer menu reads it,
PROBABLE), the overland landing cell, which the trip writes itself (below),
and the entrance selectors. Trips into overlands 17 and 25 land on the cells
of the game's first exits, shown live under `WISH-348 (Amiga Pools of Darkness
Fast Travel into an overland lands the party on its last overland cell, not
where the game's exits put it)` (the overland-cell section below).

### Still unresolved

Each defaults to straight until its check settles it.

| case | what is known | what would settle it |
|---|---|---|
| Return out of the Kobold Caves | `FastTravel.apply_back` and the Amiga `_back_by_door` consult `automap/departures.py`, so a Return out of the Kobold Caves with Princess Fatima walks her exit | a live Return out of a wilderness cave |
| L1, C64 direct trips | not run under the current code | `tools/c64/fasttravelrun.py` from `WISH-SPEC-por-c64-party-l1-intown`: 0 to 18, 18 to 9, 9 to 18, 18 to 7, 7 to 0, 0 to 1, 1 to 25, 0 to 28, 28 to 25, 0 to 26; every leg `areas_seen` [here, to], no fight, 0 to 26 on the grid with no dock text |
| Pool castle alarm, Stojanow Gate south exit | the exit clears `$4A64`; the alarm may lapse on its own | stage NEWSAVE1 at alarm 1 in area 9, trip to 18, rest 1, 6 and 24 hours, trip back, read `$4A64` after one step; 0 within a day means not needed |
| Pool, camp interrupted in a window-25 cave | can leave for area 1 with `$4A9E` still 255 (SPECULATIVE, game behaviour) | the breakpoint run in 58caa381 |
| Curse Zhentil Keep courtroom (`$23`) | every exit returns to `$20`, which clears `$4CE4`; a trip out may leave it set so the next Zhentil Keep arrival skips its map load | stage `$4CE4` = 255 outside `$20`/`$23`, trip to `$20`, compare the map (60ebad03 U1) |
| Curse Amiga wall pins `$4BE7`-`$4BE9` | the C64 trip zeroes them, the Amiga trip does not; a trip write, not a departure | 60ebad03 U2 |
| Pools of Darkness palace bearer names and the child-to-parent hand-over (40, 49, 73, 76, 77) | listed in b7604d0f section 5 | the checks there |
| Pools of Darkness companions D1, D3-D7 | rows not built; saves exist only for Storm | L9 on WinUAE against a walked control; D3 and D4 also need whether area 48's door to 19 is reachable without the Traned event |

## Visible: the overland square is whatever the party last stood on

**What the player sees.** You are in Sokol Keep and you use Fast Travel to go
to the wilderness. You arrive on the travel grid standing on whatever overland
square the party was last on -- which may be days of play ago, in a different
window, or the square the save was made on. Walking out of Sokol Keep instead
puts you on the square its exit names.

**Why.** Indoors the party's position is `$C04B`-`$C04D` and `newecl_writes`
writes it. Outdoors `$C04B`-`$C04D` is not the position, because `GDRIVE00` is
not resident. On the travel grid it is `$49C3`/`$49C4`, two bytes, which ten exits across six
scripts write on the way out. A fast travel writes neither, **and no arriving
script repairs them**: the straight path out of entry 4 was walked for all
thirty scripts and not one of them writes `$49C3` or `$49C4`. [`140`](140-loaded-files-cache.md) already
records the same thing from the other side -- a fasttravel carrying `(0,0)`
came up at `(0,0)` and one carrying `(5,2)` came up at `(5,2)`.

The travel facing is `$033D`, page 3, unsaved and of unknown encoding
([`113`](113-world-map.md), unknown 3), so it is not written.

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
The pin write is unconditional and zero. It costs nothing in the areas that
never set the pins, and one extra relocation pass on `ECL06`'s
Valjevo-to-Valjevo route, the one place the game leaves them set on purpose.

**Curse and Silver Blades have the same array, and it transfers.** It is at
`$4BE7`, `save_load_address` plus `$0200`. Each title's `DUNGEON` holds exactly
one reference to it, `LDA $4BE7,X / BNE`, in front of the same unpack setup
Pool of Radiance guards (`LDA #$0C / STA $B0 / LDA #$03 / STA $B1`, the piece
geometry): one hit per overlay across the three overlays, so no second array
exists that could be the real one. Which of the later titles' scripts pin a
piece is unmeasured.

**Grade: CONFIRMED**, in the emulator by `tools/areas/wallpins.py`. This said
PROBABLE until then, on the grounds that nobody had warped out of one of the
three and looked. Three arrivals at Podol Plaza's own arrival square,
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
`$F05D`-`$F367`; `$ED50`-`$F05C` matches the control byte for byte. A piece
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

## Visible: fast travelling out of the Kobold Caves keeps an NPC the game meant to take away

**What the player sees.** Princess Fatima is travelling with the party inside
the Kobold Caves. Walk south out of the caves, answer `YES` to
`DO YOU WANT TO LEAVE?`, read her farewell, and she is gone -- the party panel
in the wilderness lists seven names instead of eight. Use Fast Travel to leave
the caves instead and the panel still lists eight, with `PRINCESS FATIMA` on
it, at AC 0 and 33 hit points. She stays for the rest of the session and goes
into the save, and **no other script in the game removes her**: her name
appears as a compare operand once in all thirty scripts.

**Why.** `ECL0D` dispatches `GEO0D` square-attribute id 28 -- squares (6,15)
and (10,15) -- to `$99C1`, which asks whether to leave, walks the eight party
slots looking for her by name, and on finding her runs:

```
$9A84  SAVE 0, [$6B00]
$9A8A  SAVE 0, [$6C00]
$9A90  ADD 128, [$6E7A], [$6E7A]
$9A99  LOADCHAR [$6E7A]
$9A9D  NEWECL 27
```

`LOADCHAR` with bit 7 set writes the resident record **out** to the slot rather
than reading one in -- `DUNGEON $1BD0` takes `AND #$7F / STA $6DB4 / JSR $3729
/ JSR $441E` on `CMP #$80 / BCS`, and `LIBRARY $441E` copies `$6C00`-`$6C1F` to
`$8300 + slot*$20` and `$6B00` to `$4D00 + slot*$100`. So the four statements
are one thing: zero the name and the roster status, and write the emptied slot
back. That is the same pair of bytes the engine's own DROP CHARACTER zeroes
([`41`](41-memory-regions.md), `#104 (There is no party count in a C64 save)`).
The DOS guide's note that a `LOADCHAR` index of 128 or more adds a monster to
the party ([`128`](128-guide-and-scripting.md)) describes `ADDNPC` (`$36`), not
this opcode; `ECL0D $A8AB ADDNPC 104, 100` is how she joins.

**Grade: CONFIRMED**, in the emulator by `tools/pool_of_radiance/koboldnpc.py`.
Two runs of the warp plan and one of the walk plan, all three booting the same
save disk with the party in area 13 and ending in area 27, so the only thing
that differs is how the party left. Master slot 3 -- the record at `$4D00 +
3*$100` and the roster block at `$8300 + 3*$20`:

| how the party left area 13 | slot 3's name byte | slot 3's roster status | on the panel |
|---|---|---|---|
| walked out through `$99C1` | 0 | 0 | seven names |
| fast travelled, run 1 | `$50` (`PRINCESS FATIMA`) | 1 | eight names |
| fast travelled, run 2 | `$50` (`PRINCESS FATIMA`) | 1 | eight names |

The NPC bit at record `0x0B8` stays `$B2` in the walked capture; only the name
and the status are cleared. The other seven slots are untouched in all three.
The reasoning, the captures and what they do *not* show is
[walking out of the Kobold Caves drops Princess
Fatima](50-experiments.md#walking-out-of-the-kobold-caves-drops-princess-fatima-fast-travelling-out-keeps-her-180).

**What Fast Travel does about it now.** This is departure row P1: Fast Travel
is held in the Kobold Caves, so only a Return out of the caves with her in a
slot reaches it, and walks out through the caves' own exit, so the
game asks its question and removes her the way it intends; without her the
Return goes straight. On the C64 the walk is `automap.actions.reenter()`: the
party is placed on the exit
square and `DUNGEON` is re-entered at one of its own post-step points --
`$0957` after a landed step, `$0A4C` then `$0978` for the forward key off a
map edge -- with the stack rebuilt from `$03BF` first. That address is what
makes the re-entry legal rather than a hack: `NEWECL`'s own tail (`$2034`,
`LDX $03BF / TXS / JMP $0809`) rebuilds the stack from the same place and
jumps to the same main loop, so the engine does not trust the stack across an
area transition either, and `reenter()` does at a different moment exactly
what the engine's own transition does. **Grade CONFIRMED**, driven live
three times out of three on `npc_party.d64` through the hand-rolled re-entry
`tools/areas/exitreentry.py`, and once more through the shipped
`automap.actions.FastTravel().run()` itself, unmodified, through a real
`automap.target.ViceTarget` -- production code, not the hand-rolled tool,
dropped Princess Fatima the same way walking out does. `#180 (What the Kobold
Caves exit does to an NPC in the party is not understood, and Fast Travel
skips it)` is closed; the mechanism is `#207 (Run an exit's own handler
before Fast Travel warps out)`. On the Amiga the trip stands the party on the
door, which is in `DOORS_PROVEN`, and sends one forward key.

**Not yet shown under the current code.** The shipped path has one live sample,
by its author, and it ran under the earlier door rule. Live check L2 is owed:
see [The companion question](#the-companion-question).

**An area pair does not name a handler**, which is why the row tests the party
and does not just name the door: `ECL0D` has two `NEWECL 27` statements,
`$9A20` with nothing in front of it and `$9A9D` with the drop, and which one
runs depends on the party's contents and on the player's answer to a
`YES`/`NO` question. Twelve more script/target pairs in the specimens are
reached by more than one exit, and six exits read their target out of a table
so the walk cannot say where they go at all.

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

## Amiga Pools of Darkness: the overland cell

The same gap exists on the Amiga in Pools of Darkness, and there the trip does
write the cell. The party marker on an overland sits at `$25` (x, 0-37) and
`$26` (y, 0-14), and no arriving script writes either: each exit of the game
that enters an overland writes the cell with two `SAVE` statements just before
its `NEWECL`. A trip entered past those statements leaves the marker on
whatever cell the party last stood on in any overland.

A Fast Travel trip into an overland therefore writes the cell of the game's
first constant exit into it. That exit is the one with the lowest departing area
id, then the lowest script address, whose `SAVE` run sits directly before the
`NEWECL` and writes constants to both bytes; a compare between the `SAVE`s and
the `NEWECL` disqualifies a site, and so does a cell read from a table. Read
statically from both Amiga releases on the disks, which agree:

| overland | cell | exit it comes from | offered by Fast Travel |
|---|---|---|---|
| 17, the Moonsea overland | (6, 12) | Phlan's (area 16) first exit | yes |
| 25, the Moonsea overland after the ending | (10, 4) | the restored Phlan's (area 24) exit | yes |
| 51, the story dimension | none | its entries from areas 52 and 53 write the cell from a table | no |
| 80, Kalistes' dimension | (34, 1) | area 82's exit | no |

Both offered overlands put the party outside Phlan, as the game's own Phlan exit
does. The cell is written only for the offered rows.

**Not confirmed: `$0E`.** Every one of the chosen exits also writes `$0E`, and
writes 2. The trip leaves it alone. No script reads it except the developers'
menu in area 1, so only the engine can, and what it does with it is unread. If
the marker or facing after a trip differs from the one after walking out of
Phlan, `$0E` is the first suspect.

## What this does not cover

* **`ECL1E`, the attract-mode demo, has no `NEWECL` at all** and nothing
  fasttravels to it. It decodes at 89%; the remainder is data.
* **The two `NEWECL`s whose target is computed** -- `ECL03 $9AA2` and
  `ECL1D $9947` -- read the target out of a table with opcode `$2A` and the
  walk cannot say which areas they reach without running them.
* **Only one level of inbound blocks is reported** for a `NEWECL` something
  jumps to. A route two jumps back may run statements this page does not list.
* **Two of the three visible entries have been watched in the running game**
  -- the pinned wall slots by `tools/areas/wallpins.py` and the Kobold Caves'
  NPC by `tools/pool_of_radiance/koboldnpc.py`, both graded CONFIRMED above.
  The overland-square entry is still read off the bytecode only.
* **The departure rows other than P1 and P6 have no C64 live run**; their
  Amiga runs are in [the experiment
  log](50-experiments.md#fast-travels-departure-writes-on-the-amiga-the-lizardman-keep-and-the-nomad-camp-wish-313).
