"""The Amiga Curse of the Azure Bonds and Secret of the Silver Blades combat
figure, as each title's ICON screen draws it.

Everything is read from the player's own disks at run time; nothing of the
games' art, colours or tables is held here.  The files:

* `CHEAD.TLB` and `CBODY.TLB` on disk 2 (`DISKB` for Curse, `DISK2` for
  Silver Blades): the heads and bodies, `GLIB` tile libraries whose block 0
  is an `(art id, block)` index;
* `COMSPR.TLB` on disk 1: art ids 25 and 153 are the box drawn behind the
  ready and the action pose;
* `ALWAYS.TLB` on disk 1: the palette the ICON screen shows (block 87 in
  Curse, block 0 in Silver Blades, whose copy is packed with
  :func:`unpack_method_5`);
* the executable on disk 1 (`/Curse`, `/Secret`): the sixteen-entry table
  from a DOS pixel value to an Amiga palette entry and the six part values
  the record's colour bytes recolour, found by :func:`recolour_tables`.

A tile (:func:`decode_tile`) is an 8-byte header -- rows, two zero offsets,
the width in eights, a type -- then its bitplanes one after another.  Type 1
puts a mask plane first, whose set bit is see-through on the disk: the tile
loader inverts it (`/Curse` `0x3B6F8`, `/Secret` `0x3F8F8`) and the blitter
draws through it with minterm `$CA` (`/Curse` `0x3F9D8`, `/Secret`
`0x4440C`), so an opaque pixel replaces what is under it.  Type 0 has no mask
and is opaque.  The next four planes are the palette entry, bit 0 first.

:func:`compose` is the figure: the loader (`/Curse` `0x24E42`, `/Secret`
`0x266BA`) reads body and head blocks for both poses, then recolours all
four through one table (`0x3C126`, which skips the mask plane); the draw
helper (`/Curse` `0x34F44`, `/Secret` `0x3868A`) blits the body and then the
head at the same place.  Unlike DOS, which ORs the head into the body, the
head here covers the body wherever the head is opaque.
`docs/199-amiga-combat-icons.md`, "The ICON screen", is the write-up.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import amiga_hunks

#: The container magic and the four-byte tag of a tile library.
GLIB_MAGIC, TILE_TAG = b"GLIB", b"TILE"

#: The four files the figure is drawn from, by where they are.
HEAD_FILE, BODY_FILE = "CHEAD.TLB", "CBODY.TLB"
FRAME_FILE, PALETTE_FILE = "COMSPR.TLB", "ALWAYS.TLB"

#: What the block loader adds to an option for `size` 2 (the file name ends
#: `T`) and for the second pose, to heads and bodies alike (`/Curse`
#: `0x34EA8`, `0x34F1E`).
LARGE, ACTION = 0x40, 0x80

#: The `COMSPR.TLB` art id the game loads into figure slot 25, with
#: `FRAME_ID + ACTION` as its second pose (`/Curse` `0x1D86C`).  The ICON
#: screen draws slot 25's ready pose behind the ready figure and its second
#: pose behind the action figure (`/Curse` `0x157AA`, `/Secret` `0xB832`).
FRAME_ID = 25

#: Bytes of one tile header: rows, x and y offsets, width in eights, type.
TILE_HEADER = struct.Struct(">HHHBB")

#: A palette block is type 8: sixteen `(red, green, blue)` bytes after the
#: header.  The setter (`/Curse` `0x3F2FE`) makes each channel the nibble
#: `(byte + 8) // 17`, and the screen shows nibble `n` as `17 * n`.
PALETTE_TYPE, PALETTE_COLOURS = 8, 16

#: The recolour builder's first instructions, the same in both executables:
#: `andi.w #$f, d1; lea g<entry>(a4), a0; moveq #0, d0; move.b d2, d0;
#: lea g<parts>(a4), a1` (`/Curse` `0x24F0C`, `/Secret` `0x26784`).  The two
#: `lea` displacements name the entry table and the part table.
_BUILDER = (bytes.fromhex("0241000f41ec"), bytes.fromhex("70001002" "43ec"))

#: SAS/C small data: `a4` is the data hunk's start plus this.
_SMALL_DATA_BIAS = 0x7FFE


@dataclass(frozen=True)
class LaterTitle:
    """What differs between the two titles' ICON screens.

    `palette_block`: the `ALWAYS.TLB` block the ICON screen shows.  Curse's
    ICON routine (`0x15F04`) installs block 87 through `0x3549E` and the
    Alter menu reinstalls block 0 when it returns (`0x13F8`); Silver Blades'
    (`0xC62C`) installs none, so the screen keeps block 0, which `0x1D756`
    installs at start-up and the fades at `0x1CA5A` and `0x1CA94` reinstall.
    `places`: the top-left pixel, on the 320x200 screen, of each drawn
    pose, `(row, pose)`; Curse draws the figure as it was (`current`) and
    as it is being edited (`trial`), Silver Blades one row.
    """

    executable: str
    palette_block: int
    places: dict[tuple[str, int], tuple[int, int]]
    #: The drawers `COMSPR.TLB` and `ALWAYS.TLB` (disk 1, beside the
    #: executable) and `CHEAD.TLB` and `CBODY.TLB` (disk 2) are in.
    drawers: tuple[str, str]


#: The ICON screen places a pose at pixel `2 * (word - 0x1F40)` on each
#: axis (`/Curse` `0x3E548`), and the draw helper's word is
#: `0x1F44 + 12 * cell` (`0x34F44`): `8 + 24 * cell` pixels, with cells
#: (1, 2) and (4, 2) for the first row and (1, 4) and (4, 4) for Curse's
#: second.
TITLES = {
    "curse-of-the-azure-bonds": LaterTitle(
        "Curse", 87,
        {("current", 0): (32, 56), ("current", 1): (104, 56),
         ("trial", 0): (32, 104), ("trial", 1): (104, 104)},
        ("DISKA", "DISKB")),
    "secret-of-the-silver-blades": LaterTitle(
        "Secret", 0,
        {("current", 0): (32, 56), ("current", 1): (104, 56)},
        ("DISK1", "DISK2")),
}

#: The key :func:`disk_files` gives the executable under.
EXECUTABLE = "executable"

#: The size of one pose and of the box, in pixels.
CELL = 24


class LaterArtError(ValueError):
    """A file or executable this reader cannot draw a figure from."""


class LaterArtMissing(LaterArtError):
    """A file the figure needs is not on the disks given."""


@dataclass(frozen=True)
class Tile:
    """One decoded tile: `rows[y][x]` is a palette entry, `opaque[y][x]`
    whether the blitter draws it."""

    height: int
    width: int
    rows: tuple[tuple[int, ...], ...]
    opaque: tuple[tuple[bool, ...], ...]


# ---------------------------------------------------------------------------
# The GLIB container
# ---------------------------------------------------------------------------
def unpack_method_5(data: bytes, start: int = 0,
                    limit: int | None = None) -> bytes:
    """Every method-5 chunk from `data[start]` to the end, unpacked.

    The library loader (`/Secret` `0x417D6`) unpacks a packed library a
    chunk at a time into one buffer, so a copy may reach back into an
    earlier chunk's output.  With `limit`, the unpacking stops with
    :class:`LaterArtError` before the output would pass that many bytes.
    """
    out = bytearray()
    pos = start
    while pos < len(data):
        pos = unpack_chunk(data, pos, out, limit)
    return bytes(out)


def unpack_chunk(data: bytes, start: int, out: bytearray,
                 limit: int | None = None) -> int:
    """Unpack one method-5 chunk from `data[start]` onto `out`; return where
    it ends.  `limit` is :func:`unpack_method_5`'s.

    The decoder at `/Secret` `0x45524`, an LZ77 variant.  A control byte
    `0xxxxxxx` is followed by one byte `b`: `(b >> 3) & 3` literals, then a
    copy of `(b & 7) + 3` bytes from `offset + 1` back, the offset being the
    control's seven bits under bits 5-7 of `b`.  `10xxxxxx` is followed by
    two bytes `b`, `c`: `c & 3` literals, then `(b & 0x1F) + 3` bytes from
    a fifteen-bit offset (control bits 0-5, `b` bits 5-7, `c` bits 2-7).
    `110xxxxx` copies literals: `n` (the low nibble) when bit 4 is set,
    else `(n + 1) * 4`.  `111xxxxx` ends the stream.
    """
    def grow(by: int) -> None:
        if limit is not None and len(out) + by > limit:
            raise LaterArtError(f"a method-5 stream from byte {start} "
                                f"unpacks to more than {limit} bytes")

    pos = start
    try:
        while True:
            control = data[pos]
            pos += 1
            if not control & 0x80:
                second = data[pos]
                pos += 1
                literals = (second >> 3) & 3
                grow(literals)
                out += data[pos:pos + literals]
                pos += literals
                offset = (second << 2) & 0x380 | control
                length = (second & 7) + 3
            elif not control & 0x40:
                second, third = data[pos], data[pos + 1]
                pos += 2
                literals = third & 3
                grow(literals)
                out += data[pos:pos + literals]
                pos += literals
                offset = ((second & 0xE0) << 1 | control & 0x3F
                          | (third << 7) & 0x7E00)
                length = (second & 0x1F) + 3
            elif not control & 0x20:
                count = control & 0x0F
                if not control & 0x10:
                    count = (count + 1) * 4
                if pos + count > len(data):
                    raise IndexError("a literal run passes the end")
                grow(count)
                out += data[pos:pos + count]
                pos += count
                continue
            else:
                return pos
            if pos > len(data):
                raise IndexError("literals pass the end")
            source = len(out) - offset - 1
            if source < 0:
                raise LaterArtError(f"a copy at input byte {pos} reaches "
                                    f"{-source} bytes before the output")
            grow(length)
            for i in range(length):
                out.append(out[source + i])
    except IndexError as exc:
        raise LaterArtError(f"a method-5 stream from byte {start} is cut "
                            f"short at byte {pos}") from exc


def library(data: bytes, name: str = "library") -> dict[int, bytes]:
    """Every block of a `GLIB` tile library, by art id.

    The header is the magic, a `u32` size, a `u16` block count, a byte
    naming how the rest is packed (0 stored, 5 :func:`unpack_method_5`), a
    byte that is 1 when block 0 indexes the others by art id and 0 when the
    block number is the id, and the tag `TILE`.  A packed library is one
    stream after a `u16`, and must unpack to the size the header gives.
    """
    if len(data) < 16 or data[:4] != GLIB_MAGIC or data[12:16] != TILE_TAG:
        raise LaterArtError(f"{name} is not a GLIB tile library")
    size, count = struct.unpack_from(">IH", data, 4)
    method, indexed = data[10], data[11]
    if method == 5:
        data = data[:16] + unpack_method_5(data, 18, size - 16)
        if len(data) != size:
            raise LaterArtError(f"{name} unpacks to {len(data)} bytes, not "
                                f"the {size} its header gives")
    elif method:
        raise LaterArtError(f"{name} is packed by method {method}, which "
                            f"this reader does not know")
    try:
        offsets = struct.unpack_from(f">{count + 1}I", data, 16)
    except struct.error as exc:
        raise LaterArtError(f"{name}'s block table is cut short") from exc
    if list(offsets) != sorted(offsets) or offsets[-1] > len(data):
        raise LaterArtError(f"{name}'s block offsets are out of order or "
                            f"pass the end")
    blocks = [data[offsets[i]:offsets[i + 1]] for i in range(count)]
    if not indexed:
        return dict(enumerate(blocks))
    if not blocks or len(blocks[0]) < 2:
        raise LaterArtError(f"{name} has no index block")
    entries = struct.unpack_from(">H", blocks[0], 0)[0]
    if len(blocks[0]) < 2 + 4 * entries:
        raise LaterArtError(f"{name}'s index lists {entries} tiles in "
                            f"{len(blocks[0])} bytes")
    out = {}
    for art, block in struct.iter_unpack(">HH",
                                         blocks[0][2:2 + 4 * entries]):
        if not 1 <= block < len(blocks):
            raise LaterArtError(f"{name}'s index names block {block} of "
                                f"{len(blocks)}")
        out[art] = blocks[block]
    return out


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------
def decode_tile(raw: bytes, name: str = "tile") -> Tile:
    """One tile block, as palette entries and the mask the blitter uses."""
    if len(raw) < TILE_HEADER.size:
        raise LaterArtError(f"{name}: {len(raw)} bytes is shorter than a "
                            f"tile header")
    height, _x, _y, eights, kind = TILE_HEADER.unpack_from(raw, 0)
    kind &= 0x0F
    if kind not in (0, 1) or not height or not eights:
        raise LaterArtError(f"{name}: a type-{kind} header of {height} rows "
                            f"and {eights} eights is not a figure tile")
    plane = height * eights
    planes = 4 + kind
    want = TILE_HEADER.size + planes * plane
    # A block is stored at an even length, so an odd tile carries one byte
    # of padding (Silver Blades' redrawn head, art 74, is 143 and 144).
    if len(raw) != want + want % 2:
        raise LaterArtError(f"{name}: {planes} planes of {plane} bytes and "
                            f"the header make {want}, not {len(raw)}")

    def bit(p: int, y: int, x: int) -> int:
        byte = raw[TILE_HEADER.size + p * plane + y * eights + x // 8]
        return byte >> (7 - x % 8) & 1

    width = eights * 8
    rows, opaque = [], []
    for y in range(height):
        rows.append(tuple(sum(bit(kind + p, y, x) << p for p in range(4))
                          for x in range(width)))
        opaque.append(tuple(not (kind and bit(0, y, x))
                            for x in range(width)))
    return Tile(height, width, tuple(rows), tuple(opaque))


def read_tiles(data: bytes, name: str = "library") -> dict[int, Tile]:
    """Every tile of `CHEAD.TLB`, `CBODY.TLB` or `COMSPR.TLB`, by art id."""
    return {art: decode_tile(raw, f"{name} art {art}")
            for art, raw in library(data, name).items()}


def frames(comspr: dict[int, Tile]) -> tuple[Tile, Tile]:
    """The boxes behind the ready and the action pose, from `COMSPR.TLB`."""
    missing = [a for a in (FRAME_ID, FRAME_ID + ACTION) if a not in comspr]
    if missing:
        raise LaterArtError(f"{FRAME_FILE} holds no art "
                            f"{', '.join(map(str, missing))}")
    return comspr[FRAME_ID], comspr[FRAME_ID + ACTION]


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
def palette_block(raw: bytes, name: str = "palette") -> tuple[tuple[int, int, int], ...]:
    """A type-8 block's sixteen colours, as the screen shows them."""
    if (len(raw) < TILE_HEADER.size + 3 * PALETTE_COLOURS
            or raw[7] & 0x0F != PALETTE_TYPE):
        raise LaterArtError(f"{name} is not a palette block")
    body = raw[TILE_HEADER.size:TILE_HEADER.size + 3 * PALETTE_COLOURS]
    return tuple(tuple(17 * ((c + 8) // 17) for c in body[i:i + 3])
                 for i in range(0, len(body), 3))


def icon_palette(always: bytes, title: str) -> tuple[tuple[int, int, int], ...]:
    """The sixteen colours the title's ICON screen shows, from `ALWAYS.TLB`."""
    block = _title(title).palette_block
    blocks = library(always, PALETTE_FILE)
    if block not in blocks:
        raise LaterArtError(f"{PALETTE_FILE} holds no block {block}")
    return palette_block(blocks[block], f"{PALETTE_FILE} block {block}")


def recolour_tables(executable: bytes) -> tuple[bytes, bytes]:
    """`(entry, parts)`: the executable's own two recolour tables.

    `entry[v]` is the Amiga palette entry DOS pixel value `v` is drawn in
    (Curse `g0EE4`, Silver Blades `g2374`); `parts` are the six part values
    the record's colour bytes recolour, in record order (`g1BB9`, `g1F76`).
    Found through the recolour builder's own `lea` instructions rather than
    at a fixed offset.
    """
    try:
        hunks, _relocs = amiga_hunks.parse(executable)
    except (ValueError, IndexError, struct.error) as exc:
        raise LaterArtError(f"the executable is not a Hunk file, or is cut "
                            f"short: {exc}") from exc
    code = next((h for h in hunks if h.kind == "CODE"), None)
    data = next((h for h in hunks if h.kind == "DATA"), None)
    if code is None or data is None or data.file_offset is None:
        raise LaterArtError("the executable has no code and data hunk")
    head, tail = _BUILDER
    found = []
    at = executable.find(head, code.file_offset, code.file_offset + code.size)
    while at >= 0:
        after = at + len(head) + 2
        if executable[after:after + len(tail)] == tail:
            entry = struct.unpack_from(">h", executable, at + len(head))[0]
            parts = struct.unpack_from(">h", executable,
                                       after + len(tail))[0]
            found.append((entry, parts))
        at = executable.find(head, at + 2, code.file_offset + code.size)
    if len(set(found)) != 1:
        raise LaterArtError(f"the executable holds {len(set(found))} "
                            f"recolour builders, not one")
    tables = []
    for displacement, length in zip(found[0], (16, 6)):
        start = data.file_offset + _SMALL_DATA_BIAS + displacement
        if not data.file_offset <= start <= data.file_offset + data.size - length:
            raise LaterArtError("a recolour table lies outside the data hunk")
        tables.append(executable[start:start + length])
    entry, parts = tables
    if sorted(entry) != list(range(16)) or not all(1 <= p < 8 for p in parts):
        raise LaterArtError(f"the tables {entry.hex(' ')} and "
                            f"{parts.hex(' ')} are not a recolour")
    return entry, parts


def recolour_table(colours: bytes, entry: bytes,
                   parts: bytes) -> tuple[int, ...]:
    """The sixteen-entry table the loader builds from a record's colours.

    It starts as the identity over palette entries; then for each colour
    byte in record order, `entry[part]` becomes `entry[low nibble]` and
    `entry[part + 8]` becomes `entry[high nibble]` (`/Curse` `0x24EDC`-
    `0x24F82`).  That is DOS's own recolour, translated into palette entries.
    """
    if len(colours) != len(parts):
        raise LaterArtError(f"icon_colours is {len(parts)} bytes, not "
                            f"{len(colours)}")
    table = list(range(16))
    for part, chosen in zip(parts, colours):
        table[entry[part]] = entry[chosen & 0x0F]
        table[entry[part + 8]] = entry[chosen >> 4]
    return tuple(table)


# ---------------------------------------------------------------------------
# The figure
# ---------------------------------------------------------------------------
#: One pose: `rows[y][x]` is a palette entry, or None where the figure is
#: see-through and the box behind it shows.
Pose = tuple[tuple[int | None, ...], ...]


def block_ids(option: int, size: int) -> tuple[int, int]:
    """The `(ready, action)` art ids the loader asks for, head or body."""
    ready = option + (LARGE if size == 2 else 0)
    return ready, ready + ACTION


def compose(heads: dict[int, Tile], bodies: dict[int, Tile], icon_head: int,
            icon_body: int, size: int, colours: bytes, entry: bytes,
            parts: bytes) -> tuple[Pose, Pose]:
    """The `(ready, action)` poses the ICON screen draws for a record.

    Each pose is the body tile with the head tile of the same pose drawn
    over it from row 0, both recoloured through :func:`recolour_table`; a
    head pixel replaces the body pixel wherever the head is opaque.
    """
    table = recolour_table(colours, entry, parts)
    poses = []
    for head_id, body_id in zip(block_ids(icon_head, size),
                                block_ids(icon_body, size)):
        if head_id not in heads:
            raise LaterArtError(f"{HEAD_FILE} holds no art {head_id}")
        if body_id not in bodies:
            raise LaterArtError(f"{BODY_FILE} holds no art {body_id}")
        head, body = heads[head_id], bodies[body_id]
        if head.width != body.width or head.height > body.height:
            raise LaterArtError(f"head art {head_id} ({head.width}x"
                                f"{head.height}) does not fit body art "
                                f"{body_id} ({body.width}x{body.height})")
        rows = []
        for y in range(body.height):
            line = []
            for x in range(body.width):
                if y < head.height and head.opaque[y][x]:
                    line.append(table[head.rows[y][x]])
                elif body.opaque[y][x]:
                    line.append(table[body.rows[y][x]])
                else:
                    line.append(None)
            rows.append(tuple(line))
        poses.append(tuple(rows))
    return poses[0], poses[1]


def on_frame(frame: Tile, pose: Pose) -> tuple[tuple[int, ...], ...]:
    """`pose` drawn over its box, as rows of palette entries."""
    if (frame.height, frame.width) != (len(pose), len(pose[0])):
        raise LaterArtError(f"the box is {frame.width}x{frame.height} and "
                            f"the pose {len(pose[0])}x{len(pose)}")
    out = []
    for y, row in enumerate(pose):
        line = []
        for x, value in enumerate(row):
            if value is not None:
                line.append(value)
            elif frame.opaque[y][x]:
                line.append(frame.rows[y][x])
            else:
                raise LaterArtError(f"the box is see-through at ({x}, {y}), "
                                    f"where the figure is too")
        out.append(tuple(line))
    return tuple(out)


# ---------------------------------------------------------------------------
# The player's disks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LaterArt:
    """One title's figure art, box, colours and recolour tables."""

    title: str
    heads: dict[int, Tile]
    bodies: dict[int, Tile]
    frames: tuple[Tile, Tile]
    palette: tuple[tuple[int, int, int], ...]
    entry: bytes
    parts: bytes

    def poses(self, icon_head: int, icon_body: int, size: int,
              colours: bytes) -> tuple[Pose, Pose]:
        """The record's ready and action poses, see :func:`compose`."""
        return compose(self.heads, self.bodies, icon_head, icon_body, size,
                       bytes(colours), self.entry, self.parts)

    def drawn(self, icon_head: int, icon_body: int, size: int,
              colours: bytes) -> tuple[tuple[tuple[tuple[int, int, int], ...], ...], ...]:
        """Both poses over their boxes, as rows of `(r, g, b)`."""
        return tuple(tuple(tuple(self.palette[v] for v in row)
                           for row in on_frame(frame, pose))
                     for frame, pose in zip(self.frames, self.poses(
                         icon_head, icon_body, size, colours)))


def read_art(title: str, files: dict[str, bytes]) -> LaterArt:
    """:class:`LaterArt` from the five files :func:`disk_files` gathers."""
    _title(title)
    missing = [k for k in (HEAD_FILE, BODY_FILE, FRAME_FILE, PALETTE_FILE,
                           EXECUTABLE) if k not in files]
    if missing:
        raise LaterArtMissing(f"no {', '.join(missing)} to draw a figure "
                              f"from")
    entry, parts = recolour_tables(files[EXECUTABLE])
    return LaterArt(title, read_tiles(files[HEAD_FILE], HEAD_FILE),
                    read_tiles(files[BODY_FILE], BODY_FILE),
                    frames(read_tiles(files[FRAME_FILE], FRAME_FILE)),
                    icon_palette(files[PALETTE_FILE], title), entry, parts)


def disk_files(title: str, disks) -> dict[str, bytes]:
    """The five files the title's figure needs, off opened `AmigaDisk`s.

    Disk 1 is the one with the executable in its root, and gives
    `COMSPR.TLB` and `ALWAYS.TLB` from its drawer; disk 2 is one with
    `CHEAD.TLB` and `CBODY.TLB` in the title's disk-2 drawer.  Pools of
    Darkness keeps an `ALWAYS.TLB` in a `DISK1` drawer too, but not beside
    `/Secret`.  Raises :class:`LaterArtMissing` when a file is not found.
    """
    where = _title(title)
    first, second = (d.upper() for d in where.drawers)
    found: dict[str, bytes] = {}
    for disk in disks:
        names = {path.strip("/").upper(): path for path, _ in disk.walk()}
        if EXECUTABLE not in found and where.executable.upper() in names:
            wanted = {EXECUTABLE: where.executable.upper(),
                      FRAME_FILE: f"{first}/{FRAME_FILE}",
                      PALETTE_FILE: f"{first}/{PALETTE_FILE}"}
            if all(v in names for v in wanted.values()):
                found.update({k: disk.read_file(names[v])
                              for k, v in wanted.items()})
        if HEAD_FILE not in found:
            wanted = {k: f"{second}/{k}" for k in (HEAD_FILE, BODY_FILE)}
            if all(v in names for v in wanted.values()):
                found.update({k: disk.read_file(names[v])
                              for k, v in wanted.items()})
    missing = [k for k in (EXECUTABLE, FRAME_FILE, PALETTE_FILE, HEAD_FILE,
                           BODY_FILE) if k not in found]
    if missing:
        raise LaterArtMissing(f"no {', '.join(missing)} on these disks")
    return found


def _title(title: str) -> LaterTitle:
    try:
        return TITLES[title]
    except KeyError:
        raise LaterArtError(f"no Amiga ICON screen is read for {title!r}; "
                            f"known: {', '.join(TITLES)}") from None
