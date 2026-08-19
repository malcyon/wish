# `wish` — the save editor

A command-line character editor for Pool of Radiance (C64) save disks. Exports a
party to YAML, and imports an edited YAML back onto a **new** disk.

```
tools/wish.py --export PORSAVE.D64 --output party.yaml
vi party.yaml
tools/wish.py --import party.yaml  --output PORSAVE-EDITED.D64
```

The mode flag carries the file being read; `--output` is what gets written.

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

| flag | meaning |
|---|---|
| `--export SAVE.D64` | read this save disk and write YAML |
| `--import PARTY.YAML` | read this YAML and write a new save disk |
| `--output`, `-o` | the file to write |
| `--original-save`, `-s` | `--import` only: the disk to build on. Defaults to the one recorded in the YAML at export, so it is rarely needed |
| `--game-disk` | a game disk, used **only** to turn item indices into names |
| `--dry-run`, `-n` | `--import` only: report changes without writing |

`--export` and `--import` are mutually exclusive and one is required. Flags that
apply to only one mode are rejected with an explanation rather than ignored.

## Finding a game disk

Item *names* come from the game's own `ITEMNAMES` file, so a game disk is needed
to display them — nothing else depends on it, and without one items are simply
listed unnamed.

It is looked for in this order:

1. `--game-disk`
2. the `POR_GAME_DISK` environment variable
3. any `POOL*.D64` in the same directory as the save disk

Point 3 covers the normal case, where the game and save disks live together, so
usually no configuration is needed.

## The YAML

The file opens with a comment explaining what it is and how to put it back —
guidance belongs in comments, not in a field someone might try to edit. The only
non-party key is `source_path`, which is real data: it records the disk the
export came from so `--import` can default to it.

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
      hp_current: 4
      movement_current: 12
      spells_memorised: [0, 0, 0]
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

* **class** — the bitmask at `0x0EB` and the single class code at `0x073`.
  Editing `classes:` writes both. Three combinations have no code in the game's
  table (magic-user/cleric/thief, cleric/thief/fighter, and all four), and are
  refused with the valid list rather than written wrongly.
* **level** — the per-class array at `0x0C9`–`0x0CC` and the character level at
  `0x0A0`. Edit `levels:` and `level:` follows automatically; edit `level:`
  yourself and your value is kept. For a multi-class character the derived value
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

There are eight character slots. `npc:` reports which of them hold a companion
the party picked up rather than a character you made:

```yaml
    npc: false
```

It is recognised from eight record bytes that agree across every character we
hold. Which one the game tests is unknown, so **changing it is unproven in both
directions** — the import writes all eight and says so. Turning an NPC into a
player character leaves `0x0E6`–`0x0E7` reading `$FF FF`, a value no real player
character has, and nothing is known about what that field is.

If a save ever turns up with the marker half-set, the import reports it as a
warning: no genuine save has been seen in that state.

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

**Some derived values are cached and will go stale.** Raising a character's
dexterity does *not* update their armour class: the game showed the AC for the
old score after an edit ([the thirteen-field edit](50-experiments.md)). AC has
since been found — it is cached in `SAVEDGAME1`, and the game recomputes it only
when *equipment* changes, never when an ability changes. THAC0 is cached in the
same place and behaves the same way. Editing ability scores is safe, but expect
combat numbers to lag until the game recalculates them for some other reason;
re-readying a piece of armour in game forces it.

**Everything decoded is now editable**, including the spellbook and the
memorised list. Two consistency rules the editor does **not** enforce, because
neither has been proven in game: a memorised spell ought to be one the character
knows, and the number memorised at each level ought to be within the capacity
their class, level and Wisdom allow. The export prints that capacity beside the
spellbook so you can check it yourself.
