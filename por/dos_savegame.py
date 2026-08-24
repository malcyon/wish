"""The DOS ``SAVGAM<slot>.DAT`` saved game, mapped field by field (#59).

`por/dos.py` decodes the DOS *character record*; this module is the map of
the saved game around it, the DOS counterpart of `docs/30-savegame-layout.md`.
Everything here was established by differential analysis in DOSBox -- one
known in-game change per save pair -- plus three of the player's own slots
and two cross-title spot checks.  `docs/141-dos-savegame.md` is the prose
form; `docs/50-experiments.md` "Mapping the DOS saved game" is the reasoning.

The file, in five regions
-------------------------
====================  =========================================================
``0``                 one byte: the current area's ``.DAX`` container number
                      (1-8).  Numerically the same as the C64 ``POOL`` disk
                      side that carries the area.
``1``-``5120``        2560 ``u16le`` VM variables, indexed by the address the
                      ECL bytecode uses: ``offset = 1 + 2*(addr - $4900)``.
                      Sparse -- 2407 of 2560 words are zero in all nine
                      specimens.  Quest flags, the clock, the area, the party
                      size and the wallset triple all live here, mostly at the
                      *same ECL addresses the C64 uses*.
``5121``-``12800``    the ECL text buffer: the current area's script,
                      byte-identical to its ``ECL<n>.DAX`` block from some
                      interior offset on.  **Dead on load** -- the engine
                      reloads the script from the DAX file (proven by loading
                      a retargeted save whose buffer still held another
                      area's bytes), so a converter may leave it.
``12801``-``12808``   the party's square and size: x, y, facing (doubled),
                      then four bytes of unknowns, then the party size again
                      as one byte.
``12809``-``13136``   six 41-byte character entries -- a length-prefixed
                      ``CHRDAT<letter><n>`` filename the engine *actually
                      loads the party from* (proven: a slot-J file staged as
                      slot C loaded J's characters), each followed by 32
                      bytes of heap scratch -- then 82 bytes of UI scratch.
====================  =========================================================
"""
from __future__ import annotations

import struct

SAVGAM_SIZE = 13137          # Pool of Radiance; Curse is 13149, Secret 5469
VAR_BASE = 0x4900
VAR_WORDS = 2560             # $4900-$58FF
VAR_OFFSET = 1

ECL_BUFFER = (5121, 12801)   # the loaded script text; dead on load

POS_X, POS_Y, POS_FACING = 12801, 12802, 12803
FACING_SCALE = 2             # 0 N, 2 E, 4 S, 6 W
PARTY_SIZE_BYTE = 12808      # the same count the word at $503E carries

PARTY_TABLE = 12809          # six entries of 41 bytes
PARTY_ENTRY = 41
PARTY_ENTRIES = 6
PARTY_NAME_LEN = 9           # length byte + up to 8 of "CHRDAT<letter><n>"

# -- the named VM variables --------------------------------------------------
AREA = 0x49C5                # geo block id == area id, `por/areas.py` numbers
CLOCK = 0x49C6               # six digit words, exactly the C64's six bytes:
                             # sub-minute, minute units, minute tens, hour,
                             # day, month (limits 10 10 6 24 30 12)
INDOORS = 0x49E6             # 1 in all three indoor specimens
SCRIPT = 0x49F2              # the area script id
FLAGS_FIRST, FLAGS_LAST = 0x4A20, 0x4AF8    # quest flags, shared ECL addresses
WALLSET = 0x4AFA             # three words: WALLDEF/8X8D block ids, $FFFF empty
WALLMAP = 0x4AFD             # three words: (1,2,3) with three sets loaded,
                             # (1,$FFFF,$FFFF) with one
PARTY_SIZE = 0x503E          # 6 -> 1 when a six-member save became one member
DISK = 0x5012                # the DAX container number again, as a VM word;
                             # the geo load fails without it
ENCOUNTER_TEXT = 0x5227      # string buffer, one ASCII character per word


def word_offset(address: int) -> int:
    """File offset of the VM word for an ECL address."""
    if not VAR_BASE <= address < VAR_BASE + VAR_WORDS:
        raise ValueError(f"${address:04X} is outside the variable space")
    return VAR_OFFSET + 2 * (address - VAR_BASE)


def word(save: bytes, address: int) -> int:
    return struct.unpack_from("<H", save, word_offset(address))[0]


def dax_number(save: bytes) -> int:
    """Which GEO/ECL/WALLDEF/8X8D container holds the current area."""
    return save[0]


def area_id(save: bytes) -> int:
    return word(save, AREA)


def clock(save: bytes) -> tuple[int, int, int, int]:
    """(hour, minute, day, month) -- the C64's digit encoding, as words."""
    d = [word(save, CLOCK + i) for i in range(6)]
    return d[3], d[2] * 10 + d[1], d[4], d[5]


def party_size(save: bytes) -> int:
    return save[PARTY_SIZE_BYTE]


def position(save: bytes) -> tuple[int, int, int]:
    """(x, y, facing) with facing in the C64's units, 0 N 1 E 2 S 3 W."""
    return save[POS_X], save[POS_Y], save[POS_FACING] // FACING_SCALE


def wall_triple(save: bytes) -> tuple[int, int, int]:
    """The up-to-three wallset block ids, $FFFF = empty.

    Byte-identical to the C64 loaded-files cache slots 15-17 for the same
    area (PORSAVE13's Slums triple 2,4,1 == slot J's), so a converter can
    source it from the C64 save.
    """
    return tuple(word(save, WALLSET + i) for i in range(3))


def character_files(save: bytes) -> list[str]:
    """The CHRDAT filenames the engine will load the party from."""
    out = []
    for n in range(PARTY_ENTRIES):
        at = PARTY_TABLE + n * PARTY_ENTRY
        length = save[at]
        if 0 < length <= 12:
            out.append(save[at + 1:at + 1 + length].decode("ascii", "replace"))
    return out


def encounter_text(save: bytes, limit: int = 96) -> str:
    """The encounter-message scratch, one character per word."""
    chars = []
    for i in range(limit):
        v = word(save, ENCOUNTER_TEXT + i)
        chars.append(chr(v) if 32 <= v < 127 else " ")
    return "".join(chars).strip()


#: What a retarget must write, established by bisection (runs 2-9, work/p59):
#: the naive recipe (header + $49C5 + $49F2 + square) dies with "Unable to
#: load geo in Load3DMap."; adding $5012 cures the geo and $4AFA-$4AFF the
#: wallset.  The ECL buffer needs nothing.
RETARGET_WRITES = (
    "byte 0 = the target area's DAX number",
    "word $49C5 = the target area id",
    "word $49F2 = the target area id",
    "word $5012 = the target area's DAX number",
    "words $4AFA-$4AFC = the target's wallset triple ($FFFF = empty slot)",
    "words $4AFD-$4AFF = (1,2,3) for three sets, (1,$FFFF,$FFFF) for one",
    "bytes 12801-12803 = x, y, facing*2",
)
