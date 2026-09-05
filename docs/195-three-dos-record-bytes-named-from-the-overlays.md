# Three DOS record bytes named from the shipped overlays

Four bytes of the DOS character record that this project had wrong, right for
the wrong reason, or unattributed, settled by reading the game's own
instructions rather than by counting saves. `tools/dosbyteimm.py` is the scan;
`goldbox/dos_layout.py` and `goldbox/dos.py` carry the notes; the issues are
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

## The method: what constants the engine puts in a byte

`tools/dosfieldrefs.py` counts the instructions that address a record offset
through an `ES`-prefixed displacement. It does not say what value they write,
and that is the question that names a field. `tools/dosbyteimm.py` adds the
immediate.

**The shape of the set of constants is the finding, not the count.** A byte the
engine sets to `0Ah`, `0Ch` and `0FFh` and compares against 8 is not a marching
position in a six-character party, whatever six records on a disk happen to
hold. A byte it sets to `0B2h` and `0B3h` and compares against `80h` and `7Fh`
is a bitfield with a flag in the top bit. Both readings below came out that
way, before any save was consulted.

Every limit of `tools/dosfieldrefs.py` still applies: the image is scanned as
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

**The identifier in `goldbox/dos_layout.py` is still `party_order` and is a
misnomer.** `goldbox.dos.DIRECT`'s reader loop requires the DOS field name and
the neutral field name to be the same string, so renaming the DOS field means
renaming the neutral one -- which `goldbox/amiga.py`, `goldbox/c64_codec.py`,
`goldbox/yaml_io.py` and the window's own `field_party_order` all read. The
label is corrected to "Combat icon slot" and the note says the rest. What the
conversion writes is right either way: the C64 keeps its own 0-7 slot index at
`goldbox/layout.py` `0x10D`, both whole-save directions renumber by file
position, and the DOS loader reallocates the byte on load regardless.

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
the split. **For a player character the byte is never read.**

**Exactly one instruction in each engine stores an immediate into it, and it
stores 1**: Pool of Radiance `0x01C263`, Curse `0x023463`, Silver Blades
`0x0208A9`. All three are the last statement of the same routine, and all three
are preceded by the same loop exit -- not a control key, and the key is `4Bh`,
which is `K` for KEEP. The routine is `modifyPlayer` (`ovr018`), whose prompt
reads `Keep Exit` over `Modify:`, and which refuses outright unless the
character's experience is 0, 8333, 12500 or 25000. Pools of Darkness has no
site for the byte at all.

**CONFIRMED in the running game**, `tools/dosmodifyprobe.py`, 2026-09-05. Two
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

## What the conversion does with them, and what it still cannot

`goldbox.dos.WRITE_CONSTANTS` writes `00 00 01 00 00` into the five-byte run
(`00 01 00 00` in the four-byte titles). **1 is a choice, and the note now says
so**: the byte is inert for a player character, 1 is the only value any engine
writes, and 0 is the one value the split treats specially, so a converted
companion written with 0 would silently get nothing. It stays in
`WRITE_CONSTANTS` rather than moving to `WRITE_DEFAULTS`, because a default is
masked out of the round trip and moving it would hide MALACHITE's real
difference instead of converting it.

**The neutral `npc` flag now has a DOS home that nobody has wired up**: bit 7
of the control byte, in all four titles, against bit 7 of `0x0B8` on the C64
(`goldbox/record.py`'s `is_npc`). `goldbox.dos.WRITE_DROPPED`'s reason -- "no
attributed DOS field holds it" -- is wrong as of this page. Two things block
the wiring and one blocks the value:

* splitting `field_83_87` into named bytes needs `goldbox/amiga.py`, which
  names the whole run in its own drop table;
* the C64 side drops the flag in the other direction too, in
  `goldbox/c64_codec.py`;
* **what a plain companion's control byte holds is UNKNOWN.** Every immediate
  the engines store is `00`, `B2` or `B3`; not one is a bare `80h`. A plain
  companion's value arrives from a register store fed by monster data or a
  script, and the only specimen anywhere is OUGO's `B2`. Writing `0x80` would
  be a guess at the low seven bits, which `PC_Mask` says carry a morale value.
  **What would settle it:** pick up a companion in DOS Curse or Silver Blades,
  save, and read the byte.
