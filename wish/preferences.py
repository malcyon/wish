"""File > Preferences: where the game disks are, and which live backend.

**Half of this is the report, not the form.** The failure it exists to fix is
silent -- items rendered as `word 8`, an empty map tab, and the one diagnostic
that says why printed to a stderr a desktop launcher throws away. So the dialog
says what was *found*: which folder is in use, who named it, which titles are
in it, how many maps came out, and which image the item names came off. A user
who types nothing still learns what went wrong.

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

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from automap import paths
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

#: The `$POR_ULTIMATE` this process started with, read once, so that emptying
#: the box gives the user's own value back rather than nothing.
_UNREAD = object()
_ENV_HOST: object | str | None = _UNREAD


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
def _scan(where: str, key: str | None) -> dict:
    """What is in this folder: titles, maps, and which disk holds what.

    Cached because the dialog re-reports as you type and this opens D64s. The
    key is the folder and the title, which is everything the answer depends on.
    """
    from automap.__main__ import load_maps_titled
    from por.iconparts import IconParts
    from por.icons import load_icon_charset
    from por.items import load_item_names

    root = pathlib.Path(where)
    found: dict = {"titles": [], "maps": 0, "names": None, "items": 0,
                   "charset": None, "parts": None}
    if not root.is_dir():
        return found
    found["titles"] = [(g, len(_images(root, g))) for g in paths.titles_in(root)]
    game = games.BY_KEY.get(key) if key else None
    if game is None and found["titles"]:
        game = found["titles"][0][0]
    if game is None:
        return found
    try:
        found["maps"] = len(load_maps_titled(str(root), game)[0])
    except Exception:
        # A folder of the right names holding something that is not a D64.
        # "none" is the honest report, and an exception here would take down
        # the one dialog somebody opened to find out what was wrong.
        found["maps"] = 0
    for path in _images(root, game):
        if found["names"] is None:
            try:
                names = load_item_names(str(path), game)
            except Exception:
                names = None
            if names:
                found["names"], found["items"] = path.name, len(names)
        for slot, read in (("charset", load_icon_charset),
                           ("parts", IconParts.load)):
            if found[slot] is None:
                try:
                    read(str(path))
                except Exception:
                    continue
                found[slot] = path.name
    return found


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


def report(settings, flag=None, beside=None, game: games.Game | None = None,
           editor=None) -> list[tuple[str, str]]:
    """The six lines the dialog prints, as (label, value) pairs.

    Each answers a question somebody has actually had: is it even looking where
    I put them, why is it ignoring what I typed, are these the right disks, why
    is the map tab blank, why are my items numbers, and why can I not edit the
    combat icon. A failure is stated in the same slot -- an empty answer is
    more informative than a missing row.

    `editor` is the character editor, when there is one: its item names and
    icons are already loaded and may have come off a disk named by
    `--game-disk`, so what it actually used beats anything re-derived here.
    """
    where, source = paths.resolve_disks(flag=flag, beside=beside, game=game,
                                        settings=settings)
    rows = [("In use", str(where) if where is not None else "nothing found"),
            ("Set by", _set_by(source, settings))]
    if where is None:
        wanted = [game] if game else list(games.GAMES)[:2]
        patterns = " or ".join(_pretty(g.disk_glob) for g in wanted)
        return rows + [
            ("Titles", f"none; nowhere with {patterns} in it was found"),
            ("Maps", "none, so the map tab is empty"),
            ("Names", "not found, so items show as name-table indices"),
            ("Icons", "not found, so the combat icon cannot be edited")]

    found = _scan(str(where), game.key if game else None)
    titles = found["titles"]
    if titles:
        titles_line = " · ".join(f"{g.title} ({n} disk{'' if n == 1 else 's'})"
                                      for g, n in titles)
    else:
        wanted = [game] if game else list(games.GAMES)[:2]
        patterns = " or ".join(_pretty(g.disk_glob) for g in wanted)
        titles_line = f"none; no {patterns} here"
    rows.append(("Titles", titles_line))
    rows.append(("Maps", f"{found['maps']} GEO files" if found["maps"]
                 else "none, so the map tab is empty"))

    names_disk, items = found["names"], found["items"]
    spells = 0
    if editor is not None and getattr(editor, "item_names", None):
        named = getattr(editor, "game_disk_found", None)
        names_disk = pathlib.Path(named).name if named else names_disk
        items = len(editor.item_names)
        spells = len(getattr(editor, "spell_names", {}) or {})
    if names_disk:
        names_line = f"{names_disk} — {items} item names"
        if spells:
            names_line += f", {spells} spells"
    else:
        names_line = "not found, so items show as name-table indices"
    rows.append(("Names", names_line))

    charset, parts = found["charset"], found["parts"]
    if editor is not None and getattr(editor, "icon_parts_disk", None):
        parts = pathlib.Path(editor.icon_parts_disk).name
    if charset and parts:
        icons = f"{charset} · icon parts {parts}"
    elif charset:
        icons = f"{charset} · no icon parts here, so an icon can be drawn " \
                "but not changed"
    else:
        icons = "not found, so the combat icon cannot be edited"
    rows.append(("Icons", icons))
    return rows


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
        outer.addWidget(self._backend_group())
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
        for name in ("In use", "Set by", "Titles", "Maps", "Names", "Icons"):
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
        for name, action in self.win.backend_actions.items():
            button = QRadioButton(action.text())
            button.setToolTip(action.toolTip())
            button.setChecked(action.isChecked())
            button.clicked.connect(
                lambda _checked=False, n=name: self._prefer(n))
            outer.addWidget(button)
            self.radios[name] = button

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

    # -- the debug log ---------------------------------------------------

    def _log_group(self) -> QGroupBox:
        box = QGroupBox("Diagnostics")
        outer = QVBoxLayout(box)
        self.logging = QCheckBox("Debug log")
        self.logging.setChecked(self.win.debug_action.isChecked())
        self.logging.toggled.connect(self.win.debug_action.setChecked)
        self.win.debug_action.toggled.connect(self.logging.setChecked)
        outer.addWidget(self.logging)
        note = QLabel(
            "Remembered between sessions. While it is on the window title says "
            "[logging] and the status bar shows it, so a log left running is "
            "not a silent one. View > Show log opens the file.")
        note.setWordWrap(True)
        outer.addWidget(note)
        return box

    # -- what was found --------------------------------------------------

    def refresh(self) -> None:
        """Re-run the search and re-print the report. Cheap, apart from `_scan`."""
        for name, value in report(self.win.settings,
                                  flag=self.win.disks_flag,
                                  beside=self.win.editor.path,
                                  game=self.win.game(),
                                  editor=self.win.editor):
            self.report_rows[name].setText(value)
        self.win.label_backends()
        for name, button in self.radios.items():
            action = self.win.backend_actions[name]
            button.setText(action.text())
            button.setChecked(action.isChecked())
        self.password.setText(
            f"from ${PASSWORD_ENV} — "
            + ("set" if os.environ.get(PASSWORD_ENV) else "not set"))

    def showEvent(self, event):
        # `probe()` is a TCP connect: right when somebody opens this, wrong on
        # a poll timer and stale if it were done once at startup.
        self.refresh()
        super().showEvent(event)
