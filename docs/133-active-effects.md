# Active effects and traits

**Built.** The character sheet and the save header show separate lists because
a trait persists on one character while an active effect belongs to the saved
party and can expire. `wish/window.ui` carries both panels;
`editor/window.py` fills them.

| panel | records read | reader | write state |
|---|---|---|---|
| `Character Traits` | Ten bytes at record `0x0AD`–`0x0B6`, for the selected character | `editor/effects.py`, using `goldbox/traits.py` | Add and Remove write a selected trait; an untouched block is written back unchanged. |
| The untitled active-effects panel beside the roster | Four 64-slot arrays in `SAVEDGAME0`: id, owner, duration, magnitude | `editor/activeeffects.py`, using `goldbox/effects.py` | Read-only. A `.chr` export or roster disk has no save image, so the panel is hidden. |

## Character Traits

**CONFIRMED:** The `Character Traits` table always shows ten slots. `Add…`
puts a picked id in the first free slot; `Remove` clears the selected slot and
compacts the block. A trailing `255` remains the fill byte in slot 9, not a
trait. The picker and warnings name uncertainty without refusing the write.

**CONFIRMED:** `goldbox.traits.for_game()` supplies the title-specific id table
and confidence grade. Pool of Radiance and Curse share the base table; Secret
of the Silver Blades has its own meanings for some ids.

**CONFIRMED:** A trait Wish wrote through its normal save path survived four
cold boots and the game's own save, was applied by the game, and changed the
measured fire damage. The test plan's `VIEW` step was refuted: Pool of
Radiance never lists a trait for any character. [#417 (Prove the game applies a
trait Wish wrote, so WISH_EXPERIMENTAL_TRAITS can come off)](https://github.com/malcyon/wish/issues/417)
has the runs.

## Active effects

**CONFIRMED:** The save-wide panel has no title. Its approved columns are
`Party Effect` and `Target`; party-wide effects read `Entire Party`, and an
effect whose owner cannot be named reads `Unknown`. It shows one row for each
non-zero id and has no duration column.

**CONFIRMED:** `goldbox.effects.active_effects()` reads the four parallel
arrays by slot and ignores a slot whose id is zero. Expiry clears that id but
can leave the other three bytes behind, so a non-zero duration or magnitude is
not an active effect by itself. `editor/activeeffects.py` calls no effect
writer or clearer.

**CONFIRMED:** The spell-effect table has 67 records and is keyed 1–67 by
one-based record position. It provides the duration data for an id; it does not
make that duration safe to show or edit.

## The duration byte

**CONFIRMED:** Bits 0–5 are a count and bits 6–7 select the unit. The four
units are one minute, ten minutes, one hour and one day, and a count loses one
each time the clock byte one place coarser than its own unit ticks.

| bits 6–7 | unit | what advances it | grade |
|---|---|---|---|
| `00` | one minute — one dungeon step, one combat round | every minute of the clock | CONFIRMED, in the running game and from the bytecode |
| `01` | ten minutes, an AD&D turn | the minute-units digit `$49C7` wrapping | CONFIRMED, in the running game and from the bytecode |
| `10` | one hour | the tens-of-minutes digit `$49C8` wrapping | CONFIRMED, in the running game and from the bytecode |
| `11` | one day | the hour digit `$49C9` wrapping | CONFIRMED, in the running game and from the bytecode |

Units `10` and `11` were graded from the bytecode alone, with nothing live but
the negative that they did not move when no boundary was crossed, until a rest
long enough to cross theirs was driven. Two rests measured all four, each
count falling by exactly the boundaries crossed and by nothing else. Both
staged four slots at count 32, one per unit, into a copy of a save disk and
read the bytes back (`tools/c64/effectdrive.py`):

| the rest | clock | unit `00` | unit `01` | unit `10` | unit `11` |
|---|---|---|---|---|---|
| 30 minutes | 21:16 → 21:46 | 31 → 1, the thirty minutes | 32 → 29, the wraps at :20, :30 and :40 | 32, no hour crossed | 32, no day crossed |
| eight hours | 21:17 → 05:17 | expired | expired | 32 → **24**, the eight hour boundaries | 32 → **31**, the one midnight |

**So the count is not a number of minutes and `Duration.minutes` is an upper
bound.** A slot staged at 21:16 with 32 ten-minute units lost its first unit
four minutes later, at 21:20, because what it counts is the wrap and not the
elapsed time.

**Nothing counts in months.** `$49CA` and `$49CB` are a day and a month
(`docs/41-memory-regions.md`), and the day byte did tick at midnight in the
eight-hour rest — but two bits hold four units, a day is the coarsest of them,
and no unit is aged by the month byte.

**CONFIRMED: an expired slot reads id 0 and duration 0.** The two slots the
eight-hour rest ran out came back that way, so an expired slot is told from a
never-expiring one by the id and never by the duration byte. Which routine
wrote the zero — the camp sweep storing the run-out, or the expiry — is not
established, and `docs/125-bug-notes.md` N7 is the note that the expiry itself
clears the id alone.

**CONFIRMED: a duration byte of zero is never decremented and never expires.**
All three ageing routines read the byte and skip the slot when it is zero
(`DUNGEON $0E1F`, `CAMP $12A3`, `COMBAT $2228`). The project used to read zero
as permanent, then stopped when a save turned up carrying two running spells
at duration zero; the reading was right and the refutation was aimed at the
wrong claim, because nothing ages such a slot and nothing ever clears its id. A
slot staged that way kept both its id and its zero through the whole eight-hour
rest.

Three routines age the arrays, one per overlay, and they agree:

* **`DUNGEON $0E0D`**, from the clock tick at `$0DEC`, which hands it the
  coarsest digit that advanced. It ages exactly one unit per minute of
  walking, the one matching that digit less one.
* **`CAMP $1283`**, entered with the minutes to pass, which accumulates a
  wrapped-digit mask in `$28E6` from the bit table at `$165A` and then sweeps
  all 64 slots at `$1299`. Unit `00` loses the whole elapsed minutes; the
  other three lose one if their digit wrapped at all. Rest passes five minutes
  at a time (`CAMP $1D7A`), so no boundary is crossed twice in one pass.
* **`COMBAT $221E`**, once per round, which tests `CMP #$40 / BCS` and so
  decrements unit `00` and nothing else, then advances the clock a minute at
  `$224B`. A combat round is a minute.

**CONFIRMED: walking never expires anything.** When a unit-`00` count runs out
while the party walks, `DUNGEON $0E39` writes `$01` back — one minute left —
and leaves the id set, for as long as the party keeps walking. The expiry
handlers live in `SPELLE04`, which only `CAMP $133F` loads, so `DUNGEON` has
nowhere to send an expiry: it parks the effect for camp or the next fight to
collect. `ENCAMP` always collects, because `CAMP $0803` passes one minute on
entry. `DUNGEON $1241`, which passes twelve hours, parks run-out counts at one
the same way, deliberately.

### What the two rests did not settle

None of these changes the unit mapping above; each is a count the driver
recorded and did not interpret.

* **A second dungeon step passed no minute.** In the eight-hour run the first
  step moved the clock 21:16 → 21:17 and took one off unit `00`; the second
  left every clock byte and every count where the first had put them. Whether
  the party was refused that move or a step only sometimes ticks the clock is
  UNMEASURED — walk ten steps of open floor and log the clock after each.
* **The rest's expiry checkpoint fired three times for two expiring slots.**
  Three hits on `CAMP $131F` against the two slots, units `00` and `01`, that
  came back with their ids cleared. UNMEASURED which slot the third hit was:
  stop on `$131F` and read `X`.
* **No run has crossed a month boundary**, so the month byte `$49CB` has never
  been seen to move. Nothing is aged by it, so this bounds nothing about a
  duration.

## The magnitude byte, and what is restored

**CONFIRMED: bit 7 of the magnitude is the flag that says there is a value to
put back**, and the restore reads that value out of the effect record rather
than recomputing anything from the character. Both expiry routines — `CAMP
$131F` out of combat and `SQRPACI01 $07E4` in it — clear the id, read
`$4B80,X`, and give up on a `BPL`.

With bit 7 set, the byte goes to a dispatch that picks a handler by effect id:
out of combat a zero-terminated id list at `ECL65 $9AD5` with its address
halves at `$9AEE` and `$9B06`, searched; in combat a 139-entry table at
`$DA63`/`$DAEE` indexed by the id itself. `CAMP $133F` loads `SPELLE04`,
`ECL65` and `SPELLN00` before it dispatches, which is what puts the handlers
in memory.

**CONFIRMED from the bytecode: out of combat, three ids read the magnitude's
value** — 12 and 38 rebuild strength, 14 rebuilds charisma. Two more read only
its sign. The rest of the list discards it, and out of combat every id **not**
in the list reaches no handler at all, so nothing of its magnitude is ever
read. That is true out of combat only: the combat table is indexed by the id
itself, and 135 of its 139 entries are unread (below).

**The grades differ by id.** Live, in the running game: id 12 only. A run wrote
id 12 with magnitude `$F4` into a copy of a save, let `ENCAMP` pass the
minute, and watched the sweep, the expiry, the dispatch and `SPELLE04 $AD0B`
each hit once while the owner's strength went from 15 to 16, with no other
character touched. Ids 14 and 38 are read from the bytecode: 38 shares handler
`$AD0B` with 12, and 14's handler `$AD27` was read and not run. The id list
itself was read identically off the disk and out of the running machine. Each
discard verdict below is read from the bytecode; the ones with an instruction
in the table (4, 7, 22, 34, 43, 57 and the trait-clearing group) name what
overwrites the value, and for 15, 44, 50 and 62 the measurement records the
verdict and not the instruction, so the reason is not recorded.

| effect id | handler in `SPELLE04` | the magnitude |
|---|---|---|
| **12**, **38** | `$AD0B` | **read**: `AND #$7F`, then record `0x014` STR and `0x01A` STR % |
| **14** | `$AD27` | **read**: `AND #$7F` into record `0x019` CHA |
| 4 | `$ACCE` | discarded |
| 7 | `$ACD7` | discarded; constitution goes back up by one instead |
| 15 | `$AD71` | discarded |
| 22 | `$AD2F` | discarded; adds effect 15 and expires this slot |
| 34, 43 | `$AD49`, `$AD4F` | discarded; strength comes down by one instead, and never goes below 4 |
| 44 | `$AD6B` | discarded |
| 50 | `$AD97` | discarded |
| 57 | `$AD9F` | discarded; a message only |
| 62 | `$ADC2` | discarded |
| 128, 129, 130, 133, 134, 136, 138, 139 | `$ADD4` | discarded; clears the code from the ten trait slots at `0x0AD` |
| 131 | `$AE2D` | bit 7 only, as a branch; chain-expires effect 38 |
| 132 | `$AE5F` | bit 7 only, as a branch |
| 135 | `$AECD` | discarded |
| anything else | — | never dispatched |

**CONFIRMED:** the strength magnitude is `18/v` for a low 7 bits `v` under
101 and an ordinary score of `v - 100` at 101 and above — `SPELLE04 $AD0B`
and its combat twin `SPELLE01 $A81D`, instruction for instruction. A
character at strength 15 whose effect carried magnitude `$F4` came out of camp
at 16.

**CONFIRMED in combat, for four ids:** 12 and 38 at `SPELLE01 $A81D` and 13
and 14 at `$A83F`, the same two statistics. **UNKNOWN:** the other 135 entries
of the combat table, so the four ids are a lower bound in combat: another id
may restore a statistic in a fight. Reading them is static work — disassemble
`SPELLE01` at each distinct handler address and record which touch `$4B80,X`.
`goldbox.effects.COMBAT_MAGNITUDE_VALUE_IDS` holds the four and
`MAGNITUDE_VALUE_IDS` stays the exact out-of-combat set of three.

**A finding that is not about restoring:** `SPELLE01 $A84D`, shared by ids 4,
7, 15, 34, 43, 44, 50, 57 and 62, writes the id back into `$4900,X` with a
duration of `$41`, so those nine re-arm themselves for one ten-minute turn
when their round count runs out in a fight. CONFIRMED from the bytecode,
unmeasured live.

## What this means for a write path

**Clearing a slot is not the same as expiring it.** The game's own clear
restores a statistic on the way through; `goldbox.effects.clear_effect()`
zeroes the four bytes and does not. A slot whose magnitude has bit 7 set and
whose id is 12, 14 or 38 — or 13, in combat — leaves the character
permanently altered if it is cleared that way, so anything that offers Remove has to apply the restore
itself or refuse. **A magnitude written with bit 7 set on one of those ids is
a deferred write to the character record**, not an opaque byte.

The earlier plan's `P3-EFFECTS.D64` claims are removed: that disk image is not
available, so it cannot support a duration or active-effect claim.
