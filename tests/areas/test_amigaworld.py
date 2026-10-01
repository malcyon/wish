"""`goldbox/amiga_world.py` -- the Amiga wilderness picture, on a program and tiles built here.

The disk-backed tests read the player's own Amiga Pool of Radiance disks and
skip without them.
"""
from __future__ import annotations

import struct

import pytest
from support.hunks import hunk_file, u32

from goldbox import amiga_hunks
from goldbox.amiga_adf import AmigaDisk
from goldbox.amiga_world import (
    GRID_AT,
    GRID_SIZE,
    HEADER,
    PALETTE_AT,
    TILE_ROW_BYTES,
    AmigaWorld,
    colour,
)
from goldbox.world import TILE_PIXELS, WORLD_ACROSS, WORLD_DOWN, WorldError


def tiles(rows: int, paint: dict[int, list[tuple[int, int, int]]] | None = None,
          header: tuple[int, ...] | None = None) -> bytes:
    """A tile block of `rows` tile-rows; `paint` maps a tile to `(x, y, colour)`."""
    words = header or (24, 6, 0, 0, rows, TILE_ROW_BYTES)
    block = bytearray(struct.pack(">6H", *words))
    block += bytes(4 * rows * TILE_ROW_BYTES)
    for tile, pixels in (paint or {}).items():
        row, column = divmod(tile, 2)
        for x, y, index in pixels:
            for plane in range(4):
                if index >> plane & 1:
                    at = (HEADER + plane * rows * TILE_ROW_BYTES + row * TILE_ROW_BYTES
                          + y * 6 + column * 3 + x // 8)
                    block[at] |= 0x80 >> (x % 8)
    return bytes(block)


def program(grid: bytes, words: list[int], at31: int = 31) -> bytes:
    """A 32-hunk executable with the colours in hunk 23 and the grid in hunk 31."""
    bodies = [bytes(8)] * 32
    palette = bytearray(PALETTE_AT + 32 + 4)
    palette[PALETTE_AT:PALETTE_AT + 32] = struct.pack(">16H", *words)
    bodies[23] = bytes(palette)
    body = bytearray(GRID_AT + GRID_SIZE + 4)
    body[GRID_AT:GRID_AT + GRID_SIZE] = grid
    bodies[at31] = bytes(body)
    return hunk_file([(amiga_hunks.HUNK_DATA, b, []) for b in bodies])


WORDS = [0x000, 0x06B] + [0xFFF] * 14


def grid_of(**squares: int) -> bytes:
    """A grid of 1s with `x{x}y{y}=value` set."""
    grid = bytearray([1]) * GRID_SIZE
    for key, value in squares.items():
        x, y = key[1:].split("y")
        grid[int(y) * WORLD_ACROSS + int(x)] = value
    return bytes(grid)


def world(grid=None, bacpac=None, sq1=None, sq2=None, **kw) -> AmigaWorld:
    return AmigaWorld(program(grid or grid_of(), WORDS, **kw),
                      {1: sq1 or tiles(64), 2: sq2 or tiles(64)},
                      {1: bacpac or tiles(21)})


def pixel(picture, x, y):
    return picture[0][y * WORLD_ACROSS * TILE_PIXELS + x]


def test_a_palette_word_is_a_colour_with_each_nibble_times_17():
    assert colour(0x06B) == "#0066BB"
    assert colour(0xFFF) == "#FFFFFF"


def test_the_colours_come_from_hunk_23():
    assert world().picture()[1][:2] == ["#000000", "#0066BB"]


def test_the_picture_is_the_c64s_size():
    pixels, colours = world().picture()
    assert len(pixels) == WORLD_ACROSS * TILE_PIXELS * WORLD_DOWN * TILE_PIXELS
    assert (WORLD_ACROSS * TILE_PIXELS, WORLD_DOWN * TILE_PIXELS) == (1056, 864)
    assert len(colours) == 16


def test_a_pixel_set_only_in_plane_2_is_colour_4():
    assert pixel(world(bacpac=tiles(21, {0: [(0, 0, 4)]})).picture(), 0, 0) == 4


def test_tile_1_is_the_right_half_of_tile_row_0():
    picture = world(grid_of(x0y0=2), bacpac=tiles(21, {1: [(3, 5, 7)]})).picture()
    assert pixel(picture, 3, 5 * WORLD_ACROSS * TILE_PIXELS // WORLD_ACROSS) == 0
    assert picture[0][5 * WORLD_ACROSS * TILE_PIXELS + 3] == 7


def test_a_tile_is_drawn_in_its_square():
    picture = world(grid_of(x2y1=1), bacpac=tiles(21, {0: [(23, 23, 9)]})).picture()
    at = (TILE_PIXELS + 23) * WORLD_ACROSS * TILE_PIXELS + 2 * TILE_PIXELS + 23
    assert picture[0][at] == 9


@pytest.mark.parametrize("value, bank", [(1, "bacpac"), (43, "sq1"), (129, "sq2")])
def test_each_grid_value_reads_its_own_bank(value, bank):
    tile = {"bacpac": 0, "sq1": 42, "sq2": 0}[bank]
    banks = {"bacpac": {}, "sq1": {}, "sq2": {}}
    banks[bank] = {tile: [(0, 0, 11)]}
    picture = world(grid_of(x0y0=value), bacpac=tiles(21, banks["bacpac"]),
                    sq1=tiles(64, banks["sq1"]), sq2=tiles(64, banks["sq2"])).picture()
    assert pixel(picture, 0, 0) == 11


def test_moving_hunk_31_in_the_file_still_finds_the_grid():
    grid = grid_of(x0y0=2)
    bodies = [bytes(8)] * 32
    bodies[23] = bytes(PALETTE_AT + 36)
    body = bytearray(GRID_AT + GRID_SIZE + 4)
    body[GRID_AT:GRID_AT + GRID_SIZE] = grid
    bodies[31] = bytes(body)
    bodies[5] = bytes(4096)                         # pushes hunk 31 along
    data = hunk_file([(amiga_hunks.HUNK_DATA, b, []) for b in bodies])
    other = AmigaWorld(data, {1: tiles(64), 2: tiles(64)},
                       {1: tiles(21, {1: [(0, 0, 5)]})})
    assert other.grid == grid
    assert pixel(other.picture(), 0, 0) == 5


@pytest.mark.parametrize("header", [(25, 6, 0, 0, 21, 144), (24, 7, 0, 0, 21, 144),
                                    (24, 6, 0, 0, 21, 145)])
def test_a_bad_header_is_a_world_error(header):
    with pytest.raises(WorldError):
        world(bacpac=tiles(21, header=header))


def test_a_block_of_the_wrong_size_is_a_world_error():
    with pytest.raises(WorldError):
        world(bacpac=tiles(21) + bytes(4))


def test_a_missing_block_is_a_world_error():
    with pytest.raises(WorldError):
        AmigaWorld(program(grid_of(), WORDS), {1: tiles(64)}, {1: tiles(21)})


def test_a_file_that_is_not_an_executable_is_a_world_error():
    with pytest.raises(WorldError):
        AmigaWorld(b"\0" * 64, {}, {})


def test_a_truncated_program_is_a_world_error():
    whole = program(grid_of(), WORDS)
    hunks, _ = amiga_hunks.parse(whole)
    for cut in (hunks[31].file_offset + GRID_AT + 100, hunks[23].file_offset + PALETTE_AT + 10):
        with pytest.raises(WorldError):
            AmigaWorld(whole[:cut], {1: tiles(64), 2: tiles(64)}, {1: tiles(21)})


def test_a_file_with_more_hunks_than_its_table_lists_is_a_value_error():
    extra = program(grid_of(), WORDS) + u32(amiga_hunks.HUNK_DATA) + u32(0) + u32(amiga_hunks.HUNK_END)
    with pytest.raises(ValueError):
        amiga_hunks.parse(extra)
    with pytest.raises(WorldError):
        AmigaWorld(extra, {1: tiles(64), 2: tiles(64)}, {1: tiles(21)})


def test_both_tile_archives_must_come_from_one_disk():
    one, two = AmigaDisk.blank("pooldata"), AmigaDisk.blank("poolgame")
    one.write_file("sqrpaci.dax", b"x")
    two.write_file("bacpac.dax", b"x")
    two.write_file("program", program(grid_of(), WORDS))
    with pytest.raises(WorldError, match="one disk"):
        AmigaWorld.from_disks([one, two])


def test_identify_is_none():
    assert world().identify(bytes(GRID_SIZE)) is None


def test_from_disks_names_the_file_no_disk_carries():
    with pytest.raises(WorldError, match="program"):
        AmigaWorld.from_disks([AmigaDisk.blank("pooldata")])


# -- against the player's own disks ---------------------------------------------

def _players_disks():
    from tools.amiga import amigasaves
    found = {}
    for _label, data in amigasaves.images():
        try:
            disk = AmigaDisk(data)
        except ValueError:
            continue
        if disk.volume_name.lower() in ("poolgame", "pooldata"):
            found.setdefault(disk.volume_name.lower(), disk)
    if len(found) < 2:
        pytest.skip("needs the Amiga Pool of Radiance disks")
    return list(found.values())


def test_the_players_disks_give_a_whole_grid_and_the_documented_water():
    built = AmigaWorld.from_disks(_players_disks())
    assert len(built.grid) == 1584
    assert 0 not in built.grid
    assert len(set(built.grid)) > 100             # an unread grid is one tile
    pixels, colours = built.picture()
    assert len(colours) == 16
    width = WORLD_ACROSS * TILE_PIXELS
    square = {pixels[(31 * TILE_PIXELS + y) * width + 20 * TILE_PIXELS + x]
              for y in range(TILE_PIXELS) for x in range(TILE_PIXELS)}
    assert square == {1}


def test_the_palette_copy_at_0x20_equals_the_one_at_0x60():
    program_bytes = None
    for disk in _players_disks():
        try:
            program_bytes = disk.read_file("/program")
        except ValueError:
            continue
    if program_bytes is None:
        pytest.skip("no disk carries /program")
    hunks, _ = amiga_hunks.parse(program_bytes)
    at = hunks[23].file_offset
    assert program_bytes[at + 0x20:at + 0x40] == program_bytes[at + 0x60:at + 0x80]
