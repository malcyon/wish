# What DOS Pool of Radiance reads to grant a thief his abilities

`#560 (Does Pool of Radiance grant thief abilities off class_bits, or off the
level array and skill bytes?)` asked which byte the engine tests when it decides
whether a character backstabs, may pick a lock, or contributes a find-traps
roll.

**In one line: none of them is `class_bits`. Backstab and the Pick option are
gated on `class_levels[thief]` at record `0x09C`; the rolls are made against the
skill bytes at `0x078` and `0x079`; and `class_bits` at `0x0B0` is read in
exactly three places in the whole overlay, all three asking whether a character
may use an item.**

So the edited `SILAS` the issue describes — `class_bits = 8`, fighter alone,
with thief level 1 in the array and a full skill row — plays as a thief for
every purpose measured here. CONFIRMED from the instructions below; what has
not been done is watching it happen in the running game.

Read it again with `tools/dos/dosthiefgate.py`, which finds each site by its
structure rather than by the addresses printed here. Record offsets are
`goldbox/dos_port.py`'s: the per-class level array at `0x096` indexed by class
number (thief is 6, so `0x09C`), the eight thief skills at `0x077`-`0x07E`,
`class_bits` at `0x0B0`.

| what | gated on | rolled against | where |
|---|---|---|---|
| Backstab, the ×N multiplier | `class_levels[thief]` > 0 | — | `GAME.OVR:0x14DB4`, applied at `0x129F0` |
| Backstab, the to-hit and the message | the same predicate | — | `0x13DA8`, `0x13E4B` |
| `Pick` on the locked-door menu | any party member's `class_levels[thief]` > 0 | `thief_open_locks` (`0x078`) | `0x16901`, called at `0x174A9`; roll at `0x16BE6` |
| `Knock` on the same menu | any party member's `class_levels[mage]` > 0 | — | `0x16901`, called at `0x17622` |
| Find traps | nothing | `thief_find_traps` (`0x079`) | `0x2291` |
| Ready or use an item | `class_bits` (`0x0B0`) | — | `0x0C0BA`, `0x0C170`, `0x22664` |

## Backstab

`GAME.OVR:0x14D6F` is the predicate, a four-argument far routine returning a
boolean in `AL`. Its first test is the one that settles the issue:

```
014db1  les di, ptr [bp + 0xa]              ; the attacker's record
014db4  cmp byte ptr es:[di + 0x9c], 0
014dba  jle 0x14df2                         ; thief level 0 -> not a backstab
```

The rest of the routine is weapon and position: the item far pointer at record
`0x0CC` must be absent or of a type in {7, 8, 0x23, 0x24, 0x25}, the one at
`0x0D4` absent or type 0x32, the target's figure must have more than one of
something at `+0x0F`, and a direction the engine computes must equal the
target's facing at `+0x09`. Item type is offset `0x02E` of the 63-byte item
record, so those five numbers are item type indices; which weapons they are has
not been looked up.

Three sites consult it, and only those three — `0x129E6`, `0x13DA8`, `0x13E4B`.
The first is the damage multiplier:

```
0129e6  call 0x14d6f                        ; backstab?
0129eb  je   0x12a08
0129f0  mov al, byte ptr es:[di + 0x9c]     ; thief level again
0129f6  shr ax, 1 / shr ax, 1
0129fa  inc ax / inc ax                     ; (level >> 2) + 2
012a03  mul dx                              ; rolled damage x that
```

**So the multiplier is `(thief level div 4) + 2`, and its bands begin at levels
4, 8 and 12** — ×2 for 1-3, ×3 for 4-7, ×4 for 8-11. The published AD&D 1st
edition table puts the steps a level later, at 5, 9 and 13, so a level-4 thief
in this game backstabs for triple rather than double damage. CONFIRMED as the
arithmetic the engine does; **PROBABLE as a deviation from the rules**, because
the comparison rests on a rule table nobody re-read for this note, and Pool of
Radiance's own manual is not something this project holds. Settling it needs
only the printed table, not the game.

The other two sites are the to-hit adjustment at `0x13DAF` (the backstab branch
takes the defender's `0x112` less two instead of the `0x111` the ordinary branch
reads) and the message selector at `0x13E52`, which sets 2 and makes the
attack-message routine at `0x12AF4` print `-Backstabs-` instead of `Attacks`.

## Pick Locks

The locked-door menu is built at `0x17480` out of four length-prefixed strings
in the overlay — `Bash`, ` Pick`, ` Knock`, ` Exit` — each appended only if its
own condition holds. `Pick`'s condition is a call:

```
0174a5  mov al, 6                           ; class number 6 = thief
0174a9  call 0x16901
0174ac  or al, al
0174ae  je 0x174d8                          ; no thief -> no " Pick" entry
```

`0x16901` walks the party list from `[0x5D96]`, following each record's next
pointer at `0x104`, and answers whether any member has a non-zero level in the
slot it was given:

```
016926  mov al, byte ptr [bp + 6]           ; the class number
01692a  les di, ptr [bp - 5]                ; this member's record
01692d  add di, ax
01692f  cmp byte ptr es:[di + 0x96], 0      ; class_levels[n]
016935  jle 0x1693b
016937  mov byte ptr [bp - 6], 1            ; yes
```

Three callers, all in the two door menus: class 6 at `0x174A9` and `0x175E8`,
class 5 at `0x17622`, which is `Knock` asking for a magic-user.

Pressing `P` calls `0x16BAA`, which walks the same list and rolls for each
member with no class test whatever:

```
016bdb  mov al, 0x64 / push ax              ; 100 sides
016bde  lcall 0xb0, 0x48                    ; the die roller -> al
016be6  cmp al, byte ptr es:[di + 0x78]     ; thief_open_locks
016bea  ja  0x16bfb                         ; rolled over it: this one fails
016bef  cmp byte ptr es:[di + 0x10c], 0     ; status Okay
016bf7  mov byte ptr [bp - 6], 1            ; opened
```

The roll is compared unsigned, and the skill byte is signed in our tables
(`_I8`, because a halfling's read-languages is -5 on the C64). Nothing in the
game writes a negative Open Locks, but a hand-edited `0xFB` there would read as
251 and open every lock. Untested; the experiment is to stage `0xFB` at `0x078`
and press `P` on a locked door.

`Bash` next door at `0x1695F` is the strength check — it reads `0x010` and
`0x016` and rolls a d6 against the 18/91-00 rows — and needs no class at all.

## Find Traps

**There is no Find Traps command, and nothing in either binary rolls against
record `0x079`.** `SEARCH` on the dungeon bar is a mode toggle and nothing else:
at `0x17131` the `S` key flips bit 0 of a word at `+0x594` of the block at
`[0x49D6]`, and the only other reader of that bit, at `0x16E99`, uses it to
charge the party more game time per step.

What does read `0x079` is one arm of the routine at `0x0217B`, which answers the
ECL VM when a script reads a synthesised byte of the resident character record:

```
00227e  cmp ax, 0x6ba7
002281  jne 0x22f3
002291  mov al, byte ptr es:[di + 0x79]     ; thief_find_traps, each member
...     min, max, sum, then sum / count
0022ec  push bp / call 0x211d               ; hand the four back to the VM
```

`$6BA7` is `$6B00 + 0xA7`, and C64 record `0x0A7` is `thief_find_traps`
(`goldbox/layout.py`) — so **the scripts address a party member by the C64's
record offsets and the DOS engine translates**, which `docs/163-dos-vm-address-map.md`
already says of the `$6B00`-`$6D43` window and which this is an independent
check on. The neighbouring arm compares `$6C1B` and reads DOS `0x11C`, the
same relation with the combat tail's one-byte widening taken off.

So a trap is found by an ECL script asking for the party's find-traps
percentages and doing what it likes with them. Which scripts ask, and whether
they use the maximum or the average, is not read here.

## What `class_bits` is for

Five instructions in the overlay touch `0x0B0`, and none is in combat, on a
door, or in the search path.

| site | what it does |
|---|---|
| `0x0C0BA`, `0x0C170`, `0x22664` | `and al, es:[di+0xB0]` against a mask fetched from a table at `DS:0x558F` indexed by the item's type, then branch. `0x22664` goes on to write the item's `readied` byte at `0x034` |
| `0x1A650` | `mov es:[di+0xB0], 0` — the rebuild begins |
| `0x1A6D9` | `add es:[di+0xB0], al`, once per class slot whose level is non-zero, `al` from an eight-byte table at `DS:0x5D6` |

The rebuild is the whole of `class_bits`' provenance: the routine at `0x19EEB`
zeroes the byte, loops `i` from 0 to 7, and for every `class_levels[i] > 0`
accumulates that class's bit. **`class_bits` is derived from the level array,
not the other way round**, which is why nothing else needs to read it.

`0x19EEB` has one caller, `0x19CD7`, inside the unit's public entry `0x19AE0`,
and that entry has one far caller in the overlay, `0x03B90`, reached when the
first item of a menu is chosen — `CREATE NEW CHARACTER`. **So a record's
`class_bits` is not recomputed when a saved game is loaded**: PROBABLE, on the
call graph alone. What would settle it: a `BPM` on the live record's `0x0B0`
under DOSBox-X (`tools/dos/dosslotwatch.py` arms exactly this) across
`LOAD SAVED GAME` with a record staged `class_bits = 8` and thief level 1, and
reading the byte afterwards. If it still reads 8, the engine leaves it alone.

## Negative results

* **No roll anywhere against `0x077`, `0x07A`-`0x07E`.** A linear sweep of both
  binaries for a memory operand at those displacements finds only data
  coincidences; pick pockets, move silently, hide in shadows, hear noise, climb
  walls and read languages are written by the table builder and displayed, and
  the engine never rolls them itself. They are presumably the ECL scripts' to
  ask for, like find traps.
* **The resident `START.EXE` never touches `0x09C` or `0x0B0`.** Expanded with
  `tools/dos/unexepack.py` and swept the same way: zero sites each. All of this
  logic is in `GAME.OVR`.
* **The character sheet was not the route.** `docs/117-save-conversion.md` notes
  that Curse prints the thief numbers only for a thief, which suggested the
  display might be the gate. On Pool of Radiance it is not: the display is a
  separate question from any of the four above, and none of them consults it.

## The other reading the level array drives

Two more routines are indexed by the same array and are worth knowing about when
reading an edited record:

* `0x2AA87` recomputes the eight skill bytes when `class_levels[thief] > 0`, out
  of a table at `DS:0x3CF3` indexed by thief level and a race adjustment at
  `DS:0x3D3B` indexed by record `0x02E`. Four callers; whether any is on the
  load path is not read.
* `0x28F5A` rolls the hit die at a level gain — d4 for a non-zero `0x09B`
  (magic-user), d6 for `0x096` (cleric) **or** `0x09C` (thief), d8 for `0x098`
  (fighter). Again the array, again not `class_bits`.

## Two fields this settled in passing

* **Record `0x104`/`0x106` is the party list's next pointer.** Every party walk
  read here — `0x16901`, `0x16BAA`, `0x2291`'s aggregate — ends by loading
  `es:[di+0x104]` and `es:[di+0x106]` into the cursor, and the head is the far
  pointer at `[0x5D96]`. `goldbox/dos_port.py` has `0x104` as `heap_104`,
  "unnamed @0x104 (LIVE)", which is right about it being live and can now say
  what it is.
* **`class_bits` has exactly one writer**, agreeing with
  `docs/209-the-regained-dual-class-on-dos.md`'s count of one clearing site for
  Pool of Radiance, reached independently here.
