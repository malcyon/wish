# Live memory map

Addresses observed in a running game via VICE's binary monitor. Remember the
game is heavily overlaid: an address is only meaningful while the overlay that
owns it is resident.

**For a plain lookup — "what is at `$4BC2`" — see
[41-memory-regions.md](41-memory-regions.md)**, generated from `por/memory.py`.
This page keeps the reasoning and the game's own string tables.

## Party / character data

| Range | Contents |
|---|---|
| `$4900–$4CFF` | party/global header (what `SAVEDGAME0` saves first) |
| `$4D00–$64FF` | character slot area — see `docs/30-savegame-layout.md` |
| `$8300–$83FF` | the **party roster blocks** — eight 32-byte entries, one per slot, holding AC, THAC0, current hit points, movement and the damage bonus. See `docs/30-savegame-layout.md` |
| `$8400` | a jump table (`4C xx 84`) — code, and the reason the roster is known to stop at `$83FF` |
| `$8300–$8AFF` | the whole region saved as `SAVEDGAME1` |

`SAVEDGAME0` is a verbatim dump of `$4900–$64FF`, so live addresses and
save-file offsets differ only by the `$4900` base.

## Game vocabulary tables

Read out of a running game at the copy-protection prompt, so these are the
game's own strings rather than anything inferred.

**Races** — `$3243`, NUL-separated:

```
DWARF  ELF  GNOME  HALF-ELF  HALFLING  HALF-ORC  HUMAN  MONSTER
```

**Genders** — `$327C`: `MALE  FEMALE`

**Classes** — `$3288`:

```
CLERIC  DRUID  FIGHTER  MAGIC-USER  THIEF  MONK
```

**Alignments** — `$32B3`, in the conventional AD&D order. The record's
`alignment` byte at `0x0D8` is a **0-based index into exactly this list**,
confirmed against six characters of known alignment:

```
LAWFUL GOOD      LAWFUL NEUTRAL   LAWFUL EVIL
NEUTRAL GOOD     TRUE NEUTRAL     NEUTRAL EVIL
CHAOTIC GOOD     CHAOTIC NEUTRAL  CHAOTIC EVIL
```

**Ability labels** — `$332B`: `AGE STR INT WIS DEX CON CHR`
**Money labels** — `$3347`: `COPPER SIL[VER]…`

### Indexing — RESOLVED, and the two bases really are different

The sample save shipped on `POOL1.D64` supplied two more specimens and settled
this:

* **Races are 1-based**: `DWARF=1 ELF=2 GNOME=3 HALF-ELF=4 HALFLING=5
  HALF-ORC=6 HUMAN=7 MONSTER=8`. BRUTUS and ZARRADA are 7 (human), LARA is 2
  (elf, and aged 176 — consistent).
* **Classes are 0-based**: `CLERIC=0 DRUID=1 FIGHTER=2 …`. BRUTUS is 2 and plays
  as a fighter; ZARRADA is 0 and carries the AD&D 1e level-1 **cleric**
  saving-throw table (10/13/14/16/15) rather than the fighter one
  (14/15/16/17/17).

So the inconsistency flagged earlier is real, not a mistake — the two fields
genuinely use different bases. Do not "tidy" one to match the other.

### The class list is a menu, not the class table

`$3288` has six entries and omits PALADIN and RANGER. It is the
*character-creation menu* list — confirmed by driving the game, where picking
HUMAN offers only CLERIC / FIGHTER / MAGIC-USER / THIEF. Real class values run
beyond it: LARA SPELLSWORD has `char_class = 13`, a multi-class code (elf
fighter/magic-user).

**The full encoding is now known**, from the class table the 1989 BASIC editor
displays, which agrees with all four multi-class codes we had already derived
from the bitmask at `0x0EB`: 8 cleric/fighter, 9 cleric/fighter/magic-user,
10 and 11 cleric/magic-user, 12 cleric/thief, 13 fighter/magic-user,
14 fighter/thief, 15 fighter/magic-user/thief, 16 magic-user/thief. See
`docs/20-character-record.md`. `class_bits` remains the field to prefer.

## Other tables spotted (not yet mapped in detail)

| Address | Contents |
|---|---|
| `$0A35` | overlay/file name list (`ITEMS`, `SITE`, `MNAMES`, `CHARSET`, `SOUNDFX`, `DUNGEON`, `TITLEPG`, `MUSIC`, `SPR.TP`, `MDRIVER`, `COMBAT`) |
| `$2BBB` | more overlay names (`GEN`, `DUNGEON`, `COMBAT`, `INIT`, `COM.PREP`, `POST`, `FINAL`, `CAMP`) |
| `$40EA` | data-file name stems (`GDRIVE`, `SQRPACI`, `SECSET`, `SPELLN`, `SPELLE`, `WALLSET`, `WALLDEF`, `SPRITE`, `BODY`, `HEAD`, `CHARPIC`, `COMPIC`, `ITEMFILE`) |
| `$4487` | menu verbs (`VIEW ITEMS SPELLS TRADE DROP EXIT`) |
| `$4549` | item menu verbs (`READY TRADE DROP HALVE JOIN SELL EXIT`) |
| `$46A6` | error strings (`CURSED`, `WRONG CLASS`, `TOO MANY…`) |

## `$7101`, `$7800`, `$7926`, `$794D` are one table — CONFIRMED

They were listed here for a while as four separate string lists — weapon names,
item adjectives, gem names, deity names. They are not four lists. They are four
windows onto the **resident `ITEMNAMES`**, and the arithmetic is exact:

`ITEMNAMES` loads at **`$6F00`** and opens with 256 low bytes and 256 high bytes
of a pointer table, so its string block begins at `$6F00 + 512 = $7100`. Reading
the file at each of those addresses gives:

| address | file offset | reads |
|---|---|---|
| `$7101` | 0x201 | `BATTLE AXE`, `HAND AXE`, `BARDICHE`, `BEC DE CORB…` — word-table entry **1** onward |
| `$7800` | 0x900 | `HUGE`, `BONE`, `BRASS`, `KEY`, `AC2`, `AC6`… |
| `$7926` | 0xA26 | `DIAMOND`, `EMERALD`, `OPAL`, `SAPHIRE`… |
| `$794D` | 0xA4D | `TEMPUS`, `OF SUNE`, `WOODEN`, `+3 VS UNDEAD`… |

`$7101` landing exactly on entry 1 is the check that could have failed and did
not. All four are `docs/85-item-tables.md`'s single 252-entry word table, and
an item's printed name is three indices into it — noun, qualifier, suffix.

**The base is the game's own operand, not a fit.** `LIBRARY` reads the table with
`LDA $6F00,X / STA $07`, and the same instruction in the later titles reads
`$9E00`. `tests/test_titletables.py` asserts it per title. The race labels are the
same pool: `LDA $9E8C,X` is `$9E00 + 140`, so a race name is word-table entry
`140 + race`, read straight out of `ITEMNAMES`. See
`work/reports/p40-title-tables.md`.

Nothing in the tool depends on the resident copy — `por/items.py` reads the disk
file — but the identity is worth having, because it means one table explains every
name the game prints for an item.
