"""The registry of save conversions the library can build from nothing, and
the `File ▸ Convert…` dialog over it.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)` replaces the two flagged submenus -- `editor/dosimport.py`'s
`File ▸ Import` and `editor/exports.py`'s `File ▸ Export` -- with one
`File ▸ Convert…` dialog carrying a source row and a destination row. A
**direction** is registered here only when the destination can be written
whole, owing nothing to another save -- `.claude/rules/conversions.md`'s
rule against a template. Today that is:

* DOS save folder → C64, one row per entry of `goldbox.dos.CONVERTS` --
  Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver Blades
  (`goldbox.dos.new_save`; Pool of Radiance proven in VICE by
  `#119 (Play a converted DOS save in VICE, off a disk Wish built from
  nothing)`, Curse of the Azure Bonds by `#192 (Convert a Curse of the Azure
  Bonds DOS save into a C64 one, which the importer refuses today)`, Secret
  of the Silver Blades by `docs/175-silver-blades-save-conversion.md`);
* C64 `.D64` → DOS save folder, Pool of Radiance only
  (`goldbox.dos.new_dos_save`, proven in DOSBox by `tools/dosnewsave.py`
  under `#26 (Write a DOS save, not just read one)`).

**This registry derives its DOS → C64 rows from `goldbox.dos.CONVERTS`
rather than listing them, which is the point:** a title joins `CONVERTS` when
its C64 writer exists, and it appears here with no edit to this module.
`DOS_TO_C64_NAMES` below is the one thing `CONVERTS` does not carry -- the
`.D64` file name each title's conversion writes -- and a `CONVERTS` entry
missing a row there fails loudly when `DIRECTIONS` is built, at import time,
rather than answering `[]` for a title the library can actually write.

**The source is a path, not the open window.** `Source.detect` reads a
`.D64`, a `SAVGAM<slot>.DAT`/`.PTY` file, or a DOS save folder directly, the
way `tools/dosdisk.py` and `tools/dosnewsave.py` already do. When the path is
the save the editor already has open, the caller passes `party` and this
reads its in-memory bytes instead, so unsaved edits cross -- the same rule
`exports.Source.from_party` followed. `exports.Source` retires into this one
at step 5.

**`ConvertDialog`, below, is step B of `work/reports/52-plan.md`** (also
`#52`'s comment of 2026-09-05 13:58:53): the source and destination rows, a
game-files row shown only for a DOS destination, a write-to-folder row, and
the report pane -- `editor/dosimport.py`'s rehearse-then-enable pattern, one
dialog for every registered direction rather than one dialog per port. Every
string not already approved elsewhere ends in the literal
` (NOT APPROVED)`; see the block below it.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import pathlib
import re
import tempfile
from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QWidget,
)

from goldbox import dos, dos_layout, games

from . import dosimport

_log = logging.getLogger("wish.editor.convert")


class ConvertError(Exception):
    """Anything a direction or `Source.detect` refuses, phrased for a pane."""


def _same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    """Whether two paths name the same file, across relative and symlinked forms."""
    try:
        return a.resolve() == b.resolve()
    except OSError:            # a path that cannot be resolved is not a match
        return False


# ---------------------------------------------------------------------------
# What is being converted
# ---------------------------------------------------------------------------

@dataclasses.dataclass

class Source:
    """One save, read off a path -- never off what a window happens to hold.

    `title` is a `goldbox.games.Game` for a C64 source or a
    `goldbox.dos_layout.DosShape` for a DOS one; both carry `.key`, which is
    what `Direction.source_key` matches against. `save0`/`save1`/`disk` are
    set only for a C64 source -- a DOS source is a folder, read fresh by
    whichever `Direction` converts it. `slot` is the DOS save slot a DOS
    source was detected at -- the letter in `SAVGAM<slot>.DAT`/`.PTY` -- so
    the dialog needs no separate slot row; it stays `None` for a C64 source,
    which has none.
    """

    port: str                      # "c64" or "dos"
    title: Any
    path: pathlib.Path
    save0: bytes | None = None
    save1: bytes | None = None
    disk: bytes | None = None
    slot: str | None = None

    @property
    def key(self) -> str:
        return self.title.key

    @classmethod
    def detect(cls, path: str | pathlib.Path, party: Any = None) -> "Source":
        """A `.D64`, a DOS save folder, or the party already open at `path`.

        `party` is a duck-typed `editor.roster.Party` -- `.path`, `.game`,
        `.save0`, `.save1`, `.disk` -- and is used only when its own path is
        the one asked for, so unsaved edits on screen cross into the
        conversion instead of whatever is on disk.
        """
        path = pathlib.Path(path)
        # Both sides resolved: a caller may hand us a relative path where
        # `Party.path` is absolute, or either may cross a symlink.  Comparing
        # them raw falls through to reading the file, which is the stale copy
        # this branch exists to avoid -- and it would do it silently.
        if (party is not None and party.path
                and _same_file(pathlib.Path(party.path), path)):
            if party.save0 is None:
                raise ConvertError(f"{path} has no saved game open")
            return cls(port="c64", title=party.game, path=path,
                      save0=party.save0.to_bytes(),
                      save1=(party.save1.to_bytes()
                             if party.save1 is not None else None),
                      disk=party.disk.to_bytes())
        if path.is_dir():
            return cls._detect_dos_folder(path)
        if path.is_file():
            match = _SAVGAM_FILE_RE.match(path.name)
            if match:
                return cls._detect_dos_file(path.parent, match.group(1).upper())
            return cls._detect_c64_disk(path)
        raise ConvertError(
            f"{path} is neither a save disk nor a DOS save folder")

    @classmethod
    def _detect_dos_folder(cls, path: pathlib.Path) -> "Source":
        slots = _dos_slots(path)
        if not slots:
            raise ConvertError(f"{path} holds no DOS saved game")
        return cls._detect_dos_file(path, slots[0])

    @classmethod
    def _detect_dos_file(cls, folder: pathlib.Path, slot: str) -> "Source":
        """The DOS shape at `folder`, for the save at `slot`.

        The one thing the two callers above disagree on is which slot: a
        bare folder (`tools/dosdisk.py`, `tools/dosnewsave.py`, and the
        Step 1 tests) takes the first one `_dos_slots` finds, and a
        `SAVGAM<slot>.DAT`/`.PTY` file picked directly -- the dialog's own
        save picker -- names its own. Either way the title comes off
        `CHRDAT<slot>1.SAV`'s own size (`goldbox.dos_layout.shape_for`),
        never assumed.
        """
        record = folder / f"CHRDAT{slot}1.SAV"
        if not record.exists():
            raise ConvertError(
                f"{folder} holds SAVGAM{slot} but no CHRDAT{slot}1.SAV to "
                f"read its shape from")
        try:
            shape = dos_layout.shape_for(record.stat().st_size)
        except dos_layout.DosShapeError as exc:
            raise ConvertError(str(exc)) from exc
        return cls(port="dos", title=shape, path=folder, slot=slot)

    @classmethod
    def _detect_c64_disk(cls, path: pathlib.Path) -> "Source":
        from goldbox.d64 import D64, InvalidImageError
        from goldbox.savegame import SaveGameError, load_save

        try:
            disk = D64.open(str(path))
            game, sg0, sg1 = load_save(disk)
        except (SaveGameError, InvalidImageError, OSError) as exc:
            raise ConvertError(str(exc)) from exc
        return cls(port="c64", title=game, path=path,
                  save0=sg0.to_bytes(),
                  save1=sg1.to_bytes() if sg1 is not None else None,
                  disk=disk.to_bytes())


#: A DOS save container picked directly -- the dialog's save picker matches
#: `*.d64` and this pattern in one filter, so there is no separate slot row
#: (`#52`'s dialog, decision 2). Case-insensitive: the game itself always
#: writes upper case, but a picker should not refuse a renamed copy.
_SAVGAM_FILE_RE = re.compile(r"^SAVGAM([A-Za-z])\.(DAT|PTY)$", re.IGNORECASE)


def _dos_slots(folder: pathlib.Path) -> list[str]:
    """Slot letters present, from either save-container suffix.

    `goldbox.dos.slots_available` only globs `SAVGAM?.DAT`, which finds every
    title but Pools of Darkness -- its container is `SAVGAM?.PTY`
    (`goldbox/dos_savegame.py`'s `SAVE_POOLS_OF_DARKNESS`). Detecting a
    folder as DOS does not depend on which title it is, so both suffixes are
    looked for here.
    """
    slots = set()
    for pattern in ("SAVGAM?.DAT", "SAVGAM?.PTY"):
        slots.update(p.name[6] for p in folder.glob(pattern))
    return sorted(slots)


# ---------------------------------------------------------------------------
# What a direction would do
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Rehearsal:
    """What a direction's rehearsal produced, before anything is written.

    `files` is measured, not guessed: the rehearsal produced exactly these
    bytes, at a scratch location that may no longer exist by the time this is
    read back.
    """

    report: Any
    files: dict[str, bytes]


class Direction:
    """One writable conversion, registered only when it needs no template.

    `source_key` and `destination_game.key` are `goldbox.games.Game.key` or
    `goldbox.dos_layout.DosShape.key`, whichever port they name -- the two
    key spaces share the string `"pool-of-radiance"`, which is what lets
    `destinations_for` match a `Source` against a `Direction` without caring
    which module minted the key.
    """

    source_port: str
    source_key: str
    destination_port: str
    destination_game: Any

    def rehearse(self, source: Source, slot: str, options: Any) -> Rehearsal:
        raise NotImplementedError

    def write(self, rehearsal: Rehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        raise NotImplementedError


class UnnamedConversionError(Exception):
    """A `goldbox.dos.CONVERTS` entry with no row in `DOS_TO_C64_NAMES`.

    Raised while `DIRECTIONS` is being built, at import time -- never while a
    player is looking at a pane. A title the library can write and this
    module cannot name a file for is a defect in `DOS_TO_C64_NAMES`, not a
    direction to answer `[]` for the way an unregistered title does.
    """


#: The `.D64` file name each DOS → C64 direction writes, keyed by
#: `goldbox.dos_layout.DosShape.key`. The one thing `goldbox.dos.CONVERTS`
#: does not carry, so it stays a table here rather than a property on the
#: shape itself, which knows nothing about C64 file names.
DOS_TO_C64_NAMES: dict[str, str] = {
    # The player's own disks are named this way (`PORSAVE2.D64`).
    dos_layout.POOL_OF_RADIANCE.key: "PORSAVE{slot}.D64",
    # What `tools/cursedisk.py` writes.
    dos_layout.CURSE_OF_THE_AZURE_BONDS.key: "CURSE{slot}.D64",
    # What `tools/ssbdisk.py` writes.
    dos_layout.SECRET_OF_THE_SILVER_BLADES.key: "SSB{slot}.D64",
}


class DosToC64(Direction):
    """A DOS save folder becomes a C64 `.d64`, for any title in
    `goldbox.dos.CONVERTS` (#118, #119, #192).

    One instance per entry of `CONVERTS` -- see `DIRECTIONS` below -- so a
    title joining that tuple (`#193 (Convert a Secret of the Silver Blades
    DOS save into a C64 one, which the importer refuses today)` will put
    Secret of the Silver Blades there) needs no edit to this class.

    `rehearse` is `editor.dosimport.rehearse` exactly as `File ▸ Import`
    calls it today -- the whole conversion happens in memory and reads the
    title off the record itself (`goldbox.dos.shape_for`), not off `shape`
    here, so `write` only has to put the bytes it already built on disk.
    `shape` decides only which source this instance answers for and what
    the output is named.
    """

    source_port = "dos"
    destination_port = "c64"

    def __init__(self, shape: dos_layout.DosShape):
        self.shape = shape
        self.source_key = shape.key
        self.destination_game = games.by_key(shape.key)
        try:
            self._name = DOS_TO_C64_NAMES[shape.key]
        except KeyError:
            raise UnnamedConversionError(
                f"{shape.title} is in goldbox.dos.CONVERTS but "
                f"editor.convert.DOS_TO_C64_NAMES names no .D64 file for "
                f"it") from None

    def rehearse(self, source: Source, slot: str,
                options: "dosimport.GameFiles") -> Rehearsal:
        conversion = dosimport.rehearse(source.path, slot, options)
        name = self._name.format(slot=slot)
        return Rehearsal(conversion.report, {name: conversion.disk.to_bytes()})

    def write(self, rehearsal: Rehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        written = []
        for name, data in rehearsal.files.items():
            path = folder / name
            path.write_bytes(data)
            written.append(path)
        return written


@dataclasses.dataclass
class DosWriteRehearsal(Rehearsal):
    """What `PoolOfRadianceC64ToDos.write` needs to run the conversion again.

    `goldbox.dos.new_dos_save` writes real files, so the rehearsal itself
    runs into a scratch directory and `write` calls it a second time straight
    into the folder the player chose -- the same order `editor/exports.py`'s
    `DosPlan` already follows, and the reason `files` is measured from the
    scratch run rather than replayed from it.
    """

    save0: bytes
    save1: bytes | None
    slot: str
    game_dir: pathlib.Path


class PoolOfRadianceC64ToDos(Direction):
    """A C64 Pool of Radiance save becomes a DOS save folder (#26).

    No template anywhere (`.claude/rules/conversions.md`):
    `goldbox.dos.new_dos_save` is the no-template call, and `options` is the
    DOS game directory `ECL<n>.DAX` lives in -- mandatory, since the party's
    own area script has to be staged or the game exits to DOS on load.
    """

    source_port = "c64"
    source_key = games.POOL_OF_RADIANCE.key
    destination_port = "dos"
    destination_game = dos_layout.POOL_OF_RADIANCE

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path") -> DosWriteRehearsal:
        game_dir = pathlib.Path(options)
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos.new_dos_save(source.save0, source.save1,
                                      scratch_path, slot, game_dir)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return DosWriteRehearsal(report, files, source.save0, source.save1,
                                 slot, game_dir)

    def write(self, rehearsal: DosWriteRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        dos.new_dos_save(rehearsal.save0, rehearsal.save1, folder,
                         rehearsal.slot, rehearsal.game_dir)
        return sorted(folder / name for name in rehearsal.files)


#: One DOS → C64 row per entry of `goldbox.dos.CONVERTS` -- today Pool of
#: Radiance and Curse of the Azure Bonds -- plus the one C64 → DOS row. See
#: the module docstring for what would extend this and the issues it waits
#: on. `UnnamedConversionError` fires here, at import time, if `CONVERTS`
#: ever names a title `DOS_TO_C64_NAMES` does not.
DIRECTIONS: tuple[Direction, ...] = tuple(
    DosToC64(shape) for shape in dos.CONVERTS
) + (
    PoolOfRadianceC64ToDos(),
)


def destinations_for(source: Source) -> list[Direction]:
    """Every registered direction this source can be converted to.

    Empty for anything not in `DIRECTIONS` -- Secret of the Silver Blades,
    every Amiga direction -- which is the whole point: an unready direction is
    never offered and never refused.
    """
    return [d for d in DIRECTIONS
           if d.source_port == source.port and d.source_key == source.key]


# ---------------------------------------------------------------------------
# Where a conversion writes
# ---------------------------------------------------------------------------

def fresh_folder(destination: str | pathlib.Path,
                 today: datetime.date | None = None) -> pathlib.Path:
    """A folder inside `destination` this conversion owns outright.

    `wish-YYYY-MM-DD`, suffixed `-2`, `-3`... on collision, so a second
    conversion the same day never writes into the first one's folder
    (`#52 (File ▸ Import and File ▸ Export for every direction the library
    supports)`, comment 2026-09-04). **Never returns a folder that already
    exists** -- the caller creates it, this only names it.
    """
    destination = pathlib.Path(destination)
    today = today or datetime.date.today()
    stem = f"wish-{today.isoformat()}"
    candidate = destination / stem
    n = 1
    while candidate.exists():
        n += 1
        candidate = destination / f"{stem}-{n}"
    return candidate


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------

#: **Off unless `WISH_EXPERIMENTAL_CONVERT=1`.** Replaces
#: `editor.dosimport.ENV` and `editor.exports.ENV`, whose submenus this
#: dialog replaces -- `#131 (Lift WISH_EXPERIMENTAL_DOS_IMPORT, which needs
#: the import working for all three C64 titles)`'s bar transfers unchanged.
#: Not built rather than greyed out: a greyed entry invites the question of
#: how to un-grey it, and the answer would be a sentence in the interface
#: (`.claude/rules/feature-flags.md`).
#:
#: **Comes off when:** (1) no string below carries the `(NOT APPROVED)`
#: marker -- `test_every_placeholder_string_ends_in_not_approved` greps for the
#: last one; (2) a Pool of Radiance, a Curse and a Silver Blades DOS save
#: each list the Commodore 64, and a Pools of Darkness save never does
#: (`#131`); (3) every registered direction's drop list is empty --
#: `.claude/rules/conversions.md`'s list, tracked on `#131`; (4) the
#: README says how the source picker works; (5) each registered direction
#: has been loaded and walked in its emulator from a save this dialog's own
#: code path wrote.
ENV = "WISH_EXPERIMENTAL_CONVERT"

#: Anything else -- an empty string, `0`, `off` -- is off, matching
#: `wish/debugmode.py`. A variable somebody exported once and forgot must
#: not put an unfinished dialog in front of them.
TRUE = ("1", "true", "yes", "on")


def enabled() -> bool:
    """Is `File ▸ Convert…` offered in this run?"""
    import os
    return os.environ.get(ENV, "").strip().lower() in TRUE


# ---------------------------------------------------------------------------
# Strings.
#
# Reused ones carry the approval they already have, verbatim, and keep the
# name they were approved under so a reviewer can find the ruling. Every
# other one ends in the literal ` (NOT APPROVED)` until Donald rules
# (`.claude/rules/gui-text.md`) -- never invent a sentence beyond this block.
# ---------------------------------------------------------------------------

#: The File menu entry. PROPOSED -- the two submenus it replaces were
#: `&Import` and `&Export`, and this dialog is neither.
MENU_CONVERT = "&Convert… (NOT APPROVED)"

#: The dialog's title bar. PROPOSED.
DIALOG_TITLE = "Convert a save (NOT APPROVED)"

#: Row labels. `LABEL_GAME` is `editor/exports.py`'s, approved 2026-08-25;
#: `LABEL_FOLDER` is its `LABEL_DESTINATION`, approved the same day -- the
#: row where the player says which folder the write goes inside, renamed
#: here so it is not confused with `convert_destination`'s new combo.
LABEL_SOURCE = "Save (NOT APPROVED)"
LABEL_TO = "To (NOT APPROVED)"
LABEL_GAME = "DOS game folder"
LABEL_FOLDER = "Write to"

#: Buttons. `BUTTON_CHOOSE` is `editor/exports.py`'s word, approved
#: 2026-08-25; `BUTTON_CONVERT` is `editor/dosimport.py`'s, approved
#: 2026-08-24.
BUTTON_CHOOSE = "Choose…"
BUTTON_CONVERT = "Convert"

#: Picker titles. `GAME_TITLE` and `FOLDER_TITLE` are `editor/exports.py`'s
#: `GAME_TITLE` and `DESTINATION_TITLE`, approved 2026-08-25.
SOURCE_TITLE = "Choose a save (NOT APPROVED)"
GAME_TITLE = "Choose the DOS game folder"
FOLDER_TITLE = "Choose where to write"

#: The save picker's filter: a `.d64` or the DOS save container itself, so
#: picking `SAVGAMB.DAT` picks slot B with no separate slot row. PROPOSED --
#: only the descriptive label is new; `;;All files (*)` is
#: `editor/window.py`'s `DISK_FILTER` boilerplate, reused rather than
#: reworded.
SOURCE_FILTER = ("Saved games (NOT APPROVED) "
                 "(*.d64 *.D64 SAVGAM?.DAT SAVGAM?.PTY);;All files (*)")

#: The destination combo's items, by port -- never by title, since
#: `destinations_for` never offers two directions of the same port for one
#: source (`.claude/rules/conversions.md`: a conversion never crosses a
#: title). PROPOSED. Amiga has no row yet (`#316 (Write the Amiga Pool of
#: Radiance saved game from the source save, so a converted party arrives
#: where it was standing)`), so it is not listed here until it can be
#: exercised.
DESTINATION_LABELS: dict[str, str] = {
    "c64": "Commodore 64 (NOT APPROVED)",
    "dos": "DOS (NOT APPROVED)",
}

#: The pane while a required row is still empty.
NO_GAME_FOLDER = "Choose the DOS game folder. (NOT APPROVED)"
#: `editor/exports.py`'s `NO_DESTINATION`, approved 2026-08-25.
NO_FOLDER = "Choose where to write."
#: `goldbox.dos.CANNOT_CONVERT`, approved under `#195 (The import pane shows
#: a player a memory address when the conversion refuses for any reason but
#: the wrong title)` on 2026-09-02 -- reused rather than a second sentence
#: meaning the same thing, for a source with no registered destination, for
#: `Source.detect` failing, and for anything `rehearse` raises that is not a
#: `dos.DosRecordError` with its own `player_message`.
CANNOT_CONVERT = dos.CANNOT_CONVERT
#: `editor/dosimport.py`'s `NO_DISKS`/`NO_DISKS_TITLE`, approved 2026-08-27.
NO_DISKS = dosimport.NO_DISKS
NO_DISKS_TITLE = dosimport.NO_DISKS_TITLE
#: Donald's own wording, `09027bb` (2026-09-05) -- shared with
#: `editor/dosimport.py`'s and `editor/exports.py`'s `DROPPED_HEADING`, one
#: conversion vocabulary whichever way it is going.
DROPPED_HEADING = dosimport.DROPPED_HEADING
#: `editor/exports.py`'s `WRITES_HEADING`, approved 2026-08-25.
WRITES_HEADING = "This writes:"

#: The status line after a DOS write, which nothing else in the window
#: reports (a C64 write is opened in the editor and gets its own status the
#: way `File ▸ Open` does). PROPOSED.
CONVERTED_DOS = "Converted to DOS slot {slot} in {folder} (NOT APPROVED)"


def _writes_text(rehearsal: "Rehearsal", folder: pathlib.Path) -> str:
    """The files a write would produce, one to a line, under a heading.

    `folder` is `fresh_folder`'s own preview of where Convert would write --
    named, not reserved, so a second Convert before this one commits can
    still land in the same place (the review of `a60e829`; the actual
    `mkdir()` happens once, in `EditorBinding.convert`, right before the
    write it guards).
    """
    return "\n".join([WRITES_HEADING, ""]
                     + [f"  {folder / name}"
                        for name in sorted(rehearsal.files)])


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------

class ConvertDialog(QDialog):
    """The source, the destination, what will be lost, and where it goes.

    One dialog for every registered direction (`#52`'s comment of
    2026-09-02: one Convert dialog with a source and a destination, not one
    per port). Every row change calls `replan()`, which detects the source,
    lists its registered destinations, rehearses the chosen one in memory,
    and puts the result on the pane -- `editor/dosimport.py`'s
    rehearse-then-enable pattern. Convert is enabled only once a rehearsal
    exists and a folder to write it into has been named; nothing is written
    until the caller commits it (`editor.window.EditorBinding.convert`),
    which is what keeps `fresh_folder`'s naming and the actual `mkdir()`
    together rather than racing between two calls.

    `game_files` is a callable, `title -> GameFiles | None` --
    `EditorBinding.game_files_for` in the running program -- so this class
    never has to know how the player's C64 disks are found.
    """

    def __init__(self, source: str, party: Any,
                game_files: "Any",
                destination: str | None = None,
                game: str | None = None,
                folder: str | None = None,
                parent: QWidget | None = None,
                start_dir: str = ""):
        super().__init__(parent)
        from .ui_convert import Ui_ConvertDialog

        self.ui = Ui_ConvertDialog()
        self.ui.setupUi(self)
        self.setWindowTitle(DIALOG_TITLE)

        self.party = party
        self._game_files = game_files
        self.start_dir = start_dir or str(pathlib.Path.home())

        self._source_path = str(source)
        self._wanted_port = destination
        self._game_path = game
        self._folder_path = folder
        self._rebuilding_combo = False

        #: Set by `replan()`. `source`/`direction` are `None` whenever the
        #: pane is not showing a ready-to-write conversion; `rehearsal` is
        #: the one thing `EditorBinding.convert` needs to commit a write.
        #: `slot` is the DOS slot the rehearsal used -- the source's own for
        #: a DOS → C64 direction, the fixed `"A"` a fresh DOS folder always
        #: gets for a C64 → DOS one -- so a status line can name it without
        #: guessing which side of the conversion DOS was on.
        self.source: Source | None = None
        self.direction: Direction | None = None
        self.rehearsal: Rehearsal | None = None
        self.slot: str | None = None

        self.ui.label_source.setText(LABEL_SOURCE)
        self.ui.label_to.setText(LABEL_TO)
        self.ui.label_folder.setText(LABEL_FOLDER)

        self.ui.convert_source.setText(self._source_path)
        self.ui.convert_choose_source.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_source.clicked.connect(self._choose_source)

        self.ui.convert_destination.currentIndexChanged.connect(
            self._destination_changed)

        self.ui.convert_game.setText(self._game_path or "")
        self.ui.convert_choose_game.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_game.clicked.connect(self._choose_game)

        self.ui.convert_folder.setText(self._folder_path or "")
        self.ui.convert_choose_folder.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_folder.clicked.connect(self._choose_folder)

        self.buttons = self.ui.buttons
        self.buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText(BUTTON_CONVERT)

        self.replan()

    # -- where it writes ---------------------------------------------------

    @property
    def folder(self) -> str:
        """The folder Convert would write inside, as the user has left it."""
        return self._folder_path or ""

    def refuse(self, text: str) -> None:
        """Put a failed write in the pane the losses are already reported
        in, the way `editor/dosimport.py`'s `DosImportDialog.refuse` does."""
        self.ui.convert_report.setPlainText(text)

    # -- choosing -----------------------------------------------------------

    def _choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, SOURCE_TITLE, self._source_path or self.start_dir,
            SOURCE_FILTER)
        if path:
            self._source_path = path
            self.ui.convert_source.setText(path)
            self._wanted_port = None
            self.replan()

    def _choose_game(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, GAME_TITLE, self._game_path or self.start_dir)
        if path:
            self._game_path = path
            self.ui.convert_game.setText(path)
            self.replan()

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, FOLDER_TITLE, self._folder_path or self.start_dir)
        if path:
            self._folder_path = path
            self.ui.convert_folder.setText(path)
            self.replan()

    def _destination_changed(self, _index: int) -> None:
        if self._rebuilding_combo:
            return
        self._wanted_port = self.ui.convert_destination.currentData()
        self.replan()

    # -- the rehearsal --------------------------------------------------

    def replan(self) -> None:
        """Detect the source, rehearse the chosen destination, and put the
        result on the pane. Failures are shown, not raised -- the same rule
        `editor/dosimport.py`'s `_rehearse` follows."""
        self.source = None
        self.direction = None
        self.rehearsal = None
        self.slot = None

        if not self._source_path:
            self._populate_destinations([])
            self.ui.convert_report.setPlainText("")
            self._settle_game_row()
            self._settle_button()
            return

        try:
            self.source = Source.detect(self._source_path, party=self.party)
            options = destinations_for(self.source)
        except Exception:
            _log.exception("could not read %s", self._source_path)
            self._populate_destinations([])
            self.ui.convert_report.setPlainText(CANNOT_CONVERT)
            self._settle_game_row()
            self._settle_button()
            return

        self._populate_destinations(options)
        if not options:
            self.ui.convert_report.setPlainText(CANNOT_CONVERT)
            self._settle_game_row()
            self._settle_button()
            return

        self.direction = self._chosen_direction(options)
        self.ui.convert_report.setPlainText(self._rehearse_and_report())
        self._settle_game_row()
        self._settle_button()

    def _chosen_direction(self, options: list["Direction"]) -> "Direction":
        for d in options:
            if d.destination_port == self._wanted_port:
                return d
        return options[0]

    def _rehearse_and_report(self) -> str:
        direction = self.direction
        if direction.destination_port == "c64":
            if not self.source.slot:
                # Unreachable through the dialog's own save picker, which
                # always names a slot (`Source.detect`'s `SAVGAM<slot>.*`
                # branch); only a caller handing `Source.detect` a bare
                # folder directly -- a test or `tools/` script -- can reach
                # this, and there is no slot to guess at for it.
                return CANNOT_CONVERT
            slot = self.source.slot
            options: Any = self._game_files(direction.destination_game)
            if options is None:
                return NO_DISKS
        else:
            slot = "A"
            if not self._game_path:
                return NO_GAME_FOLDER
            options = pathlib.Path(self._game_path)

        try:
            self.rehearsal = direction.rehearse(self.source, slot, options)
            self.slot = slot
        except dos.DosRecordError as exc:
            _log.exception("could not rehearse %s", self._source_path)
            return exc.player_message
        except Exception:
            _log.exception("could not rehearse %s", self._source_path)
            return CANNOT_CONVERT

        if not self._folder_path:
            return NO_FOLDER

        preview = fresh_folder(pathlib.Path(self._folder_path))
        return (dosimport.dropped_text(self.rehearsal.report) + "\n\n"
               + _writes_text(self.rehearsal, preview))

    # -- what is shown, and when Convert is pressable -----------------

    def _populate_destinations(self, options: list["Direction"]) -> None:
        combo = self.ui.convert_destination
        self._rebuilding_combo = True
        combo.blockSignals(True)
        combo.clear()
        for d in options:
            combo.addItem(
                DESTINATION_LABELS.get(d.destination_port, d.destination_port),
                d.destination_port)
        if options:
            chosen = self._chosen_direction(options)
            combo.setCurrentIndex(options.index(chosen))
            self._wanted_port = chosen.destination_port
        combo.blockSignals(False)
        self._rebuilding_combo = False

    def _settle_game_row(self) -> None:
        """The game-files row is shown only for a DOS destination -- the
        C64 disks are a Preferences setting already, and there is no Amiga
        direction yet to need its own picker (`#52`'s plan, "three C64
        titles means the disks are chosen by the destination title")."""
        show = self.direction is not None and self.direction.destination_port == "dos"
        self.ui.form.setRowVisible(self.ui.game_row, show)
        if show:
            self.ui.label_game.setText(LABEL_GAME)

    def _settle_button(self) -> None:
        """Convert is pressable only once there is a rehearsal to write and
        somewhere named to write it -- `editor/dosimport.py`'s rule, and the
        reason a ready rehearsal with no folder still shows `NO_FOLDER`
        rather than the writes list (`_rehearse_and_report` above)."""
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.rehearsal is not None and bool(self._folder_path))
