"""Pool of Radiance's camp rest and effects list: `rest DURATION` and `display` before the camp save."""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

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
)
from tools.amiga import acceptance, route_camp, route_pool
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep

NAMES = ["BRUTUS", "GRIMNIR", "ROLAND", "MAGNUS", "ASTRID", "GARRETT"]
BLESS = [1, 6, 0x80, 0]
STEPS = ("display", "rest 30m", "display")
REST_KEYS = ["R", "D", "S", "S", "M", *["A"] * 6, "R"]
DISPLAY_KEYS = ["M", "D", "E", "E"]


def test_pool_takes_rest_and_display_and_drives_them_with_the_letters_read_from_program():
    tokens = route_camp.parse_steps("display; rest 30m; display", "pool")
    assert route_camp.normalise(tokens) == ("display", "rest 30m", "display")
    assert [k for k, _, _ in route_camp.steps_for(("rest 30m",), "pool", 6)] == REST_KEYS
    assert [k for k, _, _ in route_camp.steps_for(("display",), "pool", 6)] == DISPLAY_KEYS
    assert route_camp.steps_for(("display",), "pool", 6) == (
        ("M", "camp_magic", "key"), ("D", "camp_display", "key"),
        ("E", "camp_magic", "key"), ("E", "camp", "key"))
    # A day and an hour and five minutes: one press on each field.
    assert [k for k, _, _ in route_camp.steps_for(("rest 1d1h5m",), "pool", 6)] == [
        "R", "D", "S", "S", "D", "A", "H", "A", "M", "A", "R"]
    route_camp.validate_steps(("items 2", "rest 21h55m", "display"), 6, name="pool")


@pytest.mark.parametrize("text,why", [
    ("view", "reads no sheet on Pool of Radiance"),
    ("heal 1", "reads no sheet on Pool of Radiance"),
    ("rest 22h", "reads no sheet on Pool of Radiance"),
    ("rest 12h;rest 10h", "reads no sheet on Pool of Radiance"),
    ("rest 7m", "in fives"),
    ("display 2", "is not view"),
    ("join 1 1", "JOIN is built for Silver Blades only"),
])
def test_pool_refuses_a_step_it_cannot_drive_or_a_rest_its_clock_cannot_prove(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.parse_steps(text, "pool")


def test_a_pool_camp_run_that_presses_d_saves_its_after_slot_to_f():
    title = acceptance._camp_title("pool", route_pool.POOL, list(STEPS), NAMES)
    assert title.after_letter == route_pool.POOL_CAMP_AFTER == "F"
    assert [key for key, _, kind in title.route if kind == "write"] == ["C", "F"]
    at = title.route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(STEPS, "pool", len(NAMES))
    assert title.route[at - len(added):at] == added
    assert title.route[at - len(added) - 1] == ("E", "camp", "key")
    # The rest and the effects list are measured states, not strict ones.
    assert title.strict == route_pool.POOL.strict
    assert title.wait_limits["camp"] == route_camp.REST_LIMIT
    # An items-only run presses no D, so it keeps the route's own after letter.
    items = acceptance._camp_title("pool", route_pool.POOL, ["items 2"], NAMES)
    assert items.after_letter == "D"


def test_pool_camp_title_leaves_a_route_whose_keys_miss_its_after_letter():
    assert route_pool.pool_camp_title(route_pool.POOL, ("V", "I", "E")) is route_pool.POOL
    forward = route_pool.pool_camp_title(route_pool.POOL_FORWARD, ("d",))
    assert forward.after_letter == "F" and forward.turn is None
    assert forward.measure_route == route_pool.POOL_FORWARD.measure_route


def test_accept_title_turns_pool_by_its_start_square_and_then_splices_its_camp(monkeypatch):
    monkeypatch.setattr(acceptance, "pool_title_for",
                        lambda manifest: route_pool.POOL_FORWARD)
    manifest = {"title": "pool", "camp": list(STEPS), "names_a": NAMES}
    title = acceptance.accept_title(acceptance.POOL, manifest)
    assert title.turn is None and title.after_letter == "F"
    assert ("NP2", "world", "turn") not in title.route
    assert acceptance.accept_title(acceptance.POOL, {"names_a": NAMES}) is (
        route_pool.POOL_FORWARD)


def test_a_pool_prepare_keeps_camp_steps_and_the_cli_reads_them(monkeypatch, capsys):
    seen = {}

    def fake(title, run_id, **kw):
        seen.update(kw, title=title)
        return "prepare.json"

    monkeypatch.setattr(acceptance, "prepare", fake)
    assert acceptance.main(["prepare", "--title", "pool", "--run-id", "x", "--issue", "273",
                            "--camp", "display;rest 30m;display", "--substitute", "out.adf"]) == 0
    assert seen["camp"] == STEPS and seen["title"] is acceptance.POOL
    assert "pool" in acceptance.CAMP_TITLES


# --- one camp run on a fake game ----------------------------------------------------------------


def _slot(place, effects):
    return json.dumps({"place": place, "names": NAMES, "effects": effects}).encode()


def _read_slot(disk, letter):
    try:
        raw = disk.read_file(f"/SAVE/savgam{letter}.sav")
    except Exception:
        return {"missing": True, "sha256": None}
    data = json.loads(raw)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "place": data["place"],
            "names": data["names"], "effects": data["effects"]}


class RestingGuest(TitleGuest):
    """Saves C and F with the party's effects, which a rest past their time empties.

    `D` is only ever a menu key here: a run that saved slot D would show as an extra save.
    """

    def __init__(self, clock):
        super().__init__(clock, save_key="save")
        self.effects = {name: [BLESS] for name in NAMES}
        self.resting = False

    def press(self, holder, key, timeout=None):
        if key in ("C", "F"):
            self.calls.append(("press", holder, key))
            self.presses += 1
            self._save(key)
            return
        if key == "D":
            self.calls.append(("press", holder, key))
            self.presses += 1
            return
        super().press(holder, key, timeout)
        if key == "R":
            if self.resting:
                self.effects = {name: [] for name in NAMES}
            self.resting = not self.resting

    def _save(self, letter):
        remote = next(r for r in self.mounted if r and r.endswith("-save.adf"))
        disk = AmigaDisk(self.remote[remote])
        disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(self.place, self.effects))
        self.remote[remote] = disk.to_bytes()


class DisplayIdentity:
    def __contains__(self, state):
        return state in ("sheet", "camp_display")

    def __call__(self, state, path):
        return True


POOL_STATES = ("title", "party_menu", "save_path", "load_picker", "world", "sheet", "camp",
               "camp_save_picker", "quit_prompt", "rest_menu", "camp_magic", "camp_display")


def _rest_run(tmp_path, clock, *, guard_states=POOL_STATES, identity=None, on=None):
    base = dataclasses.replace(route_pool.POOL, read_slot=_read_slot, slot_letters=_letters,
                               slot_files=_files)
    slots = [("A", _slot(START, {name: [BLESS] for name in NAMES})), ("B", b"kept slot")]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "ONE"),
             "disk2": _adf(tmp_path / "disk2.adf", "TWO"),
             "save": _adf(tmp_path / "save.adf", "POOLSAVE", slots)}
    manifest = {"title": "pool", "disks": disks,
                "registered": {"reg": _adf(tmp_path / "reg.adf", "REG")},
                "loaded_letter": "A", "state_a": START, "names_a": NAMES, "camp": list(STEPS)}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    guest = RestingGuest(clock)
    result = acceptance.run_recon(
        path, guest=guest, guard=MapGuard(states=guard_states, on=on),
        identity=identity or DisplayIdentity(), holder="wish273-test",
        audio_proof=_audio_proof(tmp_path), title=base, accept=True)
    return guest, result


def _keys(guest):
    return [c[2] for c in guest.calls if c[0] == "press"]


def test_a_pool_camp_run_lists_the_effects_rests_lists_them_again_and_reads_them_gone(
        tmp_path, clock):
    guest, result = _rest_run(tmp_path, clock)
    assert result["error"] == "" and result["unguarded"] == []
    assert result["success"] is True, result["read"]
    keys = _keys(guest)
    camp = keys.index("E", keys.index("V") + 2)  # the first camp key, after the sheet's exit
    steps = [*DISPLAY_KEYS, *REST_KEYS, *DISPLAY_KEYS]
    # The steps go before the route's first camp save, so the game's own slot C is the
    # first save after the rest, and F follows the walk.
    assert keys[camp + 1:camp + 1 + len(steps)] == steps
    assert keys[camp + 1 + len(steps):] == ["S", "C", "N", "E", "NP2", "NP8", "E", "S", "F", "N"]
    assert [e["state"] for e in result["camp_displays"]] == ["camp_display"] * 2
    assert all(e["identity_checked"] for e in result["camp_displays"])
    assert result["read"]["effects"] == {"C": {name: [] for name in NAMES},
                                         "F": {name: [] for name in NAMES}}
    assert result["extra_saves"] == []


def test_an_effects_list_whose_bar_offers_a_further_page_says_only_page_1_was_read(
        tmp_path, clock):
    # The first list holds every member's Bless and GRIMNIR's Enlarge, so its bar reads
    # NEXT EXIT; after the rest the list fits one page and the bar reads EXIT.
    first = {}

    def two_pages(path):
        first.setdefault("shot", path.stem)
        return path.stem == first["shot"]

    _, result = _rest_run(tmp_path, clock, guard_states=(*POOL_STATES, "camp_display_more"),
                          on={"camp_display_more": two_pages})
    assert [e["more_pages"] for e in result["camp_displays"]] == [True, False]
    shot = result["camp_displays"][0]["shot"]
    paged = [line for line in result["read"]["verdicts"] if "page 1 only" in line]
    assert paged == [f"{shot}: the bar reads NEXT EXIT, so the list has a further page; "
                     "the display check covered page 1 only"]
    # The verdict line is evidence; it does not fail a run whose other checks passed.
    assert result["success"] is True


def test_with_no_rule_for_a_further_page_no_page_is_claimed_either_way(tmp_path, clock):
    _, result = _rest_run(tmp_path, clock)
    assert [e["more_pages"] for e in result["camp_displays"]] == [None, None]
    assert not any("page 1 only" in line for line in result["read"]["verdicts"])


def test_an_expect_whose_route_cannot_be_built_is_its_verdict_s_failure(
        tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "prepare.json"
    manifest.write_text(json.dumps({"title": "pool", "names_a": NAMES}))
    monkeypatch.setattr(acceptance, "PixelGuards", lambda path: None)
    monkeypatch.setattr(acceptance, "WinGuest", lambda: None)
    monkeypatch.setattr(acceptance, "run_recon",
                        lambda *a, **k: {"success": True, "error": "", "unguarded": []})

    def inconsistent(manifest):
        raise RouteError("the manifest turn_about disagrees with its recorded place")

    monkeypatch.setattr(acceptance, "pool_title_for", inconsistent)
    code = acceptance.main([
        "accept", "--title", "pool", "--manifest", str(manifest), "--audio-proof", "a.json",
        "--attempt", "accept1", "--guards", "g.json", "--identity", "i.json",
        "--expect", "BRUTUS:1:0:128"])
    out = capsys.readouterr().out
    assert code == 1
    assert ("expect BRUTUS id 1 at 0 minutes: refutes (the route this manifest names cannot "
            "be built: the manifest turn_about disagrees with its recorded place)") in out


def test_an_effects_list_with_no_identity_rule_fails_the_run(tmp_path, clock):
    class SheetOnly(DisplayIdentity):
        def __contains__(self, state):
            return state == "sheet"

    _, result = _rest_run(tmp_path, clock, identity=SheetOnly())
    assert result["completed"] is True and result["success"] is False
    assert any("has no identity rule" in line for line in result["read"]["verdicts"])


def test_a_rest_menu_with_no_guard_is_measured_and_fails_the_run(tmp_path, clock):
    states = tuple(s for s in POOL_STATES if s != "rest_menu")
    guest, result = _rest_run(tmp_path, clock, guard_states=states)
    assert result["unguarded"] == ["rest_menu"]
    assert result["completed"] is True and result["success"] is False
    assert _keys(guest).count("F") == 1
