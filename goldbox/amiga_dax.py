"""The Amiga Gold Box `.dax` container, and the depacker its blocks are in.

`goldbox/dos_savegame.py` reads the **DOS** `.DAX`, which is a different
format with the same extension: a little-endian index of
`id:u8 offset:u32 raw:u16 compressed:u16` and run-length coded blocks.  This
one is the Amiga's -- a big-endian index of
`id:u16 offset:u32 compressed:u16 raw:u16` and ByteKiller-packed blocks -- and
the two must never be read through each other's reader (#65).

**Why a conversion needs it.** An Amiga Pool of Radiance saved game carries
7680 bytes of the area's own ECL script, live on load exactly as the DOS one
is, and a character record holds none of it.  DOS keeps a script per container
in `ECL<n>.DAX`; the Amiga keeps all of them in one `/ecl.dax` on disk 2, the
`POOLDATA` volume.  So a party cannot be converted to the Amiga without the
player's disk 2, and this is what reads it.

**The depacker is transcribed from the game's own code**, at `/program`
hunk 27 + `$7346` (file offset `0x4887A`), read with `tools/amiga68k.py`.  It
is the ByteKiller shape: a bit stream consumed **backwards** from the end of
the block, writing the output backwards from its end, with a trailer of three
big-endian longwords -- the unpacked length, a checksum, and the first bit
buffer.  The checksum is a running XOR of every longword the stream reads and
the routine ends with `tst.l d5` on it, so a block that unpacks to the stated
length with a non-zero checksum is a block that was read wrong.

CONFIRMED, and the oracle is the game's own saved game: block 0 of `ecl.dax`
unpacked, **from byte 2 on**, is byte for byte the 7468 bytes the shipped
`save/savgamA.dat` carries in its script buffer.  All 29 blocks unpack to
exactly the length the index states with a zero checksum, and every one opens
`88 13` -- `u16le` 5000, the ECL load address DOS and the C64 use too.
"""

from __future__ import annotations

import struct
from typing import Iterator

#: The `.dax` index entry: block id, offset from the end of the index, the
#: stored size, the unpacked size.  Ten bytes, big-endian.
ENTRY = struct.Struct(">HIHH")

#: How many bytes of trailer every packed block ends with: unpacked length,
#: checksum and the first bit buffer, one big-endian longword each.
TRAILER = 12


class AmigaDaxError(ValueError):
    """This is not the Amiga `.dax` this reader knows how to read."""


def index(data: bytes, name: str = "dax") -> list[tuple[int, int, int, int]]:
    """`(id, offset, stored size, unpacked size)` for every block.

    A file too short for the index it declares is named as such rather than
    raising `struct.error` out of a comprehension, because the caller is a
    conversion reading the player's own disk and "this is not an Amiga .dax"
    is an answer it has to be able to give.
    """
    try:
        size = struct.unpack_from(">H", data, 0)[0]
        return [ENTRY.unpack_from(data, 2 + ENTRY.size * i)
                for i in range(size // ENTRY.size)]
    except struct.error as e:
        raise AmigaDaxError(f"{name}: not an Amiga .dax: {e}") from e


def _base(data: bytes, name: str) -> int:
    try:
        return 2 + struct.unpack_from(">H", data, 0)[0]
    except struct.error as e:
        raise AmigaDaxError(f"{name}: not an Amiga .dax: {e}") from e


def unpack(block: bytes, raw_size: int | None = None,
           name: str = "block") -> bytes:
    """Decompress one packed block, or raise saying what did not add up.

    `raw_size` is the index's own figure and is checked against the block's
    own trailer when it is given; the two disagreeing means the index was read
    at the wrong stride, which is the failure this argument exists to catch.

    The listing this follows, instruction for instruction:

    * the trailer, backwards -- unpacked length, checksum, first bit buffer;
    * `lsr.l #1,d0` for each bit, and when the buffer empties, a fresh
      longword with a sentinel `1` rotated into bit 31 so that each longword
      yields exactly 32 bits;
    * tag `0` then `0`: a 3-bit count, then that many plus one literal bytes;
    * tag `0` then `1`: an 8-bit offset, two bytes copied;
    * tag `1` then `00` or `01`: a 9- or 10-bit offset, three or four bytes;
    * tag `1` then `10`: an 8-bit count and a 12-bit offset;
    * tag `1` then `11`: an 8-bit count, then count + 9 literal bytes.
    """
    if len(block) < TRAILER:
        raise AmigaDaxError(
            f"{name}: {len(block)} bytes is shorter than the {TRAILER}-byte "
            f"trailer every packed block ends with")
    read_at = len(block)

    def longword() -> int:
        nonlocal read_at
        read_at -= 4
        if read_at < 0:
            raise AmigaDaxError(
                f"{name}: the bit stream ran off the front of a "
                f"{len(block)}-byte block before the output was full")
        return struct.unpack_from(">I", block, read_at)[0]

    length = longword()
    checksum = longword()
    buffer = longword()
    checksum ^= buffer
    if raw_size is not None and length != raw_size:
        raise AmigaDaxError(
            f"{name}: the index states {raw_size} bytes and the block's own "
            f"trailer states {length}")

    out = bytearray(length)
    at = length

    def bit() -> int:
        nonlocal buffer, checksum
        value = buffer & 1
        buffer >>= 1
        if buffer == 0:
            buffer = longword()
            checksum ^= buffer
            value = buffer & 1
            buffer = (buffer >> 1) | 0x80000000
        return value

    def bits(count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | bit()
        return value

    def literals(count: int) -> None:
        nonlocal at
        for _ in range(count):
            at -= 1
            out[at] = bits(8)

    def copy(count: int, offset: int) -> None:
        nonlocal at
        for _ in range(count):
            at -= 1
            out[at] = out[at + offset]

    while at > 0:
        try:
            if bit():
                tag = bits(2)
                if tag < 2:
                    copy(tag + 3, bits(9 + tag))
                elif tag == 2:
                    count = bits(8) + 1
                    copy(count, bits(12))
                else:
                    literals(bits(8) + 9)
            elif bit():
                copy(2, bits(8))
            else:
                literals(bits(3) + 1)
        except IndexError as e:
            raise AmigaDaxError(
                f"{name}: a back-reference at {at} reaches past the end of "
                f"the {length}-byte output") from e
    if at != 0:
        raise AmigaDaxError(f"{name}: unpacked to {length - at} bytes, "
                            f"not the {length} the trailer states")
    if checksum:
        raise AmigaDaxError(
            f"{name}: unpacked to its stated {length} bytes but the stream's "
            f"checksum came out {checksum:#010x} rather than zero, so the "
            f"bits were not read the way the game reads them")
    return bytes(out)


def blocks(data: bytes, name: str = "dax") -> Iterator[tuple[int, bytes]]:
    """`(id, unpacked bytes)` for every block of an Amiga `.dax`."""
    base = _base(data, name)
    for bid, off, comp, raw in index(data, name):
        yield bid, unpack(_chunk(data, base, off, comp, bid, name), raw,
                          f"{name} block {bid}")


def _chunk(data: bytes, base: int, off: int, comp: int, bid: int,
           name: str) -> bytes:
    chunk = data[base + off:base + off + comp]
    if len(chunk) != comp:
        raise AmigaDaxError(
            f"{name} block {bid}: the index states {comp} bytes at "
            f"{base + off} but the file holds {len(chunk)}")
    return chunk


def block(data: bytes, block_id: int, name: str = "dax") -> bytes:
    """One block of an Amiga `.dax`, unpacked.  Raises if it is not there."""
    base = _base(data, name)
    for bid, off, comp, raw in index(data, name):
        if bid == block_id:
            return unpack(_chunk(data, base, off, comp, bid, name), raw,
                          f"{name} block {block_id}")
    raise AmigaDaxError(f"{name}: no block {block_id} in this .dax")


def block_ids(data: bytes, name: str = "dax") -> list[int]:
    """Which blocks a container holds, in the order the index lists them."""
    return [bid for bid, _off, _comp, _raw in index(data, name)]
