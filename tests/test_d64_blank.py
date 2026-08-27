"""Building a 1541 disk from nothing: `D64.blank` and `D64.write_file` (#118).

What would actually break if this were wrong is the game's own `LOAD SAVED
GAME` picker not listing the save, or the loader not reading the file back.
Neither can be asserted without an emulator, so these tests assert the things
that stand between here and there: the image parses, the directory lists the
file, the chain terminates where it says it does, the BAM's free count agrees
with the blocks actually taken, and -- where the player's own disks are
present -- **a disk built here is byte for byte the disk the 1541 wrote**,
outside the drive-buffer leftovers in each file's last sector.

`#119 (Play a converted DOS save in VICE, off a disk Wish built from nothing)`
is what covers the rest, and it needs an emulator.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox.d64 import (
    D64,
    DEFAULT_DISK_ID,
    DEFAULT_DISK_NAME,
    DIRECTORY_SECTOR,
    DIRECTORY_TRACK,
    ENTRIES_PER_DIR_SECTOR,
    FILE_TYPE_SEQ,
    HEADER_SECTOR,
    IMAGE_SIZE,
    PAYLOAD_PER_SECTOR,
    TRACK_COUNT,
    DirectoryFullError,
    DiskFullError,
    DuplicateFileError,
    ReadOnlyImageError,
    attach_load_address,
    sector_offset,
    sectors_per_track,
)

#: A blank 1541 disk reports this many free blocks, which is what the drive
#: prints: every sector but track 18's nineteen.
BLANKS_FREE = sum(sectors_per_track(t) for t in range(1, TRACK_COUNT + 1)
                  if t != DIRECTORY_TRACK)

#: The two files a Pool of Radiance save disk has to carry, and their payload
#: lengths -- `SAVEDGAME0` is $4900-$64FF and `SAVEDGAME1` is $8300-$8AFF.
SAVE0 = (b"SAVEDGAME0", 0x4900, 7168)
SAVE1 = (b"SAVEDGAME1", 0x8300, 2048)


def _pattern(length: int, seed: int = 0) -> bytes:
    """Bytes no sector boundary can hide a mistake in."""
    return bytes((seed + i * 7 + (i >> 8)) & 0xFF for i in range(length))


def _blocks_taken(disk: D64) -> int:
    return BLANKS_FREE - disk.blocks_free


def _used_blocks(disk: D64) -> set[tuple[int, int]]:
    used: set[tuple[int, int]] = set()
    for entry in disk.directory():
        used |= set(disk.sector_chain(entry))
    return used


# ---- a blank disk -------------------------------------------------------


def test_a_blank_disk_is_a_valid_image():
    disk = D64.blank()
    assert len(disk.to_bytes()) == IMAGE_SIZE
    assert disk.writable
    assert disk.track_count == TRACK_COUNT
    # It survives a round trip through the reader that will open it later.
    reopened = D64.from_bytes(disk.to_bytes())
    assert reopened.disk_name == DEFAULT_DISK_NAME
    assert reopened.disk_id == DEFAULT_DISK_ID
    assert reopened.directory() == []


def test_a_blank_disk_names_itself_what_it_was_told():
    disk = D64.blank(name=b"WISH SAVE", disk_id=b"W1")
    assert D64.from_bytes(disk.to_bytes()).disk_name == b"WISH SAVE"
    assert D64.from_bytes(disk.to_bytes()).disk_id == b"W1"


@pytest.mark.parametrize("name,disk_id", [
    (b"A" * 17, b"00"),     # one byte too long
    (b"OK", b"000"),        # a disk id is exactly two bytes
    (b"OK", b"0"),
])
def test_a_blank_disk_refuses_a_name_it_cannot_store(name, disk_id):
    with pytest.raises(ValueError):
        D64.blank(name=name, disk_id=disk_id)


def test_a_blank_disk_has_every_block_free_but_the_bam_and_the_directory():
    disk = D64.blank()
    assert disk.blocks_free == BLANKS_FREE
    for track in range(1, TRACK_COUNT + 1):
        expected = sectors_per_track(track)
        if track == DIRECTORY_TRACK:
            expected -= 2                       # the BAM and directory sector
        assert disk.track_free(track) == expected, track
    assert not disk.is_free(DIRECTORY_TRACK, HEADER_SECTOR)
    assert not disk.is_free(DIRECTORY_TRACK, DIRECTORY_SECTOR)


def test_a_blank_disk_leaves_every_unused_sector_zero():
    """What an unused sector reads as on fourteen of the player's fifteen disks."""
    disk = D64.blank()
    for track in range(1, TRACK_COUNT + 1):
        for sector in range(sectors_per_track(track)):
            if (track, sector) == (DIRECTORY_TRACK, HEADER_SECTOR):
                continue
            expected = bytes(256)
            if (track, sector) == (DIRECTORY_TRACK, DIRECTORY_SECTOR):
                expected = b"\x00\xff" + bytes(254)
            assert disk.read_sector(track, sector) == expected, (track, sector)


def test_a_blank_disk_ends_its_directory_chain_on_track_zero():
    disk = D64.blank()
    link = disk.read_sector(DIRECTORY_TRACK, DIRECTORY_SECTOR)[:2]
    assert link[0] == 0, "a directory chain ends on track 0, never on a sector"


# ---- writing files ------------------------------------------------------


@pytest.mark.parametrize("length", [
    1,
    PAYLOAD_PER_SECTOR - 1,
    PAYLOAD_PER_SECTOR,          # exactly one block
    PAYLOAD_PER_SECTOR + 1,      # one payload byte in the second block
    SAVE1[2] + 2,                # SAVEDGAME1 as a PRG: 9 blocks
    SAVE0[2] + 2,                # SAVEDGAME0 as a PRG: 29 blocks, two tracks
    PAYLOAD_PER_SECTOR * 40,     # spills across three tracks
])
def test_a_file_written_reads_back_byte_for_byte(length):
    disk = D64.blank()
    data = _pattern(length)
    entry = disk.write_file(b"THING", data)
    assert disk.read_file(b"THING") == data
    assert entry.block_count == D64.blocks_needed(length) == len(
        disk.sector_chain(entry))
    # And through a fresh reader, not just the object that wrote it.
    assert D64.from_bytes(disk.to_bytes()).read_file(b"THING") == data


def test_the_directory_lists_what_was_written():
    disk = D64.blank()
    disk.write_file(b"SAVEDGAME0", _pattern(SAVE0[2] + 2))
    disk.write_file(b"SAVEDGAME1", _pattern(SAVE1[2] + 2, seed=9))
    listed = D64.from_bytes(disk.to_bytes()).directory()
    assert [e.name for e in listed] == [b"SAVEDGAME0", b"SAVEDGAME1"]
    assert all(e.is_prg and e.is_closed and not e.is_locked for e in listed)
    assert [e.block_count for e in listed] == [29, 9]


def test_a_name_keeps_its_control_bytes():
    """A saved character is `\\x01BRUTUS`, not `.BRUTUS`; the prefix has to survive."""
    disk = D64.blank()
    disk.write_file(b"\x01BRUTUS", _pattern(582))
    assert D64.from_bytes(disk.to_bytes()).directory()[0].name == b"\x01BRUTUS"


def test_a_file_type_other_than_prg_is_written_as_asked():
    disk = D64.blank()
    entry = disk.write_file(b"SEQFILE", _pattern(100), file_type=FILE_TYPE_SEQ)
    assert entry.type_name == "SEQ" and entry.is_closed


def test_the_last_sector_names_its_last_valid_byte():
    """Not a next sector -- the convention that makes a short final block work."""
    disk = D64.blank()
    length = PAYLOAD_PER_SECTOR + 10
    entry = disk.write_file(b"TAIL", _pattern(length))
    track, sector = disk.sector_chain(entry)[-1]
    link = disk.read_sector(track, sector)[:2]
    assert link[0] == 0
    assert link[1] == 1 + (length - PAYLOAD_PER_SECTOR)


def test_the_bam_free_count_agrees_with_the_blocks_actually_used():
    disk = D64.blank()
    disk.write_file(SAVE1[0], attach_load_address(SAVE1[1], _pattern(SAVE1[2])))
    disk.write_file(SAVE0[0], attach_load_address(SAVE0[1], _pattern(SAVE0[2], 3)))
    used = _used_blocks(disk)
    assert len(used) == 38
    assert _blocks_taken(disk) == len(used)
    for track, sector in used:
        assert not disk.is_free(track, sector), (track, sector)
    # Nothing outside the two chains was taken.
    for track in range(1, TRACK_COUNT + 1):
        if track == DIRECTORY_TRACK:
            continue
        for sector in range(sectors_per_track(track)):
            assert disk.is_free(track, sector) is ((track, sector) not in used)


def test_a_second_file_never_lands_on_the_first_ones_blocks():
    disk = D64.blank()
    first = set(disk.sector_chain(disk.write_file(b"ONE", _pattern(9000))))
    second = set(disk.sector_chain(disk.write_file(b"TWO", _pattern(9000, 5))))
    assert not first & second
    assert disk.read_file(b"ONE") == _pattern(9000)
    assert disk.read_file(b"TWO") == _pattern(9000, 5)


def test_a_name_already_on_the_disk_is_refused():
    disk = D64.blank()
    disk.write_file(b"THING", _pattern(300))
    before = disk.to_bytes()
    with pytest.raises(DuplicateFileError):
        disk.write_file(b"THING", _pattern(300, 1))
    assert disk.to_bytes() == before


@pytest.mark.parametrize("name", [b"", b"A" * 17, b"BAD\xa0NAME"])
def test_a_name_a_1541_cannot_store_is_refused(name):
    with pytest.raises(ValueError):
        D64.blank().write_file(name, _pattern(10))


def test_a_read_only_variant_refuses_to_be_written():
    """A 40-track rip is somebody else's disk, not a save disk."""
    disk = D64.from_bytes(bytes(196608))
    assert not disk.writable
    with pytest.raises(ReadOnlyImageError):
        disk.write_file(b"THING", _pattern(10))


# ---- running out of room ------------------------------------------------


def test_a_disk_too_full_is_left_exactly_as_it_was():
    disk = D64.blank()
    disk.write_file(b"REAL", _pattern(1000))
    before = disk.to_bytes()
    too_big = _pattern(PAYLOAD_PER_SECTOR * (BLANKS_FREE + 1))
    with pytest.raises(DiskFullError):
        disk.write_file(b"TOOBIG", too_big)
    assert disk.to_bytes() == before, "a half-written file is a corrupt disk"
    assert disk.read_file(b"REAL") == _pattern(1000)


def test_the_disk_fills_to_the_last_block_and_no_further():
    disk = D64.blank()
    # One directory sector holds eight entries, so eight files fit before the
    # directory has to grow -- and a grown directory costs a block on track 18,
    # which is not counted in blocks_free. Keep it to eight.
    each = BLANKS_FREE // ENTRIES_PER_DIR_SECTOR
    for i in range(ENTRIES_PER_DIR_SECTOR):
        disk.write_file(f"F{i}".encode(), _pattern(each * PAYLOAD_PER_SECTOR, i))
    assert disk.blocks_free == BLANKS_FREE - each * ENTRIES_PER_DIR_SECTOR
    with pytest.raises(DiskFullError):
        disk.write_file(b"OVER", _pattern((disk.blocks_free + 1)
                                          * PAYLOAD_PER_SECTOR))


# ---- growing the directory ----------------------------------------------


def test_the_directory_grows_past_eight_entries():
    disk = D64.blank()
    for i in range(20):
        disk.write_file(f"FILE{i:02d}".encode(), _pattern(10, i))
    listed = D64.from_bytes(disk.to_bytes()).directory()
    assert [e.name for e in listed] == [f"FILE{i:02d}".encode() for i in range(20)]
    assert len({(e.dir_track, e.dir_sector) for e in listed}) == 3
    for entry in listed:
        assert not disk.is_free(entry.dir_track, entry.dir_sector)


def test_a_grown_directory_sector_still_ends_the_chain_on_track_zero():
    disk = D64.blank()
    for i in range(9):
        disk.write_file(f"FILE{i}".encode(), _pattern(10, i))
    last = disk.directory()[-1]
    assert disk.read_sector(last.dir_track, last.dir_sector)[0] == 0


def test_the_directory_track_is_all_a_1541_directory_gets():
    """144 files: eighteen directory sectors, because sector 0 is the BAM."""
    disk = D64.blank()
    for i in range(144):
        disk.write_file(f"F{i:03d}".encode(), _pattern(10, i))
    assert len(disk.directory()) == 144
    with pytest.raises(DirectoryFullError):
        disk.write_file(b"ONEMORE", _pattern(10))


# ---- against the disks the drive actually wrote --------------------------
#
# These need the player's own save disks and skip cleanly without them, which
# is most of CI. `tests/gamedata.py` is how they are found; no game bytes are
# committed.


#: The shape this check needs: a save disk holding the two save files and
#: nothing else.  Two of the player's fifteen carry staged character files as
#: well and are skipped rather than special-cased -- they are also the two
#: written at interleave 10, so a disk built at 16 would differ from them
#: everywhere, which is a fact about the drive and not about this code.
SAVE_PAIR = [b"SAVEDGAME1", b"SAVEDGAME0"]


def _reproduces(path) -> set[int]:
    """Which bytes of `path` a disk built here does not reproduce."""
    real = D64.open(path)
    built = D64.blank(name=real.disk_name, disk_id=real.disk_id)
    for name in SAVE_PAIR:
        built.write_file(name, real.read_file(name))

    slack = set()
    for name in SAVE_PAIR:
        chain = real.sector_chain(name)
        tail = len(real.read_file(name)) - (len(chain) - 1) * PAYLOAD_PER_SECTOR
        last = sector_offset(*chain[-1])
        slack |= set(range(last + 2 + tail, last + 256))

    mine, theirs = built.to_bytes(), real.to_bytes()
    return {i for i in range(IMAGE_SIZE) if mine[i] != theirs[i]} - slack


@gamedata.needs_disks
def test_a_built_disk_matches_the_ones_the_1541_wrote():
    """The strongest structural check there is without an emulator, over
    every save disk the player has rather than one of them.

    Take the two files off a save the game itself wrote, put them on a disk
    built here, and the images agree everywhere except the slack after each
    file's last payload byte -- which is the drive's own buffer, written out
    because a 1541 writes whole 256-byte sectors.

    **The sample size is part of the finding**, so it is counted rather than
    assumed: this was written against `PORSAVE13` alone and reported n=1 with
    fifteen disks beside it.  Thirteen of Donald's fifteen are of the shape
    `SAVE_PAIR` describes and all thirteen reproduce.
    """
    checked = []
    for path in gamedata.save_disks():
        if [e.name for e in D64.open(path).directory()] != SAVE_PAIR:
            continue
        differ = _reproduces(path)
        assert not differ, (
            f"{path.name}: {len(differ)} bytes differ outside the "
            f"final-sector slack")
        checked.append(path.name)
    assert len(checked) >= 2, f"too small a sample to mean anything: {checked}"


@gamedata.needs_disks
def test_the_engines_own_save_files_survive_a_round_trip():
    """The payloads the game wrote, back off a disk this module built."""
    real = D64.open(gamedata.save_disk("PORSAVE13"))
    built = D64.blank()
    for name in (b"SAVEDGAME1", b"SAVEDGAME0"):
        built.write_file(name, real.read_file(name))
    reopened = D64.from_bytes(built.to_bytes())
    for name, load, payload in (SAVE1, SAVE0):
        raw = reopened.read_file(name)
        assert raw == real.read_file(name)
        assert len(raw) == payload + 2
        assert raw[0] | (raw[1] << 8) == load
        assert reopened.entry(name).block_count == real.entry(name).block_count
        assert reopened.entry(name).type_byte == real.entry(name).type_byte


@gamedata.needs_disks
def test_a_built_disk_lays_its_directory_out_the_way_the_drive_does():
    """Thirteen directory sectors, against a disk with 103 files on it."""
    pool = D64.open(gamedata.game_disk("POOL1"))
    want, (track, sector) = [], (DIRECTORY_TRACK, DIRECTORY_SECTOR)
    while track:
        want.append((track, sector))
        track, sector = pool.read_sector(track, sector)[:2]

    built = D64.blank()
    for i in range(len(pool.directory())):
        built.write_file(f"F{i:03d}".encode(), b"\x01\x08hi")
    assert built._directory_chain() == want
