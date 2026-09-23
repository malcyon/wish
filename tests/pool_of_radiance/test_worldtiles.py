"""`tools/pool_of_radiance/worldtiles.py` -- the C64 cell rules, against synthetic bytes.

Measurement A of `docs/217-drawing-the-wilderness.md` turns a wilderness tile
into pixels, and three rules decide every pixel of it: bit 3 of the attribute
picks multicolour over hi-res, a multicolour pixel *pair* chooses between the
three shared colours and the attribute's low three bits, and a screen code is
`$40` above its glyph. Each is asserted here on a glyph this file makes up, so
no game bytes are needed and none are read.

What is *not* here, deliberately: any comparison against a screenshot. The
travel screens in `cited/178` and `cited/11` are the game's own art
and cannot be fixtures, so the check that the renderer reproduces one is done
by eye and reported on
`#11 (Draw the wilderness on the automapper)`. The byte-level half of that
check -- 225 of 225 screen codes over the game's own pane -- is
`tools/pool_of_radiance/worldregisters.py`'s, against a running machine.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from support.worldwindow import synthetic_window  # noqa: E402

from goldbox.world import (  # noqa: E402
    GLYPH_BASE,
    GLYPH_BYTES,
    TILE_PIXELS,
    Tile,
    Window,
    cell_pixels,
    tile_pixels,
)
from tools.pool_of_radiance.worldtiles import pane_codes  # noqa: E402

#: Three shared colours no two of which are the same, so a pixel that took the
#: wrong one of them cannot pass by coincidence.
SHARED = (0x00, 0x0F, 0x05)


def test_a_hires_cell_draws_its_own_colour_on_the_background():
    # Bit 3 clear, so hi-res: every 1 bit is the cell's colour, every 0 the
    # background, one bit a pixel.
    glyph = bytes([0b10100000] + [0] * 7)
    rows = cell_pixels(glyph, 0x05, SHARED)
    assert rows[0][:4] == [5, 0, 5, 0]
    assert rows[1] == [0] * 8


def test_a_multicolour_cell_draws_pairs_out_of_four_colours():
    # Bit 3 set, so multicolour: `11` the cell's own colour (the low three
    # bits, 7), `10` $D023, `01` $D022, `00` $D021 -- two pixels each.
    glyph = bytes([0b11100100] + [0] * 7)
    rows = cell_pixels(glyph, 0x0F, SHARED)
    assert rows[0] == [7, 7, 0x05, 0x05, 0x0F, 0x0F, 0x00, 0x00]


def test_bit_three_is_what_chooses_between_the_two():
    # One bit set, and the two rules disagree about every pixel of the row:
    # hi-res draws one pixel of the cell's colour, multicolour a `01` pair of
    # $D022. The same glyph, and only bit 3 of the attribute moved.
    glyph = bytes([0b01000000] + [0] * 7)
    assert cell_pixels(glyph, 0x05, SHARED)[0][:4] == [0, 5, 0, 0]
    assert cell_pixels(glyph, 0x0D, SHARED)[0][:4] == [0x0F, 0x0F, 0, 0]


def test_a_screen_code_is_forty_hex_above_its_glyph():
    # Glyph 0 is solid, glyph 1 is blank; a tile of code $40 must come out
    # solid and one of $41 blank. An offset of anything but $40 swaps them.
    glyphs = bytes([0xFF] * GLYPH_BYTES) + bytes(GLYPH_BYTES * 191)
    solid = Tile(bytes([GLYPH_BASE] * 9), bytes([1] * 9))
    blank = Tile(bytes([GLYPH_BASE + 1] * 9), bytes([1] * 9))
    lit = tile_pixels(solid, glyphs, SHARED)
    dark = tile_pixels(blank, glyphs, SHARED)
    assert len(lit) == TILE_PIXELS and len(lit[0]) == TILE_PIXELS
    assert set(lit[0]) == {1}       # every bit of glyph 0 set, colour 1
    assert set(dark[0]) == {0}      # every bit of glyph 1 clear


def test_pane_codes_reads_three_character_rows_a_tile_row():
    window = Window(synthetic_window())
    rows = pane_codes(window, 2, 3, 2, 2)
    assert len(rows) == 2 * 3           # three character rows a tile row
    assert len(rows[0]) == 2 * 3        # three cells a tile across
    # The first row is the top third of the two tiles at (2,3) and (3,3).
    first = window.tile_at(2, 3)
    second = window.tile_at(3, 3)
    assert [c for c, _ in rows[0]] == \
        list(first.screen_codes[:3]) + list(second.screen_codes[:3])
    assert [a for _, a in rows[0]] == \
        list(first.attributes[:3]) + list(second.attributes[:3])


def test_a_pane_off_the_edge_of_the_grid_draws_nothing_there():
    window = Window(synthetic_window())
    rows = pane_codes(window, -1, 0, 2, 1)
    assert [c for c, _ in rows[0][:3]] == [0, 0, 0]
    assert [c for c, _ in rows[0][3:]] == list(window.tile_at(0, 0).screen_codes[:3])


# -- the `sample` pictures ---------------------------------------------------

def _solid_world():
    """Three windows whose every square is one solid tile, a different colour
    in each window, so a pixel names the window that drew it."""
    from goldbox.world import ROWS, STRIDE, TILE_TABLE_SIZE, World
    windows = []
    for colour in (1, 2, 3):                # hi-res, so the colour is the index
        tiles = bytearray(TILE_TABLE_SIZE)
        tiles[0:9] = bytes([GLYPH_BASE]) * 9
        tiles[9:18] = bytes([colour]) * 9
        windows.append(Window(bytes(STRIDE * ROWS) + bytes(tiles)))
    glyphs = bytes([0xFF]) * GLYPH_BYTES + bytes(GLYPH_BYTES * 191)
    return World(tuple(windows), (glyphs, glyphs, glyphs))


def _party_rgb():
    from automap.window import PARTY
    return PARTY.getRgb()[:3]


def _hex(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def test_the_default_route_crosses_both_seams_along_row_27():
    from tools.pool_of_radiance.worldtiles import DEFAULT_ROUTE
    assert DEFAULT_ROUTE == [(x, 27) for x in range(4, 40)]


def test_explored_squares_are_the_five_by_five_pane_around_every_route_square():
    from tools.pool_of_radiance.worldtiles import explored_squares
    seen = explored_squares([(10, 10), (11, 10)])
    assert seen == {(x, y) for x in range(8, 14) for y in range(8, 13)}
    assert explored_squares([(0, 0)]) == {(x, y) for x in range(3)
                                          for y in range(3)}


def test_the_four_pictures_have_the_sizes_the_plan_states(tmp_path):
    pytest.importorskip("PyQt6")
    from tools.pool_of_radiance.worldtiles import write_samples
    paths = write_samples(_solid_world(), tmp_path)
    from PIL import Image
    sizes = {p.name: Image.open(p).size for p in paths}
    assert sizes == {"whole-12.png": (44 * 12, 36 * 12),
                     "whole-7.png": (44 * 7, 36 * 7),
                     "piece-34.png": (16 * 34, 16 * 34),
                     "piece-20.png": (16 * 20, 16 * 20)}


def test_a_sample_draws_tiles_only_where_explored_over_paper_with_the_lattice_and_marker():
    pytest.importorskip("PyQt6")
    from automap.window import LATTICE, PAPER, PARTY
    from goldbox.icons import C64_PALETTE
    from tools.pool_of_radiance.worldtiles import (
        DEFAULT_ROUTE,
        explored_squares,
        sample_image,
    )
    cell = 12
    picture = sample_image(_solid_world(), explored_squares(DEFAULT_ROUTE),
                           (28, 27), cell)

    def inside(x, y):                   # a pixel clear of the lattice lines
        return picture.getpixel((x * cell + 4, y * cell + 8))

    # World x 27 is the middle window (colour 2), 28 the east one (colour 3):
    # the seam is where the window changes.
    assert inside(27, 25) == _hex(C64_PALETTE[2])
    assert inside(28, 25) == _hex(C64_PALETTE[3])
    assert inside(6, 25) == _hex(C64_PALETTE[1])
    # The pane reaches two squares off the route and no further.
    assert inside(20, 29) == _hex(C64_PALETTE[2])
    assert inside(20, 30) == PAPER.getRgb()[:3]
    assert inside(20, 24) == PAPER.getRgb()[:3]
    # The lattice is over the tiles, and the marker over both.
    assert picture.getpixel((20 * cell, 27 * cell + 8)) == LATTICE.getRgb()[:3]
    assert picture.getpixel((28 * cell + cell // 2, 27 * cell + cell // 2)) \
        == PARTY.getRgb()[:3]


def test_a_piece_is_centred_on_the_party_and_kept_inside_the_wilderness():
    pytest.importorskip("PyQt6")
    from goldbox.icons import C64_PALETTE
    from tools.pool_of_radiance.worldtiles import (
        WORLD_ACROSS,
        WORLD_DOWN,
        sample_image,
    )
    cell, piece = 34, 16
    everywhere = {(x, y) for x in range(WORLD_ACROSS) for y in range(WORLD_DOWN)}
    # (party, left, top): centred, then against each of the four edges.
    cases = [((28, 27), 20, 19),
             ((3, 27), 0, 19),
             ((40, 27), WORLD_ACROSS - piece, 19),
             ((28, 2), 20, 0),
             ((28, 34), 20, WORLD_DOWN - piece)]
    for party, left, top in cases:
        picture = sample_image(_solid_world(), everywhere, party, cell,
                               piece=piece)
        col, row = party[0] - left, party[1] - top
        # The marker sits in the party's own cell of the piece.
        assert picture.getpixel((col * cell + cell // 2, row * cell + cell // 2)) \
            == _party_rgb(), party
        # The first column of the piece is world x `left`, so its tile
        # colour names the window and proves where the piece starts.
        window = 0 if left < 15 else 1 if left < 28 else 2
        assert picture.getpixel((4, cell * 3 + 8)) == _hex(C64_PALETTE[window + 1]), party
        # The last column of the piece is world x `left + 15`.
        edge = left + piece - 1
        window = 0 if edge < 15 else 1 if edge < 28 else 2
        assert picture.getpixel((piece * cell - 6, cell * 3 + 8)) \
            == _hex(C64_PALETTE[window + 1]), party


def test_the_lattice_has_a_line_on_the_right_and_bottom_edges():
    pytest.importorskip("PyQt6")
    from automap.window import LATTICE
    from tools.pool_of_radiance.worldtiles import sample_image
    picture = sample_image(_solid_world(), set(), (28, 27), 12, piece=16)
    width, height = picture.size
    assert picture.getpixel((width - 1, 40)) == LATTICE.getRgb()[:3]
    assert picture.getpixel((40, height - 1)) == LATTICE.getRgb()[:3]
