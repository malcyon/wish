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
``5121``-``12800``    the ECL text buffer: the current area's script, its
                      ``ECL<n>.DAX`` block from byte 2 on.  **Live on load**
                      -- a retarget that leaves the template's script here
                      dies in ``Load3DMap`` whatever else it writes, so it is
                      one of the retarget's writes and the one thing the
                      recipe needs the game's own files for.
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

ECL_BUFFER = (5121, 12801)   # the loaded script text -- **live**, see below
#: The ECL text buffer holds the target area's `ECL<n>.DAX` block from its
#: third byte on: every block opens `88 13` -- `u16le` 5000 -- and the save
#: carries everything after it.  #59 measured the offset as 39/148/28 for
#: areas 0/21/20 and recorded the buffer as dead weight the loader refills;
#: both are wrong.  The offset is 2 for all three, and a retarget that leaves
#: the template's script in place dies in `Load3DMap` however many variables
#: it writes -- `work/p60/run2`, variant X1.
ECL_HEADER = 2

POS_X, POS_Y, POS_FACING = 12801, 12802, 12803
FACING_SCALE = 2             # 0 N, 2 E, 4 S, 6 W
PARTY_SIZE_BYTE = 12808      # the same count the word at $503E carries

PARTY_TABLE = 12809          # six entries of 41 bytes
PARTY_ENTRY = 41
PARTY_ENTRIES = 6
PARTY_NAME_LEN = 9           # length byte + up to 8 of "CHRDAT<letter><n>"

# -- the named VM variables --------------------------------------------------
AREA = 0x49C5                # geo block id == area id, `por/areas.py` numbers
EMPTY = 0xFFFF               # an empty word slot, the wallset triple's $FF
CLOCK_DIGITS = 6
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
    `struct.error` from somewhere inside, which says nothing useful.  Curse
    and Secret are other sizes and are not this module's yet.
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
    area (PORSAVE13's Slums triple 2,4,1 == slot J's, PORSAVE's Sokol Keep
    1,5,9 == slot B's), so a converter can source it from the C64 save.  New
    Phlan is the exception: the C64 loads no `WALLSET` there and DOS's own
    save names one, and an all-empty triple draws it identically anyway.
    """
    return tuple(word(save, WALLSET + i) for i in range(3))


def put_character_files(save: bytearray, slot: str) -> None:
    """Name the files the engine will load the party from.

    The engine loads the party from these names and not from the slot letter
    chosen at the LOAD menu -- slot J's file staged as slot C loaded J's
    characters (#59) -- so a save that does not name its own files loads
    somebody else's party.  The engine's own resave rewrites the letters; so
    does this.  All six entries are written, not `count` of them: no specimen
    shows what a blanked entry does, and the party size says how many are
    read.
    """
    _whole(save)
    for n in range(PARTY_ENTRIES):
        at = PARTY_TABLE + n * PARTY_ENTRY
        name = f"CHRDAT{slot.upper()}{n + 1}".encode("ascii")
        save[at] = len(name)
        save[at + 1:at + 1 + len(name)] = name


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


# ---------------------------------------------------------------------------
# The `.DAX` container, enough of it to lift one ECL block
# ---------------------------------------------------------------------------
#: A `.DAX` is a `u16le` index size, `size // 9` entries of
#: `id:u8, offset:u32le, raw:u16le, compressed:u16le`, then the block data with
#: each entry's offset relative to its start.  Blocks are byte run-length
#: coded: a lead byte under 128 copies the next `n + 1` bytes, one at or above
#: it repeats the next byte `256 - n` times.  `tools/dosbox.py` carries the
#: same decode for the harness; this copy exists because a retarget needs one
#: ECL block and `por/` may not import from `tools/`.
DAX_ENTRY = 9


def dax_index(data: bytes) -> list[tuple[int, int, int, int]]:
    """`(id, offset, raw size, compressed size)` for each block of a `.DAX`.

    A file too short for the index it declares is named as such rather than
    raising `struct.error` from inside a comprehension: the caller here is a
    conversion reading the player's own game directory, and "this file is not
    a .DAX" is the answer it has to be able to report.
    """
    try:
        size = struct.unpack_from("<H", data, 0)[0]
        return [struct.unpack_from("<BIHH", data, 2 + DAX_ENTRY * i)
                for i in range(size // DAX_ENTRY)]
    except struct.error as e:
        raise DosSaveError(f"not a .DAX: {e}") from e


def dax_block(data: bytes, block_id: int) -> bytes:
    """One block of a `.DAX`, decompressed.  Raises if it is not there."""
    index = dax_index(data)
    base = 2 + struct.unpack_from("<H", data, 0)[0]
    for bid, off, raw, comp in index:
        if bid != block_id:
            continue
        out = bytearray()
        chunk = data[base + off:base + off + comp]
        i = 0
        while i < len(chunk) and len(out) < raw:
            n = chunk[i]
            if n < 128:
                out += chunk[i + 1:i + 2 + n]
                i += n + 2
            else:
                out += bytes([chunk[i + 1]]) * (256 - n)
                i += 2
        if len(out) != raw:
            raise DosSaveError(
                f"block {block_id} unpacked to {len(out)} bytes, not {raw}")
        return bytes(out)
    raise DosSaveError(f"no block {block_id} in this .DAX")


# ---------------------------------------------------------------------------
# Writing: the retarget, and the two fields a conversion carries
# ---------------------------------------------------------------------------
def put_word(save: bytearray, address: int, value: int) -> None:
    struct.pack_into("<H", save, word_offset(address), value & 0xFFFF)


def put_position(save: bytearray, x: int, y: int, facing: int) -> None:
    """The square, with `facing` in the C64's 0-3."""
    _whole(save)
    save[POS_X], save[POS_Y] = x, y
    save[POS_FACING] = facing * FACING_SCALE


def put_clock(save: bytearray, digits) -> None:
    """The six digit words, in the C64's own order and encoding."""
    digits = list(digits)
    if len(digits) != CLOCK_DIGITS:
        raise DosSaveError(f"the clock is {CLOCK_DIGITS} digits, not "
                           f"{len(digits)}")
    for i, d in enumerate(digits):
        put_word(save, CLOCK + i, d)


def put_party_size(save: bytearray, count: int) -> None:
    """Both copies, which move together."""
    _whole(save)
    put_word(save, PARTY_SIZE, count)
    save[PARTY_SIZE_BYTE] = count


def wall_map(wallset) -> tuple[int, int, int]:
    """The index map that goes with a triple: 1,2,3 for the slots it fills."""
    return tuple(EMPTY if w == EMPTY else i + 1 for i, w in enumerate(wallset))


def retarget(save: bytearray, *, area: int, dax: int, wallset, script: bytes
             ) -> None:
    """Move a saved game to another area.  `script` is its `ECL` DAX block.

    Every write `RETARGET_WRITES` lists except the square and the party
    size, which a conversion sets separately because they change on their
    own.  Take any of these away and the game exits to DOS.
    """
    _whole(save)
    save[0] = dax
    put_word(save, AREA, area)
    put_word(save, SCRIPT, area)
    put_word(save, DISK, dax)
    for i, w in enumerate(wallset):
        put_word(save, WALLSET + i, w)
    for i, w in enumerate(wall_map(wallset)):
        put_word(save, WALLMAP + i, w)
    body = script[ECL_HEADER:]
    start, end = ECL_BUFFER
    if len(body) > end - start:
        raise DosSaveError(f"area {area}'s script is {len(body)} bytes and the "
                           f"buffer holds {end - start}")
    save[start:start + len(body)] = body


#: What a retarget must write.  Established by bisection -- `work/p59` runs
#: 2-9 for the variables, `work/p60/run2` for the script buffer.  The naive
#: recipe (header + $49C5 + $49F2 + square) dies with "Unable to load geo in
#: Load3DMap."; so does the seven-write recipe that leaves the template's
#: script staged.
#:
#: CONFIRMED for three area pairs: 0 -> 20 (#59 run 9), 21 -> 20 and 20 -> 0
#: (`work/p60/run2`, X2 and X3), each loaded and walked.  The addresses are
#: formatted from the constants above so the recipe cannot drift from the map
#: it is a recipe for.
RETARGET_WRITES = (
    "byte 0 = the target area's DAX number",
    f"word ${AREA:04X} = the target area id",
    f"word ${SCRIPT:04X} = the target area id",
    f"word ${DISK:04X} = the target area's DAX number",
    f"words ${WALLSET:04X}-${WALLSET + 2:04X} = the target's wallset triple "
    f"($FFFF = empty slot)",
    f"words ${WALLMAP:04X}-${WALLMAP + 2:04X} = (1,2,3) for three sets, "
    f"(1,$FFFF,$FFFF) for one",
    f"bytes {ECL_BUFFER[0]}-{ECL_BUFFER[1] - 1} = the target area's "
    f"ECL<n>.DAX block from byte {ECL_HEADER} on",
    f"bytes {POS_X}-{POS_FACING} = x, y, facing*{FACING_SCALE}",
    f"word ${PARTY_SIZE:04X} and byte {PARTY_SIZE_BYTE} = the party size",
)
