# Converting between the DOS and C64 versions — plan

**Status: unblocked.** The DOS save arrived — Donald's Steam copy of
*Forgotten Realms: The Archives* carries a played DOS Pool of Radiance party in
three slots — and DOS can now be driven. **Obstacles 1, 2, 3, 4 and 7 are
closed**: the quest flags, the party's square, the current area and the whole
63-byte item record are all read, **the two ports number their areas the same
way and index their item names and item types the same way too**, and **a C64
save written from DOS fields loads and plays** — no checksum, no validation,
not a byte rewritten by the loader (obstacle 7). What is left is conversion
work, field by field, not a question about whether the game will accept it. The
goal is one thing: turn a DOS save into a C64 save. One direction only.

The decode, with its evidence: `work/reports/dos-saves.md` for the character
record and the saved game, `work/reports/dos-items.md` for the items. The
measurements are asserted in `tests/test_dossave.py` and `tests/test_dosbox.py`,
which read the archives from Donald's machine and skip where there are none.
`tools/dosbox.py` is the harness that drives the game: an isolated DOSBox on
its own X display, keystrokes through `xdotool`, and the save file as ground
truth.

**Obstacle 1 is closed.** The quest-flag region is read — 179 of its 352 bytes
named from the bytecode, 135 more provably not flag storage, 38 unattributed
padding — and the DOS half turned out not to be a translation problem at all:
the ECL bytecode is one artefact shared by every port, so 178 of the 179 named
flags sit at the *same address* on DOS. See obstacle 1.

That narrowing is worth more than it looks. It means **no DOS encoder** — we
never have to write a DOS save, so the DOS format only has to be decoded far
enough to source what the C64 needs, and any DOS field with no C64 counterpart
can simply be ignored. It also retires the whole round-trip question: there is
no round trip.

What it does demand is absolute: **we must be able to produce every byte of a
C64 save.** All 9216 of them. Not most, not the interesting ones — a save is a
verbatim memory image and the game reads all of it.

So the goal has a number, and the number is checkable:

| | named | of which meaning is UNKNOWN |
|---|---|---|
| `SAVEDGAME0` (7168 bytes) | **99.2%** | 38 bytes |
| `SAVEDGAME1` (2048 bytes) | **100%** | 0 |

The UNKNOWN figure was 352 until the quest-flag pass; what is left of it is
38 scattered bytes inside `$4A20`-`$4AF8` that no script names and that are
zero in every save we hold.

Being able to *name* a region is not the same as being able to *fill* it, which
is what the obstacle list below is about. But it says where the edges are, and
`por/memory.py` already generates it — so progress is measurable rather than
felt.

Donald asked whether the editor could turn a DOSBox save into a C64 save.
The answer has improved again: **yes for characters, and now for whole saves
as far as reading goes** — the character record is decoded and checked, the
quest flags are located, the party's square and area are located, and the item
record is read to the byte. What is left is not a decode but a demonstration:
write a C64 save from converted fields and load it.

---

## What the two formats actually are

The record is **rearranged, not translated**. Both ports store the same
information; neither stores it in the same place. The DOS record is **285
bytes**; the C64's is 580, of which 256 is the inventory and 36 the combat
icon — so the parts that correspond are almost the same size.

Every row below was checked against 24 real DOS specimens. Nothing in the
predicted table had to be corrected.

| field | DOS | C64 | |
|---|---|---|---|
| name | `0x000` length byte, then 15 | `0x000`, 20 bytes, NUL-padded | CONFIRMED |
| strength | `0x010` | `0x014` | CONFIRMED |
| intelligence | `0x011` | `0x015` | CONFIRMED |
| exceptional strength | `0x016` | `0x01A` | CONFIRMED |
| THAC0 base, `60 − value` | `0x02D` | `0x071` | CONFIRMED |
| race / class | `0x02E` / `0x02F` | `0x072` / `0x073` | CONFIRMED |
| age | `0x030`, 2 bytes | `0x074`, 2 bytes | CONFIRMED / the high byte is 0 in all 24 |
| hit points maximum | `0x032`, **1 byte** | `0x076`, **2 bytes** | CONFIRMED — `0x033` starts the spellbook, so there is no room for a second |
| saving throws | `0x06D`, 5 | `0x09A`, 5 | CONFIRMED |
| level | `0x073` | `0x0A0` | CONFIRMED |
| thief skills | `0x077`, 8 | `0x0A5`, 8 | PROBABLE |
| money — cp sp ep gp pp gems jewelry | `0x088`, 7 × `u16le` | `0x0BB`, 7 × `u16le` | CONFIRMED |
| per-class levels, 8 wide | `0x096` | `0x0C9` | CONFIRMED, **but differently ordered** — see below |
| sex | `0x09E` | `0x0D6` | PROBABLE |
| experience | `0x0AC`, `u24le` | `0x0E8`, `u24le` | CONFIRMED |
| class bitmask — 1 mage, 2 cleric, 4 thief, 8 fighter | `0x0B0` | `0x0EB` | CONFIRMED, same bit order |
| party order | `0x0BF` | `0x10D` | CONFIRMED |
| item count | `0x0C7` | — | CONFIRMED; the C64 carries the items in the record instead |
| encumbrance | `0x102`, `u16le` | — | CONFIRMED; the C64 has no such field |
| hit points current | `0x11B` | `0x119`, 2 bytes | CONFIRMED |

The early fields differ by **exactly four**, which is exactly how much wider the
C64's name field is — the abilities are otherwise in the same order. Past that
the layouts diverge properly; from THAC0 base onwards the gap is `0x44`.

**Three places where they diverge in kind, not merely in offset.** These are
the real conversion work.

* **The spellbook.** The C64 packs it into 7 bytes of bits at `0x078`. DOS
  spends **one byte per spell** across `0x033`–`0x06A`, in an order grouped
  cleric-1, mage-1, cleric-2, mage-2, cleric-3, mage-3. Transpose, do not copy,
  and check the ordering before trusting it.
* **The per-class level array.** Eight wide on both. The C64's slots are
  ordered by the class *bits* (magic-user, cleric, thief, fighter, knight, —,
  paladin, ranger); DOS's are indexed by the class *number* (cleric, druid,
  fighter, paladin, ranger, mage, thief, monk). Same width, different meaning
  per slot.
* **Items.** Less than it looked. See obstacle 3: past its cached display
  line the DOS record *is* the C64's 16 bytes, unpacked one field to a byte.

Two things that are *not* obstacles: **both machines are little-endian** —
now verified on the file rather than assumed, see below — and the DOS
character file is ASCII, so names need padding and length-prefixing rather than
transliteration. There is no PETSCII in the record.

**Byte order, checked rather than inherited.** The Amiga stores the DOS field
order big-endian, so the claim needed testing. Three readings agree it is
little-endian on DOS: experience read big-endian puts a level-3 fighter past
ten million; both elves come out aged 46080; and the encumbrance identity
below — arithmetic entirely inside the file — only balances one way round.

**The identity worth knowing**, because it checks four things at once:

```
encumbrance (0x102) = cp + sp + ep + gp + pp + gems + jewelry
                        + Σ (item weight × quantity)
```

It balances exactly for 16 of the 18 saved characters and for all six exports.
That single sum confirms the money block, the 63-byte item stride, the weight
offset and the byte order together.

The DOS layout was originally taken from the community format notes in
`work/coab-research/formats/`. **They were right about every field they
predicted.** That is a fact about those notes worth carrying to the next
title.

---

## The one converter that already exists: the game's own

Curse of the Azure Bonds imports a Pool of Radiance character, and
**`simeonpilgrim/coab` carries that routine as source**, recovered from the
shipped DOS overlays. It is the best outside evidence this project has for the
conversion, because it is not somebody's reading of a file format — it is the
arithmetic the engine runs.

The files, read from `work/forums/ext/` (fetched, `.gitignore`d, not committed):

| file | what it is |
|---|---|
| `Classes/PoolRadPlayer.cs` | the DOS **Pool of Radiance** record, `StructSize = 0x11D` (285), fields named where Simeon identified them |
| `Classes/Player.cs` | the DOS **Curse** record, `StructSize = 0x1A6` (422), with **81 machine-readable `[DataOffset]` attributes** |
| `engine/ovr017.cs` | `ConvertPoolRadPlayer` (`import_char01`'s Pool branch) — the import itself |
| `engine/ovr025.cs`, `ovr026.cs` | `reclac_player_values` (`sub_66C20`) and `ReclacClassBonuses` (`sub_6A3C6`), which run over the result |

*Confidence: PROBABLE throughout this section.* Nothing here has been checked
against a DOS file on this machine; it is read off someone else's decompilation.
But it derives from the shipped overlays and it agrees with our own offsets
wherever both name the same field.

### What the import does, field by field

`ConvertPoolRadPlayer` starts from a **zeroed** `Player`, so every field it does
not write is left at zero — and **106 of the 285 DOS Pool bytes are never even
read**, in seven runs: `0x17`–`0x2C` (22), `0x7F`–`0x82` (4), `0x88`–`0x95`
(**the seven money words**, 14), `0xBF` (party order), `0xC8`–`0xFF` (56,
containing the item pointer block at `0xCC`), `0x104`–`0x10B` (8) and `0x10F`.
What the routine
declines to carry is as informative as what it copies.

| what happens | source | lands on |
|---|---|---|
| **name** copied | Pool `0x00` | Curse `0x00` |
| **six abilities and exceptional strength**, each `Load`ed then `EnforceRaceSexLimits(race, sex)` | Pool `0x10`–`0x16` | Curse `0x10`–`0x1D` — and `Load` writes **both halves of the (base, current) pair**, which is why one Pool byte fills two Curse bytes |
| **THAC0, race, class, age, hit points maximum** copied | Pool `0x2D`, `0x2E`, `0x2F`, `0x30`, `0x32` | Curse `0x73`, `0x74`, `0x75`, `0x76`, `0x78` |
| **spellbook**: 56 bytes copied into a 100-byte array, then `spellBook[animate_dead − 1] = 0` | Pool `0x33`–`0x6A` | Curse `0x79`; spells 57–100 stay zero. `coab`'s enum gives `animate_dead = 0x24` — **spell id 36, exactly `docs/86`'s** |
| **attack level, `field_6C`, five saving throws, base movement, hit dice, levels lost, hit points lost, `field_76`, eight thief skills** copied | Pool `0x6B`–`0x7E` | Curse `0xDD`–`0xF1`. `multiclassLevel` (Curse `0xE6`) is set from hit dice, not from the source |
| `field_83`–`field_87` copied | Pool `0x83`–`0x87` | Curse `0xF6`–`0xFA` |
| **money: `Money.SetCoins(Money.Platinum, 300)`** | *nothing* | Curse `0xFB`. Pool's own money block at `0x88`–`0x95` is **not read by the loader at all** — `PoolRadPlayer` has no field there |
| **per-class levels, sex, monster type, alignment, the eight attack-form bytes, base armour class, experience, class flags, hit points rolled, spells-cast counts, the icon bytes and six icon colours** copied | Pool `0x96`–`0xC6` | Curse `0x109`–`0x14A` |
| **items** come from the separate `<name>.swg` file, not the record. The item *count* at Pool `0xC7` is commented out in the reimplementation; the assembly quoted beside it copies **0x34 = 52 bytes** of item pointers from Pool `0xCC` to Curse `0x151` | | |
| **the combat-state tail** — hands used, weight, health status, in-combat, team, hit bonus, armour class, attacks left, dice, damage bonuses, current hit points, movement | Pool `0x100`–`0x11C` | Curse `0x185`–`0x1A5` |
| **active effects are filtered.** From the Pool `.spc` file only seven effect ids survive: `18, 26, 47, 48, 97, 107, 124` | | `coab`'s `Affects` enum names them **gnome vs man-sized giant, dwarf vs orc, dwarf and gnome vs giants, `affect_30`, constitution saving bonus, elf sleep resistance, half-elf resistance** — every one an **innate racial or constitutional bonus**. Every temporary spell effect is dropped |

Then `reclac_player_values` and `ReclacClassBonuses` run over the result and
**recompute** armour class from base plus dexterity plus readied items; hit
bonus; movement; encumbrance; attacks per round; base THAC0, from a class × level
table, taking the maximum over the eight class slots; hit dice; the class-flags
bitmask, from the class-level array; the five saving throws; the thief skills,
**but only when thief level > 0**; and `attackLevel`, which is set to the fighter
class level or to 1 when there is none. A **cleric's entire spellbook is
regenerated** by level from the spell-casting table — and that loop excludes
`animate_dead` too, so the spell is erased twice over.

Two side observations worth keeping. `reclac_player_values` computes
encumbrance as `Σ (item weight × count) + Σ all seven money counts`, which is
**the identity above, confirmed from code** — and it means the field is derived,
not stored, so a converter never has to source it. And `docs/116`'s open
question about where Curse keeps its dual-class array has a lead: DOS Curse
`0xE6` is `multiclassLevel`, and it has no C64 counterpart under the alignment
below.

### Against our own measurement: 12 of the fifteen bytes

`docs/116` imported three Pool of Radiance characters into C64 Curse, exported
one again, and found **15 of 580 bytes changed**. The DOS routine accounts for
twelve of them.

| our change (`docs/116`) | the DOS routine | |
|---|---|---|
| `0x065`–`0x06B`, the second ability array, written from `0x014`–`0x01A` (7 bytes) | `stats2.X.Load(pool.stat_X)` — Curse stores every ability as a (base, current) pair and `Load` writes both halves from Pool's single byte | **explained** |
| `0x0C1` gold zeroed (1 byte) and `0x0C3` platinum set to 300 (2 bytes) | Pool's money is never read; a fresh `MoneySet` is all zero and `SetCoins(Platinum, 300)` is the only write | **explained, and sharper than we measured** — see the prediction below |
| `0x098` fighting level set (1 byte) | `reclac_player_values`: `attackLevel = SkillLevel(Fighter)`, else 1 | **explained** |
| `0x10F` roster armour class recomputed (1 byte) | `reclac_player_values`: `ac = base_ac`, then dexterity and readied-item bonuses | **explained** |
| `0x073` `char_class` zeroed (1 byte) | the DOS routine *copies* the class byte straight across | **not explained** |
| `0x0FE`, `0x0FF` portrait head and body zeroed (2 bytes) | the DOS routine copies `head_icon` and `weapon_icon` straight across | **not explained** — but they are probably not the same field. The C64's 36-byte combat icon at `0x220` passes through untouched, so `0x0FE`/`0x0FF` are the C64's own indices into `CHARPIC00`, which Curse does not share |

`docs/116` also saw saving throws change where an item bonus had been baked in,
and **thief skills re-derived rather than copied**. Both are `ReclacClassBonuses`
exactly: `reclac_saving_throws` unconditionally, `reclac_thief_skills` only for a
thief. And what passed through byte for byte — experience, level, the per-class
level array, class bits, hit points, the spellbook, race, age, alignment, sex —
is what the routine copies verbatim, or recomputes to the same value it started
from.

**Four predictions the C64 experiment can now test**, none of which the party
used could have shown:

1. **All seven money words are discarded**, not just gold. We saw gold zeroed
   because the character carried gold; import one carrying copper, gems and
   jewelry and every word should come out zero except platinum = 300.
2. **ANIMATE DEAD is erased.** Spell id 36, which is bit 4 of `0x07C` in the
   C64's spellbook bitmask at `0x078` — the mask indexes by spell id, not by
   id − 1. No character imported so far knew the spell.
3. **A cleric's spellbook is regenerated from his level**, not copied — which is
   invisible for a Pool cleric, who already knows every spell he can cast, but
   would show on a cleric whose book had been edited.
4. **Only innate racial effects survive.** Import a character under a lasting
   spell effect and it should be gone.

### Where the C64 record sits against DOS Curse

The 81 `[DataOffset]` attributes make the DOS Curse record machine-readable, and
laid against `por/layout.py` the two run **the same fields in the same order**
at three displacements:

| zone | DOS Curse → C64 | why it shifts |
|---|---|---|
| name and abilities | +4 on the early fields | the C64 name field is 20 bytes to DOS's 16 |
| THAC0 `0x73` → `0x071`, race `0x74` → `0x072`, class `0x75` → `0x073`, age `0x76` → `0x074`, hit points `0x78` → `0x076` | **−0x02** | |
| attack level `0xDD` → `0x098`, saving throws `0xDF` → `0x09A`, movement `0xE4` → `0x09F`, thief skills `0xEA` → `0x0A5` | **−0x45** | **the spellbook**: DOS spends one byte per spell (56 in Pool, 100 in Curse), the C64 one *bit* — 7 bytes at `0x078` |
| money `0xFB` → `0x0BB`, per-class levels `0x109` → `0x0C9`, class flags `0x12B` → `0x0EB` | **−0x40** | the C64 gains five bytes: DOS spends 9 bytes on a 4-byte far pointer to the affect list plus five flag bytes (`0xF2`–`0xFA`), the C64 spends 14 (`0x0AD`–`0x0BA`) holding the item effects **inline** |

**The one field that is not a re-offset of the same data is the spellbook.** Any
DOS→C64 converter has to expand or pack that field and can copy almost
everything else.

One place the alignment is ambiguous by a byte, and it is worth saying so rather
than papering over it: `0x0A0`–`0x0A5`. DOS Curse runs hit dice, multiclass
level, levels lost, hit points lost, `field_E9`, thief skills; the C64 runs
level, levels drained, hit points lost to drain, turn class, turn power, thief
skills. DOS Pool has no `multiclassLevel` — the importer sets it from hit dice —
and `docs/117`'s own DOS Pool table has level at `0x073` → `0x0A0` (CONFIRMED)
and thief skills at `0x077` → `0x0A5` (PROBABLE), a one-byte gain in between.
The reading that fits everything is that **`multiclassLevel` is Curse-only and
the C64's `turn_class` at `0x0A3` has no DOS counterpart**, the two cancelling so
that −0x45 resumes at `0xE9` → `0x0A4`. PROBABLE, and one Curse specimen with a
turn-undead class settles it.

---

## What a DOS save actually is, as files

No container and no checksum: DOS writes plain files into its save directory.
Steam redirects that directory to `SavesDir/<steamid>/<appid>/English/`.

| file | what it is |
|---|---|
| `CHRDAT<slot><1..6>.SAV` | one character of the saved party. **285 bytes** |
| `<NAME>.CHA` | one *exported* character. **The same 285 bytes, same layout** — the export is the slot copied out, not a reduced form. The only systematic difference is that the item count at `0x0C7` is zeroed |
| `<stem>.ITM` | that character's items, **63 bytes each**, no header |
| `<stem>.SPC` | that character's active effects, **9 bytes each**; absent when there are none |
| `CHARLIST.TXT` | the names the "add character" menu offers. Plain text, CRLF |
| `SAVGAM<slot>.DAT` | the saved game. **13137 bytes** — one header byte, then the engine's variable space as `u16le`; see obstacle 1. The header byte is the `GEO`/`ECL` `.DAX` file number of the current area, 1–8; see obstacle 2 |

Slots are letters, not numbers; the engine's own format strings (visible in
Gold Box Companion's `Game.dat`) are `CHRDAT%s%d.SAV` and `SAVGAM%s.DAT`.

## Characters first, because they are the tractable half

The **character file** is what the games themselves move: Pool of Radiance
exports characters and Curse of the Azure Bonds imports a party. Getting that
working is step one and is worth having on its own — and because a DOS export
and a DOS save slot are byte-for-byte the same structure, one reader serves
both.

But the goal is the whole save, so the rest of this plan is about what stands
in the way.

## One warning for anything past Pool of Radiance

**The DOS record grows with every title: 285, 422, 439, 510 bytes for Pool of
Radiance, Curse, Secret of the Silver Blades and Pools of Darkness.** The C64
record does not — Curse reuses Pool of Radiance's 580 bytes at the same
offsets, which is this project's most valuable transferable fact.

*That fact is a C64 fact.* From Curse onwards the DOS record stores every
ability **twice**, as (base, current) pairs at `0x010`–`0x01D`, and everything
after shifts by `0x46`. A DOS reader is per title. What does hold across the
family is the item stride (63) and the effect stride (9), Pool of Radiance
through Pools of Darkness and across into the Savage Frontier pair.

---

## The shape of it

We already have the neutral middle. `por/yaml_io.py` decodes a C64 record into
named fields and writes it back; `por/layout.py` is the field table. Conversion
is the same idea with a second table:

```
DOS character file  ->  decode  ->  named fields  ->  encode  ->  C64 record
```

That means a new `por/dos_layout.py` beside `por/layout.py`, in the same
declarative style with a confidence on every field, and the existing YAML
export as the interchange. **No new format is invented**: the middle is the one
the editor already uses.

---

## What cannot survive the trip, and must be said out loud

* **The combat icon.** C64 icons are 18 screen codes into `CHARPIC00` plus 18
  colours — a C64 charset. DOS has no such thing, so the icon must be built
  from the option tables (`por/iconparts.py` composes a legal one).
* **Portrait ids.** `HEADnn`/`BODYnn` name files on the C64 disks. The DOS art
  is a different set with different numbering.
* **Anything cached rather than stored.** The C64 roster block holds derived
  combat values; they should be recomputed for the target, not copied.
* **The item list's heap pointers.** DOS chains its items through a far
  pointer at `0x02A`; the C64 keeps 16 fixed slots. Drop the chain, keep the
  order. (Item *numbering* is not on this list after all: the DOS name words
  and type byte are already the C64's indices.)
* **Spell numbering**, until someone checks it. DOS stores one byte per spell
  in a level-interleaved order; the C64 stores 56 bits. The spell *list* is the
  same game, so the mapping probably exists. **Do not assume it.**
* **Encumbrance and per-item weight**, which DOS keeps and the C64 does not.
  Both are derived; drop them.

## Losslessness, which is the project's whole promise

`wish` never modifies a save it was given, and a no-op save is byte-identical.
Conversion is a different act — it *creates* a save — so the promise takes a
different form:

* the DOS save is **read only**, always; the C64 save is a new file;
* **every byte written must be justified.** Either it came from the DOS save,
  or it was computed, or it is a documented constant. "Copied from a template
  and probably fine" is a category that should not exist by the end.
* every DOS field with no C64 home is **reported**, not silently dropped;
* the finished converter should be able to say, for any offset in its output,
  *where that byte came from*. That is the test, and it is stricter than a
  round trip would have been.

---

## Everything a C64 save contains, and whether we can produce it

`SAVEDGAME0` is a verbatim image of `$4900`-`$64FF` (7168 bytes) and
`SAVEDGAME1` of `$8300`-`$8AFF` (2048). To write one, **every byte has to come
from somewhere.** This is the whole list.

| region | size | what it is | can we produce it from a DOS save? |
|---|---|---|---|
| `$4D00`-`$58FF` | 3072 | twelve character slots | **yes, with work** — a field remap, `por/dos_layout.py` |
| `$5900`-`$64FF` | 3072 | item area, 16 items x 16 bytes per slot | **yes** — the DOS item record's last 17 bytes *are* the C64's 16, unpacked; `tools.dosbox.item_to_c64` is the copy. Obstacle 3 |
| `$8300`-`$83FF` | 256 | roster: derived combat values | **yes** — recompute for the target, do not copy |
| `$8400`-`$8AFF` | 1792 | `ANIMATE00` and a bitmap buffer — **not save data at all** | **yes** — copy from any existing C64 save; the game overwrites it |
| `$4BE0`-`$4CFF` | 288 | combat icon table | **synthesise** — DOS has no equivalent; `por/iconparts.py` composes a legal icon |
| `$49C0`-`$49C2` | 3 | party x, y, facing | **yes** — DOS keeps them at file offsets 12801, 12802, 12803; the facing is the C64's doubled. Obstacle 2 |
| `$4BC2` | 1 | current `GEO` | **yes** — DOS keeps the area id at file offset 395, in the same numbering. Obstacle 2 |
| `$49C6`-`$49CB` | 6 | clock, six digits | **probably** — needs the DOS clock format |
| `$4BC0`-`$4BD8` | 25 | loaded-files cache | **yes** — port-specific indices; zero it and let the loader refill |
| `$4900`-`$49BF`, `$4B80`-`$4BBF` | 256 | four effect arrays | **yes, by dropping them** — zero means no active effects, which is a legal state |
| `$4A00`-`$4A1F` | 32 | per-script scratch | **yes** — `DUNGEON $202A` zeroes it on every area change anyway |
| `$4A20`-`$4AF8` | 217 | **persistent quest flags** | **yes.** Located: `SAVGAM?.DAT` offsets 577-1009, one `u16le` per C64 byte. See obstacle 1 |
| `$4AF9`-`$4B7F` | 135 | **not flag storage at all** — no ECL operand and no engine reference names anything in it | **yes** — zero, in all 21 specimens and by construction |
| the gaps | ~54 | `$49C3`-`$49C5`, `$49CC`-`$49E6`, `$49EA`-`$49EF`, `$49F2`-`$49FB`, `$49FF`, `$4BD9`-`$4BDF` | **unknown, mostly zero.** `$49C3`/`$49C4` are the wilderness travel position; the rest is unattributed. Do not fill any of it from the DOS save: DOS keeps its *own* current area at the `$49C5` and `$49F2` entries, which is a DOS fact about a DOS engine and says nothing about what the C64 puts there |

## The obstacles, worst first

One direction removes two of these outright: nothing below requires writing a
DOS file, and nothing requires a C64 field to survive a trip back.

**1. The quest flags — the correspondence is identity.**
`$4A20`-`$4B7F` is 352 bytes. Every one of them has a disposition
(`work/reports/quest-flags.md`): **179 named** from an ECL instruction that
writes them, **135** (`$4AF9`-`$4B7F`) shown not to be flag storage at all, and
**38** unreferenced padding between the per-area blocks. The region is one
private block per area script plus the City Hall's books.

**And the other ports use the same addresses.** Two independent lines:

* **Amiga Pool of Radiance.** `ecl.dax` on disk 2 of the rips in
  `/mnt/media/roms/amiga/` unpacks to the C64's own scripts — 29 of the C64's
  30, each carrying the C64 `ECL` load address `$1388`, seven of them
  byte-identical. Walking them for `$4A20`-`$4B7F` references gives 1409 hits
  across **171 addresses, against the C64's 172**, with no Amiga-only address.
  The 26-entry ledger at `$4AA6`, the ten `ADD 1` sites on `$4AC1` and the
  eight-entry lock table at `$4AEA` are all present unchanged. One flag,
  `$4AD1` in the lizardman keep, is gone on the Amiga along with the encounter
  that set it. (The Amiga is a proxy for the *scripts* only. Its character
  record follows the DOS field order but stores multi-byte fields big-endian —
  don't read the DOS layout off it.)
* **DOS, through Curse of the Azure Bonds**, where we hold both ports.
  Decoding DOS `coab/Data/ECL*.DAX` and diffing against C64 `CURSE*.D64`
  `ECL*`: of the 24 scripts in both, **18 differ only in the 2-byte load
  address** (`$1388` DOS, `$3000` C64), two are byte-identical, four differ in
  length because the C64 split them. The payload — absolute address operands
  included — is the same bytes.

So the DOS flag addresses are `$4A20`-`$4AF8`, meaning what the report says.
CONFIRMED for the Amiga, PROBABLE for DOS, the gap being that no DOS *Pool of
Radiance* `ECL` file has been read, only DOS *Curse*.

*What is left* is not the meaning but the **offset**: the C64 save is a memory
image based at `$4900`, so the block is `SAVEDGAME0` offset `0x122`.

**Where the same 217 bytes sit in a DOS save is now answered, and the answer is
better than a bare offset.** `SAVGAM<slot>.DAT` is one header byte followed by
a 16-bit little-endian array of the engine's whole variable space, indexed by
the address the ECL bytecode itself uses:

```
file offset of ECL address A  =  1 + 2 × (A − $4900)
```

2560 entries cover `$4900`-`$52FF`; the remaining 8016 bytes are resident
engine state. The mechanism is in the Curse reimplementation:
`vm_SetMemoryValue` in `work/coab/engine/ovr008.cs` ends in
`area_ptr.field_6A00_Set(0x6A00 + (location * 2), value)` — the operand
address doubled — and `ovr021.cs` annotates the same array `// as WORD[]`.

Read that way, three saves of two different parties agree with
`work/reports/quest-flags.md` line for line: the six Sokal Keep flags
(`$4A21`, `$4A26`-`$4A29`, `$4AD7`) are 255 in the save whose party has taken
the keep and 0 in the two that have not; the seven consecutive slum flags
`$4ACA`-`$4AD0` are set together or not at all; `$4ABB` counts slum encounters
cleared; and `$4AC1`, the commissions counter with ten `ADD 1` sites, reads
0, 1 and 2 across the three saves in the order the parties progressed. Every
nonzero word in the 217-entry window is 1, 2, 3 or 255 and none exceeds 255 —
the C64's bytes, widened. A base off by one would straddle the runs.
**CONFIRMED**, and asserted in `tests/test_dossave.py`.

So the flag transfer is now a copy with a stride change: read the DOS word,
write the C64 byte.

*Tooling*, all in `work/amiga/` (gitignored): `adf.py` reads the Amiga
filesystem, `dax.py` the container — a big-endian index of `id:u16
offset:u32 compSize:u16 rawSize:u16` entries, and a ByteKiller-style backwards
bit-cruncher transcribed from the routine at `program` hunk27`+$7346`. All 843
blocks of all 23 `.dax` files decompress to their stated size with a zero
checksum. There is no `DAxF` magic and no `POOLDATA` volume; that was invented.

**2. Area numbering and coordinates — CLOSED, and the numbering agrees.**
The position is not in the variable array — `$49C0`, `$49C1`, `$49C2` and
`$4BC2` read 0 in every save — so it was found the way the C64 side found
everything: by driving the game and diffing saves one action apart.

| what | in `SAVGAM<slot>.DAT` | |
|---|---|---|
| party x | byte **12801** | CONFIRMED |
| party y | byte **12802** | CONFIRMED |
| facing | byte **12803**, `0` N `2` E `4` S `6` W — **the C64's value doubled** | CONFIRMED |
| current area | `u16le` at **395**, the array entry for `$49C5`; **the same numbering `por/areas.py` uses** | CONFIRMED |
| — the same id again | `u16le` at **485**, the entry for `$49F2` | CONFIRMED |
| which `GEO`/`ECL` `.DAX` file holds that area, 1–8 | byte **0**, the file's header byte; and again at **3621**, the entry for `$5012` | CONFIRMED |

**Byte 0 is not the map.** It is the container: `GEO3.DAX` holds areas 0 and
14, `GEO4.DAX` holds 2, 10 and 21, and so on, so the header narrows the area to
two to six candidates and no further. That distinction is the whole reason this
obstacle needed the array entry as well.

The evidence, all from driven runs:

* **Four turns on one square.** The status line read `5,2 E`, `5,2 S`,
  `5,2 W`, `5,2 N` while byte 12803 read 2, 4, 6, 0 — and 12801/12802 held at
  5, 2 throughout. A step then moved 12802 alone, 2 to 1.
* **One area crossing inside one session.** Taking the boat from Sokal Keep
  back to Phlan moved the area id 21 → 0, the header byte 4 → 3, and the square
  from (8, 14) to (15, 1); the 7429-byte area blob in the tail changed with it.
* **The ids are the game's own.** Area 0 sits in `GEO3.DAX`, area 21 in
  `GEO4.DAX`, area 20 in `GEO2.DAX` — read straight out of the container
  indexes — and the header byte of a save in each is 3, 4 and 2. Donald's three
  saves decode as New Phlan, Sokal Keep and the Slums, which is where those
  parties are.
* **A cross-port check nobody arranged.** `por/areas.py` records New Phlan's
  arrival square as (15, 1) facing west, measured on the C64. The DOS boat
  lands the party on DOS (15, 1) facing 6. Same square, same direction, two
  ports.

*What is left of it*: the geometry is checked at one square in one area. Two
ports agreeing on the arrival square is good evidence that a coordinate means
the same square, but it is one specimen; a converted save landing the party
where it should is the test that settles it, and that is obstacle 7.

**3. Item encoding — CLOSED, and it is a copy.** The 63-byte DOS item record
is a cached display line, a heap pointer, and then **the C64's own 16-byte item
record with its packed bytes spread out one to a byte**:

```
0x000        length byte for the rendered line
0x001-0x029  the rendered inventory line, up to 41 bytes  — a CACHE, not a source
0x02A-0x02D  far pointer to the next item, NULL on the last — live heap state
0x02E        item type          -> C64 +0        0x037  weight u16le  -> +8,+9
0x02F-0x031  three name words   -> C64 +1,+2,+3  0x039  quantity      -> +10
0x032        plus, signed       -> C64 +4        0x03A  cost u16le    -> +11,+12
0x033        save bonus, signed -> C64 +5        0x03C  charges       -> +13
0x034        readied            -> C64 +6 bit 7  0x03D  effect        -> +14
0x035        hidden-name mask   -> C64 +6 bits 0-2  0x03E  power         -> +15
0x036        cursed             -> C64 +7 bit 7
```

`tools.dosbox.item_to_c64` is that projection, and the projection is the
evidence: applied to every record in the DOS game's own `ITEM1.DAX`-`ITEM8.DAX`
it reproduces **157 of the 163 distinct item records on the C64 disks byte for
byte**, packed bytes included. One wrong offset, sign or bit collapses the
count. The six that miss are items the two ports hand out in different places.

Three things fall out, and each was an open question.

* **The plus** is `0x032`, signed: `+1`, `+2`, `+3` against the printed names,
  and `-5` in both `0x032` and `0x033` on a cursed necklace, which is the
  C64's `+4`/`+5` pair exactly. The game prints its own field names in a debug
  panel — `plus`, `plussave`, `ready`, `identified`, `cursed`, `value`,
  `special(1..3)` — in that order (`work/coab/engine/ovr020.cs`).
* **The charges** are `0x03C`. The game's use-item routine spends `count`
  (`0x039`) while it is above one and then decrements `0x03C`, destroying the
  item at zero. Three `WAND OF MAGIC MISSILES` templates differ in that byte
  alone — 20, 33, 35.
* **The class restrictions are not in the item record.** They are byte +13 of
  the `ITEMS` type table, indexed by `0x02E` — and the DOS `ITEMS` file is
  byte-identical to the C64's in **126 of its 128 records**, the two that
  differ being dagger and dart differing in range, with the class flags equal.
  Nothing to convert.

And the name is not a text match after all: `0x02F`-`0x031` hold **the C64's
own `ITEMNAMES` indices** — 48 is `MAIL`, 162 is `+1`, 208 is `CLERICAL
SCROLL`, on both ports. The rendered line is a cache the game rewrites when it
draws the list, it goes stale (`11 Darts` over a quantity of 8), and nothing
should be sourced from it.

No emulator was needed. The `.DAX` item files put every magic item in the game
on disk, and the decompiled routine says what the byte does. Reading them
needed the DOS container: a `u16le` index size, `size / 9` entries of
`id:u8, offset:u32le, raw:u16le, compressed:u16le`, then byte-level
run-length-coded blocks — all 46 blocks of the eight `ITEM*.DAX` decode to
exactly their stated size and every size is a whole number of 63-byte records.

Full working: `work/reports/dos-items.md`. Asserted in `tests/test_dosbox.py`.

**4. We have no DOS save. — CLOSED.** Donald's Steam copy of *Forgotten
Realms: The Archives* carries three played slots, 18 saved characters and 6
exports. Everything above was checked against them; see
`work/reports/dos-saves.md` and `tests/test_dossave.py`.

**5. The DOS layout we have is community documentation, not our own decode.**
`work/coab-research/formats/` is where the record table came from. **It has now
been checked, and every field it predicted was right** — name, the abilities,
exceptional strength, THAC0 base, race, class, age and the one-byte hit points.
Downgraded from an obstacle to a recommendation: those notes are good, and the
next title should start from them.

Gold Box Companion, shipped in `games/*/GBC/`, is a second source of the same
kind: a live-memory editor for DOSBox whose data files publish the level
tables (`thac0_base` in the *stored* biased form, `attacks` in halves, the five
saving throws per class per level), the experience tables, 256 effect names and
the race/class/spell name tables. **Treat it as PROBABLE the way the 1990 C64
editors were treated.** Where a real save agreed with it — the THAC0 bias, the
cleric saving throws, the class and race numbering — those fields are CONFIRMED
here on the strength of the save, not of the tool.

**6. The undocumented gaps.** About 54 bytes of `SAVEDGAME0` have no name.
They are almost all zero in the saves we hold, so writing zero is very probably
right — but "very probably" is doing work in that sentence.

**7. Does the game validate the save? — CLOSED. It does not.** A save written
from DOS fields was loaded on the C64 and the game took it without a murmur:
**no checksum, no fixup, not one byte rewritten by the loader.**

What was written: `PORSAVE12.D64`, a played C64 save standing in New Phlan, with
four regions replaced from DOS slot A (`SAVGAMA.DAT` and `CHRDATA1`-`6.SAV` /
`.ITM`), which is a party in New Phlan too — the same area on both sides on
purpose, so `$4BC2` and the loaded-files cache were left true rather than
invented.

| region | bytes changed | from |
|---|---|---|
| six character slot windows `$4D00`-`$52FF` | 205 | the DOS record, field by field |
| six inventories `$5900`-`$5EFF` | 465 | `tools.dosbox.item_to_c64` per item |
| quest flags `$4A20`-`$4AF8` | 27 | the DOS word array, narrowed to bytes |
| party square `$49C0`-`$49C2` | 3 | file offsets 12801-12803, facing halved |
| `SAVEDGAME1` roster | 6 | current hit points and party order |

**700 of `SAVEDGAME0`'s 7168 bytes, and the game loaded every one of them.**
`$4900`-`$64FF` read out of the running machine after `BEGIN ADVENTURING` is
**byte-identical to the file** — 0 of 7168 differ — so nothing is checksummed,
nothing is recomputed on load, and no field is normalised. The party stood in
the world at the DOS save's own square, (4,3) facing north, and the roster
listed the six DOS characters with their armour class and hit points.

The sheets agree with DOS too. `SILAS` reads `MALE HUMAN AGE 20 / NEUTRAL GOOD /
FIGHTER`, `STR 18(100)`, `LEVEL 4  EXP 9559`, `HITPOINTS 70`, `AC 2`,
`THACO 18  DAMAGE 1D8+5`, and his `ITEMS` list is the six records of
`CHRDATA6.ITM` in order — `SHIELD +1` readied, `LONG SWORD +1` not,
`BROAD SWORD +1` readied, `SHORT BOW +1` not, `PLATE MAIL` readied,
`50 ARROW(S)` not — which is what `por.items` reads out of the same block.
Then the party walked: five steps across New Phlan and out through the gateway
into the Slums, which loaded `GEO14` and ran `ECL14`'s arrival normally.

The converter that made it is a throwaway — `work/p20/convert.py` and
`build2.py`, which is gitignored along with the rest of `work/` — because the
real one is `por/dos_layout.py` and the order of work below. It exists only to
answer this question, and it answered it.

*What this does not yet prove.* The converted save is not a whole conversion:
the spellbook, the combat icons, alignment, the effect arrays and the clock were
left as the base save had them, the area was deliberately the same on both sides
so `$4BC2` and the loaded-files cache were never exercised, and only 27 of the
217 flag bytes actually differed from the base's — both parties are early in the
game. What is settled is the question that was asked: **a save the game did not
write, carrying another port's field values, loads and plays.** The rest is
conversion work, not validation risk.

## What is not an obstacle

Worth stating, so effort does not go here: **byte order** (both little-endian,
now verified on a real DOS file rather than assumed), **text encoding** (the
record is ASCII on both, no PETSCII), **the D64 container** (`por/d64.py`
writes valid images with correct block counts today), **the DOS container**
(there isn't one — plain files, no checksum), **the save-versus-export
question** (DOS's export is the slot copied out, so one reader serves both),
**party size** (six on both), and **the item tables** (the `ITEMS` type table
and the `ITEMNAMES` indices are shared between the ports; see obstacle 3).

## What has to be found out first

1. **Do the spell tables agree** between ports? The DOS spellbook is one byte
   per spell in a level-interleaved order; the C64's is 56 bits. The ordering
   has to be matched before the transpose can be trusted. The item side gives
   one free check on the namespace: a DOS scroll's three special bytes hold
   spell ids that the C64's own scrolls carry unchanged.
2. **Does DOS store anything the C64 does not?** Three things: an encumbrance
   field, a per-item weight, and the item list's heap pointers. All derived or
   live-only, and all droppable going to the C64.
3. **The clock.** `$49C6`-`$49CB` is six digits on the C64 and the DOS format
   is unread.

## Order of work

1. `por/dos_layout.py`, declarative, confidence per field — the tables in
   `work/reports/dos-saves.md` and `work/reports/dos-items.md` are what go in
   it.
2. Read a DOS character into the existing YAML export. That alone is useful —
   it makes `wish-cli` a DOS character viewer.
3. Write a C64 record from that YAML.
4. The items, which are `tools.dosbox.item_to_c64` and a stride change: 16
   items of 16 bytes per C64 slot, the DOS list being a chain of 63-byte
   records whose length the character record's `0x0C7` gives.
5. The quest flags, which are now a copy with a stride change.
6. The party's square and area, which are now four reads and a doubling.
7. An editor menu item, once the CLI path is trustworthy.

## Verification

* A DOS character read and written back unchanged, byte for byte — the same
  losslessness bar the C64 side already holds. The DOS side is read-only in
  practice, but the reader has to be able to prove it understood the file.
* The encumbrance identity balances on every converted character. It is the
  cheapest whole-record check available and it costs nothing to keep.
* Every DOS field with no C64 home is **reported**, not silently dropped.
* A converted character **loads in Pool of Radiance on the C64** and its sheet
  reads the same. That is the only test that really counts, and it needs one
  emulator, not two.
