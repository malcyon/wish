"""Preparing a Save As, refusing one that would lose a field, and publishing.

Everything here is built from the format rather than copied off a disk, so it
runs with no game data at all -- `test_saveplan.py`'s own builders, and the
one cross-platform direction that needs no file off the player's disks (DOS
Secret of the Silver Blades to an Amiga save disk, which stages no area
script). The native copies need no game data on any port.

Two losses are real rather than injected -- a name longer than the
destination's own field, and a value the writer clamps -- and the rest of the
failures are injected rather than waited for: a dropped field forced into a
conversion's own accounting, a publication whose rename fails, a rollback
whose unlink fails, and an adoption that never happens, each with the state
afterwards asserted.

The tests needing the player's own disks say so and skip: the DOS Pool of
Radiance game folder, the C64 game disks and the C64 save disks, all three
through `automap/gamedisks.py`.
"""
from __future__ import annotations

import os
import pathlib
import stat
import string
import sys

import pytest
from gamedata import specimen_root, synthetic_save
from support.editorwindow import make_root
from test_saveplan import (
    SILVER_BLADES,
    amiga_disk,
    amiga_two_slot_disk,
    dos_folder,
    files_under,
)

from editor import convert, files, saveplan
from editor.roster import Party
from editor.window import EditorBinding
from goldbox import amiga_savegame, dos_port
from goldbox.amiga_adf import AmigaDisk
from goldbox.d64 import D64
from goldbox.layout import LAYOUT, NAME_SIZE
from goldbox.record import RECORD_SIZE, CharacterRecord
from goldbox.savegame import SLOT_STRIDE, load_save, store_save

POOL_OF_RADIANCE = "pool-of-radiance"


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


CURSE_KEY = "curse-of-the-azure-bonds"


def edited_dos_party(tmp_path, **kwargs):
    """A DOS Silver Blades party with a changed gold and item quantity, and
    nothing saved."""
    folder = dos_folder(tmp_path, **kwargs)
    party = Party(str(folder))
    member = party.members[0]
    member.record.set("gold", 1234)
    quantity = member.inventory.raws[0][10] + 7
    member.inventory.set_quantity(0, quantity)
    return party, folder, quantity


def save_with_residue_slots(tmp_path, name="RESIDUE.D64", slots=(6, 7)):
    """A C64 save disk carrying a dropped character's residue.

    `ENCAMP > ALTER > DROP` leaves the whole of a character's record in his
    slot and clears the first byte of the name, which is what slots 6 and 7
    of the player's own Pool of Radiance save disks hold -- `.OLAND` and
    `.RUTUS`, one for each character dropped since. This builds the same
    thing from the format.
    """
    path = synthetic_save(tmp_path, name)
    disk = D64.open(str(path))
    game, save0, save1 = load_save(disk)
    residue = bytearray(save0.slot(0).window)
    residue[0] = 0
    for index in slots:
        save0.write_record(index, bytes(residue))
    store_save(disk, save0, save1, game)
    disk.save(path)
    return path


def slot_bytes(path, title, slot):
    """One saved game out of an `.adf`, which is what two Amiga images can be
    compared by -- the image itself never repeats, because `AmigaDisk` stamps
    each directory entry with the time of day."""
    return AmigaDisk.open(str(path)).read_file(
        amiga_savegame.slot_path(title, slot))


# ---------------------------------------------------------------------------
# The proof: an edited, unsaved DOS party published as an Amiga save disk
# ---------------------------------------------------------------------------

def test_an_unsaved_dos_party_saved_as_amiga_arrives_with_both_edits(
        tmp_path):
    """Edit a character and an item, Save As to a chosen `.adf` without
    saving first, and open what was written: both edits are in it and the
    player's own save folder is byte for byte what it was.

    The destination filename is the player's, not the writer's -- the Amiga
    writer names every disk it builds `POOLSAVE.ADF`, and this one is called
    something else.
    """
    party, folder, quantity = edited_dos_party(tmp_path / "save")
    before = files_under(folder)
    out = tmp_path / "out" / "chosen.adf"

    plan = saveplan.prepare_save_as(party, "amiga", out)
    assert plan.report.dropped == []
    assert not out.exists()                 # preparing writes nothing

    published = saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert published.destination.path == out
    assert published.destination.slot == "A"   # a DOS source keeps its letter
    assert published.backup is None            # a new output loses nothing
    adopted = published.party
    assert adopted.port == "amiga"
    assert adopted.members[0].record.get("gold") == 1234
    assert adopted.members[0].inventory.raws[0][10] == quantity
    assert files_under(folder) == before


def test_the_editor_adopts_the_published_save_and_points_at_it(app, tmp_path):
    """Adoption is the editor's own `_adopt` over the party publication
    handed back: the window shows the destination afterwards and the next
    Save would write there."""
    party, folder, quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    published = saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                                 party, backups=tmp_path / "backups")

    editor = EditorBinding(make_root())
    editor._adopt(published.party, str(published.destination.path))

    assert editor.path == out
    assert editor.party.port == "amiga"
    assert editor.party.members[0].record.get("gold") == 1234
    assert editor.dirty == set()


# ---------------------------------------------------------------------------
# Native copies: the same platform, and everything else in the container
# ---------------------------------------------------------------------------

def test_a_dos_native_copy_keeps_the_other_saves_and_the_stranger_files(
        tmp_path):
    """A DOS Save As to another folder copies the whole save folder, the
    slots nobody was editing included, and puts the edits in the open one."""
    party, folder, quantity = edited_dos_party(tmp_path / "save")
    dos_folder(folder, slot="B", numbers=(1,))
    (folder / "OPAQUE.BIN").write_bytes(bytes(range(64)))
    before = files_under(folder)
    out = tmp_path / "copy"

    plan = saveplan.prepare_save_as(party, "dos", out)
    published = saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert published.destination.slot == "A"    # the letter it was opened at
    after = files_under(out)
    assert sorted(after) == sorted(before)
    for name in before:
        if not name.startswith(("CHRDATA", "SAVGAMA")):
            assert after[name] == before[name], name
    assert after["SAVGAMA.DAT"] == before["SAVGAMA.DAT"]
    assert after["CHRDATA1.SAV"] != before["CHRDATA1.SAV"]
    assert published.party.members[0].record.get("gold") == 1234
    assert published.party.members[0].inventory.raws[0][10] == quantity
    assert files_under(folder) == before


def test_an_amiga_native_copy_keeps_a_second_saved_game(tmp_path):
    """The other slot on the disk is the same saved game afterwards, and the
    open one carries the edit."""
    path = amiga_two_slot_disk(tmp_path)
    party = Party(str(path))
    title = party.source.title
    party.members[0].record.set("gold", 4321)
    before = path.read_bytes()
    kept = slot_bytes(path, title, "B")
    out = tmp_path / "copy.adf"

    published = saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                                 party, backups=tmp_path / "backups")

    assert slot_bytes(out, title, "B") == kept
    assert published.party.members[0].record.get("gold") == 4321
    assert path.read_bytes() == before


def test_a_c64_native_copy_writes_the_edited_image(tmp_path):
    path = synthetic_save(tmp_path)
    party = Party(str(path))
    party.members[0].record.set("gold", 999)
    before = path.read_bytes()
    out = tmp_path / "copy.d64"

    published = saveplan.publish(saveplan.prepare_save_as(party, "c64", out),
                                 party, backups=tmp_path / "backups")

    assert published.destination.slot is None      # a C64 save has no letter
    assert published.party.members[0].record.get("gold") == 999
    assert out.read_bytes() != before
    assert path.read_bytes() == before


def test_a_c64_copy_of_a_save_holding_a_dropped_characters_residue_goes_ahead(
        tmp_path):
    """Six characters in the roster, eight slots with bytes in them, and the
    copy is not a loss.

    Counting every slot with any non-zero byte in it makes the two slots
    still holding a dropped character's record part of the party, so six
    characters arrive as eight and every real Pool of Radiance save is
    refused. The copy keeps the residue: a native copy is the image itself.
    """
    path = save_with_residue_slots(tmp_path)
    party = Party(str(path))
    assert len(party.members) == 6
    out = tmp_path / "copy.d64"

    published = saveplan.publish(saveplan.prepare_save_as(party, "c64", out),
                                 party, backups=tmp_path / "backups")

    assert len(saveplan.c64_slot_records(out)) == 6
    _game, before, _save1 = load_save(D64.open(str(path)))
    _game, after, _save1 = load_save(D64.open(str(out)))
    assert after.slot(6).window == before.slot(6).window
    assert after.slot(6).window[0] == 0
    assert published.party is not None


def test_every_pool_of_radiance_c64_save_on_this_machine_copies_to_c64(
        tmp_path):
    """The same guard against the player's own save disks rather than a
    generated one.

    Skips where this machine's registry (`automap/gamedisks.py`) has no Pool
    of Radiance disks. A `PORSAVE` image with no saved game on it is a roster
    disk and is counted separately rather than treated as a failure.
    """
    saves = _c64_pool_saves()
    if not saves:
        pytest.skip("needs the Pool of Radiance C64 save disks")
    copied, roster_disks = [], []
    for path in saves:
        party = Party(str(path))
        if saveplan.prepare(party) is None:
            roster_disks.append(path.name)
            continue
        out = tmp_path / f"{path.stem}-copy.d64"
        plan = saveplan.prepare_save_as(party, "c64", out)
        # The bytes publication would put down, read back the way the guard
        # reads them -- preparing writes no file of its own.
        out.write_bytes(next(iter(plan.files.values())))
        copied.append((path.name, len(party.members),
                       len(saveplan.c64_slot_records(out))))
    assert copied, f"nothing but roster disks: {roster_disks}"
    assert [name for name, went_in, came_out in copied
            if went_in != came_out] == []


def test_no_pool_of_radiance_c64_save_is_refused_for_the_altered_flag(
        tmp_path):
    """The symptom of #620, against the player's own disks: a C64 party whose
    scores were altered in the modification screen refused a DOS destination
    with `flags_0b8: 1 arrived as 0` on twelve of the fifteen save disks
    here, one character of six in each. No refusal may name that field now.

    Other refusals are not this test's business and are counted rather than
    asserted on, so a route that loses something else fails its own test and
    not this one. Skips where this machine's registry has no Pool of Radiance
    C64 disks or no DOS Pool of Radiance game folder.
    """
    saves = _c64_pool_saves()
    files_for = _registry_game_files(POOL_OF_RADIANCE)
    game_folder = _dos_game_folder()
    if not saves or files_for is None or game_folder is None:
        pytest.skip("needs the Pool of Radiance C64 disks and DOS game folder")
    assets = saveplan.Assets(dos_folder=game_folder, source_files=files_for)
    went_ahead, refused, roster_disks = [], {}, []
    for path in saves:
        party = Party(str(path))
        if saveplan.prepare(party) is None:
            roster_disks.append(path.name)
            continue
        try:
            saveplan.prepare_save_as(party, "dos", tmp_path / path.stem,
                                     assets)
        except saveplan.DroppedFields as caught:
            refused[path.name] = caught.lost
        else:
            went_ahead.append(path.name)

    assert went_ahead, f"every save refused: {refused}"
    assert {name: lost for name, lost in refused.items()
            if any("flags_0b8" in line for line in lost)} == {}


def test_every_pool_of_radiance_c64_save_goes_ahead_to_dos(tmp_path):
    """`#621 (A C64 character carrying an effect in a trait slot cannot be
    saved as a DOS or Amiga save, because the writer keeps only the eight
    ids the game's own importer keeps)`: SILAS, the sixth character of
    `PORSAVEA.D64` and `PORSAVEB.D64`, carries Protection from Evil, 10'
    Radius and Detect Magic in trait slots, which the writer used to drop
    and refuse the whole save for. Every non-roster Pool of Radiance C64 save
    on this machine now goes ahead. Skips where this machine's registry has
    no Pool of Radiance C64 disks or no DOS Pool of Radiance game folder.
    """
    saves = _c64_pool_saves()
    files_for = _registry_game_files(POOL_OF_RADIANCE)
    game_folder = _dos_game_folder()
    if not saves or files_for is None or game_folder is None:
        pytest.skip("needs the Pool of Radiance C64 disks and DOS game folder")
    assets = saveplan.Assets(dos_folder=game_folder, source_files=files_for)
    went_ahead, refused, roster_disks = [], {}, []
    for path in saves:
        party = Party(str(path))
        if saveplan.prepare(party) is None:
            roster_disks.append(path.name)
            continue
        try:
            saveplan.prepare_save_as(party, "dos", tmp_path / path.stem,
                                     assets)
        except saveplan.DroppedFields as caught:
            refused[path.name] = caught.lost
        else:
            went_ahead.append(path.name)

    assert went_ahead, f"every save refused: {refused}"
    assert refused == {}, refused


def test_a_native_copy_needs_no_game_data_and_has_no_conversion_report(
        tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")

    assert saveplan.requirements(party.source, "dos") == ()
    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "copy")
    assert plan.destination.native and plan.report is None


def test_a_save_as_over_the_save_it_reads_is_refused(tmp_path):
    """There is a Save for writing back to the open save, and a Save As that
    published over its own source would be reading and destroying the same
    file."""
    party, folder, _quantity = edited_dos_party(tmp_path / "save")
    before = files_under(folder)
    path = amiga_disk(tmp_path, name="open.adf")
    amiga_party = Party(str(path))
    was = path.read_bytes()

    with pytest.raises(saveplan.SaveAsError):
        saveplan.prepare_save_as(party, "dos", folder)
    with pytest.raises(saveplan.SaveAsError):
        saveplan.prepare_save_as(amiga_party, "amiga", path)

    assert files_under(folder) == before
    assert path.read_bytes() == was


# ---------------------------------------------------------------------------
# What a route needs off the player's own disks
# ---------------------------------------------------------------------------

def test_a_silver_blades_amiga_destination_asks_for_no_game_disk(tmp_path):
    """Silver Blades stages no area script, so its Amiga writer needs no game
    disk at all where a Pool of Radiance or a Curse one does."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")

    assert saveplan.requirements(party.source, "amiga") == ()
    assert saveplan.resolve_assets(party.source, "amiga") == saveplan.Assets()


def test_a_curse_party_not_yet_set_out_asks_for_no_amiga_game_disk(
        tmp_path, monkeypatch):
    """The pre-adventure Amiga save stages no `ECL.GLB`, so the route needs
    no disk 2 and neither requirements, assets nor the rehearsal ask for one;
    a Curse party already in the world still does."""
    import dataclasses

    from goldbox import world_state

    source = convert.Source.detect(
        synthetic_save(tmp_path, game=convert.c64_port.by_key(CURSE_KEY)))
    assert source.key == CURSE_KEY
    assert saveplan.requirements(source, "amiga") == (saveplan.SOURCE_DISKS,)
    assets = saveplan.resolve_assets(source, "amiga",
                                     game_files=lambda title: object())
    assert assets.amiga_disk is None
    shape = dos_port.CURSE_OF_THE_AZURE_BONDS
    assert convert._amiga_destination_data(
        shape, tmp_path / "no-such-disk.adf", source) is None

    real = world_state.from_c64

    def in_the_world(*args, **kwargs):
        return dataclasses.replace(real(*args, **kwargs), set_out=True)

    monkeypatch.setattr(world_state, "from_c64", in_the_world)
    assert saveplan.requirements(source, "amiga") == (
        saveplan.AMIGA_GAME_DISK, saveplan.SOURCE_DISKS)
    with pytest.raises(saveplan.MissingAssets) as caught:
        saveplan.resolve_assets(source, "amiga",
                                game_files=lambda title: object())
    assert caught.value.missing == (saveplan.AMIGA_GAME_DISK,)
    with pytest.raises(FileNotFoundError):
        convert._amiga_destination_data(
            shape, tmp_path / "no-such-disk.adf", source)


def test_the_c64_to_amiga_rehearsal_hands_its_source_to_the_disk_check(
        tmp_path):
    """A pre-adventure Curse party rehearses without opening the named disk:
    `rehearse` passes the source on, so the missing ADF is never read."""
    source = convert.Source.detect(
        synthetic_save(tmp_path, game=convert.c64_port.by_key(CURSE_KEY)))
    direction = convert.C64ToAmiga(dos_port.CURSE_OF_THE_AZURE_BONDS)
    seen = []
    real = convert._amiga_destination_data

    def spy(shape, options, source=None):
        seen.append(source)
        return real(shape, options, source)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(convert, "_amiga_destination_data", spy)
        try:
            direction.rehearse(source, "A", tmp_path / "no-such-disk.adf",
                              names={"W" * 18: "Wren"})
        except FileNotFoundError:
            pytest.fail("the rehearsal opened the Amiga disk")
    assert seen == [source]


def test_a_pool_of_radiance_amiga_destination_asks_for_disk_two(tmp_path):
    """The C64 party's own disks for its combat figures, and disk 2 for the
    area's own script."""
    source = convert.Source.detect(synthetic_save(tmp_path))
    assert source.key == POOL_OF_RADIANCE

    assert saveplan.requirements(source, "amiga") == (
        saveplan.AMIGA_GAME_DISK, saveplan.SOURCE_DISKS)
    with pytest.raises(saveplan.MissingAssets) as caught:
        saveplan.resolve_assets(source, "amiga")
    assert caught.value.missing == (saveplan.AMIGA_GAME_DISK,
                                    saveplan.SOURCE_DISKS)


def test_every_dos_destination_asks_for_the_game_folder(tmp_path):
    """Measured rather than assumed: a Silver Blades DOS save stages no
    script and `goldbox.dos_codec` still reads the game folder to find which
    `ECL<n>.DAX` holds the area the party is standing in, so an Amiga Silver
    Blades party converted with no folder is refused."""
    path = amiga_disk(tmp_path)          # Curse, and the same holds for it
    source = convert.Source.detect(path)

    assert saveplan.requirements(source, "dos") == (saveplan.DOS_GAME_FOLDER,)
    with pytest.raises(saveplan.MissingAssets) as caught:
        saveplan.resolve_assets(source, "dos")
    assert caught.value.missing == (saveplan.DOS_GAME_FOLDER,)


def test_the_ports_a_save_as_offers_open_with_the_saves_own(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")

    assert saveplan.destination_ports(party.source) == ["dos", "c64", "amiga"]
    assert saveplan.route(party.source, "dos") is None


# ---------------------------------------------------------------------------
# A drop stops the save before anything is written
# ---------------------------------------------------------------------------

def _drop_into(monkeypatch, direction, field=None, loss=None):
    """Force a field onto a real conversion's own accounting."""
    real = direction.rehearse

    def rehearsed(*a, **kw):
        result = real(*a, **kw)
        if field:
            result.report.dropped.append(field)
        if loss:
            result.report.losses = [loss]
        return result

    monkeypatch.setattr(direction, "rehearse", rehearsed)


def test_a_truncated_name_stops_a_save_as_and_is_on_no_list_at_all(
        tmp_path):
    """The name a player typed fills the shared record's own name field, the
    destination's own field holds fifteen, and the conversion's accounting
    says nothing: neither `report.dropped` nor `report.losses` names it --
    the truncation is a line of `report.warnings` and nothing calls
    `Report.lost` for it. What refuses it is the output read back.

    No game data: Silver Blades stages no area script, so this is the one
    cross-platform direction that runs anywhere.
    """
    party, folder, _quantity = edited_dos_party(tmp_path / "save")
    before = files_under(folder)
    probe_name = string.ascii_uppercase[:NAME_SIZE]
    party.members[0].record.set("name", probe_name)
    out = tmp_path / "chosen.adf"

    source = convert.Source.of_snapshot(saveplan.prepare(party))
    direction = saveplan.route(source, "amiga")
    rehearsal, _slot = saveplan.rehearse(direction, source, saveplan.Assets())
    assert rehearsal.report.dropped == []
    assert rehearsal.report.losses == []
    assert saveplan.losses(rehearsal.report) == []

    with pytest.raises(saveplan.DroppedFields) as caught:
        saveplan.prepare_save_as(party, "amiga", out)

    assert caught.value.lost == [
        f"name: {probe_name!r} arrived as {probe_name[:15]!r}"]
    assert not out.exists()
    assert files_under(folder) == before


def test_the_comparison_names_the_field_and_both_of_its_values():
    """The guard at unit level, for the directions this machine cannot drive
    (every one needing a DOS game folder or the C64 game disks).

    A record whose gold the destination clamped is named with what went in
    and what came back, and a party that came back a character short is
    refused before any field is looked at.
    """
    records = [CharacterRecord.from_bytes(bytes(RECORD_SIZE))
               for _ in range(2)]
    for record, name in zip(records, ("ALPHA", "OMEGA")):
        record.set("name", name)
        record.set("gold", 1234)
    clamped = CharacterRecord.from_bytes(records[0].to_bytes())
    clamped.set("gold", 255)

    assert saveplan.compare(records, records) == []
    assert saveplan.compare(records, [clamped, records[1]]) == [
        "gold: 1234 arrived as 255"]
    assert saveplan.compare(records, records[:1]) == [
        "2 character(s) went in and 1 came back out"]


def _pair(first_gold, first_hp, second_gold, second_hp):
    """Two characters, told apart by their money and their hit points."""
    out = []
    for name, gold, hp in (("ALPHA", first_gold, first_hp),
                           ("OMEGA", second_gold, second_hp)):
        record = CharacterRecord.from_bytes(bytes(RECORD_SIZE))
        record.set("name", name)
        record.set("gold", gold)
        record.set("hp_max", hp)
        out.append(record)
    return out


def test_two_characters_values_swapping_places_is_a_difference(tmp_path):
    """Whole characters are compared, not each field on its own.

    Sorting every field by itself makes the party a bag of values: one
    character's 5,000 gold arriving on the other and the other's 10 arriving
    on him leaves every per-field multiset matching exactly, and the guard
    sees nothing at all.
    """
    expected = _pair(5000, 90, 10, 5)
    swapped = _pair(10, 90, 5000, 5)

    lost = saveplan.compare(expected, swapped)

    assert lost, "two characters' gold changed places and nothing was named"
    assert any(line.startswith("gold:") for line in lost)


def test_two_characters_the_sheet_holds_identical_still_match(tmp_path):
    """The multiset is of characters, so duplicates are not a difference."""
    twins = _pair(100, 20, 100, 20)
    twins[1].set("name", "ALPHA")

    assert saveplan.compare(twins, list(reversed(twins))) == []


@pytest.mark.parametrize("field", saveplan.KEPT_FIELDS)
def test_every_kept_field_is_a_refusal_when_it_changes(field):
    """Each of the kept fields, one at a time: change it in one of the two
    written records and the comparison names it.

    A name dropped out of `KEPT_FIELDS` fails no other test in this file,
    so each one is pinned by a case of its own.
    """
    expected = _pair(1234, 40, 99, 12)
    written = [CharacterRecord.from_bytes(record.to_bytes())
               for record in expected]
    raw = written[0].get_raw(field)
    written[0].set_raw(field, bytes((byte ^ 0x01) for byte in raw))
    assert written[0].get(field) != expected[0].get(field), field

    lost = saveplan.compare(expected, written)

    assert [line for line in lost if line.startswith(f"{field}:")], lost


def test_every_known_field_is_compared_or_named_as_not_compared():
    """The two lists are a partition of the layout's known fields.

    A known field in neither list is invisible to the guard, whatever the
    conversion does to it: `flags_0b8` went from 1 to 0 on twelve of the
    fifteen real Pool of Radiance C64 saves converted to DOS here until the
    ability-altered flag was given the byte DOS keeps it in, and the guard is
    what caught it.
    """
    known = {field.name for field in LAYOUT if field.is_known}
    kept, skipped = set(saveplan.KEPT_FIELDS), set(saveplan._NOT_COMPARED)

    assert kept & skipped == set()
    assert kept | skipped == known, {
        "in neither": sorted(known - kept - skipped),
        "in neither list of the layout": sorted((kept | skipped) - known)}


def test_a_c64_party_that_does_not_fit_a_dos_save_is_refused(tmp_path):
    """A conversion driven whole, with the player's own disks, whose C64
    party carries an eighteen-character name and 65,535 maximum hit points.

    Refusing the whole party for a name alone is the defect `#619`'s Stage A
    plan fixes: with no chosen replacement, `prepare_save_as` raises
    `NamesDoNotFit` naming that name, and only that -- no game writes 65,535
    hit points, so `hp_max`'s own clamp is not this test's business. With a
    replacement supplied, the party still refuses on `hp_max` alone, and the
    name is no longer among what it names.

    Skips where this machine's registry has no Pool of Radiance C64 disks or
    no DOS Pool of Radiance game folder.
    """
    files_for = _registry_game_files(POOL_OF_RADIANCE)
    game_folder = _dos_game_folder()
    if files_for is None or game_folder is None:
        pytest.skip("needs the Pool of Radiance C64 disks and DOS game folder")
    party = Party(str(synthetic_save(tmp_path)))
    assets = saveplan.Assets(dos_folder=game_folder, source_files=files_for)
    out = tmp_path / "copy"
    long_name = "W" * NAME_SIZE

    with pytest.raises(saveplan.NamesDoNotFit) as caught:
        saveplan.prepare_save_as(party, "dos", out, assets)
    assert caught.value.unfit == (long_name,)
    assert not out.exists()

    with pytest.raises(saveplan.DroppedFields) as caught:
        saveplan.prepare_save_as(party, "dos", out, assets,
                                 names={long_name: "W" * 15})

    named = {line.split(":", 1)[0] for line in caught.value.lost}
    assert "hp_max" in named and "name" not in named
    assert not out.exists()


@pytest.mark.parametrize("port", ["dos", "amiga"])
@pytest.mark.parametrize("chosen", ["RENAMED", "Renamed"])
def test_a_c64_name_too_long_for_dos_converts_under_the_name_the_player_chose(
        tmp_path, port, chosen):
    """You have a Commodore 64 Pool of Radiance save in which one character
    is called `ABCDEFGHIJKLMNOPQR`, eighteen letters. `File ▸ Save As…`
    refuses the whole party today over that one name, though every other
    field of every character would convert -- `.claude/rules/conversions.md`,
    "Refusing a save is not a fix". `#619`'s Stage A design instead asks for
    a name that fits the destination and converts the whole party once it
    has one.

    `chosen`, `RENAMED` or `Renamed`, is deliberately not a cut of the old
    name, so this cannot pass by truncating instead of asking. The mixed-case
    `Renamed` pins #638's guard: `stored_name` has to read the destination's
    own bytes rather than the sheet's C64-folded record, or a chosen name a
    DOS or Amiga save can hold as typed reports as arriving folded to
    capitals and refuses.

    Skips where this machine's registry has no Pool of Radiance C64 save
    disks or DOS game folder, or, for the Amiga destination, no Amiga Pool
    of Radiance disk 2.
    """
    from support.toamigapor import _por_disk_2

    saves = _c64_pool_saves()
    files_for = _registry_game_files(POOL_OF_RADIANCE)
    if not saves or files_for is None:
        pytest.skip("needs the Pool of Radiance C64 save disks")
    if port == "dos":
        game_folder = _dos_game_folder()
        if game_folder is None:
            pytest.skip("needs the DOS Pool of Radiance game folder")
        assets = saveplan.Assets(dos_folder=game_folder, source_files=files_for)
        out = tmp_path / "copy"
    else:
        disk2 = _por_disk_2(tmp_path)
        assets = saveplan.Assets(amiga_disk=disk2, source_files=files_for)
        out = tmp_path / "copy.adf"

    long_name = "ABCDEFGHIJKLMNOPQR"
    party = Party(str(saves[0]))
    party.members[0].record.set("name", long_name)

    with pytest.raises(saveplan.NamesDoNotFit) as caught:
        saveplan.prepare_save_as(party, port, out, assets)
    assert caught.value.unfit == (long_name,)
    assert not out.exists()

    plan = saveplan.prepare_save_as(party, port, out, assets,
                                    names={long_name: chosen})
    assert plan.report.losses == []
    published = saveplan.publish(plan, party, assets=assets,
                                 backups=tmp_path / "backups")

    written = Party(convert.Source.detect(out, slot=published.destination.slot))
    assert "RENAMED" in {member.record.get("name")
                         for member in written.members}
    assert chosen in {saveplan.stored_name(m) for m in written.members}

    expected = [saveplan.edited_record(member) for member in party.members]
    for record in expected:
        if record.get("name") == long_name:
            record.set("name", chosen)
    assert saveplan.compare(
        expected, [member.record for member in written.members]) == []


@pytest.mark.parametrize("port", ["dos", "amiga"])
def test_a_lower_case_c64_name_saves_as_dos_and_amiga_with_its_spelling(
        tmp_path, port):
    """You have a Commodore 64 Secret of the Silver Blades party in which
    Guy de Valois's name is spelled in mixed case -- Wish's own DOS-to-C64
    conversion wrote it that way before #290 folded that direction to
    capitals, and the C64 game has since saved the party again with the
    mixed-case bytes intact. `File ▸ Save As…` to DOS or the Amiga writes
    `Guy de Valois` exactly, as SSI's own DOS pregen and Amiga save do, but
    before this fix the read-back guard rebuilds the written destination's
    name through the sheet's C64-shaped record, which folds every name to
    capitals regardless of port -- so it refuses the whole party on `name:
    'Guy de Valois' arrived as 'GUY DE VALOIS'`, though the bytes just
    written are exactly right.

    Skips where this machine has no `WISH-SPEC-ssb-52-dialog-converted-
    resave` specimen (`tools/registry/specimens.py`), no Secret of the
    Silver Blades C64 disks (`automap/gamedisks.py`), or, per destination, no
    DOS archive (`$FR_ARCHIVES`) or no Amiga game disk to stage against.
    """
    from support.doslatertitles import _c64_disk

    from tools.convert import convertdrops
    from tools.dos import dosbox

    disk = _c64_disk("ssb-52-dialog-converted-resave")
    files_for = _registry_game_files(SILVER_BLADES.key)
    if files_for is None:
        pytest.skip("needs the Secret of the Silver Blades C64 disks")
    if port == "dos":
        try:
            game_dir = dosbox.find_game("SECRET")
        except FileNotFoundError:
            pytest.skip("needs the DOS Secret of the Silver Blades archive "
                       "($FR_ARCHIVES)")
        assets = saveplan.Assets(dos_folder=game_dir, source_files=files_for)
        out = tmp_path / "copy"
    else:
        amiga_disk = convertdrops.amiga_game_disks(tmp_path).get(
            SILVER_BLADES.key)
        if amiga_disk is None:
            pytest.skip("needs an Amiga game disk")
        assets = saveplan.Assets(amiga_disk=amiga_disk, source_files=files_for)
        out = tmp_path / "copy.adf"

    party = Party(str(disk))
    party.members[0].record.set_raw(
        "name", b"Guy de Valois".ljust(NAME_SIZE, b"\x00"))

    plan = saveplan.prepare_save_as(party, port, out, assets)
    assert saveplan.losses(plan.report) == []
    published = saveplan.publish(plan, party, assets=assets,
                                 backups=tmp_path / "backups")

    written = Party(convert.Source.detect(out, slot=published.destination.slot))
    assert "Guy de Valois" in {saveplan.stored_name(m)
                               for m in written.members}

    # The guard was pointed at the destination's own stored name, not
    # removed: a written destination that genuinely came back folded still
    # has to be refused.
    lost = saveplan.compare(
        [saveplan.edited_record(m) for m in party.members],
        [m.record for m in written.members],
        published.destination,
        expected_names=[saveplan.stored_name(m) for m in party.members],
        written_name_list=[saveplan.stored_name(m).upper()
                          for m in written.members])
    assert any(line.startswith("name:") for line in lost)


@pytest.mark.parametrize("port", ["dos", "amiga"])
def test_a_dos_or_amiga_character_renamed_on_the_sheet_saves_under_its_own_name(
        tmp_path, port):
    """You open a DOS or Amiga save, rename a character straight on the
    sheet -- `HERO1` becomes `Mixed Case` -- and use `File ▸ Save As…` to
    write a copy, never touching the name-fit chooser at all. This is the one
    case `#638 (Compare a converted character's name as the DOS or Amiga
    destination actually stores it, not through the C64 sheet's
    capitals-only field, so Save As keeps the player's own spelling)`'s own
    read-back guard cannot lean on `stored_name`'s port-native reading alone:
    the character being renamed is the *source* member, whose `native` is
    still the disk's original, unedited bytes, so a guard that read
    `stored_name(member)` here instead of the sheet's own new value would
    expect the save to still hold the character's old name and refuse a
    Save As that wrote the rename correctly.

    Needs no game data: this is a native DOS-to-DOS or Amiga-to-Amiga copy,
    built from the format rather than read off a disk.
    """
    if port == "dos":
        folder = dos_folder(tmp_path / "save")
        party = Party(str(folder))
        out = tmp_path / "copy"
    else:
        disk = amiga_disk(tmp_path)
        party = Party(str(disk))
        out = tmp_path / "copy.adf"

    original_name = party.members[0].record.get("name")
    party.members[0].record.set("name", "Mixed Case")

    plan = saveplan.prepare_save_as(party, port, out)
    published = saveplan.publish(plan, party, backups=tmp_path / "backups")

    written = Party(convert.Source.detect(out, slot=published.destination.slot))
    renamed = written.members[0]
    assert saveplan.stored_name(renamed) == "MIXED CASE"
    assert saveplan.stored_name(renamed) != original_name


def _curse_game_dir():
    """The DOS Curse archive's own game directory, or None."""
    from tools.dos import dosbox

    try:
        return dosbox.find_game("CURSE")
    except FileNotFoundError:
        return None


def test_a_trained_c64_curse_character_saves_as_dos_with_its_current_class(
        tmp_path):
    """You train a Curse of the Azure Bonds character at the C64 game's own
    training hall until he is a fighter 5 / thief 6, then use `File ▸ Save
    As…` to write a DOS copy. Curse's own trainer (`GEN $1939`) never updates
    the record's `char_class` byte, which still reads 0 -- a cleric, on a
    character with no cleric level at all. Before this fix, Save As refused
    the whole party with "char_class: 0 arrived as 14", though the DOS
    record it was about to write held the right class for a fighter/thief.

    Skips where this machine has no DOS Curse archive
    (`tools/registry/README.md`, `$FR_ARCHIVES`) or no Curse C64 disks
    (`automap/gamedisks.py`) -- the source's own combat-icon table, needed so
    this conversion reports no *other*, unrelated loss.
    """
    from gamedata import synthetic_party

    from goldbox import c64_port, c64_save
    from goldbox.savegame import SaveGame0

    game_dir = _curse_game_dir()
    files_for = _registry_game_files("curse-of-the-azure-bonds")
    if game_dir is None or files_for is None:
        pytest.skip("needs the DOS Curse archive ($FR_ARCHIVES) and the "
                   "Curse C64 disks")

    disk = tmp_path / "curse.d64"
    disk.write_bytes(synthetic_party(game=c64_port.CURSE_OF_THE_AZURE_BONDS))
    party = Party(str(disk))
    payload = bytearray(party.save0.to_bytes())
    # `synthetic_party` leaves the header at area 0, which is no area of
    # Curse at all; area 1, Tilverton's streets, is where the conversion
    # actually stages a script.
    payload[party.game.current_script] = 1
    # `synthetic_party` also leaves every slot's combat icon at zero, which
    # is not a shape the game's own ICON menu ever draws -- `default_icon`
    # is the 36 bytes a freshly rolled character actually gets (#57), so the
    # conversion can recognise each character's figure instead of reporting
    # one more loss this fix has nothing to do with.
    container = c64_save.container_for(party.game)
    default_icon = files_for.icon.default_icon()
    for i in range(len(party.members)):
        at = container.icon(i)
        payload[at:at + container.icon_size] = default_icon
    party.save0 = SaveGame0.from_bytes(bytes(payload), party.game)
    for i, member in enumerate(party.members):
        member.record.set("name", f"HERO{i}")    # `synthetic_party`'s own
                                                  # name is too wide for DOS
        member.record.set("hp_max", 30)          # `synthetic_party`'s own
                                                  # 65535 does not fit DOS's
                                                  # one-byte field
        member.record.set("strength_bonus_flag", 1)  # what the DOS writer
                                                      # always writes (#637)
    trained = party.members[0].record
    trained.set("class_bits", 0x0C)              # fighter | thief
    trained.set("level_fighter", 5)
    trained.set("level_thief", 6)
    trained.set("char_class", 0)                 # Curse's trainer never fixes this

    assets = saveplan.Assets(dos_folder=game_dir, source_files=files_for)
    out = tmp_path / "copy"

    plan = saveplan.prepare_save_as(party, "dos", out, assets)
    published = saveplan.publish(plan, party, assets=assets,
                                 backups=tmp_path / "backups")

    written = Party(convert.Source.detect(out, slot=published.destination.slot))
    record = written.members[0].record
    assert record.get("char_class") == 14        # fighter/thief, Curse's own table
    assert record.get("class_bits") == 0x0C
    assert record.get("level_fighter") == 5
    assert record.get("level_thief") == 6

    # The guard was narrowed, not disabled: an actually wrong class code
    # still has to show as a loss, so the read-back is corrupted by hand and
    # `compare` is asked directly rather than through another Save As (which
    # would refuse to write a destination this test never asks it to write).
    wrong = type(record)(record.to_bytes())
    wrong.set("char_class", 3)                   # anything but the real 14
    destination = saveplan.Destination(port="dos", path=out, slot="A",
                                       title=plan.destination.title, native=False)
    lost = saveplan.compare(
        [saveplan.edited_record(party.members[0])], [wrong], destination)
    assert any(line.startswith("char_class:") for line in lost)


def test_a_regained_c64_curse_caster_derives_turn_power_from_the_zeroed_level(
        tmp_path):
    """You have a Curse of the Azure Bonds character who dual-classed out of
    cleric into fighter and has since trained fighter far enough to regain
    the cleric class. The C64's own regain rule (`GEN $20A3`,
    `docs/209-the-regained-dual-class-on-dos.md`) stores the old cleric
    level back into the current level array, so the C64 record reads fighter
    8 / cleric 5 -- but a DOS record built the same way `#209` establishes
    keeps the regained class's level at zero in the current array and only
    in the former one, so DOS itself would turn undead as a non-caster
    (`turn_power` 0), not as a cleric 5.

    `_expected_char_class` already zeroes a regained former class's level
    before asking the destination's class-code table what the character's
    code is (#636); before this fix `_expected_turn_power` did not, and
    derived the DOS destination's expected `turn_power` from the stale,
    unzeroed cleric 5 instead -- the same wrong number a correct DOS write
    would never produce.

    Needs no game data: built from the format, and `_expected_turn_power` is
    asked directly rather than through a real Save As, since only the one
    derivation is under test here.
    """
    from gamedata import synthetic_party

    from goldbox import c64_port, derive

    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    disk = tmp_path / "curse.d64"
    disk.write_bytes(synthetic_party(game=game))
    party = Party(str(disk))
    record = party.members[0].record
    record.set("class_bits", 8)     # fighter alone: the current class
    record.set("level_fighter", 8)
    record.set("level_cleric", 5)   # the C64's own regain rule stores the
                                     # old level back into the current array
    record.set("dual_class_slot", 1)     # cleric's slot
    record.set("dual_class_level", 5)    # the level he left cleric at

    destination = saveplan.Destination(port="dos", path=tmp_path / "out",
                                       slot="A", title=game, native=False)

    stale = derive.turn_power(game, {"cleric": 5})
    assert stale != 0    # the C64's own stale cached byte would still turn
    assert saveplan._expected_turn_power(record, destination) == 0


def test_c64_cached_values_follow_the_dos_rules_without_weakening_the_guard(
        tmp_path, monkeypatch):
    """You use Save As on a C64 Curse of the Azure Bonds party carrying
    MATHEW and MARK, two paladins trained to level 5, and SHARA, a cleric
    trained to level 5. The DOS record it is about to write turns undead
    correctly -- DOS derives the power to turn from the stored class level
    every time the player presses TURN, rather than keeping a cached byte for
    it -- but Save As refuses the whole party anyway, because its read-back
    guard compares the C64's own stale cached bytes literally: `WISH-SPEC-
    curse-h-engine-resave`'s clerics and paladins still hold 0 at
    `turn_power` and `strength_bonus_flag`, the C64 engine's own values from
    before this specimen's last training, which DOS does not store at all.

    Before the fix this refuses with exactly `strength_bonus_flag: 0 arrived
    as 1`, `turn_power: 0 arrived as 3` (a paladin 5, who turns as a cleric
    two levels weaker) and `turn_power: 0 arrived as 6` (a cleric 5) --
    `goldbox.derive.turn_power`'s own table. After it, the save publishes and
    the DOS party reads back with the classes intact and both derived values
    matching what DOS itself would compute.

    Needs this machine's own DOS Curse archive (`tools.dos.dosbox.find_game`,
    `$FR_ARCHIVES`), the specimen tree (`$WISH_SPECIMENS`,
    `tools/registry/specimens.py`) holding this engine-written C64 specimen,
    and the Curse C64 disks for the source's own combat icon
    (`automap/gamedisks.py`) -- skips without any of the three.
    """
    from goldbox import c64_port, derive
    from tools.dos import dosbox

    try:
        game_dir = dosbox.find_game("CURSE")
    except FileNotFoundError:
        pytest.skip("needs the DOS Curse archive ($FR_ARCHIVES)")
    root = specimen_root()
    disk_path = (None if root is None else next(
        iter(root.glob("*-c64/WISH-SPEC-curse-h-engine-resave.[dD]64")), None))
    if disk_path is None:
        pytest.skip("needs ~/wish-specimens/*-c64/WISH-SPEC-curse-h-engine-"
                    "resave.D64 (tools/registry/specimens.py)")
    files_for = _registry_game_files("curse-of-the-azure-bonds")
    if files_for is None:
        pytest.skip("needs the Curse C64 disks (automap/gamedisks.py)")

    party = Party(str(disk_path))
    stored = {member.record.get("name"): member.record
             for member in party.members}
    # The specimen's own engine-written levels: pinned so a future edit to
    # the specimen or a misreading of it fails loudly here rather than
    # silently changing what this test proves.
    assert stored["MATHEW"].get("level_paladin") == 5
    assert stored["MARK"].get("level_paladin") == 5
    assert stored["SHARA"].get("level_cleric") == 5
    for record in stored.values():
        assert record.get("turn_power") == 0
        assert record.get("strength_bonus_flag") == 0

    assets = saveplan.Assets(dos_folder=game_dir, source_files=files_for)
    out = tmp_path / "copy"

    plan = saveplan.prepare_save_as(party, "dos", out, assets)
    published = saveplan.publish(plan, party, assets=assets,
                                 backups=tmp_path / "backups")

    written = Party(convert.Source.detect(out, slot=published.destination.slot))
    by_name = {member.record.get("name"): member.record
              for member in written.members}
    assert by_name["MATHEW"].get("level_paladin") == 5
    assert by_name["MARK"].get("level_paladin") == 5
    assert by_name["SHARA"].get("level_cleric") == 5

    for member in written.members:
        record = member.record
        neutral = {"cleric": record.get("level_cleric") or 0,
                  "paladin": record.get("level_paladin") or 0}
        want = derive.turn_power(c64_port.CURSE_OF_THE_AZURE_BONDS, neutral)
        assert record.get("turn_power") == want, record.get("name")
        assert record.get("strength_bonus_flag") == 1, record.get("name")
    assert by_name["MATHEW"].get("turn_power") == 3
    assert by_name["SHARA"].get("turn_power") == 6

    # The written DOS records themselves store `strength_bonus`, unlike the
    # C64's own cache of it -- read raw off the folder Save As actually
    # wrote, not through the C64-shaped sheet the assertion above already
    # covers.
    bonus_at = dos_port.FIELDS_BY_NAME_FOR[
        plan.destination.title.key]["strength_bonus"].offset
    chrdats = sorted(out.glob("CHRDAT*.SAV"))
    assert len(chrdats) == 6
    for path in chrdats:
        assert path.read_bytes()[bonus_at] == 1, path.name

    # The guard was narrowed to these two fields, not weakened: forcing the
    # read-back to report a genuinely different `gold` still refuses.
    real_written_records = saveplan.written_records

    def tampered(port, at, slot):
        records = real_written_records(port, at, slot)
        if records:
            record = type(records[0])(records[0].to_bytes())
            record.set("gold", (record.get("gold") or 0) + 12345)
            records[0] = record
        return records

    monkeypatch.setattr(saveplan, "written_records", tampered)
    with pytest.raises(saveplan.DroppedFields) as caught:
        saveplan.prepare_save_as(party, "dos", tmp_path / "copy2", assets)
    assert any(line.startswith("gold:") for line in caught.value.lost)


def test_a_dropped_field_stops_a_save_as_before_any_destination_write(
        tmp_path, monkeypatch):
    """The guard is the drop list itself: a conversion whose accounting
    names a field with no home in the destination is refused, and the
    destination, the source and the editor are exactly as they were."""
    party, folder, _quantity = edited_dos_party(tmp_path / "save")
    before = files_under(folder)
    out = tmp_path / "chosen.adf"
    _drop_into(monkeypatch, saveplan.route(party.source, "amiga"),
               field="ring of fire resistance")

    with pytest.raises(saveplan.DroppedFields) as caught:
        saveplan.prepare_save_as(party, "amiga", out)

    assert caught.value.lost == ["ring of fire resistance"]
    assert not out.exists()
    assert files_under(folder) == before
    assert party.members[0].record.get("gold") == 1234


def test_a_name_the_destination_could_not_hold_stops_it_too(
        tmp_path, monkeypatch):
    """`report.losses` is the other list a loss can be on -- a name too long
    for the destination's own field among them -- and it stops the save as
    firmly as the drop list does. There is no consent path."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    _drop_into(monkeypatch, saveplan.route(party.source, "amiga"),
               loss="ALPHABETICAL: name truncated to 15 characters")

    with pytest.raises(saveplan.DroppedFields) as caught:
        saveplan.prepare_save_as(party, "amiga", out)

    assert caught.value.lost == ["ALPHABETICAL: name truncated to 15 characters"]
    assert not out.exists()


def test_output_that_cannot_be_read_back_is_refused_before_publication(
        tmp_path, monkeypatch):
    """Validation is of the bytes, not of the writer's word for them."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    direction = saveplan.route(party.source, "amiga")
    real = direction.rehearse

    def rehearsed(*a, **kw):
        result = real(*a, **kw)
        result.files = {name: bytes(len(data))
                        for name, data in result.files.items()}
        return result

    monkeypatch.setattr(direction, "rehearse", rehearsed)

    with pytest.raises(saveplan.SaveAsError):
        saveplan.prepare_save_as(party, "amiga", out)
    assert not out.exists()


def test_an_image_destination_that_got_two_files_is_refused(
        tmp_path, monkeypatch):
    """An image destination is one file at one chosen path, so a conversion
    that produced two is a refusal rather than a coin toss over which of them
    the player gets."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    direction = saveplan.route(party.source, "amiga")
    real = direction.rehearse

    def rehearsed(*a, **kw):
        result = real(*a, **kw)
        result.files["SECOND.ADF"] = b"\x00"
        return result

    monkeypatch.setattr(direction, "rehearse", rehearsed)

    with pytest.raises(saveplan.SaveAsError):
        saveplan.prepare_save_as(party, "amiga", out)
    assert not out.exists()


# ---------------------------------------------------------------------------
# Publication, and putting it back
# ---------------------------------------------------------------------------

def test_replacing_an_image_backs_up_the_bytes_that_were_there(tmp_path):
    """Replacing an image replaces the whole image, so what it held is
    copied first."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = amiga_disk(tmp_path, name="target.adf")
    was = out.read_bytes()
    backups = tmp_path / "backups"

    published = saveplan.publish(
        saveplan.prepare_save_as(party, "amiga", out), party, backups=backups)

    assert published.backup is not None
    assert published.backup.read_bytes() == was
    assert out.read_bytes() != was


def test_replacing_an_image_with_no_backup_folder_writes_nothing(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = amiga_disk(tmp_path, name="target.adf")
    was = out.read_bytes()

    with pytest.raises(files.NoBackupFolder):
        saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                         party, backups=None)

    assert out.read_bytes() == was


def test_a_failed_open_of_what_was_published_puts_the_old_image_back(
        tmp_path, monkeypatch):
    """The destination is opened as part of publishing it. One that cannot
    be opened is rolled back here rather than handed to the editor."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = amiga_disk(tmp_path, name="target.adf")
    was = out.read_bytes()
    plan = saveplan.prepare_save_as(party, "amiga", out)
    monkeypatch.setattr(saveplan, "open_destination",
                        lambda _d: (_ for _ in ()).throw(RuntimeError("no")))

    with pytest.raises(saveplan.SaveAsError):
        saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert out.read_bytes() == was


def test_rolling_back_after_a_failed_adoption_restores_a_replaced_image(
        tmp_path):
    """Adoption fails in the window, after publication. The destination's
    own bytes come back from the backup."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = amiga_disk(tmp_path, name="target.adf")
    was = out.read_bytes()
    published = saveplan.publish(
        saveplan.prepare_save_as(party, "amiga", out), party,
        backups=tmp_path / "backups")
    assert out.read_bytes() != was

    published.roll_back()

    assert out.read_bytes() == was


def test_rolling_back_a_new_output_removes_it(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "new.adf"
    published = saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                                 party, backups=tmp_path / "backups")
    assert out.exists()

    published.roll_back()

    assert not out.exists()


def test_rolling_back_a_new_dos_folder_removes_the_whole_folder(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    published = saveplan.publish(saveplan.prepare_save_as(party, "dos", out),
                                 party, backups=tmp_path / "backups")
    assert sorted(p.name for p in out.iterdir())

    published.roll_back()

    assert not out.exists()


def test_recovery_that_itself_fails_says_where_the_backup_is(
        tmp_path, monkeypatch):
    """A rollback that cannot run is reported with the backup still named,
    rather than a claim that nothing was written."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = amiga_disk(tmp_path, name="target.adf")
    published = saveplan.publish(
        saveplan.prepare_save_as(party, "amiga", out), party,
        backups=tmp_path / "backups")
    monkeypatch.setattr(files, "restore_file",
                        lambda *_a: (_ for _ in ()).throw(OSError("read-only")))

    with pytest.raises(saveplan.RecoveryFailed) as caught:
        published.roll_back()

    assert caught.value.backup == published.backup
    assert published.backup.exists()


def test_rolling_back_a_new_output_removes_the_folders_it_made(tmp_path):
    """Publication makes whatever folders the chosen path needs; undoing it
    takes exactly those away again and leaves one that was already there."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    kept = tmp_path / "somewhere"
    kept.mkdir()
    out = kept / "new" / "deeper" / "chosen.adf"
    published = saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                                 party, backups=tmp_path / "backups")
    assert out.exists()

    published.roll_back()

    assert not out.exists()
    assert not (kept / "new").exists()
    assert kept.is_dir()


def test_a_failed_open_after_a_dos_folder_publish_leaves_no_destination(
        tmp_path, monkeypatch, caplog):
    """The image half of this is already covered; a folder destination is
    removed whole, and the failure is in the log with the path in it."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    plan = saveplan.prepare_save_as(party, "dos", out)
    monkeypatch.setattr(saveplan, "open_destination",
                        lambda _d: (_ for _ in ()).throw(RuntimeError("no")))

    with caplog.at_level("ERROR", logger="wish.editor.saveplan"):
        with pytest.raises(saveplan.SaveAsError):
            saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert not out.exists()
    assert any(str(out) in record.getMessage() for record in caplog.records)


def test_a_rollback_that_cannot_remove_a_new_output_says_so(
        tmp_path, monkeypatch):
    """A new output has no backup to point at, so the report is the failure
    itself rather than a claim that nothing was written."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "new.adf"
    published = saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                                 party, backups=tmp_path / "backups")
    monkeypatch.setattr(
        pathlib.Path, "unlink",
        lambda self, missing_ok=False: (_ for _ in ()).throw(
            OSError("read-only")))

    with pytest.raises(saveplan.RecoveryFailed) as caught:
        published.roll_back()

    assert caught.value.backup is None
    assert str(out) in str(caught.value)
    assert isinstance(caught.value.__cause__, OSError)


def test_a_rollback_that_cannot_clear_a_part_written_folder_names_what_is_left(
        tmp_path, monkeypatch):
    """The publication fails partway through moving files into a folder that
    was already there, and the removal that should undo it fails too. What
    comes back names the files still on disk and carries the original
    failure -- a bare `OSError` would report the second one and lose the
    first, and the next attempt would meet a target that is no longer
    empty."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    out.mkdir()
    plan = saveplan.prepare_save_as(party, "dos", out)
    moves = []
    real_replace = os.replace

    def replace(src, dst):
        moves.append(dst)
        if len(moves) > 2:
            raise OSError("no room")
        real_replace(src, dst)

    real_unlink = pathlib.Path.unlink

    def unlink(self, missing_ok=False):
        if self.parent == out:
            raise OSError("read-only")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(files.os, "replace", replace)
    monkeypatch.setattr(pathlib.Path, "unlink", unlink)

    with pytest.raises(files.RecoveryFailed) as caught:
        saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert len(caught.value.left) == 2
    assert all(path.parent == out for path in caught.value.left)
    assert "no room" in str(caught.value.__cause__)
    assert saveplan.RecoveryFailed is files.RecoveryFailed


def test_a_rollback_names_every_file_it_could_not_remove(tmp_path,
                                                         monkeypatch):
    """A folder publication leaves several files, and an undo that cannot
    remove the first goes on to the rest rather than stopping there with
    five more still on disk and unmentioned."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    published = saveplan.publish(saveplan.prepare_save_as(party, "dos", out),
                                 party, backups=tmp_path / "backups")
    assert len(published.written) > 1
    monkeypatch.setattr(
        pathlib.Path, "unlink",
        lambda self, missing_ok=False: (_ for _ in ()).throw(
            OSError("read-only")))

    with pytest.raises(saveplan.RecoveryFailed) as caught:
        published.roll_back()

    assert sorted(caught.value.left) == sorted(published.written)


def test_a_write_that_fails_takes_the_folders_it_made_away_again(
        tmp_path, monkeypatch):
    """The disk fills up as the output is written. The two folders
    publication made on the way to the chosen path go with it, rather than
    leaving an empty `~/new/place/` behind for a save that never landed."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    kept = tmp_path / "somewhere"
    kept.mkdir()
    out = kept / "new" / "deeper" / "chosen.adf"
    plan = saveplan.prepare_save_as(party, "amiga", out)
    monkeypatch.setattr(files.os, "fsync",
                        lambda _fd: (_ for _ in ()).throw(OSError("no room")))

    with pytest.raises(OSError):
        saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert not (kept / "new").exists()
    assert kept.is_dir()


def test_publishing_without_naming_the_assets_again_is_not_stale(tmp_path):
    """The plan keeps the game data it was prepared from, so a caller that
    does not hand the same assets back a second time gets its output
    published rather than a `StalePlan` for output that is current."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    assets = saveplan.Assets(amiga_disk=tmp_path / "nothing-here.adf")
    plan = saveplan.prepare_save_as(party, "amiga", out, assets)

    published = saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert published.party.members[0].record.get("gold") == 1234


# ---------------------------------------------------------------------------
# What `editor.files` guarantees about the two writes publication makes
# ---------------------------------------------------------------------------

#: Windows has no POSIX permission bits -- `os.stat().st_mode` reports 0o666
#: for every file regardless of what was requested, so the mode-bit half of
#: these two tests checks nothing there.

def test_replacing_a_file_keeps_the_permissions_it_had(tmp_path):
    """`tempfile.mkstemp` makes its file 0600 and the rename carries that
    over, so a save disk the player had shared with a group would quietly
    have become theirs alone."""
    target = tmp_path / "target.adf"
    target.write_bytes(b"old bytes")
    os.chmod(target, 0o664)

    files.replace_file(target, b"new bytes", tmp_path / "backups")

    assert target.read_bytes() == b"new bytes"
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == 0o664


def test_a_restore_writes_a_sibling_and_syncs_it_before_the_rename(
        tmp_path, monkeypatch):
    """A restore is the one write in a publication that could destroy both
    the old bytes and the new at once, so it goes through a temporary
    sibling like every other write here: a failure while it is being written
    leaves the file it is repairing exactly as it was, and leaves no
    temporary behind. A plain `shutil.copy2` passes neither half."""
    target = tmp_path / "target.adf"
    target.write_bytes(b"what publication left")
    backup = tmp_path / "backup"
    backup.write_bytes(b"what was there before")
    synced = []

    def fsync(fd):
        synced.append(fd)
        raise OSError("no room")

    monkeypatch.setattr(files.os, "fsync", fsync)

    with pytest.raises(OSError):
        files.restore_file(target, backup)

    assert synced                                  # it did sync, and failed
    assert target.read_bytes() == b"what publication left"
    assert [p for p in tmp_path.iterdir()
            if p.name.startswith(".target")] == []


def test_a_restore_puts_the_backups_mode_and_times_back(tmp_path):
    party_free = tmp_path / "target.adf"
    party_free.write_bytes(b"what publication left")
    backup = tmp_path / "backup"
    backup.write_bytes(b"what was there before")
    os.chmod(backup, 0o640)
    os.utime(backup, (1_000_000, 1_000_000))

    files.restore_file(party_free, backup)

    assert party_free.read_bytes() == b"what was there before"
    if sys.platform != "win32":
        assert stat.S_IMODE(party_free.stat().st_mode) == 0o640
    assert int(party_free.stat().st_mtime) == 1_000_000


def test_a_restore_whose_copystat_fails_leaves_the_target_as_it_was(
        tmp_path, monkeypatch):
    """The mode and the times go on the temporary, before the rename. After
    it, a `copystat` that raised would leave the bytes back and the caller
    reporting a rollback that did not happen."""
    target = tmp_path / "target.adf"
    target.write_bytes(b"what publication left")
    backup = tmp_path / "backup"
    backup.write_bytes(b"what was there before")
    monkeypatch.setattr(files.shutil, "copystat",
                        lambda *_a: (_ for _ in ()).throw(OSError("no")))

    with pytest.raises(OSError):
        files.restore_file(target, backup)

    assert target.read_bytes() == b"what publication left"
    assert [p for p in tmp_path.iterdir()
            if p.name.startswith(".target")] == []


def test_a_dos_target_that_already_holds_files_is_refused(tmp_path):
    """A folder with somebody else's save in it is not mixed into."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = dos_folder(tmp_path / "other", slot="B", numbers=(1,))
    before = files_under(out)

    with pytest.raises(files.TargetNotEmpty):
        saveplan.publish(saveplan.prepare_save_as(party, "dos", out),
                         party, backups=tmp_path / "backups")

    assert files_under(out) == before


def test_an_empty_dos_target_is_written_into(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "empty"
    out.mkdir()

    published = saveplan.publish(saveplan.prepare_save_as(party, "dos", out),
                                 party, backups=tmp_path / "backups")

    assert published.party.members[0].record.get("gold") == 1234
    assert not published.folder_created     # the folder was already there


def test_a_publication_that_fails_part_way_leaves_no_destination(
        tmp_path, monkeypatch):
    """The complete set is staged elsewhere and moved in, so an injected
    failure partway through the move leaves nothing of it behind."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    out.mkdir()
    plan = saveplan.prepare_save_as(party, "dos", out)
    moves = []
    real = os.replace

    def replace(src, dst):
        moves.append(dst)
        if len(moves) > 2:
            raise OSError("no room")
        real(src, dst)

    monkeypatch.setattr(files.os, "replace", replace)

    with pytest.raises(OSError):
        saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert len(moves) == 3            # two landed, the third refused
    assert list(out.iterdir()) == []


def test_a_failure_while_staging_never_reaches_a_new_destination(
        tmp_path, monkeypatch):
    """The set is built somewhere else first, so a failure while it is being
    written leaves the destination not merely empty but absent."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    plan = saveplan.prepare_save_as(party, "dos", out)
    synced = []
    real = os.fsync

    def fsync(fd):
        synced.append(fd)
        if len(synced) > 2:
            raise OSError("no room")
        real(fd)

    monkeypatch.setattr(files.os, "fsync", fsync)

    with pytest.raises(OSError):
        saveplan.publish(plan, party, backups=tmp_path / "backups")

    assert not out.exists()
    assert [p for p in tmp_path.iterdir() if p.name.startswith(".copy")] == []


# ---------------------------------------------------------------------------
# Prepared output that is no longer the answer
# ---------------------------------------------------------------------------

def test_an_edit_after_preparing_makes_the_prepared_output_stale(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    plan = saveplan.prepare_save_as(party, "amiga", out)
    assert plan.is_current(party, "amiga", out)

    party.members[0].record.set("gold", 4321)

    assert not plan.is_current(party, "amiga", out)


def test_another_destination_or_asset_makes_it_stale(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    plan = saveplan.prepare_save_as(party, "amiga", out)

    assert not plan.is_current(party, "amiga", tmp_path / "elsewhere.adf")
    assert not plan.is_current(party, "dos", out)
    assert not plan.is_current(
        party, "amiga", out,
        saveplan.Assets(amiga_disk=pathlib.Path("/elsewhere/disk2.adf")))


def test_an_invalidated_plan_is_refused_rather_than_published(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    plan = saveplan.prepare_save_as(party, "amiga", out)

    plan.invalidate()

    assert not plan.is_current(party, "amiga", out)
    with pytest.raises(saveplan.StalePlan):
        saveplan.publish(plan, party, backups=tmp_path / "backups")
    assert not out.exists()


def test_an_amiga_source_is_current_until_it_is_edited(tmp_path):
    """An Amiga party's own plan has to survive being compared with itself.

    `goldbox.amiga_adf.AmigaDisk.write_file` stamps every directory entry
    with the time of day, so two assemblies of an unedited disk differ in a
    handful of bytes and in nothing a save holds -- a key taken over the
    image would call an untouched party stale and refuse to publish it.
    """
    party = Party(str(amiga_disk(tmp_path, name="open.adf")))
    out = tmp_path / "chosen.adf"
    plan = saveplan.prepare_save_as(party, "amiga", out)

    assert plan.is_current(party, "amiga", out)

    party.members[0].record.set("gold", 4321)

    assert not plan.is_current(party, "amiga", out)


def test_a_dos_folders_other_saved_game_is_part_of_the_key(tmp_path):
    """A native copy carries the whole folder, so another slot's files
    changing changes what a Save As would write."""
    party, folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    plan = saveplan.prepare_save_as(party, "dos", out)
    assert plan.is_current(party, "dos", out)

    dos_folder(folder, slot="B", numbers=(1,))

    assert not plan.is_current(party, "dos", out)


def test_publishing_after_an_edit_is_refused_by_publish_itself(tmp_path):
    """Not the flag: `publish` recomputes the edits, the destination and the
    assets, so a caller that forgot to invalidate still cannot write bytes
    the player has edited past."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "chosen.adf"
    plan = saveplan.prepare_save_as(party, "amiga", out)

    party.members[0].record.set("gold", 4321)
    assert not plan.stale                  # nobody told it anything changed

    with pytest.raises(saveplan.StalePlan):
        saveplan.publish(plan, party, backups=tmp_path / "backups")
    assert not out.exists()


def test_the_game_data_behind_an_assets_path_is_in_its_token(tmp_path):
    """The paths are not the key: a game disk or an `ANIMATE00` that changed
    under a path that did not would otherwise leave a prepared output looking
    current."""
    import types

    disk = tmp_path / "disk2.adf"
    disk.write_bytes(b"one")
    folder = tmp_path / "game"
    folder.mkdir()
    (folder / "ECL1.DAX").write_bytes(b"script")
    animate = saveplan.Assets(game_files=types.SimpleNamespace(animate=b"a"))
    other = saveplan.Assets(game_files=types.SimpleNamespace(animate=b"b"))
    assert animate.token() != other.token()

    was = saveplan.Assets(amiga_disk=disk, dos_folder=folder).token()
    disk.write_bytes(b"two")
    assert saveplan.Assets(amiga_disk=disk, dos_folder=folder).token() != was

    was = saveplan.Assets(amiga_disk=disk, dos_folder=folder).token()
    (folder / "ECL1.DAX").write_bytes(b"another script")
    assert saveplan.Assets(amiga_disk=disk, dos_folder=folder).token() != was


# ---------------------------------------------------------------------------
# Destinations that are refused by their name or their place
# ---------------------------------------------------------------------------

def test_a_destination_without_the_right_suffix_is_refused(tmp_path):
    """The name decides whether the output can be opened again, so it is
    checked rather than left to the reader: `MySave` for an Amiga
    destination otherwise reaches validation and comes back as a sentence
    about a D64 image of 901,120 bytes."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")

    for port, name in (("amiga", "MySave"), ("amiga", "chosen.d64"),
                       ("c64", "chosen.adf"), ("c64", "chosen")):
        with pytest.raises(saveplan.SaveAsError) as caught:
            saveplan.prepare_save_as(party, port, tmp_path / name)
        assert str(caught.value).startswith(f"a {port} destination is a")
        assert not (tmp_path / name).exists()

    # The suffix is the player's to spell how they like.
    assert saveplan.prepare_save_as(party, "amiga", tmp_path / "SHOUTED.ADF")


def test_a_destination_inside_the_open_save_is_refused(tmp_path):
    """A DOS save is a folder, so a destination under it is the same
    collision as writing over the folder itself -- and a destination folder
    that holds the source is the other way round of it."""
    party, folder, _quantity = edited_dos_party(tmp_path / "save")
    before = files_under(folder)

    for port, path in (("amiga", folder / "inside.adf"),
                       ("dos", folder / "inside"),
                       ("dos", folder.parent)):
        with pytest.raises(saveplan.SaveAsError):
            saveplan.prepare_save_as(party, port, path)

    assert files_under(folder) == before


def test_a_destination_that_is_the_conversions_own_game_data_is_refused(
        tmp_path):
    """The game disks are read-only inputs and never a place to publish
    into: a Save As over one would overwrite the player's own game with a
    saved game.

    What is refused is the file or folder itself, and a destination folder
    that would swallow it -- **not everything underneath it**. A save beside
    the game disks, or a DOS save folder made inside the game folder,
    overwrites nothing and is the player's business.
    """
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    disk = tmp_path / "disk2.adf"
    disk.write_bytes(b"not really a disk")
    games = tmp_path / "games"
    game = games / "pool"
    game.mkdir(parents=True)
    pool = game / "POOL1.D64"
    pool.write_bytes(b"not really a disk either")

    with pytest.raises(saveplan.SaveAsError) as caught:
        saveplan.prepare_save_as(party, "amiga", disk,
                                 saveplan.Assets(amiga_disk=disk))
    assert "this conversion reads" in str(caught.value)
    # And a destination beside the game disks lands rather than being refused.
    assert saveplan.prepare_save_as(party, "amiga", game / "mine.adf",
                                    saveplan.Assets(amiga_disk=disk))

    # The rest against the check itself, which runs before the route needs
    # any of the game data these assets stand for.
    snapshot = saveplan.prepare(party)
    for path, assets in ((game, saveplan.Assets(dos_folder=game)),
                         (games, saveplan.Assets(dos_folder=game)),
                         (pool, saveplan.Assets(game_disks=(pool,))),
                         (game, saveplan.Assets(game_disks=(pool,))),
                         (game, saveplan.Assets(c64_folder=game))):
        with pytest.raises(saveplan.SaveAsError) as caught:
            saveplan.refuse_alias(path, snapshot, assets)
        assert "this conversion reads" in str(caught.value)
    for path, assets in ((game / "SAVE", saveplan.Assets(dos_folder=game)),
                         (game / "MYSAVE.D64",
                          saveplan.Assets(game_disks=(pool,))),
                         (game / "MYSAVE.D64",
                          saveplan.Assets(c64_folder=game))):
        saveplan.refuse_alias(path, snapshot, assets)      # allowed
    assert disk.read_bytes() == b"not really a disk"
    assert pool.read_bytes() == b"not really a disk either"


# ---------------------------------------------------------------------------
# What the accounting says about the route this file drives
# ---------------------------------------------------------------------------

def test_a_c64_destination_is_published_at_the_filename_that_was_chosen(
        tmp_path):
    """The Commodore 64 half of the proof, with the player's own disks: the
    writer names every disk it builds `PORSAVE<slot>.D64` and publication
    puts those bytes wherever the player said.

    Skips where this machine's registry (`automap/gamedisks.py`) has no Pool
    of Radiance disks: the destination's combat icon tables and `ANIMATE00`
    are on them and may not be stored here.
    """
    files_for = _registry_game_files(POOL_OF_RADIANCE)
    if files_for is None:
        pytest.skip("needs the Pool of Radiance C64 game disks")
    folder = dos_folder(tmp_path / "save", deltas=dos_port.POOL_OF_RADIANCE)
    party = Party(str(folder))
    party.members[0].record.set("gold", 1234)
    out = tmp_path / "chosen.d64"

    assets = saveplan.resolve_assets(party.source, "c64",
                                     game_files=lambda _game: files_for)
    plan = saveplan.prepare_save_as(party, "c64", out, assets)
    published = saveplan.publish(plan, party, assets=assets,
                                 backups=tmp_path / "backups")

    assert list(plan.files) == ["PORSAVEA.D64"]     # the writer's own name
    assert saveplan.losses(plan.report) == []
    assert published.destination.path == out
    # The letter the conversion read *from* is the source's; the C64 save it
    # wrote holds one saved game and names no slot.
    assert published.destination.slot is None
    # Read out of the save's own slots rather than through the published
    # party: `support.neutralrecords._filled` rolls every ability 1 to 6,
    # below the 3-to-25 window `goldbox.savegame.looks_occupied` calls a
    # character, so the editor shows a roster of nobody for a synthetic
    # party on the C64. The records themselves are in the save.
    _game, save0, _save1 = load_save(D64.open(str(out)))
    written = {slot.window[:5]: slot.window for slot in save0.slots}
    assert b"HERO1" in written
    record = CharacterRecord(written[b"HERO1"] + bytes(RECORD_SIZE - SLOT_STRIDE),
                             stored_size=SLOT_STRIDE)
    assert record.get("gold") == 1234


def _dos_game_folder():
    """The DOS Pool of Radiance game folder this machine's registry leads to,
    or None -- recognised by holding the `ECL<n>.DAX` area scripts every DOS
    destination is written against rather than by its path."""
    from automap import gamedisks

    where = gamedisks.find("por-dos-play")
    if where is None:
        return None
    folder = pathlib.Path(where)
    return folder if any(folder.glob("ECL*.DAX")) else None


def _c64_pool_saves():
    """Every Pool of Radiance C64 save disk this machine's registry leads to,
    roster disks among them -- `PORSAVE*.D64` beside the game disks."""
    from automap import gamedisks

    where = gamedisks.find(POOL_OF_RADIANCE)
    if where is None:
        return []
    return sorted(pathlib.Path(where).glob("PORSAVE*.[dD]64"))


def _registry_game_files(key):
    """The icon tables and `ANIMATE00` off whichever disks this machine's own
    registry leads to, or None -- `editor.window.EditorBinding.game_files_for`
    is what does this in the running program, off preferences."""
    from automap import gamedisks
    from editor.dosimport import GameFiles
    from goldbox import dos_codec
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = gamedisks.find(key)
    if where is None:
        return None
    icon = animate = None
    for disk in sorted(pathlib.Path(where).glob("*.[dD]64")):
        if icon is None:
            try:
                icon = IconParts.load(str(disk))
            except Exception:
                pass
        if animate is None:
            try:
                animate = load_payload(str(disk), dos_codec.ANIMATE_FILE)
            except Exception:
                pass
    if icon is None or animate is None:
        return None
    return GameFiles(icon=icon, animate=animate, portraits=None)


def test_the_silver_blades_dos_to_amiga_conversion_loses_nothing(tmp_path):
    """The sample is one party of two characters, built from the format: both
    lists a loss can be on are empty."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")

    plan = saveplan.prepare_save_as(party, "amiga", tmp_path / "chosen.adf")

    assert saveplan.losses(plan.report) == []
    assert len(party.members) == 2
    assert plan.destination.title.key == SILVER_BLADES.key


def test_a_dos_curse_party_not_yet_set_out_asks_for_no_amiga_game_disk(tmp_path):
    """The DOS party-menu save converts to an Amiga save with no `ECL.GLB`, so
    the dialog asks for no disk 2 either."""
    import shutil

    from support.dossave import _game_dirs
    saves = _game_dirs().get("CURSE")
    if saves is None or not (saves / "SAVGAMA.DAT").is_file():
        pytest.skip("needs the archives' shipped Curse saves")
    folder = tmp_path / "Saves"
    shutil.copytree(saves, folder)
    source = convert.Source.detect(folder)
    assert source.port == "dos"
    assert saveplan.requirements(source, "amiga") == ()


def test_an_unreadable_dos_curse_save_still_asks_for_the_amiga_game_disk(
        tmp_path, monkeypatch):
    """The requirement question does not read the save's error: the
    conversion reports it, as it did before the question looked inside."""
    shape = dos_port.CURSE_OF_THE_AZURE_BONDS
    container = convert.dos_savegame.container_for(shape.key)
    (tmp_path / f"SAVGAMA{container.suffix}").write_bytes(b"\0" * 16)

    def refuse(*_args, **_kwargs):
        raise convert.dos_codec.DosRecordError("unreadable")

    monkeypatch.setattr(convert.world_state, "from_dos", refuse)
    source = convert.Source(port="dos", title=shape, path=tmp_path, slot="A")

    assert convert.amiga_needs_game_disk(shape, source) is True
    assert saveplan.requirements(source, "amiga") == (saveplan.AMIGA_GAME_DISK,)
