# Character specimens

Every character record we have, with attributes known independently of the
bytes. This is the reference set that `tools/compare.py` works from — the more
varied it is, the more fields can be identified by comparison alone.

## Donald's party — `PORSAVE.D64`

Six exported `.chr` files (full 580-byte records) plus the same six in
`SAVEDGAME0` slots 0–5 (first 256 bytes each). Alignments were supplied by
Donald and used to confirm `0x0D8`.

| name | sex | race | class(es) | alignment | age | HP | money |
|---|---|---|---|---|---:|---:|---|
| MALCYON | male | elf | magic-user | neutral good | 176 | 4 | 60 gp |
| LADY KATHERINE | female | half-elf | magic-user/thief | neutral evil | 41 | 5 | 90 gp |
| ROLAND | male | human | cleric | lawful good | 21 | 7 | 100 gp |
| SILAS | male | human | fighter | chaotic neutral | 21 | 9 | 120 gp |
| MAGNUS | male | dwarf | fighter | neutral good | 51 | 9 | 150 gp |
| BRUTUS | male | human | fighter | neutral good | 21 | 11 | 120 gp |

BRUTUS has exceptional strength 18/98, SILAS 18/81, MAGNUS 18/80 — the three
specimens that revealed `strength_index` at `0x0E2`.

## The sample party shipped on `POOL1.D64`

Six characters in `SAVEDGAME0`, so 256-byte slot images only. Alignments here
are *decoded*, not independently known.

| name | sex | race | class(es) | alignment (decoded) |
|---|---|---|---|---|
| ZARRADA | female | human | cleric | lawful good |
| SHARA THE GRAY | male | elf | magic-user/fighter | lawful neutral |
| HOGARTH | male | dwarf | thief/fighter | lawful neutral |
| TANARAKIS | male | half-elf | magic-user/cleric | lawful good |
| LARA SPELLSWORD | female | elf | magic-user/fighter | neutral good |
| ARAX THE BOLD | male | human | fighter | neutral good |

LARA SPELLSWORD is a useful independent check: her class bitmask is 9 =
magic-user/fighter, which her name states outright.

**TANARAKIS settled `spells_castable`.** Cleric 1 / magic-user 1, and `0x0EE`
reads `$31` — both nibbles set at once, cleric high and magic-user low. No
single-class specimen could tell that packing apart from two separate bytes, and
every earlier specimen was single-class. Being SSI's own shipped party makes it
the cleanest evidence in the project for that field. See
[127-community-formats.md](127-community-formats.md) §2.

## Fixtures in the repo

| file | contents |
|---|---|
| `tests/fixtures/party6_savedgame0.bin` | Donald's six-character party — the fixture that disproved the `$400` slot model |
| `tests/fixtures/pool1_savedgame0.bin` | the shipped sample party |
| `tests/fixtures/brutus.chr`, `malcyon.chr`, `lady_katherine.chr` | full 580-byte exported records |
| `tests/fixtures/savedgame0.bin`, `savedgame1.bin` | the original single-character save |

## Later states of the same party

Donald's party was captured at three points, and each one paid for itself:

| fixture | state | what it gave |
|---|---|---|
| `party6_savedgame0.bin` | six characters, no equipment | disproved the `$400` slot model |
| *(after shopping)* | equipped | the whole inventory format ([the shopping trip](50-experiments.md)) |
| `party6_after_combat.bin` | after a fight, icons changed | experience, silver, and the icon table ([the combat-icon edits](50-experiments.md)) |

## Specimens found elsewhere

Two disks that came from outside the project, and neither is one of our own
controlled saves.

**"Their values prove nothing" was too strong** and this page said it for a
while. Seven of `npc_party.d64`'s eight records satisfy a saving-throw rule
derived without them, and its five NPC records are the game's own `MON*` files
carried through play. The honest statement is the one below: one field in it was
written by an editor, and everything an editor does not touch is as good as any
other specimen.

### `npc_party.d64` — three PCs and five NPCs

Found online by Donald (discussed on r/c64 as "An unusual Pool of Radiance save
disk"). **One** thing in it cannot have come from ordinary play:

* **MAD MAN's experience is exactly `$FFFFFF`** — every bit of the 24-bit field
  set. He is a shipped record, `MON19`, and the shipped copy holds **0**, so the
  value did not come from play. It is precisely what the 1989 editor on
  `poolce.d64` writes: its own documentation says the XP option "just sets it at
  the max".

~~**PRINCESS FATIMA's race byte is 0**, outside the 1-based `DWARF=1` through
`MONSTER=8` enumeration.~~ **Withdrawn.** Race 0 is the game's own commonest
value — 75 of the 135 distinct monster records carry it — and FATIMA is
`MON68`, a shipped record whose slot matches the file on the game disk in 252 of
256 bytes, race byte included. Nothing was tampered with. See
[PRINCESS FATIMA was never impossible](50-experiments.md).

~~Weaker corroboration: XAVIER has DEX 19 and GRON CON 20, above the 3–18 a
character rolls.~~ **Withdrawn.** Donald points out that the game's own trainer
lets you alter ability scores, so a score outside the rolled range is not
evidence of anything. Whether the trainer will go above 18 is not known, but the
inference was weak enough that it is not worth leaning on either way. Four
separate characters carrying a RING OF PROTECTION +3 remains mildly odd and
proves nothing on its own.

*An earlier version of this page said "every hacked character has all-18
abilities". That is simply false — GENHEERIS, MAD MAN, DIRTEN and SKULLCRUSHER
have ordinary spreads with 8s, 9s and 10s in them. Only XAVIER and SIMON are
all-18. The conclusion stands on the two anomalies above and not on that.*

What makes it valuable
is everything an editor does *not* touch —

* it fills **all eight** character slots, which no save of ours does. That
  bounds the `SAVEDGAME1` roster at exactly one page — but it says nothing about
  how large a party the *game* permits, because this disk has been through an
  editor and has never been loaded in play. Its 3-player/5-NPC split is a fact
  about a file, not a rule;
* its characters are **levels 4 to 8**, where every other specimen we hold is
  level 1 — which is what finally identified `0x0A0` as level;
* four of them are **casters with spells memorised**, which gave the packed
  spell list at `0x020`. It also gave the roster's `+0x03`–`+0x05` a reading as
  per-level counts, which a later save contradicted;
* three are **player characters and five are NPCs**, a contrast we could not
  otherwise produce;
* it carries the project's **only records above level 1**, which is why the
  saving-throw rule could be tested against anything but a level-1 row at all.
  Seven of its eight satisfy that rule exactly. The one miss is MAD MAN, a
  level-8 NPC whose stored saves are the level-1 fighter row — a stale or
  hand-authored record, not a counter-example to the rule. And DIRTEN (cleric 6,
  wisdom 16, `5/5/2`) and SIMON (cleric 6, wisdom 18, `5/5/3`) are what pin the
  wisdom bonus on `spells_castable` at a level no clean specimen reaches.

**All five NPCs are shipped records and all three player characters are not** —
GENHEERIS is `MON58`, MAD MAN `MON19`, PRINCESS FATIMA `MON68`, DIRTEN `MON6B`
and SKULLCRUSHER `MON1B`, each matching in 230 to 252 of 256 bytes, ability
scores included. Four of the five have experience that has risen plausibly from
its shipped value. So the disk is better described as **genuine play with one
edited field** than as "hacked, values worthless", and its NPC records are worth
more than that phrase allowed.

It also carries three exported `.chr` files. Those are the *pre-hack* originals,
so diffing them against the slots does not give a clean export delta.

### `poolce.d64` — "POR EDITOR V5", 1989

A BASIC character editor from CSDb release 68820, with its documentation. It is
not a specimen so much as a second opinion: a contemporary author's reading of
the same 580-byte record, listable and checkable. Every offset it pokes matches
ours, it settles level, it completes the multi-class enumeration, and it carries
255 item names and 162 complete item records as `DATA`. See
[the 1989 BASIC editor](50-experiments.md).

## What this set still lacks

Every specimen *of Donald's own* is *level 1*. All three of the gaps listed
here have since been closed, two of them by `npc_party.d64` rather than by a
save we made:

* ~~a character who has **levelled up**~~ — **found**, in `npc_party.d64`:
  characters at levels 4, 6, 7 and 8 identified `0x0A0` as level. The
  **level-drain pair** is still open, and still needs a character drained in play.
* ~~a **spellcaster with spells memorised**~~ — **found**, in the same disk. The
  counts are in the `SAVEDGAME1` roster block and the packed list is at record
  offset `0x020`, and the **spellbook** — which spells a character knows at all —
  is a bitmask at `0x078`–`0x07E`. The standing guess had been that `0x078`
  onward was spell data, and it was right; what it took was a save with spells
  actually memorised, and the game's own name table to read the ids against.
* ~~a character whose **armour class has changed**~~ — **found.** The
  `PORSAVE.D64` / `PORSAVE2.D64` pair (unarmoured, then banded mail and shields)
  located it: AC is cached in `SAVEDGAME1`, not in the character record. See
  [the roster blocks](30-savegame-layout.md).

### `PORSAVE10.D64` — the roster disk

Eight **full 580-byte exports** and no `SAVEDGAME0` at all, which makes it more
informative than a save: a slot stores only the first 256 bytes. Four characters
Donald made to fill gaps — NYX (gnome thief), DAX (halfling fighter/thief),
ASTRID (half-elf cleric/fighter) and DELILIA (half-elf cleric/fighter/magic-user)
— alongside BRUTUS, MAGNUS, SILAS and ROLAND.

It closed four things at once: the **size flag** at `0x099`, the first **thief
skill** specimens (which showed the skills are signed), class codes **8** and
**9** on player characters, and the two races nothing had ever carried.

**Races we will never get from character creation.** Half-orc is not on the
menu; the only two in the game are the NPCs MACE and NORRIS THE GRAY, readable
out of the monster files. Gnome and halfling were missing from every specimen
and are now supplied by `PORSAVE10.D64` above — which settled `0x0AD`, though
not the way anyone expected: both read 0, so it is not a racial trait mask.

**And the reason they read 0 is now in the code.** `GEN $0BF3` seeds `0x0AD` per
race from `[1, 0, 107, 0, 124, 0, 0, 0]`, **indexed by the race byte itself**,
which is 1-based. Elf is race 2 and is born with 107; half-elf is race 4 and is
born with 124; every other race gets nothing, which is exactly what NYX and DAX
show. `0x0AD` is a ten-slot list of *active effect codes*, seeded per race and
then written by spells and readied items alike.

### `PORSAVE11.D64` — the save nobody had read

The latest state of Donald's party, and undocumented until a sweep found it. It
is the only save of ours whose roster page differs from the one written on the
shopping trip, which is what makes it worth its own entry:

* **three characters are wounded** — ROLAND 5 of 7, SILAS 6 of 9, BRUTUS 6 of 11;
* the party has **looted heavily**: SILAS, MAGNUS and BRUTUS carry a full
  sixteen items, SILAS 230 lb of them, and movement falls with the weight;
* ROLAND's `+0x03` reads **3** beside three memorised level-1 cleric spells,
  which is the first support for the retracted spell-count reading from a save
  of our own;
* both magic-users have **empty** memorised lists, having cast their sleeps;
* experience runs 45 to 86, against 17 in every earlier save.

What Donald did to produce it is not recorded, which limits what can be
concluded from it. See
[the spell counts, and how thin the retraction was](50-experiments.md).

Two more have closed since:

* ~~a character **wounded and then saved**~~ — **found**, in `PORSAVE4.D64`:
  LADY KATHERINE at 4 of 5 hit points, which confirmed roster `+0x19`. It does
  **not** settle `0x119` in an export, because no wounded character has been
  exported.
* ~~the party **moved a few squares** between two saves~~ — **done**, four
  saves one action apart, which located x, y, facing, the previous square and
  the counter in the `SAVEDGAME0` header.

Still wanted, and each needs a save we make ourselves:

* a character **exported while wounded** — the one step that settles `0x119`;
* a character **drained a level** by undead. Not for the "current/true level
  pair", which does not exist: `0x0A0` is the current level and `0x0A1`/`0x0A2`
  are the drain delta, both read off the drain and restoration routines. What is
  wanted is a specimen showing the pair non-zero, because no character of ours
  has ever been drained;
* a **multi-class character above level 1** — to tell "character level" at
  `0x0A0` apart from "the single class's level";
* a **cleric/magic-user with more than sixteen spells memorised**, which is the
  one observation that would settle whether `spells_memorised` is 16 bytes or
  the 21 the format allows;
* a **character of a sturdy race with constitution below 11**, to exercise the
  `+1` and `+2` bands of the saving-throw constitution bonus. Only `+3`/`+4`/`+5`
  have ever been seen;
* **one specimen where `0x100` reads other than 1**, which is what the status
  question turns on.

~~A **magical weapon or armour** obtained in play — to read the item effect bytes
against a known item.~~ **No longer needed for the effect bytes.** The `0x0AD`
namespace is named — 129 codes, 44 CONFIRMED off `MON*` carriers and item records
already on the disks — and the discriminator between an item's `+14` as an effect
id and as a spell id is `+15` bit 7. CLOAK OF DISPLACEMENT reads `+14` 89 (displaced)
and TWO-HANDED SWORD +1 +3 VS UNDEAD reads 3 (undead-slaying), both off the player's
own saves. See `por/traits.py` and [128-guide-and-scripting.md](128-guide-and-scripting.md).
