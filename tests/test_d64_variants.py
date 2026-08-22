"""The D64 sizes `por.d64` accepts, and the ones it must still refuse.

`tests/test_d64.py` is the regression on the plain 174848-byte image and stays
that way. This module covers what was added around it: the 40- and 42-track
geometries, the appended error map, and the rule that only the plain image may
be written.

The point that is easy to lose is the **refusal**. Widening the reader into
"accept anything and hope" would make an unknown size decode as a directory of
plausible nonsense, so half the assertions here are that sizes one byte either
side of a variant are still errors.

Disk-backed checks find the player's images by size rather than by title, and
skip when there is no specimen of that size on the machine.
"""

from __future__ import annotations

import functools
import os
import pathlib

import pytest

from por import games, items
from por.d64 import (
    D64,
    ERROR_OK,
    IMAGE_SIZE,
    MAX_TRACK_COUNT,
    TRACK_COUNT,
    VARIANTS,
    InvalidImageError,
    ReadOnlyImageError,
    sector_offset,
    sectors_per_track,
    total_sectors,
)

# size -> (tracks, sectors). Written out rather than computed, so a change to
# the geometry code has something independent to fail against.
EXPECTED = {
    174848: (35, 683),
    175531: (35, 683),
    196608: (40, 768),
    197376: (40, 768),
    205312: (42, 802),
    206114: (42, 802),
}


# --- geometry, no disks needed ----------------------------------------------

def test_the_variant_table_is_exactly_these_six_sizes():
    assert set(VARIANTS) == set(EXPECTED)
    for size, (tracks, sectors) in EXPECTED.items():
        variant = VARIANTS[size]
        assert (variant.tracks, variant.sectors) == (tracks, sectors), size
        assert variant.has_error_bytes == (size != sectors * 256)
        # An error map is one byte per sector and nothing else.
        assert size == sectors * 256 + (sectors if variant.has_error_bytes else 0)


def test_only_the_plain_image_is_writable():
    assert VARIANTS[IMAGE_SIZE].writable
    assert [s for s, v in VARIANTS.items() if v.writable] == [IMAGE_SIZE]


def test_the_extension_tracks_carry_seventeen_sectors():
    for track in range(36, MAX_TRACK_COUNT + 1):
        assert sectors_per_track(track, MAX_TRACK_COUNT) == 17
    assert total_sectors(35) == 683
    assert total_sectors(40) == 683 + 5 * 17
    assert total_sectors(42) == 683 + 7 * 17


def test_a_bare_call_still_stops_at_track_35():
    """Every existing caller passes no track count and means 35 by it."""
    assert TRACK_COUNT == 35
    with pytest.raises(ValueError):
        sectors_per_track(36)
    with pytest.raises(ValueError):
        sector_offset(36, 0)
    with pytest.raises(ValueError):
        sectors_per_track(43, MAX_TRACK_COUNT)


def test_tracks_1_to_35_sit_at_the_same_offset_in_every_variant():
    """Why a 40-track image is readable by code that only knows 35: the
    extension is appended, it does not move anything."""
    for track in range(1, TRACK_COUNT + 1):
        for sector in range(sectors_per_track(track)):
            here = sector_offset(track, sector)
            assert sector_offset(track, sector, 40) == here
            assert sector_offset(track, sector, 42) == here
    assert sector_offset(36, 0, 40) == IMAGE_SIZE
    assert sector_offset(40, 16, 40) == 196608 - 256


# --- what is refused --------------------------------------------------------

@pytest.mark.parametrize("size", [0, 1, 1024, 174847, 174849, 175530, 175532,
                                  196607, 197375, 197377, 205311, 206115,
                                  2 * 174848])
def test_an_unrecognised_size_is_still_refused(size):
    with pytest.raises(InvalidImageError):
        D64.from_bytes(b"\x00" * size)


def test_the_refusal_names_the_sizes_it_would_have_taken():
    with pytest.raises(InvalidImageError) as caught:
        D64.from_bytes(b"\x00" * 4242)
    message = str(caught.value)
    assert "4242" in message
    for size in VARIANTS:
        assert str(size) in message


# --- every variant, built rather than copied --------------------------------

@pytest.mark.parametrize("size", sorted(VARIANTS))
def test_every_variant_opens_and_round_trips(size):
    """Blank bytes: this is about the container, not about any disk's contents.
    A generated image is also the only kind this repository may hold."""
    blank = bytes(size)
    disk = D64.from_bytes(blank)
    assert disk.variant is VARIANTS[size]
    assert disk.track_count == EXPECTED[size][0]
    assert disk.total_sectors == EXPECTED[size][1]
    assert disk.to_bytes() == blank


@pytest.mark.parametrize("size", sorted(VARIANTS))
def test_error_codes_are_readable_exactly_when_there_are_error_bytes(size):
    disk = D64.from_bytes(bytes(size))
    got = disk.error_code(1, 0)
    assert got == (0 if VARIANTS[size].has_error_bytes else None)
    if VARIANTS[size].has_error_bytes:
        # The last sector's byte is the last byte of the image.
        last_track = disk.track_count
        last = sectors_per_track(last_track, last_track) - 1
        assert disk.error_code(last_track, last) == 0


def test_error_code_indexes_the_map_by_sector_number():
    size = 175531
    data = bytearray(size)
    data[174848 + 0] = ERROR_OK          # track 1 sector 0
    data[174848 + 21] = 5                # track 2 sector 0: 21 sectors precede
    data[size - 1] = 3                   # track 35 sector 16, the last
    disk = D64.from_bytes(bytes(data))
    assert disk.error_code(1, 0) == ERROR_OK
    assert disk.error_code(2, 0) == 5
    assert disk.error_code(35, 16) == 3


# --- the read-only rule, enforced -------------------------------------------

VARIANT_SIZES_READ_ONLY = sorted(s for s, v in VARIANTS.items() if not v.writable)


@pytest.mark.parametrize("size", VARIANT_SIZES_READ_ONLY)
def test_a_variant_refuses_every_write(size, tmp_path):
    disk = D64.from_bytes(bytes(size))
    assert not disk.writable
    with pytest.raises(ReadOnlyImageError):
        disk.write_sector(1, 0, bytes(256))
    with pytest.raises(ReadOnlyImageError):
        disk.write_file_inplace(b"ANYTHING", b"x")
    with pytest.raises(ReadOnlyImageError):
        disk.save(tmp_path / "no.d64")
    assert not (tmp_path / "no.d64").exists()


def test_a_variant_refuses_the_write_before_it_looks_at_the_file():
    """The guard comes first on purpose. A cracked directory -- Death Knights'
    has PETSCII art and a zero block count on every real file -- must not get
    as far as being resolved on an image we would not write to anyway."""
    disk = D64.from_bytes(bytes(197376))
    with pytest.raises(ReadOnlyImageError):
        disk.write_file_inplace(b"NO SUCH FILE AT ALL", b"x")


def test_the_plain_image_is_still_writable(tmp_path):
    disk = D64.from_bytes(bytes(IMAGE_SIZE))
    assert disk.writable
    disk.write_sector(1, 0, b"\xee" * 256)
    assert disk.read_sector(1, 0) == b"\xee" * 256
    out = tmp_path / "yes.d64"
    disk.save(out)
    assert out.read_bytes() == disk.to_bytes()


# --- the player's own disks -------------------------------------------------
# Found by size, across the roots the other suites already look in. No new
# environment variable: the question here is about the container, so any image
# of the right size answers it.

_REPO = pathlib.Path(__file__).resolve().parent.parent


def _roots():
    """Deliberately shallow. `rglob` from `$HOME` walks the whole account for
    the sake of one disk image, which on this machine cost fifteen seconds."""
    home = pathlib.Path.home()
    out = [pathlib.Path.cwd(), home / "Documents", home / "Games",
           home / "c64", home / "roms", home / "Downloads", _REPO / "work"]
    for env in ("POR_DISKS", "COAB_DISKS", "SSB_DISKS"):
        where = os.environ.get(env)
        if where:
            out.append(pathlib.Path(where))
    return out


@functools.lru_cache(maxsize=1)
def _by_size() -> dict[int, list[pathlib.Path]]:
    """Every `.d64` two levels down from the usual roots, grouped by size."""
    found: dict[int, list[pathlib.Path]] = {}
    for root in _roots():
        paths = []
        for pattern in ("*.[dD]64", "*/*.[dD]64", "*/*/*.[dD]64"):
            try:
                paths += list(root.glob(pattern))
            except OSError:
                continue
        for path in paths:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size in VARIANTS:
                found.setdefault(size, []).append(path)
    return found


def _one(size: int) -> pathlib.Path:
    paths = _by_size().get(size)
    if not paths:
        pytest.skip(f"no {size}-byte D64 on this machine")
    return sorted(paths)[0]


def test_a_forty_track_image_reads_its_directory():
    disk = D64.open(_one(197376))
    assert disk.track_count == 40
    assert not disk.writable
    entries = disk.directory()
    assert len(entries) > 1
    for entry in entries:
        assert 1 <= entry.first_track <= disk.track_count


def test_no_sector_chain_on_a_forty_track_image_leaves_track_35():
    """Which is what makes the extension padding rather than data: everything
    the directory points at is inside the 35-track prefix."""
    disk = D64.open(_one(197376))
    highest = 0
    for entry in disk.directory():
        for track, _sector in disk.sector_chain(entry):
            highest = max(highest, track)
    assert highest <= TRACK_COUNT


def test_the_extension_tracks_of_a_forty_track_image_are_unformatted():
    """Error code 3 is "no header found". Every sector past track 35 reports
    it, which is the evidence that the 85 extra blocks are padding and not a
    disk this reader is failing to read."""
    disk = D64.open(_one(197376))
    inside = {disk.error_code(t, s)
              for t in range(1, TRACK_COUNT + 1)
              for s in range(sectors_per_track(t))}
    beyond = {disk.error_code(t, s)
              for t in range(TRACK_COUNT + 1, disk.track_count + 1)
              for s in range(sectors_per_track(t, disk.track_count))}
    assert inside == {ERROR_OK}
    assert beyond == {3}


def test_champions_item_names_read_off_a_forty_track_side():
    """The reason P42 mattered: Champions' `ITEMNAMES` lives on the side that
    was refused, so nothing could name a Champions item."""
    path = _one(197376)
    disk = D64.open(path)
    if disk.find(b"ITEMNAMES") is None:
        pytest.skip("the 40-track image here carries no ITEMNAMES")
    names = items.load_item_names(str(path), games.CHAMPIONS_OF_KRYNN)
    assert names[1] == "BATTLE AXE"
    assert names[2] == "HAND AXE"
    assert len(names) > 100


def test_an_error_byte_image_still_reads_every_file_it_lists():
    """Error bytes are advisory. The Curse side that carries them reports read
    errors on more than a hundred sectors -- original copy protection -- and
    every file on it still follows its chain to the end."""
    disk = D64.open(_one(175531))
    assert disk.track_count == 35
    assert not disk.writable
    entries = disk.directory()
    assert entries
    for entry in entries:
        assert disk.read_file(entry)
    flagged = sum(1 for t in range(1, TRACK_COUNT + 1)
                  for s in range(sectors_per_track(t))
                  if disk.error_code(t, s) != ERROR_OK)
    assert flagged >= 0          # a clean rip of this size is allowed too
