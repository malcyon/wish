"""The Amiga floppy filesystem, read and written (#36).

Enough of OFS -- the *Old File System*, which is what every Gold Box Amiga
release ships on -- to **add a file to a real game disk**: allocate blocks from
the bitmap, write them, build a file header, thread it into the parent
directory's hash chain, and fix every checksum the filesystem keeps.

Until this existed a converted character reached an Amiga disk only by
overwriting an existing file's bytes, so a player could not be handed a disk
with their party on it -- which is the only form the result is useful in.

No transport, no Qt, no emulator: bytes in and bytes out, the same contract as
the rest of `goldbox/`.

What was measured rather than looked up
---------------------------------------
Every structure below was checked against the player's own disks before a byte
was written, because a filesystem write that is *nearly* right corrupts a disk
silently:

* the root block is at 880 on an 880K disk, `ht_size` 72, `bm_flag` -1, one
  bitmap page -- read off `Pool of Radiance (Disk 1 of 2).adf`;
* the block checksum is `-(sum of the 128 big-endian longwords, with the
  checksum slot zero)`, and recomputing it reproduces the stored value on the
  root block and the bitmap block of that disk;
* **a set bit in the bitmap means free**, and bit *i* of the bitmap is block
  *i + 2*: block 880 (the root) and block 2 read 0, and 258 of the 1758
  data blocks read 1 -- which is how much room a Gold Box game disk has left;
* the directory hash is `h = len(name); for c in upper(name): h = (h*13 + c)
  & 0x7FF; h %= 72`, and it puts **76 of 76** real directory entries in the
  chain the disk actually files them under.

What this does not do
---------------------
* **FFS is refused by name.** The bit is read and reported; no Gold Box Amiga
  release uses it.
* **Directories are read, not created.** Every path a conversion needs -- the
  `SAVE` drawer -- already exists on the disks.
* Comments, protection bits and the `.info` files Workbench keeps are not
  written. AmigaDOS does not need them and the game does not read them.
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import struct
from typing import Iterator

__all__ = [
    "AmigaDiskError",
    "BLOCK_SIZE",
    "HASH_TABLE_SIZE",
    "OFS_DATA_SIZE",
    "AmigaDisk",
    "DirEntry",
    "block_checksum",
    "hash_name",
]

BLOCK_SIZE = 512
#: Entries in a directory's hash table -- `(BLOCK_SIZE / 4) - 56`.
HASH_TABLE_SIZE = 72
#: Payload of one OFS data block: 512 less its 24-byte header.
OFS_DATA_SIZE = BLOCK_SIZE - 24
#: Data-block pointers a header or extension block can carry.
MAX_DATA_POINTERS = HASH_TABLE_SIZE

T_HEADER = 2
T_DATA = 8
T_LIST = 16
ST_ROOT = 1
ST_USERDIR = 2
ST_FILE = -3

#: The first two blocks are the bootblock and are outside the bitmap.
FIRST_DATA_BLOCK = 2
#: AmigaDOS counts days from this date.
AMIGA_EPOCH = datetime.date(1978, 1, 1)

_HDR_TYPE = 0x000
_HDR_KEY = 0x004
_HDR_HIGH_SEQ = 0x008
#: `ht_size` in a directory or the root; `data_size`, and unused, in a file.
_HDR_TABLE_SIZE = 0x00C
_HDR_FIRST_DATA = 0x010
_HDR_CHECKSUM = 0x014
_HDR_HASH_TABLE = 0x018
#: `data_blocks[0]`; the table runs **downwards** from here.
_HDR_DATA_TABLE = BLOCK_SIZE - 204
_HDR_BM_FLAG = BLOCK_SIZE - 200
_HDR_BM_PAGES = BLOCK_SIZE - 196
_HDR_BYTE_SIZE = BLOCK_SIZE - 188
_HDR_COMMENT = BLOCK_SIZE - 184
_HDR_DAYS = BLOCK_SIZE - 92
_HDR_NAME = BLOCK_SIZE - 80
_HDR_NEXT_HASH = BLOCK_SIZE - 16
_HDR_PARENT = BLOCK_SIZE - 12
_HDR_EXTENSION = BLOCK_SIZE - 8
_HDR_SEC_TYPE = BLOCK_SIZE - 4

_DAT_TYPE = 0x000
_DAT_KEY = 0x004
_DAT_SEQ = 0x008
_DAT_SIZE = 0x00C
_DAT_NEXT = 0x010
_DAT_CHECKSUM = 0x014
_DAT_PAYLOAD = 0x018

#: The longest name AmigaDOS stores in a header block.
MAX_NAME = 30


class AmigaDiskError(ValueError):
    """A disk image this module will not read, or a write it will not make."""


def block_checksum(block: bytes, at: int) -> int:
    """The AmigaDOS block checksum: negate the sum of the longwords.

    `at` is the offset of the checksum field itself, which counts as zero.
    Verified against the stored value on a real disk's root block and bitmap
    block before anything here wrote one.
    """
    total = 0
    for offset in range(0, BLOCK_SIZE, 4):
        if offset == at:
            continue
        total = (total + struct.unpack_from(">I", block, offset)[0]) & 0xFFFFFFFF
    return (-total) & 0xFFFFFFFF


def hash_name(name: str, size: int = HASH_TABLE_SIZE) -> int:
    """Which hash-table slot a directory entry belongs in.

    The standard (non-international) OFS hash. Measured: it reproduces the
    slot the disk actually files the entry under for **76 of 76** entries on
    Pool of Radiance disk 1, across four directories.

    The international variant differs only for `0xE0`-`0xFE`, and no Gold Box
    file name leaves ASCII.
    """
    value = len(name)
    for char in name.upper():
        value = ((value * 13) + ord(char)) & 0x7FF
    return value % size


def _amiga_date(when: datetime.datetime) -> tuple[int, int, int]:
    """`(days, minutes, ticks)` -- ticks are fiftieths of a second."""
    days = (when.date() - AMIGA_EPOCH).days
    minutes = when.hour * 60 + when.minute
    ticks = when.second * 50 + when.microsecond // 20000
    return days, minutes, ticks


@dataclasses.dataclass(frozen=True)
class DirEntry:
    """One name in a directory, and the block its header lives in."""

    name: str
    block: int
    sec_type: int

    @property
    def is_dir(self) -> bool:
        return self.sec_type in (ST_ROOT, ST_USERDIR)


class AmigaDisk:
    """One `.adf`, read and written in memory.

    Nothing here touches a file until :meth:`save` is called, and the player's
    own disks are opened read-only -- work on a copy, the way the rest of this
    project does.
    """

    def __init__(self, data: bytes | bytearray) -> None:
        if len(data) % BLOCK_SIZE:
            raise AmigaDiskError(
                f"a disk image is a whole number of {BLOCK_SIZE}-byte blocks; "
                f"{len(data)} is not")
        if len(data) < 3 * BLOCK_SIZE:
            raise AmigaDiskError(f"{len(data)} bytes is too small to be a disk")
        self._data = bytearray(data)
        if bytes(self._data[:3]) != b"DOS":
            raise AmigaDiskError(
                f"no `DOS` bootblock signature; got {bytes(self._data[:4])!r}. "
                f"This reads AmigaDOS floppies, not the `.dax` archives inside "
                f"them")
        if self.ffs:
            raise AmigaDiskError(
                "this image is FFS and only OFS is implemented; every Gold Box "
                "Amiga release ships OFS, so an FFS disk here is a surprise "
                "worth looking at rather than working around")
        self.root = self._find_root()

    # -- construction -------------------------------------------------------
    @classmethod
    def open(cls, path: str | pathlib.Path) -> "AmigaDisk":
        return cls(pathlib.Path(path).read_bytes())

    @classmethod
    def blank(cls, name: str = "Empty", blocks: int = 1760) -> "AmigaDisk":
        """A freshly formatted OFS disk, for a test that wants no game data.

        `blocks` is 1760 for a standard 880K floppy. The root goes in the
        middle block, which is where AmigaDOS puts it, and the bitmap in the
        block after.
        """
        cls._check_name(name)
        data = bytearray(blocks * BLOCK_SIZE)
        data[0:4] = b"DOS\x00"
        root = blocks // 2
        bitmap = root + 1
        struct.pack_into(">I", data, root * BLOCK_SIZE + _HDR_TYPE, T_HEADER)
        struct.pack_into(">I", data, root * BLOCK_SIZE + _HDR_TABLE_SIZE,
                         HASH_TABLE_SIZE)
        struct.pack_into(">i", data, root * BLOCK_SIZE + _HDR_BM_FLAG, -1)
        struct.pack_into(">I", data, root * BLOCK_SIZE + _HDR_BM_PAGES, bitmap)
        struct.pack_into(">i", data, root * BLOCK_SIZE + _HDR_SEC_TYPE, ST_ROOT)
        encoded = name.encode("latin1")
        data[root * BLOCK_SIZE + _HDR_NAME] = len(encoded)
        data[root * BLOCK_SIZE + _HDR_NAME + 1:
             root * BLOCK_SIZE + _HDR_NAME + 1 + len(encoded)] = encoded
        # Every block free, then the two the filesystem itself occupies taken.
        # The bootblock is outside the bitmap entirely.
        for offset in range(4, BLOCK_SIZE, 4):
            struct.pack_into(">I", data, bitmap * BLOCK_SIZE + offset, 0xFFFFFFFF)
        disk = cls(data)
        disk._set_free(root, False)
        disk._set_free(bitmap, False)
        # Bits past the end of the disk must read allocated, or a later
        # allocation walks off the end of the image.
        for block in range(blocks, blocks + (BLOCK_SIZE - 4) * 8):
            index = block - FIRST_DATA_BLOCK
            if 4 + 4 * (index // 32) >= BLOCK_SIZE:
                break
            disk._set_free(block, False)
        disk._touch(root)
        disk._fix(root, _HDR_CHECKSUM)
        disk._fix_bitmap()
        return disk

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def save(self, path: str | pathlib.Path) -> None:
        pathlib.Path(path).write_bytes(self.to_bytes())

    def restore(self, data: bytes | bytearray) -> None:
        """Put the whole image back to a snapshot taken with :meth:`to_bytes`.

        The undo half of a multi-file write.  A caller that writes sixteen
        files and fails on the tenth has a disk that is neither what it was
        nor what it meant to be, and the AmigaDOS structures are exactly the
        kind of thing that is worse half-changed than not changed at all --
        `write_file` allocates the replacement before freeing the original,
        so a run that fills the disk can stop anywhere.
        """
        if len(data) != len(self._data):
            raise AmigaDiskError(
                f"a snapshot of {len(data)} bytes is not this disk's "
                f"{len(self._data)}")
        self._data[:] = data
        self.root = self._find_root()

    # -- the shape of the disk ---------------------------------------------
    @property
    def block_count(self) -> int:
        return len(self._data) // BLOCK_SIZE

    @property
    def ffs(self) -> bool:
        """The Fast File System bit of the bootblock's flags byte."""
        return bool(self._data[3] & 1)

    @property
    def volume_name(self) -> str:
        return self._name_of(self.root)

    def block(self, number: int) -> bytes:
        if not 0 <= number < self.block_count:
            raise AmigaDiskError(
                f"block {number} is outside a {self.block_count}-block disk")
        return bytes(self._data[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE])

    def _find_root(self) -> int:
        """The root block, by looking rather than by assuming.

        880 first, because the Curse save disk is **1804** blocks and its root
        is still 880 -- it is a standard 880K filesystem with 44 extra blocks
        on the end, and its middle block, 902, is `ADDERLY.cha`. Trying the
        middle block first would read a character record as a root block.
        """
        for candidate in (880, self.block_count // 2):
            if candidate >= self.block_count:
                continue
            block = self.block(candidate)
            if (self._u32(block, _HDR_TYPE) == T_HEADER
                    and self._i32(block, _HDR_SEC_TYPE) == ST_ROOT):
                return candidate
        raise AmigaDiskError(
            "no root block: neither the middle block nor 880 has type 2 / "
            "sec_type 1")

    # -- reading ------------------------------------------------------------
    def entries(self, header: int | None = None) -> list[DirEntry]:
        """The directory's entries, hash chains followed."""
        if header is None:
            header = self.root
        block = self.block(header)
        out: list[DirEntry] = []
        for slot in range(HASH_TABLE_SIZE):
            number = self._u32(block, _HDR_HASH_TABLE + 4 * slot)
            seen = set()
            while number:
                if number in seen:
                    raise AmigaDiskError(
                        f"hash chain from block {header} slot {slot} loops at "
                        f"block {number}")
                seen.add(number)
                entry = self.block(number)
                out.append(DirEntry(self._name_of(number), number,
                                    self._i32(entry, _HDR_SEC_TYPE)))
                number = self._u32(entry, _HDR_NEXT_HASH)
        return out

    def walk(self, header: int | None = None,
             path: str = "") -> Iterator[tuple[str, DirEntry]]:
        """Every file on the disk, as `(path, entry)`, depth first."""
        for entry in self.entries(header):
            here = f"{path}/{entry.name}"
            if entry.is_dir:
                yield from self.walk(entry.block, here)
            else:
                yield here, entry

    def walk_dirs(self, header: int | None = None,
                  path: str = "") -> Iterator[tuple[str, DirEntry]]:
        """Every drawer on the disk, as `(path, entry)`, depth first.

        The companion to :meth:`walk`, which yields only files -- and the
        reason this exists is that `verify()` had no way to reach a drawer's
        own header block. Before `make_dir` every directory on a disk this
        module wrote was the root, which `verify()` checks by hand, so the
        gap was invisible: a drawer with a wrong checksum verified clean.
        """
        for entry in self.entries(header):
            if not entry.is_dir:
                continue
            here = f"{path}/{entry.name}"
            yield here, entry
            yield from self.walk_dirs(entry.block, here)

    def lookup(self, path: str) -> DirEntry:
        """One entry by `SAVE/NAME.cha`-style path, case-insensitively.

        AmigaDOS file names are case-preserving and case-insensitive, which is
        the same thing the hash function's `upper()` says.
        """
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise AmigaDiskError("an empty path names nothing")
        header = self.root
        for index, part in enumerate(parts):
            for entry in self.entries(header):
                if entry.name.upper() == part.upper():
                    break
            else:
                where = "/".join(parts[:index]) or "the root"
                raise AmigaDiskError(
                    f"{part!r} is not in {where} of {self.volume_name!r}")
            if index < len(parts) - 1:
                if not entry.is_dir:
                    raise AmigaDiskError(f"{part!r} is a file, not a drawer")
                header = entry.block
        return entry

    def read_file(self, path: str) -> bytes:
        entry = self.lookup(path)
        if entry.is_dir:
            raise AmigaDiskError(f"{path!r} is a drawer, not a file")
        return self._read_file_block(entry.block)

    def _read_file_block(self, header: int) -> bytes:
        block = self.block(header)
        size = self._u32(block, _HDR_BYTE_SIZE)
        out = bytearray()
        current = block
        while True:
            count = self._u32(current, _HDR_HIGH_SEQ)
            for index in range(count):
                data = self.block(
                    self._u32(current, _HDR_DATA_TABLE - 4 * index))
                used = self._u32(data, _DAT_SIZE)
                if used > OFS_DATA_SIZE:
                    raise AmigaDiskError(
                        f"a data block claims {used} bytes of a "
                        f"{OFS_DATA_SIZE}-byte payload")
                out += data[_DAT_PAYLOAD:_DAT_PAYLOAD + used]
            extension = self._u32(current, _HDR_EXTENSION)
            if not extension:
                break
            current = self.block(extension)
        if len(out) < size:
            raise AmigaDiskError(
                f"the header says {size} bytes and the chain holds {len(out)}")
        return bytes(out[:size])

    # -- the bitmap ---------------------------------------------------------
    #: Blocks one bitmap page can describe: its 127 usable longwords, in bits.
    BITMAP_CAPACITY = (BLOCK_SIZE - 4) * 8

    def _bitmap_block(self) -> int:
        """The one bitmap page, and only the first pointer is believed.

        A floppy never needs a second: one page carries 4064 bits against
        1758 data blocks. Real disks put junk in the later slots anyway --
        Pools of Darkness disk 2 names block 955 **twice** and disk 3 names
        1352 and 1360 -- so a reader that trusted them would refuse three
        genuine disks. A disk actually too big for one page is refused.
        """
        page = self._u32(self.block(self.root), _HDR_BM_PAGES)
        if not page:
            raise AmigaDiskError("the root block names no bitmap page")
        if self.block_count - FIRST_DATA_BLOCK > self.BITMAP_CAPACITY:
            raise AmigaDiskError(
                f"{self.block_count} blocks needs more than one bitmap page "
                f"and only the single-page floppy layout is implemented")
        return page

    def is_free(self, block: int) -> bool:
        """A **set** bit means free. Measured on a real disk, not looked up."""
        index = block - FIRST_DATA_BLOCK
        if index < 0:
            return False
        word = self._u32(self.block(self._bitmap_block()), 4 + 4 * (index // 32))
        return bool((word >> (index % 32)) & 1)

    def free_count(self) -> int:
        return sum(self.is_free(b)
                   for b in range(FIRST_DATA_BLOCK, self.block_count))

    def _set_free(self, block: int, free: bool) -> None:
        index = block - FIRST_DATA_BLOCK
        if index < 0:
            raise AmigaDiskError(f"block {block} is outside the bitmap")
        at = self._bitmap_block() * BLOCK_SIZE + 4 + 4 * (index // 32)
        if at + 4 > (self._bitmap_block() + 1) * BLOCK_SIZE:
            raise AmigaDiskError(f"block {block} is past the bitmap's last bit")
        word = struct.unpack_from(">I", self._data, at)[0]
        bit = 1 << (index % 32)
        word = (word | bit) if free else (word & ~bit & 0xFFFFFFFF)
        struct.pack_into(">I", self._data, at, word)

    def _allocate(self, count: int) -> list[int]:
        """`count` free blocks, **highest first**, or nothing at all.

        It reserves nothing until it has them all, so a disk that is too full
        is left exactly as it was rather than half-written.

        Highest first is not tidiness, it is a measurement. **A cracked
        release reads blocks the bitmap says are free.** Writing one small
        file into Pool of Radiance disk 1's lowest free blocks -- 917 and 991
        -- boots to the code wheel; writing a second, which takes 992 and 993,
        hangs the boot on a white screen with the drive still seeking, and
        that is with no existing file touched and every checksum right
        (`work/amiga/p36/shots/`, #36). Those blocks sit between the bitmap at
        990 and the `save` drawer at 996, which is where a loader would put
        its own scratch.

        The high end of a Gold Box game disk is the game's own data, allocated
        and therefore never taken; the free runs stop well below it. So
        counting down from the top stays inside genuinely unused space and
        away from whatever the front of the disk is really for.
        """
        found = [b for b in range(self.block_count - 1,
                                  FIRST_DATA_BLOCK - 1, -1)
                 if self.is_free(b)][:count]
        if len(found) < count:
            raise AmigaDiskError(
                f"{count} blocks wanted and {len(found)} free on "
                f"{self.volume_name!r}; nothing was written")
        for block in found:
            self._set_free(block, False)
        return found

    # -- writing ------------------------------------------------------------
    @staticmethod
    def _check_name(name: str) -> None:
        if not name:
            raise AmigaDiskError("an empty name")
        if len(name) > MAX_NAME:
            raise AmigaDiskError(
                f"{name!r} is {len(name)} characters; AmigaDOS stores at most "
                f"{MAX_NAME}")
        try:
            encoded = name.encode("latin1")
        except UnicodeEncodeError as exc:
            raise AmigaDiskError(f"{name!r} is not Amiga text") from exc
        for bad in b"/:":
            if bad in encoded:
                raise AmigaDiskError(
                    f"{name!r} contains {chr(bad)!r}, which separates a path")

    def write_file(self, path: str, data: bytes,
                   when: datetime.datetime | None = None) -> int:
        """Put `data` on the disk at `path`, replacing what is there.

        Returns the file header's block number. The parent drawer has to
        exist; this creates files, not directories, because every path a
        conversion needs is already on the game disk.

        A failure leaves the disk unchanged: the blocks are counted and
        reserved before anything is linked, and an existing file of the same
        name is only unlinked once the new one is written.
        """
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise AmigaDiskError("an empty path names nothing")
        name = parts[-1]
        self._check_name(name)
        parent = self.root
        for part in parts[:-1]:
            entry = self.lookup("/".join(parts[:parts.index(part) + 1]))
            if not entry.is_dir:
                raise AmigaDiskError(f"{part!r} is a file, not a drawer")
            parent = entry.block

        existing = None
        for entry in self.entries(parent):
            if entry.name.upper() == name.upper():
                if entry.is_dir:
                    raise AmigaDiskError(
                        f"{name!r} is already a drawer on this disk")
                existing = entry
                break

        when = when or datetime.datetime.now()
        blocks_needed = max(1, -(-len(data) // OFS_DATA_SIZE))
        headers_needed = max(1, -(-blocks_needed // MAX_DATA_POINTERS))
        # Allocate the replacement before touching the old file, so a
        # failure leaves the disk exactly as it was: an existing file of the
        # same name is only unlinked once the new one's blocks are secured.
        # A consequence: the old file's own blocks are not up for reuse by
        # its own replacement, so a same-size replace that used to succeed
        # on a disk with no other room now fails instead of overwriting in
        # place (#36).
        allocated = self._allocate(blocks_needed + headers_needed)
        if existing is not None:
            self._unlink(parent, existing)
            self._free_file(existing.block)
        header = allocated[0]
        extensions = allocated[1:headers_needed]
        data_blocks = allocated[headers_needed:]

        self._write_data_chain(header, data, data_blocks)
        self._write_header(header, parent, name, data, data_blocks,
                           extensions, when)
        self._link(parent, header, name)
        self._touch(parent)
        self._fix(parent, _HDR_CHECKSUM)
        if parent != self.root:
            self._touch(self.root)
            self._fix(self.root, _HDR_CHECKSUM)
        self._fix_bitmap()
        return header

    def make_dir(self, path: str,
                 when: datetime.datetime | None = None) -> int:
        """Create a drawer at `path` and return its block number.

        One block, no data chain: a `ST_USERDIR` header is a hash table and a
        name, which is why this is short where `write_file` is not.  The
        parent has to exist, and a name already in the parent is an error
        rather than a silent reuse -- a drawer that quietly turned out to be
        the file of the same name is the kind of thing that corrupts a disk
        two operations later.

        Production never needs it: a converted party lands in the `save`
        drawer of a copy of the player's own game disk, which is already
        there.  It exists so the writer above can be tested on a disk this
        module formatted, with no game data anywhere -- which is the property
        `tests/test_amiga_adf.py` is built on.
        """
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise AmigaDiskError("an empty path names nothing")
        name = parts[-1]
        self._check_name(name)
        parent = self.root
        if len(parts) > 1:
            entry = self.lookup("/".join(parts[:-1]))
            if not entry.is_dir:
                raise AmigaDiskError(
                    f"{parts[-2]!r} is a file, not a drawer")
            parent = entry.block
        for entry in self.entries(parent):
            if entry.name.upper() == name.upper():
                raise AmigaDiskError(
                    f"{name!r} is already on this disk at block {entry.block}")

        header = self._allocate(1)[0]
        at = header * BLOCK_SIZE
        self._data[at:at + BLOCK_SIZE] = bytes(BLOCK_SIZE)
        struct.pack_into(">I", self._data, at + _HDR_TYPE, T_HEADER)
        struct.pack_into(">I", self._data, at + _HDR_KEY, header)
        days, minutes, ticks = _amiga_date(when or datetime.datetime.now())
        struct.pack_into(">III", self._data, at + _HDR_DAYS,
                         days, minutes, ticks)
        encoded = name.encode("latin1")
        self._data[at + _HDR_NAME] = len(encoded)
        self._data[at + _HDR_NAME + 1:
                   at + _HDR_NAME + 1 + len(encoded)] = encoded
        struct.pack_into(">I", self._data, at + _HDR_PARENT, parent)
        struct.pack_into(">i", self._data, at + _HDR_SEC_TYPE, ST_USERDIR)
        self._fix(header, _HDR_CHECKSUM)

        self._link(parent, header, name)
        self._touch(parent)
        self._fix(parent, _HDR_CHECKSUM)
        if parent != self.root:
            self._touch(self.root)
            self._fix(self.root, _HDR_CHECKSUM)
        self._fix_bitmap()
        return header

    def remove_file(self, path: str) -> None:
        """Unlink a file and give its blocks back to the bitmap."""
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        entry = self.lookup(path)
        if entry.is_dir:
            raise AmigaDiskError(f"{path!r} is a drawer, not a file")
        parent = self.root
        if len(parts) > 1:
            parent = self.lookup("/".join(parts[:-1])).block
        self._unlink(parent, entry)
        self._free_file(entry.block)
        self._touch(parent)
        self._fix(parent, _HDR_CHECKSUM)
        self._fix_bitmap()

    def _write_data_chain(self, header: int, data: bytes,
                          blocks: list[int]) -> None:
        for index, number in enumerate(blocks):
            chunk = data[index * OFS_DATA_SIZE:(index + 1) * OFS_DATA_SIZE]
            at = number * BLOCK_SIZE
            self._data[at:at + BLOCK_SIZE] = bytes(BLOCK_SIZE)
            struct.pack_into(">I", self._data, at + _DAT_TYPE, T_DATA)
            struct.pack_into(">I", self._data, at + _DAT_KEY, header)
            struct.pack_into(">I", self._data, at + _DAT_SEQ, index + 1)
            struct.pack_into(">I", self._data, at + _DAT_SIZE, len(chunk))
            nxt = blocks[index + 1] if index + 1 < len(blocks) else 0
            struct.pack_into(">I", self._data, at + _DAT_NEXT, nxt)
            self._data[at + _DAT_PAYLOAD:at + _DAT_PAYLOAD + len(chunk)] = chunk
            self._fix(number, _DAT_CHECKSUM)

    def _write_header(self, header: int, parent: int, name: str, data: bytes,
                      blocks: list[int], extensions: list[int],
                      when: datetime.datetime) -> None:
        chain = [header] + extensions
        for position, number in enumerate(chain):
            mine = blocks[position * MAX_DATA_POINTERS:
                          (position + 1) * MAX_DATA_POINTERS]
            at = number * BLOCK_SIZE
            self._data[at:at + BLOCK_SIZE] = bytes(BLOCK_SIZE)
            first = position == 0
            struct.pack_into(">I", self._data, at + _HDR_TYPE,
                             T_HEADER if first else T_LIST)
            struct.pack_into(">I", self._data, at + _HDR_KEY, number)
            struct.pack_into(">I", self._data, at + _HDR_HIGH_SEQ, len(mine))
            # `first_data` on the header and **zero on every extension**, which
            # is what the four real disks do: 211 of 211 file headers carry
            # `data_table[0]` there and every extension block carries 0.
            if first and mine:
                struct.pack_into(">I", self._data, at + _HDR_FIRST_DATA, mine[0])
            for index, block in enumerate(mine):
                struct.pack_into(">I", self._data,
                                 at + _HDR_DATA_TABLE - 4 * index, block)
            nxt = chain[position + 1] if position + 1 < len(chain) else 0
            struct.pack_into(">I", self._data, at + _HDR_EXTENSION, nxt)
            struct.pack_into(">i", self._data, at + _HDR_SEC_TYPE, ST_FILE)
            if first:
                struct.pack_into(">I", self._data, at + _HDR_BYTE_SIZE,
                                 len(data))
                days, minutes, ticks = _amiga_date(when)
                struct.pack_into(">III", self._data, at + _HDR_DAYS,
                                 days, minutes, ticks)
                encoded = name.encode("latin1")
                self._data[at + _HDR_NAME] = len(encoded)
                self._data[at + _HDR_NAME + 1:
                           at + _HDR_NAME + 1 + len(encoded)] = encoded
                struct.pack_into(">I", self._data, at + _HDR_PARENT, parent)
            else:
                struct.pack_into(">I", self._data, at + _HDR_PARENT, header)
            self._fix(number, _HDR_CHECKSUM)

    def _link(self, parent: int, header: int, name: str) -> None:
        """Thread the header into its slot of the parent's hash chain.

        New entries go at the **head** of the chain, which is what AmigaDOS
        itself does and is why a directory listing is not in creation order.
        """
        slot = hash_name(name)
        at = parent * BLOCK_SIZE + _HDR_HASH_TABLE + 4 * slot
        first = struct.unpack_from(">I", self._data, at)[0]
        struct.pack_into(">I", self._data,
                         header * BLOCK_SIZE + _HDR_NEXT_HASH, first)
        struct.pack_into(">I", self._data, at, header)
        self._fix(header, _HDR_CHECKSUM)

    def _unlink(self, parent: int, entry: DirEntry) -> None:
        slot = hash_name(entry.name)
        at = parent * BLOCK_SIZE + _HDR_HASH_TABLE + 4 * slot
        number = struct.unpack_from(">I", self._data, at)[0]
        following = self._u32(self.block(entry.block), _HDR_NEXT_HASH)
        if number == entry.block:
            struct.pack_into(">I", self._data, at, following)
            return
        while number:
            block = self.block(number)
            nxt = self._u32(block, _HDR_NEXT_HASH)
            if nxt == entry.block:
                struct.pack_into(">I", self._data,
                                 number * BLOCK_SIZE + _HDR_NEXT_HASH,
                                 following)
                self._fix(number, _HDR_CHECKSUM)
                return
            number = nxt
        raise AmigaDiskError(
            f"{entry.name!r} is not in the hash chain of slot {slot}; the "
            f"directory and the header disagree and nothing was changed")

    def _free_file(self, header: int) -> None:
        current = header
        while current:
            block = self.block(current)
            for index in range(self._u32(block, _HDR_HIGH_SEQ)):
                self._set_free(self._u32(block, _HDR_DATA_TABLE - 4 * index),
                               True)
            nxt = self._u32(block, _HDR_EXTENSION)
            self._set_free(current, True)
            current = nxt

    # -- housekeeping -------------------------------------------------------
    def _touch(self, header: int,
               when: datetime.datetime | None = None) -> None:
        days, minutes, ticks = _amiga_date(when or datetime.datetime.now())
        struct.pack_into(">III", self._data, header * BLOCK_SIZE + _HDR_DAYS,
                         days, minutes, ticks)

    def _fix(self, block: int, at: int) -> None:
        start = block * BLOCK_SIZE
        struct.pack_into(">I", self._data, start + at, 0)
        struct.pack_into(">I", self._data, start + at,
                         block_checksum(self._data[start:start + BLOCK_SIZE],
                                        at))

    def _fix_bitmap(self) -> None:
        self._fix(self._bitmap_block(), 0)

    @staticmethod
    def _u32(block: bytes, offset: int) -> int:
        return struct.unpack_from(">I", block, offset)[0]

    @staticmethod
    def _i32(block: bytes, offset: int) -> int:
        return struct.unpack_from(">i", block, offset)[0]

    def _name_of(self, header: int) -> str:
        block = self.block(header)
        length = block[_HDR_NAME]
        if length > MAX_NAME:
            raise AmigaDiskError(
                f"block {header} claims a {length}-character name")
        return block[_HDR_NAME + 1:_HDR_NAME + 1 + length].decode("latin1")

    def block_sum(self, number: int) -> int:
        """The 128 big-endian longwords of a block, added as `u32`.

        **A valid AmigaDOS block sums to zero.** That is the invariant the
        filesystem actually enforces, and it is what this module checks with,
        because it cannot be satisfied by accident and it does not depend on
        knowing which field the checksum lives in.

        The first version of this module did depend on that, had the offset
        one longword low, and its `verify()` passed on every disk it wrote --
        vacuously, because the field it was comparing held zero on both sides.
        Kickstart said `Not a DOS disk in unit 0` and that was the first
        anybody knew. Hence this.
        """
        total = 0
        block = self.block(number)
        for offset in range(0, BLOCK_SIZE, 4):
            total = (total + struct.unpack_from(">I", block, offset)[0]) & 0xFFFFFFFF
        return total

    def verify(self) -> list[str]:
        """Everything the filesystem would notice. Empty means consistent.

        Checks the structural blocks sum to zero, that each stores its
        checksum in the field AmigaDOS reads it from, and that nothing in use
        is marked free in the bitmap. A filesystem write that is nearly right
        corrupts a disk silently, and this is what stands in for AmigaDOS
        between emulator runs -- it is not a substitute for one.

        The sum-and-declared-offset check is **vacuous against a checksum
        written one field away**, on the root and the bitmap block exactly as
        it was on a file header (see `block_sum`): if the true checksum field
        reads zero, the recomputed value at that same field is algebraically
        forced to zero too, whatever the rest of the block holds. So the root
        and the bitmap each get one more check, against a field the fault
        cannot also be zeroing.
        """
        problems: list[str] = []

        def check(number: int, at: int, what: str) -> None:
            if self.block_sum(number) != 0:
                problems.append(
                    f"{what} {number} does not sum to zero "
                    f"({self.block_sum(number):#010x})")
            stored = self._u32(self.block(number), at)
            if stored != self._recompute(number, at):
                problems.append(
                    f"{what} {number} keeps its checksum somewhere other than "
                    f"{at:#05x}")

        check(self.root, _HDR_CHECKSUM, "the root block")
        root_block = self.block(self.root)
        ht_size = self._u32(root_block, _HDR_TABLE_SIZE)
        if ht_size != HASH_TABLE_SIZE:
            problems.append(
                f"the root block's hash table size is {ht_size}, not "
                f"{HASH_TABLE_SIZE}")
        reserved = self._u32(root_block, _HDR_FIRST_DATA)
        if reserved != 0:
            problems.append(
                f"the root block's reserved word at {_HDR_FIRST_DATA:#05x} "
                f"is {reserved:#010x}, not 0")
        bm_page = self._u32(root_block, _HDR_BM_PAGES)
        if self.block_sum(bm_page) != 0:
            problems.append(
                f"the root block names block {bm_page} as its bitmap page, "
                f"and that block does not sum to zero")

        check(self._bitmap_block(), 0, "the bitmap block")
        for known in (self.root, self._bitmap_block()):
            if self.is_free(known):
                problems.append(
                    f"block {known} is in use and marked free in the bitmap")

        for where, entry in self.walk_dirs():
            check(entry.block, _HDR_CHECKSUM, f"the drawer {where!r} at block")
            if self.is_free(entry.block):
                problems.append(
                    f"block {entry.block} holds the drawer {where!r} and is "
                    f"marked free in the bitmap")

        for _, entry in self.walk():
            current = entry.block
            head = True
            while current:
                check(current, _HDR_CHECKSUM,
                      "file header" if head else "extension block")
                block = self.block(current)
                count = self._u32(block, _HDR_HIGH_SEQ)
                # Only the header carries `first_data`; an extension block
                # carries 0, on 211 of 211 real files.
                if head and count:
                    named = self._u32(block, _HDR_FIRST_DATA)
                    table = self._u32(block, _HDR_DATA_TABLE)
                    if named != table:
                        problems.append(
                            f"file header {current} names {named} as its first "
                            f"data block and {table} in the table")
                for index in range(count):
                    number = self._u32(block, _HDR_DATA_TABLE - 4 * index)
                    check(number, _DAT_CHECKSUM, "data block")
                    if self.is_free(number):
                        problems.append(
                            f"data block {number} is in use and marked free")
                if self.is_free(current):
                    problems.append(
                        f"block {current} is in use and marked free")
                current = self._u32(block, _HDR_EXTENSION)
                head = False
        return problems

    def _recompute(self, block: int, at: int) -> int:
        start = block * BLOCK_SIZE
        copy = bytearray(self._data[start:start + BLOCK_SIZE])
        struct.pack_into(">I", copy, at, 0)
        return block_checksum(copy, at)
