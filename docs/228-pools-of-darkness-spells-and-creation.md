# Pools of Darkness' spell-slot rows, spell table and creation menus

What the fourth title lets a character hold and a player make, read out of the
player's own DOS `GAME.OVR` and `GAME.EXE` and cross-checked against the Amiga
executable. `goldbox.spells.POOLS_OF_DARKNESS` carries the numbers and
`tests/records/test_pod_spells.py` reads them back off the game;
`tools/dos/dospodtables.py` is the instrument.

Before this, `goldbox.spells.BY_KEY` held three keys and `for_game` fell back
to Pool of Radiance, so `capacity_by_class(..., "pools-of-darkness")` answered
three spell levels and ids 1-55 for a record with nine slots a class and a
125-byte spellbook.

## Where the engine keeps it

| what | DOS | Amiga |
|---|---|---|
| slot builder | `GAME.OVR:0x03808A` | `0x03BE3A` |
| cleric helper: rows, wisdom bonus, wisdom ceiling | `GAME.OVR:0x03860C` | `0x03C494` |
| intelligence ceiling | `GAME.OVR:0x03874F` | `0x03BE3E` |
| cleric rows | `DS:71D4` | `0x04EE43` |
| paladin rows | `DS:755B` | `0x04EF48` |
| ranger rows | `DS:7688` | `0x04F04D` |
| magic-user rows | `DS:77B5` | `0x04F152` |
| spell table, 16 bytes an entry | `DS:651A` | `a4-$58D8` |
| creation | `GAME.OVR:0x0147D8` | unread |

The Amiga addresses are file offsets in the executable; its row tables are
where the level-1 row begins.

**Nothing above is found by a committed address.** The builder is the one of
three `add di, 0x17d` `FillChar` sites carrying the class loop; each table
offset comes out of the instruction that indexes it; creation is the one of six
`FillChar(record, 510, 0)` sites that then menus a race out of counted strings.

## The rows

**Seven class slots, 0-6**, which the builder's loop closes on
(`cmp byte ptr [bp-1], 6 / je +3 / jmp near`) and the record's seven-byte
`class_levels` at `0x151` matches. Four of them have rows:

| class slot | rows from class level | table | columns | lands in |
|---|---|---|---|---|
| 0 cleric | 1 | `DS:71D4` | 1-7 | cleric array, **assigned** |
| 3 paladin | 9 | `DS:755B` | 1-4 | cleric array, added |
| 4 ranger | 8 | `DS:7688` | 1-3 and 5-6 | druid array 1-3, magic-user array 1-2, added |
| 5 magic-user | 1 | `DS:77B5` | 1-9 | magic-user array, added |

**29 is the ceiling.** The builder and the cleric helper both clamp with
`cmp byte ptr [bp-2], 0x1d / jbe / mov byte ptr [bp-2], 0x1d`, so a class level
above 29 reads row 29 and 29 rows are the whole progression. CONFIRMED, and
twice again on the Amiga (`cmpi.b #$1d`).

**The tables hold running totals**, where Curse's and Silver Blades' hold
deltas, and the cleric's helper *assigns* where the other three *add*. So the
committed rows are what a character sheet shows, with no accumulation on our
side. CONFIRMED.

The magic-user's and cleric's rows are AD&D 1st edition's published tables to
level 29. The ceilings: magic-user 29 is `7 7 7 7 6 6 6 6 6`, cleric 29 is
`9 9 9 9 9 9 7` (its loop stops at column 7, so cleric spell levels 8 and 9 of
the nine-wide array stay zero), the paladin plateaus at level 20 with
`3 3 3 3` in the *cleric* array, and the ranger at 17 with `2 2 2` druid and
`2 2` magic-user.

### Two gates the engine applies

* **Cleric wisdom bonus.** Wisdom (record `0x015`, the second byte of the pair)
  above 12, 13, 14, 15, 16 and 17 each add one slot, at cleric spell levels 1,
  1, 2, 2, 3 and 4. Each is skipped unless that slot already holds something,
  so a bonus never arrives at a spell level the cleric's own rows do not reach.
  Cumulatively that is Curse's and Silver Blades' table for every score a
  character can have: 13 gives `1`, 14 `2`, 15 `2 1`, 16 `2 2`, 17 `2 2 1`, 18
  `2 2 1 1`. Curse's table has one more row, at wisdom 19, and this engine has
  no compare above 18 -- no race's own maximum reaches 19, so nothing depends
  on the difference. CONFIRMED on both ports.
* **Two score ceilings.** Wisdom below 17 zeroes cleric spell level 6 and below
  18 zeroes level 7. Intelligence (record `0x013`) below 12, 14, 16 and 18
  zeroes magic-user spell levels 6, 7, 8 and 9. CONFIRMED on both ports, on
  each one's own record offsets.

**`goldbox.spells.capacity_by_class` applies neither ceiling**, and its wisdom
bonus comes out of `goldbox.levels`, which has no entry for this title -- so it
answers with Pool of Radiance's bonus, which grants a spell at wisdom 12 that
this game does not and one at 13 where this game grants two. A
`pools-of-darkness` entry in `goldbox/levels.py` carrying `wisdom_bonus_from=13`
and `wisdom_bonus_level=(0, 0, 1, 1, 2, 3, 4)` -- Curse's own tuple -- is the
fix.

## The spell table

`DS:651A`, 16 bytes an entry indexed by spell id, byte 0 the casting class (0
cleric, 1 druid, 2 magic-user, 3 no class) and byte 1 the spell level. The
builder's candidate loop runs ids 1 to 126 (`cmp byte ptr [bp-5], 0x7e / jne`).

| class | level | ids | count |
|---|---|---|---|
| cleric | 1 | 1-8 | 8 |
| cleric | 2 | 22-28 | 7 |
| cleric | 3 | 37-44 | 8 |
| cleric | 4 | 58, 66-70 | 6 |
| cleric | 5 | 71-76 | 6 |
| cleric | 6 | 36, 56, 101 | 3 |
| cleric | 7 | 102-105 | 4 |
| druid | 1 | 77-80 | 4 |
| druid | 2 | 90, 96, 98 | 3 |
| druid | 3 | 106-109 | 4 |
| magic-user | 1 | 9-21 | 13 |
| magic-user | 2 | 29-35 | 7 |
| magic-user | 3 | 45-55 | 11 |
| magic-user | 4 | 81-89, 100 | 10 |
| magic-user | 5 | 91-94, 118-119 | 6 |
| magic-user | 6 | 110-114 | 5 |
| magic-user | 7 | 115-117 | 3 |
| magic-user | 8 | 120-123 | 4 |
| magic-user | 9 | 124-126 | 3 |
| none | -- | 57, 59-65, 95, 97, 99 | 11 |

115 spells and 11 non-spells in 1-126. CONFIRMED: these are the engine's own
bytes rather than a reading of names against AD&D, which is what the three
earlier titles' groups are.

**It settles three of Secret of the Silver Blades' PROBABLE groups** -- 36 and
56 are cleric 6, and 115-117 magic-user 7 -- **and corrects a fourth.** 109 is
a **druid 3** spell, where `goldbox/spells.py` grouped it as magic-user 6 and
explained its absence from Silver Blades' trainer menu as a duplicate
`DEATH SPELL`. The trainer was not skipping a magic-user spell: 109 was never
one. `_NOT_GRANTED_SILVER_BLADES` is still right about what the menu offers.

**A refuted reading, in Curse's rows.** `_GROUPS_CURSE` has
`(81, 90, "magic-user", 4)`, which puts id 90 in a magic-user group. Silver
Blades' ranger grant already moved 90 to druid 2 and this table says druid 2
outright, so Curse's group for 90 is wrong by one id. Harmless today -- Curse's
`not_granted` carries 90, so no trainer hands it out -- and correcting Curse's
rows was not part of this reading.

### The spellbook, and an id the record cannot hold

DOS keeps **one byte per spell id**, 125 of them at record `0x0B3`, written by
`mov byte ptr es:[di + 0xb2], 1` with `di` the spell id. Creation writing
`es:[di+0x131] = 1` in the same routine pins `icon_dimension` at `0x131`
independently, so the field really does stop at `0x12F` and the last id it can
record is 125. Id 126 is a spell the record cannot record, exactly as Pool of
Radiance cannot record `RESTORATION` at 56.

The candidate loop runs to 126, which would write `0x130` (`attack_level`).
**It cannot fire, and this is the engine being right rather than our stride
being wrong.** The loop appears in two branches: the cleric's, which tests
class byte 0, and the ranger's, which tests class 1 or 2 with a slot at that
spell level. Id 126 is magic-user 9, so the cleric branch never matches it, and
the ranger branch reads the magic-user array's ninth level, which a ranger's
table never fills and which no class before slot 4 fills either.

**The Amiga stores the same set differently**: a sixteen-byte mask at `0x159`,
reached with `divs.w #$8` and a bit index. Both cover the same ids -- the Amiga
candidate loop also stops at `cmpi.b #$7e` -- so a conversion between the ports
has to translate the encoding rather than copy the field.

## The creation menus

`GAME.OVR:0x0147D8` asks race, sex, class, alignment, rolls the six abilities,
then asks the name.

**Six races of the seven the table holds.** The menu appends indices 0-5
(`cmp byte ptr [bp-0x17], 5 / jne`) out of `DS:103D`, nine bytes an entry: Elf,
Half-Elf, Dwarf, Gnome, Halfling, Human. Index 6, Monster, is never offered.
The choice lands in record `0xad`.

**Classes, from a per-race list at `DS:6F57`**, fourteen bytes a race, first
byte a count, each entry indexing the eighteen class names at `DS:0E57` (27
bytes an entry). The choice lands in record `0xae`.

| race | classes offered |
|---|---|
| Elf (7) | Fighter, Magic-User, Thief, Fighter/Magic-User, Fighter/Thief, Fighter/Magic-User/Thief, Magic-User/Thief |
| Half-Elf (13) | Cleric, Fighter, Magic-User, Thief, Ranger, Cleric/Fighter, Cleric/Ranger, Cleric/Fighter/Magic-User, Cleric/Magic-User, Fighter/Magic-User, Fighter/Thief, Fighter/Magic-User/Thief, Magic-User/Thief |
| Dwarf (3) | Fighter, Thief, Fighter/Thief |
| Gnome (3) | Fighter, Thief, Fighter/Thief |
| Halfling (3) | Fighter, Thief, Fighter/Thief |
| Human (6) | Cleric, Fighter, Magic-User, Thief, Paladin, Ranger |

**No race offers Druid or Monk**, though both have class numbers (1 and 7), a
name and an alignment row. A druid or a monk can only arrive by import, which
is the other side of what `goldbox.dos_port`'s druid-slot note says: the druid
array a record carries is a ranger's.

**Alignments, from a per-class list at `DS:70F5`**, ten bytes a class, first
byte a count, indexing the nine names at `DS:107C` (17 bytes an entry). A
paladin gets Lawful Good alone, a ranger the three good ones, a druid five, a
thief seven (no Lawful Good, no Chaotic Good), a monk and a cleric all nine;
each multiclass row follows its components.

### Ability limits

Both tables clamp the rolled score at record `0x011 + 2*ability`, the abilities
being strength, intelligence, wisdom, dexterity, constitution and charisma in
record order.

**Racial, `DS:6EF7`, sixteen bytes a race**: `+0`/`+1` strength minimum by sex,
`+2`/`+3` strength maximum by sex, `+4`/`+5` the exceptional-strength
percentile cap, then five minimum/maximum pairs at `+6` through `+15`. The
clamp indexes it `shl di, 4 / add di, dx` with `dx` the sex byte at record
`0x166`.

| race | STR male | STR female | INT | WIS | DEX | CON | CHA |
|---|---|---|---|---|---|---|---|
| Elf | 3-18 | 3-16 | 8-18 | 3-18 | 7-19 | 6-18 | 8-18 |
| Half-Elf | 3-18 | 3-17 | 4-18 | 3-18 | 6-18 | 6-18 | 3-18 |
| Dwarf | 8-18 | 8-17 | 3-18 | 3-18 | 3-17 | 12-19 | 3-16 |
| Gnome | 6-18 | 6-15 | 7-18 | 3-18 | 3-18 | 8-18 | 3-18 |
| Halfling | 6-17 | 6-14 | 6-18 | 3-17 | 8-18 | 10-19 | 3-18 |
| Human | 3-18 | 3-18 | 3-18 | 3-18 | 3-18 | 3-18 | 3-18 |

The exceptional-strength caps are 75, 90, 99, 50, 0 and 100 for a male of each
race in that order, and 0, 0, 0, 0, 0 and 50 for a female.

**Per class, `DS:708F`, six bytes a class**, 0 meaning no minimum:

| class | STR | INT | WIS | DEX | CON | CHA |
|---|---|---|---|---|---|---|
| Cleric | 6 | 6 | 9 | -- | -- | 6 |
| Druid | -- | -- | 12 | -- | -- | 15 |
| Fighter | 9 | -- | 6 | 6 | 7 | 6 |
| Paladin | 12 | 9 | 13 | -- | 9 | 17 |
| Ranger | 13 | 13 | 14 | -- | 14 | 6 |
| Magic-User | -- | 9 | 6 | 6 | -- | 6 |
| Thief | 6 | 6 | -- | 9 | -- | 6 |
| Monk | 15 | -- | 15 | 15 | 11 | 6 |

Each multiclass row is the maximum of its components'. Paladin, ranger, druid
and monk are AD&D 1st edition's published minima point for point, which is a
second source agreeing with the reading.

### Name entry: fifteen characters

The prompt passes 15 to the input routine
(`GAME.OVR:0x01619B`, `push 13 / push 0 / push 15 / lcall 0x47f:0x711`) and the
copy of the answer into the record truncates at 15 -- two numbers in the same
routine, and the record's `name_text` is fifteen bytes. An empty name is
refused (`cmp byte ptr es:[di], 0 / je` back to the prompt) and the first
character is tested against a character set held in the code segment.

## The two ports read the same numbers

CONFIRMED by byte identity, not by argument. Every table above was located in
the Amiga executable by searching for the DOS bytes:

| table | bytes compared | identical |
|---|---|---|
| the four slot progressions | 1044 (4 x 261) | 1043 |
| racial ability limits | 96 | 96 |
| classes by race | 84 | 84 |
| class ability minimums | 102 | 102 |
| alignments by class | 170 in 17 rows | all 17 rows, ten bytes each |

**The one differing byte is the cleric table's column 0 at class level 1, which
neither engine reads** -- both column loops start at 1.

Two differences that are not numbers:

* **the Amiga pads each alignment row to twelve bytes** and holds the same ten,
  so a stride must be taken from the port being read;
* **the Amiga picks between the four progressions with an index table** at
  `a4-$6CDA` holding `0 FF FF 1 2 3 FF` for class slots 0-6, where DOS has a
  branch each. `FF` means the class has no rows, and the two spell out the same
  four classes.

## What stays unread

* **The Amiga's creation routine.** Its tables are byte-identical to the DOS
  ones, so the lists and both limit tables are settled, but which entries its
  menu offers and what its name prompt accepts are not read. The experiment:
  find the routine that clears a whole record and then reads `0x04EA68` with a
  fourteen-byte stride, and read its loop bound and its input call. Until then
  the Amiga's menu bounds are PROBABLE by the tables agreeing.
* **Which characters a name may begin with.** The set is a `push cs` constant in
  the overlay, and resolving it needs that overlay segment's own base, which the
  file-offset readers do not have. The experiment: take the segment base from
  the `FBOV` table (`tools/dos/dosovrmap.py`) and read the 32 bytes at offset
  `0x6B6` in it as a Pascal set.
* **The age table at `DS:6FAB`** (28 bytes a race, with columns per class
  group) and the **age-bracket table at `DS:7053`** (ten bytes a race), which
  creation uses to age a character and adjust abilities. Read as far as knowing
  what they are and where; the columns are not attributed.
* **The 22-byte-per-class-slot table at `DS:6D18`**, which creation reduces over
  the class slots into `thac0_base` at `0xac`, and the per-slot class-bit table
  at `DS:6DB2` it sums into `class_bits` at `0x17b`. Both are named and neither
  is decoded here; `docs/224-the-dos-thac0-floor.md` is the attack side.
* **Whether the two score ceilings should reach `capacity_by_class`.** The
  function answers base rows plus the wisdom bonus, so for a cleric with wisdom
  under 17 or a magic-user with intelligence under 12 it reports slots the game
  would zero. Nothing reads it for this title yet, and a boundary character
  built from it would carry a row no engine-written record has.
