"""The Amiga camp steps: viewing a camp sheet, laying on hands and resting, on a published Silver Blades or Curse route."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib

import gamedata
import pytest

from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.test_amigaacceptance import _audio_proof
from tests.amiga.test_amigaacceptance_accept import MapGuard, _IdentityMap
from tests.amiga.test_amigaacceptance_title import (
    NAMES,
    TitleGuest,
    _adf,
    _files,
    _letters,
    _read_slot,
    _slot,
)
from tests.amiga.test_amigaacceptance_titles import START
from tests.support import amigasavegame as synthetic_amiga
from tools.amiga import acceptance as foundation
from tools.amiga import route_camp, route_curse, route_silver_blades, staging
from tools.amiga.winuaesession import RouteError

clock = measure.clock  # the fixture that replaces the driver's time and sleep
STEPS = ("view 1", "heal", "view 1", "rest 60m")
CURSE_NAMES = ["MALE ELF MAGE", "FEMALE MAGE", "CLERIC", "F/T", "RANGER", "PALADIN"]


@pytest.mark.parametrize("text,tokens", [
    ("view;heal;rest 1h", ("view", "heal", "rest 1h")),
    (" rest 1d2h35m ; view 2 ", ("rest 1d2h35m", "view 2")),
])
def test_camp_steps_parse(text, tokens):
    assert route_camp.parse_steps(text) == tokens


@pytest.mark.parametrize("text,why", [
    ("", "empty"),
    ("rest 7m", "in fives"),
    ("rest 0m", "longer than no time"),
    ("rest 30d", "shorter than 30 days"),
    ("rest soon", "not like"),
    ("view 9", "sheets for lines 1 to 2 only"),
    ("view 3", "sheets for lines 1 to 2 only"),
    ("view 0", "sheets for lines 1 to 2 only"),
    ("rest 1d", "need a view or heal"),
    ("rest 1d;rest 1h", "after the last rest"),
    ("view;rest 22h", "need a view or heal"),
    ("heal;heal", "second heal needs a rest"),
    ("heal;view;heal", "second heal needs a rest"),
    ("fly", "not view"),
    ("heal 2", "lay on hands for line 1 only"),
    ("heal x", "not view"),
])
def test_camp_steps_refuse_what_the_route_cannot_drive(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.parse_steps(text)


def test_a_second_heal_is_allowed_after_a_rest():
    route_camp.validate_steps(("heal", "rest 1h", "heal"))
    route_camp.validate_steps(("heal", "rest 1d", "heal"))


@pytest.mark.parametrize("steps", [("rest 1d", "view 1"), ("heal", "rest 1d", "heal"),
                                   ("rest 1d", "rest 1h", "view"), ("rest 21h",)])
def test_a_long_rest_is_allowed_when_a_sheet_follows_and_a_short_one_alone(steps):
    route_camp.validate_steps(steps)


def test_a_view_is_refused_past_the_party_s_last_line():
    with pytest.raises(RouteError, match="sheets for line 1 only"):
        route_camp.validate_steps(("view 2",), party_size=1)
    with pytest.raises(RouteError, match="sheets for line 1 only"):
        route_camp.validate_steps(("view 6",), party_size=5, name="curse")
    with pytest.raises(RouteError, match="no line the camp route can lay on hands for"):
        route_camp.validate_steps(("heal 6",), party_size=5, name="curse")


@pytest.mark.parametrize("text,why", [
    ("view 2", "sheets for lines 1 and 6 only"),
    ("view 7", "sheets for lines 1 and 6 only"),
    ("heal", "lay on hands for line 6 only"),
    ("heal 1", "lay on hands for line 6 only"),
    ("heal 6;heal 6", "second heal needs a rest"),
])
def test_curse_camp_steps_name_only_the_lines_its_guard_map_identifies(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.parse_steps(text, "curse")


def test_curse_camp_steps_reach_the_paladin_on_line_6():
    tokens = route_camp.parse_steps("view 6; rest 1d1h; view 6; heal 6", "curse")
    assert route_camp.normalise(tokens) == ("view 6", "rest 1500m", "view 6", "heal 6")


def test_a_title_without_camp_steps_is_refused():
    with pytest.raises(RouteError, match="Silver Blades and Curse only"):
        route_camp.parse_steps("view", "pool")


def test_heal_1_is_the_normal_form_heal_so_an_older_manifest_rebuilds_the_same_route():
    assert route_camp.normalise(("heal 1", "heal 6")) == ("heal", "heal 6")
    assert route_camp.steps_for(("heal 1",)) == route_camp.steps_for(("heal",))


def test_a_rest_zeroes_the_camp_preset_from_the_days_field_then_sets_each_field():
    assert route_camp.rest_presses(1440 + 2 * 60 + 35) == (1, 2, 7)
    keys = [key for key, _, _ in route_camp.steps_for(("rest 1d2h35m",))]
    assert keys == ["R", "D", "S", "S", "D", "A", "H", "A", "A", "M", *["A"] * 7, "R"]
    states = [state for _, state, _ in route_camp.steps_for(("rest 1h",))]
    assert states == ["rest_menu"] * 6 + ["camp"]


def test_heal_views_the_sheet_offering_heal_picks_the_first_member_and_expects_it_gone():
    assert route_camp.steps_for(("heal",)) == (
        ("V", "camp_sheet_heal", "key"), ("H", "heal_whom", "key"),
        ("S", "camp_sheet_spent", "key"), ("E", "camp", "key"))


def test_heal_n_moves_the_camp_highlight_and_the_picker_to_line_n_and_back():
    # The picker starts on the first member, not on the healer, so it moves as far again.
    assert route_camp.steps_for(("heal 3",)) == (
        ("NP2", "camp", "key"), ("NP2", "camp", "key"),
        ("V", "camp_sheet_heal", "key"), ("H", "heal_whom", "key"),
        ("NP2", "heal_whom", "key"), ("NP2", "heal_whom", "key"),
        ("S", "camp_sheet_spent", "key"), ("E", "camp", "key"),
        ("NP8", "camp", "key"), ("NP8", "camp", "key"))


def test_curse_reaches_the_last_line_one_press_back_through_the_wrap():
    # Curse's highlight and picker take NP1 (`$85`) and NP7 (`$87`), and wrap at either end.
    assert route_camp.steps_for(("view 6",), "curse", 6) == (
        ("NP7", "camp", "key"), ("V", "camp_sheet_6", "key"),
        ("E", "camp", "key"), ("NP1", "camp", "key"))
    assert route_camp.steps_for(("heal 6",), "curse", 6) == (
        ("NP7", "camp", "key"), ("V", "camp_sheet_heal", "key"), ("H", "heal_whom", "key"),
        ("NP7", "heal_whom", "key"), ("S", "camp_sheet_spent", "key"),
        ("E", "camp", "key"), ("NP1", "camp", "key"))
    # A tie, or a line nearer forwards, goes forwards.
    assert route_camp.steps_for(("view 2",), "curse", 2) == (
        ("NP1", "camp", "key"), ("V", "camp_sheet_2", "key"),
        ("E", "camp", "key"), ("NP7", "camp", "key"))
    assert route_camp.steps_for(("view 3",), "curse", 6)[:2] == (("NP1", "camp", "key"),) * 2
    # Silver Blades is not read to wrap, so even a party of two goes forwards, on NP2.
    assert route_camp.steps_for(("view 2",), "ssb", 2) == route_camp.steps_for(("view 2",))


def test_only_a_title_read_to_wrap_is_driven_backwards():
    base = route_silver_blades.published_title("A")
    ssb = route_camp.camp_title(base, ("view 2",), 2, name="ssb")
    assert ("NP8", "camp", "key") == ssb.route[ssb.route.index(("V", "camp_sheet_2", "key")) + 2]
    curse = route_camp.camp_title(route_curse.published_title("D"), ("view 6",), 6,
                                  name="curse")
    at = curse.route.index(("V", "camp_sheet_6", "key"))
    assert curse.route[at - 1] == ("NP7", "camp", "key")
    assert curse.route[at + 2] == ("NP1", "camp", "key")


def test_a_later_line_moves_the_highlight_there_and_back():
    assert route_camp.steps_for(("view 2",)) == (
        ("NP2", "camp", "key"), ("V", "camp_sheet_2", "key"),
        ("E", "camp", "key"), ("NP8", "camp", "key"))


@pytest.mark.parametrize("letter", ["A", "D"])
def test_the_camp_steps_go_between_the_camp_key_and_the_camp_save(letter):
    base = route_silver_blades.published_title(letter)
    title = route_camp.camp_title(base, STEPS, 6, name="ssb")
    at = base.route.index(route_camp.CAMP_SAVE_STEP)
    added = route_camp.steps_for(STEPS)
    assert title.route == (*base.route[:at], *added, *base.route[at:])
    assert title.route[at - 1] == ("E", "camp", "key")
    assert [key for key, _, kind in title.route if kind == "write"] == ["C", "F"]
    # A slot-D source keeps slot A, so the rest menu's Add key is a plain key there only.
    assert title.plain_keys == ((("A", "rest_menu"),) if letter == "D" else ())
    assert title.wait_limits["camp"] == route_camp.REST_LIMIT
    assert title.strict == base.strict


def test_a_route_without_a_camp_save_takes_no_camp_steps():
    base = route_silver_blades.published_title("A")
    at = base.route.index(route_camp.CAMP_SAVE_STEP)
    cut = dataclasses.replace(base, route=base.route[:at])
    with pytest.raises(RouteError, match="no camp save"):
        route_camp.camp_title(cut, STEPS, name="ssb")


CURSE_STEPS = ("view 6", "rest 1500m", "view 6", "heal 6")


def test_the_curse_camp_steps_go_between_the_camp_key_and_the_camp_save():
    base = route_curse.published_title("D")
    title = route_camp.camp_title(base, CURSE_STEPS, 6, name="curse")
    at = base.route.index(route_camp.CAMP_SAVE_STEP)
    assert title.route == (*base.route[:at], *route_camp.steps_for(CURSE_STEPS, "curse", 6),
                           *base.route[at:])
    assert title.route[at - 1] == ("E", "camp", "key")
    assert [key for key, _, kind in title.route if kind == "write"] == ["C", "F"]
    # A slot-D source keeps slot A, so the rest menu's Add key is a plain key there only.
    assert title.plain_keys == (("A", "rest_menu"),)
    assert title.wait_limits["camp"] == route_camp.REST_LIMIT


@pytest.mark.parametrize("state,sheet", [
    ("camp_sheet", True), ("camp_sheet_2", True), ("camp_sheet_heal", True),
    ("camp_sheet_spent", True), ("sheet", False), ("camp", False), ("camp_sheet_x", False),
])
def test_only_camp_sheets_are_observed(state, sheet):
    assert route_camp.is_sheet(state) is sheet


GUARD_FILES = {"ssb": "guards_silver_blades.json", "curse": "guards_curse.json"}


def _maps(name):
    return json.loads((pathlib.Path(route_silver_blades.__file__).parent
                       / GUARD_FILES[name]).read_text())


@pytest.mark.parametrize("name", sorted(route_camp.SHEET_LINES))
def test_every_camp_sheet_rule_is_listed_by_the_party_menu_sheet_and_the_reverse(name):
    maps = _maps(name)
    camp = {route_camp.sheet_state(n) for n in route_camp.SHEET_LINES[name]}
    camp |= {route_camp.SHEET_HEAL, route_camp.SHEET_SPENT}
    # Every camp sheet shows the party menu's sheet frame, so the frame guard lists them all.
    assert camp <= set(maps["guards"]["sheet"]["also"])
    for kind in ("guards", "identity"):
        # A rule on the same box and picture as `sheet` collides with it, and each lists the other.
        # The identity rules name a member, so only a camp sheet of the party menu's first
        # member (Silver Blades' paladin, Curse's line 1) collides there.
        sheet = maps[kind]["sheet"]
        for state in camp & set(maps[kind]):
            value = maps[kind][state]
            for rule in value if isinstance(value, list) else [value]:
                if (rule["box"], rule["sha256"]) == (sheet["box"], sheet["sha256"]):
                    assert "sheet" in rule["also"] and state in sheet["also"], (kind, state)
    assert route_camp.sheet_state(1) in maps["identity"]["sheet"]["also"]


@pytest.mark.parametrize("name", sorted(route_camp.SHEET_LINES))
def test_every_line_a_view_may_name_has_an_identity_rule_and_every_camp_state_a_guard(name):
    maps = _maps(name)
    for line in route_camp.SHEET_LINES[name]:
        assert route_camp.sheet_state(line) in maps["identity"]
        assert route_camp.sheet_state(line) in maps["guards"]
    for state in (route_camp.SHEET_HEAL, route_camp.SHEET_SPENT):
        assert state in maps["identity"] and state in maps["guards"]
    assert {route_camp.HEAL_WHOM, route_camp.REST_MENU, route_camp.CAMP} <= set(maps["guards"])


def test_each_title_heals_from_one_of_the_lines_it_can_view():
    assert set(route_camp.HEAL_LINES) == set(route_camp.SHEET_LINES)
    for name, lines in route_camp.HEAL_LINES.items():
        assert len(lines) == 1 and set(lines) <= set(route_camp.SHEET_LINES[name])


@pytest.mark.parametrize("after,rest,ok", [
    ("05:22", 60, True), ("04:22", 60, False), ("07:30", 60, False),
    ("04:22", 0, True), ("04:22", 1440, True),
])
def test_the_after_clock_allows_for_the_rest(after, rest, ok):
    assert foundation._clock_advanced("04:20", after, rest) is ok


def test_this_issue_pins_the_joined_party():
    assert route_silver_blades.JOIN_SHA256 in foundation._source_pins("628", "ssb", "c64")
    assert foundation.PUBLISHED_ISSUE_TEXT["628"].startswith("#628 (")


#: The game-written sources the published Amiga runs start from, by pin and specimen path.
PINNED_628_SOURCES = (
    ("ssb", "c64", "ssb-c64/WISH-SPEC-ssb-628-guy-healed-after-expiry.D64"),
    ("ssb", "dos", "ssb-dos/WISH-SPEC-ssb-628-c64-to-dos-guy-rest-heal/SAVGAMD.DAT"),
    ("curse", "dos", "coab-dos/WISH-SPEC-curse-628-c2b-slot-d/SAVGAMD.DAT"),
    ("curse", "c64", "coab-c64/WISH-SPEC-curse-628-paladin-spent-lay-on-hands.D64"),
)


@pytest.mark.parametrize("name,port,relative", PINNED_628_SOURCES)
def test_each_pinned_628_source_is_the_specimen_on_disk(name, port, relative):
    root = gamedata.specimen_root()
    if root is None or not (root / relative).is_file():
        pytest.skip(f"needs the specimen {relative}")
    assert staging.sha256(root / relative) in foundation._source_pins("628", name, port)


def test_628_pins_exactly_the_titles_and_ports_the_specimen_list_names_and_each_hash_is_well_formed():
    table = foundation.PUBLISHED_SOURCES_BY_ISSUE["628"]
    assert set(table) == {(n, p) for n, p, _ in PINNED_628_SOURCES}
    assert all(len(h) == 64 and h == h.lower() for pins in table.values() for h in pins)


def test_the_manifest_s_camp_steps_rebuild_the_route_for_either_title_and_no_other():
    base = route_silver_blades.published_title("A")
    title = foundation._camp_title("ssb", base, list(STEPS), NAMES)
    assert title.route == route_camp.camp_title(base, STEPS, name="ssb").route
    curse = route_curse.published_title("D")
    title = foundation._camp_title("curse", curse, list(CURSE_STEPS), CURSE_NAMES)
    assert title.route == route_camp.camp_title(curse, CURSE_STEPS, 6, name="curse").route
    with pytest.raises(RouteError, match="Silver Blades and Curse only"):
        foundation._camp_title("pool", base, list(STEPS), NAMES)
    with pytest.raises(RouteError, match="lines 1 and 6 only"):
        foundation._camp_title("curse", curse, ["view 2"], CURSE_NAMES)
    with pytest.raises(RouteError, match="normal form"):
        foundation._camp_title("ssb", base, ["view", "rest 1h"], NAMES)
    with pytest.raises(RouteError, match="lines 1 to 2"):
        foundation._camp_title("ssb", base, ["view 3"], NAMES)


def test_the_cli_takes_camp_steps_only_for_a_published_prepare(capsys):
    assert foundation.main(["prepare", "--title", "ssb", "--run-id", "x",
                            "--camp", "view"]) == 2
    assert "--camp requires --published-disk-one" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        foundation.main(["prepare", "--title", "ssb", "--run-id", "x",
                         "--published-disk-one", "--camp", "rest 7m"])
    assert "in fives" in capsys.readouterr().err


def test_the_cli_reads_camp_steps_for_the_prepare_s_own_title(capsys):
    # Curse's lines pass the parse and reach the next check; Silver Blades' refuse line 6.
    assert foundation.main(["prepare", "--title", "curse", "--run-id", "x",
                            "--camp", "view 6;heal 6"]) == 2
    assert "--camp requires --published-disk-one" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        foundation.main(["prepare", "--title", "ssb", "--run-id", "x",
                         "--published-disk-one", "--camp", "view 6"])
    assert "lines 1 to 2 only" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        foundation.main(["prepare", "--title", "pool", "--run-id", "x",
                         "--published-disk-one", "--camp", "view"])
    assert "Silver Blades and Curse only" in capsys.readouterr().err


CAMP_STATES = ("camp_sheet", "camp_sheet_heal", "camp_sheet_spent", "heal_whom", "rest_menu")


class CampGuest(TitleGuest):
    """Walks on the keypad until the party camps, saves C and F, and spends HEAL on `S` at the picker.

    In camp `D` is the rest menu's days field and the keypad moves the highlight, so neither
    writes a slot or moves the party there. `spent` starts the paladin with HEAL used; the
    second `R` in camp (the rest menu's own) rests, which brings it back. Slots are written
    with the title's file extension.
    """

    def __init__(self, clock, *, spent=False, ext="sav", names=NAMES):
        super().__init__(clock, save_key="df0")
        self.healed, self.camped, self.ext, self.names = spent, False, ext, names
        self.picking = self.resting = False

    def _write(self, letter, place):
        remote = next(r for r in self.mounted if r and r.endswith(f"-{self.save_key}.adf"))
        disk = AmigaDisk(self.remote[remote])
        disk.write_file(f"/SAVE/savgam{letter}.{self.ext}", _slot(place, self.names))
        self.remote[remote] = disk.to_bytes()

    def press(self, holder, key, timeout=None):
        before = [c[2] for c in self.calls if c[0] == "press"][-1:]
        if self.camped or key == "D":
            measure.ScreenGuest.press(self, holder, key, timeout)
        else:
            super().press(holder, key, timeout=timeout)
        if key == "E" and before == ["NP8"]:
            self.camped = True
        if key == "F":
            self._write("F", self.place)
        if key == "H" and not self.resting:
            self.picking = True
        elif key == "S" and self.picking:
            self.picking, self.healed = False, True
        elif key == "R" and self.camped:
            if self.resting:
                self.healed = False
            self.resting = not self.resting


class CampIdentity(_IdentityMap):
    def __init__(self, missing=()):
        super().__init__()
        self.missing = set(missing)

    def __contains__(self, state):
        return (super().__contains__(state) or route_camp.is_sheet(state)) and (
            state not in self.missing)


def _curse_adf(path, volume, slots=()):
    """`_adf` with Curse's `savgam?.dat` names."""
    disk = AmigaDisk.blank(volume)
    disk.make_dir("/SAVE")
    for letter, raw in slots:
        disk.write_file(f"/SAVE/savgam{letter}.dat", raw)
    disk.save(path)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _curse_read_slot(disk, letter):
    try:
        raw = disk.read_file(f"/SAVE/savgam{letter}.dat")
    except Exception:
        return {"missing": True, "sha256": None}
    data = json.loads(raw)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "place": data["place"],
            "names": data["names"]}


def _curse_files(disk, letter):
    """The slot's file, or nothing, as `route_curse._curse_slot_files` gives a slot not on the disk."""
    name = f"savgam{letter}.dat"
    return {e.name: disk.read_file(f"/SAVE/{e.name}")
            for e in disk.entries(disk.lookup("/SAVE").block) if e.name.lower() == name.lower()}


#: The published title, its slot readers, disk builder, loaded letter, source port and file
#: extension, per title the fake camp runs cover.
FAKE_TITLES = {
    "ssb": (route_silver_blades.published_title("A"), _read_slot, _files, _adf, "A", "c64",
            "sav"),
    "curse": (route_curse.published_title("D"), _curse_read_slot, _curse_files, _curse_adf,
              "D", "dos", "dat"),
}


def _camp_run(tmp_path, clock, monkeypatch, *, guard_states=CAMP_STATES, identity=None,
              clock_f="05:22", steps=STEPS, bar=True, name="ssb", spent=False):
    published, reader, files, adf, letter, port, ext = FAKE_TITLES[name]

    def read_slot(disk, slot):
        return {**reader(disk, slot), "clock": clock_f if slot == "F" else "04:20"}

    base = dataclasses.replace(published, read_slot=read_slot,
                               slot_letters=_letters, slot_files=files)
    names = CURSE_NAMES if name == "curse" else NAMES
    title = route_camp.camp_title(base, steps, len(names), name=name)
    slots = [(letter, _slot(START, names))]
    disks = {"df0": adf(tmp_path / "df0.adf", "ONE", slots),
             "df1": adf(tmp_path / "df1.adf", "TWO")}
    registered = {key: adf(tmp_path / f"{key}.adf", key.upper(), slots)
                  for key in ("source", "report", "published", "disk_one", "disk_two")}
    (tmp_path / "published.adf").write_bytes((tmp_path / "df0.adf").read_bytes())
    registered["published"]["sha256"] = disks["df0"]["sha256"]
    (tmp_path / "disk_two.adf").write_bytes((tmp_path / "df1.adf").read_bytes())
    registered["disk_two"]["sha256"] = disks["df1"]["sha256"]
    manifest = {"mode": "published_disk_one", "issue": "628", "title": name,
                "source_port": port, "loaded_letter": letter, "state_a": START,
                "names_a": names, "clock_a": "04:20", "disks": disks,
                "registered": registered, "expected_after": None, "camp": list(steps)}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    guest = CampGuest(clock, spent=spent, ext=ext, names=names)
    guest.place = dict(START)
    def sheet(p):
        return bar and MapGuard().shown(p).startswith("camp_sheet")

    on = {"camp_sheet_heal": lambda p: not guest.healed and sheet(p),
          "camp_sheet_spent": lambda p: guest.healed and sheet(p)}
    guard = MapGuard(states=(*MapGuard.ALL, *guard_states), on=on)
    monkeypatch.setattr(foundation, "_published_manifest", lambda *_: (manifest, title))
    result = foundation.run_recon(
        path, guest=guest, holder="wish628-test", audio_proof=_audio_proof(tmp_path),
        title=title, guard=guard, identity=identity or CampIdentity(), accept=True,
        published_disk_one=True, published_name=name, journal_python="/usr/bin/python3",
        preflight=lambda _python: None, answer=lambda *_: (0, "answered"))
    return guest, result


def _keys(guest):
    return [c[2] for c in guest.calls if c[0] == "press"]


def test_a_camp_run_heals_rests_and_records_each_sheet_s_heal(tmp_path, clock, monkeypatch):
    guest, result = _camp_run(tmp_path, clock, monkeypatch)
    assert result["error"] == ""
    assert result["success"] is True, {k: result.get(k) for k in (
        "unguarded", "menu_save_problems", "camp_save_problems", "walk", "kept_unchanged",
        "extra_saves", "published_files_preserved", "control_clock_matches",
        "after_clock_advanced", "disks_unchanged", "registered_unchanged",
        "working_unchanged", "fetched_save_error")}
    keys = _keys(guest)
    camp = keys.index("NP8") + 2  # the second step's key, then the camp key
    assert keys[camp] == "E"
    assert keys[camp + 1:keys.index("F") - 1] == [
        key for key, _, _ in route_camp.steps_for(STEPS)]
    assert [(e["state"], e["heal_offered"]) for e in result["camp_sheets"]] == [
        ("camp_sheet", True), ("camp_sheet_heal", True), ("camp_sheet_spent", False),
        ("camp_sheet", False)]
    assert all(e["identity_checked"] for e in result["camp_sheets"])
    verdicts = result["read"]["verdicts"]
    assert any(line.endswith("-camp_sheet_spent: the sheet does not offer HEAL")
               for line in verdicts)
    assert result["after_clock_advanced"] is True


def test_a_curse_camp_run_views_the_spent_paladin_rests_past_it_and_heals(
        tmp_path, clock, monkeypatch):
    guest, result = _camp_run(tmp_path, clock, monkeypatch, name="curse", spent=True,
                              steps=CURSE_STEPS,
                              guard_states=(*CAMP_STATES, "camp_sheet_6"))
    assert result["error"] == ""
    assert result["success"] is True, {k: result.get(k) for k in (
        "unguarded", "menu_save_problems", "camp_save_problems", "walk", "kept_unchanged",
        "extra_saves", "published_files_preserved", "control_clock_matches",
        "after_clock_advanced", "clock_check")}
    keys = _keys(guest)
    camp = keys.index("NP8") + 2  # the second step's key, then the camp key
    assert keys[camp - 3:camp + 1] == ["NP2", "NP8", "NP8", "E"]  # turn about, walk, camp
    assert keys[camp + 1:keys.index("F") - 1] == [
        key for key, _, _ in route_camp.steps_for(CURSE_STEPS, "curse", 6)]
    assert [(e["state"], e["heal_offered"]) for e in result["camp_sheets"]] == [
        ("camp_sheet_6", False), ("camp_sheet_6", True), ("camp_sheet_heal", True),
        ("camp_sheet_spent", False)]
    assert result["clock_check"] == foundation.CLOCK_UNPROVABLE
    assert guest.healed is True


def test_a_camp_run_fails_when_the_clock_did_not_move_by_the_rest(tmp_path, clock, monkeypatch):
    _, result = _camp_run(tmp_path, clock, monkeypatch, clock_f="04:22")
    assert result["after_clock_advanced"] is False
    assert result["success"] is False


@pytest.mark.parametrize("steps,clock_f,check,success", [
    # Before 04:20; a rest of r shows as r plus the 2 minutes the walk takes, modulo a day.
    (("heal", "rest 1315m", "view"), "02:17", "advanced", True),
    (("heal", "rest 1320m", "view"), "02:22", foundation.CLOCK_UNPROVABLE, True),
    (("heal", "rest 1d", "view"), "04:22", foundation.CLOCK_UNPROVABLE, True),
    (("rest 11h", "rest 11h", "view"), "02:22", foundation.CLOCK_UNPROVABLE, True),
    (("heal", "rest 1h", "view"), "05:22", "advanced", True),
    (("heal", "rest 1h", "view"), "04:22", "not advanced", False),
    # The clock still rules out a rest that cannot have happened.
    (("heal", "rest 1d", "view"), "04:20", foundation.CLOCK_UNPROVABLE, False),
    (("heal", "rest 1d", "view"), "garbage", foundation.CLOCK_UNPROVABLE, False),
    (("heal", "rest 1d", "view"), None, foundation.CLOCK_UNPROVABLE, False),
])
def test_a_rest_the_clock_cannot_prove_still_needs_a_clock_it_could_have_made(
        tmp_path, clock, monkeypatch, steps, clock_f, check, success):
    _, result = _camp_run(tmp_path, clock, monkeypatch, clock_f=clock_f, steps=steps)
    assert result["clock_check"] == check
    assert result["success"] is success


def test_an_unprovable_rest_fails_the_run_when_no_sheet_follows_it(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(route_camp, "validate_steps", lambda *_, **__: None)
    _, result = _camp_run(tmp_path, clock, monkeypatch, clock_f="04:22",
                          steps=("view", "rest 1d"))
    assert result["clock_check"] == foundation.CLOCK_UNPROVABLE
    assert result["after_clock_advanced"] is True
    assert result["success"] is False
    assert any("no sheet was recorded after the last rest" in line
               for line in result["read"]["verdicts"])


def test_a_camp_sheet_with_no_identity_rule_fails_the_run(tmp_path, clock, monkeypatch):
    _, result = _camp_run(tmp_path, clock, monkeypatch,
                          identity=CampIdentity(missing=("camp_sheet",)))
    assert [e["identity_checked"] for e in result["camp_sheets"]] == [False, True, True, False]
    assert result["success"] is False
    assert any("no identity rule" in line for line in result["read"]["verdicts"])


def test_a_camp_screen_the_guard_map_lacks_is_settled_and_fails_the_run(
        tmp_path, clock, monkeypatch):
    guest, result = _camp_run(tmp_path, clock, monkeypatch, guard_states=(
        "camp_sheet", "camp_sheet_heal", "camp_sheet_spent", "rest_menu"))
    assert result["unguarded"] == ["heal_whom"]
    assert result["completed"] is True and result["success"] is False
    assert _keys(guest).count("F") == 1


def test_a_camp_sheet_with_neither_bar_is_reported_and_does_not_fail_the_run(
        tmp_path, clock, monkeypatch):
    _, result = _camp_run(tmp_path, clock, monkeypatch, steps=("view 1",), bar=False)
    assert [e["heal_offered"] for e in result["camp_sheets"]] == [None]
    assert result["success"] is True
    assert any(line.endswith("-camp_sheet: the sheet shows neither the HEAL bar nor the "
                             "spent bar the guard map holds")
               for line in result["read"]["verdicts"])


def test_a_heal_whose_sheet_does_not_offer_heal_fails_the_run_there(tmp_path, clock, monkeypatch):
    guest, result = _camp_run(tmp_path, clock, monkeypatch, steps=("heal",), bar=False)
    assert result["unguarded"][:1] == ["camp_sheet_heal"]
    assert result["success"] is False


def _published_report(tmp_path, monkeypatch, name="ssb", port="c64", pinned=None,
                      names=("GUY DE VALOIS",)):
    """A synthetic Save As of a party to disk one's slot, pinned for this issue.

    With `pinned` the issue's own entries stay in force and the synthetic source is reported
    under that hash; without it the source's real hash is pinned in their place."""
    key, exe, make = {
        "ssb": (route_silver_blades.TITLE, "/Secret", synthetic_amiga.synthetic_silver_blades),
        "curse": (route_curse.CURSE_KEY, "/Curse", synthetic_amiga.synthetic_curse)}[name]
    ext = "sav" if name == "ssb" else "dat"
    source = tmp_path / "party.D64"
    source.write_bytes(b"synthetic source")
    one = synthetic_amiga.synthetic_disk_one(key)
    disk1, disk2, published = (tmp_path / n for n in ("disk1.adf", "disk2.adf", "POOLSAVE.ADF"))
    disk1.write_bytes(one.to_bytes())
    disk2.write_bytes(AmigaDisk.blank("Disk2").to_bytes())
    converted = AmigaDisk(one.to_bytes())
    letter = "A" if port == "c64" else "D"
    converted.write_file(f"/SAVE/savgam{letter}.{ext}", make(names))
    published.write_bytes(converted.to_bytes())
    if pinned is None:
        monkeypatch.setitem(foundation.PUBLISHED_SOURCES_BY_ISSUE, "628",
                            {(name, port): frozenset({staging.sha256(source)})})
    else:
        real = foundation.sha256
        # The manifest hashes the source in staging and checks it again here, so both must agree.
        for module in (foundation, staging):
            monkeypatch.setattr(module, "sha256", lambda path, real=real: (
                pinned if pathlib.Path(path) == source else real(path)))
    monkeypatch.setitem(foundation.PUBLISHED_DISKS, name, (
        staging.sha256(disk1), staging.sha256(disk2), exe, "Disk1"))
    monkeypatch.setattr(foundation.scratch, "cache_dir",
                        lambda *parts: tmp_path.joinpath("cache", *map(str, parts)))
    report = {
        "specimen": str(source), "specimen_sha256": pinned or staging.sha256(source),
        "amiga_disk1": str(disk1), "amiga_disk2": str(disk2),
        **({"c64_disks_dir": str(tmp_path)} if port == "c64" else {}),
        "save_as": {"source": str(source), "to": "amiga", "slot": letter,
                    "destination": str(published), "written": [str(published)],
                    "losses": [], "dropped": []},
        "written": [str(published)],
        "written_sha256": {"POOLSAVE.ADF": staging.sha256(published)},
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    return path


def _pinned_628_hashes():
    """Each pinned (title, port, hash) triple of this issue, read from the table itself."""
    return [(name, port, sha) for (name, port), shas
            in sorted(foundation.PUBLISHED_SOURCES_BY_ISSUE["628"].items()) for sha in sorted(shas)]


#: The hashes item 3 of the plan names, spelled out so that dropping an entry fails a case.
EXPECTED_628_PINS = (
    ("ssb", "c64", route_silver_blades.JOIN_SHA256),
    ("ssb", "c64", "8246b96031f6c89e24ca5b096608b779b361e0413be85647d68c27b0ffa61a62"),
    ("ssb", "dos", "73bf301c77280eb39218fc7f6e9176cee15560585e7d20016adfd756a52b9269"),
    ("curse", "dos", "28cacbb27d4aff5bfef4c3e11a94e35d5d0bac2aa6180c394d784f7ec97e8789"),
    ("curse", "c64", "e99bb2be9c1a1a2c5f815f4fac436d7cc0a4ac3c511e7ad0a9ae1e5e7436684a"),
)


@pytest.mark.parametrize("name,port,sha", EXPECTED_628_PINS)
def test_a_published_prepare_for_628_accepts_each_pinned_source_and_refuses_another(
        tmp_path, monkeypatch, name, port, sha):
    report = _published_report(tmp_path, monkeypatch, name, port, pinned=sha)
    assert foundation.prepare_published(name, "pinned", report, "628").is_file()
    data = json.loads(report.read_text())
    data["specimen_sha256"] = "0" * 64
    report.write_text(json.dumps(data))
    with pytest.raises(RouteError, match="differs from the pinned specimen"):
        foundation.prepare_published(name, "unpinned", report, "628")


def test_628_pins_exactly_the_expected_hashes_two_for_ssb_c64_and_one_for_each_other_key():
    assert sorted(_pinned_628_hashes()) == sorted(EXPECTED_628_PINS)


def test_a_published_prepare_keeps_its_camp_steps_and_the_accept_route_has_them(
        tmp_path, monkeypatch):
    report = _published_report(tmp_path, monkeypatch)
    path = foundation.prepare_published("ssb", "camp", report, "628",
                                        camp=("view", "heal", "rest 1h"))
    manifest, title = foundation._published_manifest(path, "ssb")
    assert manifest["camp"] == ["view 1", "heal", "rest 60m"]
    assert ("H", "heal_whom", "key") in title.route
    plain = foundation.prepare_published("ssb", "plain", report, "628")
    manifest, title = foundation._published_manifest(plain, "ssb")
    assert "camp" not in manifest
    assert all(state != "heal_whom" for _, state, _ in title.route)


def test_a_published_curse_prepare_keeps_its_camp_steps_and_the_accept_route_has_them(
        tmp_path, monkeypatch):
    report = _published_report(tmp_path, monkeypatch, "curse", "dos", names=CURSE_NAMES)
    path = foundation.prepare_published("curse", "camp", report, "628",
                                        camp=("view 6", "rest 1d1h", "view 6", "heal 6"))
    manifest, title = foundation._published_manifest(path, "curse")
    assert manifest["camp"] == list(CURSE_STEPS)
    assert title.route == route_camp.camp_title(
        route_curse.published_title("D"), CURSE_STEPS, 6, name="curse").route


def test_a_published_curse_prepare_refuses_a_line_the_party_does_not_have(tmp_path, monkeypatch):
    report = _published_report(tmp_path, monkeypatch, "curse", "dos", names=CURSE_NAMES[:5])
    with pytest.raises(RouteError, match="sheets for line 1 only"):
        foundation.prepare_published("curse", "camp", report, "628", camp=("view 6",))
