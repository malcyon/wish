"""Tests for por.d64 against the real Pool of Radiance disk images."""

from __future__ import annotations

from pathlib import Path

import pytest

from por.d64 import (
    IMAGE_SIZE,
    BlockCountMismatch,
    D64,
    FileNotFoundInImage,
    InvalidImageError,
    attach_load_address,
    sector_offset,
    sectors_per_track,
    split_load_address,
)

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

PORSAVE = WORK / "PORSAVE.D64"
POOL1 = WORK / "POOL1.D64.orig"

BRUTUS = b"\x01BRUTUS"

# name, fixture file, block count, load address
SAVE_FILES = [
    (BRUTUS, "brutus.chr", 3, 0x6B00),
    (b"SAVEDGAME1", "savedgame1.bin", 9, 0x8300),
    (b"SAVEDGAME0", "savedgame0.bin", 29, 0x4900),
]


@pytest.fixture(scope="module")
def porsave_bytes() -> bytes:
    return PORSAVE.read_bytes()


@pytest.fixture()
def porsave(porsave_bytes: bytes) -> D64:
    return D64.from_bytes(porsave_bytes)


@pytest.fixture(scope="module")
def pool1_bytes() -> bytes:
    return POOL1.read_bytes()


# ---- geometry ------------------------------------------------------------


def test_geometry_totals():
    assert sum(sectors_per_track(t) for t in range(1, 36)) == 683
    assert IMAGE_SIZE == 174848


@pytest.mark.parametrize(
    "track, count",
    [(1, 21), (17, 21), (18, 19), (24, 19), (25, 18), (30, 18), (31, 17), (35, 17)],
)
def test_sectors_per_track(track, count):
    assert sectors_per_track(track) == count


def test_sector_offsets():
    assert sector_offset(1, 0) == 0
    assert sector_offset(1, 1) == 256
    assert sector_offset(2, 0) == 21 * 256
    assert sector_offset(18, 0) == 0x16500
    assert sector_offset(18, 1) == 0x16600
    assert sector_offset(35, 16) == IMAGE_SIZE - 256


def test_sector_offset_rejects_out_of_range():
    with pytest.raises(ValueError):
        sector_offset(36, 0)
    with pytest.raises(ValueError):
        sector_offset(0, 0)
    with pytest.raises(ValueError):
        sector_offset(35, 17)  # track 35 only has sectors 0..16


def test_rejects_wrong_sized_image():
    with pytest.raises(InvalidImageError):
        D64.from_bytes(b"\x00" * 1024)


# ---- directory -----------------------------------------------------------


def test_porsave_directory_lists_three_files(porsave: D64):
    entries = porsave.directory()
    assert len(entries) == 3
    assert [e.name for e in entries] == [name for name, _, _, _ in SAVE_FILES]
    assert [e.block_count for e in entries] == [blocks for _, _, blocks, _ in SAVE_FILES]
    for entry in entries:
        assert entry.is_prg
        assert entry.type_name == "PRG"
        assert entry.type_byte == 0x82
        assert entry.is_closed


def test_leading_control_byte_is_preserved(porsave: D64):
    entry = porsave.directory()[0]
    assert entry.raw_name == BRUTUS + b"\xa0" * (16 - len(BRUTUS))
    assert entry.name == BRUTUS
    assert entry.name[0] == 0x01
    assert entry.display_name == "\\x01BRUTUS"


def test_lookup_by_name_bytes_and_str(porsave: D64):
    assert porsave.entry(BRUTUS).name == BRUTUS
    assert porsave.entry("SAVEDGAME0").block_count == 29
    assert porsave.entry(b"SAVEDGAME1\xa0\xa0").name == b"SAVEDGAME1"
    assert porsave.find(b"NOPE") is None
    assert BRUTUS in porsave
    assert b"NOPE" not in porsave
    with pytest.raises(FileNotFoundInImage):
        porsave.entry(b"NOPE")


def test_directory_include_empty(porsave: D64):
    every = porsave.directory(include_empty=True)
    assert len(every) == 8  # one directory sector, eight slots
    assert sum(1 for e in every if e.is_empty) == 5


def test_pool1_directory_parses(pool1_bytes: bytes):
    disk = D64.from_bytes(pool1_bytes)
    entries = disk.directory()
    assert 90 <= len(entries) <= 110, f"unexpected entry count {len(entries)}"
    for entry in entries:
        assert len(entry.raw_name) == 16
        assert entry.name  # non-empty
        assert 1 <= entry.first_track <= 35
        assert entry.first_sector < sectors_per_track(entry.first_track)
        assert entry.block_count > 0


def test_pool1_files_are_readable_and_match_block_counts(pool1_bytes: bytes):
    disk = D64.from_bytes(pool1_bytes)
    for entry in disk.directory():
        chain = disk.sector_chain(entry)
        assert len(chain) == entry.block_count, entry.display_name
        data = disk.read_file(entry)
        assert data, entry.display_name
        assert len(chain) == D64.blocks_needed(len(data))


# ---- reading files -------------------------------------------------------


@pytest.mark.parametrize("name, fixture, blocks, load", SAVE_FILES)
def test_read_file_matches_fixture(porsave: D64, name, fixture, blocks, load):
    expected = (FIXTURES / fixture).read_bytes()
    got = porsave.read_file(name)
    assert got == expected
    assert len(porsave.sector_chain(name)) == blocks
    assert split_load_address(got)[0] == load


def test_read_file_by_entry_matches_read_by_name(porsave: D64):
    entry = porsave.entry(b"SAVEDGAME0")
    assert porsave.read_file(entry) == porsave.read_file(b"SAVEDGAME0")


def test_fixture_sizes(porsave: D64):
    sizes = {name: len(porsave.read_file(name)) for name, _, _, _ in SAVE_FILES}
    assert sizes == {BRUTUS: 582, b"SAVEDGAME1": 2050, b"SAVEDGAME0": 7170}


# ---- round trip ----------------------------------------------------------


@pytest.mark.parametrize("path", [PORSAVE, POOL1])
def test_round_trip_bytes(path: Path):
    data = path.read_bytes()
    assert D64.from_bytes(data).to_bytes() == data


def test_open_and_save_round_trip(tmp_path: Path, porsave_bytes: bytes):
    disk = D64.open(PORSAVE)
    out = tmp_path / "copy.d64"
    disk.save(out)
    assert out.read_bytes() == porsave_bytes


# ---- in-place writes -----------------------------------------------------


@pytest.mark.parametrize("name, fixture, blocks, load", SAVE_FILES)
def test_write_identical_content_is_byte_identical(
    porsave_bytes: bytes, name, fixture, blocks, load
):
    disk = D64.from_bytes(porsave_bytes)
    disk.write_file_inplace(name, disk.read_file(name))
    assert disk.to_bytes() == porsave_bytes


def test_write_all_files_identical_is_byte_identical(porsave_bytes: bytes):
    disk = D64.from_bytes(porsave_bytes)
    for entry in disk.directory():
        disk.write_file_inplace(entry, disk.read_file(entry))
    assert disk.to_bytes() == porsave_bytes


def test_write_modified_content_reads_back(porsave_bytes: bytes):
    disk = D64.from_bytes(porsave_bytes)
    original = disk.read_file(BRUTUS)
    modified = bytearray(original)
    modified[2] ^= 0xFF
    modified[-1] ^= 0xFF
    disk.write_file_inplace(BRUTUS, bytes(modified))
    assert disk.read_file(BRUTUS) == bytes(modified)
    # Other files are untouched.
    assert disk.read_file(b"SAVEDGAME0") == (FIXTURES / "savedgame0.bin").read_bytes()
    # And only the two touched bytes differ image-wide.
    diff = [
        i
        for i, (a, b) in enumerate(zip(porsave_bytes, disk.to_bytes()))
        if a != b
    ]
    assert len(diff) == 2


def test_write_shorter_within_same_block_count_is_allowed(porsave_bytes: bytes):
    disk = D64.from_bytes(porsave_bytes)
    original = disk.read_file(BRUTUS)  # 582 bytes = 3 blocks
    shorter = original[:-1]  # 581 bytes = still 3 blocks
    disk.write_file_inplace(BRUTUS, shorter)
    assert disk.read_file(BRUTUS) == shorter
    assert disk.entry(BRUTUS).block_count == 3


@pytest.mark.parametrize("delta", [-254, 254, 1000, -582])
def test_write_wrong_block_count_raises(porsave_bytes: bytes, delta: int):
    disk = D64.from_bytes(porsave_bytes)
    original = disk.read_file(BRUTUS)
    if delta < 0:
        bad = original[:delta]
    else:
        bad = original + b"\x00" * delta
    assert D64.blocks_needed(len(bad)) != 3
    with pytest.raises(BlockCountMismatch):
        disk.write_file_inplace(BRUTUS, bad)
    assert disk.to_bytes() == porsave_bytes  # nothing written


def test_blocks_needed():
    assert D64.blocks_needed(0) == 1
    assert D64.blocks_needed(1) == 1
    assert D64.blocks_needed(254) == 1
    assert D64.blocks_needed(255) == 2
    assert D64.blocks_needed(582) == 3
    assert D64.blocks_needed(2050) == 9
    assert D64.blocks_needed(7170) == 29


# ---- PRG load address ----------------------------------------------------


def test_split_and_attach_load_address(porsave: D64):
    data = porsave.read_file(b"SAVEDGAME0")
    addr, payload = split_load_address(data)
    assert addr == 0x4900
    assert len(payload) == len(data) - 2
    assert attach_load_address(addr, payload) == data


def test_load_address_helpers_validate():
    with pytest.raises(ValueError):
        split_load_address(b"\x01")
    with pytest.raises(ValueError):
        attach_load_address(0x10000, b"")
    assert attach_load_address(0x6B00, b"abc") == b"\x00\x6b" + b"abc"
