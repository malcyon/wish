"""Tests for por.geo, the GEO map geometry.

The fixture is GEO04 off POOL5. The live game disks are used only for the
whole-corpus checks, which skip when they are not mounted.
"""

import pathlib

import pytest

from por.geo import (GEO_SIZE, GRID, LOCKED, NORTH, EAST, SOUTH, WEST, SOLID,
                     WIZARD_LOCKED, Geo, GeoError, load_geo_files)

DISKS = "/home/donald/c64/Pool of Radiance Disks"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/POOL5.D64").exists(),
                                reason="needs the game disks")


@pytest.fixture
def geo():
    return Geo.from_bytes((FIXTURES / "GEO04.bin").read_bytes())


def test_a_geo_file_is_four_planes(geo):
    assert len(geo.to_bytes()) == GEO_SIZE


def test_a_short_payload_is_rejected():
    with pytest.raises(GeoError):
        Geo(b"\x00" * 100)


def test_the_prg_load_address_is_stripped():
    payload = (FIXTURES / "GEO04.bin").read_bytes()
    assert Geo.from_bytes(b"\x00\x04" + payload).to_bytes() == payload


def test_edges_are_reciprocal(geo):
    agree, total = geo.reciprocity()
    assert agree / total > 0.95


def test_north_and_east_share_a_byte(geo):
    """The four edges of a square are not adjacent in the file: N and E are the
    two nibbles of one byte in plane 0, S and W of another 256 bytes away."""
    raw = geo.to_bytes()
    for x, y in ((0, 0), (7, 9), (15, 15)):
        i = x + (y << 4)
        assert geo.wall(x, y, NORTH) == raw[i] >> 4
        assert geo.wall(x, y, EAST) == raw[i] & 0x0F
        assert geo.wall(x, y, SOUTH) == raw[0x100 + i] >> 4
        assert geo.wall(x, y, WEST) == raw[0x100 + i] & 0x0F


def test_an_edge_with_no_wall_art_is_passable_whatever_its_bits_say(geo):
    """The engine's order of tests, and the thing five failed readings missed."""
    found = False
    for y in range(GRID):
        for x in range(GRID):
            for d in (NORTH, EAST, SOUTH, WEST):
                if geo.wall(x, y, d) == 0 and geo.barrier(x, y, d) == SOLID:
                    found = True
                    assert geo.is_passable(x, y, d)
    assert found, "no bare edge carrying a solid bit -- fixture cannot test this"


def test_a_wall_with_a_solid_bit_blocks(geo):
    blocked = [(x, y, d)
               for y in range(GRID) for x in range(GRID)
               for d in (NORTH, EAST, SOUTH, WEST)
               if geo.wall(x, y, d) and geo.barrier(x, y, d) == SOLID]
    assert blocked
    for x, y, d in blocked:
        assert not geo.is_passable(x, y, d)
        assert geo.door(x, y, d) is None


def test_doors_are_walls_you_can_walk_through(geo):
    doors = [(x, y, d)
             for y in range(GRID) for x in range(GRID)
             for d in (NORTH, EAST, SOUTH, WEST)
             if geo.door(x, y, d) is not None]
    assert doors
    for x, y, d in doors:
        assert geo.wall(x, y, d) != 0
        assert geo.is_passable(x, y, d)


def test_wallset_splits_the_nibble_into_set_and_slice(geo):
    for y in range(GRID):
        for x in range(GRID):
            for d in (NORTH, EAST, SOUTH, WEST):
                v = geo.wall(x, y, d)
                if v == 0:
                    assert geo.wallset(x, y, d) is None
                else:
                    wallset, slice_ = geo.wallset(x, y, d)
                    assert v == wallset * 5 + slice_ + 1


def test_the_grid_is_bounded(geo):
    with pytest.raises(IndexError):
        geo.wall(GRID, 0, NORTH)
    with pytest.raises(IndexError):
        geo.attributes(0, -1)


def test_a_floor_plan_renders_with_a_marked_square(geo):
    text = geo.to_text(mark={(3, 11): "@"})
    lines = text.split("\n")
    assert len(lines) == 2 * GRID + 1
    assert "@" in text
    assert all(len(line) == len(lines[0]) for line in lines)


def test_walkable_route_rejects_a_diagonal(geo):
    assert not geo.walkable_route([(0, 0), (1, 1)])


@game_disks
def test_every_geo_file_on_the_disks_parses_and_is_reciprocal():
    """13793 of 13920 shared edges agree across all 29 files. A reading that
    conflates wall art with passability scores about 0.3."""
    agree = total = files = 0
    for disk in list(range(1, 9)) + ["BOOT"]:
        for _, g in load_geo_files(f"{DISKS}/POOL{disk}.D64").items():
            a, t = g.reciprocity()
            agree, total, files = agree + a, total + t, files + 1
    assert files == 29
    assert (agree, total) == (13793, 13920)


@game_disks
def test_locked_doors_are_rare_and_wizard_locked_rarer():
    counts = {SOLID: 0, 1: 0, LOCKED: 0, WIZARD_LOCKED: 0}
    for disk in list(range(1, 9)) + ["BOOT"]:
        for _, g in load_geo_files(f"{DISKS}/POOL{disk}.D64").items():
            for y in range(GRID):
                for x in range(GRID):
                    for d in (NORTH, EAST, SOUTH, WEST):
                        counts[g.barrier(x, y, d)] += 1
    assert counts == {SOLID: 26590, 1: 2962, LOCKED: 130, WIZARD_LOCKED: 14}
