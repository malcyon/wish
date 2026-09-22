# The three unnamed bytes of the NPC window, read from every engine's code

`#614 (A converted companion arrives at Amiga Pool of Radiance as a player
character, because write_por overwrites the NPC control byte and reports
nothing)` left three bytes of `field_83_87` with no reader found: DOS Pool of
Radiance `0x083`, `0x086` and `0x087`, and their positions in the other titles
and ports. Donald's ruling was that "we just don't know" is not an answer.
This page is what the engines' own code says about them, on all three
platforms, with the addressing forms the earlier searches did not cover.

**In one line: the window is the C64 record's `0xB7`-`0xBA` with the treasure
share inserted after the control byte. The fourth byte sits where the C64
keeps `dual_class_slot` and is read by Silver Blades' importer on DOS and the
Amiga as the class a dual-classed human left; the fifth sits where the C64
keeps `dual_class_level` and nothing on DOS or the Amiga reads it; the first
is the C64's own unnamed `0xB7`, read by nothing on any platform.**

Grades are `docs/50-experiments.md`'s. Every executable was read from the
player's own disks through the registry: DOS `GAME.OVR` and `START.EXE`
(`GAME.EXE`, `STARTUP.EXE`, `CONTROL.EXE` for Pools of Darkness) from
*Forgotten Realms: The Archives*; Amiga `/program` (Pool of Radiance disk 1),
`/Curse`, `/Secret` and the 341,940-byte `Pools of Darkness`; the C64 titles'
disks whole. The C# reimplementation of DOS Curse in the registry
(`coab-source`) was read beside the Curse overlay.

## The window, title by title

| title | DOS | Amiga | bytes | order |
|---|---|---|---|---|
| Pool of Radiance | `0x083`-`0x087` | `0x084`-`0x088` | 5 | first, control, share, fourth, fifth |
| Curse of the Azure Bonds | `0x0F6`-`0x0FA` | `0x0F6`-`0x0FA` | 5 | the same |
| Secret of the Silver Blades | `0x0FF`-`0x102` | `0x09A`-`0x09D` | 4 | control, share, fourth, fifth -- the first is dropped by the Curse importer |
| Pools of Darkness | `0x147`-`0x14A` | `0x093`-`0x095`, `0x05B` | 4 | the same; the Amiga scatters the fourth to `0x05B` |

The control byte and the share are CONFIRMED in `goldbox/dos_codec.py` and
`docs/124-amiga-port.md` §1.21 and are not this page's subject.

## Where the bytes come from: the C64 record

The C64 keeps, in order: `0xAD`-`0xB6` the ten trait slots, `0xB7` unnamed,
`0xB8` the control byte, `0xB9` `dual_class_slot`, `0xBA` `dual_class_level`,
`0xBB` copper (`goldbox/layout.py`). DOS Pool of Radiance keeps, in order:
`0x7F`-`0x82` the effect-chain far pointer (what the trait slots became),
`0x83` unnamed, `0x84` the control byte, `0x85` the share, `0x86`, `0x87`,
`0x88` copper. One byte inserted after the control byte, everything else in
the C64's order. The later titles keep the same run.

Three things line the two up beyond the order:

* **The share is `0x85`, not `0x86`.** `tools/dos/dosmodifyprobe.py` watched
  MODIFY-then-KEEP write 1 there, and Amiga `/program` `0x02DA28` masks
  `0x086` with 7 for the split. So the inserted byte is the second, and the
  fourth and fifth are what follow the C64 pair.
* **Silver Blades reads the fourth byte as the C64 reads `0xB9`.** Below.
* **The monster editor's fill.** C64 Pool of Radiance's `MON*` files hold
  `0xFF` at `0xB7` in 116 of 116 (Curse 70 of 70; Silver Blades' 71 hold 0);
  Amiga `moncha.dax` holds `0xFF` at `0x084` in 116 of 116; DOS `MON*CHA.DAX`
  holds `0xFF` at `0x083` in 172 of 172. Same fill at the same position, and
  the same 116 monsters on the Amiga and C64 disks.

## The fourth byte: read by Silver Blades' importer as the class he left

**CONFIRMED** as a reader, from both ports' own code. Amiga `/Secret`, in the
routine at `0x026C06` that unpacks a Curse record into Silver Blades' own:

```
026c66  tst.b  $b0(a0)          ; class_levels[ranger]
026c6c  bgt    ...              ; a ranger now: add the innate
026c72  cmpi.b #$4, $9c(a0)     ; else: the window's fourth byte == ranger
026c7e  jsr    03d5d0           ; and he has passed the level he left at
        ...                     ; -> effect node 0x69
026ca4  tst.b  $af(a0)          ; class_levels[paladin]
026cae  cmpi.b #$3, $9c(a0)     ; else: fourth byte == paladin
026cba  jsr    03d5d0
026cc8  move.b #$1, $6d(a0)     ; paladin_cures = 1
        ...                     ; -> effect node 8
```

`03d5d0` is "human, and the first non-zero class level exceeds
`former_level`". DOS `SECRET/GAME.OVR` has the same three compares at
`0x0256CF`, `0x0257BA` and `0x0257F6` (`cmp byte ptr es:[di+0x101], 3` and
`4`), and one write, the importer's copy from Curse `0x0F9` at `0x02508D`.
3 and 4 are paladin and ranger in DOS class numbering.

**The C64 makes the same test on `0xB9`.** Curse's own `GEN $128A`, and the
same code in Silver Blades' `ECL65 $2171`:

```
$128A  AD BA 7C   LDA $7CBA      ; dual_class_level: dual-classed at all?
$128D  F0 07      BEQ $1296
$128F  AE B9 7C   LDX $7CB9      ; dual_class_slot
$1292  E0 07      CPX #$07       ; the ranger's bit, C64 numbering
$1294  F0 05      BEQ $129B      ; was a ranger: count him
$1296  AD D0 7C   LDA $7CD0      ; else class_levels[ranger]
$1299  F0 0D      BEQ ...
```

"Is a ranger now, or was one before he changed class", on the byte one past
the control byte on the C64 and two past it on DOS, each in its own port's
class numbering. That the DOS byte is the C64 pair's slot byte kept in the
layout is **PROBABLE**: the position, the test and the class codes agree, and
nothing contradicts it, but it is an inference about lineage rather than a
measurement of the running game.

**Nothing on DOS or the Amiga writes it for its own characters.** Curse's
change-of-class routine (`/Curse` `0x039606`-`0x03965E`; DOS `docs/209`)
writes `former_class_levels`, `former_level`, `level` and `class_levels` and
not this byte; COAB's `Player.field_F9` is assigned in one place, the Pool of
Radiance importer, and read nowhere. The DOS engines derive a regained class
from the two former fields instead of the C64's pair -- COAB's
`SkillLevel(skill) = ClassLevel[skill] + ClassLevelsOld[skill] * (current >
multiclassLevel)` -- which is why the pair's positions are never written.
CONFIRMED for the displacement form in all eight executables; the search
below found no other form.

## The fifth byte: the C64 `dual_class_level` position, read by nothing

**PROBABLE** by position. No reader in any addressing form searched, on any
port of any title. The C64 reads its `0xBA` as the sentinel for the pair
(`GEN $18EB`: zero means not dual-classed) and DOS reads `former_level`
instead, so the position has no job left on DOS.

## The first byte: the C64's `0xB7`, read by nothing anywhere

No absolute, absolute-X or absolute-Y operand in any file on the Pool of
Radiance, Curse or Silver Blades disks lands on `0xB7` (one byte pair in
Curse's `SPRITE19`, art). No site in any form in the four DOS overlays, the
four DOS resident images, or the four Amiga executables. What it was for on
the C64 is **UNKNOWN**; that nothing reads it is CONFIRMED for every form
searched. The `0xFF` a companion carries is the editor's fill copied in with
his template (`/program` `0x00B156`-`0x00B1AA`, `memcpy` of `0x11F` bytes
then `move.b #$b2, $85(a2)`), and player creation zeroes it (`0x016C12`).

## The search, form by form

The point of this pass was the forms a displacement search misses. Each row
is a route a reader could take that the earlier `d16(An)` / `es:[di+d16]`
scans could not see.

| route | how it was asked | result |
|---|---|---|
| DOS resident code | `tools/dos/unexepack.py` on each title's `START.EXE` and Pools of Darkness' three executables, then `dosfieldrefs.references` | zero `ES` sites for any window byte **and for the control byte** in all four: record access is entirely in the overlays |
| DOS addressing without `ES` (`[bx+d16]`, `[si+d16]`, `[bp+si+d16]`) | `references(..., prefixes=())` | the extra hits are `[bp+si+0x86]`, `[bx+di+0x87]` and the like, forms Turbo Pascal never emits for a far record; the same scan adds six such hits to Pool of Radiance's control byte (43 against 37), so that is the noise level |
| the ECL script VM reaching a field by address | COAB `ovr008.cs` `get_player_values` / `alter_character`: an explicit switch over C64 offsets (`0x15`, `0x18`, `0x72`, `0x73`, `0x9B`, `0xA0`, `0xA5`-`0xAC`, `0xB8`, `0xBB`-`0xC3`, `0xC9`, `0xD6`, `0xD8`, `0xE4`, `0xF7`, `0xF9`, `0x100`, `0x10C`, `0x10D`, `0x11B`, `0x2B1`, `0x2B4`, `0x2CF`, `0x312`, `0x33E`; on the set side also `0x322`-`0x326`) | an unmapped `$7Cxx` address falls back to a word array, never to the record; `0xF6`, `0xF9`, `0xFA` are not mapped. The other three titles' dispatchers are the `es:[di+off]` chains `docs/215` reads, so any arm on a window byte would be in the displacement count, which is zero |
| Amiga `d8(An,Xn)`, the indexed form | `tools/amiga/amigaindexedrefs.py`, every CODE hunk, each candidate decoded from its own start | zero for every window byte on all four executables. The decoder was checked against a linear sweep of `/Secret`: it finds every non-zero indexed displacement the sweep finds (`$1e(a0, d0.w)`, the spell list, among them) |
| Amiga `lea d16(An), Am` then `(Am)` | the same tool, bases up to 16 below each byte, each site read | Curse `lea $f6(a2/a3), a0` at `0x00B356`, `0x00B35C`, `0x0271EA` and Secret `lea $9a(a2), a0` at `0x028374` are 3- and 2-byte `memcpy` calls in the packer and unpacker; Pools of Darkness `lea $52`/`$56(a2)` are `addq.w`/`add.w` on word fields, `lea $4c`/`$8b(a2)` are copies ending at `0x51` and `0x92`, `lea $87(a2)` a byte counter. Nothing spans `0x95` or `0x5B` |
| C64 absolute operands on the equivalent bytes | `tools/c64/c64recordoperandsweep.py 0xB7 0xBA` | `0xB7` none in code on any title; `0xB9`/`0xBA` none in Pool of Radiance, 59/77 in Curse and 47/49 in Silver Blades, all in `GEN`, `POST.COM`, `COMBAT2` and the `ECL65`/`SPELLE65` overlay |
| whole-record copies | save and load (`pea $120` around the Amiga `.sav`/`.cha` I/O at `/program` `0x026668`; the DOS `.sav`/`.cha` files are whole records), the join copy, the importers | copies, which is why the bytes survive from title to title without a reader |

Not excluded by any of this: an indexed overrun from the C64 trait array
(`$6BAD,X` with X past 9 would land on `0xB7`), and a computed store on DOS
(`rep movsb` into the window) that no displacement carries. Neither has a
positive sign anywhere; both are named so the next reader knows the edge of
the search.

## The one consequence a player could meet

On DOS, `class_levels[old]` is zeroed at the change and stays zero
(`docs/209`), so a human who was a paladin in DOS Curse, changed class and
passed his old level arrives at Silver Blades' import with `class_levels[3]`
zero. The importer's first branch fails; its second needs `0x101 == 3`, and
DOS Curse never writes it. So on DOS and the Amiga the paladin's
`paladin_cures` and Protection from Evil node, and the ranger's node `0x69`,
are not restored at import for a regained class. On the C64, `GEN $20A3`
writes the old level back into the slot and the first branch catches him.
Whether Silver Blades recomputes the innate in play from
`former_class_levels`, which would make the import step redundant, is
**UNMEASURED**, and that decides whether this is a game bug a player sees.
It is not in `goldbox-bugs.md` for that reason.

**The experiment.** DOS Silver Blades importing a Curse `.GUY` for a human
ex-paladin (`class_levels[3]` 0, `former_class_levels[3]` > 0, `former_level`
below his level) with `0x0F9` = 3, against a control copy with `0x0F9` = 0.
Prediction: the `.FX` gets node 8 and `paladin_cures` (`0x6D`) = 1 on the
first and neither on the second; then a rest and a cure attempt on each to
see whether play differs. It needs a DOSBox driver through Silver Blades'
party import, which `tools/dos/` does not have. For the first and fifth bytes
no experiment adds anything: there is no reader to trigger.

## What a writer must do

* **Routes with the window on both sides:** all five bytes byte for byte.
  The fourth is not dead data; a later title in the family reads it.
* **A C64 source:** the first byte is the C64's `0xB7` and can be copied
  rather than written as the constant -- a template-built companion carries
  `0xFF`, a player character 0, on the C64 as on DOS. The fourth and fifth
  are the C64's `0xB9`/`0xBA`. DOS Curse never writes them for its own
  characters, so zero reproduces a DOS-native record; writing the C64 pair
  would make Silver Blades' import restore an ex-paladin's cures the way the
  C64 does. That is the `#234 (A dual-classed Curse or Silver Blades
  character converted to DOS loses the class he trained out of)` decision
  and is Donald's; nothing here forces it either way.
* **Templates:** `0xFF` in the first byte means nothing to any engine. A
  writer building a companion from a template copies it and is correct to.
