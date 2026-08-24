"""The DOS ``SAVGAM<slot>.DAT`` saved game, mapped field by field (#59).

`por/dos.py` decodes the DOS *character record*; this module is the map of
the saved game around it, the DOS counterpart of `docs/30-savegame-layout.md`.
Everything here was established by differential analysis in DOSBox: nine
specimens -- Donald's own slots A, B and J, four saves taken one action
apart, and two engine resaves of converted parties.  The Curse and Secret
file sizes above are a spot check and are PROBABLE at best; the five-region
map is Pool of Radiance's.  `docs/141-dos-savegame.md` is the prose
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


class DosSaveError(ValueError):
    """A buffer that is not a DOS saved game, or an address outside it.

    Its own class rather than `por.dos.DosRecordError` because this module is
    the layer *under* `por/dos.py` -- importing it the other way would invert
    the edge the module graph in `docs/117-save-conversion.md` exists to keep
    honest.  Both derive from `ValueError`, so a caller that catches that
    catches either.
    """

SAVGAM_SIZE = 13137          # Pool of Radiance; Curse is 13149, Secret 5469
VAR_BASE = 0x4900
VAR_WORDS = 2560             # $4900-$52FF
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
        raise DosSaveError(f"${address:04X} is outside the variable space")
    return VAR_OFFSET + 2 * (address - VAR_BASE)


def _whole(save: bytes) -> bytes:
    """Refuse a truncated buffer before indexing a fixed offset into it.

    Every accessor here reads an offset established for a 13137-byte Pool of
    Radiance save.  Without this a short buffer raises `IndexError` or
    `struct.error` from somewhere inside, which says nothing useful; the
    sibling `por.dos.savgam_word` already checks its length and this matches
    it.  Curse and Secret are other sizes and are not this module's yet.
    """
    if len(save) < SAVGAM_SIZE:
        raise DosSaveError(
            f"a DOS saved game is {SAVGAM_SIZE} bytes; this is {len(save)}")
    return save


def word(save: bytes, address: int) -> int:
    return struct.unpack_from("<H", _whole(save), word_offset(address))[0]


def dax_number(save: bytes) -> int:
    """Which GEO/ECL/WALLDEF/8X8D container holds the current area."""
    return _whole(save)[0]


def area_id(save: bytes) -> int:
    return word(save, AREA)


def clock(save: bytes) -> tuple[int, int, int, int]:
    """(hour, minute, day, month) -- the C64's digit encoding, as words."""
    d = [word(save, CLOCK + i) for i in range(6)]
    return d[3], d[2] * 10 + d[1], d[4], d[5]


def party_size(save: bytes) -> int:
    return _whole(save)[PARTY_SIZE_BYTE]


def position(save: bytes) -> tuple[int, int, int]:
    """(x, y, facing) with facing in the C64's units, 0 N 1 E 2 S 3 W."""
    save = _whole(save)
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
    save = _whole(save)
    out = []
    for n in range(PARTY_ENTRIES):
        at = PARTY_TABLE + n * PARTY_ENTRY
        length = save[at]
        # An entry is one length byte, the name, then 32 bytes of heap
        # scratch, so a real name cannot exceed eight -- which is exactly
        # `CHRDATA1`. A looser bound reads the scratch as filename characters
        # and returns a wrong-but-plausible name instead of nothing.
        if 0 < length < PARTY_NAME_LEN:
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
#:
#: CONFIRMED for one area pair in one direction; a second pair would firm it
#: up. The addresses are formatted from the constants above so the recipe
#: cannot drift from the map it is a recipe for.
RETARGET_WRITES = (
    "byte 0 = the target area's DAX number",
    f"word ${AREA:04X} = the target area id",
    f"word ${SCRIPT:04X} = the target area id",
    f"word ${DISK:04X} = the target area's DAX number",
    f"words ${WALLSET:04X}-${WALLSET + 2:04X} = the target's wallset triple "
    f"($FFFF = empty slot)",
    f"words ${WALLMAP:04X}-${WALLMAP + 2:04X} = (1,2,3) for three sets, "
    f"(1,$FFFF,$FFFF) for one",
    f"bytes {POS_X}-{POS_FACING} = x, y, facing*{FACING_SCALE}",
    f"word ${PARTY_SIZE:04X} and byte {PARTY_SIZE_BYTE} = the party size",
)
