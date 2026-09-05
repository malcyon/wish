# The class code byte, and why Curse's C64 engine stops maintaining it

Every Gold Box character record says its class twice: a **bitmask** and a
**single code**. This page is about the code -- what computes it, what reads
it, and the one title on the one port where the engine writes the wrong number
into it, which a conversion then copies onto a sheet a player reads.

| | the bitmask | the code |
|---|---|---|
| C64, all titles | `class_bits` `0x0EB` | `char_class` `0x073` |
| DOS Pool of Radiance | `0x0DC` | `0x00C` |
| DOS Curse of the Azure Bonds | `0x12B` | `0x075` |

`goldbox/layout.py` and `goldbox/dos_layout.py` carry the offsets; the codes
themselves are the standard Gold Box order, 0 cleric, 1 druid, 2 fighter,
3 paladin, 4 ranger, 5 magic-user, 6 thief, 7 monk, and 8 upward for the
multi-class combinations.

## The game's own table, and the routine that walks it -- CONFIRMED

Curse of the Azure Bonds' C64 `GEN` carries the table at `$1951`, seventeen
bytes indexed by the class code and holding the bitmask that code stands for:

```
02 00 08 40 80 01 04 00 0a 0b 82 03 06 09 0c 0d 05
```

Read against `goldbox/games.py`'s class bits for that title -- magic-user 1,
cleric 2, thief 4, fighter 8, paladin `0x40`, ranger `0x80` -- every entry
places: index 0 is the cleric, 2 the fighter, 5 the magic-user, 6 the thief,
8 the cleric/fighter, 13 the fighter/magic-user, 14 the fighter/thief. Two
entries are zero, the druid at 1 and the monk at 7, which are the two classes
no Gold Box record carries.

**Index 10 is `0x82`, cleric and ranger.** Pool of Radiance has neither a
paladin nor a ranger and its table has cleric/magic-user there, which is the
row `goldbox/yaml_io.py`'s `CLASS_CODES` records. So **the table is per
title**, and a code read out of one title's record is not safe to interpret
with another's.

The routine that walks it is `GEN $1939`, twenty-three bytes:

```
LDA $7CBA        ; dual_class_level
BNE  ...         ; a dual-classed character takes a different exit
LDX #$10         ; walk the seventeen entries backwards
LDA $7CEB        ; class_bits
EOR $1951,X
BEQ  store       ; matched -- X is the class code
DEX
BPL  ...
```

`$7C00` is the live character record, so `$7CBA` is `dual_class_level`,
`$7CEB` is `class_bits` and `$7C73` is `char_class`. Those are the same base
and the same two dual-class offsets
`#224 (0x0B9 and 0x0BA are documented both as an NPC marker and as the
dual-class slot)` settled.

## The defect: the wrong register is stored -- CONFIRMED

The store at the end of that routine is `STA $7C73`, and the answer is in
**X**. `A` on the matching path is the `EOR` result, which is zero by
definition; `A` on the dual-class path is `dual_class_level`. `STA` is `$8D`
and `STX` is `$8E`.

So Curse's C64 engine writes:

* **0** into `char_class` for every character it trains -- whatever his class;
* **the level he left his old class at** for a character who uses
  `HUMAN CHANGE CLASS`.

Two watched pairs, one action apart each, say so:

| pair | what happened | `char_class` |
|---|---|---|
| `WISH-SPEC-curse-train-input` to `WISH-SPEC-curse-trained-party` | five characters trained at Curse's own hall, MARK the untrained control | 5, 0, 13, 14, **3**, 0 becomes 0, 0, 0, 0, **3**, 0 |
| `WISH-SPEC-curse-trained-party` to `WISH-SPEC-curse-dual-classed` | PHILIPPE, a magic-user 6, becomes a fighter 1 | 0 becomes **6**, her old level |

Five of five trained characters lose their code, and MARK, who was not
trained, keeps his. The cleric's right code is 0 as well, so one of the five
is invisible.

**The C64 game never notices, because it never reads the byte.** Across the
seven Curse overlays dumped in `work/issue18` there is exactly one instruction
that touches `$7C73` -- that store -- and no load, no compare and no indexed
form. `GEN $0DEB` is the only caller of the routine.

**Silver Blades does not write it at all**, and Pool of Radiance's records are
right: no store to the byte anywhere in Silver Blades' `GEN`, and 24 of 24
Pool of Radiance C64 records agree with their own level array. What a Silver
Blades C64 record holds is whatever put it there at creation, and that is
UNMEASURED.

## The census -- CONFIRMED

`tools/classcodecensus.py` compares the code with the classes the character
holds **levels** in, which is the reading that catches both kinds of
disagreement -- a code that is stale and a level array that names a class the
code does not. One thing it had to get right first, and it was this project's
mistake before it was a finding: **DOS numbers the paladin's and the ranger's
bits differently from the C64**, so reading a stored DOS `class_bits` against
the C64's table makes every DOS ranger in the corpus look like a
disagreement. `goldbox.dos.neutral_class_bits` folds it, and the census calls
it.

| corpus | records | disagree |
|---|---|---|
| C64 Curse of the Azure Bonds, specimen tree | 30 | **8** |
| C64 Pool of Radiance | 24 | 0 |
| C64 Secret of the Silver Blades | 24 | 0 |
| DOS Curse, Pool of Radiance and Silver Blades, specimen tree | 88 | 0 |
| DOS Curse and Silver Blades, archives | 74 | 0 |
| DOS Pool of Radiance, archives | 66 | 4 |
| DOS Pools of Darkness, archives | 52 | 2 |

All eight C64 disagreements are in the two disks Curse's own engine wrote
after a training or a class change.

**The four Pool of Radiance ones are all SILAS**, the same shipped fighter
twice over in two copies of the archives: `char_class` 2 and `class_bits`
`0x08`, both fighter, with a **thief 1** in his level array. His code is not
stale -- his level array carries a class his mask does not, which is the
opposite fault and the reason the fix below reads the mask rather than the
levels. The two Pools of Darkness ones are dual-classed characters in a
downloaded save with no chain of custody. Two more matches in the Curse sweep
are `DISK3/GAME.GLB`, which is not a character record at all: the census
recognises a record by its size, and a 422-byte slice of a game data file
matches.

## What it costs a conversion

**A C64 Curse party that has been trained arrives in DOS with the wrong class
drawn on its sheet.** `char_class` is in `goldbox/dos.py`'s `WRITE_DIRECT`, so
the stale byte is copied straight across, and Curse's DOS `GAME.OVR` reads
that offset in 47 places. Measured in the running game on 2026-09-05, six
records converted out of `WISH-SPEC-curse-dual-classed` and loaded in DOS
Curse under DOSBox:

| character | what he is | what DOS drew |
|---|---|---|
| TRAVIS | dwarf thief 6 / fighter 5 | **CLERIC** |
| LEDERA | elf magic-user 5 / fighter 5 | **CLERIC** |
| PHILIPPE | human fighter 1, was magic-user 6 | **THIEF** |
| MARK, MATHEW | human paladins, MARK never trained | PALADIN |
| SHARA | human cleric 6 | CLERIC, right by luck |

Levels, hit points, armour class, THAC0, saving throws and experience are all
right on those sheets. The DOS engine's own `SAVE CURRENT GAME` writes the
wrong code back rather than repairing it.

## The fix, and why the mask rather than the level array

`goldbox.dos.write` now checks the code against the record's own classes and
rewrites it when the two contradict each other. `char_class` stays in
`WRITE_DIRECT` -- a straight copy is what it is in every record whose source
kept it up to date, and the reader's `DIRECT` and the writer's table are
mirrors -- and the repair fires only on a record that disagrees with itself.

**The source is the class mask, not the level array**, and one shipped record
decides it. SILAS, a Pool of Radiance fighter in the archives, holds
`char_class` 2 and `class_bits` `0x08`, both fighter, with a **thief 1** in
his level array that neither of them knows about. Reading his code off the
levels would make him a fighter/thief, which is the conversion inventing a
class for a character the game calls a fighter.

**A dual-classed character is the exception and takes the level array after
all.** His mask carries the old class's bit back once his new class passes the
level he left the old one at, so it names two classes where the code names the
one he is; his current level array holds exactly the class he is now, because
the old class's slot is zeroed at the change and stays zero. The engine agrees
-- `GEN $1939` branches away from the mask walk entirely when
`dual_class_level` is set.

**It is not reported to the player.** `editor/exports.py`'s `losses` puts
every warning under a heading saying the conversion could not do something
faithfully, and this is the opposite. The provenance line in the report's own
byte account is where it goes.

The same six records, converted again and loaded in DOS Curse under DOSBox:

| character | before | after |
|---|---|---|
| TRAVIS | CLERIC | **FIGHTER/THIEF** |
| LEDERA | CLERIC | **FIGHTER/MAGIC-USER** |
| PHILIPPE | THIEF | **FIGHTER** |
| MATHEW | CLERIC | **PALADIN** |
| MARK, SHARA | PALADIN, CLERIC | unchanged |

And `HUMAN CHANGE CLASSES` is still absent from the party menu with PHILIPPE
highlighted, so the former-class array `#234 (A dual-classed Curse or Silver
Blades character converted to DOS loses the class he trained out of)` is about
still reads the way it did.

**What this does not fix.** The neutral record still carries the stale code,
because the repair is in the DOS writer rather than in the C64 reader --
`goldbox/c64_codec.py` -- so `goldbox/yaml_io.py`'s `class_code` export still
shows it. `editor/roster.py` draws the class from `class_bits` and is not
affected. `#310 (A trained C64 Curse character arrives in DOS with the wrong
class on his sheet)` stays open for the reader's half.

## Where the numbers came from

* `tools/classcodecensus.py` -- the census above, and it prints the mask it
  derived beside the mask the record stores.
* `tools/d6502.py work/issue18/GEN.bin 0800 1930 25` -- the routine.
* `tools/dosfieldrefs.py <Curse GAME.OVR> --offset 0x075` -- 51 sites in the
  DOS overlay, 4 write and 47 read.
* `tools/dossheetread.py` -- the six sheets in the running game.
