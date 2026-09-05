# Effect 97 is written for a race and does the constitution bonus

`#247 (Nobody knows whether innate effect 97 is racial or the constitution
bonus)` asked which of two things DOS Pool of Radiance's innate effect 97 is,
because every race that carries it also earns a constitution bonus to saving
throws, so no rollable character could tell the readings apart. The engine's
own code answers: **it is both, and they were never alternatives.** Creation
writes 97 for a dwarf, gnome or halfling on the race byte alone; the handler
97 dispatches to reads the character's constitution *when a saving throw is
rolled* and adds the band to the die. Nothing about the bonus is stored.

Grades follow `docs/50-experiments.md`'s scale. "The build" is the 1.3
`GAME.OVR` and `START.EXE` in the archives; `tools/dosracialseed.py` reads
every number below out of them and `tests/test_dosracialseed.py` pins the
project's tables to that reading.

## What a player has

| | in the record | on the roll |
|---|---|---|
| DOS | the plain class row at `0x6D`-`0x71`, and `.SPC` records 90 and 97 | 90 adds the band on the paralysis/poison/death column, 97 on wands and spell; `constitution * 2 // 7`, so +0 below 4 |
| C64 | the class row **less the band** on all five bytes (`GEN $2359`, `goldbox/levels.py`) | the stored bytes |

So a converted character with 97 in his `.SPC` and constitution 3 gets what
a DOS-born one with constitution 3 gets: the record, and +0. **The bonus a
player did not roll, which the issue was worried about, cannot be handed
out**, because the magnitude is never written anywhere. CONFIRMED.

## The chain

Six links, each read from the bytes; `tools/dosovrmap.py dis` prints any of
them.

**1. Creation, `GAME.OVR:0x1A127`.** `mov al, es:[di+0x2E]` -- the record's
race byte -- and a switch:

| `cmp al` | race | `add_affect(id, 0, 0xFF, 0)`, in order |
|---|---|---|
| 5 | halfling | 90, 97 |
| 1 | dwarf | 90, 97, 26, 47 |
| 3 | gnome | 97, 18, 47, 48 |
| 2 | elf | 107 |
| 4 | half-elf | 124 |
| other | human, half-orc | none |

Between the race read at `0x1A12A` and the last `lcall 0xB0:0x52` at
`0x1A288` no other byte of the record is read; the only other store is
`es:[di+0xC0]`, the icon size (1 for the three small races, 2 otherwise).
`docs/162-spc-permanence.md` lists all 38 `add_affect` callers and the
racial ids are pushed here and nowhere else. This is `#84 (Roll a gnome in
DOS and read the two innate effect ids nobody has seen)`'s eight-character
census, reproduced from the code. CONFIRMED.

**2. The saving throw, `0x2BC4D`** (arguments: a bonus, the save type, the
player). `1d20` into `[0x6816]`; a 1 fails and a 20 succeeds outright;
otherwise the caller's bonus and record `0x101` are added, the save type is
stored in `[0x682A]`, and check list 12 is walked. Then
`es:[di + 0x6D + type]` -- type 0 paralysis/poison/death, 1 petrification,
2 wands, 3 breath, 4 spell, the five bytes `goldbox/dos_layout.py` names --
is compared with `[0x6816]`, and `ja` fails. **The race byte is not read on
this path.** CONFIRMED.

**3. List 12, `0x2B1E4` case 12**, pushes 8, 9, 10, 17, 20, 33, 36, 45, 46,
49, 61, 111, 125, **90, 97** -- `coab`'s `CheckType.SavingThrow` for Curse,
with 90 and 97 where Curse has `con_saving_bonus` alone. Each goes to
`0x2B04A`, which asks `0xBA:0x2199` (resident; `START.img:0x2D39`) whether
the character has the id -- a walk of the chain at record `0x7F` comparing
node byte 0, the chain creation appended to -- and on a hit calls `0x2AEEA`.

**4. The dispatch, `0x2AEEA`:** `di = id * 4; lcall [di + 0x6828]`. The
table is BSS, filled at start-up by quartets of `mov ax / mov dx / mov [] /
mov []`: `0x122D3` stores `0x41:0x01B5` into `[0x69AC]`, entry 97, and
`0x12278` stores `0x41:0x0197` into `[0x6990]`, entry 90. 180 entries are
filled that way.

**5. The stubs.** Unit `0x41`'s public entry at stub `0x1B5` is code
`0x268A`, file `0x112E5`; stub `0x197` is code `0x24D9`, file `0x11134`
(`tools/dosovrmap.py units`).

**6. The handler, `0x112E5`:**

```
0112eb  cmp byte ptr [0x682a], 4      ; spell
0112f0  je  0x112f9
0112f2  cmp byte ptr [0x682a], 2      ; rod, staff or wand
0112f7  jne 0x11355                   ; any other column: nothing
0112fc  mov al, byte ptr es:[di + 0x14]   ; constitution, now
        4-6 -> 1, 7-10 -> 2, 11-13 -> 3, 14-17 -> 4, 18-20 -> 5
01134b  mov al, [0x6816] / add / mov [0x6816], al
```

`0x11134`, effect 90, is the same band gated on `[0x682A] == 0`. The bands
are `constitution * 2 // 7` at every value 4-20, which is
`goldbox.levels.constitution_save_bonus`, the C64's `GEN $2359` arithmetic
met on DOS; below 4 no band matches and 0 is added. CONFIRMED, and the test
checks all seventeen values against the function.

## What it settles beyond the question

* **`goldbox/dos.py`'s "writing 97 is PROBABLE" beside `RACE_COMBAT_EFFECTS`
  can become CONFIRMED**, and the sentence about a low-constitution
  character being handed a bonus deleted: the engine writes the id by race
  and computes the bonus from the constitution it finds.
* **`goldbox/traits.py`'s 90 and 97 can become CONFIRMED**, worded by
  column: 90 the paralysis/poison/death column, 97 wands and spell.
* **DOS gives the bonus on three of five columns** -- poison, rods/staves/
  wands, spells, the AD&D rule -- where `goldbox/levels.py` has the C64
  baking it into all five (`constitution_save_columns=(0, 1, 2, 3, 4)`). A
  port difference; the C64 half rests on `GEN $2359` and HOGARTH's stored
  bytes and is not re-derived here.
* **Curse's 0x5A is not 90.** `coab` names it `breath_acid`, and Curse's
  creation writes `con_saving_bonus` (0x61) and the combat ids only -- Curse
  folded the poison column into 97's handler. That is why Curse's importer
  keeps 97 and drops 90, and why `RACE_COMBAT_EFFECTS` is Pool of Radiance's
  table and not the family's.
* **`#191 (A converted dwarf loses his constitution bonus to saving
  throws)`'s two open items are closed by this**: the saving throw has now
  been read to the instruction, and 97 is not conditional on anything.

## What it opens

**The other direction has the bug `#191 (A converted dwarf loses his constitution bonus to saving throws)` fixed.** A DOS dwarf's five
stored bytes are the plain row; `goldbox/c64_codec.py` copies them to the
C64 unchanged, and the 90 and 97 it also writes into trait slots are on no
C64 check list (`docs/171-c64-trait-slots.md`, list 12), so a converted DOS
dwarf saves three or four worse on the C64 than one born there. Filed as
`#311 (A DOS dwarf, gnome or halfling converted to the C64 loses his
constitution bonus to saving throws, because the C64 keeps it inside the
five stored bytes)`, PROBABLE until a C64 spell save is watched with the
target number read.

## Negative results

* **No table search finds the handler table**: `ds:0x6828` lies past the end
  of the 68,592-byte expanded image, in the BSS, so a far pointer such as
  `B5 01 41 00` appears in neither file. The fill is code in unit `0x41`
  itself, `0x122D3` for entry 97.
* **Three `cmp al, 0x61` sites** (`0x2962`, `0xCFAA`, and `0xC62B`, which
  is data) are range switches on some other byte -- each tests `0x61`
  between `0x5B` and `0x64` neighbours -- and none is an effect-id test.
* **135 reads of the race byte** in the overlay; only one is followed by a
  compare and `add_affect` calls, and `tools/dosracialseed.py` finds the
  switch by that shape rather than by address.

## What would refute it

A DOSBox-X run with an exec breakpoint on the handler's bytes in memory
during a spell saving throw by a dwarf: the break fires, `es:[di+0x14]` is
his constitution, `[0x6816]` rises by his band. Not run; the code leaves
nothing to choose between, so the experiment corroborates rather than
decides.
