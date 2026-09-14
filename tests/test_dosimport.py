from __future__ import annotations


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


"""`editor/dosimport.py`: `editor/convert.py`'s own DOS-to-C64 helper.

The conversion itself is `tests/test_dosconvert.py`'s. What is tested here is
`rehearse`, `pane_text`, `name_warnings` and `log_unshown_losses` -- the
functions `editor/convert.py`'s `ConvertDialog` calls in for -- plus the two
`#176 (A player importing a Curse of the Azure Bonds save is shown an issue
number)` refusal tests that build no dialog at all. This module carried a
window in its own right, `DosImportDialog`, from 2026-08-24 until it was
deleted along with `File ▸ Import` on 2026-09-14 (`#52 (File ▸ Import and
File ▸ Export for every direction the library supports)`); what tested that
window is ported to `tests/test_convert.py` against `ConvertDialog`, noted
in place here rather than silently gone.

Both halves need somebody's files. The DOS save is Donald's unpacked copy of
*Forgotten Realms: The Archives* (`$FR_ARCHIVES`) and the game disks are his
`POOL*.D64`; with either missing the tests that need them skip, which is what
CI does. Nothing here opens a window: `tests/conftest.py` forces the offscreen
platform before Qt is imported.
"""


import gamedata
import pytest
from gamedata import disk_dir
from test_dossave import _save_dir, needs_dos_saves

from goldbox import dos_codec

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


@pytest.fixture
def app():
    """The session-wide application `tests/conftest.py` holds a reference to."""
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dos_save():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES")
    return where


@pytest.fixture
def files():
    """The icon and `ANIMATE00`, read off the player's own disks.

    The two live on different sides -- `SPELLE64`/`SPELLN64` on the
    character-creation disk and `ANIMATE00` on all eight -- so each is found
    by trying to read it, which is what `EditorBinding._find_disk` does in the
    running program.
    """
    from editor.dosimport import GameFiles
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts

    where = disk_dir()
    if where is None:
        pytest.skip("needs the game disks")
    icon = animate = None
    for disk in sorted(where.glob("POOL*.[dD]64")):
        try:
            if icon is None:
                icon = IconParts.load(str(disk)).default_icon()
        except Exception:
            pass
        try:
            if animate is None:
                animate = load_payload(str(disk), dos_codec.ANIMATE_FILE)
        except Exception:
            pass
    if icon is None or animate is None:
        pytest.skip("the game disks here carry neither SPELLE64 nor ANIMATE00")
    # No `portraits`: the creation menu is stored (2026-09-06), so a
    # conversion without one read off the disks still gives every character
    # his own face, and a fixture that skipped for want of `GEN` would skip
    # for nothing.
    return GameFiles(icon=icon, animate=animate)


# --- the rehearsal, which is the whole point --------------------------------

@needs_dos_saves
@needs_disks
def test_the_conversion_is_rehearsed_and_writes_nothing(dos_save, files,
                                                        tmp_path, monkeypatch):
    """`rehearse` builds the converted disk in memory and touches no file at
    all. Everything downstream depends on that: the report cannot be shown
    before the write unless there is a conversion with no write in it.

    It now has no template to leave alone either, so what this asserts is the
    stronger thing -- the directory it was pointed at is unchanged and the
    working directory has gained nothing. The working-directory half is an
    empty `tmp_path` this runs inside, because a relative path written by
    accident lands there and nowhere else.
    """
    from editor.dosimport import rehearse

    monkeypatch.chdir(tmp_path)
    before = sorted((p.name, p.stat().st_mtime, p.stat().st_size)
                    for p in dos_save.iterdir() if p.is_file())
    conversion = rehearse(dos_save, "A", files)
    after = sorted((p.name, p.stat().st_mtime, p.stat().st_size)
                   for p in dos_save.iterdir() if p.is_file())
    assert after == before
    assert sorted(p.name for p in tmp_path.iterdir()) == []
    assert len(conversion.disk.to_bytes()) == 174848


@needs_dos_saves
@needs_disks
def test_the_converted_disk_carries_the_two_files_and_nothing_else(
        dos_save, files):
    """Thirteen of the player's fifteen save disks hold `SAVEDGAME1` and
    `SAVEDGAME0` in that order and nothing else, so that is what a disk built
    from nothing has to be -- and it has to read back as a Pool of Radiance
    save with this party in it."""
    from editor.dosimport import rehearse
    from goldbox.savegame import load_save

    conversion = rehearse(dos_save, "A", files)
    names = [bytes(e.name) for e in conversion.disk.directory()]
    assert names == [b"SAVEDGAME1", b"SAVEDGAME0"]
    game, sg0, _sg1 = load_save(conversion.disk)
    assert game.key == conversion.game.key
    read_back = [s.record.name for s in sg0.slots if s.occupied]
    assert read_back == [c.name for c in dos_codec.read_party(dos_save, "A")][::-1]


@needs_dos_saves
@needs_disks
def test_nothing_in_the_converted_save_is_left_to_a_previous_owner(
        dos_save, files):
    """The whole of #118 in one assertion: every one of the 9216 bytes has a
    provenance and none of them is "whatever was already there".

    `unwritten` is the list of offsets the conversion did not write. Against a
    template it holds 5405 of them; from nothing it must be empty, and
    `new_save` refuses rather than returning a save it cannot account for.
    """
    from editor.dosimport import rehearse

    report = rehearse(dos_save, "A", files).report
    assert report.unwritten == []
    assert report.unaccounted == []
    assert len(report.sources) == report.total == 9216


#: `test_a_conversion_with_messages_a_drop_and_a_platform_loss_shows_
#: nothing`, which drove this against `DosImportDialog` itself, is ported
#: to `tests/test_convert.py` against `ConvertDialog` -- deleted with the
#: dialog on 2026-09-14 (`#52 (File ▸ Import and File ▸ Export for every
#: direction the library supports)`), missed by that ticket's own plan as
#: one of the four to port because it sat in this section, which the plan
#: otherwise kept whole.


def test_pane_text_is_the_messages_and_never_the_drops():
    """The renderer alone: the messages one to a line; `report.dropped`
    never reaches the returned text -- Donald's ruling of 2026-09-08
    (`.claude/rules/conversions.md`) took the drop list out of what a
    player reads, and `test_pane_text_sends_the_drops_to_the_debug_log_
    instead_of_the_pane` below is where it went instead.

    Before that ruling this test was named
    `test_pane_text_is_the_messages_then_the_drops` and asserted the
    opposite -- that `report.dropped` was joined on after a blank line."""
    from editor.dosimport import pane_text
    from goldbox.dos_codec import NOT_SET_OUT, C64SaveReport, Report

    report = C64SaveReport(save0_size=0x1C00)
    report.messages.extend([NOT_SET_OUT, "Second line."])
    assert pane_text(report) == f"{NOT_SET_OUT}\nSecond line."
    report.dropped.extend(["A drop line", "Another"])
    assert pane_text(report) == f"{NOT_SET_OUT}\nSecond line."
    plain = Report()
    assert pane_text(plain) == ""
    plain.dropped.append("Only a drop")
    assert pane_text(plain) == ""


def test_pane_text_puts_a_loss_after_the_messages_and_never_a_drop():
    """#399 (A conversion that runs out of item or trait slots tells the
    player nothing, because the pane never shows a warning): `losses` is a
    second source `pane_text` reads, after `messages`, with the same
    blank-line rule -- and `report.dropped` joins neither, on the same
    2026-09-08 ruling as the test above."""
    from editor.dosimport import pane_text
    from goldbox.dos_codec import NOT_SET_OUT, C64SaveReport, Report

    report = C64SaveReport(save0_size=0x1C00)
    report.losses.append("WISHFTR: 20 items and the C64 has sixteen slots; "
                         "4 dropped from the end")
    assert pane_text(report) == \
        ("WISHFTR: 20 items and the C64 has sixteen slots; "
         "4 dropped from the end")
    report.messages.append(NOT_SET_OUT)
    report.dropped.append("A drop line")
    assert pane_text(report) == (
        f"{NOT_SET_OUT}\n\n"
        "WISHFTR: 20 items and the C64 has sixteen slots; "
        "4 dropped from the end")
    plain = Report()
    plain.dropped.append("Only a drop")
    assert pane_text(plain) == ""


def test_pane_text_sends_the_drops_to_the_debug_log_instead_of_the_pane():
    """The accounting still exists -- it goes to `WISH_DEBUG`'s file
    (`wish/debuglog.py`) rather than to the pane, so a bug report can still
    say what a conversion left behind (`.claude/rules/conversions.md`,
    Donald's ruling of 2026-09-08). Proven by turning the log on for real
    and reading the file it wrote, not by mocking the logger."""
    from editor.dosimport import pane_text
    from goldbox.dos_codec import Report
    from wish import debuglog

    debuglog.start()
    try:
        report = Report()
        report.dropped.extend(["field_one: has nowhere to go",
                               "field_two: not understood yet"])
        text = pane_text(report)
        log_text = debuglog.path().read_text(encoding="utf-8")
    finally:
        debuglog.stop()

    assert "field_one" not in text and "field_two" not in text
    assert "field_one" in log_text and "field_two" in log_text
    # Every line a person reads opens with a capital letter
    # (`.claude/rules/gui-text.md`), the debug log included -- the composed
    # line, not the field names inside it, which stay lower case.
    assert "Not converted:" in log_text


def test_name_warnings_keeps_only_the_truncated_name():
    """Donald's ruling of 2026-09-10, on being shown three lines
    `write_c64_save` puts on `C64SaveReport.losses` alike: a name DOS's own
    fifteen-character field could not hold whole is real and a player is
    entitled to see it; a magic-user memorising more spells than the
    destination title's own slots (#508) and a spell id outside the
    destination's own book (#509) are bugs, not platform limits, and
    `name_warnings` is the filter that keeps the second two off whatever
    reads its return.

    Fails before the fix: with no filter, `name_warnings` returning the
    whole list makes the second assert below fail on the spell-count line
    -- seen red by reverting the body to `return list(report.losses)`,
    then the fix put back.
    """
    from editor.dosimport import name_warnings
    from goldbox.dos_codec import C64SaveReport

    report = C64SaveReport(save0_size=0x1C00)
    report.losses.extend([
        "SOVELISS: Name 'Soveliss the Magnificent' is longer than the DOS "
        "15 characters; truncated",
        "MIALEE: 8 spells memorised and Curse of the Azure Bonds has 6 "
        "slots; the rest dropped",
        "MIALEE: Spell id 71 is outside the Pool of Radiance book's ids "
        "1-64"])

    assert name_warnings(report) == [
        "SOVELISS: Name 'Soveliss the Magnificent' is longer than the DOS "
        "15 characters; truncated"]


def test_log_unshown_losses_keeps_the_evidence_out_of_the_players_way():
    """The other half of the same split: everything `name_warnings` leaves
    out goes to the debug log, not nowhere -- the evidence #508 and #509
    need, without putting an excuse in front of a player. Donald,
    2026-09-10: *"Things like this are WHY we have to remove the Convert
    dialog... We need it to be correct."* Proven by turning the log on for
    real and reading the file it wrote, the same recipe
    `test_pane_text_sends_the_drops_to_the_debug_log_instead_of_the_pane`
    above uses.
    """
    from editor.dosimport import log_unshown_losses
    from goldbox.dos_codec import C64SaveReport
    from wish import debuglog

    report = C64SaveReport(save0_size=0x1C00)
    report.losses.extend([
        "SOVELISS: Name 'Soveliss' is longer than the DOS 15 characters; "
        "truncated",
        "MIALEE: 8 spells memorised and Curse of the Azure Bonds has 6 "
        "slots; the rest dropped"])

    debuglog.start()
    try:
        log_unshown_losses(report)
        log_text = debuglog.path().read_text(encoding="utf-8")
    finally:
        debuglog.stop()

    assert "Soveliss" not in log_text
    assert "MIALEE" in log_text and "8 spells memorised" in log_text


@pytest.mark.skipif(not gamedata.have_specimen("por-item-twenty"),
                    reason="needs the twenty-item specimen")
def test_a_real_conversion_that_truncates_items_shows_nothing_in_the_pane():
    """The same specimen `#399 (A conversion that runs out of item or trait
    slots tells the player nothing, because the pane never shows a
    warning)`'s own measurement used, driven through `dos_codec.convert_save`
    exactly as `rehearse` drives it -- no game disks needed, since neither
    the combat icon nor `ANIMATE00` change whether the inventory truncates.

    `#399` drafted a sentence for this specimen reaching the pane; a
    950-character census across every C64 disk, DOS archive, played save
    and specimen on the machine found this manufactured character is the
    only one anywhere over sixteen items, and Donald ruled the sentence
    unneeded: "I agree that we do not need the sentences."  So the sixteenth
    item still fits and the rest are still dropped -- nothing says so.
    """
    from editor.dosimport import pane_text

    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos_codec.convert_save(gamedata.specimen("por-item-twenty"), "G",
                              save0, save1)
    text = pane_text(report)
    assert "carry only sixteen" not in text
    # And none of this project's own bookkeeping about the party as a whole.
    assert "quest-flag" not in text
    assert "emptied" not in text


@pytest.mark.skipif(not gamedata.have_specimen("por-party-l1"),
                    reason="needs the party-l1 specimen")
def test_a_real_conversion_that_truncates_nothing_shows_no_loss_line():
    """The control: `WISH-SPEC-por-party-l1` has nothing over any ceiling, so
    the pane must show no line about one -- the case that fails if `losses`
    were ever wired from `report.warnings` wholesale instead."""
    from editor.dosimport import pane_text

    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos_codec.convert_save(gamedata.specimen("por-party-l1"), "C",
                              save0, save1)
    text = pane_text(report)
    assert "do not fit" not in text
    assert "quest-flag" not in text
    assert "emptied" not in text


#: `DosImportDialog`'s own window tests and its refusal-when-disks-missing
#: tests -- `test_the_rehearsal_is_complete_before_the_button_is_
#: pressable`, `test_a_pool_of_radiance_import_with_no_creation_tables_
#: converts_with_its_own_faces`, `test_the_save_points_at_the_area_the_
#: dos_party_is_in`, `test_changing_the_slot_re_rehearses`, `test_the_
#: slots_offered_are_the_ones_the_folder_holds`, `test_no_game_disks_is_a_
#: pop_up_and_no_folder_picker`, `test_with_the_game_disks_there_the_
#: import_gets_as_far_as_the_picker`, `test_a_disk_that_loads_once_but_
#: fails_on_the_second_read_refuses`, `test_the_game_files_an_import_
#: needs_are_the_icon_and_animate`, `test_the_game_files_an_import_needs_
#: include_the_creation_menu`, `test_an_import_started_from_the_window_
#: carries_its_own_faces` -- are deleted along with the dialog, its menu
#: entry and `EditorBinding.import_dos_save`/`game_files_for_import`
#: (`#52 (File ▸ Import and File ▸ Export for every direction the library
#: supports)`, 2026-09-14). `editor.convert.ConvertDialog` and
#: `EditorBinding.game_files_for` are the survivors these tested against;
#: `tests/test_convert.py` covers them.


# --- what reaches the editor -------------------------------------------------

@needs_dos_saves
@needs_disks
def test_the_import_lands_with_no_file_behind_it_and_save_as_writes_it(
        app, tmp_path, dos_save, files, monkeypatch):
    """The converted party is in the window, marked dirty, and there is **no
    path**: the disk was built in memory a moment ago and no file it could
    have come from exists. Save As is what names one, and that is the write.

    `File ▸ Import` -- the route that made this state reachable for a
    player -- is gone (`#52 (File ▸ Import and File ▸ Export for every
    direction the library supports)`, 2026-09-14), and so is
    `EditorBinding.adopt_conversion`. The guard stays, because the state is
    still constructible from inside `EditorBinding`: a `Party` built from a
    rehearsal's own bytes, adopted with no path, exactly the three lines
    `adopt_conversion` used to be.
    """
    import editor.window as ew
    from editor.dosimport import rehearse
    from editor.roster import Party
    from editor.window import EditorBinding

    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"))
    conversion = rehearse(dos_save, "A", files)
    party = Party("", game=conversion.game, disk=conversion.disk)
    window._adopt(party, None, dirty=True)

    assert window.dirty                      # unsaved, and the title says so
    assert window.path is None, "an import has no file behind it"
    # The converter puts DOS marching position 0 in the *highest* C64 slot
    # (#101, `dos_codec.marching_slot`), and the roster now lists the highest
    # occupied slot first (`#160`) -- so the window's own order is DOS's,
    # not its reverse.
    names = [m.name for m in window.party.members if m.name]
    assert names == [c.name for c in dos_codec.read_party(dos_save, "A")]

    out = tmp_path / "NEW.D64"
    monkeypatch.setattr(ew.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    window.save_as()
    assert out.exists() and out.stat().st_size == 174848
    window.close()


@needs_dos_saves
@needs_disks
def test_closing_a_converted_party_with_no_destination_keeps_the_edit(
        app, dos_save, files, monkeypatch):
    """`#505 (A converted party with no filename would answer the new Save
    button by silently doing nothing and closing, losing the edits)`, made
    reachable again by `File ▸ Import`'s own return (`#514 (Restoring File ▸
    Import makes #505's silent-save data loss reachable, so it must be fixed
    in the same change)`): a party adopted with `path=None` -- what
    `DosImportDialog`'s own Convert button used to refuse to reach with an
    empty destination, but a caller other than that dialog is not stopped by
    a disabled button -- leaves the window dirty with nowhere to write to.
    Closing it must not silently discard the party the way `#505` found it
    would: `save()` cannot write with no path, and `close()` must read that
    as "not saved" rather than as success.

    `#515 (Clicking Save on an imported party with no destination does
    nothing and says nothing, so the button looks broken)`: clicking **Save**
    here now opens the same chooser `Save As` does, so the mocked exec below
    is followed by a mocked, cancelled `getSaveFileName` -- an empty path is
    exactly what a player sees when they close that chooser without naming a
    file, and the edit has to survive that the same way it survived before
    the chooser existed.

    `File ▸ Import` and `EditorBinding.adopt_conversion`, which used to make
    this state reachable, are both gone (`#52 (File ▸ Import and File ▸
    Export for every direction the library supports)`, 2026-09-14). The
    guard is kept because the state is still constructible from inside
    `EditorBinding` -- see the previous test's own docstring.
    """
    from PyQt6.QtWidgets import QMessageBox

    import editor.window as ew
    from editor.dosimport import rehearse
    from editor.roster import Party
    from editor.window import EditorBinding

    window = EditorBinding(make_root())
    conversion = rehearse(dos_save, "A", files)
    party = Party("", game=conversion.game, disk=conversion.disk)
    window._adopt(party, None, dirty=True)
    assert window.dirty
    assert window.path is None

    monkeypatch.setattr(ew.QMessageBox, "exec",
                        lambda self: int(QMessageBox.StandardButton.Save))
    monkeypatch.setattr(ew.QFileDialog, "getSaveFileName",
                        lambda *a, **k: ("", ""))
    assert window.close() is False, \
        "closed and lost a converted party with no file behind it"
    assert window.dirty, "the edit must not be marked saved"
    assert window.path is None, "a cancelled chooser must not adopt a path"


@needs_dos_saves
@needs_disks
def test_closing_a_converted_party_and_naming_it_in_the_chooser_saves_and_closes(
        app, dos_save, files, monkeypatch, tmp_path):
    """The other half of `#515`: given a name in the chooser the Save button
    opens, the party is written there and the window closes, the same as if
    it had been named all along.

    `File ▸ Import` and `EditorBinding.adopt_conversion`, which used to make
    this state reachable, are both gone (`#52 (File ▸ Import and File ▸
    Export for every direction the library supports)`, 2026-09-14) -- see
    `test_the_import_lands_with_no_file_behind_it_and_save_as_writes_it`'s
    own docstring for why the guard is kept anyway.
    """
    from PyQt6.QtWidgets import QMessageBox

    import editor.window as ew
    from editor.dosimport import rehearse
    from editor.roster import Party
    from editor.window import EditorBinding

    window = EditorBinding(make_root())
    conversion = rehearse(dos_save, "A", files)
    party = Party("", game=conversion.game, disk=conversion.disk)
    window._adopt(party, None, dirty=True)
    assert window.dirty
    assert window.path is None

    out = tmp_path / "NAMED.D64"
    monkeypatch.setattr(ew.QMessageBox, "exec",
                        lambda self: int(QMessageBox.StandardButton.Save))
    monkeypatch.setattr(ew.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    assert window.close() is True
    assert not window.dirty
    assert window.path == out
    assert out.exists() and out.stat().st_size == 174848


#: `DosImportDialog`'s own destination-row tests and Convert-writing tests
#: -- `test_the_destination_starts_filled_in_from_the_slot`, `test_the_
#: suggested_name_changes_with_the_slot`, `test_a_path_the_user_typed_
#: survives_a_change_of_slot`, `test_an_empty_destination_is_not_
#: convertible`, `test_convert_writes_the_file_the_window_names`, `test_a_
#: write_that_cannot_happen_pops_a_modal_naming_the_refusal`, `test_
#: import_dos_save_is_cancellable_without_touching_anything`, `test_a_
#: folder_with_no_dos_save_says_so` -- are deleted along with the dialog
#: and `EditorBinding.import_dos_save` (`#52 (File ▸ Import and File ▸
#: Export for every direction the library supports)`, 2026-09-14).
#: `editor.convert.ConvertDialog`'s own destination row and
#: `EditorBinding.convert` are the survivors; `tests/test_convert.py`
#: covers them.


#: `test_the_file_menu_carries_the_import_with_nothing_set` was added
#: 2026-09-10 for one purpose -- to catch a repeat of `File ▸ Import` being
#: removed before `File ▸ Convert…` could replace it. The removal it
#: guarded against is no longer premature: both happened in the same
#: commit, 2026-09-14 (`#52 (File ▸ Import and File ▸ Export for every
#: direction the library supports)`). Its replacement is
#: `tests/test_convert.py::test_the_file_menu_carries_convert_with_
#: nothing_set`, which asserts the File menu's whole action list in order,
#: pinning Import's absence in the same assertion that pins Convert's
#: presence -- so nobody has to remember to separately assert a deleted
#: constant is missing. `test_the_import_does_not_depend_on_the_removed_
#: variable` goes with it, replaced by `test_convert_does_not_depend_on_
#: the_removed_variable`.


# --- the refusal a player reads (#176) --------------------------------------

def test_a_refused_title_tells_the_player_which_game_and_no_issue_number():
    """`#176 (A player importing a Curse of the Azure Bonds save is shown an
    issue number)`.

    The exception is written for the tracker and keeps its issue number,
    because that is what a traceback and a log are for. What a player reads is
    the other half, and it carries no `#123` and no talk of pairs of ports.
    Donald wrote the sentence, 2026-09-02.
    """
    import re

    exc = dos_codec.WrongTitleError(
        "Curse of the Azure Bonds records read, but only Pool of Radiance "
        "converts: no other pair of ports has been measured against each "
        "other (#53)",
        title="Curse of the Azure Bonds")

    assert "(#53)" in str(exc), "the developer's reason lost its issue number"

    shown = exc.player_message
    assert shown == "Curse of the Azure Bonds imports not yet supported."
    assert not re.search(r"#\d", shown), f"an issue number reaches a player: {shown!r}"
    assert "pair of ports" not in shown


@needs_dos_saves
@needs_disks
#: `test_the_dialog_is_blocked_by_the_players_sentence_and_not_the_
#: exception` drove this against `DosImportDialog`; ported to
#: `tests/test_convert.py` against `ConvertDialog`, deleted with the
#: dialog on 2026-09-14 (`#52 (File ▸ Import and File ▸ Export for every
#: direction the library supports)`).


def test_a_refusal_cannot_be_raised_without_naming_the_title():
    """`title` is required, so a caller that forgets it fails at the raise
    site rather than putting `" imports not yet supported."` -- leading space,
    lower case, no game named -- in front of a player.

    Found in the code review of `#176 (A player importing a Curse of the Azure
    Bonds save is shown an issue number)`. It was unreachable when it was
    found; this is what keeps it that way.
    """
    with pytest.raises(TypeError):
        dos_codec.WrongTitleError("the developer's reason")



#: `test_the_dialog_is_blocked_by_the_fallback_and_not_the_developers_
#: sentence`, `test_the_dialog_is_blocked_by_the_fallback_for_a_refusal_
#: dos_record_error_never_names` and `test_a_refusal_on_construction_is_
#: shown_not_swallowed`, which drove `#195`'s guarantee against
#: `DosImportDialog`, are ported to `tests/test_convert.py` against
#: `ConvertDialog`, deleted with the dialog on 2026-09-14 (`#52 (File ▸
#: Import and File ▸ Export for every direction the library supports)`).
#: `_UNWRITTEN_BYTES_MESSAGE` and `_OUTDOOR_DISAGREEMENT_MESSAGE` moved
#: with them, quoted verbatim.
