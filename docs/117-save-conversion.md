# Converting between the DOS and C64 versions — plan

**Status: unblocked.** The DOS save arrived — Donald's Steam copy of
*Forgotten Realms: The Archives* carries a played DOS Pool of Radiance party in
three slots. **Obstacle 4 is closed**, and with it the remainder of obstacle 1:
the 217 quest-flag bytes are located inside a DOS saved game. Obstacles 2, 3
and 7 are now workable and each says below what it would take. The goal is one
thing: turn a DOS save into a C64 save. One direction only.

The decode, with its evidence: `work/reports/dos-saves.md`. The measurements
are asserted in `tests/test_dossave.py`, which reads the archives from
Donald's machine and skips where there are none.

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
The answer has improved: **yes for characters, and now plausibly for whole
saves** — the character record is decoded and checked, the quest flags are
located, and what is left is the party's position and the items' binary tail.

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
* **Items.** See obstacle 3 — DOS stores the item's name as text.

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
| `SAVGAM<slot>.DAT` | the saved game. **13137 bytes** — one header byte, then the engine's variable space as `u16le`; see obstacle 1 |

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
* **Item numbering** — because DOS has none. The item name is text in the DOS
  record and has to be looked up in the C64's `ITEMNAMES`.
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
| `$5900`-`$64FF` | 3072 | item area, 16 items x 16 bytes per slot | **probably** — the DOS item record is 63 bytes and names its item in ASCII, so this is a name lookup, not a renumbering |
| `$8300`-`$83FF` | 256 | roster: derived combat values | **yes** — recompute for the target, do not copy |
| `$8400`-`$8AFF` | 1792 | `ANIMATE00` and a bitmap buffer — **not save data at all** | **yes** — copy from any existing C64 save; the game overwrites it |
| `$4BE0`-`$4CFF` | 288 | combat icon table | **synthesise** — DOS has no equivalent; `por/iconparts.py` composes a legal icon |
| `$49C0`-`$49C2` | 3 | party x, y, facing | **only if area numbering and map geometry correspond** — unproven |
| `$4BC2` | 1 | current `GEO` | **same question**, and it is the same answer or the party lands in the wrong place |
| `$49C6`-`$49CB` | 6 | clock, six digits | **probably** — needs the DOS clock format |
| `$4BC0`-`$4BD8` | 25 | loaded-files cache | **yes** — port-specific indices; zero it and let the loader refill |
| `$4900`-`$49BF`, `$4B80`-`$4BBF` | 256 | four effect arrays | **yes, by dropping them** — zero means no active effects, which is a legal state |
| `$4A00`-`$4A1F` | 32 | per-script scratch | **yes** — `DUNGEON $202A` zeroes it on every area change anyway |
| `$4A20`-`$4AF8` | 217 | **persistent quest flags** | **yes.** Located: `SAVGAM?.DAT` offsets 577-1009, one `u16le` per C64 byte. See obstacle 1 |
| `$4AF9`-`$4B7F` | 135 | **not flag storage at all** — no ECL operand and no engine reference names anything in it | **yes** — zero, in all 21 specimens and by construction |
| the gaps | ~54 | `$49C3`-`$49C5`, `$49CC`-`$49E6`, `$49EA`-`$49EF`, `$49F2`-`$49FB`, `$49FF`, `$4BD9`-`$4BDF` | **unknown, mostly zero.** `$49C3`/`$49C4` are the wilderness travel position; the rest is unattributed |

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

**2. Area numbering and coordinates — now workable, and harder than it looked.**
`$4BC2` names the current map and `$49C0`/`$49C1` the square. The C64 `GEO`
files are a 16x16 grid per area. If the DOS maps are numbered differently, or
laid out differently, the party arrives somewhere else — possibly inside a
wall.

The DOS save is here, and it says the position is *not* in the variable array:
`$49C0`, `$49C1`, `$49C2` and `$4BC2` all read 0 in all three saves, including
two of parties standing in different places. So DOS keeps the square, the
facing and the current map somewhere else — one of `vm_GetMemoryValueType`'s
other ranges, or the 8016-byte tail of `SAVGAM?.DAT`.

*What would resolve it:* **two DOS saves one step apart.** Save, take one step,
save, diff — the same method that carried the whole C64 side of this project.
The changed bytes are the position; a second pair across an area boundary gives
the map id. Half an hour of play once a DOSBox harness exists.
`docs/123-parallel-sessions.md` plans instances; there is no DOSBox harness
yet, and that is what this obstacle is really waiting on.

**3. Item encoding — reframed, and easier than feared.** The C64 item area is
16 bytes per item with the name as an index into `ITEMNAMES`, and
`por/items.py` decodes it. **The DOS item record is 63 bytes and spells the
item's name out in ASCII** — up to 41 bytes of rendered text, then about 21 of
binary: weight as `u16le` at `+0x37`, quantity at `+0x39`, cost as `u16le` at
`+0x3A`, and an armour base at `+0x30` carrying the C64's own `48 + bonus`
encoding. The weight is confirmed by the encumbrance identity above.

So "do the item ids mean the same thing in both ports" was the wrong question:
**DOS stores no item id at all.** Converting is a *name lookup* against the
C64's `ITEMNAMES`, which is tractable and self-checking — every DOS name either
matches an entry or is reported. What is still open is the binary tail: which
of those 21 bytes carry the plus, the charges and the class restrictions.

*What would resolve it:* one DOS character with a known unusual item — a wand
with charges, a cursed weapon — saved and diffed. No emulator needed if the
item can be arranged; the shipped parties already give scrolls, bracers and a
ring of protection to compare against.

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

**7. Does the game validate the save? — now workable, and it needs no DOS
work at all.** Nothing suggests a checksum, and `wish` already writes saves the
game loads happily. What was blocking this was never the DOS save: it was that
nobody had *tried*. The experiment is one C64 save written from converted
fields and loaded in VICE, and it is the same experiment as before the DOS save
arrived. Do it at the point there is a first converted save, not before —
a checksum will announce itself immediately.

## What is not an obstacle

Worth stating, so effort does not go here: **byte order** (both little-endian,
now verified on a real DOS file rather than assumed), **text encoding** (the
record is ASCII on both, no PETSCII), **the D64 container** (`por/d64.py`
writes valid images with correct block counts today), **the DOS container**
(there isn't one — plain files, no checksum), **the save-versus-export
question** (DOS's export is the slot copied out, so one reader serves both),
and **party size** (six on both).

## What has to be found out first

1. **Where DOS keeps the party square, the facing and the current map.** Two
   saves one step apart. This is obstacle 2 and is now the only thing between
   here and a whole converted save.
2. **The binary tail of the 63-byte item record** — plus, charges,
   restrictions. Obstacle 3.
3. **Do the spell tables agree** between ports? The DOS spellbook is one byte
   per spell in a level-interleaved order; the C64's is 56 bits. The ordering
   has to be matched before the transpose can be trusted.
4. **Does DOS store anything the C64 does not?** Two things already: an
   encumbrance field and a per-item weight. Both are derived and can be
   dropped going to the C64.

## Order of work

1. `por/dos_layout.py`, declarative, confidence per field — the table in
   `work/reports/dos-saves.md` is what goes in it.
2. Read a DOS character into the existing YAML export. That alone is useful —
   it makes `wish-cli` a DOS character viewer.
3. Write a C64 record from that YAML.
4. The items, by name lookup against `ITEMNAMES`.
5. The quest flags, which are now a copy with a stride change.
6. Obstacle 2: two DOS saves one step apart, for the position and the map.
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
