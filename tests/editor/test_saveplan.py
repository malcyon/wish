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
    amiga_por,
    amiga_savegame,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    dos_savegame,
    rewrite,
)
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError
from goldbox.icons import ICON_SIZE, Icon
from goldbox.layout import Confidence
from goldbox.record import CharacterRecord
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
    rehearsal = dos_to_amiga().rehearse(
        source, "A", options=None,
        disk_one=_disk_one_path(tmp_path, SILVER_BLADES.key))

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

    ordinary = convert.Source.detect(folder)
    with ordinary.folder() as unchanged:
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

def converted_gold(source, tmp_path):
    """The gold of the first character a DOS -> Amiga conversion of `source`
    writes."""
    rehearsal = dos_to_amiga().rehearse(
        source, source.slot, options=None,
        disk_one=_disk_one_path(tmp_path, SILVER_BLADES.key))
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

    assert converted_gold(source, tmp_path) == 1234
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


@pytest.mark.parametrize("typed", [b"X\xe5Y", b"X\x01Y"])
def test_an_amiga_pool_name_with_an_alt_or_ctrl_byte_opens_and_saves_back(
        tmp_path, typed):
    """The Name span holds `0xE5` or `0x01`: the editor opens the save, shows
    the save's own name, and a same-port Save gives every byte back."""
    path = amiga_por_disk(tmp_path)
    disk = AmigaDisk.open(str(path))
    sav = bytearray(disk.read_file(_amiga_por_sav(disk)))
    sav[0:3] = typed
    disk.write_file(_amiga_por_sav(disk), bytes(sav))
    disk.save(str(path))

    party = Party(str(path))
    assert party.members[0].shown_name == typed.decode("latin1") + "HA"

    before = amiga_savegame.read_por_characters(
        AmigaDisk.open(str(path)), "A")
    written = saveplan.write_amiga(party, AmigaDisk.open(str(path)))
    after = amiga_savegame.read_por_characters(written, "A")
    assert after[0].raw == before[0].raw
    assert written.read_file(_amiga_por_sav(written))[0:3] == typed


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


def _destination(port, title, native=False):
    return saveplan.Destination(port=port, path=pathlib.Path("out"),
                                slot=None if port == "c64" else "A",
                                title=title, native=native)


def test_a_dual_class_pair_no_pool_title_reads_is_expected_back_as_zero():
    """A companion's template fill in the pair reaches DOS Pool of Radiance
    as the writer's constant 0; a title that reads the pair, and a native
    copy, still compare it literally."""
    filled = CharacterRecord.blank()
    filled.set("dual_class_slot", 255)
    filled.set("dual_class_level", 255)
    zeroed = CharacterRecord.blank()
    zeroed.set("strength_bonus_flag", 1)

    pool = _destination("dos", c64_port.POOL_OF_RADIANCE)
    assert saveplan.compare([filled], [zeroed], pool) == []

    curse = _destination("dos", c64_port.CURSE_OF_THE_AZURE_BONDS)
    lines = saveplan.compare([filled], [zeroed], curse)
    assert any("dual_class_slot" in line for line in lines)
    assert any("dual_class_level" in line for line in lines)

    native = _destination("dos", c64_port.POOL_OF_RADIANCE, native=True)
    assert any("dual_class_slot" in line
               for line in saveplan.compare([filled], [zeroed], native))


def _disk_one_path(tmp_path, key, slots=("A",)):
    from support.amigasavegame import synthetic_disk_one

    # Beside `tmp_path`, which a test may be using as the save folder itself.
    where = tmp_path.with_name(tmp_path.name + "-disk-one")
    where.mkdir(exist_ok=True)
    path = where / "disk-one.adf"
    synthetic_disk_one(key, slots).save(str(path))
    return path


def disk_one_assets(tmp_path, party, slots=("A",)):
    """`Assets` naming a synthetic disk 1 of the party's title, for the later
    titles whose Amiga output is a copy of it; `None` for any other title."""
    if saveplan.AMIGA_DISK_ONE not in saveplan.requirements(
            party.source, "amiga"):
        return None
    return saveplan.Assets(
        amiga_disk_one=_disk_one_path(tmp_path, party.source.key, slots))


@pytest.mark.parametrize("share", [0xFF, 0x84])
@pytest.mark.parametrize("port", ["dos", "amiga"])
def test_a_c64_hireling_with_bit_2_in_his_share_prepares_for_dos_and_amiga(
        tmp_path, port, share):
    """The Training Hall's `$FF` and `$84` shares arrive as the byte that
    splits treasure the same way, not as a dropped field."""
    from tools.convert import convertdrops
    from tools.dos import dosbox

    party = Party(str(synthetic_save(tmp_path)))
    for n, member in enumerate(party.members):
        member.record.set("name", f"HERO{n}")
        member.record.set("hp_max", 30)
    record = party.members[0].record
    record.set("flags_0b8", int(record.get("flags_0b8")) | 0x80)
    record.set("treasure_share", share)
    source = convert.Source.detect(party.path)
    try:
        if port == "dos":
            assets = saveplan.resolve_assets(
                source, "dos", game_files=convertdrops.game_files,
                dos_folder=dosbox.find_game("POOLRAD"))
            out = tmp_path / "out"
        else:
            disk = convertdrops.amiga_game_disks(tmp_path).get(
                c64_port.POOL_OF_RADIANCE.key)
            assets = saveplan.resolve_assets(
                source, "amiga", game_files=convertdrops.game_files,
                amiga_disk=disk)
            out = tmp_path / "out.adf"
    except (saveplan.MissingAssets, FileNotFoundError):
        pytest.skip("needs Pool of Radiance's own C64 disks and the "
                    "destination's game files")

    plan = saveplan.prepare_save_as(party, port, out, assets)
    assert isinstance(plan, saveplan.SavePlan)


def _hireling(share, written=False):
    record = CharacterRecord.blank()
    if written:
        # The one field a non-native DOS or Amiga destination is expected to
        # hold as a fixed value whatever the sheet says; not what these tests compare.
        record.set("strength_bonus_flag", 1)
    record.set("name", "HIRELING")
    record.set("flags_0b8", 0x80 | 49)
    record.set("treasure_share", share)
    return record


@pytest.mark.parametrize("source,port", [("dos", "amiga"), ("amiga", "dos")])
def test_a_dos_or_amiga_hireling_keeps_his_share_between_those_two_ports(
        source, port):
    """Only a C64 byte is rewritten on the way out, so a `$FF` that DOS and
    the Amiga both read as it stands is expected back as `$FF`."""
    destination = _destination(port, c64_port.POOL_OF_RADIANCE)
    assert saveplan.compare([_hireling(0xFF)], [_hireling(0xFF, True)],
                            destination, source_port=source) == []
    lines = saveplan.compare([_hireling(0xFF)], [_hireling(0xFB, True)],
                             destination, source_port=source)
    assert any("treasure_share" in line for line in lines)


@pytest.mark.parametrize("port", ["dos", "amiga"])
def test_a_c64_hireling_is_expected_with_bit_2_cleared_and_no_other_byte(port):
    destination = _destination(port, c64_port.POOL_OF_RADIANCE)
    assert saveplan.compare([_hireling(0xFF)], [_hireling(0xFB, True)],
                            destination, source_port="c64") == []
    lines = saveplan.compare([_hireling(0xFF)], [_hireling(0xFF, True)],
                             destination, source_port="c64")
    assert any("treasure_share" in line for line in lines)


@pytest.mark.parametrize("source", ["dos", "amiga"])
@pytest.mark.parametrize("share,written", [(0xFF, 0xFF), (0x84, 0x87),
                                           (0x04, 0x07), (0x05, 0x07),
                                           (0x03, 0x03), (0x01, 0x01)])
def test_a_dos_or_amiga_hireling_is_expected_with_bit_2_raised_to_three_parts(
        source, share, written):
    destination = _destination("c64", c64_port.POOL_OF_RADIANCE)
    assert saveplan.compare([_hireling(share)], [_hireling(written)],
                            destination, source_port=source) == []
    if written != share:
        lines = saveplan.compare([_hireling(share)], [_hireling(share)],
                                 destination, source_port=source)
        assert any("treasure_share" in line for line in lines)


def test_a_dos_share_is_expected_rewritten_for_the_c64_only_for_a_pool_companion():
    destination = _destination("c64", c64_port.POOL_OF_RADIANCE)
    player = _hireling(0x84)
    player.set("flags_0b8", 0)
    lines = saveplan.compare([player], [_hireling(0x87)],
                             destination, source_port="dos")
    assert any("treasure_share" in line for line in lines)
    other = _destination("c64", c64_port.CURSE_OF_THE_AZURE_BONDS)
    lines = saveplan.compare([_hireling(0x84)], [_hireling(0x87)],
                             other, source_port="dos")
    assert any("treasure_share" in line for line in lines)


def _prepared_dos_hireling(tmp_path, share):
    from tests.editor.test_hirelingopen import _folder
    from tools.convert import convertdrops
    folder = tmp_path / "save"
    folder.mkdir()
    party = Party(str(_folder(folder, share)))
    source = convert.Source.detect(party.path)
    try:
        assets = saveplan.resolve_assets(
            source, "c64", game_files=convertdrops.game_files)
    except (saveplan.MissingAssets, FileNotFoundError):
        pytest.skip("needs Pool of Radiance's own C64 disks")
    return saveplan.prepare_save_as(party, "c64",
                                    tmp_path / "out" / "out.d64", assets)


def test_a_dos_hirelings_reduced_share_reaches_the_debug_log(tmp_path):
    import logging

    from goldbox.c64_codec import SHARE_PARTS_REDUCED

    lines = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    log = logging.getLogger("wish.editor.saveplan")
    handler, level = Keep(), log.level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        _prepared_dos_hireling(tmp_path, 0xFF)
    finally:
        log.removeHandler(handler)
        log.setLevel(level)
    expected = SHARE_PARTS_REDUCED.format(port="DOS", value=0xFF, parts=7,
                                          written=0xFF, kept=3)
    assert any(expected in line for line in lines), lines


@pytest.mark.parametrize("port", ["dos", "amiga"])
def test_a_c64_zombie_is_expected_with_its_share_rewritten_like_a_companions(
        port):
    """The DOS writer rewrites the byte of a C64 record whose 0x0B8 is $FE,
    as it does a companion's, so the check expects the same."""
    destination = _destination(port, c64_port.POOL_OF_RADIANCE)
    zombie = _hireling(0x84)
    zombie.set("flags_0b8", 0xFE)
    written = _hireling(0x80, True)
    written.set("flags_0b8", 0xFE)
    assert saveplan.compare([zombie], [written], destination,
                            source_port="c64") == []


@pytest.mark.parametrize("share", [0xFF, 0x84, 0x04, 0x05])
def test_a_dos_hireling_prepares_for_the_c64(tmp_path, share):
    """The Training Hall's shares of 4 to 7 parts used to refuse the whole
    party; they now arrive as the C64's three."""
    plan = _prepared_dos_hireling(tmp_path, share)
    assert isinstance(plan, saveplan.SavePlan)


def test_a_c64_share_with_bit_2_is_expected_rewritten_only_for_a_pool_companion():
    """A player character's byte and another title's companion keep the
    writer's rejection, so the check expects them unchanged."""
    destination = _destination("dos", c64_port.POOL_OF_RADIANCE)
    player = _hireling(0xFF)
    player.set("flags_0b8", 0)
    lines = saveplan.compare([player], [_hireling(0xFB, True)],
                             destination, source_port="c64")
    assert any("treasure_share" in line for line in lines)
    for title in (c64_port.CURSE_OF_THE_AZURE_BONDS,
                  c64_port.SECRET_OF_THE_SILVER_BLADES):
        other = _destination("dos", title)
        lines = saveplan.compare([_hireling(0xFF)], [_hireling(0xFB, True)],
                                 other, source_port="c64")
        assert any("treasure_share" in line for line in lines), title


# ---------------------------------------------------------------------------
# C64 Pool of Radiance roster movement
# ---------------------------------------------------------------------------

def _armour_types():
    from goldbox.items import TYPE_LOCATION, ItemType

    raw = bytearray(16)
    raw[TYPE_LOCATION] = 2
    return {5: ItemType(5, bytes(raw))}


def _plate() -> bytes:
    raw = bytearray(16)
    raw[0], raw[6] = 5, 0x80
    raw[8], raw[9] = 450 & 0xFF, 450 >> 8
    return bytes(raw)


def _movement_party(tmp_path, game=None, types="armour"):
    party = Party(str(synthetic_save(tmp_path, game=game)))
    party.item_types = _armour_types() if types == "armour" else types
    member = party.members[0]
    member.record.set("movement", 12)
    return party, member


def _stored(party, member) -> int:
    _s0, save1, _disk = saveplan.c64_payloads(party)
    return save1.roster(member.index).movement


def test_a_coins_edit_recomputes_the_roster_movement(tmp_path):
    party, member = _movement_party(tmp_path)
    assert _stored(party, member) == 12
    member.record.set("gold", 3000)
    assert _stored(party, member) == 3


def test_readied_heavy_armour_recomputes_the_roster_movement(tmp_path):
    party, member = _movement_party(tmp_path)
    member.inventory.add(_plate())
    assert _stored(party, member) == 6


def test_an_untouched_party_keeps_its_movement_bytes(tmp_path):
    party = Party(str(synthetic_save(tmp_path)))
    party.item_types = _armour_types()
    _s0, save1, _disk = saveplan.c64_payloads(party)
    assert save1.to_bytes() == party.save1.to_bytes()


@pytest.mark.parametrize("types", [None, {}])
def test_no_item_table_leaves_movement_alone(tmp_path, types):
    party, member = _movement_party(tmp_path, types=types)
    member.record.set("gold", 3000)
    assert _stored(party, member) == 12


def test_another_title_keeps_its_movement(tmp_path):
    party, member = _movement_party(
        tmp_path, game=c64_port.by_key(CURSE_KEY))
    member.record.set("gold", 3000)
    assert _stored(party, member) == 12


def test_a_carried_weight_alone_recomputes_the_roster_movement(tmp_path):
    party, member = _movement_party(tmp_path)
    heavy = bytearray(16)
    heavy[0] = 6
    heavy[8], heavy[9] = 1100 & 0xFF, 1100 >> 8
    member.inventory.add(bytes(heavy))
    assert _stored(party, member) == 3


def test_a_dropped_item_recomputes_after_the_save_that_kept_it(tmp_path):
    party, member = _movement_party(tmp_path)
    slot = member.inventory.add(_plate())
    assert _stored(party, member) == 6
    party.mark_saved()
    member.inventory.set_raw(slot, bytes(16))
    assert _stored(party, member) == 12


def test_coins_put_back_after_a_save_recompute_on_the_next(tmp_path):
    party, member = _movement_party(tmp_path)
    member.record.set("gold", 3000)
    _s0, save1, _disk = saveplan.c64_payloads(party)
    party.save1 = save1
    party.mark_saved()
    member.record.set("gold", 0)
    assert _stored(party, member) == 12


def test_a_strength_index_off_the_table_leaves_movement_alone(tmp_path):
    party, member = _movement_party(tmp_path)
    member.record.set("strength_index", 31)
    member.record.set("gold", 3000)
    assert _stored(party, member) == 12


def test_a_broken_ring_alone_is_not_an_edit_of_movement(tmp_path):
    from goldbox.items import RING_OF_FIRE_RESISTANCE_ID

    # A stale 12 beside 3000 coins, as the game itself can leave it: with no
    # table nothing is recomputed on the way to the file.
    party, member = _movement_party(tmp_path, types=None)
    member.record.set("gold", 3000)
    ring = bytearray(16)
    ring[:4] = bytes(RING_OF_FIRE_RESISTANCE_ID)
    member.inventory.add(bytes(ring))
    _s0, _s1, disk = saveplan.c64_payloads(party)
    path = tmp_path / "RING.D64"
    path.write_bytes(disk.to_bytes())

    again = Party(str(path))
    again.item_types = _armour_types()
    inventory = again.members[0].inventory
    assert inventory.raws != inventory.original
    _s0, save1, _disk = saveplan.c64_payloads(again)
    assert save1.to_bytes() == again.save1.to_bytes()


# ---------------------------------------------------------------------------
# DOS Pool of Radiance roster movement
# ---------------------------------------------------------------------------

POOL_DOS = dos_port.POOL_OF_RADIANCE
_MOVEMENT_AT = dos_codec.FIELDS_BY_NAME_FOR[POOL_DOS.key][
    "movement_current"].offset


def _dos_movement_party(tmp_path, types="armour", deltas=POOL_DOS):
    """A DOS party whose first character has base movement 12 and nothing
    readied, so the stored byte and the rule agree until something is edited."""
    folder = dos_folder(tmp_path, deltas=deltas, numbers=(1,))
    seed = Party(str(folder))
    seed_record = seed.members[0].record
    seed_record.set("movement", 12)
    # Strength 17 carries 500 before it slows anybody; the made-up character's
    # 1 carries nothing, and its coins would already cap the movement.
    seed_record.set("strength", 17)
    seed_record.set("exceptional_strength", 0)
    for coin in ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry"):
        seed_record.set(coin, 0)
    for slot in range(len(seed.members[0].inventory.raws)):
        seed.members[0].inventory.set_raw(slot, bytes(16))
    for name, data in saveplan.dos_files(seed).items():
        if data:
            (folder / name).write_bytes(data)
        else:
            (folder / name).unlink(missing_ok=True)
    # The byte the game itself stores for base movement 12 and no burden.
    record = bytearray((folder / "CHRDATA1.SAV").read_bytes())
    record[_MOVEMENT_AT] = 12
    (folder / "CHRDATA1.SAV").write_bytes(bytes(record))
    party = Party(str(folder))
    party.item_types = _armour_types() if types == "armour" else types
    return party, party.members[0], folder


def _dos_stored(party, member) -> int:
    name = f"CHRDATA{member.index}.SAV"
    return saveplan.dos_files(party)[name][_MOVEMENT_AT]


def _ready(member, weight, plus=0):
    """Ready a type-5 item, which `_armour_types` makes body armour."""
    raw = bytearray(16)
    raw[0], raw[6] = 5, 0x80
    raw[8], raw[9] = weight & 0xFF, weight >> 8
    raw[7] = plus
    member.inventory.add(bytes(raw))


def test_readied_heavy_armour_writes_the_dos_movement_the_game_computes(
        tmp_path):
    """Nothing in the DOS game rebuilds the byte before an encounter menu's
    FLEE reads it."""
    party, member, _folder = _dos_movement_party(tmp_path)
    assert _dos_stored(party, member) == 12
    _ready(member, 450)
    assert _dos_stored(party, member) == 6


def test_coins_with_armour_on_write_the_dos_movement_the_game_computes(
        tmp_path):
    party, member, _folder = _dos_movement_party(tmp_path)
    _ready(member, 100)
    member.record.set("gold", 3000)
    assert _dos_stored(party, member) == 3


def test_an_untouched_dos_party_with_a_table_is_byte_identical(tmp_path):
    party, _member, folder = _dos_movement_party(tmp_path)
    before = files_under(folder)
    files = saveplan.dos_files(party)
    for name, data in files.items():
        assert data == before.get(name), name


@pytest.mark.parametrize("types", [None, {}])
def test_no_item_table_leaves_a_dos_armed_characters_movement_and_logs_it(
        tmp_path, types, caplog):
    party, member, _folder = _dos_movement_party(tmp_path, types=types)
    _ready(member, 450)
    with caplog.at_level("WARNING", logger="wish.editor.saveplan"):
        assert _dos_stored(party, member) == 12
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1 and member.name in lines[0]
    assert "not rebuilt" in lines[0]


def test_dos_curse_movement_is_written_as_it_was(tmp_path):
    curse = dos_codec.deltas_for(CURSE_KEY)
    party, member, _folder = _dos_movement_party(tmp_path, deltas=curse)
    member.record.set("gold", 3000)
    at = dos_codec.FIELDS_BY_NAME_FOR[CURSE_KEY]["movement_current"].offset
    name = f"CHRDATA{member.index}.SAV"
    with_hook = saveplan.dos_files(party)[name]
    raw = rewrite.rewrite_dos(member.native, saveplan.original_record(member),
                              saveplan.edited_record(member))
    assert with_hook == raw.record and with_hook[at] == raw.record[at]


# ---------------------------------------------------------------------------
# Amiga Pool of Radiance roster movement
# ---------------------------------------------------------------------------

_AMIGA_MOVEMENT_AT = amiga_por.amiga_por_offset(_MOVEMENT_AT)


def _amiga_por_sav(disk):
    drawer = amiga_savegame.por_save_drawer(disk)
    return amiga_savegame.por_save_path(
        amiga_por.por_filename("A", 1, "") + ".sav", drawer)


def _amiga_movement_party(tmp_path, types="armour", stored=12):
    """An Amiga party whose first character has base movement 12 and nothing
    readied, so the stored byte and the rule agree until something is edited."""
    path = amiga_por_disk(tmp_path)
    seed = Party(str(path))
    seed_record = seed.members[0].record
    seed_record.set("movement", 12)
    seed_record.set("strength", 17)
    seed_record.set("exceptional_strength", 0)
    for coin in ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry"):
        seed_record.set(coin, 0)
    for slot in range(len(seed.members[0].inventory.raws)):
        seed.members[0].inventory.set_raw(slot, bytes(16))
    disk = saveplan.write_amiga(seed, AmigaDisk.open(str(path)))
    # The byte the game itself stores for base movement 12 and no burden,
    # unless a test wants one the rule would not give.
    sav = bytearray(disk.read_file(_amiga_por_sav(disk)))
    sav[_AMIGA_MOVEMENT_AT] = stored
    disk.write_file(_amiga_por_sav(disk), bytes(sav))
    disk.save(str(path))
    party = Party(str(path))
    party.item_types = _armour_types() if types == "armour" else types
    return party, party.members[0], path


def _amiga_written(party, path):
    disk = saveplan.write_amiga(party, AmigaDisk.open(str(path)))
    return disk.read_file(_amiga_por_sav(disk))


def _amiga_stored(party, path) -> int:
    return _amiga_written(party, path)[_AMIGA_MOVEMENT_AT]


def test_amiga_coins_with_nothing_readied_write_the_movement_the_game_computes(
        tmp_path):
    """No Amiga render rebuilds the byte, and nothing in the Amiga game does
    before an encounter menu's FLEE reads it. With no table an unarmed
    character is rebuilt all the same."""
    party, member, path = _amiga_movement_party(tmp_path, types=None)
    assert _amiga_stored(party, path) == 12
    member.record.set("gold", 3000)
    assert _amiga_stored(party, path) == 3


def test_readied_heavy_armour_writes_the_amiga_movement_the_game_computes(
        tmp_path):
    party, member, path = _amiga_movement_party(tmp_path)
    _ready(member, 450)
    assert _amiga_stored(party, path) == 6


def test_amiga_coins_with_armour_on_write_the_movement_the_game_computes(
        tmp_path):
    party, member, path = _amiga_movement_party(tmp_path)
    _ready(member, 100)
    member.record.set("gold", 3000)
    assert _amiga_stored(party, path) == 3


def test_a_typed_amiga_movement_is_kept(tmp_path):
    party, member, path = _amiga_movement_party(tmp_path)
    member.record.set("roster_movement", 15)
    assert _amiga_stored(party, path) == 15


def test_a_typed_amiga_movement_survives_coins_in_the_same_save(tmp_path):
    party, member, path = _amiga_movement_party(tmp_path)
    member.record.set("roster_movement", 15)
    member.record.set("gold", 3000)
    assert _amiga_stored(party, path) == 15


def test_an_untouched_amiga_party_with_a_table_is_byte_identical(tmp_path):
    """The stored 9 is not what the rule gives (12), so a save that always
    wrote the rule's value would change it."""
    party, _member, path = _amiga_movement_party(tmp_path, stored=9)
    # File dates differ between two writes of one disk, so compare the
    # character's files rather than the image.
    def files(disk):
        stem = _amiga_por_sav(disk)[:-len(".sav")]
        out = {}
        for suffix in (".sav", ".itm", ".spc"):
            try:
                out[suffix] = disk.read_file(stem + suffix)
            except AmigaDiskError:
                out[suffix] = None
        return out

    before = files(AmigaDisk.open(str(path)))
    after = files(saveplan.write_amiga(party, AmigaDisk.open(str(path))))
    assert after == before
    assert after[".sav"][_AMIGA_MOVEMENT_AT] == 9


@pytest.mark.parametrize("types", [None, {}])
def test_no_item_table_leaves_an_amiga_armed_characters_movement_and_logs_it(
        tmp_path, types, caplog):
    party, member, path = _amiga_movement_party(tmp_path, types=types)
    _ready(member, 450)
    with caplog.at_level("WARNING", logger="wish.editor.saveplan"):
        assert _amiga_stored(party, path) == 12
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1 and member.name in lines[0]
    assert "not rebuilt" in lines[0]


def test_amiga_curse_movement_is_written_as_it_was(tmp_path):
    from support.amigasavegame import synthetic_curse

    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA",)))
    path = tmp_path / "curse.adf"
    disk.save(str(path))
    party = Party(str(path))
    party.members[0].record.set("gold", 3000)
    with_hook = saveplan.write_amiga(party, AmigaDisk.open(str(path)))
    save = amiga_savegame.read_slot(AmigaDisk.open(str(path)), "A",
                                    party.source.title.key)
    member = party.members[0]
    raw = rewrite.rewrite_amiga_later(
        member.native, saveplan.original_record(member),
        saveplan.edited_record(member)).character
    slot = amiga_savegame.slot_path(party.source.title, "A")
    assert with_hook.read_file(slot) == amiga_savegame.rebuild(save, [raw])


def _feebleminded_neutral(feebleminded):
    from goldbox import neutral

    char = neutral.NeutralCharacter("C64", source="built here",
                                    game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    char.set("abilities_second", {"intelligence": 16, "wisdom": 14},
             "built here")
    if feebleminded:
        char.set("granted_effects",
                 [bytes.fromhex("44 00 00 0A 00") + dos_codec.EFFECT_NEXT_NULL],
                 "built here")
    return char


def test_a_written_int_of_3_without_feeblemind_is_refused():
    """Feeblemind's 3 is expected only for the character whose source holds
    the node; the same 3 on another character is still a loss."""
    def sheet():
        record = CharacterRecord.blank()
        record.set("intelligence", 16)
        record.set("wisdom", 14)
        record.set_raw("abilities_second", bytes((0, 16, 14, 0, 0, 0, 0)))
        return record

    def written(intelligence, wisdom):
        record = sheet()
        record.set("intelligence", intelligence)
        record.set("wisdom", wisdom)
        return record

    curse = _destination("dos", c64_port.CURSE_OF_THE_AZURE_BONDS)
    first, second = sheet(), sheet()
    for name, score in saveplan.feeblemind_scores(
            first, _feebleminded_neutral(True), "c64", curse).items():
        first.set(name, score)
    assert saveplan.feeblemind_scores(
        second, _feebleminded_neutral(False), "c64", curse) == {}

    lines = saveplan.compare([first, second],
                             [written(3, 14), written(3, 14)], curse,
                             source_port="c64")
    # A blank record's strength-bonus flag is refused for its own reason
    # here, so only the two scores are read.
    scores = [line for line in lines if line.split(":")[0] in
              ("intelligence", "wisdom")]
    assert scores == ["intelligence: 16 arrived as 3"], lines
    assert [line for line in saveplan.compare(
        [first, second], [written(3, 14), written(16, 14)], curse,
        source_port="c64") if "intelligence" in line or "wisdom" in line] == []
    # Curse's Feeblemind leaves WIS alone, so a written 3 is a loss.
    assert [line for line in saveplan.compare(
        [first, second], [written(3, 3), written(16, 14)], curse,
        source_port="c64") if "wisdom" in line] == ["wisdom: 14 arrived as 3"]

    flagged = _feebleminded_neutral(True)
    assert saveplan.feeblemind_scores(
        first, flagged, "c64",
        _destination("dos", c64_port.CURSE_OF_THE_AZURE_BONDS,
                     native=True)) == {}
    assert saveplan.feeblemind_scores(
        first, flagged, "c64",
        _destination("dos", c64_port.POOL_OF_RADIANCE)) == {}
    assert saveplan.feeblemind_scores(
        first, flagged, "dos",
        _destination("amiga", c64_port.CURSE_OF_THE_AZURE_BONDS)) == {}


def _dos_feebleminded_neutral():
    from goldbox import neutral

    char = neutral.NeutralCharacter("DOS", source="built here")
    char.set("granted_effects",
             [bytes.fromhex("44 00 00 0A 00") + dos_codec.EFFECT_NEXT_NULL],
             "built here")
    char.set("abilities_second", {"intelligence": 16, "wisdom": 14},
             "built here")
    return char


@pytest.mark.parametrize("title, expected", [
    (c64_port.CURSE_OF_THE_AZURE_BONDS, {"intelligence": 3, "wisdom": 14}),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, {"intelligence": 3, "wisdom": 3}),
])
def test_a_feebleminded_dos_character_is_expected_at_the_c64s_feeblemind_scores(
        title, expected):
    record = CharacterRecord.blank()
    record.set_raw("abilities_second", bytes((0, 16, 14, 0, 0, 0, 0)))
    scores = saveplan.feeblemind_scores(
        record, _dos_feebleminded_neutral(), "dos",
        _destination("c64", title))
    assert scores == expected


def _charmed_pool_neutral(share, control=0xB3, charmed=True):
    from goldbox import neutral

    char = neutral.NeutralCharacter("DOS", source="built here",
                                    game=c64_port.POOL_OF_RADIANCE)
    char.set("treasure_share", share, "built here")
    char.set("npc", control >= 0x80, "built here")
    char.set("npc_control_byte", control, "built here")
    if charmed:
        char.set("granted_effects",
                 [bytes.fromhex("0B 00 00 21 01") + dos_codec.EFFECT_NEXT_NULL],
                 "built here")
    return char


def _charmed_sheet(share):
    record = CharacterRecord.blank()
    record.set("flags_0b8", 0xB3)
    record.set("treasure_share", share)
    return record


@pytest.mark.parametrize("share, flags, written_share",
                         [(1, 1, 0), (0, 0, 0)])
def test_a_charmed_pool_player_character_is_expected_as_the_writer_writes_him(
        share, flags, written_share):
    destination = _destination("c64", c64_port.POOL_OF_RADIANCE)
    sheet = _charmed_sheet(share)
    fields = saveplan.charmed_pool_fields(
        sheet, _charmed_pool_neutral(share), "dos", destination)
    assert fields == {"flags_0b8": flags, "treasure_share": written_share}
    for name, value in fields.items():
        sheet.set(name, value)
    written = _charmed_sheet(written_share)
    written.set("flags_0b8", flags)
    assert [line for line in saveplan.compare(
        [sheet], [written], destination, source_port="dos")
        if line.split(":")[0] in ("flags_0b8", "treasure_share")] == []


def test_a_character_who_is_not_charmed_keeps_his_flags_0b8_mismatch():
    destination = _destination("c64", c64_port.POOL_OF_RADIANCE)
    sheet = _charmed_sheet(1)
    for neutral_char, port, where in [
            (_charmed_pool_neutral(1, charmed=False), "dos", destination),
            (_charmed_pool_neutral(1), "c64", destination),
            (_charmed_pool_neutral(1), "dos",
             _destination("c64", c64_port.CURSE_OF_THE_AZURE_BONDS))]:
        assert saveplan.charmed_pool_fields(
            sheet, neutral_char, port, where) == {}
    written = _charmed_sheet(1)
    written.set("flags_0b8", 1)
    assert any("flags_0b8: 179 arrived as 1" in line for line in
               saveplan.compare([sheet], [written], destination,
                                source_port="dos"))


def test_a_dos_pool_party_with_a_charmed_character_saves_as_c64(tmp_path):
    from tools.convert import convertdrops
    from tools.registry import specimens
    spec = next((entry["_files"][0].parent
                 for entry in specimens.list_specimens()
                 if entry.get("name") ==
                 "pool-8-friends-mirror-prayer-charm-dos-engine-save"), None)
    if spec is None:
        pytest.skip("needs the charmed Pool of Radiance DOS specimen")
    party = Party(str(spec))
    source = convert.Source.detect(party.path)
    try:
        assets = saveplan.resolve_assets(
            source, "c64", game_files=convertdrops.game_files)
    except (saveplan.MissingAssets, FileNotFoundError):
        pytest.skip("needs Pool of Radiance's own C64 disks")
    saveplan.prepare_save_as(party, "c64", tmp_path / "out" / "out.d64",
                             assets)


def _written_charm_fields(char, free_slot=True):
    from goldbox import effects

    payload = bytearray(0x2000)
    if not free_slot:
        for slot in range(effects.EFFECT_SLOTS):
            effects.write_effect(payload, slot, 1, 0, 1, 0)
    record, _ = c64_codec.write(char, payload=payload, party_slot=2)
    return {"flags_0b8": record.get("flags_0b8"),
            "treasure_share": record.get("treasure_share")}


@pytest.mark.parametrize("share", [0, 1, 3])
def test_the_charmed_expectation_equals_what_the_writer_writes(share):
    char = _charmed_pool_neutral(share)
    expected = c64_codec.charmed_pool_player_fields(char)
    written = _written_charm_fields(char)
    assert {k: written[k] for k in expected} == expected
    assert written["flags_0b8"] == expected["flags_0b8"]
    if share == 3:
        assert expected == {"flags_0b8": 0}


@pytest.mark.parametrize("share", [0, 1, 3])
def test_a_charm_with_no_free_slot_is_expected_as_the_writer_writes_it(share):
    char = _charmed_pool_neutral(share)
    expected = c64_codec.charmed_pool_player_fields(
        char, charm_row_written=False)
    written = _written_charm_fields(char, free_slot=False)
    assert expected["flags_0b8"] == 0xB3
    assert {k: written[k] for k in expected} == expected


def test_a_companion_with_another_control_byte_is_not_a_charmed_player():
    char = _charmed_pool_neutral(1, control=0x90)
    assert c64_codec.charmed_pool_player_fields(char) == {}
    destination = _destination("c64", c64_port.POOL_OF_RADIANCE)
    assert saveplan.charmed_pool_fields(
        _charmed_sheet(1), char, "dos", destination) == {}
