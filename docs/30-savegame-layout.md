# Save game layout

## The two files: characters, and the party

A save disk holds two files, and the split between them is not arbitrary. It is
also not quite "characters here, everything else there" — `SAVEDGAME0` holds
three distinct things:

**`SAVEDGAME0`, the character slots** (`$4D00`–`$54FF`). Eight slots of `$100`,
each holding what a character *is* in their own right: name, race, class,
ability scores, hit point maximum, money, experience, thief skills, saving
throws, the spellbook, and the spells currently memorised. Nothing here depends
on who else is in the party.

**`SAVEDGAME0`, the header** (`$4900`–`$4CFF`). The party and its place in the
world: where it is standing (`$49C0`, `$49C1`), which way it faces (`$49C2`), a
counter that rises with everything it does, and the combat-icon table at
`$4BE0`. This is the part that moves when you walk, and most of its 1 KB is
still unread.

**`SAVEDGAME1`, the roster** (`$8300`–`$83FF`). Eight 32-byte blocks holding what
a character *is right now, as a member of this party*: armour class, THAC0,
current hit points, movement as encumbered, damage bonus. Every one of these is
a value the game **derives** from the character plus their equipment, and caches
rather than recomputing on load. **Everything past `$8400` is not save data at
all** — it is resident code and a graphics buffer that happened to be in memory
when the game dumped the range. See below.

**A caution about the obvious reading.** "`SAVEDGAME0` is the characters and
`SAVEDGAME1` is the world" is wrong, and it was assumed here for a while: the
automapper note had map coordinates down as `SAVEDGAME1`'s business on exactly
that reasoning. Walking six saves' worth leaves `SAVEDGAME1` **byte-identical**.
The world is in `SAVEDGAME0`'s header; `SAVEDGAME1` is about the party's
characters and nothing else.

That division is Donald's reading of the game's own behaviour, and it explains
the layout well: you can create as many characters as you like and add only some
of them to the party, so the game needs somewhere to keep the character and
somewhere separate to keep the party's view of them. The roster block even
carries a **slot index** at `+0x0D` pointing back at the `SAVEDGAME0` slot it
describes -- indirection that would be pointless if the two were simply parallel
arrays, which in every save we hold they are.

Two things stop this being the whole story, and are worth stating so nobody
assumes more than the evidence gives:

* Both files hold **eight** entries, so `SAVEDGAME0` is not an unbounded
  character library. Characters *not* in the party are written to the save disk
  as separate `\x01NAME` files, one per character, in the exported record format.
* No save we hold has a roster block pointing anywhere other than its own index,
  so the indirection has never been seen in use.

**Why it matters when editing.** Change a character's dexterity in `SAVEDGAME0`
and their armour class in `SAVEDGAME1` does not follow: the game recomputes the
cache when *equipment* changes and at no other time. An editor that writes only
`SAVEDGAME0` -- as the 1989 BASIC editor did, and as `wish` did until recently --
cannot touch armour class, THAC0, current hit points or the damage bonus at all,
because none of them is in the character record.

**Base and current are different fields in different files.** This is the single
most useful thing to hold on to:

| Value | Base, in `SAVEDGAME0` | Current, in `SAVEDGAME1` |
|---|---|---|
| THAC0 | `0x071`, as `60 - THAC0` | roster `+0x0E`, same encoding |
| movement | `0x09F` (12, unencumbered) | roster `+0x1B` (9 in banded mail) |
| hit points | `0x076` maximum | roster `+0x19` current |

The base value is what the character is worth stripped of circumstance; the
current value includes their readied weapon, their armour and their wounds. A
character sheet shows the **current** one. That is why `0x071` was written off
early as "not THAC0" -- MALCYON's sheet reads `THACO 20` while the byte holds
39, and `60 - 39` is 21, his base as a level-1 magic-user. The 20 on screen is
the roster's value after he readied a dart.

The slot layout is settled by a full six-character party — see
[the slot stride, corrected](50-experiments.md) in the experiment log. The
specimen set has grown well past the two saves that first suggested it; it is
listed in [90-specimens.md](90-specimens.md).

## Files on the save disk

| File | Raw bytes | Load addr | Memory covered |
|---|---|---|---|
| `\x01BRUTUS` | 582 | `$6B00` | standalone character export |
| `SAVEDGAME1` | 2050 | `$8300` | `$8300–$8AFF` |
| `SAVEDGAME0` | 7170 | `$4900` | `$4900–$64FF` |

Raw sizes include the 2-byte PRG load address; payloads are 580 / 2048 / 7168.

## SAVEDGAME0 is a raw memory image

The game dumps `$4900–$64FF` verbatim — no header, no packing, no checksum (the
thirteen-field edit was accepted without complaint). Non-zero byte counts per
page, on the original **single-character** save:

```
$4900:  8   $4A00:  2   $4B00: 52   $4C00: 255    <- header region ($400 bytes)
$4D00: 41   $4E00:  0   $4F00:  0   $5000:   0
$5100:  0   $5200:  0   $5300:  0   $5400:   0
$5500: 41   $5600:  0   ... slots 8-11, used only in combat
```

The name `BRUTUS` appears at `$4D00` and `$5500`.

### Slot layout — 8 slots of `$100`

```
$4900–$4BDF   header / party globals
$4BE0–$4CFF   8 combat icons of 36 bytes  (ends exactly at $4D00)
$4D00–$58FF   12 character slots of $100 — 0-7 the party, 8-11 combat
$5900–$64FF   item area — one $100 block per slot, 16 items of 16 bytes
```

A slot holds only the **first 256 bytes** of the 580-byte character record.
Verified against a real six-character party: every slot is byte-identical to the
first 256 bytes of that character's own exported `.chr` file.

Everything a character sheet needs falls inside those 256 bytes — name,
abilities, race, class, age, hit points, saving throws, money. What lives
*outside* them is the combat icon (record offset `0x220`, stored once per slot
in the shared `$4BE0` table) and the item area.

The icon table has **8** entries, which is what first suggested 8 slots. That
match is real but it counts the *party*, not the slot array — icons are a party
thing, and slots 8-11 never need one.

### Twelve slots, of which the party uses eight

`LIBRARY $312B` computes **both** `$4D00 + n*$100` and `$5900 + n*$100`, and the
arithmetic only closes at twelve:

```
records   $4D00 + 12 * $100 = $5900     <- exactly where the item area starts
items     $5900 + 12 * $100 = $6500     <- exactly where SAVEDGAME0 ends
```

At eight there is an unexplained `$400` gap. So `$5500` is **slot 8** and
`$5600`–`$58FF` are slots 9, 10 and 11. Combat fills them: the combatant table
indexes 0–63, the party occupies 0–7 in save-slot order, and monsters take the
rest.

**This page was long described here as a "staging page."** It held one record in
the character layout — a copy of slot 0 in the original single-character save,
and the encountered monster (`MON04`, `ORC`, 254 of its 256 bytes identical to
the file on the game disk) in every save taken after the orc fight. That reading
was right about what was *in* it and wrong about what it *was*: not scratch, but
slot 8 holding a combatant. See [the orc left behind at `$5500`](50-experiments.md)
and [the combat research](50-experiments.md).

Nothing outside combat should read slots 8–11. A monster loaded there carries
seven of the eight `$FF` residue bytes, so it reads as a half-marked NPC.
`SLOT_COUNT` in `por/savegame.py` is deliberately **8** — the party, which the
game enforces at six player characters and eight total.

### Correction: this was previously recorded as 6 slots of `$400`

That was wrong, and worth understanding because the error was invisible for a
long time. It came from a save holding only **two** characters: the bytes
between them were zero, and a mostly-zero exported record agreed with them, so a
580-byte contiguous record at `$4D00` appeared to fit. The sample save on
`POOL1.D64` (characters at `$4D00` and `$5100`) seemed to confirm it — but under
the correct `$100` model those are simply slots 0 and 4, so it was consistent
with both readings and proved nothing.

**Only a full party could distinguish the two models**, and it disproves `$400`
immediately: six characters at `$100` intervals would overlap catastrophically
under the old reading.

## The `$4900–$4CFF` header

A `$400`-byte region ahead of the slots. Partly understood.

### Combat icons — `$4BE0–$4CFF`

The last `$120` bytes are a table of **8 entries of 36 bytes**, ending exactly at
`$4D00` where slot 0 begins (`$4BE0 + 8 × $24 = $4D00`). Each entry is C64 screen
codes plus colour values — the character's **combat icon**.

The same 36 bytes also appear inside the character record itself, at record
offset `0x220–0x243` (its final bytes). That is what accounts for most of the
44-byte difference between an exported `.chr` file and the same character's
in-party copy: the icon is present in the export and zero in the slot, because
the party keeps icons in this shared table instead.

The table has **8** entries, one per character slot.

### Where world and quest state must live

**One region, not two.** The header at `$4900`–`$4BDF` — `$2E0` bytes — is the
only place left. `SAVEDGAME1` past the roster page is ruled out: it is code and
graphics scratch, not state.

The change in `SAVEDGAME1` above `$86B4` that this section once pointed at is
the animator **modifying its own operands**, not the game recording anything.

**Position is solved**, and it is in the header, not in `SAVEDGAME1`:

| Address | Field |
|---|---|
| `$49C0` | x |
| `$49C1` | y — rises going south |
| `$49C2` | facing: 0 north, 1 east, 2 south, 3 west |
| `$49F0`, `$49F1` | the square occupied before the last move |
| `$49C7`–`$49C9` | **the clock, HH:MM**: units of a minute, tens of a minute, then the hour. `DUNGEON $09F7` prints `$49C9 : $49C8 $49C7`. Rises by a minute per step and per turn in place |

Established by walking three steps north and three steps west and diffing: each
leg moved one coordinate by exactly 3 and left the other alone. `por/savegame.py`
exposes all of it as `SaveGame0.party`. Two header bytes that moved only on
leaving the inn, `$4A07` and `$4BC6`, are still unexplained.

`SAVEDGAME0` is a verbatim image of `$4900`–`$64FF`, so a file offset is just
`address - $4900 + 2`, the two being the PRG load address. The coordinates are
bytes **194**, **195** and **196** of the file — useful if you want to read them
without the library.

The cheapest way in is a **flag experiment**: save, do exactly one thing in the
game that the game must remember, save again, diff. A guide reports that talking
to the fortune teller in the slums raises the difficulty of random encounters
there — true or not, if the game changes its behaviour it has to record that it
happened, and one conversation is about as isolated an action as this game
offers. See `docs/50-experiments.md`.

### Other header bytes

Sparse and mostly unidentified. One candidate worth testing:

| address | offset | PORSAVE | POOL1 sample | note |
|---|---|---|---|---|
| `$49FC` | `+$0FC` | 2 | — | matches PORSAVE's two character records; plausible **party count** |

Everything else in `$4900–$4BDF` is a scatter of single bytes with no established
meaning. The editor preserves the whole header verbatim.

## SAVEDGAME1 past the roster: `ANIMATE00` and a bitmap buffer

**CONFIRMED. `$8400`–`$8AFF` holds no save data.** The game dumps `$8300`–`$8AFF`
verbatim, and only the first page is state; the rest is whatever was resident.

| Range | Size | Contents |
|---|---|---|
| `$8400`–`$8753` | 852 | the on-disk file **`ANIMATE00`** — a 7-entry jump table (`4C xx 84`) and a VIC bitmap blitter |
| `$8754`–`$882F` | 220 | zero in every specimen |
| `$8830`–`$8AFF` | 720 | C64 multicolour bitmap scratch, the leading edge of the animator's data |

The `EUD` / `PTTP` / `DQP` / `DPU` "ASCII runs" this section once flagged as a
possible journal are `45 55 44` and `50 54 54 50` — pixel patterns.

Ruled out by [SAVEDGAME1 past the roster is code](50-experiments.md).

## Character export vs in-party copy

The standalone `\x01BRUTUS` file and the same character's record at `$4D00` agree
in **536 of 580 bytes**. The 44 differing bytes are now largely accounted for:

* the **combat icon** at record offset `0x220–0x243` (36 bytes) is populated in
  the exported file and zero in the in-party record, because the party stores
  icons in the shared table at `$4BE0` instead;
* the remainder fall in the item area around `0x100` and `0x10D–0x11B`.

So an exported `.chr` is close to self-contained, while an in-party record leans
on the header for its icon. An editor writing a record into a slot should leave
the icon bytes as it finds them rather than copying them from an export.

## SAVEDGAME1: the party roster blocks

`SAVEDGAME1` loads at `$8300`. The **first eight** 32-byte blocks are a
**per-character roster entry**, one per party slot, in the same order as the
`SAVEDGAME0` slots:

    block N  =  $8300 + N * $20        N = 0..7

Eight blocks of `$20` fill `$8300`-`$83FF` exactly, and `$8400` begins a jump
table (`4C xx 84`), so the roster's extent is settled: it is one page, and there
is no ninth block. This was originally written up as six blocks, because every
save then to hand held a six-character party; `npc_party.d64` fills all eight and
its index bytes run 0..7.

| Offset | Field | Confidence | Notes |
|---|---|---|---|
| `+0x03` | spells memorised, **1st level** | PROBABLE | see below |
| `+0x04` | spells memorised, **2nd level** | PROBABLE | |
| `+0x05` | spells memorised, **3rd level** | PROBABLE | |
| `+0x0C` | unknown; `$80` on some characters | GUESS | see below |
| `+0x0D` | slot index | CONFIRMED | 0..7, matches the `SAVEDGAME0` slot |
| `+0x0E` | **THAC0**, stored as `60 - THAC0` | PROBABLE | see below |
| `+0x0F` | **armour class**, stored as `60 - AC` | CONFIRMED | AC 8 -> 52, AC 2 -> 58 |
| `+0x10` | armour bonus (shield excluded), stored as `48 + bonus` | PROBABLE | none 48, leather 50, banded mail 54 |
| `+0x11` | unknown; **not** a flag | GUESS | 1 for banded mail and 0 for leather across six characters, which read as "armour has cut the movement rate" until MALCYON turned up reading 3, unarmoured, at full movement |
| `+0x15` | tracks readied equipment | GUESS | 2 with nothing readied; +1 per weapon, +2 per shield, +3 per body armour |
| `+0x17` | **damage bonus** | PROBABLE | strength bonus plus the readied weapon's own |
| `+0x19` | **current hit points** | CONFIRMED | |
| `+0x1B` | **movement rate** | CONFIRMED | 12 normally, 9 in banded mail |

### `+0x03`-`+0x05`: retracted as the spell counts, and not settled since

These three bytes were written up as the number of spells memorised at levels 1,
2 and 3. **That reading is wrong**, and it is worth keeping the whole story
because it is a good example of a hypothesis that sparse data agreed with.

The evidence for it was `npc_party.d64`, where all eight characters fit
perfectly: every non-caster read `0/0/0`, and for the four casters the sum of the
three bytes equalled the number of ids in their memorised list exactly -- 13 for
SIMON, 11 for DIRTEN, 8 for XAVIER, 5 for GENHEERIS. Four for four, at four
different values.

Then Donald memorised spells on three characters **and rested**, and saved. The
memorised lists at record offset `0x020` filled in as expected. The roster page
did not change *at all* -- it is byte-identical to the save before it, and these
three bytes still read `0/0/0` for a party with five spells memorised between
them.

So whatever they are, they are not a straightforward count of the list at
`0x020`. `wish` exports them as `unknown_03_05` rather than pretend otherwise.

*An earlier version of this document explained the discrepancy as "memorised but
not yet rested". Donald had rested. The explanation was invented to save the
hypothesis, which is exactly what it should not have been used for.*

**A later reading weakens the retraction without overturning it.** Two things
came out of `PORSAVE11`, the save that had never been read. The per-level
agreement on `npc_party.d64` is sharper than was recorded — the three bytes
match the ids **level by level**, eight characters for eight, not merely in
sum — and in `PORSAVE11` ROLAND's three level-1 cleric spells sit beside a
`+0x03` of 3 while both magic-users, whose lists are now empty, read 0. Against
that, the contradicting save is a **single** observation: the roster page is
byte-identical across `PORSAVE2` through `PORSAVE9`, so it was written once, on
an equipment change, and was stale for everything that happened afterwards —
which is the caching behaviour armour class already shows. The bytes stay
unknown, because "the cache was stale" is exactly the kind of explanation that
rescued the hypothesis last time. What settles it is a save taken straight after
memorising at two different spell levels. See
[the spell counts, and how thin the retraction was](50-experiments.md).

**Where the spell data actually lives**, both in the character record:

| Offset | Field |
|---|---|
| `0x020` | the ids currently **memorised**, highest spell level first |
| `0x078`-`0x07E` | a bitmask of the spells the character **knows** |

How many a character *may* memorise is not stored anywhere we have found; it
follows from class, level and Wisdom, and `por/spells.py` computes it from the
AD&D 1st edition tables.

### THAC0 sits next to armour class, in the same encoding

`+0x0E` holds THAC0 the same way `+0x0F` holds armour class: as `60 - value`.
The two combat numbers the character sheet prints side by side are stored side
by side, in the same form.

On the six-character party before anything was readied, every value is the exact
AD&D 1st edition number for that character's class, level and Strength:

| Character | Class | Strength | Stored | AD&D THAC0 |
|---|---|---|---|---|
| MALCYON | magic-user 1 | 15 | 21 | 21 |
| LADY KATHERINE | magic-user/thief 1 | 16 | 21 | 21 |
| ROLAND | fighter 1 | 15 | 20 | 20 |
| SILAS | fighter 1 | 18/81 | 18 | 20 less 2 for Strength |
| MAGNUS | fighter 1 | 18/80 | 18 | 20 less 2 |
| BRUTUS | fighter 1 | 18/98 | 18 | 20 less 2 |

Six of six, including the two classes that are 21 rather than 20 at first level.
The stored value is the **current** THAC0, not a base: on the eight advanced
characters of `npc_party.d64` three match the table exactly and the other five
all read *better* than it, by 2 or 3, which is what readied magic weapons should
do. Nothing anywhere reads worse than the table.

One anomaly: MALCYON's value improves from 21 to 20 across the shopping trip,
where all he acquired was darts. A readied weapon should not improve THAC0 by
itself at DEX 16. Unexplained.

This is PROBABLE rather than CONFIRMED for the usual reason -- it has been read,
never written and checked in game.

### The combat line, complete

The character sheet prints `THACO 20  DAMAGE 1D3` beside `AC 8`, and all of it
is now accounted for:

| Shown | Where it lives |
|---|---|
| AC | roster `+0x0F`, as `60 - AC` |
| THAC0 | roster `+0x0E`, as `60 - THAC0` |
| damage dice | the item's entry in the `ITEMS` type table on the game disk |
| damage bonus | roster `+0x17` |

`+0x17` matches the AD&D 1st edition strength table on all twelve characters of
the unarmoured/armoured pair, and the one character whose value changed --
ROLAND, 0 to 1 -- did so because he readied a mace, which does 1d6**+1**. The
byte is the *total*: strength bonus plus the weapon's own.

### What the rest of the block is not

Six bytes carry something we cannot name: `+0x00`, `+0x03`–`+0x05`, `+0x13`,
`+0x1C` and `+0x1E`. (`+0x11`, `+0x15` and `+0x17` have readings in the table
above.) Everything else in the 32 is zero in every specimen. Ruled out along
the way:

* **Encumbrance is not in the block** as a number: no byte holds the carried
  weight, which is computable from the inventory. The movement rate at `+0x1B`
  does respond to it, though — LADY KATHERINE drops from 12 to 6 between two
  saves on loot alone, with no change of armour.
* **Status is not in the block** -- no specimen has a wounded-to-unconscious or
  dead character to move one, but nothing plausible varies.
* `+0x00` and `+0x13` are `1` in every occupied block on every disk. Structural
  markers rather than data.
* `+0x0A` and `+0x0B` were zero in every specimen until `PORSAVE11`, where they
  read 21 and 8 on ROLAND — the one character whose `+0x03` moved at the same
  time. Unexplained.
* `+0x1C` and `+0x1E` are zero in all of Donald's saves and non-zero only on the
  editor-hacked `npc_party.d64`, so nothing can be concluded from them.

### `+0x0C`: a near-miss worth recording

In `npc_party.d64` byte `+0x0C` is `$80` for all five NPCs and `$00` for all
three player characters, which looks exactly like an NPC flag. It is not one:
MALCYON is a player character and his `+0x0C` is `$00` in `PORSAVE.D64` and
`$80` in `PORSAVE2.D64`, having changed over a shopping trip. Whatever the bit
means, it is something a player character can acquire. The real NPC
discriminator is in the character record instead.

### This is where armour class lives -- and why it goes stale

Armour class is **not** in the 580-byte character record. Equipping banded mail on
four characters changed no byte of any character slot; every slot-level difference
between `PORSAVE.D64` and `PORSAVE2.D64` was money, experience, or the spellcaster
flag. AC is cached here, in `SAVEDGAME1`, and is recomputed only when **equipment**
changes -- never when an ability score changes.

That closes the open question from [the hunt for current hit points](50-experiments.md). In `PORSAVE4.D64` MALCYON's DEX had been
edited from 16 to 18, which should improve his AC from 8 to 6. The cached byte
stayed at 52, and the character sheet on screen still read `AC 8`. The editor was
working correctly; the game simply never recomputes the cache from DEX.

Verified against the sheet: MALCYON `+0x0F` = 52 -> `AC 8`, `+0x19` = 4 ->
`HITPOINTS 4`.

**Consequence for the editor:** changing DEX (or armour) in the YAML will not move
a character's AC until the game recomputes it. Re-readying a piece of armour in
game forces the recompute; alternatively `+0x0F` can be written directly.

### Reproducing the derivation

AC = 10 - armour - shield - DEX defensive adjustment, matching AD&D 1st edition for
five of six characters:

| Character | Readied | DEX | Expected AC | `60 - byte` |
|---|---|---|---|---|
| MALCYON | (dart only) | 16 | 8 | 8 |
| LADY KATHERINE | leather armor | 16 | 6 | 6 |
| ROLAND | banded mail | 13 | 4 | 4 |
| SILAS | banded mail, shield | 12 | 3 | 3 |
| MAGNUS | banded mail, shield | 15 | 2 | 2 |
| BRUTUS | banded mail, shield | 14 | 3 | **2** |

~~BRUTUS is one point better than the rules predict~~ — **resolved, and the
rules were the problem.** Pool of Radiance gives a dexterity bonus to armour
class from **14**, where AD&D 1st edition starts at 15. Read straight off
`PORSAVE.D64`, where nobody is wearing anything at all, so armour class is 10
minus the dexterity adjustment and nothing else:

| DEX | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|
| armour class | 10 | 10 | **9** | 9 | 8 |
| AD&D would give | 10 | 10 | **10** | 9 | 8 |

BRUTUS has DEX 14 and was the only character in the party who did, so the
one-point gap looked like something about *him*. It was about the table. With
the corrected table every character in every save comes out consistent, and
`por/derive.py` uses it.

The penalties for low dexterity are still the book's, because no specimen has a
dexterity below 12. If the whole table is shifted by one they are wrong too, and
nothing we hold would show it.

**Record byte `0x0B8` is still unexplained.** BRUTUS remains the only character
whose copy changed, 0 to 1, when the party equipped — but that is now a loose end
on its own rather than a suspected cause of an armour-class discrepancy that has
turned out not to exist.

### An independent check on all of this

The 1989 BASIC character editor on `poolce.d64` edits an **exported** character
and its author writes, in the bundled documentation, that he never found AC or
THAC0 and that hit point changes do not show up until you pay for healing at a
temple. Both follow from the layout above: an exported `.chr` is the 580-byte
record alone, and AC and current hit points are not in it. Somebody working the
same problem from the inside, thirty-seven years ago, hit exactly the wall this
section describes.
