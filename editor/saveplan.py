"""The open party's own saved game, with every pending edit in it.

The editor's sheet binds to the C64 record on every port, and a DOS or an
Amiga character is more than the sheet can show: the port's own record, its
item file, its effect file, and every byte of the save nobody has named. So a
conversion that reads the save off disk converts what was *opened* rather than
what is on screen, and one that rebuilt the save from the sheet alone would
drop everything outside it.

A `Snapshot` is the third answer. Each character's port-native bytes are
rewritten through `goldbox.rewrite`: only the field spans where the sheet's
record and the record it was built from disagree are copied, so every byte the
editor never named keeps the engine's own value, and a party with nothing
edited comes back byte for byte (`docs/223-the-differential-rewrite.md`). What
comes out is the whole saved game, in memory.

**Preparing one writes nothing.** Not the files it was read from, not the
editor's own baselines -- `Member.record_original`, `Inventory.original`,
`EditorBinding.dirty` -- and not the payload a C64 save is held in.
`EditorBinding._write_back` shares this assembly rather than repeating it,
which is what keeps a snapshot and a Save producing the same bytes.

The second half of this module is the Save As over that snapshot, in three
steps a caller takes in order: `resolve_assets` finds whatever game data the
route needs off the player's own disks, `prepare_save_as` rehearses the whole
output in memory and refuses a conversion that would lose a field, and
`publish` puts the prepared bytes where the player asked and opens them again
as the document to adopt. Nothing on disk changes before the last of the
three, and a `Published` knows how to undo itself if adoption then fails.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import pathlib
import re
import shutil
import tempfile
from typing import Any

from goldbox import amiga_por, amiga_savegame, rewrite
from goldbox.d64 import D64
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0, SaveGame1, store_save

from . import files as editor_files

_log = logging.getLogger("wish.editor.saveplan")

#: The file names one DOS saved game is made of: `SAVGAM<slot>.DAT`/`.PTY`,
#: the six `CHRDAT<slot><n>` records with their item and effect files, and
#: Pools of Darkness' `VAULT<slot>.DAT`. Case-insensitive, because a renamed
#: copy of a save is still that save (`Source._SAVGAM_FILE_RE` reads names
#: the same way).
_SLOT_FILE = r"(?:SAVGAM{slot}|CHRDAT{slot}[1-9]|VAULT{slot})\..*"


@dataclasses.dataclass(frozen=True)
class Snapshot:
    """One saved game, in memory, with the editor's pending edits in it.

    Exactly one of the three groups below is filled, by port. `files` is a
    DOS saved game -- every file of one slot, by name, the rewritten records
    among them. `image` is a whole Amiga `.adf`. `save0`, `save1` and `disk`
    are a C64 save's two payloads and its disk image.

    `path` is where the save was read from, kept so a caller can name it;
    nothing here is written back to it.
    """

    port: str                       # "c64", "dos" or "amiga"
    title: Any
    path: pathlib.Path
    slot: str | None = None
    available_slots: list[str] | None = None
    save0: bytes | None = None
    save1: bytes | None = None
    disk: bytes | None = None
    files: dict[str, bytes] | None = None
    image: bytes | None = None


def prepare(party: Any) -> "Snapshot | None":
    """The open party's saved game with every pending edit in it.

    `party` is an `editor.roster.Party`. **None for a party with no
    `members`**, which is the duck-typed stand-in `editor.convert.Source`
    documents (`.path`, `.game`, `.save0`, `.save1`, `.disk`): there is no
    roster to read edits off, so the caller falls back to the payload bytes
    the stand-in already holds.

    Raises whatever the rewrite raises -- `goldbox.rewrite.RewriteError` for
    an edit that reaches no byte of the save, and the port's own record
    errors -- rather than returning a snapshot that has quietly lost one.
    """
    if getattr(party, "members", None) is None:
        return None
    port = getattr(party, "port", "c64")
    if port == "dos":
        return Snapshot(port="dos", title=party.source.title,
                        path=pathlib.Path(party.source.path),
                        slot=party.source.slot,
                        available_slots=party.source.available_slots,
                        files=dos_snapshot(party))
    if port == "amiga":
        return Snapshot(port="amiga", title=party.source.title,
                        path=pathlib.Path(party.source.path),
                        slot=party.source.slot,
                        available_slots=party.source.available_slots,
                        image=amiga_image(party))
    if party.save0 is None:
        return None                 # a roster disk: no saved game to snapshot
    save0, save1, disk = c64_payloads(party)
    return Snapshot(port="c64", title=party.game,
                    path=pathlib.Path(party.path),
                    save0=save0.to_bytes(),
                    save1=None if save1 is None else save1.to_bytes(),
                    disk=disk.to_bytes())


# ---------------------------------------------------------------------------
# One character, as the sheet left it
# ---------------------------------------------------------------------------

def edited_record(member: Any) -> CharacterRecord:
    """The C64 record as the sheet left it, with the current inventory in it.

    The inventory is a table of its own and does not write through the sheet,
    so `Member.record` alone is missing every item edit. The blocks go back at
    the record's own item page, which is where `Party._append_converted` read
    them from.
    """
    # Imported here because `editor.roster` imports `editor.convert`, which
    # imports this module.
    from .roster import _ITEMS_AT

    raw = bytearray(member.record.to_bytes())
    if member.inventory is not None:
        blocks = member.inventory.raws
        at = _ITEMS_AT
        raw[at:at + sum(len(block) for block in blocks)] = b"".join(blocks)
    return type(member.record).from_bytes(bytes(raw))


def original_record(member: Any) -> CharacterRecord:
    """The record the editor built from the port's own bytes, before any edit.

    The rewrite compares this rendering with `edited_record`'s and copies only
    the spans where they differ, so this is what decides which bytes of the
    save a rewrite is allowed to touch.
    """
    return type(member.record).from_bytes(member.record_original)


# ---------------------------------------------------------------------------
# DOS
# ---------------------------------------------------------------------------

def dos_files(party: Any) -> dict[str, bytes | None]:
    """Each DOS file of the open slot, rewritten, by name.

    `None` where the file should not exist at all -- a character carrying no
    items has no item file -- which is what `editor.files.save_folder` deletes
    and what a snapshot leaves out.
    """
    slot = party.source.slot
    written: dict[str, bytes | None] = {}
    for member in party.members:
        result = rewrite.rewrite_dos(member.native, original_record(member),
                                     edited_record(member))
        deltas = member.native.deltas
        stem = f"CHRDAT{slot}{member.index}"
        for suffix, data in ((".SAV", result.record),
                             (deltas.item_suffix, result.items),
                             (deltas.effect_suffix, result.effects)):
            written[stem + suffix] = data or None
    return written


def dos_snapshot(party: Any) -> dict[str, bytes]:
    """The whole DOS saved game with the edits in it, by file name.

    The slot's own files are taken as they are on disk -- the `SAVGAM`
    container above all, which the editor never converts and every conversion
    reads the place and the clock out of -- and the rewritten records are laid
    over them. A file the rewrite leaves with no bytes is dropped rather than
    written empty.
    """
    folder = pathlib.Path(party.source.path)
    pattern = re.compile(_SLOT_FILE.format(slot=re.escape(party.source.slot)),
                         re.IGNORECASE)
    files = {path.name: path.read_bytes() for path in sorted(folder.iterdir())
             if path.is_file() and pattern.fullmatch(path.name)}
    for name, data in dos_files(party).items():
        if data:
            files[name] = bytes(data)
        else:
            files.pop(name, None)
    return files


# ---------------------------------------------------------------------------
# Amiga
# ---------------------------------------------------------------------------

def write_amiga(party: Any, disk: Any) -> Any:
    """Write every member's edits into `disk`, an `.adf` already open.

    Returns the same disk. **The image is put back and the failure re-raised
    if any character refuses**: AmigaDOS allocates the replacement before it
    frees the original, so a run that stops halfway leaves a disk that is
    neither what it was nor what it meant to be.
    """
    from goldbox.amiga_adf import AmigaDiskError

    snapshot = disk.to_bytes()
    try:
        if party.source.title.key == "pool-of-radiance":
            drawer = amiga_savegame.por_save_drawer(disk)
            for member in party.members:
                result = rewrite.rewrite_amiga_por(
                    member.native, original_record(member),
                    edited_record(member))
                stem = amiga_savegame.por_save_path(
                    amiga_por.por_filename(party.source.slot, member.index, ""),
                    drawer)
                for suffix, data in ((".sav", result.record),
                                     (".itm", result.items),
                                     (".spc", result.effects)):
                    path = stem + suffix
                    if data:
                        disk.write_file(path, data)
                    else:
                        try:
                            disk.remove_file(path)
                        except AmigaDiskError:
                            pass
        else:
            save = amiga_savegame.read_slot(
                disk, party.source.slot, party.source.title.key)
            characters = list(save.characters)
            for member in party.members:
                characters[member.index - 1] = rewrite.rewrite_amiga_later(
                    member.native, original_record(member),
                    edited_record(member)).character
            disk.write_file(amiga_savegame.slot_path(
                party.source.title, party.source.slot),
                amiga_savegame.rebuild(save, characters))
    except BaseException:
        disk.restore(snapshot)
        raise
    return disk


def amiga_image(party: Any) -> bytes:
    """A copy of the party's own `.adf` with the pending edits written in.

    The disk on `party.source.path` is opened again rather than `party.disk`
    reused, so the image the editor holds is left exactly as it is.
    """
    from goldbox.amiga_adf import AmigaDisk

    return write_amiga(party, AmigaDisk.open(str(party.source.path))).to_bytes()


# ---------------------------------------------------------------------------
# C64
# ---------------------------------------------------------------------------

def apply_c64(party: Any, save0: SaveGame0) -> SaveGame0:
    """Every member's record, items and icon, into `save0`.

    Returns the payload to keep: `Party.write_items` and `Party.write_icons`
    rebuild `party.save0` rather than patching it, so the party is pointed at
    `save0` for as long as they run and put back afterwards -- which makes
    this one implementation for the write-back, where `save0` is the party's
    own payload, and for a snapshot, where it is a copy.

    An item block or an icon nobody moved is not rewritten, which is what
    keeps a save with no edit in it byte-identical.
    """
    for member in party.members:
        save0.write_record(member.index, member.record)
    live, party.save0 = party.save0, save0
    try:
        party.write_items()
        party.write_icons()
        return party.save0
    finally:
        party.save0 = live


def c64_payloads(party: Any) -> tuple[SaveGame0, "SaveGame1 | None", D64]:
    """The C64 save's two payloads and its disk image, edits included.

    All three are copies, so preparing a snapshot leaves the open document
    alone -- `store_save` folds a later title's roster back into the save
    payload and writes into the image, and neither belongs to a party that has
    not been saved.
    """
    save0 = SaveGame0.from_bytes(party.save0.to_bytes(), party.game)
    save1 = (None if party.save1 is None
             else SaveGame1(party.save1.to_bytes(), party.game))
    disk = D64.from_bytes(party.disk.to_bytes())
    save0 = apply_c64(party, save0)
    store_save(disk, save0, save1, party.game)
    return save0, save1, disk


# ---------------------------------------------------------------------------
# Save As: what it refuses
# ---------------------------------------------------------------------------

class SaveAsError(Exception):
    """A Save As that cannot go ahead, with a technical reason.

    The reason is for the debug log and for a caller to decide what to say:
    nothing here is a sentence a player reads.
    """


class MissingAssets(SaveAsError):
    """Game data this route needs and nobody has found yet.

    `missing` names each requirement -- `DESTINATION_DISKS`, `SOURCE_DISKS`,
    `DOS_GAME_FOLDER`, `AMIGA_GAME_DISK` -- in the order the caller should
    ask for them, so the caller chooses which of its own approved sentences
    fits rather than being handed one.
    """

    def __init__(self, missing: "tuple[str, ...] | list[str]"):
        self.missing = tuple(missing)
        super().__init__("this route needs " + ", ".join(self.missing))


class DroppedFields(SaveAsError):
    """The conversion would lose something, so nothing is written.

    `lost` is `report.dropped` followed by every line of `report.losses`,
    including a name the destination's own field could not hold whole. Each
    one is a high-priority defect in the conversion
    (`docs/227-editor-open-save-as.md`), never a choice to put to a player.
    """

    def __init__(self, lost: "list[str]"):
        self.lost = list(lost)
        super().__init__(f"{len(self.lost)} field(s) would be lost: "
                         + "; ".join(self.lost))


class StalePlan(SaveAsError):
    """A prepared output that no longer matches the edits, the destination or
    the assets it was prepared from."""


class RecoveryFailed(SaveAsError):
    """Undoing a publication itself failed.

    `backup` is the copy of whatever was there before, still on disk, so a
    caller can say where the player's own bytes are rather than claim nothing
    was written.
    """

    def __init__(self, message: str, backup: "pathlib.Path | None" = None):
        self.backup = backup
        super().__init__(message)


#: The destination title's own C64 game disks -- the combat icon tables and
#: `ANIMATE00`, which no save of any port carries.
DESTINATION_DISKS = "destination_disks"
#: The *source* title's own C64 game disks, for a C64 party being converted
#: away: its combat icon is screen codes out of those tables.
SOURCE_DISKS = "source_disks"
#: The DOS game folder. Every DOS destination needs one, Secret of the Silver
#: Blades included: it stages no area script (`script_bytes` is 0) and
#: `goldbox.dos_codec` still reads the folder to find which `ECL<n>.DAX`
#: holds the area the party is standing in.
DOS_GAME_FOLDER = "dos_game_folder"
#: The player's own Amiga game disk 2, for an Amiga destination that stages a
#: script off it. Silver Blades stages none and does not ask for this.
AMIGA_GAME_DISK = "amiga_game_disk"


# ---------------------------------------------------------------------------
# Save As: the route and what it needs
# ---------------------------------------------------------------------------

def destination_ports(source: Any) -> list[str]:
    """Every port a Save As of this source can write.

    Its own port first -- a native copy is always available -- then one entry
    per registered conversion, so a title the registry cannot convert still
    offers a copy of itself.
    """
    from .convert import destinations_for

    ports = [source.port]
    for direction in destinations_for(source):
        if direction.destination_port not in ports:
            ports.append(direction.destination_port)
    return ports


def route(source: Any, port: str) -> Any:
    """The `Direction` that writes `source` to `port`, or `None` for a native
    copy, which is nobody's direction."""
    from .convert import destinations_for

    if port == source.port:
        return None
    for direction in destinations_for(source):
        if direction.destination_port == port:
            return direction
    raise SaveAsError(f"no registered {source.port} to {port} conversion "
                      f"for {source.key}")


def requirements(source: Any, port: str) -> tuple[str, ...]:
    """What game data this route needs, in the order to ask for it.

    A native copy needs nothing: every byte comes from the save itself. What
    a conversion needs is per destination **and per title** -- an Amiga
    Silver Blades save stages no script, so it asks for no game disk, which
    is what the old Convert window's blanket Amiga requirement got wrong.
    """
    from .convert import amiga_needs_game_disk

    direction = route(source, port)
    if direction is None:
        return ()
    needs: list[str] = []
    if port == "c64":
        needs.append(DESTINATION_DISKS)
    elif port == "dos":
        needs.append(DOS_GAME_FOLDER)
    elif amiga_needs_game_disk(direction.shape):
        needs.append(AMIGA_GAME_DISK)
    if source.port == "c64" and port in ("dos", "amiga"):
        needs.append(SOURCE_DISKS)
    return tuple(needs)


@dataclasses.dataclass(frozen=True)
class Assets:
    """The game data one route needs, already read.

    `game_files` and `source_files` are `editor.dosimport.GameFiles` -- the
    destination title's own icon tables and `ANIMATE00`, and the source
    title's for a C64 party being converted away. `dos_folder` and
    `amiga_disk` are paths the writers read their area script out of, and
    `c64_folder` records a folder a caller named by hand rather than taking
    whatever preferences answered.
    """

    game_files: Any = None
    source_files: Any = None
    dos_folder: pathlib.Path | None = None
    amiga_disk: pathlib.Path | None = None
    c64_folder: pathlib.Path | None = None

    def has(self, requirement: str) -> bool:
        if requirement == DESTINATION_DISKS:
            return self.game_files is not None
        if requirement == SOURCE_DISKS:
            return self.source_files is not None
        if requirement == DOS_GAME_FOLDER:
            return self.dos_folder is not None
        if requirement == AMIGA_GAME_DISK:
            return self.amiga_disk is not None
        raise SaveAsError(f"{requirement} is not a known requirement")

    def token(self) -> tuple[str, ...]:
        """What a prepared output would change if this changed.

        The paths a caller named, and a digest of the one thing behind them
        that can change without the path changing -- `ANIMATE00`, read off
        whichever disk answered.
        """
        return (str(self.dos_folder or ""), str(self.amiga_disk or ""),
                str(self.c64_folder or ""),
                _digest(getattr(self.game_files, "animate", None)),
                _digest(getattr(self.source_files, "animate", None)))


def resolve_assets(source: Any, port: str, *, game_files: Any = None,
                   c64_folder: "str | pathlib.Path | None" = None,
                   dos_folder: "str | pathlib.Path | None" = None,
                   amiga_disk: "str | pathlib.Path | None" = None) -> Assets:
    """Find everything `requirements` names, or say what is missing.

    `game_files` is a callable, title -> `GameFiles | None`, which is
    `editor.window.EditorBinding.game_files_for` in the running program, so
    nothing here has to know how a player's disks are found. `c64_folder`
    overrides it for the destination's own disks when a caller has named one
    folder outright.

    Raises `MissingAssets` naming every requirement nothing answered for.
    """
    from .convert import _game_files_from_folder

    direction = route(source, port)
    needs = requirements(source, port)
    resolved = Assets(
        dos_folder=pathlib.Path(dos_folder) if dos_folder else None,
        amiga_disk=pathlib.Path(amiga_disk) if amiga_disk else None,
        c64_folder=pathlib.Path(c64_folder) if c64_folder else None)
    if DESTINATION_DISKS in needs:
        found = (_game_files_from_folder(pathlib.Path(c64_folder),
                                         direction.destination_game)
                 if c64_folder else
                 (game_files(direction.destination_game) if game_files
                  else None))
        resolved = dataclasses.replace(resolved, game_files=found)
    if SOURCE_DISKS in needs:
        found = game_files(direction.title) if game_files else None
        resolved = dataclasses.replace(resolved, source_files=found)
    missing = [need for need in needs if not resolved.has(need)]
    if missing:
        raise MissingAssets(missing)
    return resolved


# ---------------------------------------------------------------------------
# Save As: rehearsing it
# ---------------------------------------------------------------------------

def rehearse(direction: Any, source: Any, assets: Assets) -> tuple[Any, str]:
    """Run `direction` in memory, and say which slot it wrote.

    The slot is not always the source's: a C64 source has none of its own and
    a fresh DOS folder is always slot A, while a DOS source keeps its own
    letter into an Amiga disk (`editor.convert.DosToAmiga`). Nothing is
    written anywhere -- the whole output is bytes in the returned
    `Rehearsal`.

    Raises `MissingAssets` before running anything when `assets` does not
    cover what `requirements` names.
    """
    missing = [need for need in requirements(source, direction.destination_port)
               if not assets.has(need)]
    if missing:
        raise MissingAssets(missing)
    port = direction.destination_port
    if port == "c64":
        if not source.slot:
            raise SaveAsError(f"{source.path} names no save slot to convert")
        slot, options = source.slot, assets.game_files
    elif port == "amiga":
        # `C64ToAmiga` always writes A and `DosToAmiga` reads `source.slot`
        # itself; this is the letter that was actually written, so a caller
        # can name it without knowing which of the two ran.
        slot, options = source.slot or "A", assets.amiga_disk
    else:
        slot, options = "A", assets.dos_folder
    if direction.source_port == "c64" and port in ("dos", "amiga"):
        return direction.rehearse(source, slot, options,
                                  icon_parts=assets.source_files.icon), slot
    return direction.rehearse(source, slot, options), slot


def losses(report: Any) -> list[str]:
    """Every field a conversion would lose, from both of the lists that hold
    one.

    `report.dropped` is the fields with no home in the destination, and
    `report.losses` is the subset of the warnings that is a player's own loss
    -- a name the destination's field could not hold whole among them. Each
    is a defect in the conversion, and neither is a thing to ask a player to
    accept (`docs/227-editor-open-save-as.md`).
    """
    return [*getattr(report, "dropped", ()), *getattr(report, "losses", ())]


# ---------------------------------------------------------------------------
# Save As: where it goes, and what it holds until it gets there
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Destination:
    """Where a Save As writes, and what the editor adopts afterwards.

    `path` is the file for a C64 `.d64` or an Amiga `.adf` and the save
    folder itself for DOS. `slot` is the letter the written save holds --
    the source's own on a native copy, `A` for a fresh DOS folder, the
    source's letter for a DOS party converted to an Amiga disk.
    """

    port: str
    path: pathlib.Path
    slot: str | None
    title: Any
    native: bool

    @property
    def is_folder(self) -> bool:
        return self.port == "dos"


@dataclasses.dataclass
class SavePlan:
    """Output that exists in memory, validated, and not yet written.

    `files` is what publication puts down, by name: one entry for an image
    destination, whose name is the codec's own and whose *path* is the
    player's choice, and the whole set for a DOS folder. `report` is the
    conversion's own accounting, `None` for a native copy, which converts
    nothing.
    """

    source: Any
    destination: Destination
    files: dict[str, bytes]
    report: Any
    key: tuple
    stale: bool = False

    def invalidate(self) -> None:
        """Mark this output as no longer the answer, so `publish` refuses it."""
        self.stale = True

    def is_current(self, party: Any, port: str,
                   path: "str | pathlib.Path", assets: "Assets | None" = None
                   ) -> bool:
        """Whether this output is still what those inputs would produce.

        Recomputes the key -- the edits, the destination and the assets --
        and compares. False means the plan has to be prepared again: an edit
        after preparing is the common case, and publishing the old bytes
        would write a save the player has since changed.
        """
        if self.stale:
            return False
        snapshot = prepare(party)
        if snapshot is None:
            return False
        return self.key == plan_key(snapshot, port, path,
                                    assets or Assets())


def _digest(data: "bytes | None") -> str:
    return "" if data is None else hashlib.sha256(bytes(data)).hexdigest()


def _snapshot_digest(snapshot: Snapshot) -> str:
    """One digest over everything a snapshot holds, whichever port it is."""
    sha = hashlib.sha256()
    for part in (snapshot.save0, snapshot.save1, snapshot.disk,
                 snapshot.image):
        sha.update(b"\x00" if part is None else bytes(part))
    for name, data in sorted((snapshot.files or {}).items()):
        sha.update(name.encode())
        sha.update(data)
    sha.update(str(snapshot.slot).encode())
    return sha.hexdigest()


def plan_key(snapshot: Snapshot, port: str, path: "str | pathlib.Path",
             assets: "Assets | None" = None) -> tuple:
    """What a prepared output depends on: the edits, the destination and the
    assets."""
    return (port, str(pathlib.Path(path)), (assets or Assets()).token(),
            _snapshot_digest(snapshot))


# ---------------------------------------------------------------------------
# Save As: preparing it
# ---------------------------------------------------------------------------

def native_files(snapshot: Snapshot) -> dict[str, bytes]:
    """A copy of the save itself, with the editor's pending edits in it.

    Every byte comes from the player's own save, so nothing is converted and
    nothing can be lost: a C64 or an Amiga copy is the whole image, and a DOS
    copy is the whole folder -- its other saved games and whatever else sits
    in it included -- with the open slot's own files replaced by the
    rewritten ones. A file of that slot the rewrite left with no bytes is
    left out rather than copied from the original, which is how a character
    who no longer carries anything loses his item file here too.

    Sub-folders of a DOS save folder are not copied; `backups/` beside a save
    is the one that normally sits there.
    """
    if snapshot.port == "c64":
        return {snapshot.path.name: bytes(snapshot.disk)}
    if snapshot.port == "amiga":
        return {snapshot.path.name: bytes(snapshot.image)}
    pattern = re.compile(_SLOT_FILE.format(slot=re.escape(snapshot.slot)),
                         re.IGNORECASE)
    copied = {path.name: path.read_bytes()
              for path in sorted(snapshot.path.iterdir())
              if path.is_file() and not pattern.fullmatch(path.name)}
    copied.update(snapshot.files or {})
    return copied


def prepare_save_as(party: Any, port: str, path: "str | pathlib.Path",
                    assets: "Assets | None" = None) -> SavePlan:
    """Everything a Save As would write, in memory and validated.

    The open party's own snapshot is the source on every port, so the edits
    on screen are in the output whether or not the save they came from has
    ever been written. A destination of the source's own port is a native
    copy; anything else is the registered conversion, which is **refused
    outright if it would lose a field**, before a byte of the destination is
    touched.

    **The destination is never the save it came from.** Writing a Save As
    over its own source destroys the thing it is reading, and for a copy of
    the same save to the same place there is already a Save; a caller that
    reaches here with the open save's own path gets a refusal rather than
    either.

    Raises `MissingAssets` for game data nothing answered for, `DroppedFields`
    for a conversion that loses something, and `SaveAsError` for a route that
    does not exist, a destination that is the source, or output that cannot
    be read back.
    """
    from .convert import Source, _same_file

    snapshot = prepare(party)
    if snapshot is None:
        raise SaveAsError("there is no saved game open to write")
    source = Source.of_snapshot(snapshot)
    if _same_file(pathlib.Path(path), snapshot.path):
        raise SaveAsError(f"{path} is the save this is being written from")
    direction = route(source, port)
    if direction is None:
        files, slot, report = native_files(snapshot), snapshot.slot, None
        title = snapshot.title
    else:
        rehearsal, slot = rehearse(direction, source, assets or Assets())
        lost = losses(rehearsal.report)
        if lost:
            # The accounting is the evidence for the defect each of these
            # is, so it goes to the log whether or not the caller says
            # anything (`.claude/rules/conversions.md`).
            _log.info("refusing a %s to %s Save As: %s", source.port, port,
                      "; ".join(lost))
            raise DroppedFields(lost)
        files, report = dict(rehearsal.files), rehearsal.report
        title = direction.destination_game
    destination = Destination(port=port, path=pathlib.Path(path), slot=slot,
                              title=title, native=direction is None)
    validate(destination, files)
    return SavePlan(source=source, destination=destination, files=files,
                    report=report,
                    key=plan_key(snapshot, port, path, assets))


def validate(destination: Destination, files: dict[str, bytes]) -> None:
    """Open the prepared bytes as a saved game, somewhere else entirely.

    A conversion that produced something the editor cannot read is a failure
    before publication rather than after it, which is the difference between
    a Save As that changes nothing and one that leaves the player holding an
    unreadable destination.

    **It does not check that the destination holds a party**, and the reason
    is that the editor's own occupancy test is stricter than the save format:
    `goldbox.savegame.looks_occupied` calls a C64 slot a character only when
    all six abilities are 3 to 25, so a party built for a test reads as an
    empty roster out of a save that really does hold its records.
    """
    if not destination.is_folder and len(files) != 1:
        raise SaveAsError(
            f"a {destination.port} destination is one file and this "
            f"conversion produced {len(files)}")
    with tempfile.TemporaryDirectory(prefix="wish-validate-") as scratch:
        at = pathlib.Path(scratch)
        if destination.is_folder:
            for name, data in files.items():
                (at / name).write_bytes(data)
            where = at
        else:
            where = at / destination.path.name
            where.write_bytes(next(iter(files.values())))
        try:
            open_destination(dataclasses.replace(destination, path=where))
        except Exception as exc:
            raise SaveAsError(
                f"the {destination.port} save this would write cannot be "
                f"read back: {exc}") from exc


def open_destination(destination: Destination) -> Any:
    """The written destination, as an `editor.roster.Party`."""
    from .convert import Source
    from .roster import Party

    if destination.port == "c64":
        return Party(str(destination.path))
    return Party(Source.detect(destination.path, slot=destination.slot))


# ---------------------------------------------------------------------------
# Save As: publishing it
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Published:
    """What landed, and how to take it back again.

    `party` is the destination read back off disk -- the document a caller
    adopts. `roll_back` is what it calls instead when adopting fails: a
    replaced image comes back from its `backup`, and a new output is removed
    outright.
    """

    destination: Destination
    party: Any
    backup: pathlib.Path | None
    written: tuple[pathlib.Path, ...]
    folder_created: bool = False

    def roll_back(self) -> None:
        """Undo the publication, or say what is left of it.

        Raises `RecoveryFailed`, carrying the backup that still holds the
        destination's own bytes, rather than let a caller report that nothing
        was written.
        """
        try:
            if self.backup is not None:
                editor_files.restore_file(self.destination.path, self.backup)
                return
            for path in self.written:
                path.unlink(missing_ok=True)
            if self.folder_created and self.destination.path.is_dir():
                shutil.rmtree(self.destination.path)
        except OSError as exc:
            raise RecoveryFailed(
                f"could not put {self.destination.path} back: {exc}",
                backup=self.backup) from exc


def publish(plan: SavePlan,
            backups: "str | pathlib.Path | None" = None) -> Published:
    """Put a prepared output where the player asked, and open it.

    An image is written through a temporary sibling and renamed over
    whatever was there, which is backed up first; a save folder is staged
    complete and moved in, and a folder that already holds files is refused
    rather than mixed into. The published output is then opened as a save in
    its own right -- a destination that cannot be read is rolled back here
    rather than handed on.

    Raises `StalePlan` for output the caller has invalidated, and whatever
    `editor.files` raises for a refused or failed write.
    """
    if plan.stale:
        raise StalePlan("this output was prepared before the last change")
    destination = plan.destination
    if destination.is_folder:
        existed = destination.path.is_dir()
        written = editor_files.publish_folder(destination.path, plan.files)
        published = Published(destination=destination, party=None,
                              backup=None, written=tuple(written),
                              folder_created=not existed)
    else:
        backup = editor_files.replace_file(
            destination.path, next(iter(plan.files.values())), backups)
        published = Published(destination=destination, party=None,
                              backup=backup, written=(destination.path,))
    try:
        published.party = open_destination(destination)
    except Exception as exc:
        published.roll_back()
        raise SaveAsError(
            f"{destination.path} was written and cannot be opened: {exc}"
        ) from exc
    return published
