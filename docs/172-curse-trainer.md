# Curse's trainer, driven and watched

`docs/135-levelling.md` is Pool of Radiance's trainer and carries a Curse
section read off `GEN` on 2026-09-04. This page is what happened when the
same trainer was **run** on 2026-09-05 for `#18 (Measure Curse's trainer so
Level Up works there)`: five level-ups in one VICE session, each diffed across
the character record and replayed through `goldbox/levelup.py`.

**The result in one line: 75 derived fields across five engine-written Curse
level-ups come back out of `goldbox/levels.py` and `goldbox/levelup.py` with no
mismatches** -- given the die and given the classes in the order the engine
raised them.

## How the hall was opened without walking to one

`GEN $12AF` builds the sixteen-bit item mask for the party menu, and its last
two instructions are the gate:

```
$12AF  LDA $4CFD / BEQ $12BA        a quest flag; non-zero cuts the menu to three
$12B4  LDA #$60 / LDX #$01          ADD, REMOVE, SAVE
$12BA  LDA #$A1 / LDX #$00          the boot menu: CREATE, ADD, LOAD SAVED GAME
$12BE  LDY $7F3E / BEQ $12C7        is a game in progress?
$12C3  LDA #$7F / LDX #$07          the in-game menu, all eleven items but LOAD
$12C7  STX $4AFA                    the mask's high byte
$12CA  LDY $7EA8 / BNE $12D1
$12CF  AND #$F7                     with no hall, no TRAIN CHARACTER
```

`LIBRARY $3DC7` takes that mask in `A` and `$4AFA` and shifts one bit per item
(`$3DF7 LSR $4AFA / ROR $4AF9 / BCS`) down the eleven strings at `GEN $08C5`:
CREATE NEW CHARACTER, DROP, MODIFY, **TRAIN CHARACTER**, VIEW, ADD, REMOVE,
LOAD SAVED GAME, SAVE CURRENT GAME, HUMAN CHANGE CLASS, BEGIN ADVENTURING.
Bit 3 is the training hall.

**CONFIRMED, three menus and one byte.** Before `LOAD SAVED GAME` the game drew
exactly the three items mask `$00A1` names. After loading, with `$7EA8` = 0, it
drew nine and `TRAIN CHARACTER` was not among them. Poked to `$7F` and the menu
rebuilt, it drew ten with `TRAIN CHARACTER` between MODIFY and VIEW; poked back
to 0 later in the same session, the line went away again.

**The area scripts write the same value.** `tools/eclcensus.py
curse-of-the-azure-bonds --sites 7EA8` finds six statements in the whole
corpus, four of them `SAVE 127, =[$7EA8]` in `ECL01`, `ECL03`, `ECL50` and
`ECL51`; `ECL01+$01EF` writes 0 and `ECL01+$0228` compares against 124. `GEN
$2029` puts it back to 0 on the way out of the party menu and `INIT $08F8`
zeroes it at start-up. Nothing else on the six sides names the address.

**It is not in the save.** `$7EA8` is engine RAM, so a conversion has no C64
save byte to write for it and none to read. **PROBABLE, and stated as a
correspondence rather than an identity:** DOS gates the same menu item on a
word in its VM array at file offset `0xD51` of `SAVGAM<slot>.DAT`, which
`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)` found by poking it to 20 and watching
`TRAIN CHARACTER` appear. That word is at VM index 1704, which is past the 1024
addresses the C64 payload's header carries, so the two cannot be the same
storage and nobody has read the DOS routine that consumes it against
`GEN $14F8`. What would settle it: disassemble the DOS trainer's own use of
`es:[di+0x550]` and see whether it is shifted a bit at a time per class the way
`$2CCA` is, or compared against a level.

**What the mask does beyond opening the menu.** `GEN $150F` copies `$7EA8` into
`$2CCA` and `$1533 LSR $2CCA / BCC` consumes one bit per class about to be
raised, so 127 permits seven. Observed at both ends: 0 refuses everything and
127 raised two classes in one visit. **The per-class consumption itself is a
code reading only** -- no character here has eight ready classes, so no value
between the two was ever distinguishable, and one attempt to test it with
`$7EA8` = 1 was spoiled by the double-read keypress below.

## The five trainings

The party is the converted Tilverton party of `#192 (Convert a Curse of the
Azure Bonds DOS save into a C64 one, which the importer refuses today)`, with
**two fields written by us** into five of the six slots before the boot and
nothing else: experience at record `0x0E8` and platinum at `0x0C3`. MARK's slot
was left alone and is the control -- his 25,000 experience and 300 platinum are
unchanged on the disk the engine saved afterwards.

| character | race | before | after | die | charged |
|---|---|---|---|---|---|
| SHARA | human | cleric 5 | cleric 6 | 4 | 1000 gp |
| TRAVIS | dwarf | thief 5 / fighter 4 | thief 6 / fighter 5, one visit | 6 | 2000 gp |
| LEDERA | elf | magic-user 4 / fighter 4 | magic-user 5 / fighter 5, one visit | 5 | 3000 gp |
| MATHEW | human | paladin 5 | paladin 6 | 7 | 1000 gp |
| PHILIPPE | human | magic-user 5 | magic-user 6, learned HASTE | 4 | 1000 gp |

LEDERA's third thousand is a stray keypress rather than a rule: the key that
dismisses `YOU ARE NOW A LEVEL n` was read twice and started a second training
call, which charged for the class it then skipped. Nothing else in the session
took a charge it did not level for.

`tools/cursetrain.py diff` replays each pair:

| character | classes given to `plan` | fields | mismatches |
|---|---|---|---|
| SHARA | cleric | 13 | 0 |
| TRAVIS | fighter, then thief | 22 | 0 |
| LEDERA | fighter, then magic-user, learn 9 | 14 | 0 |
| MATHEW | paladin | 13 | 0 |
| PHILIPPE | magic-user, learn 48 | 13 | 0 |

TRAVIS' die of 6 was tried at all seven splits between the two rolls and all
seven reproduce, because only the total feeds `hp_max`.

## The six differences from Pool of Radiance

### 1. One press raises every ready class

`GEN $14F8` walks class slots 7 down to 0 and raises each that qualifies:

```
$1515  LDX $2C8F / LDA $2C9F,X          the level this class's experience reaches
       BEQ / CMP $7CC9,X / BEQ / BCC     skip unless it is above the stored one
       JSR $1553 / BCS                   the racial class limit
       JSR $21EA / BCS                   1000 gp, or NEED 1000 GP TO TRAIN
       LDA $2CD7 / BNE / LSR $2CCA / BCC the hall permission, below
       INC $7CC9,X / INC $2CAD / JSR $15E1 / JSR $1869
$154A  DEC $2C8F / BPL $1515
```

Pool of Radiance's `$1B8C` raises one class per visit, which is why
`docs/135-levelling.md` records the order a multi-class character trains in as
mattering there. **In Curse the order is not the player's**: it is slot order,
and the messages say so -- TRAVIS was told `5 FIGHTER` (slot 3) before the
thief (slot 2), LEDERA `5 FIGHTER` before `5 MAGIC-USER` (slot 0). CONFIRMED.

`goldbox/levelup.py`'s `plan` raises one class, and asked for TRAVIS' fighter
alone it gets `level`, `hp_max` and eight thief skills wrong -- because the
engine had raised the thief in the same visit. Chained through `apply_to` it is
exact. Whatever switches Curse on has to raise every ready class in one press,
or say that it does not.

### 2. The money

`GEN $2110` totals the five coin counts at `0x0BB` with the weights at `$2160`:
**1, 10, 100, 200, 1000 copper** for copper, silver, electrum, gold and
platinum, which is AD&D 1st edition's `1 gp = 20 sp = 200 cp` and `1 pp = 5 gp`
read out of the game. `$2192` compares the total against `$030D40` = 200,000
copper = **1000 gp**; `$21A5` zeroes all ten money bytes and writes
`(total - 200000) / 1000` back as **platinum** at `0x0C3`.

Same shape as Pool of Radiance, same consequence: anything under 5 gp is lost
at every training. Watched five times over, 2000 platinum stepping down 200 a
class. CONFIRMED.

### 3. The refusal

`UNABLE TO ADVANCE` -- `GEN` message 27, `$2056 LDY #$1B` -- where Pool of
Radiance says `LOW EXPERIENCE OR WRONG CLASS`.

**A refused training costs nothing.** With the gate shut, MATHEW and PHILIPPE
were each refused, and PHILIPPE's sheet still read PLATINUM 2000 afterwards and
her slot on the next save was unchanged. The mechanism is that `$205B JMP
$2031` leaves out the `$3918`/`$45F8` write-back the success path takes at
`$2073`/`$2076`, so the deduction `$21EA` made in the working record at `$7C00`
never reaches the roster. CONFIRMED for what a player sees; **PROBABLE for the
mechanism**, because the working record read 1800 immediately after one
refusal and 2000 after the other, and which read raced a redraw was not pinned.

### 4. The paladin's turning level, and the racial saving-throw bonus

`GEN $113F` gives a paladin `max(cleric, paladin - 2)`, and from 4 up that is
`effective + 1`. MATHEW at paladin 6 stored **5**, which is what
`levels.paladin_turn_offset=2` gives. Pool of Radiance has no class this can
happen to. CONFIRMED, first paladin.

**`GEN $0F19`'s sturdy-race bonus is CONFIRMED and was PROBABLE.** TRAVIS is a
dwarf with constitution 16, and the trainer rewrote his five saving throws:

| | col 0 | col 1 | col 2 | col 3 | col 4 |
|---|---|---|---|---|---|
| thief 6 row | 12 | 11 | 12 | 15 | 13 |
| fighter 5 row | 11 | 12 | 13 | 13 | 14 |
| lower of the two | 11 | 11 | 12 | 13 | 13 |
| less `16 * 2 / 7` = 4 on columns 0, 2, 4 | **7** | 11 | **8** | 13 | **9** |
| what `GEN` wrote at `0x09A`-`0x09E` | **7** | 11 | **8** | 13 | **9** |

The bytes he arrived with were `16 11 12 15 13`, the DOS conversion's, with no
dwarf bonus in them. The value is the engine's own.

### 5. `GEN $2515` hands a paladin and a ranger a trait

`$2515` removes trait ids 45 and 134 from the ten slots at `0x0AD`, then re-adds
**45 for anyone with a paladin level** and **134 for anyone with a ranger
level**, in the first empty slot. Not level-gated: it is rebuilt whenever the
recompute at `$0DD0` runs.

MATHEW's `0x0B6` went 0 to 45, which `goldbox/traits.py` calls *Protection from
Evil, 10' Radius*. Untrained MARK, also a paladin, still has an empty slot
there -- so the conversion does not write it and the engine does. CONFIRMED.

### 6. Spell capacity is never written, and `0x073` does not survive

SHARA is a cleric with wisdom 17 taken from 5 to 6, the level at which a Pool of
Radiance trainer writes a new capacity byte. `0x0EE`-`0x0F6` read nine zeroes
before and nine zeroes after. That is a third reading behind
`levels.stores_spell_capacity=False`, after `#192 (Convert a Curse of the Azure Bonds DOS save into a
C64 one, which the importer refuses today)`'s code census and its
memorise-screen demonstration. CONFIRMED.

Five of five trained characters came out with `char_class` at `0x073` = 0 where
the DOS conversion had written 5, 0, 13, 14 and 3. The only `STA $7C73` in `GEN`
is at `$194D`. Whatever Curse keeps there, a conversion's value does not survive
the first recompute.

## `HUMAN CHANGE CLASS`, and the first dual-classed Curse character

The tenth menu item is in the mask unconditionally, so it runs with no hall.
PHILIPPE, human magic-user 6, was offered CLERIC, FIGHTER, PALADIN and RANGER
and picked FIGHTER. Eighteen bytes changed, all in her slot:

| offset | field | before | after |
|---|---|---|---|
| `0x0B9` | `dual_class_slot` | 0 | 0 -- the magic-user's own slot |
| `0x0BA` | `dual_class_level` | 0 | **6** |
| `0x0C9` | `level_magic_user` | 6 | **0** |
| `0x0CC` | `level_fighter` | 0 | **1** |
| `0x0EB` | `class_bits` | 1 | **8** |
| `0x0A0` | `level` | 6 | 1 |
| `0x0E8` | `experience` | 45000 | 0 |
| `0x020`-`0x022` | `spells_memorised` | `2f 22 0f` | cleared |
| `0x076` / `0x0ED` | `hp_max` / `hp_rolled` | 33 / 21 | unchanged |
| `0x078`+ | the spellbook | nine ids | the same nine |

So the pair is (the old class's slot, the old class's level), a zero `0x0BA`
means "not dual-classed", the old class's entry in the level array is cleared
rather than left, and the character keeps its hit points and its book and loses
its memorised spells and all its experience. That is the writer's side of what
`#224 (0x0B9 and 0x0BA are documented both as an NPC marker and as the
dual-class slot)` read out of `GEN $23C9` and `$18EB`.

**What it does not settle**, and it is what `levelup.plan`'s dual-class refusal
is about: none of the four routines that behave differently *afterwards* has
been seen running -- `$15E7` refusing the die until the new class passes the old
level, `$124F` giving the old class its own hit-point term, `$1470` and `$1321`
leaving its slot out of the clamp and out of eligibility, `$20A3` putting it
back. PHILIPPE is fighter 1 with 0 experience and 2000 gp in
`WISH-SPEC-curse-dual-classed`; giving her experience and pressing TRAIN is one
session and settles all four.

The class list the game offered her is its own small question: wisdom 14 was
offered CLERIC and dexterity 17 was not offered THIEF, so the filter at
`GEN $23FC` is not AD&D 1st edition's prime-requisite rule as printed.

## What was still open, and where it went

A second session the same day closed the first two --
`docs/192-curse-dual-class.md` has both in full.

* **The divide at `GEN $11AB` is settled, and it is not probabilistic in the
  case that matters.** The random routine turned out to be in `LIBRARY` rather
  than nowhere: Curse's runs at `$2DC8` and Pool of Radiance's at `$2C48`, both
  Curse's ending exactly where `SAVEAZURE` loads and Pool of Radiance's landing four bytes below its own, which corroborates the technique rather than checking the second base. Both roll
  `1..class_count`; Pool of Radiance rounds up when the roll is at or below the
  remainder and **Curse only when it is below**, so a two-class Curse character
  always rounds down. CONFIRMED from the bytecode and from 40 engine-written
  divides.
* **The experience clamp lowering a number** was watched six times over,
  4,000 to 125,000, each `levels.clamp_threshold("fighter", n) - 1` exactly.
* **`TRAINER_MEASURED` still has one entry**, and `docs/192-curse-dual-class.md`
  lists the three changes still in front of it.

Also closed there: the four routines that make a dual-classed character
different, all watched, so `goldbox/levelup.py` no longer refuses one. The
paragraph above under `HUMAN CHANGE CLASS` that says *"none of the four
routines that behave differently afterwards has been seen running"* was true
when it was written and is not now.

## The specimens

Three disks in `~/wish-specimens/`, each read-only with a `provenance.toml`
naming the two fields we wrote:

| specimen | what |
|---|---|
| `curse-train-input` | the before state: experience and platinum written into five slots, MARK untouched |
| `curse-trained-party` | the engine's own `SAVE CURRENT GAME` after the five trainings |
| `curse-dual-classed` | the same disk one `HUMAN CHANGE CLASS` later |

## Driving Curse's front end

Four things cost time and are why `tools/cursetrain.py run` boots and serves
rather than pressing the keys itself.

* **`YES` on `LOAD SAVED GAME ? YES NO` answers only the KERNAL buffer**, as
  `tools/cursewarp.py` already records.
* **The save-disk prompt is not answered by a keypress alone** -- the save disk
  has to be attached first, by hand, because `porcmd` does not poll
  `handle_prompt`.
* **`INSERT SIDE # 1` needs `curserun`'s two `NOP`s** at `$459A` and `$459F`.
  The magic-user's spell menu loads from side 1, so a magic-user training hits
  this and a cleric's does not.
* **The key that dismisses `YOU ARE NOW A LEVEL n` is read twice** often enough
  to start a second training nobody asked for. That is what put a third
  thousand gold on LEDERA. Read the screen after every keypress rather than
  counting presses.
