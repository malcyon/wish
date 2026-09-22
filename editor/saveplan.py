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
output in memory and refuses it if reading it back gives a party the sheet
would not recognise, and
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
from goldbox.record import RECORD_SIZE, CharacterRecord
from goldbox.savegame import SaveGame0, SaveGame1, load_save, store_save

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

    `lost` is what the conversion's own accounting calls a loss followed by
    every difference `compare` found between the sheet and the output read
    back, a name the destination's own field could not hold whole among
    them. Each one is a high-priority defect in the conversion
    (`docs/227-editor-open-save-as.md`), never a choice to put to a player.
    """

    def __init__(self, lost: "list[str]"):
        self.lost = list(lost)
        super().__init__(f"{len(self.lost)} field(s) would be lost: "
                         + "; ".join(self.lost))


class StalePlan(SaveAsError):
    """A prepared output that no longer matches the edits, the destination or
    the assets it was prepared from."""


#: Undoing a publication itself failed, carrying the backup that still holds
#: the destination's own bytes and whatever is left on disk. One class for a
#: failed rollback wherever it happens: `editor.files.publish_folder` raises
#: it for a partly published folder it cannot clear up, and `Published.
#: roll_back` for an image it cannot put back.
RecoveryFailed = editor_files.RecoveryFailed


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
    Silver Blades save stages no area script, so it asks for no game disk at
    all where a Pool of Radiance or a Curse one does.
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

    `game_disks` is the `.d64` files those `GameFiles` were actually read
    off, when anybody knows: `refuse_alias` will not let a Save As land on
    one of them. **It is empty when the disks came from the injected
    `game_files` callable**, because `editor.dosimport.GameFiles` does not
    keep which disk each part came from -- so a destination that is one of
    *those* disks is refused only by the folder the caller named, if it
    named one.
    """

    game_files: Any = None
    source_files: Any = None
    dos_folder: pathlib.Path | None = None
    amiga_disk: pathlib.Path | None = None
    c64_folder: pathlib.Path | None = None
    game_disks: tuple[pathlib.Path, ...] = ()

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

        The paths a caller named, and a digest of everything behind them a
        conversion actually reads and that can change without the path
        changing: `ANIMATE00`, the icon tables and the creation menu off
        whichever C64 disk answered, the whole Amiga disk the area's script
        comes off, and the `ECL<n>.DAX` files of the DOS game folder. The
        rest of a DOS game folder is the installed game and no writer reads
        it, so digesting the folder whole would be tens of megabytes to
        answer a question about eight files.
        """
        return (str(self.dos_folder or ""), str(self.amiga_disk or ""),
                str(self.c64_folder or ""),
                ",".join(str(disk) for disk in self.game_disks),
                _files_token(self.game_files),
                _files_token(self.source_files),
                _file_digest(self.amiga_disk),
                _script_digest(self.dos_folder))


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
        disks: tuple[pathlib.Path, ...] = ()
        if c64_folder:
            folder = pathlib.Path(c64_folder)
            found = _game_files_from_folder(folder,
                                            direction.destination_game)
            # Whichever of these answered is the one that was read, and
            # `_game_files_from_folder` tries them in this order, so all of
            # them are files this route may open.
            disks = tuple(sorted(
                folder.glob(direction.destination_game.disk_glob)))
        else:
            found = (game_files(direction.destination_game) if game_files
                     else None)
        resolved = dataclasses.replace(resolved, game_files=found,
                                       game_disks=disks)
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
    """Every field the conversion's own accounting says it lost.

    `report.dropped` is the fields with no home in the destination and
    `report.losses` is the fields a value was cut or clamped to fit --
    every direction's report carries both, from the shared `neutral.Report`
    base. `report` itself is `None` for a native, same-platform copy --
    `prepare_save_as` runs no conversion and builds no report for one --
    which is the one case `getattr` was ever guarding here, not a report
    missing either attribute. `compare` below still reads the output back
    instead of trusting either list, because a name a destination could not
    hold whole can still reach neither list on its own if a writer forgets
    to copy it (`docs/227-editor-open-save-as.md`).
    """
    if report is None:
        return []
    return [*report.dropped, *report.losses]


#: What the player's own character is, in the C64 record every port's sheet
#: is bound to, and so what every destination has to come back holding. The
#: name, which a 15-character DOS field and a 16-character Amiga one can both
#: cut; everything the writers can clamp to a narrower field; the derived
#: caches the sheet shows; and the rest of what a player would call their
#: character. Measured rather than chosen: with `_NOT_COMPARED` below this
#: is **every known field of the layout**, and
#: `test_every_known_field_is_compared_or_named_as_not_compared` fails if a
#: new one joins neither list.
KEPT_FIELDS = (
    "name", "sex", "race", "char_class", "class_bits", "alignment", "age",
    "strength", "exceptional_strength", "intelligence", "wisdom", "dexterity",
    "constitution", "charisma", "abilities_second", "experience", "hp_max",
    "hp_rolled", "hp_lost_to_drain", "levels_drained", "level",
    "level_cleric", "level_fighter", "level_knight", "level_magic_user",
    "level_paladin", "level_ranger", "level_thief", "dual_class_level",
    "dual_class_slot", "copper", "silver", "electrum", "gold", "platinum",
    "gems", "jewelry", "spells_known", "spells_known_high",
    "spells_memorised", "movement", "portrait_head", "portrait_body",
    # Stored values a writer carries rather than derives, each one measured
    # equal on every route below. A destination that came back without one
    # is a destination the sheet would draw differently.
    "abilities_second", "size_small", "armour_class_base", "attack_forms",
    "strength_bonus_flag", "turn_power", "flags_0b8", "experience_award",
    "experience_per_hit_point", "treasure_share")

#: What is deliberately **not** compared, and why. Every known field of the
#: layout is here or in `KEPT_FIELDS`, and each line below is a measurement
#: on the routes this machine can drive rather than an assumption:
#:
#: * `identity_pair` -- the two GEN bytes a DOS destination redraws:
#:   `b'D\x0d'` arrives as `b'D\x00'` on all six real Pool of Radiance C64
#:   saves converted to DOS here;
#: * `party_order` -- the marching order a DOS destination renumbers 0 to 5
#:   where a C64 save leaves it zero;
#: * `item_effects` -- the ten trait slots, which an Amiga destination stores
#:   in the opposite order, so the bytes differ where the traits do not;
#: * `thac0`, `armour_class`, `hp_current`, `combat_side`, `roster_in_use`,
#:   `roster_tail`, `roster_movement` and `inventory` -- not in the 256 bytes
#:   a C64 save stores per slot, so a C64 destination read back at slot width
#:   has nothing to compare;
#: * every field the layout does not call known -- `gap_*` and `region_*`,
#:   bytes nobody has named.
#:
#: **And the values a writer derives rather than carries**, each one a
#: measured decision of the codec with its own issue behind it. Forcing these
#: equal would refuse a conversion for writing the *right* value:
#:
#: * `thac0_base` -- `goldbox.dos_codec._THAC0_RECOMPUTE_FROM_PORTS`: the two
#:   ports ship different THAC0 tables (#366), so a C64 source's byte is
#:   recomputed from the class levels rather than copied;
#: * the eight `thief_*` columns -- `_THIEF_SKILL_RECOMPUTE_FROM_PORTS`: the
#:   two ports ship different racial rows and DOS applies a dexterity block
#:   the C64 build never reads (#431);
#: * `spells_castable` -- `_SPELL_SLOT_RECOMPUTE_FROM_PORTS`: the C64 reader
#:   hands back zeros for a title that stores no slots, so the array is
#:   rebuilt (#547);
#: * the five `save_*` -- the DOS engine recomputes all five on load from
#:   class, level and the character's `.SPC` records, so a copied number is
#:   discarded before anybody reads it (#191);
#: * `attack_level` -- DOS Pool of Radiance leaves the byte at its creation
#:   value where every other port keeps a fighting level, so the writer picks
#:   per port and title (#527);
#: * `strength_index` -- no DOS field holds one, and
#:   `goldbox.c64_codec.strength_index` computes it from the strength and the
#:   percentile at write time;
#: * `missile_attack_adjustment` -- no DOS field holds one either, and
#:   `COM.PREP $1633` rebuilds it from the record's own dexterity at the
#:   start of every fight and at no other time (the routine read end to end,
#:   and measured in the running game: `$7F` poked into all six records of
#:   the PORSAVE13 party read back as the table's own values four steps
#:   later). Dexterity is compared, so nothing the player chose is at stake
#:   -- but a C64 destination reached through DOS shows a THAC0 short by the
#:   adjustment until the next fight rewrites it;
#: * `infravision` -- the C64 computes its own from the race
#:   (`goldbox.c64_codec.DROPPED`);
#: * `turn_class` -- the undead's own row rather than the caster's, and zero
#:   for every player character (#297, #288).
#:
#: Measured over 36 runs: the fifteen Pool of Radiance C64 saves this
#: machine's registry holds, each to a C64 and a DOS destination, plus DOS
#: Silver Blades to Amiga and to DOS, DOS Pool of Radiance to C64, Amiga
#: Curse to Amiga and to C64, and Amiga Pool of Radiance to C64. Every one
#: of the fields above that ever differed is here; the one that differed and
#: is **not** here is `flags_0b8`, whose bit 0 the DOS and Amiga records keep
#: in the byte after their control byte and now comes back equal.
_NOT_COMPARED = ("identity_pair", "party_order", "item_effects", "thac0",
                 "armour_class", "hp_current", "combat_side", "roster_in_use",
                 "roster_tail", "roster_movement", "inventory",
                 "thac0_base", "attack_level", "strength_index",
                 "missile_attack_adjustment", "infravision", "turn_class",
                 "spells_castable", "save_paralysis", "save_petrification",
                 "save_wands", "save_breath", "save_spell",
                 "thief_pick_pockets", "thief_open_locks", "thief_find_traps",
                 "thief_move_silently", "thief_hide_in_shadows",
                 "thief_hear_noise", "thief_climb_walls",
                 "thief_read_languages")


def kept(record: CharacterRecord) -> "dict[str, Any]":
    """`KEPT_FIELDS` off one record, by name."""
    return {name: record.get(name) for name in KEPT_FIELDS}


def c64_slot_records(at: pathlib.Path) -> "list[CharacterRecord]":
    """Every slot of a C64 save image that holds a character, as a record.

    **A slot is a character when the first byte of its name is not zero.**
    That is the format's own free-slot marker rather than a heuristic: a
    character dropped from the party leaves the whole of his record behind
    and only that byte cleared, which is what `.OLAND` and `.RUTUS` are in
    slots 6 and 7 of the player's own save disks. Counted on the fifteen
    Pool of Radiance C64 saves this machine's registry holds, the rule
    agrees with the editor's own reader on every one of them -- six
    characters each, where "any non-zero byte in the slot" says eight on
    thirteen of the fifteen and would refuse a Save As that lost nothing.

    It is deliberately **weaker than `goldbox.savegame.looks_occupied`**,
    which also demands all six abilities in 3 to 25: a party built for a
    test rolls 1 to 6, so the editor's own occupancy test reads a save that
    really does hold its records as an empty roster, and comparing through
    `editor.roster.Party` would refuse those conversions instead.
    """
    _game, save0, _save1 = load_save(D64.open(str(at)))
    return [CharacterRecord(one.window + bytes(RECORD_SIZE - len(one.window)),
                            stored_size=len(one.window))
            for one in save0.slots if one.window and one.window[0]]


def written_records(port: str, at: pathlib.Path,
                    slot: "str | None") -> "list[CharacterRecord]":
    """Every character record a written destination holds, as a C64 record.

    A DOS folder and an Amiga disk are read back the way the editor itself
    opens one, through `editor.roster.Party`. A C64 image is read slot by
    slot instead, by `c64_slot_records`, which says why.
    """
    from .convert import Source
    from .roster import Party

    if port == "c64":
        return c64_slot_records(at)
    return [member.record
            for member in Party(Source.detect(at, slot=slot)).members]


def _signature(record: CharacterRecord) -> tuple[str, ...]:
    """One character as the comparison sees him: every kept field, in order."""
    return tuple(repr(record.get(name)) for name in KEPT_FIELDS)


def compare(expected: "list[CharacterRecord]",
            written: "list[CharacterRecord]") -> list[str]:
    """What the sheet holds and the written destination does not.

    **Whole characters are compared, as a multiset of characters.** A
    multiset because the two ports list a party from opposite ends
    (`goldbox.dos_codec.c64_party`) and a conversion that reversed the order
    lost nothing; whole characters because sorting each field on its own
    would let values move between them unseen -- one character's 5,000 gold
    arriving on another and the other's 10 arriving on him is two fields
    swapped and a per-field multiset that matches exactly. Two characters
    the sheet holds identical still match two identical ones written.

    The diagnosis then pairs the two sorted lists and names each field that
    differs with both of its values, which is the evidence for the defect
    each difference is.
    """
    if len(expected) != len(written):
        return [f"{len(expected)} character(s) went in and {len(written)} "
                f"came back out"]
    want = sorted(_signature(record) for record in expected)
    got = sorted(_signature(record) for record in written)
    if want == got:
        return []
    out: list[str] = []
    for mine, theirs in zip(want, got):
        for name, was, now in zip(KEPT_FIELDS, mine, theirs):
            line = f"{name}: {was} arrived as {now}"
            if was != now and line not in out:
                out.append(line)
    return out


# ---------------------------------------------------------------------------
# Save As: where it goes, and what it holds until it gets there
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Destination:
    """Where a Save As writes, and what the editor adopts afterwards.

    `path` is the file for a C64 `.d64` or an Amiga `.adf` and the save
    folder itself for DOS. `slot` is the letter the written save holds --
    the source's own on a native copy, `A` for a fresh DOS folder, the
    source's letter for a DOS party converted to an Amiga disk, and `None`
    for a C64 destination, which keeps one saved game and names no slot.
    The letter a C64 conversion reads *from* is the source's and belongs to
    the rehearsal rather than here.
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

    `assets` is the game data the output was prepared from, kept so that
    `publish` can recompute the freshness key from it. A caller that has to
    hand the same assets back a second time is a caller that can forget
    them, and forgetting them looks exactly like an edit: `StalePlan`, on
    output that is current.
    """

    source: Any
    destination: Destination
    files: dict[str, bytes]
    report: Any
    key: tuple
    assets: "Assets | None" = None
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


def _files_token(game_files: Any) -> str:
    """A digest of one `editor.dosimport.GameFiles`, all three parts of it.

    `animate` is bytes and digests directly. The icon tables are an
    `goldbox.iconparts.IconParts`, so what is digested is the geometry it
    fitted and the figure it composes -- its table addresses and counts, the
    class bytes, the fillers and `default_icon()`. That is what a conversion
    draws each character's combat figure out of; two `SPELLE64` files
    differing nowhere in any of it would not change a converted save. The
    creation menu is its two tables of art ids and the disk it came off.
    """
    if game_files is None:
        return ""
    sha = hashlib.sha256()
    sha.update(_digest(getattr(game_files, "animate", None)).encode())
    icon = getattr(game_files, "icon", None)
    if isinstance(icon, (bytes, bytearray)):
        sha.update(_digest(icon).encode())
    elif icon is not None:
        sha.update(repr(sorted(getattr(icon, "tables", {}).items())).encode())
        sha.update(bytes(getattr(icon, "classes", b"")))
        for filler in getattr(icon, "fillers", ()):
            sha.update(bytes(filler))
        compose = getattr(icon, "default_icon", None)
        if callable(compose):
            sha.update(bytes(compose()))
    portraits = getattr(game_files, "portraits", None)
    if portraits is not None:
        sha.update(repr((getattr(portraits, "heads", ()),
                         getattr(portraits, "bodies", ()),
                         getattr(portraits, "source", ""))).encode())
    return sha.hexdigest()


def _file_digest(path: "pathlib.Path | None") -> str:
    """A digest of one file's bytes, empty for a path with nothing at it."""
    if path is None:
        return ""
    try:
        return _digest(pathlib.Path(path).read_bytes())
    except OSError:
        return ""


def _script_digest(folder: "pathlib.Path | None") -> str:
    """A digest over a DOS game folder's `ECL<n>.DAX` files, by name."""
    if folder is None:
        return ""
    sha = hashlib.sha256()
    try:
        scripts = sorted(path for path in pathlib.Path(folder).iterdir()
                         if path.is_file()
                         and re.fullmatch(r"ECL\d*\.DAX", path.name,
                                          re.IGNORECASE))
        for path in scripts:
            sha.update(path.name.upper().encode())
            sha.update(path.read_bytes())
    except OSError:
        return ""
    return sha.hexdigest()


def _amiga_contents(image: bytes) -> dict[str, bytes]:
    """Every file on an Amiga disk image, by path.

    **The image is not the saved game and the files are.**
    `goldbox.amiga_adf.AmigaDisk.write_file` stamps each directory entry with
    the time of day, so writing the same party into the same disk twice gives
    two images that differ in the directory blocks and nowhere else -- which
    would make a plan prepared from an Amiga party stale the moment it was
    compared with itself.
    """
    from goldbox.amiga_adf import AmigaDisk

    disk = AmigaDisk(bytearray(image))
    return {path: disk.read_file(path)
            for path, _entry in sorted(disk.walk(), key=lambda one: one[0])}


def _snapshot_files(snapshot: Snapshot) -> dict[str, bytes]:
    """Everything a publication of this snapshot could put down, by name.

    A DOS folder's other saved games among them: a native copy carries the
    whole folder, so a file of another slot changing changes what a Save As
    would write.
    """
    if snapshot.image is not None:
        return _amiga_contents(snapshot.image)
    files = dict(snapshot.files or {})
    if snapshot.port == "dos" and snapshot.path.is_dir():
        for path in sorted(snapshot.path.iterdir()):
            if path.is_file() and path.name not in files:
                files[path.name] = path.read_bytes()
    return files


def _snapshot_digest(snapshot: Snapshot) -> str:
    """One digest over everything a snapshot holds, whichever port it is."""
    sha = hashlib.sha256()
    for part in (snapshot.save0, snapshot.save1, snapshot.disk):
        sha.update(b"\x00" if part is None else bytes(part))
    for name, data in sorted(_snapshot_files(snapshot).items()):
        sha.update(name.encode())
        sha.update(b"\x00")
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

#: What a destination of each port has to be called for the editor to open it
#: again. A DOS destination is a folder and is not here: it has no suffix.
DESTINATION_SUFFIX = {"c64": ".d64", "amiga": ".adf"}


def _inside_or_equal(path: pathlib.Path, other: pathlib.Path) -> bool:
    """Whether `path` is `other` or sits under it, symlinks resolved.

    `os.path.samefile` decides it where both exist, because two paths can
    resolve differently and still be one file -- a hard link, or a mount
    reached by two names -- and being the same file is the question.
    """
    try:
        here, there = path.resolve(), other.resolve()
    except OSError:
        return False
    if here == there:
        return True
    try:
        if here.exists() and there.exists() and here.samefile(there):
            return True
    except OSError:
        pass
    return here.is_relative_to(there)


def refuse_alias(path: pathlib.Path, snapshot: Snapshot,
                 assets: "Assets | None") -> None:
    """Refuse a destination that is, holds or sits inside something this
    Save As is reading.

    The save itself first: writing a Save As over its own source destroys
    the thing it is reading, and for a copy of the same save to the same
    place there is already a Save. A DOS save is a folder, so a destination
    *inside* it is the same collision under another name, and a destination
    folder that holds the source is one too.

    Then the game data, and **only what publication would actually land
    on**: a destination that *is* one of those files or folders, or one that
    holds it. A save beside the game disks is none of the project's
    business -- `<disks>/MYSAVE.D64` next to `POOL1.D64` overwrites nothing
    -- and refusing everything under the folder takes a place the player may
    well keep saves in away from them for nothing.
    """
    if _inside_or_equal(path, snapshot.path):
        raise SaveAsError(f"{path} is the save this is being written from")
    if snapshot.path.is_dir() and _inside_or_equal(snapshot.path, path):
        raise SaveAsError(f"{path} holds the save this is being written from")
    assets = assets or Assets()
    reads: list[tuple[str, pathlib.Path]] = [
        ("game disk", disk) for disk in assets.game_disks]
    for what, where in (("game disk", assets.amiga_disk),
                        ("DOS game folder", assets.dos_folder),
                        ("C64 game folder", assets.c64_folder)):
        if where is not None:
            reads.append((what, where))
    for what, where in reads:
        if _inside_or_equal(where, path):
            raise SaveAsError(f"{path} is, or holds, the {what} this "
                              f"conversion reads")


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

    **The name decides whether the output can be opened again**, so it is
    checked here rather than left to the reader: a C64 destination is a
    `.d64` and an Amiga one an `.adf` (`DESTINATION_SUFFIX`), case
    disregarded, and a DOS destination is a folder and has no suffix at all.
    Without that check a player typing `MySave` for an Amiga destination gets
    the validation's own sentence about a D64 image of 901,120 bytes.

    Raises `MissingAssets` for game data nothing answered for, `DroppedFields`
    for a conversion that loses something, and `SaveAsError` for a route that
    does not exist, a destination that is the source or one of the assets, a
    name the destination cannot be read back from, or output that cannot be
    read back.
    """
    from .convert import Source

    snapshot = prepare(party)
    if snapshot is None:
        raise SaveAsError("there is no saved game open to write")
    source = Source.of_snapshot(snapshot)
    refuse_alias(pathlib.Path(path), snapshot, assets)
    wanted = DESTINATION_SUFFIX.get(port)
    if wanted and pathlib.Path(path).suffix.lower() != wanted:
        raise SaveAsError(f"a {port} destination is a {wanted} file and "
                          f"{path} is not")
    direction = route(source, port)
    if direction is None:
        files, slot, report = native_files(snapshot), snapshot.slot, None
        title = snapshot.title
    else:
        rehearsal, slot = rehearse(direction, source, assets or Assets())
        files, report = dict(rehearsal.files), rehearsal.report
        title = direction.destination_game
    destination = Destination(port=port, path=pathlib.Path(path),
                              slot=None if port == "c64" else slot,
                              title=title, native=direction is None)
    validate(destination, files,
             [edited_record(member) for member in party.members],
             accounted=losses(report))
    return SavePlan(source=source, destination=destination, files=files,
                    report=report, assets=assets,
                    key=plan_key(snapshot, port, path, assets))


def validate(destination: Destination, files: dict[str, bytes],
             expected: "list[CharacterRecord] | None" = None,
             accounted: "list[str] | tuple[str, ...]" = ()) -> None:
    """Open the prepared bytes as a saved game, somewhere else entirely.

    Two checks, both before a byte of the player's destination is touched.
    Output the editor cannot read is a failure here rather than after
    publication, which is the difference between a Save As that changes
    nothing and one that leaves the player holding an unreadable
    destination. Then `expected` -- the party as the sheet holds it -- is
    compared with what the written save actually came back with, and **any
    difference is refused**: a name cut to the destination's own width and a
    value clamped to a narrower field are losses `losses()` also names off
    the conversion's own report (#619), and this comparison is the second
    guard rather than a redundant one -- it catches a loss no writer admitted
    to, including one whose report was thrown away before it reached here.

    `accounted` is what that report did name, and it is raised together with
    the comparison's own findings rather than ahead of them, so one refusal
    names everything this route would cost the player instead of the first
    thing it happened to notice.

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
        written = []
        if expected is not None:
            try:
                written = written_records(destination.port, where,
                                          destination.slot)
            except Exception as exc:
                raise SaveAsError(
                    f"the {destination.port} save this would write cannot be "
                    f"read back: {exc}") from exc
    lost = [*accounted,
            *(compare(expected, written) if expected is not None else [])]
    if lost:
        # The accounting is the evidence for the defect each of these is, so
        # it goes to the log whether or not the caller says anything
        # (`.claude/rules/conversions.md`).
        _log.info("refusing a Save As to %s: %s", destination.path,
                  "; ".join(lost))
        raise DroppedFields(lost)


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
    #: The folders publication had to make on the way to the destination,
    #: deepest first. A rollback takes them away again, so a Save As to
    #: `~/new/place/save.adf` that is undone leaves neither the file nor the
    #: two folders nobody had before.
    created: tuple[pathlib.Path, ...] = ()

    def roll_back(self) -> None:
        """Undo the publication, or say what is left of it.

        Raises `RecoveryFailed`, carrying the backup that still holds the
        destination's own bytes and **every path still on disk**, rather
        than let a caller report that nothing was written. The removals go
        on past a file that refuses to go, so one unremovable file does not
        leave five more beside it unmentioned and unremoved.
        """
        try:
            if self.backup is not None:
                _log.info("putting %s back from %s", self.destination.path,
                          self.backup)
                editor_files.restore_file(self.destination.path, self.backup)
                return
        except OSError as exc:
            _log.exception("could not undo the publication of %s; the "
                           "backup is %s", self.destination.path,
                           self.backup)
            raise RecoveryFailed(
                f"could not put {self.destination.path} back: {exc}",
                backup=self.backup, left=(self.destination.path,)) from exc
        left: list[pathlib.Path] = []
        failure: OSError | None = None
        for path in self.written:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                failure = failure or exc
                left.append(path)
        try:
            if self.folder_created and self.destination.path.is_dir():
                shutil.rmtree(self.destination.path)
        except OSError as exc:
            failure = failure or exc
            left.append(self.destination.path)
        editor_files.remove_if_empty(self.created)
        if failure is not None:
            _log.error("could not undo the publication of %s; the backup is "
                       "%s and %s is still there", self.destination.path,
                       self.backup, ", ".join(str(path) for path in left),
                       exc_info=failure)
            raise RecoveryFailed(
                f"could not put {self.destination.path} back: {failure}",
                backup=self.backup, left=left) from failure


def publish(plan: SavePlan, party: Any,
            backups: "str | pathlib.Path | None" = None,
            assets: "Assets | None" = None) -> Published:
    """Put a prepared output where the player asked, and open it.

    `party` is the open party the plan was prepared from, and it is checked
    against the plan rather than merely carried: the flag a caller sets is
    only as good as the caller's own noticing, so the edits, the destination
    and the assets are recomputed here and output that is no longer what
    they would produce is refused. Publishing bytes a player has since
    edited past is the one failure in this module nothing on disk would
    show.

    **`assets` defaults to the plan's own**, so a caller that does not pass
    them again gets the freshness check it meant rather than a `StalePlan`
    for output that is current.

    An image is written through a temporary sibling and renamed over
    whatever was there, which is backed up first; a save folder is staged
    complete and moved in, and a folder that already holds files is refused
    rather than mixed into. The published output is then opened as a save in
    its own right -- a destination that cannot be read is rolled back here
    rather than handed on. A write that fails takes the folders publication
    made on the way to the path away again, so a disk that filled up leaves
    no empty `~/new/place/` behind.

    Raises `StalePlan` for output the caller has invalidated or that the
    party has moved past, and whatever `editor.files` raises for a refused
    or failed write: `NoBackupFolder`, `TargetNotEmpty` and `OSError`.
    **`RecoveryFailed` has to be caught beside those three**: it is a
    `RuntimeError` rather than a `SaveAsError`, and it means bytes are on
    disk that a caller must name to the player rather than report a save
    that did not happen.
    """
    destination = plan.destination
    if assets is None:
        assets = plan.assets
    if not plan.is_current(party, destination.port, destination.path, assets):
        raise StalePlan("this output was prepared before the last change")
    created = editor_files.missing_parents(destination.path)
    try:
        if destination.is_folder:
            existed = destination.path.is_dir()
            written = editor_files.publish_folder(destination.path, plan.files)
            published = Published(destination=destination, party=None,
                                  backup=None, written=tuple(written),
                                  folder_created=not existed,
                                  created=tuple(created))
        else:
            backup = editor_files.replace_file(
                destination.path, next(iter(plan.files.values())), backups)
            published = Published(destination=destination, party=None,
                                  backup=backup, written=(destination.path,),
                                  created=tuple(created))
    except BaseException:
        editor_files.remove_if_empty(created)
        raise
    try:
        published.party = open_destination(destination)
    except Exception as exc:
        _log.exception("%s was written and cannot be opened",
                       destination.path)
        try:
            published.roll_back()
        except RecoveryFailed as failed:
            raise RecoveryFailed(
                f"{failed} after {destination.path} was written and could "
                f"not be opened: {exc}", backup=failed.backup,
                left=failed.left) from exc
        raise SaveAsError(
            f"{destination.path} was written and cannot be opened: {exc}"
        ) from exc
    return published
