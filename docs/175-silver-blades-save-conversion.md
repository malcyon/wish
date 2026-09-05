# Converting a DOS Secret of the Silver Blades save to the C64

What a Silver Blades conversion writes, where the two ports disagree, and what
was watched in the running game. `#193 (Convert a Secret of the Silver Blades
DOS save into a C64 one, which the importer refuses today)` is the ticket;
`docs/117-save-conversion.md` is Pool of Radiance's and Curse of the Azure
Bonds' account of the same job, and this page carries only what is this
title's own.

Grades follow `docs/50-experiments.md`'s scale.

## The container is Curse's under a different name

One 7424-byte `SAVEDBASH` at `$4B00`, and every page at the same offset as
Curse of the Azure Bonds': header `+$000`-`+$3FF`, eight character pages from
`+$400`, a table of the party's names at `+$C00`, eight item pages from
`+$1000`, the walked map at `+$1800`, the roster at `+$1C00`. CONFIRMED,
`tests/test_ssbconvert.py::test_the_container_is_curses_geometry_under_a_different_name`.
The row is `goldbox/c64_save.py`'s `SECRET_OF_THE_SILVER_BLADES`.

**Three header rows differ from Curse's and one is still PROBABLE.**

| | Curse | Silver Blades | grade |
|---|---|---|---|
| `+$E7`-`+$E9` | copied (two bytes) | **copied**, three bytes | CONFIRMED as the addresses; see below |
| `+$EA` | zeroed as unused | **zeroed, and named**: `DUNGEON $0B0E` stores a byte from its own table there and reads it back at `$0B1E`, so nothing in the save reaches that read | CONFIRMED |
| `+$FD`-`+$FE` | zeroed; the arriving script refills them | **copied** from the DOS save | CONFIRMED as the addresses |
| the flag page | `+$120`-`+$1F8` | **`+$120`-`+$1FF`** | CONFIRMED |
| the name table | keyed by slot | **keyed by marching order** | PROBABLE |

**The cache and the disk hint are Curse's, read out of this title's own
overlays.** `CAMP $0CA5` is `LDX #$18 / LDA $7F13,X / ORA #$80 / STA $4DC0,X`
on the save path with `LDA $4BF2 / ORA #$80 / STA $4DC8` after it, `GEN $2469`
is the same loop, and `GEN $2424` is `LDA $4DC0,X / STA $7F13,X` with **no**
`ORA` on the load path -- so a converted save has to set bit 7 on every slot
it fills, because nothing on the load path will. `CAMP $0C65` is
`LDA $7F12 / STA $4BEE` and `GEN $228E` is `LDA $4BEE / STA $7F12`, so the
disk hint is `+$EE`. CONFIRMED, and both are confirmed a second time by the
game booting a disk built that way.

**`+$E7`-`+$E9` and `+$FD`-`+$FE` are per-area constants an arriving script
sets and no script reads.** An address census over all twenty-two `ECL`
scripts, on both ports (`tools/eclcensus.py`), gives `$4BE7` and `$4BE8` 18
writes and no reads across seventeen scripts, `$4BE9` 10 writes across seven,
`$4BFD` 8 and `$4BFE` 16. The party's own value is in the DOS save at the same
ECL address, so the conversion copies it rather than writing a zero nobody has
measured -- and the engine's own resave of a converted party held the same
five bytes, where Curse's put 8 and 9 back over the zeroes it was given.

## The flag page runs five bytes further than Pool of Radiance's

Pool of Radiance's quest flags are `$4A20`-`$4AF8` and stop there because
`$4AFA` and `$4AFD` are its wallset and wallmap triples
(`goldbox/dos_savegame.py`). **Silver Blades keeps its wall triples in the
twelve unnamed bytes of the square block instead** (`#253`), and its scripts
use the page to the end: `$4CFD` -- the same word index as Pool of Radiance's
wallmap -- is named by seventeen of the twenty-two scripts, 33 reads and 63
writes, and `$4CFE` and `$4CFF` by eight and one.

So the window is `+$120`-`+$1FF`, 224 bytes, and it is per title:
`Container.quest_flags`. **CONFIRMED in the running game.** With the old
window the conversion wrote zero at `+$1FD` and the C64 engine's own
`ENCAMP > SAVE` put `$FF` back there; all three driven DOS Silver Blades
containers hold 255 at that word and the shipped one holds 0.

**Curse of the Azure Bonds has the same gap and it is not fixed here.** Its
own census names `$4CFE` (16 reads, 8 writes) and `$4CFF` (4 writes), so a
converted Curse party loses those two bytes. Filed separately rather than
changed under this ticket, because Curse's conversion was proven in the game
with the narrow window and re-proving it is that ticket's work.

## The name table may be keyed the other way round

In both engine-written Curse saves, entry *n* of the table at `+$C00` is the
name of the character in slot *n*. In the shipped `SAVEDBASH`, entry 0 is GUY
DE VALOIS and slot 0 is MORGAINE -- the table runs in marching order and the
slots run the other way, which is `goldbox.dos.marching_slot`'s top-down fill.

Everything else in that file is slot-ordered: roster block *n* carries slot
*n*'s armour class and hit points, six of six. So it is the table that is
reversed and not the file.

**PROBABLE, and this is what would settle it.** The party this ticket
converted has its own marching order, so writing the table in marching order
and reading the six sheets against the six panel lines cannot separate the two
readings -- both put GUY DE VALOIS first. A save whose marching order is *not*
the reverse of its slot order would: reorder a DOS party so that the character
in C64 slot 5 is not the head of the marching order, convert it, and read the
panel. If the names still line up with the sheets, the table is in marching
order; if they are shuffled, it is in slot order and `names_in_marching_order`
comes off.

## The record: four things this title does that Pool of Radiance does not

### A name with a lower-case letter is not a name on a C64 screen

**CONFIRMED, watched twice.** The C64 draws in the uppercase/graphics
character set, where the screen code for a byte in `$61`-`$7A` is that byte
less `$40`. Silver Blades' own DOS pregen is named `Guy de Valois ` and,
converted byte for byte, his name drew in the party panel and at the head of
his character sheet as

    G59 $% V!,/)3

`u` is `5`, `y` is `9`, `d` is `$`, `e` is `%`, `a` is `!`, `l` is `,`, `o` is
`/`, `i` is `)` and `s` is `3`. The other five characters of the same party
are named in capitals and drew correctly.

**SSI did the same thing themselves**: the C64 `SAVEDBASH` holds
`GUY DE VALOIS` for the character DOS calls `Guy de Valois `, and that is the
only field of the six shipped characters where the two ports' records differ
for a reason that is not a separate roll. So `goldbox.dos.c64_name` folds the
name to capitals and cuts its trailing blanks, and the second run of the same
disk drew `GUY DE VALOIS` in the panel.

**This is the DOS-to-C64 path only.** Any other source a C64 record is written
from can still carry a lower-case name, and `goldbox/c64_codec.py` is where it
would be closed for all of them.

### A DOS ranger is a C64 paladin if the class mask is copied

**CONFIRMED from both sides.** DOS gives the paladin and the ranger one bit
between them -- `class_bits` `$40` for Curse's MATHEW (paladin 5) and ARGORA
(ranger 5), and for Silver Blades' GUY DE VALOIS (paladin 8) and PAINE (ranger
8) -- and the class *number* is what tells them apart. The C64 gives the ranger
bit 7 of its own: the C64 twin of Curse's ranger reads `$80` with `0x0D0` = 5,
and PAINE's C64 twin reads `$80` with `level_ranger` 8.

`class_bits` used to be DIRECT, copied byte for byte, so PAINE arrived on the
C64 with `class_bits` `$40` and `level_ranger` 8 -- a paladin holding a
ranger's levels, which is a combination no C64 save of either title holds.
`goldbox.dos.neutral_class_bits` rereads **bit 6 only** from the level array
and leaves every other bit as the record has it;
`goldbox.dos.dos_class_bits` folds it back on the way out, so no DOS record's
own byte moves through a round trip. `goldbox/amiga.py`'s `CLASS_BIT` had
recorded the same fact from the other side and the Amiga codec has always
computed the mask rather than copying it.

**Curse of the Azure Bonds had the same defect and it shipped**, because the
party `#192` proved that conversion on had two paladins and no ranger. The fix
is in `goldbox/dos.py` and covers both titles.

### Items are 67 bytes, and the four extra ones hold nothing

`item_to_c64` demanded 63 and refused every Silver Blades item. Every field it
reads is below `0x03E` and so is at the same offset whichever title wrote it
(`#113`); the four extra bytes are `0x03F`-`0x042` and **read `00 00 00 00` in
48 of 48 item records**, 24 of them distinct, across every `.STF` this project
made by driving the game. A non-zero one is refused rather than dropped in
silence.

**CONFIRMED in the running game**: the twelve items DOS Silver Blades' mayor
of New Verdigris hands the party read back on the C64 `ITEMS` screen as
PLATE MAIL +1, SHIELD +2, LONG SWORD +1, MACE +1, HALBERD +2, BRACERS AC 6,
WAND OF ICE STORM, GAUNTLETS OF OGRE POWER, SCALE MAIL +2, LEATHER ARMOR +1,
30 ARROW +1 and MAGE SCROLL 3 SPELLS. That is twelve of twelve, and it settles
a second question: **the DOS item type index names the same `ITEM<nn>` entry
on the C64** in this title, whose indices are renumbered against Pool of
Radiance's.

### The free-spell-slot array is not there, demonstrated

`0x0EE`-`0x0F3` is Pool of Radiance's array of how many spells of each level a
caster may still memorise. Silver Blades does not use it, on two independent
readings:

* a reference census over its 347 files finds `$7CEE`-`$7CF3` named twenty
  times and **not once in a code file** -- every hit is a `PIC`, `COMPIC`,
  `SPRITE` or `WALLSET`, which is what a 16-bit value looks like in bitmap
  data. Pool of Radiance has 24 in `GEN` and `POOLRB` alone;
* **six records the C64 engine itself wrote back** hold zero there, including
  a cleric 8 and a magic-user 9 who have memorised nothing and would have
  every slot free.

**And the destination derives it, watched.** Wish wrote zeroes at
`0x0EE`-`0x0F3`; `ENCAMP > MAGIC > MEMORIZE` on MORGAINE, a magic-user 9, put
up her book of spells and let BURNING HANDS be picked **four times and no
more** -- six presses, four taken. `MORGAINE'S CHOSEN SPELLS` listed exactly
four, and the record's memorised list at `$7C61`-`$7C64` held `89 89 89 89`,
which is spell id 9 with bit 7 set, four times. Four is a magic-user 9's
first-level allowance. The ceiling came from her class and her level, because
nothing in the save carried it. So the grade for `spell_slots=False` moves
from PROBABLE to **CONFIRMED**.

The same screen confirms two other things. Her 117-spell book, packed into the
C64's sixteen bytes, drew as ten first-level and four second-level spells with
`NEXT` for the rest. And the memorised list's span -- 74 slots at `0x01B`, the
only measured title whose list does not start at `0x020` -- reads back exactly:
the four ids sit at `0x061`-`0x064` and `0x065` holds 17, which is MORGAINE's
strength, the first byte of `abilities_second`.

## What the running game showed, six checks

One VICE session per build, pool slots 1 and 0, 2026-09-05, on a save disk
`tools/ssbdisk.py` built from `work/curse/SSB-D-paine-memorised` slot D with
`unwritten == []` and no template.

| check | what it showed |
|---|---|
| the loader takes the disk | `LOAD SAVED GAME` on the party menu, no picker and no file list; the eight slots came back as a party. There is no save picker in this title, so what the check really tests is whether the loader accepts a container Wish built |
| the party panel | GUY DE VALOIS, PAINE, EPONA, MALACHITE, DOMINIC, MORGAINE with AC and hit points 6/95, 6/74, 7/91, 7/58, 6/78, 7/35 -- the DOS save's own, in the DOS marching order, which is the reverse of the slot array |
| the six sheets | six of six matched the DOS save on sex, age, alignment, race, class, level, experience, hit points, all seven abilities, armour class, THAC0, movement, encumbrance and money. The only differences are our own wording: our sheet writes MALACHITE's classes in the record's order (`THIEF/FIGHTER`) where the game writes them in class-bit order (`FIGHTER/THIEF`) |
| a caster's memorise screen | above |
| the abilities | in the sheet table above; `0x065` is the array this title's `GEN $1F0A` copies forward into `0x014`, seven bytes rather than Curse's twelve |
| `ENCAMP > SAVE`, diffed | below |

The party then walked two squares south from 3,3 to 3,5 with the clock moving
4:15 to 4:18, read off `$C04B` and off the status line together.

## The engine's own resave

`tools/ssbsavediff.py` against what Wish wrote, taken standing on the same
square at the same minute, before the party walked:

```
600 bytes differ in 134 runs, of 7424

  by region:
      594  [engine] the area map the engine builds on load
        5  [engine] the loaded-files cache, refilled as files load
        1  [engine] the six clock digits, which tick as time passes
```

**Nothing differs in any region a conversion writes.** Byte for byte
identical: the eight character slots, the name table, the eight item pages,
the roster, the combat icon table, the quest-flag page, the per-script
scratch, the position, the resident `GEO`, the indoors flag, the disk hint,
the script id, the portrait switch, and the five per-area bytes at `+$E7` and
`+$FD` that this title copies where Curse zeroes.

A second `ENCAMP > SAVE` after the two steps differs from the first in **six
bytes**: the party's y, the previous square, two bytes of per-script scratch
at `+$104`/`+$105`, and one clock digit. The area map at `+$1800` did not
move, which Curse's did over the same distance.

The four saves are in the specimen tree as `ssb-d-engine-resave`,
`ssb-d-engine-resave-walked`, `ssb-d-converted-resave` and
`ssb-d-converted-resave-walked` -- the first engine-written Silver Blades
saves this project has had.

## What is still wrong, and is not this page's to fix

* **A converted Silver Blades human arrives with sixty feet of infravision.**
  `goldbox/c64_codec.py`'s `INFRAVISION` table is keyed by Pool of Radiance's
  race numbering, where 7 is human, and Silver Blades numbers human 6 -- which
  in that table is the half-orc. All five humans of the converted party read 6
  at record `0x0D5` where all six shipped C64 records read 0, and the engine's
  own resave left the 6 alone. `$7CD5` is named three times in this title's
  code files, twice in `COMBAT`.
* **A converted cleric cannot turn undead.** `turn_power` at `0x0A4` reads 0 in
  every DOS record of every title, and the C64 keeps a real number there --
  9 for the shipped cleric 8 and 7 for the shipped paladin 8, which is exactly
  what Curse's table and its paladin offset compute for those levels. Silver
  Blades' `turn_power` table in `goldbox/levels.py` is empty, so nothing can
  compute it yet.
* **`missile_attack_adjustment` at `0x0EC` is written as zero**, and the C64
  engine rewrites it from dexterity when a fight starts (`COM.PREP $1633`,
  `goldbox/layout.py`). Between the conversion and the first fight a converted
  archer's ranged THAC0 is short by their dexterity bonus.

## Where the pieces are

| | |
|---|---|
| the container row | `goldbox/c64_save.py`, `SECRET_OF_THE_SILVER_BLADES` |
| the record shape | `goldbox/c64_codec.py`, `SILVER_BLADES_RECORD` |
| the DOS record table | `goldbox/dos_layout.py`, `SECRET_OF_THE_SILVER_BLADES` |
| the areas | `goldbox/areas.py`, `AREAS_SILVER_BLADES`, twenty-two rows |
| building a save disk | `tools/ssbdisk.py` |
| driving the game | `tools/ssbrun.py`, on `tools/ssbwarp.py`'s boot |
| diffing a resave | `tools/ssbsavediff.py` |
| the shipped twins | `tools/ssbtwins.py` |
| the tests | `tests/test_ssbconvert.py` |
