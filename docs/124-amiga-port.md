# Porting a C64 party into Amiga Pools of Darkness — plan

**Status: it works end to end.** A character out of the player's own C64
*Pool of Radiance* save disk now converts to a `.pc`, and Amiga *Pools of
Darkness* loaded it, put it in the party and drew a sheet that matches the C64
one field for field -- see §2.5. `goldbox/amiga.py` is the whole converter and
`tools/toamiga.py` is how it is invoked.

**Phase 4 is done for every field the character sheet shows, and the
writer works.** Amiga Pools of Darkness **accepts a C64 Pool of Radiance
export** as a `SAVE/NAME.pc` and puts it in the party — no length check, no
signature check, and the `0x00`-`0x5F` heap-address block is don't-care. So the
record was decoded by *writing* one and reading the sheet, and it is now
written the other way round: `goldbox.amiga.PodWriter` emits a **484-byte record
built from named fields alone**, and PoD drew every one of them back —
`WRITTEN`, `FEMALE 33 YEARS`, `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`,
`HIT POINTS 55/77`, `EXPERIENCE 10000`, `STR 18 INT 17 WIS 16 DEX 15 CON 14
CHA 13`, `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`, `STATUS: OKAY`.
§2.3 and §2.4 have the probes; `goldbox/amiga.py` and `tests/test_amiga.py` carry
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
  loads. The variable part is appended item and effect data; the record proper
  is **404 bytes** and the loader stops there when the counts are zero (§1.16),
  so the writer's 484 are 404 that matter and 80 PoD never reads.
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

Where the +3 comes from is **three separate insertions**, measured on
fourteen specimens (#27 (Decode the Amiga Pool of Radiance record, so a shared title exists)) and reproduced by `goldbox.amiga.amiga_por_offset`:

1. one pad byte at `0x07F`, ahead of the effect pointer — zero in 14 of 14,
   and it is there because the Amiga keeps one `u32` where DOS keeps an
   offset word and a segment word, so a 68000 compiler even-aligns it;
2. a second insertion **inside DOS `0x083`-`0x087`**, located to a window and
   not to a byte: that region is zero in 12 of the 14, so no file
   differential can place it. A ramp probe under the emulator is what would;
3. **one trailing byte at `0x11F`**, past DOS's last field. 285 + 2 is odd
   and the struct is padded to an even size; the byte is junk in 3 of 14 and
   zero in the rest, which is what an uninitialised pad looks like.

An earlier reading had the cumulative shift accounting for all three, which
is arithmetically a byte short: the shift is **+2 at the end of the record**,
not +3, and `movement_current` — DOS's last field, 12 unencumbered — sits at
Amiga `0x11E` with one byte after it. That is measured: 12 in 13 of the 14
(9 and 3 on the two carrying most weight) at `0x11E`, and nothing coherent
at `0x11F`.

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
| `0x08` | `4`, `5` or `6` | **the number of 20-byte item records appended after the 404-byte record** — the loader reads it and reads that many (§1.16) | CONFIRMED |
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

Five Amiga disks arrived on 2026-08-25 and are at
`/mnt/media/roms/amiga/Curse_Of_The_Azure_Bonds/` and
`/mnt/media/roms/amiga/Secret_Of_The_Silver_Blades/`: two Curse of the Azure
Bonds game disks, a Curse **save disk**, and two Secret of the Silver Blades
disks. `goldbox/amiga_adf.py` walks them, finding the root block by scanning
because the save disk is 1804 blocks rather than 1760, and
`tools/amigarecords.py` is what pulls the specimens out -- twenty-one of them,
none of which is a loose file on any machine.

**The save disk's fourteen 288-byte `.cha` files are Pool of Radiance, not
Curse.** CONFIRMED 14 of 14: single ability bytes at `0x010`-`0x015` where a
Curse record holds current/max pairs, and levels at Pool of Radiance's caps
(fighter 8, thief 9, mage 6) with experience past the AD&D threshold, which is
what a capped character accrues. Somebody staged a Pool of Radiance party for
import. They are the specimens #27 (Decode the Amiga Pool of Radiance record, so a shared title exists) wanted; the field map is on that issue.

**The Amiga Curse record is `SAVE/*.guy` on the game disk** — eleven
pre-generated characters, 428 to 468 bytes. CONFIRMED 11 of 11: a **428-byte
record followed by N ten-byte effect records**, the four observed sizes being
0, 1, 3 and 4 effects, with every effect id landing on the right race.

| artefact | DOS | Amiga | delta |
|---|---|---|---|
| Curse character record | `.SAV`, **422** | `.guy` / in-save block, **428** | +6, the last byte a pad |
| Curse item record | `.SWG`, **63** | **66**, inside the same file as the record | +3 |
| Curse effect record | `.FX`, **9** | appended, **10** | +1 |
| Silver Blades character record | `.SAV`, **439** | in-save block, **340** | **−99**, and 102 of it is the spellbook |
| Silver Blades item record | `.STF`, **67** | **not measured** — no specimen carries an item | — |
| Silver Blades effect record | `.SFX`, **9** | appended, **10** | +1 |

**The item list is a chain, and its count is at `0x150`** — CONFIRMED 15 of 15:
zero in all eleven `.guy` files, which carry no items, and 2, 2, 3, 2 in the
four in-save blocks, which are the numbers that make each block's byte length
come out exactly. `0x18c` was the other candidate and is **refuted**: it reads
1 where there are no items.

**The 66-byte item record**, and it is now read out of the constructor that
builds one rather than off the nine specimens —
[`166-amiga-records-from-the-code.md`](166-amiga-records-from-the-code.md) has
the routine (`/Curse` `0x1C1EA`) and the whole table. The three insertions are
at `0x02F`, `0x03B` and `0x03E`, all three of them pads the constructor never
writes:

| offset | field |
|---|---|
| `0x000`-`0x029` | display text, NUL-separated, no length prefix |
| `0x02a`-`0x02d` | next item, u32 big-endian, NULL on the last |
| `0x02e` | type index (Chain Mail 55, Shield 59, Bastard Sword 34, Mace 23, Glaive-Guisarme 15) |
| `0x030`-`0x032` | name1, name2, name3 — `name3` is why `0x032` reads the type index again |
| `0x033`-`0x037` | plus, plus save, `readied`, hidden, cursed |
| `0x038`-`0x039` | weight, u16 big-endian — Chain Mail 300, the rest 100 |
| `0x03a` | quantity |
| `0x03c`-`0x03d` | value in gold, u16 big-endian, matching the price string in the item's own display text |
| `0x03f`-`0x041` | **charges**, effect, power |

**`0x03b` = 52 and `0x03e` = 47 are not fields, and neither is the `7f` at
`0x028`.** The constructor clears the node and writes neither; the nine
specimens carry those values because they came through the `ITEM<n>` template
loader (`/Curse` `0x1F2D6`), which unpacks each template into a stack struct
it never clears. This paragraph used to say `0x03e` was `charges` and that an
Amiga Curse save holding a wand would settle it; the code settled it instead,
and `charges` is at `0x03f`.

**The item record is per-title on the Amiga**: 65 bytes in Pool of Radiance
(195 = 3x65, 130 = 2x65, neither a multiple of 66) against 66 here, where
DOS's is 63 across the whole family. **Silver Blades' is 70** — the same 66
bytes plus a `u32be` at `0x042` that heads a scroll's extra spell nodes,
CONFIRMED from `/Secret`'s own allocator and unpacker, which is what settled
the "not measured at all, because no specimen carries an item" this paragraph
used to end with.

**The Amiga packs the Silver Blades spellbook as bits**, which is where the
99-byte difference comes from, and §1.3's "the DOS record, name re-encoded and
multi-byte fields byte-swapped" is therefore **not the whole rule**: one field
changes representation. §1.6a has the measurement. (This paragraph used to say
DOS spends 114 bytes at `0x071`-`0x0e2`; it is 117 at `0x071`-`0x0e5`, which
#53 (Read and write DOS saves for Curse, Silver Blades and Pools of Darkness)'s table settled after this was written, and the three insertions make up
the rest of the 99.)

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

**The DOS Curse -> Amiga Curse shift map, on 27 specimens.** Twelve DOS
records (the archives' `Default files/Saves`), eleven Amiga `.guy` pregens and
the four character blocks embedded in the Amiga Curse saved game -- and the
last four are what place two of the anchors, because they are a *played* party
where the pregens are not. It is `CURSE_SHAPE` in `goldbox/amiga.py`, which
reads `goldbox/dos_layout.py`'s Curse table through it rather than restating
it, and `tools/amigarecords.py` produces the specimens.

| DOS | Amiga | shift | anchor |
|---|---|---|---|
| `0x000`-`0x0F8` | same | **0** | `0x0DE`=1 (27/27); movement 12 at `0x0E4` (26/27); thief skills `0x0EA`-`0x0F1`; the **far pointer** at DOS `0x0F2`-`0x0F5` onto the Amiga's `u32be` at the same offset; the party flag at `0x0F8` |
| | one insertion in Amiga `0x0F9`-`0x0FB` | | three zero bytes; the money block below is what needs it |
| `0x0FB` | `0x0FC` | **+1** | the seven-word money block |
| `0x109` | `0x10A` | **+1** | the per-class level array, whose non-zero slots are that character's classes in 15 of 15 |
| `0x127` | `0x128` | **+1** | experience, `u32le` onto `u32be` -- 25000 single-class, 12500 dual, 8333 triple |
| `0x12D`-`0x131` | `0x12E`-`0x132` | **+1** | the cleric spell-slot array: KAROLYN's `4 3 1`, IILANDA's `5 3`, TEUT HALF-ELFIN's `5 4`. Amiga `0x133` is its **sixth** byte and has no DOS counterpart |
| `0x132`-`0x136` | `0x134`-`0x138` | **+2** | the druid array, with Amiga `0x139` its sixth byte |
| `0x137`-`0x13B` | `0x13A`-`0x13E` | **+3** | the magic-user array, which is `goldbox/spells.py`'s Curse table **exactly** for all seven casters and five zeros for the other eight -- and that table was read out of Curse's own `ECL65`, so it is the game's arithmetic rather than the rulebook's. Amiga `0x13F` is its sixth byte |
| `0x13C`-`0x14C` | `0x140`-`0x150` | **+4** | DOS's three-byte `gap_13c` at `0x140`, whose first word the loader byte-swaps; `size` = 1 for the dwarves and the gnome and 2 for everybody else (15/15); the icon colours `145 162 179 196 230 247` at `0x149`; the item count at `0x150` |
| | one insertion at Amiga `0x151` | | **located**: the count is at `0x150` and the `u32be` pointer array at `0x152`, non-zero in exactly the four played blocks |
| `0x14D`-`0x1A5` | `0x152`-`0x1AA` | **+5** | encumbrance, `u16le` onto `u16be`, at `0x18C`; hit points at `0x1A9`; armour class at `0x19F`, stored `60 - AC` |
| | Amiga `0x1AB` | | the trailing pad; 422 + 5 = 427 is odd and the struct is padded to 428 |

**Every insertion is an alignment pad, and that is the rule rather than an
observation.** A 68000 compiler even-aligns a `u16` or a `u32` and pads the
struct to an even length, and each of the three titles' insertions is
accounted for by exactly that: Pool of Radiance pads before its effect
pointer and its money block, Curse before its money block and its item
pointer array, Silver Blades before its effect pointer, its experience word
and its item pointer array. The two Curse insertions in the spell-slot
region are the exception nothing explains, and see below.

**The identity that fixes the money block and the item stride together**:
`money + Σ(weight × quantity)` equals the stored encumbrance in **12 of 12 DOS
and 15 of 15 Amiga** specimens -- 300 for every characterless pregen, and 683,
683, 782 and 682 for the four played blocks whose items are a Chain Mail and a
weapon apiece. Which slot of the seven is copper and which platinum is
**settled**: GALAIN's sheet draws `PLATINUM 282  GOLD 1` against slots 4 and 3
of the seven at `0x0FC`, which is the DOS order exactly. The other five slots
are still unwitnessed.

**`0x0F8` is a party flag** -- 1 in all twelve DOS records and all four Amiga
in-save blocks, 0 in all eleven pregens, same offset on both ports. CONFIRMED,
27 of 27, and it is what fixes shift 0 that far in. It is the third byte of
what `goldbox/dos_layout.py` calls `field_83_87` and does not name, which is a
finding for the DOS side rather than for this one.

**Refuted, and it was ours**: an earlier reading put an insertion inside DOS
`0x0F2`-`0x0F4`. That region is a *normalised* far pointer -- its offset word
reads 9, 1, 11, 15, 8, 8, 8, 8 across the twelve, every one at most 15 -- and
it maps four bytes onto the Amiga's four with no shift at all.

**The three insertions in the spell-slot region are the arrays themselves:
each is six bytes on the Amiga where DOS spends five.** This page used to say
two bytes were spare and the druid array might begin at `0x133`, `0x134` or
`0x135`, waiting on an Amiga Curse ranger of level 8. It waits on nothing:
`/Curse` reads a slot count as `record[0x12E + 6 * class + level - 1]` at
three places (`0x288`, `0x482`, `0x9F4`), so the **druid array is
`0x134`-`0x139`** and each array's sixth byte is the Amiga's own. DOS's are
five, from `FillChar(record + 0x12D, 15, 0)` in its `GAME.OVR`.
[`166-amiga-records-from-the-code.md`](166-amiga-records-from-the-code.md).

**The other two windows are placed too, and by the same routine.** Amiga
`0x0FB` is the pad and `0x0F9`-`0x0FA` are `field_83_87`'s last two bytes at
shift 0; Amiga `0x140`-`0x142` is DOS's `gap_13c`. A ramp probe was never
going to help -- the character sheet draws none of these bytes -- and the
loader answered all four in one reading.

### 1.6a The Amiga Silver Blades record, against its own DOS twin (#55 (Decode the Amiga Curse and Silver Blades records))

**Both ports ship the same six characters, so this one is not a shift map
argued from plausibility -- it is 492 field comparisons across the port
boundary on the same people**, six characters by the 82 fields that are
compared as bytes. `SAVE/savgamA.sav` on Amiga disk 1 holds Guy de
Valois, PAINE, EPONA, MALACHITE, DOMINIC and MORGAINE, and the DOS archives
ship `CHRDATA1`-`CHRDATA6` under those same names.

Read through the map below, **82 of the 85 fields in
`goldbox/dos_layout.py`'s Silver Blades table decode to the byte-for-byte
value its DOS twin holds, in 6 of 6 characters**, with twenty exceptions and
they are all named. Of the other three, `name_text` and `spellbook` are the
two that change representation and are checked their own way, and
`name_length` is the one field the Amiga record does not have at all:

* `effect_chain` and `heap_104` on the four characters that have them -- an
  Amiga heap address against a DOS far pointer. They cannot agree and a
  converter must not carry either;
* MALACHITE's four saving throws and eight thief percentages. The two ports'
  shipped copies of that one character are different rolls; the other five
  agree on both groups.

Any one-byte error in any of the four shift steps takes those twenty
mismatches to between 57 and 77, which is what makes the map measured rather
than plausible.

| DOS | Amiga | shift | what changes |
|---|---|---|---|
| `0x000` | -- | | the count byte goes; the name is 16 NUL-padded bytes |
| `0x001`-`0x070` | `0x000`-`0x070` | **0** | `age` at `0x06E` becomes `u16be` |
| `0x071`-`0x0E5` | `0x071`-`0x07F` | | **117 one-byte spell flags become 15 bytes of bitmask** |
| `0x0E6`-`0x0FA` | `0x080`-`0x094` | **-102** | attack level, the saving throws, movement, level, the thief percentages |
| | pad at Amiga `0x095` | | **located**: the thief block ends at `0x094` and the chain begins at `0x096` |
| `0x0FB`-`0x12B` | `0x096`-`0x0C6` | **-101** | the effect chain as one `u32be`; the money block at `0x09E` |
| | pad at Amiga `0x0C7` | | **located**: `unnamed_0ab` is at `0x0C6`, distinct in all six, and experience reads 200 000 big-endian at `0x0C8` |
| `0x12C`-`0x160` | `0x0C8`-`0x0FC` | **-100** | experience `u32be`; the four spell-slot arrays of seven, **unwidened**; the item count at `0x0FC` |
| | pad at Amiga `0x0FD` | | **PROBABLE**, not measured -- see below |
| `0x161`-`0x1B6` | `0x0FE`-`0x153` | **-99** | the item pointer array, encumbrance `u16be` at `0x138`, the combat tail |

439 - 102 + 3 = 340, and 340 is even, so there is no trailing pad.

**The spellbook is the whole of the size difference, and it is the one field
that changes representation.** DOS spends one byte per spell for ids 1..117;
the Amiga spends 15 bytes of bitmask at `0x071`, **least-significant bit
first within each byte**, id = bit index + 1. CONFIRMED on 6 of 6 and 62 set
bits: PAINE's `77 78 79 80`, DOMINIC's 29 ids and MORGAINE's 29 come out
exactly as the DOS twin's byte array holds them, and most-significant-first
reproduces none of the three. The three non-casters are empty on both ports.

**Curse does not do this**, which makes it a per-title decision rather than a
property of the port: the Amiga Curse spellbook is 100 bytes of 0 and 1 at
`0x079`, DOS's own shape, and the ids that come out of the eleven pregens are
clean class-coherent sets -- KAROLYN the cleric holds 1-8, 22-28 and 37-44,
ARIEL the magic-user holds 10, 11, 12, 15, 18, 21, 31 and 34.

**The item region was the one thing Silver Blades left undecided, and the
loader settled both halves of it.** No Silver Blades character on either port
carries an item, so `0x0F9`-`0x137` is zero on both sides and the corpus could
say nothing. `/Secret`'s record unpacker at `0x281A2` copies DOS `0x14E`+19 to
Amiga `0x0EA` and DOS `0x161`+69 to Amiga `0x0FE`, which **measures the pad at
`0x0FD`** rather than inferring it; and the title's item allocator asks for
`0x46` = **70 bytes**, laid out as Curse's 66 plus a `u32be` at `0x042` for a
scroll's extra spell nodes.
[`166-amiga-records-from-the-code.md`](166-amiga-records-from-the-code.md).
A played Amiga Silver Blades save with something on somebody's back is still
worth having -- it would put values in the node -- but nothing is blocked on
it.

**A finding for the DOS side, not this one, and it is settled.** All six DOS
Silver Blades records hold race 6, which `goldbox/dos_layout.py`'s
`RACE_NUMBERS` called `half-orc` -- but Guy de Valois is a paladin and
MORGAINE is a magic-user, and AD&D allows a half-orc to be neither. **Silver
Blades has its own race table**: `tribble`, `elf`, `half-elf`, `dwarf`,
`gnome`, `halfling`, `human`, `monster`, so 6 is `human`. CONFIRMED, read out
of the title's own `START.EXE` by `tools/dosraces.py` and corroborated by Gold
Box Companion's per-title data (#237 (The DOS race table is one table for four titles, and it is wrong for two of them)); it is `DosShape.race_numbers` now, and
`RACE_NUMBERS` is Pool of Radiance's and Curse's only. The Amiga agrees byte
for byte, so this was a question about the DOS table rather than about the
port.

### 1.7 The Amiga saved game is the DOS file with its last region replaced

`SAVE/savgamA.dat` (Curse, 15221, byte 0 `02`) and `SAVE/savgamA.sav` (Silver
Blades, 7233, byte 0 `01`), against [`141-dos-savegame.md`](141-dos-savegame.md).
The five regions are the DOS ones at the DOS offsets; only the last is a
different object.

**Pool of Radiance's is not, and §1.9a below is the correction** -- it has no
container byte and its whole array sits one byte lower. Read the title before
reading the file.

**The variable array is `docs/141`'s, unchanged, big-endian.** CONFIRMED, and
by a whole-array match rather than spot checks: listing every non-zero word at
`1 + 2*(addr − $4900)`, the Amiga Silver Blades save and the DOS Silver Blades
save hold **the same six words with the same values and no extras on either
side** — `$49E6`=1, `$49FC`=4, `$49FF`=3, `$4AF4`=2, `$5012`=1, `$503E`=6 —
and the two files are the same party in the same state. Across all four saves
`$5012` equals byte 0 of its own file and `$503E` equals the number of
character records the file holds.

**The ECL text buffer starts at `0x1401`, the DOS offset, and holds the script
byte for byte.** CONFIRMED, one specimen: the Amiga Curse save's region at
`0x1401` is byte-identical to **block 1 of `DISKB/ECL.GLB`, all 7622 bytes,
from byte 0**. Two differences from DOS, both measured:

* DOS carries its `ECL<n>.DAX` block **from byte 2 on** because that block
  opens with a `88 13` (u16le 5000) length header. The `GLIB` block has no
  header, so the Amiga carries it from byte 0.
* The buffer is the same 7680 bytes; block 1 fills 7622 and the rest is
  **zero**, consistent with `docs/141`'s corrected reading. Both DOS shipped
  saves have the whole buffer zero.

The Silver Blades save has **no ECL buffer at all** — the variable array ends
at `0x1400` and the square region starts at `0x1401`.

**`GLIB` is not the crunched container.** `*.GLB` and `*.TLB` are: magic
`GLIB`, u32 total size, u16 block count, u16 1, magic `DATA`, then count+1
big-endian u32 offsets, block *i* being `[off[i], off[i+1])`. **The blocks are
uncompressed** — `work/amiga/dax.py`'s bit-cruncher fails on 25 of ECL.GLB's 26
and yields 3 bytes of garbage from the last. §1.1's container work is for the
Pool of Radiance `.dax` archives and does not apply. `work/amiga/goldbox/glib.py`
reads it.

**Where DOS names six `CHRDAT<letter><n>` files, the Amiga embeds the records.**
CONFIRMED, 4 of 4 Curse blocks and 6 of 6 Silver Blades blocks, parsed to the
byte with no slack: a Curse block is 428 + items×66 + effects×10, a Silver
Blades block is 340 + effects×10 with no items. The Silver Blades effect counts
match the DOS default save's `.SFX` files character for character, and its six
characters are DOS slot A's six in the same state — which is what makes §1.6's
spellbook finding a diff rather than an inference.

**The square region**, between the buffer and the first record, is 24 bytes on
Curse and 22 on Silver Blades against 20 in both DOS files, and every byte of
it is now named from the save routine itself in
[`165-amiga-savegame.md`](165-amiga-savegame.md): the square struct (8 bytes
on Curse with `u16be` x and y, 6 on Silver Blades with single bytes), the
game mode before the current one, the game mode, three (WALLDEF block, slot)
pairs, and a `u16be` party count. §1.11 read Curse's `x = 3`, `y = 14` off the
screen; the `$49F0`=2 / `$49F1`=14 pair that once looked like corroboration is
engine scratch and was a coincidence (§1.9b).

The encounter message is in the Curse save **twice**: unpacked at `$5289`, one
character per word, which is `docs/141`'s buffer; and **packed two characters
per big-endian word at `$50CC`**, which is why it also reads as contiguous
ASCII at file offset `0x0f9a`. Whether DOS keeps the packed copy too is
untestable — neither DOS save holds an encounter string, and on DOS the pairs
would be byte-swapped.

**The clock is at Pool of Radiance's addresses.** `$49C6`-`$49CB` read
0, 5, 1, 1, 0, 0 in the Amiga Curse save, which is `docs/141`'s
sub-minute / minute units / minute tens / hour and gives **01:15**; both DOS
shipped saves read 00:00 there, which is what a save taken before play looks
like. The day and month words are zero in all three, so they are either unused
in Curse or untested. PROBABLE, three saves and no specimen with a non-zero
day.

All three of the questions this section once left open are now answered in
§1.14: Curse's square by §1.11's on-screen reading, and the inserted byte and
the buffer's length by lining the two titles' square regions up against each
other.

---

### 1.8 Amiga Pool of Radiance, read on screen (#27 (Decode the Amiga Pool of Radiance record, so a shared title exists))

The record is decoded and **confirmed by the instrument**, not only by
file-internal consistency. `goldbox.amiga.AmigaPorCharacter` reads the DOS field
table in `goldbox/dos_layout.py` through `amiga_por_offset`, big-endian; there is
no second table, so the two cannot drift apart.

**Twenty specimens.** Fourteen 288-byte `.cha` files on the Curse save disk
(a Pool of Radiance party somebody staged for import) and **six more nobody
had counted**: `CHRDATA1`-`6.sav` in the `save/` drawer of Pool of Radiance
disk 1 itself, with their `.itm`, their `.spc` and a 13141-byte
`savgamA.dat`.

**Driving the game to a sheet.** The Skid Row rip boots unattended, and the
route is worth writing down because two steps of it are not guessable:

1. the code-wheel screen takes a bare **RETURN** — the crack does not enforce
   it, so nothing here has to answer the wheel;
2. `LOAD SAVED GAME` prompts `PATH FOR SAVE  RETURN = POOLSAVE:`, and
   **the default is wrong for this disk**: `POOLSAVE:` is a volume the game
   disk does not carry, so RETURN raises an AmigaDOS *please insert volume
   POOLSAVE* requester that no keystroke dismisses. Typing **`SAVE/`** reaches
   the drawer on the game disk. That is also where a converted party would
   have to go.

**What the game drew, against what the reader says** — six of six on the
roster, and every field of the one sheet photographed:

| | on screen | from the file |
|---|---|---|
| GARWAN / STONEBEARD / GOLDLEAF / LAURANN / CONLY / MELCAR | AC 1/2/3/3/4/7, HP 14/14/8/10/8/6 | identical, 6 of 6, armour class through the `60 − value` bias |
| GARWAN | `MALE HUMAN AGE 18`, `CHAOTIC GOOD`, `FIGHTER` | sex 0, race 7, age 18 (`u16be`), alignment 6, class 2 |
| | `STR 18(00) INT 9 WIS 11 DEX 16 CON 18 CHA 16` | `[18, 9, 11, 16, 18, 16]`, exceptional strength 100 |
| | `LEVEL 1  EXP 17` | level 1, experience 17 as a **`u32be`** |
| | `AC 1  HP 14  ENCUMBRANCE 543  MOVEMENT 9` | 60−59, 14, 543 (`u16be`), `movement_current` 9 against a base movement of 12 |
| | `PLATINUM 8  GOLD 1  SILVER 24` | the `u16be` money block |
| | `THAC0 17` | **derived**: the record holds 60−40 = 20 and the game applies the +3 for 18/00 |

`tests/test_amiga.py` pins those numbers, and reads its specimens from a
directory named by `$AMIGA_POR_SAVES`, skipping without one.

**A DOS-side consequence.** `movement_current` at DOS `0x11C` is PROBABLE in
`goldbox/dos_layout.py`; the Amiga's counterpart is drawn on the sheet as
`MOVEMENT 9` beside a base of 12, which settles the field and independently
refutes the third-party claim that the byte is an AD&D class group (#59 (Map the DOS saved game, not just the character record)).

### 1.9 The Amiga Pool of Radiance item and effect files, and the neutral bridge (#27 (Decode the Amiga Pool of Radiance record, so a shared title exists))

The record was only two thirds of the reader. `CHRDATA<n>.itm` and
`CHRDATA<n>.spc` beside it hold the gear and the innate effects, and both are
now decoded — so `goldbox.amiga.to_neutral` turns an Amiga character into
`goldbox/neutral.py`'s record, which is the Amiga cell of the reader row #51 (Every permutation of DOS, C64 and Amiga, in both directions)
tracks.

**The item node is 65 bytes: the DOS 63 with two insertions.** Seventeen
nodes over nine distinct items, from the party shipped on disk 1.

| DOS | Amiga | field |
|---|---|---|
| `0x000` count byte + `0x001`-`0x029` text | `0x000`-`0x029`, **NUL-separated, no count byte** | the cached display line — `Chain Mail\0Mail\0          75\0` |
| `0x02A` | `0x02A`, `u32` big-endian | `next`, NULL on the last item, ascending by `0x48` |
| `0x02E`-`0x034` | same | type index, three name-table words, plus, plus save, **readied** |
| `0x035`-`0x036` | `0x035`-`0x037`, one of the three a pad | hidden, cursed |
| `0x037` | `0x038`, `u16` big-endian | weight |
| `0x039` | `0x03A` | quantity |
| — | `0x03B` | **pad, located to the byte**: quantity is measured at `0x03A` and value at `0x03C` |
| `0x03A` | `0x03C`, `u16` big-endian | value in gold |
| `0x03C`-`0x03E` | `0x03E`-`0x040` | charges, effect, power |

**The evidence is one identity, and it cannot be satisfied by accident:**
`money + Σ(weight × quantity)` equals the record's own derived encumbrance
word for **all six characters** — GARWAN's 543 being the number the game drew
on screen beside `MOVEMENT 9`. That fixes the seven money offsets, the 65-byte
stride, the weight and quantity offsets and the byte order of both, together.
Beside it: every weight is the published AD&D one (Long Sword 60, Chain Mail
300, Shield 100, Darts 5), every value matches the price the item's own
display line carries, the record's `item_count` equals the file's length over
65 in 6 of 6, and the `next` chain terminates NULL in 6 of 6.

**`readied` is at `0x034`** — the flag #55 (Decode the Amiga Curse and Silver Blades records) could not confirm on Amiga Curse,
where every specimen was readied. Here the darts read 0 and their display
line reads ` No `; everything else reads 1 and draws ` Yes `.

**The display line is a cached render on both ports, not a canonical string.**
#55 (Decode the Amiga Curse and Silver Blades records) left this UNKNOWN, wondering whether Amiga Curse's `" Yes  Shield "` meant
the ready column lived in the text. It does — and so it does on **DOS**: the
DOS `.ITM` files in `work/dos-saves` carry ` No   Long Sword +1 `,
` Yes  * Shield +1 ` and, on the same character, a plain `Plate Mail ` with
stale bytes (`Mail           400`) past its own length byte. So the line is
**never a source**, and neither reader reads it.

The tail is a second render showing through the first, and §1.12a works it out
to the character: `' Yes  Long Sword '` overwritten by `'Long Sword \0'` leaves
exactly `'word '` from index 12, on five of the five Amiga nodes that have a
tail. **A writer leaves all 42 bytes NUL, and that is CONFIRMED rather than
argued.** The screenshot this section used to promise was taken on
2026-09-05: a party written by `write_por_slot` with every item node NUL drew
`YES LONG SWORD`, `YES BANDED MAIL` and `YES SHIELD` on its ITEMS screen, so
the line is composed when that screen draws and nothing in it comes out of
the node. `docs/182-amiga-por-in-the-running-game.md` has the pictures and
the byte comparisons, and it also settles what the tails are: the engine
writes its own render back into the buffer, which is why a shipped node
carries one render with the tail of a longer earlier one behind it.

**The effect node is 10 bytes with the pad at offset 1**, which #55 (Decode the Amiga Curse and Silver Blades records) measured
on 62 records; disk 1's six agree, and their payload bytes `0x02`-`0x05` read
`00 00 FF 00` — exactly `goldbox/dos.py`'s `INNATE_PAYLOAD`, which is DOS's bytes
1-4. So the pad is at 1 and everything after it is DOS's four payload bytes
and four pointer bytes in order.

**The neutral bridge is a transposition, not a second codec.**
`goldbox.amiga.to_dos_record` re-cuts the 288 bytes into the 285 `goldbox/dos.py`
already reads, and `goldbox.dos.to_neutral` does the rest — so every grade, drop
and provenance line the DOS side earned on 24 specimens carries over, and
there is no second bridge to drift. Four rules and nothing else: the name is
re-cut from 16 NUL-padded bytes to a count and fifteen; `u16` and `u32` fields
are byte-swapped; experience is one Amiga `u32` spanning DOS's 24-bit field
*and* `gap_0af`; and the two live heap pointers — the effect chain and each
item's `next` — are written NULL rather than converted.

**Two regions are reported rather than guessed.** DOS `0x083`-`0x087`, where
the second insertion is still unplaced, is written **zero** — DOS's own
specimens hold `00 00 01 00 00` in 24 of 24, and copying that in would be
putting a DOS value into a record built from an Amiga one. And the Amiga's
trailing byte at `0x11F` has no DOS home. Both are named in the report.

### 1.9a The Amiga Pool of Radiance saved game is a byte out (#28 (Decode an Amiga saved game, not just a character file))

`save/savgamA.dat` on Pool of Radiance disk 1, **13141 bytes**, and it is *not*
the shape §1.7 describes.

| region | DOS, 13137 | **Amiga Pool of Radiance, 13141** |
|---|---|---|
| container byte | 0 | **absent** |
| VM variable array | 1-5120, `1 + 2*(addr − $4900)` | **0-5119, `2*(addr − $4900)`** |
| ECL text buffer | 5121-12800, 7680 | **5120-12799, 7680** |
| square and party | 12801-12808, **8** | **12800-12812, 13** |
| character table | 12809-13136, 328 | **12813-13140, 328** |

`13137 = 1 + 5120 + 7680 + 8 + 328`; `13141 = 0 + 5120 + 7680 + 13 + 328`. The
+4 is **−1 for the missing container byte and +5 for the square block**, and
all four boundaries are measured.

**Six readings fix the array's base**, and the wrong one multiplies every
value by 256: `$5012`=3 (New Phlan's container number, `docs/141` slot A),
`$503E`=6 (the six `CHRDATA<n>.sav` beside it), `$49E6`=1 (indoors),
`$4AFA`-`$4AFC`=(0, `$FFFF`, `$FFFF`) — **byte-identical to DOS slot A's New
Phlan wallset triple**, `$5200`=25 (and file byte 12804 reads 25, the same copy
DOS keeps at its 12805), and the clock at `$49C6` reading 05:48.

**The ECL buffer starts at 5120, one byte before DOS's.** The Amiga's buffer
and the DOS save's open with the same twenty bytes and **3916 of 7680 are
identical**, against **574** when the two are lined up at the same offset. Both
files are New Phlan. Script data runs to 12587 (7468 bytes) with zeros after,
the same fill `docs/141` records.

**The character table names files, it does not embed records** — six 41-byte
entries holding `CHRDATA1`…`CHRDATA6` as **8 plain bytes with no count byte**,
then 33 bytes of heap junk. DOS spends a count byte, 8 name bytes and 32 of
junk. That is the third place the Amiga trades DOS's count byte for a NUL or
for nothing, after the character name and the item display text. So §1.7's
"where DOS names six files, the Amiga embeds the records" is **Curse and Silver
Blades only**.

**The square block is 13 bytes and all of them are placed**, from the save
routine rather than from the file ([`165-amiga-savegame.md`](165-amiga-savegame.md)):
a ten-byte write of a **seven-byte** square struct -- x, y, facing (doubled),
the wall in front, a square property, two bytes nothing references -- running
three bytes into the wallset table that follows it in memory, then the view
type (12810 = 1, 3D), the game mode (12811 = 2, camp) and the count byte
(12812 = 6, agreeing with `$503E`). `12800`-`12802` = 0, 4, 6 is x, y, facing
and §1.9b's step diff confirmed it. The earlier reading of this paragraph
put x at 12801 and asked whether facing was undoubled; it was off by the
missing container byte.

### 1.9b The Amiga Pool of Radiance square, measured one step apart (#28 (Decode an Amiga saved game, not just a character file))

A WinUAE run on 2026-08-26 loaded `SAVE/` slot A on disk 1 — status line
**`0,4 W 05:48`** — turned right, stepped forward to **`0,3 N 05:49`**, and
saved to slot B. Two files one action apart, in the same drawer.

```
A (0,4 W 05:48)   12800:  00 04 06 01 19 00 00 00 00 00 01 02 06
B (0,3 N 05:49)   12800:  00 03 00 00 00 00 00 00 00 00 01 02 06
```

| offset | A | B | what |
|---|---|---|---|
| 12800 | 0 | 0 | **x** |
| 12801 | 4 | 3 | **y** — the step north |
| 12802 | 6 | 0 | **facing, DOS's doubled encoding**: 6 W, 0 N |
| 12803 | 1 | 0 | DOS's unnamed engine-maintained byte |
| 12804 | 25 | 0 | **the low byte of `$5200`**, which moved 25 → 0 in the same save |
| 12805-12809 | 0 | 0 | two unreferenced struct bytes and three bytes of the neighbouring wallset table -- `165-amiga-savegame.md` |
| 12810-12812 | 1, 2, 6 | 1, 2, 6 | view mode, the constant 2, party size |

**The clock moved by one minute at `docs/141`'s own addresses**: `$49C7`, the
minute-units digit, 8 → 9 against `05:48` → `05:49` on screen.

**Four of `docs/141`'s nine engine-rebuilt words are rebuilt here too** —
`$49F0` 14 → 0, `$5079` 14 → 7, `$5082` 25 → 0, `$5200` 25 → 0 — and
**the character-table filenames are live**: saving to slot B rewrote all six
entries from `CHRDATA<n>` to `CHRDATB<n>`. **The ECL buffer did not change**,
not one byte of 5120-12799.

**`$49F0` is engine scratch and not a coordinate**: it went 14 → 0 across a
step that moved y and not x, and `docs/141` lists it among the nine words the
engine rewrites by itself. §1.7 cited it as corroboration for Curse's square;
that was an accident.

**It did not follow that Curse's square is single bytes, and §1.11 shows it is
not.** The square is a per-title object.

**The route into Amiga Pool of Radiance, complete.** §1.8 had it as far as the
roster; two more steps are not guessable:

1. code wheel — bare **RETURN**;
2. intro — **ESC**, four times at fifteen-second intervals;
3. `CHOOSE A FUNCTION` — **`L`**. Every menu in this engine picks by first
   letter, and **RETURN selects nothing**;
4. `PATH FOR SAVE  RETURN = POOLSAVE:` — type **`SAVE/`**;
5. `LOAD WHICH GAME: A` — **type the letter**, then RETURN. RETURN alone
   leaves the prompt sitting there;
6. **movement is the number keys `4`, `6`, `8`.** The arrow keys and the
   numeric keypad do nothing — `VK_LEFT`, `VK_RIGHT`, `VK_UP`, `VK_DOWN`,
   `VK_NUMPAD6` and `VK_NUMPAD8` all left the status line where it was;
7. saving — **`E`** ENCAMP, **`S`** SAVE, the slot letter, RETURN, then
   **`N`** to `QUIT TO WORKBENCH  YES  NO`.

**Amiga Curse cannot be driven this way.** Its rip still asks the code wheel:
`P` at the option bar reaches *"TYPE THE CHARACTER IN BOX NUMBER 3 UNDER THE
____ PATH"* and a bare RETURN does not satisfy it. `#108 (Amiga Curse asks its
code wheel, so the title cannot be driven unattended)`.

### 1.10 Writing an Amiga disk, and the block that is free but not free (#36 (Write an Amiga disk image, not just the character files))

`goldbox/amiga_adf.py` writes the AmigaDOS filesystem: allocate from the bitmap,
write OFS data blocks, build a file header, thread it into the parent drawer's
hash chain, fix every checksum. Until it existed a converted character reached
an Amiga disk only by overwriting an existing file's bytes.

**Proved in the running game.** Sixteen files -- a whole save slot, six
`CHRDATB<n>.sav` with their `.itm` and `.spc`, and a 13141-byte
`savgamB.dat` -- were written onto a copy of Pool of Radiance disk 1 as **new
files**, and Amiga Pool of Radiance listed slot B in `LOAD WHICH GAME: A  B`
and loaded it: the six-character roster with its own AC and HP, standing at
`0,3 N 05:49`, which is the state the save holds.
`work/amiga/p36/shots/slotb-final.png`.

**`save/save` is the slot list, not a note about the current slot.** Ten bytes;
`"A         "` on the shipped disk and `"AB        "` after the game saved to
B. A disk carrying a complete slot B that does not name B here is offered only
`A` at the picker — measured, one run wasted on it. §1.1's "which save letter
is current" is superseded. §1.13 goes further: the ten bytes are an array
indexed by the slot letter, not a list, which those two specimens cannot show
because A and B are the first two bytes either way.

**A cracked release reads blocks the bitmap says are free, and this cost two
runs.** On Pool of Radiance disk 1:

| what was written | where it landed | what the game did |
|---|---|---|
| one small file | header 917, data 991 | boots to the code wheel |
| a second small file | header 992, data 993 | **hangs on a white screen**, drive still seeking |

No existing file was touched, every checksum was right and the filesystem
verified. Blocks 992-993 sit between the bitmap at 990 and the `save` drawer at
996 — where a loader would keep its own scratch. So `_allocate` **counts down
from the top of the disk**: the high end of a Gold Box disk is the game's own
data and is allocated, so the free runs there are genuinely unused.

**And a checksum one longword low validates.** The first version of the writer
put the block checksum at `0x010` instead of `0x014`. Every block still summed
to zero, so it passed both a checksum recomputation and a sum test — the field
being compared held zero on both sides — and `verify()` called the disk clean.
Kickstart said `Not a DOS disk in unit 0`. What catches it is a *structural*
invariant: `first_data` at `0x010` names the same block as the first entry of
the data table, on **211 of 211** files across four real disks.

Three more things the real disks taught, each of which would have made a
reader refuse a genuine disk:

* **the root block is 880 even on the 1804-block Curse save disk**, whose
  middle block, 902, is `ADDERLY.cha`;
* **the second bitmap-page pointer is junk.** A floppy needs one page (4064
  bits against 1758 blocks); Pools of Darkness disk 2 names block 955 *twice*
  and disk 3 names 1352 and 1360;
* **`bm_flag` is not always -1.** Both Silver Blades disks hold 1.

### 1.11 Amiga Curse, read on screen (#55 (Decode the Amiga Curse and Silver Blades records), #28 (Decode an Amiga saved game, not just a character file), #108 (Amiga Curse asks its code wheel, so the title cannot be driven unattended))

The Curse rip still asks its code wheel, so this title could not be driven
unattended at all until the challenge was answered from Donald's separate
copy-protection repository. **Nothing about that is recorded here**, per
`.claude/rules/documentation.md`; what matters is that the game now boots,
loads and draws, and that one answer computed from the C64 tables was accepted
on the Amiga — CONFIRMED, one challenge.

**The route in**: title art takes RETURN; the `PLAY / DEMO / TRANSFER / QUIT`
bar **does not respond to RETURN** and has to be picked by first letter, `P` —
a second RETURN falls into the attract-mode combat demo, which looks exactly
like a wedge; then the challenge, one character and RETURN. The party menu
picks by first letter throughout, and `LOAD WHICH GAME:` wants the letter with
no path prompt. **Movement did not respond to the number keys that work in
Pool of Radiance**, nor to the arrow keys.

**GALAIN's whole sheet, against the record** — the block at `0x3219` of
`SAVE/savgamA.dat`:

| screen | record | offset |
|---|---|---|
| `MALE ELF AGE 180` | race 2, age 180 | `0x074`, `0x076` `u16be` |
| `FIGHTER/MAGIC-USER`, `LEVEL 4/4` | class 13; 4 at slots 2 and 5 | `0x075`, `0x10A` |
| `STR 18(75)` and five more | `18 18` … `19 19` …, `75 75` | `0x010`, `0x01C`, as current/max pairs |
| `PLATINUM 282  GOLD 1` | `[0, 0, 0, 1, 282, 0, 0]` | **`0x0FC`, seven `u16be`** |
| `EXP 12500`, `MAX HP 32`, `HP 32` | 12500, 32, 32 | `0x128` `u32be`, `0x078`, `0x1A9` |
| `AC 1` | 59 | **`0x19F`, stored `60 − value`** |
| `THAC0 15` | `60 − 43` = 17 | `0x073` — **derived**, +2 for 18/75 |
| `ENCUMBRANCE 683`, `MOVEMENT 9` | 683, base 12 and current 9 | `0x18C`, `0x0E4`, `0x1AA` |

Three things this settles that §1.6 could not:

* **armour class is at `0x19F`** — the only byte in `0x100`-`0x1AB` reading
  `60 − AC` for all four in-save characters;
* **the money block is at `0x0FC` in Pool of Radiance's order** — gold at slot
  3 and platinum at slot 4, named by a character who holds both;
* **`0x1AA` is `movement_current` and it is not the constant 12** that eleven
  pregens made it look. They carry nothing; GALAIN carries 400 and the sheet
  draws 9.

**The square is `x = 3, y = 14, facing East`** — status line `3,14 E 01:15`.
`0x3201` and `0x3203` are `u16be`, `0x3205` is the facing byte in DOS's doubled
encoding, and the clock at `$49C6` reads 01:15 as `docs/141`'s six digit words.

**So the square is a per-title object**: Pool of Radiance keeps DOS's three
single bytes (§1.9b), Curse widens x and y. That is the third per-title
difference in the Amiga port, after the saved game's missing container byte and
the item record's size. **Read the title before reading the file.**

### 1.12 Writing an Amiga Pool of Radiance character (#105 (Write an Amiga Pool of Radiance character, not just a Pools of Darkness one))

The reader landed in §1.8 and §1.9; this is the other half, and it is the same
transposition run backwards. `goldbox.amiga.write_por` takes a `NeutralCharacter`,
hands it to `goldbox.dos.write`, and re-cuts the 285-byte DOS record, its `.ITM`
and its `.SPC` into the Amiga's 288, 65 and 10. **There is no second field
table and no second conversion.** Every drop, every derived value and every
provenance line the DOS writer earned on 24 DOS specimens carries over
unchanged, and the only lines this side adds are the three bytes the Amiga has
and DOS does not.

**Twenty of twenty round-trip byte for byte**, masked by the writer's own
declared list rather than by whatever happened to differ:

| what | result |
|---|---|
| 288 -> 285 -> 288, no neutral record in the middle | **20 of 20** identical outside `POR_WRITE_UNSOURCED` |
| Amiga -> neutral -> Amiga, the whole path | **20 of 20** identical outside that list plus `goldbox.dos`'s own `WRITE_UNSOURCED`, `WRITE_CONSTANTS` and computed fields |
| the 65-byte item nodes | **17 of 17** identical past the display cache and `next` |
| the 10-byte effect nodes the neutral record can hold | **15 of 15** identical past the four-byte `next` |
| `.itm` lengths | identical to the originals, **6 of 6** |
| `.spc` lengths | identical to the originals, **9 of 12** -- see below |

Re-measured 2026-09-04 against a corpus rebuilt by `tools/amigasaves.py`. The
mask covers 125 of the 288 offsets, so **163 bytes of every record have to
match exactly**, and they do on all twenty.

**The `.spc` line was 6 of 6 and it is 9 of 12, and the difference is a
defect.** The earlier figure was measured on the six records the game shipped
on disk 1, every one of which carries only racial effects. Twelve of the twenty
specimens have a `.spc` file, and **three of them lose it entirely**:
`goldbox.dos.to_neutral` keeps only the ids in `INNATE_EFFECTS`, the neutral
record has no field for the rest, and `write_por` therefore writes a zero-byte
file. ADDERLY's extra strength (38), CONJURER's Ring of Fire Resistance (61)
and MAGICIAN's displacement (89) -- **all three at duration zero**, so none of
them is a spell that was going to expire anyway, and the only duration-bearing
`.spc` record anybody has read is a DOS `BLESS` at `02 00 01 00`.
`goldbox.amiga.to_neutral` now names each one in `dropped`, which is the
minimum `.claude/rules/conversions.md` asks for; carrying them needs a neutral
field and is `#232 (An item-granted effect is dropped on the way through the neutral record, with no report)`.

**C64 -> Amiga, which is the direction this writer exists for: 78 of 78.**
Every character on every `PORSAVE*` disk the player has converts to a 288-byte
record with `unaccounted` empty, a name that survives, an `item_count` that
matches the `.itm` file's own length, and -- the check a wrong offset cannot
fake -- **the encumbrance identity balancing**: the record's `encumbrance` word
equals its seven money words plus the weight times quantity of every item node
the same write produced. That single identity fixes the money offsets, the
65-byte stride, and the weight and quantity offsets and byte order together,
and it is what `test_a_c64_party_converts_to_a_coherent_amiga_record` asserts.
Watched failing with the item shift map's second step moved by one.

**The specimens come out of the disks now, not out of `work/`.**
`tools/amigasaves.py` reads the twenty records back out of the images they live
in -- six on Pool of Radiance disk 1 and fourteen on the Curse save disk -- and
`tests/test_amiga.py` calls it when `$AMIGA_POR_SAVES` names nothing. The
earlier corpus was extracted into `work/`, which is gitignored and was lost,
and every one of these tests was skipping until 2026-09-04.

**The second insertion is narrowed from six candidate positions to three, and
it is measured.** DOS holds `00 00 01 00 00` at `0x083`-`0x087` in 24 of 24
specimens. On the Amiga that `01` reads at **`0x086`** in **8 of 20** -- all
six `CHRDATA<n>.sav` the game itself wrote on disk 1, plus two of the fourteen
`.cha` exports -- and `0x086` is `amiga_por_offset(0x085)`, which is where
DOS's `01` lands only if the insertion sits *after* it. A pad at `0x084`,
`0x085` or `0x086` would put the `01` at `0x087`, and **no specimen reads 1
there**. So the insertion is one of `0x087`, `0x088`, `0x089`; the other twelve
specimens hold six zeros and say nothing either way. PROBABLE, resting on the
DOS constant being the same field on both ports.

All three survivors are zero in all twenty, so **a writer does not have to know
which**: `AMIGA_POR_FIELD_83_87` is the six bytes `00 00 01 00 00 00` and it is
right whichever one the pad turns out to be. `AMIGA_POR_UNPLACED` is
deliberately *not* narrowed to match -- the reader's refusal exists to stop a
caller guessing, and this reading is an inference rather than a probe.

**What the writer does with the three Amiga-only bytes**, each measured on the
twenty specimens rather than assumed: `0x07F` zero (20 of 20), the `0x084`
window as above, and `0x11F` zero (15 of 20, junk in the other five, which is
what an uninitialised pad looks like). The effect chain at `0x080` and each
item's `next` at `0x02A` are written NULL, because they are live Amiga heap
addresses and the engine relinks both on load.

**Two things `goldbox.dos.write` imposes on this side and neither is ours:**

* **memorised spells are repacked.** `goldbox.dos` reads the sixteen slots as a
  set and writes them back from the end, on the DOS reading that "DOS fills
  its sixteen slots backwards from the end". **The Amiga corpus refutes that as
  a general rule**: of the fourteen `.cha` exports, one is filled from the
  *start* (`22 22 2f 2f 00...`), and three have entries with zeros on both
  sides (`00 x10, 15 15 00 22 2f 00`). The spells survive; their slot positions
  do not. `#110 (Memorised spells lose their slot positions on the way through the neutral record)`.
* **experience is capped at 16 777 215.** The Amiga field is a `u32be` and the
  reader reads all four bytes, but `goldbox.dos.write`'s own field is three bytes
  wide, so anything going through it overflows with a bare `OverflowError`
  above that. No Pool of Radiance character can reach it. `#111 (An experience total over 16 777 215 crashes the DOS writer instead of being refused)`.

**The file names**, read off disk 1 and confirmed by the game's own save to
slot B (§1.9b): `save/CHRDAT<slot><n>.sav` with `.itm` and `.spc` beside it,
`n` from 1 to 6. `goldbox.amiga.por_filename` is the one place that knows it. **A
character carrying nothing gets no `.itm` file at all** -- `b""` is not an
empty file, and #62 (A converted character who owns nothing gets a corrupt sheet, and DOS then invents a garbage item) is what handing the engine a zero-length one did on DOS.

### 1.12a The engine's own rewrite of a party we wrote (#105 (Write an Amiga Pool of Radiance character, not just a Pools of Darkness one))

The strongest evidence the writer has is not a round trip -- it is the game
writing the same six characters out itself and the two files being compared.
That run already happened, in #109 (A save slot written onto an Amiga disk is not offered by the game's picker): slot `F` on a copy of disk 1 was written by
`write_por_slot`, the game loaded it, and from that loaded party `E` `S` `C`
saved it back into slot `C`. So `CHRDATF<n>` is ours and `CHRDATC<n>` is the
engine's, for the same party in the same session.

**The two differ in three field groups and nothing else**, and all three are
already named in `POR_WRITE_UNSOURCED` or `goldbox.dos.WRITE_UNSOURCED` as
live heap:

| Amiga offset | field | bytes differing, 6 characters |
|---|---|---|
| `0x0CB`-`0x0CD` | `item_chain` | 17 |
| `0x107`-`0x109` | `heap_104` | 15 |
| `0x081`-`0x083` | `effect_chain` | 9 |
| `0x077`-`0x07B` | five thief skills, on the one thief | 5 |

Everything else in all six 288-byte records is byte-identical. So the writer's
claim that those pointers are the engine's to fill is not an argument from
plausibility any more: **the engine filled them.** Our NULLs went in, its own
heap addresses came out, and the party played.

The same three files say two more things:

* **The item `next` chain: 17 of 17 nodes differ in `0x02A`-`0x02D` and in
  nothing else.** The engine relinked a chain we wrote as all-NULL, and the
  last node came back NULL because that is what a terminator is.
* **The effect `next` chain: 4 of 4 nodes on the one character with a chain**,
  same shape, `0x006`-`0x009` and nothing else. The payload bytes of all six
  nodes across three characters are identical.

**And the display line is not composed on load or on save.** All 17 item nodes
we wrote carry 42 NUL bytes where the game's own files carry
`Long Sword \0word \0          15\0`. The engine loaded them, ran a camp, saved,
and **wrote all 17 back still NUL**. So the moment the line is written is
neither of those two.

Which leaves the drawing, and the seventeen genuine nodes say a good deal about
it. Reading the region as three NUL-separated strings:

| what the buffer holds | readied |
|---|---|
| `Long Sword ` / `word ` / `          15` | 1 |
| `Banded Mail ` / `Mail ` / `         90` | 1 |
| `Leather Armor ` / `rmor ` / `        5` | 1 |
| ` Yes  Shield ` / `              15` | 1 |
| ` No   60 Darts ` / `             1` | 0 |

**The second string is the tail of an earlier, longer render of the same
item.** `' Yes  Long Sword '` is seventeen characters; write `'Long Sword \0'`
over the front of it and what is left from index 12 is exactly `'word '`.
`' Yes  Banded Mail '` is eighteen, and from index 13 that is `'Mail '`. Five of
five with a tail work out that way. So the buffer has been rendered **at least
twice for the same item**, once with the ready column and once without -- a
composer that runs repeatedly and on more than one screen, not once when the
item was acquired.

And **everything in the line is derivable from fields the writer carries**:
`name1`, `name2` and `name3` at `0x02F`-`0x031` are the name-table indices
(`Banded Mail` is `0, 48, 57` and `Leather Armor` is `0, 49, 50`), `readied` at
`0x034` is the ` Yes `/` No ` column, `quantity` at `0x03A` is the `60` in
`60 Darts`, and `value` at `0x03C` is the price column. Nothing in the 42 bytes
is a source for anything.

**CONFIRMED, 2026-09-05: the ITEMS screen composes the line from those fields
and caches it back, so a NUL line is filled in on the first draw and
`write_por`'s all-NUL buffer is correct as it stands.** The screenshot this
section asked for was taken under WinUAE. GARWAN's slot, written by
`write_por_slot` with all seventeen item nodes holding 42 NUL bytes, drew:

```
GARWAN'S ITEMS
READY ITEM
YES    LONG SWORD
YES    BANDED MAIL
YES    SHIELD
```

So no row comes out of the buffer, and the paragraph above about where each
column comes from is what the engine is doing.

**And the cache half was watched being written.** Two nodes of a converted DOS
character went in NUL, the game drew ITEMS, camped and saved, and the same two
nodes came back holding `Flail \0lail \0` and `Banded Mail \0Mail \0` — the
current render, then the tail of a longer earlier one, which is the shape the
shipped nodes in the table above have. That is why the earlier measurement in
this section stands rather than being contradicted: **that run never opened
ITEMS**, so nothing ever composed anything to cache.

`docs/182-amiga-por-in-the-running-game.md` has both, with the pictures.

**Five thief-skill bytes are derived, and this is the first evidence of it.**
GOLDLEAF, a level-1 elf fighter/mage/thief with DEX 19, is the party's only
thief. The record we wrote held `23 14 14 0F 14 0F 55 00` at `0x077`, copied
exactly from the disk's own shipped record; the engine wrote back
`32 28 1E 20 20 0F 55 00` -- pick pockets 35 to 50, open locks 20 to 40, find
traps 20 to 30, move silently 15 to 32, hide in shadows 20 to 32, with hear
noise, climb walls and read languages landing on the values already there.
Those are the AD&D level-1 thief figures plus a DEX 19 adjustment, which the
stored ones are not. **PROBABLE that the engine recomputes all eight on load**;
one character, one run, and load and save cannot be told apart from the file
alone. It costs a converter nothing either way -- the values we carry are
overwritten with better ones.

### 1.13 Writing a whole save slot, and the list the picker reads (#109 (A save slot written onto an Amiga disk is not offered by the game's picker))

§1.10 found that `save/save` is the **slot list**, not a note about which slot
is current, and that a disk carrying a complete slot the file does not name is
offered only the slots it does name. `#36 (Write an Amiga disk image, not just the character files)`'s demonstration worked because that
file was edited by hand as part of the experiment; nothing wrote it.

`goldbox.amiga.write_por_slot(disk, slot, characters, savegame)` is what writes
one now, and the rule it enforces is **a slot that cannot be listed is not
written**. The refusals run before anything touches the disk, and the list is
read back afterwards, because a silent failure here is invisible until
somebody boots the game.

| what it writes | why |
|---|---|
| `save/CHRDAT<slot><n>.sav`, `.itm`, `.spc` | the party, through `write_por` |
| `save/savgam<slot>.dat`, **retargeted** | the engine loads the party the saved game's character table names, not the party the slot letter implies -- measured, because the game's own save to B rewrote all six entries from `CHRDATA<n>` to `CHRDATB<n>` (§1.9b) |
| `save/save` | the slot list: ten bytes, one per slot, each letter in its own place -- `A` is byte 0 and `J` is byte 9, and a slot that does not exist is a space |

Three things it refuses rather than doing badly: a slot letter outside
`A`-`J`, which is what the ten-byte list can hold; a party that is not one to
six characters; and a slot with no saved game and none given, because the
character files alone are a drawer full of files rather than something the
game can load. It also **removes the previous occupant's files** for character
slots the new party does not fill, so a six-character save followed by a
four-character one does not leave two loadable strangers behind.

**`save/save` is an array indexed by the slot letter, not a list, and that
was measured rather than guessed.** The question this section used to leave
open -- does the game sort the letters or append them? -- had a third answer
that neither candidate covered. Amiga Pool of Radiance was booted on a
writable copy of disk 1, slot A was loaded, and the party saved to `D` and
then to `B` from one camp. The file came back:

```
"AB D      "
```

`A` at byte 0, `B` at byte 1, **a space at byte 2 where `C` would go**, and
`D` at byte 3. Sorting would have given `ABD` and appending `ADB`; both close
the gap. So byte *n* is slot `chr(ord('A') + n)`, holding its own letter when
that slot exists and a space when it does not -- which is also what the two
earlier specimens, `"A         "` and `"AB        "`, say once you know to
read them that way. **A full disk is `"ABCDEFGHIJ"`**, and the camp's own
`SAVE WHICH GAME:` line draws exactly `A B C D E F G H I J`, so ten is the
game's number and not an inference from the file's size.

**That made the old writer wrong, and it was fixed in the same session.** It
appended, so adding `F` to a disk holding A, B and D produced `"ABDF      "` --
`D` in `C`'s byte and `F` in `D`'s. The picker draws the same four letters
either way, which is why this needed watching the game write the file rather
than reasoning about it; what breaks is the *next* save, because the game
reads this array into memory and stores the new letter at its own index. From
`"ABDF      "` a save to `C` would overwrite the `D` entry and the picker
would stop offering D.

**Both halves were then proved in the running game (2026-09-01).**
`tools/porslot.py` wrote slot `F` onto that same disk with `write_por_slot`,
which produced `"AB D F    "`. Booted, `LOAD SAVED GAME`, path `SAVE/`:

```
LOAD WHICH GAME: A  B  D  F
```

`F` was offered and loaded -- the same six characters, `GARWAN` AC 1 HP 14
through `MELCAR` AC 7 HP 6, standing at `0,4 W 05:48`. That is the
demonstration `#109 (A save slot written onto an Amiga disk is not offered by
the game's picker)` asked for, and the first time a slot list *written by our
code* has been put in front of the picker; `#36 (Write an Amiga disk image,
not just the character files)` proved a hand-edited one.

**What this run does *not* prove, because it is easy to read as if it did:
the savegame repointing.** Slot F was written from slot A's own party, so the
two are the same six characters -- and a `savgam` that had never been pointed
at `CHRDATF<n>` would have loaded `CHRDATA<n>` and shown exactly the same
sheet. This run separates nothing on that half. The evidence for the
repointing is `test_a_saved_game_moved_to_another_slot_is_retargeted` and the
measurement in 1.9b, where the game's own save to B rewrote all six entries;
what would settle it in the running game is **two different parties on one
disk**, which is `#28 (Decode an Amiga saved game, not just a character
file)`. What this run proves is the slot-list mechanism, and only that.

Then, from that loaded slot F, the game was made to save to `C`, and it wrote:

```
"ABCD F    "
```

It read our file, filled byte 2, and left `F` at byte 5 exactly where we put
it. So the game and this writer now agree about the whole ten bytes, and not
merely about which letters appear.

**And it is all or nothing on the disk.** `write_file` allocates the
replacement before it frees the original (§1.10), so a slot that runs the disk
out of blocks stops part way -- and a disk carrying three of six characters is
the state this function exists to refuse, arrived at by a different route.
`write_por_slot` snapshots the image before the first write and
`AmigaDisk.restore` puts it back on any failure.

`goldbox.amiga_adf.AmigaDisk.make_dir` was added for this, and only for the
tests: production writes into the `save` drawer of a copy of the player's own
game disk, which is already there, but a blank disk this module formats has no
drawers at all and `tests/test_amiga_adf.py`'s no-game-data property is worth
more than the twenty-five lines.

### 1.14 The Curse and Silver Blades square regions, lined up (#28 (Decode an Amiga saved game, not just a character file))

§1.7 left three things open and all three fall out of one observation: **after
the coordinates, Amiga Curse's square region and Amiga Silver Blades' are the
same nineteen bytes.**

```
             x        y      facing  |  seven bytes    | u16be |  eight bytes            | u16be
DOS  both    07       0d     00      |  00 00 00 00 00 00     01 00   ff ff ff ff ff ff ff ff   06
AMI  Secret  07       0d     00      |  00 00 00 04 00 00 00 | 00 01 | ff ff ff ff ff ff ff ff | 00 06
AMI  Curse   00 03    00 0e  02      |  00 00 00 04 02 00 01 | 00 01 | 00 02 00 02 00 03 00 03 | 00 04
```

The two DOS shipped saves are **byte-identical** through the whole region --
`07 0d 00`, six zeros, `01 00`, eight `FF`, `06` -- which is what makes this a
diff rather than an inference. Three things agree across the two Amiga titles
independently: the `04` at the fourth byte of the seven, the `u16be` 1, and the
party size at the end.

**The party size is a `u16be` on both**, 6 and 4, and each is confirmed
independently by `$503E` in its own file and by the number of character records
that follow. That settles the reading §1.7 downgraded to PROBABLE for Curse:
`00 04` at `0x3217`-`0x3218` is the party size.

**Silver Blades' inserted byte is at `0x1407`, and the `04` is it.** §1.7 asked
which of two facts explained the other -- one byte inserted somewhere in
`0x1404`-`0x140a`, and a `04` at `0x1407` where DOS has `00`. **They are the
same fact.** Both Amiga titles carry a `04` at that position of a seven-byte
block where both DOS titles have six zeros, and one of those Amiga saves is at
the start of the game in the same state as the DOS file it is being diffed
against. PROBABLE, two titles. It is a field with a non-zero initial value, not
a pad -- every pad measured in this family is zero (the record's `0x07F` 20 of
20, the item's `0x03B` 17 of 17, the `.spc` pad 68 of 68).

**Curse's ECL buffer is 7680, not 7684.** CONFIRMED, three independent grounds:

* §1.11 read `3,14 E` off the status line and the file holds x at `0x3201` and
  y at `0x3203`. A 7684-byte buffer would run to `0x3204` and swallow both;
* `ECL.GLB` **block 1** is what fills the buffer -- 7622 bytes matched from
  `0x1401`, then **58 zero bytes ending exactly at `0x3200`**, which is
  `0x1401 + 7680`;
* the nineteen-byte match above only works with the square region starting at
  `0x3201`.

**And the `ECL.GLB` block 0 coincidence is a coincidence.** §1.7 flagged that
`0x320b`-`0x3218` reads `00 01 00 01 00 02 00 02 00 03 00 03 00 04`, which is
bytes 2-15 of block 0. It is -- and it is exactly fourteen bytes with a
mismatch immediately on **both** sides: block 0 opens `00 19` where the save
holds `04 02`, and continues `00 04 00 10 00 05` where the save's next byte is
the `G` of `GALAIN`. A buffer copy does not end at both edges of a
fourteen-byte window. Under the alignment above those fourteen bytes are four
separate fields, and the last two are a party size `$503E` gives independently.
A table of ascending pairs matches any block of small ascending numbers.

**The grouping above was wrong, and the save routine says what the bytes
are** -- [`165-amiga-savegame.md`](165-amiga-savegame.md). After the square
struct come the game mode before the current one (the `04`), the game mode,
then **three (WALLDEF block, slot) `u16be` pairs**: the "`u16be` 1" is entry
1's slot number and the "eight bytes" are entries 2 and 3, `$FFFF` when
empty, which is what both titles' new-game initialisation writes. Nothing in
the region is open.

### 1.15 The item record's remaining bytes: they were never fields (#28 (Decode an Amiga saved game, not just a character file), #55 (Decode the Amiga Curse and Silver Blades records))

**Amiga Curse's `0x03B` = 52 and `0x03E` = 47 are padding, and so is the `7F`
at `0x028`.** The item constructor at `/Curse` `0x1C1EA` allocates the node,
clears all 66 bytes and writes fifteen named fields into it, and none of the
three is among them; `charges` is at `0x03F` and reads zero on all nine.
[`166-amiga-records-from-the-code.md`](166-amiga-records-from-the-code.md).

The nine specimens hold the same three values because they came through the
other path -- the `ITEM<n>` template loader at `0x1F2D6` unpacks each 63-byte
template into a stack struct it never clears and copies all 66 bytes into the
node, so one uninitialised stack frame is copied nine times.

This section used to say the corpus was exhausted and that only an Amiga Curse
item with a charge count could settle it. Two things it recorded stand and
were the clue: the values are **Curse's, not the family's** -- the same two
offsets read zero in all seventeen Amiga Pool of Radiance nodes -- and
**neither is a trait id that makes sense on a weapon or a suit of armour**,
47 being the dwarf's armour-class bonus against giants and 52 *held or
paralysed* in `goldbox/traits.py`'s namespace. Both are what a byte nobody
writes looks like.

**Amiga Pool of Radiance's own pad window, `0x035`-`0x037`, cannot be placed
from files either**, and now for a measured reason rather than an unexamined
one: `hidden` and `cursed` read **zero in all seventeen** nodes, so there is
nothing to align the window against. `readied` at `0x034` is CONFIRMED (§1.9),
which fixes the window's left edge and no more. A 68000 compiler pads
immediately before the field that needs the alignment, which puts the pad at
`0x037`, in front of the `u16` weight at `0x038` -- the same inference that
places the record's own second insertion at the end of its window (§1.12), and
the same grade: an inference, not a probe.

### 1.16 The `.pc` loader, read (#148 (The Amiga port's tools are gone, and phase 1 still needs the disassembler), phase 1)

**Phase 1 is done.** `tools/m68dis.py` was written for this and the routine was
read in the Amiga *Pools of Darkness* executable. The disassembler was checked
against capstone 5.0.7 in `CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000` over 100 385
instructions of this same binary before any of the below was written down —
`docs/50-experiments.md` §"The 68000 disassembler" has the counts and why the
mode is part of the claim. The answer the phase asked
for, in one line: **the loader reads 404 bytes, then twenty bytes per item,
then ten bytes per effect, and the only thing it checks is that each of those
reads returned the length it asked for — plus one signature byte, `'I'`, on
every item record.** There is no check on the file's length and none on the
character record itself.

The entry point is `pcload(char *name, character *dest)` at file offset
`0x25BAE`. It copies the name, parks `dest` in a global, and hands the work to
the engine's open-and-retry harness (`0x3F874`) with the disk code `$53`
(`'S'`, the save disk), the mode `0` and a **callback** at `0x25806`:

```
00025bae  link    a5,#-$2a
00025bb2  move.l  $8(a5),-(a7)          ; the file name
00025bba  jsr     -$7416(a4)            ; strcpy into a local
00025bbe  move.l  $c(a5),-$31da(a4)     ; the destination record, into a global
00025bc4  pea     $25806(pc)            ; the callback that does the reading
00025bce  move.w  #$53,-(a7)            ; 'S' -- the save disk
00025bd2  jsr     -$771c(a4)            ; open, retry, call back, close
```

The harness builds `DF0:SAVE/<name>` (the literals at `0x3F868`), opens with
AmigaDOS `Open` and `MODE_OLDFILE` (`$3EE`) through the glue at `0x45AC2`, and
calls the callback as `callback(word handle, char *path)`. Every read goes
through `0x460CC` to dos.library `Read` at `-42(a6)`. So the `Open`/`Read`
pair is real AmigaDOS and not a private loader.

**What the callback reads, in order:**

| # | length | into | how many |
|---|---|---|---|
| 1 | **404** (`$194`) | the character record at offset 0 | once, always |
| 2 | **20** (`$14`) | one item node each | the longword at record `+0x08` says how many |
| 3 | **20** (`$14`) | one scroll node each, chained off the item | the item's own byte at `+0x0C` says how many |
| 4 | **10** (`$0A`) | one effect node each | while the previous record's longword at `+6` is non-zero, starting from the longword at record `+0x04` |

**What it checks:**

* **Every read is length-checked.** `cmpi.w #$194,d0` after the first,
  `cmpi.w #$14,d0` after each item, `cmpi.w #$a,d0` after each effect. A short
  read sets the failure flag, the nodes already allocated are freed, and the
  routine returns 0.
* **One signature byte, and it is on the items, not the character.**
  `cmpi.b #$49,$2e(a2)` — the first byte of every 20-byte item record must be
  `$49`, ASCII `'I'`. An item that is not `'I'` ends the list.
* **A capacity check.** Item count plus scroll count must stay within `$78`
  (120); over that, the remaining records are read into a scratch buffer and
  thrown away and the player is shown `SCROLLS DROPPED!`.
* **Nothing else.** No file length, no magic on the character record, no
  checksum. That is the same answer §2.2 got by experiment when a 582-byte C64
  export loaded, and this is why.

**This corrects §1.1 and §4 on where 484 comes from.** The record proper is
**404 bytes**, not 484, and 484 is 404 plus four 20-byte item records. The
arithmetic accounts for all four sizes seen on disk 3 and for §1.5's reading
of `0x08`:

| file size | = 404 + | and `0x08` reads |
|---|---|---|
| 484 | 4 × 20 | 4 |
| 504 | 5 × 20 | 5 |
| 514 | 5 × 20 + 1 × 10 | 5, with `0x04` non-zero |
| 524 | 6 × 20 | 6 |

CONFIRMED from the code; the match to the twelve files is PROBABLE until
somebody re-reads them, and the experiment that settles it is one line: the
514-byte file must hold 5 at `0x08` **and** a non-zero longword at `0x04`.

`goldbox.amiga.PodWriter` is unaffected — it leaves `0x04` and `0x08` zero, so
PoD reads its 404 bytes, finds no items and no effects, and never touches the
80 zero bytes after them. Those 80 bytes are harmless padding rather than a
length the game requires, and `RECORD_LENGTH = 484` says otherwise in a
comment; see `#154 (goldbox/amiga.py says 484 is the shortest record Pools of
Darkness will read, and 404 is)`.

**Two of the three `pc` literals in §1.2 were attributed to the wrong sites**,
and `tools/m68dis.py --refs` says so — each literal is referenced exactly once
in 316 KB of code:

| literal | referenced from | what that routine is |
|---|---|---|
| `0x255B2` | `pea $255b2(pc)` at `0x25568` | the **picker**: builds the list of `*.pc` on the save disk, and prints `No characters to load.` / `No characters to delete.` when it is empty |
| `0x25802` | `pea $25802(pc)` at `0x257DC` | **delete**: builds `NAME.pc` from the record's name at `+0x60` and calls dos.library `DeleteFile` |
| `0x265A2` | `lea $265a2(pc),a2` at `0x26476` | **save**, including the `Update %s?` / `New file name:` prompts |

The loader references none of them: `pcload` is handed a name the picker
already built.

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
| P3 | a 484-byte record built by `goldbox.amiga.PodWriter` from named fields and nothing else | every field back: `WRITTEN`, `FEMALE 33 YEARS`, `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`, `HIT POINTS 55/77`, `EXPERIENCE 10000`, `STR 18 INT 17 WIS 16 DEX 15 CON 14 CHA 13`, `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`, `STATUS: OKAY` |

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
`CHEAD.TLB` for item −1: `0x0B6`–`0x0C7` holds a portrait selector, not
inventory. **Zero there is accepted** — every payload that loaded had
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

**Prefer the `Secret` route** now the disks are here: writing a Silver Blades
`.sav` and letting PoD convert it is strictly less for us to get right than
writing a PoD-legal `.pc` ourselves. §1.6 has the record and §1.7 the save.

---

## 4. The three-way field map

C64 offsets from `goldbox/layout.py`. DOS Pool of Radiance offsets from
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
| race | `0x072` — CONFIRMED | `0x02E` — CONFIRMED | `0x02E` — CONFIRMED | `0x058` — CONFIRMED (`HALF-ELF`, `DWARF`). `ELF` 0, `HALF-ELF` 1, `DWARF` 2, `GNOME` 3, `HALFLING` 4, `HUMAN` 5 — a **different table again** from the C64's (`goldbox/games.py`) |
| class | `0x073` — CONFIRMED | `0x02F` — CONFIRMED | `0x02F` — CONFIRMED | `0x059` — CONFIRMED (`THIEF`, `FIGHTER`); 0-based, 17 entries, singles first (§2.4) |
| age | `0x074` u16 LE — CONFIRMED | `0x030` u16 LE — CONFIRMED | `0x030` u16 **BE** — CONFIRMED | `0x052` u16 **BE** — CONFIRMED (`21075 YEARS`) |
| hp max | `0x076` **u16** — CONFIRMED | `0x032` **u8** — CONFIRMED | `0x032` **u8** — CONFIRMED | `0x081` **u8** — CONFIRMED (`HP 0/129`). **Current** hit points are a u16 at `0x190` — CONFIRMED (`HIT POINTS 55/77`) |
| saving throws ×5 | `0x09A`–`0x09E` — CONFIRMED | ~`0x06B` block — PROBABLE | ~`0x06B` block — PROBABLE | `0x083`–`0x087` — PROBABLE; they decode to the AD&D table for each specimen's class and level, and the sheet never shows them |
| level | `0x0A0` — CONFIRMED | UNKNOWN | UNKNOWN | `0x089` — PROBABLE, and it equals the **highest** of the seven class levels in all twelve. It is a maximum, not a sum: `TRIPEL TURBO` is 6/6/12 and reads 12. The sheet draws the class levels, not this |
| per-class levels | `0x0C9`–`0x0D0`, 8 — PROBABLE | UNKNOWN | UNKNOWN | `0x09D`–`0x0A3`, **7** — CONFIRMED (`LEVEL 1/2/3/4/5/6/7`); indexed by the single-class code, so slot 6 is the thief's |
| class bits | `0x0EB` — CONFIRMED | UNKNOWN | UNKNOWN | `0x0B7` — PROBABLE; magic-user 1, cleric 2, thief 4, fighter 8, which is the C64's own numbering, and 13 = 1\|4\|8 for the fighter/magic-user/thief. But **64 for the paladin and the ranger alike**, where the C64 gives them 0x40 and 0x80 separately — so the byte is *not* the C64's and must not be copied. `goldbox/amiga.CLASS_BIT` is the table |
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
| What does writing require? | An OFS writer: bootblock, root block with its hash table and checksum, bitmap block, one dir header, and per file a header block plus data blocks each carrying a 24-byte header and its own checksum. Perhaps 300 lines, and `goldbox/d64.py` is the precedent — this project already writes a container by hand. | PROBABLE |
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
| 1 | ~~**Read the `.pc` loader.**~~ **DONE** (#148 (The Amiga port's tools are gone, and phase 1 still needs the disassembler)). `tools/m68dis.py` was rebuilt for it. 404 bytes, then 20 per item and 10 per effect; AmigaDOS `Open`/`Read`; the only checks are the read lengths and an `'I'` on each item. | §1.16 | no | done | run — see §1.16 |
| 2 | ~~**The assumption test (§2.2), cases A–D.**~~ **DONE.** | A loads; **B loads too** | yes | one session | run — see §2.2 |
| 3 | **An OFS ADF writer.** Round-trip: read every file off disk 3, rebuild an image, compare file contents byte for byte; then boot it in FS-UAE and let PoD list the twelve characters. | `goldbox/adf.py` (writer) with tests that read the player's own disks, never a committed image | yes, once | a week | PoD's `Add Character → Pools` shows all twelve names off our image |
| 4 | ~~**Decode the `.pc` record.**~~ **Done for everything the sheet shows.** The ramp of §2.3 found the numbers; the plausible-value probe of §2.4 found the four enums, current hit points and the seventh level slot. What is left is undecoded rather than blocking: saving throws, thief skills, the class bitmask, the portrait indices and the appended item data. | `goldbox/amiga.py`, plus `tests/test_amiga.py` asserting the ramp offsets, the written record and the twelve real files | yes, repeatedly | done | every named field decodes to a legal AD&D value across all twelve |
| 5 | **Resolve the pointers.** Determine whether the `0x00`–`0x5F` addresses are re-linked on load. Two ways: read the loader (phase 1 may already answer it), or write a `.pc` with those longwords zeroed and see if PoD still loads it. | a ruling: don't-care, or must-be-plausible | yes | a session | a zeroed-pointer `.pc` loads and its sheet is unchanged |
| 6 | ~~**The map and the writer.**~~ **DONE.** `goldbox.amiga.write` takes a `NeutralCharacter` — the one record every codec now shares, since #25 (One neutral character record, with a codec per format) — and `to_pc` emits the 484 bytes. `Report.unaccounted` is empty on every character of the player's own party, so there is no "template" category. `field_disposition()` names what becomes of every neutral field, and `tests/test_amiga.py` fails if a field appears in one and not the other. | `goldbox/amiga.py`, `tools/toamiga.py` | no | done | run |
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

So nobody is surprised, and nobody tries.

| thing | why it cannot cross | what to do instead |
|---|---|---|
| **The combat icon** | C64 `0x220`–`0x243`: 18 screen codes into `CHARPIC00` plus 18 colours. It is a C64 character set. Neither DOS nor the Amiga has anything of the kind. | drop it; PoD draws its own |
| **Portraits** | C64 `0x0FE`/`0x0FF` name `HEADnn`/`BODYnn` files on the C64 disks. PoD's Amiga art is `CHEAD.TLB` / `CBODY.TLB`, a different set with different numbering. | re-choose, do not copy the index. A copied index is a wrong picture, silently. |
| **Derived combat values** | The C64 roster block (`0x10E` THAC0, `0x10F` AC, `0x119` current hp) is a **cache**, and its update rule is not "on load" — armour class refreshes only when equipment changes, so it can be stale even in a healthy save. | recompute for the target from base values, always |
| **Items** | The C64 stores 16 bytes per item, an id into that title's `ITEMNAMES`. DOS and Amiga store 63–65 bytes per item **carrying the name as text**. And a Silver Blades item id and a Pools of Darkness item id are two different games' tables. | re-encode from named fields, and **check the tables agree before assuming any id means the same thing** |
| **Memorised spells** | C64 spell ids run 1–56. Pools of Darkness has cleric spells to level 7 and mage spells to level 9, so its id space is larger and the mapping is certainly not identity. | map by name, or drop and let the player re-memorise |
| **Experience** | The C64 field is **3 bytes** — 16 777 215 maximum. Pools of Darkness characters exceed that. | the target field is wider; carry the value up, and expect a C64-sourced total to look low rather than wrong |
| **Race and class codes** | `goldbox/games.py` already documents that the race table changes per title on the C64 alone (human is 7 in Pool of Radiance, 6 in Silver Blades). PoD's Amiga table has not been read. | read PoD's own table before writing a race byte |
| **Copper, silver, electrum and gold** | only platinum (`0x04C`), gems and jewelry have been located in the `.pc`. R7 was the probe for the lighter coins and did not finish; `0x048` and `0x04A` are zero in all twelve and are the obvious candidates. | reported, with the total, so the player knows what was left on the counter |
| **Armour class and unarmed damage** | not a loss so much as a category error. The C64's numbers already include worn armour and a strength bonus, PoD re-applies dexterity and strength itself, and no item crosses — so a converted character genuinely arrives unarmoured. | write the unarmoured `10` and `1d2`, which is what all twelve genuine records hold, and let PoD derive the rest. §2.5 shows it coming out at `AC 8` and `1D2+1` |
| **Everything Silver Blades knew and Pools of Darkness does not** | quest flags, position, journal entries | not converted, and not wanted — see §3 |

---

## 8. Blockers, honestly

1. ~~**There is no Amiga Secrets of the Silver Blades on this machine.**~~
   **Gone — the disks arrived 2026-08-25**, in
   `work/amiga/goldbox/Secret_Of_The_Silver_Blades/` (both sides, 901120 bytes
   each), and `SecretOfTheSilverBlades_A.adf` carries a shipped saved game at
   `SAVE/savgamA.sav`. The Curse disks and a Curse save disk came with them.
   So the `Secret` import route — the one the game was designed around, where
   PoD does the conversion arithmetic for us — is reachable, and §1.6 and §1.7
   decode the record and the save it wants. What is left is a *technical*
   question rather than a missing disk: whether PoD accepts a `.sav` we wrote.
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
4. ~~**The `.pc` length rule is not derived.**~~ **Answered, and then derived
   from the loader itself in §1.16.** Sizes 484 / 504 / 514 / 524 — and the
   rule is **404 bytes of character record, plus 20 per item and 10 per
   effect**, so 484 is four items rather than "no items". `PodWriter` emits
   484 with the item and effect counts zero, which PoD loads and puts in the
   party: it reads its 404 bytes and never looks at the 80 after them. The
   extra bytes are the item lists, still undecoded, and a converted character
   simply arrives carrying nothing. `ERROR: INVALID ITEM (-1/29)` was never about
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
7. ~~**FS-UAE is not VICE, and no live-memory path exists on the Amiga
   side.**~~ **Half-answered, as of 2026-09-03.** FS-UAE still has no binary
   monitor. But `docs/143-winuae-debugger.md` drives WinUAE from Linux instead
   — boot, halt, memory reads, watchpoints, breakpoints and single-stepping,
   unattended, over `winvm` and `tools/winuae.ps1` — and that path has been run
   for real (`#91 (Configure WinUAE in the Windows VM so an Amiga title can be driven unattended)`), reliably as far as its own §8. What it has **not** been run
   against is *Pools of Darkness* or *Secret of the Silver Blades*
   specifically — everything exercised so far is Pool of Radiance. Phase 4 of
   this plan still does not need it: differential *saves* are files, and the
   emulator is only needed to produce them. A PoD automapper is still a
   separate project and out of scope here, but it is no longer blocked on a
   missing debugger — it is blocked on nobody having pointed this one at PoD.
   Kickstart ROMs are present at `/home/donald/FS-UAE/Kickstarts` (1.3 and 3.1)
   for FS-UAE, and at `C:\Amiga\Kickstarts` in the WinUAE guest, so booting is
   not itself a blocker either way.
8. ~~**Nothing here has been run against a real emulator yet.**~~ Phase 2 has
   run (P51). What has **not** been checked is blocker 6's cross-rip repeat —
   everything observed is on the single untagged rip.

---

## 9. What is explicitly not in this plan

* **Automapping Pools of Darkness.** Donald's story has Wish mapping all four
  games, and it also needs a `GLIB` container reader for `GEO.GLB` and
  `ECL.GLB`. **As of 2026-09-03 the live-memory path itself is no longer
  missing** — `docs/143-winuae-debugger.md`'s WinUAE debugger reads, halts and
  single-steps a running Amiga title — but nobody has pointed it at PoD, so
  what memory it would read there is unmeasured. It is still a separate
  document. Note one encouraging fact for whoever writes it: PoD's `GEO.GLB`
  is 33 050 bytes for the whole game, so the map family is small.
* **Amiga → C64.** One direction only, as with `117-save-conversion.md`. No
  C64 Pools of Darkness exists, so there is nowhere to go back to.
* **Writing a `.pty` or a `Vault?.DAT`.** §3.
