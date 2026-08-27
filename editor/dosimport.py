"""Turning a DOS save into a C64 one, with the losses named first.

`goldbox/dos.py` does the conversion and this is the window over it. The one thing
this file exists for is the order of events: a DOS save carries fields the C64
has no home for -- encumbrance, the item heap pointers, the item count, the
icon selection, the strength-bonus boolean, every running spell effect -- and
`docs/117-save-conversion.md` forbids dropping them in silence. So the
conversion is **rehearsed** in memory, the losses it reports are put on
screen, and only then is there a button to press. Nothing reaches a disk until
the user names a file through the editor's own Save As, which is what keeps
the backup guarantee in `editor/files.py` covering this the way it covers
every other write.

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
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from goldbox import dos, games
from goldbox.savegame import SaveGame0, SaveGame1

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
#: **Comes off when #57 and #58 close** -- the portrait and the clock -- **and
#: when the README says how the first picker works.** It asks for the *folder*
#: a DOS save lives in, not a file, because one save is a dozen or more loose
#: files with no single one to point at. That is defensible and it is not
#: guessable: Donald, who wrote the format documentation, was stopped by it on
#: 2026-08-26 -- the folder holds no subdirectories, so the dialog listed
#: nothing and there was no sign he was already standing in the right place.
#: A player meeting it cold has less to go on than he did. Two conditions, both
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

#: The heading over the list of fields the conversion cannot carry.
DROPPED_HEADING = "The conversion cannot carry these:"

#: The refusal when the player's game disks cannot be found, which is the one
#: thing the conversion cannot do without: the combat icon comes out of
#: `SPELLE64` and `$8400` out of `ANIMATE00`, and neither may be stored here.
#: Donald's wording, approved 2026-08-27, a title and one line and no more.
#: It fires **before** the folder picker, so nothing has been chosen and no
#: dialog is left standing behind the error.
NO_DISKS_TITLE = "Game disks not found"
NO_DISKS = "Set the folder in File ▸ Preferences…"

#: The status line after the conversion, which has written nothing yet.
CONVERTED = "converted DOS slot {slot} - not saved yet"
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GameFiles:
    """The two things off the player's game disks a conversion cannot do
    without, and which disk each came from.

    Held together because the refusal is one question -- can this import read
    the player's disks? -- and answering it twice in two places is how the two
    halves drift apart.
    """

    #: The 36-byte combat icon every converted character gets, composed from
    #: `SPELLE64`/`SPELLN64` by `IconParts.default_icon`.
    icon: bytes
    #: `ANIMATE00`'s 852-byte payload, which goes at `$8400`.
    animate: bytes
    icon_disk: str
    animate_disk: str


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
    files: GameFiles


def rehearse(folder: str | pathlib.Path, slot: str,
             files: GameFiles) -> Conversion:
    """Build the save and the disk in memory and report, writing nothing.

    The DOS files are read, the game files in `files` were read before this
    was called, and the result exists only as the returned `Conversion`.
    Anything `goldbox.dos.new_save` refuses raises from in here, which is what
    the dialog turns into a sentence.
    """
    payload0, payload1, report = dos.new_save(folder, slot,
                                              files.icon, files.animate)
    game = games.POOL_OF_RADIANCE
    sg0 = SaveGame0.from_bytes(bytes(payload0), game)
    sg1 = SaveGame1(bytes(payload1), game)
    disk = dos.save_disk(bytes(payload0), bytes(payload1), game)
    return Conversion(disk, game, sg0, sg1, report,
                      pathlib.Path(folder), slot, files)


def dropped_text(report: dos.Report) -> str:
    """The losses, one to a line, under a heading.

    The lines themselves are `goldbox/dos.py`'s -- the same words the command line
    prints -- so the report a menu shows and the report a terminal shows cannot
    drift into being two different accounts of the same conversion.
    """
    return "\n".join([DROPPED_HEADING, ""]
                     + [f"  {d}" for d in report.dropped])


class DosImportDialog(QDialog):
    """The folder, the slot, and what will be lost.

    Every change to the slot re-runs `rehearse`, so the pane is never showing
    the losses of a conversion other than the one the button would commit --
    and the button is disabled whenever there is no rehearsal behind it.

    `files` is the icon and `ANIMATE00`, already read: `editor/window.py`
    refuses the whole import before this window is built when they cannot be
    found, so by the time anything here runs they exist.
    """

    def __init__(self, folder: str | pathlib.Path, files: GameFiles,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(DIALOG_TITLE)
        self.folder = pathlib.Path(folder)
        self.files = files
        self.conversion: Conversion | None = None

        form = QFormLayout()
        self._folder_label = QLabel(str(self.folder))
        self._folder_label.setObjectName("dos_folder")
        form.addRow(LABEL_FOLDER, self._folder_label)

        self.slots = QComboBox()
        self.slots.setObjectName("dos_slot")
        self.slots.addItems(dos.slots_available(self.folder))
        self.slots.currentTextChanged.connect(lambda _t: self._rehearse())
        form.addRow(LABEL_SLOT, self.slots)

        self.report_pane = QPlainTextEdit()
        self.report_pane.setObjectName("dos_report")
        self.report_pane.setReadOnly(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText(BUTTON_CONVERT)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.report_pane, 1)
        layout.addWidget(self.buttons)
        self.resize(680, 480)
        self._rehearse()

    # -- the parts ---------------------------------------------------------

    @property
    def slot(self) -> str:
        return self.slots.currentText()

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
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.conversion is not None)

    def _attempt(self) -> str:
        # No slot is not a state the user can reach: `import_dos_save` refuses
        # a folder with no DOS save in it before this window is built. An
        # empty pane rather than a sentence, because a sentence about a state
        # nobody can be in is a sentence nobody should have to read.
        if not self.slot:
            return ""
        try:
            self.conversion = rehearse(self.folder, self.slot, self.files)
        except Exception as exc:
            _log.exception("could not convert %s slot %s",
                           self.folder, self.slot)
            return str(exc)
        return dropped_text(self.conversion.report)
