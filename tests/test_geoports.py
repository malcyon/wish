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

import functools

import pytest

from automap.area import NEAR_ENOUGH, OURS, ResidentGeo
from goldbox.geo import ATTRIBUTES, BARRIERS, GEO_SIZE, WALLS_SOUTH_WEST, Geo
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
    """Six bytes at the very worst, against a tolerance of 128.

    Stated as the measurement rather than as `<= NEAR_ENOUGH`: the constant is
    under review in
    #447 (The map tolerance is wider than the gap between two of Silver Blades'
    own maps), and this has to keep saying what the game's data does when the
    constant moves.
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
    assert worst * 10 < NEAR_ENOUGH


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
