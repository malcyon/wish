"""The Amiga Curse and Silver Blades combat side and quickfight reach DOS."""

from __future__ import annotations

import dataclasses

import gamedata
import pytest

from goldbox import (
    amiga_adf,
    amiga_later,
    amiga_port,
    amiga_savegame,
    c64_codec,
    dos_codec,
    dos_port,
)

_TITLES = (
    (dos_port.CURSE_OF_THE_AZURE_BONDS, amiga_port.CURSE_DELTAS),
    (dos_port.SECRET_OF_THE_SILVER_BLADES, amiga_port.SILVER_BLADES_DELTAS),
)


def _tail_offset(deltas) -> int:
    return dos_port.FIELDS_BY_NAME_FOR[deltas.key]["field_10c_10f"].offset


def _control_offset(deltas) -> int:
    f = dos_port.FIELDS_BY_NAME_FOR[deltas.key]["field_83_87"]
    return f.offset + (1 if f.size == 5 else 0)


@pytest.mark.parametrize("dos,amiga", _TITLES, ids=lambda d: d.key)
@pytest.mark.parametrize("side,quick", [(0, 1), (1, 0), (1, 1)])
def test_an_amiga_zombie_companion_keeps_side_and_quickfight_on_dos(
        dos, amiga, side, quick):
    raw = bytearray(dos.record_size)
    tail = _tail_offset(dos)
    raw[tail:tail + 4] = bytes((1, 1, side, quick))
    raw[_control_offset(dos)] = 0xB2
    source = dos_codec.to_neutral(dos_codec.DosCharacter(bytes(raw),
                                                         deltas=dos))
    char, _report = amiga_later.write_later(source, dos.key)
    at = amiga.offset(tail)
    assert tuple(char.raw[at:at + 4]) == (1, 1, side, quick)

    back = amiga_later.to_neutral_later(char)
    assert (back.get("hostile"), back.get("quickfight")) == (
        bool(side), bool(quick))
    record, _itm, _spc, _report = dos_codec.write(back, deltas=dos)
    assert tuple(record[tail:tail + 4]) == (1, 1, side, quick)
    assert record[_control_offset(dos)] == 0xB2


def _amiga_member(dos, status: int, control: int):
    """An Amiga member whose side and quickfight bytes are both 1."""
    raw = bytearray(dos.record_size)
    tail = _tail_offset(dos)
    raw[tail:tail + 4] = bytes((status, 1, 1, 1))
    raw[_control_offset(dos)] = control
    source = dos_codec.to_neutral(dos_codec.DosCharacter(bytes(raw),
                                                         deltas=dos))
    char, _report = amiga_later.write_later(source, dos.key)
    return char


_MEMBERS = [(1, 0xB2), (0, 0)]


@pytest.mark.parametrize("dos,amiga", _TITLES, ids=lambda d: d.key)
@pytest.mark.parametrize("status,control", _MEMBERS)
def test_amiga_save_as_keeps_side_and_quickfight(dos, amiga, status,
                                                 control):
    char = _amiga_member(dos, status, control)
    at = amiga.offset(_tail_offset(dos))
    assert tuple(char.raw[at:at + 4]) == (status, 1, 1, 1)
    again, _report = amiga_later.write_later(
        amiga_later.to_neutral_later(char), dos.key)
    assert tuple(again.raw[at:at + 4]) == (status, 1, 1, 1)


@pytest.mark.parametrize("dos,amiga", _TITLES, ids=lambda d: d.key)
@pytest.mark.parametrize("status,control", _MEMBERS)
def test_amiga_side_and_quickfight_reach_the_c64_combat_byte(
        dos, amiga, status, control):
    # The C64 keeps both in record 0x10C: bit 0 the side, bit 7 quickfight.
    char = _amiga_member(dos, status, control)
    c64, _report = c64_codec.write(amiga_later.to_neutral_later(char))
    assert c64.get("combat_side") == 0x81


def test_the_disposition_names_side_and_quickfight_as_converted():
    for _dos, amiga in _TITLES:
        line = amiga_later.later_field_disposition(amiga)["field_10c_10f"]
        assert "hostile" in line and "quickfight" in line
        assert "not converted" not in line


def _evoker():
    where = gamedata.specimen("wish-plane-303-curse-evoker-add", "amiga")
    disk = amiga_adf.AmigaDisk.open(where / "fetched-save.adf")
    save = amiga_savegame.read_slot(disk, "D")
    (char,) = [c for c in save.characters if c.name == "EVOKER"]
    return char


def _dos_tail(char) -> tuple[int, ...]:
    dos = dos_port.CURSE_OF_THE_AZURE_BONDS
    record, _itm, _spc, _report = dos_codec.write(
        amiga_later.to_neutral_later(char), deltas=dos)
    tail = _tail_offset(dos)
    return (record[_control_offset(dos)], *record[tail:tail + 4])


def test_the_game_written_evoker_reaches_dos_with_his_own_four_tail_bytes():
    # Amiga Curse's ADD > Pool left his quickfight at 0, so he gets a command
    # bar on the Amiga and must get one on DOS.
    assert _dos_tail(_evoker()) == (0xB2, 1, 1, 0, 0)


def test_evoker_after_quick_in_an_amiga_fight_stays_game_run_on_dos():
    # QUICK sets $19D (`/Curse 0x3874`) and SPACE never clears it for him.
    char = _evoker()
    at = amiga_port.CURSE_DELTAS.offset(
        _tail_offset(dos_port.CURSE_OF_THE_AZURE_BONDS)) + 3
    raw = bytearray(char.raw)
    raw[at] = 1
    assert _dos_tail(dataclasses.replace(char, raw=bytes(raw))) == (
        0xB2, 1, 1, 0, 1)
