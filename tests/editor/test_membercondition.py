"""A party opened in the editor records each member's condition and roster tail.

The condition is read from the port's own status (the C64 roster block, the
DOS or Amiga character's status and active flag, a roster disk's own record),
because the sheet's byte 0x100 cannot hold every DOS state. A byte the port
does not store leaves the member's condition None.
"""
from __future__ import annotations

import pytest
from gamedata import _disk_with, synthetic_save
from support.neutralrecords import _filled

from editor.roster import Party
from goldbox import c64_codec, c64_port, dos_codec, dos_port, dos_savegame
from goldbox.layout import Confidence
from goldbox.record import CharacterRecord
from goldbox.savegame import ROSTER_IN_USE, ROSTER_TAIL_AT, ROSTER_TAIL_END

POOL = dos_port.POOL_OF_RADIANCE
TAIL = bytes.fromhex("300100010008000400")


def _roster_disk(tmp_path, **field_values):
    record = CharacterRecord.blank()
    record.set("name", "ZERO")
    for field, value in field_values.items():
        record.set(field, value)
    out = tmp_path / "ROSTER.D64"
    out.write_bytes(_disk_with([(b"ZERO", record.to_prg())]))
    return out


@pytest.mark.parametrize("byte, expected", [
    (0x01, ("okay", True)),
    (0x83, ("dead", False)),
    (0x84, ("dying", False)),
    (0x81, ("okay", False)),
])
def test_a_roster_disk_character_reads_its_own_condition(
        tmp_path, byte, expected):
    party = Party(str(_roster_disk(tmp_path, roster_in_use=byte)))
    assert party.members[0].condition == expected


def test_a_roster_disk_character_keeps_its_tail(tmp_path):
    party = Party(str(_roster_disk(tmp_path, roster_tail=TAIL)))
    assert party.members[0].roster_tail == TAIL


def _party_with_block(tmp_path, monkeypatch, byte):
    """A synthetic save whose slot 0 roster block holds `byte` and TAIL."""
    import editor.roster as roster
    real = roster.load_save

    def patched(disk, game):
        game, sg0, sg1 = real(disk, game)
        block = sg1.roster(0)
        block._set(ROSTER_IN_USE, byte)
        for i, value in enumerate(TAIL):
            block._set(ROSTER_TAIL_AT + i, value)
        return game, sg0, sg1

    monkeypatch.setattr(roster, "load_save", patched)
    return Party(str(synthetic_save(tmp_path)))


def test_a_c64_save_reads_the_condition_and_tail_from_its_roster_block(
        tmp_path, monkeypatch):
    party = _party_with_block(tmp_path, monkeypatch, 0x83)
    member = next(m for m in party.members if m.index == 0)
    assert member.condition == ("dead", False)
    assert member.roster_tail == TAIL
    assert ROSTER_TAIL_END - ROSTER_TAIL_AT == len(TAIL)


def test_a_c64_save_zombie_byte_reads_animated_in_pool(tmp_path, monkeypatch):
    party = _party_with_block(tmp_path, monkeypatch, 0x03)
    member = next(m for m in party.members if m.index == 0)
    assert member.condition == ("animated", True)


def test_a_c64_save_with_no_roster_block_leaves_the_condition_unread(
        tmp_path, monkeypatch):
    import editor.roster as roster
    real = roster.load_save
    monkeypatch.setattr(roster, "load_save",
                        lambda disk, game: (lambda g, s0, s1: (g, s0, None))(
                            *real(disk, game)))
    party = Party(str(synthetic_save(tmp_path)))
    assert party.members
    assert all(m.condition is None and m.roster_tail is None
               for m in party.members)


def _dos_folder(tmp_path, **neutral_fields):
    game = c64_port.by_key(POOL.key)
    char = _filled(game)
    char.set("name", "HERO1", "made up", Confidence.CONFIRMED,
             c64_codec.Provenance.RESHAPED)
    for field, value in neutral_fields.items():
        char.set(field, value, "made up")
    record, itm, spc, _report = dos_codec.write(char, deltas=POOL)
    stem = tmp_path / "CHRDATA1"
    stem.with_suffix(".SAV").write_bytes(record)
    stem.with_suffix(POOL.item_suffix).write_bytes(itm)
    stem.with_suffix(POOL.effect_suffix).write_bytes(spc)
    container = dos_savegame.container_for(POOL.key)
    (tmp_path / f"SAVGAMA{container.suffix}").write_bytes(
        bytes(container.size))
    return tmp_path


def test_a_dos_member_reads_the_status_the_port_holds(tmp_path):
    party = Party(str(_dos_folder(tmp_path, status="dying", active=True)))
    assert party.members[0].condition == ("dying", True)


def test_a_dos_member_out_of_play_reads_the_active_flag(tmp_path):
    party = Party(str(_dos_folder(tmp_path, status="okay", active=False)))
    assert party.members[0].condition == ("okay", False)
    assert party.members[0].roster_tail is not None


def test_an_amiga_member_reads_the_status_the_port_holds(tmp_path):
    from goldbox import amiga_savegame
    (tmp_path / "d").mkdir()
    neutral = dos_codec.to_neutral(dos_codec.read_character(
        _dos_folder(tmp_path / "d", status="dying", active=False)
        / "CHRDATA1.SAV"))
    savgam = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    at = amiga_savegame.POOL_OF_RADIANCE.party_at
    savgam[at:at + 8] = b"CHRDATA1"
    disk = amiga_savegame.make_por_save_disk("A", [neutral], bytes(savgam))
    path = tmp_path / "pool.adf"
    disk.save(str(path))
    party = Party(str(path))
    assert party.members[0].condition == ("dying", False)
