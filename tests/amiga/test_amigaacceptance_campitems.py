"""Pool of Radiance's camp item list: `items N` moves the camp highlight to line N, opens the sheet and its ITEMS list, reads the rows by the identity rule, and comes back to the camp bar."""

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
from tools.amiga import acceptance, route_camp, route_pool
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep

NAMES = ["ALPHA", "BETA", "GAMMA", "DELTA"]
#: Each member's item rows as the ITEMS list shows them; DELTA carries nothing, so his sheet
#: offers no `Items`.
ROWS = {"ALPHA": ["LONG SWORD", "CHAIN MAIL"], "BETA": ["MACE"],
        "GAMMA": ["POTION OF HEALING", "FLAIL"], "DELTA": []}


def test_items_moves_to_the_line_opens_the_sheet_and_its_list_and_comes_back():
    assert route_camp.steps_for(("items 1",), "pool", 4) == (
        ("V", "camp_sheet", "key"), ("I", "camp_items", "key"),
        ("E", "camp_sheet", "key"), ("E", "camp", "key"))
    assert route_camp.steps_for(("items 2",), "pool", 4) == (
        ("NP1", "camp", "key"), ("V", "camp_sheet_2", "key"), ("I", "camp_items_2", "key"),
        ("E", "camp_sheet_2", "key"), ("E", "camp", "key"), ("NP7", "camp", "key"))
    # The highlight wraps (`01CBD4`), so the last line is one NP7 back from the first.
    assert route_camp.steps_for(("items 4",), "pool", 4)[:2] == (
        ("NP7", "camp", "key"), ("V", "camp_sheet_4", "key"))
    assert route_camp.normalise(("items",)) == ("items 1",)
    assert route_camp.is_items("camp_items_3") and route_camp.is_items("camp_items")
    assert not route_camp.is_items("camp_sheet_3") and not route_camp.is_sheet("camp_items_3")


@pytest.mark.parametrize("text,why", [
    ("view", "item list only on Pool of Radiance"),
    ("heal", "item list only on Pool of Radiance"),
    ("rest 1h", "item list only on Pool of Radiance"),
    ("display", "item list only on Pool of Radiance"),
    ("items x", "item list only on Pool of Radiance"),
    ("items 5", "lines 1 to 4 only"),
    ("items 0", "lines 1 to 4 only"),
])
def test_pool_takes_only_items_for_a_line_the_party_has(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.validate_steps(tuple(text.split(";")), 4, name="pool")


@pytest.mark.parametrize("name", ["ssb", "curse", "darkness"])
def test_items_is_refused_for_a_title_whose_item_routine_is_unread(name):
    with pytest.raises(RouteError, match="item list is built for Pool of Radiance only"):
        route_camp.parse_steps("items 2", name)


def test_the_pool_items_steps_go_between_the_first_camp_key_and_its_camp_save():
    title = route_camp.camp_title(route_pool.POOL, ("items 3",), 4, name="pool")
    at = route_pool.POOL.route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(("items 3",), "pool", 4)
    assert title.route == (*route_pool.POOL.route[:at], *added, *route_pool.POOL.route[at:])
    assert [key for key, _, kind in title.route if kind == "write"] == ["C", "D"]
    assert title.plain_keys == ()
    assert {"camp_items_3", "camp_items"} <= set(title.min_waits)


class PoolCampGuest(TitleGuest):
    """Pool's camp as `/program` draws it: a highlight that NP1 and NP7 move with a wrap, a sheet on `V`, and an ITEMS list on `I` only for a member with items.

    Each camp crop holds the screen, the highlighted line and, on the ITEMS list, the rows.
    """

    def __init__(self, clock, rows):
        super().__init__(clock, save_key="save")
        self.rows, self.screen, self.line = rows, "other", 1

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
        elif self.screen == "items" and key == "E":
            self.screen = "sheet"
        elif self.screen == "save_picker":
            self.screen = "other"
        elif self.screen == "other" and key == "N":
            self.screen = "camp"

    def _show(self, cropped):
        if self.screen in ("camp", "sheet", "items"):
            rows = self.rows[NAMES[self.line - 1]] if self.screen == "items" else []
            cropped.write_text(json.dumps([self.screen, self.line, rows]))

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
        return (super().__contains__(state) or state == "camp" or route_camp.is_sheet(state)
                or route_camp.is_items(state))

    def __call__(self, state, path):
        if state == "camp_save_picker":
            return self.guest.screen == "save_picker"
        if state == "camp" or route_camp.is_sheet(state) or route_camp.is_items(state):
            try:
                screen, line, _rows = json.loads(path.read_text())
            except ValueError:
                return False
            if state == "camp":
                return screen == "camp"
            kind = "items" if route_camp.is_items(state) else "sheet"
            wanted = int(state.rsplit("_", 1)[1]) if state[-1].isdigit() else 1
            return state in self and screen == kind and line == wanted
        return super().__call__(state, path)


class RowsIdentity:
    """Identity rules for the prepared party: the loaded sheet, and each ITEMS list showing its member's own rows."""

    def __contains__(self, state):
        return state == "sheet" or route_camp.is_items(state)

    def __call__(self, state, path):
        if state == "sheet":
            return True
        _screen, line, rows = json.loads(path.read_text())
        return rows == ROWS[NAMES[line - 1]]


def _pool_items_run(tmp_path, clock, steps, *, shown=ROWS):
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
    guest = PoolCampGuest(clock, shown)

    def write(letter, place):
        remote = next(r for r in guest.mounted if r and r.endswith("-save.adf"))
        disk = AmigaDisk(guest.remote[remote])
        disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(place, NAMES))
        guest.remote[remote] = disk.to_bytes()

    guest._write = write
    result = acceptance.run_recon(
        path, guest=guest, guard=PoolCampGuard(guest), identity=RowsIdentity(),
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


def test_an_items_list_whose_rows_are_not_the_prepared_party_s_fails_the_run(tmp_path, clock):
    shown = {**ROWS, "GAMMA": ["FLAIL"]}
    guest, result = _pool_items_run(tmp_path, clock, ("items 3",), shown=shown)
    assert result["success"] is False
    assert "camp_items_3 shows a party other than the prepared party" in result["error"]
    assert "C" not in [c[2] for c in guest.calls if c[0] == "press"]


def test_a_member_with_no_items_shows_no_list_and_the_camp_save_picker_stops_the_run(
        tmp_path, clock):
    # The sheet offers no `Items` (`01B528`), so `I` leaves it on screen and the two exits
    # that follow land a screen early; the strict save picker then stops the run before C.
    guest, result = _pool_items_run(tmp_path, clock, ("items 4",))
    assert result["unguarded"][0] == "camp_items_4"
    assert result["success"] is False
    assert "camp_save_picker screen was not recognized" in result["error"]
    assert "C" not in [c[2] for c in guest.calls if c[0] == "press"]
