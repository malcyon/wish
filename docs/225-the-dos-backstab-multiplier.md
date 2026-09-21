# The backstab multiplier, per title and port

Issue `#607 (Show a thief's backstab bonus in the Character Editor)` needs the value
each engine uses, including for a character who has more than one class. No
title on any port read here stores a backstab bonus. DOS Curse of the Azure
Bonds and Secret of the Silver Blades compute the same multiplier from the
thief slots in the level arrays:

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

## The two inline attack paths

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

## DOS Pools of Darkness reaches the same answer another way

The last DOS title computes no effective level inline. It calls one shared
class-level routine, `GAME.OVR:0x392EE`, with the class index in `al` -- 6 for
the thief -- and that routine answers

```text
max(class_levels[c], former_class_levels[c] * Regained)
```

taking the larger rather than the sum. There is no multiply in it: it calls the
regain helper, reads `former_class_levels[c]` into a local only when the call
answered true and zeroes that local otherwise, then keeps the larger of the two
locals, so the product above is that branch written as arithmetic.
`tools/dos/backstab.py` matches the whole routine byte for byte, and a copy
with the branch or the zeroing erased is refused. `Regained` is the same rule as in the
two earlier titles: `GAME.OVR:0x38C8A` calls the active-class-level routine at
`0x38C19`, which requires race 5 (human at record `0x0AD`) and returns the
first positive entry in `class_levels` at record `0x151`, and accepts only an
active level strictly greater than `former_level` at record `0x139`.
CONFIRMED from the helper's instructions.

**Taking the larger and taking the sum agree on every record the engines can
make,** because a character cannot hold a current and a former level in the
same class at once: dual-classing zeroes the old class's slot, and no DOS
engine writes it back -- the regain is computed at each use.
`docs/209-the-regained-dual-class-on-dos.md` is the separate reading of that.
PROBABLE rather than CONFIRMED: it rests on no DOS routine restoring the slot,
which was read for the class-mask rebuild and not re-proven here. A record
edited to carry both would multiply damage by more in Curse and Silver Blades
than in Pools of Darkness, which is the experiment that would settle it.

The multiplier itself is `((effective thief level - 1) div 4) + 2` again, but
**clamped after the arithmetic rather than before it**: the result is stored
into a local, then `cmp byte [bp+d], 5 / jbe / mov byte [bp+d], 5` at
`0x1E87B` holds it at ×5 however high the thief level goes. The
C64 Silver Blades and Death Knights clamp the *level* at 14 instead, which
gives the same ceiling by a different route. DOS Curse and Silver Blades have
no clamp in the run: the tool matches their arithmetic as one contiguous byte
run, from the former slot read through the `+ 2` and into the multiply, and
that run contains no compare. Whether any other code clamps the level or the
product before it is not read.

| Site | Offset in `GAME.OVR` |
|---|---:|
| Thief-level call (`mov al,6 / lcall 0102:0048`) | `0x1E867` |
| Multiplier arithmetic | `0x1E86F` |
| Multiplier clamp at 5 | `0x1E87B` |
| Applied multiply, damage word `0xA7D8` | `0x1E88A` |
| Predicate | `0x20D62` |
| Thief-level gate inside the predicate | `0x20DAA` |
| Predicate callers: damage, to-hit, message | `0x1E85A`, `0x1FBE1`, `0x1FC86` |
| Class-level helper | `0x392EE` |
| Regain helper | `0x38C8A` |
| Active-class-level routine | `0x38C19` |

The three callers are the same three as in Curse and Silver Blades, and the
to-hit caller subtracts 4 from record `roster_tail` at `0x1F3` exactly as
Curse's does from its own `0x19B`. `class_bits` at `0x17B` does not occur in
the bounded predicate. Its ES-relative displacements are `0x2E`, `0x8`, `0xE`,
`0x131`, `0x1AB`, `0x1AD`, `0x1B3`, `0x1B5` and `0x1E7`; of those, `0x2E` is
read off the pointer held at record `0x1AB`, and `0x8` and `0xE` off the
pointer held at record `0x1E7`, so they are offsets in another structure and
not record fields. CONFIRMED from the direct ES-relative operands between the
predicate's prologue and the next routine, which the tool reads and the
disassembly of it confirms by hand.

`tools/dos/backstab.py --game DARKNESS` reproduces all of it, resolving the
far calls through `GAME.EXE` because this title ships no `START.EXE`.

## The six C64 titles

Every C64 engine computes the multiplier rather than storing it, and all six
gates read `level_thief` at record `0x0CB`; `class_bits` at `0x0EB` is absent
from each bounded predicate. The complete eligibility path then checks the
weapons and attack direction. A fighter/thief therefore uses the thief entry
of the same eight-byte level array as a single-class thief. CONFIRMED from all
six titles' instruction bytes.

The arithmetic is inline in every one of them, with no multiplier table: the
engine decrements the thief level, shifts it right twice and adds two. Three
titles cap the input at 14 first.

```text
Pool of Radiance, Curse, Gateway, Champions:  ((thief level - 1) div 4) + 2
Silver Blades, Death Knights:                 ((min(thief level, 14) - 1) div 4) + 2
```

All six give ×2 at levels 1-4, ×3 at 5-8 and ×4 at 9-12. The two capped titles
give ×5 from level 13 upward, and the four uncapped ones would keep climbing
past that. CONFIRMED from the complete arithmetic in each engine.

**The cap only ever matters in the two titles that have it.** `GEN`'s training
ceiling for the thief slot, which `tools/c64/coldread.py levels` reads, is 12
in Curse, 8 in Gateway and 9 in Champions -- none of them within reach of a
13th thief level -- against 18 in Silver Blades and Death Knights. That the
two with the high ceiling are the two that clamp the input is a likely reason
and an inference; nothing read says what the authors intended. Pool of Radiance does not use
the ceiling table the other five share, so its thief ceiling is not read here.
The multiplier a player can therefore see is ×4 in Curse and Champions, ×3 in
Gateway and ×5 in Silver Blades and Death Knights. PROBABLE: a character
imported from an earlier title arrives with whatever level that title allowed,
and the ceiling is what `GEN` refuses to train past rather than a bound on the
record.

| Title | Thief-level gate and formula | Predicate call, then factor byte | Damage multiply | To-hit adjustment | Byte multiply |
|---|---:|---:|---:|---:|---:|
| Pool of Radiance | `SQRPACI01 $06A8` | `$068B` → `$2B7C` | `SQRPACI01 $06E1` | `COMBAT $11F9` | `$2E30` |
| Curse of the Azure Bonds | `COMBAT2 $F832` | `$8164` → `$A981` | `ECL64 $86B7` | `ECL64 $83E1` | `$2FB9` |
| Secret of the Silver Blades | `COMBAT2 $F4B2` | `$8167` → `$A980` | `ECL64 $86CC` | `ECL64 $83F0` | `$2E6F` |
| Gateway to the Savage Frontier | `COMBAT2 $F81B` | `$8164` → `$A981` | `ECL64 $86BB` | `ECL64 $83E5` | `$2FB9` |
| Champions of Krynn | `COMBAT2 $F41B` | `$8167` → `$A980` | `ECL64 $86DB` | `ECL64 $83E8` | `$3007` |
| Death Knights of Krynn | `COMBAT2 $F47C` | `$8167` → `$A840` | `CODE03 $86D9` | `CODE03 $83E8` | `$2FB0` |

The overlay bases are `COMBAT2 $E000`, `ECL64` and Death Knights' `CODE03`
`$8000`, `GEN $0800`, and `LIBRARY $2C48` in Pool of Radiance and `$2DC8` in
the five later titles. Death Knights renamed its overlays and its library's
directory entry is not ASCII, so `tools/c64/backstab.py` finds that one by the
multiply routine's own bytes instead of by name. Each library base is
**derived** rather than assumed: the extractor locates the multiply routine
inside the file and subtracts its offset from the address the damage path
calls, and the answer agrees with what `tools/c64/coldread.py` established by
an unrelated route.

**Pool of Radiance keeps the whole predicate in a 1024-byte overlay at
`$0400`,** which is the one place its memory map differs. The tool pins that
base only as far as the overlay's own call goes: it finds the one `JSR` to the
gate at the address the base implies, and would find none at another. What
follows was read by hand and is not in the tool or a test: two calls from
`COMBAT`, which runs at `$0800`, appear to land on routine entries at that
base -- `$1A23` calling the eligibility wrapper at `$0680` and `$0CCF` calling
the damage multiply at `$06E1`, immediately after `COMBAT $0CAD` rolls the
damage (`docs/147-combat-rolls.md`) -- and the file is `$0400`-`$07FF` long.
Whether no other base would put both calls on an instruction was not tested.

The predicate first refuses a zero thief level, computes the factor into
zero-page `$B0`, then checks the weapons. The attack overlay checks the attack
direction and copies `$B0` only when both paths pass. The damage path loads
that same byte and calls the library's eight-bit multiply routine with the
rolled damage; the attack path also uses its presence to subtract two from the
number needed to hit. This is why the computed byte is a backstab multiplier
rather than an unrelated thief level cache. CONFIRMED from all six complete
paths.

**Silver Blades and Death Knights clamp the multiplied damage and the other
four do not.** Their damage sites follow the multiply with `CPX #$00 / BEQ +2 /
LDA #$F0`, storing 240 when the 16-bit product does not fit a byte; Pool of
Radiance, Curse, Gateway and Champions store the low byte alone, so a product
of 256 or more would wrap. No player reaches it: the byte multiplied is one
attack's rolled damage plus its bonuses, and ×4 of that stays far below 256 for
any weapon a character can wield, so this is a difference in the code with
nothing behind it on screen. CONFIRMED from the instructions; the
unreachability is PROBABLE, and what would refute it is a single melee damage
roll of 128 or more in Curse, Gateway, Champions or Pool of Radiance.

### The dual-class regain path exists in only three of them

The C64 does not keep a former-class level array. It keeps
`dual_class_slot`/`dual_class_level` at record `0x0B9`/`0x0BA`. The generic
regain path is `GEN $20A3` in Curse, `$154F` in Silver Blades and `$20A4` in
Gateway:

```text
If dual_class_level != 0 and level > dual_class_level:
    class_levels[dual_class_slot] = dual_class_level
    class_bits |= 1 << dual_class_slot
```

Thus a former thief has no backstab while his thief slot is zero. Once the new
class strictly passes the stored former level, `GEN` restores slot 2 at record
`0x0CB`, and the ordinary thief-level gate sees it. No separate former-thief
branch exists in any of the six attack paths. CONFIRMED from the three `GEN`
routines and all six backstab predicates. The class-bit tables those routines
index are `01 02 04 08 10 20 40 80` at Curse and Gateway `GEN $0B82` and
Silver Blades `LIBRARY $46E5`, so slot 2 restores bit `$04`; all three tables
are read and checked by the extractor. The C64 generic regain behavior was
independently driven for former paladins in
`docs/214-the-regained-dual-class-on-the-c64.md`; a former thief was not
driven.

**Pool of Radiance, Champions of Krynn and Death Knights of Krynn have no such
path at all.** No two bytes anywhere on their disks are the little-endian
address of `dual_class_level` -- 0 hits across 564, 338 and 277 distinct files
-- so no absolute instruction can read or write it, and the question of a
former thief's backstab does not arise in those three. That reproduces what
`goldbox/layout.py` records for the same two record bytes from a separate
sweep. CONFIRMED for the absence of an absolute reference; that no dual-class
regain exists by some indexed or indirect route is PROBABLE, and what would
settle it is a driven dual-class attempt in Pool of Radiance's own training
hall, which should not offer the choice.

`tools/c64/backstab.py` reproduces the instruction read from the player's own
disks for all six titles. No live C64 damage was measured.

## The four Amiga ports

Each Amiga executable carries **exactly one** run of the multiplier
arithmetic, which is what `tools/amiga/amigabackstab.py` finds it by; the
predicate, the record bytes and the damage byte are then read out from there.
The offsets below are file offsets in the build the most of the player's disk
images agree on.

| Title | Executable | Arithmetic | Predicate | Callers | Damage |
|---|---|---:|---:|---|---|
| Pool of Radiance | `/program` | `0xB8DE` | `0xD704` | `0xB8CC`, `0xC906`, `0xC992` | `$14DA.l` |
| Curse of the Azure Bonds | `/Curse` | `0x6FA4` | `0x8DE2` | `0x6F82`, `0x7F0C`, `0x7F8C` | `-$32C0(a4)` |
| Secret of the Silver Blades | `/Secret` | `0x7FD0` | `0x9E26` | `0x7FA2`, `0x8DAC`, `0x8E4A` | `-$1A39(a4)` |
| Pools of Darkness | `/Pools of Darkness` | `0x7FD8` | `0x9F4C` | `0x7FBC`, `0x905E`, `0x90FC` | `-$152E(a4)` |

**Each Amiga port computes what its DOS counterpart computes,** as far as the
instructions go. CONFIRMED from the instructions in all four:

```text
Pool of Radiance:  (class_levels[thief] div 4) + 2
Curse, Silver Blades:
                   ((class_levels[thief]
                     + former_class_levels[thief] * Regained - 1) div 4) + 2
Pools of Darkness: min(((effective thief level - 1) div 4) + 2, 5)
```

Pool of Radiance alone does not subtract a level first, so its steps fall at 4,
8 and 12 where the later titles' fall at 5, 9 and 13 -- the same difference
`docs/221-thief-abilities-in-dos-pool-of-radiance.md` reads out of the DOS
build of that title, now corroborated on a second port. It also has no former
level to add: `class_levels[thief]` at record `0x09E` is the whole sum. Curse
reads record `0x110` and `0x118`, Silver Blades `0x0B2` and `0x0B9`. In both,
`tools/amiga/amigabackstab.py` checks the whole run after the gate: a
small-data `jsr d16(a4)`, the former slot loaded and multiplied into its
result with `muls.w`, the current slot loaded and added with `add.w`, then the
subtract; erasing the call, the multiply or the add is refused. It also checks
that the predicate makes the same `jsr`. What it does not read is the routine
that `jsr` reaches, which lies behind the `a4` jump table, so that it is the
same regain rule as DOS is inferred from its role -- the gate calls it and the
arithmetic multiplies by its answer -- and is PROBABLE. Pools of Darkness
pushes class index 6 to a shared class-level routine, also through `a4` and
also not read, so that it takes the larger of the two slots as DOS does is
likewise not established on the Amiga; the tool checks the push and the clamp
of the multiplier at 5.

Pool of Radiance has no `muls` here: it loads the damage into a second
register and calls a multiply routine, the way its C64 port calls `LIBRARY`'s.
The tool treats any `jsr` there as the multiply, and the one it finds goes
through a jump-table thunk (`jmp` to an absolute address) that was not
followed, so that the callee multiplies is inferred from its operands -- the
factor and the damage byte go in and the damage byte is stored back.
The other three multiply in place, Pools of Darkness on a word where the
earlier two use a byte.

**Every Amiga predicate has exactly three callers**, as on DOS: damage, the
to-hit adjustment and the message. Read by hand from the second caller of
each, and not in the tool or a test: Amiga Pool of Radiance (`0xC906`) loads a
byte from record `0x114` and subtracts 2 with a byte `subq`, while Curse (`0x7F0C`, record
`0x1A0`), Silver Blades (`0x8DAC`, `0x149`) and Pools of Darkness (`0x905E`,
`0x188`) load a byte and subtract 4 with a word `subq`. So the Amiga split is by title and
matches DOS, where Curse and Pools of Darkness subtract 4; the six C64
titles all subtract 2. What is **UNKNOWN** is whether the Amiga and DOS
records hold the same quantity at the offsets read, and whether DOS Pool of
Radiance subtracts 2 or 4; neither was chased, because
`#607 (Show a thief's backstab bonus in the Character Editor)` needs the
damage multiplier.

Nothing on the Amiga was driven; these are instruction reads.

## Scope and negative results

Issue `#607 (Show a thief's backstab bonus in the Character Editor)` now has
static proof for DOS Curse, Silver Blades and Pools of Darkness, for all six
C64 titles, and for all four Amiga ports. No multiplier table exists in any of
these thirteen paths; every formula is inline arithmetic on the thief level.
No port stores the bonus, so the editor can derive it from the record it
already reads. A live damage experiment is unnecessary to identify any of
their record fields or arithmetic, but would independently corroborate the
instruction reads, and none was made on any port. DOS Pool of Radiance is in
`docs/221-thief-abilities-in-dos-pool-of-radiance.md` rather than here.

Two things are read and not settled. The to-hit adjustment is 2 in the C64
titles and Amiga Pool of Radiance and 4 in the later DOS and Amiga titles,
and this page does not say whether the quantity subtracted from is the same. And the C64 titles' thief
ceilings come from `GEN`'s training table, which bounds what a player can
train to rather than what a record can hold.
