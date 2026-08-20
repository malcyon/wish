"""The memory map is descriptive, so the tests check it stays honest."""

import pytest

from por import savegame
from por.layout import Confidence
from por.memory import MAP, at, describe, saved_regions


def test_regions_are_sane():
    for r in MAP:
        assert 0 <= r.start <= 0xFFFF, r.name
        assert r.size >= 0 and r.end <= 0x10000 + 1, r.name
        assert r.note or r.confidence is Confidence.CONFIRMED, \
            f"{r.name} is uncertain and unexplained"


def test_names_are_unique():
    names = [r.name for r in MAP]
    assert len(names) == len(set(names))


def test_it_agrees_with_the_constants_the_decoders_actually_use():
    """The map is a second statement of things savegame.py already knows, so it
    can drift. Pin the overlaps."""
    assert at(savegame.PARTY_X)[0].name == "party x"
    assert at(savegame.AREA)[-1].name == "current GEO"
    assert at(savegame.ICON_TABLE_BASE)[0].name == "combat icon table"
    assert at(savegame.ITEM_AREA_BASE)[0].name == "item area"
    assert at(savegame.ROSTER_BASE if hasattr(savegame, "ROSTER_BASE")
              else 0x8300)[0].name == "party roster"


def test_the_save_ranges_line_up_with_the_files():
    """SAVEDGAME0 is $4900-$64FF and SAVEDGAME1 is $8300-$8AFF; nothing marked
    as saved may fall outside its file."""
    bounds = {
        "SAVEDGAME0": (savegame.SAVE0_LOAD_ADDRESS,
                       savegame.SAVE0_LOAD_ADDRESS + savegame.SAVE0_SIZE),
        "SAVEDGAME1": (0x8300, 0x8B00),
    }
    for name, (lo, hi) in bounds.items():
        for r in saved_regions(name):
            assert lo <= r.start and r.end <= hi, f"{r.name} outside {name}"


def test_overlapping_regions_are_all_reported():
    """$4BC2 is both the area id and one entry of the loaded-files cache, and
    seeing both is the point."""
    names = [r.name for r in at(0x4BC2)]
    assert "loaded-files cache" in names and "current GEO" in names


def test_describe_says_so_when_it_does_not_know():
    assert "not in the map" in describe(0x1234)
