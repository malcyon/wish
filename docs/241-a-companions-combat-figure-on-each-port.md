# A companion's combat figure on each port: who joins, and what each join writes

What the games themselves do when a companion joins a Curse of the Azure Bonds
or Secret of the Silver Blades party, read from the player's own C64 disks, the
DOS archive's `GAME.OVR`/`START.EXE` and the Amiga `/Curse` and `/Secret`
executables, with no emulator run. It is the static half of the work on
converting a companion's combat figure to and from the C64, and it sets the
rules a converter must keep: which companions a player can have, where each
port keeps his figure, and what the C64 draws for him. Grades are
`docs/50-experiments.md`'s. Every C64 address is a run-time address: `DUNGEON`,
`CAMP`, `COM.PREP` and `INIT` run at `$0800` and `LIBRARY` at `$2DC8` in both
titles, whatever their PRG headers hold.

## In one paragraph

Only script opcode `$36` (`ADDNPC`) puts a monster in the party, in both titles
and on both the C64 and DOS. Curse has nine `ADDNPC` sites for seven monsters
and Silver Blades five, the same sites in the DOS scripts. The one joinable
monster whose name is shared with another `MON` file is renamed by its own
script and removed again before the player can save. All five Silver Blades
companions are story companions with a nonzero `0x0E5`. DOS and Amiga Silver
Blades write the bare `MON` id as the companion's picture, and swap three of
those ids for another picture only in the demo. The C64 join never writes
the 36-byte icon. The icon a companion fights with is whatever his party slot
held before he joined: the creation default, or the icon of the member who last
used the slot. Every companion a C64 Curse or Silver Blades save can hold has a
source for his picture, so the converter needs no question answered.

## Who can join

**Opcode `$36` is the only join.** CONFIRMED from code in both titles. Its
handler (Curse `DUNGEON $28E2`, Silver Blades `$281A`) takes the highest free
party slot below 8 (`$03FD`, set by `$1C0B`), loads `MON` operand 1 into
`$7C00`, sets `$7D0C = $80`, clears `0x0D1`-`0x0D2`, stores `0x0B8` = operand 2
halved `| $80`, runs `LIBRARY $3FB6` and `$3918` (Silver Blades `$3804`,
`$32C1`) and saves the slot through `LIBRARY $45F8` (`$2F2B`).

**Opcode `$0B` is not a join.** CONFIRMED from code. `$1C71` (Silver Blades
`$1B86`) stores into `$03FE`, the first free slot from 8 upward, which is
the enemy side of the combat roster. `COM.PREP` draws those slots from the
script's `$7EB3,X`, and the handler ends by storing there (`$1D10`). The
`ORA #$80` into `0x0B8` at `$1CA3` marks a loaded monster as engine-driven.
`docs/232-the-c64-control-byte-per-title.md` lists this site as "join, morale
untouched"; for Curse and Silver Blades that row describes the encounter
loader, and nothing it loads enters slots 0-7. Pool of Radiance's `$1AF6` and
the Gateway and Krynn sites in that row were not reread here.

**The joinable set.** CONFIRMED by a control-flow walk of every area script
(`tools/areas/eclsweep.py`'s `walk`, the reading `ecllist.py --walk` prints)
on both ports, plus a scan of every byte the walk does not reach for one that
decodes as an `ADDNPC` with variable or immediate operands. The walk reaches
134,140 of Curse's 138,268 C64 script bytes and 131,936 of Silver Blades'
137,704. The scan finds two such bytes in Curse `ECL35` (`$9668`, `$99B0`),
inside data, and none in Silver Blades.

| Title | Script (C64; DOS block where it differs) | Statement | `MON` id | Story byte `0x0E5` in the C64 `MON` file |
|---|---|---|---|---|
| Curse | `ECL11` | `$8D0F`, `$8D14` | `$16` ALIAS, `$17` DRAGONBAIT | `$16`, `$17` |
| Curse | `ECL12` | `$9010`, `$9015` | `$16`, `$17` | `$16`, `$17` |
| Curse | `ECL1E` (DOS block `$52`) | `$801F`, `$8024`, `$8029` | `$55`, `$58`, `$5A` | `$FF` |
| Curse | `ECL31` (DOS `$8BCE`) | `$8BCA` | `$3B` AKABAR | `$3B` |
| Curse | `ECL42` | `$8A04` | `$43`, renamed and removed (below) | `$FF` |
| Silver Blades | `ECL04` (DOS block `$03`, `$805C`-`$8066`) | `$8062`, `$8067`, `$806C` | `$33` CAPET, `$32` SIEGLINDA, `$34` AVEROES | `$4C`, `$4D`, `$42` |
| Silver Blades | `ECL32` | `$886C` | `$4D` VALA | `$4D` |
| Silver Blades | `ECL44` | `$8168` | `$4E` SIR DERIC | `$4E` |

Every `ADDNPC` in both titles passes morale 100 (`#$64`). No script joins
`MON57` (WORG). A party member with WORG's picture is not a C64 join.

**No script renames or edits a companion afterwards, except `ECL42`.**
CONFIRMED for the area scripts. The walked statements that write a record
byte (`$7C00`-`$7DFF`) are listed below, and only `ECL42` writes the name.

| Site | What it writes |
|---|---|
| `ECL02 $8486` | `0x0B8` of a monster in combat slots 10 and up |
| `ECL22 $87EF` | Zero at an offset that the `SPELL` statement for spell 22 returns, in the member it finds: a memorised-spell entry, not the name |
| `ECL21`, `ECL23` | `0x020` plus an index, `0x0A7`, `0x0C3`-`0x0C4`, `0x0EB` |
| Silver Blades `ECL10`, `21`, `22`, `31`-`34` | `0x0C3`-`0x0C6`, `0x019`, `0x01B`, `0x076`, `$7D00`/`$7D19` |
| `ECL32 $8C40`, `ECL33 $94FF` | Read the name into a buffer, write nothing to the record |
| `ECL42 $8A1F` | A new 8-character name, then `0x0B8 = $B2` and `$7D0C = $80`, written back by `LOADCHAR` with bit 7 set |

The player cannot rename one either. PROBABLE: the C64 camp `ALTER` bar
holds `ORDER`, `DROP` and `ICON` in both titles, and no `NAME`.

## The duplicate-name monsters

**Curse's DARK ELF LORD (`$2B`, `$30`) and RAKSHASA `$49`, and Silver
Blades' ANCIENT DRAGON (`$06`, `$08`) and FROST GIANT (`$0E`, `$62`), cannot
join.** CONFIRMED by the walk above.

**RAKSHASA `$43` joins, but never reaches a save.** PROBABLE. The `ECL42`
statements at `$8A00`-`$8B91`:

1. `ADDNPC` of `$43` with morale 100, on one of the three answers to the
   menu at `$88ED` (the second target of the `ONGOTO` at `$8907`).
2. `$8A8F` finds him by his `MON` name. The script stores a different
   8-character name, `0x0B8 = $B2` and `$7D0C = $80`, and writes him back.
3. It loads three enemy groups (opcode `$0B`, `MON43` among them) and runs
   `COMBAT` at `$8A61`.
4. After the fight it looks for him again under the new name. If he is found,
   `$3E` (`DUNGEON $1671`) clears `$7D00` and `$7C00` and saves the slot, which
   frees it. That happens before the fight result is tested at `$8AC7`, so on
   a win, a loss and a flight alike.

Between the join and the removal there is no prompt and no point where the
player can save. The grade is PROBABLE, not CONFIRMED, because it assumes
the script resumes after a fight the party flees. The `$7EC7 > 128` test at
`$8AC7` exists to handle that case, but no run has shown it. To settle it,
flee that fight on the C64 and read the save: a party with no member at the
new name confirms; the renamed member still present refutes.

So over the companions a save can hold, every `MON` name is unique. No
signature bytes are needed to tell a pair apart.

## What each port's join writes as the picture

| Port | Title | Join | Writes | Party load reads | Grade |
|---|---|---|---|---|---|
| DOS | Curse | `GAME.OVR 0x36D3` passes operand 1 to `0x1ECAE` | `0x126 = MON id` at `0x1ECE5`, then `CPIC` block `MON id` | `0x126` | CONFIRMED |
| DOS | Silver Blades | `GAME.OVR 0x3E52` passes operand 1 to `0x25EB0`; operand 2 halved `\| $80` goes to `0x0FF` at `0x3E9C` | `0x12B = MON id` at `0x25EE7`; in the demo only, the `CPIC` load uses `$32`→`$4D`, `$33`→`$4C`, `$34`→`$42` (`0x25EEC`-`0x25F0E`) | `0x12B`, unmapped (`0x265FD`) | CONFIRMED for the writes and the read |
| Amiga | Silver Blades | The `/Secret` join routine, past its room test at `0x276BA` | `$C6 = MON id` at `0x276E6`; the same three swaps under global `g56c7` (`0x276EA`-`0x27712`) | `$C6`, unmapped (`0x27B54`, `"CPIC"`) | CONFIRMED for the writes and the read |

**The swap is the demo's.** PROBABLE. DOS `START.EXE 0x0614` stores
`[0x67E9] = 1` only when the title menu's answer is `D`, and `START.EXE`
holds `Play Demo` at `0x257`. `GAME.OVR 0x10793`,
its only writer there, resets it to 0. Amiga `/Secret 0x178B4` stores `g56c7` from the same `D`
test, and the executable's menu text at `0x17A0D` reads `Play Demo Quit`. The only
other Amiga writer, `0x1D944`, clears it. To settle it, take
a DOSBox-X memory image during normal play and read `DS:0x67E9`: 0 confirms,
and a nonzero value refutes.

**So in normal DOS play, SIEGLINDA, CAPET and AVEROES are saved as pictures
`$32`, `$33` and `$34`.** CONFIRMED for the bytes. `CPIC1.DAX`, Silver Blades'
only `CPIC` file, has no block `$32`, `$33` or `$34`. It does have `$42`,
`$4C`, `$4D` and `$4E`.

**What the player sees then is unmeasured.** SPECULATIVE: the DOS game shows
those three companions with no figure, or with a figure left over from another
slot. To settle it, join SIEGLINDA in DOS Silver Blades (`ECL04`, block
`$03`), save and reload, start a fight and photograph her figure. Then repeat
at the join without reloading. If the reload loses the figure the join drew,
that is a bug in the DOS game, and it goes to `goldbox-bugs.md` with the
player's route.

**The C64 Silver Blades story byte is the demo's table.** CONFIRMED by
comparison. The `MON` files' `0x0E5` values (`$4D`, `$4C`, `$42` for `MON32`
to `MON34`) are exactly the DOS and Amiga demo's swaps. `$4D` is both
SIEGLINDA's story byte and VALA's `MON` id, so a story byte does not identify
the `MON` file.

**What this means for the converter.** A C64 Silver Blades companion
converted to DOS or the Amiga gets the picture his own DOS join writes: his
`MON` id. That is not his story byte. The `MON` id comes from the name
match, because `$4D` alone cannot tell SIEGLINDA from VALA. Going the
other way, the C64 story byte is written as his C64 `MON` file holds it, as
the plan on WISH-388 (A companion converted to or from the C64 loses his
combat figure) already requires.

## The C64 icon a companion fights with

**The join never writes the icon table.** CONFIRMED for absolute and
record-page stores; PROBABLE for the screen and text pointers. A static walk
of every `JSR`, `JMP` and branch from the `ADDNPC` handler through `DUNGEON`
and `LIBRARY` closes on 1,342 instructions in 84 routines in Curse, and 1,357
in 87 in Silver Blades. Nothing in it is undecodable, and it leaves the two
files only for the KERNAL's file calls (`$FF93`-`$FFD5`).

| Stores in the join's call graph | Target | What it is |
|---|---|---|
| None, absolute or indexed | `$4DE0`-`$4EFF` | The icon table |
| `($3F),Y` | `$4F00 + slot*$100` (`LIBRARY $32B1`, Silver Blades `$2ECB`) | The record page |
| `($4C),Y` | `$5B00 + slot*$100` (`LIBRARY $32BB`) | The item page |
| `($41),Y` | `$6700 + index*$20` (`LIBRARY $32D9`) | The roster block |
| The other `($4C)`, `($4E)`, `($A3)`, `($A7)` stores | Screen rows, colour rows and the text buffer | Printing (`LIBRARY $2E3C`-`$309A`, `$4400`-`$4425`, `DUNGEON $1585`) |

**Only four places address the icon table.** PROBABLE. A byte sweep of
every program file on all sides of both titles looked for immediate `#$E0`
and `#$4D` within 16 bytes of each other and for any absolute operand at
`$4DE0`-`$4EFF`. It is complete for those two forms; a pointer built any
other way would not show:

| Site | What it does |
|---|---|
| `INIT` | Seeds the eight entries |
| `GEN` (Curse `+0x1270`, Silver Blades `+0x1EE3`) | Creation and adding a character |
| `CAMP` (Curse `$0F67`, Silver Blades `$0F23`) | `ALTER` > `ICON` (Curse `$0940`-`$098B`), and the loop at `$0A90`/`$0B28` that copies all eight slots out to `$8000` with their icons and back |
| `COM.PREP` | Reads the table to draw the party |

The sweep found four other absolute operands in that range, in `BOOT`,
`COMBAT`, `SPELLN64` and `BODY04` for Curse and in `SECRET BLADE` for Silver
Blades. They run in other memory maps and were not read.

**So a departing member leaves his icon in the slot.** PROBABLE. Neither
`DROP`, `REMOVE` nor the script opcode `$3E` (`DUNGEON $1671`) is among
those four sites. A companion who joins a slot no member has used draws
the creation default. One who joins a slot a member left draws that member's
icon. To settle it, on the C64 drop a member whose icon was changed with
`ALTER` > `ICON`, join a companion into that slot and fight: the old member's
figure confirms, and the default figure refutes.

**The seed is the default icon in both titles.** CONFIRMED. Curse `INIT`
copies 36 bytes from `$0B0A` (payload `+0x30A`), and Silver Blades `INIT`
from `$0C1A` (payload `+0x41A`). Each equals
`IconParts.load(<title's side 1>).default_icon()` byte for byte.

**`$7F12` is the side the engine expects in the drive.** CONFIRMED from code.
`LIBRARY $4561`-`$459F` retries a failed load. It prints message `$3F`, then
`$7F12` as a number (`$457E`, `JSR $30BB`), then message `$40`. `LIBRARY`
holds `DISK ERROR` and `INSERT SIDE ` at `+0x7A6` and `+0x7BB`. `LINKER`
(Curse side 1, at `$1220`) copies `$7F12` to `$4BEE` and sets it to 1. `INIT`,
`GEN`, `CAMP` and `POST.COM` also store it.

So `COM.PREP $1490`-`$14B1` draws ALIAS and DRAGONBAIT with their own
`COMPIC16`/`17` only while the engine expects side 3, and AKABAR with
`COMPIC3B` only while it expects side 5. Those are the sides that hold the
files. The test reads `0x0E5` at `$1498`; Silver Blades' copy of the routine
is at `$1506`, reading it at `$150E`.

## Every C64 companion has a source for his picture

The C64 code that writes `0x0B8` with bit 7 set, by title:

* Opcode `$36` gives a companion. His `MON` file is one of the joinable set
  above, and the name match identifies it.
* Opcode `$0B` loads an enemy into a combat slot from 8 upward.
* `ECL42` and `ECL02` write combat-only records.
* Pool of Radiance companions and animated characters are kept out of
  Curse and Silver Blades. PROBABLE: `ADD CHARACTER` prints `CAN'T ADD NPCS`
  (Curse `SPELLE20`, Silver Blades `GEN`), but its test was not read at the
  instruction level. To settle it, find the branch to that message and check
  that it tests `0x0B8` bit 7.

`docs/232-the-c64-control-byte-per-title.md` records no other writer in
either title.

| Title | Companions a save can hold | Picture source on the C64 |
|---|---|---|
| Curse | `$16`, `$17`, `$3B` | Story byte |
| Curse | `$55`, `$58`, `$5A` | Name match only |
| Silver Blades | All five | Story byte and name match |

So no C64 companion a player can have lacks a source, and no question goes
to Donald.

**One case the game cannot produce.** A C64 save that an earlier Wish wrote
for a converted companion holds an identity digest at `0x0E6`, not a picture.
A reader that trusts any `0x0E6` other than `$FF` reads that digest as a
picture. The game does not produce this case; it reaches a player who
converted a companion with that earlier Wish.

## How it was read

Each finding is reproducible with the repository's tools, against the
player's disks through `gamedisks.yaml`:

| Finding | Tool |
|---|---|
| The `ADDNPC` sites | `tools/areas/ecllist.py <title> <ECLnn> --walk` for each script, and `eclsweep.load_port` for the DOS blocks, which share the C64 opcodes |
| C64 handlers | `tools/c64/overlay.py dis` |
| DOS sites | `tools/dos/dosdis16.py`, and `tools/dos/dosovrmap.py callers` against `START.EXE` expanded by `tools/dos/unexepack.py` |
| Amiga sites | `tools/amiga/amigarecordrefs.py`, `amigaglobal.py refs 56c7` and `amiga68k.py disasm` |
| `CPIC` block lists | `goldbox.dos_savegame.dax_index` |
