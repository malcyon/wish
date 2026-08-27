"""Writing a C64 party out to another port, with the losses named first.

The mirror of `editor/dosimport.py`, and deliberately the same order of
events: the export is **rehearsed** somewhere the user cannot see, what it
costs is put on screen, and only then is there a button to press.

What an export cannot borrow is the import's safety net. An import lands in
the open document and reaches a disk only through the editor's ordinary Save,
so `editor/files.py`'s atomic write and timestamped backup cover it. An export
writes into a folder the user picked, which we neither own nor can back up. So
the guarantee here is a different one, and it is the whole reason the report
pane has three more sections than the import's:

**An export names every file it will replace, and every file it will remove,
before the button exists to press it.** It never deletes a file it did not
write, and the only files it removes at all are the ones the destination
format makes it responsible for -- for DOS, the eighteen `CHRDAT<slot><n>`
names the engine loads the party from, which is #68: convert a party of six
into a folder, convert a party of one into the same folder, and DOS reads back
one character and five strangers. `goldbox.dos.write_dos_save` clears the slot
itself; this file's job is to say so first.

The rehearsal is a real conversion into a scratch directory that is thrown
away. That is what makes the report exact -- the losses are the codec's own
words, and the file names are the ones the write will actually produce, not a
prediction of them.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import pathlib
import tempfile
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

from goldbox import games

_log = logging.getLogger("wish.editor.exports")


# ===========================================================================
# Every string between here and the end of this block is Donald's, approved
# 2026-08-25 -- menu entries, dialog titles, row labels, button text, picker
# titles, the headings in the report pane, the refusals and the status lines.
# Changing one is his call, not a refactor. `editor/dosimport.py` carries the
# same block for the import direction.
#
# He also settled the two choices that are not words:
#   * **the report pane leads with what the conversion cannot carry**, and
#     then says what the write will replace and remove. Losses first.
#   * **`MENU_AMIGA` names the port and not the game.** "&Amiga…" is
#     deliberate: the export is meant to reach every Amiga Gold Box title
#     in time, and naming one game in the menu would have to be undone. If
#     that costs work later, that is the trade he chose. Shortened from
#     "&Amiga characters…" in 2026-08: the menu names the destination, and
#     what it writes there is the export dialog's business, not the menu's.
#
# The feature flag below stays until #52 closes. The words are settled; the
# direction is not yet proven end to end for a user.
# ===========================================================================

#: The File menu entry and the two ports under it.
MENU_EXPORT = "&Export"
MENU_DOS = "&DOS…"
MENU_AMIGA = "&Amiga…"

#: The two windows.
DOS_TITLE = "Export a DOS save"
AMIGA_TITLE = "Export Amiga characters"

#: Row labels.
LABEL_SOURCE = "C64 save"
LABEL_TEMPLATE = "DOS save"
LABEL_SLOT = "Slot"
LABEL_GAME = "DOS game folder"
LABEL_DESTINATION = "Write to"

#: Buttons. `BUTTON_CHOOSE` is `dosimport.BUTTON_CHOOSE`'s word on purpose.
BUTTON_CHOOSE = "Choose…"
BUTTON_EXPORT = "Export"

#: Picker titles.
TEMPLATE_TITLE = "Choose a DOS save"
GAME_TITLE = "Choose the DOS game folder"
DESTINATION_TITLE = "Choose where to write"

#: What the pane says while something it needs is still missing.
NOTHING_OPEN = "Open a C64 save first."
NO_TEMPLATE = "Choose a DOS save."
NO_DESTINATION = "Choose where to write."
NO_SLOTS = "{folder} holds no DOS Pool of Radiance save."

#: The refusal, shown in the pane with Export greyed out.
WRONG_GAME = "This is a {title} save. Only Pool of Radiance can be exported."

#: The headings in the report pane. `DROPPED_HEADING` is
#: `dosimport.DROPPED_HEADING` verbatim: one conversion vocabulary, whichever
#: way it is going.
DROPPED_HEADING = "The conversion cannot carry these:"
WRITES_HEADING = "This writes:"
REPLACES_HEADING = "It replaces these, already there:"
REMOVES_HEADING = "It removes these, left by an earlier export:"

#: Defensive: `goldbox.amiga.export_party` disambiguates a repeated eight-character
#: stem itself since #79, so this should never fire from that caller any more.
#: Kept because `_amiga_losses` takes any `(path, Report)` list, not only
#: `export_party`'s, and a character that does not arrive would be worse
#: unreported than reported.
COLLIDES = ("{file}: two characters have this Amiga file name, and only "
            "the last of them is written")

#: The status line after a write that has happened.
EXPORTED_DOS = "exported to DOS slot {slot} in {folder}"
EXPORTED_AMIGA = "exported {count} characters to {folder}"

#: The box when the write itself fails.
FAILED_TITLE = "Cannot export"
# ---------------------------------------------------------------------------


#: **Off unless `WISH_EXPERIMENTAL_EXPORT=1`.** Neither the menu nor the two
#: dialogs are built otherwise -- not built rather than greyed out, because a
#: greyed entry invites the question of how to un-grey it and the answer would
#: be a sentence in the interface.
#:
#: What the flag is holding back is not the conversion. `goldbox.dos.write_dos_save`
#: is proven in the emulator and `goldbox.amiga.export_party` is what
#: `tools/toamiga.py` has been driving; what is unfinished is that **every
#: word above is an agent's placeholder**. A user cannot be shown a window
#: whose labels nobody has approved.
#:
#: An environment variable and no preference, the same shape as `WISH_DEBUG`,
#: `WISH_NATIVE_LOG` and `WISH_EXPERIMENTAL_DOS_IMPORT`: a checkbox would need
#: a label, and a label saying "experimental" would need a sentence saying
#: what that meant for the folder being written into.
#:
#: **Half the condition is met: the strings are approved as of 2026-08-25.**
#: What remains is #52 closing -- the export direction proven end to end by
#: somebody using it, and #79's Amiga filename collision settled, since a
#: character that leaves the window and does not arrive is the failure this
#: dialog exists to prevent.
ENV = "WISH_EXPERIMENTAL_EXPORT"

#: Anything else -- an empty string, `0`, `off` -- is off, matching
#: `wish/debugmode.py`. A variable somebody exported once and forgot should
#: not put an unapproved window in front of them.
TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    """Is the export offered in this run?"""
    return os.environ.get(ENV, "").strip().lower() in TRUE


class ExportError(Exception):
    """Anything the export refuses, phrased for the report pane."""


class NotPoolOfRadiance(ExportError):
    """The open save is a later title's, which has no DOS writer."""


# --- what is being exported -------------------------------------------------

@dataclasses.dataclass
class Source:
    """The C64 save an export reads, as it stands in the window.

    Held as bytes rather than as a path because the window's copy is the one
    the user means: an export that read the file back off the disk would write
    out a party without the edits still on screen.
    """

    game: Any
    save0: bytes
    save1: bytes | None
    disk: bytes
    name: str = ""

    @classmethod
    def from_party(cls, party, path=None) -> "Source":
        """The open party, with whatever `_write_back` has pushed into it."""
        # A roster disk has characters and no saved game, and neither
        # direction can export one: the DOS writer converts the
        # `SAVEDGAME0`/`SAVEDGAME1` payloads and `goldbox.amiga.export_party`
        # opens the disk with `load_save`. It gets the same sentence, which is
        # close enough to true and is one fewer string for Donald to rule on.
        if party is None or party.save0 is None:
            raise ExportError(NOTHING_OPEN)
        return cls(party.game,
                   party.save0.to_bytes(),
                   party.save1.to_bytes() if party.save1 is not None else None,
                   party.disk.to_bytes(),
                   str(path or party.path or ""))

    @classmethod
    def from_disk(cls, path: str | pathlib.Path) -> "Source":
        """A save disk read off the filesystem. What a test wants."""
        from goldbox.d64 import D64
        from goldbox.savegame import load_save

        disk = D64.open(str(path))
        game, sg0, sg1 = load_save(disk)
        return cls(game, sg0.to_bytes(),
                   sg1.to_bytes() if sg1 is not None else None,
                   disk.to_bytes(), str(path))

    def scratch_disk(self, where: pathlib.Path) -> pathlib.Path:
        """The in-memory disk as a file, for a converter that wants a path."""
        path = where / "source.d64"
        path.write_bytes(self.disk)
        return path


# --- what an export would do ------------------------------------------------

class Plan:
    """A rehearsed export: what it writes, what that costs, what it destroys.

    Nothing in the destination has been touched. `files` is measured, not
    guessed -- the rehearsal wrote exactly these names into a scratch
    directory that no longer exists.

    `owned` is the narrow licence to delete: names this format makes the
    export responsible for even when this particular write does not produce
    them. Anything else in the destination is the user's and is never touched.
    """

    def __init__(self, source: Source, destination: str | pathlib.Path,
                 files, losses: str, owned=()):
        self.source = source
        self.destination = pathlib.Path(destination)
        self.files = sorted(files)
        self.losses = losses
        there = set()
        if self.destination.is_dir():
            there = {p.name for p in self.destination.iterdir() if p.is_file()}
        self.replaced = sorted(there & set(self.files))
        self.removed = sorted((there & set(owned)) - set(self.files))

    def text(self) -> str:
        """The pane: the losses first, then what the write costs the folder."""
        blocks = [_block(DROPPED_HEADING, self.losses.splitlines()),
                  _block(WRITES_HEADING, self.files),
                  _block(REPLACES_HEADING, self.replaced),
                  _block(REMOVES_HEADING, self.removed)]
        return "\n\n".join(b for b in blocks if b)

    def write(self) -> str:
        raise NotImplementedError


def losses(report) -> str:
    """A report's `dropped` and `warnings`, in the codec's own words.

    Not `summary()`: that also carries the byte count and the `carried` list,
    which are not losses and would sit under a heading that says they are.
    A warning is -- `neutral.Report` defines it as anything the conversion
    could not do faithfully, which is the same question the heading asks.
    """
    return "\n".join(list(report.dropped)
                     + [f"warning: {w}" for w in report.warnings])


def _block(heading: str, lines) -> str:
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return ""
    return "\n".join([heading, ""] + [f"  {ln.strip()}" for ln in lines])


class DosPlan(Plan):
    """C64 to a DOS save directory, through `goldbox.dos.write_dos_save`."""

    def __init__(self, source, destination, template, slot, game_dir=None):
        # Before the rehearsal, which reads it: `Plan.__init__` runs last
        # because it needs the file names the rehearsal produces.
        self.source = source
        self.template = pathlib.Path(template)
        self.slot = slot
        self.game_dir = pathlib.Path(game_dir) if game_dir else None
        with tempfile.TemporaryDirectory() as scratch:
            report = self._convert(pathlib.Path(scratch))
            files = [p.name for p in pathlib.Path(scratch).iterdir()]
        super().__init__(source, destination, files, losses(report),
                         owned=_dos_slot_names(slot))

    def _convert(self, out: pathlib.Path):
        from goldbox import dos

        return dos.write_dos_save(self.source.save0, self.source.save1,
                                  self.template, out, self.slot,
                                  self.game_dir)

    def write(self) -> str:
        self._convert(self.destination)
        return EXPORTED_DOS.format(slot=self.slot, folder=self.destination)


class AmigaPlan(Plan):
    """C64 to Amiga *Pools of Darkness* `.pc` files, one per character.

    The `SAVE` drawer is a pool the game's `Add Character -> Pools` picker
    lists, not a party file (`docs/124-amiga-port.md`), so a leftover `.pc`
    from an earlier export is one more option in that picker rather than a
    stranger in the party -- which is why nothing is `owned` here and the
    export removes nothing at all. What it can still do is overwrite a file of
    the same name, and that is what `replaced` is for.
    """

    def __init__(self, source, destination):
        with tempfile.TemporaryDirectory() as scratch:
            root = pathlib.Path(scratch)
            written = self._convert(source, root / "out", root)
            files = [path.name for path, _rep in written]
            losses = _amiga_losses(written)
        super().__init__(source, destination, files, losses, owned=())

    @staticmethod
    def _convert(source: Source, out: pathlib.Path, scratch: pathlib.Path):
        from goldbox.amiga import export_party

        return export_party(source.scratch_disk(scratch), out)

    def write(self) -> str:
        with tempfile.TemporaryDirectory() as scratch:
            written = self._convert(self.source, self.destination,
                                    pathlib.Path(scratch))
        return EXPORTED_AMIGA.format(count=len(written),
                                     folder=self.destination)


def _amiga_losses(written) -> str:
    """One `.pc` file's losses per line, its name in front.

    Six characters have six reports and the pane has to say which is which;
    the lines themselves are `goldbox/amiga.py`'s, so a report shown in a menu and
    a report printed by `tools/toamiga.py` cannot become two accounts of the
    same conversion.

    The one line that is not a codec's is the name collision. Two party
    members can still share an eight-character stem, but `export_party`
    disambiguates the second one's file name rather than overwriting (#79)
    and says so in its own report -- which reaches the pane through the
    second loop below, the same as any other warning. `COLLIDES` is a
    defensive line for a `written` list from anywhere else that still holds a
    genuine duplicate path.
    """
    out = []
    seen = set()
    for path, _rep in written:
        if path in seen:
            out.append(COLLIDES.format(file=path.name))
        seen.add(path)
    for path, rep in written:
        out += [f"{path.name}: {line}"
                for line in losses(rep).splitlines() if line.strip()]
    return "\n".join(out)


def _dos_slot_names(slot: str) -> list[str]:
    """The eighteen names `goldbox.dos.write_dos_save` clears for a slot (#68).

    Enumerated rather than globbed, and enumerated here as well as there so
    the pane can name them before the write rather than in the report after
    it.
    """
    from goldbox import dos_savegame

    return [f"CHRDAT{slot}{n}{suffix}"
            for n in range(1, dos_savegame.PARTY_ENTRIES + 1)
            for suffix in (".SAV", ".ITM", ".SPC")]


# --- the windows -------------------------------------------------------------

class ExportDialog(QDialog):
    """The rows, the report, and a button that only exists behind a rehearsal.

    Every change to any row re-plans, so the pane is never showing the cost of
    an export other than the one the button would commit -- and the button is
    disabled whenever there is no plan behind it. The same rule
    `editor/dosimport.py` follows, for the same reason.
    """

    #: Each port's own; the base class is never shown.
    TITLE = ""

    def __init__(self, source: Source, destination=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.TITLE)
        self.source = source
        self.destination = pathlib.Path(destination) if destination else None
        self.plan: Plan | None = None

        self.form = QFormLayout()
        label = QLabel(source.name)
        label.setObjectName("export_source")
        self.form.addRow(LABEL_SOURCE, label)
        self._rows()
        self._destination_label = QLabel(str(self.destination or ""))
        self._destination_label.setObjectName("export_destination")
        self.form.addRow(LABEL_DESTINATION,
                         _picker(self._destination_label, "export_choose_dest",
                                 self.choose_destination))

        self.report_pane = QPlainTextEdit()
        self.report_pane.setObjectName("export_report")
        self.report_pane.setReadOnly(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText(BUTTON_EXPORT)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.report_pane, 1)
        layout.addWidget(self.buttons)
        self.resize(680, 480)
        self.replan()

    # -- the parts the two ports differ in ---------------------------------

    def _rows(self) -> None:
        """Rows between the source and the destination. None by default."""

    def _build(self) -> Plan:
        raise NotImplementedError

    # -- the rehearsal -----------------------------------------------------

    def choose_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, DESTINATION_TITLE, str(self.destination or ""))
        if path:
            self.set_destination(path)

    def set_destination(self, path) -> None:
        self.destination = pathlib.Path(path)
        self._destination_label.setText(str(self.destination))
        self.replan()

    def replan(self) -> None:
        """Rehearse, and put what it would cost on screen.

        Failures are shown, not raised: a refusal reaches the user as its own
        sentence while the log keeps the traceback, rather than as what looks
        like a broken menu item.
        """
        self.plan = None
        text = self._attempt()
        self.report_pane.setPlainText(text)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.plan is not None)

    def _attempt(self) -> str:
        if self.destination is None:
            return NO_DESTINATION
        try:
            self.plan = self._build()
        except ExportError as exc:
            return str(exc)
        except Exception as exc:
            _log.exception("could not rehearse an export into %s",
                           self.destination)
            return str(exc)
        return self.plan.text()


class DosExportDialog(ExportDialog):
    """C64 to DOS: a template save, a slot, an optional game folder.

    The template is read for the 8016 resident-state bytes nothing has
    attributed and is never written; the game folder is where `ECL<n>.DAX`
    lives, and without it a party standing somewhere the template's party does
    not keeps the template's square -- which the report says, in
    `goldbox/dos.py`'s own words.
    """

    TITLE = DOS_TITLE

    def __init__(self, source, template=None, destination=None, parent=None,
                 game_dir=None):
        self._template = pathlib.Path(template) if template else None
        self._game_dir = pathlib.Path(game_dir) if game_dir else None
        super().__init__(source, destination, parent)

    def _rows(self) -> None:
        self._template_label = QLabel(str(self._template or ""))
        self._template_label.setObjectName("export_template")
        self.form.addRow(LABEL_TEMPLATE,
                         _picker(self._template_label, "export_choose_template",
                                 self.choose_template))

        self.slots = QComboBox()
        self.slots.setObjectName("export_slot")
        self.slots.currentTextChanged.connect(lambda _t: self.replan())
        self.form.addRow(LABEL_SLOT, self.slots)
        self._fill_slots()

        self._game_label = QLabel(str(self._game_dir or ""))
        self._game_label.setObjectName("export_game")
        self.form.addRow(LABEL_GAME,
                         _picker(self._game_label, "export_choose_game",
                                 self.choose_game))

    def _fill_slots(self) -> None:
        from goldbox import dos

        self.slots.blockSignals(True)
        self.slots.clear()
        if self._template is not None:
            self.slots.addItems(dos.slots_available(self._template))
        self.slots.blockSignals(False)

    @property
    def slot(self) -> str:
        return self.slots.currentText()

    def choose_template(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, TEMPLATE_TITLE, str(self._template or ""))
        if path:
            self.set_template(path)

    def set_template(self, path) -> None:
        self._template = pathlib.Path(path)
        self._template_label.setText(str(self._template))
        self._fill_slots()
        self.replan()

    def choose_game(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, GAME_TITLE, str(self._game_dir or self._template or ""))
        if path:
            self.set_game_dir(path)

    def set_game_dir(self, path) -> None:
        self._game_dir = pathlib.Path(path)
        self._game_label.setText(str(self._game_dir))
        self.replan()

    def _build(self) -> Plan:
        if getattr(self.source.game, "key", None) != games.POOL_OF_RADIANCE.key:
            raise NotPoolOfRadiance(
                WRONG_GAME.format(title=getattr(self.source.game, "title",
                                                "unknown")))
        if self._template is None:
            raise ExportError(NO_TEMPLATE)
        if not self.slot:
            raise ExportError(NO_SLOTS.format(folder=self._template))
        return DosPlan(self.source, self.destination, self._template,
                       self.slot, self._game_dir)


class AmigaExportDialog(ExportDialog):
    """C64 to Amiga *Pools of Darkness*: a destination and nothing else."""

    TITLE = AMIGA_TITLE

    def _build(self) -> Plan:
        return AmigaPlan(self.source, self.destination)


def _picker(label: QLabel, name: str, slot) -> QWidget:
    """A path label with a Choose button beside it, as one form row."""
    button = QPushButton(BUTTON_CHOOSE)
    button.setObjectName(name)
    button.clicked.connect(lambda _c=False: slot())
    row = QHBoxLayout()
    row.addWidget(label, 1)
    row.addWidget(button)
    holder = QWidget()
    holder.setLayout(row)
    return holder
