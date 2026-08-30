"""File > Preferences: the game disks, the live backend, and where a fasttravel
may go.

**Half of this is the report, not the form.** The failure it exists to fix is
silent -- items rendered as `word 8`, an empty map tab, and the one diagnostic
that says why printed to a stderr a desktop launcher throws away. So the dialog
says what was *found*: which folder is in use, and which titles are in it. A
user who types nothing still learns what went wrong. It said three
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
* **Two tabs, and every width in it is measured.** General holds the form;
  Fast travel holds the 29-row area table, which stretches to fill it. In one
  column neither could have the height it wanted, and a dialog compressed below
  its layout's minimum squeezes the controls that can be squeezed rather than
  refusing -- which is what "a lot of fields are squished" was. No width here
  is a chosen number either: `room_for` asks the style what a line edit needs
  for its own placeholder, the spin box sizes itself from its special-value
  text, and the table is asked for its column.

**`editor.files` is imported here, and only here.** The backup folder is that
module's business and the setting is `automap`'s, so the function that puts the
two together (`backup_folder`) lives on this side. The one-way rule the project
keeps is that `editor/` imports nothing from `automap/`; `wish/` is the layer
that is allowed to know about both, and this is it.

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
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyleOptionFrame,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from automap import paths
from automap.actionbar import DANGER, no_areas
from automap.config import clamp_to_screen
from goldbox import areas as area_table
from goldbox import games

from .ui_preferences import Ui_PreferencesDialog

#: Spelled out rather than `QKeySequence.StandardKey.Preferences`, which
#: resolves on Linux/Qt 6 to the `XF86Settings` multimedia key --
#: `toString()` returns 'Settings' -- a shortcut no ordinary keyboard can
#: produce. Measured in this venv.
SHORTCUT = "Ctrl+,"

#: How long after the last keystroke the folder is re-read. Typing a path a
#: character at a time would otherwise open eight D64s per letter.
SETTLE_MS = 400

#: What the backup box says while it is empty, which is the state a fresh
#: config is in. It is also what sets that box's width -- `room_for` measures
#: it -- so it says the rule in as few words as carry it.
BACKUPS_PLACEHOLDER = "set when you open a save"

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

#: The fewest rows of the area table worth drawing. It has no maximum -- it is
#: the one thing on its own tab that stretches, so it takes whatever height the
#: dialog has, which is the point of the tab (`docs/130-preferences.md` §14).
#: Six is enough to read as a list on a display that gives it nothing.
TABLE_MIN_ROWS = 6

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


def chosen_backup_folder(settings) -> bool:
    """Whether the backup folder is the user's own. See `backup_folder`."""
    return bool(getattr(settings, "backup_folder_chosen", False))


def backup_folder(settings, save) -> str:
    """What the backup folder setting should hold, given the open save.

    **Two states, and this function is the whole of the distinction.**

    *Chosen* -- the user typed or picked a path. It is the answer for every
    save from then on and nothing automatic may change it.

    *Automatic* -- what a fresh config is in: `backups/` under the folder of
    whatever save is open, moving with it, and **empty with nothing open**,
    because there is no save to be beside yet. Empty means no backups, and no
    backup means no save at all (`editor/files.py::save_disk`).

    It creates nothing. A dialog that only reports must not write to the folder
    somebody keeps their disks in, least of all this project's own
    `Pool of Radiance Disks/`; `back_up` makes the folder at the moment it has
    something to put in it.
    """
    from editor import files

    if chosen_backup_folder(settings):
        return (getattr(settings, "backup_folder", "") or "").strip()
    if save is None:
        return ""
    return str(files.automatic_dir(save))


def report(settings, flag=None, beside=None,
           game: games.Game | None = None) -> list[tuple[str, str]]:
    """The two lines the dialog prints, as (label, value) pairs.

    Each answers a question somebody has actually had: is it even looking where
    I put them, and are these the right disks. A failure is stated in the same
    slot -- an empty answer is more informative than a missing row.

    It printed three more -- the map count, the disk the item names came off
    and the icon charset. Donald had them out in 2026-08: they answered
    questions nobody was asking at the moment of opening this dialog, and the
    map tab and the item column say the same thing where you are looking.
    """
    where, _source = paths.resolve_disks(flag=flag, beside=beside, game=game,
                                         settings=settings)
    rows = [("In use", str(where) if where is not None else "nothing found")]
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


#: The spin box no longer carries 0 as "let the backend decide" -- the
#: checkbox does. So it needs a real floor, and 50 ms is four times the
#: fastest poll anything here runs at.
MIN_INTERVAL_MS = 50


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
        self.ui = Ui_PreferencesDialog()
        self.ui.setupUi(self)
        self.tabs = self.ui.tabs
        self._buttons = self.ui.buttons

        # Replace the placeholder tab pages with the real ones.
        self.tabs.removeTab(1)
        self.tabs.removeTab(0)
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._travel_tab(), "Fast travel")
        # General every time. A dialog that reopens on a tab nobody chose is
        # worse than one that remembers nothing, so nothing is remembered.
        self.tabs.setCurrentIndex(0)

        # One timer for both: re-reading a folder opens every D64 in it, and
        # applying it reloads 29 maps. Neither belongs on a keystroke.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._folder_settled)
        self.refresh()
        self.fit()

    def _general_tab(self) -> QWidget:
        """Everything except fast travel: the disks, the backups, the backend
        and the log.

        **The scroll area is a floor, not a feature.** At the size `fit` opens
        it there is nothing to scroll -- the bar is not drawn. It is here for
        the display that cannot give this tab its 578 lines, where the choice
        is a scrollbar or the crushed line edits this dialog was rebuilt to
        stop. Never sideways: the width is the width the content measured.
        """
        self._general = QWidget()
        box = QVBoxLayout(self._general)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._disks_group())
        box.addWidget(self._backups_group())
        box.addWidget(self._backend_group())
        box.addWidget(self._combat_group())
        box.addWidget(self._log_group())
        box.addWidget(self._automap_group())
        box.addStretch(1)

        self._general_scroll = QScrollArea()
        self._general_scroll.setWidget(self._general)
        self._general_scroll.setWidgetResizable(True)
        self._general_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._general_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return self._general_scroll

    def sizeHint(self) -> QSize:
        """The size the tabs want, with General's real page asked for.

        A `QScrollArea`'s own hint is a fraction of what it holds -- ask it and
        the dialog opens 100 px tall with the whole form scrolled away -- so
        the page inside is what is asked, plus the scrollbar's width because it
        is there on a short screen.
        """
        hint = super().sizeHint()
        room = self._general.sizeHint() - self._general_scroll.sizeHint()
        return QSize(hint.width() + max(room.width(), 0)
                     + self._general_scroll.verticalScrollBar()
                     .sizeHint().width(),
                     hint.height() + max(room.height(), 0))

    # -- how big it opens --------------------------------------------------

    def fit(self, space=None) -> None:
        """Open wide enough that the prose stops wrapping, and tall enough for
        General at that width.

        **Height is the scarce one.** The work area is 662 lines tall and 1280
        across, and every line a paragraph wraps to is a line of height a wider
        dialog would not have spent -- the backups note takes three lines at
        the width the folder row alone asks for and two at 784. So the width
        is raised while that is still true and then stopped: as narrow as it
        can be without costing height. The ceiling is twice the widest
        control, which no sentence in a settings dialog needs.

        Getting this wrong is not cosmetic. A dialog handed less height than
        its layout's minimum does not refuse -- it squeezes what can be
        squeezed, and what can be squeezed here is the Ultimate host box and
        the poll spinner, which went to nine pixels tall with their text cut
        through the middle. That was Donald's "squished and unusable".
        """
        hint = self.sizeHint()
        wrap = self._general.layout()
        widest = 2 * hint.width()
        settled = wrap.heightForWidth(widest)
        width = hint.width()
        while width < widest and wrap.heightForWidth(width) > settled:
            width += 10
        # `heightForWidth` under-reports what the group boxes then take -- by
        # 19 px here -- so it is the *saving* that is used and the size hint,
        # which is measured at the hint width, that is trusted.
        self.resize(width, hint.height() - (wrap.heightForWidth(hint.width())
                                            - settled))
        clamp_to_screen(self, space)

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
        for name in ("In use", "Titles"):
            value = QLabel("")
            value.setWordWrap(True)
            # Selectable: the first thing anybody does with a path in a
            # report is paste it somewhere.
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self.report_rows[name] = value
            form.addRow(name, value)
        outer.addLayout(form)
        return box

    # -- where the backups go ---------------------------------------------

    def _backups_group(self) -> QGroupBox:
        """Where a copy of the save goes before it is overwritten.

        Donald asked where `~/.local/share/wish/backups` came from and said no
        user would ever think to look there. Nobody does now: there is one
        folder, it is in this box, and the box says what it is.

        **Blank on a fresh config, and blank means no backups** -- and no
        saves, because the editor's licence to write over the file you opened
        is the copy it takes first. Opening a save fills it in with `backups/`
        under that save's folder and it follows every save opened after that;
        type or browse to one of your own and it stops following anything.
        Clear it to go back to following.
        """
        box = QGroupBox("Backups")
        outer = QVBoxLayout(box)
        row = QHBoxLayout()
        self.backups = QLineEdit("")
        self.backups.setPlaceholderText(BACKUPS_PLACEHOLDER)
        # Measured off its own placeholder, like the folder box: what it says
        # is the only instruction there is for an empty field.
        self.backups.setMinimumWidth(room_for(self.backups,
                                              self.backups.placeholderText()))
        self.backups.editingFinished.connect(self._backups_edited)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_backups)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.set_backup_folder(""))
        row.addWidget(QLabel("Folder"))
        row.addWidget(self.backups, 1)
        row.addWidget(browse)
        row.addWidget(clear)
        outer.addLayout(row)
        self.backups_note = QLabel("")
        self.backups_note.hide()          # two of the three states say nothing
        self.backups_note.setWordWrap(True)
        outer.addWidget(self.backups_note)
        return box

    def _say_backups(self) -> None:
        """The path and the note, re-read whenever it refreshes.

        The note is which of the two states the field is in, because the path
        alone cannot say: `/somewhere/backups` looks the same whether it is
        following the open save or was typed in and is never moving again.

        The standing facts are said here too: a backup is made only when the
        bytes changed, and the newest few are kept rather than all of them.
        """
        where = getattr(self.win.settings, "backup_folder", "") or ""
        if not self.backups.hasFocus():
            self.backups.setText(where)
        # Two lines of note is 17 px of a dialog that has to fit 662 of them
        # (§14), so each of these is one line at the width `fit` opens.
        if chosen_backup_folder(self.win.settings):
            why = "Yours, for every save. Clear it to follow the save again."
        elif where:
            why = ""
        else:
            # Nothing. An empty box with no save open explains itself, and
            # Donald removed the sentence that said so.
            why = ""
        # Hidden when it says nothing, not merely empty: an empty QLabel still
        # takes its line, and the dialog has 662 of them (§14). Two of the
        # three states have no note now, so this is where the row the checkbox
        # took comes back from.
        self.backups_note.setText(why)
        self.backups_note.setVisible(bool(why))

    def browse_backups(self) -> None:
        """The folder picker. A method so a test can replace it."""
        chosen = QFileDialog.getExistingDirectory(
            self, "Where backups of your saves go",
            self.backups.text() or str(pathlib.Path.home()))
        if chosen:
            self.set_backup_folder(chosen)

    def set_backup_folder(self, folder: str) -> None:
        """Type this in and apply it, as Browse and Clear do."""
        self.backups.setText(folder)
        self._backups_edited()

    def _backups_edited(self) -> None:
        self.win.set_backup_folder(self.backups.text().strip())
        self.refresh()

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
        # Measured like the folder box, for the same reason: what it says is
        # the only instruction there is for the field.
        self.host.setMinimumWidth(room_for(self.host,
                                           self.host.placeholderText()))
        self.host.editingFinished.connect(self._host_changed)
        form.addRow("Ultimate host", self.host)
        self.password = QLabel("")
        form.addRow("Password", self.password)

        # 0 means "the backend decides" in the setting, and it used to mean that
        # on the face too -- a spin box whose lowest value printed a sentence
        # instead of a number, and turned into milliseconds the moment anybody
        # touched an arrow. Donald: confusing. So the state is a checkbox and
        # the spin box only ever shows a number.
        self.interval_default = QCheckBox("Poll using backend default")
        self.interval_default.toggled.connect(self._interval_default_toggled)
        self.interval = QSpinBox()
        self.interval.setRange(MIN_INTERVAL_MS, 60000)
        self.interval.setSingleStep(50)
        self.interval.setSuffix(" ms")
        saved = getattr(self.win.settings, "interval_ms", 0) or 0
        self.interval_default.setChecked(not saved)
        self.interval.setEnabled(bool(saved))
        self.interval.setValue(saved or MIN_INTERVAL_MS)
        self.interval.valueChanged.connect(self._interval_changed)
        form.addRow("Poll every", self.interval)
        form.addRow(self.interval_default)
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
        if not self.interval_default.isChecked():
            self.win.set_interval(value)

    def _interval_default_toggled(self, on: bool) -> None:
        """Ticked hands the interval back to the backend; 0 is how that is
        stored, and has been since before there was a checkbox."""
        self.interval.setEnabled(not on)
        self.win.set_interval(0 if on else self.interval.value())

    # -- fast travel -----------------------------------------------------

    def _travel_tab(self) -> QWidget:
        """Which areas the Fast Travel dropdown offers, and the warning.

        **A tab of its own, and the table takes all of it.** Twenty-nine rows
        beside the rest of the form meant a table capped at 160 px inside a
        dialog that itself scrolled -- Donald, on seeing it: *"I am not sure
        that making it bigger is the right option. What about tabs across the
        top?"* On its own tab the table is the only thing that stretches, so it
        gets every pixel the dialog has and the list is scanned rather than
        hunted through.

        **The player chooses, and nothing infers.** The dropdown used to filter
        itself by the areas the automapper had watched the party walk in;
        Donald threw that out because the record is only ever ours -- a party
        walks wherever it likes while the map window is shut -- so this is an
        explicit list of ticks and there is no second, cleverer rule behind it.

        **Area 30 is not in the table**, ticked or unticked: `ECL1E` is the
        attract-mode demo and entering it ends the session. `Area.fasttravelable`
        says so, and it is asked rather than the id being written down here.

        **The table is the open title's**, and five of the six titles have no
        area table at all -- `goldbox.areas.areas_for_title`. For those the table
        is empty and a sentence says which game nothing is known for, rather
        than offering Pool of Radiance's thirty to be ticked for a game they do
        not belong to (#14, `docs/138-multiple-games.md` §7 task 1).

        **The warning is a box, not a tooltip**, and it is here rather than on
        General: beside the thing it warns about. Same amber as the
        `unverified` badge -- one visual language for "this is a thing to know
        before you press it", and a sentence nobody has to hover to find.
        """
        box = QWidget()
        outer = QVBoxLayout(box)
        warning = QLabel(DANGER)
        warning.setWordWrap(True)
        warning.setStyleSheet(WARNING_BOX)
        outer.addWidget(warning)

        #: The table's rows, in the dropdown's own order: by name. Every
        #: fasttravelable area has one, and area 30 -- the only nameless one -- is
        #: also the only unfasttravelable one, so excluding it needs no second rule.
        self.travel_game = self.win.map_game()
        self.travel_rows = sorted(
            (a for a in area_table.areas_for_title(
                getattr(self.travel_game, "title", None)) if a.fasttravelable),
            key=lambda a: a.name or "")
        chosen = set(self.win.settings.chosen_areas(self.travel_game))
        self.travel_table = QTableWidget(len(self.travel_rows), 1)
        self.travel_table.setHorizontalHeaderLabels(["Area"])
        self.travel_table.verticalHeader().setVisible(False)
        self.travel_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.travel_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.travel_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        # No cap any more: the table is the only thing on this tab that
        # stretches, so it takes the height the dialog has. The minimum is
        # measured off a row -- enough that it is recognisably a list even on a
        # display that leaves it nothing.
        self.travel_table.setMinimumHeight(
            TABLE_MIN_ROWS * self.travel_table.verticalHeader().defaultSectionSize()
            + self.travel_table.horizontalHeader().sizeHint().height()
            + 2 * self.travel_table.frameWidth())
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
        # Wide enough for the longest area name with its tick box, asked of the
        # view rather than counted here: `sizeHintForColumn` puts the indicator,
        # the cell padding and the font together the way the delegate will draw
        # them. The bar is up whenever 29 rows do not fit, so it is added.
        self.travel_table.setMinimumWidth(
            self.travel_table.sizeHintForColumn(0)
            + self.travel_table.verticalScrollBar().sizeHint().width()
            + 2 * self.travel_table.frameWidth())
        self.travel_table.itemChanged.connect(lambda _item: self._travel_changed())
        outer.addWidget(self.travel_table, 1)

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
        self.win.set_fast_travel_targets(self.travel_ticked())
        self._say_travel()

    def _say_travel(self) -> None:
        """How many areas the dropdown will offer. A count, and no more.

        Nothing ticked used to get a sentence explaining that an empty list was
        the setting doing what was asked. Donald had it out in 2026-08 -- "the
        user will figure it out" -- and the dropdown's own disabled item and
        the disabled button say it where somebody is looking for it.

        A title with no area table is the one case that still needs a sentence:
        an empty table with "0 areas" under it looks like a feature that failed
        to load, where it is a game whose areas nobody has tabulated.
        """
        if not self.travel_rows:
            self.travel_note.setText(no_areas(
                getattr(self.travel_game, "title", None)))
            return
        ticked = len(self.travel_ticked())
        self.travel_note.setText(
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

    def _automap_group(self) -> QGroupBox:
        box = QGroupBox("Automap")
        outer = QVBoxLayout(box)
        self.clear_automap_button = QPushButton("Clear Automap Memory")
        self.clear_automap_button.setToolTip("Forget which areas you have explored on the automap.")
        self.clear_automap_button.clicked.connect(self._clear_automap)
        outer.addWidget(self.clear_automap_button)
        return box

    def _clear_automap(self):
        # We need to tell the automapper to clear its current state, and delete the JSON files.
        import shutil
        from automap.config import data_dir
        from automap.paths import title_dir
        
        # Clear files for the current game
        if self.win.mapper.state and self.win.mapper.state.title:
            maps_dir = data_dir() / title_dir(self.win.mapper.state.title)
            if maps_dir.exists():
                shutil.rmtree(maps_dir)
        
        # Reset current loaded state in AutomapState so it doesn't just re-save it
        if self.win.mapper.state:
            self.win.mapper.state.exploration.seen.clear()
            self.win.mapper.state.notes.clear()
            self.win.mapper.state.save_notes()
            self.win.mapper.notes_changed()

    def _combat_group(self) -> QGroupBox:
        box = QGroupBox("Combat")
        outer = QVBoxLayout(box)
        self.watch_box = QCheckBox("Clear quickfight after a fight")
        self.watch_box.setToolTip("When a fight ends, take everyone off quickfight. Off by default: it writes to the running game on an edge you did not ask for")
        saved = getattr(self.win.settings, "clear_quickfight", False)
        self.watch_box.setChecked(bool(saved))
        self.watch_box.toggled.connect(self._clear_quickfight_toggled)
        outer.addWidget(self.watch_box)
        return box

    def _clear_quickfight_toggled(self, on: bool) -> None:
        self.win.settings.clear_quickfight = on
        if hasattr(self.win, "map") and hasattr(self.win.map, "actions_bar"):
            self.win.map.actions_bar.watcher.enabled = on

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
        # Again with a frame to measure. Before `show()` the chrome reads as
        # nothing and `clamp_to_screen` has to guess at it -- the same trap the
        # main window fell into (`docs/130-preferences.md` §12).
        clamp_to_screen(self)
