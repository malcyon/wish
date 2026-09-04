"""Commodore 1541 ``.D64`` disk image reader/writer.

Read the directory, read a file's sector chain, overwrite a file *in place*
over its existing chain -- and, since #118, **build a disk from nothing**:
:meth:`D64.blank` formats a 35-track image with a valid BAM and an empty
directory, and :meth:`D64.write_file` allocates blocks, threads the sector
chain and links a directory entry, growing the directory chain when eight
entries are not enough.

That last part is what lets a DOS save be imported without a `.d64` the
player already had. Converting *onto* somebody else's save means every byte
nobody has decoded keeps a value belonging to a different party in a
different place, which is wrong data that looks right because the file loads.

`goldbox/amiga_adf.py` is the same job on the other port and this is written
to read as its sibling.

What was measured rather than looked up
---------------------------------------
The BAM, the directory and the allocator were all checked against the
player's own fifteen `PORSAVE*.D64` saves before a byte was written, because
a filesystem write that is *nearly* right corrupts a disk silently:

* the BAM's per-track entry is `free count, then three bitmap bytes, a set
  bit meaning free` -- recomputing all 35 entries reproduces every byte of
  track 18 sector 0 on all fifteen disks;
* **the placement of a file's blocks is not something the game insists on.**
  Thirteen of the fifteen space a file's blocks six sectors apart and two
  space them ten apart, and both kinds are saves the player made with the
  game itself. :data:`FILE_INTERLEAVE` is 6 because that is what thirteen
  of them carry, and it is a parameter because the other two prove it is a
  choice;
* interleave 6, wrapping by the track's sector count and then stepping
  forward to the next free sector, reproduces the sector chain of both files
  on the thirteen clean specimens **exactly** -- 38 blocks, including the
  spill from track 17 to track 16, which keeps the running sector number
  across the track change rather than restarting at 0;
* the directory chain is the same rule with :data:`DIRECTORY_INTERLEAVE` 3,
  which reproduces all thirteen directory sectors of `POOL1.D64.orig`'s
  103-entry directory;
* an unused sector reads as 256 zero bytes -- true of all 643 of them on
  `PORSAVE13.D64`, and of every unused sector on fourteen of the fifteen
  disks. The exception is one sector on `PORSAVE.D64` holding the tail of
  something scratched, which is ordinary 1541 behaviour: the drive frees a
  block without wiping it.

What this does not do
---------------------
* **A file is never grown or replaced.** :meth:`D64.write_file` refuses a
  name already in the directory; :meth:`D64.write_file_inplace` is what
  rewrites one, and only at the same block count. Nothing here scratches a
  file, so no block is ever freed.
* **Only 35-track plain images are built.** :meth:`D64.blank` makes the one
  variant that is writable at all.

Geometry (35 tracks, 683 sectors, 174848 bytes)::

    tracks  1-17: 21 sectors
    tracks 18-24: 19 sectors
    tracks 25-30: 18 sectors
    tracks 31-35: 17 sectors
    tracks 36-42: 17 sectors   -- the 40- and 42-track extensions

Sectors are stored back to back in track order, so the byte offset of
``(track, sector)`` is ``(blocks before track + sector) * 256``. Tracks 1-35
sit at the same offsets in every variant, which is why a 40-track image can be
read by code that only knows about 35.

Variants
--------

A ``.D64`` comes in six sizes and this reader knows all six. Anything else is
still refused -- a size we cannot name is a file we cannot claim to understand,
and guessing at one is how a reader starts returning plausible nonsense.

===========  ======  ===========  ==============================================
Size         Tracks  Error bytes  Where it comes from
===========  ======  ===========  ==============================================
174848       35      no           the plain image; every save disk this project
                                  writes
175531       35      yes          a copier that recorded the read status of each
                                  of the 683 sectors (Curse side 4 is one)
196608       40      no           a 40-track format
197376       40      yes          Champions of Krynn side A is one
205312       42      no           a 42-track format; unseen here
206114       42      yes          likewise
===========  ======  ===========  ==============================================

**Error bytes are advisory and this reader does not act on them.** They are one
byte per sector appended after the sector data, ``1`` meaning "read cleanly".
They are exposed through :meth:`D64.error_code` and nothing else consults them,
because on the specimens we hold they mark *padding*, not damage: all 85 sectors
on Champions of Krynn side A's tracks 36-40 carry code 3, which is DOS error 21,
"no sync character" -- what an unformatted track reads as -- and no sector chain
on that disk leaves track 35.
Refusing an image because it reports errors would refuse a perfectly readable
disk; hiding the codes would lose the evidence that says the padding is padding.

**Only the plain 174848-byte image is writable.** Every other variant is
read-only, enforced rather than documented: :meth:`D64.write_sector`,
:meth:`D64.write_file_inplace` and :meth:`D64.save` raise
:class:`ReadOnlyImageError`. The reason is that the variants are *rips of other
people's disks*, not save disks. Writing to one would have to maintain an error
map this reader does not model, and the directories on those images are not
always the drive's own work -- Death Knights of Krynn's has PETSCII art in the
entries and a zero block count against every real file. A rewrite that trusts
such a directory misbehaves. Nothing in this project needs to write to anything
but a save disk, so the safe rule costs nothing.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Iterator, Union

__all__ = [
    "SECTOR_SIZE",
    "TRACK_COUNT",
    "MAX_TRACK_COUNT",
    "TOTAL_SECTORS",
    "IMAGE_SIZE",
    "VARIANTS",
    "Variant",
    "DIRECTORY_TRACK",
    "DIRECTORY_SECTOR",
    "FILE_TYPE_NAMES",
    "D64Error",
    "InvalidImageError",
    "ReadOnlyImageError",
    "FileNotFoundInImage",
    "SectorChainError",
    "BlockCountMismatch",
    "DiskFullError",
    "DirectoryFullError",
    "DuplicateFileError",
    "FILE_INTERLEAVE",
    "DIRECTORY_INTERLEAVE",
    "DEFAULT_DISK_NAME",
    "DEFAULT_DISK_ID",
    "ENTRY_FIELDS",
    "DirEntry",
    "D64",
    "load_payload",
    "total_sectors",
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

#: Bytes of a directory slot that belong to it. Eight 32-byte slots starting
#: two bytes in would need 258, and a sector is 256: the last two bytes of
#: every slot are the *next* slot's first two, which nothing uses -- except
#: for slot 0, where they are the sector's link. So a write must stop at 30,
#: or filling slot 7 wipes the link of the sector after it and the rest of
#: the directory disappears. That is not hypothetical; it is what the
#: 144-file test caught.
ENTRY_FIELDS = ENTRY_SIZE - 2
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

#: Byte offsets inside track 18 sector 0, the BAM. Measured against all fifteen
#: of the player's ``PORSAVE*.D64`` saves, which agree on every one of them.
BAM_TRACK_ENTRIES = 0x04    # 4 bytes per track, tracks 1..35
BAM_TRACK_ENTRY_SIZE = 4    # free count, then 3 bitmap bytes; a set bit is free
BAM_DISK_NAME = 0x90        # 16 bytes, 0xA0 padded
BAM_DISK_ID = 0xA2          # 2 bytes
BAM_DOS_TYPE = 0xA5         # 2 bytes, "2A"

#: The DOS version byte at BAM offset 2. 'A' on every disk here.
DOS_VERSION = 0x41
DOS_TYPE = b"2A"

#: How far apart :meth:`D64.write_file` spaces a file's blocks round a track.
#:
#: Six, because thirteen of the player's fifteen save disks space them six
#: apart -- and it is a parameter rather than a constant because the other two
#: space them ten apart and the game reads both. Interleave is a matter of how
#: long the drive takes to come round again, not of what the file means: a
#: reader has only the chain to go on and cannot tell the two apart.
FILE_INTERLEAVE = 6

#: The same spacing for directory sectors on track 18. Three reproduces all
#: thirteen directory sectors of ``POOL1.D64.orig``'s 103-entry directory.
DIRECTORY_INTERLEAVE = 3

#: What :meth:`D64.blank` names a disk when the caller does not.
#:
#: A single space and ``00`` are what thirteen of the player's own save disks
#: carry, so a disk built here is indistinguishable from one the drive
#: formatted. The other two read ``BLANK``, which is how we know the game does
#: not care what a save disk is called.
DEFAULT_DISK_NAME = b" "
DEFAULT_DISK_ID = b"00"

# The 40- and 42-track extensions keep track 35's 17 sectors going; nothing
# else about the geometry changes, so tracks 1-35 lie at identical offsets in
# every variant.
MAX_TRACK_COUNT = 42
_TRACK_LAYOUT = ((17, 21), (24, 19), (30, 18), (MAX_TRACK_COUNT, 17))


def sectors_per_track(track: int, track_count: int = TRACK_COUNT) -> int:
    """Number of sectors on ``track`` (1-based).

    ``track_count`` defaults to 35, so a bare call still refuses track 36 --
    which is what every existing caller means by it.
    """
    if not 1 <= track <= track_count:
        raise ValueError(f"track out of range 1..{track_count}: {track}")
    for last, count in _TRACK_LAYOUT:
        if track <= last:
            return count
    raise AssertionError("unreachable")


def _sectors_before(track: int) -> int:
    total = 0
    for t in range(1, track):
        total += sectors_per_track(t, MAX_TRACK_COUNT)
    return total


def total_sectors(track_count: int = TRACK_COUNT) -> int:
    """How many sectors an image of ``track_count`` tracks holds."""
    return sum(sectors_per_track(t, track_count) for t in range(1, track_count + 1))


TOTAL_SECTORS = total_sectors(TRACK_COUNT)          # 683
IMAGE_SIZE = TOTAL_SECTORS * SECTOR_SIZE            # 174848

# Precomputed offsets: index by track (1-based).
_TRACK_OFFSET = [0] + [_sectors_before(t) * SECTOR_SIZE
                       for t in range(1, MAX_TRACK_COUNT + 1)]


def sector_offset(track: int, sector: int, track_count: int = TRACK_COUNT) -> int:
    """Byte offset of ``(track, sector)`` within a D64 image."""
    limit = sectors_per_track(track, track_count)
    if not 0 <= sector < limit:
        raise ValueError(f"sector out of range 0..{limit - 1} for track {track}: {sector}")
    return _TRACK_OFFSET[track] + sector * SECTOR_SIZE


@dataclass(frozen=True)
class Variant:
    """One recognised ``.D64`` shape, keyed by file size.

    ``writable`` is the plain 35-track image and nothing else; see the module
    docstring for why, and :class:`ReadOnlyImageError` for what enforces it.
    """

    size: int
    tracks: int
    sectors: int
    has_error_bytes: bool
    description: str

    @property
    def writable(self) -> bool:
        return self.tracks == TRACK_COUNT and not self.has_error_bytes

    @property
    def error_base(self) -> int | None:
        """Offset of the error map, or None when there is not one."""
        return self.sectors * SECTOR_SIZE if self.has_error_bytes else None


def _variants() -> dict[int, Variant]:
    out = {}
    for tracks in (35, 40, 42):
        sectors = total_sectors(tracks)
        for errors in (False, True):
            size = sectors * SECTOR_SIZE + (sectors if errors else 0)
            out[size] = Variant(
                size=size, tracks=tracks, sectors=sectors, has_error_bytes=errors,
                description=(f"{tracks} tracks"
                             + (" plus error bytes" if errors else "")))
    return out


#: Size -> :class:`Variant`. 174848, 175531, 196608, 197376, 205312, 206114.
VARIANTS: dict[int, Variant] = _variants()

#: An error byte of 1 is "read cleanly"; anything else is the 1541 error the
#: copier saw: bytes 2 to 11 are DOS errors 20 to 29 in order, and byte 15 is
#: error 74, drive not ready. So 3 is error 21, "READ ERROR -- no sync
#: character", which the 1541 User's Guide (September 1982, p. 53) puts down to
#: an "unformatted or improperly seated diskette" -- and that is what tracks
#: 36-40 of every 40-track rip we hold report. The byte-to-code map is the
#: emulators' convention rather than Commodore's; ``docs/10-disk-format.md``
#: cites both.
ERROR_OK = 1


class D64Error(Exception):
    """Base class for disk image errors."""


class InvalidImageError(D64Error):
    """The image is not one of the D64 sizes in :data:`VARIANTS`."""


class ReadOnlyImageError(D64Error):
    """A write was attempted on a variant this reader will not modify."""


class FileNotFoundInImage(D64Error, KeyError):
    """No directory entry matched the requested name."""


class SectorChainError(D64Error):
    """A file's sector chain is malformed (bad link or a loop)."""


class BlockCountMismatch(D64Error, ValueError):
    """New data does not occupy the same number of blocks as the original."""


class DiskFullError(D64Error):
    """Not enough free blocks for the file; nothing was written."""


class DirectoryFullError(D64Error):
    """Track 18 has no room for another directory sector: 144 files is the lot."""


class DuplicateFileError(D64Error):
    """A file of that name is already in the directory."""


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
    """A 1541 disk image held in memory: 35, 40 or 42 tracks, error bytes or not.

    An unrecognised size is still an error. The point of the variant table is
    that every accepted size is one whose geometry we can state exactly, not
    that the reader will try its luck on anything handed to it.
    """

    def __init__(self, data: bytes | bytearray):
        variant = VARIANTS.get(len(data))
        if variant is None:
            raise InvalidImageError(
                f"expected a D64 image of {', '.join(str(k) for k in sorted(VARIANTS))} "
                f"bytes, got {len(data)}")
        self._variant = variant
        self._data = bytearray(data)

    # ---- variant ---------------------------------------------------------

    @property
    def variant(self) -> Variant:
        return self._variant

    @property
    def track_count(self) -> int:
        return self._variant.tracks

    @property
    def total_sectors(self) -> int:
        return self._variant.sectors

    @property
    def writable(self) -> bool:
        """False for every variant but the plain 174848-byte image."""
        return self._variant.writable

    def _require_writable(self) -> None:
        if not self._variant.writable:
            raise ReadOnlyImageError(
                f"this is a {self._variant.size}-byte D64 ({self._variant.description}); "
                f"only plain {IMAGE_SIZE}-byte 35-track images may be written")

    def error_code(self, track: int, sector: int) -> int | None:
        """The copier's error byte for a sector, or None if the image has none.

        Advisory: nothing in this reader consults it. 1 means the sector read
        cleanly; 3 -- "no header found" -- is what an unformatted track reports,
        and is why tracks 36-40 of a 40-track rip are padding rather than damage.
        """
        base = self._variant.error_base
        if base is None:
            return None
        index = (sector_offset(track, sector, self._variant.tracks) // SECTOR_SIZE)
        return self._data[base + index]

    # ---- construction / serialization -----------------------------------

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "D64":
        return cls(data)

    @classmethod
    def open(cls, path: str | os.PathLike) -> "D64":
        with open(path, "rb") as fh:
            return cls(fh.read())

    @classmethod
    def blank(cls, name: NameLike = DEFAULT_DISK_NAME,
              disk_id: NameLike = DEFAULT_DISK_ID) -> "D64":
        """A freshly formatted 35-track disk with nothing on it (#118).

        The BAM on track 18 sector 0 marks every sector free but its own and
        the first directory sector, and the directory is one sector at track
        18 sector 1 whose link reads ``00 FF`` -- track 0, so end of chain.
        Every other sector is 256 zero bytes, which is what an unused sector
        reads as on fourteen of the player's fifteen save disks.

        `name` is at most 16 bytes and `disk_id` is exactly 2. Both default to
        what the player's own disks carry; see :data:`DEFAULT_DISK_NAME`.
        """
        raw_name = _normalize_name(name)
        raw_id = _normalize_name(disk_id)
        if len(raw_name) > NAME_LENGTH:
            raise ValueError(
                f"a disk name is at most {NAME_LENGTH} bytes, got {len(raw_name)}")
        if len(raw_id) != 2:
            raise ValueError(f"a disk id is exactly 2 bytes, got {len(raw_id)}")

        data = bytearray(IMAGE_SIZE)
        bam = sector_offset(DIRECTORY_TRACK, HEADER_SECTOR)
        data[bam], data[bam + 1] = DIRECTORY_TRACK, DIRECTORY_SECTOR
        data[bam + 2] = DOS_VERSION
        data[bam + 3] = 0
        for track in range(1, TRACK_COUNT + 1):
            count = sectors_per_track(track)
            at = bam + BAM_TRACK_ENTRIES + (track - 1) * BAM_TRACK_ENTRY_SIZE
            data[at] = count
            bits = (1 << count) - 1                       # every sector free
            data[at + 1 : at + 4] = bits.to_bytes(3, "little")
        pad = bytes([NAME_PAD])
        data[bam + BAM_DISK_NAME : bam + BAM_DISK_NAME + NAME_LENGTH] = (
            raw_name.ljust(NAME_LENGTH, pad))
        data[bam + 0xA0 : bam + 0xA2] = pad * 2
        data[bam + BAM_DISK_ID : bam + BAM_DISK_ID + 2] = raw_id
        data[bam + 0xA4] = NAME_PAD
        data[bam + BAM_DOS_TYPE : bam + BAM_DOS_TYPE + 2] = DOS_TYPE
        data[bam + 0xA7 : bam + 0xAB] = pad * 4

        first = sector_offset(DIRECTORY_TRACK, DIRECTORY_SECTOR)
        data[first], data[first + 1] = 0, 0xFF   # end of chain; see the docs

        disk = cls(data)
        disk._mark(DIRECTORY_TRACK, HEADER_SECTOR, free=False)
        disk._mark(DIRECTORY_TRACK, DIRECTORY_SECTOR, free=False)
        return disk

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

        Refused on a read-only variant. `to_bytes` still works, so copying one
        out remains possible; what is refused is this module putting its name to
        a written image whose format it does not fully model.
        """
        self._require_writable()
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
        """Live mutable buffer. Mutating it mutates the image.

        Deliberately not guarded by :attr:`writable` -- it is the escape hatch,
        and a caller reaching past the accessors has said so.
        """
        return self._data

    # ---- raw sector access ----------------------------------------------

    def read_sector(self, track: int, sector: int) -> bytes:
        off = sector_offset(track, sector, self._variant.tracks)
        return bytes(self._data[off : off + SECTOR_SIZE])

    def write_sector(self, track: int, sector: int, data: bytes) -> None:
        self._require_writable()
        if len(data) != SECTOR_SIZE:
            raise ValueError(f"a sector is {SECTOR_SIZE} bytes, got {len(data)}")
        off = sector_offset(track, sector, self._variant.tracks)
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
            if len(chain) > self._variant.sectors:
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
        self._require_writable()
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
            off = sector_offset(track, sector, self._variant.tracks) + 2
            self._data[off : off + len(chunk)] = chunk
            pos += len(chunk)
            if last:
                link_off = sector_offset(track, sector, self._variant.tracks)
                self._data[link_off] = 0
                self._data[link_off + 1] = 1 + len(chunk)
        assert pos == len(new_data)

    # ---- the BAM -------------------------------------------------------

    def _bam_entry(self, track: int) -> int:
        """Byte offset of ``track``'s four-byte BAM entry."""
        if not 1 <= track <= TRACK_COUNT:
            raise ValueError(f"track out of range 1..{TRACK_COUNT}: {track}")
        return (sector_offset(DIRECTORY_TRACK, HEADER_SECTOR)
                + BAM_TRACK_ENTRIES + (track - 1) * BAM_TRACK_ENTRY_SIZE)

    def is_free(self, track: int, sector: int) -> bool:
        """Whether the BAM calls ``(track, sector)`` free. A **set** bit is free."""
        limit = sectors_per_track(track, self._variant.tracks)
        if not 0 <= sector < limit:
            raise ValueError(
                f"sector out of range 0..{limit - 1} for track {track}: {sector}")
        at = self._bam_entry(track) + 1 + sector // 8
        return bool(self._data[at] & (1 << (sector % 8)))

    def track_free(self, track: int) -> int:
        """The free-block count the BAM stores for ``track``."""
        return self._data[self._bam_entry(track)]

    @property
    def blocks_free(self) -> int:
        """Free blocks outside the directory track -- the drive's own BLOCKS FREE.

        Track 18 is left out because the drive leaves it out: its sectors are
        the BAM and the directory, and a file is never given one.
        """
        return sum(self.track_free(t) for t in range(1, TRACK_COUNT + 1)
                   if t != DIRECTORY_TRACK)

    def _mark(self, track: int, sector: int, free: bool) -> None:
        """Set or clear a sector's bitmap bit and keep the track's count in step."""
        if self.is_free(track, sector) == free:
            return
        entry = self._bam_entry(track)
        at = entry + 1 + sector // 8
        bit = 1 << (sector % 8)
        if free:
            self._data[at] |= bit
            self._data[entry] += 1
        else:
            self._data[at] &= ~bit & 0xFF
            self._data[entry] -= 1

    def _track_order(self) -> list[int]:
        """The tracks a file is allocated from, in the order the 1541 uses them.

        Down from 17 to 1, then up from 19 to 35: away from the directory
        track in one direction first. That is what the player's disks show --
        a 29-block ``SAVEDGAME0`` starting on track 17 spills onto track 16.
        """
        return ([t for t in range(DIRECTORY_TRACK - 1, 0, -1)]
                + [t for t in range(DIRECTORY_TRACK + 1, TRACK_COUNT + 1)])

    def _allocate(self, count: int,
                  interleave: int = FILE_INTERLEAVE) -> list[tuple[int, int]]:
        """``count`` free blocks in chain order, or nothing at all.

        Nothing is reserved until the whole run is in hand, so a disk without
        the room is left exactly as it was rather than half written.

        The first block is the lowest free sector on the first track that has
        one. Each block after it sits `interleave` sectors further round the
        track, wrapping by the track's sector count, and steps forward one
        sector at a time when that lands on a block already taken. When a
        track fills, the next one carries on from the same running sector
        number rather than restarting at 0 -- which is what makes the spill
        from track 17 to track 16 land on sector 4 on the player's disks.

        **Measured within one speed zone only.** Every spill in evidence is
        track 17 to track 16, both 21 sectors, because no file a 1541 wrote
        on any disk here is long enough to cross into the 19-, 18- or
        17-sector zones. The wrap uses each track's own sector count and
        fills to exactly 664 blocks when driven across all three by hand, so
        the accounting is sound -- but whether a real drive picks the *same*
        sector at a zone boundary is unverified, and a save file is far too
        short to reach one.
        """
        if count < 1:
            raise ValueError(f"a file occupies at least one block, got {count}")
        if interleave < 1:
            raise ValueError(f"interleave must be at least 1, got {interleave}")
        found: list[tuple[int, int]] = []
        taken: set[tuple[int, int]] = set()
        last: int | None = None
        for track in self._track_order():
            limit = sectors_per_track(track, self._variant.tracks)
            while len(found) < count:
                if last is None:
                    free = [s for s in range(limit)
                            if self.is_free(track, s) and (track, s) not in taken]
                    if not free:
                        break
                    sector = free[0]
                else:
                    sector = (last + interleave) % limit
                    start = sector
                    while not self.is_free(track, sector) or (track, sector) in taken:
                        sector = (sector + 1) % limit
                        if sector == start:
                            sector = -1
                            break
                    if sector < 0:
                        break
                found.append((track, sector))
                taken.add((track, sector))
                last = sector
            if len(found) == count:
                break
        if len(found) < count:
            raise DiskFullError(
                f"{count} blocks wanted and {len(found)} free on "
                f"{self.disk_name!r}; nothing was written")
        for track, sector in found:
            self._mark(track, sector, free=False)
        return found

    # ---- writing a file --------------------------------------------------

    def _directory_chain(self) -> list[tuple[int, int]]:
        """The directory's own sectors, from track 18 sector 1."""
        chain: list[tuple[int, int]] = []
        track, sector = DIRECTORY_TRACK, DIRECTORY_SECTOR
        while track != 0:
            if (track, sector) in chain:
                raise SectorChainError(
                    f"directory chain loops at track {track} sector {sector}")
            chain.append((track, sector))
            buf = self.read_sector(track, sector)
            track, sector = buf[0], buf[1]
        return chain

    def _grow_directory(self) -> tuple[int, int]:
        """Add a directory sector on track 18 and link it to the last one."""
        chain = self._directory_chain()
        last_track, last_sector = chain[-1]
        limit = sectors_per_track(DIRECTORY_TRACK, self._variant.tracks)
        sector = (last_sector + DIRECTORY_INTERLEAVE) % limit
        start = sector
        while not self.is_free(DIRECTORY_TRACK, sector):
            sector = (sector + 1) % limit
            if sector == start:
                raise DirectoryFullError(
                    f"track {DIRECTORY_TRACK} is full: "
                    f"{len(chain) * ENTRIES_PER_DIR_SECTOR} files is all a "
                    "1541 directory holds")
        self._mark(DIRECTORY_TRACK, sector, free=False)
        off = sector_offset(DIRECTORY_TRACK, sector, self._variant.tracks)
        self._data[off : off + SECTOR_SIZE] = bytes(SECTOR_SIZE)
        self._data[off], self._data[off + 1] = 0, 0xFF
        prev = sector_offset(last_track, last_sector, self._variant.tracks)
        self._data[prev], self._data[prev + 1] = DIRECTORY_TRACK, sector
        return DIRECTORY_TRACK, sector

    def _free_slot(self) -> tuple[int, int, int]:
        """``(track, sector, slot)`` of the first unused directory entry.

        Grows the directory chain when every slot in it is taken.
        """
        for entry in self.iter_directory(include_empty=True):
            if entry.is_empty:
                return entry.dir_track, entry.dir_sector, entry.slot
        track, sector = self._grow_directory()
        return track, sector, 0

    def write_file(self, name: NameLike, data: bytes,
                   file_type: int = FILE_TYPE_PRG,
                   interleave: int = FILE_INTERLEAVE) -> DirEntry:
        """Put a new file on the disk: allocate, chain, and link an entry (#118).

        `data` is the file's whole byte stream, so for a PRG that includes the
        two-byte load address -- :func:`attach_load_address` is what puts it
        there. Returns the directory entry that now names it.

        The name has to be new. Growing or replacing a file is deliberately
        not implemented, because nothing here scratches a file and so no block
        is ever freed; :meth:`write_file_inplace` rewrites one at its existing
        block count.

        A failure leaves the image byte for byte as it was -- a disk that ran
        out of room half way through a write is a corrupt disk, and the caller
        cannot tell from the exception which half happened.
        """
        self._require_writable()
        raw = _normalize_name(name)
        if not raw:
            raise ValueError("an empty name names nothing")
        if len(raw) > NAME_LENGTH:
            raise ValueError(
                f"{raw!r} is {len(raw)} bytes; a 1541 name is at most {NAME_LENGTH}")
        if NAME_PAD in raw:
            raise ValueError(
                f"{raw!r} contains {NAME_PAD:#04x}, which is the name padding "
                "and would not read back")
        if not 0 <= file_type <= 0x0F:
            raise ValueError(f"file type out of range 0..15: {file_type}")
        if self.find(raw) is not None:
            raise DuplicateFileError(
                f"{raw!r} is already on this disk; write_file only creates")

        before = bytes(self._data)
        try:
            dir_track, dir_sector, slot = self._free_slot()
            chain = self._allocate(self.blocks_needed(len(data)),
                                   interleave=interleave)
            for i, (track, sector) in enumerate(chain):
                off = sector_offset(track, sector, self._variant.tracks)
                chunk = data[i * PAYLOAD_PER_SECTOR : (i + 1) * PAYLOAD_PER_SECTOR]
                if i + 1 < len(chain):
                    self._data[off], self._data[off + 1] = chain[i + 1]
                else:
                    # The last sector links to track 0 and its second byte is
                    # the index of the last valid payload byte, not a sector.
                    self._data[off], self._data[off + 1] = 0, 1 + len(chunk)
                self._data[off + 2 : off + 2 + len(chunk)] = chunk

            at = (sector_offset(dir_track, dir_sector, self._variant.tracks)
                  + ENTRY_BASE + slot * ENTRY_SIZE)
            # Clear the slot first: a scratched entry keeps its old name and
            # REL fields, and only its type byte is zeroed. `ENTRY_FIELDS`
            # rather than `ENTRY_SIZE` -- the last two bytes of a slot are
            # the next slot's, and slot 7's are the next sector's link.
            self._data[at : at + ENTRY_FIELDS] = bytes(ENTRY_FIELDS)
            self._data[at] = 0x80 | file_type          # closed
            self._data[at + 1], self._data[at + 2] = chain[0]
            self._data[at + 3 : at + 3 + NAME_LENGTH] = raw.ljust(
                NAME_LENGTH, bytes([NAME_PAD]))
            self._data[at + 28] = len(chain) & 0xFF
            self._data[at + 29] = len(chain) >> 8
        except BaseException:
            self._data[:] = before
            raise
        return self.entry(raw)


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
