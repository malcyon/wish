"""What more than one Amiga title's codec needs, and nothing either one owns.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 10 split
`goldbox/amiga_codec.py` by title, because one 5,770-line file held Pool of
Radiance, Pools of Darkness, and Curse and Silver Blades together and the
unprefixed names in it read as the Amiga's when they were one title's.  This
module is the bottom of that split: `goldbox/amiga_pod.py`,
`goldbox/amiga_por.py` and `goldbox/amiga_later.py` import it and it imports
none of them at the top.

Nothing here carries a title fact.  The two byte readers and the enum-table
helper are the machine's rather than any game's; the three key tuples name
neutral fields, which every port spells the same way; and
:func:`amiga_shape_for`, :data:`CONVERTS` and :data:`WRITES` are the registries
that have to see all four titles at once to answer at all.

**:func:`amiga_shape_for` imports Pool of Radiance's record length inside the
function.** That is deliberate: 288 is Pool of Radiance's own number and it
stays in that title's module, so this one is reached by the titles rather than
reaching for them.
"""

from __future__ import annotations

import struct

from . import dos_port
from .amiga_port import AMIGA_DELTAS_BY_SIZE, AmigaRecordError


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]

def _name(table: tuple[str, ...], index: int) -> str:
    return table[index] if 0 <= index < len(table) else f"?{index}"


#: The six abilities in the order the sheet draws them.
ABILITY_KEYS = ("strength", "intelligence", "wisdom", "dexterity",
                "constitution", "charisma")

SAVE_KEYS = ("save_paralysis", "save_petrification", "save_wands",
             "save_breath", "save_spell")

THIEF_KEYS = ("thief_pick_pockets", "thief_open_locks", "thief_find_traps",
              "thief_move_silently", "thief_hide_in_shadows",
              "thief_hear_noise", "thief_climb_walls",
              "thief_read_languages")


def amiga_shape_for(size: int) -> "dos_port.DosDeltas":
    """Which title an Amiga character record of this length belongs to.

    The Amiga three are 288, 428 and 340 bytes and no two are the same, so a
    record names its own title the way the DOS four do
    (`goldbox.dos_port.deltas_for`) -- which is what lets a reader handed an
    `.adf` with no other clue say what is on it.  Pool of Radiance is not in
    :data:`AMIGA_DELTAS` because it has no `AmigaDeltas` of its own: it is
    read straight through the DOS field table (:func:`to_dos_record`).

    Answers with the **DOS** shape rather than the Amiga one, because that
    is the shape carrying the `key` a conversion is registered against
    (`editor/convert.py`'s `Direction.source_key`) and the one both Amiga
    readers already re-cut into.
    """
    # Deferred, and the only reach out of this module: 288 is Pool of
    # Radiance's own record length and belongs in that title's file, so this
    # one stays underneath all three rather than importing one at the top.
    from .amiga_por import AMIGA_POR_RECORD_SIZE

    if size == AMIGA_POR_RECORD_SIZE:
        return dos_port.POOL_OF_RADIANCE
    deltas = AMIGA_DELTAS_BY_SIZE.get(size)
    if deltas is None:
        known = ", ".join(str(n) for n in
                          sorted([AMIGA_POR_RECORD_SIZE]
                                 + list(AMIGA_DELTAS_BY_SIZE)))
        raise AmigaRecordError(
            f"no Amiga Gold Box character record is {size} bytes; the three "
            f"this reads are {known}")
    return deltas.dos


#: The titles an Amiga save slot can be **converted from** today, as the DOS
#: shapes whose `key` `editor/convert.py` registers a direction against.
#:
#: Pool of Radiance alone, and the two that are missing are missing for one
#: reason each rather than for want of a row here.  Curse of the Azure Bonds
#: and Secret of the Silver Blades have their records read
#: (:data:`AMIGA_DELTAS`) and their save disks read
#: (`goldbox/amiga_later.py`), and what neither has is a saved-game reader:
#: `goldbox.world_state.from_amiga` is Pool of Radiance's own container, and
#: `#55`'s work stopped at the records.  Converting a party without the game
#: around it is the thing `#353 (Convert an Amiga Pool of Radiance save to
#: the C64, so a party standing in the Slums on the Amiga arrives there in
#: VICE)` exists to stop.
CONVERTS: "tuple[dos_port.DosDeltas, ...]" = (dos_port.POOL_OF_RADIANCE,)

#: The titles a C64 or DOS save can be **converted to** an Amiga save disk
#: today, as the DOS shapes whose `key` `editor/convert.py` registers a
#: direction against -- the mirror of `dos.WRITES`, and named the same way
#: for the same reason: what the *destination* can be written from nothing,
#: not what the source happens to be.
#:
#: Pool of Radiance alone (`#316 (Write the Amiga Pool of Radiance saved
#: game from the source save, so a converted party arrives where it was
#: standing)`): `new_por_savegame` and `make_por_save_disk` build the whole
#: 13,141-byte `savgam<letter>.dat` and the disk around it with no template,
#: proven in two WinUAE runs, one from a C64 source and one from a DOS one.
#: Curse of the Azure Bonds and Secret of the Silver Blades have no such
#: writer -- `#359 (Bring the Amiga into every permutation: C64 ↔ Amiga and
#: DOS ↔ Amiga)`'s step 6 -- so they stay off this tuple until one exists,
#: the same way they are missing from `CONVERTS` above.
WRITES: "tuple[dos_port.DosDeltas, ...]" = (dos_port.POOL_OF_RADIANCE,)

#: Silver Blades' spellbook: 15 bytes of bitmask at `0x071`, **LSB first**
#: within each byte, where DOS spends one byte per spell for ids 1..117.
#:
#: CONFIRMED from the code: `/Secret`'s record unpacker at file offset
#: `0x28260` walks the packed record's 117 one-byte flags and, for each,
#: sets or clears bit `i mod 8` of `record[0x71 + i / 8]` through a mask
#: table at `g234e` that reads `01 02 04 08 10 20 40 80` -- least
#: significant bit first, by the table's own contents.
#:
#: CONFIRMED on 6 of 6 specimens and 62 set bits as well: PAINE's `77 78 79 80`,
#: DOMINIC's 29 ids and MORGAINE's 29 come out of the mask exactly as the DOS
#: twin's byte array holds them, and MSB-first reproduces none of the three.
#: The other three characters have an empty book on both ports.
#:
#: Curse does **not** do this: its Amiga spellbook is 100 bytes of 0 and 1 at
#: `0x079`, DOS's own shape, and the ids that come out of the eleven pregens
#: are clean class-coherent sets -- KAROLYN the cleric holds 1-8, 22-28 and
#: 37-44, ARIEL the magic-user holds 10, 11, 12, 15, 18, 21, 31, 34.  So this
