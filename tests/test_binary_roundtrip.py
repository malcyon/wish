"""Every binary reader, against its own bytes and against rubbish.

The read paths were well covered and the write paths were not covered at all:
nothing asserted that a parser hands back what it was given, and nothing fed a
loader a truncated file to see what it did. Both matter for a format we are
still reverse engineering, because a silent misparse looks exactly like a
discovery.
"""

import pathlib

import pytest
from gamedata import disk_dir, game_file

from por.d64 import D64, load_payload, split_load_address
from por.geo import GEO_SIZE, Geo, GeoError, load_geo_files
from por.icons import CELLS, ICON_SIZE, Icon, icon_pixels, load_icon_charset
from por.items import ITEM_SIZE, Item, load_item_names, load_item_templates
from por.record import RECORD_SIZE, CharacterRecord
from por.spells import spellbook_bytes, spells_known

# Wherever the player keeps them, not wherever one machine did.
DISKS = str(disk_dir() or "no-disks-here")
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/POOL1.D64").exists(),
                                reason="needs the game disks")


# --- round trips -------------------------------------------------------------

@game_disks
def test_every_geo_file_round_trips():
    """29 files in, 29 identical files out."""
    seen = 0
    for disk in list(range(1, 9)) + ["BOOT"]:
        for name, geo in load_geo_files(f"{DISKS}/POOL{disk}.D64").items():
            raw = geo.to_bytes()
            assert len(raw) == GEO_SIZE
            assert Geo(raw).to_bytes() == raw, name
            seen += 1
    assert seen == 29


def test_a_geo_survives_the_prg_wrapper():
    payload = game_file("GEO04")
    assert Geo.from_bytes(b"\x00\x04" + payload).to_bytes() == payload


@game_disks
def test_every_icon_round_trips_and_renders():
    charset = load_icon_charset(f"{DISKS}/POOL1.D64")
    from por.savegame import SaveGame0
    disk = D64.open(f"{DISKS}/PORSAVE11.D64")
    save = SaveGame0.from_prg(disk.read_file(b"SAVEDGAME0"))
    from por.icons import icon_for_slot
    for slot in save.characters:
        icon = icon_for_slot(save.to_bytes(), slot.index)
        assert len(icon.raw) == ICON_SIZE
        assert Icon(icon.raw).raw == icon.raw
        pixels = icon_pixels(icon, charset)
        assert len(pixels) == 48 and all(len(row) == 12 for row in pixels)
        assert all(0 <= c <= 15 for row in pixels for c in row)


@game_disks
def test_every_item_template_round_trips():
    """163 records, each 16 bytes in and 16 identical bytes out."""
    names = load_item_names(f"{DISKS}/POOL1.D64")
    templates = load_item_templates(f"{DISKS}/POOL1.D64")
    assert len(templates) > 150
    for name, raw in templates.items():
        assert len(raw) == ITEM_SIZE, name
        assert Item(raw, names).raw == raw, name


def test_a_spellbook_round_trips_for_every_legal_id():
    from por.spells import LAST_SPELLBOOK_SPELL, SPELLBOOK_OFFSET
    for ids in ([], [1], [1, 55], list(range(1, LAST_SPELLBOOK_SPELL + 1))):
        book = spellbook_bytes(ids)
        record = bytes(SPELLBOOK_OFFSET) + book + bytes(400)
        assert spells_known(record) == sorted(ids)


@game_disks
def test_a_character_record_round_trips_through_its_prg():
    disk = D64.open(f"{DISKS}/PORSAVE10.D64")
    seen = 0
    for entry in disk.directory():
        if not entry.is_prg or entry.is_empty:
            continue
        raw = disk.read_file(entry)
        record = CharacterRecord.from_prg(raw)
        assert record.to_prg(split_load_address(raw)[0]) == raw
        seen += 1
    assert seen >= 8


# --- rubbish in --------------------------------------------------------------

@pytest.mark.parametrize("data", [b"", b"\x00", bytes(1023), bytes(1025)])
def test_a_geo_of_the_wrong_size_is_refused(data):
    with pytest.raises(GeoError):
        Geo(data)


@pytest.mark.parametrize("data", [b"", b"\x01"])
def test_a_prg_without_a_load_address_is_refused(data):
    with pytest.raises(ValueError, match="load address"):
        split_load_address(data)


def test_a_truncated_record_is_refused():
    with pytest.raises(ValueError):
        CharacterRecord(bytes(RECORD_SIZE - 1))


@game_disks
def test_a_missing_file_names_itself():
    from por.d64 import FileNotFoundInImage
    with pytest.raises(FileNotFoundInImage):
        load_payload(f"{DISKS}/POOL1.D64", b"NOSUCHFILE")


def test_an_icon_of_the_wrong_size_still_slices_predictably():
    """Icon does not validate its length, so say what short input does rather
    than discover it later: shape and colours simply come back short."""
    icon = Icon(bytes(10))
    assert len(icon.shape) + len(icon.colours) == 10
    assert len(icon.shape) <= CELLS
