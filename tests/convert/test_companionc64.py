"""A companion keeps his combat figure through the C64.

A DOS or Amiga companion converted to the C64 gets his `MON` file's story
byte at `0x0E5`, the default icon and a mark beside his picture; a companion
who joined on the C64 has no stored picture and gets the one his DOS and
Amiga join writes, found by his name.  The tables come from the player's own
Curse and Silver Blades disks, and the tests skip without them.
"""

from __future__ import annotations

import functools

import gamedata
import pytest
from support import silverblades

from goldbox import amiga_later, c64_codec, dos_codec, dos_port
from goldbox.companions import (
    CURSE_KEY,
    MON_SIZE,
    SILVER_BLADES_KEY,
    Companions,
)
from goldbox.d64 import split_load_address
from goldbox.record import CharacterRecord
from tests.convert import test_companionpicture as picture_tests

CURSE = dos_port.CURSE_OF_THE_AZURE_BONDS
SILVER_BLADES = dos_port.SECRET_OF_THE_SILVER_BLADES
DEFAULTS = {CURSE_KEY: CURSE, SILVER_BLADES_KEY: SILVER_BLADES}
#: A 36-byte stand-in for the icon the caller composed.
COMPOSED = bytes(range(0xA0, 0xA0 + 36))

#: Companion name, `MON` id and the story byte his own file holds, per title.
JOINED = {
    CURSE_KEY: [("ALIAS", 0x16, 0x16), ("AKABAR BEL AKAS", 0x3B, 0x3B),
                ("RUSTLE", 0x55, 0xFF)],
    SILVER_BLADES_KEY: [("SIEGLINDA", 0x32, 0x4D), ("VALA", 0x4D, 0x4D),
                        ("SIR DERIC", 0x4E, 0x4E)],
}
CASES = [(key, *case) for key, cases in JOINED.items() for case in cases]
IDS = [f"{key.split('-')[0]}-{name.lower().replace(' ', '-')}"
       for key, name, *_ in CASES]


@functools.lru_cache(maxsize=None)
def _table(key: str) -> Companions:
    disks = (gamedata.curse_disks() if key == CURSE_KEY
             else silverblades.ssb_disks())
    return Companions.load(key, disks)


def _record(key: str, name: str, picture: int, control: int = 0xB2) -> bytes:
    return picture_tests._dos_record(DEFAULTS[key], control, picture,
                                     name.encode())


def _neutral(key: str, name: str, picture: int, control: int = 0xB2):
    return dos_codec.to_neutral(
        dos_codec.DosCharacter(_record(key, name, picture, control)))


def _join(key: str, mon_id: int) -> CharacterRecord:
    """The record `ADDNPC` leaves: the `MON` file's 480 bytes, its name
    included, then the control byte the join stores."""
    table = _table(key)
    disks = (gamedata.curse_disks() if key == CURSE_KEY
             else silverblades.ssb_disks())
    for disk in disks:
        if disk.find(f"MON{mon_id:02X}".encode()):
            payload = split_load_address(
                disk.read_file(f"MON{mon_id:02X}".encode()))[1]
            assert len(payload) == MON_SIZE
            rec = CharacterRecord(payload + bytes(CharacterRecord.SIZE - MON_SIZE))
            rec.set("flags_0b8", 0xB2)
            assert table.match(rec.get("name")) == mon_id
            return rec
    pytest.fail(f"no side carries MON{mon_id:02X}")


# -- into the C64 --------------------------------------------------------------

@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_converted_companion_gets_his_story_byte_and_a_marked_picture(
        key, name, mon_id, story):
    rec, _ = c64_codec.write(_neutral(key, name, mon_id), icon=COMPOSED,
                             companions=_table(key))
    assert rec.get("story_picture") == story
    assert rec.get_raw("identity_pair") == bytes([mon_id, 0x01])


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_converted_companion_is_drawn_with_the_default_icon(
        key, name, mon_id, story):
    table = _table(key)
    rec, _ = dos_codec.neutral_to_c64_record(
        _neutral(key, name, mon_id), icon=COMPOSED, companions=table)
    assert rec.get_raw("region_220") == table.default_icon
    assert table.default_icon != COMPOSED


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_dos_record_converted_whole_gets_the_default_icon(
        key, name, mon_id, story):
    table = _table(key)
    rec, _ = dos_codec.to_c64_record(
        dos_codec.DosCharacter(_record(key, name, mon_id)), icon=COMPOSED,
        companions=table)
    assert rec.get("story_picture") == story
    assert rec.get_raw("region_220") == table.default_icon


@pytest.mark.parametrize("key", [CURSE_KEY, SILVER_BLADES_KEY])
def test_a_companion_with_no_match_is_written_as_before(key):
    """No script joins a worg and BRUTUS names no file: the composed icon
    stays, no story byte is written and the picture is unmarked."""
    table = _table(key)
    neutral = _neutral(key, "BRUTUS", 0x57)
    rec, _ = dos_codec.neutral_to_c64_record(neutral, icon=COMPOSED,
                                             companions=table)
    assert rec.get_raw("region_220") == COMPOSED
    assert rec.get("story_picture") == 0
    assert rec.get_raw("identity_pair") == bytes([0x57, 0])


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_player_or_another_picture_under_a_companions_name_is_unchanged(
        key, name, mon_id, story):
    table = _table(key)
    for neutral in (_neutral(key, name, mon_id, control=0x00),
                    _neutral(key, name, mon_id, control=0xB3),
                    _neutral(key, name, 0x57)):
        rec, _ = dos_codec.neutral_to_c64_record(
            neutral, icon=COMPOSED, companions=table)
        assert rec.get_raw("region_220") == COMPOSED
        assert rec.get("story_picture") == 0


@pytest.mark.parametrize("key, name, mon_id, story", CASES[:1] + CASES[3:4],
                         ids=IDS[:1] + IDS[3:4])
def test_without_a_table_the_picture_is_kept_and_no_story_byte_written(
        key, name, mon_id, story):
    rec, _ = c64_codec.write(_neutral(key, name, mon_id), icon=COMPOSED)
    assert rec.get("story_picture") == 0
    assert rec.get_raw("identity_pair")[0] == mon_id


# -- out of the C64 ---------------------------------------------------------------

@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_companion_who_joined_on_the_c64_gets_his_mon_id_as_his_picture(
        key, name, mon_id, story):
    table = _table(key)
    rec = _join(key, mon_id)
    char = c64_codec.read(rec, game=key, companions=table)
    assert char.get("unnamed_0ab") == table.picture_for(mon_id) == mon_id
    if "treasure_share" in char.fields:
        # A bare `MON` payload holds `$FF` here, as DOS's own `MON` record
        # does; the writer stops on bit 2, and the picture is what this test
        # is about.
        char.set("treasure_share", 0, "test")
    back, _, _, _ = dos_codec.write(char, deltas=DEFAULTS[key])
    f = dos_port.FIELDS_BY_NAME_FOR[key]["unnamed_0ab"]
    assert back[f.offset] == mon_id
    assert dos_codec.holds_companion_picture(back, DEFAULTS[key])


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_joined_companion_read_without_a_table_has_no_picture(
        key, name, mon_id, story):
    assert c64_codec.read(_join(key, mon_id),
                          game=key).get("unnamed_0ab") is None


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_stored_picture_is_read_before_the_name(key, name, mon_id, story):
    rec = _join(key, mon_id)
    rec.set_raw("identity_pair", bytes([0x57, 0x01]))
    char = c64_codec.read(rec, game=key, companions=_table(key))
    assert char.get("unnamed_0ab") == 0x57


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_story_byte_is_never_read_as_a_picture(key, name, mon_id, story):
    """VALA's `MON` id is SIEGLINDA's story byte: SIEGLINDA is still `$32`."""
    table = _table(key)
    rec = _join(key, mon_id)
    assert rec.get("story_picture") == story
    assert c64_codec.read(rec, game=key, companions=table).get(
        "unnamed_0ab") == mon_id


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_a_player_under_a_companions_name_gets_no_picture(
        key, name, mon_id, story):
    rec = _join(key, mon_id)
    rec.set("flags_0b8", 0x00)
    rec.set_raw("identity_pair", bytes(2))
    assert c64_codec.read(rec, game=key, companions=_table(key)).get(
        "unnamed_0ab") is None


# -- round trips -------------------------------------------------------------------

@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_dos_to_the_c64_and_back_keeps_his_picture_and_story_byte(
        key, name, mon_id, story):
    table = _table(key)
    deltas = DEFAULTS[key]
    rec, _ = dos_codec.to_c64_record(
        dos_codec.DosCharacter(_record(key, name, mon_id)), icon=COMPOSED,
        companions=table)
    assert rec.get("story_picture") == story
    back, _, _, _ = dos_codec.write(
        c64_codec.read(rec, game=key, companions=table), deltas=deltas)
    f = dos_port.FIELDS_BY_NAME_FOR[key]["unnamed_0ab"]
    assert back[f.offset] == mon_id


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_amiga_to_the_c64_and_back_keeps_his_picture(key, name, mon_id, story):
    """The Amiga leg uses EVOKER's record renamed into a joinable companion."""
    if key != CURSE_KEY:
        pytest.skip("the only Amiga specimen with a companion is Curse's")
    table = _table(key)
    char = picture_tests._with_picture(picture_tests._evoker(), mon_id)
    neutral = amiga_later.to_neutral_later(char)
    neutral.set("name", name, "renamed", c64_codec.Confidence.CONFIRMED)
    rec, _ = c64_codec.write(neutral, icon=COMPOSED, companions=table)
    assert rec.get("story_picture") == story
    back, _ = amiga_later.write_later(
        c64_codec.read(rec, game=neutral.game, companions=table), key)
    assert back.raw[picture_tests.AMIGA_PICTURE] == mon_id


@pytest.mark.parametrize("key, name, mon_id, story", CASES, ids=IDS)
def test_the_c64s_own_companion_goes_to_the_c64_with_nothing_changed(
        key, name, mon_id, story):
    """A joined companion read with the table and written back is the
    record the join left, save for the mark beside his new picture."""
    table = _table(key)
    rec = _join(key, mon_id)
    char = c64_codec.read(rec, game=key, companions=table)
    again, _ = c64_codec.write(char, icon=table.default_icon,
                               companions=table)
    assert again.get("story_picture") == story
    assert again.get("name") == rec.get("name")


# -- the table is used, and a damaged side costs only the table ---------------

@pytest.mark.parametrize("key, name, mon_id, story", CASES[:1] + CASES[3:4],
                         ids=IDS[:1] + IDS[3:4])
def test_the_writer_uses_the_table_it_is_given(key, name, mon_id, story,
                                               monkeypatch):
    table = _table(key)
    neutral = _neutral(key, name, mon_id)
    with_table, _ = dos_codec.neutral_to_c64_record(
        neutral, icon=COMPOSED, companions=table)
    monkeypatch.setattr(c64_codec, "companion_mon", lambda *_: None)
    ignored, _ = dos_codec.neutral_to_c64_record(
        neutral, icon=COMPOSED, companions=table)
    assert with_table.get("story_picture") == story
    assert (ignored.get("story_picture"), ignored.get_raw("region_220"),
            ignored.get_raw("identity_pair")) == (0, COMPOSED,
                                                  bytes([mon_id, 0]))


@pytest.mark.parametrize("key, name, mon_id, story", CASES[:1] + CASES[3:4],
                         ids=IDS[:1] + IDS[3:4])
def test_the_reader_uses_the_table_it_is_given(key, name, mon_id, story,
                                               monkeypatch):
    table = _table(key)
    rec = _join(key, mon_id)
    monkeypatch.setattr(type(table), "match", lambda *_: None)
    ignored = c64_codec.read(rec, game=key, companions=table)
    assert ignored.get("unnamed_0ab") is None


def _damaged_folder(tmp_path, key: str):
    """The title's game sides copied into `tmp_path`, with the first `MON`
    file's sector chain made to loop on itself in the first side holding one.
    The image still opens; reading that file raises."""
    from goldbox.d64 import sector_offset
    disks = (gamedata.curse_disks() if key == CURSE_KEY
             else silverblades.ssb_disks())
    damaged = False
    for number, disk in enumerate(disks):
        raw = bytearray(disk.to_bytes())
        if not damaged:
            for entry in disk.iter_directory():
                if (entry.is_prg and entry.name.startswith(b"MON")
                        and len(entry.name.rstrip(b"\xa0 ")) == 5):
                    at = sector_offset(entry.first_track, entry.first_sector)
                    raw[at:at + 2] = bytes([entry.first_track,
                                            entry.first_sector])
                    damaged = True
                    break
        prefix = "CURSE" if key == CURSE_KEY else "SILVER"
        (tmp_path / f"{prefix}{number}.D64").write_bytes(bytes(raw))
    assert damaged
    return tmp_path


@pytest.mark.parametrize("key", [CURSE_KEY, SILVER_BLADES_KEY])
def test_a_damaged_side_costs_only_the_companion_table(key, tmp_path):
    from editor import dosimport, saveplan
    from goldbox import c64_port
    folder = _damaged_folder(tmp_path, key)
    game = c64_port.by_key(key)
    assert dosimport.load_companions(
        key, sorted(folder.glob(game.disk_glob))) is None
    files = saveplan._game_files_from_folder(folder, game)
    assert files is not None
    assert files.icon is not None and files.animate
    assert files.companions is None
