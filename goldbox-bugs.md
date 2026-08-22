# Bugs in the Gold Box games

A catalogue of defects in SSI's own shipped code and data, found by decoding
the games rather than by playing them.

Everything here comes from one of three places: the games' own ECL bytecode,
decoded whole — 178,035 bytes across thirty scripts, no derailments; the 6502
in their overlays; or their data files, read off the player's disks. A number
of predictions were then carried to a running Commodore 64 under emulation and
either confirmed or refuted. Each entry says which, and carries a label:

| label | means |
|---|---|
| **CONFIRMED** | corroborated a second, independent way — usually the game's own behaviour, its own printed output, or a second decode that could have disagreed and did not |
| **PROBABLE** | consistent with all the evidence held, not independently verified |
| **GUESS** | a plausible reading that something about the data argues against |

Two things to hold on to while reading. **The ECL bytecode is one artefact
shared by every port**: the Amiga's `ecl.dax` unpacks to the Commodore 64's own
scripts, load address and all, and 171 of the 172 flag addresses the C64 scripts
name appear in the Amiga's unchanged. So a script bug found on the C64 is
almost always in the other ports too, and where a port fixed one, that is said.
And **this is a short list for two games of this size.** Most of what looked
like a bug on first reading turned out to be our own misreading; the last
section is a list of those, and it is nearly as long as the rest.

---

## The list

| # | bug | game | kind | confidence | player sees it |
|---|---|---|---|---|---|
| 1 | The C64 verification check negates an index the DOS build corrects cyclically | Curse of the Azure Bonds | engine | CONFIRMED | yes |
| 2 | Sokol Keep's dead elf is guarded on an address nothing writes | Pool of Radiance | script | CONFIRMED, in game | yes |
| 3 | QUICK is never cleared when a fight ends | Pool of Radiance | engine | CONFIRMED | yes |
| 4 | The hedge maze's half-encounter-rate squares run at full rate | Pool of Radiance | script | CONFIRMED | yes |
| 5 | `ECL07` writes an `OR` to the wrong destination | Pool of Radiance | script | CONFIRMED | no |
| 6 | The VM's operand-count table disagrees with three of its own handlers | Pool of Radiance | engine | CONFIRMED | no (latent) |
| 7 | The opcode dispatch table has no bounds check | Pool of Radiance | engine | CONFIRMED | no (latent) |
| 8 | The icon editor's SIZE choice is never written back | Pool of Radiance | engine | PROBABLE | yes |
| 9 | Two monster records state a level in their name that their data contradicts | Pool of Radiance | data | CONFIRMED | yes |
| 10 | Four monster records carry a class code that contradicts their class bits | Pool of Radiance | data | CONFIRMED | yes |
| 11 | The class-name table has no string for paladin or ranger | Pool of Radiance | label | CONFIRMED | no |
| 12 | The race-name table points two codes at `HUMAN` | Curse of the Azure Bonds | label | CONFIRMED | no |
| 13 | `INTERECEPTED` | Pool of Radiance | text | CONFIRMED | yes |
| 14 | `SAPHIRE` | Pool of Radiance | text | CONFIRMED | yes |
| 15 | `UNCONSIOUS` | Pool of Radiance | text | CONFIRMED | no |
| 16 | The training routine subtracts the prime-requisite bonus from the racial cap | Curse of the Azure Bonds | engine | GUESS | maybe |
| 17 | A character export gets a directory block count of zero | Curse of the Azure Bonds | engine | PROBABLE | yes |
| 18 | `CHARPIC00` stops two bytes into its last glyph | Pool of Radiance | data | CONFIRMED | no |
| 19 | The overland map's two windows disagree on one square | Pool of Radiance | data | PROBABLE | no |
| 20 | Effect expiry clears one array of four | Pool of Radiance | engine | CONFIRMED | no |
| 21 | A dead read guards a site that was cut | Pool of Radiance | script | GUESS | no |
| 22 | Three flags are written and never read | Pool of Radiance | script | CONFIRMED | no |

---

## 1. Curse's C64 verification check asks questions its wheel cannot answer

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

**Version.** Pool of Radiance, Commodore 64. The absence is CONFIRMED; that the
map layer is authoring residue rather than a repurposed bit is PROBABLE, resting
on the pattern matching its four working siblings in density, shape and
correlation with script id 0.

---

## 5. `ECL07` writes an `OR` to the wrong destination

**What the game does.** `ECL07 $A81C` is `OR [$4A6D], 16, [$4A72]` — read
`$4A6D`, set bit 4, store the result **somewhere else**. Every other `OR` on
`$4A6D` in that script writes back to `$4A6D`: `$A326 OR 1`, `$A350 OR 2`,
`$A3BA OR 2`, `$A3F5 OR 2`, `$A551 OR 8`, `$A622 OR 4`.

**What it should do.** Write `$4A6D`. It is a single mistyped operand.

**The evidence.** Bit 4 of `$4A6D` is *tested* three times, and nothing else in
the game sets it, so it can never be set. `$4A72` exists in the address space
for no other reason: it is written once, by this instruction, and read by
nothing.

**What the player sees.** Nothing, by luck. The bit suppresses the
dagger-playing man, the robed merchant and the bronze dragon's speech once
Tyranthraxus is dead — and `PROGRAM 8`, the endgame, runs nine instructions
later. A typo made permanent with no consequence.

**Version.** Pool of Radiance, Commodore 64; `$4A72` is referenced in the Amiga
scripts too. CONFIRMED.

---

## 6. The VM's operand-count table disagrees with three of its own handlers

**What the game does.** The ECL interpreter lives in `DUNGEON`: entry `$1581`,
dispatch `$1590`, and three 62-entry tables end to end at `$15A9` (handler low),
`$15E7` (handler high) and `$1625` (operand-set count). For three opcodes,
`$1625` does not match what the handler actually fetches:

| opcode | `$1625` says | the handler consumes |
|---|---|---|
| `$0C SETUPMON` | 2 | 3 |
| `$29 ENCMENU` | 13 | 14 |
| `$36 ADDNPC` | 1 | 2 |

**What it should do. `$1625` is read at exactly one site** — `$1BB9`, inside
the skip-a-command routine `$1BB5` that a false `IF` uses to step over the
instruction it did not take. So an `IF` immediately in front of any of the
three would leave one operand set unconsumed, and the VM would resume executing
operand bytes as opcodes: everything after it becomes garbage.

**The evidence.** The handlers, read directly — `SETUPMON` at `$1F0A` fetches
three in a straight line into `$6DD0`, `$6DC1`, `$6DDA` — and the data, since
the counts the handlers use are the only ones that decode all thirty scripts
with no derailment anywhere.

**What the player sees.** Nothing. A sweep of all 16,233 decoded instructions
finds no `IF*` whose next command is one of the three. SSI got away with it.

**Version.** Pool of Radiance, Commodore 64; `DUNGEON` is byte-identical on all
eight disk sides. CONFIRMED, latent.

---

## 7. The opcode dispatch table has no bounds check

**What the game does.** There are 62 opcodes, `$00`–`$3D`, and the dispatch
tables are 62 entries long. Nothing validates the fetched opcode, so `$3E` would
index one past the end of the low table — into the high table — and jump to
nonsense.

The operand evaluator at `$1663` is equally trusting: codes `$04`–`$7F` fall
through to the `03` path (word at absolute address) and `$82`–`$FF` to the `81`
path (string at absolute address). It cannot reject a malformed operand; it can
only misread one.

**What the player sees.** Nothing. No script uses an opcode above `$3D`. This
matters mainly to anyone writing tools: a decoder that raises on those codes
derails where the game does not, which is what sank three of our own script
decodes.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED, latent.

---

## 8. The icon editor's SIZE choice is never written back

**What the game does.** `SPELLN64` is the combat-icon editor, reached through
ENCAMP → ALTER → ICON and during character creation. Its menu is `ICON: PARTS
COLOR SIZE EXIT`. Choosing SIZE switches which of the four option tables the
session offers — 28 weapons and 14 heads for small, 35 and 23 for large — and
that is all it does. **There is no `STA $6B99` anywhere in the overlay**, so
record byte `0x099`, the size flag, keeps whatever `GEN $0958` set it to from
the character's race.

**The evidence.** The absent store, plus a specimen: HOGARTH, on the player's
disks, has an icon that mixes a large body with a small head — a shape no single
(weapon, head) pair can produce. 17 of the 18 distinct shapes on our disks come
out of one pair exactly; HOGARTH's is the 18th.

**What the player sees.** The SIZE menu appears to do something and does not
persist, and an icon can end up mixing parts from both tables.

**Version.** Pool of Radiance, Commodore 64. PROBABLE — the absent store is
certain, but whether SIZE was *meant* to be persistent is an inference from the
menu's existence.

---

## 9. Two monster records disagree with their own names

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

## 10. Four monster records carry a class code that contradicts their class bits

**What the game does.** A character record says its class twice: `char_class` at
`0x073` names it, `class_bits` at `0x0EB` decides what it may use. Across 105
records they agree everywhere except four monster records:

| record | `char_class` | `class_bits` |
|---|---|---|
| `DWARVEN FIGHTER` | 0 — cleric | fighter |
| `ENVOY` | 9 | magic-user, fighter |
| `DRIDER` | 15 | magic-user, fighter |

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

## 11. The class-name table has no string for paladin or ranger

**What the game does.** The class enumeration runs `CLERIC=0 DRUID=1 FIGHTER=2
PALADIN=3 RANGER=4 MAGIC-USER=5 THIEF=6 MONK=7`. The string list at `$3288`
holds six names and omits PALADIN and RANGER. The pointer table papers over the
gap the cheapest way available: **entries 13, 14 and 15 all hold `$329D`**, the
address of `MAGIC-USER`.

**What the player sees.** Nothing in ordinary play — Pool of Radiance's creation
menu offers neither class and no record in the game uses either code. A record
imported or edited to be one displays as `MAGIC-USER`.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED, and it exonerates a
third-party tool: the 1989 BASIC editor was long blamed for listing codes 3, 4
and 5 as `MAGIC-USER`. Its author was copying the game.

---

## 12. Curse's race table points two codes at `HUMAN`

**What the game does.** Curse of the Azure Bonds drops half-orc from character
generation but leaves human at code 7, and its label table names **both 6 and 7
`HUMAN`**.

**What the player sees.** Nothing directly. It matters to anything importing a
Pool of Radiance character: a half-orc arrives as code 6, prints as HUMAN, and
there is no way to tell it apart from a real human without looking at the byte.
`por/games.py` deliberately leaves 6 unnamed for that reason — naming it
"half-orc" would contradict what the game prints and naming it "human" would let
an import silently rewrite a 7 as a 6.

**Version.** Curse of the Azure Bonds, Commodore 64. CONFIRMED, read off the
game's own label table.

---

## 13–15. Three spelling mistakes

| where | shipped | should be | seen by the player |
|---|---|---|---|
| `ECL08`, one packed string | `INTERECEPTED` | `INTERCEPTED` | yes — it is printed |
| `ITEMNAMES` index 248 | `SAPHIRE` | `SAPPHIRE` | yes — it is a gem you can carry |
| `LIBRARY` string 46 | `UNCONSIOUS` | `UNCONSCIOUS` | no |

**`INTERECEPTED` was fixed in a later port.** `ECL08`'s 77 packed strings on the
Commodore 64 are 76 shared with the Amiga release plus this one correction —
which is a useful datum in itself, because it shows the differences between the
two ports' scripts are release revisions of one artefact rather than a
re-authoring.

**`UNCONSIOUS` is never printed.** It sits in the run `OK GONE DEAD DYING
UNCONSIOUS RUNNING STONED` at `LIBRARY` string indices 42–48, and **nothing on
any of the nine disks references indices 42–48** — all 64 call sites into the
string printer were checked. The Commodore 64 party list prints name, armour
class and hit points only; status is derived, not stored. The typo is preserved
in the later titles' editors, which copied the enumeration.

All three CONFIRMED, Pool of Radiance, Commodore 64.

---

## 16. Curse subtracts the prime-requisite bonus from the racial level cap

**What the game does.** Curse's training routine checks two ceilings: a per-class
cap read as `LDA $7CC9,X / CMP $15A1,X`, and a racial cap indexed
`(race - 1) * 8`. Reading the racial check, the routine looks up the
prime-requisite bonus (+1 at 17, +2 at 18, from the second ability array at
`0x065`) and **subtracts** it from the limit rather than adding it. Written out,
a strong fighter would be capped *lower* than a weak one.

**What it should do.** Add it. AD&D 1st edition raises a demihuman's class limit
for a high prime requisite; it never lowers it.

**The evidence, and its weakness.** The racial table itself is CONFIRMED —
half-orc `0/4/8/10` and half-elf `8/5/99/8` are the AD&D rows exactly, and they
are the two no other reading of the table would produce. The sign is a reading
of the accumulation into `$B0` and nothing more. Either it is a bug or the
accumulation works some way this reading misses. Nobody has trained a strong
demihuman in the emulator to watch it refuse.

**Version.** Curse of the Azure Bonds, Commodore 64. **GUESS**, and it is on the
list precisely because it is the weakest claim here.

---

## 17. A Curse character export gets a directory block count of zero

**What the game does.** `\x02BRUTUS` on the player's own `CURSESAVE2.D64`, a
disk Curse wrote, reports **0 blocks** in its directory entry and has a
perfectly valid sector chain. The file reads back as 582 bytes at `$7C00`.

**What the player sees.** A directory listing that says 0 for a file that
exists, and anything that trusts the count — a copier, a validator, another
tool — refusing to see the file. Our own disk reader skipped zero-block entries
and so hid every Curse-written character file until it was changed to follow the
chain and ignore the count.

**Version.** Curse of the Azure Bonds, Commodore 64. **PROBABLE** — the
observation is certain, but this disk has been handled by other tools and the
count could in principle have been zeroed after the game wrote it.

---

## 18. `CHARPIC00` stops two bytes into its last glyph

**What the game does.** The icon character set is eight bytes a glyph with no
header. Its payload is 2030 bytes — six past the end of glyph 252 — so the file
**stops two bytes into glyph 253**. `2032 = 8 × 254` is the most an eight-block
PRG can carry, and a full 2048-byte set would need a ninth block.

**What the player sees.** Nothing, and this is a build artefact rather than a
design error. The highest shape code across thirteen sources is 243, ending 72
bytes clear of the truncation, and glyphs 244–252 are non-blank, so the file is
not merely blank-padded. Glyph 253's surviving bytes are `00 00 00 00 3C F4`,
and glyphs 81 and 251 are the only ones matching those six, so the lost tail was
`D4 D4`.

**Version.** Pool of Radiance, Commodore 64; one `CHARPIC`, byte-identical on
all eight sides. CONFIRMED, harmless.

---

## 19. The overland map's two windows disagree on one square

**What the game does.** The wilderness is not a `GEO` at all: `SQRDATA04`, `05`
and `06` are three overlapping windows on one world, thirteen columns apart, 18
× 36 squares each. Where two windows cover the same ground they should hold the
same terrain.

`SQRDATA05` → `SQRDATA06` agrees at **180 of 180** squares. `SQRDATA04` →
`SQRDATA05` agrees at **179 of 180**.

**What the player sees.** At most one square of terrain that changes appearance
when the party crosses between map 25 and map 26. The edge-crossing arithmetic
itself closes exactly on both boundaries, so it is a data discrepancy and not a
geometry error.

**Version.** Pool of Radiance, Commodore 64. **PROBABLE** as a defect — the
measurement is certain; that SSI did not intend the difference is an inference
from the other 359 squares.

---

## 20. Effect expiry clears one array of four

**What the game does.** An active spell effect occupies four parallel arrays:
`$4900`–`$493F` the effect code, `$4940`–`$497F` the owner (bit 7 = whole
party), a magnitude, and `$4B80`–`$4BBF` a third parallel array. `CAMP $131F`
expires an effect by clearing `$4900,X` **and nothing else**. Owner, duration
and magnitude keep the dead effect's values.

**What the player sees.** Nothing — the effect code is what everything tests.
The residue is real, though: `PORSAVE13` carries six slots with magnitude 1 that
belong to effects that had already lapsed, and for a while that looked like a
refutation of the whole decode.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED, harmless.

---

## 21. A dead read guards a site that was cut

**What the game does.** Sites on the overland map are hidden by painting plain
terrain over them until their flag is set. `ECL1B` paints three of them, each
`SAVE x, [$00FB] / SAVE y, [$00FC] / SAVE tile, [$00B1] / CALL [$C018]`, gated
on the bits of `$4AA0`: bit 0 the lizardman keep, bit 1 the kobold caves, and
**bit 2 a square at (7,23) that has no entry in the site table**. Bit 2 is read
there and written nowhere.

**What the player sees.** A square of plain terrain, permanently. This is cut
content rather than a malfunction, and it is on the list because the shape —
a read with no matching write — is exactly the shape of bugs 2 and 5, and
telling the three apart took work.

**Version.** Pool of Radiance, Commodore 64. **GUESS** that it is authoring
residue; CONFIRMED that the read is dead.

---

## 22. Three flags are written and never read

Small change, recorded because each is a loose end somebody wired up halfway.

| flag | written by | when | read by |
|---|---|---|---|
| `$4A59` | `ECL1C $9CC6` | the Zhentil Keep commandant welcomes the party | nothing |
| `$4A72` | `ECL07 $A81C` | the endgame — see bug 5 | nothing |
| `$4AC6` | `ECL00 $9BD6` | you board a boat | nothing |

`$4A59` is the interesting one: `$4A5A`, set when the commandant is *killed*, is
tested twice. The pair reads as an intended "welcomed / murdered" distinction of
which only half was wired up. `$4AC6` is redundant — `$4AC4`, the boat
destination, does all the work.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED as dead writes; that
`$4A59` was meant to be read is PROBABLE.

---

## Attribution we are not sure of

One find that may not be SSI's. **Gateway to the Savage Frontier's `GATE8` side
carries a directory entry `GE031` — a one-off misspelling of `GEO31`.** Both
files exist and both decode. The only rip available has a hand-rewritten
directory (it also carries PETSCII art entries and a `WALLDEF1F\x01`), so the
misspelling may be the rewriter's rather than the publisher's. Recorded, not
claimed.

---

## Things that look like bugs and are not

Every item below spent time on a list like this one before turning out to be
**our** mistake. They are here because a bug list read without them looks more
damning than the evidence supports, and because the failure modes repeat.

| we said | it was actually |
|---|---|
| The combat map's row stride is `$0607` | Ours. The renderer takes it from `$0612 + 1`. The two agree at 56 in a fight and the difference never shows, which is why the wrong one was written down; outdoors, `$0607` reads 20 against a true 18 and would shear every row two squares along |
| `ADDNPC` takes one operand set, and `ECL1E` is corrupt | Ours. The handler at `$2724` evaluates a second set on both arms of the `BMI` at `$2733`, so it is always 2. With 1 our decode of `ECL1E` collapsed from 89% to 7%, and we read the collapse as the game's fault |
| Characters with the `0x10`, `0x40` and `0x80` class bits have no levels, which breaks the class-bits invariant | Ours. **The per-class level array at `0x0C9` is eight bytes wide, not four.** The levels were there in the slots we were not reading. The invariant holds across all thirty-six shipped characters in six titles |
| `0x0D9` cannot be attacks-per-round-doubled, because BRUTUS reads `03` | Ours. The `03` came from a dump that started at `0x0D8`, one byte early. `0x0D9`–`0x0E0` is `attack_forms`, and twenty creatures match the *Monster Manual* |
| `npc_party.d64` has garbled item names, so it has been through an editor | Half ours. The disk *has* been edited, but the garbling was our own: `ITEMNAMES` has **no name at indices 62, 63 and 168**, and our sequential reader closed the gaps, shifting every later name by one or three. Index 66 read `STAVE` instead of `RING` — plausible, and therefore the worst kind of wrong |
| PRINCESS FATIMA's race byte is 0, which is outside the enumeration and proves tampering | Ours. **Race 0 is the commonest race in the game** — 75 of 135 monster records carry it — and `LIBRARY $3508` deliberately underflows it to print `MONSTER`. Nothing was tampered with |
| The 1989 BASIC editor wrongly lists class codes 3, 4 and 5 as `MAGIC-USER` | The game's, not the editor's. See bug 11 |
| `WALLDEF`'s colours decode wrongly, so the format is not understood | Ours. `$7A00` is a general RLE expander and its encoding is **count-then-value**; we had it the other way round, and 548 of 780 bytes came out wrong |
| Roster bytes `+0x03`–`+0x05` are memorised-spell counts | Ours. They matched for all four casters on one disk. A controlled test — memorise five spells across three characters, rest, save — produced a byte-identical roster page still reading `0/0/0` |
| The combat log picks up garbage because something else is rewriting the file | Ours, twice, both in `automap/combatlog.py`, and both only visible against a running fight |
| Driving the game wedges at the training hall, four runs running | Ours. Four runs of one wrong assumption is not four pieces of evidence; the training schools are not on that square and not in that area at all |

The pattern worth carrying away is in three of those rows: **a hypothesis that
sparse data agrees with has not been tested.** The `$400` slot stride survived
because every specimen then held at most two characters. The spell counts
survived because four casters agreed. The four-byte level array survived because
Pool of Radiance never fills the other four slots.

---

## What this is not

A completeness claim. It is a list of what has been *found*, from a project that
was decoding formats rather than hunting bugs, and it stops where the evidence
does. Two things are worth saying about the sample it comes from:

* **The ECL decode is exhaustive.** All thirty scripts, 178,035 bytes, 16,233
  instructions, zero derailments and zero bytes that neither decode nor are
  pointed at by an operand. So the script-level findings — bugs 2, 4, 5, 21, 22
  — are drawn from the whole population and not a sample of it. What remains
  unfound there would have to be a *semantic* error in code that reads correctly.
* **The engine is not.** The overlays have been read where a question demanded
  it. Nobody has swept them for defects, and bugs 3, 6, 7, 8 and 20 were all
  found while looking for something else.

There are also 182 bytes of well-formed bytecode across the thirty scripts that
nothing ever branches to — cut code, each island parsing cleanly from its first
byte to its last. That is the ordinary residue of a game shipped on floppies in
1988, and it is not on the list.
