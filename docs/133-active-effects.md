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

## Open measurements

**PROBABLE:** The duration byte uses bits 0–5 as a count and bits 6–7 to select
a unit. **UNKNOWN:** What the four units mean, and whether zero means
permanent. Until this is measured, the panel deliberately shows no remaining
duration. [#500 (What unit is an active effect's duration in, and what do bits
6-7 of the duration byte select?)](https://github.com/malcyon/wish/issues/500)
tracks it.

**CONFIRMED:** The magnitude byte is decoded for each id-table record.
**UNKNOWN:** Which ids read it on expiry and which discard it. Writing or
clearing an effect before that is known can leave a changed statistic behind,
so the panel remains read-only. [#501 (Which active effect ids read their
magnitude back when the effect expires, and which discard it?)](https://github.com/malcyon/wish/issues/501)
tracks it.

The earlier plan's `P3-EFFECTS.D64` claims are removed: that disk image is not
available, so it cannot support a duration or active-effect claim.
