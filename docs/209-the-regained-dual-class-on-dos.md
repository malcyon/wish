# What a DOS record holds when a dual-classed human gets his old class back

`#408 (What does a DOS record hold once a dual-classed character regains his
old class, since our conversion writes his old level into both arrays)` asked
which array carries which level at that moment.

**In one line: no array moves. `class_levels[old]` is zeroed at the change and
stays zero for good, the former array keeps the level he left, and everything
the regained class is worth is derived from those two plus one comparison —
which is where the C64 and DOS differ, and the only place they differ.**

`docs/192-curse-dual-class.md` is the C64 half of this. There, `GEN $20A3`
*stores* the old level back into the level array and ORs the old bit into the
mask, on the training press that crosses the threshold.

## The derive, out of Curse's own overlay

`GAME.OVR:0x3B119`, inside the record recompute the trainer calls when it has
finished, rebuilds `class_bits` (`0x12B`) from **both** level arrays:

```
03B119  mov  byte es:[di+0x12b], 0        ; class_bits = 0
03B131  cmp  byte es:[di+0x109], 0 / jg   ; class_levels[slot] > 0   -> add
03B142  cmp  byte es:[di+0x111], 0 / jle  ; else former[slot] > 0
03B15B  cmp  al, byte es:[di+0x0e5] / jge ;  and strictly < level    -> add
03B16F  add  byte es:[di+0x12b], al       ; CLASS_BIT[slot], from DS:0x3EA2
```

`level` (`0x0E5`) is itself the running maximum of the current array, written
twenty-six bytes earlier at `0x3B09F` — it is only ever raised, never cleared
— so `former < level` is exactly "the new class has passed the level he left
the old one at". That is the test the helper at `0x3C031` spells out for
callers, and the same test `GEN $20A3` uses on the C64.

**The strictness is not a detail.** Treasures of the Savage Frontier's OUGO is
a cleric 8 whose former array holds 8 at the fighter's slot, sitting exactly on
the threshold, and his stored mask is `$02`, the cleric alone. A rule with
`<=` predicts `$0A` and is wrong.

## And the rest of the regained class comes from the former array too

At `0x3B207` the same recompute calls `0x3C031`, and when it answers yes it
runs a second pass over `former_class_levels`:

* `0x3B294` improves `thac0_base` (`0x073`) from the old class's row at the
  **former** level, if that row beats what is there;
* `0x3B23F` and `0x3B254` set `turn_class` (`0x11C`) to 3 for a regained
  cleric 7+, paladin 7+ or ranger 8+.

Nothing in that pass writes `class_levels`. Nothing anywhere does, for the old
slot: sweeping every `es:[di+0x109]` instruction in the overlay finds fourteen
writers, and the only two that touch the old class's slot are the change
itself — `0x3BDA9` zeroes it and `0x3BDB8` sets the new one to 1.

`char_class` (`0x075`) is written once, at the change, from the new class's own
number (`0x3BE1C`), and nothing recomputes it. **So a dual-classed DOS record
never carries a combined class code**, before or after the regain.

## Five of five titles, and Pool of Radiance is the control

`tools/dualclassregain.py code`. Each overlay clears `class_bits` in three or
four places; in every title with a former array **exactly one** of them goes on
to read that array and compare it with `level`.

| overlay | sites that clear `class_bits` | the one that reads the former array |
|---|---|---|
| Pool of Radiance | 1 | — (no former array at all) |
| Curse of the Azure Bonds | 3 | `0x3B119` |
| Secret of the Silver Blades | 3 | `0x3C2B1` |
| Pools of Darkness | 4 | `0x38484` |
| Gateway to the Savage Frontier | 3 | `0x42D42` |
| Treasures of the Savage Frontier | 4 | `0x42A6A` |

`tools/dualclassregain.py census` predicts the mask from the rule and compares
it with the stored byte: **62 of 62** records in the archives that have a
former array agree, and **11 of 11** of the dual-classed ones across the
archives and the specimen tree.

## Watched in the running game

`WISH-SPEC-curse-408-regained-paladin`, made by `tools/curseregain.py` on
2026-09-07. MATHEW is the human magic-user of
`WISH-SPEC-curse-131-dualclassed-in-area-1` whose former array holds paladin 5.
He was trained once at Curse's own `TRAIN CHARACTER`.

| | before the press | after it |
|---|---|---|
| `class_levels` | `[0,0,0,0,0,5,0,0]` | `[0,0,0,0,0,6,0,0]` — the paladin slot still 0 |
| `former_class_levels` | `[0,0,0,5,0,0,0,0]` | untouched |
| `char_class` | 5, mage | 5, mage |
| `class_bits` | `$01` | **`$41`** |
| `level` / `former_level` | 5 / 5 | 6 / 5 |
| `thac0_base` | 40 | **44** |
| `hp_max` / `hp_rolled` | 49 / 34 | 55 / 38 |

**The two fields the question turns on went in holding the answer that would
have refuted the prediction**, so `$41` is the engine's byte and the zero is
what the engine left.

**`thac0_base` 44 is the finding in one number.** The stored byte is
`60 - THAC0`, so 44 is THAC0 16, the *paladin's* row at level 5 rather than the
magic-user 6's 19. MARK, an untouched human paladin 5 in the same party,
independently stores 44. MATHEW hits like a paladin out of a level slot holding
zero.

**Same boot, one difference.** PHILIPPE on roster line 6 is a human magic-user
with an empty former array, staged to the identical level 5 and 45,000
experience and trained in the same session; she came out `class_bits` `$01` and
`thac0_base` 41, the magic-user 6 row.

Staged before the boot and therefore ours: `class_levels[mage]` and `level` at
5, `experience` at 45,000, and `SAVGAM J.DAT+0xD51` at `$00FF` so the school
teaches every class wherever the party stands. Everything above is the
engine's.

**Reproduced on a second boot**, `work/issue408/run3`, from the same staged
input. Every field in the table came out identical except the two the hit die
decides -- MATHEW's `hp_rolled` 38 against 37 and PHILIPPE's 21 against 20 --
which is the only random part of a training.

## Two things the same run settles about the trainer

Curse's trainer is `GAME.OVR:0x24CEE`.

* **The hit-point divide counts the current array.** `0x254C4` counts the slots
  with a non-zero `class_levels` entry, and `0x25611` and `0x2564A` divide the
  hit-die roll and the constitution bonus by that count.
* **It grants no hit points until the threshold is crossed**: `0x255E7` is
  `cmp al, es:[di+0xE6] / jg`, `level` against `former_level` — the DOS twin of
  the C64's `GEN $15E7`.
* **The school's class filter is the low byte of the word at `SAVGAM+0xD51`**,
  read at `0x24D84` and ANDed at `0x252B2` with the per-class bit table at
  `DS:0x3EAA`. `docs/194-the-dos-training-ladder.md` measured what Pool of
  Radiance's own halls write there; this is the instruction that consumes it.

## What it costs a conversion

`goldbox.dos_codec.write` writes the old class's level into **both** arrays and a
combined class code, because the neutral record it is handed carries the C64's
shape faithfully and nothing transposes it.

The engine's own record does not survive a round trip. Reading
`WISH-SPEC-curse-408-regained-paladin` through `dos.to_neutral`,
`c64_codec.write`, `c64_codec.read` and `dos.write`:

| | the engine's record | what comes back |
|---|---|---|
| `class_levels` | `[0,0,0,0,0,6,0,0]` | `[0,0,0,5,0,6,0,0]` |
| `char_class` | 5 | 5, by accident |

The C64 record in the middle is right — `level_paladin` 5, `level_magic_user`
6, `class_bits` `$41`, `dual_class_slot` 6, `dual_class_level` 5, which is what
`GEN $20A3` leaves. **The import half is correct and the export half is not.**
`char_class` survives only because `goldbox.classcode.repair` has no code for
`$41` and keeps the stale byte, which happens to hold 5 for this character.

What a player sees, in his own terms: he plays Curse on the C64, his magic-user
6 changes to fighter, he trains the fighter to 8 so the magic-user comes back,
and he converts to DOS. What arrives is not a fighter 8 who used to be a
magic-user — it is a fighter 8 **and** a magic-user 6, and DOS believes both.
His sheet says FIGHTER/MAGE, the training hall will raise his magic-user again
though the game's own rule never allows it, and every level he trains from then
on gives him about half the hit points he should get, because the divide counts
two live classes where the game counts one.

The fix, which `#408 (What does a DOS record hold once a dual-classed character regains his old class, since our conversion writes his old level into both arrays) (What does a DOS record hold once a dual-classed character regains his old class, since our conversion writes his old level into both arrays)` carries and this page does not implement: in
`goldbox.dos_codec.write`, zero the regained class's slot in `class_levels` — the
mirror of the rule `goldbox.c64_codec.write` already applies going the other
way — and write `char_class` as the code for the class the character is now,
alone. `class_bits` needs no change; the engine's own derive produces the same
`$09` either way.

**One more thing in our own code implements the regained rule for every
record.** `goldbox.dos_codec.class_bits_for` ORs the class bit for every non-zero
entry in **both** arrays with no comparison against `level`, so it disagrees
with the stored byte for five characters here -- DEMELTINA `$42` against `$02`,
MATHEW-before-the-training and Silver Blades' PAINE `$41` against `$01`,
PHILIPPE `$09` against `$08`, OUGO `$0A` against `$02`; 8 of 135 records with a
former array, 127 agreeing. Its docstring already says it is the regained state
rather than the general one, and its only caller is a test that walks shipped
records and has no dual-classed one, so no player can reach it. `predict_bits`
and `regained` in `tools/dualclassregain.py` are the general rule, in three
lines.

**That second half also removes the DOS side of
`#409 (A regained dual-classed paladin or ranger has a class mask Curse's own
table cannot name, so Wish shows him a class he is not)`.** A dual-classed DOS
record never wants a combined code, so the seven pairs `GEN $1951` cannot name
are never asked for on that port. What is still open there is the C64 half —
what the Class box and the roster column should show — and that is Donald's
choice rather than a measurement.

## What is in the tree

| file | what |
|---|---|
| `tools/dualclassregain.py` | the family scan of the derive, and the mask census against every record |
| `tools/curseregain.py` | the driven run that made the specimen |
| `docs/209-the-regained-dual-class-on-dos.md` | this page |
| `WISH-SPEC-curse-408-regained-paladin` | the first DOS record past the threshold anybody here watched being written |

## What would refute this

A DOS record whose `class_bits` disagrees with `tools/dualclassregain.py
census`'s prediction, or a dual-classed DOS record with a non-zero entry in
`class_levels` at the slot its former array names. Neither exists in the 62
records on this machine that could hold one.
