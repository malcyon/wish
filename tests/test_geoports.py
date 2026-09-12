"""What the same Gold Box area holds on each port that shipped it (#443).

Three of Curse of the Azure Bonds' sixteen maps are not byte-identical between
the C64 disks and the Amiga disks. These pin which three, how far apart they
are, and -- the part a player would feel -- that `ResidentGeo` still names the
area when the maps it is holding came off the other port's disks.

**No map is in this repository.** Every byte here is read at run time off the
player's own disks by `tools/geoports.py`, and every test skips when they are
not on the machine. That means a bare checkout proves less; `AGENTS.md` makes
that trade deliberately.

The one number stated as a constant is the **two bytes** each of the three
differ by, and it is a claim about the game's shipped data rather than about
this machine: three rips of the C64 disks and two independent Amiga copies
agree, and the DOS release agrees with the Amiga.
"""

from __future__ import annotations

import collections
import functools
import io

import pytest

from automap.area import NEAR_ENOUGH, OURS, ResidentGeo, looks_like_a_map
from goldbox.geo import (
    ATTRIBUTES,
    BARRIERS,
    GEO_SIZE,
    GRID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)
from tools import geoports

#: The three Curse areas the C64 disks disagree with the other two ports about,
#: and the offsets of the two bytes in each.
CURSE_DIFFERENCES = {"GEO15": (0x299, 0x3C6),
                     "GEO20": (0x351, 0x352),
                     "GEO35": (0x13C, 0x28B)}

#: Where the resident map sits while the game is drawing it.
AT = 0x0400


class Machine:
    """A target holding one 1024-byte block, which is all `ResidentGeo` reads."""

    def __init__(self, block: bytes, address: int = AT):
        self.address = address
        self.block = block

    def read(self, addr: int, length: int) -> bytes:
        if self.address <= addr and addr + length <= self.address + len(
                self.block):
            at = addr - self.address
            return self.block[at:at + length]
        return bytes(length)


@functools.lru_cache(maxsize=1)
def _ports() -> dict[str, dict[str, dict[str, bytes]]]:
    return geoports.every_port()


def ports_for(title: str, *wanted: str) -> dict[str, dict[str, bytes]]:
    """`{port: {name: bytes}}` for one title, or skip naming what is missing."""
    found = _ports().get(title, {})
    missing = [port for port in wanted if not found.get(port)]
    if missing:
        pytest.skip(f"no {title} maps for {', '.join(missing)}; set "
                    f"$COAB_DISKS, $SSB_DISKS, $AMIGA_DISKS or $FR_ARCHIVES")
    return {port: found[port] for port in wanted}


def geo_maps(maps: dict[str, bytes]) -> dict[str, Geo]:
    return {name: Geo(raw) for name, raw in maps.items()}


# --- which three, and by how much --------------------------------------------

def test_thirteen_of_curses_sixteen_areas_are_the_same_bytes_on_both_ports():
    ports = ports_for("Curse", "C64", "Amiga")
    c64, amiga = ports["C64"], ports["Amiga"]
    assert sorted(c64) == sorted(amiga)
    assert len(c64) == 16
    same = [name for name in c64 if c64[name] == amiga[name]]
    assert len(same) == 13
    assert sorted(set(c64) - set(same)) == sorted(CURSE_DIFFERENCES)


def test_each_of_the_three_differs_in_exactly_two_of_its_1024_bytes():
    ports = ports_for("Curse", "C64", "Amiga")
    c64, amiga = ports["C64"], ports["Amiga"]
    for name, offsets in CURSE_DIFFERENCES.items():
        differ = tuple(i for i in range(GEO_SIZE)
                       if c64[name][i] != amiga[name][i])
        assert differ == offsets, name


def test_the_three_differ_in_the_planes_the_write_up_names():
    """One barrier and one attribute, two barriers, one wall and one attribute.

    Which plane a byte is in is the whole finding: a wall-art difference is
    something drawn differently, a barrier difference is somewhere the party
    can or cannot walk, and an attribute difference is a square that runs a
    script on one port and not the other.
    """
    ports = ports_for("Curse", "C64", "Amiga")
    planes = {name: sorted(offset & 0xF00 for offset in offsets)
              for name, offsets in CURSE_DIFFERENCES.items()}
    assert planes == {"GEO15": [ATTRIBUTES, BARRIERS],
                      "GEO20": [BARRIERS, BARRIERS],
                      "GEO35": [WALLS_SOUTH_WEST, ATTRIBUTES]}
    # and the barrier bytes really are the two sides of one edge in GEO20
    c64 = ports["C64"]["GEO20"]
    assert (0x351 & 0xFF) + 1 == (0x352 & 0xFF)
    assert Geo(c64).is_passable(1, 5, 1)            # east, from the west side
    assert not Geo(c64).is_passable(2, 5, 3)        # west, coming back


def test_the_c64_is_the_odd_one_out_and_dos_sides_with_the_amiga():
    """Two ports against one, which is what makes the C64 the departure.

    Skips rather than fails without the DOS archives: this is the corroboration
    and not the finding.
    """
    ports = ports_for("Curse", "C64", "Amiga", "DOS")
    amiga, dos, c64 = ports["Amiga"], ports["DOS"], ports["C64"]
    assert sorted(dos) == sorted(amiga)
    assert amiga == dos
    for name in CURSE_DIFFERENCES:
        assert c64[name] != dos[name], name


def test_every_silver_blades_area_is_the_same_bytes_on_every_port():
    """Seventeen by three, which is what makes Curse's three interesting."""
    ports = ports_for("Silver Blades", "C64", "Amiga", "DOS")
    assert len(ports["C64"]) == 17
    assert ports["C64"] == ports["Amiga"] == ports["DOS"]


# --- what the automapper does with them --------------------------------------

def test_the_resident_check_names_all_sixteen_from_the_other_ports_copies():
    """The behaviour the difference threatens, and it survives.

    `ResidentGeo.verdict` tries an exact match first, so for the three that
    differ it falls through to the tolerance -- past `looks_like_a_map`, which
    all six files pass, to a minimum distance of 2. Running one port's game
    against the other port's disks still answers `OURS` and still names the
    right area.
    """
    ports = ports_for("Curse", "C64", "Amiga")
    for loaded, held in (("Amiga", "C64"), ("C64", "Amiga")):
        maps = geo_maps(ports[held])
        for name, block in ports[loaded].items():
            got = ResidentGeo(Machine(block)).verdict(maps)
            assert got == (OURS, name), f"{loaded} {name} against {held}"


def test_the_exact_match_is_the_one_that_misses():
    """`identify` has no tolerance, and that is the path that answers wrong.

    Both its callers are exact by intent -- `check_arrival` after a fasttravel
    and `identify_elsewhere` when a title switch needs certainty -- so this
    records what those two would do rather than asserting they are right.
    """
    ports = ports_for("Curse", "C64", "Amiga")
    held = geo_maps(ports["C64"])
    for name, block in ports["Amiga"].items():
        got = ResidentGeo(Machine(block)).identify(held)
        assert got == (None if name in CURSE_DIFFERENCES else name)


def test_the_drift_between_two_ports_copies_stays_well_inside_the_tolerance():
    """Six bytes at the very worst, and the tolerance has to reach them.

    This is the *lower* bound on `NEAR_ENOUGH`, and the only one anybody has
    ever measured a real need for: a player running one port's game against
    the other port's disks. Stated as the measurement first, because the
    constant moved in
    #447 (The map tolerance is wider than the gap between two of Silver Blades'
    own maps) and has to keep saying what the game's data does whatever it is
    set to next.
    """
    worst = 0
    for _title, ports in _ports().items():
        names = sorted({name for maps in ports.values() for name in maps})
        for name in names:
            blocks = [maps[name] for maps in ports.values() if name in maps]
            for other in blocks[1:]:
                worst = max(worst, sum(a != b for a, b in zip(blocks[0],
                                                              other)))
    if worst == 0:
        pytest.skip("only one port's disks are on this machine")
    assert worst == 6                       # Pool of Radiance GEO1A, C64/DOS
    # A fourfold margin rather than the bare `worst < NEAR_ENOUGH`, so a
    # tightening that leaves the shipped data with no room says so here
    # instead of at the first player who mixes two ports.
    assert worst * 4 <= NEAR_ENOUGH


def test_the_tolerance_is_smaller_than_the_gap_between_two_distinct_maps():
    """The *upper* bound, and half of it, which is what makes it a guarantee.

    `ResidentGeo.verdict` is only ever handed one title's maps off one port
    -- `Automapper._maps` comes from `automap.maps.load_maps`, which globs a
    single title's disks -- so the gap that matters is the closest two maps
    inside one such set. Two maps both within `NEAR_ENOUGH` of the same block
    are within twice that of each other, so a tolerance under half the closest
    gap makes it impossible for one block to be eligible for two maps at once.

    Measured on the player's own disks, 2026-09-08: eight corpora, 157 maps,
    1580 within-set pairs, and the closest two are Silver Blades' `GEO50` and
    `GEO52` at 80 -- the same maze twice with different decoration, byte-
    identical on all three ports. This is the assertion that was failing when
    #447 was filed, at a tolerance of 128 against a gap of 80.

    It fails for a *new* map pair as well, which is the point: a title whose
    two closest maps come nearer than twice the tolerance turns this red
    rather than quietly making the answer ambiguous. Pools of Darkness'
    `GEO21` and `GEO31` are 18 bytes apart and would do exactly that, and are
    not measured here because `goldbox.c64_port` does not know the title, so the
    automapper can never build that candidate set.
    """
    sets = geoports.closest_within_sets(_ports())
    if not sets:
        pytest.skip("no game disks on this machine; set $POR_DISKS, "
                    "$COAB_DISKS, $SSB_DISKS, $AMIGA_DISKS or $FR_ARCHIVES")
    gap, label, a, b = sets[0]
    assert (gap, a, b) == (80, "GEO50", "GEO52"), label
    assert 2 * NEAR_ENOUGH < gap


def test_a_map_is_never_nearer_a_different_area_than_its_own_other_port():
    """The margin the answer rests on, and it is three orders of magnitude.

    A port difference could only mislead `verdict` if some *other* area were
    nearer to the block than the same area on the other port. Nothing comes
    close: the nearest wrong Curse map to any of the three is 746 bytes away.
    """
    ports = ports_for("Curse", "C64", "Amiga")
    c64, amiga = ports["C64"], ports["Amiga"]
    nearest_wrong = min(
        sum(a != b for a, b in zip(c64[name], amiga[other]))
        for name in CURSE_DIFFERENCES for other in amiga if other != name)
    assert nearest_wrong == 746
    assert nearest_wrong > NEAR_ENOUGH


# --- what the DOS reader keeps, and why ---------------------------------------

#: Every `GEO<n>.DAX` library in the Forgotten Realms archives and how many
#: blocks it holds. Measured 2026-09-09 over all six DOS titles installed
#: there; the last three are titles `goldbox.c64_port` does not know, and the
#: reader takes them because `--all-dos-titles` asks it to.
DOS_LIBRARIES = {"Pool of Radiance": 29, "Curse": 16, "Silver Blades": 17,
                 "DOS GATEWAY": 30, "DOS TREASURE": 41, "DOS DARKNESS": 32}

#: The two bytes each library puts in front of its 1024, which the engine never
#: reads. Four libraries carry the C64 PRG's `$0400`; the two titles with no
#: C64 release carry something else, and Pools of Darkness is not even
#: consistent with itself.
DOS_LEADING_WORDS = {
    "Pool of Radiance": {b"\x00\x04": 29},
    "Curse": {b"\x00\x04": 16},
    "Silver Blades": {b"\x00\x04": 17},
    "DOS GATEWAY": {b"\x00\x04": 30},
    "DOS TREASURE": {b"\x00\x00": 41},
    "DOS DARKNESS": {b"\xcc\xdd": 26, b"\x01\x11": 5, b"\x00\x04": 1},
}

#: The nine blocks the engine loads and draws that `looks_like_a_map` does not
#: clear. Six are Gateway's wilderness areas, which have no walls at all; two
#: are ordinary Treasures maps a little under `MAP_WALLED_EDGES` and
#: `MAP_RECIPROCITY`; one is an empty slot. This is why the reader's membership
#: test is the engine's own 1026 bytes and not the plausibility check (#466).
DOS_IMPLAUSIBLE = {
    "DOS GATEWAY": ["GEO15", "GEO16", "GEO17", "GEO18", "GEO19", "GEO1A"],
    "DOS TREASURE": ["GEO35", "GEO37"],
    "DOS DARKNESS": ["GEO12"],
}


def dos_blocks():
    blocks = list(geoports.dos_geo_blocks(all_titles=True))
    if not blocks:
        pytest.skip("no DOS archives on this machine; set $FR_ARCHIVES")
    return blocks


def test_every_geo_block_in_the_archives_is_read_as_a_map():
    """165 of 165, where the reader used to take 95.

    Treasures of the Savage Frontier was absent from the corpus altogether and
    Pools of Darkness was a corpus of one, because the reader asked for the
    C64's `00 04` in front and neither title has a C64 release.
    """
    dos_blocks()
    maps = geoports.dos_maps(all_titles=True)
    assert {title: len(m) for title, m in maps.items()} == DOS_LIBRARIES
    assert sum(len(m) for m in maps.values()) == 165


def test_the_only_size_any_block_has_is_the_one_the_engine_checks():
    """`Load3DMap` refuses anything but `0x402` bytes, and nothing is refused.

    So the size test drops nothing here, which is the point: it is the
    engine's own membership test rather than a filter fitted to the corpus.
    """
    sizes = collections.Counter(len(block) for _t, _n, _i, block
                                in dos_blocks())
    assert sizes == {geoports.DOS_BLOCK_SIZE: 165}
    assert geoports.DOS_BLOCK_SIZE == GEO_SIZE + 2


def test_two_of_the_six_libraries_do_not_open_with_a_c64_load_address():
    heads: dict[str, dict[bytes, int]] = {}
    for title, _name, _block_id, block in dos_blocks():
        counts = heads.setdefault(title, {})
        head = bytes(block[:geoports.DOS_SKIP])
        counts[head] = counts.get(head, 0) + 1
    assert heads == DOS_LEADING_WORDS


def test_nine_blocks_the_engine_draws_do_not_clear_the_plausibility_check():
    """The reason `looks_like_a_map` is reported and not used as the filter.

    Failing it costs a map nothing in the game -- the engine copies the four
    planes out and draws them -- so a reader that filtered on it would drop
    eight areas a player can stand in, plus one empty slot.
    """
    dos_blocks()
    failed: dict[str, list[str]] = {}
    for title, maps in geoports.dos_maps(all_titles=True).items():
        for name, raw in sorted(maps.items()):
            if not looks_like_a_map(Geo(raw)):
                failed.setdefault(title, []).append(name)
    assert failed == DOS_IMPLAUSIBLE


def test_gateways_six_wilderness_blocks_have_no_walls_at_all():
    """What the six actually are, so "implausible" is not left as a shrug.

    One wall plane is entirely empty and the party can cross all but a handful
    of the 480 interior edges -- open country, not a dungeon and not rubbish.
    """
    dos_blocks()
    maps = geoports.dos_maps(all_titles=True).get("DOS GATEWAY", {})
    if not maps:
        pytest.skip("no Gateway to the Savage Frontier in the archives")
    for name in DOS_IMPLAUSIBLE["DOS GATEWAY"]:
        raw = maps[name]
        assert set(raw[WALLS_SOUTH_WEST:WALLS_SOUTH_WEST + 256]) == {0}, name
        assert any(raw[WALLS_NORTH_EAST:WALLS_NORTH_EAST + 256]), name
        geo = Geo(raw)
        blocked = sum(not geo.is_passable(x, y, direction)
                      for y in range(GRID) for x in range(GRID - 1)
                      for direction in (1,))
        assert blocked <= 11, (name, blocked)


def test_the_empty_slot_in_pools_of_darkness_is_one_plane_of_a_single_byte():
    """`GEO1.DAX` id 18, the block with no walled edges anywhere.

    Named rather than counted: three of its four planes are all zero and the
    fourth is `$80` on every one of the 256 squares -- the roofed bit set and
    no script id. Nothing to walk on and nothing to draw.
    """
    dos_blocks()
    maps = geoports.dos_maps(all_titles=True).get("DOS DARKNESS", {})
    if not maps:
        pytest.skip("no Pools of Darkness in the archives")
    raw = maps["GEO12"]
    assert set(raw[WALLS_NORTH_EAST:WALLS_NORTH_EAST + 256]) == {0}
    assert set(raw[WALLS_SOUTH_WEST:WALLS_SOUTH_WEST + 256]) == {0}
    assert set(raw[ATTRIBUTES:ATTRIBUTES + 256]) == {0x80}
    assert set(raw[BARRIERS:BARRIERS + 256]) == {0}


def test_the_blocks_census_reports_every_library_and_filters_none_of_it():
    dos_blocks()
    out = io.StringIO()
    assert geoports.report_blocks(out) == 0
    text = out.getvalue()
    for title, count in DOS_LIBRARIES.items():
        assert f"== {title}: {count} blocks, {count} of them 1026 bytes" in text
    assert "GEO12    GEO1.DAX     ccdd" in text


# --- the tool's own decoding, on bytes we made -------------------------------

def test_describe_names_the_square_the_plane_and_what_changed():
    """No disks needed: two blocks this test builds, one byte apart."""
    from tests.gamedata import synthetic_geo
    left = bytearray(synthetic_geo())
    right = bytearray(left)
    right[ATTRIBUTES + 9 * 16 + 9] = 0x9D
    left[ATTRIBUTES + 9 * 16 + 9] = 0x80
    lines = geoports.describe(ATTRIBUTES + 9 * 16 + 9, bytes(left),
                              bytes(right), "C64", "Amiga")
    assert "attributes" in lines[0] and "( 9, 9)" in lines[0]
    assert "$299" in lines[0]
    assert lines[1] == "        script id: C64 0, Amiga 29"


def test_describe_names_both_sides_of_a_barrier_byte():
    from tests.gamedata import synthetic_geo
    left = bytearray(synthetic_geo())
    right = bytearray(left)
    at = BARRIERS + 5 * 16 + 1
    left[at], right[at] = 0x04, 0x00           # east passable, then solid
    lines = geoports.describe(at, bytes(left), bytes(right), "C64", "DOS")
    assert lines[1].startswith("        east : C64 passable, DOS solid")


def test_the_planes_a_pair_differs_in_are_counted_separately():
    from tests.gamedata import synthetic_geo
    left = bytearray(synthetic_geo())
    right = bytearray(left)
    right[ATTRIBUTES] ^= 0x01
    right[BARRIERS + 3] ^= 0x03
    right[BARRIERS + 4] ^= 0x03
    assert geoports.per_plane(bytes(left), bytes(right)) == {
        "walls N/E": 0, "walls S/W": 0, "attributes": 1, "barriers": 2}


def test_the_watch_line_names_a_value_that_would_actually_pass_the_check():
    """#466: `WATCH` prints what `NEAR_ENOUGH` would have to become, and it
    has to be a value the tool's own gate accepts.

    That gate is `2 * NEAR_ENOUGH >= gap`, which refuses equality, so the
    largest legal value for a gap of 18 is 8 and not 9.  `gap // 2` gave 9 --
    the first value that fails -- and only on an even gap, which is why Pools
    of Darkness' `GEO21`/`GEO31` at 18 is the pair that shows it and
    Treasures' 99 never did.  `automap.area.NEAR_ENOUGH`'s own note and
    `report_closest`'s docstring both say 8; the line disagreed with both.
    """
    for gap in (18, 80, 99, 100):
        named = (gap - 1) // 2
        assert 2 * named < gap, (gap, named)
        assert 2 * (named + 1) >= gap, (gap, named)
    assert (18 - 1) // 2 == 8
