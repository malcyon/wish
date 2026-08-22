# Bugs in the Gold Box games

Defects in SSI's own shipped code and data that a player can actually run into,
found by decoding the games rather than by playing them.

Everything here comes from the games' own bytecode, the 6502 in their overlays,
or their data files. Several were predicted from the code first and then carried
to a running Commodore 64 under emulation; each entry says which.

**Every bug on this list is CONFIRMED** -- corroborated a second, independent
way, usually by the game's own behaviour or its own printed output. Where a
supporting detail inside an entry is weaker than that, it says so. Findings that
no player would notice, and findings not yet confirmed, are both kept out: they
are in [`docs/125-bug-notes.md`](docs/125-bug-notes.md), with the longer list of
things that looked like bugs and turned out to be our own misreadings.

**The ECL bytecode is one artefact shared by every port** -- the Amiga's
`ecl.dax` unpacks to the Commodore 64's own scripts, load address and all -- so
a script bug found on the C64 is almost always in the other ports too, and where
a port fixed one, that is said.

---

## The list

| # | bug | game | kind | confidence |
|---|---|---|---|---|
| 1 | The C64 copy protection asks questions the code wheel cannot answer | Curse of the Azure Bonds | engine | CONFIRMED |
| 2 | Sokol Keep's dead elf comes back every time you return | Pool of Radiance | script | CONFIRMED, in game |
| 3 | QUICK is never cleared when a fight ends | Pool of Radiance | engine | CONFIRMED |
| 4 | The hedge maze's safer squares are as dangerous as the rest | Pool of Radiance | script | CONFIRMED |
| 5 | Two monsters are not the level their name claims | Pool of Radiance | data | CONFIRMED |
| 6 | Four monsters disagree with themselves about their own class | Pool of Radiance | data | CONFIRMED |

---

## 1. Curse's C64 copy protection asks questions its code wheel cannot answer

**The most consequential defect on this list, and the only one that makes the
game call a player wrong when they are right.**

**What the game does.** Curse of the Azure Bonds asks the player to look up a
rune pair on the printed wheel that shipped with it and type what they see. To
find the answer, the game computes an index. That index can come out negative,
and the two builds handle it differently:

* **DOS** adds 36 until the index is non-negative — the correct fix, and a
  cyclic one.
* **The Commodore 64 build negates it.** Two's complement, `EOR #$FF / ADC
  #$01`; in other words it takes the absolute value.

**What it should do.** What DOS does. The two operations coincide whenever the
sum is already non-negative and diverge whenever it is not.

**The evidence.** Both builds' challenges were enumerated and compared:

| | |
|---|---|
| challenges the two builds agree on | 10,135 |
| challenges they disagree on | **161** |
| total | 10,296 |

The 161 are exactly the cases where the sum goes negative — the divergence has
no other cause and no exceptions. The C64 arithmetic was read out of the binary
and then verified against the running game.

**And it is the port that is wrong, not the printed wheel.** This is settled by
the shape of the physical object rather than by consulting one. A code wheel is
two discs on a pin: what shows through a window is always
`ring[(offset + rotation) mod N]`. **A rotation is cyclic by construction and
cannot compute an absolute value.** The wheel therefore necessarily gives the
DOS answer, and where the C64 disagrees with DOS it disagrees with the wheel.

**What the player sees.** About **1.6% of C64 challenges — roughly one in 64 —
have no answer on the wheel at all.** A player who reads their wheel correctly
is told they are wrong. The failures are not spread evenly: they cluster under
one path and in the low box numbers, worst at box 1, where 66 of 572 rune pairs
are unanswerable. The game re-rolls a fresh challenge after each wrong answer
and allows three tries, so it is survivable rather than fatal — but a run of bad
luck ends the session, and the player has no way to tell an unanswerable
question from a misread one.

**Version.** Curse of the Azure Bonds, Commodore 64. DOS is unaffected.
CONFIRMED for the C64 code, from the binary and against the running game;
CONFIRMED for the wheel, by the argument above.

---

## 2. Sokol Keep's dead elf comes back every time

**Predicted from the bytecode, then confirmed on a running machine.**

**What the game does.** `ECL15 $9AE2` guards the long-dead elf's rusted
equipment with `COMPARE [$4A25], 255 / IF= / GOTO $9C9C`. **No instruction
anywhere in the game writes `$4A25`.** The branch is dead. The guard on the
line immediately below it, `COMPARE [$4A00], 255`, does work — `$9C92` sets
`$4A00` to 255 when you choose ATTACK — but `$4A00` is inside `$4A00`–`$4A1F`,
the per-script scratch page that `DUNGEON $202A` zeroes on every area change.

**What it should do.** Use a persistent flag. The game has a whole bank of them
at `$4A20`–`$4AF8`, and `$4A25` is inside it — the author reached for the right
range and then guarded on a byte he never wired up, with a scratch byte beside
it doing the work.

**The evidence.** Static first: a recursive walk of all thirty scripts finds
1,415 references into `$4A20`–`$4B7F`, and not one of them writes `$4A25`. The
prediction — *take the gear, leave the keep, come back, and the encounter is
offered again* — was then driven in the emulator at (6,13) in `GEO15`, the one
square in that map whose script id is 1:

| step | what the game printed | `$4A00` |
|---|---|---|
| first entry, step onto (6,13) | `THE SKELETON OF A LONG-DEAD ELF LIES HIDDEN BY ROCKS AND REEDS…` then `WHAT DO YOU DO? LEAVE SEARCH ATTACK TALK` | `00` |
| chose ATTACK | `YOU HACK THE BODY TO BITS.` | `FF` |
| stepped off and back on | `YOU SEE THE PITIFUL REMAINS OF A DEAD ELF.` | `FF` |
| left for the Slums, came back, stepped onto (6,13) | the original text again | `00` |

**What the player sees.** The encounter repeats on every re-entry to Sokol Keep.
Worse, SEARCH — the branch that hands you the scroll — writes no flag at all,
so it never suppresses the encounter even inside a single visit.

**Version.** Pool of Radiance, Commodore 64. `$4A25` is referenced in the Amiga
scripts too, so the Amiga has it as well. CONFIRMED.

A DOS guide published since lists "Sokal Keep's dead elf guard" among its own
script defects, which is a third port reporting the same encounter. It arrived
after the emulator run and changes nothing about the entry.

---

## 3. QUICK is never cleared when a fight ends

**What the game does.** Choosing QUICK from the combat bar sets bit 7 of roster
byte `+0x0C` for that character. Nothing clears it when the fight ends, and
`COMBAT` reads it at the *start* of the next fight.

**What it should do.** Clear it with the rest of the per-fight state.

**The evidence.** Three lines, and they only agree once you know the flag is
read at fight start:

* The live diff. With the game sitting on a command bar, 13,568 bytes were
  captured twice and **zero differed** — a machine waiting for input is
  perfectly still. QUICK on MALCYON then moved exactly three bytes, one of them
  `$830C` going `00` → `80`. Repeated on MAGNUS, slot 4: `$838C`.
* The player's own disks. `PORSAVE2`–`PORSAVE9`, all taken out of combat in
  ordinary play, read `80 00 00 00 00 00 00 00` across the eight roster blocks —
  the bit set for exactly one character, saved, and carried around.
* `PORSAVE14`. Quickfight enabled on MALCYON during a random orc encounter, the
  fight finished, saved, then a second and unrelated fight walked into — where
  MALCYON was **still under computer control**.

Two results that looked like refutations fall out of the same mechanism:
driving QUICK repeatedly shows the bit setting and clearing around each action,
and poking it on for another character mid-fight did nothing. Both follow if
`COMBAT` takes its copy when the fight begins and works from that.

**What the player sees.** Exactly the long-standing complaint: a character who
was handed to the computer once is still not yours in the next fight, which may
be a dangerous one. The only escape players found was pressing space at the
moment a turn begins.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED.

---

## 4. The hedge maze's half-rate squares run at full rate

**What the game does.** Bit 5 of a square's attribute byte marks it
`HALF_ENCOUNTER_RATE`. `GEO05`, the Valjevo Castle hedge maze, sets that bit on
**126 squares**, in contiguous blocks along corridors and courtyards, 116 of
them on squares with no script id — authored exactly the way `GEO03`, `GEO04`
and `GEO06` mark theirs. `ECL05`, the script that owns the area, contains no
test of bit 5.

**What it should do.** Halve the rate, as its siblings do. `ECL03 $9AE8` and
`ECL05 $9BD9` are the same routine with **fifteen bytes missing** from the
middle of `ECL05` — the `AND ATTR, 32` test and the `ADD` that doubles the
divisor:

```
ECL03                                   ECL05
$9AFF SAVE 20, [$6E79]                  $9BFD SAVE 20, [$6E79]
$9B12 AND ATTR, 32, [$6E82]             --- absent ---
$9B1B IF<>                              --- absent ---
$9B1C ADD [$6E79],[$6E79],[$6E79]       --- absent ---
$9B26 RANDOM [$6E79], [$6E82]           $9C03 RANDOM [$6E79], [$6E82]
```

**The evidence.** Exhaustive rather than sampled. `01 4F C0` is the VM's operand
for "read `$C04F`", the square's attribute byte, and it is the only way a script
can see it. `ECL03` has five `ATTR` references and `ECL05` has four — the same
four, minus the bit-5 test. A corpus-wide byte search for the whole instruction
finds it in `ECL03`, `ECL04`, `ECL06` and `ECL09` and nowhere else, and
`ECL64`/`ECL65`, the two scripts resident alongside every area, contain no
`ATTR` reference at all, so nothing is reading it on area 5's behalf.

**What the player sees.** Twice as many wandering monsters as intended in the
hedge maze.

**That `GEO05` is the hedge maze was independent of this finding and is now
corroborated.** It was read here off the map — 126 half-rate squares laid out
along corridors and courtyards — before any outside source was consulted; a DOS
script list published since names area 5 *Valjevo Castle Hedge Maze*. See
`docs/118-debug-mode.md`.

**Version.** Pool of Radiance, Commodore 64. The absence is CONFIRMED; that the
map layer is authoring residue rather than a repurposed bit is PROBABLE, resting
on the pattern matching its four working siblings in density, shape and
correlation with script id 0.

---

## 5. Two monster records disagree with their own names

**What the game does.** Twenty-one of the shipped `MON*` records state their
level in their name. `0x0A0`, the level byte, agrees with the name in nineteen
of them — `1ST LVL THIEF` 1, `2ND LVL CLERIC` 2, `LEVEL 3 MU` 3, `4TH LVL
FIGHTER` 4, `LEVEL 5 CLERIC` 5, `6TH LVL FIGHTER` 6, `7TH LVL DW FIGHTER` 7,
`8TH LVL FIGHTER` 8.

The two that differ are **`MON33` and `MON5D`, both named `6TH LVL THIEF`, both
carrying 7**. The per-class level array at `0x0C9` reads 7 as well, so the
record is internally consistent and it is the *label* that is wrong.

**What the player sees.** A thief the game calls 6th level fighting, saving and
being worth experience as a 7th.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED — the disagreement is
between the designer's label and his data, not between two of our readings.

---

## 6. Four monster records carry a class code that contradicts their class bits

**What the game does.** A character record says its class twice: `char_class` at
`0x073` names it, `class_bits` at `0x0EB` decides what it may use. Across the
**115 distinct `MON*` records** on the eight disks they agree everywhere except
four:

| record | file | `char_class` | `class_bits` |
|---|---|---|---|
| `DWARVEN FIGHTER` | `MON30` | 0 — cleric | fighter |
| `QUICKLINGS` | `MON0A` | 2 — fighter | cleric, fighter |
| `ENVOY` | `MON57` | 9 — cleric/fighter/magic-user | magic-user, fighter |
| `DRIDER` | `MON45` | 15 — fighter/magic-user/thief | magic-user, fighter |

`DWARVEN FIGHTER` is the telling one: its name says fighter, its bits say
fighter, and its code says cleric. Where they part company the bits match
reality — `DRIDER` is a drow, and fighter/magic-user is what a drow should be.

**What the player sees.** These are NPC and monster records, so the effect is
confined to what the character sheet prints for one of them if it ever joins.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED. Worth stating plainly
because a tool that "tidies" the two fields into agreement cannot represent
records the game itself ships — ours did, and it silently rewrote two bytes on
an import that edited nothing.

---
