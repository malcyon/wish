"""`goldbox.amiga_savegame.read_por_characters`, the one loop over an Amiga
Pool of Radiance slot's character files that `read_por_slot` and the editor's
`Party` both use.  Built from the writers, so it needs no game data."""

from __future__ import annotations

import pytest
from support.neutralrecords import _filled

from goldbox import amiga_por, amiga_savegame, c64_codec, c64_port
from goldbox.neutral import Confidence


def _disk(names, slot="A"):
    pool = c64_port.by_key("pool-of-radiance")
    characters = []
    for name in names:
        char = _filled(pool)
        char.set("name", name, "made up", Confidence.CONFIRMED,
                 c64_codec.Provenance.RESHAPED)
        characters.append(char)
    savgam = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    at = amiga_savegame.POOL_OF_RADIANCE.party_at
    savgam[at:at + 8] = b"CHRDATA1"
    return amiga_savegame.make_por_save_disk(slot, characters, bytes(savgam))


def test_each_character_file_is_read_in_order_as_the_amiga_record():
    found = amiga_savegame.read_por_characters(_disk(["ALPHA", "BETA", "GAMMA"]), "a")
    assert [type(c) for c in found] == [amiga_por.AmigaPorCharacter] * 3
    assert [amiga_por.to_dos_character(c).name for c in found] == [
        "ALPHA", "BETA", "GAMMA"]


def test_read_por_slot_returns_the_same_party_converted_to_dos_records():
    disk = _disk(["ALPHA", "BETA"])
    party, _save = amiga_savegame.read_por_slot(disk, "A")
    found = amiga_savegame.read_por_characters(disk, "A")
    assert [c.name for c in party] == [
        amiga_por.to_dos_character(c).name for c in found] == ["ALPHA", "BETA"]


def test_the_reading_stops_at_the_first_missing_character_file():
    disk = _disk(["ALPHA", "BETA", "GAMMA"])
    drawer = amiga_savegame.por_save_drawer(disk)
    disk.remove_file(amiga_savegame.por_save_path(
        amiga_por.por_filename("A", 2, ".sav"), drawer))
    found = amiga_savegame.read_por_characters(disk, "A")
    assert len(found) == 1


def test_a_slot_with_no_files_is_an_empty_list_and_a_bad_letter_is_refused():
    disk = _disk(["ALPHA"])
    assert amiga_savegame.read_por_characters(disk, "B") == []
    with pytest.raises(amiga_savegame.AmigaSaveError):
        amiga_savegame.read_por_characters(disk, "Z")
