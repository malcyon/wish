"""Tests for goldbox.icons — the combat-icon table at $4BE0."""

import pathlib

import pytest

from goldbox.icons import CELLS, ICON_COUNT, ICON_SIZE, ICON_TABLE_BASE, icon_for_slot
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
