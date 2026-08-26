# Porting a C64 party into Amiga Pools of Darkness — plan

**Status: it works end to end.** A character out of the player's own C64
*Pool of Radiance* save disk now converts to a `.pc`, and Amiga *Pools of
Darkness* loaded it, put it in the party and drew a sheet that matches the C64
one field for field -- see §2.5. `por/amiga.py` is the whole converter and
`tools/toamiga.py` is how it is invoked.

**Phase 4 is done for every field the character sheet shows, and the
writer works.** Amiga Pools of Darkness **accepts a C64 Pool of Radiance
export** as a `SAVE/NAME.pc` and puts it in the party — no length check, no
signature check, and the `0x00`-`0x5F` heap-address block is don't-care. So the
record was decoded by *writing* one and reading the sheet, and it is now
written the other way round: `por.amiga.PodWriter` emits a **484-byte record
built from named fields alone**, and PoD drew every one of them back —
`WRITTEN`, `FEMALE 33 YEARS`, `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`,
`HIT POINTS 55/77`, `EXPERIENCE 10000`, `STR 18 INT 17 WIS 16 DEX 15 CON 14
CHA 13`, `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`, `STATUS: OKAY`.
§2.3 and §2.4 have the probes; `por/amiga.py` and `tests/test_amiga.py` carry
the result. The item region at `0x0B6` turned out **not** to be a wall: zero in
it is accepted, and its error message belongs to the graphics library, not the
inventory. Everything else below is still a costing. It exists because the
four-game run ends on a title the C64 never got: Pool of Radiance, Curse and
Silver Blades on the C64, then **Pools of Darkness on the Amiga**, which is
where 1992 actually was. One direction only, C64 → Amiga.

Everything marked *(read today)* was checked in this tree on 2026-08-21 from
the disks and the archives on this machine. Everything else carries a
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
* **The `.pc` record is no longer the hard part.** Amiga Pools of Darkness
  writes each character as `NAME.pc`, 484–524 bytes, **variable length**, and
  the first 0x60 bytes contain **live Amiga heap addresses** — `0x00C69FE0`,
  `0x00098FA0` and friends. They are don't-care: a record with zeros there
  loads. The variable part is appended item data, and a record without it is
  484 bytes, which is what the writer emits.
* **The first experiment ran, and PoD did not refuse it.** A genuine `.pc` on
  a disk we edited lists and adds; a C64 export's 582 bytes under the same name
  *also* lists and adds. That killed the two blockers that made the writer
  expensive.
* **And the sheet it drew is the instrument.** Writing a controlled record and
  reading the sheet located every field the sheet shows, in eleven runs across
  two afternoons. The same offsets then decode all twelve genuine `.pc` files
  to sane values, which is the second line of evidence. See §2.3 and §2.4.
* **The record holds base values and PoD derives the rest.** THAC0,
  encumbrance, the displayed armour class and the displayed damage bonus are
  all recomputed on load, and what the file says about them is ignored. A
  writer must not try to set them. See §2.4.

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
| `Secret` | `SAVE/*.sav` on a Secrets of the Silver Blades **Amiga** disk | **the disks arrived 2026-08-25** and `SecretOfTheSilverBlades_A.adf` carries `SAVE/savgamA.sav` — see §1.6 and §1.7. Blocker 1 is gone as a *media* problem; whether PoD accepts a `.sav` we wrote is still untested |

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

Where the +3 comes from is **one pad byte at `0x07F`, ahead of the effect
pointer, and a second insertion inside DOS `0x083`-`0x087`** — §1.6, measured
on fourteen specimens. The second is located to a window, not to a byte.

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

### 1.6 Curse and Silver Blades, read off the shipped disks

Four Amiga disks arrived on 2026-08-25 (`work/amiga/goldbox/`, gitignored):
two Curse of the Azure Bonds game disks, a Curse **save disk**, and two Secret
of the Silver Blades disks. `work/amiga/goldbox/adfread.py` walks them —
importable, unlike `work/amiga/adf.py`, and it finds the root block by scanning
because the save disk is 1804 blocks rather than 1760.

**The save disk's fourteen 288-byte `.cha` files are Pool of Radiance, not
Curse.** CONFIRMED 14 of 14: single ability bytes at `0x010`-`0x015` where a
Curse record holds current/max pairs, and levels at Pool of Radiance's caps
(fighter 8, thief 9, mage 6) with experience past the AD&D threshold, which is
what a capped character accrues. Somebody staged a Pool of Radiance party for
import. They are the specimens #27 wanted; the field map is on that issue.

**The Amiga Curse record is `SAVE/*.guy` on the game disk** — eleven
pre-generated characters, 428 to 468 bytes. CONFIRMED 11 of 11: a **428-byte
record followed by N ten-byte effect records**, the four observed sizes being
0, 1, 3 and 4 effects, with every effect id landing on the right race.

| artefact | DOS | Amiga | delta |
|---|---|---|---|
| Curse character record | `.SAV`, **422** | `.guy` / in-save block, **428** | +6, the last byte a pad |
| Curse item record | inside the record | **66**, with its display text inline | — |
| Curse effect record | `.FX`, **9** | appended, **10** | +1 |
| Silver Blades character record | `.SAV`, **439** | in-save block, **340** | **−99** |
| Silver Blades effect record | `.SFX`, **9** | appended, **10** | +1 |

**The Amiga packs the spellbook as bits.** The whole 99-byte Silver Blades
difference is one region: DOS `0x071`-`0x0e2` is 114 one-byte spell flags, and
the Amiga has 15 bytes at `0x071`-`0x07f`, which is 120 bits. CONFIRMED 6 of 6
— read **least-significant bit first within each byte**, the Amiga's 15 bytes
reproduce the DOS non-zero indices exactly (29 spells, 29 spells, 4 spells,
and empty for the three non-casters); most-significant-first reproduces none of
them. So §1.3's "the DOS record, name re-encoded and multi-byte fields
byte-swapped" is **not the whole rule**: one field changes representation, and
it is the C64's own trick.

**The `.spc` / effect record, ten bytes**, on 62 records plus every appended
tail:

| bytes | what | grade |
|---|---|---|
| 0 | effect id, the same namespace as DOS | CONFIRMED — 90/97/26/47 on dwarves, 107 elf, 124 half-elf |
| 1 | **the extra byte**, a pad; zero everywhere in Pool of Radiance and Curse, uninitialised garbage in the first record of each Silver Blades character | PROBABLE |
| 2-3 | duration, u16 big-endian | PROBABLE — 10, 6, 4 and 3 read as durations; little-endian gives 2560 and 1536 |
| 4 | value; `0xFF` permanent, 92 for one character's exceptional strength | CONFIRMED for `0xFF`, 30+ records |
| 5 | zero except `0x01` on four records | UNKNOWN |
| 6-9 | next-node pointer, u32 big-endian, NULL-terminated | CONFIRMED — steps by `0x10` in Pool of Radiance, `0x0A` in Curse |

It exists to align the u16 duration and the u32 pointer on even addresses,
which a nine-byte record cannot do.

### 1.7 The Amiga saved game is the DOS file with its last region replaced

`SAVE/savgamA.dat` (Curse, 15221, byte 0 `02`) and `SAVE/savgamA.sav` (Silver
Blades, 7233, byte 0 `01`), against [`141-dos-savegame.md`](141-dos-savegame.md).

The first five regions occupy the same span they do in DOS. `docs/141` puts the
DOS character table at 12822 for Curse and 5142 for Silver Blades; the Amiga
party-size byte is at 12824 and 5142, with the first record one byte later.
**CONFIRMED**: that byte is the party size — Curse reads 4 and holds four
records, Silver Blades reads 6 and holds six.

**Where DOS names six `CHRDAT<letter><n>` files, the Amiga embeds the records.**
CONFIRMED, 4 of 4 Curse blocks and 6 of 6 Silver Blades blocks, parsed to the
byte with no slack: a Curse block is 428 + items×66 + effects×10, and a Silver
Blades block is 340 + effects×10 with no items. The Silver Blades effect counts
match the DOS default save's `.SFX` files character for character, and its six
characters are the same six as DOS slot A in the same state — so the two are a
direct diff, which is how §1.6's spellbook finding was measured.

Untested, and each is cheap: the VM variable region (the Curse save carries the
contiguous ASCII `WEAPONERS OF CORMYR` at `0x0f9a`, inside it, where `docs/141`
records the DOS encounter buffer as one character per word — so either the
Amiga stores it as bytes or the array is not two bytes per address); the ECL
text buffer, whose high-entropy span runs about `0x1472`-`0x31bf` on Curse; the
square, facing and clock; and the 66-byte item record.

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

### 2.2 The format question — RUN, and the answer is yes-but

Could the *bytes* of a C64 export be accepted if we hand them over on an
Amiga-format disk? The C64 export is `\x01NAME`, 582 bytes: a 2-byte `$6B00`
load address plus the 580-byte record, little-endian, C64 field order
(`docs/30-savegame-layout.md`).

**The experiment, as run** (P51 in `docs/50-experiments.md`, one FS-UAE
session, Kickstart 1.3, the untagged three-disk rip). `work/amiga/adfedit.py`
replaces a file's contents in place on a real disk 3 — no ADF writer needed,
because a 484-524-byte `.pc` already owns two 488-byte OFS data blocks and 582
fits. Two of the twelve were overwritten, ten left genuine.

| # | disk contains | expected | **observed** |
|---|---|---|---|
| A | ten genuine `.pc` files, one of them rewritten byte-identically by our own writer | lists and adds | **lists and adds.** TROND joined at AC −7, HP 138. Our write path is sound. |
| B | `KILLKILL.pc` = `brutus.chr`'s 582 bytes verbatim, `$6B00` load address included | refused | **listed with a blank name and added to the party** — AC 60, HP 0, a full sheet |
| C | `INRANGE.pc` = the same 580 bytes, load address stripped | refused | listed with a blank name; not the one that reached the party this session |
| D | the same offered through `Secret` | refused | **not run** — the route wants `*.sav` and `adfedit.py` cannot create a new directory entry, only rewrite an existing one |

The sheet PoD drew for B: `MALE`, `0 YEARS`, `LAWFUL GOOD`, `ELF`, `CLERIC`,
`LEVEL 15/16/17/17/12/1`, `HIT POINTS 0/0`, `EXPERIENCE 0`, `STR 0 INT 40
WIS 2 DEX 0 CON 0 CHA 0`, `ARMOR CLASS 60`, `THAC0 4`, `DAMAGE 0D0`.

Three things follow, and they are the reason this section is now the most
useful one in the document.

* **There is no length check and no signature check.** 582 bytes where the
  genuine files are 484-524, and C64 record bytes where the genuine files keep
  Amiga heap addresses, and it loaded. Blocker 3 is answered: the
  `0x00`-`0x5F` longwords are **don't-care on load**. Blocker 4 is answered for
  reading, though a writer still wants to know what length PoD itself emits.
* **The one check it does make is implicit.** A second probe — the same
  `TROND.pc` with every byte from `0x70` up set to `i & 0xFF` — listed its name
  correctly and then failed `ADD` with `DISK READ ERROR`; restoring the genuine
  bytes through the same writer made it load again. So something inside the
  record drives a read of appended data, and garbage there asks for more bytes
  than the file has. PROBABLE, one trial.
* **Phase 4 just got cheap.** We can write a `.pc`, add it, and read the sheet.
  `INT 40 WIS 2` are `brutus.chr`'s file offsets `0x73` and `0x75`, which both
  identifies B rather than C as the one that loaded and confirms
  §1.5's `0x70` base/current pairs with the **second** byte displayed. Two more
  offsets came out of the same single sheet: **name, 15 chars at `0x60`,
  NUL-terminated at `0x6F`** (re-confirmed by a probe that drew
  `` `ABCDEFGHIJKLMN ``), and **per-class levels, six bytes from `0x9D`**.

What it is **not** is a usable import. `HP 0/0` is a corpse and every field is
read from the wrong place. §6 phase 6 still has to write a PoD-legal record;
what changed is that finding out what "legal" means no longer needs
differential saves.

Practical notes for the next session, all learned the hard way: FS-UAE's arrow
keys never reach the Amiga, so the picker's cursor cannot be moved — **put the
payload in the first row's file**. The `*` in that list marks a name matching a
party member, not the cursor. The `INSERT INTO DF0` submenu opens with the
image currently in the drive highlighted; `work/amiga/pod/swap.sh` assumes that.
`PLEASE INSERT DISK 3.` is answered with `o` then Return.

---

### 2.3 The ramp probe, and thirteen numbers off the screen

**The method.** Take the 582-byte C64 export PoD is known to accept, overwrite
one window of it with a ramp — `byte[i] = i` — write a real name at `0x060`, and
put it on a copy of disk 3 in the file the picker draws **first**. Add it, view
the character, and read the numbers: a byte field prints its own offset, a
big-endian word prints two of them side by side. One run identifies every field
in the window at once, and the name on the sheet is the check that the payload
on the disk is the one that loaded.

`work/amiga/pod/probe.py` builds the payload and installs it,
`work/amiga/pod/cycle.sh` drives one probe end to end, and the screenshots are
`work/amiga/pod/R*.png`.

| probe | window | what the sheet drew | reading |
|---|---|---|---|
| baseline | none | `STR 0 INT 40 WIS 2`, `LEVEL 15/16/17/17/12/1`, `AC 60`, `HP 0/0` | reproduces the earlier run exactly; `40` and `2` are the export's own `0x073` and `0x075` |
| R1 | `0x07E`–`0x0C7` | `ERROR: INVALID ITEM (-1/29)`, and the character joined anyway | something in the window drives an item parse |
| R2 | `0x07E`–`0x0A2` | `HIT POINTS 0/129`, `MOVEMENT 136`, `LEVEL 157/158/159/160/161/16…` — the sixth ran into the experience column | **hit points maximum `0x081`**, **movement `0x088`**, **class levels from `0x09D`** |
| R3 | `0x0A3`–`0x0B5` | `ARMOR CLASS -119`, `DAMAGE 173D175-79` | **armour class `0x0B3`**, stored `60 - AC`; **damage count/sides/bonus at `0x0AD`, `0x0AF`, `0x0B1`** |
| R4 | `0x0B6`–`0x0C7` | — | the item region; the run ended in the game asking for disk 2 |
| R5 | `0x030`–`0x05F` | `21075 YEARS`, `EXPERIENCE 1145390663`, `PLATINUM 19533`, `GEMS 20047`, `JEWELRY 20561`, and unrelated game text where sex, alignment, race and class belong | **age `0x052` u16**, **experience `0x044` u32**, **platinum `0x04C`**, **gems `0x04E`**, **jewelry `0x050`**, all big-endian |
| R6 | `0x054`–`0x05F` | age back to `0`, money empty, the same four wrong strings except race | sex, alignment, class and status are in `0x054`–`0x05F`. The reading that **race is below `0x054`** was wrong: race is `0x058` (§2.4), and R6 ramped it too |
| R7 | `0x044`–`0x04B` | — | meant to separate experience from the lighter coins; the run quit to `INSERT DISK 2` before the sheet, so it is unread |

Two things the whole set agrees on and neither probe was aimed at:

* **Byte fields sit on odd offsets two apart** — abilities at `0x071`, `0x073`
  …, damage at `0x0AD`, `0x0AF`, `0x0B1`, armour class at `0x0B3`. They are the
  second half of **base/current pairs**, and the sheet draws the current one.
  §1.5 saw that for the abilities; it is the record's general shape.
* **THAC0 never moved.** Every window from `0x030` to `0x0B5` left it reading
  `4`. §2.4 explains it: THAC0 is derived and the record's copy is ignored.

**R1's seven level values were the clue nobody read.** With `0x07E`–`0x0C7`
ramped the sheet printed **seven** numbers on the level line where R2 printed
six. The array is seven wide, not six — the seventh slot is the thief's — and
§2.4 confirmed it by writing `1/2/3/4/5/6/7` and reading it straight back.

**The second line of evidence, and it is the stronger one.** These offsets were
found by watching PoD *misread* a C64 record. Turned on the twelve genuine
`.pc` files on disk 3 they decode as follows: every ability `18` (the maxed
party §1.5 warned about), hit points 32 to 141, movement `12` for all twelve,
one non-zero class level each — three for `TRIPEL TURBO`, who is triple-classed
— armour class `10` and damage `1d2` for all twelve, which is what unequipped
means, experience `1500001` for eleven and `500000` for one, and ages 28 to 46.
**`TROND.pc` reads 138 hit points, and `HP 138` is what the roster drew when
TROND was added to the party** in the earlier session. `tests/test_amiga.py`
asserts both halves — the ramp offsets, and the real files.

`Save/T.pc` is the odd one: a name the picker draws as `?T`, and its only class
level is in the thief slot. Somebody's abandoned scratch character, and the
specimen that fixed the seventh level slot.

---

### 2.4 The enums, the derived block, and a writer that works

A ramp cannot find an enum. A wrong race index does not print a number that
names its offset; it prints an unrelated string, and `R6` spent a run learning
only that four of them lie between `0x054` and `0x05F`. What found them was
**prediction plus one probe**.

**The tables came out of the game binary.** Packed NUL-terminated runs at file
offsets `0xFB8E` onwards, referenced by the character-generation menu's own
`pea` instructions:

| table | order |
|---|---|
| race | `ELF` `HALF-ELF` `DWARF` `GNOME` `HALFLING` `HUMAN` |
| sex | `MALE` `FEMALE` |
| class | `CLERIC` `DRUID` `FIGHTER` `PALADIN` `RANGER` `MAGIC-USER` `THIEF` `MONK` then the nine multi-class combinations |
| alignment | `LAWFUL` `NEUTRAL` `CHAOTIC` × `GOOD` `NEUTRAL` `EVIL`, one byte, `law × 3 + morality` |

**The offsets came out of the twelve specimens, by AD&D.** The byte at `0x059`
equals the index of the one non-zero class-level slot in every single-classed
specimen; `?T` has `6`, which is `THIEF`, and `TRIPEL TURBO` has `15`, which is
`FIGHTER/M-U/THIEF`. The byte at `0x05D` is `0` for both paladins, and a
paladin must be lawful good; both rangers are `0` or `3`, and a ranger must be
good. The byte at `0x058` is `5` for eleven and `1` for `TRIPEL TURBO`, and a
triple-classed fighter/magic-user/thief must be a half-elf while a paladin must
be human. The byte at `0x05C` is `1` for `KRISTIN` and `JORILD` and `0` for the
rest.

**Then one probe put the prediction on screen**, and a second checked the other
end of each table:

| probe | wrote | the sheet drew |
|---|---|---|
| P1 | `0x058=1 0x059=6 0x05C=1 0x05D=8`, age 33, xp 10000, plat 200, hp max 77, levels `1..7`, AC 10, damage 1d6+2 | `FEMALE 33 YEARS`, `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 1/2/3/4/5/6/7`, `HIT POINTS 0/77`, `EXPERIENCE 10000`, `PLATINUM 200`, `ARMOR CLASS 10`, `DAMAGE 1D6+2`, `STATUS: OKAY` |
| P2 | the same with `0x058=2 0x059=2 0x05C=0 0x05D=0`, plus `0x190=55`, `0x088=12`, gems 11, jewelry 22, and a deliberately wrong `0x056=1234` and `0x192=99` | `MALE`, `LAWFUL GOOD`, `DWARF`, `FIGHTER`, `HIT POINTS 55/77`, `GEMS 11`, `JEWELRY 22`, `MOVEMENT 12`, `ENCUMBRANCE 233` |
| P3 | a 484-byte record built by `por.amiga.PodWriter` from named fields and nothing else | every field back: `WRITTEN`, `FEMALE 33 YEARS`, `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`, `HIT POINTS 55/77`, `EXPERIENCE 10000`, `STR 18 INT 17 WIS 16 DEX 15 CON 14 CHA 13`, `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`, `STATUS: OKAY` |

So: **sex `0x05C`, race `0x058`, class `0x059`, alignment `0x05D`**, all
CONFIRMED, and **current hit points a big-endian word at `0x190`**, and the
class-level array **seven** wide at `0x09D`, indexed by the single-class code.
`STATUS: OKAY` came out of every payload, so status is zero-is-alive and its
byte is one of the four still-zero bytes in `0x054`–`0x05F`; the writer wants
zero there anyway.

**The derived block, and why a writer must leave it alone.** P2 set encumbrance
to 1234 and the sheet drew `233`, which is its 200 platinum plus 11 gems plus
22 jewelry. It set the second movement byte to 99 and the sheet drew `12`, the
base. P3 wrote base armour class 10 with a dexterity of 15 and the sheet drew
`ARMOR CLASS 9`; it wrote damage `1d6+2` with a strength of 18 and the sheet
drew `1D6+4`. THAC0 followed the class levels and never the record. The
character-sheet routine reads all of these from `0x186`–`0x192`, and the loader
fills that block itself:

| sheet field | drawn from | filled from |
|---|---|---|
| THAC0 | `0x186`, as `60 − value` | the best of the class levels |
| armour class | `0x187`, as `60 − value` | base `0x0B3` adjusted for dexterity |
| damage | `0x18B`/`0x18D`/`0x18F` | base `0x0AD`/`0x0AF`/`0x0B1` plus the strength bonus |
| encumbrance | `0x056`, u16 | the coins |
| movement | `0x192` | base `0x088` |
| hit points | `0x190`/`0x191` u16 current, `0x081` max | the record, unchanged |

**`ERROR: INVALID ITEM (-1/29)` is not about items.** `Invalid item (%d/%d)` is
a string in the game binary's `LBI` library-reader code, beside
`LBIBase: Invalid Library File` and the `GLIB` magic it checks. The two numbers
are a library item index and the library's item count, and **`Disk3_CHEAD.TLB`,
the portrait heads, holds exactly 29 items**. So R1's ramp made PoD ask
`CHEAD.TLB` for item −1: `0x0B6`–`0x0C7` carries a portrait selector, not
carried inventory. **Zero there is accepted** — every payload that loaded had
zeros from `0x0B9` up, including the 484-byte written one.

**What the loop costs and how it breaks.** Each probe is about three minutes:
rewrite the ADF, eject and re-insert DF0 so the Amiga re-reads it, `ADD
CHARACTER` → `POOLS` → `ADD`, `VIEW CHARACTER`, screenshot, `REMOVE CHARACTER`.
Notes for whoever runs the next one:

* **PoD is driven by first letters and Return**, not by arrows — `a`, `p`, `v`,
  `r`, `y`, `e`. FS-UAE's arrow keys reach its own menu and not the Amiga, so
  the picker's cursor cannot be moved: **the payload goes in the file the picker
  lists first**, which on this disk is `Save/TROND.pc`. The `*` in that list is
  the cursor, and the red name in the party roster is the cursor there.
* **Never press Up at the top of an FS-UAE menu list.** The cursor leaves the
  list and lands on the window's `X`, and Return there quits the emulator. That
  is what killed one session; it looked like a crash and was not.
  `work/amiga/pod/df0.sh` navigates by Down-then-Up from a clamped bottom and
  tracks which disk is in DF0 in `.df0state` so it can move by an exact delta.
* The DF0 submenu opens on **whatever is in the drive**, and the main menu's
  highlight is wherever it was left, so no fixed key sequence reaches it —
  screenshot after `F12` if anything looks wrong.
* **Start every probe with an empty party.** `VIEW CHARACTER` shows whichever
  character the cursor is on, and a failed `ADD` leaves the cursor on the
  previous one.
* **`e` on the party menu is `EXIT FROM GAME`**, not the picker's `EXIT`.
* **PoD writes the character back to the save disk when it is added** — a
  `THIEFTEST.pc` appeared in the picker one probe after `THIEFTEST` joined. It
  is written to FS-UAE's in-memory copy only: **FS-UAE never writes the ADF back
  to the host**, checked by reading the host file afterwards. So PoD's own
  emitted `.pc` cannot be harvested this way, and rewriting the host file
  between probes is safe.
* FS-UAE 3.1.66 died once with `*** buffer overflow detected ***`. Restarting it
  into the same Xephyr and rebooting the game is the recovery.

---

**What is still missing**, and none of it blocks the writer: the five saving
throws at `0x083`, the eight thief skills at `0x08B`, the class bitmask at
`0x0B7` and the portrait body index at `0x0B8` are all PROBABLE from the twelve
specimens and none appears on the character sheet, so no probe can promote
them; the appended item data that takes a record from 484 to 524 bytes is
undecoded; and spells are untouched.

### 2.5 End to end: a C64 character in the Amiga party

**The thing Donald asked for, run.** `LADY KATHERINE` off `work/PORSAVE11.D64`
-- a half-elf magic-user/thief the player rolled on the C64 -- converted with
`tools/toamiga.py`, installed as `Save/TROND.pc` on a copy of disk 3, added
through `Add Character -> Pools` and viewed. The party roster drew
`LADY KATHERINE  AC 8  HP 4`; the sheet drew everything else.

| field | the C64 save says | the sheet drew |
|---|---|---|
| name | `LADY KATHERINE` | `LADY KATHERINE` |
| sex, age | female, 41 | `FEMALE 41 YEARS` |
| alignment | neutral evil | `NEUTRAL EVIL` |
| race | half-elf | `HALF-ELF` |
| classes | magic-user + thief | `MAGIC-USER/THIEF` |
| levels | magic-user 1, thief 1 | `LEVEL 1/1` |
| hit points | 4 of 5 | `HIT POINTS 4/5` |
| experience | 40 | `EXPERIENCE: 40` |
| abilities | 16 18 14 16 14 13 | `STR 16 INT 18 WIS 14 DEX 16 CON 14 CHA 13` |
| platinum | 15 | `PLATINUM 15` |
| movement | 12 | `MOVEMENT 12` |
| alive | yes | `STATUS: OKAY` |

And the four derived fields came out **right rather than copied**, which is
the stronger half of the result:

* `ARMOR CLASS 8` -- the writer wrote the unarmoured base 10 and PoD applied
  the −2 for her dexterity of 16 itself. The C64 save said 6, because on the
  C64 she was wearing armour that does not cross.
* `DAMAGE 1D2+1` -- the writer wrote unarmed `1d2` and PoD added her strength
  bonus.
* `THAC0 20` -- a first-level character's, computed from the class levels.
* `ENCUMBRANCE 15` -- her 15 platinum. `MOVEMENT 12`, not the C64's cached 6.

The losses were the expected ones and every one was named in the report before
the run: 104 silver and gold pieces (only platinum, gems and jewelry have a
located home), her items, her spellbook, her portrait and her combat icon.

Screenshots are `work/amiga/pod/v_*.png`; `work/amiga/pod/install_pc.py` puts a
built `.pc` on a fresh copy of disk 3. Two practical notes on top of §2.4's:
**the picker takes several seconds to populate** and looks empty until it
does, and the first row is the file `Save/TROND.pc` whatever the record inside
it is called.

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

**The `.pc` files exist; the ADF does not.** `tools/toamiga.py` writes a whole
party into a directory, and §2.5 got one of them into the game by *replacing*
an existing file's contents on a copy of disk 3 — which is what
`work/amiga/adfedit.py` can do and all it can do. Authoring a disk, or adding
a directory entry to one, still wants phase 3's OFS writer. That is the last
piece between here and something a player can be handed.

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
| 60 − THAC0 | `0x071` — PROBABLE | `0x02D` — CONFIRMED | `0x02D` — CONFIRMED | `0x186`, and **derived on load** from the class levels — the record's copy is ignored (§2.4) |
| race | `0x072` — CONFIRMED | `0x02E` — CONFIRMED | `0x02E` — CONFIRMED | `0x058` — CONFIRMED (`HALF-ELF`, `DWARF`). `ELF` 0, `HALF-ELF` 1, `DWARF` 2, `GNOME` 3, `HALFLING` 4, `HUMAN` 5 — a **different table again** from the C64's (`por/games.py`) |
| class | `0x073` — CONFIRMED | `0x02F` — CONFIRMED | `0x02F` — CONFIRMED | `0x059` — CONFIRMED (`THIEF`, `FIGHTER`); 0-based, 17 entries, singles first (§2.4) |
| age | `0x074` u16 LE — CONFIRMED | `0x030` u16 LE — CONFIRMED | `0x030` u16 **BE** — CONFIRMED | `0x052` u16 **BE** — CONFIRMED (`21075 YEARS`) |
| hp max | `0x076` **u16** — CONFIRMED | `0x032` **u8** — CONFIRMED | `0x032` **u8** — CONFIRMED | `0x081` **u8** — CONFIRMED (`HP 0/129`). **Current** hit points are a u16 at `0x190` — CONFIRMED (`HIT POINTS 55/77`) |
| saving throws ×5 | `0x09A`–`0x09E` — CONFIRMED | ~`0x06B` block — PROBABLE | ~`0x06B` block — PROBABLE | `0x083`–`0x087` — PROBABLE; they decode to the AD&D table for each specimen's class and level, and the sheet never shows them |
| level | `0x0A0` — CONFIRMED | UNKNOWN | UNKNOWN | `0x089` — PROBABLE, and it equals the **highest** of the seven class levels in all twelve. It is a maximum, not a sum: `TRIPEL TURBO` is 6/6/12 and reads 12. The sheet draws the class levels, not this |
| per-class levels | `0x0C9`–`0x0D0`, 8 — PROBABLE | UNKNOWN | UNKNOWN | `0x09D`–`0x0A3`, **7** — CONFIRMED (`LEVEL 1/2/3/4/5/6/7`); indexed by the single-class code, so slot 6 is the thief's |
| class bits | `0x0EB` — CONFIRMED | UNKNOWN | UNKNOWN | `0x0B7` — PROBABLE; magic-user 1, cleric 2, thief 4, fighter 8, which is the C64's own numbering, and 13 = 1\|4\|8 for the fighter/magic-user/thief. But **64 for the paladin and the ranger alike**, where the C64 gives them 0x40 and 0x80 separately — so the byte is *not* the C64's and must not be copied. `por/amiga.CLASS_BIT` is the table |
| experience | `0x0E8`, **3 bytes** — CONFIRMED | UNKNOWN | UNKNOWN | `0x044` **u32 BE** — CONFIRMED (`EXPERIENCE 1145390663`) |
| money | `0x0BB`–`0x0C8`, 7 × u16 — CONFIRMED | UNKNOWN | UNKNOWN | platinum `0x04C`, gems `0x04E`, jewelry `0x050`, u16 BE — CONFIRMED. The lighter coins are unlocated; R7 was the probe for them and did not finish |
| thief skills ×8 | `0x0A5`–`0x0AC` — CONFIRMED | UNKNOWN | UNKNOWN | `0x08B`–`0x092` — PROBABLE; non-zero in exactly the two specimens with a thief level |
| spells known / memorised | `0x078`, 7 / `0x020`, 16 — CONFIRMED / PROBABLE | UNKNOWN | UNKNOWN | UNKNOWN |
| alignment, sex | `0x0D8`, `0x0D6` — CONFIRMED | UNKNOWN | UNKNOWN | alignment `0x05D`, `law × 3 + morality` — CONFIRMED (`CHAOTIC EVIL`, `LAWFUL GOOD`); sex `0x05C`, 0 male — CONFIRMED |
| portrait head/body | `0x0FE`/`0x0FF` — CONFIRMED | UNKNOWN | UNKNOWN | different art set — see §7 |
| armour class | roster `0x10F` — PROBABLE | `0x02D`-adjacent — PROBABLE | — | `0x0B3`, stored `60 - AC` — CONFIRMED. It is the **base**: all twelve read 10, and the sheet's number is that adjusted for dexterity and equipment (§2.4) |
| unarmed damage | — | — | — | count `0x0AD`, sides `0x0AF`, bonus `0x0B1` — CONFIRMED (`173D175-79`); all twelve read 1d2 |
| movement | roster `+0x11` — PROBABLE | UNKNOWN | UNKNOWN | `0x088` — CONFIRMED (`MOVEMENT 136`, and `12` when `0x192` said 99); all twelve read 12 |
| inventory | `0x120`, 16 × 16 bytes — CONFIRMED | separate `.ITM`, 63 B/item | separate `.itm`, 65 B/item | appended past 484 bytes; UNKNOWN and **not** the writer's blocker. `0x0B6`–`0x0C7` is a portrait selector, and `ERROR: INVALID ITEM` is the graphics library's (§2.4) |
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
| 2 | ~~**The assumption test (§2.2), cases A–D.**~~ **DONE.** | A loads; **B loads too** | yes | one session | run — see §2.2 |
| 3 | **An OFS ADF writer.** Round-trip: read every file off disk 3, rebuild an image, compare file contents byte for byte; then boot it in FS-UAE and let PoD list the twelve characters. | `por/adf.py` (writer) with tests that read the player's own disks, never a committed image | yes, once | a week | PoD's `Add Character → Pools` shows all twelve names off our image |
| 4 | ~~**Decode the `.pc` record.**~~ **Done for everything the sheet shows.** The ramp of §2.3 found the numbers; the plausible-value probe of §2.4 found the four enums, current hit points and the seventh level slot. What is left is undecoded rather than blocking: saving throws, thief skills, the class bitmask, the portrait indices and the appended item data. | `por/amiga.py`, plus `tests/test_amiga.py` asserting the ramp offsets, the written record and the twelve real files | yes, repeatedly | done | every named field decodes to a legal AD&D value across all twelve |
| 5 | **Resolve the pointers.** Determine whether the `0x00`–`0x5F` addresses are re-linked on load. Two ways: read the loader (phase 1 may already answer it), or write a `.pc` with those longwords zeroed and see if PoD still loads it. | a ruling: don't-care, or must-be-plausible | yes | a session | a zeroed-pointer `.pc` loads and its sheet is unchanged |
| 6 | ~~**The map and the writer.**~~ **DONE.** `por.amiga.write` takes a `NeutralCharacter` — the one record every codec now shares, since #25 — and `to_pc` emits the 484 bytes. `Report.unaccounted` is empty on every character of the player's own party, so there is no "template" category. `field_disposition()` names what becomes of every neutral field, and `tests/test_amiga.py` fails if a field appears in one and not the other. | `por/amiga.py`, `tools/toamiga.py` | no | done | run |
| 7 | ~~**End to end.**~~ **DONE**, on Pool of Radiance rather than Silver Blades, for blocker 2's reason. `LADY KATHERINE` off the player's own C64 save loaded into PoD and her sheet matches field for field — §2.5. | the thing Donald asked for | yes | done | run |

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
| **Copper, silver, electrum and gold** | only platinum (`0x04C`), gems and jewelry have been located in the `.pc`. R7 was the probe for the lighter coins and did not finish; `0x048` and `0x04A` are zero in all twelve and are the obvious candidates. | reported, with the total, so the player knows what was left on the counter |
| **Armour class and unarmed damage** | not a loss so much as a category error. The C64's numbers already include worn armour and a strength bonus, PoD re-applies dexterity and strength itself, and no item crosses — so a converted character genuinely arrives unarmoured. | write the unarmoured `10` and `1d2`, which is what all twelve genuine records hold, and let PoD derive the rest. §2.5 shows it coming out at `AC 8` and `1D2+1` |
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
2. **The C64 source end is weaker than the Amiga target end**, and it is why
   §2.5 ran on Pool of Radiance. `docs/121-silver-blades.md`: no Silver Blades
   save disk written by the game exists here, no exported character file
   exists on any of the six sides, and the export load address and marker byte
   are still UNKNOWN. Wish reads the shipped `SAVEDBASH` demo party and has
   never round-tripped a real Silver Blades save. The converter itself is
   title-agnostic — it reads named fields, so a Silver Blades party goes
   through the same code the moment there is one to read — but nobody has run
   it on one.
3. ~~**The `.pc` record contains live heap pointers.**~~ **Answered by writing
   one.** `PodWriter` leaves `0x00`–`0x43` entirely zero and PoD loaded the
   record and put it in the party. The longwords are don't-care, nothing has to
   be synthesised, and phase 5 is closed.
4. ~~**The `.pc` length rule is not derived.**~~ **Answered.** Sizes 484 / 504 /
   514 / 524, and **484 is the record with no appended item data** — which is
   what `PodWriter` emits, and PoD loads it and puts it in the party. The extra
   bytes are the item lists, still undecoded, and a converted character simply
   arrives carrying nothing. `ERROR: INVALID ITEM (-1/29)` was never about
   items: it is the `GLIB` library reader asking `CHEAD.TLB` — 29 portrait
   heads — for item −1 (§2.4).
5. ~~**All twelve specimens are a maxed party.**~~ **Answered, and by a cheaper
   route than manufacturing saves.** Every ability is still 18 and the variation
   is still nearly nil, but the specimens are no longer how fields get found:
   §2.3's ramp makes *us* the source of variation, one probe per window, and the
   twelve maxed records became the independent check instead — every offset the
   sheet gave up decodes them to sane values.
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
   `docs/144-decoding-a-new-title.md` transfers. The mitigation is that **phase 4 does
   not need live memory** — differential *saves* are files, and the emulator is
   only needed to produce them. Anything that does want live memory (a PoD
   automapper) is a separate project and is out of scope here. Kickstart ROMs
   are present at `/home/donald/FS-UAE/Kickstarts` (1.3 and 3.1), so booting is
   not itself a blocker.
8. ~~**Nothing here has been run against a real emulator yet.**~~ Phase 2 has
   run (P51). What has **not** been checked is blocker 6's cross-rip repeat —
   everything observed is on the single untagged rip.

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
