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
| five saving throws | `0x09A`–`0x09E` | CONFIRMED — **and the rule is known**: the class table row for the character's level, taking the best number in each column across every class held, minus the AD&D constitution bonus for a dwarf, gnome or halfling. 78 of 79 records satisfy it exactly; the miss is MAD MAN, a level-8 NPC carrying the level-1 fighter row |
| movement | `0x09F` | CONFIRMED |
| **character level** | `0x0A0` | CONFIRMED — the drain routine writes it down from the per-class array |
| **levels drained** | `0x0A1` | CONFIRMED — current-plus-delta, not a second copy of the level |
| **hit points lost to draining** | `0x0A2` | CONFIRMED — restored alongside `0x0A1` |
| **undead turning class** | `0x0A3` | CONFIRMED — matches the AD&D 1e table on all 12 undead specimens, and is non-zero on no other record |
| thief skills | `0x0A5`–`0x0AC` | CONFIRMED — **signed**; a halfling's read-languages is -5 |
| **size flag** | `0x099` | PROBABLE — 0 small, 1 large; picks the icon part tables |
| **money — all seven types** | `0x0BB`–`0x0C8` | CONFIRMED |
| **level, per class** | `0x0C9`–`0x0CC` | PROBABLE |
| infravision | `0x0D5` | CONFIRMED |
| sex | `0x0D6` | CONFIRMED |
| alignment | `0x0D8` | CONFIRMED |
| effective strength | `0x0E2` | PROBABLE |
| **experience** (24-bit) | `0x0E8` | CONFIRMED |
| **class bitmask** | `0x0EB` | CONFIRMED |
| **spells castable per level** | `0x0EE`–`0x0F0` | CONFIRMED — one byte per spell level, **cleric in the high nibble, magic-user in the low**. Settled by multi-class specimens setting both nibbles at once: TANARAKIS, cleric 1 / magic-user 1 on SSI's own shipped party, reads `$31`. `0x0F1`–`0x0F3` are zero in all 79 records, as they must be in a game that stops at third-level spells |
| **creature type** | `0x0D7` | CONFIRMED — humanoid, undead, giant, regenerating and so on. 116 `MON*` records take 13 distinct values and every one is inside the DOS enumeration; TROLL reads 10, MUMMY 4. Zero in every player character, which is what it was mistaken for |
| **experience awarded, and per hit point** | `0x0F7`–`0x0F8`, `0x0F9` | CONFIRMED — GOBLIN GUARD 10, HOBGOBLIN 20, OGRE 90, with 1, 2 and 5 per hit point: the published AD&D 1e values exactly. Zero in every player export |
| **combat behaviour** | `0x10C` | CONFIRMED — 0 allied and controlled, 128 allied and uncontrolled, 129 hostile. 115 of 116 `MON*` records read 129 |
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
| **quickfight**, bit 7 | `+0x0C` | CONFIRMED — set by QUICK, read at the start of the next fight, never cleared |
| the two attack forms, current | `+0x11`–`+0x18` | PROBABLE — eight bytes mirroring `attack_forms` at `0x0D9`; `+0x15` is the primary die sides and `+0x17` the damage bonus |
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

### Above `0x0FF` the record is somewhere else, not nowhere

A save **slot** is 256 bytes and a record is 580, but a save keeps all four
blocks of the record — it simply keeps them apart:

| record offsets | in a save |
|---|---|
| `0x000`-`0x0FF` | the slot at `$4D00 + n * $100` |
| `0x100`-`0x11F` | the roster block at `$8300 + n * $20`, in `SAVEDGAME1` |
| `0x120`-`0x21F` | the item area at `$5900 + n * $100` |
| `0x220`-`0x243` | the combat-icon table at `$4BE0 + n * $24` |

So `0x10E` (current THAC0), `0x10F` (current armour class) and `0x119` (current
hit points) are roster `+0x0E`, `+0x0F` and `+0x19` under another name, and
`wish` edits them there. An export matches a save in 579 of 580 bytes; the one
genuine difference is `0x10D`, marching order in an export and record slot in a
roster block.

This is why the THAC0, armour-class and hit-point "triples" are really **pairs**:
the record's base value and the roster's current one, which an export happens to
carry in one file.

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

**Which one the game believes: both, for different things.** CONFIRMED by
building a save where they disagree — SILAS with `0x073` = 5 (MAGIC-USER) and
`0x0EB` = 8 (fighter), loaded unreconciled — and by the disassembly:

| field | the game uses it for | evidence |
|---|---|---|
| `0x073` char_class | **the class printed on the sheet**, and as a table index | the sheet said `MAGIC-USER`; `LIBRARY $31E1`-`$320D` index three name tables by it, `POST.COM $123F`/`$15E3` `LDX` it |
| `0x0EB` class_bits | **what the character may ready** | he readied a `LONG SWORD` anyway. `LIBRARY $465D` is `LDA $6D99 / AND $6BEB / BNE` — the item type's class-usage byte against the bitmask, else "WRONG CLASS." `CAMP $167D` is the same test |

Control: LADY KATHERINE, `0x0EB` = 5, was refused `SCALE MAIL` (cleric/fighter),
so the check is real. Neither field is a cache of the other, and an editor should
keep offering both.

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

~~**What decides which items a character may wield**~~ — **found, and the two
class fields are separated.** `class_bits` at `0x0EB` is what the game ANDs
against the item type's class-usage byte; `0x073` is what the sheet prints.
Proved by building a save where they disagree — SILAS with `0x073` = 5
(MAGIC-USER) and `0x0EB` = 8 (fighter) — and by the disassembly at
`LIBRARY $465D` and `CAMP $167D`. The section "The two class fields" above has
the whole thing. Four monster records ship with the two disagreeing, so an
editor must keep offering both.

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

~~**Icon large/small flag**~~ — **found: `0x099`.** 1 for large, 0 for small,
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

~~**Constructing an item**~~ — **done, and proven in game.** A `LONG SWORD +4`,
which ships on no disk, was built from word indices, type, bonus, cost and
weight with no template copied, written to a save and booted: the sheet showed
the name, THAC0 went 21 → 17 and damage `1D6+1` → `1D8+5`. Weight is PROBABLE
(movement fell 6 → 3) and cost UNVERIFIED — neither is printed on the C64 sheet.

~~**Which map the party is on**~~ — **found: `$4BC2`**, the `GEO` file number,
inside the loader's 25-entry "what is currently loaded" cache at
`$4BC0`–`$4BD8`. Bit 7 is a reload marker and must be masked. All ten saves read
`$00` (New Phlan, agreeing with the independent wall-match); `npc_party.d64`
reads `$0D`. See [the area id](50-experiments.md).

~~**The monster attack routine**~~ — **found: `0x0D9`–`0x0E0`.** Attacks per
round are stored **doubled**, which is how AD&D's 3/2 attacks work; then two
attack forms, dice count, die size and a signed modifier. Checked against the
*Monster Manual* on twenty creatures. The **experience award is stored** too —
`0x0F7`/`0x0F8` base plus `0x0F9` per hit point, multiplied by `hp_max`; the
earlier negative failed because the award is two numbers, not one.

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
| **class** | `0x073` single code | `0x0EB` bitmask | **Understood.** Separated by a constructed save and by the code: `0x073` is printed, `0x0EB` is enforced. Four shipped `MON*` records disagree on their own |
| **level** | `0x0A0` | `0x0C9`–`0x0CC` per class | **Understood.** `0x0A0` is the *current* level. Drain state is a separate pair at `0x0A1`/`0x0A2`, so there is no hidden 'level highest' |

The pattern is instructive: every pair we *understand* turned out to be **base
versus current**, **potential versus actual**, or **printed versus enforced**.
Not one of them was a redundant copy, and the last row on the list — class —
held out longest and then fell the same way.

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

### Leads not yet pinned down

* ~~`0x078`–`0x07A`~~ — **resolved.** This was always the best spell lead and it
  was right: `0x078`–`0x07E` is the spellbook, a bitmask indexed by spell id.
  The `8,44` shared by magic-users is the starting spellbook — detect magic,
  read magic, shield, sleep — and the cleric's `254,1` is all eight cleric
  level-1 spells.
* `0x0E6`–`0x0E7` — two high-entropy bytes, different for every character. A
  per-character seed or identifier; not a checksum, since the game accepts
  edited saves without complaint ([the thirteen-field edit](50-experiments.md)).
  They sit immediately before experience, where the DOS record puts a one-byte
  per-monster index; the C64 spends two.
* `0x0EC` — went 0 → 1 after combat for MALCYON and LADY KATHERINE and nobody
  else. Those are exactly the two spellcasters, so it is more likely spell state
  than damage.

Those two are the only leads left here. Six entries previously listed have since
been resolved. `0x117` is roster
`+0x17`, the damage bonus — its 5, 0, 1 across three exports is three different
strength-and-weapon totals, not an anomaly. Item byte `+5` is a signed
saving-throw bonus, and `0x0B8` is the NPC flag in bit 7 with the trainer flag
in bit 0 (see the caution below). The other three: `0x0C9`–`0x0CC`
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
`90-specimens.md`. The two named here — a levelled-up character and one whose
armour class has changed — have both been found; what is left is a character
exported while wounded, one drained a level, and a multi-class character above
level 1.

A third technique has since joined the two above and is now the cheapest of all
where it applies: **find the game's own table and check the field against it.**
The saving throws, the thief-skill progression and the spell-group boundaries
were all settled that way, by locating an eight-by-nine or nine-by-eight table
in a binary and matching every row, rather than by any diff.

And a fourth, which turned out to be the cheapest of all and was expected to be
the most expensive: **read the code that touches the byte.** The record answers
to a fixed `$6B00`, so `LDA $6BA0` *is* offset `0x0A0`, and scanning every
absolute operand in `$6B00`-`$6D44` across every file on the disks says which
offsets the game itself reads and writes. That is what named the level-drain
pair, the NPC flag, the effect list at `0x0AD` and the class ceilings — all four
after months of save-diffing had failed on them. Try it before planning an
experiment, not after one fails.

References Donald supplied:

* <https://nerdlypleasures.blogspot.com/2015/11/goofy-things-in-pool-of-radiance-gold.html>
  — on how portraits are assembled.
* <https://gbc.zorbus.net/graphics/screen08.jpg> — GBC's combat-sprite editor,
  showing which attributes are exposed.


---

## The quickfight bit — FOUND, and closed

**Roster block `+0x0C`, bit 7.** Selecting QUICK from the combat menu moved
exactly that bit for exactly the character quickfought, and nothing else in
13568 captured bytes but two of COMBAT's own scratch. Confirmed on a second
character in the same fight.

**It survives a fight, reaches the disk, and is honoured by the next fight.**
`PORSAVE14` settles it: quickfight enabled on MALCYON during a random orc
encounter, the fight finished, saved, then a second and unrelated fight walked
into — where MALCYON was still under computer control, and the save reads
`+0x0C = 80` for him and `00` for the other five. `PORSAVE2` through `PORSAVE9`
carry the same bit set for MALCYON alone; `PORSAVE`, `PORSAVE11`, `12` and `13`
are zero throughout.

**The two results that looked like refutations both follow from one rule:**
`COMBAT` reads the flag when the fight *starts* and works from its own copy for
the rest of it. So poking the bit mid-fight is too late in either direction, and
the setting and clearing seen around each action is COMBAT's own bookkeeping.
It is also why the only escape players found was pressing space at the exact
moment a turn begins.

The game never clears it, which is
[`../goldbox-bugs.md`](../goldbox-bugs.md) bug 3, and
`automap/actions.py`'s `ClearQuickfight` is the fix.

---

## What the trainer changes when an ability score is altered — WANTED

`0x0B8` bit 0 is currently read as "score altered at the trainer", and
`docs/50-experiments.md` records that **nothing reads it back**, which is why
the rumour of a penalty has nowhere to live. That conclusion rests on a code
search, not on a controlled observation, and it should rest on both.

**The experiment, which needs two saves and nothing else:**

1. Save at the trainer, immediately before altering an ability score.
2. Alter one score — one, so the diff is unambiguous.
3. Save again, to a different disk.

Then diff the two `SAVEDGAME0` images byte for byte. What we expect: the ability
byte itself, the derived combat numbers that depend on it, and `0x0B8` bit 0.
What matters is **everything else that moves** — any byte that changes and is
not one of those is the answer to a question we have not asked yet.

Worth capturing in the same pair: whether the exceptional-strength byte
(`0x074`) is touched for a fighter, and whether `0x0E2`, effective strength,
moves independently of the score.

**If a flag does record that a score was altered, the character editor should
show it** — a character whose scores are not the ones they rolled is a fact
about that character, and the editor's job is to show facts.

Note the pair should be taken with a character whose class does not muddy the
diff: a single-classed fighter changes fewer derived fields than a
multi-classed magic-user/thief.

---

## Two saves that would finish the quickfight story — FOR DONALD

The mechanism is found and closed (`docs/50-experiments.md`): roster `+0x0C`
bit 7, set by QUICK, read by `COMBAT` when a fight starts, never cleared by the
game. `PORSAVE14` proved it survives a fight and is honoured by the next one.

Two specimens would settle the last of it. Neither is urgent.

| save | what to do first | MALCYON's quickfight |
|---|---|---|
| **PORSAVE15** | finish a fight, change nothing | leave it **on** |
| **PORSAVE16** | turn it **off**, then save | **off** |

**Why each matters.**

`PORSAVE15` shows the bit surviving a *second* fight, and that a scripted
encounter does not clear it where a random one might. It costs nothing — end a
fight and save.

`PORSAVE16` is the state **no disk we hold has ever contained**. Across fifteen
saves the byte is either `80` or already `00`; we have never once seen the game
clear it. Turning quickfight off needs the space bar at the exact start of the
character's turn, so it has to happen during combat.

* If it then reads `00`, the game writes the byte in both directions and only
  *reads* it at the start of a fight — a slightly different model from the one
  written up, and the experiment log needs correcting.
* If it still reads `80` while the character is plainly back under the player's
  control, then the space-bar escape does not touch this byte at all and there
  is a second mechanism nobody has found.

Worth noting **when** during the fight it is turned off, if that is easy: a bit
that clears at once means the game writes it live, one that clears only when the
fight resolves means `COMBAT` writes its state back at the end.
