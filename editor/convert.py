"""The registry of save conversions the library can build from nothing.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)` replaces the two flagged submenus -- `editor/dosimport.py`'s
`File ▸ Import` and `editor/exports.py`'s `File ▸ Export` -- with one
`File ▸ Convert…` dialog carrying a source row and a destination row. This
module is the library half of that plan: no window, no strings, no menu
entry. A **direction** is registered here only when the destination can be
written whole, owing nothing to another save -- `.claude/rules/
conversions.md`'s rule against a template. Today that is:

* DOS save folder → C64, one row per entry of `goldbox.dos.CONVERTS`
  (`goldbox.dos.new_save`; Pool of Radiance proven in VICE by
  `#119 (Play a converted DOS save in VICE, off a disk Wish built from
  nothing)`, Curse of the Azure Bonds by `#192 (Convert a Curse of the Azure
  Bonds DOS save into a C64 one, which the importer refuses today)`);
* C64 `.D64` → DOS save folder, Pool of Radiance only
  (`goldbox.dos.new_dos_save`, proven in DOSBox by `tools/dosnewsave.py`
  under `#26 (Write a DOS save, not just read one)`).

**This registry derives its DOS → C64 rows from `goldbox.dos.CONVERTS`
rather than listing them, which is the point:** a title joins `CONVERTS` when
its C64 writer exists, and it appears here with no edit to this module.
Secret of the Silver Blades is read but has no C64 writer yet
(`#193 (Convert a Secret of the Silver Blades DOS save into a C64 one, which
the importer refuses today)`), so a source detected as one is simply not in
`DIRECTIONS` and `destinations_for` answers `[]` -- never offered, and never
refused with a sentence either. `DOS_TO_C64_NAMES` below is the one thing
`CONVERTS` does not carry -- the `.D64` file name each title's conversion
writes -- and a `CONVERTS` entry missing a row there fails loudly when
`DIRECTIONS` is built, at import time, rather than answering `[]` for a title
the library can actually write.

**The source is a path, not the open window.** `Source.detect` reads a
`.D64` or a DOS save folder directly, the way `tools/dosdisk.py` and
`tools/dosnewsave.py` already do. When the path is the save the editor
already has open, the caller passes `party` and this reads its in-memory
bytes instead, so unsaved edits cross -- the same rule
`exports.Source.from_party` followed. `exports.Source` retires into this one
at step 5.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import tempfile
from typing import Any

from goldbox import dos, dos_layout, games

from . import dosimport


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
    whichever `Direction` converts it.
    """

    port: str                      # "c64" or "dos"
    title: Any
    path: pathlib.Path
    save0: bytes | None = None
    save1: bytes | None = None
    disk: bytes | None = None

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
            return cls._detect_c64_disk(path)
        raise ConvertError(
            f"{path} is neither a save disk nor a DOS save folder")

    @classmethod
    def _detect_dos_folder(cls, path: pathlib.Path) -> "Source":
        slots = _dos_slots(path)
        if not slots:
            raise ConvertError(f"{path} holds no DOS saved game")
        slot = slots[0]
        record = path / f"CHRDAT{slot}1.SAV"
        if not record.exists():
            raise ConvertError(
                f"{path} holds SAVGAM{slot} but no CHRDAT{slot}1.SAV to "
                f"read its shape from")
        try:
            shape = dos_layout.shape_for(record.stat().st_size)
        except dos_layout.DosShapeError as exc:
            raise ConvertError(str(exc)) from exc
        return cls(port="dos", title=shape, path=path)

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
