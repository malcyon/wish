"""The Amiga camp steps: viewing a camp sheet, laying on hands and resting, on a published Silver Blades route."""

from __future__ import annotations

import dataclasses
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
    ("heal 2", "not view"),
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
    with pytest.raises(RouteError, match="sheets for lines 1 to 1 only"):
        route_camp.validate_steps(("view 2",), party_size=1)


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


def test_a_later_line_moves_the_highlight_there_and_back():
    assert route_camp.steps_for(("view 2",)) == (
        ("NP2", "camp", "key"), ("V", "camp_sheet_2", "key"),
        ("E", "camp", "key"), ("NP8", "camp", "key"))


@pytest.mark.parametrize("letter", ["A", "D"])
def test_the_camp_steps_go_between_the_camp_key_and_the_camp_save(letter):
    base = route_silver_blades.published_title(letter)
    title = route_camp.camp_title(base, STEPS, 6)
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
        route_camp.camp_title(cut, STEPS)


@pytest.mark.parametrize("state,sheet", [
    ("camp_sheet", True), ("camp_sheet_2", True), ("camp_sheet_heal", True),
    ("camp_sheet_spent", True), ("sheet", False), ("camp", False), ("camp_sheet_x", False),
])
def test_only_camp_sheets_are_observed(state, sheet):
    assert route_camp.is_sheet(state) is sheet


def test_every_camp_sheet_rule_is_listed_by_the_party_menu_sheet_and_the_reverse():
    maps = json.loads((pathlib.Path(route_silver_blades.__file__).parent
                       / "guards_silver_blades.json").read_text())
    camp = {route_camp.sheet_state(n) for n in range(1, route_camp.SHEET_LINES + 1)}
    camp |= {route_camp.SHEET_HEAL, route_camp.SHEET_SPENT}
    for kind in ("guards", "identity"):
        assert camp <= set(maps[kind]["sheet"]["also"]), kind
        # Rules on the same box and picture as `sheet` (camp sheet 2 shows another name) collide.
        for state in camp & set(maps[kind]):
            rule, sheet = maps[kind][state], maps[kind]["sheet"]
            if (rule["box"], rule["sha256"]) == (sheet["box"], sheet["sha256"]):
                assert "sheet" in rule["also"], (kind, state)


def test_every_line_a_view_may_name_has_an_identity_rule():
    maps = json.loads((pathlib.Path(route_silver_blades.__file__).parent
                       / "guards_silver_blades.json").read_text())
    for line in range(1, route_camp.SHEET_LINES + 1):
        assert route_camp.sheet_state(line) in maps["identity"]


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


def test_the_manifest_s_camp_steps_rebuild_the_route_and_curse_refuses_them():
    base = route_silver_blades.published_title("A")
    title = foundation._camp_title("ssb", base, list(STEPS), NAMES)
    assert title.route == route_camp.camp_title(base, STEPS).route
    with pytest.raises(RouteError, match="Silver Blades only"):
        foundation._camp_title("curse", base, list(STEPS), NAMES)
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


CAMP_STATES = ("camp_sheet", "camp_sheet_heal", "camp_sheet_spent", "heal_whom", "rest_menu")


class CampGuest(TitleGuest):
    """Walks on the keypad until the party camps, saves C and F, and spends HEAL on `S` at the picker.

    In camp `D` is the rest menu's days field and the keypad moves the highlight, so neither
    writes a slot or moves the party there.
    """

    def __init__(self, clock):
        super().__init__(clock, save_key="df0")
        self.healed = self.camped = False

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
        if key == "S" and before == ["H"]:
            self.healed = True


class CampIdentity(_IdentityMap):
    def __init__(self, missing=()):
        super().__init__()
        self.missing = set(missing)

    def __contains__(self, state):
        return (super().__contains__(state) or route_camp.is_sheet(state)) and (
            state not in self.missing)


def _camp_run(tmp_path, clock, monkeypatch, *, guard_states=CAMP_STATES, identity=None,
              clock_f="05:22", steps=STEPS, bar=True):
    def read_slot(disk, letter):
        return {**_read_slot(disk, letter), "clock": clock_f if letter == "F" else "04:20"}

    base = dataclasses.replace(route_silver_blades.published_title("A"), read_slot=read_slot,
                               slot_letters=_letters, slot_files=_files)
    title = route_camp.camp_title(base, steps, len(NAMES))
    slots = [("A", _slot(START))]
    disks = {"df0": _adf(tmp_path / "df0.adf", "ONE", slots),
             "df1": _adf(tmp_path / "df1.adf", "TWO")}
    registered = {name: _adf(tmp_path / f"{name}.adf", name.upper(), slots)
                  for name in ("source", "report", "published", "disk_one", "disk_two")}
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
    guest = CampGuest(clock)
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
        published_disk_one=True, published_name="ssb", journal_python="/usr/bin/python3",
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


def _published_report(tmp_path, monkeypatch, name="ssb", port="c64", pinned=None):
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
    converted.write_file(f"/SAVE/savgam{letter}.{ext}", make(("GUY DE VALOIS",)))
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


def test_a_published_curse_prepare_refuses_camp_steps(tmp_path, monkeypatch):
    report = _published_report(tmp_path, monkeypatch, "curse")
    with pytest.raises(RouteError, match="Silver Blades only"):
        foundation.prepare_published("curse", "camp", report, "628", camp=("view",))
