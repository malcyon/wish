"""Tests for goldbox.icons — the combat-icon table at $4BE0."""

import pathlib

import pytest
from gamedata import game_file

from goldbox.icons import (
    CELL_COLS,
    CELLS,
    COMBAT_BACKGROUND,
    ICON_COUNT,
    ICON_SIZE,
    ICON_TABLE_BASE,
    icon_for_slot,
    icon_pixels,
)
from goldbox.savegame import SLOT_AREA_BASE, SaveGame0

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def save():
    return SaveGame0.from_prg((FIXTURES / "party6_after_combat.bin").read_bytes())


def test_table_ends_where_slot_zero_begins():
    assert ICON_TABLE_BASE + ICON_COUNT * ICON_SIZE == SLOT_AREA_BASE


def test_entry_splits_into_equal_shape_and_colour_halves():
    assert ICON_SIZE == CELLS * 2


def test_colours_are_valid_c64_values(save):
    """Every byte in the second half is 0-15, which is what identified it as
    colour data rather than more screen codes."""
    for s in save.characters:
        icon = icon_for_slot(save.to_bytes(), s.index)
        assert all(c <= 0x0F for c in icon.colours), s.record.name


def test_shape_and_colours_are_independently_editable(save):
    """MAGNUS changed only colours where ROLAND changed both, so the halves are
    genuinely separate."""
    icon = icon_for_slot(save.to_bytes(), 0)
    assert len(icon.shape) == CELLS
    assert len(icon.colours) == CELLS
    assert icon.palette                      # non-empty, de-duplicated


def test_scratch_slots_have_icons_too(save):
    for slot in (6, 7):
        assert len(icon_for_slot(save.to_bytes(), slot).raw) == ICON_SIZE


def test_a_bit3_clear_cell_draws_hires_not_multicolour(save):
    """#123: the VIC-II draws a cell in multicolour only when bit 3 of its
    colour byte is set. LADY KATHERINE's weapon cell (index 2) has bit 3
    clear on this save, which is her short sword -- a one-pixel-wide diagonal
    blade, not the two-pixel-wide smear a multicolour decode would produce.

    Cheaper than a photograph: with bit 3 clear, `icon_pixels` must reproduce
    the glyph's eight bits one for one -- foreground where the bit is set,
    `COMBAT_BACKGROUND` where it is clear -- for every one of the 8 columns
    the cell owns. A multicolour decode only ever writes 4 distinct values
    across those 8 columns, each doubled, so this is what tells the two
    apart.
    """
    charset = game_file("CHARPIC00")
    kath = next(c for c in save.characters if c.record.name.strip() == "LADY KATHERINE")
    icon = icon_for_slot(save.to_bytes(), kath.index)
    cell = 2
    color_byte = icon.colours[cell]
    assert not (color_byte & 0x08), "this specimen is only useful with bit 3 clear"
    own = color_byte & 0x07

    pixels = icon_pixels(icon, charset)
    code = icon.shape[cell]
    glyph = charset[code * 8: code * 8 + 8]
    cx, cy = cell % CELL_COLS, cell // CELL_COLS
    for row in range(8):
        bits = glyph[row]
        expected = [own if (bits >> (7 - bit)) & 1 else COMBAT_BACKGROUND
                    for bit in range(8)]
        actual = pixels[cy * 8 + row][cx * 8: cx * 8 + 8]
        assert actual == expected, f"row {row}"
