"""The Amiga camp steps: viewing a camp sheet, laying on hands, resting and showing Curse's effects list, on a published Silver Blades or Curse route or Pools of Darkness' accept route."""

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
from tests.amiga.test_amigaacceptance_titles import (
    DARK_STATES,
    START,
    DarkGuest,
    _dark_manifest,
    _dark_title,
    _darkness_registered,
)
from tests.support import amigasavegame as synthetic_amiga
from tools.amiga import acceptance as foundation
from tools.amiga import (
    route_camp,
    route_curse,
    route_darkness,
    route_silver_blades,
    staging,
)
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
    ("view 9", "sheets for lines 1 to 6 only"),
    ("view 7", "sheets for lines 1 to 6 only"),
    ("view 0", "sheets for lines 1 to 6 only"),
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
    with pytest.raises(RouteError, match="sheets for lines 1 to 5 only"):
        route_camp.validate_steps(("view 6",), party_size=5, name="curse")
    with pytest.raises(RouteError, match="no line the camp route can lay on hands for"):
        route_camp.validate_steps(("heal 6",), party_size=5, name="curse")


@pytest.mark.parametrize("text,why", [
    ("view 7", "sheets for lines 1 to 6 only"),
    ("view 0", "sheets for lines 1 to 6 only"),
    ("heal", "lay on hands for line 6 only"),
    ("heal 1", "lay on hands for line 6 only"),
    ("heal 6;heal 6", "second heal needs a rest"),
])
def test_curse_camp_steps_name_only_the_lines_its_guard_map_recognises(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.parse_steps(text, "curse")


def test_curse_views_every_line_of_a_party_of_six_the_shorter_way_round():
    tokens = route_camp.parse_steps("view 1;view 2;view 3;view 4;view 5;view 6", "curse")
    route_camp.validate_steps(tokens, 6, name="curse")
    steps = route_camp.steps_for(tokens, "curse", 6)
    sheets = [state for key, state, _ in steps if key == "V"]
    assert sheets == ["camp_sheet", *(f"camp_sheet_{n}" for n in range(2, 7))]
    # Each view starts and ends on line 1: forwards on NP1 up to line 4, backwards on NP7
    # through the wrap for lines 5 and 6.
    moves = {n: [key for key, _, _ in route_camp.steps_for((f"view {n}",), "curse", 6)]
             for n in range(1, 7)}
    assert moves == {
        1: ["V", "E"],
        2: ["NP1", "V", "E", "NP7"],
        3: ["NP1", "NP1", "V", "E", "NP7", "NP7"],
        4: ["NP1", "NP1", "NP1", "V", "E", "NP7", "NP7", "NP7"],
        5: ["NP7", "NP7", "V", "E", "NP1", "NP1"],
        6: ["NP7", "V", "E", "NP1"],
    }


def test_curse_camp_steps_reach_the_paladin_on_line_6():
    tokens = route_camp.parse_steps("view 6; rest 1d1h; view 6; heal 6", "curse")
    assert route_camp.normalise(tokens) == ("view 6", "rest 1500m", "view 6", "heal 6")


def test_a_title_without_camp_steps_is_refused():
    with pytest.raises(RouteError, match="Pools of Darkness and Pool of Radiance only"):
        route_camp.parse_steps("view", "darkness-unstarted")
    with pytest.raises(RouteError, match="reads no sheet on Pool of Radiance"):
        route_camp.parse_steps("view", "pool")


@pytest.mark.parametrize("text,why", [
    ("view 2", "sheets for line 1 only"),
    ("heal 2", "lay on hands for line 1 only"),
    ("heal;heal", "second heal needs a rest"),
])
def test_darkness_camp_steps_name_only_line_1(text, why):
    with pytest.raises(RouteError, match=why):
        route_camp.parse_steps(text, "darkness")


def test_darkness_lays_on_hands_with_l_and_picks_the_first_member_where_the_picker_opens():
    # `Lay` is the sheet bar's word (`038022`), and saint eric on line 1 needs no move.
    assert route_camp.steps_for(("heal",), "darkness", 6) == (
        ("V", "camp_sheet_heal", "key"), ("L", "heal_whom", "key"),
        ("S", "camp_sheet_spent", "key"), ("E", "camp", "key"))
    assert route_camp.steps_for(("view", "rest 1h"), "darkness", 6) == (
        ("V", "camp_sheet", "key"), ("E", "camp", "key"),
        *route_camp.steps_for(("rest 1h",)))


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
    # A slot-D source keeps slot A, so the rest menu's Add key is a simple key there only.
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
    # A slot-D source keeps slot A, so the rest menu's Add key is a simple key there only.
    assert title.plain_keys == (("A", "rest_menu"),)
    assert title.wait_limits["camp"] == route_camp.REST_LIMIT


@pytest.mark.parametrize("state,sheet", [
    ("camp_sheet", True), ("camp_sheet_2", True), ("camp_sheet_heal", True),
    ("camp_sheet_spent", True), ("sheet", False), ("camp", False), ("camp_sheet_x", False),
])
def test_only_camp_sheets_are_observed(state, sheet):
    assert route_camp.is_sheet(state) is sheet


GUARD_FILES = {"ssb": "guards_silver_blades.json", "curse": "guards_curse.json",
               "darkness": "guards_darkness.json"}


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
def test_every_line_a_view_may_name_and_every_camp_state_has_a_guard(name):
    # Whose sheet a line shows is checked by the identity map cut for the run's own party;
    # a sheet that map has no rule for fails the run
    # (`test_a_camp_sheet_with_no_identity_rule_fails_the_run`), so the committed map needs a
    # guard for every line and an identity rule for none in particular.
    maps = _maps(name)
    for line in route_camp.SHEET_LINES[name]:
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
    with pytest.raises(RouteError, match="reads no sheet on Pool of Radiance"):
        foundation._camp_title("pool", base, list(STEPS), NAMES)
    with pytest.raises(RouteError, match="lines 1 to 6 only"):
        foundation._camp_title("curse", curse, ["view 7"], CURSE_NAMES)
    with pytest.raises(RouteError, match="lines 1 to 5 only"):
        foundation._camp_title("curse", curse, ["view 6"], CURSE_NAMES[:5])
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
    # Curse's lines pass the parse and reach the next check; Silver Blades' refuse line 7.
    assert foundation.main(["prepare", "--title", "curse", "--run-id", "x",
                            "--camp", "view 6;heal 6"]) == 2
    assert "--camp requires --published-disk-one" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        foundation.main(["prepare", "--title", "ssb", "--run-id", "x",
                         "--published-disk-one", "--camp", "view 7"])
    assert "lines 1 to 6 only" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        foundation.main(["prepare", "--title", "pool", "--run-id", "x",
                         "--published-disk-one", "--camp", "view"])
    assert "reads no sheet on Pool of Radiance" in capsys.readouterr().err


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
        return (super().__contains__(state) or route_camp.is_sheet(state)
                or route_camp.is_display(state)) and state not in self.missing


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
              clock_f="05:22", steps=STEPS, bar=True, name="ssb", spent=False, on_also=None):
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
          "camp_sheet_spent": lambda p: guest.healed and sheet(p),
          **(on_also or {})}
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


CURSE_VIEWS = tuple(f"view {n}" for n in range(1, 7))
CURSE_SHEETS = ("camp_sheet", *(f"camp_sheet_{n}" for n in range(2, 7)))


def test_a_curse_camp_run_views_every_line_of_a_party_of_six(tmp_path, clock, monkeypatch):
    guest, result = _camp_run(tmp_path, clock, monkeypatch, name="curse", steps=CURSE_VIEWS,
                              guard_states=(*CAMP_STATES, *CURSE_SHEETS))
    assert result["error"] == ""
    assert result["success"] is True
    assert [e["state"] for e in result["camp_sheets"]] == list(CURSE_SHEETS)
    assert all(e["identity_checked"] for e in result["camp_sheets"])
    keys = _keys(guest)
    camp = keys.index("NP8") + 2  # the second step's key, then the camp key
    assert keys[camp + 1:keys.index("F") - 1] == [
        key for key, _, _ in route_camp.steps_for(CURSE_VIEWS, "curse", 6)]


def test_a_curse_line_the_run_s_identity_map_lacks_fails_the_run(tmp_path, clock, monkeypatch):
    _, result = _camp_run(tmp_path, clock, monkeypatch, name="curse", steps=CURSE_VIEWS,
                          guard_states=(*CAMP_STATES, *CURSE_SHEETS),
                          identity=CampIdentity(missing=("camp_sheet_4",)))
    assert [e["identity_checked"] for e in result["camp_sheets"]] == [
        True, True, True, False, True, True]
    assert result["success"] is False
    unchecked = [line for line in result["read"]["verdicts"] if "no identity rule" in line]
    assert len(unchecked) == 1 and unchecked[0].split(":")[0].endswith("-camp_sheet_4")


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
    ordinary = foundation.prepare_published("ssb", "ordinary", report, "628")
    manifest, title = foundation._published_manifest(ordinary, "ssb")
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
    with pytest.raises(RouteError, match="sheets for lines 1 to 5 only"):
        foundation.prepare_published("curse", "camp", report, "628", camp=("view 6",))


DARK_CAMP = ("view 1", "heal", "rest 60m", "view 1")


def test_darkness_camp_steps_go_between_its_camp_key_and_its_camp_save():
    base = route_darkness.DARKNESS
    title = route_camp.camp_title(base, DARK_CAMP, 6, name="darkness")
    at = base.route.index(route_camp.CAMP_SAVE_STEP)
    assert title.route == (*base.route[:at], *route_camp.steps_for(DARK_CAMP, "darkness", 6),
                           *base.route[at:])
    assert title.route[at - 1] == ("E", "camp", "key")
    assert [key for key, _, kind in title.route if kind == "write"] == ["F", "G"]
    # A, D and E are kept slots on disk 3, so the rest menu's Add and Days keys are simple there.
    assert title.plain_keys == (*base.plain_keys, ("D", "rest_menu"), ("A", "rest_menu"))
    assert title.wait_limits["camp"] == route_camp.REST_LIMIT
    assert title.strict == base.strict


class DarkCampGuest(DarkGuest):
    """Spends HEAL on `S` at the picker `L` opens, and gets it back on the rest menu's own `R`."""

    def __init__(self, clock, **kw):
        super().__init__(clock, save_key="disk3", **kw)
        self.healed = self.picking = self.resting = self.camped = False

    def press(self, holder, key, timeout=None):
        before = [c[2] for c in self.calls if c[0] == "press"][-1:]
        super().press(holder, key, timeout)
        if key == "E" and before == ["NP8"]:
            self.camped = True
        if key == "L" and self.camped:  # the party menu's `L` loads
            self.picking = True
        elif key == "S" and self.picking:
            self.picking, self.healed = False, True
        elif key == "R" and self.camped:
            if self.resting:
                self.healed = False
            self.resting = not self.resting


def _dark_camp_run(tmp_path, clock, *, manifest_title="darkness", accept=True,
                   camp=DARK_CAMP, guard_states=CAMP_STATES):
    path = _dark_manifest(tmp_path)
    manifest = json.loads(path.read_text())
    manifest.update(title=manifest_title, camp=list(camp))
    path.write_text(json.dumps(manifest))
    guest = DarkCampGuest(clock)
    guest.place = {"area": 2, "x": 1, "y": 2, "facing": 1}

    def sheet(p):
        return MapGuard().shown(p).startswith("camp_sheet")

    on = {"camp_sheet_heal": lambda p: not guest.healed and sheet(p),
          "camp_sheet_spent": lambda p: guest.healed and sheet(p)}
    guard = MapGuard(states=(*DARK_STATES, *guard_states), on=on)
    kw = {"accept": True, "identity": CampIdentity()} if accept else {"measure": True}
    result = foundation.run_recon(
        path, guest=guest, guard=guard, holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=_dark_title(), **kw)
    return guest, result


def test_a_darkness_camp_run_views_lays_on_hands_rests_and_views_before_the_camp_save(
        tmp_path, clock):
    guest, result = _dark_camp_run(tmp_path, clock)
    assert result["error"] == "" and result["unguarded"] == []
    assert result["success"] is True, result["read"]
    keys = _keys(guest)
    camp = keys.index("NP8") + 1
    assert keys[camp] == "E"
    assert keys[camp + 1:keys.index("G") - 1] == [
        key for key, _, _ in route_camp.steps_for(DARK_CAMP, "darkness", 6)]
    assert [(e["state"], e["heal_offered"]) for e in result["camp_sheets"]] == [
        ("camp_sheet", True), ("camp_sheet_heal", True), ("camp_sheet_spent", False),
        ("camp_sheet", True)]
    assert all(e["identity_checked"] for e in result["camp_sheets"])


def test_a_darkness_camp_screen_the_guard_map_lacks_is_settled_and_fails_the_run(tmp_path, clock):
    guest, result = _dark_camp_run(tmp_path, clock, guard_states=(
        "camp_sheet", "camp_sheet_heal", "rest_menu"))
    assert result["unguarded"] == ["heal_whom", "camp_sheet_spent"]
    assert result["completed"] is True and result["success"] is False
    assert _keys(guest).count("G") == 1


@pytest.mark.parametrize("manifest_title,accept,why", [
    ("curse", True, "Pool of Radiance accept, only"),
    (None, True, "Pool of Radiance accept, only"),
    ("darkness", False, "Pool of Radiance accept, only"),
])
def test_camp_steps_in_a_manifest_that_is_not_a_darkness_accept_are_refused(
        tmp_path, clock, manifest_title, accept, why):
    with pytest.raises(RouteError, match=why):
        _dark_camp_run(tmp_path, clock, manifest_title=manifest_title, accept=accept)


def test_only_darkness_prepares_camp_steps_outside_a_published_prepare(
        tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    with pytest.raises(RouteError, match="only on a published prepare"):
        foundation.prepare(foundation.CURSE, "camp-run", camp=("view",))
    with pytest.raises(RouteError, match="sheets for line 1 only"):
        foundation.prepare(foundation.DARKNESS, "camp-run", camp=("view 2",))
    with pytest.raises(RouteError, match="is a number"):
        foundation.prepare(foundation.DARKNESS, "camp-run", issue="../628")
    assert not (tmp_path / ".cache").exists()


def test_a_darkness_prepare_keeps_its_camp_steps_under_the_issue_it_names(tmp_path, monkeypatch):
    _darkness_registered()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    path = foundation.prepare(foundation.DARKNESS, "camp-run", issue="628",
                              camp=("view", "heal", "rest 1h", "view"))
    assert path.parent.parent.name == "628"
    manifest = json.loads(path.read_text())
    assert manifest["camp"] == list(DARK_CAMP)
    assert manifest["names_a"][0] == "saint eric"


def test_the_cli_takes_camp_steps_and_an_issue_for_a_darkness_prepare(capsys, monkeypatch):
    seen = {}

    def fake(title, run_id, **kw):
        seen.update(kw, title=title, run_id=run_id)
        return pathlib.Path("prepare.json")

    monkeypatch.setattr(foundation, "prepare", fake)
    assert foundation.main(["prepare", "--title", "darkness", "--run-id", "x", "--issue",
                            "628", "--camp", "view;heal;rest 1h;view"]) == 0
    assert seen["title"] is foundation.DARKNESS
    assert seen["camp"] == DARK_CAMP and seen["issue"] == "628"
    assert foundation.main(["prepare", "--title", "curse", "--run-id", "x",
                            "--camp", "view"]) == 2
    assert ("--camp requires --published-disk-one, --title darkness or --title pool"
            in capsys.readouterr().err)
    seen.clear()
    assert foundation.main(["prepare", "--title", "curse", "--run-id", "x",
                            "--issue", "628"]) == 0
    assert seen["title"] is foundation.CURSE and seen["issue"] == "628"


def test_a_darkness_prepare_the_party_refuses_leaves_no_run_folder_so_a_retry_can_run(
        tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def copied(run, _specimen, names=(), **_substitute):
        # Stands in for `_prepare_darkness`: the folder and its disks exist before the party is read.
        foundation.scratch.ensure(run)
        (run / "disk3.adf").write_bytes(b"copied")
        return {"names_a": list(names)}

    monkeypatch.setitem(foundation._PREPARE, "darkness", copied)
    run = foundation.scratch.cache_dir("acceptance", "628", "camp-run")
    with pytest.raises(RouteError, match="no line the camp route can read sheets for"):
        foundation.prepare(foundation.DARKNESS, "camp-run", issue="628", camp=("view",))
    assert not run.exists()
    monkeypatch.setitem(foundation._PREPARE, "darkness",
                        lambda r, s, **_substitute: copied(r, s, names=("saint eric",)))
    path = foundation.prepare(foundation.DARKNESS, "camp-run", issue="628", camp=("view",))
    assert json.loads(path.read_text())["camp"] == ["view 1"]


# The effects list: camp `M`, magic menu `D`, list viewer `E`, magic menu `E` (`/Curse`).

DISPLAY_STEPS = (("M", "camp_magic", "key"), ("D", "camp_display", "key"),
                 ("E", "camp_magic", "key"), ("E", "camp", "key"))


def test_display_opens_the_curse_magic_menu_s_effects_list_and_comes_back_to_the_camp_bar():
    assert route_camp.parse_steps("display; view 6", "curse") == ("display", "view 6")
    assert route_camp.steps_for(("display",), "curse", 2) == DISPLAY_STEPS
    assert route_camp.normalise(("display",)) == ("display",)
    assert route_camp.is_display("camp_display") and not route_camp.is_display("camp_magic")
    assert not route_camp.is_sheet("camp_display")


@pytest.mark.parametrize("name", ["ssb", "darkness"])
def test_display_is_refused_for_a_title_whose_magic_menu_is_unread(name):
    with pytest.raises(RouteError, match="effects list is built for Curse and Pool of Radiance only"):
        route_camp.parse_steps("display", name)


@pytest.mark.parametrize("text", ["display 2", "display all"])
def test_display_takes_no_line(text):
    with pytest.raises(RouteError, match="or display"):
        route_camp.parse_steps(text, "curse")


def test_a_curse_camp_display_goes_before_the_camp_save_for_a_slot_a_source():
    base = route_curse.published_title("A")
    title = route_camp.camp_title(base, ("display",), 2, name="curse")
    at = base.route.index(route_camp.CAMP_SAVE_STEP)
    assert title.route == (*base.route[:at], *DISPLAY_STEPS, *base.route[at:])
    assert title.plain_keys == ()
    assert "camp" not in title.wait_limits
    assert {"camp_magic", "camp_display"} <= set(title.min_waits)


DISPLAY_STATES = (*CAMP_STATES, "camp_sheet_6", "camp_magic", "camp_display")


def test_a_curse_camp_run_shows_the_effects_list_and_records_its_identity(
        tmp_path, clock, monkeypatch):
    guest, result = _camp_run(tmp_path, clock, monkeypatch, name="curse",
                              steps=("display",), guard_states=DISPLAY_STATES)
    assert result["error"] == ""
    assert result["success"] is True, {k: result.get(k) for k in (
        "unguarded", "camp_displays", "menu_save_problems", "camp_save_problems", "walk")}
    keys = _keys(guest)
    camp = keys.index("NP8") + 2
    assert keys[camp + 1:keys.index("F") - 1] == ["M", "D", "E", "E"]
    assert [(e["state"], e["identity_checked"]) for e in result["camp_displays"]] == [
        ("camp_display", True)]
    assert any(line.endswith("-camp_display: the effects list matches the identity rule "
                             "cut for this party") for line in result["read"]["verdicts"])


def test_an_effects_list_with_no_identity_rule_fails_the_run(tmp_path, clock, monkeypatch):
    _, result = _camp_run(tmp_path, clock, monkeypatch, name="curse", steps=("display",),
                          guard_states=DISPLAY_STATES,
                          identity=CampIdentity(missing=("camp_display",)))
    assert [e["identity_checked"] for e in result["camp_displays"]] == [False]
    assert result["completed"] is True and result["success"] is False
    assert any("has no identity rule, so nothing checked what it lists" in line
               for line in result["read"]["verdicts"])


def test_an_effects_list_the_guard_map_lacks_is_settled_and_fails_the_run(
        tmp_path, clock, monkeypatch):
    guest, result = _camp_run(tmp_path, clock, monkeypatch, name="curse", steps=("display",),
                              guard_states=(*CAMP_STATES, "camp_magic"))
    assert result["unguarded"] == ["camp_display"]
    assert "camp_displays" not in result
    assert result["completed"] is True and result["success"] is False
    assert _keys(guest).count("F") == 1


def test_curse_s_guard_map_holds_the_magic_menu_and_the_effects_list():
    guards = _maps("curse")["guards"]
    assert {"camp_magic", "camp_display"} <= set(guards)
    # Both are bar rules, so they say nothing about whose list it is: that is a per-run identity.
    assert "camp_display" not in _maps("curse")["identity"]


#: The game-written C64 Curse flight save, reloaded and resaved, that the #666 Amiga run starts from.
FLIGHT_666 = ("coab-c64/WISH-SPEC-curse-666-e1-bless-flee-orphan-reload-resave.D64",
              "9facc90c1f7cefdb909368b6db5b8135960631244ac259d21fab65d681352041")


def test_666_pins_only_the_curse_flight_save_and_names_its_issue():
    assert foundation.PUBLISHED_SOURCES_BY_ISSUE["666"] == {
        ("curse", "c64"): frozenset({FLIGHT_666[1]})}
    assert foundation.PUBLISHED_ISSUE_TEXT["666"].startswith("#666 (A C64 party under a camp")


def test_the_pinned_666_source_is_the_specimen_on_disk():
    root = gamedata.specimen_root()
    if root is None or not (root / FLIGHT_666[0]).is_file():
        pytest.skip(f"needs the specimen {FLIGHT_666[0]}")
    assert staging.sha256(root / FLIGHT_666[0]) == FLIGHT_666[1]


def test_a_published_prepare_for_666_keeps_its_display_and_refuses_another_source(
        tmp_path, monkeypatch):
    report = _published_report(tmp_path, monkeypatch, "curse", "c64", pinned=FLIGHT_666[1],
                               names=("TRAVIS", "LEDERA"))
    path = foundation.prepare_published("curse", "flight", report, "666", camp=("display",))
    manifest, title = foundation._published_manifest(path, "curse")
    assert manifest["issue"] == "666" and manifest["camp"] == ["display"]
    assert manifest["names_a"] == ["TRAVIS", "LEDERA"]
    assert title.route == route_camp.camp_title(
        route_curse.published_title("A", issue="666", turn_about=manifest["turn_about"]),
        ("display",), 2, name="curse").route
    data = json.loads(report.read_text())
    data["specimen_sha256"] = "0" * 64
    report.write_text(json.dumps(data))
    with pytest.raises(RouteError, match="differs from the pinned specimen"):
        foundation.prepare_published("curse", "other", report, "666")


#: The game-written C64 Curse strength-ladder save, reloaded and resaved, that the #667 Amiga run starts from.
LADDER_667 = ("coab-c64/WISH-SPEC-curse-667-strength-ladder-c64-resave.D64",
              "ff3228edf42aa56a0fbf5159e8354358a38673115216a1b6c7f3439cae2686f2")
#: The game-written DOS Silver Blades save of Slow Poison cast on a poisoned companion, resaved while it runs.
SLOW_POISON_667 = ("ssb-dos/WISH-SPEC-ssb-667-slow-poison-companion-running-resave/SAVGAMD.DAT",
                   "91a136ce86b34267b81d1ddd1d5037ce54d1a7d5b7e63732dddcb0af3070921b")


def test_667_pins_the_curse_ladder_and_the_silver_blades_slow_poison_saves_and_names_its_issue():
    assert foundation.PUBLISHED_SOURCES_BY_ISSUE["667"] == {
        ("curse", "c64"): frozenset({LADDER_667[1]}),
        ("ssb", "dos"): frozenset({SLOW_POISON_667[1]})}
    assert foundation.PUBLISHED_ISSUE_TEXT["667"].startswith("#667 (A DOS party under Prayer")


def test_the_pinned_667_source_is_the_specimen_on_disk():
    root = gamedata.specimen_root()
    if root is None or not (root / LADDER_667[0]).is_file():
        pytest.skip(f"needs the specimen {LADDER_667[0]}")
    assert staging.sha256(root / LADDER_667[0]) == LADDER_667[1]


def test_a_published_prepare_for_667_refuses_another_source(tmp_path, monkeypatch):
    report = _published_report(tmp_path, monkeypatch, "curse", "c64", pinned=LADDER_667[1])
    assert foundation.prepare_published("curse", "ladder", report, "667").is_file()
    data = json.loads(report.read_text())
    data["specimen_sha256"] = "0" * 64
    report.write_text(json.dumps(data))
    with pytest.raises(RouteError, match="differs from the pinned specimen"):
        foundation.prepare_published("curse", "other", report, "667")


def test_the_pinned_667_slow_poison_source_is_the_specimen_on_disk():
    root = gamedata.specimen_root()
    if root is None or not (root / SLOW_POISON_667[0]).is_file():
        pytest.skip(f"needs the specimen {SLOW_POISON_667[0]}")
    assert staging.sha256(root / SLOW_POISON_667[0]) == SLOW_POISON_667[1]


def test_a_published_prepare_for_667_takes_the_silver_blades_dos_save_and_refuses_another(
        tmp_path, monkeypatch):
    report = _published_report(tmp_path, monkeypatch, "ssb", "dos", pinned=SLOW_POISON_667[1],
                               names=("GUY DE VALOIS", "PAINE", "EPONA", "MALACHITE", "DOMINIC",
                                      "MORGAINE"))
    steps = ("view 2", "rest 30m", "view 2")
    path = foundation.prepare_published("ssb", "slow-poison", report, "667", camp=steps)
    manifest, _title = foundation._published_manifest(path, "ssb")
    assert manifest["issue"] == "667" and manifest["camp"] == list(steps)
    data = json.loads(report.read_text())
    data["specimen_sha256"] = "0" * 64
    report.write_text(json.dumps(data))
    with pytest.raises(RouteError, match="differs from the pinned specimen"):
        foundation.prepare_published("ssb", "other", report, "667", camp=steps)


#: The game-written C64 saves with a feebleminded member that the #661 Amiga runs start from.
FEEBLEMIND_661 = {
    "ssb": ("ssb-c64/WISH-SPEC-ssb-661-fml-l3-c64-feeblemind-hold-resave.D64",
            "1e5a51d1d630b518306ae9772b85de61715384ac674077fafb79f54c613e1e16"),
    "curse": ("coab-c64/WISH-SPEC-curse-661-feeblemind-cast-resave.D64",
              "9f7217a53ffe162bad585bfdf93a938929165ed2e5d2552287127c79696471a9")}


def test_661_pins_the_two_feeblemind_saves_and_names_its_issue():
    assert foundation.PUBLISHED_SOURCES_BY_ISSUE["661"] == {
        ("ssb", "c64"): frozenset({FEEBLEMIND_661["ssb"][1]}),
        ("curse", "c64"): frozenset({FEEBLEMIND_661["curse"][1]})}
    assert foundation.PUBLISHED_ISSUE_TEXT["661"].startswith("WISH-7 (A C64 party under a running spell")


@pytest.mark.parametrize("name", sorted(FEEBLEMIND_661))
def test_the_pinned_661_sources_are_the_specimens_on_disk(name):
    relative, digest = FEEBLEMIND_661[name]
    root = gamedata.specimen_root()
    if root is None or not (root / relative).is_file():
        pytest.skip(f"needs the specimen {relative}")
    assert staging.sha256(root / relative) == digest


@pytest.mark.parametrize("name,names", [
    ("ssb", ("GUY DE VALOIS", "PAINE", "EPONA", "MALACHITE", "DOMINIC", "MORGAINE")),
    ("curse", ("MATHEW", "TRAVIS"))])
def test_a_published_prepare_for_661_takes_the_pinned_source_and_refuses_another(
        tmp_path, monkeypatch, name, names):
    report = _published_report(tmp_path, monkeypatch, name, "c64",
                               pinned=FEEBLEMIND_661[name][1], names=names)
    steps = ("view 6",) if name == "ssb" else ("view 1",)
    path = foundation.prepare_published(name, "feeblemind", report, "661", camp=steps)
    manifest, _title = foundation._published_manifest(path, name)
    assert manifest["issue"] == "661" and manifest["camp"] == list(steps)
    data = json.loads(report.read_text())
    data["specimen_sha256"] = "0" * 64
    report.write_text(json.dumps(data))
    with pytest.raises(RouteError, match="differs from the pinned specimen"):
        foundation.prepare_published(name, "other", report, "661", camp=steps)


#: The DOS saves the WISH-22 Amiga-destination runs start from, under the specimen root.
DOS_22 = {
    "curse": ("por-dos/WISH-SPEC-curse-234-party-dualclassed/SAVGAMD.DAT",
              "4e911c12a449a4ff1694aab6d918f120c176df66483e32428cb50454db8b03df"),
    "ssb": ("ssb-dos/WISH-SPEC-ssb-joined-arrow-dos-672/SAVGAMD.DAT",
            "b3515793dada24b6a85061f5c2fdc5555a45df40381ee0009e9fd54ba381fb72")}


def test_22_pins_the_two_dos_saves_and_names_its_issue():
    assert foundation.PUBLISHED_SOURCES_BY_ISSUE["22"] == {
        ("curse", "dos"): frozenset({DOS_22["curse"][1]}),
        ("ssb", "dos"): frozenset({DOS_22["ssb"][1]})}
    assert foundation.PUBLISHED_ISSUE_TEXT["22"] == (
        "WISH-22 (Validate Character Editor Open, Save and Save As across C64, DOS and Amiga)")


@pytest.mark.parametrize("name", sorted(DOS_22))
def test_the_pinned_22_sources_are_the_specimens_on_disk(name):
    relative, digest = DOS_22[name]
    root = gamedata.specimen_root()
    if root is None or not (root / relative).is_file():
        pytest.skip(f"needs the specimen {relative}")
    assert staging.sha256(root / relative) == digest


@pytest.mark.parametrize("name,names", [
    ("ssb", ("GUY DE VALOIS", "PAINE")), ("curse", ("MATHEW", "TRAVIS"))])
def test_a_published_prepare_for_22_files_under_its_issue_and_refuses_another_source(
        tmp_path, monkeypatch, name, names):
    report = _published_report(tmp_path, monkeypatch, name, "dos",
                               pinned=DOS_22[name][1], names=names)
    path = foundation.prepare_published(name, "dos", report, "22")
    manifest, _title = foundation._published_manifest(path, name)
    assert manifest["issue"] == "22" and path.parent.parent.name == "22"
    data = json.loads(report.read_text())
    data["specimen_sha256"] = "0" * 64
    report.write_text(json.dumps(data))
    with pytest.raises(RouteError, match="differs from the pinned specimen"):
        foundation.prepare_published(name, "other", report, "22")


def test_silver_blades_camp_steps_reach_every_line_of_a_party_of_six():
    assert route_camp.SHEET_LINES["ssb"] == (1, 2, 3, 4, 5, 6)
    tokens = route_camp.parse_steps("view 1;view 2;view 3;view 4;view 5;view 6", "ssb")
    assert route_camp.normalise(tokens) == tuple(f"view {n}" for n in range(1, 7))
    assert route_camp.steps_for(("view 6",), "ssb", 6) == (
        ("NP2", "camp", "key"),) * 5 + (
        ("V", "camp_sheet_6", "key"), ("E", "camp", "key")) + (("NP8", "camp", "key"),) * 5
    with pytest.raises(RouteError, match="sheets for lines 1 to 6 only"):
        route_camp.parse_steps("view 7", "ssb")


def test_curse_s_party_menu_guard_matches_a_full_party_and_one_with_room_to_add():
    # ADD CHARACTER is lit only while the party has room, so a party of two needs its own picture
    # of the same button box beside the six-member one.
    rules = _maps("curse")["guards"]["loaded_menu"]
    assert isinstance(rules, list) and len(rules) == 2
    assert {tuple(r["box"]) for r in rules} == {(60, 250, 700, 430)}
    assert len({r["sha256"] for r in rules}) == 2
