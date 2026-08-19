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
controlled saves. Their values prove nothing; their structure proves a lot.

### `npc_party.d64` — three PCs and five NPCs

Found online by Donald (discussed on r/c64 as "An unusual Pool of Radiance save
disk"). Two things in it cannot have come from ordinary play:

* **PRINCESS FATIMA's race byte is 0.** Races are 1-based, `DWARF=1` through
  `MONSTER=8`, and character creation offers nothing outside that. The other
  four NPCs are race 7, so it is not an NPC convention.
* **MAD MAN's experience is exactly `$FFFFFF`** — every bit of the 24-bit field
  set — while the rest of the party holds 10,200 to 115,311. That is a
  saturation value, and it is precisely what the 1989 editor on `poolce.d64`
  writes: its own documentation says the XP option "just sets it at the max".

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
* four of them are **casters with spells memorised**, which gave both the
  per-level counts and the packed spell list;
* three are **player characters and five are NPCs**, a contrast we could not
  otherwise produce.

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

Every specimen *of Donald's own* is *level 1*, and none has ever been seen
wounded in a save. Three of the four gaps listed here have since been closed, two
of them by `npc_party.d64` rather than by a save we made:

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

Still wanted, and each needs a save we make ourselves:

* a character **wounded and then saved** — the roster block's `+0x19` should
  move, and it would settle `hp_current` in an export;
* a character **drained a level** by undead — the current/true level pair;
* a **magical weapon or armour** obtained in play — to read the item effect bytes
  against a known item, rather than against the 1989 editor's synthesised ones;
* a **multi-class character above level 1** — to tell "character level" at
  `0x0A0` apart from "the single class's level";
* the party **moved a few squares** between two saves — map coordinates, which
  nothing has yet touched.
