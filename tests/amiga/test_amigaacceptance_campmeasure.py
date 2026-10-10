"""A measure run drives a prepared manifest's camp steps and settles on screens no rule covers."""

from __future__ import annotations

import dataclasses
import json

import pytest

from tests.amiga import test_amigaacceptance_campitems as items
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_campitems import (
    NAMES,
    PoolCampGuard,
    PoolCampGuest,
    RowsIdentity,
)
from tests.amiga.test_amigaacceptance_measure import clock as measure_clock
from tests.amiga.test_amigaacceptance_title import (
    START,
    _adf,
    _files,
    _letters,
    _read_slot,
    _slot,
)
from tools.amiga import acceptance, route_camp, route_darkness, route_pool
from tools.amiga.winuaesession import RouteError

clock = measure_clock  # the fixture that replaces the driver's time and sleep


class RowlessGuard(PoolCampGuard):
    """Pool's guard map without a rule for any item row below the first, as the darkness map is cut."""

    def __contains__(self, state):
        return "_row" not in state and super().__contains__(state)


class NeverMatchingList(RowlessGuard):
    """A map with no title rule, as a measuring boot has, whose item-list rule never matches."""

    def __contains__(self, state):
        return state != "title" and super().__contains__(state)

    def __call__(self, state, path):
        return False if route_camp.is_items(state) else super().__call__(state, path)


def _run(tmp_path, clock, steps, guard_class, *, accept):
    base = dataclasses.replace(route_pool.POOL, read_slot=_read_slot, slot_letters=_letters,
                               slot_files=_files)
    slots = [("A", _slot(START, NAMES)), ("B", b"kept slot")]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "ONE"),
             "disk2": _adf(tmp_path / "disk2.adf", "TWO"),
             "save": _adf(tmp_path / "save.adf", "POOLSAVE", slots)}
    manifest = {"disks": disks, "registered": {"reg": _adf(tmp_path / "reg.adf", "REG")},
                "loaded_letter": "A", "state_a": START, "names_a": NAMES,
                "camp": list(steps), "title": "pool"}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    guest = PoolCampGuest(clock, items.ROWS)
    return guest, acceptance.run_recon(
        path, guest=guest, guard=guard_class(guest), identity=RowsIdentity(),
        holder="wish16-test", audio_proof=_audio_proof(tmp_path), title=base,
        accept=accept, measure=not accept)


def test_row_pages_the_list_down_to_the_row_and_presses_nothing_on_it():
    steps = route_camp.steps_for(("row 1 4",), "darkness", 4)
    assert [k for k, _, _ in steps] == ["V", "I", "NP2", "NP2", "NP2", "E", "E"]
    assert "R" not in [k for k, _, _ in steps]
    assert [s for _, s, _ in steps][2:5] == ["camp_items_row2", "camp_items_row3", "camp_items_row4"]


@pytest.mark.parametrize("text", ["row", "row 1", "row 9 2", "row 1 17", "row 1 x"])
def test_row_blocks_a_place_that_is_not_a_line_and_row(text):
    with pytest.raises(RouteError):
        route_camp.validate_steps((text,), 4, name="darkness")


def test_a_title_with_camp_steps_measures_them_before_its_camp_save():
    title = route_camp.camp_title(route_pool.POOL, ("row 1 3",), 4, name="pool")
    at = route_pool.POOL.measure_route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(("row 1 3",), "pool", 4)
    assert title.measure_route == (*route_pool.POOL.measure_route[:at], *added,
                                   *route_pool.POOL.measure_route[at:])
    assert title.measure_loose == {state for _, state, _ in added} - {route_camp.CAMP}
    assert route_pool.POOL.measure_loose == frozenset()


def test_measure_drives_the_camp_steps_and_names_a_crop_for_each_state(tmp_path, clock):
    guest, result = _run(tmp_path, clock, ("row 1 2",), NeverMatchingList, accept=False)
    assert result["error"] == "" and result["success"] is True
    keys = [c[2] for c in guest.calls if c[0] == "press"]
    wanted = [k for k, _, _ in route_camp.steps_for(("row 1 2",), "pool", 4)]
    start = keys.index("V", keys.index("V") + 1)
    assert keys[start:start + len(wanted) + 1] == [*wanted, "S"]
    crops = {p.name for p in tmp_path.glob("*/shots/*.png")}
    assert any(name.endswith("-camp_items_row2.png") for name in crops)
    assert any(name.endswith("-camp_items.png") for name in crops)
    assert result["measure"] is True and result["unguarded"]
    summary, = tmp_path.glob("*/summary.json")
    assert json.loads(summary.read_text())["measure"] is True


def test_accept_still_stops_before_launch_for_an_item_row_without_a_rule(tmp_path, clock):
    with pytest.raises(RouteError, match=r"screen guard map lacks \['camp_items_row2'\]"):
        _run(tmp_path, clock, ("row 1 2",), RowlessGuard, accept=True)


def test_the_loose_states_are_those_of_navigation_steps_only():
    title = route_camp.camp_title(route_darkness.DARKNESS, ("items 1", "heal", "rest 5m"), 6,
                                  name="darkness")
    assert {"camp_items", "camp_sheet_items"} <= title.measure_loose
    assert not {"rest_menu", "heal_whom", "camp_sheet_heal"} & title.measure_loose
    assert route_camp.measure_blockers(("view", "rest 5m", "snapshot a")) == ["rest 5m"]


@pytest.mark.parametrize("step", ["join 1 1", "ready 1 1", "use 1 1 S", "heal", "rest 5m"])
def test_a_measure_run_stops_before_launch_for_a_step_that_changes_the_game(
        tmp_path, clock, step):
    with pytest.raises(RouteError, match="drives no camp step that changes the game"):
        _run(tmp_path, clock, (step,), NeverMatchingList, accept=False)


def test_a_title_whose_measure_route_ends_before_the_camp_save_keeps_none_of_the_steps():
    bare = dataclasses.replace(route_pool.POOL, measure_route=route_pool.POOL.measure_route[:2])
    title = route_camp.camp_title(bare, ("items 1",), 4, name="pool")
    assert title.measure_route == bare.measure_route


def test_the_camp_bar_and_magic_menu_are_never_loose_but_the_lists_are():
    title = route_camp.camp_title(route_darkness.DARKNESS, ("memorize 1 1", "cast 2", "view"), 6,
                                  name="darkness")
    assert not {route_camp.CAMP, route_camp.MAGIC_MENU} & title.measure_loose
    assert {"camp_memorize", "camp_memorize_page1", "camp_cast_2"} <= title.measure_loose


def test_a_measure_run_sends_no_list_key_until_the_magic_menu_is_recognised(tmp_path, clock):
    class MenuNeverMatches(RowlessGuard):
        def __contains__(self, state):
            return state == route_camp.MAGIC_MENU or (
                state != "title" and super().__contains__(state))

        def __call__(self, state, path):
            return False if state == route_camp.MAGIC_MENU else super().__call__(state, path)

    darkness = route_camp.camp_title(route_darkness.DARKNESS, ("memorize 1",), 6, name="darkness")
    base = dataclasses.replace(
        route_pool.POOL, read_slot=_read_slot, slot_letters=_letters, slot_files=_files)
    at = route_pool.POOL.measure_route.index(route_camp.CAMP_SAVE_STEP)
    magic = route_camp.steps_for(("memorize 1",), "darkness", 6)
    title = dataclasses.replace(
        base, measure_route=(*base.measure_route[:at], *magic, *base.measure_route[at:]),
        measure_loose=darkness.measure_loose)
    slots = [("A", _slot(START, NAMES)), ("B", b"kept slot")]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "ONE"),
             "disk2": _adf(tmp_path / "disk2.adf", "TWO"),
             "save": _adf(tmp_path / "save.adf", "POOLSAVE", slots)}
    manifest = {"disks": disks, "registered": {"reg": _adf(tmp_path / "reg.adf", "REG")},
                "loaded_letter": "A", "state_a": START, "names_a": NAMES}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    guest = PoolCampGuest(clock, items.ROWS)
    result = acceptance.run_recon(
        path, guest=guest, guard=MenuNeverMatches(guest), identity=RowsIdentity(),
        holder="wish16-test", audio_proof=_audio_proof(tmp_path), title=title, measure=True)
    keys = [c[2] for c in guest.calls if c[0] == "press"]
    assert result["success"] is False and "camp_magic screen was not recognized" in result["error"]
    # The camp highlight's own M opens the menu; the list's M would follow only a recognised menu.
    assert keys.count("M") == 1 and keys[-1] == "M"
