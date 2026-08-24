"""Turning a DOS save into a C64 one, with the losses named first.

`por/dos.py` does the conversion and this is the window over it. The one thing
this file exists for is the order of events: a DOS save carries fields the C64
has no home for -- encumbrance, the item heap pointers, the item count, the
icon selection, the strength-bonus boolean, every running spell effect -- and
`docs/117-save-conversion.md` forbids dropping them in silence. So the
conversion is **rehearsed** against a copy held in memory, the losses it
reports are put on screen, and only then is there a button to press. Nothing
reaches a disk until the user saves the result through the editor's ordinary
Save, which is what keeps the backup guarantee in `editor/files.py` covering
this the way it covers every other write.

The second thing it exists for is the refusal. `por.dos.convert_save` will not
build a save from a C64 template standing in a different area from the DOS
party, because the loaded-files cache at `$4BC0` names the files for the
template's area and nothing in a DOS save can refill it -- the result loads,
seats the party, and then hangs asking for a disk. Coming out of a menu that
has to be a sentence, not a traceback, so `rehearse` raises and the dialog
prints `AREA_MISMATCH`.

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
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from por import areas, dos, games
from por.d64 import D64
from por.savegame import SaveGame0, SaveGame1, load_save, store_save

_log = logging.getLogger("wish.editor.dosimport")


# Every string below is Donald's, approved 2026-08-24. Changing one is his
# call, not a refactor.

#: The File menu entry and the submenu it hangs under.
MENU_IMPORT = "&Import"
MENU_DOS_SAVE = "&DOS save…"

#: The folder picker, and what is said when the folder holds no DOS save.
FOLDER_TITLE = "Choose a DOS save folder"
NO_SLOTS_TITLE = "No DOS save here"
NO_SLOTS = "{folder} holds no DOS Pool of Radiance save."

#: The conversion window.
DIALOG_TITLE = "Import a DOS save"
LABEL_FOLDER = "DOS save"
LABEL_SLOT = "Slot"
LABEL_TEMPLATE = "C64 save"
BUTTON_CHOOSE = "Choose…"
BUTTON_CONVERT = "Convert"
TEMPLATE_TITLE = "Choose the C64 save to convert into"
TEMPLATE_FILTER = "Gold Box disks (*.d64 *.D64);;All files (*)"

#: What the report pane says before anything has been chosen, and the heading
#: over the list of fields the conversion cannot carry.
NO_TEMPLATE = "Choose a C64 save to convert into."
DROPPED_HEADING = "The conversion cannot carry these:"

#: The two refusals, both shown in the report pane with Convert greyed out.
WRONG_GAME = "This is a {title} save. Only Pool of Radiance can be converted."
AREA_MISMATCH = (
    "The DOS party is in {there} and this C64 save is in {here}.\n"
    "Choose a C64 save made in {there}.")

#: The status line after the conversion, which has written nothing yet.
CONVERTED = "converted DOS slot {slot} - not saved yet"
# ---------------------------------------------------------------------------


def _area_named(id: int) -> str:
    """An area by name where we have one, by number where we do not."""
    area = areas.area(id)
    return area.name if area is not None and area.name else f"area {id}"


class NotPoolOfRadiance(dos.DosRecordError):
    """The chosen C64 save is a later title's, which has no DOS reader."""


@dataclasses.dataclass
class Conversion:
    """A converted save, held in memory. Nothing here has been written."""

    #: The template's disk image, with the converted save already stored into
    #: it -- so `disk.to_bytes()` is what a save would write.
    disk: Any
    game: Any
    save0: SaveGame0
    save1: SaveGame1 | None
    report: dos.Report
    folder: pathlib.Path
    slot: str
    template: pathlib.Path


def rehearse(folder: str | pathlib.Path, slot: str,
             template: str | pathlib.Path) -> Conversion:
    """Convert onto a copy of the template and report, writing nothing.

    The template is read; the DOS files are read; the result exists only as
    the returned `Conversion`. `por.dos.convert_save` raises `AreaMismatch`
    from in here, which is the refusal the dialog turns into a sentence.
    """
    disk = D64.open(template)
    game, sg0, sg1 = load_save(disk)
    if game.key != games.POOL_OF_RADIANCE.key:
        raise NotPoolOfRadiance(game.title)
    payload0 = bytearray(sg0.to_bytes())
    payload1 = bytearray(sg1.to_bytes()) if sg1 is not None else None
    report = dos.convert_save(folder, slot, payload0, payload1)
    sg0 = SaveGame0.from_bytes(bytes(payload0), game)
    if sg1 is not None and payload1 is not None:
        sg1 = SaveGame1(bytes(payload1), game)
    store_save(disk, sg0, sg1, game)
    return Conversion(disk, game, sg0, sg1, report,
                      pathlib.Path(folder), slot, pathlib.Path(template))


def template_area(template: str | pathlib.Path) -> int | None:
    """Which area a C64 save stands in, or None if it is not a save at all."""
    try:
        _game, sg0, _sg1 = load_save(D64.open(template))
    except Exception as exc:
        _log.debug("no area for %s: %s", template, exc)
        return None
    payload = sg0.to_bytes()
    return payload[0x4BC2 - dos.SAVE0_BASE] & ~dos.FILE_CACHE_RELOAD


def dos_area(folder: str | pathlib.Path, slot: str) -> int | None:
    """Which area the DOS party stands in, or None if the slot will not read."""
    path = pathlib.Path(folder) / f"SAVGAM{slot}.DAT"
    try:
        return dos.area_id(path.read_bytes())
    except Exception as exc:
        _log.debug("no area for %s: %s", path, exc)
        return None


def dropped_text(report: dos.Report) -> str:
    """The losses, one to a line, under a heading.

    The lines themselves are `por/dos.py`'s -- the same words the command line
    prints -- so the report a menu shows and the report a terminal shows cannot
    drift into being two different accounts of the same conversion.
    """
    return "\n".join([DROPPED_HEADING, ""]
                     + [f"  {d}" for d in report.dropped])


class DosImportDialog(QDialog):
    """The folder, the slot, the C64 save, and what will be lost.

    Every change to the slot or the template re-runs `rehearse`, so the pane
    is never showing the losses of a conversion other than the one the button
    would commit -- and the button is disabled whenever there is no rehearsal
    behind it.
    """

    def __init__(self, folder: str | pathlib.Path,
                 template: str | pathlib.Path | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(DIALOG_TITLE)
        self.folder = pathlib.Path(folder)
        self.template = pathlib.Path(template) if template else None
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

        self._template_label = QLabel(str(self.template or ""))
        self._template_label.setObjectName("dos_template")
        choose = QPushButton(BUTTON_CHOOSE)
        choose.setObjectName("dos_choose_template")
        choose.clicked.connect(lambda _c=False: self.choose_template())
        row = QHBoxLayout()
        row.addWidget(self._template_label, 1)
        row.addWidget(choose)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow(LABEL_TEMPLATE, holder)

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

    def choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, TEMPLATE_TITLE, str(self.template or self.folder),
            TEMPLATE_FILTER)
        if path:
            self.set_template(path)

    def set_template(self, path: str | pathlib.Path) -> None:
        self.template = pathlib.Path(path)
        self._template_label.setText(str(self.template))
        self._rehearse()

    # -- the rehearsal -----------------------------------------------------

    def _rehearse(self) -> None:
        """Convert onto a copy, and put what it costs on screen.

        Failures are shown, not raised: the area refusal is the expected one
        and reads as a sentence, and anything else at least reaches the user
        as its message while the log keeps the traceback.
        """
        self.conversion = None
        text = self._attempt()
        self.report_pane.setPlainText(text)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.conversion is not None)

    def _attempt(self) -> str:
        if self.template is None or not self.slot:
            return NO_TEMPLATE
        try:
            self.conversion = rehearse(self.folder, self.slot, self.template)
        except dos.AreaMismatch:
            here = template_area(self.template)
            there = dos_area(self.folder, self.slot)
            return AREA_MISMATCH.format(
                here=_area_named(here) if here is not None else "?",
                there=_area_named(there) if there is not None else "?")
        except NotPoolOfRadiance as exc:
            return WRONG_GAME.format(title=str(exc))
        except Exception as exc:
            _log.exception("could not convert %s slot %s into %s",
                           self.folder, self.slot, self.template)
            return str(exc)
        return dropped_text(self.conversion.report)
