"""`por.amiga_adf` -- the Amiga filesystem, read and written (#36).

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

from __future__ import annotations

import datetime
import os
import pathlib
import struct

import pytest

from por.amiga_adf import (
    BLOCK_SIZE,
    HASH_TABLE_SIZE,
    OFS_DATA_SIZE,
    AmigaDisk,
    AmigaDiskError,
    block_checksum,
    hash_name,
)

WHEN = datetime.datetime(1991, 6, 4, 12, 34, 56)


def real_disks() -> list[pathlib.Path]:
    where = os.environ.get("AMIGA_DISKS")
    if not where:
        pytest.skip("no Amiga disk images; set $AMIGA_DISKS")
    found = sorted(p for p in pathlib.Path(where).rglob("*.adf") if p.is_file())
    if not found:
        pytest.skip(f"no .adf under {where}")
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


def test_an_ffs_image_is_refused_by_name_rather_than_misread():
    data = bytearray(AmigaDisk.blank().to_bytes())
    data[3] = 1
    with pytest.raises(AmigaDiskError, match="FFS"):
        AmigaDisk(data)


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

    Measured under WinUAE (#36, `work/amiga/p36/shots/`): one small file in
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
