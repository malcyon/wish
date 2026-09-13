"""The later-title Amiga saved-game reader, writer and fresh disk."""

from __future__ import annotations

import pathlib

import pytest
from gamedata import specimen_root

from goldbox import amiga_later, amiga_savegame, dos_savegame
from goldbox.amiga_adf import AmigaDisk
from tools import amigasaves, specimens


def _fake_record(shape, name: str) -> bytes:
    raw = bytearray(shape.deltas.record_size)
    raw[:len(name)] = name.encode("ascii")
    for i in range(6):
        raw[0x10 + 2 * i] = raw[0x11 + 2 * i] = 12
    return bytes(raw)


def _synthetic(shape, names=("ALPHA", "BETA")) -> bytes:
    out = bytearray((2 if shape is amiga_savegame.CURSE else 1,))
    vm = bytearray(amiga_savegame.VM_BYTES)
    for address, value in ((dos_savegame.DISK, out[0]),
                           (dos_savegame.PARTY_SIZE, len(names)),
                           (dos_savegame.SCRIPT, 1)):
        at = shape.word_offset(address) - 1
        vm[at:at + 2] = value.to_bytes(2, "big")
    out += vm
    out += bytes(shape.ecl_bytes)
    out += (3).to_bytes(shape.x_bytes, "big")
    out += (14).to_bytes(shape.x_bytes, "big")
    out += bytes((2, 0, 0, 0, 4, 2))
    for block, slot in ((1, 1), (2, 2), (0xFFFF, 0xFFFF)):
        out += block.to_bytes(2, "big") + slot.to_bytes(2, "big")
    out += len(names).to_bytes(2, "big")
    for name in names:
        out += _fake_record(shape, name)
    return bytes(out)


@pytest.mark.parametrize("shape", amiga_savegame.SHAPES,
                         ids=lambda shape: shape.key)
def test_each_measured_header_parses_without_game_data(shape):
    save = amiga_savegame.parse(_synthetic(shape), shape)
    assert (save.x, save.y, save.facing) == (3, 14, 2)
    assert save.wallset == ((1, 1), (2, 2), (0xFFFF, 0xFFFF))
    assert [char.name for char in save.characters] == ["ALPHA", "BETA"]


def test_the_two_first_record_offsets_are_the_engines_own():
    assert amiga_savegame.CURSE.party_at == 0x3219
    assert amiga_savegame.SILVER_BLADES.party_at == 0x1417


def test_a_fresh_disk_has_only_the_save_drawer_and_slot():
    data = _synthetic(amiga_savegame.CURSE, ("ALPHA",))
    disk = amiga_savegame.make_save_disk(amiga_savegame.CURSE, "D", data)
    assert [(path, len(disk.read_file(path))) for path, _ in disk.walk()] == [
        ("/SAVE/savgamD.dat", len(data))]
    assert amiga_savegame.slots_present(disk, amiga_savegame.CURSE) == ["D"]
    assert amiga_savegame.read_slot(disk, "D").characters[0].name == "ALPHA"
    assert disk.verify() == []


def _verified_later_save(drawer: str, specimen: str, filename: str) -> pathlib.Path:
    root = specimen_root()
    if root is None:
        pytest.skip("needs the engine-written Amiga specimen tree")
    where = root / drawer / specimen
    provenance = where / "provenance.toml"
    if not provenance.is_file():
        pytest.skip(f"needs {where}")
    recorded = specimens.read_provenance(provenance).get("sha256", {})
    path = where / filename
    if filename not in recorded or specimens.sha256_file(path) != recorded[filename]:
        pytest.fail(f"{path} no longer matches its provenance")
    return path


def _curse_ecl() -> bytes:
    for _label, image in amigasaves.images():
        try:
            disk = AmigaDisk(image)
            return disk.read_file("/DISKB/ECL.GLB")
        except Exception:
            continue
    pytest.skip("needs the player's Amiga Curse disk B")


@pytest.mark.parametrize("shape,drawer,specimen,filename", [
    (amiga_savegame.CURSE, "coab-amiga",
     "WISH-SPEC-coab-amiga-resave", "savgamE.dat"),
    (amiga_savegame.SILVER_BLADES, "ssb-amiga",
     "WISH-SPEC-ssbwalk", "savgamF.sav"),
])
def test_an_engine_written_save_round_trips_square_clock_and_order(
        shape, drawer, specimen, filename):
    path = _verified_later_save(drawer, specimen, filename)
    source = amiga_savegame.parse(path.read_bytes(), shape, str(path))
    state = amiga_savegame.state_from_savegame(source)
    neutral_party = [amiga_later.to_neutral_later(char)
                     for char in source.characters]
    built, report = amiga_savegame.new_savegame(
        state, neutral_party, "B",
        _curse_ecl() if shape is amiga_savegame.CURSE else None)
    landed = amiga_savegame.parse(built, shape)
    landed_state = amiga_savegame.state_from_savegame(landed)

    assert report.unwritten == []
    assert report.total == len(built)
    assert (landed.x, landed.y, landed.facing) == (
        source.x, source.y, source.facing)
    assert landed_state.clock == state.clock
    assert [char.name for char in landed.characters] == [
        char.name for char in source.characters]
    assert landed_state.wallset == state.wallset


def test_the_library_and_the_tool_state_the_same_container():
    """`goldbox/amiga_savegame.py` and `tools/amigasavegame.py` each declare
    the container's byte-level numbers, and two independent statements of the
    same offsets drift silently.

    The plan recorded on #512 is to move the map into the library so the tool
    imports it rather than restating it -- the tool's own `SaveShape` is the
    richer of the two, carrying Pool of Radiance, the square struct field by
    field and the note beside each field, so the move is a real piece of work
    rather than a rename.  Until somebody does it, this is what makes the
    drift loud: every number both modules hold has to agree.
    """
    from tools import amigasavegame as tool

    assert amiga_savegame.VM_BYTES == tool.VM_BYTES
    assert amiga_savegame.VM_BASE == tool.VM_BASE
    assert amiga_savegame.ECL_BYTES == tool.ECL_BYTES
    for mine, theirs in ((amiga_savegame.CURSE, tool.CURSE),
                         (amiga_savegame.SILVER_BLADES, tool.SILVER_BLADES)):
        assert mine.title == theirs.title
        assert mine.ecl_bytes == theirs.ecl_bytes
        assert mine.square_bytes == theirs.square_bytes
        assert mine.square_at == theirs.square_at
        assert mine.first_mode_at == theirs.first_mode_at
        assert mine.mode_at == theirs.mode_at
        assert mine.wallset_at == theirs.wallset_at
        assert mine.count_at == theirs.count_at
        assert mine.party_at == theirs.party_at
        assert mine.x_bytes == theirs.square[0].size
        assert mine.deltas is theirs.record_shape
        # The library hardcodes the one-byte container-number header that the
        # tool carries as `header_bytes`; a title that ever opened without it
        # would make every offset above disagree, so pin the assumption too.
        assert theirs.header_bytes == 1
        assert theirs.wallset_table and theirs.count_bytes == 2
        assert mine.word_offset(tool.VM_BASE) == theirs.vm_offset(tool.VM_BASE)
