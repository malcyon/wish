#!/usr/bin/env python3
"""Read an Amiga Gold Box saved game through the map its own save routine writes.

`#28 (Decode an Amiga saved game, not just a character file)` found the
container's shape by reading the save and load routines out of the three
executables -- `/Curse`, `/Secret` and Pool of Radiance's `/program` -- and
this is the parser that proves the map was read right.  It walks the file
region by region in the order the game writes it, and :func:`check` compares
what it finds against things the file says independently: the signature scan
in `goldbox.amiga.party_in_savegame`, the `$503E` and `$5012` words in the
variable array, and the file's own length.

    tools/amigasavegame.py --adf work/copy-of-disk.adf
    tools/amigasavegame.py work/28/saves/curse-savgamA.dat

Each title's save routine is a straight run of `write(fd, buf, len)` calls,
so the file is the concatenation in :data:`SHAPES`.  `docs/165-amiga-savegame.md`
carries the map and the evidence; the numbers here are the code's.

Everything is read; nothing is written.
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys
from typing import Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402

#: The three heap blocks the variable array is written from, as one run.
#: The file names them `$4900`-`$52FF`; the second and third really live at
#: `$6B00` and `$9700`, exactly as `docs/163-dos-vm-address-map.md` found on
#: DOS.  2048 + 2048 + 1024.
VM_BYTES = 5120
VM_BASE = 0x4900
#: The staged area script, absent on Silver Blades.
ECL_BYTES = 7680
#: Three (WALLDEF block, slot) `u16be` pairs -- entries 1 to 3 of a four-entry
#: table whose entry 0 is never written.  `$FFFF` is an empty entry.
WALLSET_ENTRIES = 3
WALLSET_BYTES = 4 * WALLSET_ENTRIES
#: Pool of Radiance names its party: eight 41-byte slots, six used.
NAME_SLOTS = 8
NAME_SLOT_BYTES = 41
NAME_BYTES = 8

#: The game-mode byte's values, from the code beside each write of it.  The
#: same enumeration on all three titles.
GAME_MODES = {2: "camp", 3: "overland", 4: "3D adventuring", 5: "combat",
              7: "ending"}
#: Pool of Radiance keeps a view type where the later titles keep the mode
#: before the current one.
VIEW_TYPES = {1: "3D", 2: "overland"}

#: Variable-array words the code names, by address.
NAMED_WORDS = {
    0x49C5: "geo block id",
    0x49C6: "clock: sub-minute",
    0x49C7: "clock: minute units",
    0x49C8: "clock: minute tens",
    0x49C9: "clock: hour",
    0x49CA: "clock: day",
    0x49CB: "clock: month",
    0x49E6: "indoors",
    0x49FC: "engine byte g3d3e (low byte)",
    0x49FF: "2 x g63d1 + g63d0",
    0x5012: "container number",
    0x503E: "party size (cleared on load)",
}


@dataclasses.dataclass(frozen=True)
class SquareField:
    name: str
    size: int
    note: str = ""


@dataclasses.dataclass(frozen=True)
class SaveShape:
    """One title's saved game, as the sequence of writes its code makes."""

    title: str
    #: 1 when the file opens with the container number, 0 when it does not.
    header_bytes: int
    #: 7680 when the area script is staged in the file, 0 when it is not.
    ecl_bytes: int
    #: The square struct, in order, as the save writes it.
    square: tuple[SquareField, ...]
    #: What the byte before the game mode is.
    first_mode_byte: str
    #: Whether the twelve-byte wallset table follows the mode bytes.
    wallset_table: bool
    #: 2 for a `u16be` party count, 1 for a byte.
    count_bytes: int
    #: `records` when the party is embedded, `filenames` for the 8 x 41 table.
    party: str
    #: The record shape for an embedded party, `None` for filenames.
    record_shape: amiga.AmigaShape | None = None
    #: The file's fixed length when the party is filenames, else `None`.
    fixed_size: int | None = None

    @property
    def square_bytes(self) -> int:
        return sum(f.size for f in self.square)

    @property
    def vm_at(self) -> int:
        return self.header_bytes

    @property
    def ecl_at(self) -> int:
        return self.vm_at + VM_BYTES

    @property
    def square_at(self) -> int:
        return self.ecl_at + self.ecl_bytes

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
        return self.mode_at + 1 + (WALLSET_BYTES if self.wallset_table else 0)

    @property
    def party_at(self) -> int:
        return self.count_at + self.count_bytes

    def vm_offset(self, address: int) -> int:
        """File offset of a variable-array word, by its ECL address."""
        if not VM_BASE <= address < VM_BASE + VM_BYTES // 2:
            raise ValueError(f"${address:04X} is outside the variable array")
        return self.vm_at + 2 * (address - VM_BASE)


_WALL = "wall in front of the party, fn(x, y, facing), rewritten on a step"
_PROPERTY = "a square property, fn(x, y), rewritten on the same step"
_PAD = "never referenced by the code"

CURSE = SaveShape(
    title="Curse of the Azure Bonds",
    header_bytes=1, ecl_bytes=ECL_BYTES,
    square=(SquareField("x", 2), SquareField("y", 2), SquareField("facing", 1),
            SquareField("wall_ahead", 1, _WALL),
            SquareField("square_property", 1, _PROPERTY),
            SquareField("pad", 1, _PAD)),
    first_mode_byte="mode before", wallset_table=True, count_bytes=2,
    party="records", record_shape=amiga.CURSE_SHAPE)

SILVER_BLADES = SaveShape(
    title="Secret of the Silver Blades",
    header_bytes=1, ecl_bytes=0,
    square=(SquareField("x", 1), SquareField("y", 1), SquareField("facing", 1),
            SquareField("wall_ahead", 1, _WALL),
            SquareField("square_property", 1, _PROPERTY),
            SquareField("pad", 1, _PAD)),
    first_mode_byte="mode before", wallset_table=True, count_bytes=2,
    party="records", record_shape=amiga.SILVER_BLADES_SHAPE)

POOL_OF_RADIANCE = SaveShape(
    title="Pool of Radiance",
    header_bytes=0, ecl_bytes=ECL_BYTES,
    square=(SquareField("x", 1), SquareField("y", 1), SquareField("facing", 1),
            SquareField("wall_ahead", 1, _WALL),
            SquareField("square_property", 1, _PROPERTY),
            SquareField("pad", 2, _PAD),
            SquareField("wallset_entry_0", 3,
                        "the first three bytes of the wallset table, whose "
                        "entry 0 is never written; the 10-byte write runs "
                        "past the 7-byte struct into it")),
    first_mode_byte="view type", wallset_table=False, count_bytes=1,
    party="filenames",
    fixed_size=(VM_BYTES + ECL_BYTES + 10 + 1 + 1 + 1
                + NAME_SLOTS * NAME_SLOT_BYTES))

SHAPES = (CURSE, SILVER_BLADES, POOL_OF_RADIANCE)

assert POOL_OF_RADIANCE.fixed_size == 13141
assert CURSE.party_at == 0x3219
assert SILVER_BLADES.party_at == 0x1417


class AmigaSaveError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class AmigaSavegame:
    shape: SaveShape
    data: bytes
    #: `(x, y, facing, ...)` by the shape's square field names.
    square: dict[str, int]
    first_mode: int
    mode: int
    #: Entries 1 to 3 as `(block, slot)`, or `()` for Pool of Radiance.
    wallset: tuple[tuple[int, int], ...]
    count: int
    #: Embedded characters, in file order; empty for Pool of Radiance.
    characters: tuple[amiga.AmigaCharacter, ...]
    #: `(offset, end)` of each character block, in file order.
    blocks: tuple[tuple[int, int], ...]
    #: The eight name slots, NUL-stripped; empty for Curse and Silver Blades.
    names: tuple[str, ...]

    @property
    def header_byte(self) -> int | None:
        return self.data[0] if self.shape.header_bytes else None

    def word(self, address: int) -> int:
        at = self.shape.vm_offset(address)
        return int.from_bytes(self.data[at:at + 2], "big")

    @property
    def clock(self) -> str:
        """`hh:mm` from the six digit words, `docs/141`'s layout."""
        return (f"{self.word(0x49C9):02d}:"
                f"{self.word(0x49C8)}{self.word(0x49C7)}")

    @property
    def ecl(self) -> bytes:
        s = self.shape
        return self.data[s.ecl_at:s.ecl_at + s.ecl_bytes]

    @property
    def end(self) -> int:
        """Where the last thing the save wrote ends."""
        if self.blocks:
            return self.blocks[-1][1]
        return self.shape.party_at + (NAME_SLOTS * NAME_SLOT_BYTES
                                      if self.shape.party == "filenames"
                                      else 0)


def detect(data: bytes) -> SaveShape:
    """Which title wrote this, from the file itself.

    Pool of Radiance's is a fixed 13141 bytes with a name table at the end;
    the other two are told apart by where a record signature lands -- the
    Silver Blades header is 5143 bytes and Curse's 12825 -- so a file is
    never read through a map it does not fit.
    """
    if len(data) == POOL_OF_RADIANCE.fixed_size:
        return POOL_OF_RADIANCE
    for shape in (CURSE, SILVER_BLADES):
        if amiga.looks_like_amiga_record(data, shape.party_at,
                                         shape.record_shape):
            return shape
    raise AmigaSaveError(
        f"{len(data)} bytes with no record at {CURSE.party_at:#x} (Curse) or "
        f"{SILVER_BLADES.party_at:#x} (Silver Blades), and not Pool of "
        f"Radiance's {POOL_OF_RADIANCE.fixed_size}")


def parse(data: bytes, shape: SaveShape | None = None,
          source: str = "") -> AmigaSavegame:
    """Read a saved game in the order the game wrote it."""
    data = bytes(data)
    shape = shape or detect(data)
    if len(data) < shape.party_at:
        raise AmigaSaveError(
            f"{shape.title} needs {shape.party_at} bytes of header; "
            f"{len(data)} given")
    square: dict[str, int] = {}
    at = shape.square_at
    for field in shape.square:
        square[field.name] = int.from_bytes(data[at:at + field.size], "big")
        at += field.size
    first_mode = data[shape.first_mode_at]
    mode = data[shape.mode_at]
    wallset: tuple[tuple[int, int], ...] = ()
    if shape.wallset_table:
        at = shape.wallset_at
        wallset = tuple(
            (int.from_bytes(data[at + 4 * i:at + 4 * i + 2], "big"),
             int.from_bytes(data[at + 4 * i + 2:at + 4 * i + 4], "big"))
            for i in range(WALLSET_ENTRIES))
    count = int.from_bytes(data[shape.count_at:shape.party_at], "big")

    characters: list[amiga.AmigaCharacter] = []
    blocks: list[tuple[int, int]] = []
    names: list[str] = []
    at = shape.party_at
    if shape.party == "records":
        for _ in range(count):
            # The loader allocates a record and reads a block this way, once
            # per count; _amiga_block is the reader's own walk of one block.
            char, end = amiga._amiga_block(data, at, shape.record_shape,
                                           source)
            characters.append(char)
            blocks.append((at, end))
            at = end
    else:
        if len(data) != shape.fixed_size:
            raise AmigaSaveError(
                f"{shape.title} saves are {shape.fixed_size} bytes; "
                f"{len(data)} given")
        for i in range(NAME_SLOTS):
            slot = data[at + i * NAME_SLOT_BYTES:
                        at + i * NAME_SLOT_BYTES + NAME_BYTES]
            names.append(slot.split(b"\0")[0].decode("latin1"))
    return AmigaSavegame(shape, data, square, first_mode, mode, wallset,
                         count, tuple(characters), tuple(blocks), tuple(names))


#: The most characters either later title's picker will put in a party.  The
#: count is a `u16be` in the file and the loader trusts it with no bound of
#: its own, so this is the game's rule rather than the format's.
PARTY_MAX = 6


def rebuild(save: AmigaSavegame,
            characters: "Sequence[amiga.AmigaCharacter] | None" = None
            ) -> bytes:
    """A saved game with a new party in it, and everything else untouched.

    The party region is the **last** thing in a Curse or Silver Blades saved
    game -- both specimens end exactly where the last block does -- so the
    file is the header up to the count, the count as a `u16be`, and then the
    blocks.  Nothing before the count moves, which is the point: the variable
    array, the staged area script and the square block are the caller's own
    save, and this changes only the region it can account for byte by byte.

    `characters` defaults to the ones already in the file, which makes the
    identity a test rather than a claim: `rebuild(parse(data)) == data` on
    every specimen there is.

    **What this cannot say** is whether the game will load the result.  The
    format takes it -- the loader has no checksum, no length field and no
    signature, and `goldbox.amiga.AmigaCharacter.block_bytes` sets the three
    chain fields it does test -- but a save the engine has actually accepted
    is an emulator's word and nobody has had one on screen.
    """
    s = save.shape
    if s.party != "records":
        raise AmigaSaveError(
            f"{s.title} keeps its party in files beside the saved game, not "
            f"in it; goldbox.amiga.write_por_slot writes that one")
    party = save.characters if characters is None else tuple(characters)
    if not 1 <= len(party) <= PARTY_MAX:
        raise AmigaSaveError(
            f"a {s.title} party is 1 to {PARTY_MAX} characters; "
            f"{len(party)} given")
    for n, char in enumerate(party):
        if char.shape is not s.record_shape:
            raise AmigaSaveError(
                f"character {n} is a {char.shape.title} record and this is a "
                f"{s.title} saved game")
    head = bytearray(save.data[:s.count_at])
    at = s.vm_offset(0x503E)
    head[at:at + 2] = len(party).to_bytes(2, "big")
    return (bytes(head)
            + len(party).to_bytes(s.count_bytes, "big")
            + amiga.party_block_bytes(party))


def check(save: AmigaSavegame) -> list[tuple[str, bool, str]]:
    """Every way the file can contradict the map, as `(claim, ok, detail)`.

    A claim is something the file says twice, once through the map and once
    through something the map does not use.
    """
    s, out = save.shape, []
    if s.header_bytes:
        out.append(("byte 0 is $5012", save.header_byte == save.word(0x5012),
                    f"{save.header_byte} against {save.word(0x5012)}"))
    out.append(("$503E is the party count", save.word(0x503E) == save.count,
                f"{save.word(0x503E)} against {save.count}"))
    if s.party == "records":
        scan = [c for c in range(len(save.data))
                if amiga.looks_like_amiga_record(save.data, c, s.record_shape)]
        starts = [b[0] for b in save.blocks]
        out.append(("every block starts where the scan finds a record",
                    scan == starts,
                    f"scan {[hex(c) for c in scan]} against "
                    f"{[hex(c) for c in starts]}"))
        out.append(("the last block ends at the end of the file",
                    save.end == len(save.data),
                    f"{save.end} against {len(save.data)}"))
    else:
        # The loader reads `count` names and no more; slots past the count
        # hold whatever was under the buffer on the stack (`docs/141`).
        used = list(save.names[:save.count])
        out.append(("the first count slots are CHRDAT plus a letter and a "
                    "digit",
                    all(len(n) == NAME_BYTES and n.startswith("CHRDAT")
                        and n[7].isdigit() for n in used), str(used)))
        out.append(("the count is at most the eight slots",
                    save.count <= NAME_SLOTS, str(save.count)))
    if s.party == "records":
        out.append(("the party rebuilds to the bytes it was read from",
                    rebuild(save) == save.data,
                    f"{len(rebuild(save))} bytes against {len(save.data)}"))
    out.append(("facing is doubled: 0, 2, 4 or 6",
                save.square["facing"] in (0, 2, 4, 6),
                str(save.square["facing"])))
    out.append(("the mode byte is one the code writes",
                save.mode in GAME_MODES or save.mode == 0, str(save.mode)))
    for name, value in save.square.items():
        if name == "pad" or name == "wallset_entry_0":
            out.append((f"square {name} is zero", value == 0, str(value)))
    return out


def report(save: AmigaSavegame, label: str = "") -> str:
    s = save.shape
    lines = [f"{label or 'saved game'}: {s.title}, {len(save.data)} bytes"]
    if s.header_bytes:
        lines.append(f"  byte 0: container number {save.header_byte}")
    lines.append(f"  variable array at {s.vm_at}, {VM_BYTES} bytes; "
                 f"clock {save.clock}")
    for address, name in NAMED_WORDS.items():
        lines.append(f"    ${address:04X} {name}: {save.word(address)}")
    if s.ecl_bytes:
        used = len(save.ecl.rstrip(b"\0"))
        lines.append(f"  ECL buffer at {s.ecl_at:#x}, {s.ecl_bytes} bytes, "
                     f"{used} non-zero from the front")
    lines.append(f"  square block at {s.square_at:#x}, {s.square_bytes} bytes:")
    for field in s.square:
        lines.append(f"    {field.name}: {save.square[field.name]}"
                     + (f"  ({field.note})" if field.note else ""))
    first = (VIEW_TYPES if s.first_mode_byte == "view type"
             else GAME_MODES).get(save.first_mode, "?")
    lines.append(f"  {s.first_mode_byte} at {s.first_mode_at:#x}: "
                 f"{save.first_mode} ({first})")
    lines.append(f"  game mode at {s.mode_at:#x}: {save.mode} "
                 f"({GAME_MODES.get(save.mode, '?')})")
    if s.wallset_table:
        shown = ", ".join("empty" if b == 0xFFFF else f"block {b} in slot {sl}"
                          for b, sl in save.wallset)
        lines.append(f"  wallset table at {s.wallset_at:#x}: {shown}")
    lines.append(f"  party count at {s.count_at:#x}: {save.count}")
    if s.party == "records":
        for char, (at, end) in zip(save.characters, save.blocks):
            lines.append(f"    {at:#x}-{end:#x}: {char.name!r}, "
                         f"{len(char.items)} items, {len(char.effects)} "
                         f"effects")
    else:
        shown = [n if i < save.count else "(unused)"
                 for i, n in enumerate(save.names)]
        lines.append(f"  name table at {s.party_at}: " + " ".join(shown))
    for claim, ok, detail in check(save):
        lines.append(f"  [{'ok' if ok else 'FAIL'}] {claim}: {detail}")
    return "\n".join(lines)


def savegames_on(disk: AmigaDisk):
    """Every `save/savgam*` on a disk, as `(path, bytes)`."""
    for path, _entry in disk.walk():
        parts = path.strip("/").split("/")
        if (len(parts) == 2 and parts[0].lower() == "save"
                and parts[1].lower().startswith("savgam")):
            yield path, disk.read_file(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="saved games, as raw files")
    parser.add_argument("--adf", action="append", default=[],
                        help="a disk image; every save/savgam* on it is read")
    args = parser.parse_args(argv)
    todo: list[tuple[str, bytes]] = []
    for f in args.files:
        todo.append((f, pathlib.Path(f).read_bytes()))
    for image in args.adf:
        try:
            disk = AmigaDisk.open(image)
        except AmigaDiskError as ex:
            raise SystemExit(f"{image}: {ex}")
        todo.extend((f"{image}!{p}", d) for p, d in savegames_on(disk))
    if not todo:
        parser.error("name a saved game or an --adf image")
    failed = 0
    for label, data in todo:
        try:
            save = parse(data, source=label)
        except (AmigaSaveError, amiga.AmigaRecordError) as ex:
            print(f"{label}: {ex}")
            failed += 1
            continue
        print(report(save, label))
        failed += sum(1 for _, ok, _ in check(save) if not ok)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
