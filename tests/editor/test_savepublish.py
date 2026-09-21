"""Preparing a Save As, refusing one that would lose a field, and publishing.

Everything here is built from the format rather than copied off a disk, so it
runs with no game data at all -- `test_saveplan.py`'s own builders, and the
one cross-platform direction that needs no file off the player's disks (DOS
Secret of the Silver Blades to an Amiga save disk, which stages no area
script). The native copies need no game data on any port.

Failures are injected rather than waited for: a dropped field forced into a
conversion's own accounting, a publication whose rename fails, and an
adoption that never happens, each with the state afterwards asserted.
"""
from __future__ import annotations

import os
import pathlib

import pytest
from gamedata import synthetic_save
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
from goldbox.record import RECORD_SIZE, CharacterRecord
from goldbox.savegame import SLOT_STRIDE, load_save

POOL_OF_RADIANCE = "pool-of-radiance"


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


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

    published = saveplan.publish(plan, backups=tmp_path / "backups")

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
                                 backups=tmp_path / "backups")

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
    published = saveplan.publish(plan, backups=tmp_path / "backups")

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
                                 backups=tmp_path / "backups")

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
                                 backups=tmp_path / "backups")

    assert published.destination.slot is None      # a C64 save has no letter
    assert published.party.members[0].record.get("gold") == 999
    assert out.read_bytes() != before
    assert path.read_bytes() == before


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
    """Silver Blades stages no area script, so its Amiga writer needs nothing
    -- the old Convert window asked every Amiga destination alike for disk
    2."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")

    assert saveplan.requirements(party.source, "amiga") == ()
    assert saveplan.resolve_assets(party.source, "amiga") == saveplan.Assets()


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
        saveplan.prepare_save_as(party, "amiga", out), backups=backups)

    assert published.backup is not None
    assert published.backup.read_bytes() == was
    assert out.read_bytes() != was


def test_replacing_an_image_with_no_backup_folder_writes_nothing(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = amiga_disk(tmp_path, name="target.adf")
    was = out.read_bytes()

    with pytest.raises(files.NoBackupFolder):
        saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                         backups=None)

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
        saveplan.publish(plan, backups=tmp_path / "backups")

    assert out.read_bytes() == was


def test_rolling_back_after_a_failed_adoption_restores_a_replaced_image(
        tmp_path):
    """Adoption fails in the window, after publication. The destination's
    own bytes come back from the backup."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = amiga_disk(tmp_path, name="target.adf")
    was = out.read_bytes()
    published = saveplan.publish(
        saveplan.prepare_save_as(party, "amiga", out),
        backups=tmp_path / "backups")
    assert out.read_bytes() != was

    published.roll_back()

    assert out.read_bytes() == was


def test_rolling_back_a_new_output_removes_it(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "new.adf"
    published = saveplan.publish(saveplan.prepare_save_as(party, "amiga", out),
                                 backups=tmp_path / "backups")
    assert out.exists()

    published.roll_back()

    assert not out.exists()


def test_rolling_back_a_new_dos_folder_removes_the_whole_folder(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "copy"
    published = saveplan.publish(saveplan.prepare_save_as(party, "dos", out),
                                 backups=tmp_path / "backups")
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
        saveplan.prepare_save_as(party, "amiga", out),
        backups=tmp_path / "backups")
    monkeypatch.setattr(files, "restore_file",
                        lambda *_a: (_ for _ in ()).throw(OSError("read-only")))

    with pytest.raises(saveplan.RecoveryFailed) as caught:
        published.roll_back()

    assert caught.value.backup == published.backup
    assert published.backup.exists()


def test_a_dos_target_that_already_holds_files_is_refused(tmp_path):
    """A folder with somebody else's save in it is not mixed into."""
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = dos_folder(tmp_path / "other", slot="B", numbers=(1,))
    before = files_under(out)

    with pytest.raises(files.TargetNotEmpty):
        saveplan.publish(saveplan.prepare_save_as(party, "dos", out),
                         backups=tmp_path / "backups")

    assert files_under(out) == before


def test_an_empty_dos_target_is_written_into(tmp_path):
    party, _folder, _quantity = edited_dos_party(tmp_path / "save")
    out = tmp_path / "empty"
    out.mkdir()

    published = saveplan.publish(saveplan.prepare_save_as(party, "dos", out),
                                 backups=tmp_path / "backups")

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
        saveplan.publish(plan, backups=tmp_path / "backups")

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
        saveplan.publish(plan, backups=tmp_path / "backups")

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
        saveplan.publish(plan, backups=tmp_path / "backups")
    assert not out.exists()


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
    published = saveplan.publish(plan, backups=tmp_path / "backups")

    assert list(plan.files) == ["PORSAVEA.D64"]     # the writer's own name
    assert saveplan.losses(plan.report) == []
    assert published.destination.path == out
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
