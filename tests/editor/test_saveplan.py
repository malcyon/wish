"""The snapshot a conversion reads the open party out of.

Everything here is built from the format rather than copied off a disk, so it
runs with no game data at all: a DOS Secret of the Silver Blades folder
written by `goldbox.dos_codec.write`, an Amiga Curse `.adf` from
`tests/support/amigasavegame.py`, and `tests/gamedata.py`'s synthetic C64
save. The DOS -> Amiga direction is the one cross-platform conversion that
needs no file off the player's own disks -- Silver Blades stages no area
script -- which is what lets the proof test run the whole way through.
"""
from __future__ import annotations

import pathlib

import pytest
from gamedata import synthetic_save

from editor import convert, saveplan
from editor.roster import Party
from goldbox import (
    amiga_savegame,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    dos_savegame,
    rewrite,
)
from goldbox.amiga_adf import AmigaDisk
from goldbox.icons import ICON_SIZE, Icon
from goldbox.layout import Confidence
from goldbox.savegame import SaveGame0

SILVER_BLADES = dos_port.SECRET_OF_THE_SILVER_BLADES
CURSE_KEY = "curse-of-the-azure-bonds"


# ---------------------------------------------------------------------------
# Saves built from the format
# ---------------------------------------------------------------------------

def dos_folder(tmp_path, deltas=SILVER_BLADES, slot="A", numbers=(1, 2)):
    """A DOS save folder a conversion can actually read.

    `tests/editor/test_editor.py`'s own helper writes an empty `SAVGAM` file,
    which is enough to open a party and not enough to convert one: every
    DOS-source direction reads the place and the clock out of that container.
    This one writes it at the title's own size.
    """
    from support.neutralrecords import _filled

    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    game = c64_port.by_key(deltas.key)
    for n in numbers:
        char = _filled(game)
        char.set("name", f"HERO{n}", "made up", Confidence.CONFIRMED,
                 c64_codec.Provenance.RESHAPED)
        record, itm, spc, _report = dos_codec.write(char, deltas=deltas)
        (tmp_path / f"CHRDAT{slot}{n}.SAV").write_bytes(record)
        (tmp_path / f"CHRDAT{slot}{n}{deltas.item_suffix}").write_bytes(itm)
        (tmp_path / f"CHRDAT{slot}{n}{deltas.effect_suffix}").write_bytes(spc)
    container = dos_savegame.container_for(deltas.key)
    (tmp_path / f"SAVGAM{slot}{container.suffix}").write_bytes(
        bytes(container.size))
    return tmp_path


def amiga_disk(tmp_path, name="curse.adf"):
    """An Amiga Curse save disk, built not copied."""
    from support.amigasavegame import synthetic_curse

    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    path = tmp_path / name
    disk.save(str(path))
    return path


def amiga_two_slot_disk(tmp_path, name="two.adf"):
    """An Amiga Curse save disk holding slots A and B."""
    from support.amigasavegame import synthetic_curse

    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    disk.write_file(amiga_savegame.slot_path(amiga_savegame.CURSE, "B"),
                    synthetic_curse(("OMEGA",)))
    path = tmp_path / name
    disk.save(str(path))
    return path


def amiga_por_disk(tmp_path, name="por.adf"):
    """An Amiga Pool of Radiance save disk with one character in slot A."""
    from support.neutralrecords import _filled

    game = c64_port.by_key("pool-of-radiance")
    char = _filled(game)
    char.set("name", "ALPHA", "made up", Confidence.CONFIRMED,
             c64_codec.Provenance.RESHAPED)
    savgam = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    at = amiga_savegame.POOL_OF_RADIANCE.party_at
    savgam[at:at + 8] = b"CHRDATA1"
    disk = amiga_savegame.make_por_save_disk("A", [char], bytes(savgam))
    path = tmp_path / name
    disk.save(str(path))
    return path


def files_under(folder):
    return {path.name: path.read_bytes()
            for path in pathlib.Path(folder).iterdir() if path.is_file()}


def dos_to_amiga():
    return next(d for d in convert.DIRECTIONS
                if isinstance(d, convert.DosToAmiga)
                and d.source_key == SILVER_BLADES.key)


# ---------------------------------------------------------------------------
# The regression: an unsaved edit has to cross into a conversion
# ---------------------------------------------------------------------------

def test_an_unsaved_dos_edit_converts_and_leaves_the_save_folder_alone(
        tmp_path):
    """Edit a DOS character and one of his items, convert without saving, and
    both edits are in the Amiga disk the conversion wrote.

    This is the stage-1 regression of `#511 (Open a DOS save folder and an
    Amiga save disk in the Character Editor, so editing a DOS character does
    not mean two conversions)`: a conversion has to read the save as it is on
    screen, not as it was opened. The player's own folder is byte-identical
    afterwards -- a Save As must never save the original first.
    """
    folder = dos_folder(tmp_path / "save")
    before = files_under(folder)

    party = Party(str(folder))
    member = party.members[0]
    member.record.set("gold", 1234)
    quantity = member.inventory.raws[0][10] + 7
    member.inventory.set_quantity(0, quantity)

    source = convert.Source.detect(folder, party)
    rehearsal = dos_to_amiga().rehearse(source, "A", options=None)

    assert rehearsal.report.dropped == []
    written = AmigaDisk(rehearsal.files[convert.POOLSAVE_FILENAME])
    character = amiga_savegame.read_slot(
        written, "A", SILVER_BLADES.key).characters[0]
    assert character.money["gold"] == 1234
    assert [item.get("quantity") for item in character.items] == [quantity]

    assert files_under(folder) == before


def test_an_unsaved_amiga_edit_is_in_the_disk_a_conversion_reads(tmp_path):
    """The Amiga half of the same regression.

    `AmigaToC64.rehearse` and `AmigaToDos.rehearse` both start by opening the
    source's disk and reading its slot, which is exactly what this asserts
    on. Neither is driven the whole way here: an Amiga source's registered
    destinations each need a file off the player's own disks -- the C64
    combat-icon tables, or the DOS area script -- and no conversion of a
    synthetic save can supply one.
    """
    path = amiga_disk(tmp_path)
    before = path.read_bytes()

    party = Party(str(path))
    member = party.members[0]
    member.record.set("gold", 1234)
    member.inventory.set_raw(0, bytes(range(16)))

    source = convert.Source.detect(path, party)
    character = amiga_savegame.read_slot(
        source.amiga_disk(), "A", CURSE_KEY).characters[0]

    assert character.money["gold"] == 1234
    assert [item.get("quantity") for item in character.items] == [10]
    assert path.read_bytes() == before
    assert party.disk is None      # nothing opened an image into the party


def test_an_unsaved_c64_edit_is_in_the_payload_a_conversion_reads(tmp_path):
    """A C64 source holds the unsaved edit, and `party.save0` and the image
    are left exactly as they were."""
    path = synthetic_save(tmp_path)
    party = Party(str(path))
    payload, image = party.save0.to_bytes(), party.disk.to_bytes()
    member = party.members[0]
    member.record.set("gold", 1234)

    source = convert.Source.detect(path, party)
    # The first line of `C64ToAmiga.rehearse`, and `C64ToDos` reads the same
    # two payloads through `goldbox.dos_codec.new_dos_save`.
    converted, _icons = dos_codec.c64_party(source.save0, source.save1,
                                            game=party.game)

    assert converted[0].get("gold") == 1234
    assert party.save0.to_bytes() == payload
    assert party.disk.to_bytes() == image
    assert path.read_bytes() == image


# ---------------------------------------------------------------------------
# Preparing one writes nothing
# ---------------------------------------------------------------------------

def test_preparing_a_snapshot_writes_no_file_and_moves_no_baseline(tmp_path):
    """The editor is in exactly the state it was in, so the next Save still
    knows what the player changed."""
    folder = dos_folder(tmp_path)
    before = files_under(folder)

    party = Party(str(folder))
    member = party.members[0]
    originals = [(m.record_original, m.inventory.original) for m in party.members]
    member.record.set("gold", 1234)
    member.inventory.set_quantity(0, member.inventory.raws[0][10] + 1)
    assert member.inventory.changed

    saveplan.prepare(party)

    assert files_under(folder) == before
    assert [(m.record_original, m.inventory.original) for m in party.members] \
        == originals
    assert member.inventory.changed
    assert member.record.get("gold") == 1234


def test_a_dos_snapshot_of_an_unedited_party_is_the_saved_game_it_read(
        tmp_path):
    """The no-op rewrite, through the snapshot: a span the two renderings
    agree about is never copied, so nothing moves
    (`docs/223-the-differential-rewrite.md`)."""
    folder = dos_folder(tmp_path)
    before = files_under(folder)

    snapshot = saveplan.prepare(Party(str(folder)))

    assert snapshot.port == "dos" and snapshot.slot == "A"
    assert snapshot.files == before


def test_an_amiga_snapshot_of_an_unedited_party_holds_the_same_saved_game(
        tmp_path):
    """**The saved game, not the image.** `AmigaDisk.write_file` stamps the
    directory entry with the time of day, so an `.adf` written twice is never
    byte-identical and the file inside it is."""
    path = amiga_disk(tmp_path)
    slot_file = amiga_savegame.slot_path(
        Party(str(path)).source.title, "A")
    before = AmigaDisk.open(str(path)).read_file(slot_file)

    snapshot = saveplan.prepare(Party(str(path)))

    assert snapshot.port == "amiga"
    assert AmigaDisk(snapshot.image).read_file(slot_file) == before


# ---------------------------------------------------------------------------
# What a snapshot is made of
# ---------------------------------------------------------------------------

def test_a_dos_snapshot_carries_one_slots_files_and_not_another_slots(
        tmp_path):
    """A folder can hold several saved games; a snapshot is one of them."""
    folder = dos_folder(tmp_path)
    dos_folder(tmp_path, slot="B", numbers=(1,))

    snapshot = saveplan.prepare(Party(convert.Source.detect(folder, slot="B")))

    assert snapshot.slot == "B"
    assert sorted(snapshot.files) == [
        "CHRDATB1.SAV", f"CHRDATB1{SILVER_BLADES.effect_suffix}",
        f"CHRDATB1{SILVER_BLADES.item_suffix}", "SAVGAMB.DAT"]


def test_a_dos_source_reads_a_snapshot_through_a_folder_of_its_own(tmp_path):
    """`Source.folder()` is how a direction reads either kind of source, and
    a snapshot's copy is somewhere else entirely -- never the player's own
    folder, which a conversion must not write into."""
    folder = dos_folder(tmp_path)
    party = Party(str(folder))
    source = convert.Source.detect(folder, party)

    with source.folder() as scratch:
        assert scratch != folder
        assert files_under(scratch) == source.files
        inside = pathlib.Path(scratch)
    assert not inside.exists()

    plain = convert.Source.detect(folder)
    with plain.folder() as unchanged:
        assert unchanged == folder


def test_a_stand_in_party_with_no_roster_still_answers_for_its_own_path(
        tmp_path):
    """`Source.detect` documents a duck-typed party -- `.path`, `.game`,
    `.save0`, `.save1`, `.disk` -- and one with no roster has no edits to
    read, so its own payload is the answer."""
    from types import SimpleNamespace

    path = synthetic_save(tmp_path)
    party = Party(str(path))
    edited = bytearray(party.save0.to_bytes())
    edited[0] ^= 0xFF
    stand_in = SimpleNamespace(
        path=str(path), game=party.game,
        save0=SimpleNamespace(to_bytes=lambda: bytes(edited)),
        save1=party.save1, disk=party.disk)

    assert saveplan.prepare(stand_in) is None
    assert convert.Source.detect(path, stand_in).save0 == bytes(edited)


def test_a_party_with_nothing_open_is_refused_rather_than_snapshotted(
        tmp_path):
    """A roster disk has characters and no saved game."""
    from types import SimpleNamespace

    path = synthetic_save(tmp_path)
    stand_in = SimpleNamespace(path=str(path), game=None, save0=None,
                               save1=None, disk=None)
    with pytest.raises(convert.ConvertError):
        convert.Source.detect(path, stand_in)


# ---------------------------------------------------------------------------
# Which save the open party is, and which slot a conversion asked for
# ---------------------------------------------------------------------------

def converted_gold(source):
    """The gold of the first character a DOS -> Amiga conversion of `source`
    writes."""
    rehearsal = dos_to_amiga().rehearse(source, source.slot, options=None)
    written = AmigaDisk(rehearsal.files[convert.POOLSAVE_FILENAME])
    return amiga_savegame.read_slot(
        written, source.slot, SILVER_BLADES.key).characters[0].money["gold"]


def test_picking_the_save_file_of_the_open_dos_save_converts_its_edits(
        tmp_path):
    """You open a DOS save, change gold without saving, and convert by picking
    `SAVGAMA.DAT` in the Convert window's picker. `Party.path` is the folder
    and the picker hands over the file, so the two have to be recognised as
    one save or the conversion reads the old gold off disk."""
    folder = dos_folder(tmp_path)
    before = files_under(folder)
    party = Party(str(folder))
    party.members[0].record.set("gold", 1234)

    source = convert.Source.detect(folder / "SAVGAMA.DAT", party)

    assert converted_gold(source) == 1234
    assert source.slot == "A"
    assert source.path == folder        # a DOS source's path is its folder
    assert files_under(folder) == before


def test_picking_another_slots_save_file_reads_that_slot_off_disk(tmp_path):
    """The editor holds edits for the open slot only. A file that names
    another slot is not the open save."""
    folder = dos_folder(tmp_path)
    dos_folder(tmp_path, slot="B", numbers=(1,))
    party = Party(str(folder))
    party.members[0].record.set("gold", 1234)

    source = convert.Source.detect(folder / "SAVGAMB.DAT", party)

    assert source.slot == "B" and source.files is None


def test_a_save_file_in_another_folder_is_not_the_open_save(tmp_path):
    """The same slot letter in a different folder is somebody else's save."""
    folder = dos_folder(tmp_path / "open")
    other = dos_folder(tmp_path / "other")
    party = Party(str(folder))

    source = convert.Source.detect(other / "SAVGAMA.DAT", party)

    assert source.files is None and source.path == other


def test_the_slot_a_dos_conversion_asks_for_is_the_slot_it_reads(tmp_path):
    """The Convert window's slot combo re-detects the folder with the letter
    the player chose. On a folder holding two saved games the open slot's
    snapshot must not answer for the other one."""
    folder = dos_folder(tmp_path)
    dos_folder(tmp_path, slot="B", numbers=(1,))
    party = Party(str(folder))
    assert party.source.slot == "A"

    asked_for_b = convert.Source.detect(folder, party, slot="B")
    asked_for_a = convert.Source.detect(folder, party, slot="A")
    asked_for_none = convert.Source.detect(folder, party)

    assert asked_for_b.slot == "B"
    assert asked_for_b.available_slots == ["A", "B"]
    assert asked_for_b.files is None          # the editor holds nothing for B
    assert [asked_for_a.slot, asked_for_none.slot] == ["A", "A"]
    assert asked_for_a.files is not None and asked_for_none.files is not None


def test_the_slot_an_amiga_conversion_asks_for_is_the_slot_it_reads(tmp_path):
    path = amiga_two_slot_disk(tmp_path)
    party = Party(str(path))
    assert party.source.slot == "A"

    asked_for_b = convert.Source.detect(path, party, slot="B")
    asked_for_a = convert.Source.detect(path, party, slot="A")

    assert asked_for_b.slot == "B"
    assert asked_for_b.available_slots == ["A", "B"]
    assert asked_for_b.image is None
    assert asked_for_a.slot == "A" and asked_for_a.image is not None


# ---------------------------------------------------------------------------
# The other ports and the failures
# ---------------------------------------------------------------------------

def test_an_unsaved_c64_item_edit_is_in_the_snapshot_and_nowhere_else(
        tmp_path):
    """The snapshot's payload is what a real write-back produces, and the open
    party's payload, image and item baseline are untouched."""
    path = synthetic_save(tmp_path)
    party = Party(str(path))
    payload, image = party.save0.to_bytes(), party.disk.to_bytes()
    member = party.members[0]
    member.inventory.set_quantity(0, member.inventory.raws[0][10] + 7)
    assert member.inventory.changed

    snapshot = saveplan.prepare(party)

    expected = Party(str(path))
    other = expected.members[0]
    other.inventory.set_quantity(0, other.inventory.raws[0][10] + 7)
    for each in expected.members:
        expected.save0.write_record(each.index, each.record)
    expected.write_items()
    expected.write_icons()
    assert expected.save0.to_bytes() != payload      # the edit is real
    assert snapshot.save0 == expected.save0.to_bytes()
    assert party.save0.to_bytes() == payload
    assert party.disk.to_bytes() == image
    assert member.inventory.changed
    assert path.read_bytes() == image


def test_an_unsaved_c64_icon_edit_is_in_the_snapshot_and_nowhere_else(
        tmp_path):
    path = synthetic_save(tmp_path)
    party = Party(str(path))
    payload, image = party.save0.to_bytes(), party.disk.to_bytes()
    member = party.members[0]
    member.icon = Icon(bytes(b ^ 0xFF for b in member.icon.raw))
    assert member.icon != member.icon_original

    snapshot = saveplan.prepare(party)

    expected = Party(str(path))
    other = expected.members[0]
    other.icon = Icon(bytes(b ^ 0xFF for b in other.icon.raw))
    for each in expected.members:
        expected.save0.write_record(each.index, each.record)
    expected.write_items()
    expected.write_icons()
    assert expected.save0.to_bytes() != payload
    assert snapshot.save0 == expected.save0.to_bytes()
    assert party.save0.to_bytes() == payload
    assert party.disk.to_bytes() == image
    assert member.icon != member.icon_original
    assert len(member.icon.raw) == ICON_SIZE


def test_apply_c64_returns_the_payload_it_was_given_and_leaves_the_party(
        tmp_path):
    """`apply_c64` puts the party's own payload back afterwards, so writing
    into a copy never moves the live one."""
    party = Party(str(synthetic_save(tmp_path)))
    live = party.save0
    member = party.members[0]
    member.inventory.set_quantity(0, member.inventory.raws[0][10] + 1)
    copy = SaveGame0.from_bytes(live.to_bytes(), party.game)

    written = saveplan.apply_c64(party, copy)

    assert party.save0 is live
    assert written.to_bytes() != live.to_bytes()


def test_an_unsaved_amiga_pool_of_radiance_edit_is_in_the_snapshot(tmp_path):
    """Pool of Radiance keeps a slot in sibling files rather than one
    container, and takes a different branch of `write_amiga`."""
    path = amiga_por_disk(tmp_path)
    before = path.read_bytes()
    party = Party(str(path))
    assert party.source.title.key == "pool-of-radiance"
    member = party.members[0]
    member.record.set("gold", 1234)

    snapshot = saveplan.prepare(party)

    assert snapshot.port == "amiga"
    written = AmigaDisk(snapshot.image)
    characters = amiga_savegame.read_por_characters(written, "A")
    from goldbox import amiga_por
    assert amiga_por.to_dos_character(characters[0]).money["gold"] == 1234
    assert path.read_bytes() == before


def test_an_edit_that_reaches_no_byte_of_the_save_is_refused(tmp_path):
    """`turn_power` is a C64 field no DOS record holds, so the rewrite raises
    rather than returning a snapshot that quietly lost the edit -- through
    `prepare` and through `Source.detect`, which is what the Convert window
    calls."""
    folder = dos_folder(tmp_path)
    party = Party(str(folder))
    record = party.members[0].record
    record.set("turn_power", (record.get("turn_power") or 0) + 1)

    with pytest.raises(rewrite.RewriteError):
        saveplan.prepare(party)
    with pytest.raises(rewrite.RewriteError):
        convert.Source.detect(folder, party)
