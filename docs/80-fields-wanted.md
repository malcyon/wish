# Character record: what is decoded, and what is still wanted

The target field list for the editor. **Decoded** means we can read it;
**Still wanted** means we cannot.

Everything decoded is now editable. The remaining uncertainty is not about
reading but about *writing*: nothing found since the thirteen-field edit has been
written back and confirmed in game.

## Decoded — in the character record

| field | offset | confidence |
|---|---|---|
| name | `0x000` | CONFIRMED |
| **memorised spell list** | `0x020` | CONFIRMED — ids match spells Donald memorised on purpose |
| **spellbook** (spells known) | `0x078`–`0x07E` | CONFIRMED — bitmask by spell id; clerics know all, mages a subset |
| six ability scores | `0x014`–`0x019` | CONFIRMED |
| **base THAC0**, as `60 - THAC0` | `0x071` | PROBABLE — matches the AD&D table for all 12 of Donald's characters and the 6 shipped |
| **base armour class**, as `60 - AC` | `0x0E1` | PROBABLE — 10 for every player character; monsters carry their real AC here |
| **current armour class**, as `60 - AC` | `0x10F` | PROBABLE — **export only**, beyond the 256 a save slot holds; agrees with the roster exactly |
| exceptional strength | `0x01A` | CONFIRMED |
| race | `0x072` | CONFIRMED |
| class (single code) | `0x073` | CONFIRMED — but prefer the bitmask |
| age | `0x074` (16-bit) | CONFIRMED |
| five saving throws | `0x09A`–`0x09E` | CONFIRMED |
| movement | `0x09F` | CONFIRMED |
| **character level** | `0x0A0` | CONFIRMED — the drain routine writes it down from the per-class array |
| **levels drained** | `0x0A1` | CONFIRMED — current-plus-delta, not a second copy of the level |
| **hit points lost to draining** | `0x0A2` | CONFIRMED — restored alongside `0x0A1` |
| **undead turning class** | `0x0A3` | CONFIRMED — matches the AD&D 1e table on all 13 undead specimens |
| thief skills | `0x0A5`–`0x0AC` | CONFIRMED — **signed**; a halfling's read-languages is -5 |
| **small size flag** | `0x099` | PROBABLE — 0 small, 1 medium; the icon large/small flag |
| **money — all seven types** | `0x0BB`–`0x0C8` | CONFIRMED |
| **level, per class** | `0x0C9`–`0x0CC` | PROBABLE |
| infravision | `0x0D5` | CONFIRMED |
| sex | `0x0D6` | CONFIRMED |
| alignment | `0x0D8` | CONFIRMED |
| effective strength | `0x0E2` | PROBABLE |
| **experience** (24-bit) | `0x0E8` | CONFIRMED |
| **class bitmask** | `0x0EB` | CONFIRMED |
| hp max / hp rolled | `0x076` (**16-bit**) / `0x0ED` | CONFIRMED |
| **active effect list**, ten slots | `0x0AD`–`0x0B6` | PROBABLE — same namespace as item `+14`; seeded per race |
| **NPC flag** (bit 7) and **score altered at the trainer** (bit 0) | `0x0B8` | CONFIRMED — the byte the game itself tests |
| hp current | `0x119` (**16-bit**) | CONFIRMED — **export only**; initialised from `hp_max`, then moved independently |
| **combat icon** | `0x220`–`0x243` | CONFIRMED |
| **inventory** | `$5900` + slot × `$100` | CONFIRMED |

## Decoded — in the `SAVEDGAME1` roster blocks

One 32-byte block per party slot at `$8300 + N * $20`, eight of them, filling
`$8300`–`$83FF` exactly. All of them are editable: `wish` reads and writes this
page, and it is the only part of `SAVEDGAME1` it touches. See
`docs/30-savegame-layout.md`.

| field | offset | confidence |
|---|---|---|
| three bytes, meaning unknown | `+0x03`–`+0x05` | **retracted** — were read as spell counts; contradicted |
| **damage bonus** | `+0x17` | PROBABLE — strength plus the readied weapon's own |
| slot index | `+0x0D` | CONFIRMED |
| **THAC0**, as `60 - THAC0` | `+0x0E` | PROBABLE |
| **armour class**, as `60 - AC` | `+0x0F` | CONFIRMED |
| armour bonus, as `48 + bonus` | `+0x10` | PROBABLE |
| **current hit points** | `+0x19` | CONFIRMED — LADY KATHERINE at 4 of 5 after one point of damage |
| movement | `+0x1B` | CONFIRMED |

This is where the game caches what it derives, which is why editing an ability
score leaves combat numbers stale: AC and THAC0 are recomputed on an equipment
change, never on an ability change.

**Un-retired:** `0x071` was written off as "not THAC0" because the sheet shows
20 where the byte reads 39. It **is** THAC0 — the *base* value, stored as
`60 - THAC0`, while the 20 on screen is the *current* value in the roster block
at `+0x0E`. 39 is `60 - 21`, MALCYON's base as a level-1 magic-user.

### Everything above `0x0FF` exists only in an export

A save slot is **256 bytes**. A record is 580. So `0x100` and above — including
`0x10D`, `0x10E` (current THAC0), `0x10F` (current armour class), `0x119`, the
item area and the combat icon — are present in a standalone `.chr` and **absent
from a save**. `wish` will accept an edit to them and the write is silently
dropped, because the slot has nowhere to put it.

This is why the THAC0, armour-class and hit-point "triples" are really **pairs**
in a save: the record's base value, and the roster's current one. The third copy
is an export-only artefact.

### Hit points are 16-bit, in three places

| where | field |
|---|---|
| record `0x076`–`0x077` | maximum |
| record `0x119`–`0x11A` | current — **export only** |
| roster `+0x19` | current, in a save |

`0x119` **is** current hit points and not a copy of the maximum: `GEN $0BD0`
initialises it from `hp_max`, and both the trainer and the drain routine move it
independently afterwards. It equals `hp_max` in every specimen only because no
wounded character has yet been exported.

The high bytes went unread for so long because nobody in this party has more
than 255 hit points. The drain routine decrements the pair, which is what fixes
the width.

### Money

All seven types, each 16-bit little-endian, in this order: copper, silver,
electrum, gold, platinum, gems, jewelry. Confirmed three ways:

* the **shopping diff** ([the shopping trip](50-experiments.md)) — gold fell for all six characters and platinum
  moved for three;
* **looting orcs** put 25–26 silver on everyone where it had been zero;
* the **edit test** ([the thirteen-field edit](50-experiments.md)) set all seven at once on MALCYON — jewelry 10, gems
  10, platinum 100, gold 102, electrum 100, silver 126, copper 100 — and every
  one appeared on his character sheet in the game.

### Level, per class

`0x0C9`–`0x0CC`, one byte each for magic-user, cleric, thief and fighter, in the
same order as the class bits. Across all twelve specimens a byte is non-zero
exactly when its class bit is set. This is how **dual-classing** is represented:
the old class stays frozen at its level while the new one advances.

PROBABLE rather than CONFIRMED only because every specimen is level 1, so
"level" is not yet distinguishable from "class present". One levelled character
settles it.

### Inventory

Done — [the shopping trip](50-experiments.md), corrected by
[the 1989 BASIC editor](50-experiments.md). Items live at `$5900` + slot × `$100`,
sixteen 16-byte records per character:

| Byte | Meaning |
|---|---|
| `+0` | category code — **not** a name index, and still unread |
| `+1` | name word 3 (suffix): `DISPLACEMENT`, `CURSED`, `+1` |
| `+2` | name word 2 (qualifier): `MAIL`, `OF`, `AC3` |
| `+3` | name word 1 (noun): `CLOAK`, `BANDED`, `LONG SWORD` |
| `+4` | magic bonus, signed — `254` is a cursed −2 |
| `+6` | bit 7 = readied; low 3 bits = which name words are hidden until identified |
| `+7` | bit 7 = cursed |
| `+8`–`+9` | weight, 16-bit, in tenths of a pound |
| `+10` | quantity |
| `+11`–`+12` | cost in gold pieces, 16-bit |
| `+13`–`+15` | a scroll's spell ids, or a wand's charges at `+13` and its type at `+14` |

Verified against the AD&D 1st edition price and weight tables. The name is
assembled from three indices into the game's own `ITEMNAMES` table — `CLOAK` `OF`
`DISPLACEMENT`, `BROAD SWORD` `-2` `CURSED`. Two of these were wrong until the
1989 editor supplied 162 records containing magic items: the third name word was
being dropped, and cost was read as one byte, which is enough for everything
buyable in a shop and wrong for everything interesting. Only `+5` is still
unread — 0 on 162 of the 163 items on the game disks and 251 on CURSED NECKLACE
alone. See `por/items.py`.

**Combat icon: ✅ done** ([the combat-icon edits](50-experiments.md)). 36 bytes, split exactly in half — 18 screen
codes for the **shape**, then 18 **colour** values. In a save they live in a
shared table of 8 entries at `$4BE0`–`$4CFF`, one per slot, rather than in the
character record. `wish` exposes both halves.

Donald then changed every icon in the party, which gave a much better picture
than the single differing character we had before:

* **Shape and colour really are independent.** Three characters (MALCYON,
  MAGNUS, BRUTUS) ended up sharing **one shape with three different colour
  sets**. Others took distinct shapes. Four distinct shapes across six
  characters.
* **Shape bytes** range `$02`–`$E9` — screen codes into the game's custom
  character set, as expected.
* **Colour bytes** are `0`–`15` throughout, valid C64 colour codes. The party
  used 0, 8, 9, 10, 11, 13, 14, 15.
* Some cells appear fixed across every shape seen — bytes 16 and 17 are always
  `$10 $11` — which hints at a grid where part of the frame is constant. Not
  yet worked out.

The large/small flag the Gold Box Companion offers is **not** among these 36
bytes. It lives in the record instead, at `0x099` — see below.

### Alignment encoding

| value | alignment | | value | alignment |
|---:|---|---|---:|---|
| 0 | lawful good | | 5 | neutral evil |
| 1 | lawful neutral | | 6 | chaotic good |
| 2 | lawful evil | | 7 | chaotic neutral |
| 3 | neutral good | | 8 | chaotic evil |
| 4 | true neutral | | | |

Verified against Donald's party: ROLAND 0 (lawful good), BRUTUS/MAGNUS/MALCYON
3 (neutral good), LADY KATHERINE 5 (neutral evil), SILAS 7 (chaotic neutral) —
six for six.


### The two class fields

`0x073` holds a single class code in the standard Gold Box order (`CLERIC=0`,
`DRUID=1`, `FIGHTER=2`, `PALADIN=3`, `RANGER=4`, `MAGIC-USER=5`, `THIEF=6`,
`MONK=7`). Codes above 7 are multi-class, and the observed ones decode via the
bitmask:

| code | classes |
|---:|---|
| 11 | magic-user/cleric |
| 13 | magic-user/fighter |
| 14 | thief/fighter |
| 16 | magic-user/thief |

The full enumeration is unknown, and does not need to be: **`class_bits` at
`0x0EB` expresses any combination directly**, which is what `wish` uses.

### Class bitmask encoding

| bit | class |
|---:|---|
| 1 | magic-user |
| 2 | cleric |
| 4 | thief |
| 8 | fighter |

OR-ed together, so `5` = magic-user/thief and `9` = magic-user/fighter. Use this
rather than `char_class` at `0x073`, which cannot express a combination.


## Still wanted

Four entries that stood here have since been found and moved into `Decoded`:
**armour class** and **current hit points** (both in the `SAVEDGAME1` roster
block, not in the character record), **character level** (`0x0A0`), and
**memorised spells** (counts in the roster block, the packed list at `0x020`).

~~**The combat line**~~ — **done, all of it.** THAC0 has a base in the record at
`0x071` and a current value in the roster at `+0x0E`, both stored as
`60 - value`. Damage dice belong to the *item*, in the `ITEMS` type table on the
game disk, as two expressions each (versus large and versus medium); the damage
*bonus* is roster `+0x17`, strength plus the weapon's own. `DAMAGE 1D3` on
MALCYON's sheet is his readied dart.

The author of the 1989 BASIC editor never found THAC0, which now makes sense in
a way it did not before: he was editing an exported `.chr`, which carries the
base but not the current value, and the number the sheet shows is the current
one.

**What decides which items a character may wield** — Gold Box Companion shows
four checkboxes per character (fighter, cleric, magic-user, thief) that govern
what the character can wield, independently of what they *are*. There is a strong
candidate already decoded: `class_bits` at `0x0EB` is a four-bit mask in exactly
those four classes, and item-type byte `+13` in the `ITEMS` table is a usage mask
in **the same bit order**. The obvious mechanism is that the game tests
`character class_bits AND item usage mask`.

What we cannot yet say is whether `class_bits` is *only* an item-usage mask or
genuinely the character's class, because `0x073` and `0x0EB` are redundant in all
twenty specimens — every one encodes the same classes twice, and none disagrees.
The experiment that separates them is cheap and is described below.

~~**Whatever records that an ability score was altered at the trainer**~~ —
**found, and it closes the rumour.** `0x0B8` **bit 0** is set by `GEN $155D`
immediately after `INC`/`DEC $6B14,X`, and cleared again if the change is
cancelled. So the game does remember.

**And nothing ever reads it back.** Every read of `$6BB8` anywhere in the game
tests bit 7, the NPC flag. The forum claim that an original developer said
altering scores carries negative effects in play has **no code behind it on this
port**. The prediction that the game would have to remember was right; it
remembers and then never looks.

That also settles the safety question for the editor: `wish` writing
`0x014`–`0x019` directly is safe, and there is no second copy of a score.

~~**Racial traits**~~ — **found: `0x0AD`–`0x0B6`, a ten-slot list of active
effect codes**, in the same namespace as item byte `+14`. Three overlays loop
`LDX #$09` over it, and XAVIER carrying 107 in the first slot and 89 in the tenth
proves the extent. `GEN $0BF3` seeds it per race from `[1, 0, 107, 0, 124, 0, 0,
0]`.

That explains why `0x0AD` was non-zero only for elves (107) and half-elves (124):
those are the two races the seed table gives anything. 107 and 124 sit
immediately below 108 and 125 — full immunity to sleep and charm — and the table
grades other families the same way, so they read as *partial* resistance.
PROBABLE.

The percentage is **not in the byte and could not be**; it is a table index. The
earlier hunt for 90 and 30 was looking for something that was never there.

~~**Item effects**~~ — **every byte is read.** `+5` is a signed saving-throw
bonus, `+13` charges, `+14` the spell or effect carried, `+15` a handler
selector whose bit 7 marks a passive power. `+6` bits 3-6 and `+7` bits 0-6 are
unused. See [every remaining item byte](50-experiments.md) and
[the item tables](85-item-tables.md).

~~**Level-drain state**~~ — **found: `0x0A1` levels drained, `0x0A2` hit points
lost.** There is no second copy of the level; the pair is current plus delta,
which is why a "true level" was never found. `RESTORATION` reverses it exactly.

~~**Current status**~~ — **it is not stored.** `LIBRARY` holds the strings at
indices 42–48 (`OK GONE DEAD DYING UNCONSIOUS RUNNING STONED`, the game's own
misspelling), and **nothing on any of the nine disks references them**. All 64
call sites into the string printer were checked. The C64 party list prints name,
armour class and hit points only, colouring hit points when current is below
maximum. Status is derived — and 16-bit hit points are enough to derive it.

~~**Which spells are which**~~ — **done.** `SPELLN00` holds the names; ids 1-55
are the player's spells in six class/level groups, 56 is RESTORATION, and from 57
the table continues with combat messages. See [the spell table](86-spell-table.md).

~~**Portrait (head / body)**~~ — **found: `0x0FE` head, `0x0FF` body**, each an
index into the `HEAD*` and `BODY*` files in hex. All twenty-two values across
eleven exports name a file that exists. The earlier guess at `0x10D`/`0x10E` was
wrong on both counts: `0x10E` is the current THAC0, and `0x10D` looks like
marching order.

~~**Icon large/small flag**~~ — **found: `0x099`.** 1 for medium, 0 for small,
and the only byte in the stored 256 separating dwarves, gnomes and halflings
from humans, elves and half-elves. It is not among the 36 icon bytes because it
is not icon data: a small character has the same body and a smaller head, so the
icon reads as small without being smaller.

~~**What marks an NPC**~~ — **found: `0x0B8` bit 7.** Every read of `$6BB8`
tests it; the party-count routine tallies player characters with it and enforces
`CMP #$06`, so **the six-character limit exists in code**, not merely in the
error message. NPC money is zeroed on it. `npc_party.d64` splits three players
from five NPCs exactly here.

The eight `$FF` bytes were fill residue after all, as the earlier note suspected.
`wish` now writes bit 7 and leaves them untouched.

**Constructing an item** — much closer than it was. The name is three word
indices, the cost is 16-bit, the weight is in tenths of a pound, and the 1989
editor supplies 162 known-good records to copy from. What is missing is the
meaning of byte `+0` and a written-and-loaded proof that a hand-built record is
accepted.

**The monster attack routine** — how many attacks a creature makes and for how
much. Everything else about a monster is decoded: they use the character record
layout, with hit dice at `0x0A0`, armour class at `0x0E1` and movement at
`0x09F`. The **experience award is not stored at all** — no byte or word in the
480 matches the AD&D value for any of eight creatures — which fits Gold Box
games computing it from hit dice.

## Values the save appears to hold twice

Donald's observation, and a sharp one: whenever we say "the game stores this
twice", we are making an assumption, and the assumption may be hiding a field we
have not understood. Two identical-looking values in every specimen we hold is
weak evidence that they *mean* the same thing — it may only mean we have never
seen the circumstance that separates them.

| Value | Place A | Place B | Status |
|---|---|---|---|
| THAC0 | `0x071` base | roster `+0x0E` current | **Understood.** Base and current genuinely differ — MALCYON is 21 and 20 |
| movement | `0x09F` base | roster `+0x1B` current | **Understood.** 12 and 9 in banded mail |
| hit points | `0x076` max, `0x0ED` rolled | roster `+0x19` current | **Understood.** LADY KATHERINE is 5 and 4 |
| spells | `0x078` known | `0x020` memorised | **Understood.** Different sets, different sizes |
| strength | `0x014` plus `0x01A` percentile | `0x0E2` effective | **Understood.** The second collapses the exceptional bands to one number |
| armour class | roster `+0x0F` total | roster `+0x10` armour only | **Understood.** The second excludes the shield |
| armour class again | `0x0E1` base | `0x10F` current (export only) | **Understood.** Base is 10 for every character; monsters carry a real one |
| **class** | `0x073` single code | `0x0EB` bitmask | **ASSUMED.** Agree in all 20 specimens; nothing has been seen that separates them |
| **level** | `0x0A0` | `0x0C9`–`0x0CC` per class | **Understood.** `0x0A0` is the *current* level. Drain state is a separate pair at `0x0A1`/`0x0A2`, so there is no hidden 'level highest' |

The pattern is instructive: every pair we *understand* turned out to be **base
versus current**, or **potential versus actual**. Not one of them was a
redundant copy. That is a reason to doubt the row still marked ASSUMED rather
than to trust it.

**The worry about `0x0A0` is settled, and the answer was neither option.** The
Gold Box DOS field catalogue has a field called *level highest*, which records
the best level reached so it can be restored after a drain, and the fear was
that `0x0A0` was it — making `wish` finish a drain every time it reconciled the
two. Reading the drain routine settles it: **`0x0A0` is the current level**, and
drain state lives in its own pair at `0x0A1` and `0x0A2` as levels-drained and
hit-points-lost. Keeping `0x0A0` in step with the per-class array is exactly
what the game does.

A real bug was found here anyway, and it was the *other* direction: an import
that edited nothing rewrote `0x0A0` from the per-class array, so a record that
arrived already disagreeing was silently "corrected". Now gated behind an actual
edit, and covered by constructed-state tests in `tests/test_pairs.py`.

**The specific worry about `0x073`.** `class_bits` shares its bit order with the
item-type table's class-usage mask, which makes it a good candidate for "what may
this character wield". If `0x073` is what the game *displays* and `0x0EB` what it
*enforces*, they would agree in every ordinary character and diverge only in one
built deliberately — which is exactly what Gold Box Companion's four "can wield"
checkboxes appear to do.

### Leads not yet pinned down

* ~~`0x078`–`0x07A`~~ — **resolved.** This was always the best spell lead and it
  was right: `0x078`–`0x07E` is the spellbook, a bitmask indexed by spell id.
  The `8,44` shared by magic-users is the starting spellbook — detect magic,
  read magic, shield, sleep — and the cleric's `254,1` is all eight cleric
  level-1 spells.
* `0x0E6`–`0x0E7` — two high-entropy bytes, different for every character. A
  per-character seed or identifier; not a checksum, since the game accepts
  edited saves without complaint ([the thirteen-field edit](50-experiments.md)).
* `0x0EC` — went 0 → 1 after combat for MALCYON and LADY KATHERINE and nobody
  else. Those are exactly the two spellcasters, so it is more likely spell state
  than damage.
* `0x0B8` — BRUTUS is the only character whose copy changed (0 → 1) when the
  party equipped, and he is also the only one whose armour class comes out a
  point better than the AD&D tables predict. Probably one thing, not two.
* `0x117` — 5, 0, 1 across the three exports; unexplained.
* **Item byte `+5`** — 0 on 162 of the 163 items on the game disks and 251 on
  CURSED NECKLACE alone.

Four entries previously listed here have since been resolved: `0x0C9`–`0x0CC`
turned out to be the per-class levels, and `0x0CC` alone was wrongly read as an
exceptional-strength flag because the only fighters in the specimen set at the
time happened to be the only characters with exceptional strength; `0x0FE`–`0x0FF`
are the portrait head and body; and `0x10E` is the current THAC0, not the head
index it sat next to.

## How the remaining fields will most likely be found

Two techniques have carried the project, in this order of preference:

1. **Compare different characters.** A party with varied races, classes, sexes
   and alignments identified seven fields in minutes with no emulator ([the six-character comparison](50-experiments.md)).
2. **Compare the same party before and after a change.** One shopping trip gave
   the whole inventory format ([the shopping trip](50-experiments.md)); one fight gave experience and silver; one
   round of icon edits gave the icon structure ([the combat-icon edits](50-experiments.md)).

What the specimen set still lacks, and what each would unlock, is listed in
`90-specimens.md` — most usefully a **levelled-up character** and one whose
**armour class has changed**.

References Donald supplied:

* <https://nerdlypleasures.blogspot.com/2015/11/goofy-things-in-pool-of-radiance-gold.html>
  — on how portraits are assembled.
* <https://gbc.zorbus.net/graphics/screen08.jpg> — GBC's combat-sprite editor,
  showing which attributes are exposed.

