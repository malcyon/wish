# Where a paladin's lay on hands lives, on every port

A paladin may lay on hands once a day. This page gives, for each port of
Curse of the Azure Bonds, Secret of the Silver Blades and Pools of Darkness,
where the engine records that today's use is spent and how it gets it back.
It also gives the mapping a converter needs between every pair of ports. It
is the answer to
#628 (The neutral vocabulary has no field for a paladin's lay-on-hands uses, so a converted paladin loses them).

The readers are [`tools/dos/layonhands.py`](../tools/dos/layonhands.py),
[`tools/amiga/amigalayonhands.py`](../tools/amiga/amigalayonhands.py) and,
for the C64,
[`tools/c64/curedisease.py`](../tools/c64/curedisease.py).
[`tests/records/test_layonhands.py`](../tests/records/test_layonhands.py) pins
every address below against the player's own executables. It holds 9 tests,
which all skip with no disks. Everything was read statically. No emulator was
run.

## The answer

| title | C64 | DOS | Amiga |
|---|---|---|---|
| Curse | record `0x013` (1 = can heal, 0 = spent), **and** an effect-array row with id **140**, duration `$C1`, magnitude `$C1` | an effect node with id **140**, 1440 minutes, value 0, flag 0; no record byte | a node with id **140**, 1440, 0, 0; no record byte |
| Silver Blades | `0x013` and a row with id **109**, `$C1`/`$C1` | a node with id **109**, 1440, 0, 0 | a node with id **140**, 1440, 0, 0 |
| Pools of Darkness | no C64 port (`goldbox.c64_port.GAMES` has none) | a node with id **109**, 1440, 0, 0 | a node with id **140**, 1440, 0, 0 |
| Pool of Radiance | no heal | no heal | no heal |

Every cell is CONFIRMED from the engine's own code, except where the Amiga
duration unit is stated as minutes, which is PROBABLE (see "What stays
open").

**In DOS and on the Amiga the spent state is only the node.** HEAL adds it,
the character sheet offers HEAL only while the paladin has no node with that
id, and the handler for that id does nothing. The use comes back when the
clock removes the node, one day after it was added. Nothing else creates or
removes the node.

**On the C64 the state is two things.** HEAL decrements `0x013` and adds the
row. The sheet hides HEAL while `0x013` is 0. When the row expires in camp,
the id table sends it to a reset that writes `0x013` = 1. Record `0x013` and
the row are #600 (The neutral record has no field for an effect's remaining duration or a paladin's cure-disease uses, so a converted character loses both)'s
stage 7 read, pinned by `tests/records/test_curedisease.py`. `$C1` is one day:
unit 3 (`goldbox.effects.DURATION_UNIT_NAMES`), count 1.

**Amiga Silver Blades and Amiga Pools of Darkness push Curse's id, 140, where
DOS and the C64 push 109.** In both of those Amiga executables, slot 109 of
the effect handler table holds an empty handler (`rts`), which is the same
empty slot the DOS build has there. The table ends before 140: Silver Blades
fills ids 1-113 and slot 120, and Pools of Darkness fills up to 127 without
117. The heal routine and its gate were left with Curse's number. The two
sites agree with each other, so a player on the Amiga sees HEAL once a day as
usual. It is a porting quirk rather than a bug, and it only matters to a
converter.

## What a converter needs

The neutral record needs one number: **minutes until HEAL comes back**, where
0 means he can heal now. Every port stores a spent use as a timer with one
day on it, and nothing else. The C64's `0x013` does not need a separate
neutral field: the one C64 routine that clears it adds the row in the same
routine, and apart from `GEN`'s seed when he is created or joins the party,
the only write that sets it runs when the row expires.

**Reading.**

| source | spent when | minutes left |
|---|---|---|
| C64 Curse / Silver Blades | the paladin owns a row with id 140 / 109 | the row's duration byte, unit x count |
| DOS Curse / Silver Blades / Pools of Darkness | his chain has a node with id 140 / 109 / 109 | node bytes 1-2, little-endian |
| Amiga Curse / Silver Blades / Pools of Darkness | his chain has a node with id **140** in all three | node bytes 2-3, big-endian |

A C64 paladin with `0x013` = 0 and no row is a record the engine cannot
recover: no row will ever expire to reset the byte. Our own writer produced
this state before #626 (A paladin written into a C64 Curse or Silver Blades save, or renamed there in the editor, loses CURE and HEAL from his sheet, because the name field covers the two bytes that hold them),
and the C64's own ADD CHARACTER TO PARTY re-seeds it to 1. Read it as "can
heal now".

**Writing.**

| destination | can heal now | spent, `m` minutes left |
|---|---|---|
| C64 Curse / Silver Blades, paladin level `0x0CF` > 0 | `0x013` = 1, no row | `0x013` = 0, and a row with id 140 / 109, owner = his party slot, duration = `goldbox.effects.closest_duration(m, ...)`, magnitude `$C1` |
| C64, no paladin level | `0x013` = 0, no row (what `GEN` writes) | -- |
| DOS | no node | node `id, m & 0xFF, m >> 8, 0x00, 0x00` with id 140 / 109 / 109 |
| Amiga | no node | node `0x8C, 0x00, m >> 8, m & 0xFF, 0x00, 0x00` + next, id 140 in all three |

Two write details:

* **The C64 magnitude must have bit 7 set.** With bit 7 clear, the camp clears
  the row without running the reset, and the paladin never gets HEAL back.
  CONFIRMED (`CAMP $14DB` Curse, `$1314` Silver Blades).
* **The DOS and Amiga value byte must be 0, as the engine writes it, not
  `0xFF`.** Dispel Magic skips a node whose byte 3 is `0xFF` and treats any
  other value as the level to roll against
  (`docs/230-who-reads-a-dos-effect-node.md`). So a node written with `0xFF`
  would change how Dispel Magic treats his timer.

**The id per pair of ports, within one title** (conversions never cross
titles):

| title | C64 <-> DOS | C64 <-> Amiga | DOS <-> Amiga |
|---|---|---|---|
| Curse | 140 <-> 140 | 140 <-> 140 | 140 <-> 140 |
| Silver Blades | 109 <-> 109 | **109 <-> 140** | **109 <-> 140** |
| Pools of Darkness | -- | -- | **109 <-> 140** |

**An effect copied with the same id gets both Silver Blades and Pools of
Darkness directions wrong.** Take a paladin who laid on hands in DOS Silver
Blades today. With id 109 unchanged, he arrives on the Amiga with a node the
Amiga never tests, so he can heal again straight away. Going the other way,
an Amiga paladin's node 140 arrives in DOS with an id outside DOS Silver
Blades' table (1-113) and DOS Pools of Darkness' (1-126). DOS never tests that
id either, and a converter must never write such an id at all
(`docs/230-who-reads-a-dos-effect-node.md`).

**Cure disease needs no remapping.** Its timer has the same id on every port
of a title: Curse 141, Silver Blades 110, Pools of Darkness 110. It is 10080
minutes on DOS and the Amiga, and `$C7` on the C64. Only lay on hands
differs.

## How it was read

**DOS.** `tools/dos/layonhands.py` loads each `GAME.OVR` through
`tools/dos/dosaffectreads.py`'s finders, which locate `add_affect`,
`find_affect`, `remove_affect` and the handler table by instruction pattern.
Pools of Darkness loads through `GAME.EXE`. The probe finds the one
`add_affect` call whose duration is the immediate 1440, the one
`find_affect` caller that tests the same id, and that id's handler.

| | Curse | Silver Blades | Pools of Darkness |
|---|---|---|---|
| heal routine, and its `add_affect` | `0x2A734`, `0x2A806` | `0x2AF21`, `0x2AFF5` | `0x26BC3`, `0x26C90` |
| pushes: id, minutes, value, flag | 140, 1440, 0, 0 | 109, 1440, 0, 0 | 109, 1440, 0, 0 |
| writes through a far pointer in the heal routine | none | none | none |
| gate routine; record bytes it tests before `find_affect` | `0x2A64D`; `0x75`, `0x114`, `0x195` | `0x2AE3B`; `0x6C`, `0x11B`, `0x1A6` | `0x26ADA`; `0xAE`, `0x15B`, `0x1ED` |
| constant uses of the id | one `add_affect`, one `find_affect` | the same | the same |
| handler | `0x129B8`, empty | `0x145CA`, empty | `0x1DCCF`, empty |
| cure routine: id, record byte decremented | `0x2A849`: 141, `0x191` | `0x2B04B`: 110, `0x6D` | `0x26CE6`: 110, `0xAF` |

The three decremented cure bytes are the three offsets `goldbox/dos_port.py`
already names `paladin_cures`, an independent check that the probe found the
right routines. The DOS clock ages every node by elapsed minutes and removes
it at zero. `docs/162-spc-permanence.md` measured that with Bless.

**Amiga.** `tools/amiga/amigalayonhands.py` reads `/Curse`, `/Secret` and
`/Pools of Darkness` from the registry's Amiga disks. It finds
`clr.w -(a7) / clr.w -(a7) / move.w #1440,-(a7) / move.w #id,-(a7) /
move.l An,-(a7) / jsr d16(a4)` and checks that the callee stores the id at
node `+0` and the duration at `+2`. It finds the `find_affect(id)` call and
checks that its callee walks the paladin's chain comparing node byte 0.
Then it reads the handler table from the dispatcher that `remove_affect`
calls, and the start-up code that fills it. Addresses are file offsets into
each executable.

| | Curse | Silver Blades | Pools of Darkness |
|---|---|---|---|
| heal routine; `jsr add_affect` at; `add_affect` | `023A9A`; `023B54`; `00F176` | `024E30`; `024ED8`; `012DAC` | `023DA0`; `023E62`; `012FD4` |
| pushes: id, minutes, value, flag | 140, 1440, 0, 0 | 140, 1440, 0, 0 | 140, 1440, 0, 0 |
| record stores in the heal routine | none | none | none |
| gate: `find_affect` call, callee | `023A2A`, `01B6D2` | `024DC0`, `01AB12` | `023D30`, `01A6EE` |
| handler table; dispatcher | `g58C2`; `00E222` | `g7778`; `0120DC` | `g7700`; `01214C` |
| handler for the heal id | `0127AE`, `rts` | none, past the table | none, past the table |
| handler for 109 | a real handler (109 is another effect in Curse) | `016B86`, `rts` | `016A18`, `rts` |
| cure routine: id, record byte decremented | `023B64`: 141, `0x196` | `024EE6`: 110, `0x6D` | `023EA2`: 110, `0x80` |

The id is pushed only at the gate and the add. The one exception is Silver
Blades `0175C8`, which pushes 140 and 400 to `03DD0C`, a four-argument
routine that is not an effect routine. The Amiga effect node is ten bytes:
id, a pad, the duration `u16` big-endian, value, flag and the next pointer
(`goldbox/amiga_por.py`'s `amiga_por_effect_to_dos`). `add_affect` stores the
first-pushed word's low byte at `+5`, the flag `remove_affect` tests, and the
second's at `+4`, the value; the cure's pushes (flag 1, value 0) land where
DOS keeps its flag and value. So the heal node is `8C 00 05 A0 00 00` when
it is added.

**Pool of Radiance.** Neither DOS `GAME.OVR` nor the Amiga `/program` has a
1440-minute `add_affect` call or a `Heal whom` prompt. The C64 side is
`tools/c64/curedisease.py pool`.

## What stays open

* **The Amiga duration unit is PROBABLE minutes, not measured.** The
  evidence: the Amiga pushes the same constants as DOS (1440 for this node,
  10080 for the cure), and the build is a mechanical translation of DOS
  (`docs/124-amiga-port.md` 1.3). To settle it: in Amiga Curse under
  `tools/amiga/fsuaepor.py serve --floppy ...`, lay on hands, save, rest a
  known number of hours, save again, and read the paladin's 140 node.
  Minutes are confirmed if the duration word drops from 1440 by 60 per hour
  rested.
* **Whether any Amiga Silver Blades or Pools of Darkness path dispatches a
  140 node through the handler table is UNKNOWN.** 140 is past both tables'
  ends. `remove_affect` dispatches only a node whose flag byte is set, and the
  heal node's flag is 0, so expiry and Dispel Magic never reach the table
  with it. The other 15 callers of Silver Blades' dispatcher (`0120DC`) have
  not been read. The engine creates this node in ordinary play, so a crash
  here would be a well-known bug. To settle it statically: read each caller
  of `0120DC` for one that passes a node's own id without testing its flag.
  To settle it driven: lay on hands in Amiga Silver Blades, fight one combat
  and rest a day, and check that HEAL returns and the game does not crash.
* **When a C64 row expires away from camp** is #600's open question and
  applies to lay on hands unchanged. The one-row staging on `SSBC.D64` in
  #600's stage 7 comment settles it for both timers.

## Negative results

* No save on this machine holds a paladin with a lay-on-hands node or row.
  #600's census found none on the C64 or DOS. The Amiga readers' own census
  (`docs/124-amiga-port.md`) found 11 of 11 nodes with duration 0. So this
  reading has not been checked against a save the game wrote after a HEAL.
  A DOS Silver Blades save made with `tools/dos/ssbimport.py` before and
  after Guy de Valois uses HEAL would show node 109 with 1440 minutes.
* No record byte in DOS or on the Amiga moves when HEAL is used. The heal
  routines write nothing through the record pointer, and the gates only read.
