# Writing a DOS record for Curse and Silver Blades

What it took to make `goldbox.dos.write` build the 422-byte Curse of the Azure
Bonds record and the 439-byte Secret of the Silver Blades one, what came out
byte for byte, and what a converted character still loses.

`docs/117-save-conversion.md` is the plan this serves and
`docs/141-dos-savegame.md` the container; the field table itself is
`goldbox/dos_layout.py`. This page is the writing side, for
`#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing can
be converted to DOS for the later titles)`.

## What a player could not do, and what the code actually did

Take a Curse or Silver Blades character off a C64 or Amiga save and convert it
to DOS. Not badly -- at all.

The failure was worse than a refusal. `goldbox.dos.write` built 285 bytes
whatever it was handed, so a C64 Curse party came back as six **Pool of
Radiance** records:

| C64 save | before | after |
|---|---|---|
| `WISH-SPEC-curse-h-engine-resave.D64`, six characters | 285 bytes each | 422 |
| `WISH-SPEC-ssb-d-engine-resave.D64`, six characters | 285 bytes each | 439, one with an 804-byte `.STF` |

Nothing raised. `goldbox.dos.read_character` would have identified the result
as Pool of Radiance, because the record size names the title, and no Curse or
Silver Blades game could ever have loaded it. `editor/convert.py` does not
offer the direction, so no user could reach it; `goldbox/amiga.py`'s
`write_por` calls `goldbox.dos.write` directly and could.

## The shape decides, and the character decides the shape

`goldbox.dos.write_shape` takes the title off the neutral character --
`NeutralCharacter.game`, which a reader sets and which is a
`goldbox.games.Game`, its key, or `None` for Pool of Radiance -- and every
width in the writer then comes off `goldbox/dos_layout.py`'s table for that
title. Nothing is a constant in the writer any more:

| what | Pool of Radiance | Curse | Silver Blades |
|---|---|---|---|
| record | 285 | 422 | 439 |
| each ability | 1 byte | a (current, base) pair | a pair |
| memorised spells | 16 slots | 84 | 75 |
| spellbook | 56 ids | 100 | 117 |
| class levels | 8 slots | 8 | **7**, no monk |
| spell-slot levels | 3 | 5 | 7 |
| slot arrays | cleric, magic-user | + druid | + druid + one unattributed |
| experience | 3 bytes | 4 | 4 |
| items | 63 bytes in `.ITM` | 63 in `.SWG` | **67 in `.STF`** |
| effects | `.SPC` | `.FX` | `.SFX` |
| `field_83_87` | 5 bytes | 5 | 4 |

The 67-byte item stride is the trap `#113 (Play DOS Curse far enough to save a
party with items)` closed once already, and it is why `item_from_c64` now takes
the stride rather than assuming one. `goldbox.dos.ITEM_TAIL` names the four
bytes Silver Blades has and the others do not; they are zero in 48 of 48 item
records driven out of the game, so the longer record is the shorter one with
four measured zeroes after it.

Pools of Darkness is refused rather than written. Its shape reads, there is no
C64 port to convert from, and nobody has written one of its 510-byte records;
`goldbox.dos.WRITES` is the list and `WrongTitleError` is the refusal, the same
one `to_neutral` makes in the other direction.

## What round-trips

A DOS record read into the neutral middle and written back, compared byte for
byte outside the writer's own declared mask -- `WRITE_UNSOURCED`,
`WRITE_UNSOURCED_LATER`, `WRITE_DEFAULTS` and `WRITE_DERIVED`, and never
whatever happened to differ. `tools/dosrecordwrite.py roundtrip` is the sweep.

The eight engine-written Curse records are the party driven for
`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)` and
`#256 (The neutral record has nowhere to put a dual-classed character's former
levels)`.

| corpus | records | identical outside the mask |
|---|---|---|
| Curse, engine-written for the dual-class work | 8 | **8** |
| Curse, shipped in the archives | 24 | **24** |
| Silver Blades, engine-written | 20 | 17 |
| Silver Blades, shipped | 24 | 22 |

**The five Silver Blades exceptions are one character.** MALACHITE, the dwarf
fighter 8 / thief 7 of the shipped party, differs at one byte -- the third of
`field_83_87` -- where he reads 0 and every other record of the title reads 1.
Three of the five are saves this project drove the game into writing and two
are shipped, so it is his value rather than a corpus artefact.

**Why he differs is now known, and it is not that he is a companion**
(`#304 (field_83_87 is written as a constant that the characters we rolled
ourselves do not hold)`, and
`docs/195-three-dos-record-bytes-named-from-the-overlays.md`). The byte is the
treasure share, and the only instruction in any of these engines that stores an
immediate into it stores 1 at the end of MODIFY CHARACTER, on KEEP -- watched
doing exactly that in DOSBox, where it moved one byte of 285 and left a control
character's record untouched. MALACHITE was never modified. His control byte,
which is the one that would make him a companion, reads 0.

Two more differences are masked and each is masked by name rather than by the
diff:

* **the name bytes past the count byte.** The neutral record carries a *name*,
  not whatever the engine left after it. Curse's shipped TRAVIS has a space at
  the seventh byte over a count of six; one record in 32.
* **`spells_castable_unattributed`**, Silver Blades' fourth slot array. Zero in
  44 of 44 records and attributed to no class, which is
  `#222 (Silver Blades' fourth spell-slot array is zero in every state anybody
  can create)`.

## The loop that puts the C64 game in the middle

Bytes matching is necessary and not sufficient. The strongest measurement
available without booting DOS is the loop `tools/dosrecordwrite.py loop` runs,
because the **C64 engine itself** is one of its steps:

    a DOS record  ->  neutral  ->  a C64 record  ->  the C64 game loaded it
    and saved it  ->  neutral  ->  a DOS record  ->  compared with the first

The two C64 saves are `WISH-SPEC-curse-h-engine-resave.D64` and
`WISH-SPEC-ssb-d-engine-resave.D64`, both the C64 game's own `ENCAMP > SAVE`
of a party this project converted, from `#192 (Convert a Curse of the Azure
Bonds DOS save into a C64 one, which the importer refuses today)` and
`#193 (Convert a Secret of the Silver Blades DOS save into a C64 one, which
the importer refuses today)`.

**The measurement below was taken once, on 2026-09-05, and its other half is
gone.** The DOS folders those two parties were converted from were
`work/curse/H-square-5-13` and `work/curse/SSB-D-paine-memorised`, and
`work/curse` was deleted by something else in the tree the same afternoon,
so the run cannot be repeated as it stands. The nearest specimen of the same
party, `WISH-SPEC-ssb-234-party-pair`, is a *different state* of those
characters and comparing against it shows real differences rather than
conversion faults. Re-taking it means putting a converted party through the
C64 game again, which is what `#192 (Convert a Curse of the Azure Bonds DOS
save into a C64 one, which the importer refuses today)` and `#193 (Convert a
Secret of the Silver Blades DOS save into a C64 one, which the importer
refuses today)` did.

| party | characters back byte for byte | what differs, and why |
|---|---|---|
| Curse slot H | 3 of 6 | three characters' `spells_castable` |
| Silver Blades slot D | 1 of 6 | three `spells_castable`, one name, one MALACHITE |

Every difference is one of three known things, and none of them is the DOS
writer:

* **`spells_castable`.** `goldbox/c64_codec.py`'s `RecordShape.spell_slots` is
  `False` for both later titles -- the C64 records of those two games have
  nowhere to keep how many spells are still free -- so the DOS-to-C64 leg
  reports the loss (`NO_SPELL_SLOTS`) and the C64-to-DOS leg has nothing to
  give back. **The section below shows the DOS engine putting it back on
  load**, so this costs a converted cleric nothing.
* **the name.** `Guy de Valois ` comes back as `GUY DE VALOIS`, 13 bytes
  over 14. That is `goldbox.dos.c64_name` doing what `#193 (Convert a Secret
  of the Silver Blades DOS save into a C64 one, which the importer refuses
  today)` proved in the running game: the C64 draws its text in the
  uppercase/graphics set, where a lower-case letter is a punctuation mark,
  and SSI's own C64 copy of that party holds `GUY DE VALOIS` too.
* **MALACHITE's treasure-share byte**, above.

## The DOS game loaded it

`#192 (Convert a Curse of the Azure Bonds DOS save into a C64 one, which the
importer refuses today)` and `#193 (Convert a Secret of the Silver Blades
DOS save into a C64 one, which the importer refuses today)` set the
standard: convert, boot the game, read the sheets, and diff the engine's own
resave. The record half of that was done for Silver Blades on 2026-09-05.

The six records `tools/dosrecordwrite.py from-c64` built out of
`WISH-SPEC-ssb-d-engine-resave.D64` were staged into DOS Silver Blades under
DOSBox beside an unchanged `SAVGAMD.DAT` -- **the container is the engine's,
because no Silver Blades container can be written yet** -- and `LOAD SAVED
GAME` took them.

* The party panel drew all six names with their own armour class and hit
  points: GUY DE VALOIS 6/95, PAINE 6/74, EPONA 7/91, MALACHITE 7/58,
  DOMINIC 6/78, MORGAINE 7/35. Six of six against the records.
* `VIEW CHARACTER` on Guy de Valois drew MALE, 20 YEARS, LAWFUL GOOD, HUMAN,
  PALADIN, LEVEL 8, HIT POINTS 95/95, EXPERIENCE 202,750, STR 18(00) INT 14
  WIS 18 DEX 18 CON 18 CHA 17, ARMOR CLASS 6, THAC0 10, DAMAGE 1D2+6,
  ENCUMBRANCE 1490, MOVEMENT 12.
* `ITEMS` listed all twelve out of the 804-byte `.STF` this writer built:
  MAGE SCROLL 3 SPELLS, 30 ARROWS +1, LEATHER ARMOR +1, SCALE MAIL +2,
  GAUNTLETS OF OGRE POWER, WAND OF ICE STORM, BRACERS AC 6, HALBERD +2,
  MACE +1, LONG SWORD +1, SHIELD +2, PLATE MAIL +1. Every name, plus and
  quantity, at the 67-byte stride.
* PAINE drew as a **RANGER** level 8 -- the class that arrived as a paladin
  before `#193 (Convert a Secret of the Silver Blades DOS save into a C64
  one, which the importer refuses today)` -- and his `SPELLS` list held
  INVISIBILITY TO ANIMALS, a druid spell in Silver Blades' own 1..117 id
  space, converted through the C64 and back.

Then `SAVE CURRENT GAME` to the same slot, and the engine's own rewrite
against what we handed it: **31 bytes of 2,634 differ, and every one is a
byte this writer declares.**

| what moved | bytes | why |
|---|---|---|
| `heap_104` | 15, three in each of five records | live heap, `WRITE_UNSOURCED` |
| `item_chain` | 3, Guy de Valois | the item list head, rebuilt by the loader |
| `effect_chain` | 3, MALACHITE | the effect list head, likewise |
| `spells_castable` | 10, across PAINE, DOMINIC and MORGAINE | **the engine derives it on load** |

**That last row settles something the C64 side could only report as a loss.**
The C64 records of Curse and Silver Blades have nowhere to keep how many
spells are still free (`RecordShape.spell_slots` is `False` for both), so this
writer put zeroes in. DOMINIC went in with a zeroed cleric array and the
engine's own resave holds `05 05 04 03 00 00 00`, which is byte for byte what
the DOS specimen of the same cleric 8 holds; MORGAINE's magic-user array came
back `04 03 03 02 01 00 00`, likewise. PAINE, a ranger 8, was given his one
druid slot. So the field is **derived by the destination** and the conversion
loses nothing -- the demonstration in the running game that
`.claude/rules/conversions.md` asks for before a field may go unreported.

The `.STF` and `.SFX` differences are the same kind. The engine filled in the
item record's cached display line -- ours is empty and its rewrite reads
` No   Mage Scroll 3 Spells ` -- and relinked the effect records' far
pointers, both of which this writer leaves empty by measurement rather than
by omission.

Both halves are in the specimen tree:
`WISH-SPEC-ssb-299-converted-and-resaved` is our writer's output and is not
evidence about the game, and `WISH-SPEC-ssb-299-engine-resave` is the engine's
own save of it.

## Two bytes the Curse decompilation named

`simeonpilgrim/coab` is a re-implementation of the DOS Curse overlays that
`docs/117-save-conversion.md` and `tests/test_coabsource.py` already read as
corroboration. Its `Classes/Player.cs` declares a player struct of
`StructSize = 0x1A6` -- the 422 bytes of the Curse record -- so its offsets
are file offsets, and against `goldbox/dos_layout.py`'s Curse table it
agrees on every field but two (`#305 (Two DOS record bytes have one name
from Pool of Radiance and another from the Curse decompilation)`).

**`paladin_cures`, and it is now a named field.** coab calls Curse record
`0x191` `paladinCuresLeft`: character creation writes 1 (`ovr018`), CURE
DISEASE is offered only while it is above zero and decrements it (`ovr020`),
and a refresh sets `((paladinLevel - 1) / 5) + 1` (`ovr013`). The measurement
agrees across four record shapes and six titles:

| shape | where | paladins holding 1 | everybody else |
|---|---|---|---|
| 422 (Curse, Gateway) | `0x191` | MATHEW, MARK, DEMELTINA, JERRICUS | 0 in 20 |
| 439 (Silver Blades) | `char_class + 1` | Guy de Valois, DEMELTINA | 0 in 18 |
| 510 (Pools of Darkness, Treasures) | `char_class + 1` | Guy de Valois, DEMELTINA, MAXWELL, JERRICUS | 0 in 22 |

CONFIRMED that the byte is 1 for a paladin and 0 for everybody else, in all
four shapes. It stays 1 after HUMAN CHANGE CLASSES -- DEMELTINA is a cleric 1
with former paladin 5 and still reads 1 -- so the writer derives it from the
class the character holds **or** the class a dual-classed one left.

**Silver Blades does not use it the way Curse's code says, and that is a
negative result worth having.** Staged on Guy de Valois in the running game:

| staged | what the sheet offered | after one CURE |
|---|---|---|
| 0 | `ITEMS HEAL CURE EXIT` | `ITEMS HEAL EXIT` |
| 2 | `ITEMS HEAL CURE EXIT` | `ITEMS HEAL EXIT`, and the engine's resave holds **0** |

So in Silver Blades the byte does not gate whether CURE is offered -- at zero
the command is still there -- and it does not count uses either, since two did
not buy two. What it does do is get **cleared** by a cure rather than
decremented, which is the one thing that ties it to cure-disease at all in
that title. Curse's own code decrements it and refuses the command at zero
(`CanCastCureDiseases`), so the two engines differ.

The consequence for the writer is a change of justification rather than of
value. It writes 1 for a paladin because **that is what every engine-written
paladin record holds**, not because a converted paladin gains a cure by it:
what a player gets from the byte in Silver Blades is UNMEASURED and may be
nothing. The C64 has no counterpart to convert from -- no byte of
`goldbox/layout.py` separates a paladin that way in the 78 C64 records here,
12 of them paladins, and the only two bytes that separate paladins at all are
the class byte and one that tracks level.

**`field_83_87` is three named bytes and two unnamed.** coab's run at Curse
`0x0F6`-`0x0FA` is `field_F6`, `control_morale`, `npcTreasureShareCount`,
`field_F9`, `field_FA`. `control_morale >= 0x80` is the engine's own test for
"this is an NPC I run myself", in nine places, and the share count is read only
for such a character. Silver Blades' four bytes are that run with the first
one gone: `00 01 00 00` against Pool of Radiance's `00 00 01 00 00`, and the
byte that differs for MALACHITE is the share.

That gives the neutral `npc` field a DOS home, which
`goldbox.dos.WRITE_DROPPED` still says it has none of. **The reading is now
CONFIRMED out of each title's own shipped `GAME.OVR` rather than from coab**,
and the measurement that seemed to contradict it does not:
`docs/195-three-dos-record-bytes-named-from-the-overlays.md` has the constants
each engine stores and compares, the eight-record Treasures of the Savage
Frontier party whose seventh member holds `0xB2`, and why MALACHITE's share of
zero says nothing about companions.
`#303 (The DOS record may hold the NPC flag that the conversion reports as
having nowhere to go)` carries what is left, which is the wiring and one
unmeasured value.

## What a converted character still loses

Everything below is a Curse or Silver Blades character coming *from* the C64.

| | what happens | why |
|---|---|---|
| the sheet portrait | not written | those two titles' sheets draw none: the pair is zero in all 76 records here |
| the combat figure | the game's own default | `#130 (A converted DOS party arrives with six identical combat figures, not its own)` |
| lower case and trailing blanks in a name | folded to capitals, blanks cut | the C64 draws no lower case, and SSI's own C64 copy of the same party is in capitals -- a limit of the destination on the way out, and it does not come back |
| spell slots free today | written zero | **and the DOS engine fills them in on load**, measured above, so nothing is lost |
| `paladin_cures` | derived from the class | the C64 has no such byte; what it is worth in Silver Blades is UNMEASURED |
| `npc` | not written | `#303 (The DOS record may hold the NPC flag that the conversion reports as having nowhere to go)` may give it a home |

## The container, written and loaded (#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing can be converted to DOS for the later titles))

The DOS engine loads a party *from* `SAVGAM<slot>.DAT`: it holds the six
character filenames, the quest flags, the clock, the party's place and, in
Curse, the area's own script. `goldbox.dos.write_dos_save` built only Pool of
Radiance's 13137 bytes until `#299 (goldbox.dos.write builds only Pool of
Radiance's record, so nothing can be converted to DOS for the later titles)`
made it shape-driven on both ends: it reads the C64 party through
`c64_save.container_for(title)` and builds the DOS file to
`dos_savegame.save_shape_for(title)`, so a Curse party comes out a 13149-byte
`SAVGAMD.DAT` with its `ECL2.DAX` script staged and a Silver Blades one 5469
bytes with none.

**Loaded and played, both titles, from a save built from nothing.** The whole
container -- no template, no engine save underneath -- was converted from
each title's own engine-written C64 disk, loaded in the DOS game under
DOSBox, and its resave diffed against what we handed it:

| title | container | `LOAD SAVED GAME` | engine resave differs |
|---|---|---|---|
| Curse of the Azure Bonds | 13149, script staged | six sheets, PHILIPPE FIGHTER 1 EXP 0 carrying magic-user 6 | 204 of 13149 bytes |
| Secret of the Silver Blades | 5469, no script | six drawn with own AC/HP, party walked into area 16 | 175 of 5469 bytes |

Every differing byte is one the writer declares: ~170-198 in the name-table
heap and menu scratch the engine fills, the two square-block scratch bytes it
recomputes from the map on the first step, the wall-colour words `$49FD`/`$49FE`
the arriving area's script writes on entry, and a handful the engine advanced
during play (`$4FC6`, `$5079` in Curse, a quest flag `$4A3C` 2->3 in Silver
Blades). Not one is a field the conversion sourced wrong. The specimens are
`WISH-SPEC-{curse,ssb}-299-built-from-nothing` (ours) and
`WISH-SPEC-{curse,ssb}-299-whole-engine-resave` (the engine's).

**Three things the container writer had to get right, none of them a size
change:**

* **The wall triples move.** Pool of Radiance keeps its wallset/wallmap in the
  variable array at `$4AFA`/`$4AFD`; Curse and Silver Blades hold those at
  zero and write the triples into the twelve-byte block inside the square
  block instead (`dos_savegame.put_wall_block`). `$4AFD` is a quest flag in
  the later titles -- 255 in every played Silver Blades container and on its
  C64 disk -- so writing a wallmap there would overwrite one.
* **The DAX container number is the DOS file, not the C64 side.** Pool of
  Radiance and Curse pack one `ECL<n>.DAX` per C64 side, so the area table's
  disk column is the DOS number too (29 of 29 and 24 of 24 rows checked file
  by file). Silver Blades packs six C64 sides into three DOS containers --
  `ECL1` holds `$03`/`$10`/`$20`-`$22`, `ECL2` holds `$11`/`$30`-`$44`, `ECL3`
  holds `$50`-`$63` -- so 21 of its 22 rows disagree, and
  `goldbox.dos.dos_dax_number` reads the answer off the DOS files.
  **The table is not wrong and must not be "fixed":** its column is the side
  the C64 loader asks for.
* **`$49FC` and `$49FF` are not zero in the later titles.** Each engine's save
  routine mirrors two interface globals into the array just before writing it
  (Curse `GAME.OVR:0x1F8D4`, Silver Blades `0x26AE0`), and the loader unpacks
  them again -- so a converted save must carry the initialiser's 4 and 3,
  which every Curse and Silver Blades container holds, rather than the zero
  Pool of Radiance writes and the portrait gate Pool of Radiance keeps at
  `$49FF`. The later titles draw no sheet portrait, so `$49FF` is the two
  engine flags there, not a face.

## The one byte the plan flagged, sourced (#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing can be converted to DOS for the later titles))

`$503F` reads 4 in a played Curse container and 0 everywhere else, and Pool of
Radiance's byte account does not name it. Read off the overlays rather than
guessed: `GAME.OVR:0x0B1F` (Curse) and `0x0DD4` (Silver Blades) are the ECL
VM arithmetic handler's divide arm storing the division remainder into VM word
`$6E3F`, which the file's contiguous naming calls `$503F`
(`docs/163-dos-vm-address-map.md`). It is the only site in either overlay that
writes it, nothing reads it, and no script of either title names it
(`tools/dosptrfields.py`, `tools/eclcensus.py`). So the conversion writes it
**zero** with that reason in `SAVGAM_UNSOURCED_LATER`, and the running game
confirmed the zero loads and plays. It is a stale VM register, not party
state.

## What is left

The library now writes the whole later-title save; what remains is
`editor/convert.py`'s `DIRECTIONS` rows, so the four cells of `#51 (Every
permutation of DOS, C64 and Amiga, in both directions)` are offered -- a
`junior-dev` step, gated behind `WISH_EXPERIMENTAL_*` and needing Donald's
wording. `#234 (A dual-classed Curse or Silver Blades character converted to
DOS loses the class he trained out of)` is unblocked: PHILIPPE now loads from
a whole Wish-built Curse save with her magic-user 6 on the sheet.

## Where the tests are

`tests/test_doslatertitles.py`, 42 of them, none skipped on this machine. They
divide into the tables (every field of every title has a target and a
disposition), the shapes (each width comes off the title's table, tested
without any save), and the round trips above. With the one line that picks the
title reverted to Pool of Radiance, 28 of the 42 fail.
