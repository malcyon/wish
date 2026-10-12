"""The Amiga Pool of Radiance combat-figure art, `/chead.dax` and `/cbody.dax`.

Both files are on disk 2, the `POOLDATA` volume, and are Amiga `.dax`
containers (`goldbox/amiga_dax.py`), not the `GLIB` `.TLB` libraries the two
later Amiga titles use.  Each unpacked block is one image:

* a 12-byte header of big-endian words -- rows at bytes 0-1, the drawn width
  in eights at 2-3, zero at 4-7, 1 at 8-9 in every block on the disk, and the
  length of one bitplane in bytes at 10-11;
* then four bitplanes stored one after another, each `rows * stride` bytes,
  where `stride` is the plane length over the rows -- 4 bytes in every block,
  so 32 pixels are stored a row and the first 24 are drawn.

Plane `p` holds bit `p` of a pixel's value and the leftmost pixel is a byte's
top bit: the remapper at `/program` file offset `0x048774` assembles a value
from planes 3, 2, 1, 0 into bits 3, 2, 1, 0 of `d1`, taking each word's top
bit first.  There is no mask plane; value 0 is the empty one.

The loader at `0x036192` and the preparer at `0x0262A0` fix which blocks a
character's figure is made of, and :func:`block_ids` is that rule.  The
preparer's recolour, read at `0x0263A6`-`0x0263FC`, is :func:`recolour_table`.
`docs/240-amiga-pool-combat-figure.md` is the write-up, and
`tools/icons/amigaporicons.py` re-takes every measurement against the
player's own disks.  Nothing here holds any of the game's art.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import amiga_dax

#: The two files, on the disk whose volume is `POOLDATA`.
HEAD_FILE, BODY_FILE = "chead.dax", "cbody.dax"

#: The block header: rows, width in eights, two unused words, a word that is
#: 1 in all 156 blocks on the disk, and the plane length in bytes.
HEADER = struct.Struct(">HHHHHH")
PLANES = 4

#: What the loader adds to an option number when the size letter is `T`
#: (`size` 2), and what it adds to a body option for the action pose.
LARGE, ACTION = 0x40, 0x80

#: The size letter the preparer appends to `CHEAD` and `CBODY`, by `size`;
#: `/program` file offset `0x02C713`.  Only `T` changes the block.
SIZE_LETTERS = {1: "S", 2: "T"}

#: The six pairs of pixel values the record's six `icon_colours` bytes
#: replace, in record order (body, arm, leg, hair, shield, weapon), at
#: `/program` file offset `0x06DD4F`.  A byte's high nibble replaces the
#: value in the pair's high nibble and its low nibble the value in its low
#: nibble, so a record holding these six bytes draws the art unchanged.
SOURCE_PAIRS = bytes.fromhex("192a3b7685ef")

#: How a DOS Pool of Radiance pixel value is stored in the Amiga art, where
#: the two drawings are the same picture.  Measured, not read from code: under
#: this table 50 of the 128 body blocks and 11 of the 28 head blocks are some
#: DOS block pixel for pixel.  It is not one-to-one -- the plume's DOS values
#: 5 and 13 land on the body pair 9 and 1 -- so it only runs from DOS to the
#: Amiga.
DOS_TO_AMIGA = (0, 1, 2, 3, 6, 9, 5, 14, 4, 9, 10, 11, 7, 1, 8, 15)


class PorArtError(ValueError):
    """This is not a combat-figure block this reader knows how to read."""


@dataclass(frozen=True)
class ArtBlock:
    """One decoded block: `rows[y][x]` is a four-bit pixel value, 0 empty."""

    height: int
    width: int
    rows: tuple[tuple[int, ...], ...]


def decode_block(raw: bytes, name: str = "block") -> ArtBlock:
    """One unpacked `chead.dax` or `cbody.dax` block, as rows of values.

    Raises :class:`PorArtError` when the header does not describe the bytes
    that follow it, rather than reading a picture at the wrong stride.
    """
    if len(raw) < HEADER.size:
        raise PorArtError(f"{name}: {len(raw)} bytes is shorter than the "
                          f"{HEADER.size}-byte header")
    height, eights, _, _, _, plane = HEADER.unpack_from(raw, 0)
    if not height or not eights or plane % height:
        raise PorArtError(f"{name}: a header of {height} rows, {eights} "
                          f"eights and {plane}-byte planes is not an image")
    stride = plane // height
    if stride * 8 < eights * 8:
        raise PorArtError(f"{name}: {stride} bytes a row cannot hold "
                          f"{eights * 8} pixels")
    if len(raw) != HEADER.size + PLANES * plane:
        raise PorArtError(f"{name}: four {plane}-byte planes and the header "
                          f"make {HEADER.size + PLANES * plane} bytes, not "
                          f"{len(raw)}")
    width = eights * 8
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            value = 0
            for p in range(PLANES):
                byte = raw[HEADER.size + p * plane + y * stride + x // 8]
                value |= ((byte >> (7 - x % 8)) & 1) << p
            row.append(value)
        rows.append(tuple(row))
    return ArtBlock(height, width, tuple(rows))


def read_art(data: bytes, name: str = "dax") -> dict[int, ArtBlock]:
    """Every block of `chead.dax` or `cbody.dax`, by block id."""
    return {bid: decode_block(raw, f"{name} block {bid}")
            for bid, raw in amiga_dax.blocks(data, name)}


def block_ids(kind: str, option: int, size: int) -> tuple[int, int]:
    """The `(ready, action)` block ids the loader asks for.

    `kind` is `"head"` or `"body"`, `option` the record's `icon_head` or
    `icon_body`, `size` the record's `size`.  The loader adds `LARGE` when the
    file name ends `T`; for a body it loads `id + ACTION` as the second pose,
    and for a head it loads the same block twice.
    """
    if kind not in ("head", "body"):
        raise ValueError(f"kind is 'head' or 'body', not {kind!r}")
    ready = option + (LARGE if SIZE_LETTERS.get(size) == "T" else 0)
    return ready, ready + ACTION if kind == "body" else ready


def recolour_table(colours: bytes) -> tuple[int, ...]:
    """The sixteen-entry pixel-value table the preparer builds from a record.

    It starts as the identity; then for each of the six pairs, the pair's low
    value becomes the colour byte's low nibble and its high value the byte's
    high nibble, in that order.  The remapper then replaces every pixel value
    `v` of both body poses, the head already ORed in, with `table[v]`.
    """
    if len(colours) != len(SOURCE_PAIRS):
        raise ValueError(f"icon_colours is {len(SOURCE_PAIRS)} bytes, "
                         f"not {len(colours)}")
    table = list(range(16))
    for source, chosen in zip(SOURCE_PAIRS, colours):
        table[source & 0xF] = chosen & 0xF
        table[source >> 4] = chosen >> 4
    return tuple(table)
