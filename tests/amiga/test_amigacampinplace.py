"""The Pools of Darkness accept route can skip its walk and camp where the party stands."""
from __future__ import annotations

import pytest

from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance_title import (
    ROUTE,
    START,
    TitleGuest,
    _keys,
    _run,
    make_title,
)
from tools.amiga import route_camp, route_darkness
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep

CAMP = ("view 1", "rest 60m")


def _kinds(title):
    return [kind for _, _, kind in title.route]


def test_the_default_route_still_walks_before_camp():
    keys = [key for key, _, _ in route_darkness.DARKNESS.route]
    assert "NP8" in keys and keys.index("NP8") < keys.index("E", keys.index("RET"))


def test_camp_in_place_drops_the_walk_and_keeps_camp_entry_and_guards():
    base = route_darkness.DARKNESS
    title = route_darkness.camp_in_place_title(base)
    assert "move" not in _kinds(title) and "move" not in [k for _, _, k in title.measure_route]
    assert title.route == tuple(step for step in base.route if step[2] != "move")
    at = title.route.index(("RET", "world", "key"))
    assert title.route[at + 1:at + 3] == (("E", "camp", "key"), ("S", "camp_save_picker", "key"))
    assert (title.strict, title.min_waits, title.plain_keys) == (
        base.strict, base.min_waits, base.plain_keys)


def test_camp_steps_still_go_before_the_camp_save_without_the_walk():
    title = route_darkness.camp_in_place_title(route_darkness.DARKNESS)
    camped = route_camp.camp_title(title, CAMP, 6, name="darkness")
    at = camped.route.index(route_camp.CAMP_SAVE_STEP)
    assert camped.route[at - 1] != ("NP8", "world", "move")
    assert camped.route[at - len(route_camp.steps_for(CAMP, "darkness", 6)) - 1] == (
        "E", "camp", "key")
    assert "move" not in _kinds(camped)


def test_a_route_with_no_walk_is_not_changed_silently():
    walkless = route_darkness.camp_in_place_title(route_darkness.DARKNESS)
    with pytest.raises(RouteError, match="no walk step"):
        route_darkness.camp_in_place_title(walkless)


def test_the_accept_run_presses_no_walk_key_and_records_the_skip(tmp_path, clock):
    route = tuple(step for step in ROUTE if step[2] != "turn")
    walking = make_title(route=route, measure_route=route, turn=None)
    guest, result = _run(tmp_path, clock, title=walking, camp_in_place=True,
                         cli_title="darkness",
                         guest=TitleGuest(clock, land=dict(START)))
    assert "NP8" not in _keys(guest)
    assert "E" in _keys(guest)
    assert result["walk_skipped"] is True and result["success"] is True


def test_the_default_accept_run_walks_and_records_no_skip(tmp_path, clock):
    guest, result = _run(tmp_path, clock)
    assert "NP8" in _keys(guest)
    assert "walk_skipped" not in result


def test_camp_in_place_is_for_pools_of_darkness_only(tmp_path, clock):
    with pytest.raises(RouteError, match="Pools of Darkness only"):
        _run(tmp_path, clock, camp_in_place=True, cli_title="curse")


