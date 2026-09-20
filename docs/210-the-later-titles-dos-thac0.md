# Curse and Silver Blades: the DOS THAC0 table, and who writes the byte

`#318 (DOS gives a low-level magic-user or thief THAC0 20 where the C64 gives
21, and our table holds only the C64's)` was answered for Pool of Radiance and
left open for the two later titles, because their records store 40 for a
low-level magic-user where their own table appeared to say 39 and nobody could
say why. Both halves are settled here, from the shipped bytes and the corpus,
with no emulator. `docs/135-levelling.md` has the C64 side of all three
titles; `docs/50-experiments.md`, "Two ports, two THAC0 tables", has Pool of
Radiance's.

**The short of it.** The tables are real and they are not the C64's. Nothing
clamps anything.

**The reading that a stored 40 is a creation or import value no rebuild has run
over is wrong, and `docs/224-the-dos-thac0-floor.md` replaces it.** A rebuild
does run, on every load, and it writes the 40 itself: entry 0 of each row below
is a real THAC0 rather than the `$00` the C64's rows start with, and the loop
that runs on load reads it for every class the character has no level in. That
puts a floor of THAC0 20 under every DOS record, which is where a magic-user's
40 comes from at levels 1-5. The rows below are unaffected -- they were read
correctly; what was wrong was applying the C64's rule to them.

## Where the tables are

Both titles reach their table the way Pool of Radiance does -- `mov dx,
<stride> / mul dx / mov di, ax / add di, cx / mov al, [di + <DS offset>]`,
with `di` the class number and `cx` that class's level -- and both keep it in
the EXEPACK-packed `START.EXE`, in `DGROUP`.

| title | rows | stride | `DS` offset | expanded image | `DS` |
|---|---|---|---|---|---|
| Pool of Radiance | 8 | 11 | `0x3C7C` | `0x1043C` | `0xC7C` |
| Curse of the Azure Bonds | 8 | 13 | `0x3E3A` | `0xEA1A` | `0xABE` |
| Secret of the Silver Blades | **7** | 19 | `0x4C0C` | `0x12A2C` | `0xDE2` |

**`tools/records/thac0census.py` cannot read either later title**, which is why this
sat: it anchors on the eight class bits that follow Pool of Radiance's table,
`02 20 08 40 80 01 04 10`, and the later titles carry a different permutation,
`02 10 08 40 40 01 04 20` -- paladin and ranger share bit `0x40`, and druid
and monk swap. That run occurs nowhere in either image, so the census exits
with "the class-bit anchor occurs 0 times".

`tools/c64/laterthac0.py` locates it without knowing a THAC0 number at all, and
three checks have to agree:

* the block is the **one maximal run of bytes in 30..70** whose length is
  `rows * stride`, where `rows` is the width of `class_levels` in
  `goldbox/dos_port.py` -- 7 for Silver Blades, which drops the monk -- and
  `stride` is the engine's own `mul`;
* `block - DS offset` is a **paragraph boundary**, which is what fixes `DS`;
* the **class-bit array follows the block**, which is the array the same loop
  reads four instructions after the THAC0 lookup.

Pool of Radiance is the control: the locator lands on `0x1043C`, the byte the
class-bit anchor finds by a completely different route.
`tests/c64/test_laterthac0.py` holds all of it.

## The rows

THAC0, not the stored `60 - THAC0`, and level 1 first. Entry 0 of each row is
unused: the engine indexes `class * stride + level` with a level of 1 or more.
Cleric, druid and monk share a row; fighter, paladin and ranger share another.

**Curse of the Azure Bonds**, levels 1-12:

| class | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cleric, druid, monk | 20 | 20 | 20 | 18 | 18 | 18 | 16 | 16 | 16 | 14 | 14 | 14 |
| fighter, paladin, ranger | 20 | **20** | 18 | 17 | 16 | 15 | 14 | 13 | 12 | 11 | 10 | 9 |
| magic-user | 21 | 21 | 21 | 21 | 21 | 19 | 19 | 19 | 19 | 19 | **17** | **17** |
| thief | **20** | **20** | **20** | **20** | 19 | 19 | 19 | 19 | 16 | 16 | 16 | 16 |

**Secret of the Silver Blades**, levels 1-18:

| class | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cleric, druid | 20 | 20 | 20 | 18 | 18 | 18 | 16 | 16 | 16 | 14 | 14 | 14 | 12 | 12 | 12 | 10 | 10 | 10 |
| fighter, paladin, ranger | 20 | **20** | 18 | 17 | 16 | 15 | 14 | 13 | 12 | 11 | 10 | 9 | 8 | 7 | 6 | 5 | 4 | 3 |
| magic-user | 21 | 21 | 21 | 21 | 21 | 19 | 19 | 19 | 19 | 19 | **17** | **17** | **17** | **17** | **17** | 14 | 14 | 14 |
| thief | **20** | **20** | **20** | **20** | 19 | 19 | 19 | 19 | 16 | 16 | 16 | 16 | 14 | 14 | 14 | 14 | 12 | 12 |

The bold entries are where the port disagrees with the C64, whose rows are
cold-read off the player's own `GEN` by `tests/curse_of_the_azure_bonds/test_curselevels.py` and
`tests/c64/test_coldread.py`. There are three disagreements and they are the same
two in both titles plus one that grows:

| | levels | DOS | C64 |
|---|---|---|---|
| thief | 1-4 | 20 | 21 |
| fighter, paladin, ranger | 2 | 20 | 19 |
| magic-user | Curse 11-12, Silver Blades 11-15 | 17 | 16 |

**A low-level magic-user is not one of them in the table, and that is the
surprise.** Pool of Radiance is the odd title in its shipped rows: its DOS
build's magic-user row reads 20 at levels 1-5 where its C64 gives 21, and both
later DOS builds' rows read 21, agreeing with their own C64 side. What the
later DOS engines **store** for such a magic-user is 20 all the same, because
of the floor -- `docs/224-the-dos-thac0-floor.md`. So the three rows below are
where the tables disagree, and the stored byte disagrees in one place more.

**The level-2 fighter is one byte.** The whole row is `39 + level` -- which is
exactly the rule the C64 computes, `LDA $7C98 / CLC / ADC #$27 / STA $7C71`,
the fighting level biased by 39 -- at every index except 2, which holds 40
where the sequence gives 41. Both later titles carry the same single
deviation, in two separately built data files, so it is not one flipped bit in
one rip. Pool of Radiance's own row has no such kink -- its level 2 is 19 --
and its ladder holds fighters at level 2 to prove it. No Curse or Silver
Blades record on this machine has a fighter, paladin or ranger at level 2, so
what a player sees has not been observed: the **bytes are CONFIRMED** and the
**consequence is PROBABLE**, and a driven training from 1 to 2 in either DOS
title would settle it.

## Why a record can hold a number the table does not give

`tools/c64/laterthac0.py writers` prints every instruction in `GAME.OVR` that
touches `thac0_base` -- `0x02D` in Pool of Radiance, `0x073` in Curse, `0x06A`
in Silver Blades, which is what `goldbox/dos_port.py` says for each and is
the first corroboration that our layouts are right. Five kinds of site, and
no sixth:

* **The rebuild, of which there are two and they do not agree.** Both clear
  the byte, walk the class slots and store the row when it beats what is there
  -- `mov es:[di+off], 0`, then per class `cmp al, es:[di+off] / jbe / mov
  es:[di+off], al` -- but only one of them tests the class level before the
  lookup. Curse's guarded one is at `GAME.OVR:0x020FF5` and its unguarded one
  at `0x03B026`; Silver Blades' are `0x01E59B` and `0x03C1B1`; Pool of
  Radiance's are `0x01A659` and `0x02AA87`. The unguarded one is what runs
  when a party loads, and reading entry 0 for every empty slot is what floors
  the byte at 40 -- `docs/224-the-dos-thac0-floor.md`.
* **The regained class's row**, folded in without clearing -- Curse
  `0x03B274`, Silver Blades `0x03C444`. That loop walks
  `former_class_levels` (`0x111` in Curse, `0x118` in Silver Blades) rather
  than `class_levels`, so it can only improve what is there, which is what a
  routine putting an old class back has to do.
  `docs/209-the-regained-dual-class-on-dos.md` has it whole.
* **A flat 40 out of a block of new-character defaults**, in no loop at all.
  Curse has two, `0x01E0DB` and `0x0207BA`; Pool of Radiance one, `0x019F6C`;
  Silver Blades one, `0x01DDE1`.
* **The import.** Curse `0x01D0BC` reads `es:[di+0x2D]` -- a *Pool of
  Radiance* record -- and writes it to `es:[di+0x73]`. Silver Blades
  `0x024DE5` reads `es:[di+0x73]`, a *Curse* record, and writes `es:[di+0x6A]`.
  Both copy the byte across untouched, which is what our own conversion does.
* **Three reads**, where the sheet and the fight use it.

**Nothing compares the field against a constant anywhere**, in any of the
three engines. There is no clamp, and the reading that "something clamps a
magic-user to 40" is refuted.

So a record's stored byte is the last of these that ran, and for a character
the party has loaded since, that is the unguarded rebuild.

## What the corpus says

`tools/records/thac0census.py dos --title <key>` sweeps every DOS record in the
specimen tree and the player's archives against the title's own table, by each
of the two rules: the engine's own, entry 0 and all, and the best of the
classes the character has.

| title | records | engine's rule | table alone |
|---|---|---|---|
| Pool of Radiance | 250 | 250 | 250 |
| Curse of the Azure Bonds | 104 | 101 | 92 |
| Secret of the Silver Blades | 86 | 86 | 84 |

**Every record the table alone misses is a low-level magic-user, and the
engine's own rule accounts for all of them.** The three Curse records left
over are MATHEW at magic-user 6 holding 44, which is his regained paladin 5's
row out of `former_class_levels` and not a miss at all once
`docs/209-the-regained-dual-class-on-dos.md` is read, and the two magic-users
of `WISH-SPEC-curse-551-party-as-converted`, whose 39 our own writer put there.

**PHILIPPE is the proof that the rebuild runs on a training**, and it is
engine-written: `WISH-SPEC-curse-408-regained-paladin` staged him at magic-user
5 and trained him once in DOS Curse's own party menu, and he came out
magic-user 6 holding **41** -- the table's magic-user row at index 6, which
beats the floor. CONFIRMED, and it settles that the row is indexed by the level
itself rather than by `level - 1`.

**MATHEW is the proof that a constant overwrites a good value**, and it is
engine-written too: he went into `HUMAN CHANGE CLASSES` a paladin 5 holding
44, and came out a magic-user 1 holding **40**. A loop that keeps the better
row cannot turn 44 into 40, so a constant store did. CONFIRMED.

What is not directly witnessed is character *creation* in Curse or Silver
Blades: no specimen here was rolled in either game's own creation screens.
The constant-40 store sits in a run of new-character defaults and is
**PROBABLE** for creation on that reading. It no longer matters much which of
the two wrote a given 40, because the next load writes 40 anyway.

## What a player sees

A Curse or Silver Blades magic-user hits at THAC0 20 from level 1 to 5, where
the same character on the C64 hits at 21: the DOS floor is 40 and the C64's is
39. CONFIRMED for DOS from the running game --
`docs/224-the-dos-thac0-floor.md`'s differential -- and from ten C64 records
holding 39 on the other side.

And the three table disagreements above are real for a converted character: a
C64 Curse thief 1-4 arriving in DOS holds 21 among natively-trained thieves
holding 20, and a DOS one arriving on the C64 holds 20 where the C64's own
trainer would write 21.
