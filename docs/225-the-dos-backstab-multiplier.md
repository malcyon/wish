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
later titles. DOS Pool of Radiance lacks it and steps at levels 4, 8 and 12;
that earlier reading is in
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
does not occur in any of these instruction paths. CONFIRMED from the named
sites; this is a bounded claim about backstab, not a census of every use of
`class_bits` in either overlay.

## Scope and negative results

Issue `#607 (Show a thief's backstab bonus in the Character Editor)` now has static
proof for all three DOS titles the editor opens. The C64 and Amiga engines
remain unread. No multiplier table exists in these two DOS paths; the formula
is inline. A live damage experiment is unnecessary to identify the record
fields or arithmetic, but would independently corroborate the instruction
read.
