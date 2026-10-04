from __future__ import annotations

import json

import pytest

from goldbox import geo
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga import test_amigaacceptance_title as title_run
from tools.amiga import acceptance, route_pool, winuaesession
from tools.amiga.route import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep

SOLID_WALL = 1


def _map(*, x: int, y: int, closed: tuple[int, ...] = (), doors: tuple[int, ...] = ()) -> geo.Geo:
    """A GEO with wall art and a solid barrier on `closed` edges, and an open door on `doors`, at one square."""
    data = bytearray(geo.GEO_SIZE)
    i = x + (y << 4)
    for direction in (*closed, *doors):
        shift = 4 if direction in (geo.NORTH, geo.SOUTH) else 0
        plane = geo.WALLS_NORTH_EAST if direction in (geo.NORTH, geo.EAST) else geo.WALLS_SOUTH_WEST
        data[plane + i] |= SOLID_WALL << shift
    for direction in doors:
        data[geo.BARRIERS + i] |= geo.PASSABLE << (2 * direction)
    return geo.Geo(data)


def _loader(walls: geo.Geo):
    return lambda name: walls


KOBOLD_CAVES = {"area": 13, "x": 6, "y": 5, "facing": geo.NORTH}


def test_a_closed_edge_behind_the_party_sends_the_route_forward():
    walls = _map(x=6, y=5, closed=(geo.SOUTH,))
    assert route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls)) is False


def test_an_open_edge_behind_the_party_keeps_the_turn_about():
    walls = _map(x=6, y=5, closed=(geo.NORTH,))
    assert route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls)) is True


def test_an_open_door_behind_the_party_keeps_the_turn_about():
    walls = _map(x=6, y=5, closed=(geo.NORTH,), doors=(geo.SOUTH,))
    assert route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls)) is True


def test_a_square_closed_both_ways_is_blocked():
    walls = _map(x=6, y=5, closed=(geo.NORTH, geo.SOUTH))
    with pytest.raises(RouteError, match="no open edge"):
        route_pool.pool_turns_about(KOBOLD_CAVES, load_geo=_loader(walls))


def test_an_area_with_two_maps_keeps_the_turn_about_without_reading_walls():
    def block(name):
        raise AssertionError("no wall data should be read")
    place = {"area": 24, "x": 8, "y": 11, "facing": geo.SOUTH}
    assert route_pool.pool_turns_about(place, load_geo=block) is True


def test_the_forward_route_has_no_turn_and_the_other_steps_are_unchanged():
    forward = route_pool.POOL_FORWARD
    assert forward.turn is None and route_pool.POOL.turn == "about"
    for got, kept in ((forward.route, route_pool.POOL.route),
                      (forward.measure_route, route_pool.POOL.measure_route)):
        assert ("NP2", "world", "turn") in kept and ("NP2", "world", "turn") not in got
        assert got == tuple(s for s in kept if s != ("NP2", "world", "turn"))
        assert ("NP8", "world", "move") in got


def test_the_manifest_picks_the_route_and_is_cross_checked_against_the_walls():
    walls = _loader(_map(x=6, y=5, closed=(geo.SOUTH,)))
    manifest = {"state_a": KOBOLD_CAVES, "turn_about": False}
    assert route_pool.pool_title_for(manifest, load_geo=walls) is route_pool.POOL_FORWARD
    with pytest.raises(RouteError, match="disagrees"):
        route_pool.pool_title_for(dict(manifest, turn_about=True), load_geo=walls)
    with pytest.raises(RouteError, match="boolean"):
        route_pool.pool_title_for(dict(manifest, turn_about="no"), load_geo=walls)
    # A manifest written before the choice existed keeps the route it was made for.
    assert route_pool.pool_title_for({"state_a": KOBOLD_CAVES}, load_geo=walls) is route_pool.POOL


def test_prepare_records_the_choice(monkeypatch):
    walls = _loader(_map(x=6, y=5, closed=(geo.SOUTH,)))
    real = route_pool.pool_turns_about
    monkeypatch.setattr(route_pool, "_prepare_from", lambda *a, **k: {"state_a": KOBOLD_CAVES})
    monkeypatch.setattr(route_pool, "pool_turns_about",
                        lambda place: real(place, load_geo=walls))
    assert route_pool._prepare_pool(None, None)["turn_about"] is False


def test_missing_disks_are_a_route_error_not_a_type_error(monkeypatch):
    monkeypatch.setattr("automap.paths.tool_disks", lambda game=None: None)
    with pytest.raises(RouteError, match="disks are not found"):
        route_pool._disk_geo("GEO0D")


def test_a_manifest_or_place_missing_its_area_is_a_route_error():
    with pytest.raises(RouteError, match="no state_a"):
        route_pool.pool_title_for({"turn_about": True})
    with pytest.raises(RouteError, match="lacks an area"):
        route_pool.pool_turns_about({"x": 6, "y": 5, "facing": 0})
    with pytest.raises(RouteError, match="lacks an area"):
        route_pool.pool_title_for({"turn_about": True, "state_a": {"x": 1}})


def test_run_recon_selects_the_forward_route_for_a_manifest_that_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(route_pool, "_disk_geo", _loader(_map(x=6, y=5, closed=(geo.SOUTH,))))
    monkeypatch.setattr(winuaesession, "_mute_proof", lambda _path: True)
    seen = []

    def stop(_manifest, title):
        seen.append(title)
        raise RouteError("stop here")

    monkeypatch.setattr(acceptance, "_title_inputs", stop)
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps({"state_a": KOBOLD_CAVES, "turn_about": False}))
    with pytest.raises(RouteError, match="stop here"):
        acceptance.run_recon(path, guest=winuaesession.WinGuest(), holder="wish679-test",
                             audio_proof=tmp_path / "mute.json", title=acceptance.POOL, measure=True)
    assert seen == [route_pool.POOL_FORWARD]
    assert ("NP2", "world", "turn") not in seen[0].route and seen[0].turn is None


TOUR_START = {"area": 0, "x": 15, "y": 1, "facing": geo.WEST}


OPEN_AT_TOUR_END = _loader(_map(x=0, y=4))
TOUR_MANIFEST = {"state_a": route_pool.POOL_TOUR_END, "turn_about": True, "opening_tour": True}


def _continue_rows(title):
    return [row for row in title.interstitials if row[0] == "continue"]


@pytest.mark.parametrize("tour, closed, wanted", [
    (True, (), "POOL_TOUR"), (True, (geo.EAST,), "POOL_FORWARD_TOUR"),
    (False, (geo.NORTH,), "POOL"), (False, (geo.SOUTH,), "POOL_FORWARD"),
])
def test_only_an_opening_tour_manifest_gets_the_continue_row(tour, closed, wanted):
    place = route_pool.POOL_TOUR_END if tour else KOBOLD_CAVES
    walls = _loader(_map(x=place["x"], y=place["y"], closed=closed))
    manifest = {"state_a": place, "turn_about": wanted in ("POOL", "POOL_TOUR"),
                "opening_tour": tour}
    title = route_pool.pool_title_for(manifest, load_geo=walls)
    assert title is getattr(route_pool, wanted)
    rows = _continue_rows(title)
    assert rows == ([("continue", ("keys", "RET"), frozenset({"world"}),
                      route_pool.POOL_CONTINUE_PAGES)] if tour else [])
    assert route_pool.POOL_CONTINUE_PAGES > 8  # the eight pages of Rolf's tour, and a stuck one stops


def test_an_opening_tour_manifest_must_start_at_the_tour_end_and_record_its_turn():
    with pytest.raises(RouteError, match="opening_tour is not a boolean"):
        route_pool.pool_title_for(dict(TOUR_MANIFEST, opening_tour="yes"))
    with pytest.raises(RouteError, match="opening_tour disagrees"):
        route_pool.pool_title_for(dict(TOUR_MANIFEST, state_a=KOBOLD_CAVES))
    with pytest.raises(RouteError, match="no turn_about"):
        route_pool.pool_title_for({"state_a": route_pool.POOL_TOUR_END, "opening_tour": True})


def test_the_committed_continue_guard_reads_the_world_bar_row_as_a_different_picture():
    guards = json.loads((acceptance.REPO / "tools" / "amiga" / "guards_pool.json").read_text())["guards"]
    bar, world = guards["continue"], guards["world"]
    assert bar["box"][1:4:2] == world["box"][1:4:2]  # the same row, so a map bar never reads as it
    assert bar["sha256"] != world["sha256"]


def _from_look(n):
    """A guard rule that matches from its `n`-th look onward."""
    looks = []

    def on(_path):
        looks.append(1)
        return len(looks) >= n

    return on


def _drive(tmp_path, clock, pool_title, on):
    """Run the synthetic route with `pool_title`'s interstitial table and a continue bar always shown."""
    guard = title_run.MapGuard(states=("title", *title_run.STATES, "continue"),
                               on={"continue": lambda _path: True, **on})
    guest, result = title_run._run(tmp_path, clock,
                                   title=title_run.make_title(interstitials=pool_title.interstitials),
                                   guard=guard)
    return title_run._keys(guest), result


def test_a_tour_manifest_presses_return_on_each_continue_page_while_waiting_for_the_world(
        tmp_path, clock):
    title = route_pool.pool_title_for(TOUR_MANIFEST, load_geo=OPEN_AT_TOUR_END)
    keys, result = _drive(tmp_path, clock, title, {"world": _from_look(4)})
    assert result["success"], result["error"]
    assert keys.count("RET") == 3  # three looks at the page before the map shows
    assert [e["key"] for e in result["events"] if e.get("interstitial") == "continue"] == ["RET"] * 3


def test_a_manifest_without_the_tour_never_presses_return_on_a_continue_page(tmp_path, clock):
    title = route_pool.pool_title_for({"state_a": KOBOLD_CAVES, "turn_about": True},
                                      load_geo=_loader(_map(x=6, y=5, closed=(geo.NORTH,))))
    keys, result = _drive(tmp_path, clock, title, {"world": _from_look(4)})
    assert result["success"], result["error"]
    assert "RET" not in keys


def test_a_tour_manifest_leaves_a_continue_page_alone_while_waiting_for_another_screen(
        tmp_path, clock):
    title = route_pool.pool_title_for(TOUR_MANIFEST, load_geo=OPEN_AT_TOUR_END)
    keys, result = _drive(tmp_path, clock, title, {"load_picker": _from_look(6)})
    assert result["success"], result["error"]
    assert "RET" not in keys


def _prepared(monkeypatch, place, clock):
    monkeypatch.setattr(route_pool, "_prepare_from", lambda *a, **k: {
        "state_a": dict(place), "loaded_letter": "A", "disks": {"save": {"path": "save.adf"}}})
    monkeypatch.setattr(route_pool, "_pool_loaded_clock", lambda manifest: clock)
    monkeypatch.setattr(route_pool, "pool_turns_about", lambda place: True)
    return route_pool._prepare_pool(None, None)


def test_a_party_that_has_not_taken_the_tour_is_judged_from_where_the_tour_leaves_it(monkeypatch):
    manifest = _prepared(monkeypatch, TOUR_START, (0, 0, 0, 0, 0, 0))
    assert manifest["opening_tour"] is True
    assert manifest["loaded_place"] == TOUR_START
    assert manifest["state_a"] == route_pool.POOL_TOUR_END == {"area": 0, "x": 0, "y": 4,
                                                               "facing": geo.WEST}


@pytest.mark.parametrize("place, clock", [
    (TOUR_START, (0, 5, 0, 0, 0, 0)),  # played, and back on New Phlan's arrival square
    ({"area": 0, "x": 0, "y": 4, "facing": geo.WEST}, (0, 0, 0, 0, 0, 0)),  # the tour is over
])
def test_a_party_past_the_tour_keeps_its_own_place(monkeypatch, place, clock):
    manifest = _prepared(monkeypatch, place, clock)
    assert manifest["state_a"] == place
    assert "opening_tour" not in manifest and "loaded_place" not in manifest
