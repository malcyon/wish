"""Pool of Radiance's camp item list: `items N` opens line N's ITEMS list on guarded screens."""

from __future__ import annotations

import dataclasses
import json

import pytest

from goldbox import geo
from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import MapGuard
from tests.amiga.test_amigaacceptance_title import (
    START,
    TitleGuest,
    _adf,
    _files,
    _letters,
    _read_slot,
    _slot,
)
from tools.amiga import acceptance, route_camp, route_darkness, route_pool
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep

NAMES = ["ALPHA", "BETA", "GAMMA", "DELTA"]
#: Each member's item rows as the ITEMS list shows them; DELTA carries nothing, so his sheet
#: offers no `Items`.
ROWS = {"ALPHA": ["LONG SWORD", "CHAIN MAIL"], "BETA": ["MACE"],
        "GAMMA": ["POTION OF HEALING", "FLAIL"], "DELTA": []}


def test_items_moves_to_the_line_opens_the_sheet_and_its_list_and_comes_back():
    # `V` waits for the sheet whose bar offers `Items`, so `I` goes out only on that sheet.
    assert route_camp.steps_for(("items 1",), "pool", 4) == (
        ("V", "camp_sheet_items", "key"), ("I", "camp_items", "key"),
        ("E", "camp_sheet_items", "key"), ("E", "camp", "key"))
    assert route_camp.steps_for(("items 2",), "pool", 4) == (
        ("NP1", "camp", "key"), ("V", "camp_sheet_items_2", "key"),
        ("I", "camp_items_2", "key"), ("E", "camp_sheet_items_2", "key"),
        ("E", "camp", "key"), ("NP7", "camp", "key"))
    # The highlight wraps (`01CBD4`), so the last line is one NP7 back from the first.
    assert route_camp.steps_for(("items 4",), "pool", 4)[:2] == (
        ("NP7", "camp", "key"), ("V", "camp_sheet_items_4", "key"))
    assert route_camp.normalise(("items",)) == ("items 1",)
    assert route_camp.is_items("camp_items_3") and route_camp.is_items("camp_items")
    assert not route_camp.is_items("camp_sheet_3") and not route_camp.is_sheet("camp_items_3")
    # The item sheet records no HEAL reading, so it is not one of the camp sheets.
    assert not route_camp.is_sheet("camp_sheet_items_3")


@pytest.mark.parametrize("text,why", [
    ("view", "reads no sheet on Pool of Radiance"),
    ("heal", "reads no sheet on Pool of Radiance"),
    ("view 2", "reads no sheet on Pool of Radiance"),
    ("items x", "is not items or items N"),
    ("items 5", "lines 1 to 4 only"),
    ("items 0", "lines 1 to 4 only"),
    ("rest 22h", "reads no sheet on Pool of Radiance"),
])
def test_pool_takes_items_for_a_line_the_party_has_and_no_sheet(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.validate_steps(tuple(text.split(";")), 4, name="pool")


@pytest.mark.parametrize("name", ["curse", "darkness"])
def test_items_is_refused_for_a_title_whose_item_routine_is_unread(name):
    with pytest.raises(RouteError,
                       match="item list is built for Pool of Radiance and Silver Blades only"):
        route_camp.parse_steps("items 2", name)


def test_the_pool_items_steps_go_between_the_first_camp_key_and_its_camp_save():
    title = route_camp.camp_title(route_pool.POOL, ("items 3",), 4, name="pool")
    at = route_pool.POOL.route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(("items 3",), "pool", 4)
    assert title.route == (*route_pool.POOL.route[:at], *added, *route_pool.POOL.route[at:])
    assert [key for key, _, kind in title.route if kind == "write"] == ["C", "D"]
    assert title.plain_keys == ()
    assert {"camp_items_3", "camp_sheet_items_3"} <= set(title.min_waits)
    # Every state an `items` step waits for is strict, the camp bar included.
    assert title.strict == route_pool.POOL.strict | {
        "camp", "camp_sheet_items_3", "camp_items_3"}
    # The other titles' camp states stay as they were.
    darkness = route_camp.camp_title(route_darkness.DARKNESS, ("view",), 6, name="darkness")
    assert darkness.strict == route_darkness.DARKNESS.strict


class PoolCampGuest(TitleGuest):
    """Pool's camp as `/program` draws it, for a party whose rows are `rows`.

    NP1 and NP7 move the highlight with a wrap, `V` shows a sheet whose bar
    offers `Items` only for a member with items, and `I` there shows his list.
    Each camp crop holds the screen, the line, whether the bar offers `Items`
    and, on the ITEMS list, the rows. `stuck` keeps the ITEMS list on screen.
    """

    def __init__(self, clock, rows, stuck=False):
        super().__init__(clock, save_key="save")
        self.rows, self.screen, self.line, self.stuck = rows, "other", 1, stuck

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout)
        size = len(NAMES)
        if self.screen == "camp" and key == "NP1":
            self.line = self.line % size + 1
        elif self.screen == "camp" and key == "NP7":
            self.line = (self.line - 2) % size + 1
        elif self.screen == "camp" and key.startswith("NP"):
            self.line = 1
        elif key == "A" and self.screen == "other":
            self.screen = "world"
        elif self.screen in ("world", "sheet_world") and key in ("V", "E"):
            self.screen = {("world", "V"): "sheet_world", ("sheet_world", "E"): "world",
                           ("world", "E"): "camp"}[(self.screen, key)]
        elif self.screen == "camp":
            self.screen = {"V": "sheet", "E": "world", "S": "save_picker"}.get(key, "other")
        elif self.screen == "sheet":
            if key == "I" and self.rows[NAMES[self.line - 1]]:
                self.screen = "items"
            elif key == "E":
                self.screen = "camp"
        elif self.screen == "items" and key == "E" and not self.stuck:
            self.screen = "sheet"
        elif self.screen == "save_picker":
            self.screen = "other"
        elif self.screen == "other" and key == "N":
            self.screen = "camp"

    def _show(self, cropped):
        if self.screen in ("camp", "sheet", "items"):
            rows = self.rows[NAMES[self.line - 1]]
            cropped.write_text(json.dumps([self.screen, self.line, bool(rows),
                                           rows if self.screen == "items" else []]))

    def capture(self, state, raw, cropped, timeout=None):
        super().capture(state, raw, cropped, timeout)
        self._show(cropped)

    def grab(self, state, raw, cropped, timeout=None):
        grabbed = super().grab(state, raw, cropped, timeout)
        self._show(cropped)
        return grabbed


class PoolCampGuard(MapGuard):
    """The fake guard map: Pool's route by crop name, and its camp screens by what the crop shows."""

    def __init__(self, guest):
        super().__init__(states=("title", "party_menu", "save_path", "load_picker", "world",
                                 "sheet", "camp_save_picker", "quit_prompt"))
        self.guest = guest

    def __contains__(self, state):
        return super().__contains__(state) or _camp_state(state)

    def __call__(self, state, path):
        if state == "camp_save_picker":
            return self.guest.screen == "save_picker"
        if _camp_state(state):
            try:
                screen, line, offers_items, _rows = json.loads(path.read_text())
            except ValueError:
                return False
            if state == "camp":
                return screen == "camp"
            wanted = int(state.rsplit("_", 1)[1]) if state[-1].isdigit() else 1
            if route_camp.is_items(state):
                return screen == "items" and line == wanted
            # The item sheet's rule is the bar with `Items` on it.
            return screen == "sheet" and offers_items and line == wanted
        return super().__call__(state, path)


def _camp_state(state):
    return state == "camp" or state.startswith("camp_sheet_items") or route_camp.is_items(state)


class RowsIdentity:
    """Identity rules for the prepared party: the loaded sheet, and each member's own ITEMS rows."""

    def __contains__(self, state):
        return state == "sheet" or route_camp.is_items(state)

    def __call__(self, state, path):
        if state == "sheet":
            return True
        _screen, line, _offers, rows = json.loads(path.read_text())
        return rows == ROWS[NAMES[line - 1]]


def _pool_items_run(tmp_path, clock, steps, *, shown=ROWS, stuck=False, guard=None):
    base = dataclasses.replace(route_pool.POOL, read_slot=_read_slot, slot_letters=_letters,
                               slot_files=_files)
    title = route_camp.camp_title(base, steps, len(NAMES), name="pool")
    slots = [("A", _slot(START, NAMES)), ("B", b"kept slot")]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "ONE"),
             "disk2": _adf(tmp_path / "disk2.adf", "TWO"),
             "save": _adf(tmp_path / "save.adf", "POOLSAVE", slots)}
    manifest = {"disks": disks, "registered": {"reg": _adf(tmp_path / "reg.adf", "REG")},
                "loaded_letter": "A", "state_a": START, "names_a": NAMES}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    guest = PoolCampGuest(clock, shown, stuck)

    def write(letter, place):
        remote = next(r for r in guest.mounted if r and r.endswith("-save.adf"))
        disk = AmigaDisk(guest.remote[remote])
        disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(place, NAMES))
        guest.remote[remote] = disk.to_bytes()

    guest._write = write
    result = acceptance.run_recon(
        path, guest=guest, guard=guard or PoolCampGuard(guest), identity=RowsIdentity(),
        holder="wish16-test", audio_proof=_audio_proof(tmp_path), title=title, accept=True)
    return guest, result


def _shot_states(result):
    return [e.get("recognized") for e in result["events"] if "recognized" in e]


def test_a_pool_camp_run_reads_the_items_rows_of_the_members_it_names(tmp_path, clock):
    steps = ("items 3", "items 1", "items 2")
    guest, result = _pool_items_run(tmp_path, clock, steps)
    assert result["error"] == "" and result["unguarded"] == []
    assert result["success"] is True, result["read"]
    keys = [c[2] for c in guest.calls if c[0] == "press"]
    camp = keys.index("E", keys.index("V") + 2)  # the camp key after the world sheet's exit
    assert keys[camp + 1:camp + 1 + len(route_camp.steps_for(steps, "pool", 4))] == [
        key for key, _, _ in route_camp.steps_for(steps, "pool", 4)]
    assert keys[camp + 1 + len(route_camp.steps_for(steps, "pool", 4))] == "S"
    recognized = _shot_states(result)
    assert [s for s in recognized if route_camp.is_items(s)] == [
        "camp_items_3", "camp_items", "camp_items_2"]
    assert guest.place == {**START, "facing": geo.SOUTH, "y": START["y"] + 1}
    assert [(e["state"], e["shot"].split("-", 1)[1], e["identity_checked"])
            for e in result["camp_item_lists"]] == [
        (state, state, True) for state in ("camp_items_3", "camp_items", "camp_items_2")]


def test_an_items_list_whose_rows_are_not_the_prepared_party_s_fails_the_run(tmp_path, clock):
    shown = {**ROWS, "GAMMA": ["FLAIL"]}
    guest, result = _pool_items_run(tmp_path, clock, ("items 3",), shown=shown)
    assert result["success"] is False
    assert "camp_items_3 shows a party other than the prepared party" in result["error"]
    assert "C" not in [c[2] for c in guest.calls if c[0] == "press"]


def _after_camp(guest):
    keys = [c[2] for c in guest.calls if c[0] == "press"]
    return keys[keys.index("E", keys.index("V") + 2) + 1:]


def test_a_sheet_that_offers_no_items_stops_the_run_before_i_is_pressed(tmp_path, clock):
    # DELTA has no items, so his sheet's bar has no `Items` (`01B528`) and its rule never matches.
    guest, result = _pool_items_run(tmp_path, clock, ("items 4",))
    assert result["success"] is False and result["unguarded"] == []
    assert "camp_sheet_items_4 screen was not recognized" in result["error"]
    assert _after_camp(guest) == ["NP7", "V"]


def test_a_screen_that_does_not_come_back_stops_the_run_with_nothing_more_pressed(
        tmp_path, clock):
    guest, result = _pool_items_run(tmp_path, clock, ("items 3",), stuck=True)
    assert result["success"] is False
    assert "camp_sheet_items_3 screen was not recognized" in result["error"]
    assert _after_camp(guest) == ["NP1", "NP1", "V", "I", "E"]


def test_a_guard_map_without_the_items_screens_is_refused_before_a_key_is_pressed(
        tmp_path, clock):
    class Lacking(PoolCampGuard):
        def __contains__(self, state):
            return state != "camp_items_3" and super().__contains__(state)

    guest = PoolCampGuest(clock, ROWS)
    with pytest.raises(RouteError, match=r"screen guard map lacks \['camp_items_3'\]"):
        _pool_items_run(tmp_path, clock, ("items 3",), guard=Lacking(guest))
