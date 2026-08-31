"""The DOS ``SAVGAM<slot>.DAT`` saved game, mapped field by field (#59).

`goldbox/dos.py` decodes the DOS *character record*; this module is the map of
the saved game around it, the DOS counterpart of `docs/30-savegame-layout.md`.
Everything here was established by differential analysis in DOSBox: twelve
specimens -- Donald's own slots A, B and J, four saves taken one action
apart, two engine resaves of converted parties, and three saves made on the
overland travel map by playing there (#59's outdoor pass, `work/p59-outdoor`).  The Curse and Secret
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
                      as one byte.  Outdoors x and y freeze at the last
                      indoor square and the live square is the VM pair
                      ``$49C3``/``$49C4`` -- `travel_square`.
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

    Its own class rather than `goldbox.dos.DosRecordError` because this module is
    the layer *under* `goldbox/dos.py` -- importing it the other way would invert
    the edge the module graph in `docs/117-save-conversion.md` exists to keep
    honest.  Both derive from `ValueError`, so a caller that catches that
    catches either.
    """


class DaxError(DosSaveError):
    """A `.DAX` block does not decode -- truncated, or not this container.

    A subclass so that `goldbox.dos.write_dos_save`, which catches `DosSaveError`
    around the block it lifts the target area's script out of, keeps catching
    it.
    """


SAVGAM_SIZE = 13137          # Pool of Radiance; Curse is 13149, Secret 5469,
                             # and Pools of Darkness has no SAVGAM?.DAT at all
                             # -- 1364 bytes of SAVGAM?.PTY beside a 12-byte
                             # VAULT?.DAT (#53). Only this one is decoded.
DAX_NUMBER = 0               # byte 0: which GEO/ECL container holds the area
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
#:
#: Past the script's end the buffer is **all zeros** -- 6 of 6 specimens,
#: Donald's A/B/J and the three outdoor saves, remnants of 209/1972/3/1113
#: bytes each without one nonzero byte (#59, the outdoor pass).  An earlier
#: claim that it held stale remnants of longer previous scripts was wrong.
ECL_HEADER = 2

POS_X, POS_Y, POS_FACING = 12801, 12802, 12803
FACING_SCALE = 2             # 0 N, 2 E, 4 S, 6 W
# The four bytes between the facing and the party size, measured over the
# twelve genuine engine-written specimens (#59). None of them is party or
# place data and none is read by the load path, but a conversion that leaves
# them at the template's values is inheriting somebody else's state, so each
# has a measured value to write instead.
SCRATCH_BYTE = 12804         # unnamed, and the value depends on where the
                             # party stands: 0 in the eight walked-in indoor
                             # saves, 14 in B and in all three outdoor ones.
                             # The engine replaced a hand-built 0 with 9 by
                             # itself, so it maintains this -- but a writer
                             # still puts the value measured for the situation
                             # it is writing, not the one measured elsewhere
SCRATCH_INDOORS, SCRATCH_OUTDOORS = 0, 14
VM_COPY_BYTE = 12805         # the low byte of $5200, equal in 13 of 13 files
VIEW_MODE_BYTE = 12806       # 1 indoors, 3 outdoors -- perfectly correlated
                             # with $49E6 in 12 of 12, so write it from that
TAIL_CONSTANT_BYTE = 12807   # 2 in all twelve genuine specimens
TAIL_CONSTANT = 2
VIEW_MODE_INDOORS, VIEW_MODE_OUTDOORS = 1, 3
PARTY_SIZE_BYTE = 12808      # the same count the word at $503E carries

PARTY_TABLE = 12809          # six entries of 41 bytes
PARTY_ENTRY = 41
PARTY_ENTRIES = 6
PARTY_NAME_LEN = 9           # length byte + up to 8 of "CHRDAT<letter><n>"

# -- the named VM variables --------------------------------------------------
TRAVEL_X = 0x49C3            # the overland square, window-local, live only
TRAVEL_Y = 0x49C4            # outdoors -- see `travel_square`
AREA = 0x49C5                # geo block id == area id, `goldbox/areas.py` numbers
                             # -- but **0 in all three outdoor saves**, not
                             # the C64's SQRDATA number (#59, outdoor pass)
EMPTY = 0xFFFF               # an empty word slot, the wallset triple's $FF
CLOCK_DIGITS = 6
CLOCK = 0x49C6               # six digit words, exactly the C64's six bytes:
                             # sub-minute, minute units, minute tens, hour,
                             # day, month (limits 10 10 6 24 30 12)
INDOORS = 0x49E6             # 1 in the three indoor specimens, 0 in the three
                             # outdoor ones; written 0->1 by the boat-back
                             # transition, writer 30F6:0CA1 (#59 run2)
SCRIPT = 0x49F2              # the area script id
FLAGS_FIRST, FLAGS_LAST = 0x4A20, 0x4AF8    # quest flags, shared ECL addresses
WALLSET = 0x4AFA             # three words: WALLDEF/8X8D block ids, $FFFF empty
WALLMAP = 0x4AFD             # three words: (1,2,3) with three sets loaded,
                             # (1,$FFFF,$FFFF) with one
PARTY_SIZE = 0x503E          # 6 -> 1 when a six-member save became one member
DISK = 0x5012                # the DAX container number again, as a VM word;
                             # the geo load fails without it
ENCOUNTER_TEXT = 0x5227      # string buffer, one ASCII character per word
VM_SCRATCH = 0x5200          # byte 12805 is this word's low byte
# The shared, cross-port ECL variable space ends here. No ECL script in the
# thirty-script corpus references an address at or above $4AF9 (2544 distinct
# bracketed addresses), and on the C64 $4D00 upwards is the twelve character
# slots -- so nothing the DOS save holds above this can be sourced from a C64
# save, however tempting the address looks (#59).
ECL_SHARED_LAST = FLAGS_LAST


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
    return _whole(save)[DAX_NUMBER]


def area_id(save: bytes) -> int:
    return word(save, AREA)


def current_area(save: bytes) -> int:
    """The area the party is in, indoors or out.

    Indoors `$49C5` and `$49F2` agree (asserted across every indoor specimen).
    Outdoors `$49C5` is 0 -- the DOS overland names no GEO there -- and the
    area id (25-27) is carried by `$49F2` alone, so a reader keying on
    `area_id` would take a party on the travel grid for one in New Phlan
    (#59, the outdoor pass).
    """
    return word(save, SCRIPT) if outdoors(save) else word(save, AREA)


def clock(save: bytes) -> tuple[int, int, int, int]:
    """(hour, minute, day, month) -- the C64's digit encoding, as words."""
    d = [word(save, CLOCK + i) for i in range(6)]
    return d[3], d[2] * 10 + d[1], d[4], d[5]


def party_size(save: bytes) -> int:
    return _whole(save)[PARTY_SIZE_BYTE]


def position(save: bytes) -> tuple[int, int, int]:
    """(x, y, facing) with facing in the C64's units, 0 N 1 E 2 S 3 W.

    Indoors only for x and y: an outdoor save freezes 12801/12802 at the last
    indoor square (the pier, in all three specimens) while the facing byte
    stays live -- read `travel_square` when `outdoors(save)`.  The mirror of
    the C64, whose stale copy outdoors is `$49C0`-`$49C2` (#47, #59).
    """
    save = _whole(save)
    return save[POS_X], save[POS_Y], save[POS_FACING] // FACING_SCALE


def outdoors(save: bytes) -> bool:
    """Was this save made on the overland travel map?  `$49E6` = 0 there.

    CONFIRMED three specimens each way (#59): 1 in A/B/J indoors, 0 in the
    three overland saves, and the boat-back transition was caught writing it
    0 -> 1 live.
    """
    return word(save, INDOORS) == 0


#: What the status line adds to the window-local x to print a world
#: coordinate, per outdoor area.  Window 26 measured on-screen -- world
#: `20,29` against `$49C3`/`$49C4` = (7,29), three of three (#59); 25 and 27
#: are the C64 seam arithmetic (write-up lost, `work/reports/world-map.md` §3:
#: window 25's x+13 is window 26's x, and 26's x+13 is 27's), PROBABLE for the DOS
#: display.  y is world y in every window.
WINDOW_X_OFFSET = {25: 0, 26: 13, 27: 26}


def travel_square(save: bytes) -> tuple[int, int]:
    """The overland square, window-local, from `$49C3`/`$49C4`.

    CONFIRMED (#59): three engine-written overland saves read (7,29), (7,28),
    (8,28) against on-screen `20,29`/`20,28`/`21,28` -- world x = local x +
    `WINDOW_X_OFFSET[area]` -- and a live watch caught one east step writing
    `$49C3` 7 -> 8.  Meaningful only when `outdoors(save)`; indoor saves hold
    zeros (A/B/J) or the stale square the party left the grid on.
    """
    return word(save, TRAVEL_X), word(save, TRAVEL_Y)


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
# The `.DAX` container
# ---------------------------------------------------------------------------
#: A `.DAX` is a `u16le` index size, `size // 9` entries of
#: `id:u8, offset:u32le, raw:u16le, compressed:u16le`, then the block data with
#: each entry's offset relative to its start.  Blocks are byte run-length
#: coded: a lead byte under 128 copies the next `n + 1` bytes, one at or above
#: it repeats the next byte `256 - n` times.
#:
#: **One copy, here** (#76).  `tools/dosbox.py` carried a second and re-exports
#: this one; a retarget needs one ECL block out of the player's own archive and
#: `goldbox/` may not import from `tools/`, so the shared copy has to be this side
#: of the edge.
#:
#: This is *not* the Amiga container.  That one is big-endian, orders the entry
#: `id:u16 offset:u32 compressed:u16 raw:u16`, and is bit-packed rather than
#: run-length coded; `docs/117-save-conversion.md`'s "all 843 blocks of all 23
#: `.dax` files" is a statement about that format and `work/amiga/dax.py`, and
#: says nothing about this one (#65).
DAX_ENTRY = 9


def dax_index(data: bytes, name: str = "dax") -> list[tuple[int, int, int, int]]:
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
        raise DaxError(f"{name}: not a .DAX: {e}") from e


def dax_unpack(block: bytes, raw_size: int, name: str = "block") -> bytes:
    """Decompress one `.DAX` block, or raise `DaxError` saying which.

    All three refusals mean the same thing -- a length that is not this
    block's -- and all three used to be silent (#65).  A run whose operand is
    past the end of the block raised `IndexError` from the subscript, and a
    block that ran out before `raw_size` returned a plausible prefix and left
    the caller to notice.  `goldbox.dos.write_dos_save` catches `DosSaveError` and
    keeps the template's square; an `IndexError` took the whole conversion down
    with a traceback instead.
    """
    out = bytearray()
    i = 0
    while i < len(block) and len(out) < raw_size:
        n = block[i]
        if n < 128:
            run = block[i + 1:i + 2 + n]
            if len(run) != n + 1:
                raise DaxError(
                    f"{name}: copy of {n + 1} bytes at {i} runs "
                    f"{n + 1 - len(run)} past the end of a {len(block)}-byte "
                    f"block")
            out += run
            i += n + 2
        else:
            if i + 1 >= len(block):
                raise DaxError(
                    f"{name}: repeat opcode at {i} is the last byte of a "
                    f"{len(block)}-byte block, so its operand is missing")
            out += bytes([block[i + 1]]) * (256 - n)
            i += 2
    if len(out) != raw_size:
        raise DaxError(
            f"{name}: unpacked to {len(out)} bytes, not the {raw_size} the "
            f"index states")
    return bytes(out)


def _dax_chunk(data: bytes, base: int, off: int, comp: int, name: str) -> bytes:
    """The stored bytes of one block, or a refusal naming what is short."""
    chunk = data[base + off:base + off + comp]
    if len(chunk) != comp:
        raise DaxError(
            f"{name}: the index states {comp} bytes at {base + off} but the "
            f"file holds {len(chunk)}")
    return chunk


def dax_blocks(data: bytes, name: str = "dax"):
    """Yield `(id, decompressed bytes)` for every block of a `.DAX`."""
    index = dax_index(data, name)
    base = 2 + struct.unpack_from("<H", data, 0)[0]
    for bid, off, raw, comp in index:
        chunk = _dax_chunk(data, base, off, comp, f"{name} block {bid}")
        yield bid, dax_unpack(chunk, raw, f"{name} block {bid}")


def dax_block(data: bytes, block_id: int, name: str = "dax") -> bytes:
    """One block of a `.DAX`, decompressed.  Raises if it is not there."""
    index = dax_index(data, name)
    base = 2 + struct.unpack_from("<H", data, 0)[0]
    for bid, off, raw, comp in index:
        if bid != block_id:
            continue
        where = f"{name} block {block_id}"
        return dax_unpack(_dax_chunk(data, base, off, comp, where), raw, where)
    raise DaxError(f"{name}: no block {block_id} in this .DAX")


# ---------------------------------------------------------------------------
# Writing: the retarget, and the two fields a conversion carries
# ---------------------------------------------------------------------------
def put_word(save: bytearray, address: int, value: int) -> None:
    _whole(save)
    struct.pack_into("<H", save, word_offset(address), value & 0xFFFF)


def put_position(save: bytearray, x: int, y: int, facing: int) -> None:
    """The square, with `facing` in the C64's 0-3."""
    _whole(save)
    save[POS_X], save[POS_Y] = x, y
    save[POS_FACING] = facing * FACING_SCALE


def put_tail_state(save: bytearray, *, indoors: bool = True) -> None:
    """Bytes 12804-12807, from measurement rather than from the template.

    `indoors` sets **two** of them, not one: the view-mode byte, and the
    scratch byte at 12804, which reads 0 in every indoor specimen and 14 in
    every outdoor one.  Writing 0 outdoors would put a value measured indoors
    into a save that stands outdoors -- inheriting a different situation's
    state, which is the thing this function exists to stop.  The engine
    maintains 12804 itself, so it is probably harmless either way; "probably
    harmless" is not a reason to write the wrong one.

    `TAIL_CONSTANT_BYTE` is 2 in all twelve genuine specimens regardless.
    `VM_COPY_BYTE` is written from `$5200` as it stands in this save, which is
    the relationship 13 of 13 files show.
    """
    _whole(save)
    save[SCRATCH_BYTE] = SCRATCH_INDOORS if indoors else SCRATCH_OUTDOORS
    save[VM_COPY_BYTE] = word(bytes(save), VM_SCRATCH) & 0xFF
    save[VIEW_MODE_BYTE] = VIEW_MODE_INDOORS if indoors else VIEW_MODE_OUTDOORS
    save[TAIL_CONSTANT_BYTE] = TAIL_CONSTANT


def put_travel_square(save: bytearray, x: int, y: int) -> None:
    """The overland square, window-local, into `$49C3`/`$49C4`.

    The facing byte still matters out there: the engine keeps 12803 live
    (doubled, as indoors) while 12801/12802 go stale, so a writer placing a
    party outdoors sets this *and* `put_position`'s facing.
    """
    _whole(save)
    put_word(save, TRAVEL_X, x)
    put_word(save, TRAVEL_Y, y)


def put_clock(save: bytearray, digits) -> None:
    """The six digit words, in the C64's own order and encoding."""
    _whole(save)
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
