# The combat view

**Status: built**, on the Automapper tab. When the game enters combat the area
map becomes the combat map, and when the fight ends it changes back.

Modelled on Gold Box Companion's combat view — party green, enemies red, and a
tooltip on a combatant giving its full statistics.

---

## Why it belongs in the automapper rather than beside it

Both answer the same question — *where is everything?* — and only one of them is
ever true at a time. Two tabs would mean the useful one is always the one you
are not looking at, and you would spend every fight clicking between them.

So the Automapper tab holds a `QStackedWidget` of two canvases and swaps them.
The tab keeps its name; the status line says which map is showing and how the
fight stands.

It keeps the visual language too: the same graph paper, the same ink, the same
line art. A player should not feel they have changed program because a fight
started.

---

## Where everything is

Pool of Radiance's, which is what the view itself reads. The other two C64
titles are the next section.

| what | where |
|---|---|
| mode | `$6E11` = 2 |
| the map | `$8C00`, one byte a square — pointer at `$0602`/`$0603` |
| row stride | `$0607` |
| maximum square x, y | `$0612`, `$0613` |
| camera origin | `$037E`, `$037F` — top-left of the 7 x 7 window |
| where they stand | `$8B00 + i*4` = `x, y, slot*4 \| pose, 0`; `$FF $FF` = off the map |
| who is fighting | `$8300 + i*32`, the roster block continued past `$83FF` |
| whose record | roster `+0x0D` names one of the twelve record slots at `$4D00` |
| initiative | `$A380 + i`; the round ends when all 64 are zero |
| how a combatant is | roster `+0x00`, record `0x100`: bit 7 means out of the fight, the low three bits name the state |
| how the fight ended | `$6DC7` — `$00`/`$01` won, `$80` lost, `$81` ran away |

`i` is 0–63: **0–7 the party in save-slot order, 8 upward the monsters** — the
same encoding the effects owner byte uses. **Monsters share one record per
type**: eight `GOBLIN GUARD`s in a slums encounter all named record slot 8,
which is what makes twelve slots enough.

**Bit 7 of a square means a combatant stands there**; mask `& $7F` for the
terrain, where 0 is floor. The view checks the two against each other.

**The shape is read at runtime, never hard-coded.** `SQRPACI01` carries a stride
of 56 and bounds 55 x 25; `SQRPACI00` a stride of 20 and bounds 17 x 35. The
write-up behind those numbers, `work/reports/combat-terrain.md`, is lost.

The tooltip's own fields come off the character record, which is what a monster
is: name `0x000`, hit dice `0x0A0`, armour class `0x0E1` (as `60 - AC`),
movement `0x09F`, attacks `0x0D9`–`0x0E0`, experience `0x0F7`–`0x0F9`, traits
`0x0AD`–`0x0B6`, saving throws `0x09A`–`0x09E`.

**AC, THAC0 and current hit points come from the roster block, not the record.**
`0x0E1` is the unarmoured base — AC 10 for every player character — and the
roster carries what they are actually fighting at.

---

## The same fight in Curse and Silver Blades

Four addresses move, two do not, and **the two later titles agree on every one
of them**. Each was derived from that title's own binary and then read off a
running Curse on 2026-09-08, pool slot 2 -- `#334 (The session driver
cannot fight in Curse or Silver Blades, and says the party is not in a
fight while it is standing on the combat floor)`, `work/issue334/run5`;
`tools/latercombat.py` is the table and `tools/session.py` reads a fight
through it.

| what | Pool of Radiance | Curse and Silver Blades |
|---|---|---|
| mode | `$6E11` | **`$7F11`** |
| the parameter block | `$0600` | `$0600` — the same address |
| camera origin | `$037E`/`$037F` | `$037E`/`$037F` — the same |
| the map | `$8C00` | **`$6F00`** |
| the glyph table after it | `$91B0` | **`$74B0`** |
| where they stand | `$8B00 + i*4` | **`$CB00 + i*4`** |
| who is fighting | `$8300 + i*32` | **`$6700 + i*32`** |
| whose record | twelve slots at `$4D00` | **`$4F00`** |
| initiative | `$A380 + i` | **`$92E8 + i`** |
| how the fight ended | `$6DC7` | **`$7EC7`** |

Everything else on this page — the stride, the 56 x 26 arena, `$FF $FF` for
off the map, bit 7 of a square, one record shared by every monster of a type —
holds unchanged. The two arenas are the same size.

**The parameter block is not relocated, and that is a reading rather than a
convenience.** `GDRIVE00`, the square engine that draws the arena, names the
same twenty absolute addresses `$0600`-`$061B` and the same camera in the same
order and at the same relative code positions in all three binaries. Its
header claims `$3000` in Curse and `$4000` in Silver Blades and it runs at
`$C000` in both, like Pool of Radiance's.

**Where the block's contents come from is the one structural difference.**
Pool of Radiance loads them off a `SQRPACI<nn>` file. Curse and Silver Blades
ship no such file — `docs/120-curse-testing.md` records that — and their
`COM.PREP` writes the whole block as immediate constants instead, Curse at
`$1436`-`$147E` and Silver Blades at `$14AC`-`$14F4`, identical value for
value. A running Curse read `b0 74 00 6f 00 cb 40 80 80 80 01 80 c0 c0 c0 c0
31 13 37 19` at `$0600` on the combat floor, which is those constants exactly.
Nothing about the *reading* changes, because the block is read at run time in
both cases.

**`$1100` is the offset between the two engines' work areas**, and every pair
found so far obeys it: `$6E11` → `$7F11`, `$6DC7` → `$7EC7`, `$6D56` →
`$7E56`, `$6DB1` → `$7EB1`. It is a pattern rather than a proof, so an address
derived from it alone is a guess until the instruction naming it has been
read.

---

## What it draws

* **Party green, enemies red**, filled squares on the graph-paper ground, with
  **a health bar along the bottom of each occupied square** in place of a
  number or a letter (`#345 (Draw a letter in each combat-map square saying
  what is standing there, instead of the index the backend counts with)`).
* **Terrain** as wall or not wall, and nothing finer. The glyphs at `$91B0` say
  what each code looks like on the C64's own screen, and until they are checked
  against, a map that invented a diagonal would be worse than one that draws a
  block.
* **The 7 x 7 window the game itself is showing**, dashed, so the two views can
  be read against each other.
* **Whoever may still act** outlined — a non-zero initiative byte.
* **Dead or fled combatants dimmed**, not removed. One that leaves the map keeps
  the last square the previous poll saw it on, and is never invented: with
  nothing remembered there is nothing to draw.

  The states behind that word are readable and the view does not yet
  distinguish them: `LIBRARY $38BE` masks roster `+0x00` with 7 and draws
  1 `OK`, 2 `GONE`, 3 `DEAD`, 4 `DYING`, 5 `UNCONSIOUS` (the game's spelling),
  6 `RUNNING`, 7 `STONED`, with bit 7 on top meaning out of the fight — so
  `$84` is dying and `$85` unconscious. `docs/110-combat-log.md` has the
  table and where it was read.
* Only the part of the map the fight uses. 56 x 26 is 1456 squares and both maps
  seen put the action in a corner, so the box covers the combatants and the
  camera window, padded, and the cell shrinks to fit rather than the window
  growing to 1900 pixels.

## The tooltip

Hovering a combatant gives the record. Two rules. **Only what is decoded** — a
field we cannot read is left out rather than guessed at. And **the trait codes
we know are named and the rest show their number**, so an unnamed code is
visibly unnamed rather than silently dropped; that is also how new codes get
noticed. The table is `goldbox/traits.py`, shared with the character sheet.

```
15. ORC  (28,15)
5 / 5 hp
AC 6   THAC0 19   move 9
1 hit dice
1 attack per round (1d8)
saves 14 / 15 / 16 / 17 / 17  (paralysis, petrification, wands, breath, spell)
15 experience
```

Read live off an orc ambush in the slums. The *Monster Manual* gives an orc AC
6, 1 hit die, one weapon attack, and 10 + 1 per hit point of experience — 15 at
five hit points. Four independent numbers, all right.

The fill byte 255 is not a trait and is dropped; the character sheet still shows
it, because there the point is the whole ten slots.

## Where the code is

| file | what |
|---|---|
| `automap/combat.py` | reads the fight and yields its geometry. No Qt |
| `automap/window.py` | `CombatCanvas`, and the swap in `AutomapWindow.poll_battle` |
| `goldbox/monster.py` | attacks and the experience award, off any record |
| `goldbox/traits.py` | the trait codes, named where we know them |

`goldbox/` stays transport-free and `editor/` stays emulator-free; reads go through
the `Target` protocol, so the Commodore 64 Ultimate backend gets this for free.

**Two bursts a poll**: the mode byte, the parameter block and the camera, then
the map, the roster, the positions, the initiative bytes and the twelve record
slots. The cost of a read is the round trip and not the bytes.

**Polled once a second in the world and every tick in a fight.** The area map is
not polled at all during a fight — the party is not moving through the world,
and its explored squares sit untouched until the fight ends.

---

## What is still open

* **Where the terrain bytes come from.** `$8C00` is `LIBRARY`'s file staging
  buffer, so the map is most likely loaded and decompressed into it at fight
  setup, but no file has been matched to it and neither map appears verbatim on
  any disk. `SQRDATA` is ruled out — never loaded in either fight. A store
  checkpoint on `$8C00`-`$91AF` armed *while a fight starts* would name the
  builder in one hit. Cosmetic: it changes nothing the view draws.
* **What each terrain code looks like.** The glyphs are at
  `$91B0 + (t + $30) * 18`, nine screen codes then nine colours, so they can be
  rendered rather than guessed at.
* **Pose**, the low two bits of `$8B00 + i*4 + 2`. Read and carried, not drawn.

## Verification

Against `tests/fixtures/combat-arena.bin`, a real training-hall duel trimmed to
the seven ranges the view reads:

* the shape, the camera, both combatants, their records and their initiative
  bytes decode, and **bit 7 of the map agrees exactly with `$8B00`**;
* with the mode byte anything but 2, **no combat memory is read at all** —
  three addresses, and none of them `$8B00`;
* a parameter block that cannot be one is refused, including the real bytes
  `$0600` holds in the world;
* the canvas swaps on the flag and back, with the area map's explored squares
  unchanged.

And live: VICE booted, `work/drive/SLUMS.D64` loaded, three steps out of (15, 4)
into an orc ambush. `$6E11` read 1 and `read_battle` returned None; three steps
later it read 2 and returned six party at 0-5 and **eight orcs from 8, all
sharing record slot 8** — one record per type, exercised for the first time.

Still wanted: a tooltip checked against the game's own `VIEW` command for the
same creature, which is the only check the game itself can give.
