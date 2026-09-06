"""Turning a DOS save into a C64 one, with the losses named first.

`goldbox/dos.py` does the conversion and this is the window over it. The one thing
this file exists for is the order of events: a DOS save carries fields the C64
has no home for -- encumbrance, the item heap pointers, the item count, the
icon selection, the strength-bonus boolean, every running spell effect -- and
`docs/117-save-conversion.md` forbids dropping them in silence. So the
conversion is **rehearsed** in memory, the losses it reports are put on
screen, and only then is there a button to press. The file the write goes to
is named in this window, on the bottom row, before Convert is pressed --
Donald's shape, 2026-08-27: *"when the user clicks the Convert button, it does
what the user expects. it converts."* The write itself is still the editor's
own Save, so the backup guarantee in `editor/files.py` covers this the way it
covers every other write.

**There is no template any more** (#118). The dialog used to make the user
pick an existing `.d64` to convert *onto*, and every byte the conversion did
not explicitly set kept the value it had in somebody else's saved game -- a
different party, in a different place, at a different time. `goldbox.dos`
now writes all 9216 bytes of both payloads and `D64.blank()` carries them, so
what the user gets is theirs and nothing else's.

What that costs is the player's own `POOL*` disks at the moment the import
runs: the combat icon is composed out of `SPELLE64`/`SPELLN64` and `$8400` is
`ANIMATE00`, and neither may be stored here. Donald's ruling, 2026-08-27 --
*"We should never attempt to write a save file if we don't have the game
disks and we need them. That would mean making up data, which we will not
do."* -- so `editor/window.py` checks for them before the folder picker opens
and refuses with a pop-up.

A DOS save is a *directory* of loose files and a C64 save is one `.d64`, so
the two are never told apart by sniffing: the first picker asks for a folder.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QWidget,
)

from goldbox import dos, games
from goldbox.iconparts import IconParts
from goldbox.portraits import PortraitTables
from goldbox.savegame import SaveGame0, SaveGame1

from .ui_dosimport import Ui_DosImportDialog

_log = logging.getLogger("wish.editor.dosimport")


# Every string below is Donald's -- approved 2026-08-24, and the refusal
# 2026-08-27. Changing one is his call, not a refactor.

#: **Off unless `WISH_EXPERIMENTAL_DOS_IMPORT=1`.** The conversion works and is proven --
#: a C64 party built from a DOS save loads and walks -- but what it cannot
#: carry is still being closed out: the sheet portrait (#57) and the clock
#: (#58) are dropped in this direction too. Until those land the menu entry
#: is not built at all, so a player cannot reach a conversion that quietly
#: loses two things.
#:
#: An environment variable and no preference, which is deliberate. The same
#: shape as `WISH_DEBUG` and `WISH_NATIVE_LOG`: a checkbox would need a label
#: and a sentence explaining what "experimental" meant, and this interface has
#: had several such sentences removed already.
#:
#: **Comes off when #57 and #58 close** -- the portrait and the clock -- **when
#: the import works for all three C64 titles (#131)**, **and when the README
#: says how the first picker works.** The three titles are Donald's bar, set
#: 2026-08-27: Pool of Radiance, Curse of the Azure Bonds and Secret of the
#: Silver Blades all have to convert, and Pools of Darkness may refuse,
#: because the Amiga export it would need is not finished. Only Pool of
#: Radiance has been played from a converted save so far. The README condition
#: is about the first picker: it asks for the *folder* a DOS save lives in,
#: not a file, because one save is a dozen or more loose
#: files with no single one to point at. That is defensible and it is not
#: guessable: Donald, who wrote the format documentation, was stopped by it on
#: 2026-08-26 -- the folder holds no subdirectories, so the dialog listed
#: nothing and there was no sign he was already standing in the right place.
#: A player meeting it cold has less to go on than he did.
#:
#: **A fourth condition, and it is the largest: nothing may be dropped at
#: all.** Donald, 2026-09-04: *"We should not be dropping anything when
#: converting a save. Anything less is a bug, and the feature flag cannot be
#: lifted until that is true."* So `goldbox.dos.DROPPED` and every list like
#: it must be empty, and every entry standing on one today is a bug with an
#: issue of its own rather than a documented exemption -- see
#: `.claude/rules/conversions.md`. That subsumes the portrait and the clock,
#: which were only the two drops anybody had named. Four conditions, all
#: stated; a flag with no way out is a second code path kept forever.
ENV = "WISH_EXPERIMENTAL_DOS_IMPORT"

#: Anything else -- an empty string, `0`, `off` -- is off, matching
#: `wish/debugmode.py`. A variable somebody exported once and forgot should
#: not put an unfinished menu in front of them.
TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    """Is the DOS import offered in this run?"""
    import os
    return os.environ.get(ENV, "").strip().lower() in TRUE


#: The File menu entry and the submenu it hangs under.
MENU_IMPORT = "&Import"
#: The entry says **Folder** because the picker behind it asks for one -- a
#: DOS save is a dozen loose files with no single one to point at, and
#: "DOS…" read as a file chooser.  Donald's wording, approved 2026-08-26.
MENU_DOS_SAVE = "&DOS Save Folder…"

#: The folder picker, and what is said when the folder holds no DOS save.
FOLDER_TITLE = "Choose a DOS save folder"
NO_SLOTS_TITLE = "No DOS save here"
NO_SLOTS = "{folder} holds no DOS Pool of Radiance save."

#: The conversion window.
DIALOG_TITLE = "Import a DOS save"
LABEL_FOLDER = "DOS save"
LABEL_SLOT = "Slot"
BUTTON_CONVERT = "Convert"

#: The destination row, from the mock-up Donald picked on #118: a full path,
#: filled in before he touches it, and a button beside it. *"when the user
#: clicks the Convert button, it does what the user expects. it converts."*
#: -- so there is no Save As after this window any more.
LABEL_DESTINATION = "Save as"
BUTTON_BROWSE = "Browse…"

#: What the path is suggested as. The C64 game's own save name with the DOS
#: slot letter in it, so importing slot J offers `PORSAVEJ.D64`. The letter is
#: the slot's, so the box is rebuilt every time the slot changes or it goes on
#: naming a slot nobody is converting -- but never over a path the user typed
#: or browsed to, which is theirs.
DEFAULT_NAME = "PORSAVE{slot}.D64"

#: The heading over the list of what a converted character loses.
#:
#: **PROPOSED, not yet approved** -- replaces "The conversion cannot carry
#: these:", which named fields and a conversion rather than the player's own
#: party; `.claude/rules/gui-text.md` makes the wording Donald's.
DROPPED_HEADING = "Wish cannot currently convert these fields:"

#: The refusal when the player's game disks cannot be found, which is the one
#: thing the conversion cannot do without: the combat icon comes out of
#: `SPELLE64` and `$8400` out of `ANIMATE00`, and neither may be stored here.
#: Donald's wording, approved 2026-08-27, a title and one line and no more.
#: It fires **before** the folder picker, so nothing has been chosen and no
#: dialog is left standing behind the error.
NO_DISKS_TITLE = "Game disks not found"
NO_DISKS = ("You must set the Game Disk folder in File ▸ Preferences… "
            "before importing a character.")

#: The status line when a conversion reaches the window with no file behind
#: it. Convert names one and writes it, so what a user sees after an import is
#: `editor/files.py`'s own line about the file it wrote; this is what is left
#: for a caller that adopts a conversion without a path.
CONVERTED = "converted DOS slot {slot} - not saved yet"
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GameFiles:
    """The two things off the player's game disks a conversion cannot do
    without.

    Held together because the refusal is one question -- can this import read
    the player's disks? -- and answering it twice in two places is how the two
    halves drift apart.

    **Which disk each came from is not kept.** It was, and nothing ever read
    it: the one place the disks have to be named is the log line
    `editor/window.py` writes when the second read fails, and that runs where
    there is no `GameFiles` to have named them.
    """

    #: `SPELLE64`/`SPELLN64`, read into an `IconParts` (#130): each converted
    #: character gets the combat figure his own DOS record names, through
    #: `IconParts.dos_icon`.
    icon: bytes | IconParts
    #: `ANIMATE00`'s 852-byte payload, which goes at `$8400`.
    animate: bytes
    #: The creation menu's two tables (#57), or `None` when no disk here
    #: carries `GEN`. Unlike `icon` and `animate` a conversion does not
    #: refuse without it -- a party converted with `portraits` `None` keeps
    #: its own records but arrives with the sheet portrait switched off, the
    #: same as an engine-written save with it turned off.
    portraits: PortraitTables | None = None


@dataclasses.dataclass
class Conversion:
    """A converted save, held in memory. Nothing here has been written."""

    #: A `.d64` built by `goldbox.dos.save_disk` and carrying nothing but the
    #: two files this conversion wrote -- so `disk.to_bytes()` is what a save
    #: would write, and every byte of it is this party's.
    disk: Any
    game: Any
    save0: SaveGame0
    save1: SaveGame1 | None
    report: dos.Report
    folder: pathlib.Path
    slot: str


def rehearse(folder: str | pathlib.Path, slot: str,
             files: GameFiles) -> Conversion:
    """Build the save and the disk in memory and report, writing nothing.

    The DOS files are read, the game files in `files` were read before this
    was called, and the result exists only as the returned `Conversion`.
    Anything `goldbox.dos.new_save` refuses raises from in here, which is what
    the dialog turns into a sentence.

    **The title comes from the save itself, not from an assumption.** A
    character's own record length names its shape (`goldbox.dos.shape_for`),
    so a Curse or Silver Blades folder converts into its own title rather than
    being written out as a Pool of Radiance save it never was (#192). A
    Curse save has no separate roster file -- its roster lives inside the one
    payload `goldbox/c64_save.py` describes -- so `save1` stays `None` rather
    than an empty `SaveGame1`, which the constructor would refuse anyway.
    """
    party = dos.read_party(folder, slot)
    try:
        game = games.by_key(party[0].shape.key)
    except games.UnknownGameError:
        # Pools of Darkness is the one title this reads and `goldbox/games.py`
        # does not list, because there is no C64 port to convert it to. Before
        # the title came from the save, that folder ran on into `to_neutral`
        # and got Donald's own sentence for exactly this case (#176). Without
        # this, `UnknownGameError` is not a `DosRecordError`, so the dialog
        # falls through to "This save cannot be converted." and the player is
        # told less than we know.
        raise dos.WrongTitleError(
            f"{party[0].shape.title} has no C64 port to convert to, so "
            f"goldbox/games.py has no entry for it (#176)",
            party[0].shape.title) from None
    payload0, payload1, report = dos.new_save(folder, slot,
                                              files.icon, files.animate,
                                              portraits=files.portraits,
                                              game=game)
    sg0 = SaveGame0.from_bytes(bytes(payload0), game)
    sg1 = SaveGame1(bytes(payload1), game) if payload1 else None
    disk = dos.save_disk(bytes(payload0), bytes(payload1), game)
    return Conversion(disk, game, sg0, sg1, report,
                      pathlib.Path(folder), slot)


def dropped_text(report: dos.Report) -> str:
    """The losses, one to a line, under a heading -- or nothing at all.

    The lines themselves are `goldbox/dos.py`'s -- the same words the command line
    prints -- so the report a menu shows and the report a terminal shows cannot
    drift into being two different accounts of the same conversion.

    Empty when nothing was dropped (#338): the heading says something was
    lost, and a heading over no lines told a player that with nothing to
    back it up. A caller that puts more text after this one must not glue a
    blank line onto an empty string either.
    """
    if not report.dropped:
        return ""
    return "\n".join([DROPPED_HEADING, ""]
                     + [f"  {d}" for d in report.dropped])


class DosImportDialog(QDialog):
    """The folder, the slot, what will be lost, and where it goes.

    Every change to the slot re-runs `rehearse`, so the pane is never showing
    the losses of a conversion other than the one the button would commit --
    and Convert is disabled unless there is a rehearsal behind it and a path
    in front of it.

    The bottom row is the destination, and it is why there is no Save As after
    this window any more: the file is named before Convert is pressed, so
    Convert converts.

    `files` is the icon and `ANIMATE00`, already read: `editor/window.py`
    refuses the whole import before this window is built when they cannot be
    found, so by the time anything here runs they exist.
    """

    def __init__(self, folder: str | pathlib.Path, files: GameFiles,
                 parent: QWidget | None = None, start_dir: str = ""):
        super().__init__(parent)
        self.ui = Ui_DosImportDialog()
        self.ui.setupUi(self)
        self.folder = pathlib.Path(folder)
        self.files = files
        self.conversion: Conversion | None = None
        #: Where a suggested path is put. `editor/window.py` hands over what
        #: `editor/files.py`'s `open_start_dir` answered -- the saves folder
        #: preference if one is set, otherwise beside the open save, or the
        #: folder one was last opened from -- so an import and a `File > Open`
        #: start in the same place rather than under two rules. That answer is
        #: empty when none of those apply, and a field that has to show a path
        #: cannot be empty, so the home directory is the last resort.
        self.start_dir = start_dir or str(pathlib.Path.home())
        #: The user has typed a path or browsed to one, and the slot must stop
        #: rewriting it.
        self._named = False

        self._folder_label = self.ui.dos_folder
        self._folder_label.setText(str(self.folder))

        self.slots = self.ui.dos_slot
        self.slots.addItems(dos.slots_available(self.folder))
        self.slots.currentTextChanged.connect(lambda _t: self._rehearse())

        self.report_pane = self.ui.dos_report

        self.destination = self.ui.dos_destination
        self.destination.textEdited.connect(self._typed)
        self.destination.textChanged.connect(lambda _t: self._settle_button())

        self.browse_button = self.ui.dos_browse
        self.browse_button.clicked.connect(self.browse)

        self.buttons = self.ui.buttons
        self.buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText(BUTTON_CONVERT)

        self._rehearse()

    # -- the parts ---------------------------------------------------------

    @property
    def slot(self) -> str:
        return self.slots.currentText()

    def target(self) -> str:
        """The file Convert writes, as the user has left it."""
        return self.destination.text().strip()

    # -- where it goes -----------------------------------------------------

    def _typed(self, _text: str) -> None:
        """Anything the user types in the box is theirs from then on."""
        self._named = True

    def _suggest(self) -> None:
        """Fill the destination in from the slot, over nothing the user chose.

        The name is the slot's -- `PORSAVEJ.D64` for slot J -- so it has to be
        rebuilt whenever the slot changes or it goes on naming a slot that is
        no longer being converted.
        """
        if self._named:
            return
        self.destination.setText(
            str(pathlib.Path(self.start_dir)
                / DEFAULT_NAME.format(slot=self.slot or "")))

    def browse(self) -> None:
        """The editor's own Save As picker, with its own title and filter.

        Imported here rather than worded again: it is the same picker doing
        the same job, and two copies of an approved string is how they drift.
        """
        from PyQt6.QtWidgets import QFileDialog

        from .window import DISK_FILTER, SAVE_AS_TITLE

        path, _ = QFileDialog.getSaveFileName(self, SAVE_AS_TITLE,
                                              self.target(), DISK_FILTER)
        if path:
            self._named = True
            self.destination.setText(path)

    def refuse(self, text: str) -> None:
        """Put a failed write in the pane the losses are already reported in.

        The window stays open on the path that did not work, which is the one
        thing the user has to change -- and it is a sentence rather than the
        traceback that reaches `wish/debuglog.py`.
        """
        self.report_pane.setPlainText(text)

    # -- the rehearsal -----------------------------------------------------

    def _rehearse(self) -> None:
        """Build the save in memory, and put what it costs on screen.

        Failures are shown, not raised: a refusal reaches the user as its own
        message while the log keeps the traceback, which is a sentence in the
        pane rather than what looks like a broken menu item.
        """
        self.conversion = None
        text = self._attempt()
        self.report_pane.setPlainText(text)
        self._suggest()
        self._settle_button()

    def _settle_button(self) -> None:
        """Convert is pressable when there is a conversion and somewhere to
        put it. Clearing the box is the one way a user can leave it with
        nowhere, and a disabled button says so without a sentence saying it."""
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.conversion is not None and bool(self.target()))

    def _attempt(self) -> str:
        # No slot is not a state the user can reach: `import_dos_save` refuses
        # a folder with no DOS save in it before this window is built. An
        # empty pane rather than a sentence, because a sentence about a state
        # nobody can be in is a sentence nobody should have to read.
        if not self.slot:
            return ""
        try:
            self.conversion = rehearse(self.folder, self.slot, self.files)
        except dos.DosRecordError as exc:
            # The exception text is written for the tracker and may carry an
            # issue number, an address or a source file name; a player reads
            # `player_message` instead -- `WrongTitleError`'s own sentence, or
            # `dos.CANNOT_CONVERT` for every other refusal (#176, #195).
            _log.exception("could not convert %s slot %s",
                           self.folder, self.slot)
            return exc.player_message
        except Exception:
            # Anything `DosRecordError` does not cover is still not a
            # developer's traceback in front of a player (#195).
            _log.exception("could not convert %s slot %s",
                           self.folder, self.slot)
            return dos.CANNOT_CONVERT
        return dropped_text(self.conversion.report)
