"""A status line the game has already moved past is not believed."""
from support.stalestatus import curse_target, walk_into_the_sewers

from automap.target import party_fix
from goldbox import c64_port
from goldbox.geo import (
    ATTRIBUTES,
    BARRIERS,
    GEO_SIZE,
    GRID,
    WALLS_NORTH_EAST,
    WALLS_SOUTH_WEST,
    Geo,
)

CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS


def synthetic_map(salt: int) -> Geo:
    """Doors on every edge, so two salts are two maps a resident match tells apart."""
    raw = bytearray(GEO_SIZE)
    for i in range(GRID * GRID):
        raw[WALLS_NORTH_EAST + i] = 0x11
        raw[WALLS_SOUTH_WEST + i] = 0x11
        raw[BARRIERS + i] = 0x55
    raw[ATTRIBUTES] = salt
    return Geo(bytes(raw))


def test_a_status_square_the_engine_has_left_gives_way_to_the_engine():
    """Curse's line lags a step: it still read 14,15 when `$C04B` held 0,0."""
    target = curse_target("S 8:37 14,15", (0, 0, 2))
    fix = party_fix(target.read, CURSE)
    assert (fix.x, fix.y, fix.facing, fix.source) == (0, 0, 2, "memory")
    assert fix.clock == 8 * 60 + 37


def test_an_implausible_triple_never_overrides_the_line():
    """On the world map `$C04B` reads 33,208,202."""
    target = curse_target("S 8:37 14,15", (33, 208, 202))
    fix = party_fix(target.read, CURSE)
    assert (fix.x, fix.y, fix.facing, fix.source) == (14, 15, 2, "status")


def test_the_sewers_are_entered_at_the_square_the_game_names(tmp_path, monkeypatch):
    mapper = walk_into_the_sewers(synthetic_map(1), synthetic_map(2),
                                  tmp_path, monkeypatch)
    state = mapper.state
    assert state.area == "GEO03"
    assert (state.x, state.y, state.facing) == (0, 0, 2)
    assert (14, 15) not in state.exploration
