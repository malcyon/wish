"""The DOS combat figure and the ICON screen it is shown on, for Pool of
Radiance, Curse of the Azure Bonds and Secret of the Silver Blades.

The art is `CHEAD.DAX` and `CBODY.DAX` in the title's own game folder, read
at run time through :func:`read_game`; nothing of the game's is held here.
Each unpacked block is one image (`docs/168-dos-dax-and-combat-icons.md`):

* a 17-byte header -- rows at byte 0, the width in eights at byte 2;
* then `rows * width * 4` bytes, two four-bit pixels a byte, high nibble
  first.

A pixel is a part number, not a colour.  The figure loader (Pool of Radiance
`GAME.OVR:0x1E468`, Curse `0x1C1C1`, Silver Blades `0x242B7`) loads a head
and a body block for each pose, ORs the head into the body from row 0, and
recolours the result through a table built from the record's six
`icon_colours` bytes; :func:`compose` is that rule.  Transparency is decided
when a block is loaded, from the stored part number: the loader's mask
helper (Pool of Radiance `START.EXE` image `0x4640`) marks a pixel see-through
where its stored value is 0, the composite ANDs the two masks, and the
recolour never touches the mask.  So a colour nibble of 0 draws colour 0; it
does not let the background show.

The ICON screen draws, behind each pose, a fill of colour 0 and a box from
`COMSPR.DAX` (:func:`frame_for`, :func:`on_frame`), then the figure.  Pool
of Radiance and Curse exchange palette registers 0 and 8 for the whole ICON
screen, and Silver Blades turns the outline value 8 into 0 before the
recolour instead;
:data:`ICON_SCREENS` records both, and :func:`icon_palette` gives the sixteen
colours.  All of this is for the EGA mode the three titles' shipped
configuration files select (first line `E`).
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from .dos_savegame import dax_blocks

#: The three files the ICON screen draws from, in the title's game folder.
HEAD_FILE, BODY_FILE, FRAME_FILE = "CHEAD.DAX", "CBODY.DAX", "COMSPR.DAX"

#: The block of `COMSPR.DAX` the game loads into figure slot 25, with block
#: `25 + ACTION` as its second pose (Pool of Radiance `GAME.OVR:0xEB17`, Curse
#: `0xFB55`, Silver Blades `0x10905`); the ICON screen draws it behind each
#: pose of the figure.
FRAME_BLOCK = 25

#: The image header's length; the pixels start here.
IMAGE_HEADER = 17

#: What the block loader adds to an option for `size` 2 (the file name ends
#: `T`), and what it adds for the second pose, to heads and bodies alike
#: (Pool of Radiance `GAME.OVR:0x31CAE`, `0x31D03`, `0x31D3F`).
LARGE, ACTION = 0x40, 0x80

#: The part values each of the record's six colour bytes recolours, in record
#: order (body, arm, leg, hair and face, shield, weapon): a byte's low nibble
#: replaces value `t` and its high nibble value `t + 8`.  Entries 1-6 of the
#: seven-byte table each title's recolour builder indexes -- `START.EXE` data
#: segment `0x3CF5` (Pool of Radiance), `0x3EC2` (Curse), `0x4CAF` (Silver
#: Blades); `tools/icons/dosicons.py --palette` reads it off the player's own
#: executable.  Values 5, 13 (plume) and 8 (outline) are never recoloured.
PART_TABLE = (1, 2, 3, 4, 6, 7)

#: The sixteen colours of the EGA 200-line palette, which is the hardware's
#: own: the games set palette register `c` to attribute `c` below 8 and
#: `c + 8` from 8 (Pool of Radiance `START.EXE` image `0x704D`), which is the
#: power-on mapping.  Not game data.
EGA = ((0x00, 0x00, 0x00), (0x00, 0x00, 0xAA), (0x00, 0xAA, 0x00),
       (0x00, 0xAA, 0xAA), (0xAA, 0x00, 0x00), (0xAA, 0x00, 0xAA),
       (0xAA, 0x55, 0x00), (0xAA, 0xAA, 0xAA), (0x55, 0x55, 0x55),
       (0x55, 0x55, 0xFF), (0x55, 0xFF, 0x55), (0x55, 0xFF, 0xFF),
       (0xFF, 0x55, 0x55), (0xFF, 0x55, 0xFF), (0xFF, 0xFF, 0x55),
       (0xFF, 0xFF, 0xFF))


@dataclass(frozen=True)
class IconScreen:
    """What one title's ICON screen does beyond the shared figure rule.

    `swaps_black_and_grey`: the screen sets palette register 0 to colour 8
    and register 8 to colour 0 on entry and puts them back on exit.
    `outline_to_black`: after the composite the loader remaps value 8 to 0
    in EGA mode, before the record's recolour.  `action_box`: which of the
    box's two poses (block 25 or 153) is drawn behind the action pose; the
    ready pose always gets block 25.
    """

    swaps_black_and_grey: bool
    outline_to_black: bool
    action_box: int


#: Read from each title's `GAME.OVR`.  Pool of Radiance's ICON routine
#: (`0x1D1AC`) calls the exchange at `0x3081D` first and the restore at
#: `0x3083F` last; Curse's (`0x23EAD`) does the same through `0x4012E` and
#: `0x4016C`.  Silver Blades' ICON routine (`0x21398`) calls the same two
#: entries, which are empty there (`0x418B3`, `0x418BA`), and its loader
#: remaps through the `START.EXE` data tables `0x19A4` and `0x19B4` -- equal
#: but for entry 8, which is 0 -- when the display mode byte `0x6816` is not
#: 0 (`0x2437E`, `0x243D6`).  The box behind the action pose is block 153
#: in Pool of Radiance (`GAME.OVR:0x1CEFB`) and Curse (`0x23C00`), and block
#: 25 again in Silver Blades (`0x210E9`).
ICON_SCREENS: dict[str, IconScreen] = {
    "pool-of-radiance": IconScreen(True, False, 1),
    "curse-of-the-azure-bonds": IconScreen(True, False, 1),
    "secret-of-the-silver-blades": IconScreen(False, True, 0),
}

#: Where the ICON screen draws, in 24-pixel cells: `(column, row)` of each
#: pose of the figure as it was (`OLD`) and as it is being edited (`NEW`).
#: Pool of Radiance `GAME.OVR:0x1D26F` and `0x1D2EE` call the draw helper at
#: `0x1CE5E` with rows 2 and 4, which draws the first pose at column 1 and the
#: second at column 4; the draw routine `0x31F68` multiplies both by three
#: eight-pixel units.
PLACES = {("old", 0): (1, 2), ("old", 1): (4, 2),
          ("new", 0): (1, 4), ("new", 1): (4, 4)}
CELL = 24


class DosArtError(ValueError):
    """This is not a combat-figure block or game folder this reader knows."""


@dataclass(frozen=True)
class ArtBlock:
    """One decoded block: `rows[y][x]` is a four-bit pixel value, 0 empty."""

    height: int
    width: int
    rows: tuple[tuple[int, ...], ...]


#: One pose: `rows[y][x]` is a palette index, or None where the figure is
#: empty and whatever is behind it shows through.
Pose = tuple[tuple[int | None, ...], ...]


def block_pixels(block: bytes) -> list[list[int]]:
    """One image block's stored values as `[y][x]`, read by its own header."""
    rows, stride = block[0], block[2] * 4
    expected = IMAGE_HEADER + rows * stride
    if len(block) < expected:
        raise DosArtError(f"A block of {len(block)} bytes is shorter than "
                          f"the {expected} its header describes")
    out = []
    for y in range(rows):
        line: list[int] = []
        for byte in block[IMAGE_HEADER + y * stride:
                          IMAGE_HEADER + (y + 1) * stride]:
            line.append(byte >> 4)
            line.append(byte & 0x0F)
        out.append(line)
    return out


def decode_block(raw: bytes, name: str = "block") -> ArtBlock:
    """One unpacked image block, as rows of values.

    Raises :class:`DosArtError` when the header does not describe the bytes
    that follow it, rather than reading a picture at the wrong stride.
    """
    if len(raw) < IMAGE_HEADER:
        raise DosArtError(f"{name}: {len(raw)} bytes is shorter than the "
                          f"{IMAGE_HEADER}-byte header")
    height, eights = raw[0], raw[2]
    if not height or not eights:
        raise DosArtError(f"{name}: a header of {height} rows and {eights} "
                          f"eights is not an image")
    want = IMAGE_HEADER + height * eights * 4
    if len(raw) != want:
        raise DosArtError(f"{name}: {height} rows of {eights * 8} pixels and "
                          f"the header make {want} bytes, not {len(raw)}")
    rows = tuple(tuple(row) for row in block_pixels(raw))
    return ArtBlock(height, eights * 8, rows)


def read_art(data: bytes, name: str = "dax") -> dict[int, ArtBlock]:
    """Every block of `CHEAD.DAX`, `CBODY.DAX` or `COMSPR.DAX`, by block id."""
    return {bid: decode_block(raw, f"{name} block {bid}")
            for bid, raw in dax_blocks(data, name)}


@dataclass(frozen=True)
class GameArt:
    """One title's figure art, as the ICON screen uses it."""

    heads: dict[int, ArtBlock]
    bodies: dict[int, ArtBlock]
    frame: tuple[ArtBlock, ArtBlock]


def _file(folder: pathlib.Path, name: str) -> pathlib.Path:
    """`name` in `folder`, whatever its case on this file system."""
    exact = folder / name
    if exact.is_file():
        return exact
    for path in folder.iterdir():
        if path.name.upper() == name and path.is_file():
            return path
    raise DosArtError(f"{folder} holds no {name}")


def read_game(folder: str | pathlib.Path) -> GameArt:
    """The heads, bodies and ICON-screen box from a DOS game folder."""
    folder = pathlib.Path(folder)
    if not folder.is_dir():
        raise DosArtError(f"{folder} is not a folder")
    heads = read_art(_file(folder, HEAD_FILE).read_bytes(), HEAD_FILE)
    bodies = read_art(_file(folder, BODY_FILE).read_bytes(), BODY_FILE)
    frames = read_art(_file(folder, FRAME_FILE).read_bytes(), FRAME_FILE)
    missing = [b for b in (FRAME_BLOCK, FRAME_BLOCK + ACTION)
               if b not in frames]
    if missing:
        raise DosArtError(f"{FRAME_FILE} holds no block "
                          f"{', '.join(map(str, missing))}")
    return GameArt(heads, bodies,
                   (frames[FRAME_BLOCK], frames[FRAME_BLOCK + ACTION]))


def block_ids(option: int, size: int) -> tuple[int, int]:
    """The `(ready, action)` block ids the loader asks for, head or body."""
    ready = option + (LARGE if size == 2 else 0)
    return ready, ready + ACTION


def recolour_table(colours: bytes) -> tuple[int, ...]:
    """The sixteen-entry table the recolour builder makes from a record.

    It starts as the identity; then for each of the six colour bytes in
    record order, value `t` becomes the byte's low nibble and value `t + 8`
    its high nibble, `t` from :data:`PART_TABLE`.
    """
    if len(colours) != len(PART_TABLE):
        raise DosArtError(f"icon_colours is {len(PART_TABLE)} bytes, "
                         f"not {len(colours)}")
    table = list(range(16))
    for part, chosen in zip(PART_TABLE, colours):
        table[part] = chosen & 0x0F
        table[part + 8] = chosen >> 4
    return tuple(table)


def recolour(pixels: list[list[int]], colours: bytes) -> list[list[int]]:
    """Stored values as the palette indices a record's colours make them."""
    table = recolour_table(colours)
    return [[table[v] for v in row] for row in pixels]


def composite(body: list[list[int]], head: list[list[int]],
              size: int = 24) -> list[list[int]]:
    """The head ORed into the body from row 0, padded to `size` square."""
    out = [list(row[:size]) + [0] * (size - len(row[:size]))
           for row in body[:size]]
    out += [[0] * size for _ in range(size - len(out))]
    for y, row in enumerate(head[:size]):
        for x, value in enumerate(row[:size]):
            out[y][x] |= value
    return out


def compose(heads: dict[int, ArtBlock], bodies: dict[int, ArtBlock],
            icon_head: int, icon_body: int, size: int, colours: bytes,
            title: str = "pool-of-radiance") -> tuple[Pose, Pose]:
    """The `(ready, action)` poses the figure loader builds for a record.

    `heads` and `bodies` are :func:`read_art` of the title's `CHEAD.DAX` and
    `CBODY.DAX`; `title` picks the title's :data:`ICON_SCREENS` entry.  Each
    pose is the body block :func:`block_ids` names with the head block of the
    same pose ORed in from row 0, then (Silver Blades) value 8 turned into 0,
    then every value replaced through :func:`recolour_table`.  A pixel is None
    where head and body both store 0.
    """
    screen = _screen(title)
    table = recolour_table(colours)
    poses = []
    for head_id, body_id in zip(block_ids(icon_head, size),
                                block_ids(icon_body, size)):
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
            over = head.rows[y] if y < head.height else (0,) * body.width
            line = []
            for b, h in zip(row, over):
                value = b | h
                if not value:
                    line.append(None)
                    continue
                if screen.outline_to_black and value == 8:
                    value = 0
                line.append(table[value])
            rows.append(tuple(line))
        poses.append(tuple(rows))
    return poses[0], poses[1]


def frame_for(art: GameArt, pose: int,
              title: str = "pool-of-radiance") -> ArtBlock:
    """The box the title's ICON screen draws behind pose 0 (ready) or 1."""
    return art.frame[_screen(title).action_box if pose else 0]


def on_frame(frame: ArtBlock, pose: Pose) -> tuple[tuple[int, ...], ...]:
    """`pose` drawn over the ICON screen's fill and box, as palette indices.

    The screen fills each place with colour 0, draws the `COMSPR.DAX` box
    over it (its stored 0 is see-through) and then the figure.
    """
    if (frame.height, frame.width) != (len(pose), len(pose[0])):
        raise DosArtError(f"the box is {frame.width}x{frame.height} and the "
                          f"pose {len(pose[0])}x{len(pose)}")
    return tuple(tuple(b if p is None else p for p, b in zip(prow, brow))
                 for prow, brow in zip(pose, frame.rows))


def icon_palette(title: str = "pool-of-radiance"
                 ) -> tuple[tuple[int, int, int], ...]:
    """The sixteen `(r, g, b)` colours the title's ICON screen shows."""
    palette = list(EGA)
    if _screen(title).swaps_black_and_grey:
        palette[0], palette[8] = EGA[8], EGA[0]
    return tuple(palette)


def _screen(title: str) -> IconScreen:
    try:
        return ICON_SCREENS[title]
    except KeyError:
        raise DosArtError(f"no DOS ICON screen is read for {title!r}; "
                          f"known: {', '.join(ICON_SCREENS)}") from None
