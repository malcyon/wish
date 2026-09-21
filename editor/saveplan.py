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
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from typing import Any

from goldbox import amiga_por, amiga_savegame, rewrite
from goldbox.d64 import D64
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0, SaveGame1, store_save

#: Where the sixteen item blocks sit in the 580-byte C64 record the sheet
#: edits -- `editor.roster`'s own `_ITEMS_AT`, which is where a converted
#: character's inventory was read from.
_ITEMS_AT = 0x120

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
    are a C64 save's two payloads and its disk image, which is the group
    `editor.convert.Source` already carried.

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
