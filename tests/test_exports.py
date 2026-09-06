from __future__ import annotations


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


"""File > Export: the windows over `goldbox.dos.write_dos_save` and
`goldbox.amiga.export_party`.

The conversions themselves are `tests/test_doswriter.py`'s and
`tests/test_amiga.py`'s. What is tested here is the pair of things a menu item
can get wrong that a command line cannot:

* **the losses are on screen before anything is written**, the same promise
  `tests/test_dosimport.py` holds the import to;
* **so is every file the write would replace or remove.** An export has no
  backup behind it -- it writes into a folder the editor does not own -- so
  naming the damage in advance is the whole guarantee. #68 is what that is
  for: a party of one written into a folder that held six is a party of one,
  and the five files that stop existing are named before the button.

And the gate: `WISH_EXPERIMENTAL_EXPORT` unset is the shipped state and the
menu is **not built**, because every string in `editor/exports.py` is still an
agent's placeholder.

The DOS half needs Donald's unpacked *Forgotten Realms: The Archives*
(`$FR_ARCHIVES`) for a template; the Amiga half needs one of his save disks.
Either missing and those tests skip, which is what CI does. Nothing here opens
a window: `tests/conftest.py` forces the offscreen platform.
"""


import pathlib

import pytest
from gamedata import disk_path
from test_dossave import _save_dir, needs_dos_saves

from goldbox import dos, games

SAVE_DISK = "PORSAVE11"

needs_disks = pytest.mark.skipif(disk_path(SAVE_DISK) is None,
                                 reason="needs the save disks")

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def app():
    """The session-wide application `tests/conftest.py` holds a reference to."""
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _source(fixture: str, save1: str | None = None, game=None):
    """A C64 party built from the committed payloads.

    No disk image behind it, which the DOS direction never reads: it converts
    the `SAVEDGAME0`/`SAVEDGAME1` payloads, not the file they came out of.
    """
    from editor.exports import Source
    from goldbox.savegame import SaveGame0, SaveGame1

    return Source(
        game or games.POOL_OF_RADIANCE,
        SaveGame0.from_prg((FIXTURES / fixture).read_bytes()).to_bytes(),
        SaveGame1.from_prg((FIXTURES / save1).read_bytes()).to_bytes()
        if save1 else None,
        b"", fixture)


@pytest.fixture
def one():
    return _source("savedgame0.bin", "savedgame1.bin")


@pytest.fixture
def six():
    return _source("party6_savedgame0.bin")


@pytest.fixture
def dos_template():
    where = _save_dir()
    if where is None:
        pytest.skip("needs a DOS save; set FR_ARCHIVES")
    return where


# --- the rehearsal, which is the whole point ---------------------------------

@needs_dos_saves
def test_the_export_is_rehearsed_and_the_destination_is_untouched(
        one, dos_template, tmp_path):
    """Planning creates nothing. The rehearsal happens in a scratch directory
    that is thrown away, so the pane can be filled before the folder the user
    picked has been written to at all."""
    from editor.exports import DosPlan

    out = tmp_path / "out"
    plan = DosPlan(one, out, dos_template, "A")
    assert not out.exists()
    assert plan.files == ["CHRDATA1.SAV", "SAVGAMA.DAT"]
    assert plan.losses


@needs_dos_saves
def test_the_losses_are_the_codecs_own_words(one, dos_template, tmp_path):
    """The lines come from `goldbox/dos.py`'s report, so the pane and
    `tools/` cannot become two accounts of the same conversion."""
    from editor.exports import DROPPED_HEADING, DosPlan

    text = DosPlan(one, tmp_path / "out", dos_template, "A").text()
    assert text.startswith(DROPPED_HEADING)
    for field in ("infravision", "portrait_head"):
        assert field in text
    # `innate_effects` used to sit here.  Since #61 the racial bonuses are
    # written to the `.SPC`, so they are not a loss and must not be named as
    # one.
    assert "innate_effects" not in text
    # `summary()` also carries a byte count and the `converted` list; neither
    # is a loss and neither belongs under that heading.
    assert "bytes accounted for" not in text
    assert "converted:" not in text


# --- the destination, which is what an export has and an import does not -----

@needs_dos_saves
def test_a_second_export_names_the_first_partys_leftovers_before_writing(
        one, six, dos_template, tmp_path):
    """#68, moved forward of the button.

    `goldbox.dos.write_dos_save` clears the slot, so the party that arrives is
    right -- but a user who is told nothing has five files silently deleted.
    The plan names them while there is still a Cancel.
    """
    from editor.exports import REMOVES_HEADING, DosPlan

    DosPlan(six, tmp_path, dos_template, "B").write()
    assert len(dos.read_party(tmp_path, "B")) == 6

    plan = DosPlan(one, tmp_path, dos_template, "B")
    # The elf, the half-elf and the dwarf of the six-party each left a `.SPC`
    # behind (#61); BRUTUS is human and writes none, so those go with the five
    # strangers' records. The party is written back to front (#101), so the
    # three are files 2, 5 and 6 rather than 1, 2 and 5.
    assert plan.removed == sorted(
        ["CHRDATB2.SPC", "CHRDATB5.SPC", "CHRDATB6.SPC"]
        + [f"CHRDATB{n}.SAV" for n in range(2, 7)])
    assert plan.replaced == ["CHRDATB1.SAV", "SAVGAMB.DAT"]
    assert REMOVES_HEADING in plan.text()
    for name in plan.removed:
        assert (tmp_path / name).exists()      # still there, nothing written

    plan.write()
    assert [c.name for c in dos.read_party(tmp_path, "B")] == ["BRUTUS"]


@needs_dos_saves
def test_an_export_claims_nothing_it_did_not_write(one, dos_template,
                                                   tmp_path):
    """Only the eighteen names the engine reads for this slot are ever
    removed. Another slot's files and the user's own are neither replaced nor
    removed, and are not named as if they were."""
    from editor.exports import DosPlan

    (tmp_path / "CHRDATA1.SAV").write_bytes(b"another slot")
    (tmp_path / "notes.txt").write_bytes(b"the user's own file")
    plan = DosPlan(one, tmp_path, dos_template, "B")
    assert plan.removed == [] and plan.replaced == []
    assert "notes.txt" not in plan.text()
    plan.write()
    assert (tmp_path / "notes.txt").read_bytes() == b"the user's own file"
    assert (tmp_path / "CHRDATA1.SAV").read_bytes() == b"another slot"


@needs_dos_saves
def test_the_write_puts_a_readable_party_where_it_said_it_would(
        one, dos_template, tmp_path):
    from editor.exports import DosPlan

    out = tmp_path / "out"
    plan = DosPlan(one, out, dos_template, "A")
    note = plan.write()
    assert sorted(p.name for p in out.iterdir()) == plan.files
    assert [c.name for c in dos.read_party(out, "A")] == ["BRUTUS"]
    assert "A" in note and str(out) in note


# --- the Amiga direction ------------------------------------------------------

@needs_disks
def test_the_amiga_export_names_a_pc_file_per_character(tmp_path):
    from editor.exports import AmigaPlan, Source

    plan = AmigaPlan(Source.from_disk(disk_path(SAVE_DISK)), tmp_path / "SAVE")
    assert not (tmp_path / "SAVE").exists()
    assert plan.files and all(n.endswith(".pc") for n in plan.files)
    assert "MALCYON.pc" in plan.files
    # Six characters, six reports: the pane has to say which loss is whose.
    assert "MALCYON.pc:" in plan.text()


@needs_disks
def test_the_amiga_export_removes_nothing_and_says_what_it_overwrites(
        tmp_path):
    """The `SAVE` drawer is the picker's pool, not a party file
    (`docs/124-amiga-port.md`), so a leftover `.pc` is one more option in
    `Add Character -> Pools` rather than a stranger in the party. It is never
    deleted -- but a file of the same name is overwritten, and that is said."""
    from editor.exports import AmigaPlan, Source

    source = Source.from_disk(disk_path(SAVE_DISK))
    stranger = tmp_path / "BJORK.pc"
    stranger.write_bytes(b"somebody else's character")
    (tmp_path / "MALCYON.pc").write_bytes(b"an earlier export")

    plan = AmigaPlan(source, tmp_path)
    assert plan.removed == []
    assert "MALCYON.pc" in plan.replaced
    assert "BJORK.pc" not in plan.replaced
    plan.write()
    assert stranger.read_bytes() == b"somebody else's character"
    assert (tmp_path / "MALCYON.pc").read_bytes() != b"an earlier export"


def test_two_characters_with_one_amiga_file_name_are_named_as_a_loss():
    """`goldbox.amiga.pc_filename` cuts a name to eight AmigaDOS characters, so
    LADY KATHERINE and LADY KATHRYN are both `LADYKATH.pc` and
    `goldbox.amiga.export_party` writes the second over the first in silence --
    a character that leaves the window and does not arrive.

    The defect is `goldbox/amiga.py`'s and is #79; what this asserts
    is that the pane does not repeat it, because a menu item that drops a
    whole character silently would be worse than no menu item (#36).
    """
    from editor.exports import COLLIDES, _amiga_losses
    from goldbox.neutral import Report

    same = pathlib.Path("LADYKATH.pc")
    text = _amiga_losses([(same, Report()), (same, Report())])
    assert COLLIDES.format(file="LADYKATH.pc") in text
    # One line, not one per file: only the loser is a loss.
    assert text.count("LADYKATH.pc: two characters") == 1


# --- the windows --------------------------------------------------------------

@needs_dos_saves
def test_with_no_destination_there_is_nothing_to_export(app, one):
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.exports import NO_DESTINATION, DosExportDialog

    dialog = DosExportDialog(one)
    assert dialog.report_pane.toPlainText() == NO_DESTINATION
    assert not dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


@needs_dos_saves
def test_choosing_a_template_fills_the_slots_and_replans(app, one,
                                                         dos_template,
                                                         tmp_path):
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.exports import DROPPED_HEADING, NO_TEMPLATE, DosExportDialog

    dialog = DosExportDialog(one, destination=tmp_path)
    assert dialog.report_pane.toPlainText() == NO_TEMPLATE
    dialog.set_template(dos_template)
    offered = [dialog.slots.itemText(i) for i in range(dialog.slots.count())]
    assert offered == dos.slots_available(dos_template)
    assert dialog.report_pane.toPlainText().startswith(DROPPED_HEADING)
    assert dialog.plan is not None
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


@needs_dos_saves
def test_a_later_title_cannot_be_exported_to_dos(app, dos_template, tmp_path):
    """A sentence in the pane with Export greyed out, not a traceback: the DOS
    writer is Pool of Radiance's and reading a Curse save with it would
    misread every field it shares a name with."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.exports import DosExportDialog

    curse = _source("savedgame0.bin", "savedgame1.bin",
                    game=games.CURSE_OF_THE_AZURE_BONDS)
    dialog = DosExportDialog(curse, template=dos_template,
                             destination=tmp_path)
    text = dialog.report_pane.toPlainText()
    assert games.CURSE_OF_THE_AZURE_BONDS.title in text
    assert "Traceback" not in text
    assert dialog.plan is None
    assert not dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


@needs_disks
def test_the_editor_exports_the_party_on_screen_not_the_one_on_disk(
        app, tmp_path):
    """An edit typed but not saved crosses. `export_source` flushes and pushes
    into the in-memory disk exactly as Save does, and touches no file."""
    from editor.exports import AmigaPlan, Source
    from editor.window import EditorBinding

    disk = tmp_path / f"{SAVE_DISK}.D64"
    disk.write_bytes(disk_path(SAVE_DISK).read_bytes())
    before = disk.read_bytes()

    window = EditorBinding(make_root(), str(disk), backups=str(tmp_path / "backups"))
    window.roster.selectRow(0)
    window._widgets["gold"].setValue(1234)
    window._edited()

    source = window.export_source()
    assert source.save0 != Source.from_disk(disk).save0
    assert disk.read_bytes() == before          # and nothing was written

    plan = AmigaPlan(source, tmp_path / "SAVE")
    window.commit_export(plan)
    assert sorted(p.name for p in (tmp_path / "SAVE").iterdir()) == plan.files
    # The C64 save is still unsaved: an export writes somewhere else and is
    # not this window's Save.
    assert disk.read_bytes() == before
    assert window.dirty
    window.dirty.clear()
    window.close()


# --- the gate -----------------------------------------------------------------

def _window(tmp_path, monkeypatch):
    """A window with nothing to attach to. The caller closes it."""
    from wish.session import Session
    from wish.window import WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Nothing answering, and nothing looked for: a menu test must not go
    # probing the ports a human's own game session is on.
    return WishWindow(maps={}, session=Session(find=lambda pref=None: None))


def _file_menu(window):
    return next(a.menu() for a in window.menuBar().actions()
                if a.text() == "&File")


def test_the_export_is_not_offered_unless_it_is_asked_for(app, tmp_path,
                                                          monkeypatch):
    """The gate, asserted from the outside: no submenu, not a greyed one.

    Every word in `editor/exports.py` is a placeholder nobody has approved, so
    unset is the shipped state and there is nothing on the File menu at all.
    """
    from editor.exports import ENV, MENU_EXPORT

    monkeypatch.delenv(ENV, raising=False)
    window = _window(tmp_path, monkeypatch)
    assert MENU_EXPORT not in [a.text() for a in _file_menu(window).actions()]
    assert window.export_dos_action is None
    assert window.export_amiga_action is None
    window.close()


def test_a_variable_somebody_forgot_does_not_turn_it_on(app, tmp_path,
                                                        monkeypatch):
    """`0` and `off` are off, the same rule `wish/debugmode.py` follows."""
    from editor.exports import ENV, MENU_EXPORT

    for value in ("", "0", "off", "no"):
        monkeypatch.setenv(ENV, value)
        window = _window(tmp_path, monkeypatch)
        assert MENU_EXPORT not in [a.text()
                                   for a in _file_menu(window).actions()], value
        assert window.export_dos_action is None, value
        window.close()


def test_the_file_menu_carries_both_directions_when_asked(app, tmp_path,
                                                          monkeypatch):
    from editor.exports import ENV, MENU_AMIGA, MENU_DOS, MENU_EXPORT

    monkeypatch.setenv(ENV, "1")
    window = _window(tmp_path, monkeypatch)
    submenu = next(a.menu() for a in _file_menu(window).actions()
                   if a.text() == MENU_EXPORT)
    assert [a.text() for a in submenu.actions()] == [MENU_DOS, MENU_AMIGA]
    assert window.export_dos_action.text() == MENU_DOS
    assert window.export_amiga_action.text() == MENU_AMIGA
    window.close()


def test_import_and_export_are_two_submenus_not_one_dialog(app, tmp_path,
                                                           monkeypatch):
    """The shape, asserted so a later change to it is a deliberate one.

    Import is already a submenu (#23) and export sits beside it: the source of
    an export is always the save this window has open, so a source control in
    a combined dialog would be a control with one sensible value.  Import is
    built for everyone since `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which
    needs the import working for all three C64 titles)`; only Export still
    needs its flag.
    """
    from editor.dosimport import MENU_IMPORT
    from editor.exports import ENV, MENU_EXPORT

    monkeypatch.setenv(ENV, "1")
    window = _window(tmp_path, monkeypatch)
    texts = [a.text() for a in _file_menu(window).actions()]
    assert texts.index(MENU_IMPORT) + 1 == texts.index(MENU_EXPORT)
    window.close()
