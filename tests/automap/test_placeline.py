"""The place line names a shared map from the game's own area id."""
from __future__ import annotations

from support.stalestatus import curse_target

from automap import amiga
from automap.state import Automapper
from goldbox import areas
from goldbox.geo import GEO_SIZE, Geo

CURSE = areas.CURSE_OF_THE_AZURE_BONDS
AREA_BYTE = 0x7F1B


def _geo(seed: int) -> Geo:
    return Geo(bytes((seed * 31 + i) & 0xFF for i in range(GEO_SIZE)))


def test_a_shared_curse_map_is_named_from_the_c64_area_byte():
    town, guild = _geo(1), _geo(3)
    target = curse_target("S 8:37 14,15", (14, 15, 2), town)
    target.memory[AREA_BYTE] = bytes([0x02])
    mapper = Automapper(target, {"GEO01": town, "GEO03": guild},
                        title=CURSE)
    assert mapper._check_resident()
    assert mapper.state.area_label == "Thieves' Guild under Tilverton"
    target.memory[AREA_BYTE] = bytes([0x01])
    assert mapper._check_resident()
    assert mapper.state.area == "GEO01"
    assert mapper.state.area_label == "Tilverton streets"


def test_a_named_curse_map_does_not_read_the_area_byte():
    sewers = _geo(3)
    target = curse_target("S 8:37 14,15", (14, 15, 2), sewers)
    mapper = Automapper(target, {"GEO03": sewers}, title=CURSE)
    mapper._check_resident()
    assert (AREA_BYTE, 1) not in target.reads


class _AmigaStub:
    """Enough of an Amiga target for the resident-map and area reads."""

    c64_memory = False
    data_base = 0x1000

    def __init__(self, layout, geo_at, geo, area_byte):
        self.layout = layout
        self._geo_at = geo_at
        self.memory = {geo_at: geo.to_bytes(),
                       self.data_base + 0x7A0A: bytes([area_byte])}

    def resident_geo_address(self):
        return self._geo_at

    def read(self, addr, length):
        for base, blob in self.memory.items():
            if base <= addr and addr + length <= base + len(blob):
                return blob[addr - base:addr - base + length]
        return bytes(length)


def test_amiga_pools_of_darkness_names_mulmaster_from_the_area_byte():
    geo = _geo(13)
    target = _AmigaStub(amiga.MACHINES["pools-of-darkness"], 0x20000, geo, 26)
    mapper = Automapper(target, {"GEO13": geo}, title=areas.POOLS_OF_DARKNESS)
    assert mapper._check_resident()
    assert mapper.state.area_label == "The Black City of Mulmaster"
