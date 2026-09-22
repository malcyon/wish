# Three DOS record bytes named from the shipped overlays

Four bytes of the DOS character record that this project had wrong, right for
the wrong reason, or unattributed, settled by reading the game's own
instructions rather than by counting saves. `tools/dos/dosbyteimm.py` is the scan;
`goldbox/dos_port.py` and `goldbox/dos_codec.py` carry the notes; the issues are
`#305 (Two DOS record bytes have one name from Pool of Radiance and another
from the Curse decompilation)`,
`#304 (field_83_87 is written as a constant that the characters we rolled
ourselves do not hold)` and
`#303 (The DOS record may hold the NPC flag that the conversion reports as
having nowhere to go)`.

| Pool of Radiance | Curse | what it is | grade |
|---|---|---|---|
| `0x084` | `0x0F7` | the control byte: the engine drives this character when it is at or above `0x80` | CONFIRMED |
| `0x085` | `0x0F8` | the treasure share, `& 7`, read only for such a character | CONFIRMED |
| `0x0BF` | `0x143` | the combat-icon slot, 0-7, **not** the marching order | CONFIRMED |
| `0x10D` | `0x196` | the engine's `in_combat`, which is `#235 (Two unattributed DOS byte ranges in the combat tail are dropped converting to C64, and nobody knows what they hold)`'s active flag under another name | CONFIRMED |

The control byte is **C64 `0x0B8`** as well, in the same encoding, and the two
ports read against each other are what settled its low seven bits: they are a
morale percentage stored halved. That is the second half of this page and
`tools/records/controlbyte.py` is its census.

## The method: what constants the engine puts in a byte

`tools/dos/dosfieldrefs.py` counts the instructions that address a record offset
through an `ES`-prefixed displacement. It does not say what value they write,
and that is the question that names a field. `tools/dos/dosbyteimm.py` adds the
immediate.

**The shape of the set of constants is the finding, not the count.** A byte the
engine sets to `0Ah`, `0Ch` and `0FFh` and compares against 8 is not a marching
position in a six-character party, whatever six records on a disk happen to
hold. A byte it sets to `0B2h` and `0B3h` and compares against `80h` and `7Fh`
is a bitfield with a flag in the top bit. Both readings below came out that
way, before any save was consulted.

Every limit of `tools/dos/dosfieldrefs.py` still applies: the image is scanned as
an undifferentiated byte stream, a displacement match does not prove the
pointer is a character record, and an offset reached by any other addressing is
invisible. So a count is an upper bound and an empty result is evidence rather
than proof.

## `0x0BF` is a combat-icon slot, not the marching order

Pool of Radiance's own `GAME.OVR` holds an allocation loop at file offset
`0x01F51E`:

```
mov  byte ptr es:[di+0BFh], 0
cmp  byte ptr es:[di+0BFh], 8      ; jnb out
mov  al, es:[di+0BFh]              ; xor ah,ah / mov di,ax
cmp  byte ptr [bp+di-0Ch], 0       ; index an 8-entry array of taken flags
inc  byte ptr es:[di+0BFh]         ; jmp back
```

Curse's `GAME.OVR` holds the same 45 bytes at `0x01EE20` with the displacement
changed to its own `0x143`. Three other stores finish it: Pool of Radiance
writes **12** at `0x01D219`, calls something, restores the old value at
`0x01D22D` and then reads `0x0BD`, the icon head; it writes **255** at
`0x01F435`; Curse writes **10** as well. No marching position in a
six-character party is 10, 12 or 255.

**Why "0-5 in file order" proved nothing either way.** `LOAD SAVED GAME` walks
the six saved filenames in order and calls the allocator once per character, so
character *i* of a party with no NPC gets slot *i*, which is also its marching
position. The two stop agreeing after a drop-and-add or a reorder, because the
slot stays with the character and the file order does not. And no record byte
holds the marching order in any of these engines: `ENCAMP > ALTER > ORDER`
moves list nodes (`MoveCurrentPlayerUp`, `sub_4558D`) and writes nothing.

The census over every DOS record on this machine reaches 7, twice: Treasures of
the Savage Frontier's shipped save has eight records, and its seventh and
eighth hold 6 and 7. Eight is the number of combat-icon slots and the number of
combatants a party can have -- six player characters plus two companions.

**The identifier in `goldbox/dos_port.py` was `party_order`, a misnomer, and
`#305 (Two DOS record bytes have one name from Pool of Radiance and another
from the Curse decompilation)` renamed it to `combat_figure`.**
`goldbox.dos_codec.DIRECT`'s reader loop requires the DOS field name and the
neutral field name to be the same string, so renaming the DOS field meant
renaming the neutral one -- across `goldbox/amiga_pod.py`,
`goldbox/c64_codec.py` and `goldbox/yaml_io.py`. The window's own
`field_party_order` keeps its old identifier, because it names a different
field: the C64's own 0-7 slot index at `goldbox/layout.py` `0x10D`. What the
conversion writes was right under either name; both whole-save directions
renumber by file position, and the DOS loader reallocates the byte on load
regardless.

## `0x10D` and `in_combat` are one field, not two readings

Curse's own Pool of Radiance importer, in the shipped `GAME.OVR`, copies Pool
of Radiance record bytes into Curse ones in consecutive instruction groups:

| file offset | copies |
|---|---|
| `0x01D54A` | PoR `0x10C` -> Curse `0x195`, `health_status` |
| `0x01D55F` | PoR `0x10D` -> Curse `0x196`, `in_combat` |
| `0x01D574` | PoR `0x10E` -> Curse `0x197`, `combat_team` |

So `#235 (Two unattributed DOS byte ranges in the combat tail are dropped
converting to C64, and nobody knows what they hold)`'s active flag and coab's
`in_combat` are the same byte, named by the engine that reads both records.
The descriptions agree too: coab's `displayPlayerName` (`sub_678A2`) paints a
character whose `in_combat` is false in colour `0x0C`, EGA light red, which is
the red name the staging measured 3 of 3 against 9 of 9.

**The whole importer, reconstructed from the binary**, is 29 byte copies and it
settles the per-title alignment `docs/180-writing-a-later-dos-record.md`
claims. `0x083`-`0x087` go to `0x0F6`-`0x0FA` one for one; `0x0BD`, `0x0BE` and
`0x0C0` go to `0x141`, `0x142` and `0x144` with **`0x0BF` skipped**; `0x10C`,
`0x10D` and `0x10E` go to `0x195`-`0x197` with **`0x10F` skipped**, which is
quickfight.

## `0x084` is the control byte, in all four titles

Every instruction reaching the byte, per title's own overlay:

| title | offset | `cmp` `7Fh` | `cmp` `80h` | `cmp` `B3h` | stores | sites |
|---|---|---|---|---|---|---|
| Pool of Radiance | `0x084` | 9 | 10 | 4 | `00`, `B2`, `B3` | 37 |
| Curse | `0x0F7` | 15 | 13 | 10 | `00`, `B2`, `B3` | 62 |
| Silver Blades | `0x0FF` | 14 | 13 | 10 | `00`, `B2`, `B3` | 58 |
| Pools of Darkness | `0x147` | 14 | 14 | 9 | `00`, `B2`, `B3` | 58 |

That is coab's `Control` enum -- `PC_Base 0`, `PC_Mask 0x7F`, `NPC_Base 0x80`,
`NPC_Berzerk 0xB2`, `PC_Berzerk 0xB3` -- in Pool of Radiance's binary, which
coab never decompiled. `cmp ..., 7Fh` and `cmp ..., 80h` are the same "at or
above `NPC_Base`" test written two ways.

**`PC_Berzerk` is `0xB3`, which is itself above `NPC_Base`.** So the test is
"the engine drives this character", true of a companion and of a berzerk player
character alike, and bit 7 is not quite "this is an NPC".

**The only record anywhere here with a non-zero control byte** is `CHRDATA7.SAV`
of Treasures of the Savage Frontier's shipped save -- OUGO, level 8, control
`0xB2`, combat-icon slot 6, in the seventh record of an eight-record party. It
is a downloaded save with no chain of custody, so it corroborates rather than
proves; but `0xB2` is a value nothing except the engine's own constant table
would produce, and it sits exactly where a companion sits.

## `0x085` is the treasure share, and it records MODIFY CHARACTER

Pool of Radiance reads it at `0x006885`, behind two guards:

```
cmp byte ptr es:[di+84h], 7Fh     ; jbe -- skip unless the engine drives him
cmp byte ptr es:[di+10Ch], 0      ; jne -- skip unless his status is Okay
mov al, es:[di+85h] / and al, 7 / add [bp-5], al
...
inc byte ptr [bp-6]               ; the else branch: a player takes one part
```

A second reader at `0x006998` runs the same guards then `cmp byte ptr
es:[di+85h], 0` / `jbe`, so a companion whose share is zero is skipped out of
the split. **For a player character the byte is never read.** Those three
reads and the one store below are the whole of the byte in the overlay:
`tools/dos/dosbyteimm.py --offset 0x85 --sites` finds four sites and no
register store at all, so a DOS record's share is whatever the file it was
loaded from held.

**Exactly one instruction in each engine stores an immediate into it, and it
stores 1**: Pool of Radiance `0x01C263`, Curse `0x023463`, Silver Blades
`0x0208A9`. All three are the last statement of the same routine, and all three
are preceded by the same loop exit -- not a control key, and the key is `4Bh`,
which is `K` for KEEP. The routine is `modifyPlayer` (`ovr018`), whose prompt
reads `Keep Exit` over `Modify:`, and which refuses outright unless the
character's experience is 0, 8333, 12500 or 25000. Pools of Darkness has no
site for the byte at all.

**CONFIRMED in the running game**, `tools/dos/dosmodifyprobe.py`, 2026-09-05. Two
human fighters rolled from CREATE NEW CHARACTER and added to the party:

| stage | PROBEA | PROBEB |
|---|---|---|
| rolled, added, saved | 0 | 0 |
| MODIFY on PROBEB, left by **EXIT**, saved | 0 | 0 |
| MODIFY on PROBEB, left by **KEEP**, saved | 0 | **1** |

Between the last two saves PROBEA's record is byte-identical and PROBEB's
differs at **one offset of 285**, `0x085`. `WISH-SPEC-por-304-modify-exited`
and `WISH-SPEC-por-304-modify-kept` are the pair.

That is why the corpus splits on provenance rather than on anything about the
characters: 66 of 66 Pool of Radiance archive records read 1, and 38 of 38
records this project rolled and never modified read 0. Silver Blades' MALACHITE
reads 0 for the same reason, and not because he is a companion -- his control
byte is 0.

## The low seven bits are a morale percentage, and the C64 keeps the same byte

This section settled the UNKNOWN the rest of the page left -- what a plain
companion's control byte holds -- and it needed no companion and no emulator.
The C64 port answers it, because **C64 `0x0B8` is the same field as DOS
`0x084`, with the same encoding**, and the two engines can be read against each
other. `tools/c64/recordsweep.py --game pool --offset 0xB8 --context` is the C64
census and `tools/dos/dosdis16.py` the DOS listing.

| what happens | Pool of Radiance, C64 | Pool of Radiance, DOS |
|---|---|---|
| a script makes a character a companion with a morale | `DUNGEON $2753`: `JSR $1B87` (fetch the script argument) / `LSR A` / `ORA #$80` / `STA $6BB8` | `0x00390A`: a call returning the argument / `shr ax, 1` / `or al, 80h` / `mov es:[di+84h], al` |
| a script makes a character a companion, morale untouched | `DUNGEON $1AF6`: `LDA #$80` / `ORA $6BB8` / `STA $6BB8` | `0x007FAB`: script command `0B8h`, the supplied value stored straight in |
| the engine uses the morale | `COMBAT $211C`: `LDA $6BB8` / `BPL` out / `AND #$7F` / `ASL A` | `0x00BD09`, behind `cmp es:[di+84h], 7Fh` / `ja`: `and al, 7Fh` / `shl ax, 1` |
| a spell drives a character berserk | `SPELLE00 $0C76`, `SPELLE04 $0AFA`: `LDA #$B2` / `LDX $6BB8` / `BMI` / `TXA` / `ORA #$FE` | `0x02917F`: `cmp es:[di+84h], 7Fh` / `jbe` / `mov` `0B2h` or `0B3h` |

**So the low seven bits are a morale percentage stored halved**, and the scale
is the clamp in Curse's own C64 code at `SECSET64 $0A14` -- Pool of Radiance's
`COMBAT $211C` with the ceiling written out:

```
LDA $7CB8 / BPL out      ; only for a character the engine drives
AND #$7F / ASL A         ; the stored value, doubled
CMP #$64 / BCC / LDA #$64 ; clamped at 100
EOR #$FF / SEC / ADC #$64 ; 100 - it, and then the hit points
```

The two reads after it are `hp_current` and `hp_max` (`0x119` and `0x076` in
the C64 record), which is an AD&D morale check adjusted by how hurt the
character is. DOS's own out-of-range guard agrees on the scale: at
`0x00D976` it takes `& 7Fh`, and if the result is 0 or above `66h` it replaces
the whole byte with `80h` plus a default from the encounter -- so a raw value
of 1 to 102 is what the engine considers sane. CONFIRMED for the encoding, and
the *name* morale is PROBABLE: it is what coab calls the byte, it is a
percentage, and it is checked against the character's wounds, but no
disassembly here reaches the consequence of failing the check.

**There is therefore no single "plain companion" constant to find**, which is
why no immediate anywhere is a bare `80h`. A companion's byte is `0x80 | (his
own morale / 2)`, supplied per companion by the area script, and every value
from `0x80` to `0xFF` is legitimate.

**The one place the two ports disagree is the berserk player character.** DOS
writes `0xB3` and reads it back with `cmp ..., 0B3h` / `mov ..., 0`; the C64
writes `old | 0xFE` and reads it back with `SQRPACI64 $09B5`, `CMP #$FE` /
`BCC` / `AND #$01` -- which preserves bit 0, the C64's own trainer flag, where
DOS has nothing to preserve. Both ports write `0xB2` for a berserk companion.

### What the records hold, both ports

`tools/records/controlbyte.py`, 2026-09-07. The C64 half is new; the DOS half
reproduces the counts above through `tools/dos/dostailcensus.py`'s finder.

| port | records | `$00` | `$01` | engine-driven |
|---|---|---|---|---|
| C64, all three titles | 297 | 276 | 16 | 5, all in `npc_party.d64` |
| DOS, all four titles | 458 | 457 | 0 | 1, OUGO at `$B2` |

The five C64 companions are MAD MAN `$80`, DIRTEN `$B1`, and GENHEERIS,
PRINCESS FATIMA and SKULLCRUSHER at `$B2` -- morale 0, 98 and 100. **A bare
`0x80` does exist in a save**, which the page previously said no specimen held.
`npc_party.d64` has been through an editor (`docs/90-specimens.md`), so it
corroborates rather than proves; what makes it more than a curiosity is that
`$B1` is a value no immediate in either engine writes and only the
halve-and-set-bit-7 producer can make.

The sixteen C64 records at `$01` are BRUTUS, thirteen times, plus three players
of `npc_party.d64`: bit 0 is the trainer flag, set by `GEN $155D` when a score
is changed in the character-modification screen and restored from a saved copy
at `$157F` if the player leaves without keeping. **DOS records the same thing
in the share byte instead** -- 64 of the 177 Pool of Radiance records this
machine holds read `0x085` = 1, and the counts per title are in the table
below -- so the ports keep one flag in two different bytes, and a DOS control
byte's bit 0 stands for nothing. That crossing is what the conversion has to
do, and the last section says how.

### The C64's own treasure share is `0x0FA`, not the byte beside the control

`POST.COM $194A` is DOS `0x006885` on the other port, guard for guard, and
**it is the only instruction in the title that touches the byte at all**:
`tools/c64/recordsweep.py --game pool --offset 0xFA` finds one reference in
589 distinct files and `--indirect` finds none, so nothing in C64 Pool of
Radiance ever *writes* `0x0FA`, and a C64 player character's share is zero
because no code puts anything else there -- 90 of 90 records on the fifteen
`PORSAVE*.D64` save disks.

```
LDA $6BB8 / BPL out      ; only for a character the engine drives
LDA $6BFA / BEQ out      ; a share of zero takes nothing
AND #$03                 ; DOS masks with 7 here
... added to two running totals
```

The engines' own consumers settle the port boundary: C64 masks `0x0FA` with
`3`; DOS and Amiga mask their aligned byte with `7`. Every engine tests the raw
byte for zero before applying its mask. `goldbox.layout` names the C64 field
and the neutral record preserves the raw byte, including explicit zero.

## What the conversion does with them

`goldbox.dos_codec.WRITE_CONSTANTS` supplies the destination's `1` only when a
source has no neutral treasure share. A present field overwrites it, including
`0`; the C64 writer likewise writes only a present field.

The control byte remains separate: bit 7 and the low seven morale bits cross
through `npc` and `npc_control_byte`, and a player character's DOS control byte
is written **exactly** `0x00`, which is what `0x0251B7`'s equality test
demands.

### For a player character the two ports' live bytes are crossed over

This is the correction `#620 (A C64 party that used the trainer cannot be
saved as a DOS save, because the DOS writer zeroes the byte recording it)`
made, and the reason the page previously stopped short of it is that the two
flags had been read as separate facts about separate ports rather than as one
field in two places:

| | the ability-altered flag | the treasure share |
|---|---|---|
| C64 | `0x0B8` bit 0, written by `GEN $155D` | `0x0FA`, read only for an engine-driven character and **written by nothing** |
| DOS | `0x085`, written by MODIFY's KEEP at `0x01C263` | `0x085`, the same byte |
| Amiga Pool of Radiance | `0x086` | `0x086`, the same byte (`docs/124-amiga-port.md` 1.21) |

So the neutral `treasure_share` field is the byte DOS and the Amiga keep after
their control byte, and `goldbox/c64_codec.py` converts both ways: for a
player character it reads `flags_0b8` bit 0 in place of `0x0FA`, and writes
the value back to `flags_0b8` bit 0 with `0x0FA` left at zero. A companion is
untouched, and no Amiga writer needed a change, because it already writes that
neutral field into its own aligned byte.

What every record on this machine holds in the share byte,
`tools/dos/dostailcensus.py --field field_83_87 --per-title` and a sweep of
the registry's `PORSAVE*.D64` through `editor.saveplan.c64_slot_records`:

| port and title | records | `0` | `1` | above 1 |
|---|---|---|---|---|
| DOS Pool of Radiance | 177 | 113 | 64 | 0 |
| DOS Curse | 79 | 18 | 61 | 0 |
| DOS Silver Blades | 52 | 11 | 41 | 0 |
| DOS Pools of Darkness | 12 | 8 | 4 | 0 |
| C64 Pool of Radiance save disks | 90 | 90 | 0 | 0 |

The control byte is `0x00` in all 320 DOS records, so every one of them is a
player character and every `1` above is the modify flag.

### What still refuses

Values `0` through `3` preserve the raw byte and engine behaviour across all
three ports for a companion. DOS and Amiga preserve `4` through `7` between
themselves. A value with bit 2 set refuses before output when crossing the C64
two-bit family and the DOS/Amiga three-bit family: masking, clamping or
defaulting would lose the raw-zero condition or change the engine-effective
share.

One record reports a loss and no engine writes it: a C64 **player character**
holding both bit 0 of `0x0B8` and a non-zero `0x0FA`. The other ports have one
byte for the two, so the raw share crosses as it always did and the flag is
reported dropped, which refuses the conversion rather than losing it in
silence. Nothing in C64 Pool of Radiance writes `0x0FA` and 90 of 90 records
hold zero, so no save here can reach it.
