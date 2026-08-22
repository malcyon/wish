# Converting between the DOS and C64 versions — plan

**Status: parked, waiting on a DOS save.** Donald has one and will supply it
later; until then obstacles 2, 3, 4 and 7 below cannot be worked at all. The
goal is one thing: turn a DOS save into a C64 save. One direction only.

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

Donald asked whether the editor could turn a DOSBox save into a C64 save and
back. The short answer is **yes for characters, probably not for saves**, and
the difference is worth stating before any code is written.

---

## What the two formats actually are

The record is **rearranged, not translated**. Both ports store the same
information; neither stores it in the same place.

| field | DOS | C64 |
|---|---|---|
| name | `0x000` length byte, then 15 | `0x000`, 20 bytes, NUL-padded |
| strength | `0x010` | `0x014` |
| intelligence | `0x011` | `0x015` |
| exceptional strength | `0x016` | `0x01A` |
| THAC0 base | `0x02D` | `0x071` |
| race / class | `0x02E` / `0x02F` | `0x072` / `0x073` |
| age | `0x030`, 2 bytes | `0x074`, 2 bytes |
| hit points maximum | `0x032`, **1 byte** | `0x076`, **2 bytes** |

The early fields differ by **exactly four**, which is exactly how much wider the
C64's name field is — the abilities are otherwise in the same order. Past that
the layouts diverge properly.

Two things that are *not* obstacles, and are worth saying so nobody worries
about them: **both machines are little-endian**, so multi-byte fields need no
swapping; and the DOS character file is ASCII, so names need padding and
length-prefixing rather than transliteration. There is no PETSCII in the record.

The DOS layout above comes from the community format notes in
`work/coab-research/formats/`, **not from a file we have decoded ourselves**.
Treat it as PROBABLE until checked against a real DOS save.

---

## Characters first, because they are the tractable half

The **character file** is what the games themselves move: Pool of Radiance
exports characters and Curse of the Azure Bonds imports a party. Getting that
working is step one and is worth having on its own.

But the goal is the whole save, so the rest of this plan is about what stands
in the way.

---

## The shape of it

We already have the neutral middle. `por/yaml_io.py` decodes a C64 record into
named fields and writes it back; `por/layout.py` is the field table. Conversion
is the same idea with a second table:

```
DOS character file  ->  decode  ->  named fields  ->  encode  ->  C64 record
C64 record          ->  decode  ->  named fields  ->  encode  ->  DOS file
```

That means a new `por/dos_layout.py` beside `por/layout.py`, in the same
declarative style with a confidence on every field, and the existing YAML
export as the interchange. **No new format is invented**: the middle is the one
the editor already uses.

---

## What cannot survive the trip, and must be said out loud

* **The combat icon.** C64 icons are 18 screen codes into `CHARPIC00` plus 18
  colours — a C64 charset. DOS has no such thing. Going to C64, the icon must
  be built from the option tables (`por/iconparts.py` composes a legal one);
  going to DOS, it is dropped.
* **Portrait ids.** `HEADnn`/`BODYnn` name files on the C64 disks. The DOS art
  is a different set with different numbering.
* **Anything cached rather than stored.** The C64 roster block holds derived
  combat values; they should be recomputed for the target, not copied.
* **Item and spell numbering**, until someone checks they agree. They may; the
  spell list is the same game. **Do not assume it.**

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
| `$5900`-`$64FF` | 3072 | item area, 16 items x 16 bytes per slot | **probably** — needs the DOS item encoding and a check that item numbering agrees |
| `$8300`-`$83FF` | 256 | roster: derived combat values | **yes** — recompute for the target, do not copy |
| `$8400`-`$8AFF` | 1792 | `ANIMATE00` and a bitmap buffer — **not save data at all** | **yes** — copy from any existing C64 save; the game overwrites it |
| `$4BE0`-`$4CFF` | 288 | combat icon table | **synthesise** — DOS has no equivalent; `por/iconparts.py` composes a legal icon |
| `$49C0`-`$49C2` | 3 | party x, y, facing | **only if area numbering and map geometry correspond** — unproven |
| `$4BC2` | 1 | current `GEO` | **same question**, and it is the same answer or the party lands in the wrong place |
| `$49C6`-`$49CB` | 6 | clock, six digits | **probably** — needs the DOS clock format |
| `$4BC0`-`$4BD8` | 25 | loaded-files cache | **yes** — port-specific indices; zero it and let the loader refill |
| `$4900`-`$49BF`, `$4B80`-`$4BBF` | 256 | four effect arrays | **yes, by dropping them** — zero means no active effects, which is a legal state |
| `$4A00`-`$4A1F` | 32 | per-script scratch | **yes** — `DUNGEON $202A` zeroes it on every area change anyway |
| `$4A20`-`$4AF8` | 217 | **persistent quest flags** | **yes, once the block is located in a DOS save.** 179 bytes named, and 178 of them mean the same thing at the same address on DOS; see below |
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
image based at `$4900`, so the block is `SAVEDGAME0` offset `0x122`; where the
same 217 bytes sit in a DOS save is unknown and needs a DOS save. That is
obstacle 4, not this one.

*Tooling*, all in `work/amiga/` (gitignored): `adf.py` reads the Amiga
filesystem, `dax.py` the container — a big-endian index of `id:u16
offset:u32 compSize:u16 rawSize:u16` entries, and a ByteKiller-style backwards
bit-cruncher transcribed from the routine at `program` hunk27`+$7346`. All 843
blocks of all 23 `.dax` files decompress to their stated size with a zero
checksum. There is no `DAxF` magic and no `POOLDATA` volume; that was invented.

**2. Area numbering and coordinates.** `$4BC2` names the current map and
`$49C0`/`$49C1` the square. The C64 `GEO` files are a 16x16 grid per area. If
the DOS maps are numbered differently, or laid out differently, the party
arrives somewhere else — possibly inside a wall.

*What would resolve it:* compare a known position. Stand somewhere identifiable
in both ports and read the bytes. This needs a DOS save and half an hour.

**3. Item encoding and numbering.** The C64 item area is 16 bytes per item and
`por/items.py` decodes it. The DOS layout is not decoded, and even once it is,
**item ids must be shown to mean the same thing** in both ports. The spell list
is the same game and probably agrees; nobody has checked.

**4. We have no DOS save.** Everything above is unverifiable until there is
one, and it is now the *only* thing blocking obstacle 1's remainder — the
question "where in a DOS save do the 217 flag bytes live" cannot be answered
from disks. This is not a difficulty, only a dependency, and Donald has one on
a Windows laptop.

**5. The DOS layout we have is community documentation, not our own decode.**
`work/coab-research/formats/` is where the record table came from. It has been
right about everything checkable so far, which is encouraging and is not proof.

**6. The undocumented gaps.** About 54 bytes of `SAVEDGAME0` have no name.
They are almost all zero in the saves we hold, so writing zero is very probably
right — but "very probably" is doing work in that sentence.

**7. Does the game validate the save?** Nothing suggests a checksum, and
`wish` already writes saves the game loads happily. Listed because it has not
been *looked for*, and a checksum would be discovered fastest by writing one
save and watching it fail.

## What is not an obstacle

Worth stating, so effort does not go here: **byte order** (both little-endian),
**text encoding** (the record is ASCII on both, no PETSCII), **the D64
container** (`por/d64.py` writes valid images with correct block counts today),
and **party size** (six on both).

## What has to be found out first

1. **Verify the DOS record against a real DOS save.** We have none. This is the
   blocker, and it is small: one DOS save of a known party.
2. **The DOS save container.** The C64 keeps `SAVEDGAME0`/`SAVEDGAME1` as PRG
   files on a D64. What does the DOS version write, and where do character
   files live relative to it?
3. **Do the item and spell tables agree** between ports?
4. **Does DOS store anything the C64 does not?** If so, C64 to DOS has holes to
   fill as well.

## Order of work

1. Get a DOS save and check the layout above. Nothing else is worth doing
   first.
2. `por/dos_layout.py`, declarative, confidence per field.
3. Read a DOS character into the existing YAML export. That alone is useful —
   it makes `wish-cli` a DOS character viewer.
4. Write a C64 record from that YAML.
5. The reverse.
6. An editor menu item, once the CLI path is trustworthy.

## Verification

* A DOS character read and written back unchanged, byte for byte — the same
  losslessness bar the C64 side already holds.
* A C64 character converted to DOS and back preserves everything on the
  documented "survives" list, and nothing on the "lost" list surprises anyone.
* A converted character **loads in the target game** and its sheet reads the
  same. That is the only test that really counts, and it needs both emulators.
