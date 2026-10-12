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
:func:`compose` builds the two poses from those rules, :func:`on_frame`
lays a pose over the ICON screen's box (`/comspr.dax` block 12), and
:func:`icon_palette` finds the sixteen colours the ICON screen installs in
the player's own `/program`.
`docs/240-amiga-pool-combat-figure.md` is the write-up, and
`tools/icons/amigaporicons.py` re-takes every measurement against the
player's own disks.  Nothing here holds any of the game's art or colours.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import amiga_dax, amiga_hunks

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

#: The box the ICON screen draws behind each pose: block 12 of `/comspr.dax`
#: on disk 2, which `/program` loads into figure slot 25 at `0x03CF20`.  The
#: placement helper at `0x0199E8` draws slot 25 at each pose's place and the
#: figure over it.
FRAME_FILE, FRAME_BLOCK = "comspr.dax", 12

#: The ICON menu's bar.  :func:`icon_palette` finds the menu routine by the
#: one instruction that loads this string's address.
ICON_MENU_BAR = b"Parts color-1 color-2 Size Exit"

#: `lea.l -32(a5), a1; moveq #7, d0; move.l (a0)+, (a1)+; dbra d0` -- the
#: copy every palette setter makes of its sixteen words, straight after the
#: `lea.l table, a0` that names the table.
_SETTER_COPY = bytes.fromhex("43EDFFE0" "7007" "22D8" "51C8FFFC")
_LEA_ABS_A0, _JSR_PC, _JMP_ABS = 0x41F9, 0x4EBA, 0x4EF9

#: How far past the bar's `lea` the menu calls its palette setter (`0x34` in
#: the one build read), and how far into a setter its `lea` sits (`0x0E`).
_MENU_REACH, _SETTER_REACH = 0x80, 0x20

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


#: One pose: `rows[y][x]` is a pixel value, or None where the figure is empty
#: and whatever is behind it shows through.
Pose = tuple[tuple[int | None, ...], ...]


def compose(heads: dict[int, ArtBlock], bodies: dict[int, ArtBlock],
            icon_head: int, icon_body: int, size: int,
            colours: bytes) -> tuple[Pose, Pose]:
    """The `(ready, action)` poses the preparer at `0x0262A0` builds.

    `heads` and `bodies` are :func:`read_art` of `chead.dax` and `cbody.dax`.
    Each pose is the body block :func:`block_ids` names with the head block
    ORed in from row 0 (`0x0261E0`), then every value replaced through
    :func:`recolour_table` (`0x048774`).  A pixel is empty where the head and
    body are both 0 *before* the recolour, so a colour nibble of 0 draws
    colour 0 rather than letting the box show through.
    """
    head_id = block_ids("head", icon_head, size)[0]
    ready_id, action_id = block_ids("body", icon_body, size)
    if head_id not in heads:
        raise PorArtError(f"{HEAD_FILE} holds no block {head_id}")
    head = heads[head_id]
    table = recolour_table(colours)
    poses = []
    for body_id in (ready_id, action_id):
        if body_id not in bodies:
            raise PorArtError(f"{BODY_FILE} holds no block {body_id}")
        body = bodies[body_id]
        if head.width != body.width or head.height > body.height:
            raise PorArtError(f"head block {head_id} ({head.width}x"
                              f"{head.height}) does not fit body block "
                              f"{body_id} ({body.width}x{body.height})")
        rows = []
        for y, row in enumerate(body.rows):
            over = head.rows[y] if y < head.height else (0,) * body.width
            rows.append(tuple(table[b | h] if b | h else None
                              for b, h in zip(row, over)))
        poses.append(tuple(rows))
    return poses[0], poses[1]


def on_frame(frame: ArtBlock, pose: Pose) -> tuple[tuple[int, ...], ...]:
    """`pose` drawn over the ICON screen's box, as rows of pixel values."""
    if (frame.height, frame.width) != (len(pose), len(pose[0])):
        raise PorArtError(f"the box is {frame.width}x{frame.height} and the "
                          f"pose {len(pose[0])}x{len(pose)}")
    return tuple(tuple(b if p is None else p for p, b in zip(prow, brow))
                 for prow, brow in zip(pose, frame.rows))


def icon_palette(program: bytes) -> tuple[tuple[int, int, int], ...]:
    """The sixteen `(r, g, b)` colours the ICON screen draws with.

    Each of the table's words is `0RGB`, a nibble a component, and a nibble
    `n` is the 8-bit `17 * n`.  :func:`icon_palette_chain` finds the table.
    """
    table = icon_palette_chain(program)[3]
    words = [int.from_bytes(program[table + 2 * i:table + 2 * i + 2], "big")
             for i in range(16)]
    return tuple(((w >> 8 & 0xF) * 17, (w >> 4 & 0xF) * 17, (w & 0xF) * 17)
                 for w in words)


def icon_palette_chain(program: bytes) -> tuple[int, int, int, int]:
    """`(bar lea, call, setter, table)` file offsets of the ICON palette.

    Found in `/program` by what the code does rather than at a fixed offset:
    the menu routine is the one whose `lea.l abs.l, a0` loads
    :data:`ICON_MENU_BAR`; within `_MENU_REACH` bytes it calls, through a
    `jmp abs.l` stub, a setter that copies sixteen words from a `lea.l
    abs.l, a0` table and installs them as the screen's colours.  In the one
    build read the menu is at `0x019C52`, the call at `0x019C96`,
    the setter at `0x03499E` and the table at `0x03B260`.

    Raises :class:`PorArtError` when no such chain is found.
    """
    try:
        hunks, relocs = amiga_hunks.parse(program)
    except (ValueError, IndexError, struct.error) as exc:
        raise PorArtError(f"/program is not a Hunk executable, or is cut "
                          f"short: {exc}") from exc
    fields = {}
    for (number, offset), to in relocs.items():
        if number < len(hunks) and hunks[number].file_offset is not None:
            fields[hunks[number].file_offset + offset] = to

    def word(at: int) -> int:
        return int.from_bytes(program[at:at + 2], "big")

    def resolve(field: int) -> int | None:
        to = fields.get(field)
        if to is None or to >= len(hunks) or hunks[to].file_offset is None:
            return None
        return hunks[to].file_offset + int.from_bytes(
            program[field:field + 4], "big")

    def setter_table(at: int) -> int | None:
        for lea in range(at, at + _SETTER_REACH, 2):
            if (word(lea) == _LEA_ABS_A0 and program[
                    lea + 6:lea + 6 + len(_SETTER_COPY)] == _SETTER_COPY):
                return resolve(lea + 2)
        return None

    bars = []
    start = program.find(ICON_MENU_BAR)
    while start >= 0:
        bars.append(start)
        start = program.find(ICON_MENU_BAR, start + 1)
    for field, _to in sorted(fields.items()):
        if word(field - 2) != _LEA_ABS_A0 or resolve(field) not in bars:
            continue
        for call in range(field + 4, field + 4 + _MENU_REACH, 2):
            if word(call) != _JSR_PC:
                continue
            stub = call + 2 + int.from_bytes(program[call + 2:call + 4], "big",
                                             signed=True)
            if word(stub) != _JMP_ABS or (setter := resolve(stub + 2)) is None:
                continue
            table = setter_table(setter)
            if table is None or table + 32 > len(program):
                continue
            return field - 2, call, setter, table
    raise PorArtError("no ICON menu in this /program installs a palette the "
                      "way the one build read does")


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
