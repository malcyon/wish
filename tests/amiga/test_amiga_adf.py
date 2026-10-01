from __future__ import annotations

"""`goldbox.amiga_adf` -- the Amiga filesystem, read and written (#36).

The reader is checked against **the player's own disks**, because a
filesystem reader that agrees with itself proves nothing: every real Amiga
disk on the machine has to `verify()` clean before anything here writes one.
`$AMIGA_DISKS` names a directory of **game** disks -- it is searched
recursively, so pointing it at a scratch directory full of half-written images
makes these fail for the wrong reason -- and the tests that need them skip
without it.

The writer is checked on a **blank disk this module formats**, so those tests
need no game data at all, and then on a copy of a real one.

What the tests cannot do is what the emulator did: a disk this file called
clean was rejected by Kickstart with `Not a DOS disk in unit 0`, because the
checksum was being written one longword low and `verify()` was comparing a
field that held zero on both sides. Hence :meth:`AmigaDisk.block_sum` and
`test_a_block_with_its_checksum_in_the_wrong_field_is_caught`.
"""


import datetime
import os
import pathlib
import struct

import pytest

from goldbox.amiga_adf import (
    BLOCK_SIZE,
    FFS_DATA_SIZE,
    HASH_TABLE_SIZE,
    OFS_DATA_SIZE,
    AmigaDisk,
    AmigaDiskError,
    AmigaDiskTypeError,
    block_checksum,
    hash_name,
    upper_name,
)

WHEN = datetime.datetime(1991, 6, 4, 12, 34, 56)


#: The Amiga ROM library roots, `gamedisks.yaml`'s `amiga` entry (#212). These
#: four skipped here for months against images that were on the disk the whole
#: time -- `#211 (103 tests skip on the machine that has the game files, and
#: the game files are not why)`. `tests/gamedata.py` does the same for the C64
#: disks.
AMIGA_KEY = "amiga"

#: The Gold Box titles, as the directories under those roots are named.
#: **The root is a whole Amiga library, not a Gold Box folder**, so scanning it
#: whole picks up Lemmings -- which is a bootable disk with no AmigaDOS
#: filesystem on it, and reading it fails correctly. That is not a fault in the
#: reader and must not be asserted against.
AMIGA_GAMES = ("Curse_Of_The_Azure_Bonds", "Secret_Of_The_Silver_Blades",
               "Pool_Of_Radiance", "Pools_Of_Darkness")


def amiga_dirs() -> list[pathlib.Path]:
    """The directories holding Amiga Gold Box images, `$AMIGA_DISKS` first.

    `$AMIGA_DISKS` is taken whole and is the caller's business to scope; the
    defaults are narrowed to the game directories, because their roots hold
    every Amiga disk on the machine.
    """
    from automap import gamedisks
    where = os.environ.get("AMIGA_DISKS")
    if where:
        return [pathlib.Path(where)]
    roots = gamedisks.candidates(AMIGA_KEY)
    return [root / name for root in roots for name in AMIGA_GAMES
            if (root / name).is_dir()]


def real_disks() -> list[pathlib.Path]:
    from automap import gamedisks
    where = amiga_dirs()
    if not where:
        pytest.skip(
            "no Amiga Gold Box disks; set $AMIGA_DISKS, or put them under "
            + " or ".join(str(p) for p in gamedisks.candidates(AMIGA_KEY)))
    found = sorted(p for d in where for p in d.rglob("*.adf") if p.is_file())
    if not found:
        pytest.skip("no .adf under " + ", ".join(str(p) for p in where))
    return found


# ---------------------------------------------------------------------------
# The pieces, against the numbers they were measured from
# ---------------------------------------------------------------------------
def test_a_valid_block_sums_to_zero():
    """The invariant the filesystem enforces, on a block we build."""
    block = bytearray(BLOCK_SIZE)
    struct.pack_into(">I", block, 0, 2)
    struct.pack_into(">I", block, BLOCK_SIZE - 4, 1)
    struct.pack_into(">I", block, 20, block_checksum(block, 20))
    total = sum(struct.unpack_from(">I", block, o)[0]
                for o in range(0, BLOCK_SIZE, 4)) & 0xFFFFFFFF
    assert total == 0


def test_the_hash_is_case_insensitive_and_in_range():
    for name in ("CHRDATA1.sav", "chrdata1.SAV", "savgamA.dat", "X"):
        assert 0 <= hash_name(name) < HASH_TABLE_SIZE
    assert hash_name("GARWAN.cha") == hash_name("garwan.CHA")


# ---------------------------------------------------------------------------
# The reader, against the player's own disks
# ---------------------------------------------------------------------------
def test_every_real_disk_verifies_clean():
    """The reader has to agree with seven real filesystems before the writer
    is allowed to touch one. This is what makes `verify()` mean something."""
    for path in real_disks():
        disk = AmigaDisk.open(path)
        assert disk.verify() == [], (path.name, disk.verify()[:3])


def test_every_real_disk_reads_every_file_to_its_stated_length():
    for path in real_disks():
        disk = AmigaDisk.open(path)
        seen = 0
        for name, entry in disk.walk():
            data = disk.read_file(name)
            size = struct.unpack_from(">I", disk.block(entry.block),
                                      BLOCK_SIZE - 188)[0]
            assert len(data) == size, (path.name, name)
            seen += 1
        assert seen, path.name


def test_a_file_that_is_not_there_is_refused_by_name():
    for path in real_disks():
        disk = AmigaDisk.open(path)
        with pytest.raises(AmigaDiskError):
            disk.read_file("NOT/A/FILE")
        return


# ---------------------------------------------------------------------------
# The writer, on a disk this module formats
# ---------------------------------------------------------------------------
def test_a_blank_disk_is_a_consistent_filesystem():
    disk = AmigaDisk.blank("wishtest")
    assert disk.volume_name == "wishtest"
    assert disk.verify() == []
    assert list(disk.walk()) == []
    # 1760 blocks less the bootblock's two, the root and the bitmap.
    assert disk.free_count() == 1760 - 4


def test_a_written_file_reads_back_byte_for_byte():
    disk = AmigaDisk.blank()
    payload = bytes(range(256)) * 7 + b"tail"
    disk.write_file("PARTY.cha", payload, when=WHEN)
    assert disk.verify() == []
    assert disk.read_file("PARTY.cha") == payload


def test_a_file_longer_than_one_header_can_index_still_round_trips():
    """72 data-block pointers fit in a header; past that it needs an
    extension block, and 51200 bytes is 105 blocks."""
    disk = AmigaDisk.blank()
    payload = bytes(range(256)) * 200
    assert len(payload) // OFS_DATA_SIZE > HASH_TABLE_SIZE
    disk.write_file("BIG.BIN", payload, when=WHEN)
    assert disk.verify() == []
    assert disk.read_file("BIG.BIN") == payload


def test_an_extension_chain_that_loops_is_refused_rather_than_followed_forever():
    """A crafted image whose extension block names itself would otherwise be
    walked for ever."""
    disk = AmigaDisk.blank()
    disk.write_file("BIG.BIN", bytes(range(256)) * 200, when=WHEN)
    header = disk.lookup("BIG.BIN").block
    extension = struct.unpack_from(">I", disk.block(header),
                                   BLOCK_SIZE - 8)[0]
    assert extension
    struct.pack_into(">I", disk._data, extension * BLOCK_SIZE + BLOCK_SIZE - 8,
                     extension)
    with pytest.raises(AmigaDiskError, match="extension chain"):
        disk.read_file("BIG.BIN")


def test_an_empty_file_round_trips():
    disk = AmigaDisk.blank()
    disk.write_file("EMPTY", b"", when=WHEN)
    assert disk.verify() == []
    assert disk.read_file("EMPTY") == b""


def test_removing_a_file_gives_every_block_back():
    disk = AmigaDisk.blank()
    free = disk.free_count()
    disk.write_file("GONE", bytes(5000), when=WHEN)
    assert disk.free_count() < free
    disk.remove_file("GONE")
    assert disk.free_count() == free
    assert disk.verify() == []
    assert list(disk.walk()) == []


def test_writing_over_a_file_replaces_it_rather_than_doubling_it():
    disk = AmigaDisk.blank()
    disk.write_file("SAME", b"first version", when=WHEN)
    free = disk.free_count()
    disk.write_file("SAME", b"second", when=WHEN)
    assert [name for name, _ in disk.walk()] == ["/SAME"]
    assert disk.read_file("SAME") == b"second"
    assert disk.free_count() == free
    assert disk.verify() == []


def test_many_files_in_one_directory_thread_their_hash_chains():
    """Two names in one hash slot have to chain, and both have to survive
    the other being removed. 72 slots and 200 names guarantees collisions."""
    disk = AmigaDisk.blank()
    names = [f"CHAR{n:03d}.cha" for n in range(200)]
    for name in names:
        disk.write_file(name, name.encode(), when=WHEN)
    assert disk.verify() == []
    assert sorted(p.lstrip("/") for p, _ in disk.walk()) == sorted(names)
    for name in names[::2]:
        disk.remove_file(name)
    assert disk.verify() == []
    assert sorted(p.lstrip("/") for p, _ in disk.walk()) == sorted(names[1::2])
    for name in names[1::2]:
        assert disk.read_file(name) == name.encode()


def test_a_full_disk_is_refused_and_leaves_the_disk_alone():
    disk = AmigaDisk.blank()
    disk.write_file("KEEP", b"keep me", when=WHEN)
    free = disk.free_count()
    with pytest.raises(AmigaDiskError, match="nothing was written"):
        disk.write_file("TOOBIG", bytes(OFS_DATA_SIZE * (free + 10)), when=WHEN)
    assert disk.free_count() == free
    assert disk.verify() == []
    assert disk.read_file("KEEP") == b"keep me"


def _data_blocks_for_total(total_blocks: int,
                           max_pointers: int = HASH_TABLE_SIZE) -> int:
    """The data-block count whose data-plus-header total is `total_blocks`.

    Inverts `blocks_needed + headers_needed`, so a test can ask for an
    allocation of an exact size without hardcoding the disk's block count.
    """
    headers = 1
    while True:
        data = total_blocks - headers
        if data <= 0:
            raise ValueError(f"{total_blocks} is too small for any header")
        needed = max(1, -(-data // max_pointers))
        if needed == headers:
            return data
        headers = needed


def test_a_failed_replacement_leaves_the_original_file_readable():
    """The docstring's promise: the old file is only unlinked once the new
    one's blocks are secured, so a replacement that cannot fit leaves the
    original exactly as it was.

    The replacement is sized to need exactly one block more than is
    currently free -- which the old, buggy order would have satisfied by
    freeing `KEEP.cha` first, and the fixed order must not."""
    disk = AmigaDisk.blank()
    original = b"original bytes"
    disk.write_file("KEEP.cha", original, when=WHEN)
    free = disk.free_count()
    data_blocks = _data_blocks_for_total(free + 1)
    payload = bytes(OFS_DATA_SIZE * data_blocks)
    with pytest.raises(AmigaDiskError, match="nothing was written"):
        disk.write_file("KEEP.cha", payload, when=WHEN)
    assert disk.free_count() == free
    assert [name for name, _ in disk.walk()] == ["/KEEP.cha"]
    assert disk.read_file("KEEP.cha") == original
    assert disk.verify() == []


@pytest.mark.parametrize("name", ["", "x" * 31, "with/slash", "with:colon"])
def test_a_name_amigados_cannot_store_is_refused_by_name(name):
    disk = AmigaDisk.blank()
    with pytest.raises(AmigaDiskError):
        disk.write_file(name, b"x", when=WHEN)


def test_a_block_with_its_checksum_in_the_wrong_field_is_caught():
    """The regression the emulator found.

    Put a self-consistent checksum in the longword **before** the one
    AmigaDOS reads it from. The block still sums to zero, so a sum-only test
    passes -- and so does a "recompute the checksum" test, because the field
    it compares now holds zero on both sides. That is exactly how the first
    version of this module called a disk clean that Kickstart rejected with
    `Not a DOS disk in unit 0`.

    What catches it is a structural invariant instead: the longword the
    checksum landed on is `first_data`, which has to name the same block as
    the first entry of the data table -- true on **211 of 211** files across
    the four real Amiga disks.
    """
    disk = AmigaDisk.blank()
    disk.write_file("VICTIM", b"payload", when=WHEN)
    header = disk.lookup("VICTIM").block
    raw = bytearray(disk.block(header))
    good = struct.unpack_from(">I", raw, 0x014)[0]
    struct.pack_into(">I", raw, 0x014, 0)
    struct.pack_into(">I", raw, 0x010, block_checksum(raw, 0x010))
    broken = AmigaDisk(disk.to_bytes()[:header * BLOCK_SIZE] + bytes(raw)
                       + disk.to_bytes()[(header + 1) * BLOCK_SIZE:])
    assert broken.block_sum(header) == 0, "the sum-only test would pass"
    assert good != 0
    assert any("first data block" in p for p in broken.verify()), broken.verify()


def test_a_root_block_with_its_checksum_in_the_wrong_field_is_caught():
    """The same fault as above, on the root block instead of a file header.

    The old `verify()` only ran the structural first-data check inside the
    `walk()` loop, so a root block with its checksum one longword low --
    the reserved word at 0x010 -- was caught by nothing but the vacuous
    sum-and-declared-offset check. That reserved word is otherwise always
    zero, so it is what catches this instead (#36 code review).
    """
    disk = AmigaDisk.blank()
    raw = bytearray(disk.block(disk.root))
    good = struct.unpack_from(">I", raw, 0x014)[0]
    struct.pack_into(">I", raw, 0x014, 0)
    struct.pack_into(">I", raw, 0x010, block_checksum(raw, 0x010))
    broken = AmigaDisk(disk.to_bytes()[:disk.root * BLOCK_SIZE] + bytes(raw)
                       + disk.to_bytes()[(disk.root + 1) * BLOCK_SIZE:])
    assert broken.block_sum(disk.root) == 0, "the sum-only test would pass"
    assert good != 0
    assert any("reserved word" in p for p in broken.verify()), broken.verify()


def test_a_bitmap_block_with_its_checksum_in_the_wrong_field_is_caught():
    """The bitmap block's own version of the same fault.

    Its checksum has nowhere to go but *up* a longword, into the first word
    of bitmap data -- the bits for blocks 2 through 33. On a disk small
    enough that the root and bitmap blocks' own bits live in that word (as
    they do here), the fault does not just hide a bad checksum: it reports
    two blocks the filesystem is using as free. `verify()` used to call this
    clean (#36 code review).
    """
    disk = AmigaDisk.blank("t", blocks=64)
    bitmap = disk.root + 1
    raw = bytearray(disk.block(bitmap))
    good = struct.unpack_from(">I", raw, 0x000)[0]
    struct.pack_into(">I", raw, 0x000, 0)
    struct.pack_into(">I", raw, 0x004, block_checksum(raw, 0x004))
    broken = AmigaDisk(disk.to_bytes()[:bitmap * BLOCK_SIZE] + bytes(raw)
                       + disk.to_bytes()[(bitmap + 1) * BLOCK_SIZE:])
    assert broken.block_sum(bitmap) == 0, "the sum-only test would pass"
    assert good != 0
    assert any("marked free" in p for p in broken.verify()), broken.verify()


def test_a_short_or_unaligned_image_is_refused_by_name():
    with pytest.raises(AmigaDiskError):
        AmigaDisk(b"DOS\x00" + bytes(100))
    with pytest.raises(AmigaDiskError):
        AmigaDisk(bytes(BLOCK_SIZE * 4))          # no DOS signature


@pytest.mark.parametrize("dos_type", [8, 0xFF])
def test_a_disk_type_this_module_does_not_read_is_refused_by_type(dos_type):
    """Anything past `DOS\\7` is no AmigaDOS type at all."""
    data = bytearray(AmigaDisk.blank().to_bytes())
    data[3] = dos_type
    with pytest.raises(AmigaDiskTypeError) as caught:
        AmigaDisk(data)
    assert caught.value.dos_type == dos_type
    assert caught.value.writing is False


# ---------------------------------------------------------------------------
# The writer, on a copy of a real game disk
# ---------------------------------------------------------------------------
def test_adding_a_file_to_a_real_disk_leaves_every_other_file_alone():
    """The whole point: hand a player a disk with their party on it.

    Two independent checks -- every existing file still reads back byte for
    byte, and the filesystem still verifies. The player's own image is opened
    read-only and never written; everything happens in memory.
    """
    for path in real_disks():
        disk = AmigaDisk.open(path)
        before = {name: disk.read_file(name) for name, _ in disk.walk()}
        if disk.free_count() < 8:
            continue
        target = None
        for name, entry in disk.walk():
            parent = name.rsplit("/", 1)[0]
            if parent:
                target = f"{parent}/WISHTST.cha"
                break
        if target is None:
            target = "WISHTST.cha"
        payload = bytes(range(256)) + b"party"
        disk.write_file(target, payload, when=WHEN)
        assert disk.verify() == [], path.name
        after = {name: disk.read_file(name) for name, _ in disk.walk()}
        assert {k: v for k, v in after.items() if k in before} == before, path.name
        assert after[target] == payload
        return
    pytest.skip("no disk under $AMIGA_DISKS has room for a test file")


def test_allocation_stays_away_from_the_front_of_the_disk():
    """A cracked release reads blocks the bitmap says are free.

    Measured under WinUAE (#36, `amiga/p36/shots/` in scratch, deleted): one small file in
    Pool of Radiance disk 1's lowest free blocks boots; a second, which takes
    992 and 993, hangs the boot with every checksum right and no existing
    file touched. So the allocator counts down from the top, and this is what
    keeps it that way.
    """
    disk = AmigaDisk.blank()
    disk.write_file("HIGH", b"x", when=WHEN)
    used = [b for b in range(2, disk.block_count) if not disk.is_free(b)]
    header = disk.lookup("HIGH").block
    assert header > disk.block_count * 3 // 4, (header, used[:5])


# ---------------------------------------------------------------------------
# Drawers (#109)
# ---------------------------------------------------------------------------
#
# `make_dir` exists so a save slot can be written onto a disk this module
# formatted, with no game data anywhere. Production never calls it: a
# converted party lands in the `save` drawer of a copy of the player's own
# game disk.


def test_a_new_drawer_is_a_consistent_filesystem():
    disk = AmigaDisk.blank("wishtest")
    block = disk.make_dir("save", when=WHEN)
    assert disk.verify() == []
    entry = disk.lookup("save")
    assert entry.is_dir and entry.block == block


def test_a_file_written_into_a_new_drawer_reads_back():
    disk = AmigaDisk.blank("wishtest")
    disk.make_dir("save", when=WHEN)
    payload = bytes(range(256)) * 3
    disk.write_file("save/CHRDATA1.sav", payload, when=WHEN)
    assert disk.read_file("/save/CHRDATA1.sav") == payload
    assert [p for p, _ in disk.walk()] == ["/save/CHRDATA1.sav"]
    assert disk.verify() == []


def test_a_drawer_inside_a_drawer_works():
    disk = AmigaDisk.blank("wishtest")
    disk.make_dir("outer", when=WHEN)
    disk.make_dir("outer/inner", when=WHEN)
    disk.write_file("outer/inner/FILE", b"payload", when=WHEN)
    assert disk.read_file("outer/inner/FILE") == b"payload"
    assert disk.verify() == []


def test_a_drawer_over_a_name_already_there_is_refused():
    """Quietly returning the file of the same name is how a disk gets
    corrupted two operations later."""
    disk = AmigaDisk.blank("wishtest")
    disk.write_file("save", b"not a drawer", when=WHEN)
    with pytest.raises(AmigaDiskError):
        disk.make_dir("save", when=WHEN)
    disk.make_dir("other", when=WHEN)
    with pytest.raises(AmigaDiskError):
        disk.make_dir("other", when=WHEN)


def test_a_drawer_under_a_file_is_refused():
    disk = AmigaDisk.blank("wishtest")
    disk.write_file("FILE", b"x", when=WHEN)
    with pytest.raises(AmigaDiskError):
        disk.make_dir("FILE/under", when=WHEN)


def test_a_drawer_takes_exactly_one_block():
    disk = AmigaDisk.blank("wishtest")
    before = disk.free_count()
    disk.make_dir("save", when=WHEN)
    assert disk.free_count() == before - 1


def _looping_big_file(tmp_path):
    """A disk holding a file whose extension block names itself."""
    disk = AmigaDisk.blank()
    disk.write_file("BIG.BIN", bytes(range(256)) * 200, when=WHEN)
    header = disk.lookup("BIG.BIN").block
    extension = struct.unpack_from(">I", disk.block(header),
                                   BLOCK_SIZE - 8)[0]
    assert extension
    struct.pack_into(">I", disk._data, extension * BLOCK_SIZE + BLOCK_SIZE - 8,
                     extension)
    path = tmp_path / "loop.adf"
    disk.save(str(path))
    return AmigaDisk.open(str(path))


def test_removing_a_file_whose_extension_chain_loops_is_refused_and_changes_nothing(
        tmp_path):
    disk = _looping_big_file(tmp_path)
    before = bytes(disk._data)
    with pytest.raises(AmigaDiskError, match="extension chain"):
        disk.remove_file("BIG.BIN")
    assert bytes(disk._data) == before


def test_writing_over_a_file_whose_extension_chain_loops_is_refused_and_changes_nothing(
        tmp_path):
    disk = _looping_big_file(tmp_path)
    before = bytes(disk._data)
    with pytest.raises(AmigaDiskError, match="extension chain"):
        disk.write_file("BIG.BIN", b"new", when=WHEN)
    assert bytes(disk._data) == before


def test_verify_reports_an_extension_chain_that_loops_and_returns(tmp_path):
    disk = _looping_big_file(tmp_path)
    problems = disk.verify()
    assert sum("extension chain" in p and "loops" in p for p in problems) == 1


def test_a_directory_tree_that_loops_is_refused_by_walk(tmp_path):
    disk = AmigaDisk.blank()
    disk.make_dir("SAVE")
    drawer = disk.lookup("SAVE").block
    # The drawer's hash table points back at the root.
    struct.pack_into(">I", disk._data, drawer * BLOCK_SIZE + 24, disk.root)
    with pytest.raises(AmigaDiskError, match="directory tree"):
        list(disk.walk())
    with pytest.raises(AmigaDiskError, match="directory tree"):
        list(disk.walk_dirs())


def test_verify_reports_a_directory_tree_that_loops_and_returns():
    disk = AmigaDisk.blank()
    disk.make_dir("SAVE")
    drawer = disk.lookup("SAVE").block
    struct.pack_into(">I", disk._data, drawer * BLOCK_SIZE + 24, disk.root)
    problems = disk.verify()
    assert sum("directory tree" in p for p in problems) == 1


# ---------------------------------------------------------------------------
# The Fast File System and international mode (#809)
# ---------------------------------------------------------------------------
#
# An FFS disk differs from OFS only in its data blocks: 512 bytes of file, no
# header, no checksum, no chain. International mode differs only in how a name
# is upper-cased. These tests build every image at run time; the reference
# image below is laid out from the format description by code that shares
# nothing with the module under test.

FFS_TYPES = (1, 3, 5, 7)
WRITABLE_TYPES = (0, 1, 2, 3, 4, 5, 6, 7)
DIRCACHE_TYPES = (4, 5)
LONG_NAME_TYPES = (6, 7)


def _spec_sum(block: bytes, at: int) -> int:
    total = 0
    for offset in range(0, BLOCK_SIZE, 4):
        if offset != at:
            total += struct.unpack_from(">I", block, offset)[0]
    return -total & 0xFFFFFFFF


def _spec_upper(code: int, international: bool) -> int:
    if ord("a") <= code <= ord("z"):
        return code - 32
    if international and 224 <= code <= 254 and code != 247:
        return code - 32
    return code


def _spec_hash(name: bytes, international: bool) -> int:
    value = len(name)
    for code in name:
        value = (value * 13 + _spec_upper(code, international)) & 0x7FF
    return value % 72


def _spec_ffs_image(files: dict[str, bytes], dos_type: int = 1) -> bytes:
    """An FFS floppy holding `files` in its root, laid out by the format
    description alone: root 880, bitmap 881, then each file's header, its
    extension blocks and its raw 512-byte data blocks in ascending order."""
    blocks, root, bitmap = 1760, 880, 881
    image = bytearray(blocks * BLOCK_SIZE)
    image[0:4] = b"DOS" + bytes([dos_type])

    def put(number: int, offset: int, fmt: str, *values) -> None:
        struct.pack_into(fmt, image, number * BLOCK_SIZE + offset, *values)

    used = {root, bitmap}
    following = bitmap + 1
    hash_table = [0] * 72
    for name, data in files.items():
        encoded = name.encode("latin1")
        count = -(-len(data) // 512)
        chunks = [data[i * 512:(i + 1) * 512] for i in range(count)]
        headers = max(1, -(-count // 72))
        chain = list(range(following, following + headers))
        data_blocks = list(range(following + headers,
                                 following + headers + count))
        following += headers + count
        used.update(chain, data_blocks)
        for number, chunk in zip(data_blocks, chunks):
            image[number * BLOCK_SIZE:number * BLOCK_SIZE + len(chunk)] = chunk
        for position, number in enumerate(chain):
            mine = data_blocks[position * 72:(position + 1) * 72]
            put(number, 0, ">I", 2 if position == 0 else 16)
            put(number, 4, ">I", number)
            put(number, 8, ">I", len(mine))
            for index, block in enumerate(mine):
                put(number, BLOCK_SIZE - 204 - 4 * index, ">I", block)
            put(number, BLOCK_SIZE - 8, ">I",
                chain[position + 1] if position + 1 < len(chain) else 0)
            put(number, BLOCK_SIZE - 4, ">i", -3)
            if position == 0:
                put(number, 16, ">I", mine[0] if mine else 0)
                put(number, BLOCK_SIZE - 188, ">I", len(data))
                put(number, BLOCK_SIZE - 92, ">III", 4900, 754, 2800)
                image[number * BLOCK_SIZE + BLOCK_SIZE - 80] = len(encoded)
                at = number * BLOCK_SIZE + BLOCK_SIZE - 79
                image[at:at + len(encoded)] = encoded
                put(number, BLOCK_SIZE - 12, ">I", root)
                slot = _spec_hash(encoded, bool(dos_type & 6))
                put(number, BLOCK_SIZE - 16, ">I", hash_table[slot])
                hash_table[slot] = number
            else:
                put(number, BLOCK_SIZE - 12, ">I", chain[0])
    put(root, 0, ">I", 2)
    put(root, 12, ">I", 72)
    for slot, number in enumerate(hash_table):
        put(root, 24 + 4 * slot, ">I", number)
    put(root, BLOCK_SIZE - 200, ">iI", -1, bitmap)
    image[root * BLOCK_SIZE + BLOCK_SIZE - 80] = 3
    at = root * BLOCK_SIZE + BLOCK_SIZE - 79
    image[at:at + 3] = b"REF"
    put(root, BLOCK_SIZE - 4, ">i", 1)
    for number in range(2, blocks):
        if number not in used:
            index = number - 2
            at = bitmap * BLOCK_SIZE + 4 + 4 * (index // 32)
            word = struct.unpack_from(">I", image, at)[0] | 1 << index % 32
            struct.pack_into(">I", image, at, word)
    for number in used:
        if number in (root, bitmap) or struct.unpack_from(
                ">I", image, number * BLOCK_SIZE)[0] in (2, 16):
            at = 0 if number == bitmap else 20
            block = image[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE]
            put(number, at, ">I", _spec_sum(block, at))
    return bytes(image)


def _spec_read_root_file(image: bytes, name: str) -> bytes:
    """One root-level file of an FFS image, read by the format description:
    the hash slot, the chain, the data-block tables and raw 512-byte blocks."""
    def u32(number: int, offset: int) -> int:
        return struct.unpack_from(">I", image, number * BLOCK_SIZE + offset)[0]

    encoded = name.encode("latin1")
    international = bool(image[3] & 6)
    # A long-name disk keeps an entry's name at the start of the merged
    # name-and-comment field instead.
    name_at = BLOCK_SIZE - 184 if image[3] in (6, 7) else BLOCK_SIZE - 80
    number = u32(880, 24 + 4 * _spec_hash(encoded, international))
    while number:
        length = image[number * BLOCK_SIZE + name_at]
        at = number * BLOCK_SIZE + name_at + 1
        if image[at:at + length] == encoded:
            break
        number = u32(number, BLOCK_SIZE - 16)
    assert number, f"{name} is not in its hash chain"
    size = u32(number, BLOCK_SIZE - 188)
    out = bytearray()
    current = number
    while current:
        for index in range(u32(current, 8)):
            block = u32(current, BLOCK_SIZE - 204 - 4 * index)
            out += image[block * BLOCK_SIZE:(block + 1) * BLOCK_SIZE]
        current = u32(current, BLOCK_SIZE - 8)
    return bytes(out[:size])


#: Sizes either side of one OFS block, one FFS block and one header's 72
#: pointers, and an empty file.
FFS_SIZES = (0, 1, 488, 489, 511, 512, 513, 72 * 512, 72 * 512 + 1, 120000)


def _ffs_payload(size: int, seed: int = 0) -> bytes:
    return bytes((seed + index * 7) & 0xFF for index in range(size))


@pytest.mark.parametrize("dos_type", WRITABLE_TYPES)
def test_a_blank_disk_of_each_writable_type_is_consistent(dos_type):
    disk = AmigaDisk.blank("wishtest", dos_type=dos_type)
    assert disk.block(0)[:4] == b"DOS" + bytes([dos_type])
    assert disk.dos_type == dos_type
    assert disk.ffs is bool(dos_type & 1)
    assert disk.international is bool(dos_type & 6)
    assert disk.verify() == []
    # Boot block pair, root, bitmap, and on a directory-cache disk the root's
    # one empty cache block. A long-name disk has no cache.
    assert disk.free_count() == 1760 - 4 - (dos_type in DIRCACHE_TYPES)


@pytest.mark.parametrize("dos_type", FFS_TYPES)
@pytest.mark.parametrize("size", FFS_SIZES)
def test_an_ffs_file_round_trips_in_512_byte_blocks(dos_type, size):
    """An FFS data block holds 512 bytes, so a file takes ceil(size / 512) of
    them plus one header per 72 -- and an empty file is its header alone."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    free = disk.free_count()
    payload = _ffs_payload(size, size)
    disk.write_file("FILE.BIN", payload, when=WHEN)
    assert disk.verify() == []
    assert disk.read_file("FILE.BIN") == payload
    data_blocks = -(-size // FFS_DATA_SIZE)
    headers = max(1, -(-data_blocks // HASH_TABLE_SIZE))
    assert free - disk.free_count() == data_blocks + headers


@pytest.mark.parametrize("dos_type", FFS_TYPES)
def test_an_ffs_data_block_is_the_file_bytes_and_nothing_else(dos_type):
    disk = AmigaDisk.blank(dos_type=dos_type)
    payload = _ffs_payload(1300, 9)
    disk.write_file("RAW", payload, when=WHEN)
    header = disk.block(disk.lookup("RAW").block)
    table = [struct.unpack_from(">I", header, BLOCK_SIZE - 204 - 4 * i)[0]
             for i in range(3)]
    assert struct.unpack_from(">I", header, 8)[0] == 3          # high_seq
    assert struct.unpack_from(">I", header, 16)[0] == table[0]  # first_data
    assert disk.block(table[0]) == payload[:512]
    assert disk.block(table[1]) == payload[512:1024]
    assert disk.block(table[2]) == payload[1024:].ljust(512, b"\0")


@pytest.mark.parametrize("dos_type", (1, 3))
def test_a_spec_built_ffs_image_reads_back(dos_type):
    """The reader against an image it did not write."""
    files = {f"F{size}.bin": _ffs_payload(size, size) for size in FFS_SIZES}
    files["caf\xe9"] = b"accented"
    disk = AmigaDisk(_spec_ffs_image(files, dos_type))
    assert disk.ffs and disk.volume_name == "REF"
    assert disk.verify() == []
    assert {path.lstrip("/"): disk.read_file(path)
            for path, _ in disk.walk()} == files


@pytest.mark.parametrize("dos_type", FFS_TYPES)
def test_an_ffs_file_this_module_writes_reads_by_the_spec(dos_type):
    """The writer against a reader it does not share."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    files = {f"F{size}.bin": _ffs_payload(size, size) for size in FFS_SIZES}
    files["caf\xe9"] = b"accented"
    for name, data in files.items():
        disk.write_file(name, data, when=WHEN)
    image = disk.to_bytes()
    for name, data in files.items():
        assert _spec_read_root_file(image, name) == data, name


@pytest.mark.parametrize("dos_type", FFS_TYPES)
def test_ffs_replace_and_remove_keep_the_hash_chains_and_the_bitmap(dos_type):
    disk = AmigaDisk.blank(dos_type=dos_type)
    free = disk.free_count()
    names = [f"CHAR{n:03d}.cha" for n in range(150)]
    for name in names:
        disk.write_file(name, name.encode() * 40, when=WHEN)
    for name in names[::3]:
        disk.write_file(name, b"short", when=WHEN)
    for name in names[1::3]:
        disk.remove_file(name)
    assert disk.verify() == []
    kept = {name: disk.read_file(name) for name in names
            if name not in names[1::3]}
    assert all(kept[n] == b"short" for n in names[::3])
    assert all(kept[n] == n.encode() * 40 for n in names[2::3])
    for name in kept:
        disk.remove_file(name)
    assert disk.free_count() == free
    assert disk.verify() == []


def _ffs_file_pointing_at(bad: str) -> tuple[AmigaDisk, bytes, int]:
    """An FFS disk, and the same disk with the second data pointer of `FILE`
    moved onto a filesystem block, and that block's number."""
    disk = AmigaDisk.blank(dos_type=1)
    disk.write_file("FILE", _ffs_payload(1000), when=WHEN)
    header = disk.lookup("FILE").block
    bitmap = struct.unpack_from(">I", disk.block(disk.root), BLOCK_SIZE - 196)[0]
    pointer = {"boot": 1, "zero": 0, "root": disk.root, "bitmap": bitmap}[bad]
    raw = bytearray(disk.to_bytes())
    at = header * BLOCK_SIZE
    struct.pack_into(">I", raw, at + BLOCK_SIZE - 204 - 4, pointer)
    struct.pack_into(">I", raw, at + 20, 0)
    struct.pack_into(">I", raw, at + 20, _spec_sum(raw[at:at + BLOCK_SIZE], 20))
    return disk, bytes(raw), pointer


@pytest.mark.parametrize("bad", ["boot", "zero", "root", "bitmap"])
def test_an_ffs_data_pointer_at_a_filesystem_block_is_refused(bad):
    """An FFS data block has no header to check, so the pointer itself is
    checked: the bootblock, a zero, the root and the bitmap hold no file."""
    disk, raw, pointer = _ffs_file_pointing_at(bad)
    with pytest.raises(AmigaDiskError, match=f"block {pointer}"):
        AmigaDisk(raw).read_file("FILE")
    assert AmigaDisk(disk.to_bytes()).read_file("FILE") == _ffs_payload(1000)


@pytest.mark.parametrize("bad", ["boot", "zero", "root", "bitmap"])
def test_verify_reports_an_ffs_data_pointer_at_a_filesystem_block(bad):
    """The same pointer `read_file` refuses is damage to `verify()`."""
    disk, raw, pointer = _ffs_file_pointing_at(bad)
    problems = AmigaDisk(raw).verify()
    assert any(f"block {pointer} as file data" in p for p in problems), problems
    assert disk.verify() == []


def test_a_drawer_and_a_file_in_it_on_ffs():
    disk = AmigaDisk.blank("wishtest", dos_type=1)
    disk.make_dir("save", when=WHEN)
    disk.write_file("save/CHRDATA1.sav", _ffs_payload(3000), when=WHEN)
    assert disk.read_file("/SAVE/chrdata1.SAV") == _ffs_payload(3000)
    assert disk.verify() == []


def test_the_international_hash_raises_accented_letters():
    """Pinned to amitools' `FileName.hash`, run once on these names: the
    standard hash leaves `0xE0`-`0xFE` alone, the international one raises
    them, except `0xF7`."""
    assert [hash_name(n) for n in ("caf\xe9", "CAF\xc9", "\xe0\xf7\xfe")] == [
        35, 3, 16]
    assert [hash_name(n, international=True)
            for n in ("caf\xe9", "CAF\xc9", "\xe0\xf7\xfe")] == [3, 3, 0]
    # `0xFF` and `0xDF` are outside the raised range in both modes: a rule
    # that raised `0xE0`-`0xFF` would fold `\xff` onto `\xdf` and move it.
    for international in (False, True):
        assert [hash_name(n, international=international)
                for n in ("\xff", "\xdf", "\xdf\xff", "\xff\xdf")] == [
                    52, 20, 4, 28]
        assert upper_name("\xff\xdf\xf7", international) == "\xff\xdf\xf7"
    for name in ("savgamA.dat", "GARWAN.cha", "CHRDATA1.sav"):
        assert hash_name(name) == hash_name(name, international=True)


@pytest.mark.parametrize("dos_type", WRITABLE_TYPES)
def test_an_accented_name_is_filed_and_found_by_the_disks_own_rule(dos_type):
    """International mode folds `é` to `É`; the standard mode does not, so the
    other spelling is a different name there."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    disk.write_file("caf\xe9", b"one", when=WHEN)
    international = bool(dos_type & 6)
    slot = hash_name("caf\xe9", international=international)
    root = disk.block(disk.root)
    assert struct.unpack_from(">I", root, 24 + 4 * slot)[0] == (
        disk.lookup("caf\xe9").block)
    assert disk.read_file("CAF\xe9") == b"one"
    if international:
        assert disk.read_file("CAF\xc9") == b"one"
    else:
        with pytest.raises(AmigaDiskError):
            disk.read_file("CAF\xc9")
        disk.write_file("CAF\xc9", b"two", when=WHEN)
        assert disk.read_file("caf\xe9") == b"one"
        assert disk.verify() == []


def _dircache_disk(dos_type: int) -> AmigaDisk:
    """An FFS or OFS disk turned into its directory-cache type by hand: one
    cache block on the root, recording its two files as the format lays a
    record out."""
    disk = AmigaDisk.blank("dcache", dos_type=dos_type & 1)
    disk.write_file("ONE", b"first file", when=WHEN)
    disk.write_file("TWO", _ffs_payload(2000), when=WHEN)
    cache = disk._allocate(1)[0]
    disk._fix_bitmap()
    raw = bytearray(disk.to_bytes())
    at = cache * BLOCK_SIZE
    struct.pack_into(">III", raw, at, 33, cache, disk.root)
    offset = at + 24
    for name in ("ONE", "TWO"):
        entry = disk.lookup(name)
        size = len(disk.read_file(name))
        days, minutes, ticks = struct.unpack_from(
            ">III", disk.block(entry.block), BLOCK_SIZE - 92)
        struct.pack_into(">IIIHHhhhb", raw, offset, entry.block, size, 0, 0, 0,
                         days, minutes, ticks, -3)
        raw[offset + 23] = len(name)
        raw[offset + 24:offset + 24 + len(name)] = name.encode()
        raw[offset + 24 + len(name)] = 0
        offset += (25 + len(name) + 1) & ~1
    struct.pack_into(">I", raw, at + 12, 2)
    struct.pack_into(">I", raw, at + 20,
                     _spec_sum(raw[at:at + BLOCK_SIZE], 20))
    root_at = disk.root * BLOCK_SIZE
    struct.pack_into(">I", raw, root_at + BLOCK_SIZE - 8, cache)
    struct.pack_into(">I", raw, root_at + 20, 0)
    struct.pack_into(">I", raw, root_at + 20,
                     _spec_sum(raw[root_at:root_at + BLOCK_SIZE], 20))
    raw[3] = dos_type
    return AmigaDisk(raw)


@pytest.mark.parametrize("dos_type", [4, 5])
def test_a_directory_cache_disk_is_read_through_its_hash_tables(dos_type):
    disk = _dircache_disk(dos_type)
    assert disk.dircache and disk.international
    assert disk.ffs is bool(dos_type & 1)
    assert disk.verify() == []
    assert disk.read_file("one") == b"first file"
    assert disk.read_file("TWO") == _ffs_payload(2000)


def _spec_cache(image: bytes, drawer: int) -> tuple[list[int], list[tuple]]:
    """A drawer's cache blocks and their records, read by the format
    description: the chain from the drawer's `extension` field, each block's
    header and checksum, then `(entry, size, protect, date, type, name,
    comment)` per record, each record padded to an even length."""
    def u32(number: int, offset: int) -> int:
        return struct.unpack_from(">I", image, number * BLOCK_SIZE + offset)[0]

    blocks: list[int] = []
    records: list[tuple] = []
    number = u32(drawer, BLOCK_SIZE - 8)
    while number:
        assert number not in blocks
        blocks.append(number)
        block = image[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE]
        assert (u32(number, 0), u32(number, 4), u32(number, 8)) == (
            33, number, drawer)
        assert u32(number, 20) == _spec_sum(block, 20)
        offset = 24
        for _ in range(u32(number, 12)):
            name_length = block[offset + 23]
            comment_length = block[offset + 24 + name_length]
            records.append((
                u32(number, offset), u32(number, offset + 4),
                u32(number, offset + 8),
                struct.unpack_from(">HHH", block, offset + 16),
                block[offset + 22],
                bytes(block[offset + 24:offset + 24 + name_length]),
                bytes(block[offset + 25 + name_length:
                            offset + 25 + name_length + comment_length])))
            offset += (25 + name_length + comment_length + 1) & ~1
        assert offset <= BLOCK_SIZE
        number = u32(number, 16)
    return blocks, records


def _spec_listing(image: bytes, drawer: int) -> list[tuple]:
    """What every record of `drawer` should say, read off the headers its
    hash table reaches, in the same form as `_spec_cache`."""
    def u32(number: int, offset: int) -> int:
        return struct.unpack_from(">I", image, number * BLOCK_SIZE + offset)[0]

    out = []
    for slot in range(72):
        number = u32(drawer, 24 + 4 * slot)
        while number:
            block = image[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE]
            sec_type = struct.unpack_from(">i", block, BLOCK_SIZE - 4)[0]
            days, minutes, ticks = struct.unpack_from(">III", block,
                                                      BLOCK_SIZE - 92)
            length = block[BLOCK_SIZE - 80]
            out.append((number,
                        u32(number, BLOCK_SIZE - 188) if sec_type == -3 else 0,
                        u32(number, BLOCK_SIZE - 192),
                        (days, minutes, ticks), sec_type & 0xFF,
                        bytes(block[BLOCK_SIZE - 79:BLOCK_SIZE - 79 + length]),
                        b""))
            number = u32(number, BLOCK_SIZE - 16)
    return out


def _drawers(disk: AmigaDisk) -> list[int]:
    return [disk.root] + [entry.block for _, entry in disk.walk_dirs()]


def _assert_caches_match(disk: AmigaDisk) -> None:
    """Every drawer's cache records exactly what its hash table holds, and
    every cache block is allocated."""
    image = disk.to_bytes()
    for drawer in _drawers(disk):
        blocks, records = _spec_cache(image, drawer)
        assert blocks, f"drawer {drawer} has no cache block"
        assert sorted(records) == sorted(_spec_listing(image, drawer)), drawer
        assert not any(disk.is_free(number) for number in blocks)
    assert disk.verify() == []
    assert disk.cache_warnings() == []


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
def test_a_blank_directory_cache_disk_has_one_empty_cache_block(dos_type):
    disk = AmigaDisk.blank("dcache", dos_type=dos_type)
    blocks, records = _spec_cache(disk.to_bytes(), disk.root)
    assert len(blocks) == 1 and records == []
    _assert_caches_match(disk)


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
def test_every_write_to_a_directory_cache_disk_keeps_its_records(dos_type):
    """Add, replace and remove, each followed by the records read back by the
    format description against the headers the hash tables reach."""
    disk = _dircache_disk(dos_type)
    free = disk.free_count()
    disk.write_file("THREE", b"third", when=WHEN)
    _assert_caches_match(disk)
    disk.write_file("one", _ffs_payload(5000), when=WHEN)
    _assert_caches_match(disk)
    assert disk.read_file("ONE") == _ffs_payload(5000)
    disk.remove_file("TWO")
    _assert_caches_match(disk)
    disk.remove_file("ONE")
    disk.remove_file("THREE")
    _assert_caches_match(disk)
    assert _spec_cache(disk.to_bytes(), disk.root)[1] == []
    # Boot block pair, root, bitmap and the root's one cache block remain.
    assert disk.free_count() == 1760 - 5 > free


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
def test_a_full_cache_block_chains_a_second_and_gives_it_back_when_empty(
        dos_type):
    """A 30-character name makes a 56-byte record, so eight fill a block."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    free = disk.free_count()
    names = [f"{n:02d}".ljust(30, "x") for n in range(20)]
    for name in names:
        disk.write_file(name, name.encode(), when=WHEN)
    blocks, records = _spec_cache(disk.to_bytes(), disk.root)
    assert len(blocks) == 3 and len(records) == 20
    _assert_caches_match(disk)
    for name in names[:8]:
        disk.write_file(name, b"replaced", when=WHEN)
    _assert_caches_match(disk)
    for name in names:
        disk.remove_file(name)
        _assert_caches_match(disk)
    blocks, records = _spec_cache(disk.to_bytes(), disk.root)
    assert len(blocks) == 1 and records == []
    assert disk.free_count() == free


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
def test_a_new_drawer_on_a_directory_cache_disk_gets_its_own_cache(dos_type):
    disk = AmigaDisk.blank(dos_type=dos_type)
    free = disk.free_count()
    drawer = disk.make_dir("save", when=WHEN)
    blocks, records = _spec_cache(disk.to_bytes(), drawer)
    assert len(blocks) == 1 and records == []
    assert free - disk.free_count() == 2
    _assert_caches_match(disk)
    later = datetime.datetime(1992, 2, 3, 4, 5, 6)
    disk.write_file("save/CHRDATA1.sav", _ffs_payload(3000), when=later)
    disk.make_dir("save/deeper", when=WHEN)
    disk.write_file("save/deeper/X", b"x", when=WHEN)
    _assert_caches_match(disk)
    assert disk.read_file("SAVE/chrdata1.SAV") == _ffs_payload(3000)
    disk.remove_file("save/CHRDATA1.sav")
    _assert_caches_match(disk)


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
def test_a_directory_cache_write_that_cannot_fit_changes_nothing(dos_type):
    """The file's two blocks fit and the cache block its record needs does
    not: the write is refused and every byte is as it was."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    for n in range(8):
        disk.write_file(f"{n:02d}".ljust(30, "x"), b"", when=WHEN)
    assert len(_spec_cache(disk.to_bytes(), disk.root)[0]) == 1
    disk._allocate(disk.free_count() - 2)
    disk._fix_bitmap()
    before = disk.to_bytes()
    with pytest.raises(AmigaDiskError):
        disk.write_file("NEWFILE".ljust(30, "z"), b"x", when=WHEN)
    assert disk.to_bytes() == before
    with pytest.raises(AmigaDiskError):
        disk.make_dir("NEWDRAWER".ljust(30, "z"), when=WHEN)
    assert disk.to_bytes() == before


def _restale(raw: bytearray, number: int) -> None:
    """Fix one cache block's checksum after a test edits its records."""
    at = number * BLOCK_SIZE
    struct.pack_into(">I", raw, at + 20, 0)
    struct.pack_into(">I", raw, at + 20, _spec_sum(raw[at:at + BLOCK_SIZE], 20))


def _stale_cache_disk(dos_type: int, stale: str) -> AmigaDisk:
    """`_dircache_disk` with one disagreement between the root's cache and its
    hash table: `ONE` listed under another name or size, `TWO` not listed, or
    a record for a block that is in no drawer.

    The records sit at 24 (`ONE`, 28 bytes) and 52 (`TWO`)."""
    disk = _dircache_disk(dos_type)
    cache = struct.unpack_from(">I", disk.block(disk.root), BLOCK_SIZE - 8)[0]
    raw = bytearray(disk.to_bytes())
    at = cache * BLOCK_SIZE
    if stale == "name":
        raw[at + 24 + 24:at + 24 + 27] = b"ONX"
    elif stale == "size":
        struct.pack_into(">I", raw, at + 24 + 4, 99)
    elif stale == "missing":
        struct.pack_into(">I", raw, at + 12, 1)
    elif stale == "extra":
        offset = at + 80
        struct.pack_into(">IIIHHhhhb", raw, offset, 1234, 7, 0, 0, 0,
                         1, 2, 3, -3)
        raw[offset + 23] = 4
        raw[offset + 24:offset + 28] = b"GONE"
        raw[offset + 28] = 0
        struct.pack_into(">I", raw, at + 12, 3)
    _restale(raw, cache)
    return AmigaDisk(raw)


STALE_KINDS = ("name", "size", "missing", "extra")


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
@pytest.mark.parametrize("stale", STALE_KINDS)
def test_a_stale_cache_is_a_warning_and_not_damage(dos_type, stale):
    """AmigaDOS finds a file through the hash tables, so a listing that
    disagrees with them is reported apart from damage `verify()` refuses."""
    disk = _stale_cache_disk(dos_type, stale)
    assert disk.verify() == []
    warnings = disk.cache_warnings()
    word = {"name": "name", "size": "size", "missing": "no record",
            "extra": "1234"}[stale]
    assert any(word in w for w in warnings), warnings
    assert disk.read_file("ONE") == b"first file"


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
@pytest.mark.parametrize("stale", STALE_KINDS)
@pytest.mark.parametrize("operation", ("add", "replace", "remove"))
def test_a_stale_cache_on_the_disk_as_it_came_still_saves(
        dos_type, stale, operation):
    """The write goes through, and the drawer it wrote to comes out with a
    cache that lists exactly what its hash table holds."""
    disk = _stale_cache_disk(dos_type, stale)
    if operation == "add":
        disk.write_file("THREE", b"third", when=WHEN)
        assert disk.read_file("THREE") == b"third"
    elif operation == "replace":
        disk.write_file("TWO", b"replaced", when=WHEN)
        assert disk.read_file("TWO") == b"replaced"
    else:
        disk.remove_file("TWO")
        assert [name for name, _ in disk.walk()] == ["/ONE"]
    _assert_caches_match(AmigaDisk(disk.to_bytes()))


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
@pytest.mark.parametrize("operation", ("add", "remove", "make_dir"))
def test_a_drawer_its_parent_does_not_list_still_takes_a_save(
        dos_type, operation):
    """The root's cache has lost `save`'s record: a write into `save`, which
    redates it in the root's listing, rebuilds the root's cache instead."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    disk.make_dir("save", when=WHEN)
    disk.write_file("save/OLD", b"old", when=WHEN)
    cache = struct.unpack_from(">I", disk.block(disk.root), BLOCK_SIZE - 8)[0]
    raw = bytearray(disk.to_bytes())
    struct.pack_into(">I", raw, cache * BLOCK_SIZE + 12, 0)
    _restale(raw, cache)
    disk = AmigaDisk(raw)
    assert any("no record" in w for w in disk.cache_warnings())
    if operation == "add":
        disk.write_file("save/NEW", b"new", when=WHEN)
    elif operation == "remove":
        disk.remove_file("save/OLD")
    else:
        disk.make_dir("save/deeper", when=WHEN)
    _assert_caches_match(AmigaDisk(disk.to_bytes()))


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
def test_a_cache_mismatch_the_write_introduces_is_refused(dos_type, monkeypatch):
    """A drawer whose cache agreed before the write must agree after it: a
    write that forgets the new record is refused and changes nothing."""
    disk = _dircache_disk(dos_type)
    before = disk.to_bytes()
    monkeypatch.setattr(AmigaDisk, "_cache_add", lambda self, drawer, header: None)
    with pytest.raises(AmigaDiskError, match="directory cache"):
        disk.write_file("THREE", b"third", when=WHEN)
    assert disk.to_bytes() == before


def test_verify_reports_a_directory_cache_block_marked_free():
    disk = _dircache_disk(5)
    cache = struct.unpack_from(">I", disk.block(disk.root), BLOCK_SIZE - 8)[0]
    disk._set_free(cache, True)
    disk._fix_bitmap()
    assert any("directory cache block" in p and "marked free" in p
               for p in disk.verify()), disk.verify()


@pytest.mark.parametrize("dos_type", (0, 1, 5))
@pytest.mark.parametrize("fails", ("_free_blocks", "_fix_bitmap"))
def test_a_remove_that_fails_part_way_puts_every_byte_back(
        dos_type, fails, monkeypatch):
    """`_free_blocks` raises after the file is unlinked from its drawer, and
    `_fix_bitmap` after everything else is done: either way the image is the
    one the call started with."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    disk.make_dir("save", when=WHEN)
    disk.write_file("save/KEEP", _ffs_payload(3000), when=WHEN)
    disk.write_file("save/GONE", _ffs_payload(40000), when=WHEN)
    before = disk.to_bytes()

    def broken(self, *args, **kwargs):
        raise OSError("failed part way")

    monkeypatch.setattr(AmigaDisk, fails, broken)
    with pytest.raises(OSError, match="failed part way"):
        disk.remove_file("save/GONE")
    monkeypatch.undo()
    assert disk.to_bytes() == before
    assert disk.read_file("save/GONE") == _ffs_payload(40000)
    assert disk.verify() == []


def _ffs_copy(disk: AmigaDisk, dos_type: int) -> AmigaDisk:
    """Every drawer and file of `disk` written onto a freshly formatted disk
    of `dos_type` with the same volume name and block count."""
    copy = AmigaDisk.blank(disk.volume_name, blocks=disk.block_count,
                           dos_type=dos_type)
    for path, _ in disk.walk_dirs():
        copy.make_dir(path, when=WHEN)
    for path, _ in disk.walk():
        copy.write_file(path, disk.read_file(path), when=WHEN)
    return copy


@pytest.mark.parametrize("dos_type", (1, 3, 4, 5, 6, 7))
def test_every_real_disk_copied_onto_another_type_reads_back_identically(
        dos_type):
    """A game disk's files fit an FFS or a directory-cache floppy and come
    back byte for byte. The player's images are only read; every copy is in
    memory."""
    for path in real_disks():
        disk = AmigaDisk.open(path)
        files = {name: disk.read_file(name) for name, _ in disk.walk()}
        copy = AmigaDisk(_ffs_copy(disk, dos_type).to_bytes())
        assert copy.ffs is bool(dos_type & 1), path.name
        assert copy.verify() == [], (path.name, copy.verify()[:3])
        if copy.dircache:
            _assert_caches_match(copy)
        assert sorted(p for p, _ in copy.walk_dirs()) == sorted(
            p for p, _ in disk.walk_dirs()), path.name
        assert {name: copy.read_file(name)
                for name, _ in copy.walk()} == files, path.name


@pytest.mark.parametrize("dos_type", (1, 5, 7))
def test_a_save_on_an_ffs_disk_one_round_trips_like_on_ofs(dos_type):
    """`slot_on_disk_one` writes the same slot onto the player's OFS disk 1
    and onto an FFS, FFS directory-cache or FFS long-name copy of it, and the
    two read back
    the same: every file, and the parsed save."""
    import support.amigasavegame as support

    from goldbox import amiga_savegame

    makers = {amiga_savegame.CURSE.key: support.synthetic_curse,
              amiga_savegame.SILVER_BLADES.key: support.synthetic_silver_blades}
    done = 0
    for path in real_disks():
        disk = AmigaDisk.open(path)
        for container in (amiga_savegame.CURSE, amiga_savegame.SILVER_BLADES):
            executable = amiga_savegame.DISK_ONE_EXECUTABLE[container.key]
            try:
                disk.lookup(executable)
                disk.lookup("/SAVE/spindisk")
            except AmigaDiskError:
                continue
            saved = makers[container.key](("OMEGA",))
            ofs = amiga_savegame.slot_on_disk_one(disk, container, "B", saved)
            ffs = amiga_savegame.slot_on_disk_one(
                _ffs_copy(disk, dos_type), container, "B", saved)
            ffs = AmigaDisk(ffs.to_bytes())
            assert ffs.dos_type == dos_type and ffs.verify() == []
            if ffs.dircache:
                _assert_caches_match(ffs)
            assert ({p: ffs.read_file(p) for p, _ in ffs.walk()}
                    == {p: ofs.read_file(p) for p, _ in ofs.walk()}), path.name
            assert (amiga_savegame.slots_present(ffs, container)
                    == amiga_savegame.slots_present(ofs, container))
            for slot in amiga_savegame.slots_present(ofs, container):
                assert (amiga_savegame.read_slot(ffs, slot, container)
                        == amiga_savegame.read_slot(ofs, slot, container))
            assert amiga_savegame.read_slot(ffs, "B", container).data == saved
            done += 1
    if not done:
        pytest.skip("no Curse or Silver Blades disk 1 among the Amiga disks")


@pytest.mark.parametrize("dos_type", DIRCACHE_TYPES)
def test_rebuilding_a_cache_keeps_a_record_that_already_agrees(dos_type):
    """A record with the right name, type and size survives a rebuild byte for
    byte, date included; only the record with the wrong size is replaced."""
    disk = _dircache_disk(dos_type)
    cache = struct.unpack_from(">I", disk.block(disk.root), BLOCK_SIZE - 8)[0]
    one, two = disk.lookup("ONE").block, disk.lookup("TWO").block
    raw = bytearray(disk.to_bytes())
    at = cache * BLOCK_SIZE
    # ONE's record sits at 24 and TWO's at 52; see `_stale_cache_disk`.
    struct.pack_into(">HHH", raw, at + 24 + 16, 7000, 11, 22)
    struct.pack_into(">I", raw, at + 52 + 4, 99)
    _restale(raw, cache)
    disk = AmigaDisk(raw)

    def records() -> dict[int, bytes]:
        return {struct.unpack_from(">I", r, 0)[0]: r
                for r in disk._cache_records(cache)}

    before = records()
    assert before[one][16:22] != disk._cache_record(one)[16:22]
    assert not disk._record_agrees(before[two], disk._cache_record(two))

    disk.write_file("THREE", b"third", when=WHEN)

    after = records()
    assert after[one] == before[one]
    assert after[two] == disk._cache_record(two)
    assert disk.cache_warnings() == []


# ---------------------------------------------------------------------------
# Long file names: `DOS\6` and `DOS\7`
# ---------------------------------------------------------------------------
#
# Laid out from the format description, by code sharing nothing with the
# module: amiga-ffs's `layout` module (longwords -46, -18, -15 of an entry
# header; -11 and -4 of the root; block type 64) and amitools'
# `EntryBlock._read_nac_modts`, `RootBlock` and `CommentBlock`, which agree.
# An entry header's name and comment are two length-prefixed strings laid end
# to end in 112 bytes at 0x148; a comment that does not fit there goes in a
# type-64 block named at 0x1B8, and the date moves from 0x1A4 to 0x1C4. The
# root keeps the short layout, and adds the count of blocks the bitmap marks
# used at 0x1D4 and the DOS type itself at 0x1F0.

_LN_NAC, _LN_COMMENT_BLOCK, _LN_DATE = 0x148, 0x1B8, 0x1C4
_LN_USED, _LN_FS_TYPE = 0x1D4, 0x1F0
#: A 106-character name, the longest the module writes.
LONGEST = "".join(chr(ord("a") + n % 26) for n in range(105)) + "Z"


def _spec_u32(image: bytes, number: int, offset: int) -> int:
    return struct.unpack_from(">I", image, number * BLOCK_SIZE + offset)[0]


def _spec_used(image: bytes) -> int:
    """Blocks the bitmap marks used, over the blocks it covers (2 to the end),
    read from the bitmap page the root names."""
    bitmap = _spec_u32(image, 880, BLOCK_SIZE - 196)
    used = 0
    for number in range(2, len(image) // BLOCK_SIZE):
        index = number - 2
        word = _spec_u32(image, bitmap, 4 + 4 * (index // 32))
        used += not word >> (index % 32) & 1
    return used


def _spec_lnfs_image(dos_type: int,
                     entries: list[tuple[str, bytes | None, bytes]]) -> bytes:
    """A long-name floppy holding `entries` -- `(path, data, comment)`, data
    None for a drawer, drawers before what they hold -- laid out by the format
    description: root 880, bitmap 881, then every block in ascending order."""
    blocks, root, bitmap = 1760, 880, 881
    ffs = dos_type == 7
    image = bytearray(blocks * BLOCK_SIZE)
    image[0:4] = b"DOS" + bytes([dos_type])

    def put(number: int, offset: int, fmt: str, *values) -> None:
        struct.pack_into(fmt, image, number * BLOCK_SIZE + offset, *values)

    following = [bitmap + 1]

    def take(count: int) -> list[int]:
        out = list(range(following[0], following[0] + count))
        following[0] += count
        return out

    sums: dict[int, int] = {root: 20, bitmap: 0}
    drawers = {"": root}
    for path, data, comment in entries:
        parent_path, _, name = path.rpartition("/")
        parent = drawers[parent_path]
        encoded = name.encode("latin1")
        header = take(1)[0]
        sums[header] = 20
        put(header, 0, ">I", 2)
        put(header, 4, ">I", header)
        nac = bytes([len(encoded)]) + encoded
        if len(nac) + 1 + len(comment) <= 112:
            nac += bytes([len(comment)]) + comment
        else:
            nac += b"\0"
            note = take(1)[0]
            sums[note] = 20
            put(note, 0, ">III", 64, note, header)
            image[note * BLOCK_SIZE + 24] = len(comment)
            at = note * BLOCK_SIZE + 25
            image[at:at + len(comment)] = comment
            put(header, _LN_COMMENT_BLOCK, ">I", note)
        image[header * BLOCK_SIZE + _LN_NAC:
              header * BLOCK_SIZE + _LN_NAC + len(nac)] = nac
        put(header, _LN_DATE, ">III", 4900, 754, 2800)
        put(header, BLOCK_SIZE - 12, ">I", parent)
        slot = _spec_hash(encoded, True)
        put(header, BLOCK_SIZE - 16, ">I",
            _spec_u32(image, parent, 24 + 4 * slot))
        put(parent, 24 + 4 * slot, ">I", header)
        if data is None:
            put(header, BLOCK_SIZE - 4, ">i", 2)
            drawers[path] = header
            continue
        put(header, BLOCK_SIZE - 4, ">i", -3)
        put(header, BLOCK_SIZE - 188, ">I", len(data))
        size = 512 if ffs else 488
        count = max(-(-len(data) // size), 0 if ffs else 1)
        assert count <= 72, "one header's worth is all this builder lays out"
        chain = take(count)
        put(header, 8, ">I", count)
        if chain:
            put(header, 16, ">I", chain[0])
        for index, number in enumerate(chain):
            put(header, BLOCK_SIZE - 204 - 4 * index, ">I", number)
            chunk = data[index * size:(index + 1) * size]
            if ffs:
                image[number * BLOCK_SIZE:number * BLOCK_SIZE + len(chunk)] = (
                    chunk)
                continue
            following_block = chain[index + 1] if index + 1 < count else 0
            put(number, 0, ">IIIII", 8, header, index + 1, len(chunk),
                following_block)
            image[number * BLOCK_SIZE + 24:
                  number * BLOCK_SIZE + 24 + len(chunk)] = chunk
            sums[number] = 20
    put(root, 0, ">I", 2)
    put(root, 12, ">I", 72)
    put(root, BLOCK_SIZE - 200, ">iI", -1, bitmap)
    image[root * BLOCK_SIZE + BLOCK_SIZE - 80] = 3
    image[root * BLOCK_SIZE + BLOCK_SIZE - 79:
          root * BLOCK_SIZE + BLOCK_SIZE - 76] = b"REF"
    put(root, BLOCK_SIZE - 4, ">i", 1)
    for number in range(following[0], blocks):
        index = number - 2
        at = bitmap * BLOCK_SIZE + 4 + 4 * (index // 32)
        struct.pack_into(">I", image, at,
                         struct.unpack_from(">I", image, at)[0]
                         | 1 << index % 32)
    put(root, _LN_USED, ">I", following[0] - 2)
    put(root, _LN_FS_TYPE, ">4s", b"DOS" + bytes([dos_type]))
    for number, at in sums.items():
        block = image[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE]
        put(number, at, ">I", _spec_sum(block, at))
    return bytes(image)


def _spec_lnfs_entry(image: bytes, path: str) -> int:
    """The header block of `path` on a long-name image, by hash chain and by
    the name at the start of the merged field."""
    number = 880
    for part in path.strip("/").split("/"):
        encoded = part.encode("latin1")
        want = bytes(_spec_upper(c, True) for c in encoded)
        number = _spec_u32(image, number, 24 + 4 * _spec_hash(encoded, True))
        while number:
            at = number * BLOCK_SIZE + _LN_NAC
            name = image[at + 1:at + 1 + image[at]]
            if bytes(_spec_upper(c, True) for c in name) == want:
                break
            number = _spec_u32(image, number, BLOCK_SIZE - 16)
        assert number, f"{part} is not in its hash chain"
    return number


def _spec_lnfs_read(image: bytes, path: str) -> bytes:
    header = _spec_lnfs_entry(image, path)
    ffs = image[3] == 7
    out = bytearray()
    for index in range(_spec_u32(image, header, 8)):
        number = _spec_u32(image, header, BLOCK_SIZE - 204 - 4 * index)
        if ffs:
            out += image[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE]
        else:
            used = _spec_u32(image, number, 12)
            out += image[number * BLOCK_SIZE + 24:
                         number * BLOCK_SIZE + 24 + used]
    return bytes(out[:_spec_u32(image, header, BLOCK_SIZE - 188)])


def _spec_lnfs_comment(image: bytes, path: str) -> bytes:
    header = _spec_lnfs_entry(image, path)
    at = header * BLOCK_SIZE + _LN_NAC
    comment_at = at + 1 + image[at]
    if image[comment_at]:
        return image[comment_at + 1:comment_at + 1 + image[comment_at]]
    note = _spec_u32(image, header, _LN_COMMENT_BLOCK)
    if not note:
        return b""
    assert _spec_u32(image, note, 0) == 64
    assert _spec_u32(image, note, 8) == header
    return image[note * BLOCK_SIZE + 25:
                 note * BLOCK_SIZE + 25 + image[note * BLOCK_SIZE + 24]]


#: A name long enough that a 79-character comment no longer fits beside it.
COMMENTED = "a file commented at length, with a long name"
#: What `_spec_lnfs_image` lays out for the reader tests: names past 30
#: characters at the root and in a drawer, an accented name, a comment that
#: fits beside its name and one that needs its own block.
SPEC_LNFS = [
    ("short", b"one", b""),
    (LONGEST, _ffs_payload(1500, 3), b""),
    ("A drawer whose name runs past thirty", None, b"drawer note"),
    ("A drawer whose name runs past thirty/inner file with a long name.cha",
     _ffs_payload(700, 5), b"hi"),
    ("caf\xe9 au lait with sugar, and a long name", b"accented", b""),
    (COMMENTED, b"text", b"c" * 79),
    ("empty", b"", b""),
]


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_spec_built_long_name_disk_reads_back(dos_type):
    """The reader against a long-name image it did not write: every name,
    every file, and a clean `verify()`."""
    image = _spec_lnfs_image(dos_type, SPEC_LNFS)
    disk = AmigaDisk(image)
    assert disk.volume_name == "REF" and disk.ffs is (dos_type == 7)
    assert not disk.dircache
    assert disk.verify() == []
    files = {"/" + path: data for path, data, _ in SPEC_LNFS
             if data is not None}
    assert {path: disk.read_file(path) for path, _ in disk.walk()} == files
    assert [path for path, _ in disk.walk_dirs()] == [
        "/A drawer whose name runs past thirty"]
    assert disk.read_file("CAF\xc9 AU LAIT WITH SUGAR, AND A LONG NAME") == (
        b"accented")
    for path, data, comment in SPEC_LNFS:
        assert _spec_lnfs_comment(image, path) == comment, path


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_long_name_disk_this_module_writes_reads_by_the_spec(dos_type):
    """The writer against a reader it does not share: names in the merged
    field with an empty comment after them and no comment block, the date at
    0x1C4, the root's DOS type and used-block count."""
    disk = AmigaDisk.blank("LONGNAMES", dos_type=dos_type)
    drawer = "A drawer whose name runs past thirty"
    disk.make_dir(drawer, when=WHEN)
    files = {LONGEST: _ffs_payload(1500, 3),
             f"{drawer}/inner file with a long name.cha": _ffs_payload(700, 5),
             "caf\xe9 au lait with sugar, and a long name": b"accented",
             "empty": b""}
    for path, data in files.items():
        disk.write_file(path, data, when=WHEN)
    assert disk.verify() == []
    image = disk.to_bytes()
    days = (WHEN.date() - datetime.date(1978, 1, 1)).days
    for path, data in files.items():
        assert _spec_lnfs_read(image, path) == data, path
        assert _spec_lnfs_comment(image, path) == b""
        header = _spec_lnfs_entry(image, path)
        assert _spec_u32(image, header, _LN_COMMENT_BLOCK) == 0
        at = header * BLOCK_SIZE + _LN_NAC
        name = path.rpartition("/")[2].encode("latin1")
        assert image[at:at + 112] == (
            bytes([len(name)]) + name).ljust(112, b"\0")
        assert struct.unpack_from(">III", image,
                                  header * BLOCK_SIZE + _LN_DATE) == (
            days, 12 * 60 + 34, 56 * 50)
    assert _spec_lnfs_entry(image, drawer) == disk.lookup(drawer).block
    assert image[880 * BLOCK_SIZE + _LN_FS_TYPE:
                 880 * BLOCK_SIZE + _LN_FS_TYPE + 4] == (
        b"DOS" + bytes([dos_type]))
    assert _spec_u32(image, 880, _LN_USED) == _spec_used(image)
    assert image[880 * BLOCK_SIZE + BLOCK_SIZE - 80:
                 880 * BLOCK_SIZE + BLOCK_SIZE - 70] == b"\x09LONGNAMES"


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_the_root_counts_used_blocks_after_every_write(dos_type):
    disk = AmigaDisk.blank(dos_type=dos_type)
    assert _spec_u32(disk.to_bytes(), 880, _LN_USED) == 2
    steps = [lambda: disk.make_dir("save", when=WHEN),
             lambda: disk.write_file("save/big", _ffs_payload(60000), when=WHEN),
             lambda: disk.write_file("save/big", b"small", when=WHEN),
             lambda: disk.write_file("loose", b"x" * 3000, when=WHEN),
             lambda: disk.remove_file("save/big")]
    for step in steps:
        step()
        image = disk.to_bytes()
        assert _spec_u32(image, 880, _LN_USED) == _spec_used(image)
        assert disk.verify() == []


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_long_name_disk_has_no_directory_cache(dos_type):
    """`DOS\\6` and `DOS\\7` carry the cache bit's value in their number and
    are not cache disks: no drawer gets a cache block."""
    disk = AmigaDisk.blank(dos_type=dos_type)
    disk.make_dir("save", when=WHEN)
    disk.write_file("save/file", b"data", when=WHEN)
    image = disk.to_bytes()
    assert _spec_u32(image, 880, BLOCK_SIZE - 8) == 0
    assert _spec_u32(image, disk.lookup("save").block, BLOCK_SIZE - 8) == 0
    # Boot blocks, root, bitmap, then the drawer, the file header and one
    # data block.
    assert disk.free_count() == 1760 - 2 - 2 - 3


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_long_name_up_to_106_characters_is_written(dos_type):
    disk = AmigaDisk.blank(dos_type=dos_type)
    disk.write_file(LONGEST, b"long", when=WHEN)
    disk.make_dir(LONGEST[1:] + "D", when=WHEN)
    assert disk.read_file(LONGEST.upper()) == b"long"
    assert disk.lookup(LONGEST[1:] + "d").is_dir
    assert disk.verify() == []


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
@pytest.mark.parametrize("name", ["", LONGEST + "x", "with/slash", "a:b"])
def test_a_name_a_long_name_disk_cannot_store_is_refused(dos_type, name):
    disk = AmigaDisk.blank(dos_type=dos_type)
    before = disk.to_bytes()
    with pytest.raises(AmigaDiskError):
        disk.write_file(name, b"x", when=WHEN)
    with pytest.raises(AmigaDiskError):
        disk.make_dir(name, when=WHEN)
    assert disk.to_bytes() == before


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_long_name_disk_keeps_a_30_character_volume_name(dos_type):
    """The root does not move to the long layout, so its name stays at 30."""
    AmigaDisk.blank("v" * 30, dos_type=dos_type)
    with pytest.raises(AmigaDiskError):
        AmigaDisk.blank("v" * 31, dos_type=dos_type)


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
@pytest.mark.parametrize("operation", ("replace", "remove"))
def test_a_file_s_comment_block_goes_back_with_the_file(dos_type, operation):
    """A file AmigaOS gave a long comment owns a type-64 block; replacing or
    removing the file gives that block back, and nothing else is lost."""
    image = _spec_lnfs_image(dos_type, SPEC_LNFS)
    disk = AmigaDisk(image)
    note = _spec_u32(image, _spec_lnfs_entry(image, COMMENTED),
                     _LN_COMMENT_BLOCK)
    assert note and not disk.is_free(note)
    if operation == "replace":
        disk.write_file(COMMENTED, b"new text", when=WHEN)
        assert disk.read_file(COMMENTED) == b"new text"
    else:
        disk.remove_file(COMMENTED)
    assert disk.is_free(note)
    assert disk.verify() == []
    after = disk.to_bytes()
    assert _spec_u32(after, 880, _LN_USED) == _spec_used(after)
    for path, data, _ in SPEC_LNFS:
        if data is not None and path != COMMENTED:
            assert disk.read_file(path) == data


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_comment_pointer_at_another_block_is_refused_and_changes_nothing(
        dos_type):
    """Freeing a block a header only claims to own would free somebody
    else's; the write is refused, every byte stays, and verify says why."""
    image = bytearray(_spec_lnfs_image(dos_type, SPEC_LNFS))
    header = _spec_lnfs_entry(image, COMMENTED)
    victim = _spec_lnfs_entry(image, "short")
    struct.pack_into(">I", image, header * BLOCK_SIZE + _LN_COMMENT_BLOCK,
                     victim)
    struct.pack_into(">I", image, header * BLOCK_SIZE + 20, 0)
    block = image[header * BLOCK_SIZE:(header + 1) * BLOCK_SIZE]
    struct.pack_into(">I", image, header * BLOCK_SIZE + 20,
                     _spec_sum(block, 20))
    disk = AmigaDisk(image)
    assert any("comment" in p for p in disk.verify()), disk.verify()
    for attempt in (lambda: disk.remove_file(COMMENTED),
                    lambda: disk.write_file(COMMENTED, b"x")):
        with pytest.raises(AmigaDiskError):
            attempt()
        assert disk.to_bytes() == bytes(image)


def _lnfs_broken(dos_type: int, how: str,
                 value: int | None = None) -> AmigaDisk:
    """A spec-built long-name disk with one thing broken, checksums fixed.
    `value` is what `used` or `fs_type` writes into the root field."""
    image = bytearray(_spec_lnfs_image(dos_type, SPEC_LNFS))
    note = _spec_u32(image, _spec_lnfs_entry(image, COMMENTED),
                     _LN_COMMENT_BLOCK)
    number, at = 880, 20
    if how == "used":
        struct.pack_into(">I", image, 880 * BLOCK_SIZE + _LN_USED, value)
    elif how == "fs_type":
        struct.pack_into(">I", image, 880 * BLOCK_SIZE + _LN_FS_TYPE, value)
    elif how == "comment_sum":
        image[note * BLOCK_SIZE + 30] ^= 1
        return AmigaDisk(image)
    elif how == "comment_owner":
        number = note
        struct.pack_into(">I", image, note * BLOCK_SIZE + 8, 880)
    elif how == "comment_free":
        index = note - 2
        at = 881 * BLOCK_SIZE + 4 + 4 * (index // 32)
        struct.pack_into(">I", image, at,
                         struct.unpack_from(">I", image, at)[0]
                         | 1 << index % 32)
        number, at = 881, 0
        struct.pack_into(">I", image, 880 * BLOCK_SIZE + _LN_USED,
                         _spec_used(image))
        struct.pack_into(">I", image, 880 * BLOCK_SIZE + 20, 0)
        root = image[880 * BLOCK_SIZE:881 * BLOCK_SIZE]
        struct.pack_into(">I", image, 880 * BLOCK_SIZE + 20,
                         _spec_sum(root, 20))
    elif how == "name_overrun":
        number = _spec_lnfs_entry(image, "short")
        image[number * BLOCK_SIZE + _LN_NAC] = 111
    struct.pack_into(">I", image, number * BLOCK_SIZE + at, 0)
    block = image[number * BLOCK_SIZE:(number + 1) * BLOCK_SIZE]
    struct.pack_into(">I", image, number * BLOCK_SIZE + at,
                     _spec_sum(block, at))
    return AmigaDisk(image)


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
@pytest.mark.parametrize("how, says", [
    ("comment_sum", "does not sum to zero"),
    ("comment_owner", "comment"),
    ("comment_free", "marked free"),
])
def test_verify_reports_a_long_name_disk_s_own_fields(dos_type, how, says):
    problems = _lnfs_broken(dos_type, how).verify()
    assert any(says in p for p in problems), problems


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
@pytest.mark.parametrize("field, stale, says", [
    ("used", 0, "used blocks"),
    ("used", "wrong", "used blocks"),
    ("fs_type", 0, "DOS type"),
    ("fs_type", "wrong", "DOS type"),
])
def test_a_stale_root_field_is_a_warning_and_still_saves(
        dos_type, field, stale, says):
    """Nobody has read a disk AmigaOS wrote, so a root whose used-block count
    at 0x1D4 or DOS type at 0x1F0 disagrees with the bitmap or the bootblock
    -- left at zero, or wrong -- is reported as a warning and not as damage:
    the disk opens, verifies, and takes a save, and the save rewrites both."""
    image = _spec_lnfs_image(dos_type, SPEC_LNFS)
    if field == "used":
        value = 0 if stale == 0 else _spec_used(image) + 1
    else:
        value = 0 if stale == 0 else 0x444F5300 | (dos_type ^ 1)
    disk = _lnfs_broken(dos_type, field, value)
    assert disk.to_bytes() != image
    assert disk.verify() == []
    assert any(says in w for w in disk.root_warnings()), disk.root_warnings()
    assert disk.cache_warnings() == []
    disk.write_file("A drawer whose name runs past thirty/saved.cha",
                    b"party" * 100, when=WHEN)
    after = disk.to_bytes()
    assert _spec_u32(after, 880, _LN_USED) == _spec_used(after)
    assert after[880 * BLOCK_SIZE + _LN_FS_TYPE:
                 880 * BLOCK_SIZE + _LN_FS_TYPE + 4] == after[0:4]
    assert disk.verify() == [] and disk.root_warnings() == []
    reopened = AmigaDisk(after)
    assert reopened.verify() == [] and reopened.root_warnings() == []
    assert reopened.read_file(
        "A drawer whose name runs past thirty/saved.cha") == b"party" * 100
    for path, data, _ in SPEC_LNFS:
        if data is not None:
            assert reopened.read_file(path) == data, path


@pytest.mark.parametrize("dos_type", WRITABLE_TYPES)
def test_a_disk_as_written_has_no_root_warning(dos_type):
    disk = AmigaDisk.blank(dos_type=dos_type)
    disk.write_file("file", b"data", when=WHEN)
    assert disk.root_warnings() == []


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_name_longer_than_the_merged_field_holds_is_refused(dos_type):
    disk = _lnfs_broken(dos_type, "name_overrun")
    with pytest.raises(AmigaDiskError):
        list(disk.walk())
    assert disk.verify()


@pytest.mark.parametrize("dos_type", LONG_NAME_TYPES)
def test_a_save_on_a_long_name_disk_one_keeps_its_long_names(dos_type):
    """A disk AmigaOS laid out with long names takes a write into its drawer
    and keeps every other entry, long names and comments included."""
    image = _spec_lnfs_image(dos_type, SPEC_LNFS)
    disk = AmigaDisk(image)
    target = "A drawer whose name runs past thirty/added by wish.cha"
    disk.write_file(target, b"party" * 100, when=WHEN)
    after = disk.to_bytes()
    assert disk.verify() == []
    assert _spec_lnfs_read(after, target) == b"party" * 100
    for path, data, comment in SPEC_LNFS:
        if data is not None:
            assert _spec_lnfs_read(after, path) == data, path
        assert _spec_lnfs_comment(after, path) == comment, path
