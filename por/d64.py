"""Commodore 1541 ``.D64`` disk image reader/writer.

Only what this project actually needs: read the directory, read a file's
sector chain, and overwrite a file *in place* by reusing its existing chain.
There is deliberately no block allocation (BAM) support -- we only ever
rewrite saves of identical length, so we never need to allocate or free a
block.

Geometry (35 tracks, 683 sectors, 174848 bytes)::

    tracks  1-17: 21 sectors
    tracks 18-24: 19 sectors
    tracks 25-30: 18 sectors
    tracks 31-35: 17 sectors

Sectors are stored back to back in track order, so the byte offset of
``(track, sector)`` is ``(blocks before track + sector) * 256``.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Iterator, Union

__all__ = [
    "SECTOR_SIZE",
    "TRACK_COUNT",
    "TOTAL_SECTORS",
    "IMAGE_SIZE",
    "DIRECTORY_TRACK",
    "DIRECTORY_SECTOR",
    "FILE_TYPE_NAMES",
    "D64Error",
    "InvalidImageError",
    "FileNotFoundInImage",
    "SectorChainError",
    "BlockCountMismatch",
    "DirEntry",
    "D64",
    "load_payload",
    "sectors_per_track",
    "sector_offset",
    "split_load_address",
    "attach_load_address",
]

SECTOR_SIZE = 256
TRACK_COUNT = 35
PAYLOAD_PER_SECTOR = SECTOR_SIZE - 2  # 2 bytes of next-sector link

DIRECTORY_TRACK = 18
DIRECTORY_SECTOR = 1
HEADER_SECTOR = 0  # track 18 sector 0: BAM + disk name

ENTRIES_PER_DIR_SECTOR = 8
ENTRY_SIZE = 32
ENTRY_BASE = 2  # first entry starts after the next-sector link
NAME_LENGTH = 16
NAME_PAD = 0xA0

FILE_TYPE_DEL = 0
FILE_TYPE_SEQ = 1
FILE_TYPE_PRG = 2
FILE_TYPE_USR = 3
FILE_TYPE_REL = 4

FILE_TYPE_NAMES = {
    FILE_TYPE_DEL: "DEL",
    FILE_TYPE_SEQ: "SEQ",
    FILE_TYPE_PRG: "PRG",
    FILE_TYPE_USR: "USR",
    FILE_TYPE_REL: "REL",
}

_TRACK_LAYOUT = ((17, 21), (24, 19), (30, 18), (35, 17))


def sectors_per_track(track: int) -> int:
    """Number of sectors on ``track`` (1-based)."""
    if not 1 <= track <= TRACK_COUNT:
        raise ValueError(f"track out of range 1..{TRACK_COUNT}: {track}")
    for last, count in _TRACK_LAYOUT:
        if track <= last:
            return count
    raise AssertionError("unreachable")


def _sectors_before(track: int) -> int:
    total = 0
    for t in range(1, track):
        total += sectors_per_track(t)
    return total


TOTAL_SECTORS = sum(sectors_per_track(t) for t in range(1, TRACK_COUNT + 1))
IMAGE_SIZE = TOTAL_SECTORS * SECTOR_SIZE  # 174848

# Precomputed offsets: index by track (1-based).
_TRACK_OFFSET = [0] + [_sectors_before(t) * SECTOR_SIZE for t in range(1, TRACK_COUNT + 1)]


def sector_offset(track: int, sector: int) -> int:
    """Byte offset of ``(track, sector)`` within a D64 image."""
    limit = sectors_per_track(track)
    if not 0 <= sector < limit:
        raise ValueError(f"sector out of range 0..{limit - 1} for track {track}: {sector}")
    return _TRACK_OFFSET[track] + sector * SECTOR_SIZE


class D64Error(Exception):
    """Base class for disk image errors."""


class InvalidImageError(D64Error):
    """The image is not a well-formed 35-track D64."""


class FileNotFoundInImage(D64Error, KeyError):
    """No directory entry matched the requested name."""


class SectorChainError(D64Error):
    """A file's sector chain is malformed (bad link or a loop)."""


class BlockCountMismatch(D64Error, ValueError):
    """New data does not occupy the same number of blocks as the original."""


NameLike = Union[bytes, bytearray, str]
EntryLike = Union["DirEntry", bytes, bytearray, str]


def _normalize_name(name: NameLike) -> bytes:
    """Coerce a name to raw disk bytes and strip trailing 0xA0 padding.

    Leading/embedded control bytes are preserved -- real filenames on these
    disks include them (e.g. a character file is ``b"\\x01BRUTUS"``).
    """
    if isinstance(name, str):
        raw = name.encode("latin-1")
    elif isinstance(name, (bytes, bytearray)):
        raw = bytes(name)
    else:
        raise TypeError(f"name must be str or bytes, got {type(name).__name__}")
    return raw.rstrip(bytes([NAME_PAD]))


@dataclass(frozen=True)
class DirEntry:
    """One 32-byte directory slot."""

    index: int
    """Ordinal position across the whole directory (including empty slots)."""

    dir_track: int
    dir_sector: int
    slot: int
    """Which of the 8 slots inside ``(dir_track, dir_sector)`` this is."""

    type_byte: int
    first_track: int
    first_sector: int
    raw_name: bytes
    """The 16 name bytes exactly as stored, including 0xA0 padding."""

    block_count: int

    @property
    def offset(self) -> int:
        """Byte offset of this entry within the image."""
        return sector_offset(self.dir_track, self.dir_sector) + ENTRY_BASE + self.slot * ENTRY_SIZE

    @property
    def name(self) -> bytes:
        """The name with trailing 0xA0 padding removed; nothing else stripped."""
        return self.raw_name.rstrip(bytes([NAME_PAD]))

    @property
    def file_type(self) -> int:
        """Low nibble of the type byte (0=DEL, 1=SEQ, 2=PRG, 3=USR, 4=REL)."""
        return self.type_byte & 0x0F

    @property
    def type_name(self) -> str:
        return FILE_TYPE_NAMES.get(self.file_type, f"?{self.file_type:X}")

    @property
    def is_closed(self) -> bool:
        """True unless the file was left open (``*PRG`` splat file)."""
        return bool(self.type_byte & 0x80)

    @property
    def is_locked(self) -> bool:
        return bool(self.type_byte & 0x40)

    @property
    def is_prg(self) -> bool:
        return self.file_type == FILE_TYPE_PRG

    @property
    def is_empty(self) -> bool:
        """An unused slot: no type and no start block."""
        return self.type_byte == 0 and self.first_track == 0

    @property
    def display_name(self) -> str:
        """Printable rendering of :attr:`name`; non-ASCII shown as ``\\xNN``."""
        out = []
        for b in self.name:
            out.append(chr(b) if 0x20 <= b < 0x7F else f"\\x{b:02x}")
        return "".join(out)

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.display_name!r} {self.type_name} {self.block_count} blocks"


class D64:
    """A 35-track 1541 disk image held in memory."""

    def __init__(self, data: bytes | bytearray):
        if len(data) != IMAGE_SIZE:
            # Name the likely variants rather than just the byte count. A
            # 40-track image or one carrying error bytes is a perfectly good
            # disk that this reader does not handle, and "expected 174848" does
            # not tell you that.
            hint = {
                175531: " (35 tracks plus error bytes)",
                196608: " (40 tracks)",
                197376: " (40 tracks plus error bytes)",
                174848 + 1: "",
            }.get(len(data), "")
            if hint:
                raise InvalidImageError(
                    f"this is a {len(data)}-byte D64{hint}; only plain 35-track "
                    f"images of {IMAGE_SIZE} bytes are supported")
            raise InvalidImageError(
                f"expected a {IMAGE_SIZE}-byte 35-track D64 image, got {len(data)} bytes"
            )
        self._data = bytearray(data)

    # ---- construction / serialization -----------------------------------

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "D64":
        return cls(data)

    @classmethod
    def open(cls, path: str | os.PathLike) -> "D64":
        with open(path, "rb") as fh:
            return cls(fh.read())

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def save(self, path: str | os.PathLike) -> None:
        """Write the image, atomically.

        A save disk is often the only copy of hours of play, and the editor
        writes back over the file it opened. A plain truncate-and-write loses
        the lot if the process dies or the filesystem fills half way through, so
        write a temporary beside the target, flush it to the platter, and rename
        over. `os.replace` is atomic on POSIX: after it, the file is either
        entirely the old image or entirely the new one.
        """
        target = pathlib.Path(path)
        tmp = target.with_name(f".{target.name}.tmp{os.getpid()}")
        try:
            with open(tmp, "wb") as fh:
                fh.write(self._data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    @property
    def data(self) -> bytearray:
        """Live mutable buffer. Mutating it mutates the image."""
        return self._data

    # ---- raw sector access ----------------------------------------------

    def read_sector(self, track: int, sector: int) -> bytes:
        off = sector_offset(track, sector)
        return bytes(self._data[off : off + SECTOR_SIZE])

    def write_sector(self, track: int, sector: int, data: bytes) -> None:
        if len(data) != SECTOR_SIZE:
            raise ValueError(f"a sector is {SECTOR_SIZE} bytes, got {len(data)}")
        off = sector_offset(track, sector)
        self._data[off : off + SECTOR_SIZE] = data

    # ---- disk header -----------------------------------------------------

    @property
    def disk_name(self) -> bytes:
        """The 16-byte disk name from track 18 sector 0, 0xA0 padding stripped."""
        off = sector_offset(DIRECTORY_TRACK, HEADER_SECTOR)
        return bytes(self._data[off + 0x90 : off + 0xA0]).rstrip(bytes([NAME_PAD]))

    @property
    def disk_id(self) -> bytes:
        off = sector_offset(DIRECTORY_TRACK, HEADER_SECTOR)
        return bytes(self._data[off + 0xA2 : off + 0xA4])

    # ---- directory -------------------------------------------------------

    def iter_directory(self, include_empty: bool = False) -> Iterator[DirEntry]:
        """Walk the directory chain from track 18 sector 1.

        Empty (never-used) slots are skipped unless ``include_empty`` is set.
        """
        track, sector = DIRECTORY_TRACK, DIRECTORY_SECTOR
        seen: set[tuple[int, int]] = set()
        index = 0
        while track != 0:
            if (track, sector) in seen:
                raise SectorChainError(
                    f"directory chain loops at track {track} sector {sector}"
                )
            seen.add((track, sector))
            try:
                buf = self.read_sector(track, sector)
            except ValueError as exc:
                raise SectorChainError(f"bad directory link: {exc}") from exc

            for slot in range(ENTRIES_PER_DIR_SECTOR):
                base = ENTRY_BASE + slot * ENTRY_SIZE
                raw = buf[base : base + ENTRY_SIZE]
                entry = DirEntry(
                    index=index,
                    dir_track=track,
                    dir_sector=sector,
                    slot=slot,
                    type_byte=raw[0],
                    first_track=raw[1],
                    first_sector=raw[2],
                    raw_name=bytes(raw[3 : 3 + NAME_LENGTH]),
                    block_count=raw[28] | (raw[29] << 8),
                )
                index += 1
                if include_empty or not entry.is_empty:
                    yield entry

            track, sector = buf[0], buf[1]

    def directory(self, include_empty: bool = False) -> list[DirEntry]:
        return list(self.iter_directory(include_empty=include_empty))

    def __iter__(self) -> Iterator[DirEntry]:
        return self.iter_directory()

    def find(self, name: NameLike) -> DirEntry | None:
        """First directory entry whose name matches, or ``None``."""
        wanted = _normalize_name(name)
        for entry in self.iter_directory():
            if entry.name == wanted:
                return entry
        return None

    def entry(self, name: NameLike) -> DirEntry:
        """Like :meth:`find` but raises if the name is absent."""
        found = self.find(name)
        if found is None:
            raise FileNotFoundInImage(f"no such file on disk: {_normalize_name(name)!r}")
        return found

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, (str, bytes, bytearray)):
            return False
        return self.find(name) is not None

    def _resolve(self, entry_or_name: EntryLike) -> DirEntry:
        if isinstance(entry_or_name, DirEntry):
            return entry_or_name
        return self.entry(entry_or_name)

    # ---- file contents ---------------------------------------------------

    def sector_chain(self, entry_or_name: EntryLike) -> list[tuple[int, int]]:
        """The ordered list of ``(track, sector)`` blocks holding a file."""
        entry = self._resolve(entry_or_name)
        chain: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        track, sector = entry.first_track, entry.first_sector
        while track != 0:
            if (track, sector) in seen:
                raise SectorChainError(
                    f"{entry.name!r}: chain loops at track {track} sector {sector}"
                )
            if len(chain) > TOTAL_SECTORS:
                raise SectorChainError(f"{entry.name!r}: chain longer than the disk")
            seen.add((track, sector))
            chain.append((track, sector))
            try:
                buf = self.read_sector(track, sector)
            except ValueError as exc:
                raise SectorChainError(f"{entry.name!r}: bad link: {exc}") from exc
            track, sector = buf[0], buf[1]
        if not chain:
            raise SectorChainError(f"{entry.name!r}: empty sector chain")
        return chain

    def read_file(self, entry_or_name: EntryLike) -> bytes:
        """Full raw byte stream of a file (for a PRG this includes the load address)."""
        entry = self._resolve(entry_or_name)
        out = bytearray()
        track, sector = entry.first_track, entry.first_sector
        seen: set[tuple[int, int]] = set()
        while track != 0:
            if (track, sector) in seen:
                raise SectorChainError(
                    f"{entry.name!r}: chain loops at track {track} sector {sector}"
                )
            seen.add((track, sector))
            try:
                buf = self.read_sector(track, sector)
            except ValueError as exc:
                raise SectorChainError(f"{entry.name!r}: bad link: {exc}") from exc
            next_track, next_sector = buf[0], buf[1]
            if next_track == 0:
                # next_sector is the index of the LAST valid byte in this sector.
                if next_sector < 1:
                    raise SectorChainError(
                        f"{entry.name!r}: bad final-byte index {next_sector}"
                    )
                out += buf[2 : next_sector + 1]
            else:
                out += buf[2:]
            track, sector = next_track, next_sector
        return bytes(out)

    @staticmethod
    def blocks_needed(length: int) -> int:
        """How many 254-byte blocks a file of ``length`` bytes occupies."""
        if length < 0:
            raise ValueError("length must be non-negative")
        if length == 0:
            return 1
        return (length + PAYLOAD_PER_SECTOR - 1) // PAYLOAD_PER_SECTOR

    def write_file_inplace(self, entry_or_name: EntryLike, new_data: bytes) -> None:
        """Overwrite a file's contents, reusing its existing sector chain.

        Raises :class:`BlockCountMismatch` unless ``new_data`` occupies exactly
        the same number of blocks as the file already on disk. Nothing outside
        the file's own payload bytes is touched -- links, the directory entry,
        and any slack after the payload in the final sector are left alone --
        so rewriting a file with its current contents is a no-op on the image.
        """
        entry = self._resolve(entry_or_name)
        chain = self.sector_chain(entry)
        needed = self.blocks_needed(len(new_data))
        if needed != len(chain):
            raise BlockCountMismatch(
                f"{entry.name!r}: new data is {len(new_data)} bytes = {needed} block(s), "
                f"but the existing chain is {len(chain)} block(s); "
                "in-place writes must keep the same block count"
            )

        pos = 0
        for i, (track, sector) in enumerate(chain):
            last = i == len(chain) - 1
            take = len(new_data) - pos if last else PAYLOAD_PER_SECTOR
            chunk = new_data[pos : pos + take]
            off = sector_offset(track, sector) + 2
            self._data[off : off + len(chunk)] = chunk
            pos += len(chunk)
            if last:
                link_off = sector_offset(track, sector)
                self._data[link_off] = 0
                self._data[link_off + 1] = 1 + len(chunk)
        assert pos == len(new_data)


# ---- PRG load-address helpers -------------------------------------------
# Kept separate from read_file/write_file_inplace on purpose: the caller
# decides whether a file is a PRG and whether to peel the load address off.


def load_payload(disk: "D64 | str", name: NameLike) -> bytes:
    """Read one file off a disk and drop its 2-byte PRG load address.

    Four modules were each opening the image, reading a file and splitting the
    load address by hand. One place to get that wrong is enough.
    """
    image = D64.open(disk) if isinstance(disk, (str, os.PathLike)) else disk
    _, payload = split_load_address(image.read_file(name))
    return payload


def split_load_address(data: bytes) -> tuple[int, bytes]:
    """Split a PRG into ``(load_address, payload)``."""
    if len(data) < 2:
        raise ValueError(f"a PRG needs at least a 2-byte load address, got {len(data)}")
    return data[0] | (data[1] << 8), bytes(data[2:])


def attach_load_address(load_address: int, payload: bytes) -> bytes:
    """Prepend a 2-byte little-endian load address to ``payload``."""
    if not 0 <= load_address <= 0xFFFF:
        raise ValueError(f"load address out of range: {load_address:#x}")
    return bytes((load_address & 0xFF, load_address >> 8)) + bytes(payload)
