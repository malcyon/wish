"""A Pool of Radiance party of seven converts to the Amiga with all seven.

The Amiga engine loads and saves up to eight characters, so DIRTEN, the
companion who joins as the seventh, is written like any other member.  The
inputs are the player's own C64 disk and the engine-resaved DOS specimen;
each test skips when they or the Amiga game disk are absent.  No game bytes
are stored here.
"""

from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root
from PyQt6.QtWidgets import QApplication

from automap import gamedisks
from editor import convert, roster, saveplan
from goldbox import amiga_savegame, c64_port
from goldbox.amiga_adf import AmigaDisk
from tools.convert import convertdrops

SEVEN = 7


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _dos_party():
    root = specimen_root()
    found = list(root.glob("*-dos/WISH-SPEC-issue641-dirten-seven-resave")) if root else []
    if not found:
        pytest.skip("needs ~/wish-specimens/*-dos/"
                    "WISH-SPEC-issue641-dirten-seven-resave")
    return roster.Party(str(found[0]))


def _c64_party():
    where = gamedisks.find(c64_port.POOL_OF_RADIANCE.key)
    disk_path = pathlib.Path(where) / "TEST_DOS_IMPORT9.D64" if where else None
    if disk_path is None or not disk_path.exists():
        pytest.skip("needs TEST_DOS_IMPORT9.D64 in the Pool of Radiance folder")
    return roster.Party(str(disk_path))


def _assets(party, scratch):
    amiga = convertdrops.amiga_game_disks(scratch).get(c64_port.POOL_OF_RADIANCE.key)
    source = party.source or convert.Source.detect(party.path)
    try:
        return source, saveplan.resolve_assets(
            source, "amiga", game_files=convertdrops.game_files, amiga_disk=amiga)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks and Amiga disk 2")


def _check_disk(image: bytes, party, slot: str):
    disk = AmigaDisk(bytearray(image))
    drawer = amiga_savegame.por_save_drawer(disk)
    save = disk.read_file(amiga_savegame.por_save_path(
        amiga_savegame.por_savegame_filename(slot), drawer))
    assert save[amiga_savegame.POR_PARTY_SIZE_BYTE] == SEVEN
    assert amiga_savegame.por_word(save, 0x503E) == SEVEN
    for n in range(SEVEN):
        at = amiga_savegame.POR_CHARACTER_TABLE + n * amiga_savegame.POR_CHARACTER_TABLE_STRIDE
        assert save[at:at + 8] == f"CHRDAT{slot}{n + 1}".encode("ascii")
    got = [c.name for c in amiga_savegame.read_por_characters(disk, slot, drawer)]
    assert got == [m.record.get("name") for m in party.members]


@pytest.mark.parametrize("make,slot", [(_c64_party, "A"), (_dos_party, "B")])
def test_a_seven_member_party_saves_as_amiga_with_all_seven(app, tmp_path, make, slot):
    party = make()
    assert len(party.members) == SEVEN
    _source, assets = _assets(party, tmp_path)
    plan = saveplan.prepare_save_as(party, "amiga", tmp_path / "out.adf", assets)
    assert saveplan.losses(plan.report) == []
    (image,) = plan.files
    _check_disk(plan.files[image], party, slot)


def test_a_seven_member_c64_party_converts_to_amiga_through_file_convert(app, tmp_path):
    party = _c64_party()
    source, assets = _assets(party, tmp_path)
    direction = next(d for d in convert.DIRECTIONS
                     if type(d) is convert.C64ToAmiga
                     and d.shape.key == c64_port.POOL_OF_RADIANCE.key)
    rehearsal, slot = saveplan.rehearse(direction, source, assets)
    assert saveplan.losses(rehearsal.report) == []
    images = [data for name, data in rehearsal.files.items()
              if name.lower().endswith(".adf")] or list(rehearsal.files.values())[:1]
    _check_disk(images[0], party, slot)
