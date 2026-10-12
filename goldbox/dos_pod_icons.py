"""The DOS Pools of Darkness combat figure and the ICON screen it is shown on.

Pools of Darkness keeps the other DOS titles' block numbering and colour rule
(:mod:`goldbox.dos_icons`) but stores its art for the VGA mode the shipped
`POOL4.CFG` selects (its display line is `V`, which the expanded `GAME.EXE`
image turns into display mode 2 and BIOS mode 13h at `0x1A6D`).  The art is
`CHEAD.DAX`, `CBODY.DAX` and `COMSPR.DAX` in the game folder, read at run
time through :func:`read_game`; nothing of the game's is held here.

An image block, as the header reader `GAME.EXE` image `0x1CE9` takes it:

* byte 0 the rows, byte 1 the width in eights, words at 2 and 4 copied into
  the image record and not used for a figure, word 6 the frame count;
* byte 8 the first palette entry the block sets and byte 9 the count less
  one; then three six-bit DAC values an entry, then one EGA colour nibble an
  entry (two a byte, high first), then four bytes the reader skips -- so the
  figure blocks' header is 182 bytes and the ICON box's 126;
* then each frame's `rows * width` pixels, one byte a pixel, copied as they
  are in VGA mode (`0x2386`).

A figure pixel is still a part number, 0 to 15.  The loader (`GAME.OVR`
`0x11048`) loads a head and a body for each pose; in VGA mode its composite
(`0x10F6C`) writes every head byte that is not 8 over the body from row 0;
the recolour (`0x3051`, VGA branch `0x34B6`) replaces part values through
:func:`goldbox.dos_icons.recolour_table`; and the blitter (`0x4541`, loop
`0x4776`) skips every pixel equal to the image's key, which the block loader
(`0x3FEE9`) sets to 8 for these files.  So 8 is the see-through value, 0 is
drawn black, and a colour nibble of 8 makes its part see-through.
"""

from __future__ import annotations

import pathlib
import struct
from dataclasses import dataclass

from .dos_icons import EGA, DosArtError, recolour_table
from .dos_savegame import dax_blocks

#: The three files the ICON screen draws from, in the game folder.
HEAD_FILE, BODY_FILE, BOX_FILE = "CHEAD.DAX", "CBODY.DAX", "COMSPR.DAX"

#: Where the palette starts in a block header.
PALETTE_AT = 10

#: The value the blitter leaves see-through: the block loader passes 8 for
#: `CHEAD`, `CBODY` and `COMSPR` (`GAME.OVR:0x3FFA4`, `0x400AE`).
KEY = 8

#: What the block loader adds for `size` 2 (the name's `T`, `0x3FF67`), and
#: what it adds to a body block for the second pose (`0x40002`).  A head has
#: no second-pose block: `0x3FFCD` loads the same head for both poses.
LARGE, ACTION = 0x40, 0x80

#: The `COMSPR.DAX` block the ICON routine (`GAME.OVR:0x17E16`) loads into
#: figure slot 28 and draws, pose 0, behind both poses (`0x17B42`).
BOX_BLOCK = 15

#: The top-left pixel of each pose, as in :data:`goldbox.dos_icons.PLACES`:
#: the ICON routine draws the box and both poses at cells (1, 2) and (4, 2)
#: for `OLD` and (1, 4) and (4, 4) for `NEW` (`0x17EEF`, `0x17F58`), and the
#: game's own ICON screens show them at these pixels
#: (`tools/icons/dospodicons.py --run`).
PLACES = {("old", 0): (32, 56), ("old", 1): (104, 56),
          ("new", 0): (32, 104), ("new", 1): (104, 104)}
CELL = 24


@dataclass(frozen=True)
class PodBlock:
    """One decoded block: `rows[y][x]` is the stored byte of frame 0.

    `first` and `colours` are the palette entries the header sets, each a
    six-bit `(r, g, b)` DAC triple; `ega` is each entry's EGA colour.
    """

    height: int
    width: int
    rows: tuple[tuple[int, ...], ...]
    first: int
    colours: tuple[tuple[int, int, int], ...]
    ega: tuple[int, ...]
    frames: int = 1


#: One pose: `rows[y][x]` is a palette index, or None where the figure is
#: see-through and whatever is behind it shows.
Pose = tuple[tuple[int | None, ...], ...]


def header_length(count: int, first: int) -> int:
    """The header's length for a palette of `count` entries from `first`.

    The reader skips four bytes after the EGA nibbles, or 32 for the one
    palette of 112 entries from entry 32 (`GAME.EXE` image `0x1E51`).
    """
    skip = 0x20 if (first, count) == (0x20, 0x70) else 4
    return PALETTE_AT + 3 * count + count // 2 + skip


def decode_block(raw: bytes, name: str = "block") -> PodBlock:
    """One unpacked image block, as rows of stored bytes.

    Raises :class:`DosArtError` when the header does not describe the bytes
    that follow it, rather than reading a picture at the wrong stride.
    """
    if len(raw) < PALETTE_AT:
        raise DosArtError(f"{name}: {len(raw)} bytes is shorter than the "
                          f"{PALETTE_AT}-byte fixed header")
    height, eights = raw[0], raw[1]
    frames = struct.unpack_from("<H", raw, 6)[0]
    first, count = raw[8], raw[9] + 1
    if not height or not eights or not frames:
        raise DosArtError(f"{name}: a header of {height} rows, {eights} "
                          f"eights and {frames} frames is not an image")
    if count < 2 or count % 2:
        raise DosArtError(f"{name}: a palette of {count} entries is not one "
                          f"this reader knows")
    start = header_length(count, first)
    width = eights * 8
    want = start + frames * height * width
    if len(raw) != want:
        raise DosArtError(f"{name}: {frames} frame(s) of {height} rows of "
                          f"{width} pixels and a {start}-byte header make "
                          f"{want} bytes, not {len(raw)}")
    colours = tuple(tuple(raw[PALETTE_AT + 3 * i:PALETTE_AT + 3 * i + 3])
                    for i in range(count))
    nibbles = raw[PALETTE_AT + 3 * count:PALETTE_AT + 3 * count + count // 2]
    ega = tuple(v for byte in nibbles for v in (byte >> 4, byte & 0x0F))
    rows = tuple(tuple(raw[start + y * width:start + (y + 1) * width])
                 for y in range(height))
    return PodBlock(height, width, rows, first, colours, ega, frames)


def read_art(data: bytes, name: str = "dax") -> dict[int, PodBlock]:
    """Every block of `CHEAD.DAX`, `CBODY.DAX` or `COMSPR.DAX`, by block id."""
    return {bid: decode_block(raw, f"{name} block {bid}")
            for bid, raw in dax_blocks(data, name)}


@dataclass(frozen=True)
class PodGameArt:
    """The figure art and the ICON screen's box, from one game folder."""

    heads: dict[int, PodBlock]
    bodies: dict[int, PodBlock]
    box: PodBlock


def _file(folder: pathlib.Path, name: str) -> pathlib.Path:
    """`name` in `folder`, whatever its case on this file system."""
    exact = folder / name
    if exact.is_file():
        return exact
    for path in folder.iterdir():
        if path.name.upper() == name and path.is_file():
            return path
    raise DosArtError(f"{folder} holds no {name}")


def read_game(folder: str | pathlib.Path) -> PodGameArt:
    """The heads, bodies and ICON-screen box from a Pools of Darkness folder."""
    folder = pathlib.Path(folder)
    if not folder.is_dir():
        raise DosArtError(f"{folder} is not a folder")
    heads = read_art(_file(folder, HEAD_FILE).read_bytes(), HEAD_FILE)
    bodies = read_art(_file(folder, BODY_FILE).read_bytes(), BODY_FILE)
    boxes = read_art(_file(folder, BOX_FILE).read_bytes(), BOX_FILE)
    if BOX_BLOCK not in boxes:
        raise DosArtError(f"{BOX_FILE} holds no block {BOX_BLOCK}")
    return PodGameArt(heads, bodies, boxes[BOX_BLOCK])


def block_ids(icon_head: int, icon_body: int, size: int
              ) -> tuple[tuple[int, int], tuple[int, int]]:
    """`((head, body) ready, (head, body) action)`: the blocks the loader asks for."""
    large = LARGE if size == 2 else 0
    head, body = icon_head + large, icon_body + large
    return (head, body), (head, body + ACTION)


def compose(heads: dict[int, PodBlock], bodies: dict[int, PodBlock],
            icon_head: int, icon_body: int, size: int,
            colours: bytes) -> tuple[Pose, Pose]:
    """The `(ready, action)` poses the ICON screen draws for a record.

    Each pose is the body block :func:`block_ids` names with every head
    byte that is not :data:`KEY` written over it from row 0, then every
    value replaced through the record's recolour table; a pixel is None
    where the result is :data:`KEY`.
    """
    table = recolour_table(colours)
    poses = []
    for head_id, body_id in block_ids(icon_head, icon_body, size):
        if head_id not in heads:
            raise DosArtError(f"{HEAD_FILE} holds no block {head_id}")
        if body_id not in bodies:
            raise DosArtError(f"{BODY_FILE} holds no block {body_id}")
        head, body = heads[head_id], bodies[body_id]
        if head.width != body.width or head.height > body.height:
            raise DosArtError(f"head block {head_id} ({head.width}x"
                              f"{head.height}) does not fit body block "
                              f"{body_id} ({body.width}x{body.height})")
        rows = []
        for y, row in enumerate(body.rows):
            over = head.rows[y] if y < head.height else (KEY,) * body.width
            line = []
            for b, h in zip(row, over):
                value = h if h != KEY else b
                if value < len(table):
                    value = table[value]
                line.append(None if value == KEY else value)
            rows.append(tuple(line))
        poses.append(tuple(rows))
    return poses[0], poses[1]


def on_box(box: PodBlock, pose: Pose) -> tuple[tuple[int, ...], ...]:
    """`pose` drawn over the ICON screen's box, as palette indices.

    Raises :class:`DosArtError` for a box with see-through pixels: the fill
    the screen draws first (`GAME.EXE` image `0x3727`) has not been read.
    """
    if (box.height, box.width) != (len(pose), len(pose[0])):
        raise DosArtError(f"the box is {box.width}x{box.height} and the "
                          f"pose {len(pose[0])}x{len(pose)}")
    if any(v == KEY for row in box.rows for v in row):
        raise DosArtError("the box has see-through pixels, and what the "
                          "ICON screen fills behind it is not read")
    return tuple(tuple(b if p is None else p for p, b in zip(prow, brow))
                 for prow, brow in zip(pose, box.rows))


def dac_rgb(value: int) -> int:
    """A six-bit DAC value as an eight-bit channel."""
    return (value << 2) | (value >> 4)


def icon_palette(art: PodGameArt) -> dict[int, tuple[int, int, int]]:
    """The `(r, g, b)` colour of every palette entry the ICON screen sets.

    Entries 0-15 are the sixteen EGA colours, which `GAME.EXE`'s table at
    `ds:0x9D6` writes (`GAME.OVR:0x1A106`), every block that sets them
    repeats, and the game's ICON screens show; the ICON routine then sets
    the box block's own entries (`GAME.OVR:0x17E45`).
    """
    palette = dict(enumerate(EGA))
    for i, (r, g, b) in enumerate(art.box.colours):
        palette[art.box.first + i] = (dac_rgb(r), dac_rgb(g), dac_rgb(b))
    return palette
