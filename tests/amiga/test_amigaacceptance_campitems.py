"""Pool of Radiance's camp item list: `items N` opens line N's ITEMS list on guarded screens."""

from __future__ import annotations

import dataclasses
import json
import pathlib

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


# Pools of Darkness' item routine is read now, so only Curse is left without one; the message
# names the three titles that have it.
@pytest.mark.parametrize("name", ["curse"])
def test_items_is_blocked_for_a_title_whose_item_routine_is_unread(name):
    with pytest.raises(RouteError, match="item list is built for Pool of Radiance, "
                                         "Pools of Darkness and Silver Blades only"):
        route_camp.parse_steps("items 2", name)


def test_darkness_camp_highlight_wraps_on_np2_and_np8():
    assert "darkness" in route_camp.WRAPS
    assert route_camp.steps_for(("items 2",), "darkness", 6)[0] == ("NP2", "camp", "key")
    # The last of six lines is one NP8 back from the first, and NP2 forward brings it home.
    steps = route_camp.steps_for(("items 6",), "darkness", 6)
    assert steps[0] == ("NP8", "camp", "key") and steps[-1] == ("NP2", "camp", "key")


def test_darkness_items_goes_v_i_e_e():
    assert route_camp.steps_for(("items 1",), "darkness", 6) == (
        ("V", "camp_sheet_items", "key"), ("I", "camp_items", "key"),
        ("E", "camp_sheet_items", "key"), ("E", "camp", "key"))


def test_ready_presses_np2_down_to_the_row_then_r_on_the_redrawn_row():
    assert route_camp.steps_for(("ready 1 7",), "darkness", 6) == (
        ("V", "camp_sheet_items", "key"), ("I", "camp_items", "key"),
        *[("NP2", f"camp_items_row{n}", "key") for n in range(2, 8)],
        ("R", "camp_items_row7", "key"),
        ("E", "camp_sheet_items", "key"), ("E", "camp", "key"))
    assert route_camp.steps_for(("ready 1 1",), "darkness", 6)[2] == (
        "R", "camp_items", "key")
    assert route_camp.steps_for(("ready 3 1",), "darkness", 6)[:2] == (
        ("NP2", "camp", "key"), ("NP2", "camp", "key"))


@pytest.mark.parametrize("text,why", [
    ("ready 1 0", "rows 1 to 16 only"),
    ("ready 1 17", "rows 1 to 16 only"),
    ("ready 7 1", "lines 1 to 6 only"),
    ("ready 1", "is not ready N I"),
    ("ready x 1", "is not ready N I"),
])
def test_ready_blocks_a_place_that_is_not_a_line_and_row(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.validate_steps((text,), 6, name="darkness")


@pytest.mark.parametrize("name", ["pool", "ssb", "curse"])
def test_ready_is_blocked_for_a_title_whose_ready_routine_is_unread(name):
    with pytest.raises(RouteError, match="READY is built for Pools of Darkness only"):
        route_camp.validate_steps(("ready 1 1",), 4, name=name)


def test_ready_steps_go_before_the_camp_save_and_every_state_is_strict():
    tokens = ("ready 1 7", "ready 1 7")
    title = route_camp.camp_title(route_darkness.DARKNESS, tokens, 6, name="darkness")
    at = route_darkness.DARKNESS.route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(tokens, "darkness", 6)
    assert title.route == (*route_darkness.DARKNESS.route[:at], *added,
                           *route_darkness.DARKNESS.route[at:])
    assert {"camp", "camp_sheet_items", "camp_items",
            *(f"camp_items_row{n}" for n in range(2, 8))} <= set(title.strict)


def test_ready_marks_land_after_the_steps_before_them():
    title = route_camp.camp_title(route_darkness.DARKNESS, ("ready 1 2", "snapshot a"), 6,
                                  name="darkness")
    marks = route_camp.camp_marks(title, ("ready 1 2", "snapshot a"), 6, name="darkness")
    assert list(marks.values()) == [(("snapshot", "a"),)]
    assert title.route[next(iter(marks)) - 1] == ("E", "camp", "key")


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


def test_a_guard_map_without_the_items_screens_is_blocked_before_a_key_is_pressed(
        tmp_path, clock):
    class Lacking(PoolCampGuard):
        def __contains__(self, state):
            return state != "camp_items_3" and super().__contains__(state)

    guest = PoolCampGuest(clock, ROWS)
    with pytest.raises(RouteError, match=r"screen guard map lacks \['camp_items_3'\]"):
        _pool_items_run(tmp_path, clock, ("items 3",), guard=Lacking(guest))


def test_use_casts_each_case_spell_and_returns_to_the_same_row_of_the_list():
    # HILDE is line 5 of 7, reached backwards; the case is row 3. Each spell is U, C, then S at the target picker or Y at
    # the combat-only prompt, and the list comes back with the row still highlighted.
    assert route_camp.steps_for(("use 5 3 SY",), "darkness", 7) == (
        ("NP8", "camp", "key"), ("NP8", "camp", "key"), ("NP8", "camp", "key"),
        ("V", "camp_sheet_items_5", "key"),
        ("I", "camp_items_5", "key"),
        ("NP2", "camp_items_5_row2", "key"), ("NP2", "camp_items_5_row3", "key"),
        ("U", "camp_use_list", "key"), ("C", "camp_use_target", "key"),
        ("S", "camp_items_5_row3", "key"),
        ("U", "camp_use_list", "key"), ("C", "camp_use_combat", "key"),
        ("Y", "camp_items_5_row3", "key"),
        ("E", "camp_sheet_items_5", "key"), ("E", "camp", "key"),
        ("NP2", "camp", "key"), ("NP2", "camp", "key"), ("NP2", "camp", "key"))


@pytest.mark.parametrize("text,why", [
    ("use 1 1", "is not use N I followed by one S or Y per spell"),
    ("use 1 1 X", "is not use N I followed by one S or Y per spell"),
    ("use 1 1 SYx", "is not use N I followed by one S or Y per spell"),
    ("use 1 0 S", "rows 1 to 16 only"),
    ("use 1 17 S", "rows 1 to 16 only"),
    ("use 7 1 S", "lines 1 to 6 only"),
])
def test_use_blocks_a_place_or_answer_it_cannot_drive(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.validate_steps((text,), 6, name="darkness")


@pytest.mark.parametrize("name", ["pool", "ssb", "curse"])
def test_use_is_blocked_for_a_title_whose_use_routine_is_unread(name):
    with pytest.raises(RouteError, match="USE is built for Pools of Darkness only"):
        route_camp.validate_steps(("use 1 1 S",), 4, name=name)


def test_use_states_are_strict_and_the_steps_go_before_the_camp_save():
    tokens = ("use 1 1 SY",)
    title = route_camp.camp_title(route_darkness.DARKNESS, tokens, 6, name="darkness")
    at = route_darkness.DARKNESS.route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(tokens, "darkness", 6)
    assert title.route == (*route_darkness.DARKNESS.route[:at], *added,
                           *route_darkness.DARKNESS.route[at:])
    assert {"camp", "camp_sheet_items", "camp_items", "camp_use_list", "camp_use_target",
            "camp_use_combat"} <= set(title.strict)


def test_use_marks_land_after_the_steps_before_them():
    tokens = ("use 1 2 S", "snapshot a")
    title = route_camp.camp_title(route_darkness.DARKNESS, tokens, 6, name="darkness")
    marks = route_camp.camp_marks(title, tokens, 6, name="darkness")
    assert list(marks.values()) == [(("snapshot", "a"),)]
    assert title.route[next(iter(marks)) - 1] == ("E", "camp", "key")


def test_the_darkness_guards_tell_the_spell_list_the_target_picker_and_the_prompt_apart():
    guards = json.loads(pathlib.Path(route_darkness.__file__).with_name(
        "guards_darkness.json").read_text())["guards"]
    assert {"camp_use_list", "camp_use_target", "camp_use_combat"} <= set(guards)


def _play_use(steps, spells, row):
    """The screens a case's `U`, `C` and answer keys lead to, for spells that ask `spells` in turn.

    Returns the screen after every step: a spell that asks whom shows the target picker, a
    combat-only one shows its prompt, any other name (a thief's `oops!`, "Must be readied") shows
    a screen of its own that no answer leaves, and either answer returns to the list with the row kept.
    """
    screen, asked, shown = "camp", iter(spells), []
    for key, _state, _ in steps:
        if screen == "camp" and key == "V":
            screen = "camp_sheet_items_5"
        elif screen == "camp_sheet_items_5" and key == "I":
            screen = "camp_items_5"
        elif screen.startswith("camp_items_5") and key == "NP2":
            at = int(screen.rsplit("row", 1)[1]) + 1 if "row" in screen else 2
            screen = f"camp_items_5_row{at}"
        elif screen.startswith("camp_items_5") and key == "U":
            screen = "camp_use_list"
        elif screen == "camp_use_list" and key == "C":
            screen = {"target": "camp_use_target", "combat": "camp_use_combat"}.get(
                (asked_next := next(asked)), f"camp_use_{asked_next}")
        elif screen == "camp_use_target" and key == "S" or (
                screen == "camp_use_combat" and key == "Y"):
            screen = f"camp_items_5_row{row}" if row > 1 else "camp_items_5"
        elif screen.startswith("camp_items_5") and key == "E":
            screen = "camp_sheet_items_5"
        elif screen == "camp_sheet_items_5" and key == "E":
            screen = "camp"
        elif key.startswith("NP"):
            pass
        else:
            screen = f"unexpected-{screen}-{key}"
        shown.append(screen)
    return shown


@pytest.mark.parametrize("answers,spells", [
    ("S", ["target"]), ("Y", ["combat"]), ("SYS", ["target", "combat", "target"])])
def test_each_use_branch_shows_the_screen_its_step_waits_for(answers, spells):
    steps = route_camp.steps_for((f"use 5 3 {answers}",), "darkness", 7)
    shown = _play_use(steps, spells, 3)
    assert all(s == state or key.startswith("NP") and state == "camp"
               for s, (key, state, _) in zip(shown, steps)), shown
    assert shown[-1] == "camp"


def test_a_spell_that_asks_whom_is_not_answered_with_the_combat_only_key():
    steps = route_camp.steps_for(("use 5 3 Y",), "darkness", 7)
    shown = _play_use(steps, ["target"], 3)
    expected = [state for _, state, _ in steps]
    assert shown != expected
    assert shown[expected.index("camp_use_combat")] == "camp_use_target"


@pytest.mark.parametrize("what", ["oops", "must_be_readied"])
def test_a_screen_after_cast_that_is_neither_prompt_stops_the_run_before_any_answer(what):
    steps = route_camp.steps_for(("use 5 3 SY",), "darkness", 7)
    shown = _play_use(steps, [what], 3)
    # The runner stops at the first step whose screen is not the state it waits for.
    stop = next(i for i, (s, (_, state, _)) in enumerate(zip(shown, steps)) if s != state)
    assert steps[stop][0] == "C" and shown[stop] == f"camp_use_{what}"
    assert not {"S", "Y"} & {key for key, _, _ in steps[:stop + 1]}
    assert {"camp_use_target", "camp_use_combat"} <= set(
        route_camp.camp_title(route_darkness.DARKNESS, ("use 5 3 SY",), 7,
                              name="darkness").strict)


def test_use_answers_are_read_in_either_case_and_parse_to_the_same_steps():
    upper = route_camp.parse_steps("use 5 3 SYY", "darkness")
    assert route_camp.parse_steps("use 5 3 syy", "darkness") == upper == ("use 5 3 SYY",)
    assert route_camp.steps_for(upper, "darkness", 7) == route_camp.steps_for(("use 5 3 SYY",), "darkness", 7)
