"""Silver Blades' camp item list and JOIN, and the load's SCROLLS DROPPED!, on a published route.

`items N` opens line N's item list; `join N I` highlights row I there, presses
`J`, grabs the screen at once for JOIN's message and settles on the list JOIN
redrew. Every key of both goes out on a strict state its guard recognised. The
accept route tests the SCROLLS DROPPED! rule on every grab while it waits for
the loaded menu.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import MapGuard
from tests.amiga.test_amigaacceptance_camp import CampGuest, CampIdentity
from tests.amiga.test_amigaacceptance_title import (
    NAMES,
    _adf,
    _files,
    _letters,
    _read_slot,
    _slot,
)
from tests.amiga.test_amigaacceptance_titles import START
from tools.amiga import acceptance as foundation
from tools.amiga import route_camp, route_silver_blades
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep

#: Each member's item rows as the ITEMS list shows them, and BETA's after a JOIN that works.
ROWS = {"ALPHA": ["LONG SWORD"],
        "BETA": ["MACE", "MAGE SCROLL", "MAGE SCROLL", "PLATE MAIL"]}
JOINED = ["MACE", "2 MAGE SCROLLS", "PLATE MAIL"]


# --- the steps -----------------------------------------------------------------------------
def test_items_n_opens_the_sheet_offering_items_then_its_list_and_comes_back():
    assert route_camp.steps_for(("items 2",), "ssb", 2) == (
        ("NP2", "camp", "key"), ("V", "camp_sheet_items_2", "key"),
        ("I", "camp_items_2", "key"), ("E", "camp_sheet_items_2", "key"),
        ("E", "camp", "key"), ("NP8", "camp", "key"))


def test_join_n_i_highlights_row_i_presses_j_and_leaves_through_the_sheet():
    assert route_camp.steps_for(("join 2 3",), "ssb", 2) == (
        ("NP2", "camp", "key"), ("V", "camp_sheet_items_2", "key"),
        ("I", "camp_items_2", "key"),
        ("NP2", "camp_items_2_row2", "key"), ("NP2", "camp_items_2_row3", "key"),
        ("J", "camp_join_2", "key"),
        ("E", "camp_sheet_items_2", "key"), ("E", "camp", "key"), ("NP8", "camp", "key"))
    assert route_camp.steps_for(("join 1 1",), "ssb", 2) == (
        ("V", "camp_sheet_items", "key"), ("I", "camp_items", "key"),
        ("J", "camp_join", "key"),
        ("E", "camp_sheet_items", "key"), ("E", "camp", "key"))
    assert route_camp.joined_after("camp_join_2") == "camp_joined_2"
    assert route_camp.is_items("camp_items_2_row16") and not route_camp.is_items("camp_join_2")
    assert route_camp.is_join("camp_join") and not route_camp.is_join("camp_joined")
    assert route_camp.is_joined("camp_joined_8") and not route_camp.is_sheet("camp_joined_2")


@pytest.mark.parametrize("steps", [("join 2 3",), ("view", "items 2", "rest 1h", "join 1 2")])
def test_every_key_of_an_items_or_join_step_goes_out_on_a_strict_state(steps):
    title = route_camp.camp_title(route_silver_blades.published_title("A"), steps, 2,
                                  name="ssb")
    route = list(title.route)
    at = route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(steps, "ssb", 2)
    assert tuple(route[at - len(added):at]) == added
    item_states = set()
    for token in steps:
        if token.split()[0] not in ("items", "join"):
            continue
        # Each key goes out on the state the step before it reached; the first on the camp bar.
        before = route_camp.CAMP
        for key, state, _ in route_camp.steps_for((token,), "ssb", 2):
            assert before in title.strict, (token, key, before)
            item_states.add(state)
            before = state
        assert before in title.strict
    joins = {s for s in item_states if route_camp.is_join(s)}
    assert {route_camp.joined_after(s) for s in joins} <= title.strict
    assert {route_camp.CAMP, *item_states} <= title.strict
    # The sheets and rest menu of the other steps stay measurable, as before.
    assert "camp_sheet" not in title.strict and "rest_menu" not in title.strict
    for state in joins:
        assert title.min_waits[state] == 0.0
        assert title.min_waits[route_camp.joined_after(state)] == route_camp.JOINED_WAIT


@pytest.mark.parametrize("text,why", [
    ("join", "is not join N I"),
    ("join 1", "is not join N I"),
    ("join x 2", "is not join N I"),
    ("join 3 1", "lines 1 to 2 only"),
    ("join 1 0", "rows 1 to 16 only"),
    ("join 1 17", "rows 1 to 16 only"),
    ("items 3", "lines 1 to 2 only"),
    ("items x", "is not items or items N"),
])
def test_silver_blades_refuses_an_items_or_join_step_it_cannot_drive(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.validate_steps((text,), 2, name="ssb")


@pytest.mark.parametrize("name", ["curse", "darkness"])
def test_join_is_refused_for_a_title_whose_join_routine_is_unread(name):
    with pytest.raises(RouteError, match="JOIN is built for Silver Blades only"):
        route_camp.validate_steps(("join 1 1",), 6, name=name)


def test_pool_still_takes_only_items():
    with pytest.raises(RouteError, match="item list only on Pool of Radiance"):
        route_camp.validate_steps(("join 1 1",), 4, name="pool")


def test_silver_blades_takes_items_and_join_beside_its_other_camp_steps():
    assert route_camp.parse_steps("view;items 2;join 2 3;rest 1h", "ssb") == (
        "view", "items 2", "join 2 3", "rest 1h")
    assert route_camp.sheet_lines("ssb") == (route_camp.SHEET_LINES["ssb"],
                                             route_camp.HEAL_LINES["ssb"])


# --- a run ---------------------------------------------------------------------------------
class ItemsGuest(CampGuest):
    """Silver Blades' camp, sheet and item list, as `/Secret` draws them, for `ROWS`.

    NP2 and NP8 move the camp highlight without a wrap, `V` shows a sheet whose bar offers
    `Items` while the member has items, and `I` shows his list with row 1 highlighted, where
    NP2 moves the highlight down unless `stuck`. `J` answers `answer`: a message key from
    `route_camp.JOIN_MESSAGES`, drawn on the next `message_grabs` grabs, or None, which joins
    the rows into `JOINED`. Each camp crop holds what the screen shows.
    """

    def __init__(self, clock, *, answer=None, message_grabs=1, stuck=False, dropped=False):
        super().__init__(clock)
        self.answer, self.message_grabs, self.stuck = answer, message_grabs, stuck
        self.screen, self.line, self.row, self.message = "other", 1, 1, None
        self.rows = {name: list(rows) for name, rows in ROWS.items()}
        self.dropped, self.loaded = dropped, False

    def press(self, holder, key, timeout=None):
        was_camped = self.camped
        super().press(holder, key, timeout)
        if self.screen == "other" and key == "A":
            self.loaded = True  # the published route loads slot A
        elif self.loaded and key != "A":
            self.loaded = False
        if not was_camped:
            if self.camped:
                self.screen = "camp"
            return
        rows = self.rows[NAMES[self.line - 1]]
        if self.screen == "camp":
            if key == "NP2":
                self.line = min(self.line + 1, len(NAMES))
            elif key == "NP8":
                self.line = max(self.line - 1, 1)
            elif key == "V":
                self.screen = "sheet"
            elif key == "S":
                self.screen = "save_picker"
        elif self.screen == "sheet":
            if key == "I" and rows:
                self.screen, self.row = "items", 1
            elif key == "E":
                self.screen = "camp"
        elif self.screen == "items":
            if key == "NP2" and not self.stuck:
                self.row = min(self.row + 1, len(rows))
            elif key == "J":
                if self.answer is None:
                    self.rows[NAMES[self.line - 1]] = list(JOINED)
                    self.row = 1
                else:
                    self.message, self.left = self.answer, self.message_grabs
            elif key == "E":
                self.screen = "sheet"
        elif self.screen == "save_picker":
            self.screen = "other"
        if self.screen == "other" and key == "N":
            self.screen = "camp"

    def _show(self, cropped):
        if self.loaded and self.dropped:
            cropped.write_text(json.dumps({"screen": "loaded", "message": "scrolls_dropped"}))
            return
        if self.screen not in ("camp", "sheet", "items"):
            return
        rows = self.rows[NAMES[self.line - 1]]
        message = None
        if self.screen == "items" and self.message is not None:
            message = self.message
            self.left -= 1
            if self.left <= 0:
                self.message = None
        cropped.write_text(json.dumps({
            "screen": self.screen, "line": self.line, "items": bool(rows),
            "rows": rows if self.screen == "items" else [], "row": self.row,
            "message": message}))

    def capture(self, state, raw, cropped, timeout=None):
        super().capture(state, raw, cropped, timeout)
        self._show(cropped)

    def grab(self, state, raw, cropped, timeout=None):
        grabbed = super().grab(state, raw, cropped, timeout)
        self._show(cropped)
        return grabbed


def _shown(path):
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def _wanted(state):
    tail = state.split("_row")[0].rsplit("_", 1)[1]
    return int(tail) if tail.isdigit() else 1


def _item_state(state):
    return (state == "camp" or state.startswith("camp_sheet_items") or route_camp.is_items(state)
            or route_camp.is_join(state) or route_camp.is_joined(state))


class ItemsGuard(MapGuard):
    """The published route by crop name, and the camp item screens by what the crop shows.

    An item list's guard is its frame: the screen and the line, never the highlight or the
    rows, which are the identity rule's. `messages` are the message rules the map holds.
    """

    def __init__(self, guest, *, messages=None, lacking=(), load_rule=False):
        if messages is None:
            messages = tuple(route_camp.JOIN_MESSAGES)
        states = [*MapGuard.ALL, "camp_sheet", "camp_sheet_heal", "camp_sheet_spent",
                  "heal_whom", "rest_menu", *messages]
        if load_rule:
            states.append(route_silver_blades.LOAD_MESSAGE)
        super().__init__(states=states)
        self.guest, self.messages, self.lacking = guest, set(messages), set(lacking)
        self.load_rule = load_rule

    def __contains__(self, state):
        if state in self.lacking:
            return False
        return super().__contains__(state) or _item_state(state)

    def __call__(self, state, path):
        shown = _shown(path)
        if state == route_silver_blades.LOAD_MESSAGE:
            return self.load_rule and bool(shown) and shown.get("message") == state
        if state in self.messages:
            return bool(shown) and shown.get("message") == state
        if state == "camp_save_picker":
            return self.guest.screen == "save_picker"
        if _item_state(state):
            if not shown or "line" not in shown:
                return False
            if state == "camp":
                return shown["screen"] == "camp"
            if state.startswith("camp_sheet_items"):
                return shown["screen"] == "sheet" and shown["items"] and \
                    shown["line"] == _wanted(state)
            return shown["screen"] == "items" and shown["line"] == _wanted(state)
        return super().__call__(state, path)


class RowsIdentity(CampIdentity):
    """The party's own rows: before JOIN with the state's row highlighted, and after it."""

    def __init__(self, after=None):
        super().__init__()
        self.after = after

    def __contains__(self, state):
        return (super().__contains__(state) or route_camp.is_items(state)
                or route_camp.is_joined(state))

    def __call__(self, state, path):
        if not (route_camp.is_items(state) or route_camp.is_joined(state)):
            return super().__call__(state, path)
        shown = _shown(path)
        name = NAMES[shown["line"] - 1]
        if route_camp.is_joined(state):
            return shown["rows"] == (self.after or ROWS[name])
        row = int(state.rsplit("_row", 1)[1]) if "_row" in state else 1
        return shown["rows"] == ROWS[name] and shown["row"] == row


def _run(tmp_path, clock, monkeypatch, steps, *, guest=None, guard=None, identity=None):
    published = route_silver_blades.published_title("A")

    def read_slot(disk, slot):
        return {**_read_slot(disk, slot), "clock": "05:22" if slot == "F" else "04:20"}

    base = dataclasses.replace(published, read_slot=read_slot, slot_letters=_letters,
                               slot_files=_files)
    title = route_camp.camp_title(base, steps, len(NAMES), name="ssb")
    slots = [("A", _slot(START, NAMES))]
    disks = {"df0": _adf(tmp_path / "df0.adf", "ONE", slots),
             "df1": _adf(tmp_path / "df1.adf", "TWO")}
    registered = {key: _adf(tmp_path / f"{key}.adf", key.upper(), slots)
                  for key in ("source", "report", "published", "disk_one", "disk_two")}
    (tmp_path / "published.adf").write_bytes((tmp_path / "df0.adf").read_bytes())
    registered["published"]["sha256"] = disks["df0"]["sha256"]
    (tmp_path / "disk_two.adf").write_bytes((tmp_path / "df1.adf").read_bytes())
    registered["disk_two"]["sha256"] = disks["df1"]["sha256"]
    manifest = {"mode": "published_disk_one", "issue": "628", "title": "ssb",
                "source_port": "c64", "loaded_letter": "A", "state_a": START,
                "names_a": NAMES, "clock_a": "04:20", "disks": disks,
                "registered": registered, "expected_after": None, "camp": list(steps)}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    guest = guest or ItemsGuest(clock)
    guest.place = dict(START)
    monkeypatch.setattr(foundation, "_published_manifest", lambda *_: (manifest, title))
    result = foundation.run_recon(
        path, guest=guest, holder="wish4-test", audio_proof=_audio_proof(tmp_path),
        title=title, guard=guard or ItemsGuard(guest), identity=identity or RowsIdentity(),
        accept=True, published_disk_one=True, published_name="ssb",
        journal_python="/usr/bin/python3", preflight=lambda _python: None,
        answer=lambda *_: (0, "answered"))
    return guest, result


def _camp_keys(guest):
    keys = [c[2] for c in guest.calls if c[0] == "press"]
    camp = keys.index("NP8") + 2  # the second step's key, then the camp key
    return keys[camp + 1:]


def _why(result):
    return {k: result.get(k) for k in (
        "error", "unguarded", "menu_save_problems", "camp_save_problems", "walk",
        "kept_unchanged", "extra_saves", "published_files_preserved", "control_clock_matches",
        "after_clock_advanced", "disks_unchanged", "registered_unchanged", "working_unchanged",
        "fetched_save_error")}


def test_a_join_the_game_refuses_records_its_message_and_the_rows_after(
        tmp_path, clock, monkeypatch):
    steps = ("items 1", "join 2 3")
    guest, result = _run(tmp_path, clock, monkeypatch, steps,
                         guest=ItemsGuest(clock, answer="join_too_many"))
    assert result["error"] == "" and result["unguarded"] == []
    assert result["success"] is True, _why(result)
    added = route_camp.steps_for(steps, "ssb", 2)
    assert _camp_keys(guest)[:len(added) + 1] == [key for key, _, _ in added] + ["S"]
    [join] = result["camp_joins"]
    assert join["state"] == "camp_join_2" and join["message"] == "join_too_many"
    assert join["shot"].endswith("-camp_join_2")
    assert join["message_shot"].endswith("-camp_join_2-join_too_many.png")
    assert join["messages_ruled"] == list(route_camp.JOIN_MESSAGES)
    assert join["joined"]["state"] == "camp_joined_2" and join["joined"]["identity_checked"]
    # The redrawn list is settled on only after JOIN's message has had its time.
    joined = next(e for e in result["events"] if str(e.get("crop", "")).endswith(
        "-camp_joined_2.png"))
    assert joined["recognized"] == "camp_joined_2"
    assert [e["state"] for e in result["camp_item_lists"]] == [
        "camp_items", "camp_items_2", "camp_items_2_row2", "camp_items_2_row3"]
    assert any(line.endswith("JOIN answered 'Too many Bundles!'; the redrawn list matches "
                             "the identity rule cut for this party")
               for line in result["read"]["verdicts"])


def test_a_join_that_works_shows_no_message_and_the_joined_rows(tmp_path, clock, monkeypatch):
    guest, result = _run(tmp_path, clock, monkeypatch, ("join 2 2",),
                         identity=RowsIdentity(after=JOINED))
    assert result["success"] is True, _why(result)
    [join] = result["camp_joins"]
    assert join["message"] is None and join["message_shot"] is None
    assert join["joined"]["identity_checked"] is True
    assert guest.rows["BETA"] == JOINED
    assert any(line.endswith("no JOIN message rule matched; the redrawn list matches the "
                             "identity rule cut for this party")
               for line in result["read"]["verdicts"])


def test_a_join_message_drawn_before_the_list_matched_is_still_recorded(
        tmp_path, clock, monkeypatch):
    class Late(ItemsGuard):
        """The list's frame is not recognised while the message covers part of it."""

        def __call__(self, state, path):
            shown = _shown(path)
            if route_camp.is_join(state) and shown and shown.get("message"):
                return False
            return super().__call__(state, path)

    guest = ItemsGuest(clock, answer="join_no_similar", message_grabs=1)
    _, result = _run(tmp_path, clock, monkeypatch, ("join 2 3",), guest=guest,
                     guard=Late(guest))
    assert result["success"] is True, _why(result)
    assert result["camp_joins"][0]["message"] == "join_no_similar"


def test_a_guard_map_with_no_message_rule_says_the_message_was_not_read(
        tmp_path, clock, monkeypatch):
    guest = ItemsGuest(clock, answer="join_too_many")
    _, result = _run(tmp_path, clock, monkeypatch, ("join 2 3",), guest=guest,
                     guard=ItemsGuard(guest, messages=()))
    [join] = result["camp_joins"]
    assert join["message"] is None and join["messages_ruled"] == []
    assert any("the guard map holds no JOIN message rule, so the message line was not read"
               in line for line in result["read"]["verdicts"])


def test_a_highlight_that_did_not_move_stops_the_run_before_j(tmp_path, clock, monkeypatch):
    guest, result = _run(tmp_path, clock, monkeypatch, ("join 2 3",),
                         guest=ItemsGuest(clock, stuck=True))
    assert result["success"] is False
    assert "camp_items_2_row2 shows a party other than the prepared party" in result["error"]
    assert "J" not in _camp_keys(guest)
    assert "F" not in _camp_keys(guest)


def test_rows_other_than_the_prepared_party_s_after_join_stop_the_run_before_e(
        tmp_path, clock, monkeypatch):
    # The game joined the rows, but the run expected JOIN to refuse.
    guest, result = _run(tmp_path, clock, monkeypatch, ("join 2 2",))
    assert result["success"] is False
    assert "camp_joined_2 shows a party other than the prepared party" in result["error"]
    keys = _camp_keys(guest)
    assert keys[-1] == "J" and "F" not in keys


def test_a_member_with_no_items_stops_the_run_at_his_sheet_before_i(tmp_path, clock, monkeypatch):
    guest = ItemsGuest(clock)
    guest.rows["BETA"] = []
    _, result = _run(tmp_path, clock, monkeypatch, ("join 2 1",), guest=guest)
    assert result["success"] is False
    assert "camp_sheet_items_2 screen was not recognized" in result["error"]
    assert _camp_keys(guest) == ["NP2", "V"]


@pytest.mark.parametrize("lacking", ["camp_joined_2", "camp_join_2", "camp_items_2_row3"])
def test_a_guard_map_without_a_join_screen_is_refused_before_a_key_is_pressed(
        tmp_path, clock, monkeypatch, lacking):
    guest = ItemsGuest(clock)
    with pytest.raises(RouteError, match=rf"screen guard map lacks .*'{lacking}'"):
        _run(tmp_path, clock, monkeypatch, ("join 2 3",), guest=guest,
             guard=ItemsGuard(guest, lacking=(lacking,)))
    assert [c for c in guest.calls if c[0] == "press"] == []


# --- the load ------------------------------------------------------------------------------
def test_scrolls_dropped_after_the_load_is_recorded_by_its_rule(tmp_path, clock, monkeypatch):
    guest = ItemsGuest(clock, dropped=True)
    _, result = _run(tmp_path, clock, monkeypatch, ("items 1",), guest=guest,
                     guard=ItemsGuard(guest, load_rule=True))
    shown = result["load_message"]
    assert shown["state"] == "scrolls_dropped" and shown["guarded"] is True
    assert shown["shown"] is True and shown["shot"].endswith("-loaded_menu-scrolls_dropped.png")
    assert any(line.startswith("SCROLLS DROPPED! was drawn after the load")
               for line in result["read"]["verdicts"])


def test_a_load_with_no_scrolls_dropped_is_recorded_as_not_drawn(tmp_path, clock, monkeypatch):
    guest = ItemsGuest(clock)
    _, result = _run(tmp_path, clock, monkeypatch, ("items 1",), guest=guest,
                     guard=ItemsGuard(guest, load_rule=True))
    assert result["success"] is True, _why(result)
    shown = result["load_message"]
    assert shown["guarded"] is True and shown["shown"] is False and shown["grabs"] >= 1
    assert any(line.startswith("SCROLLS DROPPED! was not drawn on any of")
               for line in result["read"]["verdicts"])


def test_a_guard_map_with_no_scrolls_dropped_rule_reads_nothing_about_the_load(
        tmp_path, clock, monkeypatch):
    guest = ItemsGuest(clock, dropped=True)
    _, result = _run(tmp_path, clock, monkeypatch, ("items 1",), guest=guest)
    assert result["load_message"] == {"state": "scrolls_dropped", "guarded": False,
                                      "grabs": result["load_message"]["grabs"],
                                      "shown": None, "shot": None}
    assert ("the guard map holds no SCROLLS DROPPED! rule, so the load message was not read"
            in result["read"]["verdicts"])
