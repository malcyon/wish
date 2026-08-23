"""File > Preferences: the game disks, the live backend, and where a warp
may go.

**Half of this is the report, not the form.** The failure it exists to fix is
silent -- items rendered as `word 8`, an empty map tab, and the one diagnostic
that says why printed to a stderr a desktop launcher throws away. So the dialog
says what was *found*: which folder is in use, who named it, and which titles
are in it. A user who types nothing still learns what went wrong. It said three
things more -- maps, item names, icons -- until Donald called that too chatty
in 2026-08; what those three answered is visible on the map tab and in the
item column, where you are already looking.

Three things about the shape of it:

* **No OK, no Cancel -- one Close.** Every control here applies at once, as the
  backend menu it replaces already did. A Cancel would need an undo path back
  through `Session.prefer`, a map reload and the editor's item tables.
* **Hand-written, not Designer.** `editor/character.ui` is the only `.ui` in
  the tree and `tools/genui.py` hard-codes that one pair of paths. Every other
  dialog here is code, and this one re-probes backends and re-runs a directory
  search as you type, which is code either way.
* **`report()` is a plain function over a folder.** It takes settings and a
  path, not a window, so what the dialog claims can be tested without opening
  one.

**`editor.files` is imported here, and only here.** The dialog reports where a
backup of the open save would go, which is that module's decision to make. The
one-way rule the project keeps is that `editor/` imports nothing from
`automap/`; `wish/` is the layer that is allowed to know about both, and this
is it.

The password is deliberately absent. `$POR_ULTIMATE_PASSWORD` is the only way
to give one, and all this shows is whether it is set: the settings file is
documented as one you can read and hand-edit, and a secret does not belong in
a file described that way.
"""

from __future__ import annotations

import functools
import os
import pathlib
import re

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyle,
    QStyleOptionFrame,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from automap import paths
from automap.actionbar import DANGER
from por import areas as area_table
from por import games

#: Spelled out rather than `QKeySequence.StandardKey.Preferences`, which
#: resolves on Linux/Qt 6 to the `XF86Settings` multimedia key --
#: `toString()` returns 'Settings' -- a shortcut no ordinary keyboard can
#: produce. Measured in this venv.
SHORTCUT = "Ctrl+,"

#: How long after the last keystroke the folder is re-read. Typing a path a
#: character at a time would otherwise open eight D64s per letter.
SETTLE_MS = 400

HINT = ("Leave it empty to search: beside the open save disk first, then the "
        "usual folders.")

PASSWORD_ENV = "POR_ULTIMATE_PASSWORD"

#: Qt keeps two pixels each side of the text inside a line edit for the cursor,
#: on top of the frame and the text margins, and `CT_LineEdit` does not add
#: them. Without it the last letter of the placeholder is a pixel short.
CARET = 4

#: A backend's state is a badge, not more words in its label. Both colours are
#: named on every one of them: a badge that set only its ink would be dark on
#: dark under a dark desktop theme, and the whole point is that it reads.
_BADGE = ("border: 1px solid {edge}; border-radius: 7px; padding: 0px 7px;"
          " background: {ground}; color: {ink};")
ANSWERING = _BADGE.format(edge="#8fbf9c", ground="#eaf5ed", ink="#1d5b34")
SILENT = _BADGE.format(edge="#c3c8cf", ground="#f1f3f5", ink="#4a5b6d")
UNVERIFIED = _BADGE.format(edge="#d8c48a", ground="#fbf4e2", ink="#6b5510")

#: The unverified badge with room for a sentence in it. Same amber, same
#: border: a warning that looked like a different kind of object from the one
#: beside the backends would be a second visual language for one idea.
WARNING_BOX = UNVERIFIED + " padding: 6px 8px;"

#: How tall the area table is allowed to get. Twenty-nine rows is more than a
#: dialog can show without becoming a wall, so it scrolls. 160 keeps the whole
#: dialog inside a 1080-line screen's work area with room to spare, which the
#: geometry work (`docs/130-preferences.md` §12) is the reason to care about.
TABLE_HEIGHT = 160

#: The `$POR_ULTIMATE` this process started with, read once, so that emptying
#: the box gives the user's own value back rather than nothing.
_UNREAD = object()
_ENV_HOST: object | str | None = _UNREAD


def room_for(edit: QLineEdit, text: str) -> int:
    """How wide the box has to be for `text` to fit inside it, on this style.

    Measured, not written down. The dialog opened 397 px wide and gave the
    folder box 137 of them, which is 66 px short of its own placeholder --
    Donald: "you can't read the helptext written in the Folder edit box". A
    constant would have been right on the font and style it was measured on and
    wrong on his Windows build, which is the mistake `_spin_width` was already
    made to fix once.
    """
    option = QStyleOptionFrame()
    option.initFrom(edit)
    option.lineWidth = edit.style().pixelMetric(
        QStyle.PixelMetric.PM_DefaultFrameWidth, option, edit)
    margins = edit.textMargins()
    inner = QSize(edit.fontMetrics().horizontalAdvance(text)
                  + margins.left() + margins.right() + CARET,
                  edit.sizeHint().height())
    return edit.style().sizeFromContents(
        QStyle.ContentsType.CT_LineEdit, option, inner, edit).width()


def _pretty(glob: str) -> str:
    """`POOL*.[dD]64` as somebody would say it."""
    return re.sub(r"\[[a-zA-Z]*([a-zA-Z])\]", r"\1", glob)


def game_named(title: str | None) -> games.Game | None:
    """The `Game` a title string names, or None."""
    return next((g for g in games.GAMES if g.title == title), None)


def _images(where: pathlib.Path, game: games.Game | None) -> list[pathlib.Path]:
    """Every disk image of a title in this folder, each of them once.

    Both patterns match the same file on a case-insensitive filesystem, so a
    naive loop over `disk_globs` reads every disk twice.
    """
    seen: dict[str, pathlib.Path] = {}
    for pattern in paths.disk_globs(game):
        try:
            for path in where.glob(pattern):
                seen.setdefault(os.path.normcase(str(path.resolve())), path)
        except OSError:
            pass
    return sorted(seen.values())


@functools.lru_cache(maxsize=8)
def _scan(where: str) -> dict:
    """Which titles are in this folder, and how many disks of each.

    Cached because the dialog re-reports as you type and this opens D64s. The
    key is the folder, which is everything the answer depends on.

    It used to count the maps and open every image looking for item names and
    an icon charset as well. Donald had those three lines out of the dialog in
    2026-08 -- "Game disks is too chatty" -- and an unprinted line is not worth
    reading eight disk images for.
    """
    root = pathlib.Path(where)
    found: dict = {"titles": []}
    if not root.is_dir():
        return found
    found["titles"] = [(g, len(_images(root, g))) for g in paths.titles_in(root)]
    return found


def backup_folder(save) -> tuple[pathlib.Path, bool]:
    """Where a backup of `save` would go, and whether that is the fallback.

    `editor.files.backup_dir_for` is the authority and is what runs at save
    time -- but it answers "may I write here" by *making* the folder and
    touching a probe file in it, and a dialog that only reports must not write
    to the folder somebody keeps their disks in. So this asks the same question
    read-only. The two can disagree only on a filesystem that lies about
    access, and there the status line after a save names the real path, from
    the real chooser.

    With nothing open there is no per-file answer, so the fallback is named and
    said to be the fallback.
    """
    from editor import files

    if save is None:
        return files.fallback_dir(), True
    beside = pathlib.Path(save).parent / files.BACKUP_DIR
    # The folder itself once it exists, its parent while it does not: making
    # it is the first thing `backup_dir_for` would have to do.
    probe = beside if beside.is_dir() else beside.parent
    if os.access(probe, os.W_OK):
        return beside, False
    return files.fallback_dir(), True


def _set_by(source: str, settings) -> str:
    """Who named the folder in use, and what was overridden to say so."""
    words = {
        paths.FLAG: "--disks, this run only",
        paths.PREFERENCE: "this preference",
        paths.ENVIRONMENT: "$POR_DISKS",
        paths.BESIDE: "beside the open save",
        paths.SEARCHED: "found by searching the usual folders",
        paths.NOWHERE: "nothing found",
    }
    text = words.get(source, source)
    extra = []
    if source != paths.ENVIRONMENT and os.environ.get("POR_DISKS"):
        extra.append("$POR_DISKS is set and overridden")
    if source == paths.FLAG and (getattr(settings, "disks", "") or ""):
        extra.append(f"the saved preference {settings.disks} is not used "
                     "for this run")
    return text + (f"  ({'; '.join(extra)})" if extra else "")


def report(settings, flag=None, beside=None,
           game: games.Game | None = None) -> list[tuple[str, str]]:
    """The three lines the dialog prints, as (label, value) pairs.

    Each answers a question somebody has actually had: is it even looking where
    I put them, why is it ignoring what I typed, and are these the right disks.
    A failure is stated in the same slot -- an empty answer is more informative
    than a missing row.

    It printed three more -- the map count, the disk the item names came off
    and the icon charset. Donald had them out in 2026-08: they answered
    questions nobody was asking at the moment of opening this dialog, and the
    map tab and the item column say the same thing where you are looking.
    """
    where, source = paths.resolve_disks(flag=flag, beside=beside, game=game,
                                        settings=settings)
    rows = [("In use", str(where) if where is not None else "nothing found"),
            ("Set by", _set_by(source, settings))]
    wanted = [game] if game else list(games.GAMES)[:2]
    patterns = " or ".join(_pretty(g.disk_glob) for g in wanted)
    if where is None:
        return rows + [("Titles",
                        f"none; nowhere with {patterns} in it was found")]

    titles = _scan(str(where))["titles"]
    if titles:
        titles_line = " · ".join(f"{g.title} ({n} disk{'' if n == 1 else 's'})"
                                      for g, n in titles)
    else:
        titles_line = f"none; no {patterns} here"
    return rows + [("Titles", titles_line)]


def apply_ultimate_host(host: str) -> None:
    """Make the preference the answer for this process.

    `wish/ultimate.py::configured()` reads `$POR_ULTIMATE` and nothing else, so
    the preference is applied by being *put there* -- one lookup path, and the
    §4 precedence (the setting first, the environment when it is empty) holds
    without a second one. Emptying the box puts the user's own value back.
    """
    global _ENV_HOST
    if not host and _ENV_HOST is _UNREAD:
        # Nothing set and nothing to put back. Notably this is every window
        # with no Ultimate preference, which must not go near the environment.
        return
    if _ENV_HOST is _UNREAD:
        _ENV_HOST = os.environ.get("POR_ULTIMATE")
    if host:
        os.environ["POR_ULTIMATE"] = host
    elif _ENV_HOST:
        os.environ["POR_ULTIMATE"] = _ENV_HOST
    else:
        os.environ.pop("POR_ULTIMATE", None)


class PreferencesDialog(QDialog):
    """The window's settings, and what they found.

    Built around the window rather than around `Settings`: choosing a backend
    has to reach `Session.prefer`, and changing the folder has to reload the
    maps and re-read the editor's item tables. `WishWindow` owns all three, and
    every one of those was already a method on it.
    """

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.win = window
        self.setWindowTitle("Preferences")
        self.setModal(True)
        outer = QVBoxLayout(self)
        outer.addWidget(self._disks_group())
        outer.addWidget(self._backups_group())
        outer.addWidget(self._backend_group())
        outer.addWidget(self._travel_group())
        outer.addWidget(self._log_group())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

        # One timer for both: re-reading a folder opens every D64 in it, and
        # applying it reloads 29 maps. Neither belongs on a keystroke.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._folder_settled)
        self.refresh()

    # -- the game disks --------------------------------------------------

    def _disks_group(self) -> QGroupBox:
        box = QGroupBox("Game disks")
        outer = QVBoxLayout(box)
        row = QHBoxLayout()
        self.folder = QLineEdit(getattr(self.win.settings, "disks", "") or "")
        self.folder.setPlaceholderText("the folder holding your .D64 images")
        # Wide enough to read what it says. This is what sets the width of the
        # whole dialog, and it is measured off the placeholder rather than
        # chosen, so a longer sentence or a wider font widens the dialog with
        # it instead of losing the end of the line.
        self.folder.setMinimumWidth(room_for(self.folder,
                                             self.folder.placeholderText()))
        self.folder.textEdited.connect(lambda _t: self._settle.start(SETTLE_MS))
        self.folder.editingFinished.connect(self._folder_settled)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.set_folder(""))
        row.addWidget(QLabel("Folder"))
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        row.addWidget(clear)
        outer.addLayout(row)

        self.report_rows: dict[str, QLabel] = {}
        form = QFormLayout()
        for name in ("In use", "Set by", "Titles"):
            value = QLabel("")
            value.setWordWrap(True)
            # Selectable: the first thing anybody does with a path in a
            # report is paste it somewhere.
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self.report_rows[name] = value
            form.addRow(name, value)
        outer.addLayout(form)
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        outer.addWidget(hint)
        return box

    # -- where the backups go ---------------------------------------------

    def _backups_group(self) -> QGroupBox:
        """Where a copy of the save goes before it is overwritten.

        Donald asked where `~/.local/share/wish/backups` came from and said no
        user would ever think to look there. He is right, and that folder is
        only the *fallback*: the copy normally lands in `backups/` beside the
        save disk, which is the folder somebody was already looking at. Saying
        so in a line that is always here beats saying it in a status message
        already dismissed.

        Its own group, titled with the word somebody would look for. Read-only:
        which of the two it is depends on the save, not on a preference.

        Laid out like a backend: the path, then which of the two folders it is
        as a badge beside it, then the standing facts underneath. It was one
        sentence with all three run together until Donald asked for "the same
        effect" the backend states got -- and the answer to *which folder is
        this* is a state, exactly as "answering" is.
        """
        box = QGroupBox("Backups")
        outer = QVBoxLayout(box)
        row = QHBoxLayout()
        self.backups = QLabel("")
        self.backups.setWordWrap(True)
        self.backups.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.backups_badge = QLabel("")
        row.addWidget(QLabel("Folder"))
        row.addWidget(self.backups, 1)
        row.addWidget(self.backups_badge)
        outer.addLayout(row)
        self.backups_note = QLabel("")
        self.backups_note.setWordWrap(True)
        outer.addWidget(self.backups_note)
        return box

    def _say_backups(self) -> None:
        """The path, the badge and the note, re-read whenever it refreshes.

        The standing facts are said here because both are behaviours somebody
        would otherwise have to guess at: a backup is made only when the bytes
        changed, and the newest few are kept rather than all of them.
        """
        from editor import files

        save = getattr(self.win.editor, "path", None)
        where, fallback = backup_folder(save)
        if save is None:
            # Nothing open, so there is no per-save answer yet. Grey, not
            # amber: this is the ordinary state of a window nobody has opened
            # a save in, and nothing is wrong.
            state, badge, why = (
                "fallback", SILENT,
                "For a save whose own folder cannot be written. Open a save "
                "and this names where that save's backups go.")
        elif fallback:
            state, badge, why = (
                "fallback", UNVERIFIED,
                "The folder beside the save disk cannot be written, so they "
                "go here instead.")
        else:
            state, badge, why = ("beside the save disk", ANSWERING, "")
        self.backups.setText(str(where))
        self.backups_badge.setText(state)
        self.backups_badge.setStyleSheet(badge)
        self.backups_note.setText(
            f"{why}  Only when something changed; the newest "
            f"{files.KEEP_BACKUPS} are kept.".strip())

    def browse(self) -> None:
        """The folder picker. A method so a test can replace it."""
        chosen = QFileDialog.getExistingDirectory(
            self, "Where the game disks are", self.folder.text() or str(
                pathlib.Path.home()))
        if chosen:
            self.set_folder(chosen)

    def set_folder(self, folder: str) -> None:
        """Type this in and apply it, as Browse and Clear do."""
        self.folder.setText(folder)
        self._folder_settled()

    def _folder_settled(self) -> None:
        self._settle.stop()
        self.win.set_disks(self.folder.text().strip())
        self.refresh()

    # -- the live backend ------------------------------------------------

    def _backend_group(self) -> QGroupBox:
        """The View > Backend radio group, moved across whole.

        The actions are still the window's -- one model, so the preference,
        the session and this dialog cannot disagree -- and these buttons are a
        view of them.
        """
        box = QGroupBox("Live backend")
        outer = QVBoxLayout(box)
        self.radios: dict[str, QRadioButton] = {}
        self.badges: dict[str, QLabel] = {}
        self.unverified: dict[str, QLabel] = {}
        for name, action in self.win.backend_actions.items():
            row = QHBoxLayout()
            button = QRadioButton(name or action.text())
            button.setToolTip(action.toolTip())
            button.setChecked(action.isChecked())
            button.clicked.connect(
                lambda _checked=False, n=name: self._prefer(n))
            row.addWidget(button)
            badge = QLabel("")
            badge.setVisible(False)
            row.addWidget(badge)
            flag = QLabel("unverified")
            flag.setStyleSheet(UNVERIFIED)
            flag.setToolTip("Written from the vendor's documentation. Nobody "
                            "on this project has the hardware.")
            flag.setVisible(False)
            row.addWidget(flag)
            row.addStretch(1)
            outer.addLayout(row)
            self.radios[name] = button
            self.badges[name] = badge
            self.unverified[name] = flag

        form = QFormLayout()
        self.host = QLineEdit(getattr(self.win.settings, "ultimate_host", "")
                              or "")
        self.host.setPlaceholderText("ultimate64.local, or host:port")
        self.host.editingFinished.connect(self._host_changed)
        form.addRow("Ultimate host", self.host)
        self.password = QLabel("")
        form.addRow("Password", self.password)

        self.interval = QSpinBox()
        self.interval.setRange(0, 60000)
        self.interval.setSingleStep(50)
        self.interval.setSuffix(" ms")
        self.interval.setSpecialValueText("the backend's own "
                                          "(VICE 200, Ultimate 500)")
        self.interval.setValue(getattr(self.win.settings, "interval_ms", 0) or 0)
        self.interval.valueChanged.connect(self._interval_changed)
        form.addRow("Poll every", self.interval)
        outer.addLayout(form)
        return box

    def _prefer(self, name: str) -> None:
        self.win.backend_actions[name].setChecked(True)
        self.win._prefer_backend(name)
        self.refresh()

    def _host_changed(self) -> None:
        host = self.host.text().strip()
        if host == (getattr(self.win.settings, "ultimate_host", "") or ""):
            return
        self.win.set_ultimate_host(host)
        self.refresh()

    def _interval_changed(self, value: int) -> None:
        self.win.set_interval(value)

    # -- fast travel -----------------------------------------------------

    def _travel_group(self) -> QGroupBox:
        """Which areas the Fast Travel dropdown offers, and the warning.

        **The player chooses, and nothing infers.** The dropdown used to filter
        itself by the areas the automapper had watched the party walk in;
        Donald threw that out because the record is only ever ours -- a party
        walks wherever it likes while the map window is shut -- so this is an
        explicit list of ticks and there is no second, cleverer rule behind it.

        **Area 30 is not in the table**, ticked or unticked: `ECL1E` is the
        attract-mode demo and entering it ends the session. `Area.warpable`
        says so, and it is asked rather than the id being written down here.

        **The warning is a box, not a tooltip.** It is the same amber as the
        `unverified` badge above it: one visual language for "this is a thing
        to know before you press it", and a sentence nobody has to hover to
        find.
        """
        box = QGroupBox("Fast travel")
        outer = QVBoxLayout(box)
        warning = QLabel(DANGER)
        warning.setWordWrap(True)
        warning.setStyleSheet(WARNING_BOX)
        outer.addWidget(warning)

        #: The table's rows, in the dropdown's own order: by name. Every
        #: warpable area has one, and area 30 -- the only nameless one -- is
        #: also the only unwarpable one, so excluding it needs no second rule.
        self.travel_rows = sorted((a for a in area_table.AREAS if a.warpable),
                                  key=lambda a: a.name or "")
        chosen = set(self.win.settings.chosen_areas())
        self.travel_table = QTableWidget(len(self.travel_rows), 1)
        self.travel_table.setHorizontalHeaderLabels(["Area"])
        self.travel_table.verticalHeader().setVisible(False)
        self.travel_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.travel_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.travel_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.travel_table.setMaximumHeight(TABLE_HEIGHT)
        self.travel_table.blockSignals(True)
        for i, row in enumerate(self.travel_rows):
            item = QTableWidgetItem(row.name or row.ecl)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                          | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(Qt.CheckState.Checked if row.id in chosen
                               else Qt.CheckState.Unchecked)
            # The maps and the disk, exactly as the dropdown's items carry
            # them: interesting to whoever wants them, in nobody's way.
            item.setToolTip(row.label)
            self.travel_table.setItem(i, 0, item)
        self.travel_table.blockSignals(False)
        self.travel_table.itemChanged.connect(lambda _item: self._travel_changed())
        outer.addWidget(self.travel_table)

        self.travel_note = QLabel("")
        self.travel_note.setWordWrap(True)
        outer.addWidget(self.travel_note)
        self._say_travel()
        return box

    def travel_ticked(self) -> list[int]:
        """The area ids with a tick against them, in table order."""
        return [row.id for i, row in enumerate(self.travel_rows)
                if self.travel_table.item(i, 0).checkState()
                == Qt.CheckState.Checked]

    def _travel_changed(self) -> None:
        self.win.set_warp_areas(self.travel_ticked())
        self._say_travel()

    def _say_travel(self) -> None:
        """How many areas the dropdown will offer, and none is an answer."""
        ticked = len(self.travel_ticked())
        self.travel_note.setText(
            "Nothing ticked, so the Fast Travel list is empty. That is this "
            "setting doing what you asked, not a fault."
            if not ticked else
            f"{ticked} area{'' if ticked == 1 else 's'} in the Fast Travel "
            "list.")

    # -- the debug log ---------------------------------------------------

    def _log_group(self) -> QGroupBox:
        box = QGroupBox("Diagnostics")
        outer = QVBoxLayout(box)
        self.logging = QCheckBox("Debug log")
        self.logging.setChecked(self.win.debug_action.isChecked())
        self.logging.toggled.connect(self.win.debug_action.setChecked)
        self.win.debug_action.toggled.connect(self.logging.setChecked)
        outer.addWidget(self.logging)
        # No paragraph under it. A debug log does not need explaining, and the
        # two things that were worth saying are said where they matter: the
        # title bar and the status bar show [logging] while it is on, and the
        # status bar names the file the moment it opens.
        return box

    # -- what was found --------------------------------------------------

    def refresh(self) -> None:
        """Re-run the search and re-print the report. Cheap, apart from `_scan`."""
        for name, value in report(self.win.settings,
                                  flag=self.win.disks_flag,
                                  beside=self.win.editor.path,
                                  game=self.win.game()):
            self.report_rows[name].setText(value)
        self._say_backups()
        self.win.label_backends()
        for name, button in self.radios.items():
            action = self.win.backend_actions[name]
            state, verified = self.win.backend_status.get(name, ("", True))
            # The name is the label and the state is a badge beside it. One
            # string carrying both ran together under the Windows style, which
            # draws a radio button's text tight against its circle.
            button.setText(name or action.text())
            button.setChecked(action.isChecked())
            badge = self.badges[name]
            badge.setText(state)
            badge.setStyleSheet(ANSWERING if state == "answering" else SILENT)
            badge.setVisible(bool(state))
            self.unverified[name].setVisible(not verified)
        self.password.setText(
            f"from ${PASSWORD_ENV} — "
            + ("set" if os.environ.get(PASSWORD_ENV) else "not set"))

    def showEvent(self, event):
        # `probe()` is a TCP connect: right when somebody opens this, wrong on
        # a poll timer and stale if it were done once at startup.
        self.refresh()
        super().showEvent(event)
