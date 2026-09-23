"""The registry of save conversions the library can build from nothing, and
the `File ▸ Convert…` dialog over it.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)` replaces the two flagged submenus -- `editor/dosimport.py`'s
`File ▸ Import` and `editor/exports.py`'s `File ▸ Export` -- with one
`File ▸ Convert…` dialog carrying a source row and a destination row. A
**direction** is registered here only when the destination can be written
whole, owing nothing to another save -- `.claude/rules/conversions.md`'s
rule against a template. Today that is:

* DOS save folder → C64, one row per entry of `C64_PAIRED`, which is
  `goldbox.dos_codec.CONVERTS` cut to the titles with a C64 port to convert to --
  Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver Blades
  (`goldbox.dos_codec.new_save`; Pool of Radiance proven in VICE by
  `#119 (Play a converted DOS save in VICE, off a disk Wish built from
  nothing)`, Curse of the Azure Bonds by `#192 (Convert a Curse of the Azure
  Bonds DOS save into a C64 one, which the importer refuses today)`, Secret
  of the Silver Blades by `docs/175-silver-blades-save-conversion.md`);
* C64 `.D64` → DOS save folder, one row per entry of the same `C64_PAIRED` --
  the same three titles (`goldbox.dos_codec.new_dos_save`; Pool of Radiance proven
  in DOSBox by `tools/dos/dosnewsave.py` under `#26 (Write a DOS save, not just
  read one)`, Curse of the Azure Bonds and Secret of the Silver Blades by
  `#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing
  can be converted to DOS for the later titles)`, whose container writer this
  registry was waiting on, and `#234 (A dual-classed Curse or Silver Blades
  character converted to DOS loses the class he trained out of)`, whose own
  dual-classed Curse character loaded from a save this direction writes);
* Amiga `.adf` → C64, one row per entry of `goldbox.amiga_shared.CONVERTS` --
  Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver Blades
  (`goldbox.amiga_savegame.read_por_slot` or `goldbox.amiga_savegame.read_slot`,
  then `goldbox.dos_codec.new_save_from`; Pool of Radiance proven in VICE by
  `#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
  standing in the Slums on the Amiga arrives there in VICE)`);
* Amiga `.adf` → DOS save folder, one row per entry of
  `goldbox.amiga_shared.CONVERTS` -- the same three titles
  (`goldbox.amiga_savegame.read_por_slot` or `goldbox.amiga_savegame.read_slot`,
  then `goldbox.dos_codec.new_dos_save_from`; Pool of Radiance proven in DOSBox by
  `#354 (Convert an Amiga Pool of Radiance save to DOS, so a party standing
  in the Slums on the Amiga arrives there under DOSBox)`);
* C64 `.D64` → Amiga save disk, and DOS save folder → Amiga save disk, one
  row each per entry of `goldbox.amiga_shared.WRITES` -- the same three titles
  (`goldbox.amiga_savegame.new_por_savegame` or
  `goldbox.amiga_savegame.new_savegame`, each building the whole
  `POOLSAVE.ADF` from the source save with no template; Pool of Radiance
  proven in two WinUAE runs by
  `#316 (Write the Amiga Pool of Radiance saved game from the source save,
  so a converted party arrives where it was standing)`). The disk this
  writes carries the party; the area's own script comes off the player's own
  Amiga disk 2 (`ecl.dax`, the `POOLDATA` volume), read and never written
  to;
* Amiga `.adf` → DOS save folder, Pools of Darkness only, one row --
  `PodAmigaToDos`, in `POD_DIRECTIONS` rather than `DIRECTIONS` because this
  title has no C64 port and cannot join `amiga_shared.CONVERTS`/`WRITES`
  (`goldbox.amiga_savegame.pod_from_amiga`/`pod_parse`,
  `goldbox.amiga_pod.pod_to_neutral`, then `goldbox.dos_codec.
  new_pod_save_from`). Offered only with `WISH_EXPERIMENTAL_POD_CONVERT`
  set, until its own proof in the running game and #650 (A played Amiga
  Pools of Darkness party converted to DOS loses a master thief's pick
  pockets over 127 and a scroll case's extra spells) and #651 (Convert a
  Pools of Darkness party's item vault between DOS and the Amiga along with
  its saved game) close (`#194 (Import and export a Pools of Darkness save
  between DOS and the Amiga)`).

**This registry derives every row from a library tuple rather than listing
them, which is the point:** DOS → C64 from `goldbox.dos_codec.CONVERTS`, C64 → DOS
from `goldbox.dos_codec.WRITES`, both Amiga rows from `goldbox.amiga_shared.CONVERTS`; a
title joins one of those tuples when its writer exists, and it appears here
with no edit to this module. `DOS_TO_C64_NAMES` below is the one thing
`CONVERTS` does not carry -- the `.D64` file name each title's DOS → C64
conversion writes -- and a `CONVERTS` entry missing a row there fails loudly
when `DIRECTIONS` is built, at import time, rather than answering `[]` for a
title the library can actually write. `WRITES` needs no such table: a C64 →
DOS conversion always writes the same file names (`SAVGAM<slot>.DAT`,
`CHRDAT<slot><n>.SAV`...), whatever the title, so `c64_port.by_key(shape.key)`
-- which already raises loudly on a key with no C64 game -- is the whole of
the check that direction needs.

**The source is a path, not the open window.** `Source.detect` reads a
`.D64`, an Amiga `.adf`, a `SAVGAM<slot>.DAT`/`.PTY` file, or a DOS save
folder directly, the way `tools/dos/dosdisk.py` and `tools/dos/dosnewsave.py`
already do. When the path is
the save the editor already has open, the caller passes `party` and
`editor.saveplan` assembles that save's own bytes with the pending edits in
them, on every port, so unsaved edits cross -- the same rule
`exports.Source.from_party` followed before that module was deleted.
`exports.Source` retired into this one at step 5. A DOS or an Amiga
snapshot rides on the `Source` as `files` or `image`, and `folder()` and
`amiga_disk()` are what a direction reads it through.

**`ConvertDialog`, below, is step B of `#52 (File ▸ Import and File ▸ Export for every direction the library supports)`'s plan comment** (also
`#52`'s comment of 2026-09-05 13:58:53): the source and destination rows, a
game-files row and a write-to-folder row carrying its own `Destination:`
line -- `editor/dosimport.py`'s rehearse-then-enable pattern, one dialog for
every registered direction rather than one dialog per port. The report pane
this paragraph used to name is gone (2026-09-10): what it showed is now a
modal `QMessageBox`, a silently disabled Convert button, or the debug log,
`_rehearse_and_report`'s own docstring has which goes where. **A modal fires
only for a real refusal** -- a source that cannot be read, a conversion that
cannot run -- **never for a row the player has simply not filled in yet**;
that used to pop on the very next field after `From`, before the player had
done anything wrong, and `ConvertDialog._SILENT_BLOCKS` is what stops it
(`#52`'s comment of 2026-09-10). **Four rows, in the
same places, in all six directions** since `#413 (The Convert window changes
shape depending on which platforms you are converting between)`: the
game-files row used to appear only for a DOS or an Amiga destination and
vanish for a Commodore 64 one, which moved the buttons under the pointer
every time the destination changed; it is always shown now, and only its
label, its displayed value and what `Choose…` opens follow the
destination. Every string not already approved elsewhere ends in the
literal ` (NOT APPROVED)`; see the block below it.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import logging
import os
import pathlib
import re
import tempfile
from collections.abc import Iterator, Mapping
from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QWidget,
)

from goldbox import (
    amiga_later,
    amiga_pod,
    amiga_por,
    amiga_savegame,
    amiga_shared,
    c64_port,
    dos_codec,
    dos_port,
    dos_savegame,
    neutral,
    world_state,
)

# By name rather than as a module: `amiga_port` and `amiga_por` differ by one
# letter, and only one of them belongs in the line above.
from goldbox.amiga_port import AmigaRecordError
from goldbox.iconparts import amiga_combat_icon

from . import dosimport, saveplan

_log = logging.getLogger("wish.editor.convert")


class ConvertError(Exception):
    """Anything a direction or `Source.detect` refuses, phrased for a
    player to read -- in a modal `QMessageBox` since 2026-09-10."""


def _same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    """Whether two paths name the same file, across relative and symlinked forms."""
    try:
        return a.resolve() == b.resolve()
    except OSError:            # a path that cannot be resolved is not a match
        return False


def _is_slot_file_of(party: Any, path: pathlib.Path) -> bool:
    """Whether `path` is the `SAVGAM<slot>` file of the party's own DOS folder
    and slot, which is the open save picked by its file rather than its
    folder."""
    match = _SAVGAM_FILE_RE.match(path.name)
    source = getattr(party, "source", None)
    slot = getattr(source, "slot", None)
    return (match is not None and slot is not None
            and match.group(1).upper() == slot.upper()
            and _same_file(pathlib.Path(party.path), path.parent))


def _asks_for_slot_of(party: Any, slot: str | None,
                      path: pathlib.Path) -> bool:
    """Whether a request for `slot` at `path` is for the slot the party has
    open.

    A picked `SAVGAM<slot>` file names its own slot, so `slot` does not apply
    to it; a party with no slot of its own (a C64 disk) has only one saved
    game to ask for.
    """
    open_slot = getattr(getattr(party, "source", None), "slot", None)
    return (slot is None or open_slot is None
            or bool(_SAVGAM_FILE_RE.match(path.name))
            or slot == open_slot)


# ---------------------------------------------------------------------------
# What is being converted
# ---------------------------------------------------------------------------

@dataclasses.dataclass

class Source:
    """One save, read off a path -- never off what a window happens to hold.

    `title` is a `goldbox.c64_port.Game` for a C64 source or a
    `goldbox.dos_port.DosDeltas` for a DOS or an Amiga one; both carry
    `.key`, which is what `Direction.source_key` matches against.
    `save0`/`save1`/`disk` are set only for a C64 source -- a DOS source is a
    folder and an Amiga source is an `.adf`, each read fresh by whichever
    `Direction` converts it. `slot` is the save slot the source was detected
    at -- the letter in `SAVGAM<slot>.DAT`/`.PTY`, or the Amiga slot letter
    in `savgam<slot>.dat`; it stays `None` for a C64 source, which has none.

    `available_slots` is every slot the source actually holds files for --
    `None` for a C64 source or a DOS save file, which already names exactly
    one slot through `_SAVGAM_FILE_RE`. A DOS save folder and an Amiga `.adf`
    can each hold several saved games, so this is what the editor's slot row
    (`#372 (An Amiga disk with more than one saved game converts its first
    slot, whichever one the player meant)`) is built from, and it is a list
    of one when either source holds only one saved game.

    `files` and `image` are a DOS or an Amiga saved game held in memory
    rather than read off `path` -- `editor.saveplan`'s snapshot of the open
    party, edits included. They are `None` for every source read off a path,
    and `folder()` and `amiga_disk()` below are how a direction reads either
    kind without knowing which it has.
    """

    port: str                      # "c64", "dos" or "amiga"
    title: Any
    path: pathlib.Path
    save0: bytes | None = None
    save1: bytes | None = None
    disk: bytes | None = None
    slot: str | None = None
    available_slots: list[str] | None = None
    files: dict[str, bytes] | None = None
    image: bytes | None = None

    @property
    def key(self) -> str:
        return self.title.key

    @classmethod
    def of_snapshot(cls, snapshot: saveplan.Snapshot) -> "Source":
        """The source a snapshot of the open party is."""
        return cls(port=snapshot.port, title=snapshot.title,
                   path=snapshot.path, save0=snapshot.save0,
                   save1=snapshot.save1, disk=snapshot.disk,
                   slot=snapshot.slot,
                   available_slots=snapshot.available_slots,
                   files=snapshot.files, image=snapshot.image)

    @contextlib.contextmanager
    def folder(self) -> Iterator[pathlib.Path]:
        """The DOS save folder to read this source out of.

        `path` for a source read off disk. A source holding a snapshot has no
        folder of its own, so its files are written into a temporary
        directory for as long as the block runs: `goldbox.dos_codec` reads a
        party out of a folder rather than out of bytes, and a scratch copy is
        what lets an unsaved edit reach it without the player's own save
        being touched.
        """
        if self.files is None:
            yield self.path
            return
        with tempfile.TemporaryDirectory(prefix="wish-source-") as scratch:
            scratch_path = pathlib.Path(scratch)
            for name, data in self.files.items():
                (scratch_path / name).write_bytes(data)
            yield scratch_path

    def amiga_disk(self) -> Any:
        """The Amiga disk to read this source out of.

        A snapshot's `image` is already a whole `.adf`, so unlike a DOS save
        it needs no scratch copy -- `AmigaDisk` works in memory and touches no
        file until it is saved.
        """
        from goldbox.amiga_adf import AmigaDisk

        if self.image is not None:
            return AmigaDisk(self.image)
        return AmigaDisk.open(str(self.path))

    @staticmethod
    def looks_like_a_save(path: str | pathlib.Path) -> bool:
        """Whether `path` is named like a DOS save folder, a
        `SAVGAM<slot>.DAT`/`.PTY` file or an Amiga `.adf`.

        Reads the name and whether it is a folder, never the contents, so a
        path that does not exist and is called `x.adf` still answers True and
        `detect` is what refuses it. Anything else is taken for a C64 disk
        image.
        """
        path = pathlib.Path(path)
        return (path.is_dir() or path.suffix.lower() == AMIGA_SUFFIX
                or bool(_SAVGAM_FILE_RE.match(path.name)))

    @classmethod
    def detect(cls, path: str | pathlib.Path, party: Any = None,
              slot: str | None = None) -> "Source":
        """A `.D64`, an Amiga `.adf`, a DOS save folder, or the party
        already open at `path`.

        `party` is a duck-typed `editor.roster.Party` -- `.path`, `.game`,
        `.save0`, `.save1`, `.disk`, and `.members` when it has a roster --
        and is used only when it is the save asked for, so unsaved edits on
        screen cross into the conversion instead of whatever is on disk. It
        is the save asked for when its own path is `path`, or when `path` is
        the `SAVGAM<slot>.DAT`/`.PTY` file of the party's own folder and
        slot, which is what the Convert window's picker hands over for a DOS
        save (`Party.path` is the folder). Every port takes this branch:
        `editor.saveplan.prepare` assembles the port's own bytes with the
        pending edits in them (`#511 (Open a DOS save folder and an Amiga
        save disk in the Character Editor, so editing a DOS character does
        not mean two conversions)`). A stand-in with no `.members` has no
        roster to read edits off, so a C64 one answers with the payload
        bytes it holds and another port's is read off the path.

        `slot` names which of a DOS folder's or an Amiga disk's several saved
        games to read -- the dialog's own slot row passes the letter the
        player chose. The editor holds edits for the slot it has open only,
        so a different `slot` is read off the path like any other source.
        Every other branch ignores it: a C64 disk holds one saved game and a
        DOS save file already names its own slot.
        """
        path = pathlib.Path(path)
        # Both sides resolved: a caller may hand us a relative path where
        # `Party.path` is absolute, or either may cross a symlink.  Comparing
        # them raw falls through to reading the file, which is the stale copy
        # this branch exists to avoid -- and it would do it silently.
        if (party is not None and party.path
                and _asks_for_slot_of(party, slot, path)
                and (_same_file(pathlib.Path(party.path), path)
                     or _is_slot_file_of(party, path))):
            snapshot = saveplan.prepare(party)
            if snapshot is not None:
                # A picked `SAVGAM<slot>` file leaves the snapshot on the
                # party's folder, which is what every DOS source's path is.
                at = path if _same_file(pathlib.Path(party.path), path) \
                    else snapshot.path
                return cls.of_snapshot(dataclasses.replace(snapshot, path=at))
            # No roster to read edits off: a C64 stand-in answers with the
            # payload it holds, and one reporting another port holds no bytes
            # of its own, so the save is read off the path.
            if getattr(party, "port", "c64") == "c64":
                if party.save0 is None:
                    raise ConvertError(f"{path} has no saved game open")
                return cls(port="c64", title=party.game, path=path,
                          save0=party.save0.to_bytes(),
                          save1=(party.save1.to_bytes()
                                 if party.save1 is not None else None),
                          disk=party.disk.to_bytes())
        if path.is_dir():
            return cls._detect_dos_folder(path, slot)
        if path.is_file():
            if not cls.looks_like_a_save(path):
                return cls._detect_c64_disk(path)
            match = _SAVGAM_FILE_RE.match(path.name)
            if match:
                return cls._detect_dos_file(path.parent, match.group(1).upper())
            return cls._detect_amiga_disk(path, slot)
        raise ConvertError(
            f"{path} is neither a save disk nor a DOS save folder")

    @classmethod
    def _detect_dos_folder(cls, path: pathlib.Path,
                           slot: str | None = None) -> "Source":
        slots = _dos_slots(path)
        if not slots:
            raise ConvertError(f"{path} holds no DOS saved game")
        chosen = slot if slot in slots else slots[0]
        return cls._detect_dos_file(path, chosen, available_slots=slots)

    @classmethod
    def _detect_dos_file(cls, folder: pathlib.Path, slot: str,
                         available_slots: list[str] | None = None) -> "Source":
        """The DOS shape at `folder`, for the save at `slot`.

        The one thing the two callers above disagree on is which slot: a
        bare folder (`tools/dos/dosdisk.py`, `tools/dos/dosnewsave.py`, and the
        Step 1 tests) takes the first complete slot `_dos_slots` finds, and a
        `SAVGAM<slot>.DAT`/`.PTY` file picked directly -- the dialog's own
        save picker -- names its own. Either way the title comes off
        `CHRDAT<slot>1.SAV`'s own size (`goldbox.dos_port.deltas_for`),
        never assumed.
        """
        record = folder / f"CHRDAT{slot}1.SAV"
        if not record.exists():
            raise ConvertError(
                f"{folder} holds SAVGAM{slot} but no CHRDAT{slot}1.SAV to "
                f"read its shape from")
        try:
            shape = dos_port.deltas_for(record.stat().st_size)
        except dos_port.DosDeltasError as exc:
            raise ConvertError(str(exc)) from exc
        return cls(port="dos", title=shape, path=folder, slot=slot,
                   available_slots=available_slots)

    @classmethod
    def _detect_amiga_disk(cls, path: pathlib.Path,
                           slot: str | None = None) -> "Source":
        """The Amiga disk at `path`, at `slot` -- or the first slot it holds
        files for, when the caller (or the dialog, before its slot row has
        anything to offer) names none.

        **Detected by its suffix rather than by trying both readers**, and
        the reason is what the other branch would say: an `.adf` handed to
        `goldbox.d64.D64.open` fails on its size, and the player would read
        a sentence about a C64 disk over a floppy that is plainly an Amiga
        one.

        `goldbox.amiga_savegame.por_slots_present` asks which slots have files rather
        than which the game's own picker offers, since a slot the picker
        lists and the disk has lost the files for is not one this can
        convert. Every slot it finds is kept as `available_slots`, which is
        what the dialog's slot row lists (`#372 (An Amiga disk with more
        than one saved game converts its first slot, whichever one the
        player meant)`) -- a DOS save file already names its own slot, while
        a folder and an `.adf` can each hold several saved games.
        A `slot` the disk does not actually hold files for is treated the
        same as none named, rather than raised on -- the combo below is
        always built from `available_slots`, so this can only happen when a
        caller other than the dialog hands in a stale letter.

        The title comes off the chosen slot's own character record length
        (`goldbox.amiga_shared.deltas_for`), never assumed -- so an Amiga
        Curse or Silver Blades disk is detected as itself and simply has no
        registered destination yet, rather than being read as a Pool of
        Radiance save it never was.
        """
        from goldbox.amiga_adf import AmigaDisk, AmigaDiskError

        try:
            disk = AmigaDisk.open(str(path))
            por_slots = amiga_savegame.por_slots_present(disk)
            later_slots = amiga_savegame.slots_present(disk)
            pod_slots = amiga_savegame.pod_slots_present(disk)
        except (AmigaDiskError, AmigaRecordError,
                amiga_savegame.AmigaSaveError, OSError) as exc:
            raise ConvertError(str(exc)) from exc
        slots = sorted(set(por_slots + later_slots + pod_slots))
        if not slots:
            raise ConvertError(f"{path} holds no Amiga saved game")
        chosen = slot if slot in slots else slots[0]
        try:
            if chosen in pod_slots:
                shape = dos_port.POOLS_OF_DARKNESS
            elif chosen in por_slots:
                record = disk.read_file(amiga_savegame.por_save_path(
                    amiga_por.por_filename(chosen, 1),
                    amiga_savegame.por_save_drawer(disk)))
                shape = amiga_shared.deltas_for(len(record))
            else:
                container = amiga_savegame.read_slot(disk, chosen).container
                if container.party != "records" or container.deltas is None:
                    raise ConvertError(f"slot {chosen} has no embedded party")
                shape = container.deltas.dos
        except (AmigaDiskError, AmigaRecordError,
                amiga_savegame.AmigaSaveError) as exc:
            raise ConvertError(str(exc)) from exc
        return cls(port="amiga", title=shape, path=path, slot=chosen,
                  available_slots=slots)

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

#: What an Amiga disk image is called. Lower case, and `Source.detect`
#: lower-cases what it compares, so a `.ADF` off a case-preserving volume is
#: the same disk.
AMIGA_SUFFIX = ".adf"


def _dos_slots(folder: pathlib.Path) -> list[str]:
    """Complete and readable slot letters, from either save-container suffix.

    `goldbox.dos_codec.slots_available` only globs `SAVGAM?.DAT`, which finds every
    title but Pools of Darkness -- its container is `SAVGAM?.PTY`
    (`goldbox/dos_savegame.py`'s `SAVE_POOLS_OF_DARKNESS`). Detecting a
    folder as DOS does not depend on which title it is, so both suffixes are
    looked for here.
    """
    slots = set()
    for pattern in ("SAVGAM?.DAT", "SAVGAM?.PTY"):
        slots.update(p.name[6] for p in folder.glob(pattern))
    return [slot for slot in sorted(slots)
            if _dos_slot_is_readable(folder, slot)]


def _dos_slot_is_readable(folder: pathlib.Path, slot: str) -> bool:
    """Whether a slot has a readable first character record of a known shape."""
    record = folder / f"CHRDAT{slot}1.SAV"
    try:
        with record.open("rb") as source:
            source.read(1)
        dos_port.deltas_for(record.stat().st_size)
    except (OSError, dos_port.DosDeltasError):
        return False
    return True


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

    `source_key` and `destination_game.key` are `goldbox.c64_port.Game.key` or
    `goldbox.dos_port.DosDeltas.key`, whichever port they name -- the two
    key spaces share the string `"pool-of-radiance"`, which is what lets
    `destinations_for` match a `Source` against a `Direction` without caring
    which module minted the key.
    """

    source_port: str
    source_key: str
    destination_port: str
    destination_game: Any

    def rehearse(self, source: Source, slot: str, options: Any,
                names: "Mapping[str, str] | None" = None) -> Rehearsal:
        raise NotImplementedError

    def write(self, rehearsal: Rehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        raise NotImplementedError


class UnnamedConversionError(Exception):
    """A `goldbox.dos_codec.CONVERTS` entry with no row in `DOS_TO_C64_NAMES`.

    Raised while `DIRECTIONS` is being built, at import time -- never while a
    player is looking at a pane. A title the library can write and this
    module cannot name a file for is a defect in `DOS_TO_C64_NAMES`, not a
    direction to answer `[]` for the way an unregistered title does.
    """


#: The `.D64` file name each DOS → C64 direction writes, keyed by
#: `goldbox.dos_port.DosDeltas.key`. The one thing `goldbox.dos_codec.CONVERTS`
#: does not carry, so it stays a table here rather than a property on the
#: shape itself, which knows nothing about C64 file names.
DOS_TO_C64_NAMES: dict[str, str] = {
    # The player's own disks are named this way (`PORSAVE2.D64`).
    dos_port.POOL_OF_RADIANCE.key: "PORSAVE{slot}.D64",
    # What `tools/curse_of_the_azure_bonds/cursedisk.py` writes.
    dos_port.CURSE_OF_THE_AZURE_BONDS.key: "CURSE{slot}.D64",
    # What `tools/secret_of_the_silver_blades/ssbdisk.py` writes.
    dos_port.SECRET_OF_THE_SILVER_BLADES.key: "SSB{slot}.D64",
}


class DosToC64(Direction):
    """A DOS save folder becomes a C64 `.d64`, for any title in
    `goldbox.dos_codec.CONVERTS` (#118, #119, #192).

    One instance per entry of `CONVERTS` -- see `DIRECTIONS` below -- so a
    title joining that tuple (`#193 (Convert a Secret of the Silver Blades
    DOS save into a C64 one, which the importer refuses today)` will put
    Secret of the Silver Blades there) needs no edit to this class.

    `rehearse` is `editor.dosimport.rehearse` exactly as `File ▸ Import`
    calls it today -- the whole conversion happens in memory and reads the
    title off the record itself (`goldbox.dos_port.deltas_for`), not off `shape`
    here, so `write` only has to put the bytes it already built on disk.
    `shape` decides only which source this instance answers for and what
    the output is named.
    """

    source_port = "dos"
    destination_port = "c64"

    def __init__(self, deltas: dos_port.DosDeltas):
        self.shape = deltas
        self.source_key = deltas.key
        self.destination_game = c64_port.by_key(deltas.key)
        try:
            self._name = DOS_TO_C64_NAMES[deltas.key]
        except KeyError:
            raise UnnamedConversionError(
                f"{deltas.title} is in goldbox.dos_codec.CONVERTS but "
                f"editor.convert.DOS_TO_C64_NAMES names no .D64 file for "
                f"it") from None

    def rehearse(self, source: Source, slot: str,
                options: "dosimport.GameFiles",
                names: "Mapping[str, str] | None" = None) -> Rehearsal:
        if names:
            # A DOS name is at most fifteen characters and the C64 field
            # holds eighteen (`goldbox.layout.NAME_SIZE`, #626), so this
            # direction never has a name to ask the player about.
            raise saveplan.SaveAsError(
                f"{self.source_port} to c64 never needs a chosen name")
        with source.folder() as folder:
            conversion = dosimport.rehearse(folder, slot, options)
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


class AmigaToC64(DosToC64):
    """An Amiga `.adf` becomes a C64 `.d64`, for any title in
    `goldbox.amiga_shared.CONVERTS` (#353).

    You save on the Amiga standing in the Slums at 21:22 with half the
    quests done, and the party arrives in the Slums at 21:22 with the same
    quests done. The six characters have crossed since 2026-08-26
    (`goldbox.amiga_por.to_neutral` then `goldbox.c64_codec.write`, 90 of 90
    sheet fields); what this adds is the game around them.

    **Everything but `rehearse` is `DosToC64`'s**, and deliberately: the
    destination is the same `.d64` written by the same engine
    (`goldbox.dos_codec.write_c64_save`) to the same file name, so `__init__`'s
    `DOS_TO_C64_NAMES` lookup and `write`'s put-the-bytes-down are one
    implementation rather than two that have to be kept saying the same
    thing. What differs is where the party and the place are read from, and
    that is this method.

    `options` is the same `dosimport.GameFiles` the DOS → C64 row takes --
    the combat icon tables and `ANIMATE00` off the player's own C64 disks,
    which no save of any port carries and which the destination needs.
    """

    source_port = "amiga"

    def rehearse(self, source: Source, slot: str,
                options: "dosimport.GameFiles",
                names: "Mapping[str, str] | None" = None) -> Rehearsal:
        disk = source.amiga_disk()
        if self.shape is dos_port.POOL_OF_RADIANCE:
            party, savgam = amiga_savegame.read_por_slot(disk, slot)
            state = amiga_savegame.read_por_state(
                savgam, source=f"{source.path} slot {slot}")
            # `read_por_slot` hands back `goldbox.dos_codec.DosCharacter`,
            # not a neutral party -- `fit_names` cannot run against it, and
            # a fifteen-character Pool of Radiance name never overflows the
            # C64's eighteen, so this direction never has one to ask about.
            if names:
                raise saveplan.SaveAsError(
                    f"{self.source_port} to c64 never needs a chosen name "
                    f"for {self.shape.key}")
            characters = party
            party_icons = None
        else:
            save = amiga_savegame.read_slot(disk, slot, self.shape.key)
            state = amiga_savegame.state_from_savegame(save)
            characters = [amiga_later.to_neutral_later(c)
                          for c in save.characters]
            party_icons = [amiga_combat_icon(c) for c in save.characters]
            # Cannot fire today: an Amiga name is at most fifteen
            # characters and the C64 field holds eighteen (#619's plan).
            # Called anyway, so a direction added later does not have to
            # remember to.
            characters = saveplan.fit_names(
                characters, self.destination_port, self.shape.key, names)
        if party_icons is None:
            save0, save1, report = dos_codec.new_save_from(
                state, characters, options.icon, options.animate,
                portraits=options.portraits, game=self.destination_game)
        else:
            save0, save1, report = dos_codec.new_save_from_neutral(
                state, characters, party_icons, options.icon, options.animate,
                game=self.destination_game)
        image = dos_codec.save_disk(bytes(save0), bytes(save1),
                              self.destination_game)
        name = self._name.format(slot=slot)
        return Rehearsal(report, {name: image.to_bytes()})


class C64ToDos(Direction):
    """A C64 save becomes a DOS save folder, for any title in
    `goldbox.dos_codec.WRITES` (#26, #299, #234).

    One instance per entry of `WRITES` -- see `DIRECTIONS` below -- so a
    title joining that tuple needs no edit to this class.  `goldbox.dos_codec.
    new_dos_save` is the no-template call for every title alike; `title=`
    is what tells it which one, since Curse of the Azure Bonds and Secret
    of the Silver Blades write the same 7424-byte C64 payload and only the
    title says which DOS container it becomes (`goldbox.dos_codec.c64_title`).
    `options` is the DOS game directory `ECL<n>.DAX` lives in -- mandatory,
    since a Curse party's own area script has to be staged or the game
    exits to DOS on load; Silver Blades stages none and Pool of Radiance's
    own area machinery is unchanged.

    `icon_parts` is `goldbox.dos_codec.new_dos_save`'s own argument -- the source
    title's own `SPELLE64`/`SPELLN64`, read into a `goldbox.iconparts.
    IconParts` -- which turns each character's own combat icon into a DOS
    figure (`#320 (A C64 party converted to DOS arrives with no combat
    figure at all, because the table only runs one way)`). `ConvertDialog`
    supplies it, off the *source*'s own title rather than the destination's
    (`#383 (The live Convert dialog never wires a C64 party's own combat
    icon into DOS, so region_220 stays on the drop list)`); left out, every
    figure is the game's own default, as before that ticket.
    """

    source_port = "c64"
    destination_port = "dos"

    def __init__(self, deltas: dos_port.DosDeltas):
        self.shape = deltas
        self.source_key = deltas.key
        self.destination_game = deltas
        # Raises `c64_port.UnknownGameError` at import time (via `DIRECTIONS`
        # below) if `WRITES` ever named a title with no C64 port -- the
        # loud failure `DOS_TO_C64_NAMES` gives the other direction, with no
        # table of its own needed: a C64 → DOS conversion writes the same
        # file names whatever the title.
        self.title = c64_port.by_key(deltas.key)

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                icon_parts: "Any | None" = None,
                names: "Mapping[str, str] | None" = None
                ) -> "AmigaDosRehearsal":
        game_dir = pathlib.Path(options)
        c64 = dos_codec.c64_title(source.save0, self.title)
        state = world_state.from_c64(source.save0, game=c64)
        characters, icons = dos_codec.c64_party(
            source.save0, source.save1, c64, icon_parts=icon_parts)
        characters = saveplan.fit_names(
            characters, self.destination_port, self.shape.key, names)
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos_codec.new_dos_save_from(
                state, characters, scratch_path, slot, game_dir, icons=icons)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return AmigaDosRehearsal(report, files, state, characters, icons,
                                 slot, game_dir)

    def write(self, rehearsal: "AmigaDosRehearsal",
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        dos_codec.new_dos_save_from(rehearsal.state, rehearsal.characters,
                              folder, rehearsal.slot, rehearsal.game_dir,
                              icons=rehearsal.icons)
        return sorted(folder / name for name in rehearsal.files)


@dataclasses.dataclass
class AmigaDosRehearsal(Rehearsal):
    """What `AmigaToDos.write` needs to run the conversion again.

    `DosWriteRehearsal`'s sibling, and for the same reason: `goldbox.dos_codec.
    new_dos_save_from` writes real files, so the rehearsal runs into a
    scratch directory and `write` runs it a second time into the folder the
    player chose.  What it carries is the place and the party rather than a
    C64 payload -- the `.adf` is read once, in `rehearse`, so a disk swapped
    or unplugged between the rehearsal and the Convert button cannot change
    what lands.
    """

    state: Any
    characters: list
    icons: list
    slot: str
    game_dir: pathlib.Path | None


class AmigaToDos(C64ToDos):
    """An Amiga `.adf` becomes a DOS save folder, for any title in
    `goldbox.amiga_shared.CONVERTS` (#354).

    You save on the Amiga standing in the Slums at 21:22 with half the
    quests done, and the party arrives in the Slums at 21:22 with the same
    quests done under DOSBox.  The six characters have crossed since
    2026-08-26; what this adds is the game around them -- the area, the
    party's own square, the facing, the clock and the 217 quest flags.

    **`__init__` is `C64ToDos`'s**, and deliberately, the way `AmigaToC64`
    takes `DosToC64`'s: the destination is the same DOS save folder written
    by the same engine to the same file names, so the shape lookup and the
    `c64_port.by_key` check that fails loudly at import time are one
    implementation rather than two.  What differs is where the party and
    the place are read from, which is `rehearse`, and that
    `goldbox.dos_codec.new_dos_save_from` takes them directly where
    `new_dos_save` reads them out of a C64 payload first.

    **Two slots, and they are not the same letter.**  `slot` is the DOS
    slot being written -- always `"A"` from the dialog, since a fresh DOS
    folder has no slot to inherit -- and `source.slot` is the Amiga slot
    being read.  Handing one where the other belongs converts whichever
    Amiga slot happens to share the DOS letter, which on a disk with two
    saved games is a different party.

    `options` is the DOS game directory `ECL<n>.DAX` lives in, exactly as
    the C64 → DOS row takes it; the dialog already shows that row for any
    DOS destination (`_settle_files_row`), so this needs nothing new there.
    """

    source_port = "amiga"

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                names: "Mapping[str, str] | None" = None
                ) -> AmigaDosRehearsal:
        if not source.slot:
            # Unreachable through `Source.detect`, whose `.adf` branch always
            # names the first slot the disk holds files for; only a caller
            # building a `Source` by hand can get here, and there is no Amiga
            # slot to guess at for it.
            raise ConvertError(f"{source.path} names no Amiga save slot")
        game_dir = pathlib.Path(options)
        disk = source.amiga_disk()
        if self.shape is dos_port.POOL_OF_RADIANCE:
            party, savgam = amiga_savegame.read_por_slot(disk, source.slot)
            state = amiga_savegame.read_por_state(
                savgam, source=f"{source.path} slot {source.slot}")
            characters = [dos_codec.to_neutral(c) for c in party]
        else:
            save = amiga_savegame.read_slot(disk, source.slot, self.shape.key)
            state = amiga_savegame.state_from_savegame(save)
            party = list(save.characters)
            characters = [amiga_later.to_neutral_later(c) for c in party]
        # Cannot fire today: an Amiga name is at most fifteen characters and
        # the DOS field holds the same fifteen. Called anyway, so a
        # direction added later does not have to remember to.
        characters = saveplan.fit_names(
            characters, self.destination_port, self.shape.key, names)
        # The Amiga file order **is** the DOS file order (`docs/165-amiga-
        # savegame.md`), so there is no reversal here; `goldbox.dos_codec.
        # marching_slot` and `c64_party`'s own `reverse()` are the C64's
        # business and `#101`'s.
        icons = [amiga_combat_icon(c) for c in party]
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos_codec.new_dos_save_from(state, characters, scratch_path,
                                           slot, game_dir, icons=icons)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return AmigaDosRehearsal(report, files, state, characters, icons,
                                 slot, game_dir)


class PodAmigaToDos(Direction):
    """An Amiga Pools of Darkness saved game becomes a DOS save folder.

    Its own class rather than a row `amiga_shared.CONVERTS`/`WRITES` feed:
    those two tuples build all four shared Amiga rows, including
    `AmigaToC64` and `C64ToAmiga`, and this title cannot join either of
    them -- it never shipped on the C64.  `AmigaToDos` inherits
    `C64ToDos.__init__`, which calls `c64_port.by_key` and would raise at
    import for a title with no C64 port, so this direction is not built on
    that pair; it goes straight through `dos_codec.new_pod_save_from`
    (`goldbox.amiga_savegame.pod_from_amiga`, `pod_parse`, `amiga_pod.
    pod_to_neutral`) instead of the shared `WorldState`/`new_dos_save_from`
    path the other three DOS destinations share.

    Registered only in `POD_DIRECTIONS`, behind `WISH_EXPERIMENTAL_
    POD_CONVERT` -- see the flag below for when that changes.
    """

    source_port = "amiga"
    destination_port = "dos"

    def __init__(self) -> None:
        self.shape = dos_port.POOLS_OF_DARKNESS
        self.destination_game = dos_port.POOLS_OF_DARKNESS
        self.source_key = self.shape.key

    def rehearse(self, source: Source, slot: str, options: Any,
                names: "Mapping[str, str] | None" = None
                ) -> AmigaDosRehearsal:
        if not source.slot:
            # Unreachable through `Source.detect`, whose `.adf` branch
            # always names the first slot the disk holds files for; only a
            # caller building a `Source` by hand can get here.
            raise ConvertError(f"{source.path} names no Amiga save slot")
        disk = source.amiga_disk()
        data = amiga_savegame.pod_read_slot(disk, source.slot)
        state = amiga_savegame.pod_from_amiga(
            data, source=f"{source.path} slot {source.slot}")
        characters = [amiga_pod.pod_to_neutral(block)
                     for block in amiga_savegame.pod_parse(data).blocks]
        characters = saveplan.fit_names(
            characters, self.destination_port, self.shape.key, names)
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos_codec.new_pod_save_from(
                state, characters, scratch_path, slot)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return AmigaDosRehearsal(report, files, state, characters, [],
                                 slot, None)

    def write(self, rehearsal: AmigaDosRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        dos_codec.new_pod_save_from(rehearsal.state, rehearsal.characters,
                                    folder, rehearsal.slot)
        return sorted(folder / name for name in rehearsal.files)


# ---------------------------------------------------------------------------
# C64 and DOS -> an Amiga save disk (#36, #316)
# ---------------------------------------------------------------------------
#
# `options` for either direction below is the path to the player's own Amiga
# Pool of Radiance disk 2 -- never disk 1, and never a folder -- because the
# one thing the writer cannot build from the source save is the area's own
# 7680-byte ECL script, which the Amiga keeps in a single `/ecl.dax` on the
# `POOLDATA` volume (`#316`). The disk named is read from and never written
# to: what this writes is a fresh `POOLSAVE.ADF`, formatted from nothing,
# inside the folder the player chose -- the save disk a player is actually
# handed, settled on `#36 (Write an Amiga disk image, not just the character
# files)`'s comment of 2026-09-07 over the other Amiga route (writing into a
# copy of the game disk's own `save` drawer), which nobody has asked for.

#: The one file either direction below writes. Uppercase, matching
#: `CONVERTED_AMIGA`'s own wording below and the volume the game itself asks
#: for at `LOAD SAVED GAME`'s `PATH FOR SAVE` prompt.
POOLSAVE_FILENAME = "POOLSAVE.ADF"

#: Where every Amiga Pool of Radiance area's own script lives -- one file,
#: on disk 2, the `POOLDATA` volume. `tools/amiga/toamigapor.py`'s own `ECL_DAX`,
#: repeated here because that module is a script this one must not import.
_ECL_DAX_PATH = "/ecl.dax"
_ECL_GLB_PATH = "/DISKB/ECL.GLB"


@dataclasses.dataclass
class AmigaWriteRehearsal(Rehearsal):
    """What either Amiga-destination direction needs to write again.

    Unlike `DosWriteRehearsal` and `AmigaDosRehearsal`, `write` does not run
    the conversion a second time: `goldbox.amiga_savegame.make_por_save_disk` writes
    into an in-memory `AmigaDisk` rather than onto a filesystem, so `files`
    already holds the exact bytes a second run would produce and `write`
    only has to put them down.
    """

    party: list
    state: Any
    slot: str
    savegame: bytes


def _rehearse_por_savegame(state: Any, slot: str, party: list,
                           ecl_dax: bytes,
                           icons: "list | None" = None) -> AmigaWriteRehearsal:
    """The tail both Amiga-destination directions share: build the saved
    game and the disk around it, and a report neither `write_por` nor
    `make_por_save_disk` return on their own.

    `report.dropped` is the union of each character's own reader-side drops
    -- a C64 record's combat-icon screen codes, a DOS record's field with no
    Amiga home -- and `goldbox.amiga_por.write_por`'s own drops for the same
    character, which is what `write_por`'s report already carries by way of
    `goldbox.dos_codec.write`'s own use of `neutral.Writer.finish` (`goldbox/neutral.py`).
    `report.warnings` gets the same, plus `PorSaveReport.converted` -- the
    place, the clock and the quest-flag count `tools/amiga/toamigapor.py` already
    prints -- so a player reading the pane sees where the party has arrived.
    `report.losses` is each character's own `write_por` losses, the same way
    (#619).

    `icons` is each character's own `goldbox.iconparts.DosIcon`, `None`
    where there is none, in the same order as `party` -- `write_por`'s own
    `icon` argument, threaded through per character (#422). Left out, every
    character's icon is `None` and every figure is written zero, exactly as
    before this parameter existed.
    """
    if icons is None:
        icons = [None] * len(party)
    # `"portrait_head" in c`, not `c.get("portrait_head")`: the field is set
    # to `0` for a character who really chose the menu's first head (HEAD00),
    # and a truthiness test reads that zero as "no portrait" -- the same
    # ambiguity `goldbox.c64_codec.read` had before #503 (A C64 character
    # with no sheet portrait arrives in DOS or on the Amiga wearing the
    # menu's first head), fixed there by leaving both fields unset for a
    # portrait-less character rather than by the value either one holds.
    portraits = any("portrait_head" in c for c in party)
    savegame, save_report = amiga_savegame.new_por_savegame(
        state, slot, len(party), ecl_dax, portraits=portraits)
    disk = amiga_savegame.make_por_save_disk(slot, party, savegame, icons=icons)
    problems = disk.verify()
    if problems:
        raise AmigaRecordError(
            "the disk this conversion built does not verify:\n  "
            + "\n  ".join(problems))

    report = neutral.Report()
    for char, icon in zip(party, icons):
        _, _, _, char_report = amiga_por.write_por(char, icon=icon)
        report.dropped.extend(char_report.dropped)
        report.warnings.extend(char_report.warnings)
        report.losses.extend(char_report.losses)
    report.warnings.extend(save_report.converted)

    return AmigaWriteRehearsal(
        report, {POOLSAVE_FILENAME: disk.to_bytes()}, party, state, slot,
        savegame)


def _rehearse_later_savegame(state: Any, shape: dos_port.DosDeltas,
                             slot: str, party: list,
                             ecl_glb: bytes | None,
                             icons: "list | None" = None,
                             ) -> AmigaWriteRehearsal:
    """Build a fresh Curse or Silver Blades saved game and disk."""
    savegame, report = amiga_savegame.new_savegame(
        state, party, slot, ecl_glb=ecl_glb, icons=icons)
    disk = amiga_savegame.make_save_disk(shape.key, slot, savegame)
    return AmigaWriteRehearsal(
        report, {POOLSAVE_FILENAME: disk.to_bytes()}, party, state, slot,
        savegame)


def amiga_needs_game_disk(shape: dos_port.DosDeltas,
                          source: "Source | None" = None) -> bool:
    """Whether an Amiga destination of this title reads anything off the
    player's own disk 2.

    Pool of Radiance stages the area's own `ecl.dax` and Curse of the Azure
    Bonds its `ECL.GLB`; Secret of the Silver Blades stages neither and needs
    no disk at all. A Curse party from a C64 or DOS `source` that has not set out
    stages no script either. `editor.saveplan.requirements` asks this rather
    than demanding a disk for every Amiga destination alike.
    """
    if shape is dos_port.SECRET_OF_THE_SILVER_BLADES:
        return False
    if (shape is dos_port.CURSE_OF_THE_AZURE_BONDS
            and source is not None and source.port == "c64"
            and source.save0 is not None):
        state = world_state.from_c64(
            source.save0, game=c64_port.by_key(shape.key),
            source=str(source.path))
        return not world_state.has_not_set_out(state)
    if (shape is dos_port.CURSE_OF_THE_AZURE_BONDS
            and source is not None and source.port == "dos"
            and source.slot):
        container = dos_savegame.container_for(shape.key)
        with source.folder() as folder:
            savgam = (pathlib.Path(folder)
                      / f"SAVGAM{source.slot}{container.suffix}").read_bytes()
        state = world_state.from_dos(savgam, container,
                                     source=str(source.path))
        return not world_state.has_not_set_out(state)
    return True


def dos_needs_game_folder(shape: dos_port.DosDeltas) -> bool:
    """Whether a DOS destination of this title reads anything off the
    player's own game folder.

    Every other DOS destination stages the party's own area script out of
    `ECL<n>.DAX`, which is the game's own file; Pools of Darkness stages no
    script (`goldbox.dos_codec.new_pod_save_from` reads nothing off disk)
    and so needs no game folder at all -- the same per-title question
    `amiga_needs_game_disk` answers for an Amiga destination.
    """
    return shape is not dos_port.POOLS_OF_DARKNESS


def _amiga_destination_data(shape: dos_port.DosDeltas,
                            options: "str | pathlib.Path",
                            source: "Source | None" = None) -> bytes | None:
    """The one game-data file a fresh save needs, when it needs one."""
    if not amiga_needs_game_disk(shape, source):
        return None
    from goldbox.amiga_adf import AmigaDisk

    path = (_ECL_DAX_PATH if shape is dos_port.POOL_OF_RADIANCE
            else _ECL_GLB_PATH)
    return AmigaDisk.open(str(options)).read_file(path)


def _rehearse_amiga_savegame(state: Any, shape: dos_port.DosDeltas,
                             slot: str, party: list,
                             game_data: bytes | None,
                             icons: "list | None" = None,
                             ) -> AmigaWriteRehearsal:
    if shape is dos_port.POOL_OF_RADIANCE:
        if game_data is None:
            raise AmigaRecordError("Amiga Pool of Radiance needs ecl.dax")
        return _rehearse_por_savegame(
            state, slot, party, game_data, icons=icons)
    return _rehearse_later_savegame(
        state, shape, slot, party, game_data, icons=icons)


class C64ToAmiga(Direction):
    """A C64 save becomes an Amiga save disk, for any title in
    `goldbox.amiga_shared.WRITES` (#316, #36).

    One instance per entry of `WRITES` -- see `DIRECTIONS` below -- so a
    title joining that tuple needs no edit to this class. `options` is the
    path to the player's own Amiga disk 2, never disk 1.

    A C64 source has no slot of its own, so the built saved game is always
    slot `A` -- the same rule `C64ToDos.rehearse` follows for a fresh DOS
    folder.

    `icon_parts` is `goldbox.dos_codec.c64_party`'s own argument -- the source
    title's own `SPELLE64`/`SPELLN64`, read into a `goldbox.iconparts.
    IconParts` -- which turns each character's own C64 combat icon into an
    Amiga figure, mirroring `C64ToDos`'s own parameter (#422 (A C64 party
    converted to an Amiga save disk arrives with no combat figure at all,
    because C64ToAmiga never recognises it), the same shape #383 gave the
    DOS destination). `ConvertDialog` supplies it, off the *source*'s own
    title; left out, every figure is the game's own default, as before that
    ticket.
    """

    source_port = "c64"
    destination_port = "amiga"

    def __init__(self, deltas: dos_port.DosDeltas):
        self.shape = deltas
        self.source_key = deltas.key
        self.destination_game = deltas
        # The C64 title `dos_codec.c64_party` reads the source disk against --
        # `c64_port.by_key` raises loudly at import time if `WRITES` ever named
        # a title with no C64 port, the same guard `C64ToDos.__init__` keeps.
        self.title = c64_port.by_key(deltas.key)

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                icon_parts: "Any | None" = None,
                names: "Mapping[str, str] | None" = None) -> AmigaWriteRehearsal:
        game_data = _amiga_destination_data(self.shape, options, source)
        party, icons = dos_codec.c64_party(source.save0, source.save1,
                                     game=self.title, icon_parts=icon_parts)
        party = saveplan.fit_names(
            party, self.destination_port, self.shape.key, names)
        state = world_state.from_c64(
            source.save0, game=self.title, source=str(source.path))
        return _rehearse_amiga_savegame(
            state, self.shape, "A", party, game_data, icons=icons)

    def write(self, rehearsal: AmigaWriteRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / POOLSAVE_FILENAME
        path.write_bytes(rehearsal.files[POOLSAVE_FILENAME])
        return [path]


class DosToAmiga(Direction):
    """A DOS save becomes an Amiga save disk, for any title in
    `goldbox.amiga_shared.WRITES` (#316, #36).

    One instance per entry of `WRITES` -- see `DIRECTIONS` below. `options`
    is the path to the player's own Amiga disk 2, exactly as `C64ToAmiga`
    takes it.

    **The built saved game keeps the source's own slot letter**, not the
    fixed `A` a C64 source gets -- `#316`'s comment of 2026-09-07:
    *"A for a C64 source, which has no slot; the source's own letter for a
    DOS `SAVGAM<slot>.DAT`, the letter `CONVERTED_DOS` already reports."*
    So the `slot` this class's own `rehearse` is handed (always `"A"`, the
    dialog's fixed DOS-destination default -- there is no DOS destination
    here, so nothing reads it) is not what is written; `source.slot` is.
    """

    source_port = "dos"
    destination_port = "amiga"

    def __init__(self, deltas: dos_port.DosDeltas):
        self.shape = deltas
        self.source_key = deltas.key
        self.destination_game = deltas

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                names: "Mapping[str, str] | None" = None) -> AmigaWriteRehearsal:
        if not source.slot:
            # Unreachable through `Source.detect`, whose DOS branches always
            # name a slot; only a caller building a `Source` by hand can get
            # here, mirroring `AmigaToDos.rehearse`'s own guard.
            raise ConvertError(f"{source.path} names no DOS save slot")
        letter = source.slot
        game_data = _amiga_destination_data(self.shape, options, source)
        with source.folder() as folder:
            raw_party = dos_codec.read_party(folder, letter)
            container = dos_savegame.container_for(self.shape.key)
            savgam_path = pathlib.Path(folder) / (
                f"SAVGAM{letter}{container.suffix}")
            savgam = savgam_path.read_bytes()
        party = [dos_codec.to_neutral(c) for c in raw_party]
        # Cannot fire today: a DOS name is at most fifteen characters and an
        # Amiga field holds the same fifteen (`amiga_por._por_name_bytes`).
        # Called anyway, so a direction added later does not have to
        # remember to.
        party = saveplan.fit_names(
            party, self.destination_port, self.shape.key, names)
        # `amiga_combat_icon` is duck-typed to `goldbox.dos_codec.DosCharacter`
        # too (its own docstring) and reads the icon straight off the raw
        # record, before `dos_codec.to_neutral` discards it -- the same shape
        # `AmigaToDos.rehearse` already uses for an Amiga source (#424,
        # mirroring #422's fix for a C64 source).
        icons = [amiga_combat_icon(c) for c in raw_party]
        # Named for the player's own save rather than for the scratch copy a
        # snapshot is read through: the name only ever labels the state.
        state = world_state.from_dos(
            savgam, container,
            source=str(pathlib.Path(source.path) / savgam_path.name))
        return _rehearse_amiga_savegame(
            state, self.shape, letter, party, game_data, icons=icons)

    def write(self, rehearsal: AmigaWriteRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / POOLSAVE_FILENAME
        path.write_bytes(rehearsal.files[POOLSAVE_FILENAME])
        return [path]


#: One DOS → C64 row and one C64 → DOS row per entry of `C64_PAIRED` below
#: -- today Pool of Radiance, Curse of the Azure Bonds and Secret of the
#: Silver Blades, both ways -- one
#: Amiga → C64 row and one Amiga → DOS row per entry of
#: `goldbox.amiga_shared.CONVERTS`, and one C64 → Amiga row and one DOS → Amiga row
#: per entry of `goldbox.amiga_shared.WRITES` -- Pool of Radiance, Curse of
#: the Azure Bonds and Secret of the Silver Blades for every Amiga tuple.
#: `UnnamedConversionError` fires here, at import time, if `CONVERTS` ever
#: names a title `DOS_TO_C64_NAMES` does not; `c64_port.UnknownGameError` does
#: the same for `WRITES` and a title with no C64 game at all.
#: The DOS shapes with a C64 port on the other side.
#:
#: **`goldbox.dos_codec.CONVERTS` stopped being that list on 2026-09-08**, when
#: Pools of Darkness joined it (`#194 (Import and export a Pools of Darkness
#: save between DOS and the Amiga)`).  That tuple says which DOS records
#: `goldbox.dos_codec.to_neutral` will read, and its newest entry is there for its
#: **Amiga** pairing: the title never shipped on the C64, so a DOS-to-C64 row
#: has no destination and a C64-to-DOS row has no source.
#:
#: The test is **"does this title have a C64 port", not "is this a title we
#: know"** -- `#470 (Give the project a neutral title beside its neutral
#: character record, with one port per platform a title shipped on)`'s own
#: model, a port being optional and absent being normal.  `c64_port.BY_KEY` is
#: that answer: it is the six C64 titles' own registry and stays that way
#: through `#470`'s stage 2, so it is the test here too, and it is the same
#: one `DosToC64.__init__` makes one line further down -- kept here so a
#: title with no C64 game at all is *left out* rather than raising at import
#: time.  The alarm the comment above describes is unchanged for every title
#: that does have one: a shape `games` knows and `DOS_TO_C64_NAMES` does not
#: still raises `UnnamedConversionError`.
#:
#: **Do not swap this for `goldbox.titles.BY_KEY`.** Every other table this
#: stage touches reads through `titles` instead of `games`, because a title's
#: races and classes are the same fact on every port; whether a title *has*
#: a C64 port is not that kind of fact, and `titles.BY_KEY` knows Pools of
#: Darkness, which has none.  That swap is exactly what broke the editor on
#: import once already, the other way round, when `dos_codec.CONVERTS` gained the
#: title before this guard existed (`#194`'s comment of 2026-09-08).
C64_PAIRED: tuple[dos_port.DosDeltas, ...] = tuple(
    shape for shape in dos_codec.CONVERTS if shape.key in c64_port.BY_KEY)

DIRECTIONS: tuple[Direction, ...] = tuple(
    DosToC64(shape) for shape in C64_PAIRED
) + tuple(
    C64ToDos(shape) for shape in C64_PAIRED
) + tuple(
    AmigaToC64(shape) for shape in amiga_shared.CONVERTS
) + tuple(
    AmigaToDos(shape) for shape in amiga_shared.CONVERTS
) + tuple(
    C64ToAmiga(shape) for shape in amiga_shared.WRITES
) + tuple(
    DosToAmiga(shape) for shape in amiga_shared.WRITES
)

#: Pools of Darkness directions, kept out of `DIRECTIONS` because the title
#: has no C64 port and cannot join `amiga_shared.CONVERTS`/`WRITES` --
#: `#194 (Import and export a Pools of Darkness save between DOS and the
#: Amiga)`'s 2026-09-23 plan comment, "the one design point". Offered only
#: with `WISH_EXPERIMENTAL_POD_CONVERT` set, and each row comes off this
#: tuple on its own proof: `PodAmigaToDos` moves into `DIRECTIONS` when its
#: piece-2 proof has passed in its own running game and #650 (A played
#: Amiga Pools of Darkness party converted to DOS loses a master thief's
#: pick pockets over 127 and a scroll case's extra spells) and #651
#: (Convert a Pools of Darkness party's item vault between DOS and the
#: Amiga along with its saved game) are closed. The flag and this tuple are
#: deleted once the tuple is empty.
POD_DIRECTIONS: tuple[Direction, ...] = (PodAmigaToDos(),)

#: The environment variable that gates `POD_DIRECTIONS`. `WISH_EXPERIMENTAL_`
#: rather than `WISH_DEBUG`/`WISH_NATIVE_LOG`'s prefix, because this one is
#: meant to be deleted and those two are permanent (`.claude/rules/
#: feature-flags.md`).
POD_CONVERT_ENV = "WISH_EXPERIMENTAL_POD_CONVERT"


def pod_convert_enabled() -> bool:
    """Whether `POD_DIRECTIONS` is offered.

    The same truthy set `wish.debugmode.TRUE` uses, copied rather than
    imported: `editor/` does not import `wish/`.
    """
    return os.environ.get(POD_CONVERT_ENV, "").strip().lower() in (
        "1", "true", "yes", "on")


def destinations_for(source: Source) -> list[Direction]:
    """Every registered direction this source can be converted to.

    Empty for anything not in `DIRECTIONS` and, unless
    `WISH_EXPERIMENTAL_POD_CONVERT` is set, `POD_DIRECTIONS`.  An unready
    direction is never offered and never refused.
    """
    directions = DIRECTIONS + (POD_DIRECTIONS if pod_convert_enabled() else ())
    return [d for d in directions
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
# The flag, lifted
# ---------------------------------------------------------------------------

#: **`WISH_EXPERIMENTAL_CONVERT` no longer exists.** `File ▸ Convert…` is
#: built for everyone, unconditionally, since 2026-09-14. Donald lifted it
#: directly: *"Lift WISH_EXPERIMENTAL_CONVERT, remove File ▸ Import, close
#: #52."* All nine conditions the flag once named were met -- the evidence
#: is `#52 (File ▸ Import and File ▸ Export for every direction the library
#: supports)`'s own comment history and the byte-level manifest at
#: `2ae11ba` -- and `File ▸ Import ▸ DOS Save Folder…` was removed in the
#: same commit that lifted this flag, because condition 7 required exactly
#: that: this dialog was the only import route a player had, so the two
#: could not land apart. `editor.dosimport.ENV`
#: (`WISH_EXPERIMENTAL_DOS_IMPORT`) went the same way earlier, `#131 (Lift
#: WISH_EXPERIMENTAL_DOS_IMPORT, which needs the import working for all
#: three C64 titles)`, 2026-09-06.

# ---------------------------------------------------------------------------
# Strings.
#
# Reused ones carry the approval they already have, verbatim, and keep the
# name they were approved under so a reviewer can find the ruling. Every
# other one ends in the literal ` (NOT APPROVED)` until Donald rules
# (`.claude/rules/gui-text.md`) -- never invent a sentence beyond this block.
# ---------------------------------------------------------------------------

#: The File menu entry. Approved by Donald 2026-09-05, with every other
#: string in this block: *"I think these are all fine."*  The two submenus
#: it replaced, `&Import` and `&Export`, are both gone now -- this dialog
#: was neither.
MENU_CONVERT = "&Convert…"

#: The dialog's title bar. Approved 2026-09-05.
DIALOG_TITLE = "Convert a save"

#: Row labels. `LABEL_GAME` is `editor/exports.py`'s, approved 2026-08-25;
#: `LABEL_FOLDER` is its `LABEL_DESTINATION`, approved the same day -- the
#: row where the player says which folder the write goes inside, renamed
#: here so it is not confused with `convert_destination`'s new combo.
#: **`From`, not `Save`, since 2026-09-07.** It read `Save` from the
#: dialog's first day and Donald changed it on seeing the form drawn:
#: `To` below it had no partner, so the row above read as a noun where
#: a person expected the other half of a pair, and `Save` competes with
#: `File > Save` for the same word. Approved by him on 2026-09-05 in its
#: old form and re-ruled here, so it carries no marker.
LABEL_SOURCE = "From"
LABEL_TO = "To"
LABEL_GAME = "DOS game folder"
#: The game-files row's label for an Amiga destination. Ruled on
#: `#316 (Write the Amiga Pool of Radiance saved game from the source save,
#: so a converted party arrives where it was standing)` on 2026-09-07, over
#: `Amiga disk 2` and `Amiga data disk`, because it is unambiguous the
#: player is being asked for one of his own original game disks rather than
#: anything Wish produced. Not `#36 (Write an Amiga disk image, not just the
#: character files)`'s own -- `#316` settled it first and this one follows.
#: Re-confirmed rather than reopened on `#413`'s comment of 2026-09-09.
LABEL_DISK = "Amiga game disk 2"
#: The game-files row's label for a Commodore 64 destination. Approved
#: 2026-09-09 on `#413 (The Convert window changes shape depending on which
#: platforms you are converting between)`, alongside a real, editable
#: picker replacing the three drawn alternatives (a blank row, a line of
#: read-only text, and a `Preferences…` button) that a C64 destination used
#: to need nothing shown at all -- Donald: *"How about you include a file
#: input, but autofill it with whatever is in the preferences."* It borrows
#: Preferences' own noun (`Game disks not found`) rather than inventing a
#: fourth word for the same thing, matching `LABEL_GAME` and `LABEL_DISK`'s
#: own pattern of naming the platform and what it keeps: a folder, one
#: particular disk, a set of disks. A single shared label (`Your game
#: files`) was also put to him and rejected, because it would stop telling
#: an Amiga player they need disk 2 specifically.
LABEL_C64 = "C64 game disks"
LABEL_FOLDER = "Write to"

#: **Removed 2026-09-10.** The heading was Donald's own words, 2026-09-07,
#: from reviewing the Amiga-row mock-up for `#316 (Write the Amiga Pool of
#: Radiance saved game from the source save, so a converted party arrives
#: where it was standing)`: *"It gains a label above it reading `Convert
#: Log`."* He then found it still on screen and asked for it gone: *"In the
#: Convert Window, I still see the Convert Log. I specifically asked for
#: that to be removed."* The pane it headed carries no label any more --
#: `dosimport.pane_text`'s own messages and capacity losses (`#416`) and
#: this dialog's own error text still show inside it, unlabeled; the
#: destination path that used to live under a `This writes:` line inside it
#: is `DESTINATION_PREFIX` below, on its own line under `Write to`.

#: One combo item per slot `Source.available_slots` lists, `{slot}` the
#: letter `read_por_slot` takes. **No separate label any more** -- the combo
#: sits on the `From` row now (`#413`'s comment of 2026-09-09, "the `Slot`
#: combo rides on the `From` row, not in the third-row position"), after
#: `Choose…`, and each item already names itself. The row it used to have of
#: its own is what this dropped: `LABEL_SLOT`, unused since.
SLOT_ITEM = "Slot {slot}"

#: Buttons. `BUTTON_CHOOSE` is `editor/exports.py`'s word, approved
#: 2026-08-25; `BUTTON_CONVERT` is `editor/dosimport.py`'s, approved
#: 2026-08-24.
BUTTON_CHOOSE = "Choose…"
BUTTON_CONVERT = "Convert"

#: Picker titles. `GAME_TITLE` and `FOLDER_TITLE` are `editor/exports.py`'s
#: `GAME_TITLE` and `DESTINATION_TITLE`, approved 2026-08-25.
SOURCE_TITLE = "Choose a save"
GAME_TITLE = "Choose the DOS game folder"
#: The Amiga disk row's own picker title, ruled the same night as
#: `LABEL_DISK` and following its own wording.
DISK_TITLE = "Choose Amiga game disk 2"
FOLDER_TITLE = "Choose where to write"

#: The save picker's filter: a `.d64` or the DOS save container itself, so
#: picking `SAVGAMB.DAT` picks slot B with no separate slot row. PROPOSED --
#: only the descriptive label is new; `;;All files (*)` is
#: `editor/window.py`'s `DISK_FILTER` boilerplate, reused rather than
#: reworded.  Approved 2026-09-05.
#:
#: **`*.adf` is in it**, approved by Donald on 2026-09-07 -- *"Yes, the file
#: picker should allow .adf files."*  Before that an Amiga disk was reachable
#: only through the `All files (*)` entry, which works and gives a player no
#: reason to think an Amiga save is something Wish takes.  It was left out
#: rather than shipped unapproved because marking a glob ` (NOT APPROVED)`
#: the way an unshipped sentence is marked would have put those two words in
#: the picker's own dropdown (`.claude/rules/gui-text.md`, and `#353 (Convert
#: an Amiga Pool of Radiance save to the C64, so a party standing in the
#: Slums on the Amiga arrives there in VICE)`).
SOURCE_FILTER = ("Saved games "
                 "(*.d64 *.D64 *.adf *.ADF SAVGAM?.DAT SAVGAM?.PTY);;"
                 "All files (*)")

#: The Amiga disk row's own picker filter. Approved 2026-09-07, unchanged
#: from the proposal on `#36 (Write an Amiga disk image, not just the
#: character files)`'s comment.
DISK_FILTER = "Amiga disks (*.adf *.ADF);;All files (*)"

#: The destination combo's items, by port -- never by title, since
#: `destinations_for` never offers two directions of the same port for one
#: source (`.claude/rules/conversions.md`: a conversion never crosses a
#: title). Approved 2026-09-05; `"amiga"` approved 2026-09-07 on `#316`'s
#: mock-up, once `goldbox.amiga_shared.WRITES` gave it something to build
#: (`#36`'s comment of 2026-09-07).
DESTINATION_LABELS: dict[str, str] = {
    "c64": "Commodore 64",
    "dos": "DOS",
    "amiga": "Amiga",
}

#: **Never shown to the player** -- `_settle_button` already leaves Convert
#: disabled for as long as this row is empty, and popping a modal on top of
#: a form a player has not finished filling in told them they had made a
#: mistake that was actually inevitable (`#52`'s comment of 2026-09-10:
#: Donald hit this the first time he opened the dialog, on the very next
#: field, before he had done anything wrong). Kept as a string and recorded
#: on `self._blocked` -- `_maybe_warn` reads that set to decide what still
#: needs a modal -- so the reason is still there to test and to log, it is
#: only the popup that is gone.
NO_GAME_FOLDER = "Choose the DOS game folder."
#: The Amiga disk row's own empty-state line, ruled the same night as
#: `LABEL_DISK` and following its own wording. Silent for the same reason
#: as `NO_GAME_FOLDER` above.
NO_DISK = "Choose Amiga game disk 2."
#: `editor/exports.py`'s `NO_DESTINATION`, approved 2026-08-25. The first of
#: these a player would actually reach -- `Write to` is the very next field
#: after `From` -- and so the one Donald caught: a modal here fired before
#: he had touched anything past the source row. Silent since `#52`'s fix of
#: 2026-09-10, for the same reason as `NO_GAME_FOLDER` above.
NO_FOLDER = "Choose where to write."
#: `goldbox.dos_codec.CANNOT_CONVERT`, approved under `#195 (The import pane shows
#: a player a memory address when the conversion refuses for any reason but
#: the wrong title)` on 2026-09-02. It names a source Wish cannot read, or a
#: rehearsal failure that has no `dos_codec.DosRecordError.player_message`.
CANNOT_CONVERT = dos_codec.CANNOT_CONVERT
#: Donald's approved wording for a readable Pools of Darkness save: it has no
#: C64 port, so `destinations_for` correctly answers no direction.
POOLS_OF_DARKNESS_UNSUPPORTED = "Pools of Darkness saves are not yet supported."
#: `editor/dosimport.py`'s `NO_DISKS`/`NO_DISKS_TITLE`. The title is Donald's
#: of 2026-08-27; the line is his of 2026-09-05, rewritten when
#: `#342 (A Curse or Silver Blades save cannot be converted unless its C64
#: sides sit in the Pool of Radiance disk folder)` gave each title its own
#: folder and the old wording named `File ▸ Import` and one shared folder.
#: **Reused for a missing source's disks too, since #482**
#: (`#482 (With no game disks for the source title, a C64 party converted to
#: DOS or the Amiga silently arrives with no combat figures, though a C64
#: destination refuses)`): it names no direction, so the same sentence fits
#: whichever side of the conversion could not be read.
#:
#: **Silent inside `ConvertDialog`, since `#52`'s fix of 2026-09-10** -- a
#: missing set of game disks is a field the dialog itself cannot fill in for
#: the player, the same shape as `NO_FOLDER` and the other rows above, so a
#: modal added nothing a disabled Convert button did not already say.
#: `editor/window.py`'s own direct use of it, refusing `File ▸ Import`
#: outright before its dialog even opened, is gone along with that menu
#: entry, `#52 (File ▸ Import and File ▸ Export for every direction the
#: library supports)`, 2026-09-14.
NO_DISKS = dosimport.NO_DISKS
NO_DISKS_TITLE = dosimport.NO_DISKS_TITLE

#: Which of the refusals above each requirement of
#: `editor.saveplan.requirements` is, so the service names what is missing
#: and this module keeps the wording a player reads.
MISSING_ASSET_BLOCKS: dict[str, tuple[str, str]] = {
    saveplan.DESTINATION_DISKS: (NO_DISKS_TITLE, NO_DISKS),
    saveplan.SOURCE_DISKS: (NO_DISKS_TITLE, NO_DISKS),
    saveplan.DOS_GAME_FOLDER: (DIALOG_TITLE, NO_GAME_FOLDER),
    saveplan.AMIGA_GAME_DISK: (DIALOG_TITLE, NO_DISK),
}
#: Donald's own wording, `09027bb` (2026-09-05) -- shared with
#: `editor/dosimport.py`'s and `editor/exports.py`'s `DROPPED_HEADING`, one
#: conversion vocabulary whichever way it is going. **Not drawn by this
#: dialog's own pane** -- `#416` first moved it onto `dosimport.pane_text`
#: with no heading of its own, and 2026-09-08's ruling took the drop lines
#: out of `pane_text` altogether (`.claude/rules/conversions.md`), so there
#: is no longer a list here for a heading to sit over. Kept defined for
#: whichever caller still names it.
DROPPED_HEADING = dosimport.DROPPED_HEADING
#: The destination line under `Write to`, replacing the `This writes:`
#: heading that used to sit inside the report pane
#: (`editor/exports.py`'s own `WRITES_HEADING`, approved 2026-08-25, was the
#: shape it copied). Donald's own wording, 2026-09-10, asking for the report
#: pane's heading gone and the path moved: *"Make it say `Destination:
#: /tmp/wish-2026-09-10/wish-2026-09-10/PORSAVEA.D64`."* Names the folder
#: alone as of the same day's second ruling -- a C64 → DOS write can name a
#: dozen files, and joining them onto this one line was what forced the
#: dialog to 6688px wide; the pane itself is gone too, so there is nothing
#: left of it for this line to sit "inside" any more.
DESTINATION_PREFIX = "Destination: "

#: The status line after a DOS write, which nothing else in the window
#: reports (a C64 write is opened in the editor and gets its own status the
#: way `File ▸ Open` does). Approved 2026-09-05.
CONVERTED_DOS = "Converted to DOS slot {slot} in {folder}"

#: The status line after an Amiga write. Ruled on `#316 (Write the Amiga
#: Pool of Radiance saved game from the source save, so a converted party
#: arrives where it was standing)` on 2026-09-07, over the `CONVERTED_DOS`
#: shape, because it names the two facts needed to actually play the
#: result: the file to mount and the letter to type at the Amiga's own
#: `LOAD WHICH GAME:` prompt. `{slot}` is a substitution -- a DOS-sourced
#: conversion keeps its own source letter (`DosToAmiga`), and a C64-sourced
#: one is always `A` (`C64ToAmiga`), the same rule `CONVERTED_DOS` follows.
#: Not wired into `EditorBinding.convert` yet -- that is `editor/window.py`,
#: which is another agent's file tonight; see `#36`'s comment.
CONVERTED_AMIGA = "Wrote POOLSAVE.ADF to {folder}. Load game {slot}."

#: The modal `QMessageBox.information` shown after any write that succeeds
#: -- C64, Amiga or DOS alike, over `EditorBinding.convert`'s own already-
#: closed dialog. Donald's own wording, verbatim, `#52 (File ▸ Import and
#: File ▸ Export for every direction the library supports)`, 2026-09-10:
#: *"Instead of closing the window, could we get a success pop-up that
#: says, 'Conversion successful!'. Then, on the next line, say, 'Your new
#: save is located at: '"* -- `{folder}` is the same path named on the
#: `Destination:` line above (`_destination_text`), never a second path
#: composed some other way. `CONVERTED_DOS` and `CONVERTED_AMIGA` still
#: carry the slot this sentence does not -- both fire alongside this one
#: rather than being replaced by it.
CONVERT_SUCCESS = "Conversion successful!\nYour new save is located at: {folder}"


def _destination_text(folder: pathlib.Path) -> str:
    """`DESTINATION_PREFIX` followed by the folder Convert would write
    into -- the folder alone, not the files inside it (2026-09-10: a C64 ->
    DOS write can name a dozen of those, and joining them onto one line
    was what forced the dialog to 6688px wide).

    `folder` is `fresh_folder`'s own preview of where Convert would write --
    named, not reserved, so a second Convert before this one commits can
    still land in the same place (the review of `a60e829`; the actual
    `mkdir()` happens once, in `EditorBinding.convert`, right before the
    write it guards).
    """
    return DESTINATION_PREFIX + str(folder)


def _game_files_from_folder(folder: pathlib.Path,
                            game: Any) -> "dosimport.GameFiles | None":
    """The icon, `ANIMATE00` and the creation menu read straight off
    `folder`, for a Commodore 64 destination whose game-files row a player
    has pointed at a specific folder by hand (`#413 (The Convert window
    changes shape depending on which platforms you are converting
    between)`, 2026-09-09's ruling: *"Just this conversion. Preferences is
    untouched."*).

    Mirrors `editor.window.EditorBinding.game_files_for`'s own read, cut to
    the one folder the row names -- this module must not import
    `wish.preferences`, so it cannot walk that method's full precedence of a
    title's own folder, the shared one, an environment variable and a path
    beside the open save. A player who edits the row is naming this one
    folder outright, not adding another candidate to that chain; with
    nothing edited, `ConvertDialog` still calls the injected `game_files`
    callable instead of this, which is that full precedence in the running
    program.
    """
    from goldbox.d64 import load_payload
    from goldbox.iconparts import IconParts
    from goldbox.portraits import PortraitError, tables_from_disks

    def read_animate(disk):
        return load_payload(disk, dos_codec.ANIMATE_FILE)

    candidates = sorted(pathlib.Path(folder).glob(game.disk_glob))

    def find(read):
        for candidate in candidates:
            try:
                read(str(candidate))
            except Exception:
                continue
            return str(candidate)
        return None

    icon_disk = find(IconParts.load)
    animate_disk = find(read_animate)
    if icon_disk is None or animate_disk is None:
        return None
    portraits = None
    if game.key == c64_port.POOL_OF_RADIANCE.key:
        try:
            portraits = tables_from_disks(folder)
        except (PortraitError, OSError) as exc:
            _log.debug("no creation menu off %s: %s", folder, exc)
    try:
        return dosimport.GameFiles(icon=IconParts.load(icon_disk),
                                   animate=read_animate(animate_disk),
                                   portraits=portraits)
    except Exception:
        _log.exception("could not read the conversion's game files off %s",
                       folder)
        return None


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------

class ConvertDialog(QDialog):
    """The source, the destination, and where it goes.

    One dialog for every registered direction (`#52`'s comment of
    2026-09-02: one Convert dialog with a source and a destination, not one
    per port). Every row change calls `replan()`, which detects the source,
    lists its registered destinations, rehearses the chosen one in memory,
    and either names the destination or says why it cannot -- a modal
    `QMessageBox` for a real refusal, and nothing at all for a row still
    empty, since the disabled Convert button already says that
    (`_maybe_warn`, `_SILENT_BLOCKS`) -- now that the pane this used to draw
    on is gone (2026-09-10) -- `editor/dosimport.py`'s rehearse-then-enable
    pattern otherwise unchanged. Convert is enabled
    only once a rehearsal exists and a folder to write it into has been
    named; nothing is written until the caller commits it
    (`editor.window.EditorBinding.convert`), which is what keeps
    `fresh_folder`'s naming and the actual `mkdir()` together rather than
    racing between two calls.

    `game_files` is a callable, `title -> GameFiles | None` --
    `EditorBinding.game_files_for` in the running program -- so this class
    never has to know how the player's C64 disks are found. `game_folder` is
    its sibling for the third row's own prefill (`#413 (The Convert window
    changes shape depending on which platforms you are converting between)`,
    2026-09-09: *"How about you include a file input, but autofill it with
    whatever is in the preferences."*): `title -> str | None`, read on every
    `replan()` until the player edits the row by hand, and never written
    back to -- this module must not import `wish.preferences`, so the
    injected callable is what stands in for it, the same way `game_files`
    already does.
    """

    def __init__(self, source: str, party: Any,
                game_files: "Any",
                destination: str | None = None,
                game: str | None = None,
                disk: str | None = None,
                folder: str | None = None,
                parent: QWidget | None = None,
                start_dir: str = "",
                game_folder: "Any | None" = None):
        super().__init__(parent)
        from .ui_convert import Ui_ConvertDialog

        self.ui = Ui_ConvertDialog()
        self.ui.setupUi(self)
        self.setWindowTitle(DIALOG_TITLE)

        self.party = party
        self._game_files = game_files
        #: `title -> str | None`, the game-files row's own prefill for a
        #: Commodore 64 destination -- `None` with nothing injected, which
        #: leaves the row exactly as blank as it was before this existed.
        self._game_folder = game_folder or (lambda _game: None)
        self.start_dir = start_dir or str(pathlib.Path.home())

        self._source_path = str(source)
        self._wanted_port = destination
        self._wanted_slot: str | None = None
        self._game_path = game
        #: The player's own Amiga disk 2, for an Amiga destination -- `disk=`
        #: here is what lets a test drive the whole path with no picker, the
        #: way `game=` already does for the DOS game folder.
        self._disk_path = disk
        #: The Commodore 64 game-files row's own value -- prefilled from
        #: `game_folder` on each `replan()` until `_c64_folder_edited` is
        #: set, which happens the first time the player picks one by hand
        #: (`_choose_files`) and then holds for the rest of this dialog's
        #: life, per 2026-09-09's ruling: *"Just this conversion. Preferences
        #: is untouched."*
        self._c64_folder_path: str | None = None
        self._c64_folder_edited = False
        self._folder_path = folder
        self._rebuilding_combo = False
        self._rebuilding_slot_combo = False

        #: Set by `replan()`. `source`/`direction` are `None` whenever this
        #: dialog does not currently hold a ready-to-write conversion;
        #: `rehearsal` is the one thing `EditorBinding.convert` needs to
        #: commit a write.
        #: `slot` is the DOS slot the rehearsal used -- the source's own for
        #: a DOS → C64 direction, the fixed `"A"` a fresh DOS folder always
        #: gets for a C64 → DOS one -- so a status line can name it without
        #: guessing which side of the conversion DOS was on.
        self.source: Source | None = None
        self.direction: Direction | None = None
        self.rehearsal: Rehearsal | None = None
        self.slot: str | None = None

        #: What stops Convert right now, `(title, text)` or `None`. Four of
        #: the reasons below (`_SILENT_BLOCKS`) mean only "a row is still
        #: empty" and never reach a modal; the rest are a real refusal --
        #: `CANNOT_CONVERT`, a `DosRecordError`'s own message -- and are
        #: shown verbatim as `QMessageBox.critical`, in place of a line in a
        #: pane that no longer exists (2026-09-10).
        self._blocked: tuple[str, str] | None = None
        #: What `_maybe_warn` last actually showed, so replanning after an
        #: unrelated change -- cancelling a picker, say -- does not repeat
        #: an identical modal the player has already read.
        self._last_blocked_shown: tuple[str, str] | None = None
        #: `False` through the constructor's own first `replan()` below, so
        #: building a `ConvertDialog` with a state already prefilled --
        #: every test in `tests/convert/test_convert.py` that does that -- never
        #: has to expect a modal of its own. `True` from here on: a real
        #: player only reaches this dialog after construction has already
        #: run once.
        self._interactive = False

        self.ui.label_source.setText(LABEL_SOURCE)
        self.ui.label_to.setText(LABEL_TO)
        self.ui.label_folder.setText(LABEL_FOLDER)

        self.ui.convert_source.setText(self._source_path)
        self.ui.convert_choose_source.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_source.clicked.connect(self._choose_source)

        self.ui.convert_slot.currentIndexChanged.connect(self._slot_changed)

        self.ui.convert_destination.currentIndexChanged.connect(
            self._destination_changed)

        self.ui.convert_choose_files.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_files.clicked.connect(self._choose_files)

        self.ui.convert_folder.setText(self._folder_path or "")
        self.ui.convert_choose_folder.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_folder.clicked.connect(self._choose_folder)

        self.buttons = self.ui.buttons
        self.buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText(BUTTON_CONVERT)

        self.replan()
        self._interactive = True

    # -- where it writes ---------------------------------------------------

    @property
    def folder(self) -> str:
        """The folder Convert would write inside, as the user has left it."""
        return self._folder_path or ""

    def refuse(self, text: str) -> None:
        """Report a failed write the way the rest of the app reports one --
        `EditorBinding.save`'s own `QMessageBox.critical(self.root, "Cannot
        save", ...)` -- now that this dialog carries no pane of its own to
        put it on (2026-09-10). `editor/window.py`'s two callers
        (`dialog.refuse(str(exc))`, `dialog.refuse(convert_mod.
        CANNOT_CONVERT)`) are unchanged; only what this does with the text
        they hand it changed."""
        QMessageBox.critical(self, DIALOG_TITLE, text)

    # -- choosing -----------------------------------------------------------

    def _choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, SOURCE_TITLE, self._source_path or self.start_dir,
            SOURCE_FILTER)
        if path:
            self._source_path = path
            self.ui.convert_source.setText(path)
            self._wanted_port = None
            self._wanted_slot = None
            self.replan()

    def _choose_files(self) -> None:
        """`Choose…` on the one row for the destination's own game files --
        `_settle_files_row` already says, by its label and its displayed
        value, which of the three this destination needs, so this only has
        to pick the right kind of picker.

        A Commodore 64 destination marks itself edited on a real choice --
        never on a cancelled picker, which leaves whatever `game_folder`
        prefilled in place rather than clearing it -- so a later `replan()`
        stops overwriting it with Preferences' own answer
        (2026-09-09's ruling: *"Just this conversion. Preferences is
        untouched."*).
        """
        if self.direction is None:
            return
        port = self.direction.destination_port
        if port == "amiga":
            path, _ = QFileDialog.getOpenFileName(
                self, DISK_TITLE, self._disk_path or self.start_dir,
                DISK_FILTER)
            if path:
                self._disk_path = path
        elif port == "c64":
            # No title of its own yet -- `LABEL_C64` is the row's own label
            # and is approved; a picker caption saying the same thing is a
            # second string nobody has ruled on, so this leaves Qt's own
            # platform default in place rather than inventing one
            # (`.claude/rules/gui-text.md`).
            path = QFileDialog.getExistingDirectory(
                self, "", self._c64_folder_path or self.start_dir)
            if path:
                self._c64_folder_path = path
                self._c64_folder_edited = True
        else:
            path = QFileDialog.getExistingDirectory(
                self, GAME_TITLE, self._game_path or self.start_dir)
            if path:
                self._game_path = path
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

    def _slot_changed(self, _index: int) -> None:
        if self._rebuilding_slot_combo:
            return
        self._wanted_slot = self.ui.convert_slot.currentData()
        self.replan()

    # -- the rehearsal --------------------------------------------------

    def replan(self) -> None:
        """Detect the source, rehearse the chosen destination, and either
        name where it would write or say why it cannot -- a modal for a real
        refusal, nothing at all for a row still empty (`_maybe_warn` below,
        `_SILENT_BLOCKS`), in place of a line in a pane that no longer
        exists (2026-09-10). Failures are shown, not raised -- the same
        rule `editor/dosimport.py`'s `_rehearse` follows. Called on every
        row change, so an empty row is the normal state this runs against
        far more often than a finished one."""
        self.source = None
        self.direction = None
        self.rehearsal = None
        self.slot = None
        #: Cleared on every plan and set only by `_rehearse_and_report`'s
        #: own success tail below, so every early return here -- no source,
        #: an unreadable one, no registered destination -- leaves both
        #: blank rather than naming a file Convert will not write.
        self.ui.convert_destination_line.setText("")
        self._blocked = None

        if not self._source_path:
            self._populate_destinations([])
            self._populate_slots(None)
            self._settle_files_row()
            self._settle_button()
            self._maybe_warn()
            return

        try:
            self.source = Source.detect(self._source_path, party=self.party,
                                        slot=self._wanted_slot)
            options = destinations_for(self.source)
        except Exception:
            _log.exception("could not read %s", self._source_path)
            self._populate_destinations([])
            self._populate_slots(None)
            self._blocked = (DIALOG_TITLE, CANNOT_CONVERT)
            self._settle_files_row()
            self._settle_button()
            self._maybe_warn()
            return

        self._populate_destinations(options)
        self._populate_slots(self.source)
        if not options:
            refusal = (POOLS_OF_DARKNESS_UNSUPPORTED
                       if self.source.key == dos_port.POOLS_OF_DARKNESS.key
                       else CANNOT_CONVERT)
            self._blocked = (DIALOG_TITLE, refusal)
            self._settle_files_row()
            self._settle_button()
            self._maybe_warn()
            return

        self.direction = self._chosen_direction(options)
        self._rehearse_and_report()
        self._settle_files_row()
        self._settle_button()
        self._maybe_warn()

    #: The `self._blocked` reasons that mean nothing more than "a field the
    #: player has not filled in yet" -- `NO_FOLDER`, `NO_GAME_FOLDER`,
    #: `NO_DISK` and `NO_DISKS`. `_settle_button` already leaves Convert
    #: disabled while any of these hold, so popping a modal on top of that
    #: told a player they had made a mistake that was actually inevitable
    #: (`#52`'s comment of 2026-09-10: it fired the moment `From` was filled
    #: in, before `Write to` had been touched at all). `self._blocked` is
    #: still set for these -- tests read it, and it is what `_settle_button`
    #: would explain if it had a line to draw -- only the popup is gone.
    _SILENT_BLOCKS = frozenset((NO_FOLDER, NO_GAME_FOLDER, NO_DISK, NO_DISKS))

    def _maybe_warn(self) -> None:
        """Tell the player the one thing left to tell them, now that
        `replan()` has nowhere to draw a running status: why Convert will
        not go (`self._blocked`).

        A loss `report.losses` names -- a name cut to fit, a value clamped
        to a narrower field -- is never shown here. That consent path
        (`dosimport.name_warnings`) is retired (#619,
        `docs/227-editor-open-save-as.md`); every loss goes to the debug
        log only (`dosimport.log_unshown_losses`).

        **Only a real refusal pops a modal.** `self._blocked` also carries
        the four `_SILENT_BLOCKS` reasons -- a row the player has simply not
        filled in yet -- and those never reach `QMessageBox`: the Convert
        button is already disabled for exactly as long as one of them holds,
        so the modal said nothing the greyed-out button did not already say,
        and firing on every field change made it appear before the player
        had done anything wrong (`#52`'s comment of 2026-09-10). `CANNOT_
        CONVERT` and a `DosRecordError`'s own message are not in that set --
        the player asked for a file that could not be read, or a conversion
        that could not run, which is a real refusal of something they
        actually did.

        Gated on `self._interactive`, so a `ConvertDialog` built with a
        state already prefilled -- every test in `tests/convert/test_convert.py`
        that does that -- never has to expect a modal of its own; a real
        player only reaches this after `__init__` has already run once.
        Deduplicated against what was last actually shown, so replanning
        after an unrelated change -- cancelling a picker, say -- does not
        repeat an identical modal the player has already read.
        """
        if not self._interactive:
            return
        if self._blocked != self._last_blocked_shown:
            self._last_blocked_shown = self._blocked
            if self._blocked is not None and self._blocked[1] not in self._SILENT_BLOCKS:
                title, text = self._blocked
                QMessageBox.critical(self, title, text)

    def _chosen_direction(self, options: list["Direction"]) -> "Direction":
        for d in options:
            if d.destination_port == self._wanted_port:
                return d
        return options[0]

    def _rehearse_and_report(self) -> None:
        """Rehearse `self.direction`, and set `self._blocked` or the
        destination line -- never both -- for `_maybe_warn` and the dialog
        itself to read.  Returned a string for `convert_report` to show
        until 2026-09-10, when that pane was removed outright (Donald: "the
        box under it has to be removed, too. That was the entire point.");
        every `return NO_X` below became `self._blocked = (title, NO_X);
        return` instead.
        """
        direction = self.direction
        if direction.destination_port == "c64" and not self.source.slot:
            # Unreachable through the dialog's own save picker, which
            # always names a slot (`Source.detect`'s `SAVGAM<slot>.*`
            # branch); only a caller handing `Source.detect` a bare
            # folder directly -- a test or `tools/` script -- can reach
            # this, and there is no slot to guess at for it.
            self._blocked = (DIALOG_TITLE, CANNOT_CONVERT)
            return
        try:
            # A folder the player picked or edited by hand off the game-files
            # row names exactly that folder (2026-09-09's ruling: "just this
            # conversion"); anything else goes through the injected
            # `game_files` lookup, which is Preferences' full precedence in
            # the running program.
            assets = saveplan.resolve_assets(
                self.source, direction.destination_port,
                game_files=self._game_files,
                c64_folder=(self._c64_folder_path
                            if self._c64_folder_edited else None),
                dos_folder=self._game_path, amiga_disk=self._disk_path)
        except saveplan.MissingAssets as exc:
            self._blocked = MISSING_ASSET_BLOCKS[exc.missing[0]]
            return

        try:
            self.rehearsal, self.slot = saveplan.rehearse(
                direction, self.source, assets)
        except saveplan.NamesDoNotFit as exc:
            # No dialog to ask for a replacement yet (#619's Stage C), so
            # this stops the write the way a name too long for the C64's
            # field already refuses it: a real refusal, not a silent cut.
            _log.info("names do not fit the %s destination: %s",
                      direction.destination_port, exc)
            self._blocked = (DIALOG_TITLE, CANNOT_CONVERT)
            return
        except dos_codec.DosRecordError as exc:
            _log.exception("could not rehearse %s", self._source_path)
            self._blocked = (DIALOG_TITLE, exc.player_message)
            return
        except Exception:
            _log.exception("could not rehearse %s", self._source_path)
            self._blocked = (DIALOG_TITLE, CANNOT_CONVERT)
            return

        if not self._folder_path:
            self._blocked = (DIALOG_TITLE, NO_FOLDER)
            return

        preview = fresh_folder(pathlib.Path(self._folder_path))
        self.ui.convert_destination_line.setText(_destination_text(preview))

        #: Still called for its own side effect -- `report.dropped`, to the
        #: debug log -- even though nothing shows its returned text any
        #: more. `DosImportDialog` stopped calling this too, 2026-09-14,
        #: when its own pane went the same way this dialog's did, and was
        #: itself deleted later that same day along with `File ▸ Import`,
        #: `#52 (File ▸ Import and File ▸ Export for every direction the
        #: library supports)`.
        dosimport.pane_text(self.rehearsal.report)

        #: Every `report.losses` line goes to the debug log and nowhere a
        #: player reads (#619): the name-truncation consent modal this
        #: comment once described is retired
        #: (`docs/227-editor-open-save-as.md` -- "a loss does not become
        #: acceptable by being classified outside the drop list"), so a
        #: loss is evidence for a bug (#508, #509 among them) rather than a
        #: sentence a player is asked to accept.
        dosimport.log_unshown_losses(self.rehearsal.report)

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

    def _populate_slots(self, source: "Source | None") -> None:
        """The slot combo on the `From` row: shown only when the source
        names more than one saved game (`#372 (An Amiga disk with more than
        one saved game converts its first slot, whichever one the player
        meant)`) -- an Amiga `.adf` or a DOS save folder, while a DOS save
        file already names its own slot through the save picker.

        **A widget's own visibility, not a form row's**, since 2026-09-09
        (`#413 (The Convert window changes shape depending on which
        platforms you are converting between)`): the combo sits inside
        `source_row` next to `Choose…` now rather than owning a row of its
        own, so hiding it hides only itself and never moves the `From` row
        the way `setRowVisible` would have.

        Rebuilt from `source.available_slots` every `replan()`, the way
        `_populate_destinations` rebuilds the destination combo from
        `destinations_for` -- so a source with one slot never shows a combo
        of one, and switching to a source with several grows it back."""
        combo = self.ui.convert_slot
        slots = source.available_slots if source is not None else None
        show = bool(slots) and len(slots) > 1
        combo.setVisible(show)
        if not show:
            return
        self._rebuilding_slot_combo = True
        combo.blockSignals(True)
        combo.clear()
        for letter in slots:
            combo.addItem(SLOT_ITEM.format(slot=letter), letter)
        chosen = source.slot if source.slot in slots else slots[0]
        combo.setCurrentIndex(slots.index(chosen))
        self._wanted_slot = chosen
        combo.blockSignals(False)
        self._rebuilding_slot_combo = False

    def _settle_files_row(self) -> None:
        """The one row for the destination's own game files -- always
        shown, in all six directions, replacing `_settle_game_row` and
        `_settle_disk_row`, which used to show and hide two different rows
        and left the window a different height for a DOS, a C64 and an
        Amiga destination alike (`#413 (The Convert window changes shape
        depending on which platforms you are converting between)`).  Only
        the label, the displayed value and what `Choose…` opens change.

        A Commodore 64 destination is prefilled from `_game_folder` on
        every call here, unless the player has already edited this row by
        hand (`_c64_folder_edited`) -- 2026-09-09's ruling: *"How about you
        include a file input, but autofill it with whatever is in the
        preferences,"* and, on what an edit does to that setting, *"Just
        this conversion. Preferences is untouched."*

        With no direction chosen yet -- the dialog holds no source, or the
        source could not be read -- the row stays visible with nothing in
        it and its `Choose…` disabled, rather than guessing which of the
        three destinations it does not yet know about.
        """
        self.ui.form.setRowVisible(self.ui.files_row, True)
        port = self.direction.destination_port if self.direction is not None else None
        self.ui.convert_choose_files.setEnabled(port is not None)
        if port == "amiga":
            self.ui.label_files.setText(LABEL_DISK)
            self.ui.convert_files.setText(self._disk_path or "")
        elif port == "c64":
            if not self._c64_folder_edited:
                self._c64_folder_path = self._game_folder(
                    self.direction.destination_game) or ""
            self.ui.label_files.setText(LABEL_C64)
            self.ui.convert_files.setText(self._c64_folder_path or "")
        elif port == "dos":
            self.ui.label_files.setText(LABEL_GAME)
            self.ui.convert_files.setText(self._game_path or "")
        else:
            self.ui.label_files.setText("")
            self.ui.convert_files.setText("")

    def _settle_button(self) -> None:
        """Convert is pressable only once there is a rehearsal to write and
        somewhere named to write it -- `editor/dosimport.py`'s rule, and the
        reason a ready rehearsal with no folder still shows `NO_FOLDER`
        rather than the writes list (`_rehearse_and_report` above)."""
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.rehearsal is not None and bool(self._folder_path))
