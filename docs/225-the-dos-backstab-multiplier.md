# The backstab multiplier in DOS Curse and Silver Blades

Issue `#607 (Show a thief's backstab bonus in the Character Editor)` needs the value
the two later DOS engines use, including a character who has more than one
class. Neither title stores a backstab bonus. Both compute the same multiplier
from the thief slots in the level arrays:

```text
Regained = race is human and active class level > former_level
Effective thief level = class_levels[thief]
                      + former_class_levels[thief] * Regained
Backstab multiplier = ((Effective thief level - 1) div 4) + 2
```

The gate is `class_levels[thief] > 0`, or a positive
`former_class_levels[thief]` after `Regained` becomes true. Thus a normal
fighter/thief uses his current thief level. A human who leaves thief loses
backstab until his new class passes the level at which he left thief, then uses
that former thief level. Other class levels do not enter the calculation.
CONFIRMED from both engines' instruction bytes. No running-game damage was
measured.

This also settles the step boundaries. Levels 1-4 give ×2, 5-8 give ×3, 9-12
give ×4 and 13-16 give ×5. The subtraction before division is present in both
later titles. The prior DOS Pool of Radiance evidence from
`#560 (Does Pool of Radiance grant thief abilities off class_bits, or off the
level array and skill bytes?)` found no subtraction and steps at levels 4, 8
and 12; that reading is in
`docs/221-thief-abilities-in-dos-pool-of-radiance.md`.

## The two attack paths

`tools/dos/backstab.py` finds the following sites by their instruction
structure, then expands each title's `START.EXE` in memory to resolve the far
call to the regain helper. The offsets below are file offsets in the Archives'
build of `GAME.OVR`.

| Title | Formula / applied multiply | Predicate | Current thief test | Former thief test | Regain helper |
|---|---:|---:|---:|---:|---:|
| Curse of the Azure Bonds | `0x1356C` / `0x1358F` | `0x15C3F` | `0x15C84`, record `0x10F` | `0x15C8F`, record `0x117` | `00FE:0052` → `0x3C031` |
| Secret of the Silver Blades | `0x150C2` / `0x150E8` | `0x1766D` | `0x176AC`, record `0x117` | `0x176B7`, record `0x11E` | `0164:0057` → `0x3CBB6` |

At each formula site, the engine calls the predicate, calls the regain helper,
multiplies the former thief slot by its zero-or-one result, adds the current
thief slot, subtracts one, divides by four and adds two. Curse expresses the
division as two right shifts; Silver Blades uses signed `IDIV 4`. The predicate
uses the same helper before accepting the former slot. CONFIRMED: matching the
same far-call bytes in both places rules out two unrelated boolean tests.

The resolved helper calls the title's active-class-level routine (`0x3BFC2` in
Curse, `0x3CB44` in Silver Blades). That routine first requires the title's
human race code, then returns the first positive entry in `class_levels`. The
regain helper compares it with record `former_level` (`0x0E6` in Curse at
`0x3C044`, `0x0EF` in Silver Blades at `0x3CBC9`) and returns true only when
the active level is strictly greater. This is the same regain rule
independently read from the class-mask rebuild in
`docs/209-the-regained-dual-class-on-dos.md`. CONFIRMED from both titles'
helper instructions.

The predicate has three callers in each overlay:

| Title | Damage | To-hit | Backstab message |
|---|---:|---:|---:|
| Curse of the Azure Bonds | `0x13554` | `0x149FC` | `0x14AA0` |
| Secret of the Silver Blades | `0x150AA` | `0x1626F` | `0x16314` |

So the gate is shared by damage, the attack adjustment and the printed
`-Backstabs-` action. `class_bits` (`0x12B` in Curse, `0x130` in Silver Blades)
does not occur in either bounded predicate routine. CONFIRMED from the direct
ES-relative operands between each predicate's prologue and the next routine;
this is not a census of the three caller routines or of every use of
`class_bits` in either overlay.

## The C64 Curse and Silver Blades paths

The two C64 engines also compute the multiplier rather than storing it. Both
gate directly on `level_thief` at record `0x0CB`; `class_bits` at `0x0EB` is
absent from each bounded predicate. A fighter/thief therefore uses the thief
entry of the same eight-byte level array as a single-class thief. CONFIRMED
from both titles' instruction bytes.

The arithmetic differs in one place:

```text
Curse:         ((thief level - 1) div 4) + 2
Silver Blades: ((min(thief level, 14) - 1) div 4) + 2
```

Both give ×2 at levels 1-4, ×3 at 5-8 and ×4 at 9-12. Silver Blades gives ×5
from level 13 upward because it caps the input at 14 before subtracting and
shifting. Curse has no cap instruction in this path. There is no multiplier
table: the engine decrements the level, shifts it right twice and adds two.
CONFIRMED from the complete arithmetic in each `COMBAT2`.

| Title | Gate and formula (`COMBAT2`, base `$E000`) | Factor copied (`ECL64`, base `$8000`) | Damage multiply | To-hit adjustment | Byte multiply (`LIBRARY`, base `$2DC8`) |
|---|---:|---:|---:|---:|---:|
| Curse of the Azure Bonds | `$F832` | `$8164` → `$A981` | `$86B7` | `$83E1` | `$2FB9` |
| Secret of the Silver Blades | `$F4B2` | `$8167` → `$A980` | `$86CC` | `$83F0` | `$2E6F` |

`COMBAT2` first refuses a zero thief level, computes the factor into zero-page
`$B0`, then checks the weapons. `ECL64` checks the attack direction and copies
`$B0` only when both paths pass. The damage path loads that same byte and calls
`LIBRARY`'s eight-bit multiply routine with the rolled damage; the attack path
also uses its presence to subtract two from the number needed to hit. This is
why the computed byte is a backstab multiplier rather than an unrelated thief
level cache. CONFIRMED from both complete paths.

The C64 does not keep a former-class level array. It keeps
`dual_class_slot`/`dual_class_level` at record `0x0B9`/`0x0BA`. The generic
regain path is `GEN $20A3` in Curse and `$154F` in Silver Blades:

```text
If dual_class_level != 0 and level > dual_class_level:
    class_levels[dual_class_slot] = dual_class_level
    class_bits |= 1 << dual_class_slot
```

Thus a former thief has no backstab while his thief slot is zero. Once the new
class strictly passes the stored former level, `GEN` restores slot 2 at record
`0x0CB`, and the ordinary backstab gate sees it. No separate former-thief
branch exists in the attack path. CONFIRMED from both `GEN` routines and both
backstab predicates. The C64 generic regain behavior was independently driven
for former paladins in `docs/214-the-regained-dual-class-on-the-c64.md`; a
former thief was not driven.

`tools/c64/backstab.py` reproduces the instruction read from the player's
`COMBAT2`, `ECL64`, `LIBRARY` and `GEN` files. No live C64 damage was measured.

## Scope and negative results

Issue `#607 (Show a thief's backstab bonus in the Character Editor)` now has
static proof for DOS and C64 Curse and Silver Blades. No multiplier table
exists in any of these four paths; each formula is inline. A live damage
experiment is unnecessary to identify their record fields or arithmetic, but
would independently corroborate the instruction read. This write-up makes no
claim about another title or port.
