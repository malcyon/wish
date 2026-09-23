# Porting a C64 party into Amiga Pools of Darkness — plan

**Status: it works end to end.** A character out of the player's own C64
*Pool of Radiance* save disk now converts to a `.pc`, and Amiga *Pools of
Darkness* loaded it, put it in the party and drew a sheet that matches the C64
one field for field -- see §2.5. `goldbox/amiga_pod.py` is the whole converter and
`tools/amiga/toamiga.py` is how it is invoked.

**Phase 4 is done for every field the character sheet shows, and the
writer works.** Amiga Pools of Darkness **accepts a C64 Pool of Radiance
export** as a `SAVE/NAME.pc` and puts it in the party — no length check, no
signature check, and the `0x00`-`0x5F` heap-address block is don't-care. So the
record was decoded by *writing* one and reading the sheet, and it is now
written the other way round: `goldbox.amiga_pod.PodWriter` emits a **484-byte record
built from named fields alone**, and PoD drew every one of them back —
`WRITTEN`, `FEMALE 33 YEARS`, `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`,
`HIT POINTS 55/77`, `EXPERIENCE 10000`, `STR 18 INT 17 WIS 16 DEX 15 CON 14
CHA 13`, `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`, `STATUS: OKAY`.
§2.3 and §2.4 have the probes; `goldbox/amiga_pod.py` and `tests/amiga/test_amiga.py` carry
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

`amiga/adf.py` (scratch, deleted) reads all of it today with no change. **The `.dax` /
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
fourteen specimens (#27 (Decode the Amiga Pool of Radiance record, so a shared title exists)) and reproduced by `goldbox.amiga_por.amiga_por_offset`:

1. one pad byte at `0x07F`, ahead of the effect pointer — zero in 14 of 14,
   and it is there because the Amiga keeps one `u32` where DOS keeps an
   offset word and a segment word, so a 68000 compiler even-aligns it;
2. one pad byte at **Amiga `0x089`**, between `field_83_87` and the `u16`
   money block. This said "inside DOS `0x083`-`0x087`, located to a window
   and not to a byte" until the two engines were read: no file differential
   could place it because the region is zero in 12 of the 14, and §1.21 has
   the reading that did — `field_83_87` is Amiga `0x084`-`0x088` at the `+1`
   shift, so the pad is the byte after it;
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
| `0x7C`–`0x7D` | `00 00`, `32 32`, `00 00` | **exceptional strength**, a pair of equal halves in all 19 specimens — matches DOS PoD `0x1C`–`0x1D` `43 43`. Byte 0 is the percentile in force and byte 1 the permanent one, **inferred from the later titles** (`goldbox.dos_codec._ability_pair`); no Amiga specimen tells the halves apart | PROBABLE (the pair itself CONFIRMED) |

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

Five Amiga disks arrived on 2026-08-25 and are in the
`Curse_Of_The_Azure_Bonds/` and `Secret_Of_The_Silver_Blades/` folders of the
`amiga` registry entry: two Curse of the Azure
Bonds game disks, a Curse **save disk**, and two Secret of the Silver Blades
disks. `goldbox/amiga_adf.py` walks them, finding the root block by scanning
because the save disk is 1804 blocks rather than 1760, and
`tools/amiga/amigarecords.py` is what pulls the specimens out -- twenty-one of them,
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
where the pregens are not. It is `CURSE_DELTAS` in `goldbox/amiga_port.py`, which
reads `goldbox/dos_port.py`'s Curse table through it rather than restating
it, and `tools/amiga/amigarecords.py` produces the specimens.

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
what `goldbox/dos_port.py` calls `field_83_87` and does not name, which is a
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
`goldbox/dos_port.py`'s Silver Blades table decode to the byte-for-byte
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
Silver Blades records hold race 6, which `goldbox/dos_port.py`'s
`RACE_NUMBERS` called `half-orc` -- but Guy de Valois is a paladin and
MORGAINE is a magic-user, and AD&D allows a half-orc to be neither. **Silver
Blades has its own race table**: `tribble`, `elf`, `half-elf`, `dwarf`,
`gnome`, `halfling`, `human`, `monster`, so 6 is `human`. CONFIRMED, read out
of the title's own `START.EXE` by `tools/dos/dosraces.py` and corroborated by Gold
Box Companion's per-title data (#237 (The DOS race table is one table for four titles, and it is wrong for two of them)); it is `DosDeltas.race_numbers` now, and
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
uncompressed** — the bit-cruncher in `amiga/dax.py` (scratch, deleted) fails on 25 of ECL.GLB's 26
and yields 3 bytes of garbage from the last. §1.1's container work is for the
Pool of Radiance `.dax` archives and does not apply. `amiga/goldbox/glib.py` (scratch, deleted)
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
file-internal consistency. `goldbox.amiga_por.AmigaPorCharacter` reads the DOS field
table in `goldbox/dos_port.py` through `amiga_por_offset`, big-endian; there is
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

`tests/amiga/test_amiga.py` pins those numbers, and reads its specimens from a
directory named by `$AMIGA_POR_SAVES`, skipping without one.

**A DOS-side consequence.** `movement_current` at DOS `0x11C` is PROBABLE in
`goldbox/dos_port.py`; the Amiga's counterpart is drawn on the sheet as
`MOVEMENT 9` beside a base of 12, which settles the field and independently
refutes the third-party claim that the byte is an AD&D class group (#59 (Map the DOS saved game, not just the character record)).

### 1.9 The Amiga Pool of Radiance item and effect files, and the neutral bridge (#27 (Decode the Amiga Pool of Radiance record, so a shared title exists))

The record was only two thirds of the reader. `CHRDATA<n>.itm` and
`CHRDATA<n>.spc` beside it hold the gear and the innate effects, and both are
now decoded — so `goldbox.amiga_por.to_neutral` turns an Amiga character into
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
DOS `.ITM` files in `dos-saves` (scratch, deleted) carry ` No   Long Sword +1 `,
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
`00 00 FF 00` — exactly `goldbox/dos_codec.py`'s `INNATE_PAYLOAD`, which is DOS's bytes
1-4. So the pad is at 1 and everything after it is DOS's four payload bytes
and four pointer bytes in order.

**The neutral bridge is a transposition, not a second codec.**
`goldbox.amiga_por.to_dos_record` re-cuts the 288 bytes into the 285 `goldbox/dos_codec.py`
already reads, and `goldbox.dos_codec.to_neutral` does the rest — so every grade, drop
and provenance line the DOS side earned on 24 specimens carries over, and
there is no second bridge to drift. Four rules and nothing else: the name is
re-cut from 16 NUL-padded bytes to a count and fifteen; `u16` and `u32` fields
are byte-swapped; experience is one Amiga `u32` where DOS keeps a four-byte
`u32le`; and the two live heap pointers — the effect chain and each
item's `next` — are written NULL rather than converted.

**One region is reported rather than guessed:** the Amiga's trailing byte at
`0x11F`, which has no DOS home, and the report names it. DOS `0x083`-`0x087`
was written zero here too while the second insertion was unplaced inside it;
it is placed now (§1.21), so `field_83_87` is transposed like any other field
and a companion's control byte crosses.

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
6. **movement is the number keys `4`, `6`, `8`** — `8` forward, `4` and `6`
   the two turns, re-measured on 2026-09-07 across eleven steps and confirmed
   with `joyport1=none` in the config, so it is the title rather than the
   emulator eating the alternatives. This build has no console.device, no
   gameport.device and no keymap patch, which is why the numeric keypad the
   two later titles use does nothing here; the arrows did nothing in the
   original run and that run predates the `joyport1` fix, so **whether an
   arrow key reaches this title is untested** rather than answered.
   **Outdoors the same `8` steps north**: overland movement is absolute and
   the facing shown is the direction of the last step;
7. saving — **`E`** ENCAMP, **`S`** SAVE, the slot letter, RETURN, then
   **`N`** to `QUIT TO WORKBENCH  YES  NO`. It works on the travel grid as
   well as indoors, which had been an open question
   (`docs/113-world-map.md`).

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
`amiga/p36/shots/slotb-final.png` (scratch, deleted).

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

**The rest of the route, driven on 2026-09-05** for
`docs/165-amiga-savegame.md`'s run: `LOAD WHICH GAME:` offers **the letters it
found in the `SAVE` drawer** -- `A B C D` on a disk carrying four -- where
`SAVE WHICH GAME:` offers ten regardless; `BEGIN ADVENTURING` is `B`; the
adventuring bar is `AREA CAST VIEW ENCAMP SEARCH LOOK`, so `V` opens the first
character's sheet, `I` his items, and `E` backs out of each; `ENCAMP` is the
same `E` from the bar, then `SAVE`, the slot letter, RETURN, and finally
`EXIT GAME  YES  NO`, answered **`N`**. **Movement was still not found** -- the
`4`/`6`/`8` that work in Pool of Radiance do nothing, and neither do the arrow
keys -- and nothing in that run needed a step.

### 1.11a Amiga Silver Blades, read on screen (#28 (Decode an Amiga saved game, not just a character file), #331 (Amiga Silver Blades asks a journal word before it will adventure, so the title cannot be driven past its party menu))

**The route in, as far as it goes**: the title painting takes **RETURN**, the
version screen another; the `PLAY / DEMO / QUIT` bar takes **`P`** and, like
Curse's, ignores RETURN; the party menu picks by first letter throughout, and
`LOAD WHICH GAME:` offers the letters it found with no path prompt.
`SAVE CURRENT GAME` is `S` on that menu and is enabled once a party is loaded,
which is how the run got an engine-written saved game without adventuring.

**`BEGIN ADVENTURING` asks a copy-protection question**, on a screen of its own
with an `ENTER` field: it names a word number, a journal entry and a page of
the printed Adventurer's Journal, and a bare RETURN is refused. **PROBABLE,
one observation**: the same word, entry and page stay on screen afterwards
rather than a new challenge being drawn, so a misread costs a retry rather
than a reboot -- pressed once, at the prompt whose misread
`#371 (The Silver Blades journal reader misreads a 6 as an 8, so a boot is
spent on a question the disk can answer)` diagnoses, and not reproduced since.
ESC has not been tested against this. This **corrects an assumption taken
from the C64**, whose release here
never asks because its check is dead code: the two rips are different and one
port does not predict another, which is the lesson `#108 (Amiga Curse asks
its code wheel, so the title cannot be driven unattended)` taught on Curse.

**The prompt is answered and the title is drivable, as of 2026-09-06.**
`tools/amiga/amigabladesjournal.py` reads the challenge off the guest's screen and
types the word. The screen reader samples each Amiga pixel's own centre out
of the capture and hands the private repository's reader a whole number of
pixels per Amiga pixel, rather than resampling to its declared fractional
pitch -- `#371 (The Silver Blades journal reader misreads a 6 as an 8, so a
boot is spent on a question the disk can answer)` has the fault that left and
the measurements that settled it. **Run it with `/usr/bin/python3`**: it
reaches into the private repository, which imports `numpy`, and this
project's virtual environment has none.
Neither the challenge nor the word is recorded anywhere here, per
`#108 (Amiga Curse asks its code wheel, so the title cannot be driven
unattended)`'s ruling; what the tool prints is `answered` or `no challenge on screen`.

**The whole route, from a cold boot to a party standing in the world**, is
RETURN past the credits, `P`, `L`, the slot letter, `B`, and then the tool.
Timings on this machine: 47 s to the credits, 39 s to the version screen, 9 s
to the party menu, 13 s to the load prompt, 13 s to a loaded party, and 56 s
from `B` to the challenge -- so a key pressed on a fixed delay lands in the
middle of a load and is swallowed, and every step here waited for the screen
to stop changing instead.

**`EXIT GAME` does not go back to the party menu.** Answering its `YES` quits
to AmigaDOS with `Please re-boot your system.`, so a second run through the
prompt costs a WinUAE restart. Curse's answer of `N` in §1.11 keeps the party
in play; there is no `N` route back to the roster on this title.

**Movement is the numeric keypad, and the emulator was eating it.** This
paragraph used to read "movement is not a key, and that is now measured rather
than suspected", on the strength of twenty virtual keys pressed at the
adventuring bar on 2026-09-07 with the party at `5,9 W 00:00` -- the four
arrows (VK 0x25-0x28), the numeric keypad (0x60, 0x62, 0x64, 0x66, 0x68, 0x6B,
0x6C), the top-row digits (0x32, 0x34, 0x36, 0x38) and `I`, `J`, `K` -- none of
which changed the square or the facing. The presses were real and the reading
of them was wrong: **`tools/amiga/goldbox-a500.uae` set no `joyport` line, so WinUAE
gave Amiga port 2 its default "kbd1", which is Keyboard Layout A, which
consumes `DIK_NUMPAD4`, `6`, `8`, `2`, `0`, `5`, `DECIMAL` and `NUMPADENTER`
for a joystick.** Eight of the twenty keys reached that layout and no further
(`keybd_event` gives `VK_UP` the unprefixed scancode 0x48, which is
`DIK_NUMPAD8`, so the "arrows" were keypad keys too); the top-row digits and
`I`, `J`, `K` are not movement in this title and did nothing for that reason.
`joyport1=none` and the party walks -- §1.11b.

**The attract loop runs on its own timer, and a screenshot is too slow to
aim a key at it.** From the credits the title reaches a `PLAY DEMO QUIT` bar
and, if nobody answers within a few seconds, starts the DEMO -- a scripted
party in a fight, which looks enough like the game to be mistaken for one. A
grab costs two to four seconds through `winvm shot` and a keystroke another two
to three, so a key aimed at what the last grab showed lands after the bar has
gone: six of one session's keystrokes went nowhere that way on 2026-09-08. What
works from anywhere in the loop, as one `tools/amiga/amigadrive.py` call so the keys
are about two seconds apart:

    tools/amiga/amigadrive.py --holder <lane> --settle 0.2 keys ESC RET

`ESC` leaves the demo for the bar and `RET` takes the bar's highlighted `PLAY`.
Then `L`, the slot letter and `B`. **Run `tools/amiga/amigabladesjournal.py` under
the system `python3`**, not the project's virtual environment: it reaches into
the private code-wheel repository, which imports `numpy`, and the virtual
environment has none -- the failure is a `ModuleNotFoundError` out of a file in
the other repository, which reads like that repository being broken.

**A saved game made from inside the world now exists**, which is the specimen
`#28 (Decode an Amiga saved game, not just a character file)` could not reach: `~/wish-specimens/ssb-amiga/WISH-SPEC-ssb-amiga-adventuring/savgamB.sav`,
written by `ENCAMP > SAVE > B` at square 3,3 facing South. It is **7233 bytes
against the 6553** of the four-character saves in
`WISH-SPEC-ssb-amiga-resave`, and 7233 − 6553 = 680 = 2 × 340, which is two
more characters at the 340-byte in-save block §1.6a measured -- an
independent corroboration of that block size from a file neither of us cut.

### 1.11b Walking an Amiga party (#361 (An Amiga party cannot be made to walk, because the WinUAE driver sends only keystrokes))

**An Amiga party took its first step on 2026-09-07**, in Silver Blades, and the
status line read it out: `5,9 E 00:00` → `6,9 E 00:01`. Everything below is
that run and the code it was predicted from.

**How the later titles read a direction, out of the executable.** Curse and
Silver Blades do the same thing in the same order, and neither reads a
joystick or a mouse for it:

* each asks console.device for the current keymap (`CD_ASKKEYMAP`), copies the
  256-byte low keymap into a buffer of its own, and rewrites the entry of ten
  keys -- Amiga rawkeys `$0F`, `$1D`-`$1F`, `$2D`-`$2F`, `$3D`-`$3F`, which are
  **numeric keypad 0 to 9** -- so that each returns `$B0` + its digit, shifted
  and unshifted alike, and installs it with `CD_SETKEYMAP`. The originals are
  kept so they can be put back; read in the running game they are `'0'`-`'9'`,
  which is why an unpatched keypad is indistinguishable from the top row;
* the key translator turns `$B0`-`$B9` into the codes `$100`-`$109`, and turns
  a `CSI A`/`B`/`C`/`D` sequence -- what console.device makes of the four
  **cursor keys** -- into `$108`, `$104`, `$102`, `$106`, the same four values.
  So the keypad and the cursor keys are two spellings of one thing;
* the step routine switches on the facing byte and adds ±1 to x or y with
  wraparound at 0 and 15, then recomputes the two bytes after the facing: the
  square's own attribute from `(x, y)` and the wall in front from
  `(x, y, facing)`. Those five bytes are consecutive globals and are the
  saved game's square block at `0x1401` in file order.

Curse and Silver Blades each also carry a complete gameport.device reader --
unit 1, which is Amiga port 2, opened `GPCT_ABSJOYSTICK` with triggers on both
key edges and on one unit of movement, with a 3×3 table turning
(`ie_X`, `ie_Y`) into a direction. **It is never called.** The routine that
opens the device has no caller anywhere in either executable, and the flag it
would set reads 0 in the running game with a party standing in the world. So
the joystick is compiled in and inert, and the compass in the corner of the 3D
view is a drawing rather than a control.

**What the emulator was doing to it** is in §1.11a and in
`tools/amiga/goldbox-a500.uae`: WinUAE's default gives Amiga port 2 the numeric
keypad as a joystick, which swallowed every movement key before the Amiga saw
it. `joyport1=none` stops that.

**And `sound_output=none` deadlocks Silver Blades on the second turn.** With
Paula's emulation off altogether, the first turn drew, the second wrote the
new facing into the game's own byte and never redrew, and from then on nothing
was read: the `Secret` process sat in Exec's `Wait` on a single signal, with
the next keypress still sitting unread in its console buffer. That is not a
game bug and not a wrong key -- it is an emulator setting, and
`sound_output=interrupts` (silent on the host, Paula's interrupts emulated)
fixes it. Eight turns and three steps in a row afterwards, every one drawn.

**The measured vocabulary**, at square 5,9 of Silver Blades' opening area:

| key | what it did |
|---|---|
| numeric keypad `8` | one square forward, and the clock one minute on |
| numeric keypad `2` | about face -- East to West on the spot |
| numeric keypad `4` | turn left -- West to South, South to East, North to West |
| numeric keypad `6` | turn right -- West to North |
| cursor **up**, sent extended | one square forward, exactly as keypad `8` |

The cursor keys need `KEYEVENTF_EXTENDEDKEY`, which is `winuae.ps1 key
<vk> -Extended` and is what `tools/amiga/amigadrive.py` sends for `UP`, `DOWN`,
`LEFT` and `RIGHT`. Without it `keybd_event` hands `VK_UP` the unprefixed
scancode `0x48`, which is `DIK_NUMPAD8` -- so before this the driver had no
way to press a cursor key at all, and its `UP` was keypad `8` under another
name.

**The step diff, which no Amiga title had.**
`~/wish-specimens/ssb-amiga/WISH-SPEC-ssbwalk` holds three engine-written
saves of one party: `savgamD.sav` as it was loaded, `savgamE.sav` one square
east, `savgamF.sav` one step back. **E and F differ in 7 bytes of 7233:**

| offset | E | F | what |
|---|---|---|---|
| `0x190` | 2 | 3 | the clock's minute-units word, `$49C7` |
| `0x20c` | | | `$4A05`, the per-script scratch |
| `0x27a` | | | `$4A3C`, a quest flag |
| `0xef4` | | | `$5079`, one of the words the engine rebuilds by itself |
| `0x1401` | 6 | 5 | x |
| `0x1403` | 2 | 6 | facing, doubled: East then West |
| `0x1404` | 0 | `0x0c` | **the wall in front**, and this is the first time it has been seen to move |

Nothing else in the file changes across a step -- not the map, not the wallset
table, not one byte of any character record. `0x1404` was the field
`#361 (An Amiga party cannot be made to walk, because the WinUAE driver sends
only keystrokes)` named as unreadable without a step, and the code says what it
is: the value the step routine computes from `(x, y, facing)` and stores in the
byte after the facing.

### 1.11c Reading a running Amiga, and drawing its map (#37 (Automap the Amiga version, not just the C64))

**The automapper's two inputs are both live on the Amiga since 2026-09-08.**
`automap/amiga.py` is the backend and `docs/143-winuae-debugger.md` §10 has the
transport, the costs and how the base is measured. What belongs here is what
the *game* holds.

**Every address is an offset into the title's data hunk**, and the hunk's own
load address is measured at run time because AmigaDOS relocates on every
`LoadSeg`. Measured bases, both in slow memory: `/Curse` at `$00C4E270` and
`/Secret` at `$00C55CE0`, each on its own boot.

| | Silver Blades | Curse | width |
|---|---|---|---|
| x, y, facing | `g57a0`, `g57a1`, `g57a2` | `g3f5e`, `g3f60`, `g3f62` | 1 byte / `u16be` |
| the wall type ahead, the square's attribute | `g57a3`, `g57a4` | `g3f63`, `g3f64` | |
| **a pointer to the resident 1024-byte `GEO` block** | `g7bf8` | `g5eb6` | `u32` |

The pointer is the new one. Both map-indexing routines -- Silver Blades
`0x3b78c` and `0x3b8a6`, Curse `0x37a22` and `0x37b3c` -- do
`movea.l d16(a4), a0` and then index `16*y + x`, `+$100` and `+$200` off it, so
the map moves with whatever the loader allocated and the global is the only
fixed thing. CONFIRMED from the code on both titles.

**The step diff, live.** A six-character Silver Blades party at `6,9 E 00:02`
took one `NP8` and read `7,9 E 00:03`. The eight bytes at `g57a0` went
`06 09 02 00 80 00 00 2a` to `07 09 02 0c 86 00 00 2a`, and the 1024 bytes the
pointer led to did not change at all. `geo[$200 + 16*9 + 7]` is **134** and the
stored attribute became `$86`, which is 134 -- so the engine recomputed the
byte from that block, which is what makes the two addresses check each other
rather than merely both being plausible.

**The buffer is allocated before an area is loaded into it.** At the party menu
after `LOAD SAVED GAME` the pointer already held an address and the 1024 bytes
there were all zero, while the party globals already held
`06 09 02 00 80` -- the first five bytes of `savgamE`'s square block at file
offset `0x1401`, byte for byte. So the file's square reaches the globals as the
load finishes, and a null-or-zeroes map has to be told from a real one.

**The map identifies itself against the disk.** `automap.area.ResidentGeo`
matched the live block to `GEO` id **16**, uniquely, among the 17 blocks of
`/DISK2/GEO.GLB` -- the id both engine-written Silver Blades saves carry at
`$49C5`. The block reciprocates 480 of 480.

**The whole walk, through the shipped automapper.** On 2026-09-08 the same
party walked `GEO10` while `automap.state.Automapper.poll()` watched: a turn
(`NP2`, East to West), a step west to (5,9), and a step the map says is
impossible -- `GEO10` walls (5,9) to the west, the game refused it, and the 3D
view drew a wall dead ahead with the status line still reading `5,9 W 00:04`.
The mapper named the area on every poll, moved its marker on the turn and the
step and not on the refusal, and held its fix while the shop's own
`DEPOSIT WITHDRAW TRADE EXIT` bar was up. A poll costs 10-22 s, or 31-50 s on
the polls that re-read the map block.

**The clock is not in the data hunk, and the saved game's array is resident.**
PROBABLE, one boot. All 36,736 bytes of `/Secret`'s data hunk were dumped at
four consecutive polls across a step that moved the status line from `00:03` to
`00:04`, and no byte or `u16be` in it moved with the clock. Two whole-machine
dumps of the A500's 512K of slow memory one step apart hold **exactly one** byte
that goes 4 to 5, and it is the low half of a `u16be`: the saved game's own
`$49C7`, in a resident copy of the `$49xx` array stored as **`u16be` words, one
per DOS byte**, exactly as the file stores it. `$49C5` there reads 16 -- the
`GEO` id `ResidentGeo` had just named independently -- `$49E6` reads 1 for
indoors and `$49F2` reads 16 for the area. The array's base was `$00C60540` on
that boot, and two data-hunk globals, `+0x5160` and `+0x8F30`, hold
`$00C60038`, which is the base minus `$508`; read live back through the first
of those the words agreed with the screen again. **What would confirm it is one
more boot**: re-derive the hunk, dereference `+0x5160`, and check `$49C5`
against the map the mapper names and `$49C7` against the status line. Nothing
reads any of it -- `automap/amiga.py` records the two numbers in the layout's
`notes` and leaves `Fix.clock` None, because the clock's only consumer,
`Automapper._refused`, requires both fixes to come from a status line this
backend never reads.

**Pool of Radiance is not covered.** Its Amiga build is a many-hunk executable
with absolute relocations rather than a small-data one, so there is no single
base to find; §1.9 and `docs/165-amiga-savegame.md` put its party struct at
`h32+0x176f`, and reaching it live needs hunk 32's load address.

### 1.12 Writing an Amiga Pool of Radiance character (#105 (Write an Amiga Pool of Radiance character, not just a Pools of Darkness one))

The reader landed in §1.8 and §1.9; this is the other half, and it is the same
transposition run backwards. `goldbox.amiga_por.write_por` takes a `NeutralCharacter`,
hands it to `goldbox.dos_codec.write`, and re-cuts the 285-byte DOS record, its `.ITM`
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
| Amiga -> neutral -> Amiga, the whole path | **20 of 20** identical outside that list plus `goldbox.dos_codec`'s own `WRITE_UNSOURCED`, `WRITE_CONSTANTS` and computed fields |
| the 65-byte item nodes | **17 of 17** identical past the display cache and `next` |
| the 10-byte effect nodes the neutral record can hold | **15 of 15** identical past the four-byte `next` |
| `.itm` lengths | identical to the originals, **6 of 6** |
| `.spc` lengths | identical to the originals, **9 of 12** -- see below |

Re-measured 2026-09-04 against a corpus rebuilt by `tools/amiga/amigasaves.py`. The
mask covers 125 of the 288 offsets, so **163 bytes of every record have to
match exactly**, and they do on all twenty.

**The `.spc` line was 6 of 6 and it is 9 of 12, and the difference is a
defect.** The earlier figure was measured on the six records the game shipped
on disk 1, every one of which carries only racial effects. Twelve of the twenty
specimens have a `.spc` file, and **three of them lose it entirely**:
`goldbox.dos_codec.to_neutral` keeps only the ids in `INNATE_EFFECTS`, the neutral
record has no field for the rest, and `write_por` therefore writes a zero-byte
file. ADDERLY's extra strength (38), CONJURER's Ring of Fire Resistance (61)
and MAGICIAN's displacement (89) -- **all three at duration zero**, so none of
them is a spell that was going to expire anyway, and the only duration-bearing
`.spc` record anybody has read is a DOS `BLESS` at `02 00 01 00`.
`goldbox.amiga_por.to_neutral` now names each one in `dropped`, which is the
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

**The specimens come out of the disks now, not out of scratch.**
`tools/amiga/amigasaves.py` reads the twenty records back out of the images they live
in -- six on Pool of Radiance disk 1 and fourteen on the Curse save disk -- and
`tests/amiga/test_amiga.py` calls it when `$AMIGA_POR_SAVES` names nothing. The
earlier corpus was extracted into gitignored scratch and was lost,
and every one of these tests was skipping until 2026-09-04.

**The second insertion was narrowed here from six candidate positions to
three, from the specimens alone.** DOS holds `00 00 01 00 00` at
`0x083`-`0x087` in 24 of 24 specimens. On the Amiga that `01` reads at
**`0x086`** in **8 of 20** -- all six `CHRDATA<n>.sav` the game itself wrote on
disk 1, plus two of the fourteen `.cha` exports -- and `0x086` is
`amiga_por_offset(0x085)`, which is where DOS's `01` lands only if the
insertion sits *after* it. A pad at `0x084`, `0x085` or `0x086` would put the
`01` at `0x087`, and **no specimen reads 1 there**. So the insertion was one of
`0x087`, `0x088`, `0x089`.

**It is `0x089`, and the writer did have to know which** -- §1.21 reads it out
of two executables. The claim this paragraph rested on, that all three
survivors are zero in all twenty so a writer need not know, is true of the pad
and false of the two bytes beside it: `0x087` and `0x088` are DOS `0x086` and
`0x087`, and writing the six-byte constant `00 00 01 00 00 00` over the window
threw away the control byte and the treasure share with it (#614 (A converted
companion arrives at Amiga Pool of Radiance as a player character, because
write_por overwrites the NPC control byte and reports nothing)).

**What the writer does with the three Amiga-only bytes**, each measured on the
twenty specimens rather than assumed: `0x07F` zero (20 of 20), `0x089` zero
(20 of 20), and `0x11F` zero (15 of 20, junk in the other five, which is
what an uninitialised pad looks like). The effect chain at `0x080` and each
item's `next` at `0x02A` are written NULL, because they are live Amiga heap
addresses and the engine relinks both on load.

**Two things `goldbox.dos_codec.write` imposes on this side and neither is ours:**

* **memorised spells are repacked.** `goldbox.dos_codec` reads the sixteen slots as a
  set and writes them back from the end, on the DOS reading that "DOS fills
  its sixteen slots backwards from the end". **The Amiga corpus refutes that as
  a general rule**: of the fourteen `.cha` exports, one is filled from the
  *start* (`22 22 2f 2f 00...`), and three have entries with zeros on both
  sides (`00 x10, 15 15 00 22 2f 00`). The spells survive; their slot positions
  do not. `#110 (Memorised spells lose their slot positions on the way through the neutral record)`.
* **experience is capped at 16 777 215.** The Amiga field is a `u32be` and the
  reader reads all four bytes, but `goldbox.dos_codec.write`'s own field is three bytes
  wide, so anything going through it overflows with a bare `OverflowError`
  above that. No Pool of Radiance character can reach it. `#111 (An experience total over 16 777 215 crashes the DOS writer instead of being refused)`.

**The file names**, read off disk 1 and confirmed by the game's own save to
slot B (§1.9b): `save/CHRDAT<slot><n>.sav` with `.itm` and `.spc` beside it,
`n` from 1 to 6. `goldbox.amiga_por.por_filename` is the one place that knows it. **A
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
already named in `POR_WRITE_UNSOURCED` or `goldbox.dos_codec.WRITE_UNSOURCED` as
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

`goldbox.amiga_savegame.write_por_slot(disk, slot, characters, savegame)` is what writes
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
`tools/amiga/porslot.py` wrote slot `F` onto that same disk with `write_por_slot`,
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
drawers at all and `tests/amiga/test_amiga_adf.py`'s no-game-data property is worth
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

### 1.14a A Silver Blades party stood where we put it (#28 (Decode an Amiga saved game, not just a character file))

WinUAE, 2026-09-07, holder `wish28sq`; screenshots in `cited/28ssb/shots` and
both files in `~/wish-specimens/ssb-amiga/WISH-SPEC-ssb-amiga-moved/`.

**The edit is three bytes.** `WISH-SPEC-ssb-amiga-adventuring/savgamB.sav` is
the game's own save at `3,3 S`; `tools/amiga/amigalaterslot.py --square 5,9,6` wrote
it back as slot C with `0x1401` 3 to 5, `0x1402` 3 to 9 and `0x1403` 4 to 6,
and **nothing else in 7233 bytes**. The square attribute byte at `0x1405` was
left at the value belonging to the old square, deliberately.

**The status line read `5,9 W 00:00`** after `PLAY`, `L`, `C`,
`BEGIN ADVENTURING` and the journal prompt. So `0x1401` is x, `0x1402` is y and
`0x1403` is the doubled facing with 6 = west -- which the specimen at `3,3`
could not separate -- and **the engine reads the square out of the file** rather
than recomputing or resetting it. Loading an in-world save also does **not**
replay the opening scene, which is the control that attributes the 2750
experience each character gained on the previous run to that scene.

**The engine's resave differs in 23 bytes of 7233**, from `ENCAMP > SAVE > D`:

| offset | ours | the engine's | what |
|---|---|---|---|
| `0x1401`-`0x1403` | 5, 9, 6 | **5, 9, 6** | the square, written back unchanged |
| `0x1405` | 135 | **128** | the square attribute, **recomputed for the new square** |
| `0x1407` | 4 | 2 | the mode before |
| `0x027a` (`$4A3C`) | 1 | **2** | a quest-flag word the visit advanced |
| 20 bytes | | | `effect_chain` and `heap_104` on the six records |

Everything else is identical, including the whole variable array bar `$4A3C`,
the wallset table and the party count.
[`165-amiga-savegame.md`](165-amiga-savegame.md) has what the two map bytes
read and the `GEO.GLB` block that corroborates them.

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
`0x037`, in front of the `u16` weight at `0x038`. That is the same inference
that put the record's own second insertion at the end of its window, and the
record's turned out to be right when it was read out of the engines (§1.21) --
which raises the odds here and is still not a probe. The grade stays an
inference.

### 1.16 The `.pc` loader, read (#148 (The Amiga port's tools are gone, and phase 1 still needs the disassembler), phase 1)

**Phase 1 is done.** `tools/amiga/m68dis.py` was written for this and the routine was
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
* **~~One signature byte, and it is on the items, not the character.~~
  `cmpi.b #$49,$2e(a2)` is the scroll test, and this reading of it was
  wrong.** Node `+0x2E` is the item's `type_index`, not a signature: across
  the 93 items in the nineteen `.pc` files on the Amiga disks it reads 5, 8,
  15, 18, 22, 28, 29, 30, 36, 37, 40 and 50, and **never** `$49`. `$49` is the
  scroll type — the same constant Silver Blades chains further nodes off — and
  the compare belongs to the `+0x0C` read in row 3 of the table above. The
  rest of the table is confirmed. Corrected on `#462 (Decode the rest of
  the Amiga Pools of Darkness .pc: 37 of 75 neutral fields have no home in it,
  so a converted character loses his spells and possessions)`, from
  `tools/amiga/podpcregions.py`.
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

`goldbox.amiga_pod.PodWriter` is unaffected — it leaves `0x04` and `0x08` zero, so
PoD reads its 404 bytes, finds no items and no effects, and never touches the
80 zero bytes after them. Those 80 bytes are harmless padding rather than a
length the game requires, and `RECORD_LENGTH = 484` says otherwise in a
comment; see `#154 (goldbox/amiga.py says 484 is the shortest record Pools of
Darkness will read, and 404 is)`.

**Two of the three `pc` literals in §1.2 were attributed to the wrong sites**,
and `tools/amiga/m68dis.py --refs` says so — each literal is referenced exactly once
in 316 KB of code:

| literal | referenced from | what that routine is |
|---|---|---|
| `0x255B2` | `pea $255b2(pc)` at `0x25568` | the **picker**: builds the list of `*.pc` on the save disk, and prints `No characters to load.` / `No characters to delete.` when it is empty |
| `0x25802` | `pea $25802(pc)` at `0x257DC` | **delete**: builds `NAME.pc` from the record's name at `+0x60` and calls dos.library `DeleteFile` |
| `0x265A2` | `lea $265a2(pc),a2` at `0x26476` | **save**, including the `Update %s?` / `New file name:` prompts |

The loader references none of them: `pcload` is handed a name the picker
already built.

### 1.17 The rest of the record, off the engine's own Silver Blades importer (#462 (Decode the rest of the Amiga Pools of Darkness .pc: 37 of 75 neutral fields have no home in it, so a converted character loses his spells and possessions))

**Every byte of the 404-byte record is named now, and the naming is the
engine's own.** Amiga Pools of Darkness carries a routine that turns an Amiga
*Secret of the Silver Blades* character record into one of its own — the
player's finished Silver Blades party, arriving in the next title — and it is
a straight field-by-field copy: 66 `move.b $src(a3), $dst(a2)` instructions
and eleven block copies, at file offset `0x026000` to `0x0262DC`.
`goldbox.amiga_port.SILVER_BLADES_DELTAS` already names every source offset, because
§1.6a decoded that record for `#55 (Decode the Amiga Curse and Silver Blades
records)`, so each instruction reads as *"Silver Blades' `hp_rolled` is Pools
of Darkness' `0x0B8`"*.

`tools/amiga/podimportmap.py` re-derives the whole map from the player's own disk
and `--check` compares it with `goldbox/amiga_pod.py`'s constants;
`tests/amiga/test_podamiga.py::test_every_offset_matches_the_engines_own_silver_
blades_importer` runs it. **51 of 51 constants match.** This is proof from the
shipped code rather than from a probe, so it cannot be spoiled by an edited
specimen — which matters here, because seven of the nineteen `.pc` files on
this machine come off cracked rips and none of the nineteen has a chain of
custody.

**The record's own routines named three more fields the importer cannot**,
because Silver Blades has nothing to copy into them. `0x015F6C` raises three
high-water marks in one pass — each of the seven class levels at `0x096`, the
experience longword at `0x048` and the maximum hit points at `0x0B6` — and
`0x03315E` restores experience from `0x048`. That is what a title with level
drain that matters keeps instead of the earlier titles' `levels_drained` and
`hp_lost_to_drain`, and it names the same two runs in the **DOS** record:
`goldbox.dos_port.POOLS_OF_DARKNESS` puts `highest_class_levels` at `0x15F`
already, and its five-byte `gap_176` is highest experience at `0x176`-`0x179`
and highest hit points at `0x17A` (PROBABLE, from the Amiga's own three and
from both being zero in 12 of 12 DOS records).

#### The map

Everything below is CONFIRMED unless the row says otherwise. "DOS" is the
name `goldbox.dos_port.POOLS_OF_DARKNESS` gives the field.

| Amiga | width | DOS field | how it was found |
|---|---|---|---|
| `0x000` | 4 | `heap_104[0:4]` | importer |
| `0x004` | 4 | `effect_chain` | importer; §1.16 row 4 |
| `0x008` | 4 | item chain head, and **the item count in a file** | §1.16; the tail is exactly consumed in 19 of 19 |
| `0x040` | 4 | `heap_104[4:8]` | importer |
| `0x044` | 4 | `experience` | probe (§2.3) |
| `0x048` | 4 | highest experience (DOS `gap_176[0:4]`) | `0x015FA4`, `0x03315E` |
| `0x04C` | 6 | `platinum`, `gems`, `jewelry` | probe |
| `0x052` | 2 | `age` | probe |
| `0x054` | 2 | `experience_award` | importer |
| `0x056` | 2 | `encumbrance` | importer; recomputed on load |
| `0x058`, `0x059` | 1, 1 | `race`, `char_class` | probe |
| `0x05A` | 1 | `turn_class` | importer |
| `0x05B` | 1 | `field_83_87[2]` | importer |
| `0x05C`, `0x05D` | 1, 1 | `sex`, `alignment` | probe |
| `0x05E` | 1 | **`status`** | importer, **and the sheet's own string table** |
| `0x05F` | 1 | **`hostile`**, the combat side | importer; compared between two records |
| `0x060` | 16 | `name` | probe |
| `0x070` | 12 | the six ability pairs | probe |
| `0x07C` | 2 | `exceptional_strength` pair; byte 0 in force, inferred from the later titles | importer |
| `0x07E` | 1 | Silver Blades' `gap_069` | importer. UNKNOWN |
| `0x07F` | 1 | `thac0_base` | importer; agrees with the DOS peer 12 of 12 |
| `0x080` | 1 | `paladin_cures` | importer; 1 for both paladins, 0 for the other 17. Converted both ways since the neutral record gained the field: the reader takes it and the writer puts the source's own byte back, where it used to write 0 for both paladins |
| `0x081` | 1 | `hp_max` | probe |
| `0x082` | 1 | `icon_dimension` | importer; 1 in 19 of 19 |
| `0x083` | 5 | the five saving throws | importer |
| `0x088`, `0x089` | 1, 1 | `movement`, `level` | probe |
| `0x08A` | 1 | `former_level` | importer, and the dual-class routine |
| `0x08B` | 8 | the eight thief skills | importer |
| `0x093` | 1 | `field_83_87[0]`, **the NPC control byte** | importer |
| `0x094`, `0x095` | 1, 1 | `field_83_87[1]`, `[3]` | importer |
| `0x096` | 7 | **highest class levels** | `0x015F6C` |
| `0x09D` | 7 | `class_levels` | probe |
| `0x0A4` | 7 | `former_class_levels` | importer, and the dual-class routine |
| `0x0AB` | 8 | `attack_forms` | importer. `0x0AB` is attacks in halves and `0x0AD`/`0x0AF`/`0x0B1` the damage triple |
| `0x0B3` | 1 | `armour_class_base` | importer; 50 in 19 of 19, as DOS in 12 of 12. The writer now copies this byte through from the source rather than always writing 50 (#635 (Read what a Pools of Darkness armour-class base other than 50 means, so the Amiga conversion writes it instead of refusing)) |
| `0x0B4`, `0x0B5` | 1, 1 | `strength_bonus`, `unnamed_0ab` | importer |
| `0x0B6` | 1 | **highest hit points** (DOS `gap_176[4]`) | `0x015FB4` |
| `0x0B7` | 1 | `class_bits` | importer |
| `0x0B8` | 1 | **`hp_rolled`** | importer, and the constitution arithmetic below |
| `0x0B9`, `0x0BA` | 1, 1 | `portrait_head`, `portrait_body` | importer; zero in 19 of 19, and this title draws no sheet face |
| `0x0BB`, `0x0BC` | 1, 1 | `icon_head`, `icon_body` | importer |
| `0x0BD` | 1 | `combat_figure` | importer; the code compares it at 7 and 8 |
| `0x0BE` | 1 | `size` | importer; 1 for the one dwarf on the disks, 2 for the rest |
| `0x0BF` | 6 | `icon_colours` | importer; `91 a2 b3 c4 e6 f7` in 15 of 19 |
| `0x0C5` | 2 | `unnamed_1a4` | importer; `02 02` in 19 of 19, as DOS in 12 of 12 |
| `0x0C7` | 1 | a **stale** cached item count | importer; 3 in 17 of 19 against four to six items |
| `0x0C8` | 1 | `hands_used` | importer; 2 in 18 of 19 |
| `0x0C9`, `0x0CA` | 1, 1 | Silver Blades' `gap_19a`, `gap_1a5` | importer |
| `0x0CB` | 1 | a cached count, written after `SCROLLS DROPPED!` | eight write sites. UNKNOWN |
| `0x0CC` | **141** | **`spells_memorised`** | the dual-class routine clears it |
| `0x159` | **16** | **`spellbook`**, as a bitmask | importer, and nine of ten DOS peers id for id |
| `0x169`, `0x172`, `0x17B` | 9 each | `spells_castable` cleric, druid, magic-user | importer's own loop, and 10 of 10 DOS peers |
| `0x184` | 1 | **`active`** | importer; 1 in 19 of 19 and 63 `tst.b` sites |
| `0x185` | 1 | **`quickfight`** | importer |
| `0x186`, `0x187` | 1, 1 | `thac0_current`, `armour_class` | importer |
| `0x188` | 9 | `roster_tail` | importer |
| `0x191` | **1** | `hp_current` | importer |
| `0x192` | 1 | `movement_current` | importer |

**`attack_level` was the one field of the record still unlocated, and §1.18
settles it: this title has none.** Silver Blades keeps it at Amiga `0x080` and
the importer does not copy it; Pools of Darkness' `0x080` is `paladin_cures`
and its `0x082` is `icon_dimension`, with `hp_max` between them, so the field
is not merely displaced — the engine indexes its attack table with the class
level and keeps no fighting level anywhere. The bytes nothing claims are
`0x07E`, `0x0CB` and `0x193`.

#### Three things the map corrected

* **`hp_current` is the byte at `0x191`, not the big-endian word at `0x190`.**
  The probe that found it wrote `00 37` and both readings gave 55, so it never
  told them apart; the importer copies Silver Blades' thirteen-byte derived
  tail one for one, and `hp_current` is one byte in it. `0x190` is
  `roster_tail`'s last byte and is zero in 19 of 19.
* **`0x0B8` is `hp_rolled`, not a portrait.** The nineteen files are the
  AD&D table exactly: `hp_max - 0x0B8` is 22 for each magic-user 14 (eleven hit dice at
  +2 for constitution 18), 18 for each cleric 14 (nine at +2), 40 for each
  ranger 13 (ten at +4), 36 for the paladin 12 and the fighter 14 (nine at
  +4), 20 for the thief 16 (ten at +2), and 15 for HOPE, a fighter 5 whose
  constitution is 17 rather than 18 (five at +3).
* **`armour_class` and `armour_class_base` are two bytes, not one.** The
  reader gave both from `0x0B3`, which is the unarmoured 50 in every record,
  so an Amiga character in plate mail converted as though he were unarmoured.

#### The spellbook, and the one anomaly

Bit `i` of byte `i >> 3` of the sixteen bytes at `0x159` is index `i` of the
DOS record's 125-byte `spellbook` array, which is spell id `i + 1`. Ten of the
nineteen `.pc` files have a DOS record of the same class and the same class
levels, and **nine of the ten agree with it id for id**.

The tenth is the three cleric 14s — CLERIC and FRODE on the shipped disk 3,
and lady gwendolyne on an alternate rip. All three carry an identical mask,
and it is the DOS cleric's spellbook **plus exactly seventeen ids**: 9-21,
which is the magic-user's whole level-1 group, and 77-80, which is the
druid's. That is a fact about those three characters rather than about the
encoding — no other class among the nineteen shows anything like it — and it
is UNKNOWN. **The experiment**: read Pools of Darkness' own cleric grant table
the way `tests/secret_of_the_silver_blades/test_silverblades.py::_grant_table` reads Silver Blades', and
see whether a cleric is handed those two groups. If he is, the game gives its
clerics magic-user and druid spells and the three records are right; if he is
not, somebody edited a shipped pregen and every `.pc` on these disks is a
weaker specimen than it looks.

#### What it leaves

`goldbox.amiga_pod.pod_to_neutral` filled **61 of the 75 neutral fields** after
this run, where it filled 38, and §1.18 takes it to 63. Of the fourteen it did
not fill then: nine are fields *this title* has on neither port (four coins,
`levels_drained`, `hp_lost_to_drain`, `experience_per_hit_point`,
`infravision`, `turn_power`), three were the item and effect regions the
reader had not been taught to walk, one was `attack_level`, and one is
`npc_control_byte`, which a player character does not have.

**What the writer does with all of this is §1.19**, which is
`#475 (The Amiga Pools of Darkness writer leaves 27 decoded fields zero, and
one of them may mark a converted character as out of the party)`.

### 1.18 The tail, walked, and the attack table that has no field (#462 (Decode the rest of the Amiga Pools of Darkness .pc: 37 of 75 neutral fields have no home in it, so a converted character loses his spells and possessions))

§1.16 read the loader and §1.17 the record; this is the reader catching up
with both. `goldbox.amiga_pod.pod_to_neutral` walks the item region and the
effect chain, so a character read off an Amiga disk arrives in DOS with his
own possessions and his running magic instead of nothing:
`goldbox.dos_codec.write` builds him a `.THG` of four, five or six items and
an `.EFX` where the file had one.

#### What the reader is checked against

Every row is a test in `tests/amiga/test_podamiga_regions.py`, over every
`Save/*.pc` on the player's own disks — 19 files, 93 items and 11 effect
nodes on this machine.

| claim | sample |
|---|---|
| `money + Σ(weight × max(quantity, 1))` is the stored encumbrance word at `0x056` | **19 of 19**, at three distinct totals: 601, 960, 371 |
| every item decodes in range — `readied` a flag, `hidden` and `cursed` 0, `plus` 1-6, the three insertion pads zero | **93 of 93** |
| `404 + 20 × items + 20 × scroll nodes + 10 × effects` is the file's own length, walking the effect chain rather than dividing the remainder | **19 of 19** |
| an effect node re-cuts to DOS's `<id> 00 00 FF 00` and a NULL next | **11 of 11** |

#### Two things in the region nothing had noted

* **A scroll's chained nodes have nowhere to go.** §1.16 row 3: an item whose
  `type_index` is `0x49` is followed by its own `quantity` further twenty-byte
  nodes, each carrying three more spell ids. No item in the nineteen files is
  a scroll — `type_index` reads 5, 8, 15, 18, 22, 28, 29, 30, 36, 37, 40, 50
  and 59 across the 93 — so nothing has ever been lost here, and a reader
  that walked twenty bytes an item regardless would have read the first
  chained node as the next item. The reader follows the chain and counts the
  nodes onto the drop list rather than converting them.
* **An effect still counting down is `running_effects`.** The vocabulary
  keeps `innate_effects` and `granted_effects`, both of which are what never
  expires, and now a third, `running_effects`, holds the nodes with time
  left as whole nine-byte records whose duration is game-clock minutes
  (`docs/162-spc-permanence.md`). Before that the reader counted them onto the
  drop list and the two later titles' reader dropped them with no line. The
  duration word is zero in 11 of 11 nodes here, so no record on any disk has
  one, and **the big-endian byte order of the word at `0x002` has never been
  read against a value**: it stays PROBABLE, and `tests/convert/
  test_runningeffects.py` pins both orders with a synthetic 0x0102 so a wrong
  swap fails. One `.pc` written with a known duration and loaded in the
  running game settles it.

#### `attack_level`: the engine works it out and stores nothing

**The two routines that derive `thac0_base` at `0x07F` both index one attack
table with a class level**, and `tools/amiga/podimportmap.py --thac0` finds
no third: it searches the code hunk for every `d16(a4)` that lands anywhere in
the table and finds four references, two in each of those routines (`0x03C274`
and `0x03C290`, `0x00EFAC` and `0x00EFD4`) and none outside them. That search
sees one addressing mode only, so a pointer to the table kept in a global, or
an absolute address the loader relocates, would not show; the claim is that
no other routine reaches the table through the small-data register, which is
how the engine reaches it in both. The derived-fields rebuild at `0x03C238` walks the seven
class slots, asks `0x03D046` for each one's level, caps it at 21 and keeps
the best entry of `data + 0x1DE0`, a table of seven rows of 22 bytes in the
family's stored `60 - THAC0` form. Character creation does the same at
`0x00EF82`, on its own global, with no cap. **Neither reads any other byte
of the record.**

```
03c26a: muls.w #$16, d0           ; 22 bytes a class row
03c274: lea.l  -$621e(a4), a0     ; the attack table, data+0x1DE0
03c278: move.b (a0, d0.l), d0     ; row[level]
03c27c: cmp.b  $7f(a2), d0        ; keep the best
03c294: move.b (a0, d0.l), $7f(a2)
```

**`0x03D046` is not `max(class_levels[i], former_class_levels[i])`, and this
page said it was.** It reads the former array only when `0x03D020` returns 1,
and that is two tests rather than one:

* `0x03CFB2` returns 0 unless the record's race byte at `0x058` is **5, the
  human** (`cmpi.b #$5, $58(a2)`), which is the only race AD&D lets
  dual-class. For a human it returns the level in the first non-zero class
  slot, scanning slots 0 to 5 and falling through to slot 6.
* `0x03D020` compares that level with the byte at `0x08A`, `former_level`,
  and returns 1 only when it is **greater** — which is AD&D's rule that a
  dual-classed character uses his old class again only once his new level
  passes the level he left at.

With the gate shut the former array contributes nothing at all. Corrected
here because a bare `max` would give a converted character the wrong
THAC0 the moment his new class was the lower of the two, and because
`tools/amiga/podimportmap.py`'s own arithmetic was written from it.

**What the nineteen files corroborate, and what they do not.** The
arithmetic reproduces the stored `thac0_base` byte of **19 of 19** `.pc`
files, which fixes the table's address, its stride and the rule that the
best of the seven class slots wins — three of the nineteen are multi-classed
(BOHLO BART AB a fighter 9/thief 13, SILBERMO and TRIPEL TURBO
fighter/magic-user/thieves), so that last part is not a single-class claim.
**None of the nineteen is dual-classed**: `former_class_levels` is zero in
all of them, so the gate above and the cap at level 21 are read off the
listing and are measured by nothing.
`tools/amiga/podimportmap.py --thac0` prints the table off the player's own
executable and runs the check.

So the record's last UNKNOWN is not a field nobody has found: **Pools of
Darkness keeps no `attack_level`**, and the reader names it as a field the
title has on neither port rather than as one still unlocated. It bears on
`#527 (Every Gold Box engine keeps a fighting level in attack_level and our
Pools of Darkness conversion writes 0)` from the other side: DOS Pools of
Darkness holds 0 at `0x130` in 52 of 52 records, and the **prediction** is
that its `GAME.OVR` derives the fighting level the same way this binary
does. That is inference from the Amiga executable and nothing has read the
DOS one — `tools/dos/dosfieldrefs.py` over this title's own `GAME.OVR` is
the run that would settle it, and what it should find is no site indexing an
attack table by `0x130`.

#### What it leaves

`pod_to_neutral` fills **64 of the 78 neutral fields**, and 65 for a character
with an effect that never expires, since `granted_effects` is set only when
there is one; `running_effects` is set only for a node with time left, which
no disk has. The eleven it names on `pod_read_dropped()`: nine this title stores on
neither port, `attack_level` above, and `innate_effects` — a label rather than
a byte, because which node is an innate property of the race or the class and
which a readied item granted cannot be told apart for this title, the same
unknown that binds Curse and Silver Blades. The twelfth name absent from a
converted character is `npc_control_byte`, which a player character has not
got.

**The single unapproved warning is gone rather than reworded.** It said the
part of the file holding possessions and running magic had not been read, and
that stopped being true.

### 1.19 The writer, filling what the reader reads (#475 (The Amiga Pools of Darkness writer leaves 27 decoded fields zero, and one of them may mark a converted character as out of the party))

§1.17 decoded the record and §1.18 taught the reader its tail; the writer
emitted zero for all 27 of the decoded fields until this run. **A character
converted into the Amiga now arrives with his spells, his possessions, his
running magic and his state**, and the one that was not merely missing is
`active` at `0x184`: 19 of 19 records the game itself wrote hold 1 there, 63
`tst.b $184(aN)` sites read it, and this writer left the value the other two
ports draw a name red for.

#### What it writes now

| what | where | how it is checked |
|---|---|---|
| `status`, `hostile`, `active`, `quickfight` | `0x05E`, `0x05F`, `0x184`, `0x185` | round trip, and `active` is 1 on both routes into the writer |
| `thac0_base`, `hp_rolled`, `unnamed_0ab`, `experience_award` | `0x07F`, `0x0B8`, `0x0B5`, `0x054` | round trip, 19 of 19 |
| `size` | `0x0BE` | round trip; the neutral 0/1 is this port's 1/2 |
| the NPC control byte | `0x093` | written when the source has one |
| `former_levels`, and the level he left at | `0x0A4`, `0x08A` | the two dual-classed DOS records, ABAGAIL and PAINE |
| the permanent half of each ability pair | `0x070`, `0x07C` | round trip |
| `attack_forms`, as a block | `0x0AB` | round trip, 19 of 19 |
| the spellbook | `0x159` | round trip, 19 of 19 |
| the three spell-slot arrays | `0x169`, `0x172`, `0x17B` | round trip, 19 of 19 |
| the item region, and its count | `404`, `0x008` | **93 of 93 items byte for byte** |
| the effect chain, and its head | after the items, `0x004` | 11 of 11 nodes but for two bytes named below |
| the memorised list, the combat icon and the roster byte | `0x0CC`, `0x0BB`-`0x0BD`, `0x0BF`-`0x0C4`, `0x082` | §1.19a, which is the engine's own code and came after this run |

**The tail is the strongest of these.** A `.pc` read into the neutral record
and written back out reproduces every one of the 93 item nodes on the disks
byte for byte, because the sixteen-byte projection both ports share carries
all fifteen DOS item fields a node holds and the three insertion bytes are
zero on both sides. The file's length matches its source in 19 of 19.

Two bytes of an effect node do not survive and both are named rather than
left to a diff: the byte at node offset 1, which nothing in the engine reads
and the neutral record has nowhere for — non-zero in 7 of the 11 nodes here —
and the four-byte `next`, which is a live Amiga heap address in a file the
game wrote and `1` in one this writes. **The stored pointer is a boolean**:
the loader allocates each node and overwrites the value before the read that
fills it, which is read out of the two later Amiga titles' own loaders
(`goldbox.amiga_later`'s `AMIGA_LATER_CHAIN_PRESENT`) and is how §1.16 reads
this one. A scroll is written with its own `quantity` further twenty-byte
nodes after it, empty, so that the loader's walk stays in step; nothing else
in the file would be where the loader expected it otherwise.

#### What is still zero, and why

| field | why not |
|---|---|
| `encumbrance`, `thac0_current`, `armour_class`, `movement_current` | the game recomputes them on load, each demonstrated by a probe that wrote a wrong value and read the right one back off the sheet |
| `armour_class_base`, `0x0B3` | **superseded by #635 (Read what a Pools of Darkness armour-class base other than 50 means, so the Amiga conversion writes it instead of refusing)**: copied through from the source's own stored base, because both engines seed the current armour-class calculation from it on creation and on every rebuild. A source with none of its own gets the unarmoured `60 - 10`, which is what 19 of 19 `.pc` files — whose characters all carry items — and 12 of 12 DOS records hold |
| `roster_tail`, `0x188` | all nine bytes are rebuilt by the engine — §1.19b, which is why the row is in `POD_WRITE_DERIVED` rather than the drop list |
| bytes no neutral field names, all left zero | the stale item count `0x0C7`, `hands_used` `0x0C8` (2 in 18 of 19) and `gap_19a` `0x0C9` (2 in 5 of 19, 0 in the other 14; its neighbour `0x0CA` is 0 in 19 of 19) |

**All three of those bytes are rebuilt on load**, by the one routine at `0x019428`: it clears the item count, `hands_used`, `gap_19a` and the encumbrance word together and then walks the item chain filling all four, which is the rebuild §2.3's encumbrance probe watched happen. This section said `gap_19a` had no routine and that what its zero does was unmeasured; §1.19b has both, and the byte is the readied items' saving-throw bonus.

**None of this has been in front of the game yet**, and that is the boundary
of the claim: the bytes match and the lengths match, and a conversion is not
proven until a party made this way walks. What a driven session still owes is
the sheet — the STATUS line for `status`, and what the party panel draws for a
character whose `active` is 0, which §1.19a settles the *meaning* of and not
the colour.

### 1.19a What the engine itself puts in the eight fields the writer left zero (#475 (The Amiga Pools of Darkness writer leaves 27 decoded fields zero, and one of them may mark a converted character as out of the party))

§1.19 left eight fields zero and named three driven experiments to settle
them. **The engine's own code settles all three**, so none of them was run.
The disassembly is of the build most disk-1 images agree on, the one
`tools/amiga/podimportmap.py` takes.

#### `active` at `0x184`, which this issue is named for

CONFIRMED, and 0 is out of the party. Four sites, and the first is the
decisive one:

| where | what it does |
|---|---|
| `0x003712` | walks the roster chain and counts a member only when `$184 == 1` **and** `$5E == 0` **and** `$5F != 1` — the party enumeration itself |
| `0x011D98` | the field setter writes `$5E` and then puts 1 in `$184` when the new status is 0 and 0 otherwise, so **`active` is "status is Okay"** |
| `0x011E6C` | the routine that gives a character a bad status clears `$184` and `$191` on its way past |
| `0x00FD46` | character creation writes 1, which is what 19 of 19 files hold |

**The join path does not repair it.** The routine at `0x027398` that appends a
record to the roster chain writes `$BD`, the chain and the NPC byte and never
touches `$184`, so a `.pc` carrying 0 joins as a character the enumeration
above does not count. What the party panel *draws* for that is still
unmeasured; that the engine does not count him is not.

#### The memorised list fills from `0x0CC` forwards

CONFIRMED, and neither of the two payloads §1.19 proposed would have been
needed:

* `0x000A5C` — the MEMORIZE screen counts up from index 0 for the first zero
  byte and writes the spell there;
* `0x000864` — the tidy pass sorts the region ascending by `id & 0x7F`
  towards index 0 and closes the hole behind a cleared entry;
* `0x015CE0` — the surplus check counts entries per class and level from
  index 0 and clears the **later** ones when a character holds more than
  `spells_castable` allows;
* `0x002EE6`, `0x02208E` and `0x0154F6` — every reader iterates 0 to `0x8C`.

**Bit 7 is the pending flag here as in DOS**: memorising stores `id + 0x80`
(`subi.b #$80` on a byte, `0x000A76`) and the rest that completes it takes the
bit off and prints "has memorized" (`0x002F30`), so the byte crosses between
the ports unchanged.

This corrects §1.19 and the reader's own note, both of which said this port
fills from the end backwards as DOS does. The reader's *output* was right
regardless — ids run ascending through memory on both ports, DOS ending at the
last byte and this one starting at the first, so reversing is the transpose
either way — but the reason was wrong.

#### `combat_figure` at `0x0BD` is assigned on join, not read from the file

`0x027398` stores `0xFF` over whatever the file held, appends the record to the
chain, walks the chain marking which of the eight marching slots are taken, and
counts the byte up from 0 to the first free one (`0x0273FE`-`0x027432`) — which
is what the compares at 7 and 8 are. So the 13 in 17 of 19 files is what
creation writes (`0x00FD5A`) for a character in nobody's line, and LADYGWEN's 3
and MAGNUS MAGNUSSON's 4 are their parties' own slots. The field is derived
rather than dropped, and the writer emits creation's 13.

#### The combat icon has an engine default, and zero was not it

`0x00C736`, which creation calls at `0x00FD92`:

| byte | what the engine gives a new character |
|---|---|
| `icon_head` `0x0BB` | halfling → 3; otherwise female → 9 medium, 7 small; male → 5 medium, 0 small |
| `icon_body` `0x0BC` | the first class slot with a level: cleric → `0x17`, ranger → 1, paladin or fighter → `0x18`, magic-user → `0x1D`, else 5 |
| `icon_colours` `0x0BF`-`0x0C4` | `t * 17 + 0x80` for t in 1, 2, 3, 4, 6, 7 — the bytes `91 A2 B3 C4 E6 F7`; the fill loop is `0x00FCE6`-`0x00FD1E` and reads its values through `-$6158(a4)`, so 1, 2, 3, 4, 6, 7 are inferred from the ten unedited files |
| `icon_dimension` `0x082` | 1 |

The rule reproduces the stored head in 15 of 19 files and the body in 11 of 19,
and the colours in 10 of 19; the rest were changed on the ICON screen, which is
the screen this routine supplies the starting position for. That screen's wrap
points bound both bytes — `cmpi.b #$d` at `0x00CAC8` and `cmpi.b #$1f` at
`0x00CDF8` — so the head is 0-13 and the body 0-31, and 19 of 19 files are
inside both.

**`size` at `0x0BE` was the unnamed risk.** The drawing routine at `0x0255F0`
builds the icon library's name as `CHEAD%c`/`CBODY%c` with a letter indexed by
`size`, so a converted character whose source had no `size_small` — the byte
was left zero — asked for a file that does not exist. That is a likelier cause
of §2.3's `ERROR: INVALID ITEM (-1/29)` than `icon_head` was, because the ramp
moved `0x0B6`-`0x0C7` together and `0x0BE` is inside it. The engine sets the
byte from race at `0x00E552` through the jump table at `0x00E648`: **1 for the
dwarf, the gnome and the halfling and 2 for the elf, the half-elf and the
human**, each with its own racial effects granted in the same breath. The
writer now writes the source's size when it has one and the race's otherwise.

#### The rest of the bytes no neutral field names

`0x0C5`-`0x0C6` is `02 02` in 19 of 19, and creation writes 2 into each
(`0x00FDA2`, `0x00FDAC`); the Silver Blades importer copies that title's byte
into `0x0C5` and then overwrites it with 2 at `0x0262C8`, so every record the
engine makes holds it however it was made. The writer emits the pair. What it
*is* stays UNKNOWN.

**The stale item count `0x0C7` and `hands_used` `0x0C8` are rebuilt on load,
so leaving them zero is right.** The routine at `0x019428` clears the thirteen
readied-item longwords at `0x00C`, then `0x0C7`, `0x0C8` and the encumbrance
word at `0x056`, and walks the item chain adding one to the count per node,
each item type's hands out of `g6968[type * 16 + 1]`, and each item's weight
into the encumbrance. §2.3's probe wrote 1234 into that encumbrance word and
read 233 back off the sheet, which is this routine running on load and is what
the other two bytes ride on. So `hands_used` 0 beside a readied weapon is not
a state a loaded record stays in.

`gap_19a` `0x0C9` is the third byte of that same rebuild and §1.19b has it;
this section said it had no routine, which was true of what had been read and
not of the engine.

#### What a player still loses

**A chosen combat icon does not survive a conversion.** No neutral field holds
one, so an Amiga character who picked his own head comes back with the default
for his race and class; 13 of the 19 characters on the disks differ from the engine's default in at least one of head, body and colours (4 in the head, 8 in the body, 9 in the colours).
It was a loss before this as well — to zero — and it is now a loss to a value
the engine itself would have written. Giving it a neutral home is vocabulary
work.

### 1.19b The last two zeros, and the routine that fills them both (#475 (The Amiga Pools of Darkness writer leaves 27 decoded fields zero, and one of them may mark a converted character as out of the party))

§1.19a left `roster_tail` at `0x188` and `gap_19a` at `0x0C9` as the two bytes
that were neither written nor known-derived. **Both are rebuilt on load, by
one routine, and the `.pc` load path is what calls it.** Read out of the same
disk-1 build; nothing was run in an emulator.

#### The load path, which is what makes this a claim about loading a file

*Add Character* is `0x026A1C`-`0x026A78`. It allocates `0x194` bytes, calls the
`.pc` loader at `0x025806`, and on success calls **`0x019428`** and then the
roster join at `0x027394`. The inter-title import path does the same at
`0x026326`. `0x019428` is the derived-fields rebuild §1.19a already credits
with the item count, `hands_used` and the encumbrance word — and §2.3's probe
wrote 1234 into that encumbrance word and read 233 off the sheet, so there is
a run in the running game behind everything this routine does. Twenty-seven
call sites reach it in all.

#### `roster_tail` `0x188`-`0x190`: every one of the nine

| byte | what it is | who writes it |
|---|---|---|
| `0x188` | the armour bonus | `0x0196E8`, the rebuild's last act: the four accumulated armour terms less 2 |
| `0x189`, `0x18A` | the two attack counts | **not on load.** A fight's setup loop walks every combatant (`0x003972`-`0x003990`) calling `0x007D5E`, which clears the combat block's `$0A` at `0x007E26` and then sets `0x189` from `attack_forms`' first byte (`0x008A4E`, inside `0x008A34`) and `0x18A` from its second (`0x007E6A`), both unconditionally |
| `0x18B`-`0x190` | the running damage | the rebuild copies `0x0AD`-`0x0B2` here (`0x019556`-`0x0195AE`), then `0x018778` — called at `0x019610` — overwrites `0x18B`, `0x18D` and `0x18F` from the readied weapon's own item-table entry (`$9`, `$a`, `$b` of `g6968[type * 16]`), and `0x019604` adds the unarmed bonus when nothing is readied |

**The nineteen `.pc` files agree, and two columns settle the copy:**

| byte | across 19 records |
|---|---|
| `0x188` | 56 in 5, 58 in 14 |
| `0x189`, `0x18A` | **0 in 19 of 19** |
| `0x18B` | 1 in 19 of 19 |
| `0x18C`, `0x18E`, `0x190` | 0 in 19 of 19 |
| `0x18D` | 6 in 7, 8 in 12 — while `0x0AF`, the byte the copy puts there, is **2 in 19 of 19** |
| `0x18F` | 4, 5, 6, 7, 8 or 9 |

`0x18D` holding a weapon's die size where its copy source holds the unarmed 2
is `0x018778`'s overwrite showing in the files. The two bytes the code says are
combat-time only are zero in every record the game wrote, which is what this
writer emits; that column shows what the shipped files hold and does not decide
the question (see the limit below).

So no part of the block can come from a source: five bytes are zero in every
engine record, three are the readied weapon's numbers out of a table the record
does not hold, and one is an accumulation the rebuild computes. `roster_tail`
leaves `POD_WRITE_DROPPED` for `POD_WRITE_DERIVED`, and the drop list is
**twelve rows where it was thirteen**.

#### `gap_19a` `0x0C9` is the readied items' saving-throw bonus

No neutral field names it, so it is on no list — but it is no longer
unexplained:

* the rebuild clears it at `0x0195C0`, beside the item count and `hands_used`;
* `0x01891E`, called from the rebuild's own item loop at `0x019638`, adds an
  item's `plus_save` in at `0x0189AC`-`0x0189B8` (`move.b $c9(a0), d0;
  add.b $34(a2), d0; move.b d0, $c9(a0)`, where `a2` is the item node and item
  `+$34` is DOS's `plus_save` — the Amiga node runs one byte later than DOS's
  from `0x032` on), **behind a branch**: the item-table entry's byte 6 must
  have bit 7 set, its low seven bits must be zero, and the item type
  (`g6968[type * 16]`) must not be 1 (types 7 and 9 write their own
  byte through the third argument first and then reach the add);
* the saving-throw routine at `0x012EB0` reads it back at `0x012F10`, into the
  roll's modifier before it indexes the five throws at `0x083`.

**19 of 19 `.pc` files equal the sum of `plus_save` over their own readied
items**: 2 for the five characters wearing the one type-59 item that carries
`plus_save` 2 — BJORK, KRISTIN, MAGIC JHO, MAGNUSMA and ?T — and 0 for the
other fourteen, and no other value occurs. That is the pattern the files show
and not the engine's whole rule, which is the branch above: only the readied
items that qualify are summed, and nineteen files with one item type between
them cannot say which those are. The conclusion stands on the routines, which
clear, accumulate and read the byte back: this corrects §1.19 and §1.19a, both
of which said no routine had been found and that what the zero does to the game
was unmeasured. The game fills it in, as it does `hands_used`.

#### What is left, and one limit on the claim

Nothing on this issue is now both zero and unexplained. `0x0CA` is 0 in 19 of
19 and is written only by the Silver Blades importer and a field setter at
`0x011D90`; `0x0CB` is still the UNKNOWN cached count; the heap pointers at
`0x000`-`0x03F` stay zero because the loader overwrites them.

For `0x189` and `0x18A` the evidence is the **setup order**: a fight's setup
loop (`0x003972`-`0x003990`) calls `0x007D5E`, which clears the combat block's
`$0A` at `0x007E26`, then sets `0x189` through `0x008A34` (`0x008A4E`) and
`0x18A` at `0x007E6A`, both unconditionally, so a loaded value is overwritten
before that fight reads it. The displacement search sees `d16(An)` and would
miss a read through a pointer computed another way, and it does: indexed
`adda.w #$188` accesses (index 1 or 2) at `0x0088DA`, `0x0088F4`, `0x008904`,
`0x008F3A` and `0x009122`, `adda.l #$189` at `0x009142` and `adda.w #$18A` at
`0x007F68`. `0x0088FC`-`0x008908` writes 1 into `0x189` or `0x18A` when it is
zero. The six routines from `0x0088DA` to `0x009142` dereference the combat
block at `$40(a2)`, `0x007F68` is a helper handed the record, and the attack
routine `0x007738` has callers only at `0x0067DA` and `0x00725A`. All of this
is read from the engine's code; nothing was run.

**The `0 in 19 of 19` column is not an independent half of that argument.** It
shows only that the shipped files were saved outside a fight, when the engine
holds zero there whatever the setup would write. The claim is the code's, not
the measurement's.

`tests/amiga/test_podamiga.py` re-derives the load call, the import call and
the twenty-seven instructions of `DERIVED_SITES` off the player's own disk 1
rather than quoting them — the item count and `hands_used` cleared and
counted, `gap_19a` cleared, accumulated and read back, the armour bonus, the
two attack counts, the `0x18B`-`0x190` copy loop with its source and
destination bases, and the weapon routine's three overwrites — and checks the
`plus_save` sum and the five zero bytes against all nineteen records.

### 1.20 The saved game, read from the routine that writes it (#599 (How is the Amiga Pools of Darkness saved game laid out, so a whole save can convert and not only its characters?))

`Save/SavGam<L>.pty` is a straight run of `write(fd, buf, len)` calls, and the
loader reads the same sequence back into the same globals — the method
[`165-amiga-savegame.md`](165-amiga-savegame.md) used on the other three
titles. The save callback is `/Pools of Darkness` file offset `0x270E0` and
the load callback `0x26904`; each region below is one of their calls.
`tools/amiga/podsavegame.py` is the reader and `tests/amiga/test_podsavegame.py`
the proof.

| at | bytes | source | what |
|---|---|---|---|
| 0 | 1024 | `[g57ac] + 1` | the byte-wide ECL variable array, variable *N* at offset *N* − 1 |
| 1024 | 6 | `g5f20` | x, y, facing (0/2/4/6), the wall type ahead, the square's attribute byte, a pad nothing references |
| 1030 | 1 | `g743c` | the mode the party was in before this one |
| 1031 | 1 | `g5b12` | the game mode |
| 1032 | 2 | `g5f2c` | the dungeon map, `u16be`, the loader's first argument to `LoadMap` |
| 1034 | 2 | `g5f2e` | that loader's second argument, `u16be` |
| 1036 | 2 | a walk of the party list | the party count, `u16be`, capped at 8 |
| 1038 | … | each character | a 404-byte record, its items twenty bytes each, its effects ten each |
| … | … | `[g6e96]` | padding to a fixed **10,828** bytes |

**CONFIRMED from the code, and every byte accounted for in 14 of 14.** Fourteen
distinct saved games are on the Amiga disk images here — the eight shipped in
disk 3's `Save` drawer and six more on alternate rips — and all fourteen parse,
rebuild byte for byte and measure 10,828. Give the same reader DOS's own
widths, a five-byte square struct and a one-byte count, and **14 of 14 fail**,
so the map is not true of any reading.

#### It is DOS's container, in DOS's field order

Every name and its order is `goldbox.dos_savegame.SAVE_POOLS_OF_DARKNESS`'s,
and there are exactly two differences. The Amiga struct at 1024 is **six bytes
where DOS writes five** — DOS has no pad — so every offset after it is DOS's
plus one, which is why the mode byte looked one byte late. And the party count
is a **`u16be` where DOS keeps a byte**, the way Curse and Silver Blades do on
this port. DOS's file ends at the count; this one carries its party inline
rather than naming `CHRDAT` files.

The engine's own reads corroborate each field. The loader hands `g5f2c` and
`g5f2e` to `LoadMap` at `0x26B3A` when variable 34 is set, which is DOS's
`POD_MAP`/`POD_MAP_BLOCK` pair and its `POD_IN_DUNGEON`. The step routine at
`0x11532`-`0x1157A` increments and wraps `g5f20` and `g5f21` at 15, so they are
x and y on a 16 × 16 grid, and it rewrites `g5f23` and `g5f24` on the same
step. `g5f25` has **no reference anywhere in the executable** and reads 0 in 14
of 14 — Curse's `g3f65` and Silver Blades' `g57a5` again. `g743c` is only ever
assigned from `g5b12` (`prev = mode`), which is DOS's
`POD_PREVIOUS_MODE`/`POD_MODE` order exactly.

The modes read as the DOS enumeration says. **`g5b12` is 2, camp, in 12 of 14**
— a save is made from camp — and 0 in the two whose square is the new game's
own `7,13,0` and whose clock is all zeros, which is the value a load leaves
behind and the same reading `165-amiga-savegame.md` gives the shipped Silver
Blades save. **`g743c` is 3 in every slot whose variable 34 is 0 and 4 in every
slot whose is 1**, 12 of 12 that have been in the world: `POD_MODE_WILDERNESS`
and `POD_MODE_DUNGEON`.

Byte 1028 is the square's attribute byte, read out of the resident 16 × 16 map
the way [`165-amiga-savegame.md`](165-amiga-savegame.md) reads the later
titles'. In 14 of 14 some block of disk 3's `GEO.GLB` holds that byte at
`0x200 + 16y + x`, and in 3 of them exactly one of the 32 blocks does.
PROBABLE: no saved game here has been matched to the block it actually names.

#### The party region is a `.pc` file, repeated

The write loop at `0x26338` puts the **item count** into the record's long at
`0x08`, where memory keeps the chain head, writes the 404 bytes, then twenty
bytes of each item node from node offset `0x2E`, then ten bytes of each effect
node. An item whose first byte is `0x49` — the scroll bundle — is followed by
`node[0x0C]` more twenty-byte nodes. The loader at `0x25806` reverses it: it
takes the count from `0x08` and zeroes it, and it walks the effect chain by
each node's own long at `0x06`, so the head at record `0x04` is a flag rather
than a count. That is the `Save/NAME.pc` layout §1.18 already walks, so the
container's party is the existing `.pc` reader with an offset. CONFIRMED.

#### The padding is the item table, and nothing reads it

The save ends `lseek(fd, 0, 1)` and, when the position is short of 10,828,
writes the difference from `[g6e96]` — the 0x13EC-byte item template table
indexed at `id × 20` at `0x100FE`. **The first 5100 bytes of the padding are
byte-identical in 14 of 14**; past that the write runs off the allocation into
neighbouring heap and the files diverge. The loader stops at the last
character and never seeks past it, so a writer may put anything there.
CONFIRMED from both callbacks.

#### `Vault<L>.DAT` is the item vault, and a slot loads without one

4016 bytes: twelve of header, the marker `$FFFF`, a `u16be` item count, then a
fixed two hundred twenty-byte item nodes with the unused ones padded from the
same item table (`0x3DA86`). 12 + 4 + 200 × 20 = 4016, which is what all
seventeen on these disks measure, all with the marker and counts of 0 to 97.
**The saved-game loader never opens it** — it is read when the player enters
the vault and written when they leave (`0x3DD66`, `0x3DF1E`), and the save
menu copies the old slot's vault to the new one when the letter changes
(`0x27354`). So a converted slot does not need one to load, and a player who
walks into the vault without one meets the engine's disk request rather than
an empty vault. CONFIRMED for the loader; PROBABLE for what the vault screen
then does, which nobody has watched.

#### Which variables mean the same on both ports

`tools/dos/dosptrfields.py` finds displacements 0-58 and 195-197 off DOS's
block pointer, which are variables 1-59 and 196-198. The same census on the
Amiga — every displacement after a `movea.l -$2852(a4), aN` — finds **48
variables in 1-59, 198, and 418**, over 246 sites.

So the engine-owned region is the same on both ports, and four of its members
are confirmed to be the same variable by what the Amiga code does with each:
19 is the dungeon map handed to the loader, 32 is the party count and **the
loader clears it on load** exactly as the later titles clear `$503E`, 34 runs
the dungeon or the wilderness, and 58 indexes a wilderness-region table. The
clock is the same seven digits with the same radices: the table
`00 0a 00 0a 00 06 00 18 00 1e 00 0c 00 64` is at Amiga file offset `0x4F79A`,
which is DOS's `(10, 10, 6, 24, 30, 12, 100)` big-endian, and the seven digits
at variables 5-11 are legal against it in 14 of 14.

**The one disagreement is variable 418**, read at `0x57D6` into `g5f2a` and
used as an index at `0x506A`. DOS's census does not name it. That is a
variable this port's engine owns and the other's does not appear to, and it is
the counterexample to "all 1024 mean the same". Everything outside 1-59 is
written by the title's own `ECL` scripts, which are the same content on both
ports, so those are expected to agree — PROBABLE, and untested.

#### What a driven session still owes

The volume the game saves to. `0x25194` guards both the save and the load menu
with a check for a volume and the prompt **"Please insert disk 3."**, and the
path builder at `0x3F7D8` prefixes `SAVE` only on a hard-disk install and
`DF0:` otherwise, leaving the name unqualified — so the file lands in whatever
directory the game is in, and the shipped slots are in disk 3's `Save` drawer.
PROBABLE, from the code; one `ENCAMP ▸ SAVE` settles it.

### 1.21 Where Amiga Pool of Radiance keeps the NPC control byte, and the second insertion (#614 (A converted companion arrives at Amiga Pool of Radiance as a player character, because write_por overwrites the NPC control byte and reports nothing))

`field_83_87` is Amiga **`0x084`-`0x088`**, the whole five bytes at the `+1`
shift, and the second insertion is **`0x089`**, the alignment pad in front of
the `u16` money block at `0x08A`. CONFIRMED, from two executables that agree,
and it corrects §1.12's reading that the pad could be any of `0x087`, `0x088`
and `0x089` and that a writer need not know which.

What it cost while it was wrong: `goldbox.amiga_por.write_por` wrote the
constant `00 00 01 00 00 00` over `0x084`-`0x089`, so a companion converted
into Amiga Pool of Radiance arrived as an ordinary player character, his
morale and his treasure share gone, with nothing in the conversion report.

#### `/program`: the engine's own reads

Every site found with `tools/amiga/amigarecordrefs.py`, over all seventeen of
`/program`'s CODE hunks -- the command-line tool searches every one of them.
Each site was then read in `tools/amiga/amiga68k.py disasm`. File offsets into
the executable:

| where | what it does | what it says |
|---|---|---|
| `0x02DA28` | `cmpi.b #$7f, $85(a3)` / `bls` → the character takes one share; otherwise `moveq #$7, d0` / `and.b $86(a3), d0`, added to the split | `0x085` bit 7 is the engine-driven test; `0x086` is the treasure share, masked with 7 |
| `0x02DB08` | `cmpi.b #$0, $86(a3)` | a share of zero is skipped, as DOS's `0x085` is |
| `0x01B568`, `0x01B5C8` | `move.b $85(a0), d0` compared against `0x80`; RENAME is drawn only below it | a player character may be renamed, a companion may not |
| `0x00B196` | `move.b #$b2, $85(a2)` while building a joining character's record | `0xB2` is bit 7 plus morale 50, stored halved |
| `0x010290` | `cmpi.b #$7f, $85(a3)` / `bhi` / `move.b #$b3, $85(a3)` | the engine takes a character over |
| `0x010244` | reads `$85(a3)`, compares it with `0xB3`, writes `0` | and hands him back: `0` is a player character |

Those are the same three immediates — `0x00`, `0xB2`, `0xB3` — and the same
`0x7F`/`0x80` comparisons that `goldbox/dos_codec.py`'s `FIELD_83_87` note
records out of the DOS overlays. The split walks the party through
`movea.l $106(a3), a3`, Amiga `0x106` = DOS `0x104` = `heap_104`, and its
status test is `tst.b $10E(a3)` = DOS `0x10C` = `field_10c_10f`, which is the
"status test" the DOS note names. Nothing in `/program` reaches `0x084`,
`0x087` or `0x088`: the displacement search's candidates there are a `movep`,
a `negx` and a word store into another struct, which agrees with the DOS
reading that the first, fourth and fifth bytes have no site in any overlay.

#### `/Curse`: Amiga Curse's Pool of Radiance importer places the window

`/Curse` on Curse disk 1, file offset `0x02565E`, five consecutive one-byte
copies from the source record in `a3` into the Curse record in `a2`:

```
02565e: move.b $84(a3), $f6(a2)
025664: move.b $85(a3), $f7(a2)
02566a: move.b $86(a3), $f8(a2)
025670: move.b $87(a3), $f9(a2)
025676: move.b $88(a3), $fa(a2)
```

[`166-amiga-records-from-the-code.md`](166-amiga-records-from-the-code.md) has
Amiga Curse's `field_83_87` at `0x0F6`-`0x0FA` at shift 0, CONFIRMED from that
title's own unpacker, and `/Curse` tests `$f7(a2)` against `0x7F` and `0x80`
and stores `0xB2`, `0xB3` and `0` into it in some thirty places. So Pool of
Radiance's `0x085` is the same field as Curse's `0x0F7`, which is DOS `0x084`.

**`a3` is an Amiga record and not a packed DOS one**, which is what makes those
five copies place the window rather than merely repeat it. The same routine
copies `$a0(a3)` to `$11a(a2)`, and Curse `0x11A` is `sex` = DOS `0x119`; Pool
of Radiance's `sex` is DOS `0x09E`, which is Amiga `0x0A0` under the `+2`
shift. A DOS-layout source would have had `sex` at `0x09E` and `field_83_87` at
`0x083`-`0x087`. `$2e(a3)` → `$74(a2)` is race to race, `$30(a3)` → `$76(a2)`
the age word, and `$77(a3)` → `$ea(a2)` the eight thief percentages.

#### What the twenty specimens hold

| specimen | `0x084`-`0x089` |
|---|---|
| the six `CHRDATA<n>.sav` on disk 1 | `00 00 01 00 00 00` |
| two of the fourteen `.cha` | `00 00 01 00 00 00` |
| one `.cha`, a companion | `ff b2 00 00 00 00` |
| the other eleven `.cha` | `00 00 00 00 00 00` |

`0x089` is zero in 20 of 20, which is what a pad looks like. Placed through
the `+1` shift, the six records the game itself wrote read `00 00 01 00 00` at
DOS `0x083`-`0x087` — `goldbox/dos_codec.py`'s DOS constant byte for byte in
24 of 24 DOS records, the same corroboration Curse's own placement got. The
companion reads `0xB2` at `0x085`, the value `/program` `0x00B196` writes while
it builds a joining character's record, and `0xFF` at `0x084`, so the first
byte is not always zero either. `0xB3`, the other immediate `/program` stores
there, is the take-over value at `0x010290`.

#### The three bytes nothing reads convert too

`0x084`, `0x087` and `0x088` — DOS's `0x083`, `0x086` and `0x087` — have no
site in any of the four DOS overlays and none in `/program`, so nobody can say
what they are. That is a reason to **carry** them and not a reason to write
over them: `goldbox/dos_codec.py`'s `WRITE_CONSTANTS` wrote `00 00 01 00 00`
across the whole run, so the companion's `0xFF` became `0x00` on every route
out of an Amiga or DOS record, with nothing in the report.

They cross on `dos_codec.set_window_source`, an attribute the DOS reader hangs
the source's own run on and the DOS writer reads back, which puts them on every
route both ends of which have the window: DOS to DOS, DOS to Amiga, Amiga to
DOS and Amiga to Amiga, the Amiga three by way of
`goldbox.amiga_por.to_dos_record` and `from_dos_record`. The constant is now
what a source with no window of its own gets — a C64 record, which keeps the
control byte at `0x0B8` and the share at `0x0FA` and has nowhere for the rest.

**They are deliberately not a neutral field.** `goldbox/neutral.py`'s
vocabulary names the *thing* a character has, and no name exists for these;
and `neutral.Writer.finish` reports every neutral field a writer took nothing
from, so declaring them would put three bytes no engine reads on the drop list
of every conversion to the C64 — a reported loss where there is nothing a
player could lose.

**What the `0xFF` is, is still UNKNOWN**, and it is the only non-zero any of
the three has shown in twenty Amiga specimens and twenty-four DOS ones. The
specimen holding it is a `.cha` found on a save disk, so it has no chain of
custody; what would name the byte is a differential in the running game, a
character saved before and after whatever sets it, and nobody knows what that
is. The conversion no longer has to know.

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
session, Kickstart 1.3, the untagged three-disk rip). `amiga/adfedit.py` (scratch, deleted)
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
image currently in the drive highlighted; `amiga/pod/swap.sh` (scratch, deleted) assumes that.
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

`amiga/pod/probe.py` (scratch, deleted) builds the payload and installs it,
`amiga/pod/cycle.sh` drives one probe end to end, and the screenshots are
`amiga/pod/R*.png` (scratch, deleted).

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
TROND was added to the party** in the earlier session. `tests/amiga/test_amiga.py`
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
| P3 | a 484-byte record built by `goldbox.amiga_pod.PodWriter` from named fields and nothing else | every field back: `WRITTEN`, `FEMALE 33 YEARS`, `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`, `HIT POINTS 55/77`, `EXPERIENCE 10000`, `STR 18 INT 17 WIS 16 DEX 15 CON 14 CHA 13`, `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`, `STATUS: OKAY` |

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
the combat-icon heads, holds exactly 29 items**. So R1's ramp made PoD ask
`CHEAD.TLB` for item −1: `0x0B6`–`0x0C7` includes combat-icon data, not
inventory. **Zero there is accepted** — every payload that loaded had
zeros from `0x0B9` up, including the 484-byte written one.

**What the loop costs and how it breaks.** Each probe is about three minutes:
rewrite the ADF, eject and re-insert DF0 so the Amiga re-reads it, `ADD
CHARACTER` → `POOLS` → `ADD`, `VIEW CHARACTER`, screenshot, `REMOVE CHARACTER`.
Notes for whoever runs the next one:

* **PoD is driven by first letters and Return** — `a`, `p`, `v`, `r`, `y`, `e`.
  FS-UAE's arrow keys reach its own menu and not the Amiga, so under FS-UAE the
  picker's cursor cannot be moved and **the payload goes in the file the picker
  lists first**, which on this disk is `Save/TROND.pc`. **Under WinUAE the
  cursor keys do move it**, sent with `KEYEVENTF_EXTENDEDKEY` — one `DOWN` went
  from `TROND` to `PAINE` on 2026-09-07, so any row can be reached now and a
  payload no longer has to go in the first file
  (`docs/206-three-amiga-questions.md` §3). The `*` in that list marks a name
  matching a party member, and the red name in the party roster is the cursor
  there.
* **Never press Up at the top of an FS-UAE menu list.** The cursor leaves the
  list and lands on the window's `X`, and Return there quits the emulator. That
  is what killed one session; it looked like a crash and was not.
  `amiga/pod/df0.sh` (scratch, deleted) navigates by Down-then-Up from a clamped bottom and
  tracks which disk is in DF0 in `.df0state` so it can move by an exact delta.
* The DF0 submenu opens on **whatever is in the drive**, and the main menu's
  highlight is wherever it was left, so no fixed key sequence reaches it —
  screenshot after `F12` if anything looks wrong.
* **Start every probe with an empty party.** `VIEW CHARACTER` shows whichever
  character the cursor is on, and a failed `ADD` leaves the cursor on the
  previous one.
* **`e` on the party menu is `EXIT FROM GAME`**, not the picker's `EXIT`.
* **`ADD` itself writes nothing to the save disk**, corrected 2026-09-07. This
  line used to say PoD writes the character back when it is added, from a
  `THIEFTEST.pc` that appeared in the picker one probe after `THIEFTEST`
  joined. It did not reproduce under WinUAE, which *does* hand the ADF back to
  the host: a disk taken through `ADD CHARACTER` → `POOLS` → `ADD` came off the
  guest byte for byte identical to the one that went in
  (`docs/206-three-amiga-questions.md` §3). So whatever wrote that file was
  something later in that FS-UAE session rather than `ADD`, and the practical
  advice stands for a different reason: PoD's own emitted `.pc` cannot be
  harvested this way, and rewriting the host file between probes is safe.
* FS-UAE 3.1.66 died once with `*** buffer overflow detected ***`. Restarting it
  into the same Xephyr and rebooting the game is the recovery.

---

**What is still missing**, and none of it blocks the writer: the five saving
throws at `0x083`, the eight thief skills at `0x08B`, and the class bitmask at
`0x0B7` are all PROBABLE from the twelve specimens and none appears on the
character sheet, so no probe can promote them; the appended item data that
takes a record from 484 to 524 bytes is
undecoded; and spells are untouched.

### 2.5 End to end: a C64 character in the Amiga party

**The thing Donald asked for, run.** `LADY KATHERINE` off `PORSAVE11.D64` (scratch, deleted)
-- a half-elf magic-user/thief the player rolled on the C64 -- converted with
`tools/amiga/toamiga.py`, installed as `Save/TROND.pc` on a copy of disk 3, added
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

Screenshots are `amiga/pod/v_*.png` (scratch, deleted); `amiga/pod/install_pc.py` (scratch, deleted) puts a
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

**The `.pc` files exist; the ADF does not.** `tools/amiga/toamiga.py` writes a whole
party into a directory, and §2.5 got one of them into the game by *replacing*
an existing file's contents on a copy of disk 3 — which is what
`amiga/adfedit.py` (scratch, deleted) can do and all it can do. Authoring a disk, or adding
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
| race | `0x072` — CONFIRMED | `0x02E` — CONFIRMED | `0x02E` — CONFIRMED | `0x058` — CONFIRMED (`HALF-ELF`, `DWARF`). `ELF` 0, `HALF-ELF` 1, `DWARF` 2, `GNOME` 3, `HALFLING` 4, `HUMAN` 5 — a **different table again** from the C64's (`goldbox/c64_port.py`) |
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
| portrait head/body | `0x0FE`/`0x0FF` — CONFIRMED | UNKNOWN | UNKNOWN | `0x0B9`/`0x0BA`, unused: PoD draws no sheet portrait |
| armour class | roster `0x10F` — PROBABLE | `0x02D`-adjacent — PROBABLE | — | `0x0B3`, stored `60 - AC` — CONFIRMED. It is the **base**: all twelve read 10, and the sheet's number is that adjusted for dexterity and equipment (§2.4) |
| unarmed damage | — | — | — | count `0x0AD`, sides `0x0AF`, bonus `0x0B1` — CONFIRMED (`173D175-79`); all twelve read 1d2 |
| movement | roster `+0x11` — PROBABLE | UNKNOWN | UNKNOWN | `0x088` — CONFIRMED (`MOVEMENT 136`, and `12` when `0x192` said 99); all twelve read 12 |
| inventory | `0x120`, 16 × 16 bytes — CONFIRMED | separate `.ITM`, 63 B/item | separate `.itm`, 65 B/item | appended past 484 bytes; UNKNOWN and **not** the writer's blocker. `0x0B6`–`0x0C7` includes combat-icon data, and `ERROR: INVALID ITEM` is the graphics library's (§2.4) |
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
| Are PoD's saves inside the `.dax` / `GLIB` container scheme? | **No.** They are ordinary AmigaDOS files in a `Save` drawer. | CONFIRMED — `amiga/adf.py` (scratch, deleted) reads them |
| What filesystem? | **OFS.** All three PoD ADFs are `DOS\0`, FFS bit clear, root names `POD 1/2/3`. | CONFIRMED |
| Can we read one already? | Yes. `amiga/adf.py` (scratch, deleted) walks the hash chains, follows extension blocks and extracts every file. | CONFIRMED |
| Can we **write** one? | Yes, for Pool of Radiance: `#36 (Write an Amiga disk image, not just the character files)` writes a fresh 880K `POOLSAVE.ADF` carrying a converted party and no game code, without `amitools` — `wish` ships as a PyInstaller binary and does not take dependencies lightly. `docs/191-the-amiga-save-disk.md` has the format and the WinUAE proof. Pools of Darkness, the subject of this table, is not built yet. | CONFIRMED for Pool of Radiance |
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
| 0 | **Confirm §1 independently.** Re-extract both PoD and PoR ADFs, re-derive the file inventory and the twelve `.pc` constants. | a reproducible script in `tools/` | no | an hour | the numbers in §1 come out again |
| 1 | ~~**Read the `.pc` loader.**~~ **DONE** (#148 (The Amiga port's tools are gone, and phase 1 still needs the disassembler)). `tools/amiga/m68dis.py` was rebuilt for it. 404 bytes, then 20 per item and 10 per effect; AmigaDOS `Open`/`Read`; the only checks are the read lengths and an `'I'` on each item. | §1.16 | no | done | run — see §1.16 |
| 2 | ~~**The assumption test (§2.2), cases A–D.**~~ **DONE.** | A loads; **B loads too** | yes | one session | run — see §2.2 |
| 3 | **An OFS ADF writer.** Round-trip: read every file off disk 3, rebuild an image, compare file contents byte for byte; then boot it in FS-UAE and let PoD list the twelve characters. | `goldbox/adf.py` (writer) with tests that read the player's own disks, never a committed image | yes, once | a week | PoD's `Add Character → Pools` shows all twelve names off our image |
| 4 | ~~**Decode the `.pc` record.**~~ **Done for everything the sheet shows.** The ramp of §2.3 found the numbers; the plausible-value probe of §2.4 found the four enums, current hit points and the seventh level slot. What is left is undecoded rather than blocking: saving throws, thief skills, the class bitmask, the portrait indices and the appended item data. | `goldbox/amiga_pod.py`, plus `tests/amiga/test_amiga.py` asserting the ramp offsets, the written record and the twelve real files | yes, repeatedly | done | every named field decodes to a legal AD&D value across all twelve |
| 5 | **Resolve the pointers.** Determine whether the `0x00`–`0x5F` addresses are re-linked on load. Two ways: read the loader (phase 1 may already answer it), or write a `.pc` with those longwords zeroed and see if PoD still loads it. | a ruling: don't-care, or must-be-plausible | yes | a session | a zeroed-pointer `.pc` loads and its sheet is unchanged |
| 6 | ~~**The map and the writer.**~~ **DONE.** `goldbox.amiga_pod.write_pod` takes a `NeutralCharacter` — the one record every codec now shares, since #25 (One neutral character record, with a codec per format) — and `to_pc` emits the 484 bytes. `Report.unaccounted` is empty on every character of the player's own party, so there is no "template" category. `pod_write_field_disposition()` names what becomes of every neutral field, and `tests/amiga/test_amiga.py` fails if a field appears in one and not the other. | `goldbox/amiga_pod.py`, `tools/amiga/toamiga.py` | no | done | run |
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
| **Portraits** | C64 `0x0FE`/`0x0FF` name `HEADnn`/`BODYnn` files on the C64 disks. PoD has no character-sheet portrait on either port; `CHEAD.TLB` / `CBODY.TLB` are combat-icon art. | drop it: the target has no sheet face. |
| **Derived combat values** | The C64 roster block (`0x10E` THAC0, `0x10F` AC, `0x119` current hp) is a **cache**, and its update rule is not "on load" — armour class refreshes only when equipment changes, so it can be stale even in a healthy save. | recompute for the target from base values, always |
| **Items** | The C64 stores 16 bytes per item, an id into that title's `ITEMNAMES`. DOS and Amiga store 63–65 bytes per item **carrying the name as text**. And a Silver Blades item id and a Pools of Darkness item id are two different games' tables. | re-encode from named fields, and **check the tables agree before assuming any id means the same thing** |
| **Memorised spells** | C64 spell ids run 1–56. Pools of Darkness has cleric spells to level 7 and mage spells to level 9, so its id space is larger and the mapping is certainly not identity. | map by name, or drop and let the player re-memorise |
| **Experience** | The C64 field is **3 bytes** — 16 777 215 maximum. Pools of Darkness characters exceed that. | the target field is wider; carry the value up, and expect a C64-sourced total to look low rather than wrong |
| **Race and class codes** | `goldbox/c64_port.py` already documents that the race table changes per title on the C64 alone (human is 7 in Pool of Radiance, 6 in Silver Blades). PoD's Amiga table has not been read. | read PoD's own table before writing a race byte |
| **Copper, silver, electrum and gold** | only platinum (`0x04C`), gems and jewelry have been located in the `.pc`. R7 was the probe for the lighter coins and did not finish; `0x048` and `0x04A` are zero in all twelve and are the obvious candidates. | reported, with the total, so the player knows what was left on the counter |
| **Unarmed damage** | not a loss so much as a category error: the C64's damage triple already includes the readied weapon, and PoD's item nodes carry the same information the writer emits. | write the unarmoured `1d2`, which is what all twelve genuine records hold, and let PoD derive the rest from the item nodes. §2.5 shows it coming out at `1D2+1` with no items; that the game applies a worn item's bonus is argued from the recompute, not run, because probe P3 carried none |
| **Armour class** | **superseded by #635 (Read what a Pools of Darkness armour-class base other than 50 means, so the Amiga conversion writes it instead of refusing)**: the *stored base* (`armour_class_base`) is not a category error, because both engines seed the current armour-class calculation from that one byte, so it is real state and the writer copies it through. Only the *current, post-modifier* value (`armour_class`, the byte at `0x187`) stays a category error — PoD recomputes it from the base and whatever is readied, on every load | copy `armour_class_base` from the source and let PoD derive `armour_class` itself. §2.5 shows it coming out at `AC 8` with an unarmoured base and no items |
| **Everything Silver Blades knew and Pools of Darkness does not** | quest flags, position, journal entries | not converted, and not wanted — see §3 |

---

## 8. Blockers, honestly

1. ~~**There is no Amiga Secrets of the Silver Blades on this machine.**~~
   **Gone — the disks arrived 2026-08-25**, in
   `amiga/goldbox/Secret_Of_The_Silver_Blades/` (both sides, 901120 bytes
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
   items: it is the `GLIB` library reader asking `CHEAD.TLB` — 29 combat-icon
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
   unattended, over `winvm` and `tools/amiga/winuae.ps1` — and that path has been run
   for real (`#91 (Configure WinUAE in the Windows VM so an Amiga title can be driven unattended)`), reliably as far as its own §8. What it has **not** been run
   against is *Pools of Darkness* or *Secret of the Silver Blades*
   specifically — everything exercised so far is Pool of Radiance. Phase 4 of
   this plan still does not need it: differential *saves* are files, and the
   emulator is only needed to produce them. A PoD automapper is still a
   separate project and out of scope here, but it is no longer blocked on a
   missing debugger — it is blocked on nobody having pointed this one at PoD.
   Kickstart ROMs are present in the `kickstarts` registry entry's folder (1.3 and 3.1; `$WISH_KICKSTARTS`)
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
