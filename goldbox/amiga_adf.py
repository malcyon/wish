"""The Amiga floppy filesystem, read and written (#36).

Enough of OFS -- the *Old File System*, which is what every Gold Box Amiga
release ships on -- and of FFS, the *Fast File System* a player can format a
save disk with, to **add a file to a real disk**: allocate blocks from the
bitmap, write them, build a file header, thread it into the parent directory's
hash chain, and fix every checksum the filesystem keeps.

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

The disk types
--------------
The fourth byte of the bootblock is the DOS type. Its low bit is FFS; the
rest says how names are kept: 0 standard, 2 international mode, 4 directory
cache and 6 long file names, both of which imply international mode.
The two file systems share every block but one: an FFS data block is 512
bytes of file with no header, so it has no checksum and no chain, and the
header's data-block table is the only way to it. International mode changes
only how a name is upper-cased for the hash and for comparing names.

* `DOS\\0` OFS and `DOS\\1` FFS, and `DOS\\2` and `DOS\\3`, the same two in
  international mode, are read and written.
* `DOS\\4` and `DOS\\5`, directory-cache OFS and FFS, are read through the hash
  tables, which the cache does not replace, and written: every add, replace
  and remove also edits the parent drawer's cache records, and a new drawer
  gets one empty cache block of its own. A cache that already disagrees with
  its hash table is reported by `cache_warnings()`, not by `verify()`, and a
  write into that drawer rebuilds its records from the hash table.
* `DOS\\6` and `DOS\\7`, long file names, are read and written. Every entry
  header keeps its name and comment as two length-prefixed strings in one
  112-byte field at 0x148, a comment that does not fit there in a type-64
  block named at 0x1B8, and its date at 0x1C4. The root keeps the standard
  layout and its 30-character name, and adds the DOS type at 0x1F0 and the
  count of blocks the bitmap marks used at 0x1D4, both of which every write
  rewrites; a root that disagrees with the bootblock or the bitmap is
  reported by `root_warnings()`, not by `verify()`. Wish writes names of up to
  106 characters, and replacing or removing a file gives back its comment
  block. The layout is from the
  `amiga-ffs` crate's `layout` module and amitools' `EntryBlock`, `RootBlock`
  and `CommentBlock`, which agree; no disk AmigaOS itself wrote has been
  read.

What this does not do
---------------------
* **A drawer is created only on a disk this module formatted:**
  `amiga_savegame.make_save_disk` gives a fresh save disk its `SAVE` drawer.
  A save written onto a copy of the player's own disk goes into the `SAVE`
  drawer already there.
* Comments, protection bits and the `.info` files Workbench keeps are not
  written. AmigaDOS does not need them and the game does not read them.
"""

from __future__ import annotations

import dataclasses
import datetime
import functools
import os
import pathlib
import struct
from typing import Iterator

__all__ = [
    "AmigaDiskError",
    "AmigaDiskTypeError",
    "BLOCK_SIZE",
    "FFS_DATA_SIZE",
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
#: Payload of one FFS data block: the whole block, with no header.
FFS_DATA_SIZE = BLOCK_SIZE
#: Data-block pointers a header or extension block can carry.
MAX_DATA_POINTERS = HASH_TABLE_SIZE

T_HEADER = 2
T_DATA = 8
T_LIST = 16
T_DIRCACHE = 33
T_COMMENT = 64
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
_HDR_PROTECT = BLOCK_SIZE - 192
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

#: A directory-cache block: the drawer it lists, how many records it holds,
#: the next block of the chain, its checksum, then the records.
_DC_PARENT = 0x008
_DC_COUNT = 0x00C
_DC_NEXT = 0x010
_DC_CHECKSUM = 0x014
_DC_RECORDS = 0x018
#: One record: header block, size, protection, user and group, date, the
#: secondary type, then a length-prefixed name and a length-prefixed comment,
#: padded to an even length.
_REC_SIZE = 4
_REC_DATE = 16
_REC_TYPE = 22
_REC_NAME = 23
_REC_FIXED = 25

#: Where a long-name disk keeps an entry header's name and comment, two
#: length-prefixed strings laid end to end; the block a comment that does not
#: fit there goes in; and the date, moved down to make room.
_LN_NAC = BLOCK_SIZE - 184
_LN_NAC_SIZE = 112
_LN_COMMENT_BLOCK = BLOCK_SIZE - 72
_LN_DAYS = BLOCK_SIZE - 60
#: A long-name root: the blocks its bitmap marks used, and its own DOS type.
_LN_ROOT_USED = BLOCK_SIZE - 44
_LN_ROOT_FS_TYPE = BLOCK_SIZE - 16
#: A comment block: the header it belongs to, and the comment.
_CB_HEADER = 0x008
_CB_CHECKSUM = 0x014

#: The longest name AmigaDOS stores in a header block.
MAX_NAME = 30
#: The longest entry name this module writes on a long-name disk. The
#: `amiga-ffs` crate and the AmigaOS wiki say 107 and Hyperion's AmigaOS
#: 3.1.4 FAQ says 106, so the lower. A longer name AmigaOS wrote still reads,
#: up to what the 112-byte field holds beside a comment's length byte.
MAX_LONG_NAME = 106

#: Flag bits of the DOS type, the bootblock's fourth byte.
DOSTYPE_FFS = 1
DOSTYPE_INTL = 2
DOSTYPE_DIRCACHE = 4
#: The DOS types with a directory cache, and with long file names.
DIRCACHE_DOS_TYPES = frozenset((4, 5))
LONG_NAME_DOS_TYPES = frozenset((6, 7))
#: The DOS types this module reads, and the ones it also writes.
READ_DOS_TYPES = frozenset(range(8))
WRITE_DOS_TYPES = frozenset(range(8))
#: What each DOS type is, for an error naming it.
DOS_TYPE_NAMES = {
    0: "OFS", 1: "FFS",
    2: "OFS, international", 3: "FFS, international",
    4: "OFS, directory cache", 5: "FFS, directory cache",
    6: "OFS, long file names", 7: "FFS, long file names",
}


class AmigaDiskError(ValueError):
    """A disk image this module will not read, or a write it will not make."""


class AmigaDiskTypeError(AmigaDiskError):
    """A disk whose DOS type this module does not read, or does not write.

    `dos_type` is the bootblock's fourth byte; `writing` says whether it was
    the write that was blocked, the disk itself having been read.
    """

    def __init__(self, dos_type: int, writing: bool) -> None:
        self.dos_type = dos_type
        self.writing = writing
        kind = DOS_TYPE_NAMES.get(dos_type)
        label = f"DOS\\{dos_type}" + (f" ({kind})" if kind else "")
        verb = "written" if writing else "read"
        super().__init__(f"disk type {label} cannot be {verb}")


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


def _upper_code(code: int, international: bool) -> int:
    """AmigaDOS's `toupper` for one Latin-1 code.

    Without international mode only `a`-`z` change. International mode also
    raises `0xE0`-`0xFE`, except `0xF7` (the division sign).
    """
    if 0x61 <= code <= 0x7A or (international and 0xE0 <= code <= 0xFE
                                and code != 0xF7):
        return code - 0x20
    return code


def upper_name(name: str, international: bool = False) -> str:
    """`name` upper-cased the way the filesystem compares names."""
    return "".join(chr(_upper_code(ord(char), international)) for char in name)


def hash_name(name: str, size: int = HASH_TABLE_SIZE,
              international: bool = False) -> int:
    """Which hash-table slot a directory entry belongs in.

    The standard hash is measured: it reproduces the slot the disk actually
    files the entry under for **76 of 76** entries on Pool of Radiance disk 1,
    across four directories. `international` is the `DOS\\2`-`DOS\\5` variant,
    which differs only in upper-casing `0xE0`-`0xFE`; no Gold Box file name
    leaves ASCII, where the two agree.
    """
    value = len(name)
    for char in name:
        value = ((value * 13) + _upper_code(ord(char), international)) & 0x7FF
    return value % size


def _all_or_nothing(method):
    """Put every byte back if the write raises part way through.

    A directory-cache write can find it needs a new cache block after the
    file's own blocks are taken; restoring the snapshot is what keeps a
    blocked write from leaving half its work behind.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        before = bytes(self._data)
        try:
            return method(self, *args, **kwargs)
        except BaseException:
            self._data[:] = before
            raise
    return wrapper


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
        if self.dos_type not in READ_DOS_TYPES:
            raise AmigaDiskTypeError(self.dos_type, writing=False)
        self.root = self._find_root()

    # -- construction -------------------------------------------------------
    @classmethod
    def open(cls, path: str | pathlib.Path) -> "AmigaDisk":
        return cls(pathlib.Path(path).read_bytes())

    @classmethod
    def blank(cls, name: str = "Empty", blocks: int = 1760,
              dos_type: int = 0) -> "AmigaDisk":
        """A freshly formatted disk, for a test that wants no game data.

        `blocks` is 1760 for a standard 880K floppy. The root goes in the
        middle block, which is where AmigaDOS puts it, and the bitmap in the
        block after. `dos_type` is 0 for OFS and 1 for FFS, or either plus 2
        for international mode, plus 4 for the directory cache, which gives
        the root one empty cache block, or plus 6 for long file names, which
        puts the DOS type in the root as well.
        """
        cls._check_name(name, MAX_NAME)
        if dos_type not in WRITE_DOS_TYPES:
            raise AmigaDiskTypeError(dos_type, writing=True)
        data = bytearray(blocks * BLOCK_SIZE)
        data[0:4] = b"DOS" + bytes([dos_type])
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
        if disk.dircache:
            disk._new_cache_block(root)
        disk._touch(root)
        disk._fix(root, _HDR_CHECKSUM)
        disk._fix_bitmap()
        return disk

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def save(self, path: str | pathlib.Path) -> None:
        """Write the image atomically, like a C64 disk image."""
        target = pathlib.Path(path)
        tmp = target.with_name(f".{target.name}.tmp{os.getpid()}")
        try:
            with open(tmp, "wb") as out:
                out.write(self._data)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

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

    # -- the structure of the disk ---------------------------------------------
    @property
    def block_count(self) -> int:
        return len(self._data) // BLOCK_SIZE

    @property
    def dos_type(self) -> int:
        """The bootblock's fourth byte: `DOS\\0` is 0, `DOS\\1` is 1."""
        return self._data[3]

    @property
    def ffs(self) -> bool:
        """The Fast File System bit of the bootblock's flags byte."""
        return bool(self.dos_type & DOSTYPE_FFS)

    @property
    def international(self) -> bool:
        """International mode, which the directory cache also implies."""
        return bool(self.dos_type & (DOSTYPE_INTL | DOSTYPE_DIRCACHE))

    @property
    def dircache(self) -> bool:
        """`DOS\\4` and `DOS\\5`. `DOS\\6` and `DOS\\7` have the same bit in
        their number and no cache."""
        return self.dos_type in DIRCACHE_DOS_TYPES

    @property
    def long_names(self) -> bool:
        """`DOS\\6` and `DOS\\7`, whose entry headers keep long names."""
        return self.dos_type in LONG_NAME_DOS_TYPES

    @property
    def max_name(self) -> int:
        """The longest file or drawer name this module writes on the disk."""
        return MAX_LONG_NAME if self.long_names else MAX_NAME

    @property
    def data_block_size(self) -> int:
        """File bytes one data block holds: 488 on OFS, 512 on FFS."""
        return FFS_DATA_SIZE if self.ffs else OFS_DATA_SIZE

    def _hash(self, name: str) -> int:
        return hash_name(name, international=self.international)

    def _same_name(self, one: str, other: str) -> bool:
        return (upper_name(one, self.international)
                == upper_name(other, self.international))

    def _check_writable(self) -> None:
        if self.dos_type not in WRITE_DOS_TYPES:
            raise AmigaDiskTypeError(self.dos_type, writing=True)

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

    def _start_walk(self, header: int | None,
                    seen: set[int] | None) -> set[int]:
        """The visited-drawer set, started at the drawer being walked."""
        if seen is None:
            seen = {self.root if header is None else header}
        return seen

    @staticmethod
    def _enter_dir(seen: set[int], block: int) -> None:
        """Block a drawer reached a second time."""
        if block in seen:
            raise AmigaDiskError(
                f"the directory tree returns to block {block}")
        seen.add(block)

    def walk(self, header: int | None = None, path: str = "",
             _seen: set[int] | None = None) -> Iterator[tuple[str, DirEntry]]:
        """Every file on the disk, as `(path, entry)`, depth first."""
        seen = self._start_walk(header, _seen)
        for entry in self.entries(header):
            here = f"{path}/{entry.name}"
            if entry.is_dir:
                self._enter_dir(seen, entry.block)
                yield from self.walk(entry.block, here, seen)
            else:
                yield here, entry

    def walk_dirs(self, header: int | None = None, path: str = "",
                  _seen: set[int] | None = None
                  ) -> Iterator[tuple[str, DirEntry]]:
        """Every drawer on the disk, as `(path, entry)`, depth first.

        The companion to :meth:`walk`, which yields only files -- and the
        reason this exists is that `verify()` had no way to reach a drawer's
        own header block. Before `make_dir` every directory on a disk this
        module wrote was the root, which `verify()` checks by hand, so the
        gap was invisible: a drawer with a wrong checksum verified clean.
        """
        seen = self._start_walk(header, _seen)
        for entry in self.entries(header):
            if not entry.is_dir:
                continue
            self._enter_dir(seen, entry.block)
            here = f"{path}/{entry.name}"
            yield here, entry
            yield from self.walk_dirs(entry.block, here, seen)

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
                if self._same_name(entry.name, part):
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
        seen = {header}
        while True:
            count = self._u32(current, _HDR_HIGH_SEQ)
            for index in range(count):
                number = self._u32(current, _HDR_DATA_TABLE - 4 * index)
                if self.ffs:
                    # No header to check, so the pointer itself is checked.
                    if self._not_ffs_data(number):
                        raise AmigaDiskError(
                            f"file header {header} names block {number} as "
                            f"file data")
                    out += self.block(number)
                    continue
                data = self.block(number)
                used = self._u32(data, _DAT_SIZE)
                if used > OFS_DATA_SIZE:
                    raise AmigaDiskError(
                        f"a data block claims {used} bytes of a "
                        f"{OFS_DATA_SIZE}-byte payload")
                out += data[_DAT_PAYLOAD:_DAT_PAYLOAD + used]
            extension = self._u32(current, _HDR_EXTENSION)
            if not extension:
                break
            if extension in seen:
                raise AmigaDiskError(
                    f"the extension chain of block {header} returns to "
                    f"block {extension}")
            seen.add(extension)
            current = self.block(extension)
        if len(out) < size:
            raise AmigaDiskError(
                f"the header says {size} bytes and the chain holds {len(out)}")
        return bytes(out[:size])

    def _not_ffs_data(self, number: int) -> bool:
        """A block an FFS data pointer cannot name: outside the disk, the
        bootblock, the root or the bitmap."""
        return (not FIRST_DATA_BLOCK <= number < self.block_count
                or number in (self.root, self._bitmap_block()))

    # -- the bitmap ---------------------------------------------------------
    #: Blocks one bitmap page can describe: its 127 usable longwords, in bits.
    BITMAP_CAPACITY = (BLOCK_SIZE - 4) * 8

    def _bitmap_block(self) -> int:
        """The one bitmap page, and only the first pointer is believed.

        A floppy never needs a second: one page carries 4064 bits against
        1758 data blocks. Real disks put junk in the later slots anyway --
        Pools of Darkness disk 2 names block 955 **twice** and disk 3 names
        1352 and 1360 -- so a reader that trusted them would block three
        genuine disks. A disk actually too big for one page is blocked.
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
        (`amiga/p36/shots/` in scratch, deleted; #36). Those blocks sit between the bitmap at
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
    def _check_name(name: str, limit: int) -> None:
        if not name:
            raise AmigaDiskError("an empty name")
        if len(name) > limit:
            raise AmigaDiskError(
                f"{name!r} is {len(name)} characters; this disk stores at most "
                f"{limit}")
        try:
            encoded = name.encode("latin1")
        except UnicodeEncodeError as exc:
            raise AmigaDiskError(f"{name!r} is not Amiga text") from exc
        for bad in b"/:":
            if bad in encoded:
                raise AmigaDiskError(
                    f"{name!r} contains {chr(bad)!r}, which separates a path")

    @_all_or_nothing
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
        self._check_writable()
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise AmigaDiskError("an empty path names nothing")
        name = parts[-1]
        self._check_name(name, self.max_name)
        parent = self.root
        for part in parts[:-1]:
            entry = self.lookup("/".join(parts[:parts.index(part) + 1]))
            if not entry.is_dir:
                raise AmigaDiskError(f"{part!r} is a file, not a drawer")
            parent = entry.block

        existing = None
        for entry in self.entries(parent):
            if self._same_name(entry.name, name):
                if entry.is_dir:
                    raise AmigaDiskError(
                        f"{name!r} is already a drawer on this disk")
                existing = entry
                break

        stale = self._stale_caches(parent)
        when = when or datetime.datetime.now()
        # An empty FFS file is a header alone, as the format describes; the
        # OFS writer gives an empty file one empty data block.
        blocks_needed = -(-len(data) // self.data_block_size)
        if not self.ffs:
            blocks_needed = max(1, blocks_needed)
        headers_needed = max(1, -(-blocks_needed // MAX_DATA_POINTERS))
        # Allocate the replacement before touching the old file, so a
        # failure leaves the disk exactly as it was: an existing file of the
        # same name is only unlinked once the new one's blocks are secured.
        # A consequence: the old file's own blocks are not up for reuse by
        # its own replacement, so a same-size replace that used to succeed
        # on a disk with no other room now fails instead of overwriting in
        # place (#36).
        old_blocks = (self._file_blocks(existing.block)
                      if existing is not None else [])
        allocated = self._allocate(blocks_needed + headers_needed)
        if existing is not None:
            self._unlink(parent, existing)
            self._free_blocks(old_blocks)
            if self.dircache:
                self._cache_remove(parent, existing.block)
        header = allocated[0]
        extensions = allocated[1:headers_needed]
        data_blocks = allocated[headers_needed:]

        self._write_data_chain(header, data, data_blocks)
        self._write_header(header, parent, name, data, data_blocks,
                           extensions, when)
        self._link(parent, header, name)
        self._touch(parent)
        self._fix(parent, _HDR_CHECKSUM)
        if self.dircache:
            self._cache_add(parent, header)
            self._cache_touch(parent)
            self._settle_caches(parent, stale)
        if parent != self.root:
            self._touch(self.root)
            self._fix(self.root, _HDR_CHECKSUM)
        self._fix_bitmap()
        return header

    @_all_or_nothing
    def make_dir(self, path: str,
                 when: datetime.datetime | None = None) -> int:
        """Create a drawer at `path` and return its block number.

        One block, no data chain: a `ST_USERDIR` header is a hash table and a
        name, which is why this is short where `write_file` is not.  The
        parent has to exist, and a name already in the parent is an error
        rather than a silent reuse -- a drawer that quietly turned out to be
        the file of the same name is the kind of thing that corrupts a disk
        two operations later.

        `amiga_savegame.make_save_disk` uses it to give a freshly formatted
        save disk its `SAVE` drawer; a save written onto a copy of the
        player's own disk goes into the drawer already there. The tests use
        it to exercise the writer on a disk with no game data anywhere.
        """
        self._check_writable()
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if not parts:
            raise AmigaDiskError("an empty path names nothing")
        name = parts[-1]
        self._check_name(name, self.max_name)
        parent = self.root
        if len(parts) > 1:
            entry = self.lookup("/".join(parts[:-1]))
            if not entry.is_dir:
                raise AmigaDiskError(
                    f"{parts[-2]!r} is a file, not a drawer")
            parent = entry.block
        for entry in self.entries(parent):
            if self._same_name(entry.name, name):
                raise AmigaDiskError(
                    f"{name!r} is already on this disk at block {entry.block}")

        stale = self._stale_caches(parent)
        header = self._allocate(1)[0]
        at = header * BLOCK_SIZE
        self._data[at:at + BLOCK_SIZE] = bytes(BLOCK_SIZE)
        struct.pack_into(">I", self._data, at + _HDR_TYPE, T_HEADER)
        struct.pack_into(">I", self._data, at + _HDR_KEY, header)
        self._put_entry_name(header, name)
        self._touch(header, when)
        struct.pack_into(">I", self._data, at + _HDR_PARENT, parent)
        struct.pack_into(">i", self._data, at + _HDR_SEC_TYPE, ST_USERDIR)
        self._fix(header, _HDR_CHECKSUM)
        if self.dircache:
            self._new_cache_block(header)

        self._link(parent, header, name)
        self._touch(parent)
        self._fix(parent, _HDR_CHECKSUM)
        if self.dircache:
            self._cache_add(parent, header)
            self._cache_touch(parent)
            self._settle_caches(parent, stale)
            self._settle_caches(header, set())
        if parent != self.root:
            self._touch(self.root)
            self._fix(self.root, _HDR_CHECKSUM)
        self._fix_bitmap()
        return header

    @_all_or_nothing
    def remove_file(self, path: str) -> None:
        """Unlink a file and give its blocks back to the bitmap."""
        self._check_writable()
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        entry = self.lookup(path)
        if entry.is_dir:
            raise AmigaDiskError(f"{path!r} is a drawer, not a file")
        parent = self.root
        if len(parts) > 1:
            parent = self.lookup("/".join(parts[:-1])).block
        blocks = self._file_blocks(entry.block)
        stale = self._stale_caches(parent)
        self._unlink(parent, entry)
        self._free_blocks(blocks)
        if self.dircache:
            self._cache_remove(parent, entry.block)
        self._touch(parent)
        self._fix(parent, _HDR_CHECKSUM)
        if self.dircache:
            self._cache_touch(parent)
            self._settle_caches(parent, stale)
        self._fix_bitmap()

    def _write_data_chain(self, header: int, data: bytes,
                          blocks: list[int]) -> None:
        if self.ffs:
            for index, number in enumerate(blocks):
                chunk = data[index * FFS_DATA_SIZE:(index + 1) * FFS_DATA_SIZE]
                at = number * BLOCK_SIZE
                self._data[at:at + BLOCK_SIZE] = chunk.ljust(BLOCK_SIZE, b"\0")
            return
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
                self._touch(number, when)
                self._put_entry_name(number, name)
                struct.pack_into(">I", self._data, at + _HDR_PARENT, parent)
            else:
                struct.pack_into(">I", self._data, at + _HDR_PARENT, header)
            self._fix(number, _HDR_CHECKSUM)

    def _link(self, parent: int, header: int, name: str) -> None:
        """Thread the header into its slot of the parent's hash chain.

        New entries go at the **head** of the chain, which is what AmigaDOS
        itself does and is why a directory listing is not in creation order.
        """
        slot = self._hash(name)
        at = parent * BLOCK_SIZE + _HDR_HASH_TABLE + 4 * slot
        first = struct.unpack_from(">I", self._data, at)[0]
        struct.pack_into(">I", self._data,
                         header * BLOCK_SIZE + _HDR_NEXT_HASH, first)
        struct.pack_into(">I", self._data, at, header)
        self._fix(header, _HDR_CHECKSUM)

    def _unlink(self, parent: int, entry: DirEntry) -> None:
        slot = self._hash(entry.name)
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
        self._free_blocks(self._file_blocks(header))

    def _free_blocks(self, blocks: list[int]) -> None:
        for number in blocks:
            self._set_free(number, True)

    def _file_blocks(self, header: int) -> list[int]:
        """Every block a file holds, its comment block included, blocking a
        looping extension chain."""
        blocks: list[int] = self._comment_blocks(header)
        seen: set[int] = set()
        current = header
        while current:
            if current in seen:
                raise AmigaDiskError(
                    f"the extension chain of block {header} returns to "
                    f"block {current}; nothing was changed")
            seen.add(current)
            block = self.block(current)
            for index in range(self._u32(block, _HDR_HIGH_SEQ)):
                blocks.append(self._u32(block, _HDR_DATA_TABLE - 4 * index))
            blocks.append(current)
            current = self._u32(block, _HDR_EXTENSION)
        return blocks

    # -- long file names ----------------------------------------------------
    def _comment_blocks(self, header: int) -> list[int]:
        """The comment block a long-name entry owns, as a list of none or one.

        Blocks a pointer at anything but a comment block naming `header`,
        because freeing it would free a block something else holds.
        """
        if not self.long_names:
            return []
        number = self._u32(self.block(header), _LN_COMMENT_BLOCK)
        if not number:
            return []
        fault = self._comment_block_fault(header, number)
        if fault:
            raise AmigaDiskError(fault + "; nothing was changed")
        return [number]

    def _comment_block_fault(self, header: int, number: int) -> str:
        """Why `number` is not `header`'s comment block, or empty."""
        if not FIRST_DATA_BLOCK <= number < self.block_count or number in (
                self.root, self._bitmap_block()):
            return f"block {header} names block {number} as its comment block"
        block = self.block(number)
        if (self._u32(block, _HDR_TYPE) != T_COMMENT
                or self._u32(block, _HDR_KEY) != number
                or self._u32(block, _CB_HEADER) != header):
            return (f"block {number}, named as the comment block of block "
                    f"{header}, is not that header's comment block")
        return ""

    def _put_entry_name(self, header: int, name: str) -> None:
        """Write `name` into an entry header with no comment, in the layout
        the disk's type uses."""
        encoded = name.encode("latin1")
        at = header * BLOCK_SIZE + (_LN_NAC if self.long_names else _HDR_NAME)
        self._data[at] = len(encoded)
        self._data[at + 1:at + 1 + len(encoded)] = encoded

    def _date_offset(self, header: int) -> int:
        """Where `header` keeps its date: moved on a long-name disk, except
        in the root."""
        if self.long_names and header != self.root:
            return _LN_DAYS
        return _HDR_DAYS

    # -- the directory cache ------------------------------------------------
    def _cache_chain(self, drawer: int) -> list[int]:
        """The drawer's cache blocks in chain order, from its `extension`."""
        chain: list[int] = []
        number = self._u32(self.block(drawer), _HDR_EXTENSION)
        while number:
            if number in chain:
                raise AmigaDiskError(
                    f"the directory cache of block {drawer} loops back to "
                    f"block {number}")
            block = self.block(number)
            if self._u32(block, _HDR_TYPE) != T_DIRCACHE:
                raise AmigaDiskError(
                    f"block {number} in the directory cache of block {drawer} "
                    f"is not a cache block")
            chain.append(number)
            number = self._u32(block, _DC_NEXT)
        return chain

    def _cache_records(self, number: int) -> list[bytes]:
        """One cache block's records, each as its padded bytes."""
        block = self.block(number)
        records: list[bytes] = []
        offset = _DC_RECORDS
        for _ in range(self._u32(block, _DC_COUNT)):
            if offset + _REC_FIXED > BLOCK_SIZE:
                raise AmigaDiskError(
                    f"directory cache block {number} counts more records than "
                    f"it holds")
            name_length = block[offset + _REC_NAME]
            comment_at = offset + _REC_NAME + 1 + name_length
            if comment_at >= BLOCK_SIZE:
                raise AmigaDiskError(
                    f"directory cache block {number} counts more records than "
                    f"it holds")
            size = (_REC_FIXED + name_length + block[comment_at] + 1) & ~1
            if offset + size > BLOCK_SIZE:
                raise AmigaDiskError(
                    f"directory cache block {number} counts more records than "
                    f"it holds")
            records.append(block[offset:offset + size])
            offset += size
        return records

    def _put_cache_records(self, number: int, records: list[bytes]) -> None:
        """Rewrite one cache block's records, keeping its links."""
        at = number * BLOCK_SIZE
        start = at + _DC_RECORDS
        self._data[start:at + BLOCK_SIZE] = bytes(BLOCK_SIZE - _DC_RECORDS)
        packed = b"".join(records)
        self._data[start:start + len(packed)] = packed
        struct.pack_into(">I", self._data, at + _DC_COUNT, len(records))
        self._fix(number, _DC_CHECKSUM)

    def _set_link(self, block: int, at: int, target: int) -> None:
        struct.pack_into(">I", self._data, block * BLOCK_SIZE + at, target)
        self._fix(block, _HDR_CHECKSUM)

    def _new_cache_block(self, drawer: int) -> int:
        """An empty cache block at the end of `drawer`'s chain."""
        chain = self._cache_chain(drawer)
        number = self._allocate(1)[0]
        at = number * BLOCK_SIZE
        self._data[at:at + BLOCK_SIZE] = bytes(BLOCK_SIZE)
        struct.pack_into(">I", self._data, at + _HDR_TYPE, T_DIRCACHE)
        struct.pack_into(">I", self._data, at + _HDR_KEY, number)
        struct.pack_into(">I", self._data, at + _DC_PARENT, drawer)
        self._fix(number, _DC_CHECKSUM)
        if chain:
            self._set_link(chain[-1], _DC_NEXT, number)
        else:
            self._set_link(drawer, _HDR_EXTENSION, number)
        return number

    def _cache_record(self, header: int) -> bytes:
        """The record that lists `header`, built from the header itself."""
        block = self.block(header)
        sec_type = self._i32(block, _HDR_SEC_TYPE)
        size = self._u32(block, _HDR_BYTE_SIZE) if sec_type == ST_FILE else 0
        days, minutes, ticks = struct.unpack_from(">III", block, _HDR_DAYS)
        name = block[_HDR_NAME + 1:_HDR_NAME + 1 + block[_HDR_NAME]]
        comment = block[_HDR_COMMENT + 1:
                        _HDR_COMMENT + 1 + block[_HDR_COMMENT]]
        record = (struct.pack(">IIIHHHHH", header, size,
                              self._u32(block, _HDR_PROTECT), 0, 0,
                              days, minutes, ticks)
                  + bytes([sec_type & 0xFF, len(name)]) + name
                  + bytes([len(comment)]) + comment)
        return record + b"\0" * (len(record) % 2)

    def _cache_add(self, drawer: int, header: int) -> None:
        """List `header` in the first cache block of `drawer` with room."""
        record = self._cache_record(header)
        for number in self._cache_chain(drawer):
            records = self._cache_records(number)
            if (_DC_RECORDS + sum(map(len, records)) + len(record)
                    <= BLOCK_SIZE):
                self._put_cache_records(number, records + [record])
                return
        self._put_cache_records(self._new_cache_block(drawer), [record])

    def _cache_remove(self, drawer: int, header: int) -> None:
        """Drop `header`'s record; a block left empty is unchained and freed,
        except the drawer's last one. A cache with no record of `header` was
        stale already, and is rebuilt from the hash table instead."""
        chain = self._cache_chain(drawer)
        for position, number in enumerate(chain):
            records = self._cache_records(number)
            kept = [r for r in records if self._u32(r, 0) != header]
            if len(kept) == len(records):
                continue
            if kept or len(chain) == 1:
                self._put_cache_records(number, kept)
                return
            following = self._u32(self.block(number), _DC_NEXT)
            if position == 0:
                self._set_link(drawer, _HDR_EXTENSION, following)
            else:
                self._set_link(chain[position - 1], _DC_NEXT, following)
            self._set_free(number, True)
            return
        self._rebuild_cache(drawer)

    def _cache_touch(self, drawer: int) -> None:
        """Copy a drawer's date into the record its own parent keeps,
        rebuilding the parent's cache first if it has no such record."""
        if drawer == self.root:
            return
        parent = self._u32(self.block(drawer), _HDR_PARENT)
        date = self.block(drawer)[_HDR_DAYS:_HDR_DAYS + 12]
        days, minutes, ticks = struct.unpack(">III", date)
        for attempt in range(2):
            for number in self._cache_chain(parent):
                records = self._cache_records(number)
                for index, record in enumerate(records):
                    if self._u32(record, 0) == drawer:
                        changed = bytearray(record)
                        struct.pack_into(">HHH", changed, _REC_DATE,
                                         days, minutes, ticks)
                        records[index] = bytes(changed)
                        self._put_cache_records(number, records)
                        return
            if attempt == 0:
                self._rebuild_cache(parent)
        raise AmigaDiskError(
            f"block {drawer} is not in the hash table of its parent, block "
            f"{parent}; nothing was written")

    @staticmethod
    def _record_agrees(record: bytes, want: bytes) -> bool:
        """Whether a cache record gives an entry the name, type and size its
        header does. Dates are not compared."""
        return not AmigaDisk._record_faults(record, want)

    @staticmethod
    def _record_faults(record: bytes, want: bytes) -> list[str]:
        return [what for what, start, end in (
                    ("name", _REC_NAME, _REC_NAME + 1 + want[_REC_NAME]),
                    ("type", _REC_TYPE, _REC_TYPE + 1),
                    ("size", _REC_SIZE, _REC_SIZE + 4))
                if record[start:end] != want[start:end]]

    def _rebuild_cache(self, drawer: int) -> None:
        """Rewrite `drawer`'s cache records from its hash table.

        A record that already gives an entry the right name, type and size is
        kept as it is; every other entry gets a record built from its header,
        and records for blocks not in the drawer are dropped. The chain keeps
        its blocks in order, gains one if the records need it, and gives back
        any it no longer needs except the first.
        """
        chain = self._cache_chain(drawer)
        have: dict[int, bytes] = {}
        for number in chain:
            for record in self._cache_records(number):
                have.setdefault(self._u32(record, 0), record)
        packed: list[list[bytes]] = [[]]
        used = _DC_RECORDS
        for entry in self.entries(drawer):
            want = self._cache_record(entry.block)
            record = have.get(entry.block)
            if record is None or not self._record_agrees(record, want):
                record = want
            if used + len(record) > BLOCK_SIZE:
                packed.append([])
                used = _DC_RECORDS
            packed[-1].append(record)
            used += len(record)
        while len(chain) < len(packed):
            chain.append(self._new_cache_block(drawer))
        if len(chain) > len(packed):
            self._set_link(chain[len(packed) - 1], _DC_NEXT, 0)
            for number in chain[len(packed):]:
                self._set_free(number, True)
        for number, records in zip(chain, packed):
            self._put_cache_records(number, records)

    def _cache_family(self, drawer: int) -> list[int]:
        """The drawers whose caches a write into `drawer` edits: its own,
        and its parent's, which lists it."""
        if drawer == self.root:
            return [drawer]
        return [drawer, self._u32(self.block(drawer), _HDR_PARENT)]

    def _stale_caches(self, drawer: int) -> set[int]:
        """Which of the caches a write into `drawer` edits disagree with
        their hash tables before the write."""
        if not self.dircache:
            return set()
        return {number for number in self._cache_family(drawer)
                if self._cache_mismatches("", number)}

    def _settle_caches(self, drawer: int, stale: set[int]) -> None:
        """After a write into `drawer`: rebuild a cache that was stale before
        it, and block the write if a cache it edited now disagrees with its
        hash table."""
        for number in self._cache_family(drawer):
            if number in stale and self._cache_mismatches("", number):
                self._rebuild_cache(number)
            faults = self._cache_mismatches(f"block {number}", number)
            if faults:
                raise AmigaDiskError(
                    "the write would leave the directory cache of block "
                    f"{number} disagreeing with its hash table ("
                    + "; ".join(faults) + "); nothing was written")

    # -- housekeeping -------------------------------------------------------
    def _touch(self, header: int,
               when: datetime.datetime | None = None) -> None:
        days, minutes, ticks = _amiga_date(when or datetime.datetime.now())
        struct.pack_into(">III", self._data,
                         header * BLOCK_SIZE + self._date_offset(header),
                         days, minutes, ticks)

    def _fix(self, block: int, at: int) -> None:
        start = block * BLOCK_SIZE
        struct.pack_into(">I", self._data, start + at, 0)
        struct.pack_into(">I", self._data, start + at,
                         block_checksum(self._data[start:start + BLOCK_SIZE],
                                        at))

    def _fix_bitmap(self) -> None:
        """Checksum the bitmap and, on a long-name disk, recount the root's
        used blocks, which every write that reaches here may have changed,
        and copy the bootblock's DOS type into the root."""
        self._fix(self._bitmap_block(), 0)
        if self.long_names:
            at = self.root * BLOCK_SIZE + _LN_ROOT_FS_TYPE
            self._data[at:at + 4] = self._data[0:4]
            struct.pack_into(">I", self._data,
                             self.root * BLOCK_SIZE + _LN_ROOT_USED,
                             self.used_count())
            self._fix(self.root, _HDR_CHECKSUM)

    def used_count(self) -> int:
        """Blocks the bitmap marks used, over the blocks it covers: the two
        boot blocks have no bit and are not counted."""
        return self.block_count - FIRST_DATA_BLOCK - self.free_count()

    @staticmethod
    def _u32(block: bytes, offset: int) -> int:
        return struct.unpack_from(">I", block, offset)[0]

    @staticmethod
    def _i32(block: bytes, offset: int) -> int:
        return struct.unpack_from(">i", block, offset)[0]

    def _name_of(self, header: int) -> str:
        block = self.block(header)
        at, limit = _HDR_NAME, MAX_NAME
        if self.long_names and header != self.root:
            # The name and the comment's length byte share the field.
            at, limit = _LN_NAC, _LN_NAC_SIZE - 2
        length = block[at]
        if length > limit:
            raise AmigaDiskError(
                f"block {header} claims a {length}-character name")
        return block[at + 1:at + 1 + length].decode("latin1")

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

        try:
            drawers = list(self.walk_dirs())
            files = list(self.walk())
        except AmigaDiskError as exc:
            problems.append(str(exc))
            return problems

        for where, entry in drawers:
            check(entry.block, _HDR_CHECKSUM, f"the drawer {where!r} at block")
            if self.is_free(entry.block):
                problems.append(
                    f"block {entry.block} holds the drawer {where!r} and is "
                    f"marked free in the bitmap")

        if self.long_names:
            for _, entry in drawers + files:
                problems.extend(self._verify_comment(entry.block, check))

        if self.dircache:
            for where, number in [("/", self.root)] + [
                    (where, entry.block) for where, entry in drawers]:
                problems.extend(self._verify_cache_chain(where, number, check))

        for _, entry in files:
            current = entry.block
            head = True
            chain = set()
            while current:
                if current in chain:
                    problems.append(
                        f"the extension chain of block {entry.block} loops "
                        f"back to block {current}")
                    break
                chain.add(current)
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
                    # An FFS data block is all file: nothing to sum, so the
                    # pointer is checked the way `read_file` checks it.
                    if self.ffs and self._not_ffs_data(number):
                        problems.append(
                            f"file header {entry.block} names block {number} "
                            f"as file data")
                        continue
                    if not self.ffs:
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

    def root_warnings(self) -> list[str]:
        """Where a long-name root disagrees with the rest of the disk: a DOS
        type at 0x1F0 other than the bootblock's, or a count of used blocks
        at 0x1D4 other than what the bitmap marks. Empty on any other disk
        type.

        Kept apart from :meth:`verify` because no disk AmigaOS wrote has been
        read, so whether AmigaOS keeps either field exact is unknown, and a
        player's disk as it came must not fail on it; every write rewrites
        both.
        """
        if not self.long_names:
            return []
        warnings: list[str] = []
        root = self.block(self.root)
        stored = bytes(root[_LN_ROOT_FS_TYPE:_LN_ROOT_FS_TYPE + 4])
        if stored != bytes(self._data[0:4]):
            warnings.append(
                f"the root block gives the DOS type as {stored!r}, and the "
                f"bootblock as {bytes(self._data[0:4])!r}")
        used = self._u32(root, _LN_ROOT_USED)
        if used != self.used_count():
            warnings.append(
                f"the root block counts {used} used blocks and the bitmap "
                f"marks {self.used_count()}")
        return warnings

    def _verify_comment(self, header: int, check) -> list[str]:
        """A long-name entry's comment: within its field, and any comment
        block summed, its own, and in use."""
        problems: list[str] = []
        block = self.block(header)
        name_length = block[_LN_NAC]
        comment_length = block[_LN_NAC + 1 + name_length]
        if name_length + comment_length + 2 > _LN_NAC_SIZE:
            problems.append(
                f"block {header} gives a name and comment longer than their "
                f"{_LN_NAC_SIZE}-byte field")
        number = self._u32(block, _LN_COMMENT_BLOCK)
        if not number:
            return problems
        fault = self._comment_block_fault(header, number)
        if fault:
            problems.append(fault)
            return problems
        check(number, _CB_CHECKSUM, "comment block")
        if self.is_free(number):
            problems.append(
                f"comment block {number} is in use and marked free")
        return problems

    def _verify_cache_chain(self, where: str, drawer: int,
                            check) -> list[str]:
        """The directory-cache blocks of one drawer: summed, typed, in use,
        and holding the records they count. What the records say is
        :meth:`cache_warnings`'s business."""
        problems: list[str] = []
        number = self._u32(self.block(drawer), _HDR_EXTENSION)
        seen: set[int] = set()
        while number:
            if number in seen:
                problems.append(
                    f"the directory cache of {where!r} loops back to block "
                    f"{number}")
                break
            seen.add(number)
            try:
                block = self.block(number)
            except AmigaDiskError as exc:
                problems.append(str(exc))
                break
            if self._u32(block, _HDR_TYPE) != T_DIRCACHE:
                problems.append(
                    f"block {number} in the directory cache of {where!r} is "
                    f"not a cache block")
                break
            check(number, _HDR_CHECKSUM, "directory cache block")
            try:
                self._cache_records(number)
            except AmigaDiskError as exc:
                problems.append(str(exc))
            if self.is_free(number):
                problems.append(
                    f"directory cache block {number} is in use and marked "
                    f"free")
            number = self._u32(block, _HDR_FIRST_DATA)
        return problems

    def cache_warnings(self) -> list[str]:
        """Where a directory cache lists something other than its drawer's
        hash table holds: a record with the wrong name, type or size, an entry
        with no record, a record for a block not in the drawer, or one listed
        twice. Empty on a disk with no cache.

        Kept apart from :meth:`verify` because AmigaDOS finds a file through
        the hash tables and not the cache, so a stale listing on a disk as it
        came is not damage a save should stop for; a write rebuilds the cache
        of the drawer it writes to. Dates are not compared. A cache too
        broken to read is :meth:`verify`'s to report.
        """
        if not self.dircache:
            return []
        try:
            drawers = [("/", self.root)] + [
                (where, entry.block) for where, entry in self.walk_dirs()]
        except AmigaDiskError:
            return []
        warnings: list[str] = []
        for where, drawer in drawers:
            try:
                warnings.extend(self._cache_mismatches(where, drawer))
            except AmigaDiskError:
                continue
        return warnings

    def _cache_mismatches(self, where: str, drawer: int) -> list[str]:
        """One drawer's :meth:`cache_warnings`; raises on a cache it cannot
        read."""
        records = [record for number in self._cache_chain(drawer)
                   for record in self._cache_records(number)]
        listed = {self._u32(record, 0): record for record in records}
        problems: list[str] = []
        if len(listed) != len(records):
            problems.append(
                f"the directory cache of {where!r} lists an entry twice")
        for entry in self.entries(drawer):
            record = listed.pop(entry.block, None)
            if record is None:
                problems.append(
                    f"{entry.name!r} in {where!r} has no record in the "
                    f"directory cache")
                continue
            for what in self._record_faults(record,
                                            self._cache_record(entry.block)):
                problems.append(
                    f"the directory cache of {where!r} gives "
                    f"{entry.name!r} the wrong {what}")
        for block in listed:
            problems.append(
                f"the directory cache of {where!r} lists block {block}, which "
                f"is not in the drawer")
        return problems

    def _recompute(self, block: int, at: int) -> int:
        start = block * BLOCK_SIZE
        copy = bytearray(self._data[start:start + BLOCK_SIZE])
        struct.pack_into(">I", copy, at, 0)
        return block_checksum(copy, at)
