# `wish export` and `wish import` — the save editor

A command-line character editor for **C64 Gold Box** save disks. Exports a party
to YAML, and imports an edited YAML back onto a **new** disk.

**These were `wish-cli` until [129-one-binary.md](129-one-binary.md)**, which
folded that program into `wish` as two subcommands. The file name here is kept
so the links to it keep working; nothing else about the tool changed.

Pool of Radiance is the reference title. `goldbox/games.py` carries save geometry,
race, class and item-name tables for six titles, and the title is detected from
the save file's own name and load address — a Curse of the Azure Bonds or Secret
of the Silver Blades save opens and round-trips byte-identically through the same
code path. Everything below is written in Pool of Radiance's terms because that
is where the offsets were earned; the record is the same 580 bytes in all of them.

```
wish export PORSAVE.D64 -o party.yaml
vi party.yaml
wish import party.yaml  -o PORSAVE-EDITED.D64
```

The subcommand names the direction; `-o` is what gets written. Each takes its
own `--help`.

## Safety

* **An existing save is never modified.** `import` always writes a new disk, and
  refuses if `--output` names the original.
* **`--dry-run`** reports exactly what would change without writing anything.
* **Unknown bytes are preserved.** Only fields we understand are written back;
  the party header, everything in `SAVEDGAME1` past its first page, and the
  majority of each character record that is still unidentified are carried
  through untouched.
* **The round-trip is lossless** — exporting and re-importing unchanged
  reproduces the disk byte for byte. This is asserted in `tests/test_yaml_io.py`
  and is the property everything else depends on.

## Options

`wish export SAVE.D64`:

| flag | meaning |
|---|---|
| `--output`, `-o` | the YAML to write. Defaults to beside the disk |
| `--game-disk` | a game disk, used **only** to turn item indices into names |

`wish import PARTY.YAML`:

| flag | meaning |
|---|---|
| `--output`, `-o` | the new save disk to write. Required unless `--dry-run` |
| `--original-save`, `-s` | the disk to build on. Defaults to the one recorded in the YAML at export, so it is rarely needed |
| `--game-disk` | needed only to turn item words into indices when you build a new item |
| `--dry-run`, `-n` | report changes without writing |

A flag that applies to one subcommand is simply not on the other, so there is
nothing left to reject with an explanation: `wish export --dry-run` is an
unrecognised argument. The first argument to `wish` is a subcommand only when it
is *exactly* `export` or `import`; a save disk genuinely called `export` is
reachable as `./export`.

## Finding a game disk

Item *names* come from the game's own `ITEMNAMES` file, so a game disk is needed
to display them — nothing else depends on it, and without one items are simply
listed unnamed.

It is looked for in this order:

1. `--game-disk`
2. the `POR_GAME_DISK` environment variable
3. any game disk of the save's own title in the same directory as the
   save disk — `POOL*.D64` for Pool of Radiance, `CURSE*.D64` for Curse,
   whatever `Game.disk_glob` says for the rest

Point 3 covers the normal case, where the game and save disks live together, so
usually no configuration is needed.

## The YAML

The file opens with a comment explaining what it is and how to put it back —
guidance belongs in comments, not in a field someone might try to edit. The only
non-party key is `source_path`, which is real data: it records the disk the
export came from so `wish import` can default to it.

Fields appear in the order the game's own character sheet uses — identity
first, then class and level, then abilities, then money from jewelry down to
copper — so the file reads the way the screen does.

Opaque encodings are **hidden**. Sex, race, alignment and class appear as names,
not numbers — the bitmask, the race table and the alignment index are
implementation details a person editing a save should never have to learn:

```yaml
    sex: female    # male or female
    race: half-elf    # dwarf, elf, gnome, half-elf, halfling, half-orc, human, monster
    # lawful good     lawful neutral    lawful evil
    # neutral good    true neutral      neutral evil
    # chaotic good    chaotic neutral   chaotic evil
    alignment: neutral evil
    # --- class
    # one or more of: magic-user, cleric, thief, fighter
    # e.g. [magic-user, thief] for a multi-class character
    classes: [magic-user, thief]
```

Multi-class is just a list, so `[magic-user, thief]` says what `class_bits: 5`
used to. Names are case-insensitive and order does not matter. A raw number is
still accepted if you prefer it, and an unrecognised name is refused with the
valid options listed rather than being silently mangled.

Sections are separated by headings (`# --- money`), and derived groups say so,
because the game may recompute them.

## The combat block

Five values the character sheet shows are not in the character record at all.
The game caches them in `SAVEDGAME1`, in a 32-byte roster block per party slot,
and `wish` reads and writes that page:

```yaml
    combat:
      armour_class: 8
      thac0: 20
      damage_bonus: 0
      hp_current: 4
      movement_current: 12
      unknown_03_05: [0, 0, 0]
```

Both combat numbers are stored as `60 - value`, so `wish` refuses anything that
will not fit rather than wrapping it around. `movement_current` is the encumbered
figure and drops with armour — 12 unencumbered, 9 in banded mail — while the
`movement` field further up is the unencumbered base.

`unknown_03_05` is three bytes whose meaning is **not** established. They were
read as per-level spell counts, which fitted one save and is flatly contradicted
by another; see `docs/30-savegame-layout.md`. They are exported so they can be
round-tripped, not because we know what they do.

Spells themselves are two separate lists further up the character — `spells_known`
(the spellbook) and `spells` (currently memorised).

## Fields the game stores twice

Two values exist in two places, and `wish` keeps both halves in step so an edit
cannot leave a save in a state no real save has been seen in:

* **class** — the bitmask at `0x0EB` and the single class code at `0x073`,
  shown as `classes:` and `class_code:`. Editing `classes:` updates the code to
  match; three combinations have no code in the game's table
  (magic-user/cleric/thief, cleric/thief/fighter, and all four) and are refused
  rather than written wrongly.

  **They are allowed to disagree.** The game itself ships NPCs where they do —
  `DWARVEN FIGHTER` has a fighter's bits and a cleric's code. So `class_code:`
  is only touched when you change something, and setting it yourself overrides
  the reconciliation, with a note in the change list. A record that arrives
  disagreeing leaves untouched.
* **level** — the per-class array at `0x0C9`–`0x0CC` and the character level at
  `0x0A0`. Edit `levels:` and `level:` follows automatically; edit `level:`
  yourself and your value is kept. The per-class array is reconciled against the
  class bitmask **only when you edit the classes**, for the same reason: a
  record that already disagrees is not ours to correct. For a multi-class character the derived value
  is the highest of the per-class levels, and the import says so in its change
  list, because what that byte holds for a multi-class character is unproven —
  every specimen above level 1 is single-class.

## What can be edited

Every field in the YAML is editable — there are no read-only decorations left.

Editable: name, sex, race, alignment, age, classes, per-class and character
level, the six ability scores and exceptional strength, hit points, movement,
infravision, the five saving throws, all coin types plus gems and jewelry, thief
skills, experience, the combat block above, each item's `readied` / `quantity` /
`cost_gp`, and the combat icon's `shape` and `colours`.

Items keep their raw bytes in the YAML alongside friendly values. `raw` is the
whole 16-byte record and is the starting point on import; the friendly fields are
applied over it, so an item survives a round-trip exactly while every part of it
stays changeable.

An item *name* is three indices into the game's own word table — noun,
qualifier, suffix, as in `CLOAK` `OF` `DISPLACEMENT`. `type` indexes a second
table, `ITEMS`, which is what actually decides damage, armour class and which
classes may use the thing; the comment beside it summarises that entry:

```yaml
      - name: SHORT SWORD
        readied: true
        bonus: 0
        quantity: 0
        cost_gp: 8
        weight_lb: 3.5
        type: 37    # 1d6 damage (1d8 vs large); thief, fighter
        raw: '25000025000080002300000800000000'
```

**Changing, adding and removing items.** Edit a field to change an item. Remove
its entry to delete it — every one of the sixteen slots is written, so a shorter
list really does shorten the inventory.

To **add** one, the best way is to copy a real record out of the game's own item
files:

```yaml
      - template: WAND OF MAGIC MISSILES
        readied: true
```

`docs/87-item-templates.md` lists all 163. A template is better than building an
item by hand because the bytes we do not understand come with it — including the
effect bytes at `+13`–`+15`, which on a scroll are its spells and on a wand its
charges. Building one from scratch leaves those at zero.

Failing that, append an entry with **no `raw`** and describe the item:

```yaml
      - name: LONG SWORD +1
        words: [LONG SWORD, '', '+1']   # noun, qualifier, suffix
        type: 36
        bonus: 1
        cost_gp: 3500
        weight_lb: 6.0
        readied: true
```

`words` accepts names or numbers. Seven words appear twice in the game's table —
`RING`, `CLOAK`, `JAVELIN`, `TRIDENT`, `STONE`, `OINTMENT`, `MIRROR` — and are
refused with both indices rather than guessed at. Building by name needs a game
disk, so pass `--game-disk` on import if one is not found beside the save. A
character carries at most sixteen items and more than that is refused.

Bytes we do not understand are zero in a built item, which is why copying an
existing `raw` and editing it is safer than building one when a template exists.
`docs/85-item-tables.md` lists every word and every type.

## When a character does not add up

Armour class, THAC0 and the damage bonus are **cached** by the game and only
recomputed when equipment changes. Edit a dexterity or a strength and they go
stale — the character sheet in game will show the old numbers.

`wish` recomputes all three from the AD&D 1st edition rules on export and says
where the cache disagrees, both on the terminal and as a comment above the
`combat:` block:

```
  MALCYON: armour class is cached as 8, but the rules give 6
```

That is a real example: MALCYON's dexterity was edited from 16 to 18 and his
armour class never followed. Re-readying a piece of armour in game forces the
recompute, or you can correct the value under `combat:` directly.

The same check covers spells — a memorised spell that is not in the spellbook,
or more memorised at a level than the character's class, level and Wisdom allow.

**Nothing here is enforced**, only reported. No save that breaks these rules has
been written and loaded in game, so refusing one would be guessing.

One discrepancy is known and expected: MALCYON's THAC0 improves by one when he
readies darts, which nothing accounts for. A second — BRUTUS coming out a point
of armour class better than predicted — turned out to be our own dexterity
table, not his record, and is fixed. See `docs/30-savegame-layout.md`.

## NPCs

A save disk has eight character slots — at most six may hold *player* characters,
the game enforcing that itself, and the remaining two are NPC-only. `npc:` reports
which of them hold a companion the party picked up rather than one you made:

```yaml
    npc: false
```

**It is bit 7 of `0x0B8`, and that is the byte the game itself tests.** Every read
of `$6BB8` in the overlays checks it; the party-count routine tallies player
characters with it and enforces `CMP #$06`, which is the six-PC limit in code
rather than in anecdote; NPC money is zeroed on it. So `npc:` writes one bit.

Six other bytes — `0x0B7`, `0x0D3`, `0x0D4`, `0x0E4`, `0x0E5` and `0x0FB` — read
`$FF` for every NPC and `$00` for every player character, and were read as the
flag for a while. They are **fill residue**, and the set is not even a set:
every shipped `MON*` record carries `$FF` at the same sixteen offsets before any
save exists, the party loader overwrites six of them, and ten survive. These six
are the survivors that a player character reads `$00` at. `wish` leaves them
alone, because rewriting bytes we do not understand is how a lossless editor
stops being lossless.

**This set held eight bytes until `#224 (0x0B9 and 0x0BA are documented both as
an NPC marker and as the dual-class slot)`, and two of them were never
residue.** `0x0B9` and `0x0BA` are a dual-classed human's old class slot and the
level it was left at, written by Curse of the Azure Bonds, Secret of the Silver
Blades and Gateway to the Savage Frontier, and never touched by Pool of Radiance
— see `docs/20-character-record.md`. While they were counted here, the import
warned that a dual-classed character's record was in a state no real save had
been seen in, which is `#229 (A dual-classed Curse character imports with a
warning that its record is corrupt)`. They are out of the set and the warning is
right again. The other two survivors are `0x0E6`–`0x0E7` below.

`0x0E6`–`0x0E7` are **not** part of that set and were briefly miscounted as
such. They hold a non-zero, high-entropy per-character value in *every* player
character, so they are not a `0`/`$FF` pair at all. What they are is UNKNOWN; the
DOS record carries a single high-entropy byte in the same place, immediately
before experience, which its community documentation calls `MON_Index`.

Three item bugs have been fixed, none of which anything bought in a shop would
have exposed:

* **cost is 16-bit** — anything over 255 gp used to read as nonsense, and the
  import path wrote only the low byte;
* **the third name word was being dropped**, which hid every `+1` and `CURSED`;
* **names above index 62 were wrong.** `ITEMNAMES` has three gaps in it, and the
  parser numbered the strings sequentially instead of following the file's own
  pointer table, shifting every later name onto a different, plausible-looking
  word. Every item in Donald's party indexes below the first gap, which is why
  it never showed.

What the YAML still does not show: the magic bonus, and anything from the item
**type** table — damage, armour protection, hands, range, class restrictions.
Those are reachable now (`docs/85-item-tables.md`); they are simply not
exported.

## Cautions

**Ability scores may not be as simple as they look.** The game's own trainer can
alter them, and there is an untested rumour that doing so carries a penalty in
play. If that is true the save must record it somewhere, and `wish` writes only
the six bytes at `0x014`–`0x019`. Nothing has been found alongside them, but
nobody has yet diffed a save taken before and after a trainer visit. See
`docs/80-fields-wanted.md`.

**Derived values may not behave as you expect.** Saving throws, infravision and
the thief skills are computed by the game from class, race and level. They are
stored, so they can be edited, but the game may recompute and overwrite them.
Editing the inputs is more likely to stick than editing the results.

The saving-throw rule is no longer a guess: **the class-table row for the
character's level, best number in each column across every class held, minus the
AD&D constitution bonus for a dwarf, gnome or halfling.** 78 of 79 records
satisfy it exactly. So if you edit a level, a class or a constitution, the five
saves at `0x09A`–`0x09E` are now predictable rather than merely stale — you can
work out what they ought to be. See
[127-community-formats.md](127-community-formats.md) §1.

**Some derived values are cached and will go stale.** Raising a character's
dexterity does *not* update their armour class: the game showed the AC for the
old score after an edit ([the thirteen-field edit](50-experiments.md)). AC has
since been found — it is cached in `SAVEDGAME1`, and the game recomputes it only
when *equipment* changes, never when an ability changes. THAC0 is cached in the
same place and behaves the same way. Editing ability scores is safe, but expect
combat numbers to lag until the game recalculates them for some other reason;
re-readying a piece of armour in game forces it.

**Writing `SAVEDGAME1` is proven.** MALCYON was edited to armour class 1 and 11
hit points — two bytes, `$830F` and `$8319` — booted, and the game showed both on
the party list and the character sheet, then wrote the same roster page back on
save. Everything that lives only in the roster is editable for real.

`0x0E2`, **effective strength**, is a third cached value and the quietest one.
It is not exported, not editable, and not among the discrepancies `wish`
reports, so editing `strength` leaves it holding the old score while the roster
numbers that depend on strength *are* flagged. That is deliberate — the game
refills it — but it means a hand-edited save disagrees with itself in one place
the tool will not tell you about.

**An edit above `0x0FF` is silently dropped.** A save slot is 256 bytes, so the
record's tail — `0x10D`, `0x10E`, `0x10F`, `0x119` and the combat icon — exists
only in a standalone `.chr` export. `wish` will accept the change and the write
goes nowhere.

**Everything decoded is now editable**, including the spellbook and the
memorised list. Two consistency rules the editor does **not** enforce, because
neither has been proven in game: a memorised spell ought to be one the character
knows, and the number memorised at each level ought to be within the capacity
their class, level and Wisdom allow. The export prints that capacity beside the
spellbook so you can check it yourself.

## What has been confirmed in the game, and what has not

Being able to *read* a field is not evidence that the game will accept it
written. Four things have been written back, booted and seen on screen:

* the **thirteen-field edit** — all six ability scores and all seven money types
  at once, every one of them shown on the character sheet, and no checksum or
  rejection anywhere ([the thirteen-field edit](50-experiments.md));
* **armour class** and **current hit points** in the `SAVEDGAME1` roster —
  MALCYON at `AC 1` and `HITPOINTS 11`, and the game wrote the same page back
  when it saved;
* a **constructed item** — a `LONG SWORD +4` that ships on no disk, with THAC0
  and the damage expression both moving to match
  ([a constructed item is accepted by the game](50-experiments.md));
* **character creation under script**, which is how `\x01WYVERN` exists;
* an **edited combat icon**, which Donald has seen on the combat screen. It
  was carried as unproven for a while on the strength of nobody having written
  down that they looked.

Everything else `wish` can write has been located by diffing or by reading the
game's code and has **never been written back and confirmed in play**. Each is
one edit and one look at the character sheet, and the bar is that the change
also survives a save-and-reload unchanged:

| what | the question it also answers |
|---|---|
| **experience** | whether the game re-derives level from it on load |
| **character level** (`0x0A0`) | the same question from the other side — change level without touching experience and see which wins |
| **class, race, alignment, sex** | whether the game rejects or corrupts them. Most likely of the lot to go wrong, so prove them on a throwaway party |
| **a memorised spell** (`0x020`) and a **spellbook** bit (`0x078`) | whether the game accepts a spell memorised by a character who does not know it |
| **movement** (roster `+0x1B`) | nothing else; it is simply the one roster field never written |
| **the NPC bit** (`0x0B8` bit 7) | what the game actually permits — a written marker is not the same as a party the game will run |
