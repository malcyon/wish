# The floor under a DOS THAC0, and why a magic-user comes out 20

`#608 (Curse's DOS engine writes THAC0 20 for a magic-user at levels 1-5 where
our table holds 21, so a converted magic-user arrives one point worse to hit)`
asked which value is right for a converted magic-user: the 21 Curse's own
shipped table holds at levels 1-5, or the 20 the running game wrote over our
39 with no training in between. The answer is 20, and the reason is not in the
magic-user row at all.

**The short of it.** Every DOS row's **entry 0** holds a real THAC0 rather than
a zero sentinel -- 39 or 40 stored -- and the recompute the engine runs when it
loads a party walks all eight class slots **without testing whether the level
is zero**. So a character reads entry 0 of every class he does not have, and
since every row but the fighter's and the magic-user's holds 40 there, the
best-of is never worse than 40: THAC0 20, for everybody, in all three DOS
titles. The magic-user's
own row is the only place in Curse or Silver Blades that ever asks for worse
than that, which is why he is the only character the floor shows on.

The C64 has no such floor because its rows start `$00`, and `docs/210-the-later-titles-dos-thac0.md`
read the DOS rows correctly and then applied the C64's rule to them. Its
section "The experiment the issue asked for, and its answer" concluded a
rebuild writes 39 for a magic-user 1-5; that is wrong, and this page is why.

## The two loops, and the one that runs on load

`tools/c64/laterthac0.py writers` prints every instruction in each `GAME.OVR`
that touches `thac0_base`. Two of them clear the byte and rebuild it, and they
are not the same routine:

| title | clears, **tests the level**, rebuilds | clears, **does not test**, rebuilds |
|---|---|---|
| Pool of Radiance | `0x01A659` | `0x02AA87` |
| Curse of the Azure Bonds | `0x020FF5` | `0x03B026` |
| Secret of the Silver Blades | `0x01E59B` | `0x03C1B1` |

The first kind reads the slot and skips it when it is empty --

```
01A670  cmp byte ptr es:[di + 0x96], 0
01A676  jle <next slot>
```

-- and the second goes straight from the slot to the lookup:

```
03B046  mov al, byte ptr es:[di + 0x109]     ; Curse: class_levels[slot]
03B04B  mov byte ptr [bp - 4], al            ; kept even when it is zero
03B058  mov dx, 0xd / mul dx                 ; row = slot * 13
03B05F  add di, cx                           ; + level
03B061  mov al, byte ptr [di + 0x3e3a]
03B068  cmp al, byte ptr es:[di + 0x73]
03B06C  jbe <next slot>                      ; keep the larger stored byte
03B088  mov byte ptr es:[di + 0x73], al
```

with `cmp byte ptr [bp - 1], 7` closing the loop, so all eight slots run.

**The unguarded one is what ran on the load measured for `#574 (Camp.memorize's
page-turn landing is stateful and not proven for page > 0)`.** It is the only
one of the two that also writes `level` at `0x0E5` to the highest class level
(`03B08F`-`03B09F`) and `attack_forms` at `0x11C` to 3 past the class's
threshold (`03B0B4`), and both of those changed in that save: the paladin's and
the ranger's `level` went 5 to 11 and their `attack_forms` 2 to 3. CONFIRMED.

## The level-0 column

Entry 0, as THAC0, of every row of every DOS table, read straight out of each
EXEPACK-expanded `START.EXE`:

| title | cleric | druid | fighter | paladin | ranger | magic-user | thief | monk |
|---|---|---|---|---|---|---|---|---|
| Pool of Radiance | 20 | 20 | 20 | 20 | 20 | 20 | 20 | 20 |
| Curse of the Azure Bonds | 20 | 20 | **21** | 20 | 20 | **21** | 20 | 20 |
| Secret of the Silver Blades | 20 | 20 | **21** | 20 | 20 | **21** | 20 | -- |

The C64's own three tables are `GEN $0E2C` (magic-user), `$0E39` (cleric) and
`$0E46` (thief), and each of them starts `$00`; the fighter group is not a
table at all but `LDA attack_level / CLC / ADC #$27`, which is 39 at a fighting
level of zero. So the C64's floor is 39 -- THAC0 21 -- and its magic-user row
holds 39 at levels 1-5 anyway, so the floor never shows there.

A character can hold at most three classes, so at least one row whose entry 0
is 40 is always read, and `max(40, best of the classes)` is what the DOS
engine stores. CONFIRMED: `tools/records/thac0census.py` implements exactly
that as `dos_engine_thac0`, and `tests/records/test_thac0census.py` walks every
class at every level of all three titles asserting the result is never above
20.

## What the records say

`tools/records/thac0census.py dos --title <key>` now covers all three titles --
it could not read Curse or Silver Blades before, because their class-bit array
is a different permutation from Pool of Radiance's and the anchor found
nothing; it locates their tables through `tools/c64/laterthac0.py` instead. It
prints both counts, because the two rules are two different claims:

| title | records | agree with the engine's rule | agree with the table alone |
|---|---|---|---|
| Pool of Radiance | 250 | 250 | 250 |
| Curse of the Azure Bonds | 104 | **101** | 92 |
| Secret of the Silver Blades | 86 | **86** | 84 |

Pool of Radiance cannot tell the two rules apart: no entry in its table is
above 20 at any level, so the floor never binds. The twelve Curse records and
two Silver Blades records that the table alone misses are every low-level
magic-user on this machine.

**The three Curse records the engine's rule does not account for are each
accounted for.** `WISH-SPEC-curse-408-regained-paladin/CHRDATJ1.SAV` holds 16,
which is his former paladin 5's row folded in by the third loop -- Curse
`0x03B211`, which walks `former_class_levels` at `0x111` and does not clear
(`docs/209-the-regained-dual-class-on-dos.md`). The other two are
`WISH-SPEC-curse-551-party-as-converted`'s two magic-users, holding 21: those
bytes are `goldbox/dos_codec.py`'s, not the game's, and they are the defect
this page is about.

## The differential that settles it

`WISH-SPEC-curse-551-party-as-converted` was loaded into DOS Curse, and the
party saved to the other slot minutes later with no training visit and no class
change. Six records, by name rather than by slot number, since the marching
order moved them:

| character | classes | before | after |
|---|---|---|---|
| MALE ELF MAGE | magic-user 5 | 39 | **40** |
| FEMALE MAGE | magic-user 5 | 39 | **40** |
| CLERIC | cleric 5 | 42 | 42 |
| F/T | fighter 4, thief 5 | 43 | 43 |
| RANGER | ranger 11 | 50 | 50 |
| PALADIN | paladin 11 | 50 | 50 |

Stored bytes, `0x073`. `class_levels` at `0x109` is unchanged in all six. The
engine's rule predicts every one of those six numbers, including the two that
moved and the four that did not; the table alone predicts the four and gets the
mages wrong by one. MALE ELF MAGE's `thac0_current` at `0x199` went 39 to 42 in
the same save, which is 40 plus the 2 his readied weapon gives, so a second
field agrees. CONFIRMED.

The corroborating measurement from the other direction was already on record
and is not contradicted: PHILIPPE, staged at magic-user 5 and trained once in
DOS Curse's own party menu, came out magic-user 6 holding 41 -- the row's own
value at level 6, which beats the floor.

## So the two ports really do disagree

For a magic-user at levels 1-5 in Curse or Silver Blades:

* the **C64** stores 39, THAC0 21 -- its table's own number. Ten records on
  the Curse C64 disks and specimens hold a pure magic-user at levels 1-5,
  including both of the level-5 mages in SSI's own shipped party on
  `CURSE_C.D64`, and every one of the ten stores 39;
* **DOS** stores 40, THAC0 20.

This is not our table being wrong about either port. `_DOS_THAC0_CURSE` and
`_DOS_THAC0_SSB` transcribe the shipped rows correctly, and the C64 rows are
cold-read off the player's own `GEN`. What was wrong is the **rule** applied to
the DOS rows: `goldbox.levels.dos_base_thac0` takes the best of the classes the
character has, which is the C64's rule, and the DOS engine's own rule reads the
level-0 column as well.

**So a conversion must convert the byte rather than copy it, in one direction
only.** A C64 or Amiga Curse or Silver Blades magic-user of level 1-5
converted into DOS should arrive holding 40, where `goldbox/dos_codec.py`
writes 39 today; the same character converted the other way should hold 39,
which is what `goldbox/levels.py`'s `base_thac0` already gives. Pool of
Radiance is unaffected in both directions. Nothing else in any of the three
tables ever asks for worse than 20, so the magic-user at 1-5 is the whole of
the change.

## What a player sees, and what has not been measured

A magic-user rolled or trained in DOS Curse hits one point more easily than the
rulebook or the C64 build gives him, from level 1 to level 5. The sheet's THAC0
is the *current* value rather than the base, so what shows there is the base
plus whatever is readied -- 42 for MALE ELF MAGE with his weapon, where the C64
would give 41. PROBABLE: the base is measured, the sheet was not read in this
work.

Not established, and each with the experiment that would settle it:

* **Whether the guarded loop ever writes what its table says.** Nothing on this
  machine holds a value only it could have left. A driven `HUMAN CHANGE
  CLASSES` into magic-user, followed by reading `0x073` before any load,
  separates them: 39 means the guarded loop wrote it and the next load will
  raise it to 40, 40 means the constant store at `0x0207BA` got there first.
* **The Amiga builds.** Neither Amiga port's recompute has been read, so
  whether an Amiga Curse magic-user 1-5 holds 39 or 40 is UNKNOWN. Reading
  `thac0_base` out of the Amiga Curse specimens' magic-user records would say
  what that port stores, and the conversion into Amiga needs the answer before
  it can claim to be converting rather than copying.
* **Pools of Darkness.** Its root is in `GAME.EXE` rather than `START.EXE`, so
  neither census tool reaches its data segment and its table has never been
  read.
