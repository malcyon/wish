from __future__ import annotations


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


"""File > Import > DOS save: the window over `goldbox/dos.py`'s converter.

The conversion itself is `tests/test_dosconvert.py`'s. What is tested here is
the one thing a menu can get wrong that a command line cannot: **the losses
are on screen before anything is written**, a refusal reaches the user as a
sentence rather than as a traceback, and the import refuses outright when the
player's game disks are not there rather than writing a save with invented
bytes in it (#118).

Both halves need somebody's files. The DOS save is Donald's unpacked copy of
*Forgotten Realms: The Archives* (`$FR_ARCHIVES`) and the game disks are his
`POOL*.D64`; with either missing the tests that need them skip, which is what
CI does. Nothing here opens a window: `tests/conftest.py` forces the offscreen
platform before Qt is imported.
"""


import pytest
from gamedata import disk_dir, game_disk
from test_dossave import _save_dir, needs_dos_saves

from goldbox import dos, dos_savegame

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
                animate = load_payload(str(disk), dos.ANIMATE_FILE)
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
    assert read_back == [c.name for c in dos.read_party(dos_save, "A")][::-1]


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


def _stub_conversion(report):
    """A `Conversion` with only what the pane reads -- the report -- so a
    pane test can force any mix of messages and drops rather than wait for a
    specimen that happens to produce it."""
    import types
    return types.SimpleNamespace(report=report, slot="A")


def _dialog_showing(app, tmp_path, monkeypatch, report):
    """The real dialog, rehearsed over `report` instead of a DOS folder."""
    from editor import dosimport

    folder = _fake_dos_dir(tmp_path)
    dialog = dosimport.DosImportDialog(folder, _fake_files())
    monkeypatch.setattr(dosimport, "rehearse",
                        lambda *_a, **_k: _stub_conversion(report))
    dialog._rehearse()
    return dialog


def test_the_pane_shows_what_the_conversion_did_and_what_it_did_not_convert(
        app, tmp_path, monkeypatch):
    """Donald, 2026-09-06, having seen the messages-only pane `#131 (Lift
    WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import working for all
    three C64 titles)` shipped: *"do not show dropped fields if they are
    derived in the new game. Show others for now. I will refine them as we
    go."*

    A report carrying both -- the one approved sentence on `messages` and a
    drop line from `DROPPED_PLAYER_TEXT` -- puts the sentence on screen
    first and the drop line after it, with no `DROPPED_HEADING` over either:
    the pane's own `Conversion Info` label is the heading.  Watched failing
    against the night-before pane, which drew the sentence alone.
    """
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import DROPPED_HEADING
    from goldbox.dos import DROPPED_PLAYER_TEXT, NOT_SET_OUT, C64SaveReport

    drop = DROPPED_PLAYER_TEXT["turn_class"]
    report = C64SaveReport(save0_size=0x1C00)
    report.messages.append(NOT_SET_OUT)
    report.dropped.append(drop)
    dialog = _dialog_showing(app, tmp_path, monkeypatch, report)

    shown = dialog.report_pane.toPlainText()
    assert shown.startswith(NOT_SET_OUT)
    assert shown.endswith(drop)
    assert DROPPED_HEADING not in shown
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_a_conversion_with_nothing_to_say_leaves_the_pane_empty(
        app, tmp_path, monkeypatch):
    """No heading over nothing (#338's rule): a conversion that did nothing
    remarkable and dropped nothing shows an empty pane under its label --
    and one that only dropped something shows that line alone."""
    from goldbox.dos import DROPPED_PLAYER_TEXT, C64SaveReport

    report = C64SaveReport(save0_size=0x1C00)
    dialog = _dialog_showing(app, tmp_path, monkeypatch, report)
    assert dialog.report_pane.toPlainText() == ""

    report.dropped.append(DROPPED_PLAYER_TEXT["icon_dimension"])
    dialog = _dialog_showing(app, tmp_path, monkeypatch, report)
    assert dialog.report_pane.toPlainText() == \
        DROPPED_PLAYER_TEXT["icon_dimension"]


def test_pane_text_is_the_messages_then_the_drops():
    """The renderer alone: the messages one to a line, a blank line, then
    the drop lines one to a line; either half alone with no blank line; a
    plain `Report` -- which has no `messages` -- contributes its drops."""
    from editor.dosimport import pane_text
    from goldbox.dos import NOT_SET_OUT, C64SaveReport, Report

    report = C64SaveReport(save0_size=0x1C00)
    report.messages.extend([NOT_SET_OUT, "Second line."])
    assert pane_text(report) == f"{NOT_SET_OUT}\nSecond line."
    report.dropped.extend(["A drop line", "Another"])
    assert pane_text(report) == \
        f"{NOT_SET_OUT}\nSecond line.\n\nA drop line\nAnother"
    plain = Report()
    assert pane_text(plain) == ""
    plain.dropped.append("Only a drop")
    assert pane_text(plain) == "Only a drop"


def test_the_pane_is_headed_conversion_info_and_is_half_the_height_it_was(
        app, tmp_path, monkeypatch):
    """Donald, 2026-09-06: *"how about 'Conversion Info'. I think it should
    be half its current size, too."*

    The label is the form's, above the pane, with his words exactly; the
    pane's height is measured in lines of its own font rather than in
    pixels, because a pixel count is a measurement of this machine.  The
    pane before this was 342 pixels high in the 680x480 dialog -- about
    twenty lines at the base font -- and half of that is ten; the dialog is
    330 high now and the pane comes out at 169, nine or ten lines.  A pane
    that fits eleven lines or more at the base font has grown back.
    """
    from editor.dosimport import PANE_HEADING
    from goldbox.dos import C64SaveReport

    dialog = _dialog_showing(app, tmp_path, monkeypatch,
                             C64SaveReport(save0_size=0x1C00))
    dialog.show()
    app.processEvents()
    label = dialog.ui.label_report
    assert label.text() == PANE_HEADING == "Conversion Info"
    assert label.isVisibleTo(dialog)
    assert label.y() < dialog.report_pane.y()
    #: Against what it was, with room for a machine that lays out
    #: differently. Neither a line count nor a share of the dialog works
    #: here: CI's line spacing is 14 px where this desktop's is about 17, so
    #: the same pane is ten lines on one and thirteen on the other, and the
    #: dialog shrank alongside the pane so the share barely moved. What
    #: "half its current size" means is the pane itself, and the pane was
    #: **342 px** before Donald asked on 2026-09-06. Under two thirds of
    #: that is half within any font's rounding; over 100 says it did not
    #: collapse to nothing.
    was = 342
    height = dialog.report_pane.height()
    assert 100 < height < was * 2 / 3, (height, was)
    dialog.close()


def test_a_conversion_that_drops_nothing_gets_no_heading():
    """#338 (The conversion pane says fields could not be converted and then
    lists none): a heading over no lines told a player something was lost
    with nothing to name, which is worse than saying nothing."""
    from editor.dosimport import dropped_text
    from goldbox.dos import Report

    assert dropped_text(Report()) == ""


# --- the window -------------------------------------------------------------

@needs_dos_saves
@needs_disks
def test_the_pane_is_filled_before_the_button_is_pressable(
        app, dos_save, files):
    """The dialog rehearses on construction, so the pane holds the
    conversion's own messages and every field it did not convert, in the
    words the report gives them, at the moment Convert first becomes
    pressable -- and no address, file name or issue number among them."""
    import re

    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import DROPPED_HEADING, DosImportDialog, pane_text

    dialog = DosImportDialog(dos_save, files)
    assert dialog.conversion is not None
    text = dialog.report_pane.toPlainText()
    assert text == pane_text(dialog.conversion.report)
    assert DROPPED_HEADING not in text
    for line in dialog.conversion.report.dropped:
        assert line in text
    assert not re.search(r"\$[0-9A-F]{4}\b|0x[0-9A-Fa-f]+|\.py\b|#\d", text), text
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


@needs_dos_saves
def test_a_pool_of_radiance_import_with_no_creation_tables_converts_with_its_own_faces(
        app, dos_save):
    """A disk folder that carries `SPELLE64` and `ANIMATE00` but no readable
    `GEN` -- `GameFiles` with `portraits` `None` -- converts, and every
    character arrives with the face his own DOS record names, out of the
    stored menu (`goldbox.portraits.POOL_OF_RADIANCE_MENU`, 2026-09-06).
    For one night `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs the
    import working for all three C64 titles)` had this refuse in the pane
    with Convert disabled; Donald: *"We don't need to refuse game disks.
    Just store the IDs we would otherwise be looking up."*

    `icon` and `animate` are dummy bytes: what is under test is the third
    file nobody read, not the two.
    """
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import DosImportDialog, GameFiles
    from goldbox.portraits import stored_tables

    menu = stored_tables(None)
    dialog = DosImportDialog(dos_save, GameFiles(icon=bytes(36),
                                                 animate=bytes(852)))
    for slot in dos.slots_available(dos_save):
        party = dos.read_party(dos_save, slot)
        if all(menu.head_art(c.get("portrait_head")) is not None
               and menu.body_art(c.get("portrait_body")) is not None
               for c in party):
            break
    else:
        pytest.skip("no DOS slot here has every character in the menu")
    dialog.slots.setCurrentText(slot)
    assert dialog.conversion is not None
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "portrait" not in dialog.report_pane.toPlainText().lower()
    save0 = dialog.conversion.save0.to_bytes()
    assert save0[dos.PORTRAIT_SWITCH - dos.SAVE0_BASE] == dos.PORTRAIT_ON
    for index, char in enumerate(party):
        place = dos.marching_slot(index, len(party))
        rec_at = dos.SLOT_AREA - dos.SAVE0_BASE + place * dos.SLOT_STRIDE
        assert save0[rec_at + 0x0FE] == \
            menu.head_art(char.get("portrait_head")), char.name
        assert save0[rec_at + 0x0FF] == \
            menu.body_art(char.get("portrait_body")), char.name


@needs_dos_saves
@needs_disks
def test_the_save_points_at_the_area_the_dos_party_is_in(app, dos_save, files):
    """There is no template to agree or disagree with any more, so the
    loaded-files cache is computed from the DOS save alone every time.
    `docs/140-loaded-files-cache.md`."""
    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save, files)
    assert dialog.conversion is not None
    payload = dialog.conversion.save0.to_bytes()
    at = dos.FILE_CACHE[0] - dos.SAVE0_BASE
    there = dos_savegame.area_id(
        (dos_save / f"SAVGAM{dialog.slot}.DAT").read_bytes())
    want = bytearray(b"\xFF" * dos.FILE_CACHE[1])
    want[dos.CACHE_GEO] = want[dos.CACHE_ECL] = there
    # Slot 11: the save carries `ANIMATE00` in `SAVEDGAME1`'s tail, so the
    # cache has to say it is resident or the party cannot walk into an area
    # (#102). The literal 11 and 0, not the module's names, so this fails on a
    # renumbering rather than following it.
    want[11] = 0
    assert payload[at:at + dos.FILE_CACHE[1]] == bytes(want)


@needs_dos_saves
@needs_disks
def test_changing_the_slot_re_rehearses(app, dos_save, files):
    """Every change re-rehearses, so the pane is never the losses of a
    conversion other than the one the button would commit."""
    from editor.dosimport import DosImportDialog

    offered = dos.slots_available(dos_save)
    if len(offered) < 2:
        pytest.skip("needs a DOS save folder holding two slots")
    dialog = DosImportDialog(dos_save, files)
    first = dialog.conversion
    assert first is not None
    other = next(s for s in offered if s != dialog.slot)
    dialog.slots.setCurrentText(other)
    assert dialog.conversion is not None and dialog.conversion is not first
    assert dialog.conversion.slot == other


@needs_dos_saves
@needs_disks
def test_the_slots_offered_are_the_ones_the_folder_holds(app, dos_save, files):
    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save, files)
    offered = [dialog.slots.itemText(i) for i in range(dialog.slots.count())]
    assert offered == dos.slots_available(dos_save)


# --- the refusal when the game disks are missing (#118) ----------------------

def test_no_game_disks_is_a_pop_up_and_no_folder_picker(app, tmp_path,
                                                        monkeypatch):
    """Donald's ruling, 2026-08-27: *"We should never attempt to write a save
    file if we don't have the game disks and we need them. That would mean
    making up data, which we will not do."*

    The check fires **before** the folder picker, so a user with no disks is
    not asked to choose a folder and only then told it was pointless. This
    fails without the guard in two ways at once: the picker opens, and the
    box is never shown.
    """
    import editor.window as ew
    from editor.dosimport import NO_DISKS, NO_DISKS_TITLE
    from editor.window import EditorBinding

    said, picked = [], []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    monkeypatch.setattr(ew.QFileDialog, "getExistingDirectory",
                        lambda *a, **k: picked.append(a) or "")
    # An empty folder for the Game directory and nothing in the environment,
    # so nothing on this machine can be found however many disks it has.
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.delenv("POR_GAME_DISK", raising=False)
    empty = tmp_path / "no disks here"
    empty.mkdir()
    monkeypatch.chdir(empty)
    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(empty))
    assert window.import_dos_save() == "no game disks"
    assert said == [(NO_DISKS_TITLE, NO_DISKS)]
    assert picked == [], "the folder picker opened before the refusal"
    window.close()


@needs_disks
def test_with_the_game_disks_there_the_import_gets_as_far_as_the_picker(
        app, tmp_path, monkeypatch):
    """The other direction, which is what stops the refusal being a refusal of
    everything: with the disks configured the import goes on to the folder
    picker, and cancelling it is the only reason it stops."""
    import editor.window as ew
    from editor.window import EditorBinding

    said, picked = [], []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append(a))
    monkeypatch.setattr(ew.QFileDialog, "getExistingDirectory",
                        lambda *a, **k: picked.append(a) or "")
    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    assert window.import_dos_save() == "cancelled"
    assert said == []
    assert len(picked) == 1
    window.close()


@needs_disks
def test_a_disk_that_loads_once_but_fails_on_the_second_read_refuses(
        app, tmp_path, monkeypatch):
    """`_find_disk` proves `IconParts.load` succeeds *once*, on the probe
    read; `game_files_for_import` reads the same disk a second time to build
    the `GameFiles` it returns (#130 -- the table is now kept whole rather
    than reduced to one composed default at this point, so it is read once
    more rather than reused).  A corrupt or truncated `SPELLE64` that fails
    only on that second read must not escape the menu's slot uncaught:
    `wish/debuglog.py` logs it and **the user sees nothing at all happen**.

    What has to come back is the refusal the missing-disks case already
    gets, and no folder picker.
    """
    import editor.window as ew
    from editor.dosimport import NO_DISKS, NO_DISKS_TITLE
    from editor.window import EditorBinding
    from goldbox.iconparts import IconParts

    said, picked = [], []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    monkeypatch.setattr(ew.QFileDialog, "getExistingDirectory",
                        lambda *a, **k: picked.append(a) or "")

    # Construct the window with the real reader first -- it already calls
    # `IconParts.load` more than once for its own game-disk setup, and the
    # scenario this test wants is specific to `import_dos_save`'s own second
    # read, not to whatever `EditorBinding.__init__` did on the way up.
    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))

    real_load = IconParts.load
    calls = []

    def fails_on_the_second_call(disk):
        calls.append(disk)
        if len(calls) > 1:
            raise ValueError("SPELLE64 truncated on the second read")
        return real_load(disk)

    monkeypatch.setattr(IconParts, "load", staticmethod(fails_on_the_second_call))
    assert window.import_dos_save() == "no game disks"
    assert said == [(NO_DISKS_TITLE, NO_DISKS)]
    assert picked == []
    assert len(calls) > 1, "the scenario needs a second read to fail on"
    window.close()


@needs_disks
def test_the_game_files_an_import_needs_are_the_icon_and_animate(app, tmp_path):
    """What `game_files_for_import` actually found, rather than that it found
    something: the C64's own icon option tables (#130 -- kept whole rather
    than reduced to one composed default here, so each character can get his
    own figure later) and `ANIMATE00`'s own 852 bytes."""
    from editor.window import EditorBinding
    from goldbox.iconparts import IconParts

    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    found = window.game_files_for_import()
    assert found is not None
    assert isinstance(found.icon, IconParts)
    default = found.icon.default_icon()
    assert len(default) == 36 and any(default)
    assert len(found.animate) == 852 and any(found.animate)
    assert len(found.animate) == dos.ANIMATE_SIZE
    window.close()


@needs_disks
def test_the_game_files_an_import_needs_include_the_creation_menu(app, tmp_path):
    """`game_files_for_import` also reads the creation menu (#57) off the
    same disks directory, through `goldbox.portraits.tables_from_disks` --
    the wiring `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs the
    import working for all three C64 titles)` is waiting on.

    Before this wiring `GameFiles` carried no `portraits` field at all, so
    this raised `AttributeError` rather than finding one.
    """
    from editor.window import EditorBinding
    from goldbox.portraits import PortraitTables

    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    found = window.game_files_for_import()
    assert found is not None
    assert isinstance(found.portraits, PortraitTables)
    window.close()


@needs_dos_saves
@needs_disks
def test_an_import_started_from_the_window_carries_its_own_faces(app, tmp_path):
    """The whole chain, window to converted disk: `game_files_for_import`
    finds the creation menu, `rehearse` passes it on to `dos.new_save`, and a
    party wholly inside the fourteen-and-twelve menu comes back with the
    sheet portrait switched on.

    Reusing a `GameFiles` built by hand -- as the `files` fixture above does
    -- would say nothing about this: it never carries `portraits`, so it
    cannot tell a wired `rehearse` from one that still defaults to `None`.
    This is deliberately the one test in the module that goes through
    `EditorBinding.game_files_for_import` instead.
    """
    from editor.dosimport import rehearse
    from editor.window import EditorBinding

    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    game_files = window.game_files_for_import()
    assert game_files is not None and game_files.portraits is not None

    where = _save_dir()
    slot = None
    for candidate in dos.slots_available(where):
        party = dos.read_party(where, candidate)
        neutral = [dos.to_neutral(c, portraits=game_files.portraits)
                  for c in party]
        if all("portrait_head" in n and "portrait_body" in n
               for n in neutral):
            slot = candidate
            break
    if slot is None:
        pytest.skip("no DOS slot here has every character in the menu")

    conversion = rehearse(where, slot, game_files)
    at = dos.PORTRAIT_SWITCH - dos.SAVE0_BASE
    assert conversion.save0.to_bytes()[at] == dos.PORTRAIT_ON
    window.close()


# --- what reaches the editor -------------------------------------------------

@needs_dos_saves
@needs_disks
def test_the_import_lands_with_no_file_behind_it_and_save_as_writes_it(
        app, tmp_path, dos_save, files, monkeypatch):
    """The converted party is in the window, marked dirty, and there is **no
    path**: the disk was built in memory a moment ago and no file it could
    have come from exists. Save As is what names one, and that is the write.
    """
    import editor.window as ew
    from editor.dosimport import rehearse
    from editor.window import EditorBinding

    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"))
    note = window.adopt_conversion(rehearse(dos_save, "A", files))

    assert window.dirty                      # unsaved, and the title says so
    assert window.path is None, "an import has no file behind it"
    # The converter puts DOS marching position 0 in the *highest* C64 slot
    # (#101, `dos.marching_slot`), and the roster now lists the highest
    # occupied slot first (`#160`) -- so the window's own order is DOS's,
    # not its reverse.
    names = [m.name for m in window.party.members if m.name]
    assert names == [c.name for c in dos.read_party(dos_save, "A")]
    assert "slot A" in note or "A" in note

    out = tmp_path / "NEW.D64"
    monkeypatch.setattr(ew.QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    window.save_as()
    assert out.exists() and out.stat().st_size == 174848
    window.close()


# --- the destination row, and Convert writing (#118) -------------------------

@needs_dos_saves
@needs_disks
def test_the_destination_starts_filled_in_from_the_slot(app, dos_save, files,
                                                        tmp_path):
    """Donald picked a full path that starts filled in, so Convert has
    somewhere to write the moment the window opens: `PORSAVEJ.D64` for slot J,
    in the folder `File > Open` would have started in."""
    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save, files, start_dir=str(tmp_path))
    assert dialog.target() == str(tmp_path / f"PORSAVE{dialog.slot}.D64")


@needs_dos_saves
@needs_disks
def test_the_suggested_name_changes_with_the_slot(app, dos_save, files,
                                                  tmp_path):
    """The name is built out of the slot letter, so a slot the user changes
    their mind about must not leave the previous slot's name behind it."""
    from editor.dosimport import DosImportDialog

    offered = dos.slots_available(dos_save)
    if len(offered) < 2:
        pytest.skip("needs a DOS save folder holding two slots")
    dialog = DosImportDialog(dos_save, files, start_dir=str(tmp_path))
    other = next(s for s in offered if s != dialog.slot)
    dialog.slots.setCurrentText(other)
    assert dialog.target() == str(tmp_path / f"PORSAVE{other}.D64")


@needs_dos_saves
@needs_disks
def test_a_path_the_user_typed_survives_a_change_of_slot(app, dos_save, files,
                                                         tmp_path):
    """The other direction, and the one that would cost somebody their choice:
    a path somebody typed is theirs, and the slot stops rewriting the box."""
    from PyQt6.QtTest import QTest

    from editor.dosimport import DosImportDialog

    offered = dos.slots_available(dos_save)
    if len(offered) < 2:
        pytest.skip("needs a DOS save folder holding two slots")
    dialog = DosImportDialog(dos_save, files, start_dir=str(tmp_path))
    mine = str(tmp_path / "MINE.D64")
    dialog.destination.clear()
    # Typed, not `setText`: `textEdited` is what tells a box from a program
    # filling it in, and using `setText` here would test nothing.
    QTest.keyClicks(dialog.destination, mine)
    other = next(s for s in offered if s != dialog.slot)
    dialog.slots.setCurrentText(other)
    assert dialog.target() == mine


@needs_dos_saves
@needs_disks
def test_an_empty_destination_is_not_convertible(app, dos_save, files,
                                                 tmp_path):
    """Clearing the box is the one way to leave Convert with nowhere to write,
    and a disabled button says so without a sentence saying it."""
    from PyQt6.QtWidgets import QDialogButtonBox

    from editor.dosimport import DosImportDialog

    dialog = DosImportDialog(dos_save, files, start_dir=str(tmp_path))
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled()
    dialog.destination.clear()
    assert not ok.isEnabled()


@needs_dos_saves
@needs_disks
def test_convert_writes_the_file_the_window_names(app, tmp_path, dos_save,
                                                 monkeypatch):
    """The whole of Donald's ruling in one test: *"when the user clicks the
    Convert button, it does what the user expects. it converts."*

    Pressing Convert writes the `.d64` the bottom row names -- no Save As
    after it -- and what lands on disk is byte for byte the disk the rehearsal
    built, so the editor's save machinery carrying the write changes nothing
    about it. Afterwards the window has that file: a path, an `opened` signal,
    a title bar with the name in it and no unsaved mark.

    The comparison rehearsal uses `game_files_for_import` rather than the
    module-level `files` fixture: since the wiring in `#57 (Carry the
    character portrait across ports)` a `GameFiles` also carries the
    creation menu, and the fixture's hand-built one does not, so the two
    would legitimately disagree on the sheet portrait bytes.
    """
    from PyQt6.QtWidgets import QDialog

    import editor.dosimport as di
    from editor.dosimport import rehearse
    from editor.window import EditorBinding

    monkeypatch.setattr(di.DosImportDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent),
                          last_save_folder=str(tmp_path))
    opened = []
    window.opened.connect(opened.append)

    slot = dos.slots_available(dos_save)[0]
    game_files = window.game_files_for_import()
    note = window.import_dos_save(folder=str(dos_save))
    out = tmp_path / f"PORSAVE{slot}.D64"

    assert out.exists(), f"Convert wrote nothing; it said {note!r}"
    assert out.read_bytes() == \
        rehearse(dos_save, slot, game_files).disk.to_bytes()
    assert window.path == out
    assert not window.dirty
    assert opened == [str(out)]
    assert out.name in note
    assert out.name in window.root.windowTitle()
    assert "*" not in window.root.windowTitle()
    window.close()


@needs_dos_saves
@needs_disks
def test_a_write_that_cannot_happen_is_a_sentence_in_the_report_pane(
        app, tmp_path, dos_save, monkeypatch):
    """A refused write reaches the user as the sentence it raised, in the pane
    the losses are already reported in, with the window still open on the path
    that has to change -- not as a traceback in the log and nothing on screen.

    No backup folder is the refusal that can be stood up without depending on
    what a filesystem allows: `editor/files.py` will not overwrite a save with
    nowhere to put the copy, and it checks that before it looks at whether the
    target exists.
    """
    from PyQt6.QtWidgets import QDialog

    import editor.dosimport as di
    import editor.window as ew
    from editor.window import EditorBinding

    tries = []

    def once(self):
        tries.append(self)
        return (QDialog.DialogCode.Accepted if len(tries) == 1
                else QDialog.DialogCode.Rejected)

    monkeypatch.setattr(di.DosImportDialog, "exec", once)
    # A window somebody is managing the backup folder for, and it is unset --
    # `wish/window.py` hands over `""` before any save has been opened.
    window = EditorBinding(make_root(), backups="", disks=str(game_disk().parent),
                          last_save_folder=str(tmp_path))
    assert window.import_dos_save(folder=str(dos_save)) == "cancelled"

    said = tries[0].report_pane.toPlainText()
    assert "backup" in said.lower(), said
    assert not said.startswith("Traceback")
    assert sorted(p.name for p in tmp_path.iterdir()) == []
    # The party is still in the window and still unsaved, which is the honest
    # state and is what a failed Save As leaves too -- so closing asks, and a
    # test that did not answer would block here forever.
    assert window.dirty
    monkeypatch.setattr(ew.QMessageBox, "question",
                        lambda *a, **k: ew.QMessageBox.StandardButton.Discard)
    window.close()


@needs_dos_saves
@needs_disks
def test_import_dos_save_is_cancellable_without_touching_anything(
        app, tmp_path, dos_save, monkeypatch):
    """A folder picker dismissed is a menu item that did nothing."""
    from editor.window import EditorBinding

    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    before = sorted(p.name for p in tmp_path.iterdir())
    assert window.import_dos_save(folder="") == "cancelled"
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    window.close()


@needs_disks
def test_a_folder_with_no_dos_save_says_so(app, tmp_path, monkeypatch):
    """And says it in a box rather than opening an empty conversion window."""
    import editor.window as ew
    from editor.window import EditorBinding

    said = []
    monkeypatch.setattr(ew.QMessageBox, "warning",
                        lambda *a, **k: said.append(a[2]))
    window = EditorBinding(make_root(), backups=str(tmp_path / "backups"),
                          disks=str(game_disk().parent))
    assert window.import_dos_save(folder=str(tmp_path)) == "no DOS save"
    assert said and str(tmp_path) in said[0]
    window.close()


# --- the menu ----------------------------------------------------------------

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


def test_the_file_menu_carries_the_import_with_nothing_set(app, tmp_path,
                                                           monkeypatch):
    """`File ▸ Import ▸ DOS Save Folder…` is built for everyone.

    It sat behind `WISH_EXPERIMENTAL_DOS_IMPORT` until `#131 (Lift
    WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import working for all
    three C64 titles)` closed; the three tests that proved the gate held
    came down with the gate, and this is the direction they never covered.
    """
    from editor.dosimport import MENU_DOS_SAVE, MENU_IMPORT

    monkeypatch.delenv("WISH_EXPERIMENTAL_DOS_IMPORT", raising=False)
    window = _window(tmp_path, monkeypatch)
    submenu = next(a.menu() for a in _file_menu(window).actions()
                   if a.text() == MENU_IMPORT)
    assert [a.text() for a in submenu.actions()] == [MENU_DOS_SAVE]
    assert window.import_dos_action.text() == MENU_DOS_SAVE
    window.close()


@pytest.mark.parametrize("value", ["1", "0", "true", "off", "", "no"])
def test_the_import_does_not_depend_on_the_removed_variable(app, tmp_path,
                                                            monkeypatch,
                                                            value):
    """A player who exported the old flag once, at any value, before its
    removal (#131), gets the same File menu as everyone else."""
    def file_menu_texts():
        window = _window(tmp_path, monkeypatch)
        try:
            return [a.text() for a in _file_menu(window).actions()]
        finally:
            window.close()

    monkeypatch.setenv("WISH_EXPERIMENTAL_DOS_IMPORT", value)
    with_var = file_menu_texts()
    monkeypatch.delenv("WISH_EXPERIMENTAL_DOS_IMPORT", raising=False)
    assert with_var == file_menu_texts()


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

    exc = dos.WrongTitleError(
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
def test_the_pane_shows_the_players_sentence_and_not_the_exception(
        app, dos_save, files, monkeypatch):
    """The routing, which is the half a unit test of the exception cannot see.

    `_attempt` used to put `str(exc)` straight into the pane. Reverting that
    turns this red: the pane fills with the tracker's sentence instead.
    """
    from editor import dosimport

    def refuse(*_args, **_kwargs):
        raise dos.WrongTitleError(
            "Curse of the Azure Bonds records read, but only Pool of "
            "Radiance converts: no other pair of ports has been measured "
            "against each other (#53)",
            title="Curse of the Azure Bonds")

    dialog = dosimport.DosImportDialog(dos_save, files)
    monkeypatch.setattr(dosimport, "rehearse", refuse)
    dialog._rehearse()

    assert dialog.report_pane.toPlainText() == (
        "Curse of the Azure Bonds imports not yet supported.")


def test_a_refusal_cannot_be_raised_without_naming_the_title():
    """`title` is required, so a caller that forgets it fails at the raise
    site rather than putting `" imports not yet supported."` -- leading space,
    lower case, no game named -- in front of a player.

    Found in the code review of `#176 (A player importing a Curse of the Azure
    Bonds save is shown an issue number)`. It was unreachable when it was
    found; this is what keeps it that way.
    """
    with pytest.raises(TypeError):
        dos.WrongTitleError("the developer's reason")


# --- every other refusal a player reads (#195) ------------------------------

#: The two developer sentences `#195 (The import pane shows a player a
#: memory address when the conversion refuses for any reason but the wrong
#: title)` names as confirmed reachable from `rehearse` -> `dos.new_save`,
#: quoted from `goldbox/dos.py:new_save` and `goldbox/dos.py:apply_file_cache`
#: so the test forces the real wording rather than a guess at it.
_UNWRITTEN_BYTES_MESSAGE = (
    "29 bytes of the save have no source and were left zero by accident "
    "rather than by measurement; the first is SAVEDGAME0 $8300")
_OUTDOOR_DISAGREEMENT_MESSAGE = (
    "the save's own $49E6 says outdoors, but script id 12 (Kuto's Well) is "
    "marked indoors in goldbox/areas.py -- these two disagree and neither "
    "is trusted over the other")


def _fake_dos_dir(tmp_path):
    """A folder `dos.slots_available` reads as holding slot A, with none of
    a real DOS save's files in it. `rehearse` is monkeypatched in every test
    below, so nothing here ever reads a character out of it."""
    (tmp_path / "SAVGAMA.DAT").write_bytes(b"")
    return tmp_path


def _fake_files():
    from editor.dosimport import GameFiles
    return GameFiles(icon=b"\x00" * 36, animate=b"\x00" * 852)


@pytest.mark.parametrize("message", [
    _UNWRITTEN_BYTES_MESSAGE, _OUTDOOR_DISAGREEMENT_MESSAGE,
    "an area with no row in our table",
])
def test_the_pane_shows_the_fallback_and_not_the_developers_sentence(
        message, app, tmp_path, monkeypatch):
    """`_attempt` used to catch `dos.WrongTitleError` specially and fall
    through to `str(exc)` for everything else, so a real refusal -- the
    unwritten-bytes one, or the outdoor-signals one -- filled the pane with
    `SAVEDGAME0 $8300` or `goldbox/areas.py`. This forces each of those two
    confirmed developer sentences through the real dialog and checks what a
    player would actually read, not a list of expected strings: it asserts
    the exact approved sentence, and separately that nothing matching a
    memory address, a source path or an issue number reaches the pane, so a
    fallback that echoed part of `message` back would still be caught.
    """
    import re

    from editor import dosimport

    def refuse(*_args, **_kwargs):
        raise dos.DosRecordError(message)

    folder = _fake_dos_dir(tmp_path)
    dialog = dosimport.DosImportDialog(folder, _fake_files())
    monkeypatch.setattr(dosimport, "rehearse", refuse)
    dialog._rehearse()

    shown = dialog.report_pane.toPlainText()
    assert shown == "This save cannot be converted."
    assert not re.search(r"\$[0-9A-F]{4}\b", shown), (
        f"a memory address reaches the pane: {shown!r}")
    assert not re.search(r"\.py\b", shown), (
        f"a source file name reaches the pane: {shown!r}")
    assert not re.search(r"#\d", shown), (
        f"an issue number reaches the pane: {shown!r}")


def test_the_pane_shows_the_fallback_for_a_refusal_dos_record_error_never_names(
        app, tmp_path, monkeypatch):
    """Not every refusal is a `DosRecordError` -- `_attempt`'s bare `except
    Exception` is what stands between an unanticipated one and a raw
    traceback in the pane. It must show the same approved sentence, not
    `str(exc)`.
    """
    from editor import dosimport

    def refuse(*_args, **_kwargs):
        raise RuntimeError("$49E6 disagrees with goldbox/areas.py (#99)")

    folder = _fake_dos_dir(tmp_path)
    dialog = dosimport.DosImportDialog(folder, _fake_files())
    monkeypatch.setattr(dosimport, "rehearse", refuse)
    dialog._rehearse()

    assert dialog.report_pane.toPlainText() == "This save cannot be converted."
