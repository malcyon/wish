"""Amiga Curse and Silver Blades saved games and save disks.

Both later titles embed the party after a common big-endian variable array.
The layouts come from their save and load routines; ``docs/165-amiga-savegame.md``
records the byte-level evidence.  This module is the library counterpart of
``tools/amigasavegame.py``: it reads a whole slot and builds one from a
``WorldState`` and neutral characters without a template.
"""

from __future__ import annotations

import dataclasses
import struct
from collections.abc import Sequence

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


class AmigaSaveError(ValueError):
    """A later-title Amiga saved game does not have the measured shape."""


@dataclasses.dataclass(frozen=True)
class SaveShape:
    key: str
    title: str
    suffix: str
    ecl_bytes: int
    x_bytes: int
    deltas: amiga_port.AmigaDeltas

    @property
    def square_at(self) -> int:
        return 1 + VM_BYTES + self.ecl_bytes

    @property
    def square_bytes(self) -> int:
        return 2 * self.x_bytes + 4

    @property
    def first_mode_at(self) -> int:
        return self.square_at + self.square_bytes

    @property
    def mode_at(self) -> int:
        return self.first_mode_at + 1

    @property
    def wallset_at(self) -> int:
        return self.mode_at + 1

    @property
    def count_at(self) -> int:
        return self.wallset_at + 12

    @property
    def party_at(self) -> int:
        return self.count_at + 2

    def word_offset(self, address: int) -> int:
        if not VM_BASE <= address < VM_BASE + VM_BYTES // 2:
            raise AmigaSaveError(f"${address:04X} is outside the variable array")
        return 1 + 2 * (address - VM_BASE)


CURSE = SaveShape(
    "curse-of-the-azure-bonds", "Curse of the Azure Bonds", ".dat",
    ECL_BYTES, 2, amiga_port.CURSE_DELTAS)
SILVER_BLADES = SaveShape(
    "secret-of-the-silver-blades", "Secret of the Silver Blades", ".sav",
    0, 1, amiga_port.SILVER_BLADES_DELTAS)
SHAPES = (CURSE, SILVER_BLADES)
SHAPES_BY_KEY = {shape.key: shape for shape in SHAPES}
SHAPES_BY_SUFFIX = {shape.suffix: shape for shape in SHAPES}

assert CURSE.party_at == 0x3219
assert SILVER_BLADES.party_at == 0x1417


@dataclasses.dataclass(frozen=True)
class Savegame:
    shape: SaveShape
    data: bytes
    x: int
    y: int
    facing: int
    first_mode: int
    mode: int
    wallset: tuple[tuple[int, int], ...]
    characters: tuple[amiga_later.AmigaCharacter, ...]

    @property
    def count(self) -> int:
        return len(self.characters)

    def word(self, address: int) -> int:
        at = self.shape.word_offset(address)
        return int.from_bytes(self.data[at:at + 2], "big")


def shape_for(what: str | SaveShape | amiga_port.AmigaDeltas) -> SaveShape:
    if isinstance(what, SaveShape):
        return what
    key = getattr(what, "key", what)
    try:
        return SHAPES_BY_KEY[key]
    except KeyError:
        raise AmigaSaveError(f"no later Amiga title keyed {key!r}") from None


def slot_letter(slot: str) -> str:
    letter = slot.upper()
    if len(letter) != 1 or letter not in SLOT_LETTERS:
        raise AmigaSaveError(
            f"an Amiga save slot is one of {SLOT_LETTERS}; got {slot!r}")
    return letter


def slot_path(shape: SaveShape | str, slot: str) -> str:
    shape = shape_for(shape)
    return f"/{SAVE_DRAWER}/savgam{slot_letter(slot)}{shape.suffix}"


def detect(data: bytes) -> SaveShape:
    for shape in SHAPES:
        if amiga_later.looks_like_amiga_record(data, shape.party_at,
                                                shape.deltas):
            return shape
    raise AmigaSaveError(
        f"{len(data)} bytes with no Amiga Curse record at {CURSE.party_at:#x} "
        f"or Silver Blades record at {SILVER_BLADES.party_at:#x}")


def parse(data: bytes, shape: SaveShape | str | None = None,
          source: str = "") -> Savegame:
    data = bytes(data)
    shape = detect(data) if shape is None else shape_for(shape)
    if len(data) < shape.party_at:
        raise AmigaSaveError(
            f"{shape.title} needs {shape.party_at} header bytes; got {len(data)}")
    at = shape.square_at
    x = int.from_bytes(data[at:at + shape.x_bytes], "big")
    at += shape.x_bytes
    y = int.from_bytes(data[at:at + shape.x_bytes], "big")
    at += shape.x_bytes
    facing = data[at]
    wallset = tuple(
        (int.from_bytes(data[shape.wallset_at + 4 * i:
                             shape.wallset_at + 4 * i + 2], "big"),
         int.from_bytes(data[shape.wallset_at + 4 * i + 2:
                             shape.wallset_at + 4 * i + 4], "big"))
        for i in range(3))
    count = int.from_bytes(data[shape.count_at:shape.party_at], "big")
    if not 1 <= count <= PARTY_MAX:
        raise AmigaSaveError(
            f"a {shape.title} party is 1 to {PARTY_MAX} characters; got {count}")
    characters = []
    at = shape.party_at
    for _ in range(count):
        char, at = amiga_later._amiga_block(data, at, shape.deltas, source)
        characters.append(char)
    if at != len(data):
        raise AmigaSaveError(
            f"the {count} character blocks end at {at:#x}; file ends at "
            f"{len(data):#x}")
    save = Savegame(shape, data, x, y, facing, data[shape.first_mode_at],
                    data[shape.mode_at], wallset, tuple(characters))
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
              shape: SaveShape | str | None = None) -> Savegame:
    letter = slot_letter(slot)
    if shape is not None:
        shapes = (shape_for(shape),)
    else:
        shapes = SHAPES
    for candidate in shapes:
        path = slot_path(candidate, letter)
        try:
            data = disk.read_file(path)
        except AmigaDiskError:
            continue
        return parse(data, candidate, path)
    raise AmigaSaveError(
        f"slot {letter} is not an Amiga Curse or Silver Blades save")


def slots_present(disk: AmigaDisk,
                  shape: SaveShape | str | None = None) -> list[str]:
    shapes = (shape_for(shape),) if shape is not None else SHAPES
    out = []
    for letter in SLOT_LETTERS:
        if any(_slot_present(disk, candidate, letter)
               for candidate in shapes):
            out.append(letter)
    return out


def _slot_present(disk: AmigaDisk, shape: SaveShape, slot: str) -> bool:
    """Whether the named file is a valid slot for this later title.

    Curse and Pool of Radiance both call their container ``savgamA.dat``.
    File presence alone therefore misidentifies every Pool disk as Curse;
    the container and embedded record have to agree with the later layout.
    """
    path = slot_path(shape, slot)
    try:
        parse(disk.read_file(path), shape, path)
    except (AmigaDiskError, AmigaSaveError):
        return False
    return True


def _dos_image(save: Savegame) -> bytes:
    """The common regions re-cut as the corresponding DOS container.

    This is only a bridge to ``world_state.from_dos``.  The variable array has
    the same words and the later DOS square block carries the same wallset
    pairs; only endianness and the embedded-party tail differ.
    """
    container = dos_savegame.container_for(save.shape.key)
    out = bytearray(container.size)
    out[0] = save.data[0]
    for i in range(0, VM_BYTES, 2):
        out[1 + i:1 + i + 2] = save.data[1 + i:1 + i + 2][::-1]
    if save.shape.ecl_bytes:
        start = 1 + VM_BYTES
        out[start:start + ECL_BYTES] = save.data[start:start + ECL_BYTES]
    dos_savegame.put_position(
        out, save.x, save.y,
        save.facing // dos_savegame.FACING_SCALE, container)
    blocks = tuple(block for block, _slot in save.wallset)
    dos_savegame.put_wall_block(out, blocks, container)
    dos_savegame.put_party_size(out, save.count, container)
    return bytes(out)


def state_from_savegame(save: Savegame) -> world_state.WorldState:
    state = world_state.from_dos(_dos_image(save), save.shape.key,
                                 source=save.characters[0].source)
    # Later DOS saves keep this table in their square block too, but the
    # generic DOS reader predates that layout and reads Pool of Radiance's
    # variable-array triple.  The Amiga save routine names these six words
    # directly, so take them from the parsed table.
    return dataclasses.replace(
        state, wallset=tuple(block for block, _slot in save.wallset))


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
    shape = shape_for(c64_port.by_title(state.title).key)
    party = tuple(characters)
    if not 1 <= len(party) <= PARTY_MAX:
        raise AmigaSaveError(
            f"a {shape.title} party is 1 to {PARTY_MAX} characters; "
            f"got {len(party)}")
    if icons is None:
        icons = (None,) * len(party)
    if len(icons) != len(party):
        raise AmigaSaveError("the icon count does not match the party count")
    built = []
    char_reports = []
    report = SaveReport()
    for char, icon in zip(party, icons):
        block, char_report = amiga_later.write_later(char, shape.deltas,
                                                      icon=icon)
        built.append(block)
        char_reports.append(char_report)
        report.dropped.extend(char_report.dropped)
        report.warnings.extend(char_report.warnings)

    script = None
    if shape.ecl_bytes:
        if ecl_glb is None:
            raise AmigaSaveError(
                "Amiga Curse needs ECL.GLB from the player's game disk")
        script = b"\0\0" + area_script(ecl_glb, state.area)
    elif ecl_glb is not None:
        raise AmigaSaveError("Amiga Silver Blades does not stage ECL.GLB")

    container = dos_savegame.container_for(shape.key)
    dos = bytearray(container.size)
    dos_report = dos_codec.SaveReport(total=container.size)
    where = areas.area_in(state.area, state.title)
    if where is None:
        raise AmigaSaveError(
            f"area {state.area} has no {state.title} row in goldbox/areas.py")
    dos_codec.savgam_writes(
        dos, dos_report, state, slot_letter(slot), len(built), script,
        game=shape.key, dax=where.disk)
    dos_codec.savgam_zeroes(dos, dos_report, container)

    out = bytearray()
    out.append(dos[0])
    report.note(0, 1, dos_report.sources[0])
    for i in range(0, VM_BYTES, 2):
        out += dos[1 + i:1 + i + 2][::-1]
        report.sources[1 + i] = dos_report.sources[2 + i]
        report.sources[2 + i] = dos_report.sources[1 + i]
    if shape.ecl_bytes:
        start = 1 + VM_BYTES
        out += dos[start:start + ECL_BYTES]
        for i in range(start, start + ECL_BYTES):
            report.sources[i] = dos_report.sources[i]
    tail_at = len(out)
    out += state.x.to_bytes(shape.x_bytes, "big")
    out += state.y.to_bytes(shape.x_bytes, "big")
    out += bytes((state.facing * dos_savegame.FACING_SCALE, 0, 0, 0))
    out += bytes((GAME_MODE_OVERLAND if state.outdoors else
                  GAME_MODE_ADVENTURING, GAME_MODE_CAMP))
    wallset = (dos_savegame.OUTDOOR_WALLSET if state.outdoors
               else state.wallset)
    for index, block in enumerate(wallset):
        out += int(block).to_bytes(2, "big")
        out += int(EMPTY if block == EMPTY else index + 1).to_bytes(2, "big")
    out += len(built).to_bytes(2, "big")
    report.note(tail_at, shape.x_bytes, "x square copied from the source save")
    report.note(tail_at + shape.x_bytes, shape.x_bytes,
                "y square copied from the source save")
    report.note(tail_at + 2 * shape.x_bytes, 1,
                "facing copied from the source save in the Amiga's doubled encoding")
    report.note(tail_at + 2 * shape.x_bytes + 1, 3,
                "the square block's three measured zero pad bytes")
    report.note(shape.first_mode_at, 1,
                "overland or adventuring mode derived from the source position")
    report.note(shape.mode_at, 1, "camp mode, which is where a loaded save resumes")
    report.note(shape.wallset_at, 12,
                "three wall blocks copied from the source area and numbered in order")
    report.note(shape.count_at, 2, "the number of converted characters")
    party_at = len(out)
    for block, char_report in zip(built, char_reports):
        raw = block.block_bytes()
        out += raw
        for offset, why in char_report.sources.items():
            report.sources[party_at + offset] = why
        party_at += len(raw)

    parsed = parse(bytes(out), shape, source="converted")
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


def make_save_disk(shape: SaveShape | str, slot: str, savegame: bytes,
                   volume: str | None = None) -> AmigaDisk:
    """A fresh OFS disk with one later-title save and no game bytes."""
    shape = shape_for(shape)
    parse(savegame, shape, source="converted")
    disk = AmigaDisk.blank(volume or
                           ("AZURESAVE" if shape is CURSE else "SECRETSAVE"))
    disk.make_dir(f"/{SAVE_DRAWER}")
    disk.write_file(slot_path(shape, slot), savegame)
    problems = disk.verify()
    if problems:
        raise AmigaSaveError("the built Amiga save disk does not verify: "
                             + "; ".join(problems))
    return disk
