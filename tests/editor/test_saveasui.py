"""The split Open and Save buttons, the conditional destination section, and
every refusal or failure text `editor.window`'s Save As controller shows for
a `saveplan`/`editor.files` exception (#511,
docs/227-editor-open-save-as.md, the string inventory on that issue --
comment 5769421923 -- and Donald's decisions on it, comment 5770669768).

Everything here is built from the format, so it runs with no game data:
`test_saveplan.py`'s own DOS folder builder and `tests/gamedata.py`'s
synthetic C64 save. A native copy needs no game files at all, which is what
lets the refusal-text tests drive `confirm_save_as` for real rather than
only asserting the mapping in isolation.
"""
from __future__ import annotations

import pathlib

import pytest
from gamedata import synthetic_save
from support.editorwindow import make_root
from test_saveplan import SILVER_BLADES, dos_folder

import editor.window as ew
from editor import files, saveplan
from editor.window import EditorBinding


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def c64_party(app, tmp_path, name="SYNTHETIC.D64"):
    path = synthetic_save(tmp_path, name)
    return EditorBinding(make_root(), str(path)), path


# ---------------------------------------------------------------------------
# The split buttons: a main action, and an arrow with its own menu
# ---------------------------------------------------------------------------

def test_the_open_buttons_main_action_opens_a_file_picker(app, tmp_path,
                                                           monkeypatch):
    binding = EditorBinding(make_root())
    picked = {}
    loaded = []
    monkeypatch.setattr(ew.QFileDialog, "getOpenFileName",
                        lambda *a: (picked.setdefault("args", a)
                                   and (str(tmp_path / "x.adf"), "")))
    monkeypatch.setattr(binding, "load", loaded.append)
    binding._child("button_open").click()
    assert loaded == [str(tmp_path / "x.adf")]


def test_the_open_arrow_duplicates_the_main_action_and_adds_a_folder_picker(app):
    binding = EditorBinding(make_root())
    texts = [a.text() for a in binding._open_menu.actions()]
    assert texts == [ew.OPEN_MENU_FILE, ew.OPEN_MENU_FOLDER]


def test_the_open_arrow_folder_entry_calls_open_folder(app, tmp_path,
                                                        monkeypatch):
    binding = EditorBinding(make_root())
    loaded = []
    monkeypatch.setattr(ew.QFileDialog, "getExistingDirectory",
                        lambda *a: str(tmp_path))
    monkeypatch.setattr(binding, "load", loaded.append)
    action = next(a for a in binding._open_menu.actions()
                 if a.text() == ew.OPEN_MENU_FOLDER)
    action.trigger()
    assert loaded == [str(tmp_path)]


def test_the_save_arrow_is_disabled_with_nothing_open(app):
    binding = EditorBinding(make_root())
    assert not binding._child("button_save").isEnabled()
    assert binding._save_menu.actions() == []


def test_the_save_buttons_main_action_saves_the_open_file(app, tmp_path,
                                                           monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.roster.selectRow(0)
    saved = []
    monkeypatch.setattr(binding, "_write_back", lambda: saved.append(True) or {})
    monkeypatch.setattr(ew.files, "save_disk", lambda *a: "wrote it")
    binding._child("button_save").click()
    assert saved == [True]


def test_the_save_arrow_lists_every_destination_port_with_nothing_greyed(
        app, tmp_path):
    from editor.convert import Source

    folder = dos_folder(tmp_path, deltas=SILVER_BLADES)
    binding = EditorBinding(make_root(), str(folder))
    source = Source.detect(str(binding.path), binding.party)
    expected = [ew.SAVE_AS_ENTRY.format(label=ew.PORT_LABEL[port])
               for port in saveplan.destination_ports(source)]
    actions = binding._save_menu.actions()
    assert [a.text() for a in actions] == expected
    assert all(a.isEnabled() for a in actions)
    assert binding._child("button_save").isEnabled()


def test_opening_a_save_rebuilds_the_save_menu_for_its_own_title(app, tmp_path):
    binding, _path = c64_party(app, tmp_path)
    texts = [a.text() for a in binding._save_menu.actions()]
    assert texts[0] == ew.SAVE_AS_ENTRY.format(label="C64")


# ---------------------------------------------------------------------------
# The destination section: visibility and fields
# ---------------------------------------------------------------------------

def test_the_destination_section_is_hidden_until_a_save_as_entry_is_chosen(
        app, tmp_path):
    binding, _path = c64_party(app, tmp_path)
    assert binding._child("destination_section").isHidden()


def test_choosing_c64_shows_its_own_label_and_no_slot_or_asset_rows(
        app, tmp_path):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    section = binding._child("destination_section")
    assert not section.isHidden()
    assert (binding._child("label_destination_path").text()
            == ew.DESTINATION_PATH_LABEL["c64"])
    assert binding._child("box_destination_slot").isHidden()
    for row in ("box_c64_disks", "box_dos_folder", "box_amiga_disk"):
        assert binding._child(row).isHidden()
    assert binding._child("button_destination_save_as").isEnabled()


def test_choosing_dos_shows_its_own_label_and_the_dos_game_folder_row(
        app, tmp_path, monkeypatch):
    """A C64 party converting away also needs its own game disks
    (`saveplan.SOURCE_DISKS`) -- resolved only through the injected
    `game_files_for` callable, never through a typed row
    (`_destination_manual_assets`'s own docstring), so this fixes that half
    automatically the way Preferences would and drives the DOS folder row on
    its own."""
    binding, _path = c64_party(app, tmp_path)
    monkeypatch.setattr(binding, "game_files_for", lambda _game: object())
    binding.begin_save_as("dos")
    assert (binding._child("label_destination_path").text()
            == ew.DESTINATION_PATH_LABEL["dos"])
    assert not binding._child("box_destination_slot").isHidden()
    assert binding._child("label_destination_slot").text() == "A"
    assert not binding._child("box_dos_folder").isHidden()
    # A DOS destination never needs the destination's own C64 disks.
    assert binding._child("box_c64_disks").isHidden()
    assert binding._child("box_amiga_disk").isHidden()
    assert not binding._child("button_destination_save_as").isEnabled()
    binding._child("destination_dos_folder").setText(str(tmp_path))
    assert binding._child("button_destination_save_as").isEnabled()
    assert binding._child("box_dos_folder").isHidden()


def test_a_c64_source_missing_its_own_disks_cannot_be_fixed_from_the_section(
        app, tmp_path, monkeypatch):
    """The known gap: `saveplan.resolve_assets` takes no manual override for
    `SOURCE_DISKS`, so with no game disks configured Save As to DOS stays
    disabled and no row in the section can change that."""
    binding, _path = c64_party(app, tmp_path)
    monkeypatch.setattr(binding, "game_files_for", lambda _game: None)
    binding.begin_save_as("dos")
    binding._child("destination_dos_folder").setText(str(tmp_path))
    # `box_dos_folder` is genuinely resolved; nothing here names the
    # still-missing `SOURCE_DISKS` with a row, since there is none to show,
    # and the button stays off.
    assert not binding._child("button_destination_save_as").isEnabled()


def test_a_native_dos_save_as_shows_its_own_open_slot(app, tmp_path):
    folder = dos_folder(tmp_path, deltas=SILVER_BLADES, slot="B")
    binding = EditorBinding(make_root(), str(folder))
    binding.begin_save_as("dos")
    assert binding._child("label_destination_slot").text() == "B"


def test_cancel_hides_the_section_and_forgets_the_destination(app, tmp_path):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    binding.cancel_save_as()
    assert binding._child("destination_section").isHidden()
    assert binding._save_as_port is None


def test_the_path_field_takes_focus_with_the_suggested_name_selected(
        app, tmp_path):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    field = binding._child("destination_path")
    text = field.text()
    stem = pathlib.Path(text).stem
    assert field.selectedText() == stem
    assert text.endswith(".d64")


# ---------------------------------------------------------------------------
# Every refusal and failure text, wired to its exact trigger
# ---------------------------------------------------------------------------

def _confirm(binding, monkeypatch, target=None):
    """Type `target` (or keep the suggestion) and click Save As."""
    field = binding._child("destination_path")
    if target is not None:
        field.setText(str(target))
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda _parent, title, text: said.append((title, text)))
    binding._child("button_destination_save_as").click()
    return said


class _StubDestination:
    def __init__(self, path):
        self.path = path


class _StubPlan:
    """A `saveplan.SavePlan` double carrying only what `_publish_plan`'s own
    exception handlers read off it -- `publish` is mocked in every test that
    uses this, so nothing else is ever touched."""

    def __init__(self, path):
        self.destination = _StubDestination(pathlib.Path(path))


def test_a_lossy_conversion_is_refused_with_the_approved_sentence_only(
        app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")

    def fake_prepare(*_a, **_k):
        raise saveplan.DroppedFields(["name: 'A LONG NAME' -> 'A LONG NA'"])

    monkeypatch.setattr(ew.saveplan, "prepare_save_as", fake_prepare)
    said = _confirm(binding, monkeypatch)
    assert said == [(ew.CANNOT_SAVE_TITLE, ew.LOSS_REFUSED)]
    assert "This is a fault in Wish." not in said[0][1]
    assert not binding._child("destination_section").isHidden()


def test_a_nonempty_dos_target_is_refused(app, tmp_path, monkeypatch):
    """`prepare_save_as` and `publish` are both stubbed -- what is exercised
    is `_publish_plan`'s own mapping from `files.TargetNotEmpty` to C4's
    text, not a real conversion, which is `test_savepublish.py`'s job and
    needs no game data to prove that half either."""
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("dos")
    target = tmp_path / "already-has-files"
    target.mkdir()
    (target / "x.txt").write_text("hi")
    monkeypatch.setattr(ew.saveplan, "resolve_assets",
                        lambda *a, **k: saveplan.Assets())
    monkeypatch.setattr(ew.saveplan, "prepare_save_as",
                        lambda *a, **k: _StubPlan(target))
    monkeypatch.setattr(
        ew.saveplan, "publish",
        lambda *a, **k: (_ for _ in ()).throw(files.TargetNotEmpty("nope")))
    said = _confirm(binding, monkeypatch, target)
    assert said == [(ew.CANNOT_SAVE_TITLE, ew.TARGET_NOT_EMPTY)]


def test_no_backup_folder_reuses_the_files_module_sentence_verbatim(
        app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    exc = files.NoBackupFolder("No backup folder is set, so x.d64 was not "
                               "written. File > Preferences… to say where "
                               "backups go.")
    monkeypatch.setattr(ew.saveplan, "publish",
                        lambda *a, **k: (_ for _ in ()).throw(exc))
    said = _confirm(binding, monkeypatch, tmp_path / "fresh.d64")
    assert said == [(ew.CANNOT_SAVE_TITLE, str(exc))]


def test_recovery_failed_with_a_backup_names_it(app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    backup = tmp_path / "backups" / "fresh.d64.2026-01-01"
    exc = files.RecoveryFailed("could not undo", backup=backup, left=())
    monkeypatch.setattr(ew.saveplan, "publish",
                        lambda *a, **k: (_ for _ in ()).throw(exc))
    target = tmp_path / "fresh.d64"
    said = _confirm(binding, monkeypatch, target)
    assert said == [(ew.CANNOT_SAVE_TITLE,
                     ew.RECOVERY_FAILED_WITH_BACKUP.format(
                         destination=target, backup=backup))]


def test_recovery_failed_with_no_backup_says_so_and_names_nothing_untouched(
        app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("dos")
    target = tmp_path / "new-save"
    exc = files.RecoveryFailed("could not remove", backup=None,
                               left=(target / "CHRDATA1.SAV",))
    monkeypatch.setattr(ew.saveplan, "resolve_assets",
                        lambda *a, **k: saveplan.Assets())
    monkeypatch.setattr(ew.saveplan, "prepare_save_as",
                        lambda *a, **k: _StubPlan(target))
    monkeypatch.setattr(ew.saveplan, "publish",
                        lambda *a, **k: (_ for _ in ()).throw(exc))
    said = _confirm(binding, monkeypatch, target)
    assert said == [(ew.CANNOT_SAVE_TITLE,
                     ew.RECOVERY_FAILED_NO_BACKUP.format(destination=target))]
    assert "unchanged" not in said[0][1]


def test_a_wrong_extension_is_refused_before_anything_is_read(
        app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    called = []
    monkeypatch.setattr(ew.saveplan, "prepare_save_as",
                        lambda *a, **k: called.append(True))
    said = _confirm(binding, monkeypatch, tmp_path / "mysave.txt")
    assert said == [(ew.CANNOT_SAVE_TITLE, ew.WRONG_EXTENSION["c64"])]
    assert called == []


def test_no_extension_gets_the_platforms_own_appended(app, tmp_path,
                                                       monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    seen = {}

    def fake_prepare(_party, port, path, _assets):
        seen["path"] = path
        raise saveplan.SaveAsError("stop here")

    monkeypatch.setattr(ew.saveplan, "prepare_save_as", fake_prepare)
    monkeypatch.setattr(ew.QMessageBox, "critical", lambda *a: None)
    field = binding._child("destination_path")
    field.setText(str(tmp_path / "mysave"))
    binding._child("button_destination_save_as").click()
    assert str(seen["path"]).endswith("mysave.d64")


def test_a_destination_that_is_the_open_save_is_refused(app, tmp_path,
                                                         monkeypatch):
    binding, path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")

    def fake_refuse(target, _snapshot, _assets):
        raise saveplan.SaveAsError(f"{target} is the save this is being "
                                   f"written from")

    monkeypatch.setattr(ew.saveplan, "refuse_alias", fake_refuse)
    said = _confirm(binding, monkeypatch, path)
    assert said == [(ew.CANNOT_SAVE_TITLE, ew.DESTINATION_IS_SOURCE)]


def test_a_destination_that_is_a_game_file_is_refused(app, tmp_path,
                                                       monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")

    def fake_refuse(target, _snapshot, _assets):
        raise saveplan.SaveAsError(
            f"{target} is, or holds, the game disk this conversion reads")

    monkeypatch.setattr(ew.saveplan, "refuse_alias", fake_refuse)
    said = _confirm(binding, monkeypatch, tmp_path / "beside-a-disk.d64")
    assert said == [(ew.CANNOT_SAVE_TITLE, ew.DESTINATION_IS_GAME_FILE)]


def test_any_other_failure_shows_the_generic_sentence_not_the_developer_text(
        app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    monkeypatch.setattr(
        ew.saveplan, "prepare_save_as",
        lambda *a, **k: (_ for _ in ()).throw(
            saveplan.SaveAsError("no registered c64 to c64 conversion")))
    said = _confirm(binding, monkeypatch, tmp_path / "fresh.d64")
    assert said == [(ew.CANNOT_SAVE_TITLE, ew.SAVE_AS_FAILED)]
    assert "no registered" not in said[0][1]


def test_an_os_error_at_publish_shows_the_generic_sentence(app, tmp_path,
                                                            monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    monkeypatch.setattr(
        ew.saveplan, "publish",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    said = _confirm(binding, monkeypatch, tmp_path / "fresh.d64")
    assert said == [(ew.CANNOT_SAVE_TITLE, ew.SAVE_AS_FAILED)]


def test_a_stale_plan_is_silently_reprepared_and_the_save_still_lands(
        app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    target = tmp_path / "fresh.d64"

    real_publish = saveplan.publish
    calls = []

    def flaky_publish(plan, party, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise saveplan.StalePlan("edited since")
        return real_publish(plan, party, **kwargs)

    monkeypatch.setattr(ew.saveplan, "publish", flaky_publish)
    said = _confirm(binding, monkeypatch, target)
    assert said == []
    assert target.exists()
    assert len(calls) == 2
    assert binding._child("destination_section").isHidden()


def test_a_replace_confirmation_is_shown_before_an_existing_image_is_overwritten(
        app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    binding, path = c64_party(app, tmp_path)
    target = tmp_path / "existing.d64"
    target.write_bytes(b"\x00" * 10)
    binding.begin_save_as("c64")

    seen = {}

    def fake_exec(box):
        seen["title"] = box.windowTitle()
        seen["text"] = box.text()
        seen["buttons"] = {b.text() for b in box.buttons()}
        return 0

    def cancel_clicked(box):
        return box.button(QMessageBox.StandardButton.Cancel)

    monkeypatch.setattr(ew.QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(ew.QMessageBox, "clickedButton", cancel_clicked)
    called = []
    monkeypatch.setattr(ew.saveplan, "prepare_save_as",
                        lambda *a, **k: called.append(True))
    binding._child("destination_path").setText(str(target))
    binding._child("button_destination_save_as").click()

    assert seen["title"] == ew.REPLACE_TITLE
    assert seen["text"] == ew.REPLACE_TEXT.format(name=target.name)
    assert seen["buttons"] == {"Replace", "Cancel"}
    assert called == []               # Cancel stopped it before prepare ran


def test_a_successful_save_as_shows_the_wrote_backup_note_and_adopts_it(
        app, tmp_path, monkeypatch):
    binding, path = c64_party(app, tmp_path)
    binding.begin_save_as("c64")
    target = tmp_path / "fresh.d64"
    statuses = []
    monkeypatch.setattr(binding, "status", statuses.append)
    said = _confirm(binding, monkeypatch, target)
    assert said == []
    assert target.exists()
    assert statuses == [f"wrote {target.name}"]
    assert binding.path == target
    assert binding._child("destination_section").isHidden()


# ---------------------------------------------------------------------------
# The unsaved-changes guard, shared by Open and by close()
# ---------------------------------------------------------------------------

def test_opening_another_save_with_pending_edits_asks_before_discarding_them(
        app, tmp_path, monkeypatch):
    binding, _path = c64_party(app, tmp_path)
    binding.roster.selectRow(0)
    binding._widgets["gold"].setValue(binding._widgets["gold"].value() + 1)
    binding._edited()

    seen = {}

    def fake_exec(box):
        seen["title"] = box.windowTitle()
        seen["text"] = box.text()
        from PyQt6.QtWidgets import QMessageBox
        return int(QMessageBox.StandardButton.Cancel)

    monkeypatch.setattr(ew.QMessageBox, "exec", fake_exec)
    other = synthetic_save(tmp_path, "OTHER.D64")
    binding.load(str(other))
    assert seen["title"] == ew.UNSAVED_CHANGES_TITLE
    assert seen["text"] == ew.UNSAVED_BEFORE_OPEN
    assert binding.path.name == pathlib.Path(_path).name   # unchanged
