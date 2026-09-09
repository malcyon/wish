"""`tools/worldtiles.py` -- the C64 cell rules, against synthetic bytes.

Measurement A of `docs/217-drawing-the-wilderness.md` turns a wilderness tile
into pixels, and three rules decide every pixel of it: bit 3 of the attribute
picks multicolour over hi-res, a multicolour pixel *pair* chooses between the
three shared colours and the attribute's low three bits, and a screen code is
`$40` above its glyph. Each is asserted here on a glyph this file makes up, so
no game bytes are needed and none are read.

What is *not* here, deliberately: any comparison against a screenshot. The
travel screens in `work/issue178/` and `work/issue11/` are the game's own art
and cannot be fixtures, so the check that the renderer reproduces one is done
by eye and reported on
`#11 (Draw the wilderness on the automapper)`. The byte-level half of that
check -- 225 of 225 screen codes over the game's own pane -- is
`tools/worldregisters.py`'s, against a running machine.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from goldbox.world import (
    Tile,  # noqa: E402
    Window,  # noqa: E402
)
from tests.test_world import synthetic_window  # noqa: E402
from tools.worldtiles import (  # noqa: E402
    GLYPH_BASE,
    GLYPH_BYTES,
    TILE_PIXELS,
    cell_pixels,
    pane_codes,
    tile_pixels,
)

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
