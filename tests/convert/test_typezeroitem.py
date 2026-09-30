"""A type-0 item record is written into its C64 slot and reported as dropped.

The C64 counts a slot whose type byte is 0 as empty.  No game data creates
such a record; a DOS Pool party Wish converted from the C64 before it read the
empty slot that way holds ten of them.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root
from PyQt6.QtWidgets import QApplication
from support.neutralrecords import FILLED_ITEM, _filled

from editor import roster, saveplan
from goldbox import c64_codec, dos_codec
from tools.convert import convertdrops


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


TYPE_ZERO = "has type 0"
# One named word and type 0: the record the old C64 reader wrote to DOS.
TYPE_ZERO_RECORD = bytes((0, 5)) + bytes(14)

# Type-0 records per member, read off each specimen: 10 in all.
EXPECTED = {"SIMON": 4, "PRINCESS FATIMA": 2, "MAD MAN": 1, "DIRTEN": 3}


def _type_zero_lines(report) -> list[str]:
    return [x for x in report.dropped if TYPE_ZERO in x]


def _specimen(name: str) -> pathlib.Path:
    root = specimen_root()
    found = list(root.glob(f"*-dos/WISH-SPEC-{name}")) if root else []
    if not found:
        pytest.skip(f"needs WISH-SPEC-{name} (tools/registry/specimens.py)")
    return found[0]


def test_a_type_zero_record_is_written_and_reported():
    char = _filled()
    char.set("inventory", [FILLED_ITEM, TYPE_ZERO_RECORD], "made up")
    rec, report = c64_codec.write(char)
    assert len(_type_zero_lines(report)) == 1
    assert "item 1 " in _type_zero_lines(report)[0]
    assert report.losses == []
    slots = rec.get_raw("inventory")
    # The list is in screen order, top row first, so the second of two items
    # is in slot 0.
    assert slots[:16] == TYPE_ZERO_RECORD
    assert slots[16:32] == FILLED_ITEM


def test_a_party_with_no_type_zero_record_has_no_such_line():
    char = _filled()
    char.set("inventory", [FILLED_ITEM], "made up")
    _rec, report = c64_codec.write(char)
    assert _type_zero_lines(report) == []


@pytest.mark.parametrize("name, slot", [
    ("por-790-scribe-complete-stale-count", "E"),
    ("issue641-dirten-seven-resave", "B"),
])
def test_the_wish_made_specimens_count_ten_type_zero_records(name, slot):
    folder = _specimen(name)
    counts = {}
    for n in range(1, 8):
        dos = dos_codec.read_character(folder / f"CHRDAT{slot}{n}.SAV")
        _rec, report = dos_codec.to_c64_record(dos)
        counts[dos.name] = len(_type_zero_lines(report))
    assert {k: v for k, v in counts.items() if v} == EXPECTED
    assert sum(counts.values()) == 10


def test_save_as_to_the_c64_refuses_the_type_zero_records(app, tmp_path):
    folder = _specimen("issue641-dirten-seven-resave")
    party = roster.Party(str(folder))
    try:
        assets = saveplan.resolve_assets(party.source, "c64",
                                         game_files=convertdrops.game_files)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks, found through "
                    "automap/gamedisks.py")
    with pytest.raises(saveplan.DroppedFields) as caught:
        saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)
    # The same line from two members is one entry, so the ten records show as
    # the nine distinct item indexes they sit at.
    lines = {x for x in caught.value.lost if TYPE_ZERO in x}
    assert {int(x.split()[2]) for x in lines} == {1, 2, 4, 5, 11, 12, 13, 14, 15}
