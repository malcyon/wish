"""The registry of save conversions the library can build from nothing, which
Save As offers as destinations.

A **direction** is registered here only when the destination can be written
whole, owing nothing to another save -- `.claude/rules/conversions.md`'s
rule against a template. Today that is:

* DOS save folder → C64, one row per entry of `C64_PAIRED`, which is
  `goldbox.dos_codec.CONVERTS` cut to the titles with a C64 port to convert to --
  Pool of Radiance, Curse of the Azure Bonds and Secret of the Silver Blades
  (`goldbox.dos_codec.new_save`; Pool of Radiance proven in VICE by
  `#119 (Play a converted DOS save in VICE, off a disk Wish built from
  nothing)`, Curse of the Azure Bonds by the work on converting a Curse of the Azure Bonds DOS save into a C64 one, Secret
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
* Pools of Darkness, one row each way -- `PodAmigaToDos` (Amiga `.adf` →
  DOS save folder; `goldbox.amiga_savegame.pod_from_amiga`/`pod_parse`,
  `goldbox.amiga_pod.pod_to_neutral`, then `goldbox.dos_codec.
  new_pod_save_from`) and `PodDosToAmiga` (DOS save folder → the Amiga disk 3).
  This title has no C64 port and cannot join `amiga_shared.CONVERTS`/`WRITES`,
  so both are listed in `DIRECTIONS` by hand.

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
`CHRDAT<slot><n>.SAV`...), whatever the title, so `c64_port.by_key(deltas.key)`
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
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import logging
import pathlib
import re
import tempfile
from collections.abc import Collection, Iterator, Mapping
from typing import Any

from goldbox import (
    amiga_later,
    amiga_pod,
    amiga_por,
    amiga_savegame,
    amiga_shared,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    dos_savegame,
    neutral,
    titles,
    world_state,
)
from goldbox.amiga_adf import AmigaDiskError, AmigaDiskFull

# By name rather than as a module: `amiga_port` and `amiga_por` differ by one
# letter, and only one of them belongs in the line above.
from goldbox.amiga_port import AmigaRecordError
from goldbox.iconparts import (
    amiga_combat_icon,
    amiga_por_icon_from_dos,
    amiga_por_icon_to_dos,
)

from . import dosimport, saveplan

_log = logging.getLogger("wish.editor.convert")


class ConvertError(Exception):
    """Anything a direction or `Source.detect` blocks, phrased for a
    player to read -- in a modal `QMessageBox` since 2026-09-10."""


def overflow_of(exc: Exception) -> "tuple[dos_codec.PackOverflow, ...]":
    """The packs a pack-overflow exception names, as the tuple the left-behind
    window takes: the C64's carries one per character, the Amiga's one for the
    party."""
    if isinstance(exc, amiga_savegame.AmigaJoinedScrollsDoNotFit):
        return (exc.overflow,)
    return exc.overflow


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

def _unread_dos_title(folder: pathlib.Path) -> str | None:
    """The key of a DOS title Wish does not read that `folder` or the game
    folder above it, holds.

    A folder the readable table already names as Curse or Pools of Darkness
    is never one of the unread titles, whatever else it holds or is called,
    so such a save opens as its own title.
    """
    for where in (folder, folder.parent):
        try:
            if (titles.dos_folder_title(where)
                    in (dos_port.CURSE_OF_THE_AZURE_BONDS.key,
                        dos_port.POOLS_OF_DARKNESS.key)):
                return None
            key = titles.dos_folder_title(
                where, table=titles.DOS_UNREAD_FOLDER_FILES)
        except OSError:
            continue
        if key is not None:
            return key
    return None


@dataclasses.dataclass

class Source:
    """One save, read off a path -- never off what a window happens to hold.

    `title` is a `goldbox.c64_save.C64Container` for a C64 source or a
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
        `detect` is what blocks it. Anything else is taken for a C64 disk
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
        slot, which is what a file picker hands over for a DOS
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
        """The DOS source at `folder`, for the save at `slot`.

        The one thing the two callers above disagree on is which slot: a
        bare folder (`tools/dos/dosdisk.py`, `tools/dos/dosnewsave.py`, and the
        Step 1 tests) takes the first complete slot `_dos_slots` finds, and a
        `SAVGAM<slot>.DAT`/`.PTY` file picked directly -- the dialog's own
        save picker -- names its own. Either way the title comes off
        `CHRDAT<slot>1.SAV`'s own size (`goldbox.dos_port.deltas_for`),
        never assumed.
        """
        record = dos_savegame.save_file(folder, f"CHRDAT{slot}1.SAV")
        if not record.exists():
            raise ConvertError(
                f"{folder} holds SAVGAM{slot} but no CHRDAT{slot}1.SAV to "
                f"read its shape from")
        try:
            deltas = dos_port.deltas_for(record.stat().st_size)
        except dos_port.DosDeltasError as exc:
            raise ConvertError(str(exc)) from exc
        if deltas.key == dos_port.CURSE_OF_THE_AZURE_BONDS.key:
            if (_unread_dos_title(folder)
                    == titles.GATEWAY_TO_THE_SAVAGE_FRONTIER.key):
                raise dos_codec.WrongTitleError(
                    f"{folder} is a Gateway to the Savage Frontier save "
                    f"folder; its 422-byte records would read through "
                    f"Curse's tables",
                    titles.GATEWAY_TO_THE_SAVAGE_FRONTIER.title)
        elif (deltas.key == dos_port.POOLS_OF_DARKNESS.key
                and _unread_dos_title(folder)
                == titles.TREASURES_OF_THE_SAVAGE_FRONTIER_KEY):
            raise dos_codec.WrongTitleError(
                f"{folder} is a Treasures of the Savage Frontier save "
                f"folder; its 510-byte records would read through Pools of "
                f"Darkness' tables",
                titles.TREASURES_OF_THE_SAVAGE_FRONTIER_TITLE)
        return cls(port="dos", title=deltas, path=folder, slot=slot,
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
                deltas = dos_port.POOLS_OF_DARKNESS
            elif chosen in por_slots:
                record = disk.read_file(amiga_savegame.por_save_path(
                    amiga_por.por_filename(chosen, 1),
                    amiga_savegame.por_save_drawer(disk)))
                deltas = amiga_shared.deltas_for(len(record))
            else:
                container = amiga_savegame.read_slot(disk, chosen).container
                if container.party != "records" or container.deltas is None:
                    raise ConvertError(f"slot {chosen} has no embedded party")
                deltas = container.deltas.dos
        except (AmigaDiskError, AmigaRecordError,
                amiga_savegame.AmigaSaveError) as exc:
            raise ConvertError(str(exc)) from exc
        return cls(port="amiga", title=deltas, path=path, slot=chosen,
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
#: writes upper case, but a picker should not block a renamed copy.
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
    return [slot for slot in dos_savegame.slot_letters(folder)
            if _dos_slot_is_readable(folder, slot)]


def _dos_slot_is_readable(folder: pathlib.Path, slot: str) -> bool:
    """Whether a slot has a readable first character record of a known form."""
    record = dos_savegame.save_file(folder, f"CHRDAT{slot}1.SAV")
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

    `source_key` and `destination_game.key` are `goldbox.c64_save.C64Container.key` or
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
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None,
                leave_effects: "Mapping[int, Collection[int]] | None" = None
                ) -> Rehearsal:
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
#: deltas object itself, which knows nothing about C64 file names.
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
    title joining that tuple (the work on converting a Secret of the Silver Blades DOS save into a C64 one will put
    Secret of the Silver Blades there) needs no edit to this class.

    `rehearse` is `editor.dosimport.rehearse` exactly as `File ▸ Import`
    calls it today -- the whole conversion happens in memory and reads the
    title off the record itself (`goldbox.dos_port.deltas_for`), not off `deltas`
    here, so `write` only has to put the bytes it already built on disk.
    `deltas` decides only which source this instance answers for and what
    the output is named.
    """

    source_port = "dos"
    destination_port = "c64"

    def __init__(self, deltas: dos_port.DosDeltas):
        self.deltas = deltas
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
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None,
                leave_effects: "Mapping[int, Collection[int]] | None" = None
                ) -> Rehearsal:
        with source.folder() as folder:
            # Sent only when the player chose something, as `leave` is.
            conversion = dosimport.rehearse(
                folder, slot, options, leave=leave,
                **({"names": names} if names else {}),
                **({"leave_effects": leave_effects}
                   if leave_effects else {}))
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
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None,
                leave_effects: "Mapping[int, Collection[int]] | None" = None
                ) -> Rehearsal:
        disk = source.amiga_disk()
        if self.deltas is dos_port.POOL_OF_RADIANCE:
            party, savgam = amiga_savegame.read_por_slot(disk, slot)
            state = amiga_savegame.read_por_state(
                savgam, source=f"{source.path} slot {slot}")
            # `read_por_slot` hands back `goldbox.dos_codec.DosCharacter`,
            # not a neutral party -- `fit_names` cannot run against it, so
            # the check runs on its names and the choice goes to the writer.
            chosen = saveplan.check_names(
                [c.name for c in party], self.destination_port,
                self.deltas.key, names)
            if leave:
                raise saveplan.SaveAsError(
                    f"{self.source_port} to c64 has no joined scroll to "
                    f"leave anything of for {self.deltas.key}")
            characters = party
            party_icons = None
            pool_icons = [amiga_por_icon_to_dos(amiga_combat_icon(c),
                                                c.get("size"))
                          for c in party]
        else:
            pool_icons = None
            save = amiga_savegame.read_slot(disk, slot, self.deltas.key)
            state = amiga_savegame.state_from_savegame(save)
            characters = [amiga_later.to_neutral_later(c)
                          for c in save.characters]
            party_icons = [amiga_combat_icon(c) for c in save.characters]
            chosen = None
            characters = saveplan.fit_names(
                characters, self.destination_port, self.deltas.key, names)
        if party_icons is None:
            save0, save1, report = dos_codec.new_save_from(
                state, characters, options.icon, options.animate,
                portraits=options.portraits, game=self.destination_game,
                leave=leave, item_types=options.item_types, names=chosen,
                leave_effects=leave_effects, party_icons=pool_icons)
        else:
            save0, save1, report = dos_codec.new_save_from_neutral(
                state, characters, party_icons, options.icon, options.animate,
                game=self.destination_game, leave=leave,
                item_types=options.item_types, leave_effects=leave_effects)
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
    figure at all, because the table only runs one way)`). Save As
    supplies it, off the *source*'s own title rather than the destination's
    (`#383`); left out, every figure is the game's own default.
    """

    source_port = "c64"
    destination_port = "dos"

    def __init__(self, deltas: dos_port.DosDeltas):
        self.deltas = deltas
        self.source_key = deltas.key
        self.destination_game = deltas
        # Raises `titles.UnknownTitleError` at import time (via `DIRECTIONS`
        # below) if `WRITES` ever named a title with no C64 port -- the
        # loud failure `DOS_TO_C64_NAMES` gives the other direction, with no
        # table of its own needed: a C64 → DOS conversion writes the same
        # file names whatever the title.
        self.title = c64_port.by_key(deltas.key)

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                icon_parts: "Any | None" = None,
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None
                ) -> "AmigaDosRehearsal":
        if leave:
            # Only a C64 record has a slot count a pack can overflow; a
            # choice of what to leave behind means nothing to this port.
            raise saveplan.SaveAsError(
                f"{self.source_port} to {self.destination_port} has no "
                f"pack to leave anything of")
        game_dir = pathlib.Path(options)
        c64 = dos_codec.c64_title(source.save0, self.title)
        state = world_state.from_c64(source.save0, game=c64)
        characters, icons = dos_codec.c64_party(
            source.save0, source.save1, c64, icon_parts=icon_parts)
        characters = saveplan.fit_names(
            characters, self.destination_port, self.deltas.key, names)
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


@dataclasses.dataclass
class PodAmigaDosRehearsal(AmigaDosRehearsal):
    """`AmigaDosRehearsal` plus the slot's item vault.

    Its own subclass rather than a field on the shared one: `AmigaToDos`
    builds `AmigaDosRehearsal` positionally, for titles that have no vault,
    and this one field belongs only to Pools of Darkness.
    """

    vault: Any


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
    by the same engine to the same file names, so the deltas lookup and the
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
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None
                ) -> AmigaDosRehearsal:
        if leave:
            # Only a C64 record has a slot count a pack can overflow; a
            # choice of what to leave behind means nothing to this port.
            raise saveplan.SaveAsError(
                f"{self.source_port} to {self.destination_port} has no "
                f"pack to leave anything of")
        if not source.slot:
            # Unreachable through `Source.detect`, whose `.adf` branch always
            # names the first slot the disk holds files for; only a caller
            # building a `Source` by hand can get here, and there is no Amiga
            # slot to guess at for it.
            raise ConvertError(f"{source.path} names no Amiga save slot")
        game_dir = pathlib.Path(options)
        disk = source.amiga_disk()
        if self.deltas is dos_port.POOL_OF_RADIANCE:
            party, savgam = amiga_savegame.read_por_slot(disk, source.slot)
            state = amiga_savegame.read_por_state(
                savgam, source=f"{source.path} slot {source.slot}")
            characters = [c64_codec.living_player(dos_codec.to_neutral(c))
                          for c in party]
        else:
            save = amiga_savegame.read_slot(disk, source.slot, self.deltas.key)
            state = amiga_savegame.state_from_savegame(save)
            party = list(save.characters)
            characters = [c64_codec.living_player(
                              amiga_later.to_neutral_later(c))
                          for c in party]
        # Cannot fire today: an Amiga name is at most fifteen characters and
        # the DOS field holds the same fifteen. Called anyway, so a
        # direction added later does not have to remember to.
        characters = saveplan.fit_names(
            characters, self.destination_port, self.deltas.key, names)
        # The Amiga file order **is** the DOS file order (`docs/165-amiga-
        # savegame.md`), so there is no reversal here; `goldbox.dos_codec.
        # marching_slot` and `c64_party`'s own `reverse()` are the C64's
        # business and `#101`'s.
        icons = [amiga_combat_icon(c) for c in party]
        if self.deltas is dos_port.POOL_OF_RADIANCE:
            icons = [amiga_por_icon_to_dos(icon, c.get("size"))
                     for icon, c in zip(icons, party)]
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos_codec.new_dos_save_from(state, characters, scratch_path,
                                           slot, game_dir, icons=icons)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return AmigaDosRehearsal(report, files, state, characters, icons,
                                 slot, game_dir)


def _pod_living(char: Any) -> Any:
    """`char` as `living_player` leaves it, with the source's
    `field_83_87` window kept: that function builds a new record, and the
    Pools of Darkness writers need the window's bytes after the control byte,
    whose own byte becomes the living record's."""
    living = c64_codec.living_player(char)
    window = dos_codec.window_source(char)
    if living is not char and window is not None:
        control = living.get("npc_control_byte") or 0
        dos_codec.set_window_source(
            living, bytes((control,)) + bytes(window[1:]))
    return living


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

    Registered in `DIRECTIONS` by hand.
    """

    source_port = "amiga"
    destination_port = "dos"

    def __init__(self) -> None:
        self.deltas = dos_port.POOLS_OF_DARKNESS
        self.destination_game = dos_port.POOLS_OF_DARKNESS
        self.source_key = self.deltas.key

    def rehearse(self, source: Source, slot: str, options: Any,
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None
                ) -> "PodAmigaDosRehearsal":
        if leave:
            # Only a C64 record has a slot count a pack can overflow; a
            # choice of what to leave behind means nothing to this port.
            raise saveplan.SaveAsError(
                f"{self.source_port} to {self.destination_port} has no "
                f"pack to leave anything of")
        if not source.slot:
            # Unreachable through `Source.detect`, whose `.adf` branch
            # always names the first slot the disk holds files for; only a
            # caller building a `Source` by hand can get here.
            raise ConvertError(f"{source.path} names no Amiga save slot")
        disk = source.amiga_disk()
        data = amiga_savegame.pod_read_slot(disk, source.slot)
        state = amiga_savegame.pod_from_amiga(
            data, source=f"{source.path} slot {source.slot}")
        characters = [
            _pod_living(amiga_pod.pod_to_neutral(block))
            for block in amiga_savegame.pod_parse(data).blocks]
        characters = saveplan.fit_names(
            characters, self.destination_port, self.deltas.key, names)
        vault = amiga_savegame.pod_read_vault(disk, source.slot)
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos_codec.new_pod_save_from(
                state, characters, scratch_path, slot, vault=vault)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return PodAmigaDosRehearsal(report, files, state, characters, [],
                                    slot, None, vault)

    def write(self, rehearsal: "PodAmigaDosRehearsal",
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        dos_codec.new_pod_save_from(rehearsal.state, rehearsal.characters,
                                    folder, rehearsal.slot,
                                    vault=rehearsal.vault)
        return sorted(folder / name for name in rehearsal.files)


@dataclasses.dataclass
class PodDosAmigaRehearsal(Rehearsal):
    """A Pools of Darkness DOS slot written onto a copy of the player's disk 3.

    `files` holds the finished image under `POOLSAVE_FILENAME`, as
    `DosToAmiga`'s does; Save As publishes it under the file name the player
    chose.  `disk` is the same image.
    """

    disk: bytes
    state: Any
    characters: list
    slot: str


class PodDosToAmiga(Direction):
    """A DOS Pools of Darkness save slot becomes the player's Amiga disk 3 with
    that slot written into its `SAVE` drawer.

    Registered in `DIRECTIONS` by hand.  Save As asks for the disk through
    `saveplan.AMIGA_DISK_THREE`.  The slot keeps the source's letter, as
    `DosToAmiga` does.
    """

    source_port = "dos"
    destination_port = "amiga"

    def __init__(self) -> None:
        self.deltas = dos_port.POOLS_OF_DARKNESS
        self.destination_game = dos_port.POOLS_OF_DARKNESS
        self.source_key = self.deltas.key

    def rehearse(self, source: Source, slot: str, options: Any,
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None,
                disk_three: "Any | None" = None,
                replace: bool = False) -> PodDosAmigaRehearsal:
        """`disk_three` is the player's own `goldbox.amiga_adf.AmigaDisk`.

        A slot letter the disk already holds is replaced only when `replace`
        is true."""
        if leave:
            raise saveplan.SaveAsError(
                f"{self.source_port} to {self.destination_port} has no "
                f"pack to leave anything of")
        if not source.slot:
            raise ConvertError(f"{source.path} names no DOS save slot")
        if disk_three is None:
            raise ConvertError("a Pools of Darkness save written for the Amiga "
                               "needs the player's disk 3")
        if slot.upper() != source.slot.upper():
            raise ConvertError(
                f"slot {slot} was asked for but the source is slot "
                f"{source.slot}")
        letter = source.slot
        container = dos_savegame.container_for(self.deltas.key)
        with source.folder() as folder:
            folder = pathlib.Path(folder)
            savgam_path = dos_savegame.save_file(
                folder, f"SAVGAM{letter}{container.suffix}")
            savgam = savgam_path.read_bytes()
            raw_party = dos_codec.read_party(folder, letter)
            vault_path = dos_savegame.save_file(folder, f"VAULT{letter}.DAT")
            # A slot with no vault file is taken to hold no stored items.
            vault = (dos_codec.pod_vault_from_dos(vault_path.read_bytes())
                     if vault_path.is_file() else dos_codec.EMPTY_POD_VAULT)
        state = world_state.pod_from_dos(
            savgam, container,
            source=str(pathlib.Path(source.path) / savgam_path.name))
        characters = saveplan.fit_names(
            [_pod_living(dos_codec.to_neutral(c)) for c in raw_party],
            self.destination_port, self.deltas.key, names)
        savegame, save_report = amiga_savegame.pod_new_savegame(
            state, characters)
        try:
            vault_bytes = amiga_savegame.pod_vault_to_amiga(
                vault, amiga_savegame.pod_party_nodes(savegame))
            disk = amiga_savegame.pod_slot_on_disk_three(
                disk_three, letter, savegame, vault_bytes, replace=replace)
        except AmigaDiskFull:
            raise
        except (amiga_savegame.AmigaSaveError, AmigaDiskError) as e:
            raise ConvertError(str(e)) from e
        report = neutral.Report()
        report.dropped.extend(save_report.dropped)
        report.losses.extend(save_report.losses)
        report.warnings.extend(save_report.warnings)
        image = disk.to_bytes()
        return PodDosAmigaRehearsal(report, {POOLSAVE_FILENAME: image},
                                    image, state, characters, letter)

    def write(self, rehearsal: PodDosAmigaRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / POOLSAVE_FILENAME
        path.write_bytes(rehearsal.files[POOLSAVE_FILENAME])
        return [path]


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


def _rehearse_later_savegame(state: Any, deltas: dos_port.DosDeltas,
                             slot: str, party: list,
                             ecl_glb: bytes | None,
                             icons: "list | None" = None,
                             disk_one: "str | pathlib.Path | None" = None,
                             leave: "Mapping[int, Collection[int]] | None" = None,
                             ) -> AmigaWriteRehearsal:
    """Build a fresh Curse or Silver Blades saved game on a copy of the
    player's disk 1, the disk the game reads its `SAVE` drawer from."""
    from goldbox.amiga_adf import AmigaDisk

    if disk_one is None:
        raise saveplan.MissingAssets((saveplan.AMIGA_DISK_ONE,))
    savegame, report = amiga_savegame.new_savegame(
        state, party, slot, ecl_glb=ecl_glb, icons=icons, leave=leave)
    disk = amiga_savegame.slot_on_disk_one(
        AmigaDisk.open(str(disk_one)), deltas.key, slot, savegame)
    return AmigaWriteRehearsal(
        report, {POOLSAVE_FILENAME: disk.to_bytes()}, party, state, slot,
        savegame)


def amiga_needs_disk_one(deltas: dos_port.DosDeltas) -> bool:
    """Whether an Amiga destination of this title is a copy of the player's
    own disk 1: Curse and Silver Blades read their saves from its `SAVE`
    drawer and search no other disk."""
    return deltas in (dos_port.CURSE_OF_THE_AZURE_BONDS,
                     dos_port.SECRET_OF_THE_SILVER_BLADES)


def amiga_needs_disk_three(deltas: dos_port.DosDeltas) -> bool:
    """Whether an Amiga destination of this title is a copy of the player's
    own disk 3: Pools of Darkness reads its saves from that disk's `SAVE`
    drawer."""
    return deltas is dos_port.POOLS_OF_DARKNESS


def amiga_needs_game_disk(deltas: dos_port.DosDeltas,
                          source: "Source | None" = None) -> bool:
    """Whether an Amiga destination of this title reads anything off the
    player's own disk 2.

    Pool of Radiance stages the area's own `ecl.dax` and Curse of the Azure
    Bonds its `ECL.GLB`; Secret of the Silver Blades stages neither and needs
    no disk 2. A Curse party from a C64 or DOS `source` that has not set out
    stages no script either. `editor.saveplan.requirements` asks this rather
    than demanding a disk for every Amiga destination alike.
    """
    if deltas in (dos_port.SECRET_OF_THE_SILVER_BLADES,
                  dos_port.POOLS_OF_DARKNESS):
        return False
    if (deltas is dos_port.CURSE_OF_THE_AZURE_BONDS
            and source is not None and source.port == "c64"
            and source.save0 is not None):
        state = world_state.from_c64(
            source.save0, game=c64_port.by_key(deltas.key),
            source=str(source.path))
        return not world_state.has_not_set_out(state)
    if (deltas is dos_port.CURSE_OF_THE_AZURE_BONDS
            and source is not None and source.port == "dos"
            and source.slot):
        container = dos_savegame.container_for(deltas.key)
        try:
            with source.folder() as folder:
                savgam = dos_savegame.save_file(
                    folder, f"SAVGAM{source.slot}{container.suffix}"
                ).read_bytes()
            state = world_state.from_dos(savgam, container,
                                         source=str(source.path))
        except (OSError, dos_codec.DosRecordError):
            # A save that cannot be read is reported by the conversion itself,
            # where the error is handled; asking for the disk is the safe answer.
            return True
        return not world_state.has_not_set_out(state)
    return True


def dos_needs_game_folder(deltas: dos_port.DosDeltas) -> bool:
    """Whether a DOS destination of this title reads anything off the
    player's own game folder.

    Every other DOS destination stages the party's own area script out of
    `ECL<n>.DAX`, which is the game's own file; Pools of Darkness stages no
    script (`goldbox.dos_codec.new_pod_save_from` reads nothing off disk)
    and so needs no game folder at all -- the same per-title question
    `amiga_needs_game_disk` answers for an Amiga destination.
    """
    return deltas is not dos_port.POOLS_OF_DARKNESS


def _amiga_destination_data(deltas: dos_port.DosDeltas,
                            options: "str | pathlib.Path",
                            source: "Source | None" = None) -> bytes | None:
    """The one game-data file a fresh save needs, when it needs one."""
    if not amiga_needs_game_disk(deltas, source):
        return None
    from goldbox.amiga_adf import AmigaDisk

    path = (_ECL_DAX_PATH if deltas is dos_port.POOL_OF_RADIANCE
            else _ECL_GLB_PATH)
    return AmigaDisk.open(str(options)).read_file(path)


def _figure_size(char: Any) -> int | None:
    """1 small or 2 large, from a DOS record's `size` or a neutral `size_small`."""
    size = char.get("size")
    if size is None and char.get("size_small") is not None:
        size = 1 + char.get("size_small")
    return size


def _rehearse_amiga_savegame(state: Any, deltas: dos_port.DosDeltas,
                             slot: str, party: list,
                             game_data: bytes | None,
                             icons: "list | None" = None,
                             disk_one: "str | pathlib.Path | None" = None,
                             leave: "Mapping[int, Collection[int]] | None" = None,
                             ) -> AmigaWriteRehearsal:
    if deltas is dos_port.POOL_OF_RADIANCE:
        if game_data is None:
            raise AmigaRecordError("Amiga Pool of Radiance needs ecl.dax")
        # The sources hold DOS numbers; the Amiga's art numbers its drawings
        # differently (`goldbox.amiga_por_icons.SAME_DRAWING`).
        if icons is not None:
            icons = [None if icon is None
                     else amiga_por_icon_from_dos(icon, _figure_size(member))
                     for icon, member in zip(icons, party)]
        return _rehearse_por_savegame(
            state, slot, party, game_data, icons=icons)
    return _rehearse_later_savegame(
        state, deltas, slot, party, game_data, icons=icons,
        disk_one=disk_one, leave=leave)


class C64ToAmiga(Direction):
    """A C64 save becomes an Amiga disk holding the saved game, for any title in
    `goldbox.amiga_shared.WRITES` (#316, #36).

    One instance per entry of `WRITES` -- see `DIRECTIONS` below -- so a
    title joining that tuple needs no edit to this class. `options` is the
    path to the player's own Amiga disk 2, never disk 1. Curse and Silver
    Blades are written onto a copy of the player's disk 1, given as `disk_one`.

    A C64 source has no slot of its own, so the built saved game is always
    slot `A` -- the same rule `C64ToDos.rehearse` follows for a fresh DOS
    folder.

    `icon_parts` is `goldbox.dos_codec.c64_party`'s own argument -- the source
    title's own `SPELLE64`/`SPELLN64`, read into a `goldbox.iconparts.
    IconParts` -- which turns each character's own C64 combat icon into an
    Amiga figure, mirroring `C64ToDos`'s own parameter (#422 (A C64 party
    converted to an Amiga save disk arrives with no combat figure at all,
    because C64ToAmiga never recognises it), the same form #383 gave the
    DOS destination). Save As supplies it, off the *source*'s own
    title; left out, every figure is the game's own default, as before that
    ticket.
    """

    source_port = "c64"
    destination_port = "amiga"

    def __init__(self, deltas: dos_port.DosDeltas):
        self.deltas = deltas
        self.source_key = deltas.key
        self.destination_game = deltas
        # The C64 title `dos_codec.c64_party` reads the source disk against --
        # `c64_port.by_key` raises loudly at import time if `WRITES` ever named
        # a title with no C64 port, the same guard `C64ToDos.__init__` keeps.
        self.title = c64_port.by_key(deltas.key)

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                icon_parts: "Any | None" = None,
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None,
                disk_one: "str | pathlib.Path | None" = None) -> AmigaWriteRehearsal:
        if leave:
            # Only a C64 record has a slot count a pack can overflow; a
            # choice of what to leave behind means nothing to this port.
            raise saveplan.SaveAsError(
                f"{self.source_port} to {self.destination_port} has no "
                f"pack to leave anything of")
        game_data = _amiga_destination_data(self.deltas, options, source)
        party, icons = dos_codec.c64_party(source.save0, source.save1,
                                     game=self.title, icon_parts=icon_parts)
        party = saveplan.fit_names(
            party, self.destination_port, self.deltas.key, names)
        state = world_state.from_c64(
            source.save0, game=self.title, source=str(source.path))
        return _rehearse_amiga_savegame(
            state, self.deltas, "A", party, game_data, icons=icons,
            disk_one=disk_one)

    def write(self, rehearsal: AmigaWriteRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / POOLSAVE_FILENAME
        path.write_bytes(rehearsal.files[POOLSAVE_FILENAME])
        return [path]


class DosToAmiga(Direction):
    """A DOS save becomes an Amiga disk holding the saved game, for any title in
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
        self.deltas = deltas
        self.source_key = deltas.key
        self.destination_game = deltas

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                names: "Mapping[int, str] | None" = None,
                leave: "Mapping[int, Collection[int]] | None" = None,
                disk_one: "str | pathlib.Path | None" = None) -> AmigaWriteRehearsal:
        if leave and self.deltas is not dos_port.SECRET_OF_THE_SILVER_BLADES:
            # Only Silver Blades' joined scrolls can pass an Amiga limit; a
            # choice of what to leave behind means nothing to another title.
            raise saveplan.SaveAsError(
                f"{self.source_port} to {self.destination_port} has no "
                f"pack to leave anything of")
        if not source.slot:
            # Unreachable through `Source.detect`, whose DOS branches always
            # name a slot; only a caller building a `Source` by hand can get
            # here, mirroring `AmigaToDos.rehearse`'s own guard.
            raise ConvertError(f"{source.path} names no DOS save slot")
        letter = source.slot
        game_data = _amiga_destination_data(self.deltas, options, source)
        with source.folder() as folder:
            raw_party = dos_codec.read_party(folder, letter)
            container = dos_savegame.container_for(self.deltas.key)
            savgam_path = pathlib.Path(folder) / (
                f"SAVGAM{letter}{container.suffix}")
            savgam = savgam_path.read_bytes()
        party = [c64_codec.living_player(dos_codec.to_neutral(c))
                 for c in raw_party]
        # Cannot fire today: a DOS name is at most fifteen characters and an
        # Amiga field holds the same fifteen (`amiga_por._por_name_bytes`).
        # Called anyway, so a direction added later does not have to
        # remember to.
        party = saveplan.fit_names(
            party, self.destination_port, self.deltas.key, names)
        # `amiga_combat_icon` is duck-typed to `goldbox.dos_codec.DosCharacter`
        # too (its own docstring) and reads the icon straight off the raw
        # record, before `dos_codec.to_neutral` discards it -- the same form
        # `AmigaToDos.rehearse` already uses for an Amiga source (#424,
        # mirroring #422's fix for a C64 source).
        icons = [amiga_combat_icon(c) for c in raw_party]
        # Named for the player's own save rather than for the scratch copy a
        # snapshot is read through: the name only ever labels the state.
        state = world_state.from_dos(
            savgam, container,
            source=str(pathlib.Path(source.path) / savgam_path.name))
        return _rehearse_amiga_savegame(
            state, self.deltas, letter, party, game_data, icons=icons,
            disk_one=disk_one, leave=leave)

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
#: names a title `DOS_TO_C64_NAMES` does not; `titles.UnknownTitleError` does
#: the same for `WRITES` and a title with no C64 game at all.
#: The DOS forms with a C64 port on the other side.
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
#: that does have one: a title `games` knows and `DOS_TO_C64_NAMES` does not
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
    deltas for deltas in dos_codec.CONVERTS if deltas.key in c64_port.BY_KEY)

DIRECTIONS: tuple[Direction, ...] = tuple(
    DosToC64(deltas) for deltas in C64_PAIRED
) + tuple(
    C64ToDos(deltas) for deltas in C64_PAIRED
) + tuple(
    AmigaToC64(deltas) for deltas in amiga_shared.CONVERTS
) + tuple(
    AmigaToDos(deltas) for deltas in amiga_shared.CONVERTS
) + tuple(
    C64ToAmiga(deltas) for deltas in amiga_shared.WRITES
) + tuple(
    DosToAmiga(deltas) for deltas in amiga_shared.WRITES
) + (
    PodAmigaToDos(),
    PodDosToAmiga(),
)


def destinations_for(source: Source) -> list[Direction]:
    """Every registered direction this source can be converted to.

    Empty for anything not in `DIRECTIONS`.  An unready direction is never
    offered and never blocked.
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
# Strings used outside this module.
# ---------------------------------------------------------------------------

#: `goldbox.dos_codec.CANNOT_CONVERT`, approved under `#195 (The import pane shows
#: a player a memory address when the conversion blocks for any reason but
#: the wrong title)` on 2026-09-02. It names a source Wish cannot read, or a
#: rehearsal failure that has no `dos_codec.DosRecordError.player_message`.
CANNOT_CONVERT = dos_codec.CANNOT_CONVERT


#: The sentence for a Treasures of the Savage Frontier folder, which no
#: title row names and which is never to be read.
TREASURES_UNSUPPORTED = (
    f"{titles.TREASURES_OF_THE_SAVAGE_FRONTIER_TITLE} saves are not supported.")


def unsupported_save_sentence(title: str) -> str | None:
    """"[Game title] saves are not yet supported." for a title the editor
    cannot read, or None for one it can; Treasures of the Savage Frontier,
    which will not be read, gets `TREASURES_UNSUPPORTED`.

    "Cannot read" is a title with no row in `goldbox.c64_codec.DELTAS_BY_KEY`
    and no reader of its own; Pools of Darkness has one. The sentence is built from the title table's own names.
    """
    if title == titles.TREASURES_OF_THE_SAVAGE_FRONTIER_TITLE:
        return TREASURES_UNSUPPORTED
    for known in titles.TITLES:
        if known.key == titles.POOLS_OF_DARKNESS.key:
            continue
        if known.title == title and known.key not in c64_codec.DELTAS_BY_KEY:
            return f"{title} saves are not yet supported."
    return None
