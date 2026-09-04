from __future__ import annotations

"""`goldbox/world.py` -- the SQRDATA reader, against the format and the disks.

Two groups. The arithmetic -- window bounds, the world-coordinate seams, the
glyph-table split -- is tested against a synthetic window built from the
documented format, the way `tests/gamedata.py`'s `synthetic_geo` is: no game
bytes are needed to prove the shape is read correctly. Everything that checks
an actual value -- file sizes, a known site square, the seam agreement counts
`docs/113-world-map.md` reports -- is read off the player's own disks through
`disk_dir()` and skipped when there are none.
"""

import pathlib

import pytest

from goldbox.world import (
    GRID_SIZE,
    MIN_FILE_SIZE,
    PLAYABLE_X,
    ROWS,
    SEAM_MIDDLE_EAST,
    SEAM_WEST_MIDDLE,
    STRIDE,
    TILE_COUNT,
    TILE_TABLE_SIZE,
    WINDOW_NAMES,
    WINDOW_STEP,
    WORLD_WIDTH,
    Window,
    World,
    WorldError,
    passable,
    site_at,
)
from tests.gamedata import disk_dir

needs_disks = pytest.mark.skipif(disk_dir() is None, reason="needs the game disks")


def synthetic_window(fill: int = 0) -> bytes:
    """A well-formed `SQRDATA` payload built from the documented format, not
    copied from one: the grid holds `(x + y) % 120` so every square names a
    distinct-ish tile, and each of the 120 glyph entries holds its own index
    twice over, nine times, so `tile(i)` is checkable without reading a real
    file at all."""
    grid = bytes((x + y) % TILE_COUNT for y in range(ROWS) for x in range(STRIDE))
    tiles = bytearray(TILE_TABLE_SIZE)
    for i in range(TILE_COUNT):
        at = i * 18
        tiles[at:at + 9] = bytes([i & 0xFF]) * 9
        tiles[at + 9:at + 18] = bytes([(i + fill) & 0xFF]) * 9
    return grid + bytes(tiles)


# -- the format, against a synthetic file -------------------------------------


def test_the_documented_sizes_add_up():
    assert GRID_SIZE == STRIDE * ROWS == 648
    assert TILE_TABLE_SIZE == TILE_COUNT * 18 == 2160
    assert MIN_FILE_SIZE == GRID_SIZE + TILE_TABLE_SIZE == 2808


def test_a_short_payload_is_refused():
    with pytest.raises(WorldError):
        Window(synthetic_window()[:MIN_FILE_SIZE - 1])


def test_the_grid_reads_back_what_it_was_given():
    window = Window(synthetic_window())
    for y in range(ROWS):
        for x in range(STRIDE):
            assert window.square(x, y) == (x + y) % TILE_COUNT


def test_a_square_outside_the_grid_raises():
    window = Window(synthetic_window())
    with pytest.raises(IndexError):
        window.square(STRIDE, 0)
    with pytest.raises(IndexError):
        window.square(0, ROWS)


def test_the_glyph_table_splits_nine_and_nine():
    window = Window(synthetic_window(fill=1))
    tile = window.tile(5)
    assert tile.screen_codes == bytes([5]) * 9
    assert tile.attributes == bytes([6]) * 9


def test_a_tile_index_outside_120_raises():
    window = Window(synthetic_window())
    with pytest.raises(IndexError):
        window.tile(TILE_COUNT)


def test_is_playable_matches_the_documented_border():
    window = Window(synthetic_window())
    assert window.is_playable(2, 2)
    assert window.is_playable(15, 33)
    assert not window.is_playable(1, 10)
    assert not window.is_playable(16, 10)
    assert not window.is_playable(10, 1)
    assert not window.is_playable(10, 34)


# -- the world coordinate, against three synthetic windows --------------------


def _synthetic_world() -> World:
    # Fill each window with its own index so a stitched read shows which
    # window answered it.
    return World(tuple(Window(synthetic_window(fill=k), name=n)
                       for k, n in enumerate(WINDOW_NAMES)))


def test_the_seams_are_the_documented_world_x():
    assert SEAM_WEST_MIDDLE == 15
    assert SEAM_MIDDLE_EAST == 28


def test_locate_picks_the_window_the_seam_documents():
    world = _synthetic_world()
    west, x = world.locate(2)
    assert west is world.windows[0] and x == 2
    # the world x just west of the seam is still the west window
    mid, x = world.locate(SEAM_WEST_MIDDLE - 1)
    assert mid is world.windows[0] and x == PLAYABLE_X.stop - 2
    # at the seam itself, the eastern window answers
    mid, x = world.locate(SEAM_WEST_MIDDLE)
    assert mid is world.windows[1] and x == PLAYABLE_X.start
    east, x = world.locate(SEAM_MIDDLE_EAST)
    assert east is world.windows[2] and x == PLAYABLE_X.start
    east, x = world.locate(WORLD_WIDTH + 1)  # world x 41, the world's own max
    assert east is world.windows[2] and x == PLAYABLE_X.stop - 1


def test_world_x_outside_the_playable_range_raises():
    world = _synthetic_world()
    with pytest.raises(IndexError):
        world.locate(PLAYABLE_X.start - 1)
    with pytest.raises(IndexError):
        world.locate(WORLD_WIDTH + 2)


def test_world_square_matches_the_window_it_stitched_in():
    world = _synthetic_world()
    for k, (lo, hi) in enumerate(((2, SEAM_WEST_MIDDLE - 1),
                                  (SEAM_WEST_MIDDLE, SEAM_MIDDLE_EAST - 1),
                                  (SEAM_MIDDLE_EAST, WORLD_WIDTH + 1))):
        for world_x in range(lo, hi + 1):
            local_x = world_x - WINDOW_STEP * k
            assert world.square(world_x, 10) == world.windows[k].square(local_x, 10)


# -- against the player's own disks -------------------------------------------


def _pool_disks() -> list[pathlib.Path]:
    where = disk_dir()
    return sorted(where.glob("POOL*.[dD]64"))


@needs_disks
def test_the_three_files_are_the_documented_sizes():
    """SQRDATA05 is exactly 2808 bytes; the other two carry eight spares --
    the same check `tests/test_p3.py` makes, now against `goldbox.world`'s own
    reader rather than a raw slice."""
    world = World.from_disks(_pool_disks())
    assert len(world.windows[1].to_bytes()) == MIN_FILE_SIZE          # SQRDATA05
    for k in (0, 2):                                                  # 04, 06
        assert len(world.windows[k].to_bytes()) == MIN_FILE_SIZE + 8
    assert [w.name for w in world.windows] == list(WINDOW_NAMES)


@needs_disks
def test_from_disks_names_the_window_no_disk_carried():
    with pytest.raises(WorldError):
        World.from_disks([])


# `tests/test_p3.py`'s PAINTED table, translated to world coordinates: the
# disk's own (unpainted) value at four known site squares, each converted
# with `world_x = local_x + 13 * window_index` -- window 1 for SQRDATA05,
# window 2 for SQRDATA06, matching `WINDOW_NAMES`.
KNOWN_SQUARES = [
    (12 + WINDOW_STEP * 1, 11, 0x37),   # SQRDATA05, the nomad camp
    (11 + WINDOW_STEP * 2, 8, 0x71),    # SQRDATA06, the lizardman keep
    (6 + WINDOW_STEP * 2, 15, 0x49),    # SQRDATA06, the kobold caves
    (7 + WINDOW_STEP * 2, 23, 0x6D),    # SQRDATA06, the site that was cut
]


@needs_disks
@pytest.mark.parametrize("world_x,y,value", KNOWN_SQUARES)
def test_world_square_matches_known_site_squares(world_x, y, value):
    world = World.from_disks(_pool_disks())
    assert world.square(world_x, y) == value


@needs_disks
def test_the_seam_agreement_matches_the_documented_counts():
    """`docs/113-world-map.md`: 179 of 180 squares agree between the west and
    middle windows across their overlap, 180 of 180 between the middle and
    east. The overlap is the raw grid, all 36 rows, over the five columns
    (18 - 13) two neighbouring windows share -- 36 x 5 = 180, and the count
    is over the whole grid rather than the playable band, which would give
    32 x 5 = 160.
    """
    world = World.from_disks(_pool_disks())
    west, middle, east = world.windows
    overlap_width = STRIDE - WINDOW_STEP
    assert overlap_width == 5

    def agreement(a: Window, b: Window) -> tuple[int, int]:
        agree = total = 0
        for y in range(ROWS):
            for i in range(overlap_width):
                total += 1
                # a's easternmost `overlap_width` columns are b's westernmost.
                agree += a.square(STRIDE - overlap_width + i, y) == b.square(i, y)
        return agree, total

    assert agreement(west, middle) == (179, 180)
    assert agreement(middle, east) == (180, 180)


@needs_disks
def test_sample_size():
    """How many windows and squares this file exercised against the disks,
    per `.claude/rules/testing.md`: 3 windows, 648 grid squares apiece,
    1944 in total."""
    world = World.from_disks(_pool_disks())
    assert len(world.windows) == 3
    assert all(len(w.to_bytes()) >= MIN_FILE_SIZE for w in world.windows)
    assert 3 * GRID_SIZE == 1944


def test_the_two_blocked_functions_say_what_blocks_them():
    """`passable` and `site_at` are declared and raise, which is deliberate.

    Their tables are not in `SQRDATA0n` at all -- they live in `ECL19`/`1A`/
    `1B`'s own bytecode, and the addresses were in a write-up lost with
    `work/` (`#136`). Declaring them and failing loudly is better than
    leaving a caller to guess the module simply has no such idea, and much
    better than guessing an address; but a function that raises is exactly
    what a reader mistakes for dead code, so the message is part of the
    contract and is asserted here.
    """
    for call in (lambda: passable(Window(bytes(GRID_SIZE + TILE_TABLE_SIZE)),
                                  0, 0),
                 lambda: site_at(0, 0)):
        with pytest.raises(NotImplementedError) as caught:
            call()
        said = str(caught.value)
        assert "ECL19" in said and "#136" in said, said
        assert "world-map.md" in said, said
