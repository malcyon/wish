# The character record

580 bytes, uncompressed, the same in Pool of Radiance and Curse of the Azure
Bonds. On disk an export is a PRG: a 2-byte load address then the 580 bytes.
Inside a save, only the **first 256 bytes** sit in the character slot.

## A record is four blocks the game saves separately

| Record range | Size | Where it goes in a save |
|---|---|---|
| `0x000`-`0x0FF` | 256 | the character slot |
| `0x100`-`0x11F` | 32 | the **roster block** |
| `0x120`-`0x21F` | 256 | the item area |
| `0x220`-`0x243` | 36 | the combat-icon table |

`256 + 32 + 256 + 36 = 580`. Two agents reached this independently — one from
the loader routine that copies `roster_base + N*$20` in and out, the other from
matching exports against saves by name — and an export and the roster page agree
in **31 of 32 bytes for every character**, differing only at `0x10D`
(marching order in an export, the record slot index in a roster block).

**So there is no mysterious "export delta".** An earlier figure of 44 bytes came
from reading 580 contiguous bytes out of a `$100` slot and running off the end
into zeroed neighbours. If your export-versus-save diff is large, check your
slot stride before theorising.

## Base versus current: the single most useful thing to hold on to

The record holds what a character is worth **stripped of circumstance**; the
roster block holds the **current** value including weapon, armour and wounds. A
character sheet shows the current one.

| Value | Base, in the record | Current, in the roster |
|---|---|---|
| THAC0 | `0x071`, as `60 - THAC0` | `+0x0E`, same encoding |
| armour class | `0x0E1`, as `60 - AC` | `+0x0F`, same encoding |
| movement | `0x09F` (12, unencumbered) | `+0x1B` (9 in banded mail) |
| hit points | `0x076` maximum | `+0x19` current |

`0x071` was written off once as "not THAC0" because a magic-user's sheet read
20 while the byte held 39 — and `60 - 39` is 21, his base as a level-1
magic-user. The 20 on screen was the roster's value after he readied a dart.

**Every pair of fields this project understood turned out to be
base-versus-current rather than a duplicate.** When two fields look like copies
of each other, that is the first hypothesis, not "one is redundant".

## The biased encodings

Three fields are stored as an offset because the value gets *better* as it gets
smaller and the game wanted a byte that rises.

| Stored as | Fields |
|---|---|
| `60 - value` | THAC0 and armour class — record `0x071`, `0x0E1`, `0x10E`, `0x10F`; roster `+0x0E`, `+0x0F` |
| `48 + value` | the armour bonus at roster `+0x10` |
| `12 - AC` | an item's protection nibble in the item type table |

Wrap these in functions, not constants. `60 - (-5)` is `65`, a perfectly
ordinary byte, so a silent wrap produces a plausible wrong number.

**`60 - x` is the first encoding to try** on any new combat-adjacent byte in a
new title.

## Indexing bases genuinely differ between fields

* **Races are 1-based**: `DWARF=1 ELF=2 GNOME=3 HALF-ELF=4 HALFLING=5
  HALF-ORC=6 HUMAN=7 MONSTER=8`.
* **Classes are 0-based**: `CLERIC=0 DRUID=1 FIGHTER=2 …`.

That inconsistency is real. Do not "tidy" one to match the other. Confirmed by
saving-throw tables: a class-0 character carries the AD&D 1e level-1 cleric row
(10/13/14/16/15) rather than the fighter one (14/15/16/17/17).

**Prefer `class_bits` at `0x0EB` to `char_class` at `0x073`.** The bitmask is
`magic-user=1 cleric=2 thief=4 fighter=8` OR-ed together, with bits 6 and 7
added for paladin and ranger in Curse; `char_class` is a single code whose
multi-class values run past the class-name table, and Curse zeroes it entirely.

**The class-name table in memory is the character-creation menu, not the class
table.** It has six entries and omits paladin and ranger, because the creation
menu offers only what a given race can be. Real class values run beyond it.

## Two useful cross-checks that need no emulator

* **AD&D 1st edition tables.** Saving throws, thief skills, THAC0, hit dice and
  experience thresholds are all published. A field that matches the published
  table for every specimen at the right class and level is CONFIRMED by external
  rule, not by correlation. This is how five saving throws, eight thief skills
  and THAC0 were settled.
* **Monsters use the character-record layout.** So the monster files are a free
  corpus of a hundred-plus more specimens, with values a player character never
  has: real armour classes, undead turning rows, and the `$FF` residue that marks
  a record as not-a-player. `0x0E1` reads 10 for every player character (that is
  unarmoured, before dexterity), which made it look like a constant — the
  monsters put their real armour class there and match the Monster Manual.

## The layout table discipline

The field table must **tile the whole record**: every one of the 580 bytes
belongs to exactly one entry, with gaps generated automatically as `UNKNOWN`
regions and the invariant asserted at import time.

Why it matters: an edit can then never silently drop bytes nobody understands
yet, overlaps are impossible to introduce, adding a field is a one-line change,
and the documentation and coverage figures generate from the table rather than
being maintained beside it.

Report coverage honestly. This project has 139 of 580 bytes named — 24% — and
says so. A generated table with a coverage figure is worth more than prose
claiming the record is "mostly understood".

## Where specimens come from

* **`REMOVE` a character from the party** writes a complete 580-byte file to the
  save disk. Diffing two exports is far cleaner than diffing whole saves,
  because it removes all party-context noise.
* **A varied party is better than a before/after pair.** Six characters with
  different races, classes, sexes and alignments identified seven fields in
  minutes with no emulator at all. Compare *different characters* first; fall
  back to before/after diffing only for fields that need a character to *change*
  — experience, level, damage, inventory.
* **Outside specimens are worth having and worth distrusting.** A hacked save
  found online had worthless values but its *structure* bounded the roster at one
  page and settled character level, because it was the only specimen with eight
  slots filled and characters above level 1.
