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
* C64 `.D64` → DOS save folder, one row per entry of `goldbox.dos.WRITES` --
  the same three titles (`goldbox.dos.new_dos_save`; Pool of Radiance proven
  in DOSBox by `tools/dosnewsave.py` under `#26 (Write a DOS save, not just
  read one)`, Curse of the Azure Bonds and Secret of the Silver Blades by
  `#299 (goldbox.dos.write builds only Pool of Radiance's record, so nothing
  can be converted to DOS for the later titles)`, whose container writer this
  registry was waiting on, and `#234 (A dual-classed Curse or Silver Blades
  character converted to DOS loses the class he trained out of)`, whose own
  dual-classed Curse character loaded from a save this direction writes);
* Amiga `.adf` → C64, one row per entry of `goldbox.amiga.CONVERTS` -- Pool
  of Radiance alone (`goldbox.amiga.read_por_slot` then
  `goldbox.dos.new_save_from`, proven in VICE by
  `#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
  standing in the Slums on the Amiga arrives there in VICE)`);
* Amiga `.adf` → DOS save folder, one row per entry of
  `goldbox.amiga.CONVERTS` -- Pool of Radiance alone
  (`goldbox.amiga.read_por_slot` then `goldbox.dos.new_dos_save_from`,
  proven in DOSBox by
  `#354 (Convert an Amiga Pool of Radiance save to DOS, so a party standing
  in the Slums on the Amiga arrives there under DOSBox)`).

**This registry derives every row from a library tuple rather than listing
them, which is the point:** DOS → C64 from `goldbox.dos.CONVERTS`, C64 → DOS
from `goldbox.dos.WRITES`, both Amiga rows from `goldbox.amiga.CONVERTS`; a
title joins one of those tuples when its writer exists, and it appears here
with no edit to this module. `DOS_TO_C64_NAMES` below is the one thing
`CONVERTS` does not carry -- the `.D64` file name each title's DOS → C64
conversion writes -- and a `CONVERTS` entry missing a row there fails loudly
when `DIRECTIONS` is built, at import time, rather than answering `[]` for a
title the library can actually write. `WRITES` needs no such table: a C64 →
DOS conversion always writes the same file names (`SAVGAM<slot>.DAT`,
`CHRDAT<slot><n>.SAV`...), whatever the title, so `games.by_key(shape.key)`
-- which already raises loudly on a key with no C64 game -- is the whole of
the check that direction needs.

**The source is a path, not the open window.** `Source.detect` reads a
`.D64`, an Amiga `.adf`, a `SAVGAM<slot>.DAT`/`.PTY` file, or a DOS save
folder directly, the way `tools/dosdisk.py` and `tools/dosnewsave.py`
already do. When the path is
the save the editor already has open, the caller passes `party` and this
reads its in-memory bytes instead, so unsaved edits cross -- the same rule
`exports.Source.from_party` followed. `exports.Source` retires into this one
at step 5.

**`ConvertDialog`, below, is step B of `#52 (File ▸ Import and File ▸ Export for every direction the library supports)`'s plan comment** (also
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

from goldbox import amiga, dos, dos_layout, games

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
    `goldbox.dos_layout.DosShape` for a DOS or an Amiga one; both carry
    `.key`, which is what `Direction.source_key` matches against.
    `save0`/`save1`/`disk` are set only for a C64 source -- a DOS source is a
    folder and an Amiga source is an `.adf`, each read fresh by whichever
    `Direction` converts it. `slot` is the save slot the source was detected
    at -- the letter in `SAVGAM<slot>.DAT`/`.PTY`, or the Amiga slot letter
    in `savgam<slot>.dat`; it stays `None` for a C64 source, which has none.

    `available_slots` is every slot the source actually holds files for --
    `None` for a DOS or a C64 source, which the dialog's own save picker or
    file choice already names exactly one slot for (`_SAVGAM_FILE_RE`'s
    comment). An Amiga `.adf` has no per-file equivalent: every slot lives
    inside the one image, so this is what the dialog's slot row
    (`#372 (An Amiga disk with more than one saved game converts its first
    slot, whichever one the player meant)`) is built from, and it is a list
    of one for an Amiga disk that only ever had one game saved to it.
    """

    port: str                      # "c64", "dos" or "amiga"
    title: Any
    path: pathlib.Path
    save0: bytes | None = None
    save1: bytes | None = None
    disk: bytes | None = None
    slot: str | None = None
    available_slots: list[str] | None = None

    @property
    def key(self) -> str:
        return self.title.key

    @classmethod
    def detect(cls, path: str | pathlib.Path, party: Any = None,
              slot: str | None = None) -> "Source":
        """A `.D64`, an Amiga `.adf`, a DOS save folder, or the party
        already open at `path`.

        `party` is a duck-typed `editor.roster.Party` -- `.path`, `.game`,
        `.save0`, `.save1`, `.disk` -- and is used only when its own path is
        the one asked for, so unsaved edits on screen cross into the
        conversion instead of whatever is on disk.

        `slot` names which of an Amiga disk's several saved games to read --
        the dialog's own slot row passes the letter the player chose. Every
        other branch ignores it: a C64 disk holds one saved game, a DOS
        folder or file already names its own slot, and neither has a row to
        pick a different one from.
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
            if path.suffix.lower() == AMIGA_SUFFIX:
                return cls._detect_amiga_disk(path, slot)
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

        `goldbox.amiga.por_slots_present` asks which slots have files rather
        than which the game's own picker offers, since a slot the picker
        lists and the disk has lost the files for is not one this can
        convert. Every slot it finds is kept as `available_slots`, which is
        what the dialog's slot row lists (`#372 (An Amiga disk with more
        than one saved game converts its first slot, whichever one the
        player meant)`) -- a DOS folder has no row because `SAVGAM<slot>.DAT`
        picked directly already names its own slot; an `.adf` has no
        per-file equivalent, since every slot lives inside the one image.
        A `slot` the disk does not actually hold files for is treated the
        same as none named, rather than raised on -- the combo below is
        always built from `available_slots`, so this can only happen when a
        caller other than the dialog hands in a stale letter.

        The title comes off the chosen slot's own character record length
        (`goldbox.amiga.amiga_shape_for`), never assumed -- so an Amiga
        Curse or Silver Blades disk is detected as itself and simply has no
        registered destination yet, rather than being read as a Pool of
        Radiance save it never was.
        """
        from goldbox.amiga_adf import AmigaDisk, AmigaDiskError

        try:
            disk = AmigaDisk.open(str(path))
            slots = amiga.por_slots_present(disk)
        except (AmigaDiskError, amiga.AmigaRecordError, OSError) as exc:
            raise ConvertError(str(exc)) from exc
        if not slots:
            raise ConvertError(f"{path} holds no Amiga saved game")
        chosen = slot if slot in slots else slots[0]
        try:
            record = disk.read_file(amiga.por_save_path(
                amiga.por_filename(chosen, 1), amiga.por_save_drawer(disk)))
            shape = amiga.amiga_shape_for(len(record))
        except (AmigaDiskError, amiga.AmigaRecordError) as exc:
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


class AmigaToC64(DosToC64):
    """An Amiga `.adf` becomes a C64 `.d64`, for any title in
    `goldbox.amiga.CONVERTS` (#353).

    You save on the Amiga standing in the Slums at 21:22 with half the
    quests done, and the party arrives in the Slums at 21:22 with the same
    quests done. The six characters have crossed since 2026-08-26
    (`goldbox.amiga.to_neutral` then `goldbox.c64_codec.write`, 90 of 90
    sheet fields); what this adds is the game around them.

    **Everything but `rehearse` is `DosToC64`'s**, and deliberately: the
    destination is the same `.d64` written by the same engine
    (`goldbox.dos.write_c64_save`) to the same file name, so `__init__`'s
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
                options: "dosimport.GameFiles") -> Rehearsal:
        from goldbox.amiga_adf import AmigaDisk

        disk = AmigaDisk.open(str(source.path))
        party, savgam = amiga.read_por_slot(disk, slot)
        state = amiga.read_por_state(
            savgam, source=f"{source.path} slot {slot}")
        save0, save1, report = dos.new_save_from(
            state, party, options.icon, options.animate,
            portraits=options.portraits, game=self.destination_game)
        image = dos.save_disk(bytes(save0), bytes(save1),
                              self.destination_game)
        name = self._name.format(slot=slot)
        return Rehearsal(report, {name: image.to_bytes()})


@dataclasses.dataclass
class DosWriteRehearsal(Rehearsal):
    """What `C64ToDos.write` needs to run the conversion again.

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
    #: The source C64 title's own `IconParts` (`goldbox.iconparts`), so the
    #: second run in `write` recognises the same combat icons the rehearsal
    #: did -- `None` when the dialog could not read the source disk, in
    #: which case this direction writes exactly what it wrote before #383.
    icon_parts: "Any | None" = None


class C64ToDos(Direction):
    """A C64 save becomes a DOS save folder, for any title in
    `goldbox.dos.WRITES` (#26, #299, #234).

    One instance per entry of `WRITES` -- see `DIRECTIONS` below -- so a
    title joining that tuple needs no edit to this class.  `goldbox.dos.
    new_dos_save` is the no-template call for every title alike; `title=`
    is what tells it which one, since Curse of the Azure Bonds and Secret
    of the Silver Blades write the same 7424-byte C64 payload and only the
    title says which DOS container it becomes (`goldbox.dos.c64_title`).
    `options` is the DOS game directory `ECL<n>.DAX` lives in -- mandatory,
    since a Curse party's own area script has to be staged or the game
    exits to DOS on load; Silver Blades stages none and Pool of Radiance's
    own area machinery is unchanged.

    `icon_parts` is `goldbox.dos.new_dos_save`'s own argument -- the source
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

    def __init__(self, shape: dos_layout.DosShape):
        self.shape = shape
        self.source_key = shape.key
        self.destination_game = shape
        # Raises `games.UnknownGameError` at import time (via `DIRECTIONS`
        # below) if `WRITES` ever named a title with no C64 port -- the
        # loud failure `DOS_TO_C64_NAMES` gives the other direction, with no
        # table of its own needed: a C64 → DOS conversion writes the same
        # file names whatever the title.
        self.title = games.by_key(shape.key)

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path",
                icon_parts: "Any | None" = None) -> DosWriteRehearsal:
        game_dir = pathlib.Path(options)
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos.new_dos_save(source.save0, source.save1,
                                      scratch_path, slot, game_dir,
                                      title=self.title,
                                      icon_parts=icon_parts)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return DosWriteRehearsal(report, files, source.save0, source.save1,
                                 slot, game_dir, icon_parts)

    def write(self, rehearsal: DosWriteRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        dos.new_dos_save(rehearsal.save0, rehearsal.save1, folder,
                         rehearsal.slot, rehearsal.game_dir, title=self.title,
                         icon_parts=rehearsal.icon_parts)
        return sorted(folder / name for name in rehearsal.files)


def amiga_combat_icon(char: Any) -> Any:
    """One Amiga character's own combat figure, in the DOS record's terms.

    Any of the three Amiga Gold Box titles keeps `icon_head`, `icon_body`
    and the six `icon_colours` bytes at the same DOS offsets its own
    `.get()` reads through -- `goldbox.amiga.AmigaPorCharacter` re-cuts a
    Pool of Radiance record into the DOS one (`goldbox.amiga.to_dos_record`,
    #354) and `goldbox.amiga.AmigaCharacter` reads a Curse or Silver Blades
    one through its own shift map (#396, docs/199-amiga-combat-icons.md) --
    so the figure a player drew on the Amiga is already the number DOS
    stores, in all three titles: nothing is recognised, composed or looked
    up. `char` is duck-typed to either -- and to `goldbox.dos.DosCharacter`,
    which shares the same `.get()`.  What it is **not** is a neutral field:
    `goldbox.dos.to_neutral` and `goldbox.amiga.to_neutral_later` both have
    nowhere to put it, since the C64 stores drawn cells rather than an
    index, so a party read into neutral records and written back out would
    arrive with six identical default figures.  That is `#130 (A converted
    DOS party arrives with six identical combat figures, not its own)` in
    this direction, and this is what stops it: `goldbox.dos.write`'s own
    `icon` argument, which bypasses the neutral vocabulary for exactly this
    reason, and which `goldbox.amiga.write_later` now takes as well.

    **`figure_source` and `colours_source` say so**, rather than the sentence
    `goldbox.dos.write` used to build unconditionally around any `DosIcon`,
    which claimed every figure was recognised off eighteen C64 screen codes
    -- true for `IconParts.dos_icon_from_c64`'s own `DosIcon` and false for
    this one. `#379 (The DOS writer's byte accounting says an Amiga party's
    combat figure was recognised off C64 screen codes)` moved that sentence
    here, to the builder that knows which port it is describing.

    **`choice` is left `None`.** It answers `IconParts.recognise`'s question
    -- which C64 weapon and head option drew this icon -- and an Amiga
    source has no C64 icon behind it to have recognised one from; `body` and
    `head` are DOS numbers already, not menu positions in either of the
    C64's two option lists, so there is no real `IconChoice` to construct.
    """
    from goldbox.iconparts import DosIcon

    head, body = char.get("icon_head"), char.get("icon_body")
    figure_source = (
        "the Amiga source record's own combat icon, already stored as "
        "these DOS icon_head/icon_body numbers and copied across unchanged "
        "(#354, #396, goldbox.amiga)")
    colours_source = (
        "the Amiga source record's own combat icon colours, already "
        "stored as these DOS icon_colours pairs and copied across "
        "unchanged (#354, #396, goldbox.amiga)")
    # `.get()`, not `.raw()`: a `DosCharacter`'s two methods return the same
    # bytes for a RAW-kind field like `icon_colours`, but `AmigaCharacter`
    # (Curse and Silver Blades, #396) has no `.raw(name)` method -- its own
    # `raw` is the record's bytes, not a lookup -- so `.get()` is the one
    # spelling that works on every port this function is handed.
    return DosIcon(head=head, body=body,
                   colours=bytes(char.get("icon_colours")),
                   figure_source=figure_source,
                   colours_source=colours_source)


@dataclasses.dataclass
class AmigaDosRehearsal(Rehearsal):
    """What `AmigaToDos.write` needs to run the conversion again.

    `DosWriteRehearsal`'s sibling, and for the same reason: `goldbox.dos.
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
    game_dir: pathlib.Path


class AmigaToDos(C64ToDos):
    """An Amiga `.adf` becomes a DOS save folder, for any title in
    `goldbox.amiga.CONVERTS` (#354).

    You save on the Amiga standing in the Slums at 21:22 with half the
    quests done, and the party arrives in the Slums at 21:22 with the same
    quests done under DOSBox.  The six characters have crossed since
    2026-08-26; what this adds is the game around them -- the area, the
    party's own square, the facing, the clock and the 217 quest flags.

    **`__init__` is `C64ToDos`'s**, and deliberately, the way `AmigaToC64`
    takes `DosToC64`'s: the destination is the same DOS save folder written
    by the same engine to the same file names, so the shape lookup and the
    `games.by_key` check that fails loudly at import time are one
    implementation rather than two.  What differs is where the party and
    the place are read from, which is `rehearse`, and that
    `goldbox.dos.new_dos_save_from` takes them directly where
    `new_dos_save` reads them out of a C64 payload first.

    **Two slots, and they are not the same letter.**  `slot` is the DOS
    slot being written -- always `"A"` from the dialog, since a fresh DOS
    folder has no slot to inherit -- and `source.slot` is the Amiga slot
    being read.  Handing one where the other belongs converts whichever
    Amiga slot happens to share the DOS letter, which on a disk with two
    saved games is a different party.

    `options` is the DOS game directory `ECL<n>.DAX` lives in, exactly as
    the C64 → DOS row takes it; the dialog already shows that row for any
    DOS destination (`_settle_game_row`), so this needs nothing new there.
    """

    source_port = "amiga"

    def rehearse(self, source: Source, slot: str,
                options: "str | pathlib.Path") -> AmigaDosRehearsal:
        from goldbox.amiga_adf import AmigaDisk

        if not source.slot:
            # Unreachable through `Source.detect`, whose `.adf` branch always
            # names the first slot the disk holds files for; only a caller
            # building a `Source` by hand can get here, and there is no Amiga
            # slot to guess at for it.
            raise ConvertError(f"{source.path} names no Amiga save slot")
        game_dir = pathlib.Path(options)
        disk = AmigaDisk.open(str(source.path))
        party, savgam = amiga.read_por_slot(disk, source.slot)
        state = amiga.read_por_state(
            savgam, source=f"{source.path} slot {source.slot}")
        # The Amiga file order **is** the DOS file order (`docs/165-amiga-
        # savegame.md`), so there is no reversal here; `goldbox.dos.
        # marching_slot` and `c64_party`'s own `reverse()` are the C64's
        # business and `#101`'s.
        characters = [dos.to_neutral(c) for c in party]
        icons = [amiga_combat_icon(c) for c in party]
        with tempfile.TemporaryDirectory(prefix="wish-convert-") as scratch:
            scratch_path = pathlib.Path(scratch)
            report = dos.new_dos_save_from(state, characters, scratch_path,
                                           slot, game_dir, icons=icons)
            files = {p.name: p.read_bytes()
                    for p in sorted(scratch_path.iterdir())}
        return AmigaDosRehearsal(report, files, state, characters, icons,
                                 slot, game_dir)

    def write(self, rehearsal: AmigaDosRehearsal,
             folder: str | pathlib.Path) -> list[pathlib.Path]:
        folder = pathlib.Path(folder)
        dos.new_dos_save_from(rehearsal.state, rehearsal.characters, folder,
                              rehearsal.slot, rehearsal.game_dir,
                              icons=rehearsal.icons)
        return sorted(folder / name for name in rehearsal.files)


#: One DOS → C64 row per entry of `goldbox.dos.CONVERTS`, one C64 → DOS row
#: per entry of `goldbox.dos.WRITES` -- today Pool of Radiance, Curse of the
#: Azure Bonds and Secret of the Silver Blades, both ways -- and one
#: Amiga → C64 row per entry of `goldbox.amiga.CONVERTS`, today Pool of
#: Radiance alone. See the module docstring for what would extend this and
#: the issues it waits on.
#: `UnnamedConversionError` fires here, at import time, if `CONVERTS` ever
#: names a title `DOS_TO_C64_NAMES` does not; `games.UnknownGameError` does
#: the same for `WRITES` and a title with no C64 game at all.
DIRECTIONS: tuple[Direction, ...] = tuple(
    DosToC64(shape) for shape in dos.CONVERTS
) + tuple(
    C64ToDos(shape) for shape in dos.WRITES
) + tuple(
    AmigaToC64(shape) for shape in amiga.CONVERTS
) + tuple(
    AmigaToDos(shape) for shape in amiga.CONVERTS
)


def destinations_for(source: Source) -> list[Direction]:
    """Every registered direction this source can be converted to.

    Empty for anything not in `DIRECTIONS` -- an Amiga Curse or Silver
    Blades disk, a C64 save with no Amiga writer registered -- which is the
    whole point: an unready direction is never offered and never refused.
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
#: **Lifted once, on 2026-09-07 (`e9e4bac`), and put back the same night.**
#: The five conditions below were all met and every one of them was a
#: property of the code -- directions registered, drop panes clear, no
#: unapproved string reachable. None asked whether a person could actually
#: reach the dialog. Donald: *"When I pick File->Convert, it still
#: immediately opens a file picker dialog."* Two more conditions join the
#: five for that reason, and this flag stays on until both are met.
#:
#: **Comes off when, all seven:** (1) no string below carries the
#: `(NOT APPROVED)` marker -- met 2026-09-05, kept met by
#: `test_no_string_the_player_reads_is_unapproved`; (2) a Pool of Radiance, a
#: Curse and a Silver Blades DOS save each list the Commodore 64, and a Pools
#: of Darkness save never does -- met 2026-09-07,
#: `test_a_pool_of_radiance_savgam_file_lists_c64_and_records_its_slot`,
#: `test_a_curse_or_silver_blades_savgam_file_lists_c64`,
#: `test_a_curse_or_silver_blades_d64_lists_dos` and
#: `test_a_pools_of_darkness_folder_lists_nothing`; (3) every registered
#: direction's drop list is empty or accounts for a named, tracked line
#: rather than a silent one -- met 2026-09-07,
#: `#355 (A C64 party converted to DOS is shown nine developer notes, with
#: memory addresses, overlay names and issue numbers in them)` and
#: `#388 (A converted paladin or ranger loses his innate effect on the way to
#: DOS, because the writer filters through Pool of Radiance's id list)` both
#: closed; (4) the README says how the source picker works -- waived by
#: Donald, 2026-09-07: *"I will update the README, but don't wait on that to
#: remove WISH_EXPERIMENTAL_CONVERT and close the related tickets. It is a
#: simple interface, and people will figure it out."*; (5) each registered
#: direction has been loaded and walked in its emulator from a save this
#: dialog's own code path wrote -- met 2026-09-07, eight of eight, `#52`'s
#: own comments; (6) `File ▸ Convert…` opens the Convert window directly,
#: with no file picker in front of it -- met 2026-09-07 by this same change,
#: `#412 (File ▸ Convert demands a save in a file picker before it will show
#: you the Convert window)`; (7) `File ▸ Import ▸ DOS save folder` is
#: removed, since two menu items doing the same job is the state this dialog
#: exists to end -- `#52`'s own step 5. **Not met.** Removing it needs
#: `editor/dosimport.py`, which this change does not touch.
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

#: The File menu entry. Approved by Donald 2026-09-05, with every other
#: string in this block: *"I think these are all fine."*  The two submenus
#: it replaces were `&Import` and `&Export`, and this dialog is neither.
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
LABEL_FOLDER = "Write to"

#: The heading above the report pane. Donald's own words, 2026-09-07, from
#: reviewing the Amiga-row mock-up for `#316 (Write the Amiga Pool of
#: Radiance saved game from the source save, so a converted party arrives
#: where it was standing)`: *"It gains a label above it reading `Convert
#: Log`."* Not marked unapproved -- he supplied the text himself.
LABEL_REPORT = "Convert Log"

#: The slot row's label, shown only when the source names more than one
#: saved game -- today an Amiga `.adf`, the source port that has no other
#: way to say which slot (`#372 (An Amiga disk with more than one saved game
#: converts its first slot, whichever one the player meant)`).
LABEL_SLOT = "Slot"

#: One combo item per slot `Source.available_slots` lists, `{slot}` the
#: letter `read_por_slot` takes.
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

#: The destination combo's items, by port -- never by title, since
#: `destinations_for` never offers two directions of the same port for one
#: source (`.claude/rules/conversions.md`: a conversion never crosses a
#: title). PROPOSED. Amiga has no row yet (`#316 (Write the Amiga Pool of
#: Radiance saved game from the source save, so a converted party arrives
#: where it was standing)`), so it is not listed here until it can be
#: exercised.  Approved 2026-09-05.
DESTINATION_LABELS: dict[str, str] = {
    "c64": "Commodore 64",
    "dos": "DOS",
}

#: The pane while a required row is still empty.
NO_GAME_FOLDER = "Choose the DOS game folder."
#: `editor/exports.py`'s `NO_DESTINATION`, approved 2026-08-25.
NO_FOLDER = "Choose where to write."
#: `goldbox.dos.CANNOT_CONVERT`, approved under `#195 (The import pane shows
#: a player a memory address when the conversion refuses for any reason but
#: the wrong title)` on 2026-09-02 -- reused rather than a second sentence
#: meaning the same thing, for a source with no registered destination, for
#: `Source.detect` failing, and for anything `rehearse` raises that is not a
#: `dos.DosRecordError` with its own `player_message`.
CANNOT_CONVERT = dos.CANNOT_CONVERT
#: `editor/dosimport.py`'s `NO_DISKS`/`NO_DISKS_TITLE`. The title is Donald's
#: of 2026-08-27; the line is his of 2026-09-05, rewritten when
#: `#342 (A Curse or Silver Blades save cannot be converted unless its C64
#: sides sit in the Pool of Radiance disk folder)` gave each title its own
#: folder and the old wording named `File ▸ Import` and one shared folder.
NO_DISKS = dosimport.NO_DISKS
NO_DISKS_TITLE = dosimport.NO_DISKS_TITLE
#: Donald's own wording, `09027bb` (2026-09-05) -- shared with
#: `editor/dosimport.py`'s and `editor/exports.py`'s `DROPPED_HEADING`, one
#: conversion vocabulary whichever way it is going. **Not drawn by this
#: dialog's own pane** since `#416` moved it onto `dosimport.pane_text`,
#: which puts drop lines under `LABEL_REPORT` with no heading of their own
#: -- the same shape `editor/dosimport.py`'s own dialog already draws. Kept
#: defined for whichever caller still names it.
DROPPED_HEADING = dosimport.DROPPED_HEADING
#: `editor/exports.py`'s `WRITES_HEADING`, approved 2026-08-25.
WRITES_HEADING = "This writes:"

#: The status line after a DOS write, which nothing else in the window
#: reports (a C64 write is opened in the editor and gets its own status the
#: way `File ▸ Open` does). Approved 2026-09-05.
CONVERTED_DOS = "Converted to DOS slot {slot} in {folder}"


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

    #: How tall the report pane is, in lines of its own font. Donald,
    #: 2026-09-07: "The report pane gets smaller."
    REPORT_LINES = 6

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
        self._wanted_slot: str | None = None
        self._game_path = game
        self._folder_path = folder
        self._rebuilding_combo = False
        self._rebuilding_slot_combo = False

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

        self.ui.convert_slot.currentIndexChanged.connect(self._slot_changed)

        self.ui.convert_destination.currentIndexChanged.connect(
            self._destination_changed)

        self.ui.convert_game.setText(self._game_path or "")
        self.ui.convert_choose_game.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_game.clicked.connect(self._choose_game)

        self.ui.convert_folder.setText(self._folder_path or "")
        self.ui.convert_choose_folder.setText(BUTTON_CHOOSE)
        self.ui.convert_choose_folder.clicked.connect(self._choose_folder)

        self.ui.label_report.setText(LABEL_REPORT)
        #: Donald, 2026-09-07: "The report pane gets smaller." A fixed
        #: number of the pane's own font's lines, the way
        #: `editor.window.CharacterEditor.HEADER_LINES` sizes the character
        #: header, rather than a pixel count that would only mean this
        #: machine's font (`.claude/rules/testing.md`). Longer content still
        #: scrolls; nothing it prints is lost.
        metrics = self.ui.convert_report.fontMetrics()
        self.ui.convert_report.setMaximumHeight(
            self.REPORT_LINES * metrics.height()
            + 2 * self.ui.convert_report.frameWidth())

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
            self._wanted_slot = None
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

    def _slot_changed(self, _index: int) -> None:
        if self._rebuilding_slot_combo:
            return
        self._wanted_slot = self.ui.convert_slot.currentData()
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
            self._populate_slots(None)
            self.ui.convert_report.setPlainText("")
            self._settle_game_row()
            self._settle_button()
            return

        try:
            self.source = Source.detect(self._source_path, party=self.party,
                                        slot=self._wanted_slot)
            options = destinations_for(self.source)
        except Exception:
            _log.exception("could not read %s", self._source_path)
            self._populate_destinations([])
            self._populate_slots(None)
            self.ui.convert_report.setPlainText(CANNOT_CONVERT)
            self._settle_game_row()
            self._settle_button()
            return

        self._populate_destinations(options)
        self._populate_slots(self.source)
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
            if direction.source_port == "c64" and direction.destination_port == "dos":
                # The source title's own `SPELLE64`/`SPELLN64` -- the same
                # lookup `game_files_for` already does for a C64
                # *destination*'s icon table, keyed here by the *source*'s
                # title instead (`direction.title`, `C64ToDos.__init__`).
                # `None` when the player's disks do not carry it: the
                # conversion still runs, exactly as before #383, and every
                # figure comes out the game's own default.
                source_files: Any = self._game_files(direction.title)
                icon_parts = (source_files.icon
                             if source_files is not None else None)
                self.rehearsal = direction.rehearse(
                    self.source, slot, options, icon_parts=icon_parts)
            else:
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
        #: `dosimport.pane_text`, not `dropped_text` -- the same function
        #: `editor/dosimport.py`'s own dialog draws, so the two cannot drift
        #: on what a conversion tells the player (`#416 (The live Convert
        #: dialog never shows a DOS→C64 conversion's own messages or
        #: capacity-ceiling warnings)`).  It reads `report.messages` (what
        #: Wish did to the player's own save) and `report.losses` (a genuine
        #: platform ceiling a character's own data hit, #399) ahead of
        #: `report.dropped`, and is empty when there is nothing to say
        #: (`#338 (The conversion pane says fields could not be converted
        #: and then lists none)`) -- joining it unconditionally would leave
        #: two blank lines above what it writes, which a player reads as
        #: something missing.
        report_text = dosimport.pane_text(self.rehearsal.report)
        writes = _writes_text(self.rehearsal, preview)
        return f"{report_text}\n\n{writes}" if report_text else writes

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
        """The slot row: shown only when the source names more than one
        saved game (`#372 (An Amiga disk with more than one saved game
        converts its first slot, whichever one the player meant)`) -- an
        Amiga `.adf` today, since a DOS folder or file already names its own
        slot through the save picker and has nothing to list here.

        Rebuilt from `source.available_slots` every `replan()`, the way
        `_populate_destinations` rebuilds the destination combo from
        `destinations_for` -- so a source with one slot never shows a combo
        of one, and switching to a source with several grows it back."""
        combo = self.ui.convert_slot
        slots = source.available_slots if source is not None else None
        show = bool(slots) and len(slots) > 1
        self.ui.form.setRowVisible(self.ui.convert_slot, show)
        if not show:
            return
        self.ui.label_slot.setText(LABEL_SLOT)
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

    def _settle_game_row(self) -> None:
        """The game-files row is shown only for a DOS destination -- the C64
        disks are a Preferences setting already, whichever port the source
        is, so the Amiga → C64 row needs no picker of its own either
        (`#52`'s plan, "three C64 titles means the disks are chosen by the
        destination title"). A row for an Amiga *destination* would need
        one, since that conversion reads `ecl.dax` off the player's own disk
        2 -- `#316 (Write the Amiga Pool of Radiance saved game from the
        source save, so a converted party arrives where it was standing)`,
        which has no row here yet."""
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
