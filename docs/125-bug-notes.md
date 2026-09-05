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

**A second derivation, from the DOS side.** Stephen S. Lee's guide lists six
opcodes a false `IF` fails to skip: `SETUPMON`, `VERTMENU`, `ONGOTO`, `ONGOSUB`,
`HORIZMENU` and `ADDNPC`. Ours and his overlap on `SETUPMON` and `ADDNPC`; his
four extras are the **variable-length** opcodes, whose length the skip routine
cannot know at all, and ours adds `ENCMENU`. **The union is seven**:
`SETUPMON`, `ENCMENU`, `ADDNPC`, `VERTMENU`, `ONGOTO`, `ONGOSUB`, `HORIZMENU`.
Two people, two ports, two methods, one defect.
(`docs/128-guide-and-scripting.md` says "eight"; naming the members gives
seven, and the members are what matters.)

**What the player sees.** Nothing. A sweep of all 16,233 decoded instructions
finds no `IF*` whose next command is one of the three — and the guide reports
that no DOS script fires its four either. SSI got away with it.

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
`goldbox/games.py` deliberately leaves 6 unnamed for that reason — naming it
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

## N10. The pyramid's "no monsters left" test needs a bit nothing sets

**What the game does.** Yarash's pyramid, first level (`ECL16`), keeps a bitmask
of the fixed encounters it has already used — `$4A4E` for the north half of the
map, `$4A4C` for the south, chosen on `mapY < 8`. Five encounters are drawn by
`RANDOM 5` and marked off through a powers-of-two table, so they occupy bits 0
to 4; bit 6 is the human priest. Before setting the wandering-monster rate,
`$9BE9` asks whether the mask has run out: `AND [$6E82], 63 / COMPARE [$6E82],
63 / IF= / EXIT`.

**What it should do.** Compare against 31. Bit 5 is never written by anything —
the only two writes to either mask are `$A38F` and `$A39A`, both
`OR [$4A4C|$4A4E], [$6E7F], …` where `[$6E7F]` is the table entry for an index
that is only ever 0-4 or 6.

**The evidence.** With all five encounters used and the priest met, the mask is
`$5F`; `$5F & 63` is 31, not 63. The test can never pass.

**What the player sees.** Almost nothing: the pyramid's first level keeps
rolling wandering monsters after its fixed encounters are exhausted, where it
was meant to go quiet. Nobody would know the difference without the code.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED from the bytecode.

---

## N11. Phlan's proclamation board runs out of proclamations

**What the game does.** The notice board in civilised Phlan reads out a journal
reference chosen by how many major commissions the council has paid for:
`ECL00 $AC60 SUB 1, [$4AC1], [$4A18]` then `ONGOSUB [$4A18], 9, …`, nine
handlers, each of which stores a roman numeral into the string slot the next
two instructions print.

**What it should do.** Carry ten handlers. `$4AC1` is bumped by exactly ten of
the clerk's speeches, so it reaches 10 and the index reaches 9 — one past the
end of a nine-entry table.

**The evidence.** The VM's `ONGOSUB` at `DUNGEON $20B7` walks its operand list
counting up to the index and leaves the target's high byte zero if it never
matches; `$20F2 BEQ $20F9` then returns without calling anything. So the
out-of-range case is safe, and the string slot keeps whatever it last held.

**What the player sees.** Once the tenth major commission is paid, the board
repeats the previous proclamation number instead of showing a new one. Two of
the nine handlers already print `CXIV.`, so a repeat is not even conspicuous.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED from the bytecode.

---

## N12. The reward ledger has a twenty-third commission that was cut

**What the game does.** The council's ledger is 26 bytes at `$4AA6`. Index 22,
`$4ABC`, is named by **no instruction in any of the thirty scripts** — not a
read, not a write — and its handler in the clerk's speech table at
`ECL08 $9D55` is a bare `RETURN` at `$A4CD`.

**The evidence.** Two independent ones. The three-byte operand a script spends
naming `$4ABC` occurs zero times across all 46 `ECL*` files on the eight disks
(`tests/test_commissions_data.py` asserts it). And the entry is not merely a
spare slot: the clerk's four payout tables run 0-22, and index 22's row is not
empty, so the byte was a commission that paid something before it was cut.

**What the player sees.** Nothing. The byte can never leave 0.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED unreachable; that it is
cut content rather than a slot never filled is PROBABLE.

---

## N13. A cleric one point short of the rulebook still gets the bonus spell

**What the game does.** `GEN $2108` looks up the wisdom bonus in the table at
`$10AD`, indexed by the score. The table is zero to 11, **1 at 12** and 2 from
13 up. AD&D 1st edition gives the first bonus first-level spell at wisdom 13
and the second at 14, so the whole first-level column is shifted one point
down: a wisdom-12 cleric memorises a first-level spell the rules do not give
it, and a wisdom-13 cleric gets two where the rules give one.

**What it should do.** Start at 13. The second- and third-level columns are the
rulebook's exactly — they are gated on `CPY #$0F`, `#$10` and `#$11`, which is
wisdom 15, 16 and 17 — so it is the one column and not the whole table.

**The evidence.** The table's bytes and the three compares. ROLAND, wisdom 16,
stores `50 50 20` at cleric 6, which is `3,3,2` plus `+2,+2,0` and agrees with
both readings; no cleric on the player's disks has a wisdom of 12 or 13, which
is why the shift has never been seen rather than computed.

**What the player sees.** One extra first-level spell on the memorise screen,
and no way to tell it is extra. Here rather than in the front-door file for
that reason: it is CONFIRMED from the table and the compares, but what it costs
a player is a spell they will assume they were owed.

**Version.** Pool of Radiance, Commodore 64. CONFIRMED.

---

## N14. Ours: the fighter's level-4 breath save, and the four THAC0 rows above it

**What we got wrong.** `goldbox/levels.py` gave a level-4 fighter a breath save of
16, which is the AD&D 1st edition number, and the game writes 15. It was
recorded as a divergence in `tests/test_liveparty.py` for a day on the reading
that the game might be wrong.

**What is actually there.** The game does not tabulate saving throws. It holds
a level-1 row at `GEN $1FA2` and two per-column bitmasks at `$1FB6` and
`$1FCA`, and a column improves by one for every set bit, in either mask, among
the low `level - 1` bits. The fighter's fourth column carries mask `$0C` where
its other four carry `$08`, so that column improves twice by level 4 and once
elsewhere. Fifteen is the table's own answer, deliberately, and ours was a
transcription of the rulebook rather than of the game.

`goldbox/derive.py` had the same shape of error next door: its fighter THAC0 row
was AD&D's grouped one, `20 20 18 18 16 16 14 14`, where the game's table at
`$1F1F` runs `20 19 18 17 16 15 14 13`. Every even fighter level was one out,
and no specimen was an even-level fighter with cached combat numbers to catch
it.

**The lesson, which is the same one twice.** A published table and the game's
table are different documents. `tests/test_levels.py` now re-expands every row
from the player's own `GEN` rather than trusting the longhand.

---

## N15. The slums' booth man is tested against a value he cannot hold

`ECL14` counts a cleared slum encounter by `GOSUB [$B69C]`, and at the booth in
the old Rope Guild the call is guarded: `$AF73 COMPARE [$4A81], 255 / IF<> /
GOSUB [$B69C]`. The guard can never fail. The booth encounter's own entry test
two hundred bytes earlier is `$AE1E COMPARE [$4A81], 250 / IF>= / EXIT`, so
control only reaches `$AF73` when `$4A81` is below 250, and 255 is not.

The author was guarding against double-counting the man who wants the potion —
`$4A81` is shared between the two scenes and both `$A0B8` and `$A3A8` set it to
255 — but the entry test already does that job. Nothing is miscounted and the
player sees nothing.

Found while settling whether `$4ABB`'s threshold of 25 means encounters,
`docs/134-commissions.md`.

## N16. Thirteen slums squares carry a script id the dispatcher cannot reach

`ECL14`'s square dispatcher walks a counter against the square's own id:
`$99A2 SAVE 0, [$9800]`, `$99A8 COMPARE [$9800], [$6E82] / IF= / GOTO [$99C9]`,
`$99B4 COMPARE [$9800], 20 / IF> / EXIT`, `ADD 1`, loop. Twenty-one ids, 0 to
20, and `$99C9`'s `ONGOTO` has exactly twenty-one pointers.

**Thirteen squares in `GEO14` have id 21.** `(1,0) (2,0) (3,0) (0,1) (1,1)` in
the north-west and `(8,5) (6,6) (7,6) (8,6) (6,7) (7,7) (8,7) (7,8)` in the
middle — two building-shaped blocks. The counter reaches 21, matches, and the
`ONGOTO` is handed an index one past its last entry.

**What the player sees.** Two rooms that say nothing, where the map data says
something was meant to happen. Whether the out-of-range `ONGOTO` falls through
into the instruction after it — which is `$9A0E`, the script's own entry 2 —
or does nothing at all has not been driven. PROBABLE, and what would promote it
is standing on one of the thirteen with a checkpoint on `$9A0E`.

Found while confirming `goldbox-bugs.md` #9 (Finish the packaging icons: .desktop, .icns and a README lockup), which needed the dispatcher's
indexing settled: it is 0-based, so script id 8 is the fortune teller.

## N17. Ohlo introduces himself again after a trip out of the slums

`ECL14 $9F13` is the small man with the pen who wants a potion fetched. His
handler keeps two bytes: `$4A81`, in the persistent bank, which is 250 once you
are carrying the potion and 255 once the errand is closed either way, and
`$4A04`, which `$A251` sets to 250 when you accept the commission and which is
only read to print `YOU HAVE RETURNED EMPTY HANDED` on the way back.

`$4A04` is in `$4A00`-`$4A1F`, the page `DUNGEON $202A` zeroes on every area
change. So a party that takes the errand, walks out of the slums and comes back
without the potion gets `YOU BURST INTO AN ELEGANTLY PANELLED ROOM…` and the
whole parlay again, instead of the one line written for that case.

**What the player sees.** A scene replayed, and nothing else: `$4A81` carries
the errand itself, so no reward is repeated and no state is lost. PROBABLE —
read from the bytecode, not driven. Same page and same class of mistake as
`goldbox-bugs.md` #9 (Finish the packaging icons: .desktop, .icns and a README lockup); it is here rather than there because the consequence is
a repeated paragraph.

## N18. A zero-length `.ITM` gives a DOS character one item made of heap

**What the game does.** DOS Pool of Radiance, handed a character whose item
count is 0 and whose `.ITM` file exists but is **empty**, builds a chain of one
item it never read. The view screen draws it — `WEAPON 254 PASSS`,
`DAMAGE 0D8-128`, `THAC0 148`, `ENCUMBRANCE 60540`, the quantity `254` being
the heap's `0xFE` — and the next save writes the phantom out as a 63-byte
`.ITM`, rebuilding the chain-head pointer at `0x0C8`/`0x0CA`/`0x0CB`.

**What it should do.** Treat an empty file as no items. Its own save writes
**no `.ITM` at all** for a character carrying nothing, so the empty file is a
state it never produces and never checks for.

**The evidence.** The same 285 record bytes, run twice, differing only in
whether the file is there: with it the sheet is garbage, without it there is no
`WEAPON` line, `DAMAGE 1D2+5`, `THAC0 18`, `ENCUMBRANCE 120` and no `ITEMS` in
the VIEW bar. Six variants in one save slot separated on the file and not on
`hands_used`. CONFIRMED, `docs/50-experiments.md` "A converted character who
owns nothing (#62 (A converted character who owns nothing gets a corrupt sheet, and DOS then invents a garbage item))".

**Why no player sees it.** Nothing in the game writes an empty `.ITM`: both
in-game routes to owning nothing — a freshly rolled character, and one who
drops every item in play — render clean. It takes a file written from outside,
which is how our own converter reached it (#62 (A converted character who owns nothing gets a corrupt sheet, and DOS then invents a garbage item), fixed).

## N19. A shop purchase leaves the buyer's encumbrance high by what it just paid

**What the game does.** Curse of the Azure Bonds keeps each character's
encumbrance -- `money + Σ(item weight × quantity)`, in tenths of a pound, at
`0x187` of the DOS Curse record -- as a stored total that the engine
recomputes when something changes. Buying an item in a shop does the two
halves in the wrong order: it adds the item and recomputes the whole total,
and *then* takes the coins off the character. The number written out is the
sum as it stood before the price was paid, and it stays that way until the
next recompute.

**What it should do.** Take the money first, or recompute after taking it.
Everything else that moves money -- pooling it, taking it back out of the pool
-- keeps the total right.

**The evidence.** Four measurements in a driven DOS session, on MATHEW of the
Curse party from `#113 (Play DOS Curse far enough to save a party with
items)`, plus two an earlier session took:

| what was done, in order | money | Σ weight | stored | delta |
|---|---|---|---|---|
| before shopping | 300 | 0 | 300 | 0 |
| buy a battle axe, listed at 5 gp | 297 | 75 | 375 | **+3** |
| buy a dagger and four darts | 291 | 105 | 399 | **+3** |
| ready the axe, which forces a recompute | 291 | 105 | 396 | 0 |
| buy a composite long bow, listed at 100 gp | 288 | 185 | 476 | **+3** |
| pool 288 away, then take 1000 back | 1000 | 185 | 1188 | **+3** |
| buy two battle axes back to back | 994 | 335 | 1332 | **+3** |
| pool *every* coin away, then buy an axe | 0 | 410 | 410 | 0 |

Each stored number is the money term one debit behind: `375 = 300 + 75`,
`476 = 291 + 185`, `1332 = 997 + 335`. It is never cumulative, because each
purchase recomputes the whole sum and so overwrites the last purchase's error.
The last row is the proof of which debit is at fault: with the character's
coins all in the party pool the **pool** pays, his own money never moves, and
a freshly shopped character balances exactly.

The recovered Curse overlays agree -- `simeonpilgrim/coab`'s
`engine/ovr007.cs` has `shop_buy` call `PlayerAddItem`, which ends in
`reclac_player_values`, and subtract the money on the next statement.
CONFIRMED, seven purchases across two sessions.

**The same staleness, in Pool of Radiance, from a weight change.** The two
DOS Pool of Radiance characters who fail the identity are both carrying a
readied stack of darts, and the shortfall is exactly the darts the quantity
byte has and the cached display line does not: ASTRID stores 635 against 700,
`37 Darts` over a quantity of 50, and 13 x 5 = 65; GILES stores 787 against
807, `46 Darts` over 50, and 4 x 5 = 20. Exact on both, 2 of 2. The stored
total sides with the cached line, so throwing a dart decrements the quantity
and recomputes neither -- the same field going stale on a weight change rather
than a money one. It also settles which of the two disagreeing numbers is the
fresh one, which `goldbox/dos_layout.py`'s field note leaves open: the
quantity byte.

**Why no player sees it.** Every screen that draws encumbrance recomputes
first: `#113 (Play DOS Curse far enough to save a party with items)` watched
the sheet draw 396 while the file held 399. The cost is entirely ours -- a save
taken straight out of a shop is the only kind that fails the
`money + Σ(weight × quantity)` identity this project checks records with, and
it fails it by the coins of the last purchase, so a check on that identity has
to allow it and a converter must go on recomputing the field rather than
copying it. Measured for `#225 (A shopped Curse character's stored encumbrance
is three tenths above the sum)`; how much the shop takes, and why it is always
three, is bug 11 in [`../goldbox-bugs.md`](../goldbox-bugs.md).

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

## U4. The Ring of Fire Resistance does nothing on the C64

**What the game does.** Readying a magical item is what grants its effect:
`CAMP $10B5` reads the item's byte `+15`, and only when bit 7 is set does it
dispatch through `ECL65`'s power table to `SPELLE04 $ADD4`, which puts byte
`+14` -- the effect id -- into a free trait slot. The C64's RING OF FIRE
RESISTANCE template is `45 cd a7 42 00 00 00 00 01 00 00 88 13 00 00 00`:
`+14 = 0`, `+15 = $00`, and the protection bytes `+4`/`+5` a Ring of
Protection uses are zero too. So readying it grants nothing, and nothing
else in the engine reads an item for fire resistance. The engine *does*
implement the effect: id 61 is on the spell-damage and saving-throw check
lists, and its handler at `SPELLE01 $A9EE` zeroes fire-spell damage -- the
ring just never puts 61 anywhere (`docs/171-c64-trait-slots.md`).

**What the player sees.** A character wearing the ring takes full damage
from Fireball and Burning Hands, the same as one without it. The four
templates that do set the bit -- the Cloak of Displacement, the Gauntlets of
Ogre Power, the undead-slaying two-handed sword and the alignment-locked
Long Sword +3 -- work.

**Version.** Pool of Radiance, Commodore 64. PROBABLE: that the ring grants
no effect is CONFIRMED from the template and the READY gate, both quoted
above; that a wearer takes full damage has not been watched. **What would
promote it:** Fireball from a level-5 magic-user at a party member wearing
the ring, readied in camp, against one with 61 written into a trait slot by
`tools/traitask.py --stage`: the wearer takes the full roll, the 61-carrier
less. Burning Hands at level 1 cannot show it -- the handler never takes
one die below one point, and `work/issue252/fire9/` watched a 61-carrier
take exactly that.

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

## Rumours from the community forums

**None of these is ours and none of them may be promoted into
`../goldbox-bugs.md`.** That file is CONFIRMED-only, and CONFIRMED there means
*we* reproduced it — in the running game on this machine, or proved it from the
bytecode beyond argument. An unverified report by a stranger about a port we do
not own is the opposite of that. A rumour leaves this section only by being
independently reproduced here, and then it is logged as our own finding with
our own evidence, not as a citation.

Read them as leads. Most are cheap to test, several are about **the DOS or
Amiga build and not the C64**, and the distinction matters: three of the bugs
already in the front-door file are port-specific, and the one C64-specific
report below (`R8`, `R9`) comes from somebody who says so explicitly because
the rest of his thread had not been.

Source unless stated: [Gold Box games bugs](https://forums.goldbox.games/index.php?topic=2772.0),
posters Gwindor, Null Null, Amarande, PetrusOctavianus and Kirben, 2014–2015.
Raw capture in `work/forums/p2772.txt`. Summarised in our own words.

### Pool of Radiance

| # | claim | platform stated | to confirm |
|---|---|---|---|
| R1 | Using the thief Restal in the Cadorna Textile House to open **and re-seal** the treasure lock lets the loot be taken again: leave the Cadorna block, re-enter, revisit Restal, and the money and Gauntlets of Ogre Power are there again, indefinitely | none | Cheapest of the lot from the bytecode alone. `ECL02` is Cadorna; look for the treasure branch and whether its flag in `$4A00`-`$4AF8` is written before or after the re-seal path, and whether entry 4's re-entry compare skips the clear. No emulator needed. |
| R2 | Animate Dead can be cast on a **dead NPC**, who then joins the party as a zombie | none, video cited | Needs a live session: get an NPC killed, cast it. `SPELLE*` is where the target filter would be. |
| R3 | Animate Dead cast **in combat** may animate enemy combatants, who come back at full hit points and keep attacking you | none | Same session; read the target loop in the Animate Dead handler for a missing side check. |
| R4 | Podol Plaza cannot be cleared by camping and having rests interrupted — it needs **ten random encounters** | none | Directly checkable. `ECL12` is Podol Plaza; we already read the identical mechanism in the Slums, where `$4ABB` counts to **25** and latches 254. Find Podol's counterpart flag and read its threshold. If it is 10, the claim is exact. |
| R5 | The Buccaneer's Base captain can be fought — and looted — **twice**, "in some versions" | "some versions" | `ECL01`. Same shape as our bug 2: a cleared-flag that is written on one path and not another. |
| R6 | After Tyranthraxus, resting in some New Phlan areas (the training hall named) can still be stopped by the city watch; **if you fight them the shops stop giving commissions** | none | Two halves. The watch check is in `ECL00`/`ECL0B`; the commission ledger is the one `docs/103` reads. The second half — a permanent loss of the commission clerk — would be a real player-visible bug and is worth the work. |
| R7 | Tyranthraxus can be fought again if you return to his lair after killing him | none | `ECL07`. Our own note says `ECL07` writes ledger flag 20; check whether the encounter branch tests it. |
| R8 | **C64 only:** an infinite loop in combat if an enemy casts an offensive spell while the party is using **dust of disappearance** | **C64**, stated | The only C64-specific report on the forum, and therefore the most valuable one here. Reproducible in VICE: acquire the dust, ready it, and fight something that casts. If it hangs, it is ours to log properly. |
| R9 | **C64 only:** items get corrupted when using **gauntlets**, producing strange items | **C64**, stated | Same session. "Strange items" reads like an item-slot index running off the end of `ITEMNAMES` — the same failure mode as our own indices 62/63 gap. Testable from a save plus `goldbox/items.py` without the emulator if a corrupted specimen can be produced. |
| R10 | Paladins and rangers (only reachable by editing) get **no sweep attack**; level drain followed by restoration cycles the gender byte and awards 10,000,000 experience | DOS, via Gold Box Companion, [topic 1913](https://forums.goldbox.games/index.php?topic=1913.0) | Consistent with what we already hold — `docs/20` records that those two classes are named in the table and instantiated nowhere. Confirming it on the C64 needs `wish` to write a paladin and a restoration scroll; the drain path is `SPELLE02`/`SPELLE04`, which we have read. |

Kirben's framing is worth keeping: *"It would be worth mentioning which port(s)
that bugs occur in, as some bugs were often specific to one port."* Every row
above without a stated platform is most likely DOS or Apple II, because that is
what the thread's regulars played.

### Curse of the Azure Bonds

| # | claim | platform stated | to confirm |
|---|---|---|---|
| R11 | A programming error at the **Teshwave Ruins** traps the party in a couple of rooms; LOOK or SEARCH may get you out | none | Curse area **69** is one of three ids the forum says holds *shared* dungeon blocks — Hillsfar and Teshwave are built from one map plus party-movement events ([topic 1048](https://forums.goldbox.games/index.php?topic=1048.0)). A movement event with a wrong destination is exactly what would strand a party. Readable from Curse's `ECL` once we decode it. |
| R12 | A scroll of protection from dragon breath stayed active for the rest of the game | none | `docs/125` N7 already has effect expiry clearing one array of four. Same neighbourhood; check whether the scroll writes an effect slot the expiry loop does not cover. |
| R13 | A THAC0 of −1 prints as **255** on the character sheet, while combat behaves correctly | none | Almost certainly true and almost certainly the same on the C64: our THAC0 is stored biased as `60 - value` and the sheet prints the unbiased byte unsigned. One `wish` edit to a THAC0 past 60 and one screenshot settles it. Cosmetic — this belongs here even if confirmed. |
| R14 | SHARE hands out absurd jewelry totals inside the Shadowdale side dungeon, repeatably, surviving a restart, and not outside that dungeon | none, screenshots | Odd and specific. The poster's own guess is overflow from an over-encumbered character. Our `0x0C7` jewelry word is `u16le`; a signed/unsigned mix in the divide would do it. |
| R15 | The Wand of Magic Missiles in Zhentil Keep costs **14,464 gp**, apparently a 16-bit truncation of 80,000 | none | 80000 − 65536 = 14464 exactly. Arithmetically certain, and checkable from the Curse item tables on disk with `goldbox/items.py` and no emulator at all. **The cheapest confirmable claim in this section.** |
| R16 | Buying with more than 65,535 gp worth of platinum makes money evaporate | none | Same overflow, other side. Testable with an edited party. |
| R17 | Importing a character with exceptional strength from Pool of Radiance: the first time strength is magically modified in Curse, the **score itself becomes the exceptional number** | none | We have the import routine (`docs/116` §2.2) and both fields — `0x014` strength, `0x01A` exceptional. Readable from the bytecode. |
| R18 | The Girdle of the Dwarves on an imported fighter with a Manual-raised constitution of 19 produced "weird ability numbers" instead of 20 | none | Vague. Log it, do not chase it. |
| R19 | Re-entering the caves under Hap re-fights the salamanders | none | Same class as our bug 2. |

### Later titles

Kept because they are the same engine and the failure modes repeat, not because
we intend to test them. Platform is stated only where the poster stated it.

| # | game | claim |
|---|---|---|
| R20 | Silver Blades ← Curse | a character imported wearing strength-boosting items never has strength reset when they come off — a permanent 24. Fixed in Pools of Darkness, where a non-fighter can still end up at 18(00) |
| R21 | Silver Blades, **Amiga** | Cloaks of Displacement grant outright immunity to physical attacks |
| R22 | Silver Blades | resting always succeeds beside the large black-and-blue doors in the crevasses, which the cluebook says is impossible |
| R23 | Champions of Krynn | the front-gate troops at Gargath Keep must be fought again on every approach |
| R24 | Pools of Darkness | declining Vala, then meeting her again, puts **two** Valas in the party |
| R25 | Pools of Darkness | random encounters continue in Kalistes' Parlor after she is dead |
| R26 | Pools of Darkness | hidden loot in the beholder-attacked village regenerates on re-entry — unlimited arrows |
| R27 | Pools of Darkness | REPAIR sometimes decreases (rarely increases) **permanent** hit points |
| R28 | Pools of Darkness | Manshoon exists as a monster record and cannot be fought by normal means |
| R29 | Pools of Darkness | refusing to see Arcam after qualifying leaves you unable to leave the arena by the front door, re-triggering the fight every two steps |
| R30 | Pools of Darkness | Hold Monster works on dracoliches |
| R31 | Pools of Darkness | countermanding Gothmenes' summons *increases* the number of Pets of Kalistes while decreasing the other three types |
| R32 | Pools of Darkness | in the Palace of Gothmenes without the Crystal Ring, an encounter frightened off with the Horn or Talisman never clears while you stand on the square — repeatable experience |
| R33 | Pools of Darkness, **DOS** | the Ring of Lightning Immunity does not work; it does on the Amiga |
| R34 | Pools of Darkness | a freeze shortly after defeating Kalistes |
| R35 | Dark Queen of Krynn | falling down certain Tower of Flame shafts strands the party in a sealed room with no game-over; LOOK reports "You are on level 255" |
| R36 | Dark Queen of Krynn | a save state in which every step triggers the same black-dragon battle and no other event ever fires. Diagnosed live with ECL-Monitor: one flag checked at script address `$AE20` was 1 and the script wanted 0; clearing it restored the game ([topic 4581](https://forums.goldbox.games/index.php?topic=4581.0)) |
| R37 | Death Knights of Krynn | being hit by a Spectral Dragon in the final battle of Dave's Challenge can freeze the game |
| R38 | Death Knights of Krynn | Knights gain 3 hit points per level after name level where the manual says 2 — offered as the *cause* of R27 rather than a bug of its own |
| R39 | Krynn and Savage Frontier titles | Dispel Magic cures paralytic toxins (Kapak draconians, driders, snakes). Probably a design limitation rather than a defect |

Five of those — R23, R25, R26, R29 and R32 — are the same defect as our own bug
2, *Sokol Keep's dead elf comes back every time*: an encounter or a pickup whose
"already done" flag is not latched on every path out. **The forums never report
the Sokol Keep elf itself.** What they establish is that we found a habitual
Gold Box fault rather than a freak one, which is corroboration of the pattern
and not of the entry, and it stays worded that way. The DOS guide, added below,
*does* name Sokol Keep's dead elf guard — a second sighting of the entry itself
rather than of the pattern. By then we had already driven it in the emulator, so
it changes nothing; it is recorded because a corroboration that arrives after
the fact is still corroboration.

---

## Rumours from the DOS guide

Second source, same rules: **none of these may be promoted into
`../goldbox-bugs.md`** without our own reproduction. They come from Stephen
S. Lee's *Pool of Radiance: Exhaustive Game Information* v2.00, written for
**PC v1.3**, and are set out with their evidence in
[`128-guide-and-scripting.md`](128-guide-and-scripting.md).

These are worth more than the forum rumours for one specific reason: **the ECL
bytecode is one artefact shared by every port**, so a defect the guide locates
in a *script* or in the *VM* is almost certainly in our bytes too, and most of
them are checkable statically against our own exhaustive decode with no
emulator at all.

| # | claim | kind | to confirm |
|---|---|---|---|
| R40 | `$23 SURPRISE` applies its four modifiers to the wrong sides. Harmless while the modifiers are zero, which is the usual case | engine | Read `DUNGEON`'s `$23` handler and check which side each modifier lands on. Static, no emulator |
| R41 | `$22 PARTYSURPRISE` does nothing special for a ranger and mis-sets one of its two variables | engine | Same handler pass |
| R42 | `$28 ROB` never restores the item-loss chance while walking one character's inventory, so putting heavy items first sharply reduces theft — and it steals **equipped** items | engine | Same. The exploit half is testable in play: order a character's inventory and get robbed |
| R43 | `$34 ECLCLOCK` advances the clock by an uninitialised byte rather than by its operand; fixed in *Curse*. Used once in the whole game | engine | Read the handler; the one call site is in our decode. A watchpoint on the clock digits at `$49C6`-`$49CB` would settle it in a minute |
| R44 | `$3B SPELL` never does anything; fixed in *Curse*. Used once | engine | Same shape as R43 |
| R45 | Podol Plaza's buccaneer can be looted twice; the Cadorna family treasure can be opened twice; Valhingen Graveyard's treasures at locations 12 and 24 are transposed; Stojanow Gate's alarm starts nothing | script | All four are static checks against `ECL12`, `ECL02`, `ECL0A` and `ECL09`. The Cadorna one is R1 from the forums arriving by a second route, which raises it above the rest |
| R46 | Going south from the Wealthy Area at (4,15) crashes; fleeing the bugbear patrol after the tower guards crashes | script | Two fasttravels and two steps. Worth trying on the C64 precisely because a crash is port-sensitive |
| R47 | **Exploit.** A targeted damage spell can raise the dead: a dead character has 0 hit points, and a spell doing under 10 leaves them dying rather than dead. Still present in *Curse*, gone in *Silver Blades* | engine | Read the damage handler's death threshold. `$2E DAMAGE` is in our decode |
| R48 | **Exploit.** Items can be duplicated by saving and reloading in the training hall | engine | Area 11, which a fasttravel cannot enter — so this one needs a walked session |
| R49 | **Exploit.** Constitution 22, or 0, gives out-of-range hit points per level | engine | `wish` can write either score; one train and one look at the sheet |
| R50 | The `bec de corbin` is flagged **slashing** in `ITEMS` (`+7` = 0) where AD&D makes it bashing or piercing; the `military fork`, `ranseur` and `trident` are flagged slashing too | data | **Half done.** We read the bytes ourselves: item types 4, 13, 29 and 39 all hold `+7` = 0, and the only values the whole table takes are 0, 1 and 128. What is third-party is the AD&D categorisation, and it is not only those four — `partisan` (25) and `spetum` (32) read 0 as well, and both are piercing weapons in the book. Somebody who knows the 1e weapon table should say how many of the 98 zero entries are actually wrong |
| R51 | **DOS defect, and the C64 is the better of the two: the DOS dagger cannot be thrown.** | data | **Confirmed by measurement, both files.** DOS `ITEMS` and C64 `ITEMS` are **126 of 128 16-byte records byte-identical**, and the DOS file even carries the same `$7600` load address. The two that differ are exactly the thrown weapons: item type 8 (dagger) reads rate of fire 2, range 4 and the thrown flag on the C64 against 0, 1 and no thrown flag on DOS, and item type 9 (dart) is multi-fire ranged on the C64 and thrown-only on DOS. The guide's author noticed the DOS dagger independently. Nothing to reproduce; what is left is deciding whether a defect in a port we do not own belongs on the front-door list at all |

**A clean negative, and it is worth as much as the positives.** The DOS build
has a cheat mode started with the command-line argument `STING` — Ctrl-C to
quit, Alt-X to win a combat, `J` for free training, copy protection bypassed.
**There is no C64 counterpart.** The literal `STING` appears on all eight `POOL`
disks and **every occurrence is inside the word `CASTING`**. Checked, and
recorded so nobody searches for it twice.

**One free find while checking R50.** The `bec de corbin` — a ten-pound polearm
— carries `+14` = 20, the **thrown** flag with the strength-bonus bit, the same
value as the dagger, hand axe and spear. Nobody has flagged that, on either
port, and it is one `wish` edit and one throw away from being settled.

Everything else from the two passes — the playtester mode, the DOS area tables,
the item record, the tooling, the format spreadsheets and the ECL semantics — is
in [`126-forum-findings.md`](126-forum-findings.md),
[`127-community-formats.md`](127-community-formats.md) and
[`128-guide-and-scripting.md`](128-guide-and-scripting.md).
