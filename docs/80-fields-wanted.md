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
| **current armour class**, as `60 - AC` | `0x10F` | PROBABLE — export only; agrees with the roster exactly |
| exceptional strength | `0x01A` | CONFIRMED |
| race | `0x072` | CONFIRMED |
| class (single code) | `0x073` | CONFIRMED — but prefer the bitmask |
| age | `0x074` (16-bit) | CONFIRMED |
| five saving throws | `0x09A`–`0x09E` | CONFIRMED |
| movement | `0x09F` | CONFIRMED |
| **character level** | `0x0A0` | PROBABLE |
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
| hp max / hp rolled | `0x076` / `0x0ED` | PROBABLE |
| hp current? | `0x119` | PROBABLE — see caveat below |
| **combat icon** | `0x220`–`0x243` | CONFIRMED |
| **inventory** | `$5900` + slot × `$100` | CONFIRMED |

## Decoded — in the `SAVEDGAME1` roster blocks

One 32-byte block per party slot at `$8300 + N * $20`, eight of them, filling
`$8300`–`$83FF` exactly. **None of these is editable yet**; `wish` does not touch
`SAVEDGAME1`. See `docs/30-savegame-layout.md`.

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

### A caveat on `hp_current` in an export

`0x119` equals `hp_max` in every specimen and **has never been seen differing**.
No wounded character has ever been captured in an exported `.chr`, so it may
simply be a second copy of the maximum. [The hunt for current hit points](50-experiments.md) searched both save files for a
wounded character's current total and found nothing — but that byte lies beyond
the 256 a save slot stores, so it exists only in exports and that search does
not settle it either way.

Treat the name as a hypothesis. Exporting a wounded character's `.chr` would
resolve it in one step.

This is a separate question from *current hit points in a save*, which are found:
roster byte `+0x19`, confirmed against MALCYON's character sheet. What `0x119` in
an export is remains open.

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
| `+6` | bit 7 = readied |
| `+8`–`+9` | weight, 16-bit, in tenths of a pound |
| `+10` | quantity |
| `+11`–`+12` | cost in gold pieces, 16-bit |

Verified against the AD&D 1st edition price and weight tables. The name is
assembled from three indices into the game's own `ITEMNAMES` table — `CLOAK` `OF`
`DISPLACEMENT`, `BROAD SWORD` `-2` `CURSED`. Two of these were wrong until the
1989 editor supplied 162 records containing magic items: the third name word was
being dropped, and cost was read as one byte, which is enough for everything
buyable in a shop and wrong for everything interesting. `+5`, `+7` and `+13`–`+15`
are still unread. See `por/items.py`.

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

**Still missing: the large/small flag** the Gold Box Companion offers. It is not
among these 36 bytes, so it lives elsewhere or is implied by the shape.

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

**Whatever records that an ability score was altered at the trainer** — if
anything does. Two separate things here, and they should not be run together:

* **Fact, first-hand from Donald:** the game's own trainer will alter an ability
  score. So a score is not fixed at creation, and a score outside the 3–18 a
  character rolls is not by itself evidence of tampering.
* **Rumour:** a post on the Gold Box forums reports a claim, attributed to one
  of the original developers, that using it carries **negative effects in play**.
  That is two removes from evidence — a forum post about what someone says a
  developer said — and it should be treated the way this knowledge base treats
  everything in `docs/60-goldbox-field-checklist.md` §5 until it is tested.

It is worth testing anyway, because **the rumour makes a prediction we can
check**: if the game penalises an altered score, it has to remember that the
score was altered. Either a flag, or — far more likely given everything else in
this save format — a **true** score kept alongside the **current** one. Every
pair of values we have come to understand has turned out to be base-versus-
current, and this would be another. Nothing of the sort has been found near
`0x014`–`0x019`, but nobody has looked for it with a before/after pair in hand.

**Why it matters for the editor.** `wish` writes `0x014`–`0x019` directly. If a
second copy or a flag exists, editing the scores alone would leave a character in
a state the game never produces — exactly the trap the class and level pairs
already set. Until the experiment is run, that risk is unquantified.

**Racial traits** — Gold Box Companion on the DOS version shows an editable
trait list, and a trait **survives a race change**, so a trait is stored per
character rather than derived from race. Detecting magic was set that way and
then worked permanently in play.

`0x0AD` was the leading candidate and is **ruled out as a general trait mask**:
it is non-zero only for elves (107) and half-elves (124), and gnomes and
halflings — both rich in racial traits — read 0. It is still unexplained and
still belongs to those two races specifically. Nothing else in the record is
tied to traits.

**Item effects** — a `+1 long sword` and a `flame tongue` differ from a plain
long sword somewhere in the 16 bytes. Byte `+4` is the numeric bonus, signed,
and `+3`/`+2`/`+1` build the printed name. **`+0` is settled**: it indexes the
`ITEMS` type table, which carries damage, protection, hands, range and class
usage (`docs/85-item-tables.md`). Still unread: `+5`, `+7`, `+13`, `+14`, `+15`,
and `+6` below its readied bit — charges are the obvious candidate, since the
1989 editor's documentation describes editing them. Its 162 item records include
magic items we have never seen in play and remain the cheapest way in.

**Level-drain state** — undead drain levels, so the game should track both a
current and a "true" level to restore to. Expect a *pair* per class. Now
testable in a way it was not before: `0x0A0` and the per-class array at
`0x0C9`-`0x0CC` finally have specimens above level 1.

**Current status** — OK / unconscious / dead / stoned / fled. The game has
status strings somewhere worth locating.

~~**Which spells are which**~~ — **done.** `SPELLN00` holds the names; ids 1-55
are the player's spells in six class/level groups, 56 is RESTORATION, and from 57
the table continues with combat messages. See [the spell table](86-spell-table.md).

**Portrait (head / body)** — half found. Export byte `0x10D` reads 8, 3 and 4 for
our three exported characters and `BODY08`, `BODY03` and `BODY04` all exist on
the disks, so it is a good **body** index. The **head** index is not found:
`0x10E` reads 42, 39, 39, and neither hex nor decimal turns those into filenames
that all exist. Three characters is too small a sample; a party with visibly
different portraits would settle it.

~~**Icon large/small flag**~~ — **found: `0x099`.** 1 for medium, 0 for small,
and the only byte in the stored 256 separating dwarves, gnomes and halflings
from humans, elves and half-elves. It is not among the 36 icon bytes because it
is not icon data: a small character has the same body and a smaller head, so the
icon reads as small without being smaller.

**What marks an NPC** — eight record bytes (`0x0B7`, `0x0B9`, `0x0BA`, `0x0D3`,
`0x0D4`, `0x0E4`, `0x0E5`, `0x0FB`) read `$FF` for every NPC and `$00` for every
player character, so the distinction is readable today and `wish` exposes it as
`npc:`. Which of them the game actually tests is not known, so writing the flag
is unproven in both directions.

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
| **level** | `0x0A0` | `0x0C9`–`0x0CC` per class | **ASSUMED.** Agree in all 20; every specimen is single-class and none has been level-drained |

The pattern is instructive: every pair we *understand* turned out to be **base
versus current**, or **potential versus actual**. Not one of them was a
redundant copy. That is a reason to doubt the two marked ASSUMED rather than to
trust them.

**The specific worry about `0x0A0`.** The Gold Box DOS field catalogue has a
field called *level highest*, which records the best level a character has
reached so it can be restored after a level drain. If `0x0A0` is that, then the
per-class array is the *current* level and the two are base-and-current like
everything else here — and they would agree in every save we hold, because none
of our characters has ever been drained. `wish` currently keeps them in step
when `levels:` is edited, which is right if they are duplicates and wrong if they
are not. This was flagged early as a possibility in
`docs/60-goldbox-field-checklist.md` and then overridden; the override may have
been the mistake.

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
* `0x0FE`–`0x0FF` — vary per character with no pattern identified yet.
* `0x10E` — 42, 39, 39 across the three exports. Sits between the body index and
  the current armour class, which is where a **head** index belongs, but no
  filename reading of those values works.
* `0x117` — 5, 0, 1 across the three exports; unexplained.
* **Item byte `+5`** — 0 on 162 of the 163 items on the game disks and 251 on
  CURSED NECKLACE alone.

Two entries previously listed here have since been resolved: `0x0C9`–`0x0CC`
turned out to be the per-class levels, and `0x0CC` alone was wrongly read as an
exceptional-strength flag because the only fighters in the specimen set at the
time happened to be the only characters with exceptional strength.

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

