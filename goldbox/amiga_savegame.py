"""Amiga saved-game containers and save disks.

Both later titles embed the party after a common big-endian variable array.
The layouts come from their save and load routines; ``docs/165-amiga-savegame.md``
records the byte-level evidence.  This module is the library counterpart of
``tools/amigasavecheck.py``: it reads a whole slot and builds one from a
``WorldState`` and neutral characters without a template.

The shared map is called :class:`AmigaContainer`, because it describes the
saved-game container rather than an unspecified geometric shape.  The
diagnostic checker imports this map; Pool of Radiance's filename-party row is
being consolidated here with the slot implementation.
"""

from __future__ import annotations

import contextlib
import dataclasses
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from . import (
    amiga_later,
    amiga_port,
    areas,
    c64_port,
    dos_codec,
    dos_savegame,
    neutral,
    world_state,
)
from .amiga_adf import AmigaDisk, AmigaDiskError
from .amiga_port import AmigaRecordError

VM_BYTES = 5120
VM_BASE = 0x4900
ECL_BYTES = 7680
SAVE_DRAWER = "SAVE"
SLOT_LETTERS = "ABCDEFGHIJ"
PARTY_MAX = 6
GAME_MODE_CAMP = 2
GAME_MODE_OVERLAND = 3
GAME_MODE_ADVENTURING = 4
EMPTY = 0xFFFF
POR_POSITION = (12800, 12801, 12802)
POR_WALLSET = 0x4AFA


def word(save: bytes, address: int,
         container: AmigaContainer | None = None) -> int:
    """One big-endian variable-array word from an Amiga saved game."""
    container = POOL_OF_RADIANCE if container is None else container
    at = container.vm_offset(address)
    return int.from_bytes(save[at:at + 2], "big")


class AmigaSaveError(AmigaRecordError):
    """A later-title Amiga saved game does not have the measured shape."""


@dataclasses.dataclass(frozen=True)
class SquareField:
    """One field in the saved square structure, in write order."""

    name: str
    size: int
    note: str = ""


@dataclasses.dataclass(frozen=True)
class AmigaContainer:
    key: str
    title: str
    suffix: str
    ecl_bytes: int
    x_bytes: int
    deltas: amiga_port.AmigaDeltas | None
    header_bytes: int = 1
    square: tuple[SquareField, ...] = ()
    first_mode_byte: str = "mode before"
    wallset_table: bool = True
    count_bytes: int = 2
    party: str = "records"
    fixed_size: int | None = None

    @property
    def vm_at(self) -> int:
        return self.header_bytes

    @property
    def ecl_at(self) -> int:
        return self.vm_at + VM_BYTES

    @property
    def square_at(self) -> int:
        return self.header_bytes + VM_BYTES + self.ecl_bytes

    @property
    def square_bytes(self) -> int:
        return sum(field.size for field in self.square) or 2 * self.x_bytes + 4

    @property
    def first_mode_at(self) -> int:
        return self.square_at + self.square_bytes

    @property
    def mode_at(self) -> int:
        return self.first_mode_at + 1

    @property
    def wallset_at(self) -> int | None:
        return self.mode_at + 1 if self.wallset_table else None

    @property
    def count_at(self) -> int:
        return self.mode_at + 1 + (12 if self.wallset_table else 0)

    @property
    def party_at(self) -> int:
        return self.count_at + self.count_bytes

    def word_offset(self, address: int) -> int:
        if not VM_BASE <= address < VM_BASE + VM_BYTES // 2:
            raise AmigaSaveError(f"${address:04X} is outside the variable array")
        return self.header_bytes + 2 * (address - VM_BASE)

    vm_offset = word_offset


CURSE = AmigaContainer(
    "curse-of-the-azure-bonds", "Curse of the Azure Bonds", ".dat",
    ECL_BYTES, 2, amiga_port.CURSE_DELTAS,
    square=(SquareField("x", 2), SquareField("y", 2), SquareField("facing", 1),
            SquareField("wall_ahead", 1), SquareField("square_property", 1),
            SquareField("pad", 1)))
SILVER_BLADES = AmigaContainer(
    "secret-of-the-silver-blades", "Secret of the Silver Blades", ".sav",
    0, 1, amiga_port.SILVER_BLADES_DELTAS,
    square=(SquareField("x", 1), SquareField("y", 1), SquareField("facing", 1),
            SquareField("wall_ahead", 1), SquareField("square_property", 1),
            SquareField("pad", 1)))
POOL_OF_RADIANCE = AmigaContainer(
    "pool-of-radiance", "Pool of Radiance", ".dat", ECL_BYTES, 1, None,
    header_bytes=0,
    square=(SquareField("x", 1), SquareField("y", 1), SquareField("facing", 1),
            SquareField("wall_ahead", 1), SquareField("square_property", 1),
            SquareField("pad", 2), SquareField("wallset_entry_0", 3)),
    first_mode_byte="view type", wallset_table=False, count_bytes=1,
    party="filenames", fixed_size=13141)
CONTAINERS = (CURSE, SILVER_BLADES, POOL_OF_RADIANCE)
CONTAINERS_BY_KEY = {container.key: container for container in CONTAINERS}
CONTAINERS_BY_SUFFIX = {container.suffix: container for container in CONTAINERS}

assert CURSE.party_at == 0x3219
assert SILVER_BLADES.party_at == 0x1417
assert POOL_OF_RADIANCE.party_at == 12813


@dataclasses.dataclass(frozen=True)
class AmigaSavegame:
    container: AmigaContainer
    data: bytes
    x: int
    y: int
    facing: int
    first_mode: int
    mode: int
    wallset: tuple[tuple[int, int], ...]
    characters: tuple[amiga_later.AmigaCharacter, ...]
    names: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.characters)

    def word(self, address: int) -> int:
        at = self.container.word_offset(address)
        return int.from_bytes(self.data[at:at + 2], "big")


def container_for(what: str | AmigaContainer | amiga_port.AmigaDeltas) -> AmigaContainer:
    if isinstance(what, AmigaContainer):
        return what
    key = getattr(what, "key", what)
    try:
        return CONTAINERS_BY_KEY[key]
    except KeyError:
        raise AmigaSaveError(f"no later Amiga title keyed {key!r}") from None


def slot_letter(slot: str) -> str:
    letter = slot.upper()
    if len(letter) != 1 or letter not in SLOT_LETTERS:
        raise AmigaSaveError(
            f"an Amiga save slot is one of {SLOT_LETTERS}; got {slot!r}")
    return letter


def slot_path(container: AmigaContainer | str, slot: str) -> str:
    container = container_for(container)
    return f"/{SAVE_DRAWER}/savgam{slot_letter(slot)}{container.suffix}"


def detect(data: bytes) -> AmigaContainer:
    if len(data) == POOL_OF_RADIANCE.fixed_size:
        return POOL_OF_RADIANCE
    for container in CONTAINERS:
        if container.deltas is None:
            continue
        if amiga_later.looks_like_amiga_record(data, container.party_at,
                                                container.deltas):
            return container
    raise AmigaSaveError(
        f"{len(data)} bytes with no Amiga Curse record at {CURSE.party_at:#x} "
        f"or Silver Blades record at {SILVER_BLADES.party_at:#x}")


def parse(data: bytes, container: AmigaContainer | str | None = None,
          source: str = "", validate: bool = True) -> AmigaSavegame:
    data = bytes(data)
    container = detect(data) if container is None else container_for(container)
    if container.fixed_size is not None and len(data) != container.fixed_size:
        raise AmigaSaveError(
            f"{container.title} saves are {container.fixed_size} bytes; got {len(data)}")
    if len(data) < container.party_at:
        raise AmigaSaveError(
            f"{container.title} needs {container.party_at} header bytes; got {len(data)}")
    at = container.square_at
    x = int.from_bytes(data[at:at + container.x_bytes], "big")
    at += container.x_bytes
    y = int.from_bytes(data[at:at + container.x_bytes], "big")
    at += container.x_bytes
    facing = data[at]
    wallset = ()
    if container.wallset_at is not None:
        wallset = tuple(
            (int.from_bytes(data[container.wallset_at + 4 * i:
                                 container.wallset_at + 4 * i + 2], "big"),
             int.from_bytes(data[container.wallset_at + 4 * i + 2:
                                 container.wallset_at + 4 * i + 4], "big"))
            for i in range(3))
    count = int.from_bytes(data[container.count_at:container.party_at], "big")
    if validate and not 1 <= count <= PARTY_MAX:
        raise AmigaSaveError(
            f"a {container.title} party is 1 to {PARTY_MAX} characters; got {count}")
    characters = []
    names = ()
    at = container.party_at
    if container.party == "records":
        assert container.deltas is not None
        for _ in range(count):
            char, at = amiga_later._amiga_block(data, at, container.deltas, source)
            characters.append(char)
    else:
        if len(data) != container.fixed_size:
            raise AmigaSaveError(
                f"{container.title} saves are {container.fixed_size} bytes; got {len(data)}")
        names = tuple(data[at + 41 * i:at + 41 * i + 8].split(b"\0")[0].decode("latin1")
                      for i in range(8))
        at = len(data)
    if at != len(data):
        raise AmigaSaveError(
            f"the {count} character blocks end at {at:#x}; file ends at "
            f"{len(data):#x}")
    save = AmigaSavegame(container, data, x, y, facing, data[container.first_mode_at],
                    data[container.mode_at], wallset, tuple(characters), names)
    if container.party == "filenames":
        return save
    if save.word(dos_savegame.PARTY_SIZE) != count:
        raise AmigaSaveError(
            f"$503E says {save.word(dos_savegame.PARTY_SIZE)} characters; "
            f"the saved-game count says {count}")
    if data[0] != save.word(dos_savegame.DISK):
        raise AmigaSaveError(
            f"byte 0 says container {data[0]}; $5012 says "
            f"{save.word(dos_savegame.DISK)}")
    return save


def read_slot(disk: AmigaDisk, slot: str,
              container: AmigaContainer | str | None = None) -> AmigaSavegame:
    letter = slot_letter(slot)
    if container is not None:
        containers = (container_for(container),)
    else:
        containers = CONTAINERS
    for candidate in containers:
        path = slot_path(candidate, letter)
        try:
            data = disk.read_file(path)
        except AmigaDiskError:
            continue
        try:
            return parse(data, candidate, path)
        except AmigaSaveError:
            continue
    raise AmigaSaveError(
        f"slot {letter} is not an Amiga Curse or Silver Blades save")


def slots_present(disk: AmigaDisk,
                  container: AmigaContainer | str | None = None) -> list[str]:
    containers = (container_for(container),) if container is not None else CONTAINERS
    out = []
    for letter in SLOT_LETTERS:
        if any(_slot_present(disk, candidate, letter)
               for candidate in containers):
            out.append(letter)
    return out


def _slot_present(disk: AmigaDisk, container: AmigaContainer, slot: str) -> bool:
    """Whether the named file is a valid slot for this later title.

    Curse and Pool of Radiance both call their container ``savgamA.dat``.
    File presence alone therefore misidentifies every Pool disk as Curse;
    the container and embedded record have to agree with the later layout.
    """
    path = slot_path(container, slot)
    try:
        parse(disk.read_file(path), container, path)
    except (AmigaDiskError, AmigaSaveError):
        return False
    return True


def _dos_image(save: AmigaSavegame) -> bytes:
    """The common regions re-cut as the corresponding DOS container.

    This is only a bridge to ``world_state.from_dos``.  The variable array has
    the same words and the later DOS square block carries the same wallset
    pairs; only endianness and the embedded-party tail differ.
    """
    container = dos_savegame.container_for(save.container.key)
    out = bytearray(container.size)
    out[0] = save.data[0]
    for i in range(0, VM_BYTES, 2):
        out[1 + i:1 + i + 2] = save.data[1 + i:1 + i + 2][::-1]
    if save.container.ecl_bytes:
        start = 1 + VM_BYTES
        out[start:start + ECL_BYTES] = save.data[start:start + ECL_BYTES]
    dos_savegame.put_position(
        out, save.x, save.y,
        save.facing // dos_savegame.FACING_SCALE, container)
    blocks = tuple(block for block, _slot in save.wallset)
    dos_savegame.put_wall_block(out, blocks, container)
    dos_savegame.put_party_size(out, save.count, container)
    return bytes(out)


def state_from_savegame(save: AmigaSavegame) -> world_state.WorldState:
    if save.container.party == "filenames":
        return world_state.from_amiga(save.data)
    state = world_state.from_dos(_dos_image(save), save.container.key,
                                 source=save.characters[0].source)
    # Later DOS saves keep this table in their square block too, but the
    # generic DOS reader predates that layout and reads Pool of Radiance's
    # variable-array triple.  The Amiga save routine names these six words
    # directly, so take them from the parsed table.
    return dataclasses.replace(
        state, wallset=tuple(block for block, _slot in save.wallset))


def read_por_state(data: bytes, source: str = "") -> world_state.WorldState:
    """Pool of Radiance's filename-party container as a world state."""
    parsed = parse(data, POOL_OF_RADIANCE, source)
    return dataclasses.replace(state_from_savegame(parsed), source=source)


def _glib_blocks(data: bytes, name: str = "ECL.GLB") -> tuple[bytes, ...]:
    """The uncompressed blocks of an Amiga GLIB container."""
    if data[:4] != b"GLIB" or data[12:16] != b"DATA":
        raise AmigaSaveError(f"{name} is not a GLIB container")
    count = int.from_bytes(data[8:10], "big")
    table = 16
    try:
        offsets = struct.unpack_from(f">{count + 1}I", data, table)
    except struct.error as error:
        raise AmigaSaveError(f"{name} has a truncated block table") from error
    if tuple(sorted(offsets)) != offsets or offsets[-1] != len(data):
        raise AmigaSaveError(f"{name} has invalid block offsets")
    return tuple(data[offsets[i]:offsets[i + 1]] for i in range(count))


def area_script(ecl_glb: bytes, area: int) -> bytes:
    blocks = _glib_blocks(ecl_glb)
    if not 0 <= area < len(blocks):
        raise AmigaSaveError(
            f"ECL.GLB has {len(blocks)} blocks and no area {area}")
    return blocks[area]


@dataclasses.dataclass
class SaveReport(neutral.Report):
    total: int = 0
    unwritten: list[int] = dataclasses.field(default_factory=list)
    converted: list[str] = dataclasses.field(default_factory=list)

    def summary_notes(self) -> list[str]:
        lines = list(self.converted)
        if self.unwritten:
            lines.append(
                f"{len(self.unwritten)} bytes left without provenance; "
                f"the first is {self.unwritten[0]:#x}")
        return lines


def new_savegame(state: world_state.WorldState,
                 characters: Sequence[neutral.NeutralCharacter],
                 slot: str,
                 ecl_glb: bytes | None = None,
                 icons: Sequence[object | None] | None = None,
                 ) -> tuple[bytes, SaveReport]:
    """Build one later-title Amiga saved game from zeroes.

    Curse requires ``ECL.GLB`` from the player's Amiga disk holding the
    current area.  Silver Blades stages no script and rejects that argument.
    Every character is converted through ``write_later`` and embedded in
    marching order.
    """
    container = container_for(c64_port.by_title(state.title).key)
    party = tuple(characters)
    if not 1 <= len(party) <= PARTY_MAX:
        raise AmigaSaveError(
            f"a {container.title} party is 1 to {PARTY_MAX} characters; "
            f"got {len(party)}")
    if icons is None:
        icons = (None,) * len(party)
    if len(icons) != len(party):
        raise AmigaSaveError("the icon count does not match the party count")
    built = []
    char_reports = []
    report = SaveReport()
    for char, icon in zip(party, icons):
        block, char_report = amiga_later.write_later(char, container.deltas,
                                                      icon=icon)
        built.append(block)
        char_reports.append(char_report)
        report.dropped.extend(char_report.dropped)
        report.warnings.extend(char_report.warnings)

    script = None
    if container.ecl_bytes:
        if ecl_glb is None:
            raise AmigaSaveError(
                "Amiga Curse needs ECL.GLB from the player's game disk")
        script = b"\0\0" + area_script(ecl_glb, state.area)
    elif ecl_glb is not None:
        raise AmigaSaveError("Amiga Silver Blades does not stage ECL.GLB")

    dos_container = dos_savegame.container_for(container.key)
    dos = bytearray(dos_container.size)
    dos_report = dos_codec.SaveReport(total=dos_container.size)
    where = areas.area_in(state.area, state.title)
    if where is None:
        raise AmigaSaveError(
            f"area {state.area} has no {state.title} row in goldbox/areas.py")
    dos_codec.savgam_writes(
        dos, dos_report, state, slot_letter(slot), len(built), script,
        game=container.key, dax=where.disk)
    dos_codec.savgam_zeroes(dos, dos_report, dos_container)

    out = bytearray()
    out.append(dos[0])
    report.note(0, 1, dos_report.sources[0])
    for i in range(0, VM_BYTES, 2):
        out += dos[1 + i:1 + i + 2][::-1]
        report.sources[1 + i] = dos_report.sources[2 + i]
        report.sources[2 + i] = dos_report.sources[1 + i]
    if container.ecl_bytes:
        start = 1 + VM_BYTES
        out += dos[start:start + ECL_BYTES]
        for i in range(start, start + ECL_BYTES):
            report.sources[i] = dos_report.sources[i]
    tail_at = len(out)
    out += state.x.to_bytes(container.x_bytes, "big")
    out += state.y.to_bytes(container.x_bytes, "big")
    out += bytes((state.facing * dos_savegame.FACING_SCALE, 0, 0, 0))
    out += bytes((GAME_MODE_OVERLAND if state.outdoors else
                  GAME_MODE_ADVENTURING, GAME_MODE_CAMP))
    wallset = (dos_savegame.OUTDOOR_WALLSET if state.outdoors
               else state.wallset)
    for index, block in enumerate(wallset):
        out += int(block).to_bytes(2, "big")
        out += int(EMPTY if block == EMPTY else index + 1).to_bytes(2, "big")
    out += len(built).to_bytes(2, "big")
    report.note(tail_at, container.x_bytes, "x square copied from the source save")
    report.note(tail_at + container.x_bytes, container.x_bytes,
                "y square copied from the source save")
    report.note(tail_at + 2 * container.x_bytes, 1,
                "facing copied from the source save in the Amiga's doubled encoding")
    report.note(tail_at + 2 * container.x_bytes + 1, 3,
                "the square block's three measured zero pad bytes")
    report.note(container.first_mode_at, 1,
                "overland or adventuring mode derived from the source position")
    report.note(container.mode_at, 1, "camp mode, which is where a loaded save resumes")
    report.note(container.wallset_at, 12,
                "three wall blocks copied from the source area and numbered in order")
    report.note(container.count_at, 2, "the number of converted characters")
    party_at = len(out)
    for block, char_report in zip(built, char_reports):
        raw = block.block_bytes()
        out += raw
        for offset, why in char_report.sources.items():
            report.sources[party_at + offset] = why
        party_at += len(raw)

    parsed = parse(bytes(out), container, source="converted")
    landed = state_from_savegame(parsed)
    for field in ("title", "area", "geo", "x", "y", "facing", "clock",
                  "wallset", "flags", "scratch", "outdoors", "travel"):
        if getattr(landed, field) != getattr(state, field):
            raise AmigaSaveError(
                f"the built save changed world-state field {field}")
    report.total = len(out)
    report.converted.extend((
        f"the party is at ({state.x},{state.y}) facing {state.facing}",
        f"the clock reads {state.clock[3]:02d}:{state.clock[2]}{state.clock[1]}",
        f"{len(built)} characters in marching order",
    ))
    report.unwritten = [i for i in range(report.total) if i not in report.sources]
    if report.unwritten:
        raise AmigaSaveError(
            f"{len(report.unwritten)} bytes of the Amiga save have no source; "
            f"the first is {report.unwritten[0]:#x}")
    return bytes(out), report


def make_save_disk(container: AmigaContainer | str, slot: str, savegame: bytes,
                   volume: str | None = None) -> AmigaDisk:
    """A fresh OFS disk with one later-title save and no game bytes."""
    container = container_for(container)
    parse(savegame, container, source="converted")
    disk = AmigaDisk.blank(volume or
                           ("AZURESAVE" if container is CURSE else "SECRETSAVE"))
    disk.make_dir(f"/{SAVE_DRAWER}")
    disk.write_file(slot_path(container, slot), savegame)
    problems = disk.verify()
    if problems:
        raise AmigaSaveError("the built Amiga save disk does not verify: "
                             + "; ".join(problems))
    return disk


# Pool of Radiance keeps the party in sibling files.  These disk operations
# live with the shared container map; record conversion remains in amiga_por.
POR_SAVE_DRAWER = "save"
POR_SLOT_LIST_NAME = "save"
POR_SLOT_LIST = f"/{POR_SAVE_DRAWER}/{POR_SLOT_LIST_NAME}"
POR_SLOT_LIST_SIZE = 10
POR_SLOT_LETTERS = SLOT_LETTERS
POR_SAVE_VOLUME = "POOLSAVE"
POR_CHARACTER_LIST_NAME = "charlist.txt"
POR_SAVEGAME_SIZE = 13141
POR_CHARACTER_TABLE = 12813
POR_CHARACTER_TABLE_STRIDE = 41
POR_CHARACTER_TABLE_NAME = 8
POR_PARTY_MAX = PARTY_MAX


def _por_slot(slot: str) -> str:
    letter = slot.upper()
    if len(letter) != 1 or letter not in POR_SLOT_LETTERS:
        raise AmigaSaveError(f"a Pool of Radiance save slot is one of {POR_SLOT_LETTERS}; got {slot!r}")
    return letter


def _por_slot_letter(slot: str) -> str:
    """The filename-table writer's validated uppercase slot letter."""
    return _por_slot(slot)


def por_savegame_filename(slot: str) -> str:
    return f"savgam{_por_slot(slot)}.dat"


def por_save_path(name: str, drawer: str = POR_SAVE_DRAWER) -> str:
    return f"/{drawer}/{name}" if drawer else f"/{name}"


def por_save_drawer(disk: AmigaDisk) -> str:
    try:
        entry = disk.lookup(f"/{POR_SAVE_DRAWER}")
    except AmigaDiskError:
        raise AmigaSaveError(f"{disk.volume_name!r} has no {POR_SLOT_LIST_NAME!r}") from None
    return POR_SAVE_DRAWER if entry.is_dir else ""


def read_slot_list(disk: AmigaDisk, drawer: str = POR_SAVE_DRAWER) -> list[str]:
    try:
        raw = disk.read_file(por_save_path(POR_SLOT_LIST_NAME, drawer))
    except AmigaDiskError:
        return []
    return list(dict.fromkeys(chr(b).upper() for b in raw[:10]
                              if chr(b).upper() in POR_SLOT_LETTERS))


def slot_list_bytes(slots: Sequence[str]) -> bytes:
    out = bytearray(b" " * 10)
    for slot in slots:
        letter = _por_slot(slot)
        out[POR_SLOT_LETTERS.index(letter)] = ord(letter)
    return bytes(out)


def por_slots_present(disk: AmigaDisk, drawer: str | None = None) -> list[str]:
    drawer = por_save_drawer(disk) if drawer is None else drawer
    from . import amiga_por
    out = []
    for letter in POR_SLOT_LETTERS:
        try:
            disk.lookup(por_save_path(por_savegame_filename(letter), drawer))
            disk.lookup(por_save_path(amiga_por.por_filename(letter, 1), drawer))
        except AmigaDiskError:
            continue
        out.append(letter)
    return out


def _por_file(disk: AmigaDisk, letter: str, index: int, suffix: str,
              drawer: str) -> bytes | None:
    from . import amiga_por
    try:
        return disk.read_file(por_save_path(amiga_por.por_filename(letter, index, suffix), drawer))
    except AmigaDiskError:
        return None


def read_por_slot(disk: AmigaDisk, slot: str, drawer: str | None = None):
    """Pool party records and its parsed saved-game bytes from one disk slot."""
    from . import amiga_por
    letter = _por_slot(slot)
    drawer = por_save_drawer(disk) if drawer is None else drawer
    party = []
    for index in range(1, PARTY_MAX + 1):
        raw, items, effects = (_por_file(disk, letter, index, suffix, drawer)
                               for suffix in (".sav", ".itm", ".spc"))
        if raw is None:
            break
        party.append(amiga_por.to_dos_character(amiga_por.por_character(
            raw, items or b"", effects or b"", source=f"{disk.volume_name}:{letter}{index}")))
    if not party:
        raise AmigaRecordError(
            f"slot {letter} has no character files at "
            f"{por_save_path(amiga_por.por_filename(letter, 1), drawer)}")
    try:
        save = disk.read_file(por_save_path(por_savegame_filename(letter), drawer))
    except AmigaDiskError:
        raise AmigaRecordError(f"slot {letter} has character files but no saved game") from None
    parse(save, POOL_OF_RADIANCE, f"{disk.volume_name}:{letter}")
    return party, save


def retarget_savegame(save: bytes, slot: str) -> bytes:
    parsed = parse(save, POOL_OF_RADIANCE, validate=False)
    letter = _por_slot(slot)
    out = bytearray(parsed.data)
    named = 0
    for index in range(8):
        at = POOL_OF_RADIANCE.party_at + index * POR_CHARACTER_TABLE_STRIDE
        if out[at:at + POR_CHARACTER_TABLE_NAME].startswith(b"CHRDAT"):
            out[at + 6] = ord(letter)
            named += 1
    if not named:
        raise AmigaSaveError("the Pool character table has no CHRDAT name")
    return bytes(out)


@contextlib.contextmanager
def _atomic_slot(disk: AmigaDisk):
    snapshot = disk.to_bytes()
    try:
        yield
    except BaseException:
        disk.restore(snapshot)
        raise


def _remove_file(disk: AmigaDisk, path: str) -> None:
    try:
        entry = disk.lookup(path)
    except AmigaDiskError:
        return
    if entry.is_dir:
        raise AmigaSaveError(f"{path!r} is a drawer, not a save file")
    disk.remove_file(path)


def write_por_slot(disk: AmigaDisk, slot: str, characters: Sequence[neutral.NeutralCharacter],
                   savegame: bytes | None = None, drawer: str = POR_SAVE_DRAWER,
                   icons: Sequence[object | None] | None = None) -> list[str]:
    from . import amiga_por
    letter = _por_slot(slot)
    if not 1 <= len(characters) <= PARTY_MAX:
        raise AmigaSaveError(f"a Pool of Radiance party is 1 to {PARTY_MAX} characters; got {len(characters)}")
    icons = [None] * len(characters) if icons is None else icons
    if len(icons) != len(characters):
        raise AmigaSaveError("the icon count does not match the party count")
    with _atomic_slot(disk):
        written = []
        for index, (character, icon) in enumerate(zip(characters, icons), 1):
            record, items, effects, report = amiga_por.write_por(character, icon=icon)
            if report.unaccounted:
                raise AmigaSaveError(f"character {index} has unaccounted bytes")
            stem = por_save_path(amiga_por.por_filename(letter, index, ""), drawer)
            disk.write_file(stem + ".sav", record)
            written.append(stem + ".sav")
            for suffix, payload in ((".itm", items), (".spc", effects)):
                if payload:
                    disk.write_file(stem + suffix, payload)
                    written.append(stem + suffix)
                else:
                    _remove_file(disk, stem + suffix)
        for index in range(len(characters) + 1, PARTY_MAX + 1):
            stem = por_save_path(amiga_por.por_filename(letter, index, ""), drawer)
            for suffix in (".sav", ".itm", ".spc"):
                _remove_file(disk, stem + suffix)
        path = por_save_path(por_savegame_filename(letter), drawer)
        if savegame is not None:
            disk.write_file(path, retarget_savegame(savegame, letter))
            written.append(path)
        else:
            try:
                disk.lookup(path)
            except AmigaDiskError as ex:
                raise AmigaRecordError(str(ex)) from None
        listing = por_save_path(POR_SLOT_LIST_NAME, drawer)
        disk.write_file(listing, slot_list_bytes(read_slot_list(disk, drawer) + [letter]))
        written.append(listing)
        if letter not in read_slot_list(disk, drawer):
            raise AmigaSaveError(f"slot {letter} is not listed after writing")
    return written


def make_por_save_disk(slot: str, characters: Sequence[neutral.NeutralCharacter],
                       savegame: bytes, volume: str = POR_SAVE_VOLUME,
                       icons: Sequence[object | None] | None = None) -> AmigaDisk:
    """A fresh POOLSAVE disk containing one Pool of Radiance slot."""
    disk = AmigaDisk.blank(volume)
    disk.write_file(por_save_path(POR_CHARACTER_LIST_NAME, ""), b"")
    write_por_slot(disk, slot, characters, savegame, drawer="", icons=icons)
    return disk


# **The four bytes between the two files** (13141 against DOS's 13137): the
# Amiga has no container byte at the front, and its tail is thirteen bytes
# where DOS's is eight.  The five extra are 12805-12809 -- two the square
# struct pads to and the first three of wallset entry 0, which the game's
# 10-byte write runs into -- and nothing reads any of them.  5 - 1 = 4.
#
# **The corpus cannot settle a field and this is why.**  There are ten distinct
# Amiga Pool of Radiance saved games on this machine, the shipped one and nine
# the engine wrote, and every one of them is at (0,4) facing west at 05:48 in
# New Phlan.  Diffing all ten gives 148 differing bytes, every one of them the
# party size or inside the 328-byte character table; the whole variable array
# and the whole script buffer are identical.  So no Amiga saved game here can
# be differenced into a map, the map has to come from the code and from the
# DOS page, and the proof has to come from the running game.

#: The variable array: 2560 big-endian words at the front of the file, indexed
#: by the ECL address the bytecode itself uses.  DOS spends a container byte
#: ahead of its copy and the Amiga does not, which is why the offset has no
#: `+ 1` in it.
POR_VAR_BASE = 0x4900
POR_VAR_WORDS = 2560
POR_VAR_OFFSET = 0
POR_VAR_LAST = POR_VAR_BASE + POR_VAR_WORDS - 1

#: `(start, end)` of the staged area script, and how much of the `.dax` block
#: is header rather than script.  Live on load: DOS dies in `Load3DMap` when
#: the buffer holds somebody else's area (#60), and the Amiga loader reads the
#: same buffer back into the same globals.
POR_ECL_BUFFER = (5120, 12800)
POR_ECL_HEADER = 2

#: The thirteen-byte tail, in the order the save routine writes it.
POR_POS_X, POR_POS_Y, POR_POS_FACING = 12800, 12801, 12802
#: The wall art in front of the party, `fn(x, y, facing)`, recomputed by the
#: step routine at `/program` `0x2ec1c`.
POR_WALL_BYTE = 12803
#: What the engine leaves in :data:`POR_WALL_BYTE` **outdoors**, where there
#: is no wall in front of anybody: 14, in both engine-written outdoor Amiga
#: saved games (`#321 (An Amiga Pool of Radiance conversion refuses a party
#: standing on the travel grid, because no outdoor Amiga saved game has ever
#: been read)`, 2026-09-07).  It did not move across an overland step that
#: changed the square and the facing, and it is the same 14 DOS's own
#: engine-written outdoor saves hold at `goldbox.dos_savegame.SCRATCH_BYTE`.
POR_WALL_OUTDOORS = 14
#: A square property, `fn(x, y)` at `0x2ec54`, and the low byte of `$5200`.
#: The two engine-written outdoor saves hold 1 here with `$5200` = 1, keeping
#: that relationship; this writer leaves `$5200` zero, so it writes zero.
POR_SQUARE_PROPERTY = 12804
#: `(start, end)` of the five bytes nothing reads: two the struct pads to and
#: the first three of wallset entry 0.  The write is ten bytes long and the
#: struct is seven (`docs/165-amiga-savegame.md`).
POR_SQUARE_PAD = (12805, 12810)
#: The view type.  The code beside the write names **1 = 3D and 2 = overland**
#: and that second value is not what the engine stores: two saved games the
#: Amiga game itself made on the travel grid hold **3**, which is what DOS
#: holds at `goldbox.dos_savegame.VIEW_MODE_BYTE` in 10 of 10 outdoor
#: specimens.  So the two ports agree after all, and 2 belongs to a mode
#: nothing here has seen -- `#321 (An Amiga Pool of Radiance conversion
#: refuses a party standing on the travel grid, because no outdoor Amiga
#: saved game has ever been read)`, 2026-09-07.
POR_VIEW_TYPE = 12810
POR_VIEW_TYPE_3D = 1
POR_VIEW_TYPE_OVERLAND = 3
#: What the code beside the write calls the overland, and what no saved game
#: on this machine has ever held.  Kept named so the disagreement above is
#: readable rather than looking like a typo.
POR_VIEW_TYPE_CODE_OVERLAND = 2
#: The game mode.  A save is taken from camp, so this is 2 in every saved game
#: the engine writes -- all ten here.
POR_GAME_MODE = 12811
POR_GAME_MODE_CAMP = 2
POR_PARTY_SIZE_BYTE = 12812
#: Eight 41-byte name slots, of which the first `count` are used.
POR_NAME_SLOTS = 8

#: The empty wallset word, and the words the triple and its index map live in.
POR_EMPTY = 0xFFFF
POR_WALLSET = 0x4AFA
POR_WALLMAP = 0x4AFD


def por_word_offset(address: int) -> int:
    """File offset of the variable-array word for an ECL address."""
    if not POR_VAR_BASE <= address <= POR_VAR_LAST:
        raise AmigaRecordError(
            f"${address:04X} is outside the Amiga Pool of Radiance variable "
            f"array ${POR_VAR_BASE:04X}-${POR_VAR_LAST:04X}")
    return POR_VAR_OFFSET + 2 * (address - POR_VAR_BASE)


def por_word(save: bytes, address: int) -> int:
    at = por_word_offset(address)
    return int.from_bytes(save[at:at + 2], "big")


def por_put_word(save: bytearray, address: int, value: int) -> None:
    at = por_word_offset(address)
    save[at:at + 2] = (value & 0xFFFF).to_bytes(2, "big")


#: `PorSaveState` is now `WorldState` under its old name (`#352 (Lift
#: PorSaveState into one WorldState that every port's saved-game reader
#: fills and both container writers take)`): `por_savegame_writes` below only
#: ever reads the ten fields Pool of Radiance needed, and a `WorldState` is
#: a strict superset of those, so nothing here has to convert one into the
#: other.  The three `por_state_from_*` readers are one-line wrappers of
#: `goldbox.world_state`'s three general ones, each keeping the one thing
#: that was Amiga-specific about it.  **They no longer refuse an outdoor
#: party**: the two bytes that had never been seen were measured on
#: 2026-09-07, on two saved games the Amiga game itself made on the travel
#: grid (`#316 (Write the Amiga Pool of Radiance saved game from the source
#: save, so a converted party arrives where it was standing)`, `#321 (An
#: Amiga Pool of Radiance conversion refuses a party standing on the travel
#: grid, because no outdoor Amiga saved game has ever been read)`).
PorSaveState = world_state.WorldState


def por_state_from_c64(save0: bytes, source: str = "") -> PorSaveState:
    """A C64 Pool of Radiance `SAVEDGAME0` payload, as a place and a clock."""
    return world_state.from_c64(save0, source=source)


def por_state_from_dos(savgam: bytes, source: str = "") -> PorSaveState:
    """A DOS `SAVGAM<slot>.DAT`, as a place and a clock."""
    return world_state.from_dos(savgam, source=source)


def por_state_from_amiga(savgam: bytes, source: str = "") -> PorSaveState:
    """An Amiga `savgam<letter>.dat`, as a place and a clock.

    Here so the writer can be checked against the game's own file: read a
    shipped saved game through this, hand the result back to
    :func:`new_por_savegame`, and every byte that differs has to be one the
    writer *declares* it cannot source.  A round trip masked by the declared
    list rather than by the diff is the test
    `.claude/rules/conversions.md` asks for.
    """
    if len(savgam) != POR_SAVEGAME_SIZE:
        raise AmigaRecordError(
            f"an Amiga Pool of Radiance saved game is {POR_SAVEGAME_SIZE} "
            f"bytes, got {len(savgam)}")
    return world_state.from_amiga(savgam, source=source)


#: The travel grid used to be refused here, because two bytes of an outdoor
#: Amiga saved game had never been seen.  **Both were measured on 2026-09-07**
#: and both agree with DOS: byte 12810, the view type, is
#: :data:`POR_VIEW_TYPE_OVERLAND` = 3, and byte 12803, the wall in front, is
#: :data:`POR_WALL_OUTDOORS` = 14.  A party bought passage from New Phlan's
#: harbour master, sailed to the west landing and camped and saved there
#: twice, one overland step apart, in Amiga Pool of Radiance under WinUAE;
#: `tools/porboat.py` staged the eight bytes that put it in front of the
#: harbour master and the engine wrote everything else.  `#321 (An Amiga Pool
#: of Radiance conversion refuses a party standing on the travel grid,
#: because no outdoor Amiga saved game has ever been read)` and
#: `docs/196-the-amiga-saved-game-built.md` have the numbers.
#:
#: What an outdoor container needs beyond those two, all of it now written by
#: :func:`por_savegame_writes` and all of it the same as DOS's outdoor path
#: (`#190 (A C64 party standing on the travel grid cannot be written into a
#: DOS save)`): `$49E6` = 0, `$49C5` = 0, the travel square in
#: `$49C3`/`$49C4`, the area in `$49F2`, the wallset triple
#: `(0, $FFFF, $FFFF)`, and the indoor square left stale in bytes 12800-12801
#: while the facing at 12802 stays live.

#: Why an area cannot be written, or `None`.  Two refusals, and both are about
#: the script rather than about the party.
#:
#: `ecl.dax` on disk 2 holds blocks 0-11 and 13-29.  Area 30 (`ECL1E`) has no
#: Amiga block at all -- 29 of the C64's 30, which
#: `docs/117-save-conversion.md` already recorded -- so a party standing there
#: has no script to stage and the save would carry somebody else's area.
POR_NO_AMIGA_SCRIPT = ("area {area} has no script in the Amiga game's own "
                       "ecl.dax, so there is nothing to stage in the saved "
                       "game and the party would arrive in somebody else's "
                       "area")


def por_conversion_reason(area: int) -> "str | None":
    """Why this area cannot be converted to the Amiga, or `None` if it can.

    The mirror of `goldbox.dos_codec.conversion_reason`.  An area with no row has no
    disk number and no script.  **The three travel windows are no longer
    refused**: areas 25, 26 and 27 have blocks in `ecl.dax` and the two bytes
    that stopped this were measured (`#321 (An Amiga Pool of Radiance
    conversion refuses a party standing on the travel grid, because no
    outdoor Amiga saved game has ever been read)`).  Whether `ecl.dax` holds
    the block is checked by :func:`por_area_script`, which is the only place
    that can see the player's own disk.
    """
    where = areas.area(area)
    if where is None:
        return (f"area {area} is not an area of Pool of Radiance, so there is "
                f"no script to stage")
    return None


def por_area_script(ecl_dax: bytes, area: int) -> bytes:
    """The area's own block of the Amiga `ecl.dax`, unpacked.

    The block **including** its two-byte header; the writer stages it from
    byte :data:`POR_ECL_HEADER` on, which is the relationship the shipped save
    has with block 0 -- byte for byte over all 7468 bytes.
    """
    from . import amiga_dax

    why = por_conversion_reason(area)
    if why is not None:
        raise AmigaRecordError(why)
    try:
        return amiga_dax.block(ecl_dax, area, "ecl.dax")
    except amiga_dax.AmigaDaxError as e:
        raise AmigaRecordError(
            f"{POR_NO_AMIGA_SCRIPT.format(area=area)} ({e})") from e


#: The reasons a word this conversion cannot source is written **zero** rather
#: than left at somebody else's value.  Each is the head of a reason string in
#: :data:`POR_SAVGAM_UNSOURCED`.
POR_ENGINE_REBUILT = (
    "one of the words the Amiga engine rewrites for itself: it came back "
    "non-zero from the game's own ENCAMP > SAVE of a party loaded out of a "
    "container built here with it zero, in both WinUAE runs of #316 -- and "
    "the same word is engine-rebuilt on DOS (#59, #26)")
POR_ENGINE_ONLY = (
    "engine state with no counterpart in a C64 or DOS save -- above $4AF9, "
    "which no ECL script in the thirty-script corpus references (#59)")
POR_ENCOUNTER_STATE = (
    "the pending-encounter record: it changes together with the message "
    "buffer beside it, and a converted party has no encounter pending")

#: Words of `$4900`-`$52FF` no source save can answer for, written **zero**
#: with the reason each is nobody's.  The Amiga counterpart of
#: `goldbox.dos_codec.SAVGAM_UNSOURCED`, and it is that list address for address --
#: which is a finding rather than a convenience.  **Every one of the 92
#: distinct nonzero words the ten Amiga saved games on this machine hold is
#: either written by :func:`por_savegame_writes` or named here**, with nothing
#: left over.
POR_SAVGAM_UNSOURCED: tuple[tuple[int, int, str], ...] = (
    (0x49F0, 2, f"the previous square -- {POR_ENGINE_REBUILT}"),
    (0x49FC, 1, "an engine byte the save routine copies into the array and "
                "the loader copies back out (`g3d3e`, "
                "`docs/165-amiga-savegame.md`). The three ports disagree on "
                "it -- the Amiga reads 1, DOS 6 or 4 by area, the C64 2 -- so "
                "there is nothing to convert"),
    (0x49FD, 2, "the two wall colours, which the arriving area's own ECL "
                "prologue writes on entry: `ECL00` opens `SAVE [$6E7D],"
                "[$49FD] / SAVE 10,[$49FE]` and `ECL14` the same with 9. "
                "Measured in the running game: both WinUAE runs of #316 wrote "
                "zero here, and the engine's own resave of a party standing "
                "in the Slums came back holding the Slums' 9"),
    (0x4DB8, 1, POR_ENGINE_ONLY), (0x4DC3, 1, POR_ENGINE_ONLY),
    (0x4E0C, 1, POR_ENGINE_ONLY), (0x4FA8, 1, POR_ENGINE_ONLY),
    (0x4FC0, 2, POR_ENGINE_ONLY), (0x4FC6, 1, POR_ENGINE_ONLY),
    (0x4FC8, 1, POR_ENGINE_ONLY),
    (0x4FD2, 2, "the rest-interruption pair `$6DD2`/`$6DD3` -- how many "
                "five-minute passes between checks and the chance of one. The "
                "area's own script writes them on ENCAMP and the area-init "
                "routine zeroes them on load. Measured: both WinUAE runs of "
                "#316 wrote zero and the engine's resave in the Slums came "
                "back with the Slums' own (24, 24), which is docs/141's "
                "figure for that area"),
    (0x5079, 1, POR_ENGINE_REBUILT),
    (0x507A, 4, POR_ENGINE_ONLY + " -- and the overland script's own loop "
                "registers, rewritten on the first step out there (#59)"),
    (0x507F, 2, POR_ENGINE_ONLY),
    (0x5082, 1, POR_ENGINE_REBUILT),
    (0x5200, 1, POR_ENGINE_REBUILT),
    (0x5202, 6, POR_ENCOUNTER_STATE),
    (0x5208, 1, POR_ENGINE_REBUILT),
    (0x520A, 6, POR_ENCOUNTER_STATE),
    (0x5227, POR_VAR_LAST - 0x5227 + 1,
     "the encounter and monster message buffers, one ASCII character per "
     "word -- a converted party is not being shouted at. The shipped Amiga "
     "save is still holding `YOU HAVE SURPRISED A PARTY OF  ORCS.`"),
)

#: The 32 bytes of heap after each of the eight names in the character table.
#: Written zero, and the same 274 bytes DOS zeroes: display scratch, and the
#: evidence is what is in them -- the engine's own menu words, and the ten
#: Amiga saved games differ from each other in almost nothing else.
POR_TABLE_SCRATCH = ("display scratch: the 33 bytes after each of the eight "
                     "names in the character table, zeroed")

#: Words written to a value **measured** rather than sourced, as
#: `(address, value, why)`.
#:
#: `$49FF` gates the sheet portrait on the C64 (`LIBRARY $48A9`, bit 7) and on
#: DOS, where zero left a converted party faceless whatever its records said
#: (#57).  **It gates nothing on the Amiga**: that port draws no portrait on
#: a character sheet at all, and no box for one -- where the other two put a
#: face it puts `GOLD`, `ENCUMBRANCE` and `MOVEMENT`, watched on seven sheets
#: across two WinUAE sessions on 2026-09-07
#: (`#322 (Nobody has looked at an Amiga Pool of Radiance character sheet to
#: see whether it draws a portrait at all)`, `docs/206-three-amiga-questions.md`).
#: Writing 3 stays right -- it is what 17 of the 19 Amiga saved games here
#: hold, the two exceptions being a container we built with no portrait
#: crossed and the engine's resave of it, which inherited that zero rather
#: than choosing it -- so nothing a player sees changes; what changed is the
#: reason (`#441 (A converted Amiga save's provenance claims three words are
#: zero in every saved game, and they are not)`).  The Amiga's own code
#: calls it `2 * g63d1 + g63d0`, split back into two engine bytes on load,
#: and it is the same 3 all three engine-written DOS ones hold.  PROBABLE
#: for the Amiga: the value is the engine's own on both ports that have been
#: bisected, and no Amiga run has bisected it.
POR_SAVGAM_MEASURED: tuple[tuple[int, int, str], ...] = (
    (0x49FF, 3, "the word that gates the sheet portrait on the two ports "
                "where it has been bisected, and 3 is what it reads in "
                "every Amiga and DOS saved game measured except our own "
                "builds with no portrait crossed and their engine resaves, "
                "which inherit that zero rather than choosing it -- re-run "
                "`tools/amigasavegame.py --sweep` for a current count "
                "(#57, #441)"),
)


@dataclass
class PorSaveReport(neutral.Report):
    """Where every byte of a built `savgam<letter>.dat` came from.

    `sources` covers all 13141 bytes, so what is *not* written is countable --
    which is the whole of how "no template" is checked rather than asserted.
    """

    total: int = POR_SAVEGAME_SIZE
    #: One line per field taken from the source save, for a person to read.
    converted: list[str] = dataclass_field(default_factory=list)
    #: Offsets nothing wrote.  **Empty when the buffer started from zeroes**,
    #: and that is what makes "no template" checkable rather than asserted.
    unwritten: list[int] = dataclass_field(default_factory=list)

    def address(self, offset: int) -> str:
        """`$4A20` for a variable, `the script buffer`, or `byte 12800`."""
        if POR_VAR_OFFSET <= offset < POR_VAR_OFFSET + 2 * POR_VAR_WORDS:
            word = POR_VAR_BASE + (offset - POR_VAR_OFFSET) // 2
            return f"${word:04X}"
        if POR_ECL_BUFFER[0] <= offset < POR_ECL_BUFFER[1]:
            return "the script buffer"
        return f"byte {offset}"

    def summary_notes(self) -> list[str]:
        lines = [f"  converted: {c}" for c in self.converted]
        if self.unwritten:
            lines.append(f"  {len(self.unwritten)} bytes unwritten, from "
                         f"{self.address(self.unwritten[0])}")
        return lines


def _por_note_word(report: PorSaveReport, address: int, words: int,
                   why: str) -> None:
    report.note(por_word_offset(address), 2 * words, why)


def por_savegame_writes(save: bytearray, report: PorSaveReport,
                        state: PorSaveState, slot: str, count: int,
                        script: bytes, *, portraits: bool = False) -> None:
    """Write everything the source save answers for into a 13141-byte buffer.

    `save` is modified in place and every byte written gets a line in
    `report.sources`.  `script` is the party's own area's `ecl.dax` block,
    header and all; there is no path here without one, because the buffer is
    live on load and a save carrying a stranger's area is a party standing
    somewhere it has never been.
    """
    where = areas.area(state.area)
    why = por_conversion_reason(state.area)
    if why is not None:
        raise AmigaRecordError(why)

    outdoors = state.outdoors
    por_put_word(save, dos_savegame.AREA, 0 if outdoors else state.geo)
    _por_note_word(report, dos_savegame.AREA, 1,
                   "zero, which is what both engine-written outdoor Amiga "
                   "saves hold: a travel window loads a SQRDATA rather than "
                   "a GEO and $49E6 is what picks the file type (#321)"
                   if outdoors else
                   "the resident GEO, the source save's own $49C5 -- which is "
                   "not the area id for a script that loads no map of its own")
    por_put_word(save, dos_savegame.SCRIPT, state.area)
    _por_note_word(report, dos_savegame.SCRIPT, 1,
                   f"the area the party is in, {state.area} "
                   f"({where.name or where.ecl})")
    por_put_word(save, dos_savegame.DISK, where.disk)
    _por_note_word(report, dos_savegame.DISK, 1,
                   f"the container number, {where.disk}. The Amiga keeps it "
                   f"only here: it has no header byte where DOS has one")
    wallset = (dos_savegame.OUTDOOR_WALLSET if outdoors else state.wallset)
    for i, w in enumerate(wallset):
        por_put_word(save, POR_WALLSET + i, w)
    _por_note_word(report, POR_WALLSET, 3,
                   "the overland wallset triple (0, $FFFF, $FFFF), which is "
                   "the engine's own out here rather than whatever the party "
                   "left the grid on -- both Amiga saved games made outdoors "
                   "hold it, as do six DOS ones (#190, #321)"
                   if outdoors else
                   "the wallset triple, the source save's own three "
                   "WALLDEF/8X8D block ids")
    for i, w in enumerate(dos_savegame.wall_map(wallset)):
        por_put_word(save, POR_WALLMAP + i, w)
    _por_note_word(report, POR_WALLMAP, 3,
                   "the wall-index map that goes with the triple")

    body = script[POR_ECL_HEADER:]
    start, end = POR_ECL_BUFFER
    if len(body) > end - start:
        raise AmigaRecordError(
            f"area {state.area}'s script is {len(body)} bytes and the "
            f"buffer holds {end - start}")
    save[start:start + len(body)] = body
    report.note(start, end - start,
                f"the area's own ecl.dax block {state.area} from byte "
                f"{POR_ECL_HEADER} on, then zero to the end of the buffer -- "
                f"which is what the shipped saved game holds past its "
                f"script's end, byte for byte over 7468 bytes")

    por_put_word(save, dos_savegame.INDOORS, 0 if outdoors else 1)
    _por_note_word(report, dos_savegame.INDOORS, 1,
                   "outdoors" if outdoors else "indoors")
    if outdoors:
        travel_x, travel_y = state.travel
        por_put_word(save, dos_savegame.TRAVEL_X, travel_x)
        por_put_word(save, dos_savegame.TRAVEL_Y, travel_y)
        _por_note_word(report, dos_savegame.TRAVEL_X, 2,
                       f"the travel square ({travel_x},{travel_y}), "
                       f"window-local, the source save's own. The Amiga "
                       f"keeps it where DOS does and the status line prints "
                       f"the world coordinate instead (#321)")
    else:
        _por_note_word(report, dos_savegame.TRAVEL_X, 2,
                       "zeroed: this party is indoors, so this build "
                       "writes no travel square here. That is not the same "
                       "as reading zero in every Amiga saved game -- the "
                       "sweep finds these two words non-zero in the saved "
                       "games made on the travel grid; re-run "
                       "`tools/amigasavegame.py --sweep` for a current "
                       "count (#441)")

    save[POR_POS_X] = state.x
    save[POR_POS_Y] = state.y
    save[POR_POS_FACING] = state.facing * dos_savegame.FACING_SCALE
    report.note(POR_POS_X, 3,
                f"the indoor square ({state.x},{state.y}) the party left, "
                f"which the engine freezes out here, and facing "
                f"{state.facing}, which stays live and steps with the party"
                if outdoors else
                f"the square ({state.x},{state.y}) facing {state.facing}, the "
                f"source save's own, doubled the way both ports store it")
    save[POR_WALL_BYTE] = POR_WALL_OUTDOORS if outdoors else 0
    report.note(POR_WALL_BYTE, 1,
                f"the wall in front of the party: {POR_WALL_OUTDOORS}, which "
                f"is what both saved games the Amiga game itself made on the "
                f"travel grid hold, unmoved across a step that changed the "
                f"square and the facing (#321). DOS holds the same 14 there "
                f"outdoors"
                if outdoors else
                "the wall art in front of the party: zero. It is a function "
                "of the map and the facing and the step routine recomputes it "
                "(/program 0x2ec1c). Measured: the engine's own ENCAMP > SAVE "
                "of a party loaded out of a container written this way came "
                "back holding zero too, in both WinUAE runs of #316")
    save[POR_SQUARE_PROPERTY] = 0
    report.note(POR_SQUARE_PROPERTY, 1,
                "the square property: zero. It is the low byte of $5200, "
                "which nothing can source, and the same step routine "
                "rewrites it. The engine's own resave holds zero here too "
                "(#316), and its own outdoor saves hold 1 with $5200 at 1, "
                "which is the same relationship (#321)")
    pad_start, pad_end = POR_SQUARE_PAD
    report.note(pad_start, pad_end - pad_start,
                "five bytes nothing reads: two the seven-byte square struct "
                "pads to and the first three of wallset entry 0, which the "
                "game's own ten-byte write runs into. Zero in all ten Amiga "
                "saved games here")
    save[POR_VIEW_TYPE] = (POR_VIEW_TYPE_OVERLAND if outdoors
                           else POR_VIEW_TYPE_3D)
    report.note(POR_VIEW_TYPE, 1,
                f"the view type: {POR_VIEW_TYPE_OVERLAND}, the travel grid. "
                f"Both saved games the Amiga game itself made out there hold "
                f"it, and it is what DOS holds in 10 of 10 outdoor specimens "
                f"-- not the 2 the code beside the write names (#321)"
                if outdoors else
                "the view type: 1, the 3D view, from the code beside the "
                "write and 1 in all ten Amiga saved games")
    save[POR_GAME_MODE] = POR_GAME_MODE_CAMP
    report.note(POR_GAME_MODE, 1,
                "the game mode: 2, camp. A save is taken from camp, so this "
                "is what the engine writes -- 2 in all ten")

    por_put_word(save, dos_savegame.PARTY_SIZE, count)
    _por_note_word(report, dos_savegame.PARTY_SIZE, 1,
                   f"the party size, {count}")
    save[POR_PARTY_SIZE_BYTE] = count
    report.note(POR_PARTY_SIZE_BYTE, 1, f"the party size again, {count}")

    letter = _por_slot_letter(slot)
    for n in range(POR_NAME_SLOTS):
        at = POR_CHARACTER_TABLE + n * POR_CHARACTER_TABLE_STRIDE
        if n < count:
            save[at:at + POR_CHARACTER_TABLE_NAME] = \
                f"CHRDAT{letter}{n + 1}".encode("ascii")
            report.note(at, POR_CHARACTER_TABLE_NAME,
                        f"CHRDAT{letter}{n + 1}, which is what the engine "
                        f"loads the party from -- not the slot letter at the "
                        f"picker (#28)")
        else:
            report.note(at, POR_CHARACTER_TABLE_NAME,
                        f"an unused name slot: this party has {count} "
                        f"characters and the table holds {POR_NAME_SLOTS}")
        report.note(at + POR_CHARACTER_TABLE_NAME,
                    POR_CHARACTER_TABLE_STRIDE - POR_CHARACTER_TABLE_NAME,
                    POR_TABLE_SCRATCH)

    for i, address in enumerate(range(dos_savegame.FLAGS_FIRST,
                                      dos_savegame.FLAGS_LAST + 1)):
        por_put_word(save, address, state.flags[i])
    _por_note_word(report, dos_savegame.FLAGS_FIRST,
                   dos_savegame.FLAGS_LAST - dos_savegame.FLAGS_FIRST + 1,
                   "a quest flag: the source save's own value at the same ECL "
                   "address, which is the address all three ports share")
    for address, value in state.scratch.items():
        por_put_word(save, address, value)
        _por_note_word(report, address, 1,
                       "script scratch: the source save's own value at the "
                       "same ECL address")

    for i, digit in enumerate(state.clock):
        por_put_word(save, dos_savegame.CLOCK + i, digit)
    _por_note_word(report, dos_savegame.CLOCK, dos_savegame.CLOCK_DIGITS,
                   "a clock digit, the source save's own")

    for address, value, why in dos_savegame.SAVGAM_CONSTANTS:
        por_put_word(save, address, value)
        _por_note_word(report, address, 1, f"a documented constant: {why}")
    for address, value, why in POR_SAVGAM_MEASURED:
        if address == 0x49FF and not portraits:
            _por_note_word(report, address, 1,
                           "zeroed: no portrait crossed for this party, "
                           "so this build does not write the word that "
                           "gates the sheet portrait on the other two "
                           "ports. That is not the same as reading zero in "
                           "every Amiga saved game -- the sweep finds it "
                           "non-zero in most of the saved games examined, "
                           "including the one SSI shipped; re-run "
                           "`tools/amigasavegame.py --sweep` for a current "
                           "count (#441)")
            continue
        por_put_word(save, address, value)
        _por_note_word(report, address, 1, f"measured: {why}")


def por_savegame_zeroes(save: bytearray, report: PorSaveReport) -> None:
    """Account for every byte :func:`por_savegame_writes` left zero."""
    for address, words, why in POR_SAVGAM_UNSOURCED:
        _por_note_word(report, address, words, f"zeroed -- {why}")
    rest = [i for i in range(POR_VAR_OFFSET,
                             POR_VAR_OFFSET + 2 * POR_VAR_WORDS)
            if i not in report.sources]
    for i in rest:
        report.sources[i] = (
            "zeroed: this word reads zero in every Amiga saved game swept "
            "so far, and nothing in a C64 or DOS save corresponds to it -- "
            "run `tools/amigasavegame.py --sweep` to re-take the "
            "measurement (docs/165-amiga-savegame.md, \"Still open\")")


def new_por_savegame(state: PorSaveState, slot: str, count: int,
                     ecl_dax: bytes, *, portraits: bool = False
                     ) -> "tuple[bytes, PorSaveReport]":
    """Build all 13141 bytes of a `savgam<letter>.dat` from 13141 zeroes.

    `ecl_dax` is the whole of `/ecl.dax` off the player's Amiga disk 2, which
    is the only copy of the party's area's script.  `count` is how many
    characters the slot holds; `slot` is the letter, which is what the eight
    `CHRDAT` names in the table are built from.

    Returns the file and a report whose `sources` covers every byte and whose
    `unwritten` is empty.  There is no template and no argument for one.
    """
    if not 1 <= count <= POR_PARTY_MAX:
        raise AmigaRecordError(
            f"a Pool of Radiance party is 1 to {POR_PARTY_MAX} characters; "
            f"got {count}")
    script = por_area_script(ecl_dax, state.area)
    save = bytearray(POR_SAVEGAME_SIZE)
    report = PorSaveReport(total=POR_SAVEGAME_SIZE)
    por_savegame_writes(save, report, state, slot, count, script,
                        portraits=portraits)
    por_savegame_zeroes(save, report)
    where = areas.area(state.area)
    report.converted = [
        (f"the party is on the travel grid in "
         f"{where.name or where.ecl} at "
         f"({state.travel[0]},{state.travel[1]}), window-local"
         if state.outdoors else
         f"the party is in {where.name or where.ecl} at "
         f"({state.x},{state.y}) facing "
         f"{'NESW'[state.facing % 4]}"),
        f"the clock reads {state.clock[3]:02d}:"
        f"{state.clock[2]}{state.clock[1]}",
        f"{sum(1 for f in state.flags if f)} quest flags are set",
    ]
    report.unwritten = [i for i in range(POR_SAVEGAME_SIZE)
                        if i not in report.sources]
    return bytes(save), report
