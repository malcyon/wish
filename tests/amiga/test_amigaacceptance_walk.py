"""The Pools of Darkness accept read-back judges an overland step on the overland grid."""

from __future__ import annotations

import types

from goldbox import amiga_savegame, world_state
from tools.amiga import acceptance as foundation
from tools.amiga import route_darkness

FACING_EAST, FACING_NORTH = 1, 0
DUNGEON_SQUARE = (4, 7)


def _variables(*, in_dungeon: int, wild: tuple[int, int]) -> bytes:
    """The variable bytes at the offsets the reader names (variable N is byte N-1)."""
    variables = bytearray(1024)
    variables[34 - 1] = in_dungeon
    variables[37 - 1], variables[38 - 1] = wild
    return bytes(variables)


def _state(variables: bytes, facing: int) -> world_state.PodWorldState:
    return world_state.PodWorldState(
        title="pod", variables=variables, x=DUNGEON_SQUARE[0], y=DUNGEON_SQUARE[1],
        facing=facing, wall_ahead=0, square_property=0, previous_mode=3, mode=2,
        dungeon_map=0, map_block=0, count=1)


def _reading(state: world_state.PodWorldState) -> dict:
    """What `_darkness_read_slot` returns for this state, decoded through its own code."""
    class Disk:
        def read_file(self, path):
            return b"x"
    saved = (amiga_savegame.pod_read_slot, amiga_savegame.pod_from_amiga,
             amiga_savegame.pod_parse)
    amiga_savegame.pod_read_slot = lambda disk, letter: b"x"
    amiga_savegame.pod_from_amiga = lambda data: state
    amiga_savegame.pod_parse = lambda data: types.SimpleNamespace(
        characters=[], effect_nodes=[])
    try:
        return route_darkness._darkness_read_slot(Disk(), "F")
    finally:
        (amiga_savegame.pod_read_slot, amiga_savegame.pod_from_amiga,
         amiga_savegame.pod_parse) = saved


def _outdoors(x: int, y: int, facing: int = FACING_EAST) -> dict:
    return _reading(_state(_variables(in_dungeon=0, wild=(x, y)), facing))


BEFORE = {"area": 0, "x": 4, "y": 7, "facing": FACING_EAST}
GRID = route_darkness.WILDERNESS_GRID


def test_the_reading_names_whether_the_party_is_outdoors_and_where():
    assert _outdoors(22, 5)["in_dungeon"] is False
    assert _outdoors(22, 5)["wilderness_square"] == [22, 5]
    inside = _reading(_state(_variables(in_dungeon=1, wild=(22, 5)), FACING_EAST))
    assert inside["in_dungeon"] is True


def test_one_step_north_outdoors_is_a_move_even_with_the_dungeon_square_stale():
    control = _outdoors(22, 5)
    after = _outdoors(22, 4, FACING_NORTH)
    after["place"] = dict(BEFORE, facing=FACING_NORTH)
    verdict = foundation.walk_verdict(BEFORE, control, after, 1, wilderness_grid=GRID)
    assert verdict["b_ok"] and verdict["d_ok"], verdict
    assert verdict["squares_moved"] is None or verdict["squares_moved"] == 1
    assert verdict["place_changed"] is True


def test_a_party_that_stood_still_outdoors_did_not_move():
    control = _outdoors(22, 5)
    verdict = foundation.walk_verdict(BEFORE, control, dict(control), 1, wilderness_grid=GRID)
    assert verdict["walk_blocked"] and not verdict["d_ok"]


def test_a_step_at_the_northern_edge_stays_put_rather_than_wrapping():
    control = _outdoors(22, 0)
    verdict = foundation.walk_verdict(BEFORE, control, _outdoors(22, 0), 1, wilderness_grid=GRID)
    wrapped = foundation.walk_verdict(BEFORE, control, _outdoors(22, 14), 1,
                                      wilderness_grid=GRID)
    assert verdict["d_ok"]
    assert not wrapped["d_ok"]


def test_a_dungeon_control_is_judged_on_the_dungeon_square_as_before():
    inside = _reading(_state(_variables(in_dungeon=1, wild=(22, 5)), FACING_EAST))
    after = dict(inside, place=dict(BEFORE, x=5))
    verdict = foundation.walk_verdict(BEFORE, inside, after, 1, wilderness_grid=GRID)
    assert verdict["d_ok"]
    old = foundation.walk_verdict(BEFORE, inside, after, 1)
    assert old == verdict


def test_a_title_without_a_wilderness_grid_keeps_its_verdict():
    control = _outdoors(22, 5)
    after = _outdoors(22, 4, FACING_NORTH)
    verdict = foundation.walk_verdict(BEFORE, control, after, 1)
    assert not verdict["d_ok"]
    assert "expected 5,7" in verdict["verdicts"][1]


def test_only_pools_of_darkness_names_a_wilderness_grid():
    assert route_darkness.DARKNESS.wilderness_grid == (38, 15)
    assert route_darkness.DARKNESS_RELOAD.wilderness_grid == (38, 15)
    assert foundation.AmigaTitle.__dataclass_fields__["wilderness_grid"].default is None


def test_the_guard_key_adds_the_overland_square_only_outdoors():
    place = dict(BEFORE)
    assert foundation.place_state(place) == "place_x4_y7_f1"
    assert foundation.place_state(place, [22, 5]) != foundation.place_state(place, [22, 4])
    assert foundation.place_state(place, None) == "place_x4_y7_f1"
