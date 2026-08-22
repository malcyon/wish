# Porting a C64 party into Amiga Pools of Darkness — plan

**Status: nothing built. This is a costing and a first experiment.** It exists
because the four-game run ends on a title the C64 never got: Pool of Radiance,
Curse and Silver Blades on the C64, then **Pools of Darkness on the Amiga**,
which is where 1992 actually was. One direction only, C64 → Amiga.

Everything below marked *(read today)* was checked in this tree on 2026-08-21
from the disks and the archives on this machine. Everything else carries a
confidence label.

---

## The verdict

* **Reachable, and smaller than it sounds.** The deliverable is **not** a
  converted save disk full of game state. It is **one small file per
  character** in a `SAVE` drawer on an AmigaDOS floppy, because Pools of
  Darkness has an `Add Character` menu whose options are literally
  `Pools Secret Exit` *(read today, from the game binary)*. Following the
  game's own between-titles path means we never have to author its world
  state.
* **The hardest part is the `.pc` record itself.** Amiga Pools of Darkness
  writes each character as `NAME.pc`, 484–524 bytes, **variable length**, and
  the first 0x60 bytes contain **live Amiga heap addresses** — `0x00C69FE0`,
  `0x00098FA0` and friends *(read today)*. Until we know the game re-links
  those on load, we cannot say which bytes are don't-care. That is the
  difference between "write six files" and "write six files the game believes".
* **The first experiment is the refutation, and it costs one FS-UAE session.**
  Put a genuine `.pc` on a disk we built ourselves and see PoD list it; then
  put a C64 character export on the same disk under both `.pc` and `.sav` and
  see PoD refuse it. If it does not refuse it, this document is over and that
  is the best possible outcome.

---

## 1. What was read today, and it changes the shape of the problem

### 1.1 The Amiga saves are plain AmigaDOS files, not a container

Amiga Pools of Darkness, disk 3 (`POD 3`, OFS — bootblock `DOS\0`, FFS bit
clear), root drawer `Save/`:

| file | size | count | what |
|---|---|---|---|
| `NAME.pc` | 484–524, **variable** | 12 | one character each: BJORK, JORILD, TROND, KRISTIN, TRIPEL TURBO … |
| `SavGam[A-H].pty` | 10828, fixed | 8 | party/world saves, **all eight distinct**, all real |
| `Vault[A-H].DAT` + `VaultT.DAT` | 4016, fixed | 9 | the item vault |
| `spindisk` | 16538 | 1 | loader, not save data |
| `WRITE.ME` | 0 | 1 | write-test probe |

`work/amiga/adf.py` reads all of it today with no change. **The `.dax` /
`GLIB` container work is irrelevant to saves** — saves are ordinary files.

Amiga Pool of Radiance, disk 1, `save/` drawer, for comparison: `CHRDATAn.sav`
(288), `CHRDATAn.itm` (195 or 130), `CHRDATAn.spc` (40 or 10),
`savgamA.dat` (13141), `charlist.txt`, `save` (10 bytes, contents
`"A         "` — which save letter is current).

### 1.2 The game binary names its own file scheme

String literals in the Amiga `Pools of Darkness` executable *(read today)*:

| literal | file offset | what it means |
|---|---|---|
| `Pools Secret Exit` | `0x3809C` | the **Add Character** menu — import from a PoD save, or from a Secrets of the Silver Blades disk |
| `pc` | `0x255B2`, `0x25802`, `0x265A2` | the character-file extension, used at a load site, a save site and an `Update %s?` / `New file name:` site |
| `pty`, `sav`, `SavGam` | `0x2706C` | one literal pool: party extension, **the extension it reads from the Silver Blades disk**, and the party stem |
| `/Secret Drawer/SAVE`, `Place Secret save disk in DF0:`, `DF0:SAVE` | `0x254FA`, `0x2707F` | the Silver Blades import path — hard-disk drawer first, floppy second |
| `Vault%c.DAT` | `0x274AC` | the vault |
| `DF0:`, `SAVE`, `DISKA` | `0x3F868` | the save-disk path builder |
| `No characters to load.` | `0x255D1` | the picker's empty case |

So there are **two import routes**, and they want different files:

| route | reads | we have the format? |
|---|---|---|
| `Pools` | `SAVE/NAME.pc` on a PoD save disk | 12 real specimens, **undecoded** |
| `Secret` | `SAVE/*.sav` on a Secrets of the Silver Blades **Amiga** disk | **no Amiga SSB exists on this machine** — blocker 1 |

### 1.3 The Amiga port is a mechanical translation of the DOS build

This is the fact that makes the whole thing tractable, and today it got much
stronger. Every DOS file has an Amiga counterpart with the same name and a
size a few bytes larger:

| artefact | DOS | Amiga | delta |
|---|---|---|---|
| Pool of Radiance character record | `CHRDATAn.SAV` / `NAME.CHA`, **285** | `CHRDATAn.sav`, **288** | +3 |
| Pool of Radiance item record | `.ITM`, **63** per item (sizes 63…693, all multiples) | `.itm`, **65** per item (195 = 3 × 65, 130 = 2 × 65) | +2 |
| Pool of Radiance effect record | `.SPC`, **9** per entry (9, 18, 27, 45) | `.spc`, **10** per entry (10, 40) | +1 |
| Pool of Radiance world save | `SAVGAMA.DAT`, **13137** | `savgamA.dat`, **13141** | +4 |

And the first 0x33 bytes of the record are **the same layout on both**,
demonstrated on two specimens *(read today)*:

| offset | DOS `CHRDATA1.SAV` (BRUTUS) | Amiga `CHRDATA1.sav` (GARWAN) |
|---|---|---|
| `0x00` | `06 "BRUTUS"` — length byte + 15 | `"GARWAN\0"` — 16 NUL-padded, **no length byte** |
| `0x10`–`0x15` | `12 10 0E 12 12 0E` = 18/16/14/18/18/14 | `12 09 0B 10 12 10` = 18/9/11/16/18/16 |
| `0x16` | `64` = 100 exceptional strength | `64` = 100 |
| `0x2D` | `2A` → THAC0 = 60 − 42 = 18 | `2A` → 18 |
| `0x2E`/`0x2F` | `07` human / `02` | `07` human / `02` |
| `0x30` | `12 00` = age 18, **little-endian** | `00 12` = age 18, **big-endian** |
| `0x32` | `2A` = 42 hp max, 1 byte | `0E` = 14 hp max, 1 byte |
| `0x6B` | `03 01 0D 0E 0F 10 10 0C 03` | `01 01 0E 0F 10 11 11 0C 01` — same nine-byte saving-throw shape |

CONFIRMED: **the Amiga record is the DOS record, name field re-encoded and
multi-byte fields byte-swapped.** That corroborates the earlier finding in
`117-save-conversion.md` from an independent direction and makes **DOS the
Rosetta stone for every Amiga question in this document**.

Where the +3 comes from is UNKNOWN. See phase 4.

### 1.4 But the DOS/Amiga record is not one record across the family

The C64's great gift is that all six titles share one 580-byte record. **The
DOS line does not** *(read today, from the four titles' shipped default
saves)*:

| title | DOS character record | items | effects | world save |
|---|---|---|---|---|
| Pool of Radiance | `.SAV` **285** | `.ITM`, 63/item | `.SPC`, 9 | `SAVGAM?.DAT` 13137 |
| Curse of the Azure Bonds | `.SAV` **422** | none — inside the record | `.FX`, 9 | `SAVGAM?.DAT` 13149 |
| Secret of the Silver Blades | `.SAV` **439** | none — inside the record | `.SFX`, 9 | `SAVGAM?.DAT` 5469 |
| Pools of Darkness | `.SAV` **510** | `.THG`, 63/item | `.EFX`, 9 | `SAVGAM?.PTY` 1364, `VAULT?.DAT` 12 |

So "the Amiga character record" is a per-title object. The 288-byte Amiga
Pool of Radiance `.sav` we hold tells us the **scheme**; it does not give us
Pools of Darkness's **layout**. That has to be earned.

### 1.5 What twelve `.pc` specimens already say

Across all 12 Amiga PoD characters *(computed today)*, over their common
484-byte prefix: **326 bytes are identical in all twelve, 297 of those are
zero.** Only ~158 bytes of the prefix vary at all. That is the search surface.

| offset | observation | reading | confidence |
|---|---|---|---|
| `0x00`–`0x5F` | 24 big-endian longwords; 4–8 per file hold values in `0x098C58`–`0xC71842` | Amiga heap addresses — chip and fast RAM. The file is a struct dump with live pointers. | CONFIRMED (the values are addresses; what they point at is UNKNOWN) |
| `0x08` | `4`, `5` or `6` | a count; does **not** determine the file size on its own | PROBABLE |
| `0x0C`, `0x10`, `0x14`, `0x38` | pointer slots; which are populated tracks the file size loosely | list heads for the appended variable data | PROBABLE |
| `0x44` | `0x0016E361` (1 500 001) in 11 of 12, `0x0007A120` (500 000) in one | a large scalar — experience or coin | GUESS |
| `0x4C` | `0x00C8` = 200 in all twelve | a cap or a rate | GUESS |
| `0x50` | 28–46 | character level (PoD runs to the high 30s) | PROBABLE |
| `0x54` | 371, 601 or 960 | hit points | GUESS |
| `0x60` | 16 bytes, NUL-padded, `"BJORK\0…"` | **name**, same encoding as Amiga PoR at `0x00` | CONFIRMED |
| `0x70`–`0x7B` | twelve bytes, `18` in every specimen | **six abilities as base/current pairs** — matches DOS PoD `CHRDATA1.SAV` `0x10`–`0x1B` `12 12 0F 0F 0F 0F 12 12 12 12 0F 0F` | CONFIRMED |
| `0x7C`–`0x7D` | `00 00`, `32 32`, `00 00` | **exceptional strength**, base/current pair — matches DOS PoD `0x1C`–`0x1D` `43 43` | CONFIRMED |

Two things fall straight out:

* **The `.pc` record is the DOS PoD record shifted by `0x60`** — name at
  `0x00`→`0x60`, abilities `0x10`→`0x70`, exceptional strength `0x1C`→`0x7C`.
  PROBABLE, on three landmarks. It cannot hold all the way to the end: DOS is
  510 + a separate 315-byte `.THG`, the Amiga is 484–524 with no `.thg` at all.
* **Pools of Darkness stores abilities as base/current pairs where Pool of
  Radiance stored singles.** CONFIRMED on both platforms. The C64's
  `abilities_second` at `0x065` is probably the same idea in a different place.

Caveat on the specimens: **all twelve have every ability at 18.** They are a
maxed party, so they give layout and give almost no value variation. Real
variation has to be manufactured (phase 4).

---

## 2. The assumption to test first: can Amiga PoD read a C64 character?

Donald flagged this himself and asked for it to be checked rather than
assumed. It splits into two questions with different answers.

### 2.1 The media question — settled, and it is a no

A C64 save disk is a 1541 D64: 170 KB, GCR-encoded, 35 tracks, its own
directory format. An Amiga floppy is 880 KB MFM with an AmigaDOS filesystem,
and FS-UAE takes ADF images. **An Amiga cannot read a C64 disk at all** — not
"cannot understand the files", cannot read the flux. CONFIRMED by
construction; there is nothing to test. So "port the save disk" always means
"author a new Amiga disk", never "make the Amiga read the old one".

### 2.2 The format question — worth one session, because a yes ends the project

Could the *bytes* of a C64 export be accepted if we hand them over on an
Amiga-format disk? The C64 export is `\x01NAME`, 582 bytes: a 2-byte `$6B00`
load address plus the 580-byte record, little-endian, C64 field order
(`docs/30-savegame-layout.md`).

**The experiment** — one FS-UAE session, no code beyond a disk builder:

| # | disk contains | expected | what a surprise means |
|---|---|---|---|
| A | `SAVE/` with a genuine `.pc` copied verbatim off disk 3, on an ADF **we built** | PoD lists the character and adds it | if this fails, our ADF writer is wrong, not the format — fix that before believing B or C |
| B | `SAVE/GARWAN.pc` = the C64 export's 582 bytes verbatim | refused, or garbage on the sheet | **if it loads and reads correctly, stop — the whole plan collapses to a rename** |
| C | `SAVE/GARWAN.pc` = the same 580 bytes with the load address stripped | refused | as B |
| D | the same two files as `SAVE/GARWAN.sav`, offered through `Secret` | refused | as B, and it would also tell us the `Secret` reader is length-tolerant |

Prediction, PROBABLE and close to CONFIRMED: **all of B, C and D fail.** The
`.pc` reader is looking at a 484–524-byte struct whose name lives at `0x60`
and whose abilities are big-endian pairs; a C64 export has ASCII at offset
`0x02` and 18-decimal singles at `0x016`. There is no reading under which
those coincide. A is the control that makes B/C/D mean anything.

**A cheaper pre-test that needs no emulator**: disassemble the `.pc` reader.
The literal `pc\0` at `0x255B2` sits in the load path (`who`,
`No characters to load.`); `work/amiga/m68dis.py` already disassembles this
binary. If the reader checks a length or a signature before parsing, that
answers 2.2 statically for the cost of an afternoon. Do this first — it is
free and it may make the FS-UAE session unnecessary.

---

## 3. What actually has to be produced

**Six character files, not a save.** The reasoning, because the alternative
looks tempting:

| candidate output | size to justify | can a C64 Silver Blades save source it? |
|---|---|---|
| `SAVE/NAME.pc` × 6 | ~3 000 bytes total | **yes, in principle** — every byte is about a character |
| `SavGam?.pty` | 10 828 | **no.** It is PoD's world: quest flags, party position, journal, which of PoD's own areas you are in. A Silver Blades save knows none of that, because they are different games with different scripts. The one thing that *did* transfer between C64 and Amiga — the ECL bytecode and therefore the flag addresses — transfers only within a title. |
| `Vault?.DAT` | 4 016 | no, and not wanted: the vault is PoD's own storage |

And the player's own experience argues the same way. Between two real Gold Box
titles you do not carry a save; you carry a party, and the new game places it.
Following the game's path means PoD does its own import arithmetic — level
caps, starting position, the opening scene — instead of us guessing at it.

So the deliverable is: **one OFS ADF, a `SAVE` drawer, six `.pc` files.** The
player boots PoD normally, chooses `Add Character` → `Pools`, and picks them.

If the `Secret` route ever becomes reachable (blocker 1), prefer it: writing a
Silver Blades `.sav` and letting PoD convert it is strictly less for us to get
right than writing a PoD-legal `.pc` ourselves.

---

## 4. The three-way field map

C64 offsets from `por/layout.py`. DOS Pool of Radiance offsets from
`docs/117-save-conversion.md` and verified today against a real DOS record.
Amiga Pool of Radiance verified today. Amiga Pools of Darkness is the column
that is mostly empty, and filling it is the project.

| field | C64 (580 B, LE) | DOS PoR (285 B, LE) | Amiga PoR (288 B, **BE**) | Amiga PoD `.pc` (484–524 B, **BE**) |
|---|---|---|---|---|
| name | `0x000`, 20, NUL-pad — CONFIRMED | `0x000`, len + 15 — CONFIRMED | `0x000`, 16, NUL-pad — CONFIRMED | `0x060`, 16, NUL-pad — CONFIRMED |
| abilities ×6 | `0x014` singles — CONFIRMED | `0x010` singles — CONFIRMED | `0x010` singles — CONFIRMED | `0x070`, **base/current pairs** — CONFIRMED |
| exceptional strength | `0x01A` — CONFIRMED | `0x016` — CONFIRMED | `0x016` — CONFIRMED | `0x07C`, pair — CONFIRMED |
| second ability block | `0x065`, 7 — CONFIRMED | — | — | folded into the pairs — PROBABLE |
| 60 − THAC0 | `0x071` — PROBABLE | `0x02D` — CONFIRMED | `0x02D` — CONFIRMED | UNKNOWN |
| race | `0x072` — CONFIRMED | `0x02E` — CONFIRMED | `0x02E` — CONFIRMED | UNKNOWN, and the **code table differs per title** (`por/games.py`: human is 7 in PoR, 6 in Silver Blades) |
| class | `0x073` — CONFIRMED | `0x02F` — CONFIRMED | `0x02F` — CONFIRMED | UNKNOWN |
| age | `0x074` u16 LE — CONFIRMED | `0x030` u16 LE — CONFIRMED | `0x030` u16 **BE** — CONFIRMED | UNKNOWN |
| hp max | `0x076` **u16** — CONFIRMED | `0x032` **u8** — CONFIRMED | `0x032` **u8** — CONFIRMED | `0x054`? u16 (371/601/960) — GUESS |
| saving throws ×5 | `0x09A`–`0x09E` — CONFIRMED | ~`0x06B` block — PROBABLE | ~`0x06B` block — PROBABLE | UNKNOWN |
| level | `0x0A0` — CONFIRMED | UNKNOWN | UNKNOWN | `0x050`? (28–46) — PROBABLE |
| per-class levels ×8 | `0x0C9`–`0x0D0` — PROBABLE | UNKNOWN | UNKNOWN | UNKNOWN |
| class bits | `0x0EB` — CONFIRMED | UNKNOWN | UNKNOWN | UNKNOWN |
| experience | `0x0E8`, **3 bytes** — CONFIRMED | UNKNOWN | UNKNOWN | `0x044`? 1 500 001 — GUESS |
| money ×7 | `0x0BB`–`0x0C8`, u16 each — CONFIRMED | UNKNOWN | UNKNOWN | UNKNOWN |
| thief skills ×8 | `0x0A5`–`0x0AC` — CONFIRMED | UNKNOWN | UNKNOWN | UNKNOWN |
| spells known / memorised | `0x078`, 7 / `0x020`, 16 — CONFIRMED / PROBABLE | UNKNOWN | UNKNOWN | UNKNOWN |
| alignment, sex, infravision | `0x0D8`, `0x0D6`, `0x0D5` — CONFIRMED | UNKNOWN | UNKNOWN | UNKNOWN |
| portrait head/body | `0x0FE`/`0x0FF` — CONFIRMED | UNKNOWN | UNKNOWN | different art set — see §7 |
| derived combat (roster) | `0x10E` THAC0, `0x10F` AC, `0x119` hp current — PROBABLE | UNKNOWN | UNKNOWN | recompute, never copy — see §7 |
| inventory | `0x120`, 16 × 16 bytes — CONFIRMED | separate `.ITM`, 63 B/item | separate `.itm`, 65 B/item | **inside the `.pc`**, encoding UNKNOWN |
| combat icon | `0x220`, 36 — CONFIRMED | none | none | none — see §7 |
| live heap pointers | none | DOS far pointers embedded (`44 D7 46 12` at `0x1D7` of DOS PoD's record) | present | `0x000`–`0x05F`, 4–8 of them — CONFIRMED they are addresses |

**Endianness rule, CONFIRMED**: every multi-byte field is little-endian on
both the C64 and DOS, and big-endian on the Amiga. There is no exception known
and none expected — it is the 68000.

**Text**: ASCII everywhere. No PETSCII in the record on any platform. The only
name difference is the DOS length byte, which the Amiga drops for NUL padding.

---

## 5. The container and the filesystem

| question | answer | confidence |
|---|---|---|
| Are PoD's saves inside the `.dax` / `GLIB` container scheme? | **No.** They are ordinary AmigaDOS files in a `Save` drawer. | CONFIRMED — `work/amiga/adf.py` reads them |
| What filesystem? | **OFS.** All three PoD ADFs are `DOS\0`, FFS bit clear, root names `POD 1/2/3`. | CONFIRMED |
| Can we read one already? | Yes. `work/amiga/adf.py` walks the hash chains, follows extension blocks and extracts every file. | CONFIRMED |
| Can we **write** one? | Not yet. Nothing in this tree writes an ADF, and `amitools` is not installed in `.venv` and should not be — `wish` ships as a PyInstaller binary and does not take dependencies lightly. | — |
| What does writing require? | An OFS writer: bootblock, root block with its hash table and checksum, bitmap block, one dir header, and per file a header block plus data blocks each carrying a 24-byte header and its own checksum. Perhaps 300 lines, and `por/d64.py` is the precedent — this project already writes a container by hand. | PROBABLE |
| Does PoD want its own save disk? | It prompts (`is your save disk in drive`, `Place Secret save disk in DF0:`), and the rip we read carries `Save/` on disk 3 itself. Whether an original demands a separately formatted disk is UNKNOWN and phase 2 answers it. | — |

The one thing the container work does **not** need to touch: `dax.py`. Pools
of Darkness's game data is in `GLIB`-magic `.TLB`/`.GLB` archives, a different
format from Pool of Radiance's `.dax`, and none of it is on the save path.

---

## 6. Phases

Ordered so the cheapest thing that could kill the approach runs first.

| # | phase | produces | emulator? | cost | pass/fail |
|---|---|---|---|---|---|
| 0 | **Confirm §1 independently.** Re-extract both PoD and PoR ADFs, re-derive the file inventory and the twelve `.pc` constants. | a reproducible script under `work/` | no | an hour | the numbers in §1 come out again |
| 1 | **Read the `.pc` loader.** Disassemble around `0x255B2` / `0x25802` with `work/amiga/m68dis.py`; find the `Open`/`Read` pair and any length or signature check. | a written account of what the reader validates | no | a day | we can name the number of bytes it reads and say whether it checks anything |
| 2 | **The assumption test (§2.2), cases A–D.** | a yes/no on "can PoD eat a C64 export" | **yes** | a session | A loads and B/C/D are refused. **If B or C loads, stop and celebrate.** |
| 3 | **An OFS ADF writer.** Round-trip: read every file off disk 3, rebuild an image, compare file contents byte for byte; then boot it in FS-UAE and let PoD list the twelve characters. | `por/adf.py` (writer) with tests that read the player's own disks, never a committed image | yes, once | a week | PoD's `Add Character → Pools` shows all twelve names off our image |
| 4 | **Decode the `.pc` record.** Method, in the project's own order: (a) align against DOS PoD's 510-byte `.SAV` using the three confirmed landmarks; (b) the twelve specimens for structure; (c) **differential saves** — in FS-UAE, save, change exactly one thing, save again, diff. This is the method that carried the whole project and it needs no live memory, only the emulator to *make* the files. | `por/amiga_pod_layout.py`, declarative, confidence per field, asserting at import that it tiles all its bytes | yes, repeatedly | the bulk of the work | the table tiles every byte of a real `.pc` and every named field decodes to a legal AD&D value across all twelve |
| 5 | **Resolve the pointers.** Determine whether the `0x00`–`0x5F` addresses are re-linked on load. Two ways: read the loader (phase 1 may already answer it), or write a `.pc` with those longwords zeroed and see if PoD still loads it. | a ruling: don't-care, or must-be-plausible | yes | a session | a zeroed-pointer `.pc` loads and its sheet is unchanged |
| 6 | **The map and the writer.** C64 Silver Blades record → named fields → `.pc`, through the existing `por/yaml_io.py` middle. No new interchange format. | the converter, plus a **provenance report**: for every byte of the output, where it came from | no | a week | the report has no "template" category, per `117-save-conversion.md` |
| 7 | **End to end.** A C64 Silver Blades party through Wish onto an ADF, imported in PoD, sheets compared field by field against the source. | the thing Donald asked for | yes | a session | every field on the "survives" list matches and nothing on the "lost" list surprises anyone |

Two side experiments worth naming, both cheap and neither on the critical path:

* **Where does the +3 come from?** The DOS PoR record is 285 and the Amiga's
  288, identical to at least `0x73`. With 30-odd DOS specimens and 6 Amiga
  ones in hand, align the *pattern of non-zero runs* across both sets to
  localise the split point. No emulator, and the answer generalises to PoD.
* **`fr-archives` holds a DOS `SAVGAM?.DAT` for Pool of Radiance (13137
  bytes) and DOS default saves for all four titles.** That is the dependency
  `117-save-conversion.md` has been parked on since it was written. It is
  another agent's inventory to report, not this document's, but the two plans
  should be re-read together once it lands.

---

## 7. What cannot survive the trip

Stated out loud, so nobody is surprised and nobody tries.

| thing | why it cannot cross | what to do instead |
|---|---|---|
| **The combat icon** | C64 `0x220`–`0x243`: 18 screen codes into `CHARPIC00` plus 18 colours. It is a C64 character set. Neither DOS nor the Amiga has anything of the kind. | drop it; PoD draws its own |
| **Portraits** | C64 `0x0FE`/`0x0FF` name `HEADnn`/`BODYnn` files on the C64 disks. PoD's Amiga art is `CHEAD.TLB` / `CBODY.TLB`, a different set with different numbering. | re-choose, do not copy the index. A copied index is a wrong picture, silently. |
| **Derived combat values** | The C64 roster block (`0x10E` THAC0, `0x10F` AC, `0x119` current hp) is a **cache**, and its update rule is not "on load" — armour class refreshes only when equipment changes, so it can be stale even in a healthy save. | recompute for the target from base values, always |
| **Items** | The C64 stores 16 bytes per item, an id into that title's `ITEMNAMES`. DOS and Amiga store 63–65 bytes per item **carrying the name as text**. And a Silver Blades item id and a Pools of Darkness item id are two different games' tables. | re-encode from named fields, and **check the tables agree before assuming any id means the same thing** |
| **Memorised spells** | C64 spell ids run 1–56. Pools of Darkness has cleric spells to level 7 and mage spells to level 9, so its id space is larger and the mapping is certainly not identity. | map by name, or drop and let the player re-memorise |
| **Experience** | The C64 field is **3 bytes** — 16 777 215 maximum. Pools of Darkness characters exceed that. | the target field is wider; carry the value up, and expect a C64-sourced total to look low rather than wrong |
| **Race and class codes** | `por/games.py` already documents that the race table changes per title on the C64 alone (human is 7 in Pool of Radiance, 6 in Silver Blades). PoD's Amiga table has not been read. | read PoD's own table before writing a race byte |
| **Everything Silver Blades knew and Pools of Darkness does not** | quest flags, position, journal entries | not carried, and not wanted — see §3 |

---

## 8. Blockers, honestly

1. **There is no Amiga Secrets of the Silver Blades on this machine.** Only
   Amiga Pool of Radiance and Amiga Pools of Darkness are here. That closes the
   `Secret` import route — the one the game was actually designed around, and
   the one where PoD would do the conversion arithmetic for us. We are left
   with the `Pools` route, which makes **us** responsible for producing a
   PoD-legal character. This is the largest single cost in the plan and it is a
   missing-disk problem, not a technical one.
2. **The C64 source end is weaker than the Amiga target end.**
   `docs/121-silver-blades.md`: no Silver Blades save disk written by the game
   exists here, no exported character file exists on any of the six sides, and
   the export load address and marker byte are still UNKNOWN. Wish reads the
   shipped `SAVEDBASH` demo party and has never round-tripped a real Silver
   Blades save. The chain starts at a link that has not been tested.
3. **The `.pc` record contains live heap pointers and we do not know what the
   game does with them.** Four to eight longwords in `0x00`–`0x5F` are Amiga
   addresses. If the loader re-links them, they are don't-care and we write
   zeros. If it does not, we have to synthesise addresses a 1992 allocator
   would have produced, which is exactly the "copied from a template and
   probably fine" category `117-save-conversion.md` says should not exist by
   the end. Phase 5 exists to settle it and it must settle it before phase 6.
4. **The `.pc` length rule is not derived.** Sizes 484 / 504 / 514 / 524
   against a count at `0x08` of 4 / 5 / 5 / 6 — the count does not determine
   the size, so at least two variables are in play. A writer cannot emit a file
   whose length it cannot predict.
5. **All twelve specimens are a maxed party** — every ability 18, levels 28–46.
   They are excellent for finding *where* fields are and nearly useless for
   finding *what encodes what*, because almost nothing varies. Real variation
   has to be manufactured in FS-UAE, which is phase 4 and is the expensive part.
6. **The Amiga releases are rips of unknown provenance.** The Pool of Radiance
   set is `[cr SKR]` and its disk 1 carries a hard-disk installer and a
   previous owner's saved party — definitely modified. The Pools of Darkness
   set we read carries no `[cr]` tag, boots through an ordinary AmigaDOS
   `startup-sequence` and ships `Install_DH0`/`Install_DH1` scripts, so it is
   plausibly an original; three other rips of it are on this machine including
   a `[cr SKR]` set, and they should be cross-checked. **What a crack changes**:
   the loader, the copy protection, and where the `Save` drawer lives. **What
   it does not change**: the record formats, the file names, and the code that
   reads them. The one real risk is that a crack also patched the disk-prompt
   logic, which would make "PoD accepted our save disk" weaker evidence than it
   looks. Run phase 2 against the untagged rip and repeat it on a second rip
   before believing it.
7. **FS-UAE is not VICE.** There is no binary monitor with the shape
   `automap/vice.py` expects, so none of the live-memory technique in
   `skills/goldbox/SKILL.md` transfers. The mitigation is that **phase 4 does
   not need live memory** — differential *saves* are files, and the emulator is
   only needed to produce them. Anything that does want live memory (a PoD
   automapper) is a separate project and is out of scope here. Kickstart ROMs
   are present at `/home/donald/FS-UAE/Kickstarts` (1.3 and 3.1), so booting is
   not itself a blocker.
8. **Nothing here has been run against a real emulator yet.** Every claim in
   this document is a static read of files. The first time PoD is actually
   asked to load something we wrote is phase 2, and that is where the
   assumptions get their first real test.

---

## 9. What is explicitly not in this plan

* **Automapping Pools of Darkness.** Donald's story has Wish mapping all four
  games, but PoD on the Amiga needs a live-memory path FS-UAE does not offer in
  the shape this project uses, plus a `GLIB` container reader for `GEO.GLB`
  and `ECL.GLB`. It is a separate document. Note one encouraging fact for
  whoever writes it: PoD's `GEO.GLB` is 33 050 bytes for the whole game, so the
  map family is small.
* **Amiga → C64.** One direction only, as with `117-save-conversion.md`. No
  C64 Pools of Darkness exists, so there is nowhere to go back to.
* **Writing a `.pty` or a `Vault?.DAT`.** §3.
