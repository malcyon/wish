# Silver Blades' fourth spell-slot array is spell class 2's, and no spell has that class

The question behind `#222 (Silver Blades' fourth spell-slot array is zero in
every state anybody can create)`: the DOS Silver Blades record has 28 bytes
of spell slots at `0x132`, three seven-byte arrays of them attributed by
measurement and a fourth at `0x140`-`0x146` that no class, level or edit
ever put a value in. Answered by reading the engine's own slot builder out
of `GAME.OVR`, the spell table it walks out of `START.EXE`, and the same
block in four other titles for comparison.

**The answer -- CONFIRMED from the code: the block is
`array[0..3, 1..7] of byte`, indexed `0x131 + 7 * class + level` with
`class` the first byte of the title's spell-table entry, and Silver Blades'
spell table assigns its 117 ids to classes 0 (cleric), 1 (druid), 3
(magic-user) and 4 (not a spell) and never to 2. Every writer of the block
begins by zeroing all 28 bytes and then adds into classes 0, 1 and 3. So
`0x140`-`0x146` is zeroed by the engine itself on every rebuild and is added
to by nothing, and a converter writing zero there has a tested reason.**

Grades follow `docs/50-experiments.md`'s scale. "The build" is the
*Forgotten Realms: The Archives, Collection Two* copy of each title; file
offsets are into that title's `GAME.OVR`, and `START.img` is Silver Blades'
`START.EXE` expanded by `tools/unexepack.py`. `tools/dosspellslots.py`
regenerates every table below in three commands per title.

## The block is indexed by the spell table's class byte

Silver Blades' spell table is 16 bytes per id at `DS:0x449D`, `DS = 0xDE2`
(the System unit's `mov dx, 0xDE2 / mov ds, dx` at `START.img:0xC5D0`), so
`START.img:0x122BD`. Byte 0 is the class and byte 1 the level. Every access
to the slot block goes through that pair, and the memorise screen's scan is
the plainest instance:

```
1B370  mov al, [di + 0x449E]         ; the spell's level
1B382  mov al, [di + 0x449D]         ; the spell's class
1B387  mov dx, 7 / mul dx
1B38C  les di, [0x7D38]              ; the selected character
1B394  cmp byte ptr es:[di + 0x131], 0
```

| class | slots | what the table calls it | ids |
|---|---|---|---|
| 0 | `0x132`-`0x138` | cleric | 37 |
| 1 | `0x139`-`0x13F` | druid | 8 |
| 2 | **`0x140`-`0x146`** | **nothing** | **0** |
| 3 | `0x147`-`0x14D` | magic-user | 54 |
| 4 | `0x14E`-`0x154`, outside the block | not a spell | 18 |

The ids agree with `goldbox/spells.py`'s `_GROUPS_SILVER_BLADES` group for
group -- 1-8 class 0 level 1, 9-21 class 3 level 1, 77-80 class 1 level 1,
90, 96 and 98 class 1 level 2 -- and the eighteen at class 4 are
`_NOT_A_SPELL_SILVER_BLADES` to the id: 57, 59-65, 95, 97, 99, 101-107. That
list was read off the names; this is the same list read off the table.
CONFIRMED.

## Every writer zeroes all four arrays and adds into three

A Turbo Pascal `FillChar(record.slots, 28, 0)` begins with `add di, 0x132`,
and the whole binary holds three of them (`81 C7 32 01`), each pushing
`0x1C`:

| site | routine | what it adds afterwards |
|---|---|---|
| `0x3BE5D` | the slot builder, unit `0x164` entry 0, called at `0x3C28C` from the recalculation routine `0x164:0x25` (`0x3C1B1`) | cleric: `0x132`-`0x138` from the table at `DS:0x50A1`, then the wisdom bonuses (`0x3C477`-`0x3C603`); paladin over 8: into the **cleric** array from `DS:0x52D2`; ranger over 7: `0x139`-`0x13B` from `DS:0x538D` columns 1-3 and `0x147`-`0x148` from columns 4-5 (`0x3C02C`, `0x3C06A`); magic-user: `inc [0x147]` then `0x147`-`0x14D` from `DS:0x5448`, capped by intelligence at `0x3C609` |
| `0x1F4C5` | character creation | class 0: `[0x132] = 2`; class 5: `[0x147] = 1` |
| `0x3D050` | dual-classing, then `call 0x3C1B1` at `0x3D10E` | class 0: `[0x132] = 1`; class 5: `[0x147] = 1` |

The recalculation routine is reached by far call from `0x22828`, `0x25B9A`
and `0x26081` in unit `0xF8`, the party-management unit, and it is what
rebuilds a record's slots on load -- which is why `#113 (Play DOS Curse far
enough to save a party with items)`'s edited paladin came back with a cleric
slot the file did not carry.

The four increment tables are AD&D's, which is what fixes `DS`: the cleric's
row for level 9 reads `1 1 0 0 1 0 0` and the magic-user's for level 5
`1 0 1 0 0 0 0`, and the ranger's rows 8-13 are `coab`'s `unk_1A758` exactly
(druid at 8, 10, 12; magic-user at 9, 11, 13).

**The one instruction in the binary with displacement `0x140` is not this
record's.** It is at `0x25323` inside the Curse import (`0x24CB0`, unit
`0xF8` entry `0x70`), reading **Curse's** `0x140` -- the portrait body --
into Silver Blades' `0x152`. The same routine copies Curse's three five-byte
slot arrays into `0x132`, `0x139` and `0x147` in a loop of five
(`0x25269`-`0x252C5`) and touches nothing at `0x140`. A search for every
`es:[reg + 0x140..0x146]` in `GAME.OVR` and `START.img` finds no other.

## The engine knows class 2 is there and steps over it

The memorise screen at `0x1AB28` scans four classes by seven levels (its
class loop ends on `cmp [bp-0x83], 3` at `0x1AC0B`) and marks each class
that has a slot. Choosing captions, it then does

```
1AC52  cmp byte ptr [bp-0x83], 2
1AC57  jne 1AC5C
1AC59  jmp 1AD34                     ; class 2: next class
```

and maps 0, 1 and 3 to the three captions the unit carries: `Cleric
Spells:`, `Druid Spells:`, `Magic-User Spells:` (`0x1AAF0`, `0x1AB03`,
`0x1AB16`; class 3 to the third at `0x1ACA3`). There is no fourth caption.
CONFIRMED.

## The same block in the other titles on this machine

`tools/dosspellslots.py sites` and `census` on each:

| title | record | block | `FillChar` | classes in the spell table | magic-user is |
|---|---|---|---|---|---|
| Curse of the Azure Bonds | 422 | `0x12D` | 15 = 3 x 5 | 0 (36), 1 (4), 2 (45), 3 (15) | 2 |
| Gateway to the Savage Frontier | 422 | `0x12D` | 15 = 3 x 5 | 0 (36), 1 (4), 2 (45), 3 (15) | 2 |
| **Secret of the Silver Blades** | 439 | `0x132` | **28 = 4 x 7** | 0 (37), 1 (8), **3 (54)**, 4 (18) | **3** |
| Pools of Darkness | 510 | `0x17D` | 27 = 3 x 9 | 0 (42), 1 (11), 2 (61), 3 (11) | 2 |
| Treasures of the Savage Frontier | 510 | `0x17D` | 27 = 3 x 9 | 0 (42), 1 (11), 2 (61), 3 (11) | 2 |

Four of the five number the magic-user 2 and put the monster-only entries
(`coab`'s `SpellClass.Monster`) at 3, outside a three-wide block. Silver
Blades alone numbers the magic-user 3, the non-spells 4, dimensions the block
for four classes, and leaves 2 empty. Pools of Darkness' builder writes the
same three classes Curse's does (`0x38206` druid, `0x38248` and `0x382F7`
magic-user), so the fourth array is Silver Blades' alone.

## Watched in the running game

`tools/dosslotwatch.py`, DOSBox-X with the debugger, the played save
`work/curse/SSB-D-paine-memorised` staged with PAINE's `CHRDATD2.SAV`
patched to `05` at `0x140` and `07` at `0x143` before the game saw it --
DOSBox-X's `BPM` fires on change, so a byte the file holds at zero cannot
be watched being zeroed.

| run | what was done | result |
|---|---|---|
| 1 | `LOAD SAVED GAME` D, then every party record found by name | PAINE at `5EEAC` reads `00 00 00 00 00 00 00 \| 01 00 00 00 00 00 00 \| 00 00 00 00 00 00 00 \| 00 00 00 00 00 00 00`: the druid slot kept, both patched bytes gone. The other five read exactly what their files hold |
| 1 | `SAVE CURRENT GAME` to E | `CHRDATE2.SAV` differs from the patched input in seven bytes: `0x140` `05 -> 00`, `0x143` `07 -> 00`, and five bytes of live heap pointers (`0xFD`-`0xFE`, `0x19D`, `0x19F`-`0x1A0`). Now the specimen `ssb-slote-zeroed140` in `tools/specimens.py list` |
| 2 | fresh boot, `BPM` on `5EFE:000C` armed before the load, then D | two hits: `00 -> 05` at `F000:CA40` (DOS's file read landing the byte) and **`05 -> 00` at `0F11:04D8`, far return `319B:0021`** -- `FillChar`'s `rep stosw` (`0F11 = 0x822 + 0x6EF`, the twelve bytes at `IP` are `START.img:0x73BC`-`0x73C7`), returning to code offset `0x21` of unit `0x164`, the byte after the builder's `lcall 0x6EF:0x4C4` at `0x3BE67`. Then 25 seconds of quiet and the record at `5EEAC` again, zero at `0x140`-`0x146` |

Two writes to the byte across a load: the file arriving and the builder's
zero fill, in that order, and nothing after. Logs and the save trees are
under `work/issue222/run1/` and `run2/`.

## Grades

* **CONFIRMED** -- the block is `0x131 + 7 * class + level`; the three
  writers zero all 28 bytes and add to classes 0, 1 and 3 only; no spell in
  the table carries class 2; the memorise screen skips class 2 by name. All
  read out of the build's `GAME.OVR` and `START.EXE`.
* **CONFIRMED** -- on load, the only instruction that writes `0x140` after
  the file read is the builder's `FillChar`, and a nonzero value put there
  by hand does not survive to the next save. Watched, above. That nothing
  else writes the seven bytes on the two other paths (creation,
  dual-classing) rests on the code: the byte searches cover every
  `add di, 0x132` and every displacement in `0x140`-`0x146`, and a
  whole-record `Move` carries what the fill left.
* **UNKNOWN** -- what class 2 was. The numbering looks like a class inserted
  between druid and magic-user in the engine Silver Blades was built on.
  The DOS Champions of Krynn is not on this machine; the same census on its
  spell table would name it. A stride-16 scan of the C64 Krynn disks
  (`~/c64/Champions of Krynn (SSI)[dom]/`) found no table laid out the DOS
  way, so the C64 side is not a shortcut.

## Negative results

* **The fourth array is not "slots remaining", not the paladin's, not the
  ranger's, and not a seven-byte field of another kind** -- `#113`'s
  measurements said so and the code agrees: the paladin adds into class 0,
  the ranger into 1 and 3, and the `FillChar` of 28 dimensions the block as
  four sevens rather than three sevens and something else.
* **The druid array only ever holds three bytes.** The ranger's table is
  read for columns 1-3 into `0x139`-`0x13B`; `0x13C`-`0x13F` are zeroed and
  never added to, on the same evidence as class 2's seven.
* **The DOS spell-table entries are not byte-identical to the C64's.** The
  16 bytes of ids 1, 10, 21, 77 and 115 appear nowhere on the six
  `SILVER-*.D64` sides.

## What should change in `goldbox/`, reported rather than done

`goldbox/dos_layout.py`'s `spells_castable_unattributed` (and the `_NOPE`
grade on it) can become a field whose note says: spell class 2's slots in a
block the engine dimensions as four classes, zeroed by the engine's own
`FillChar` before every rebuild and added to by nothing, because no spell in
this title carries class 2. A converter writes zero with that as the tested
reason. Two smaller corrections from the same read: `gap_14e`'s three bytes
are what the Curse import carries over from Curse's `0x13C`-`0x13E`
(`0x252D8`-`0x252FD`, `coab`'s `field_13C` and `field_13E`), and the
`spells_castable_druid` note can say the engine fills three of its seven.
