from __future__ import annotations


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


"""`goldbox/dos.py`'s DOS → C64 converter, at the layer under any window:
`rehearse`, `pane_text`, `dropped_text` and `GameFiles`, and what
`editor/window.py`'s `EditorBinding.game_files_for_import` and
`adopt_conversion` still do with them.

`File ▸ Import ▸ DOS Save Folder…`, which drove all four through its own
`DosImportDialog`, is gone -- `#52 (File ▸ Import and File ▸ Export for
every direction the library supports)`'s step 5, since `File ▸ Convert…`
does the same job and, since `#416 (The live Convert dialog never shows a
DOS→C64 conversion's own messages or capacity-ceiling warnings)`, shows
everything the old dialog's pane did; `editor/convert.py`'s own window is
`tests/test_convert.py`'s. `EditorBinding.game_files_for_import` and
`adopt_conversion` are no longer reached from any menu -- nothing in
`wish/window.py` calls them any more -- and are tested here directly
because deleting them was not this ticket's to do.

What survives here is the one thing a menu can get wrong that a command
line cannot: **the losses are on screen before anything is written**.

Both halves need somebody's files. The DOS save is Donald's unpacked copy of
*Forgotten Realms: The Archives* (`$FR_ARCHIVES`) and the game disks are his
`POOL*.D64`; with either missing the tests that need them skip, which is what
CI does. Nothing here opens a window: `tests/conftest.py` forces the offscreen
platform before Qt is imported.
"""


import gamedata
import pytest
from gamedata import disk_dir, game_disk
from test_dossave import _save_dir, needs_dos_saves

from goldbox import dos

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


# --- the renderers: `pane_text` (the current window's) and `dropped_text`
# (nobody's, kept because #52's step 5 is not the ticket that deletes it) ---

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


def test_pane_text_puts_a_loss_between_the_messages_and_the_drops():
    """#399 (A conversion that runs out of item or trait slots tells the
    player nothing, because the pane never shows a warning): `losses` is a
    third source `pane_text` reads, between `messages` and `dropped`, with
    the same blank-line rule as the other two -- and a plain `Report`, which
    has no `losses` either, still renders its drops alone."""
    from editor.dosimport import pane_text
    from goldbox.dos import NOT_SET_OUT, C64SaveReport, Report

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
        "4 dropped from the end\n\n"
        "A drop line")
    plain = Report()
    plain.dropped.append("Only a drop")
    assert pane_text(plain) == "Only a drop"


@pytest.mark.skipif(not gamedata.have_specimen("por-item-twenty"),
                    reason="needs the twenty-item specimen")
def test_a_real_conversion_that_truncates_items_shows_it_in_the_pane():
    """The same specimen `#399`'s own measurement used, driven through
    `dos.convert_save` exactly as `rehearse` drives it -- no game disks
    needed, since neither the combat icon nor `ANIMATE00` change whether the
    inventory truncates."""
    from editor.dosimport import pane_text

    save0 = bytearray(0x1C00)
    save1 = bytearray(0x0800)
    report = dos.convert_save(gamedata.specimen("por-item-twenty"), "G",
                              save0, save1)
    text = pane_text(report)
    assert "WISHFTR" in text and "carry only sixteen" in text
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
    report = dos.convert_save(gamedata.specimen("por-party-l1"), "C",
                              save0, save1)
    text = pane_text(report)
    assert "do not fit" not in text
    assert "quest-flag" not in text
    assert "emptied" not in text


def test_a_conversion_that_drops_nothing_gets_no_heading():
    """#338 (The conversion pane says fields could not be converted and then
    lists none): a heading over no lines told a player something was lost
    with nothing to name, which is worse than saying nothing."""
    from editor.dosimport import dropped_text
    from goldbox.dos import Report

    assert dropped_text(Report()) == ""


# --- what `EditorBinding` still does with the library ------------------------

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


def test_the_file_menu_no_longer_carries_the_dos_import_submenu(
        app, tmp_path, monkeypatch):
    """`File ▸ Import ▸ DOS Save Folder…` is gone (`#52 (File ▸ Import and
    File ▸ Export for every direction the library supports)`'s step 5):
    `File ▸ Convert…` does the same job and, since `#416 (The live Convert
    dialog never shows a DOS→C64 conversion's own messages or
    capacity-ceiling warnings)`, shows everything the old dialog's pane did.

    The two strings are hard-coded rather than imported from
    `editor.dosimport` -- which no longer defines them -- because what this
    proves is their *absence*, not their wording.
    """
    monkeypatch.delenv("WISH_EXPERIMENTAL_DOS_IMPORT", raising=False)
    monkeypatch.delenv("WISH_EXPERIMENTAL_CONVERT", raising=False)
    window = _window(tmp_path, monkeypatch)
    texts = [a.text() for a in _file_menu(window).actions()]
    assert "&Import" not in texts
    assert not hasattr(window, "import_dos_action")
    window.close()


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
