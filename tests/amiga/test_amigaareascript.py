"""`amiga_savegame.area_script` looks an area up in block 0 of the Amiga `ECL.GLB`."""
from __future__ import annotations

import pathlib
import struct

import pytest

from goldbox import amiga_savegame
from goldbox.amiga_savegame import AmigaSaveError, area_script


def _glib(blocks: list[bytes]) -> bytes:
    """A GLIB container of `blocks`, built here and not read from any game."""
    head = b"GLIB" + struct.pack(">I", 0) + struct.pack(">HH", len(blocks), 0)
    head += b"DATA"
    start = len(head) + 4 * (len(blocks) + 1)
    offsets, at = [], start
    for block in blocks:
        offsets.append(at)
        at += len(block)
    offsets.append(at)
    return head + struct.pack(f">{len(offsets)}I", *offsets) + b"".join(blocks)


def _table(pairs: list[tuple[int, int]], count: int | None = None) -> bytes:
    count = len(pairs) if count is None else count
    return struct.pack(">H", count) + b"".join(
        struct.pack(">HH", a, b) for a, b in pairs)


def _library(pairs: list[tuple[int, int]]) -> bytes:
    blocks = [_table(pairs)] + [bytes([i]) * (3 + i)
                                for i in range(1, 1 + max(b for _a, b in pairs))]
    return _glib(blocks)


def test_the_world_map_resolves_through_the_table():
    pairs = [(1, 1), (0x50, 23)] + [(0x60 + i, i + 2) for i in range(21)]
    data = _library(pairs)
    assert area_script(data, 0x50) == bytes([23]) * 26


def test_an_area_in_the_sixteens_gets_its_own_block_and_not_the_block_of_that_number():
    data = _library([(1, 1), (0x10, 5), (0x11, 6), (0x32, 16)])
    assert area_script(data, 0x10) == bytes([5]) * 8
    assert area_script(data, 0x32) == bytes([16]) * 19


def test_an_area_the_table_does_not_name_raises():
    data = _library([(1, 1), (2, 2)])
    with pytest.raises(AmigaSaveError, match="no script for area 3"):
        area_script(data, 3)


@pytest.mark.parametrize("table,area", [
    (_table([(1, 1), (2, 2)], count=3), 1),       # count past the block
    (_table([(1, 0)]), 1),                         # block 0 is the table itself
    (_table([(1, 1), (2, 9)]), 2),                 # block number past the file
    (b"\x00", 1),                                  # no room for a count
])
def test_a_table_that_does_not_fit_the_file_raises_and_never_indexes_by_area(
        table, area):
    data = _glib([table, b"aa", b"bbb"])
    with pytest.raises(AmigaSaveError):
        area_script(data, area)


def test_a_table_padded_past_its_count_still_resolves():
    data = _glib([_table([(1, 1), (2, 2)]) + bytes(6), b"aa", b"bbb"])
    assert area_script(data, 2) == b"bbb"


def test_a_bad_pair_for_another_area_does_not_block_this_one():
    data = _glib([_table([(1, 1), (2, 9), (3, 0)]), b"aa", b"bbb"])
    assert area_script(data, 1) == b"aa"
    with pytest.raises(AmigaSaveError, match="block 9"):
        area_script(data, 2)


def test_two_entries_for_the_area_asked_about_raise():
    data = _glib([_table([(1, 1), (2, 2), (1, 2)]), b"aa", b"bbb"])
    assert area_script(data, 2) == b"bbb"
    with pytest.raises(AmigaSaveError, match="2 times"):
        area_script(data, 1)


# -- the player's own disks ---------------------------------------------------


def _amiga_curse_glb() -> bytes:
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    from tools.amiga import amigasaves
    for _label, image in amigasaves.images():
        try:
            return AmigaDisk(image).read_file("/DISKB/ECL.GLB")
        except (AmigaDiskError, ValueError):
            continue
    pytest.skip("needs the player's Amiga Curse disk B")


def _c64_scripts() -> dict[int, bytes]:
    from automap import gamedisks
    from goldbox.d64 import D64
    try:
        root = pathlib.Path(str(gamedisks.find("curse-of-the-azure-bonds")))
    except gamedisks.RegistryError:
        pytest.skip("needs the player's C64 Curse disks")
    out: dict[int, bytes] = {}
    for path in sorted(root.glob("CURSE_?.D64")):
        img = D64.open(path)
        for entry in img.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if (len(name) == 5 and name.startswith("ECL")
                    and name[3:] not in ("64", "65")):
                out.setdefault(int(name[3:], 16), img.read_file(name)[2:])
    if not out:
        pytest.skip("needs the player's C64 Curse disks")
    return out


#: Areas whose Amiga script differs from the C64 one by more than a trailing
#: byte: the Amiga port's own edits, measured against the player's disks.
KNOWN_DIFFERENT = {0x12, 0x31, 0x32}


def _pairs(glb: bytes) -> list[tuple[int, int]]:
    table = amiga_savegame._glib_blocks(glb)[0]
    count = int.from_bytes(table[:2], "big")
    return list(struct.iter_unpack(">HH", table[2:2 + 4 * count]))


def test_every_area_in_the_players_curse_table_resolves_to_the_c64_script():
    glb = _amiga_curse_glb()
    blocks = amiga_savegame._glib_blocks(glb)
    pairs = _pairs(glb)
    assert pairs
    c64 = _c64_scripts()
    compared = 0
    for area, block in pairs:
        assert area_script(glb, area) == blocks[block]
        if area not in c64:
            continue
        compared += 1
        script = blocks[block]
        if area in KNOWN_DIFFERENT:
            continue
        assert script[:len(c64[area])] == c64[area], f"area ${area:02X}"
        assert len(script) - len(c64[area]) in (0, 1), f"area ${area:02X}"
    assert compared > len(KNOWN_DIFFERENT)


@pytest.mark.parametrize("area", [0x50, 0x10])
def test_a_saved_party_in_a_later_area_stages_the_block_the_table_names(area):
    """The whole path: the staged script region, then the area on reading back."""
    import dataclasses

    from goldbox import amiga_later, areas
    from tests.amiga.test_amiga_savegame import _verified_later_save
    glb = _amiga_curse_glb()
    path = _verified_later_save(
        "coab-amiga", "WISH-SPEC-coab-amiga-resave", "savgamE.dat")
    source = amiga_savegame.parse(path.read_bytes(), amiga_savegame.CURSE,
                                  str(path))
    state0 = amiga_savegame.state_from_savegame(source)
    where = areas.area_in(area, state0.title)
    geo = areas.geo_number(where.geos[0]) if where.geos else state0.geo
    state = dataclasses.replace(state0, area=area, geo=geo,
                                outdoors=where.saves_outdoors)
    party = [amiga_later.to_neutral_later(c) for c in source.characters]
    built, _report = amiga_savegame.new_savegame(state, party, "B", glb)
    landed = amiga_savegame.parse(built, amiga_savegame.CURSE)
    script = amiga_savegame._glib_blocks(glb)[dict(_pairs(glb))[area]]
    assert landed.ecl[:len(script)] == script
    assert amiga_savegame.state_from_savegame(landed).area == area


#: A Curse party the game saved in area $10 (Yulash), made by an agent driving
#: the C64 game, so it is a record we watched being written.
YULASH_C64 = "coab-c64/WISH-SPEC-curse-wish23-c64-yulash-sneak-in.D64"


def test_a_c64_party_in_area_sixteen_saves_as_amiga_with_the_script_the_table_names(
        tmp_path):
    """Save As from the C64 specimen: the converted save keeps area $10 and
    stages block 5 of `ECL.GLB`, the block the area table names for it (and
    not block 16, which is area $32's script)."""
    from editor import convert
    from goldbox import dos_port, world_state
    from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
    from tests import gamedata
    from tests.support.amigasavegame import synthetic_disk_one
    from tools.amiga import amigasaves

    root = gamedata.specimen_root()
    path = root / YULASH_C64 if root else None
    if path is None or not path.is_file():
        pytest.skip(f"needs {YULASH_C64}; set $WISH_SPECIMENS")
    image = None
    for _label, data in amigasaves.images():
        try:
            AmigaDisk(data).read_file("/DISKB/ECL.GLB")
        except (AmigaDiskError, ValueError):
            continue
        image = data
        break
    if image is None:
        pytest.skip("needs the player's Amiga Curse disk B")
    disk_two = tmp_path / "disk-two.adf"
    disk_two.write_bytes(image)
    glb = AmigaDisk(image).read_file("/DISKB/ECL.GLB")

    deltas = dos_port.CURSE_OF_THE_AZURE_BONDS
    source = convert.Source.detect(path)
    assert world_state.from_c64(source.save0, source=str(path)).area == 0x10
    disk_one = tmp_path / "disk-one.adf"
    synthetic_disk_one(deltas.key, ("A",)).save(str(disk_one))

    rehearsal = convert.C64ToAmiga(deltas).rehearse(
        source, "A", disk_two, disk_one=disk_one)

    landed = amiga_savegame.parse(rehearsal.savegame, amiga_savegame.CURSE)
    block = amiga_savegame._glib_blocks(glb)[dict(_pairs(glb))[0x10]]
    assert len(block) == 7664
    assert amiga_savegame.state_from_savegame(landed).area == 0x10
    assert landed.ecl[:len(block)] == block
    assert rehearsal.report.losses == []
