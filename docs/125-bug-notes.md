# Bug notes -- the ones no player sees

The companion to [`../goldbox-bugs.md`](../goldbox-bugs.md), which is the
front-door list and carries only defects a player can actually run into. This
file holds the rest, because a finding that costs an afternoon should not be
lost for being undramatic:

* **latent defects** -- real errors in SSI's code that no shipped data reaches,
  and that would only bite a modified game;
* **cosmetic and internal** -- a truncated glyph, a duplicated label, flags
  written and never read;
* **unfinished work** rather than broken work, which is a different thing and
  does not belong on a bug list at all;
* **our own misreadings** -- the long tail of things this project called a game
  bug before finding the mistake was ours. That section is the most useful one
  here, because the failure modes repeat;
* **findings not yet CONFIRMED**, including ones a player would notice. The
  front-door file takes CONFIRMED only, so those wait here until they earn it.

Confidence labels mean what they mean in the front-door file. Entries are
numbered `N1` upwards so they cannot be mistaken for it.

One thing worth stating once, because it bounds every script finding in
both files: **the ECL decode is exhaustive.** All thirty scripts, 178,035
bytes, 16,233 instructions, zero derailments and zero bytes that neither
decode nor are pointed at by an operand. The engine overlays are not --
they have been read where a question demanded it and never swept.

---

## N1. `ECL07` writes an `OR` to the wrong destination

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

## N2. The VM's operand-count table disagrees with three of its own handlers

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

## N3. The opcode dispatch table has no bounds check

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

## N4. Curse's race table points two codes at `HUMAN`

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

## N5. `CHARPIC00` stops two bytes into its last glyph

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

## N6. The overland map's two windows disagree on one square

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

## N7. Effect expiry clears one array of four

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

## N8. A dead read guards a site that was cut

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

## N9. Three flags are written and never read

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

## Not yet confirmed

Three findings that a player *would* notice, and that are kept out of
[`../goldbox-bugs.md`](../goldbox-bugs.md) only because they are not CONFIRMED.
Each says what would promote it. Move it across when that is done, rather than
lowering the bar over there.

## U1. The icon editor's SIZE choice is never written back

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

## U2. Curse subtracts the prime-requisite bonus from the racial level cap

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

## U3. A Curse character export gets a directory block count of zero

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

---

## Unfinished, not broken

**Pool of Radiance has no paladin and no ranger, and that is a feature they did
not finish rather than a defect.** It shipped in the next game.

The class enumeration already runs `CLERIC=0 DRUID=1 FIGHTER=2 PALADIN=3
RANGER=4 MAGIC-USER=5 THIEF=6 MONK=7` — the full AD&D list, in the rulebook's
order. What is missing is everything downstream of it. The string list at
`$3288` holds six names and omits PALADIN and RANGER, so pointer entries 13, 14
and 15 all hold `$329D`, the address of `MAGIC-USER`. The creation menu offers
neither class, no record in the game uses either code, and the per-class level
array leaves their slots empty.

Curse of the Azure Bonds fills all of it in: paladin and ranger are offered at
creation, they take the `0x40` and `0x80` class bits, and their levels live in
the array slots Pool of Radiance left at zero. The enumeration did not change —
Pool of Radiance was built on the same table and simply stopped short of the
last two entries.

So this is scaffolding for work that came later, not a mistake, and it does not
belong on the list above. It is worth recording because it **exonerates a
third-party tool**: the 1989 BASIC editor was long blamed for listing class
codes 3, 4 and 5 as `MAGIC-USER`. Its author was reading the game's own table.

*Pool of Radiance, Commodore 64. CONFIRMED.*

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
| The 1989 BASIC editor wrongly lists class codes 3, 4 and 5 as `MAGIC-USER` | The game's, not the editor's — and not a bug either. See *Unfinished, not broken* |
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
