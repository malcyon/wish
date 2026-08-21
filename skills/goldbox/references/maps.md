# The map files

## The format

A `GEO` file is **four 256-byte planes over a 16×16 grid**, not an array of
per-square records. Every square is indexed `x + (y << 4)` — row-major, y
increasing southward, origin top-left.

| Plane | Offset | Content |
|---|---|---|
| 0 | `$000` | high nibble = wall art **north**, low nibble = **east** |
| 1 | `$100` | high nibble = **south**, low nibble = **west** |
| 2 | `$200` | square attributes; bit 7 = roofed / indoor, bits 0-6 a script id |
| 3 | `$300` | passability, two bits per direction: N = 0-1, E = 2-3, S = 4-5, W = 6-7 |

A wall nibble of 0 means no wall; otherwise `wallset = (v-1)/5` and
`slice = (v-1)%5` index the wall-definition graphics.

| Passability value | Meaning |
|---|---|
| 0 | solid |
| 1 | passable — an opening or an open door |
| 2 | locked door |
| 3 | wizard-locked door |

On the C64 the file is a PRG loading at `$0400` with **no header in the
payload**: the planes land at `$000`/`$100`/`$200`/`$300` unadjusted. The DOS
block of the same data has a two-byte prefix; the C64 file does not.

## The mistake five readings made

**A wall and a barrier are two independent fields.** Every failed reading
assumed one field per edge, so that "there is a wall here" and "you cannot walk
through here" were the same bit. They are not, and they live in different
planes.

The passability field is **only consulted where there is wall art**. An edge
with no art is passable whatever its bits say. So:

* **for walking**, use passability;
* **for seeing**, use the wall art. Sight passes only through an edge with no
  art at all. Using passability for sight lifts the fog off rooms behind doors
  the party has never opened — measured at 7.27 squares revealed per stand
  against the correct 5.49.

Locked and wizard-locked doors are a strict subset of "has art", so they block
sight too. Barrier-based sight rules fix essentially nothing: across 29 files
there are 130 locked and 14 wizard-locked edges against roughly thirty thousand.
What over-reveals is ordinary doors.

## Reciprocity: the parse checks itself

The east edge of a square is the west edge of its neighbour. So a correct parse
makes adjacent squares agree about their shared edge, and **this needs no ground
truth at all**.

| | Score |
|---|---|
| correct assignment, Pool of Radiance, 30 files | 28540/28800 = 99.1% |
| correct assignment, Curse, 16 files | 15114/15360 = 98.4% |
| best of the other 23 nibble-to-direction permutations | 0.845 against 0.652 |
| any of the five failed readings | ~0.3, which is chance |

**Compute reciprocity on every file, every time.** A mis-parsed file, a wrong
plane assignment or a corrupt read shows up here first. A per-file inventory —
walls, doors, locked, indoor, reciprocity — is worth generating and keeping.

`indoor` separates the kinds of area at a glance: 256/256 is entirely under a
roof (a dungeon), 0/256 entirely open (wilderness), and mid-range values are
town blocks.

## Anchoring: which file is which area

A decoded map is a floor plan of nowhere until it is anchored, and **this never
transfers between titles**. Three routes, best first:

1. **The area id in the save.** Once found (see `save-layout.md`), it names the
   file outright. Make a boundary pair to find it.
2. **The resident copy in RAM.** In a running game the map the engine is drawing
   is resident and, in Pool of Radiance, **not relocated at all** — the file
   loads at `$0400`, which is screen memory at boot, but in the world the screen
   has moved to `$CC00`, so the page is free and the loader leaves the map there.
   Byte-match RAM against the disk copies and the answer is exact.
3. **Match against transcribed maps.** Transcribe a drawn map into a 16×16 wall
   grid and score every file against every area. Report the **next-best score**
   alongside the best: nine Phlan blocks matched their files at φ 0.733-0.992
   with the highest score anywhere else in the 261-cell matrix at 0.316. The gap
   is the result; a high score alone is not.

Two independent anchors inside one map are worth having. The alignment was
confirmed by an inn glyph on the drawn map sitting exactly where a save put the
party, and by that square's neighbour carrying a door flag on the correct edge —
with a ±1 or ±2 shift dropping the score from 0.705 to 0.146.

**A blind layout search can rediscover the format.** An exhaustive search over
`unit[base + x*sx + y*sy]` — unit ∈ {byte, high nibble, low nibble}, `sx`, `sy`
∈ ±{1…128}, base 0-1023, 29 files, 1,029,312 layouts — scored against a
transcribed map and returned the correct assignment 18 standard deviations above
the population mean. Expensive, but it works when you have one transcribed map
and nothing else.

## The attribute plane is a script id

Bits 0-6 of plane `$200` are a **per-square script id**. The area's own script
does `AND <mask>, ATTR, [v]` then `ONGOTO idx=[v]`, so the id indexes a jump
table into the area's event script.

**The mask is the area's, not yours.** In Pool of Radiance eighteen scripts mask
`$7F`, the dungeon-floor family masks `$1F`, and one masks `$3F`. Only in the
`$1F` family do the freed bits mean anything, and there they control wandering
monsters: bit 6 suppresses a random encounter on that square and bit 5 halves
the rate. Elsewhere those bits are part of the id. **Read them only when you
know the area's mask.**

Ids are about 63% single-square triggers and 37% multi-square regions —
shopfronts and rooms — so both readings are true, per id.

## The script VM

The event scripts are bytecode for the Gold Box VM, and the VM transfers even
where the addresses do not: opcode table, operand encoding, a 6-bit packed
string format, and a variable window in which one slot is the attribute-plane
byte of the party's square. In C64 Pool of Radiance the block is based at
`$9900` where DOS uses `$8000`; five entry-point words sit in the first `$14`
bytes.

**The closing proof is a prediction that lands.** Take a square you can stand
on, read its attribute byte, mask it, index the area script's jump table, follow
the target, and read the string it prints. If that is the message the game
actually prints when you step there, the map decode, the mask, the jump table
and the string unpacker are all confirmed at once.

14 of 22 map/script pairs have a jump table exactly `max id + 1` long, covering
`0…max` with nothing spare — which independently confirms the pairing, as does
the scripts' own text naming their areas.
