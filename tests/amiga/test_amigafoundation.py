"""The foundation module's Pool of Radiance description, driven with a fake guest and patched readings."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib

import pytest

from goldbox import geo
from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigasecretsavemeasure as measure
from tests.amiga.test_amigasecretsave import _audio_proof
from tests.amiga.test_amigasecretsaveaccept import MapGuard, _IdentityMap
from tests.amiga.test_amigasecretsavetitle import (
    NAMES,
    TitleGuest,
    _adf,
    _files,
    _letters,
    _read_slot,
    _slot,
)
from tools.amiga import amigafoundation as foundation
from tools.amiga import amigasecretsave as drive

clock = measure.clock  # the fixture that replaces the driver's time and sleep
START = {"area": 0, "x": 9, "y": 13, "facing": geo.NORTH}
LATER = dict(START, y=14, facing=geo.SOUTH)
STATES = ("title", "wheel", "party_menu", "save_path", "load_picker", "sheet", "world", "camp",
          "camp_save_picker", "quit_prompt")
# The first screen is the code wheel until RETURN leaves it; the first crop is "frame 0".
FIRST_SCREEN = {"wheel": lambda path: path.read_bytes() == b"frame 0",
                "title": lambda path: path.read_bytes() != b"frame 0"}
POOL_KEYS = ["RET", "RET", "L", "RET", "A", "V", "E", "E", "S", "C", "N",
             "E", "NP2", "NP8", "E", "S", "D", "N"]


def _title():
    """The real Pool description with its slot readers replaced by the synthetic ones."""
    return dataclasses.replace(foundation.POOL, read_slot=_read_slot, slot_letters=_letters,
                               slot_files=_files)


def _manifest(tmp_path):
    slots = [("A", _slot(START)), ("B", _slot(LATER))]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "ONE"),
             "disk2": _adf(tmp_path / "disk2.adf", "TWO"),
             "save": _adf(tmp_path / "save.adf", "POOLSAVE", slots)}
    data = {"disks": disks, "registered": {"specimen": _adf(tmp_path / "specimen.adf", "REG")},
            "loaded_letter": "A", "state_a": START, "names_a": NAMES, "expected_after": LATER}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


def _run(tmp_path, clock, *, guest=None, **kw):
    guest = guest or TitleGuest(clock, save_key="save")
    guest.place = dict(START)
    kw.setdefault("accept", True)
    if not kw["accept"]:
        kw.setdefault("guard", None)
    else:
        kw.setdefault("guard", MapGuard(states=STATES, on=FIRST_SCREEN))
        kw.setdefault("identity", _IdentityMap())
    result = drive.run_recon(
        _manifest(tmp_path), guest=guest, holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=_title(), **kw)
    return guest, result


def _keys(guest):
    return [c[2] for c in guest.calls if c[0] == "press"]


def test_accept_presses_exactly_the_plans_keys_in_order_and_never_y(tmp_path, clock):
    guest, result = _run(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]
    keys = _keys(guest)
    assert keys == POOL_KEYS
    assert "Y" not in keys
    # RETURN never follows a save letter: nothing after C or D but the answer N.
    for letter in ("C", "D"):
        assert keys[keys.index(letter) + 1] == "N"
    (drives, options), = guest.starts
    assert [d and d.rsplit("-", 1)[1] for d in drives] == ["disk1.adf", "disk2.adf", "save.adf"]
    assert options == ("nr_floppies=3", "floppy2type=0")
    assert guest.inserted == []


def test_the_description_itself_has_no_y_and_no_return_after_a_write():
    route = foundation.POOL.route
    assert "Y" not in [str(step[0]).upper() for step in route]
    for at, (key, _state, kind) in enumerate(route):
        if kind == "write":
            assert key in ("C", "D")
            assert route[at + 1][0] == "N"
    assert not any(row[1][1].upper() == "Y" for row in foundation.POOL.interstitials)


def test_the_walk_passes_with_c_at_the_prepared_place_and_d_one_square_on_facing_south(
        tmp_path, clock):
    _, result = _run(tmp_path, clock)
    verdicts = result["read"]["verdicts"]
    assert verdicts[0] == "slot C: did not move"
    assert verdicts[2] == "slot D matches the game's own save after the same walk"
    assert result["read"]["verdicts"][1].startswith("slot D: moved 1 square")
    assert result["walk"]["b_ok"] and result["walk"]["d_ok"]


@pytest.mark.parametrize("land,expected", [
    (dict(START, facing=geo.SOUTH), "did not move"),
    (dict(START, y=14), "expected 9,14"),
])
def test_the_walk_fails_when_d_stands_still_or_keeps_facing_north(tmp_path, clock, land, expected):
    guest = TitleGuest(clock, save_key="save", land=land)
    _, result = _run(tmp_path, clock, guest=guest)
    assert result["success"] is False
    assert expected in result["read"]["verdicts"][1]


def test_measure_stops_before_the_first_save_and_presses_the_measure_route(tmp_path, clock):
    guest, result = _run(tmp_path, clock, accept=False, measure=True)
    assert _keys(guest) == "RET RET L RET A V E NP2 NP8 E S".split()
    assert result["success"] is True and result["control_sha256"] is None
    assert not {"C", "D", "Y"} & set(_keys(guest))


def test_prepare_refuses_a_specimen_whose_sha256_differs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    other = tmp_path / "other.adf"
    other.write_bytes(b"not the specimen")
    with pytest.raises(drive.RouteError, match="specimen SHA-256 differs"):
        foundation.prepare(foundation.POOL, "refused", specimen=other)
    assert not (tmp_path / ".cache").exists()


def test_prepare_refuses_a_title_that_is_not_registered_here(tmp_path):
    with pytest.raises(drive.RouteError, match="not one of this module's titles"):
        foundation.prepare(_title(), "x")


def test_prepare_refuses_a_run_id_that_is_not_lane_safe():
    with pytest.raises(drive.RouteError, match="run id"):
        foundation.prepare(foundation.POOL, "a b")


def test_main_runs_each_command_and_exits_zero_only_on_success(tmp_path, clock, monkeypatch,
                                                              capsys):
    guest = TitleGuest(clock, save_key="save")
    guest.place = dict(START)
    monkeypatch.setattr(foundation, "WinGuest", lambda: guest)
    monkeypatch.setattr(foundation, "PixelGuards",
                        lambda path: MapGuard(states=STATES, on=FIRST_SCREEN)
                        if "guards" in str(path) else _IdentityMap())
    monkeypatch.setattr(foundation, "TITLES", {"pool": _title()})
    manifest = _manifest(tmp_path)
    args = ["accept", "--title", "pool", "--manifest", str(manifest), "--audio-proof",
            str(_audio_proof(tmp_path)), "--attempt", "accept1", "--guards", "guards.json",
            "--identity", "identity.json", "--holder", "wish679-test"]
    assert foundation.main(args) == 0
    out = capsys.readouterr().out
    assert '"success": true' in out and "slot D matches the game's own save" in out
    guest2 = TitleGuest(clock, save_key="save", land=dict(START))
    guest2.place = dict(START)
    monkeypatch.setattr(foundation, "WinGuest", lambda: guest2)
    other = tmp_path / "second"
    other.mkdir()
    args2 = [a if a != str(manifest) else str(_manifest(other)) for a in args]
    assert foundation.main(args2) == 1
    assert "slot D: did not move" in capsys.readouterr().out


def test_main_exits_two_when_the_run_is_refused(tmp_path, capsys):
    assert foundation.main(["prepare", "--title", "pool", "--run-id", "a b"]) == 2
    assert "run id" in capsys.readouterr().err


# What needs the player's own disks and the specimen tree; CI has neither.
def _registered():
    try:
        specimen = foundation.specimens.tree_root().joinpath(*foundation.POOL_SPECIMEN)
        if not specimen.is_file():
            pytest.skip("the Pool specimen is not in the registry")
        foundation._find_images({"disk1": foundation.POOL_DISK1_SHA256,
                                 "disk2": foundation.POOL_DISK2_SHA256})
    except drive.RouteError:
        pytest.skip("the registered Pool disks are not here")
    return specimen


def test_the_real_readers_decode_the_specimens_two_slots():
    specimen = _registered()
    disk = AmigaDisk.open(specimen)
    assert foundation.POOL.slot_letters(disk) == ["A", "B"]
    a, b = (foundation.POOL.read_slot(disk, letter) for letter in "AB")
    assert a["place"] == START and b["place"] == LATER
    assert a["names"] == b["names"] and a["names"][0] == "BRUTUS"
    assert foundation.POOL.read_slot(disk, "C") == {"missing": True, "sha256": None}
    assert all(name.startswith("CHRDAT") or name.startswith("savgam")
               for name in foundation.POOL.slot_files(disk, "A"))
    assert "savgamA.dat" in foundation.POOL.slot_files(disk, "A")


def test_prepare_writes_the_places_and_leaves_every_registered_image_unchanged(
        tmp_path, monkeypatch):
    specimen = _registered()
    before = {label: hashlib.sha256(data).hexdigest()
              for label, data in foundation.amigasaves.images()}
    specimen_before = drive.sha256(specimen)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    path = foundation.prepare(foundation.POOL, "registry-run")
    manifest = json.loads(path.read_text())
    assert manifest["title"] == "pool"
    assert manifest["state_a"] == START and manifest["expected_after"] == LATER
    assert manifest["loaded_letter"] == "A" and manifest["names_a"][0] == "BRUTUS"
    assert set(manifest["disks"]) == {"disk1", "disk2", "save"}
    for key, entry in manifest["disks"].items():
        assert drive.sha256(pathlib.Path(entry["path"])) == entry["sha256"]
        assert pathlib.Path(entry["path"]).is_relative_to(tmp_path)
    assert manifest["disks"]["disk1"]["sha256"] == foundation.POOL_DISK1_SHA256
    assert manifest["disks"]["save"]["sha256"] == foundation.POOL_SPECIMEN_SHA256
    after = {label: hashlib.sha256(data).hexdigest()
             for label, data in foundation.amigasaves.images()}
    assert after == before and drive.sha256(specimen) == specimen_before
    # The manifest is one the driver accepts, before any lane is claimed.
    assert drive._title_inputs(manifest, foundation.POOL)[2] == "A"


# Curse of the Azure Bonds: the control save is D, the after save F, and the game's own exit key E
# is never a save letter.
CURSE_START = {"area": 1, "x": 4, "y": 4, "facing": geo.NORTH}
CURSE_LATER = dict(CURSE_START, y=2)
CURSE_STATES = ("title", "front_end", "load_picker", "loaded_menu", "sheet", "save_picker",
                "world", "camp", "camp_save_picker", "exit_game")
_FRONT = (b"frame 0", b"frame 1")
CURSE_FIRST_SCREEN = {"front_end": lambda path: path.read_bytes() in _FRONT,
                      "title": lambda path: path.read_bytes() not in _FRONT}
CURSE_KEYS = ["ESC", "ESC", "L", "B", "V", "E", "S", "D", "B", "NP8", "NP8", "E", "S", "F", "N"]


class CurseGuest(TitleGuest):
    """The game writes slot D at its `D` and slot F at its `F`, with the party where the keys took it."""

    def press(self, holder, key, timeout=None):
        super(TitleGuest, self).press(holder, key, timeout)
        if key == "NP8":
            dx, dy = geo.STEP[self.place["facing"]]
            self.place["x"] += dx
            self.place["y"] += dy
        elif key == "D":
            self._write("D", self.place)
        elif key == "F":
            self._write("F", self.land or self.place)


def _curse_title():
    return dataclasses.replace(foundation.CURSE, read_slot=_read_slot, slot_letters=_letters,
                               slot_files=_files)


def _curse_manifest(tmp_path):
    slots = [("A", _slot(dict(CURSE_START, x=3, y=14))), ("B", _slot(CURSE_START)),
             ("C", _slot(CURSE_LATER))]
    disks = {"save": _adf(tmp_path / "save.adf", "CurseA", slots),
             "diskb": _adf(tmp_path / "diskb.adf", "CurseB")}
    data = {"disks": disks, "registered": {"specimen": _adf(tmp_path / "specimen.adf", "REG")},
            "loaded_letter": "B", "state_a": CURSE_START, "names_a": NAMES,
            "expected_after": CURSE_LATER}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


def _curse_run(tmp_path, clock, *, guest=None, **kw):
    guest = guest or CurseGuest(clock, save_key="save")
    guest.place = dict(CURSE_START)
    kw.setdefault("accept", True)
    if kw["accept"]:
        kw.setdefault("guard", MapGuard(states=CURSE_STATES, on=CURSE_FIRST_SCREEN))
        kw.setdefault("identity", _IdentityMap())
    result = drive.run_recon(
        _curse_manifest(tmp_path), guest=guest, holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=_curse_title(), **kw)
    return guest, result


def test_curse_accept_presses_exactly_the_plans_keys_in_order_and_never_y(tmp_path, clock):
    guest, result = _curse_run(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]
    assert _keys(guest) == CURSE_KEYS and "Y" not in _keys(guest)
    (drives, options), = guest.starts
    assert [d and d.rsplit("-", 1)[1] for d in drives] == ["save.adf", "diskb.adf"]
    assert options == ()
    assert result["read"]["verdicts"][0] == "slot D: did not move"
    assert result["read"]["verdicts"][1].startswith("slot F: moved 2 squares")
    assert result["read"]["verdicts"][2] == "slot F matches the game's own save after the same walk"


def test_curse_fails_when_f_is_one_square_on(tmp_path, clock):
    guest = CurseGuest(clock, save_key="save", land=dict(CURSE_START, y=3))
    _, result = _curse_run(tmp_path, clock, guest=guest)
    assert result["success"] is False
    assert "expected 4,2" in result["read"]["verdicts"][1]


def test_curse_measure_stops_before_the_first_save(tmp_path, clock):
    guest, result = _curse_run(tmp_path, clock, accept=False, measure=True)
    assert _keys(guest) == "ESC ESC L B V E S".split()
    assert result["success"] is True and result["control_sha256"] is None
    assert not {"D", "F", "Y"} & set(_keys(guest))


def test_the_curse_after_letter_is_not_the_exit_key_and_no_plain_step_presses_a_save_letter():
    curse = foundation.CURSE
    assert curse.after_letter == "F" and curse.control_letter == "D"
    for route in (curse.route, curse.measure_route):
        for key, _state, kind in route:
            if kind != "write":
                assert key not in ("D", "F", "A", "C")
    assert [key for key, _s, kind in curse.route if kind == "write"] == ["D", "F"]


def test_an_after_letter_of_e_is_refused_at_construction():
    with pytest.raises(drive.RouteError, match="presses a save or kept slot letter"):
        dataclasses.replace(foundation.CURSE, after_letter="E")


def test_the_boot_spans_are_pinned():
    assert foundation.POOL.boot_span == 150.0
    assert foundation.CURSE.boot_span == 120.0


def test_prepare_refuses_a_curse_specimen_whose_sha256_differs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    other = tmp_path / "other.adf"
    other.write_bytes(b"not the specimen")
    with pytest.raises(drive.RouteError, match="specimen SHA-256 differs"):
        foundation.prepare(foundation.CURSE, "refused", specimen=other)
    assert not (tmp_path / ".cache").exists()


def _curse_registered():
    specimen = foundation.specimens.tree_root().joinpath(*foundation.CURSE_SPECIMEN)
    if not specimen.is_file():
        pytest.skip("the Curse specimen is not in the registry")
    try:
        foundation._find_images({"diskb": foundation.CURSE_DISK_B_SHA256})
    except drive.RouteError:
        pytest.skip("the registered Curse disk B is not here")
    return specimen


def test_the_real_curse_readers_decode_the_specimens_slots_and_slot_f_is_free():
    disk = AmigaDisk.open(_curse_registered())
    assert foundation.CURSE.slot_letters(disk) == ["A", "B", "C"]
    b, c = (foundation.CURSE.read_slot(disk, letter) for letter in "BC")
    assert b["place"] == CURSE_START and c["place"] == CURSE_LATER
    for letter in "DF":
        assert foundation.CURSE.read_slot(disk, letter) == {"missing": True, "sha256": None}
    assert set(foundation.CURSE.slot_files(disk, "A")) == {"savgamA.dat", "spindisk"}


def test_curse_prepare_writes_the_places_and_leaves_every_registered_image_unchanged(
        tmp_path, monkeypatch):
    specimen = _curse_registered()
    before = {label: hashlib.sha256(data).hexdigest()
              for label, data in foundation.amigasaves.images()}
    specimen_before = drive.sha256(specimen)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    manifest = json.loads(foundation.prepare(foundation.CURSE, "registry-run").read_text())
    assert manifest["title"] == "curse"
    assert manifest["state_a"] == CURSE_START and manifest["expected_after"] == CURSE_LATER
    assert manifest["loaded_letter"] == "B" and set(manifest["disks"]) == {"diskb", "save"}
    assert manifest["disks"]["diskb"]["sha256"] == foundation.CURSE_DISK_B_SHA256
    assert manifest["disks"]["save"]["sha256"] == foundation.CURSE_SPECIMEN_SHA256
    after = {label: hashlib.sha256(data).hexdigest()
             for label, data in foundation.amigasaves.images()}
    assert after == before and drive.sha256(specimen) == specimen_before
    assert drive._title_inputs(manifest, foundation.CURSE)[2] == "B"


# Pools of Darkness: disk 3 goes into DF1 when the boot asks for it, then SPACE; F is the control save
# and G the after save (both offered by the game's save picker, which lists A to H), and E is the game's exit key though slot E is a kept slot.
DARK_START = {"area": 2, "x": 1, "y": 2, "facing": geo.EAST}
DARK_LATER = dict(DARK_START, x=2)
DARK_STATES = ("title", "journal", "journal_answer", "party_menu", "load_from", "load_picker", "disk2_prompt",
               "loaded_menu", "sheet", "save_picker", "world", "camp", "camp_save_picker", "exit_game")
MEASURE_STATES = tuple(s for s in DARK_STATES if s != "title")  # boot crops are not named "title"
DARK_FIRST_SCREEN = {}  # the title crop is recognised by its own name, and nothing precedes it
DARK_KEYS = ["P", "L", "P", "B", "SPACE", "V", "E", "S", "F", "B", "X", "RET", "NP8", "E", "S", "G", "N"]
DARK_ACCEPT_STATES = ("journal", "journal_answer", "world", "camp", "exit_game")


class DarkGuest(TitleGuest):
    """The game writes slot F at its `F` and slot G at its `G`, with the party where the keys took it."""

    def press(self, holder, key, timeout=None):
        super(TitleGuest, self).press(holder, key, timeout)
        if key == "NP8":
            dx, dy = geo.STEP[self.place["facing"]]
            self.place["x"] += dx
            self.place["y"] += dy
        elif key == "F":
            self._write("F", self.place)
        elif key == "G":
            self._write("G", self.land or self.place)


def _dark_title():
    return dataclasses.replace(foundation.DARKNESS, read_slot=_read_slot,
                               slot_letters=_letters, slot_files=_files)


def _dark_manifest(tmp_path):
    slots = [(letter, _slot(dict(DARK_START, x=5) if letter != "B" else DARK_START))
             for letter in "ABCDE"]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "POD 1"),
             "disk2": _adf(tmp_path / "disk2.adf", "POD 2"),
             "disk3": _adf(tmp_path / "disk3.adf", "POD 3", slots)}
    data = {"disks": disks, "registered": {}, "loaded_letter": "B", "state_a": DARK_START,
            "names_a": NAMES}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


def _dark_run(tmp_path, clock, *, guest=None, guard=None, **kw):
    guest = guest or DarkGuest(clock, save_key="disk3")
    guest.place = dict(DARK_START)
    kw.setdefault("accept", True)
    if kw["accept"]:
        kw.setdefault("identity", _IdentityMap())
        guard = guard or MapGuard(states=DARK_STATES, on=DARK_FIRST_SCREEN)
    result = drive.run_recon(
        _dark_manifest(tmp_path), guest=guest, guard=guard, holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=_dark_title(), **kw)
    return guest, result


def test_darkness_accept_presses_the_plans_keys_with_disk_3_mounted_in_df1_and_never_y(
        tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]
    keys = _keys(guest)
    assert result["unguarded"] == []
    assert keys == DARK_KEYS and "Y" not in keys
    assert guest.inserted == [(0, "C:/Amiga/Disks/wish679-wish679-test-disk2.adf")]
    assert keys[0] == "P"
    (drives, options), = guest.starts
    assert [d and d.rsplit("-", 1)[1] for d in drives] == ["disk1.adf", "disk3.adf"]
    assert options == ()
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order[3:6] == ["B", "insert", "SPACE"] and order[6] == "V"
    # E leaves the sheet once and never twice in a row at the party menu.
    assert keys[keys.index("L"):keys.index("S")].count("E") == 1
    assert result["read"]["verdicts"][0] == "slot F: did not move"
    assert result["read"]["verdicts"][1].startswith("slot G: moved 1 square")


@pytest.mark.parametrize("land", [dict(DARK_START), dict(DARK_START, x=2, area=1),
                                  dict(DARK_START, x=3)])
def test_darkness_fails_when_g_stays_or_is_on_another_map_or_two_squares_on(
        tmp_path, clock, land):
    guest = DarkGuest(clock, save_key="disk3", land=land)
    _, result = _dark_run(tmp_path, clock, guest=guest)
    assert result["success"] is False and result["walk"]["d_ok"] is False


def test_darkness_accept_order_puts_the_control_save_before_the_walk_and_the_after_save_after(
        tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock)
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order == "P L P B insert SPACE V E S F B X RET NP8 E S G N".split()
    assert result["events"] and not any("answer" in e or "interstitial" in e
                                        for e in result["events"])


@pytest.mark.parametrize("state", DARK_ACCEPT_STATES)
def test_darkness_accept_refuses_to_start_when_the_guard_map_lacks_a_new_state(
        tmp_path, clock, state):
    guard = MapGuard(states=tuple(s for s in DARK_STATES if s != state), on=DARK_FIRST_SCREEN)
    with pytest.raises(drive.RouteError, match="screen guard map lacks"):
        _dark_run(tmp_path, clock, guard=guard)


def test_darkness_accept_route_answers_the_journal_with_explicit_steps_and_asks_no_answerer():
    darkness = foundation.DARKNESS
    assert darkness.route[8:] == (
        ("F", "loaded_menu", "write"), ("B", "journal", "key"),
        ("X", "journal_answer", "key"), ("RET", "world", "key"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"), ("G", "exit_game", "write"),
        ("N", "camp", "key"))
    assert {"journal", "journal_answer", "world", "camp", "exit_game"} <= darkness.strict
    assert darkness.min_waits["exit_game"] == 20.0
    assert [row[0] for row in darkness.interstitials] == ["yes_no", "continue"]
    assert darkness.interstitials == (
        ("yes_no", ("keys", "N"), frozenset({"world"}), 1),
        ("continue", ("keys", "RET"), frozenset({"world"}), 3))
    assert not any(kind == "answer" for _, _, kind in darkness.route)


def test_darkness_measure_ends_at_the_camp_save_picker_and_writes_nothing(tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock, guard=MapGuard(states=MEASURE_STATES),
                              accept=False, measure=True)
    assert _keys(guest) == "P L P B SPACE V E B X RET NP8 E S".split()
    assert [d for d, _ in guest.inserted] == [0] and result["success"] is True
    assert result["control_sha256"] is None
    order = [c[2] if c[0] == "press" else "insert" for c in guest.calls
             if c[0] in ("press", "insert")]
    assert order == "P L P B insert SPACE V E B X RET NP8 E S".split()
    assert not {"F", "G", "I", "J", "Y"} & set(_keys(guest))


def test_darkness_route_and_measure_route_are_pinned_and_write_only_f_and_g():
    darkness = foundation.DARKNESS
    head = (("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
            ("B", "disk2_prompt", "key"), foundation.DISK2_INSERT,
            ("V", "sheet", "key"), ("E", "loaded_menu", "key"))
    assert darkness.route == head + (
        ("S", "save_picker", "key"), ("F", "loaded_menu", "write"), ("B", "journal", "key"),
        ("X", "journal_answer", "key"), ("RET", "world", "key"),
        ("NP8", "world", "move"), ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("G", "exit_game", "write"), ("N", "camp", "key"))
    assert darkness.measure_route == head + (
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "world", "key"),
        ("NP8", "world", "move"), ("E", "camp", "key"), ("S", "camp_save_picker", "key"))
    assert darkness.min_waits["journal"] == 45.0
    assert darkness.min_waits["journal_answer"] == 3.0
    assert (darkness.control_letter, darkness.after_letter) == ("F", "G")
    assert not {"F", "G"} & set(darkness.kept_letters)
    assert {step[0] for step in darkness.route if step[2] == "write"} == {"F", "G"}


@pytest.mark.parametrize("letter", ["A", "H", "I", "J"])
def test_darkness_refuses_a_write_step_that_is_not_the_control_or_after_letter(letter):
    route = tuple((letter, state, kind) if kind == "write" and key == "F" else (key, state, kind)
                  for key, state, kind in foundation.DARKNESS.route)
    with pytest.raises(drive.RouteError):
        dataclasses.replace(foundation.DARKNESS, route=route)


def test_the_real_darkness_readers_show_f_g_and_h_free_on_disk_3():
    try:
        images = foundation._find_images({"disk3": foundation.DARKNESS_DISK3_SHA256})
    except drive.RouteError:
        pytest.skip("the registered Pools of Darkness disk 3 is not here")
    disk = AmigaDisk(images["disk3"][1])
    assert foundation.DARKNESS.slot_letters(disk) == list("ABCDE")
    for letter in "FGH":
        assert foundation.DARKNESS.read_slot(disk, letter) == {"missing": True, "sha256": None}


def test_darkness_names_where_e_is_the_exit_key_and_nowhere_else():
    darkness = foundation.DARKNESS
    assert darkness.plain_keys == (("E", "loaded_menu"), ("E", "camp"))
    assert darkness.kept_letters == ("A", "C", "D", "E")
    assert darkness.title_limit == 420.0 and darkness.boot_span == 225.0
    assert [s[0][0] for s in darkness.route if s[2] == "insert"] == [0]
    assert all(row[1][0] != "insert" or row[1][1] == 1 for row in darkness.interstitials)
    with pytest.raises(drive.RouteError, match="presses a save or kept slot letter"):
        dataclasses.replace(darkness, plain_keys=(("E", "camp"),))


def test_prepare_refuses_a_darkness_disk_whose_sha256_differs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    other = tmp_path / "other.adf"
    other.write_bytes(b"not disk 3")
    with pytest.raises(drive.RouteError, match="specimen SHA-256 differs"):
        foundation.prepare(foundation.DARKNESS, "refused", specimen=other)
    assert not (tmp_path / ".cache").exists()


def _darkness_registered():
    try:
        return foundation._find_images({"disk1": foundation.DARKNESS_DISK1_SHA256,
                                        "disk2": foundation.DARKNESS_DISK2_SHA256,
                                        "disk3": foundation.DARKNESS_DISK3_SHA256})
    except drive.RouteError:
        pytest.skip("the registered Pools of Darkness disks are not here")


def test_the_real_darkness_readers_decode_slot_b_and_find_i_and_j_free():
    disk = AmigaDisk(_darkness_registered()["disk3"][1])
    assert foundation.DARKNESS.slot_letters(disk) == ["A", "B", "C", "D", "E"]
    b = foundation.DARKNESS.read_slot(disk, "B")
    assert b["place"] == DARK_START and len(b["names"]) == 6
    for letter in "IJ":
        assert foundation.DARKNESS.read_slot(disk, letter) == {"missing": True, "sha256": None}


def test_darkness_prepare_writes_the_place_and_leaves_every_registered_image_unchanged(
        tmp_path, monkeypatch):
    _darkness_registered()
    before = {label: hashlib.sha256(data).hexdigest()
              for label, data in foundation.amigasaves.images()}
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    manifest = json.loads(foundation.prepare(foundation.DARKNESS, "registry-run").read_text())
    assert manifest["title"] == "darkness"
    assert manifest["state_a"] == DARK_START and manifest["loaded_letter"] == "B"
    assert "expected_after" not in manifest
    assert set(manifest["disks"]) == {"disk1", "disk2", "disk3"}
    assert manifest["disks"]["disk3"]["sha256"] == foundation.DARKNESS_DISK3_SHA256
    after = {label: hashlib.sha256(data).hexdigest()
             for label, data in foundation.amigasaves.images()}
    assert after == before
    assert drive._title_inputs(manifest, foundation.DARKNESS)[2] == "B"


# What each title's interstitials do and where: a screen guard that matches only the crop of one
# named wait shows the run answering it there, up to its limit, and staying silent in every other wait.
def _on(*stems):
    return lambda path: path.stem in stems


def _never(_path):
    return False


def _dark_guard(screen, when, **closed):
    on = {**DARK_FIRST_SCREEN, screen: _on(*when), **{s: _never for s in closed}}
    return MapGuard(states=(*DARK_STATES, screen), on=on)


def test_darkness_answers_yes_no_with_n_once_and_only_while_waiting_for_the_world(
        tmp_path, clock):
    guest, _ = _dark_run(tmp_path, clock, guard=_dark_guard("yes_no", ["12-world"], world=1))
    assert _keys(guest).count("N") == 1 and "Y" not in _keys(guest)
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _dark_run(other, clock, guard=_dark_guard("yes_no", ["01-party_menu"], party_menu=1))
    assert "N" not in _keys(guest) and "Y" not in _keys(guest)


def test_darkness_presses_return_at_a_continue_page_three_times_at_most_and_only_for_the_world(
        tmp_path, clock):
    guest, _ = _dark_run(tmp_path, clock, guard=_dark_guard("continue", ["12-world"], world=1))
    assert _keys(guest).count("RET") == 4  # the route's own, then three page turns
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _dark_run(other, clock, guard=_dark_guard("continue", ["01-party_menu"], party_menu=1))
    assert "RET" not in _keys(guest)


def _curse_guard(screen, when, **closed):
    on = {**CURSE_FIRST_SCREEN, screen: _on(*when), **{s: _never for s in closed}}
    return MapGuard(states=(*CURSE_STATES, screen, "front_end"), on=on)


def test_curse_leaves_the_front_end_with_escape_four_times_at_most_and_only_for_the_title(
        tmp_path, clock):
    guard = MapGuard(states=CURSE_STATES, on={"title": _never, "front_end": _on("title")})
    guest, result = _curse_run(tmp_path, clock, guard=guard)
    assert _keys(guest) == ["ESC"] * 4 and "title screen was not recognized" in result["error"]
    other = tmp_path / "other"
    other.mkdir()
    guard = MapGuard(states=CURSE_STATES, on={
        **CURSE_FIRST_SCREEN, "load_picker": _never,
        "front_end": lambda path: (path.stem == "title" and path.read_bytes() in _FRONT
                                   or path.stem == "01-load_picker")})
    guest, _ = _curse_run(other, clock, guard=guard)
    assert _keys(guest).count("ESC") == 2  # the two the title wait needed, none at load_picker


@pytest.mark.parametrize("screen,state", [("07-world", "world"), ("12-exit_game", "exit_game")])
def test_curse_presses_return_at_a_continue_page_three_times_at_most(
        tmp_path, clock, screen, state):
    guest, _ = _curse_run(tmp_path, clock, guard=_curse_guard("continue", [screen],
                                                              **{state: 1}))
    assert _keys(guest).count("RET") == 3


def test_curse_presses_no_return_at_a_continue_page_while_waiting_for_another_state(
        tmp_path, clock):
    guest, _ = _curse_run(tmp_path, clock, guard=_curse_guard("continue", ["01-load_picker"],
                                                              load_picker=1))
    assert "RET" not in _keys(guest)


def _pool_guard(screen, when, **closed):
    on = {**FIRST_SCREEN, screen: _on(*when), **{s: _never for s in closed}}
    return MapGuard(states=(*STATES, screen), on=on)


def test_pool_presses_return_at_the_wheel_once_and_only_while_waiting_for_the_title(
        tmp_path, clock):
    guard = MapGuard(states=STATES, on={"title": _never, "wheel": _on("title")})
    guest, _ = _run(tmp_path, clock, guard=guard)
    assert _keys(guest) == ["RET"]
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _run(other, clock, guard=_pool_guard("wheel", ["title", "01-party_menu"],
                                                    party_menu=1))
    assert _keys(guest) == ["RET", "RET"]  # the wheel's, then the route's first; none at party_menu


def test_pool_answers_the_path_prompt_once_at_the_camp_save_picker_and_nowhere_else(
        tmp_path, clock):
    guest, _ = _run(tmp_path, clock, guard=_pool_guard(
        "save_path", ["08-camp_save_picker"], camp_save_picker=1))
    assert _keys(guest).count("RET") == 4  # wheel, two route RETs, and the one prompt answer
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _run(other, clock, guard=_pool_guard("save_path", ["05-sheet"], sheet=1))
    assert _keys(guest).count("RET") == 3


@pytest.mark.parametrize("title,key,prefix,at_least", [
    ("darkness", "B", "10-journal", 45.0),   # BEGIN loads the journal question, so the wait is long
    ("curse", "B", "07-world", 20.0),
    ("pool", "A", "04-world", 20.0),
])
def test_the_world_is_not_looked_at_before_its_minimum_wait_has_passed(
        tmp_path, clock, title, key, prefix, at_least):
    log = []
    guest = {"darkness": DarkGuest, "curse": CurseGuest, "pool": TitleGuest}[title](
        clock, save_key={"darkness": "disk3", "curse": "save", "pool": "save"}[title])
    press = guest.press
    guest.press = lambda holder, k, timeout=None: (log.append((k, clock.now)),
                                                    press(holder, k, timeout))[1]
    run = {"darkness": _dark_run, "curse": _curse_run, "pool": _run}[title]
    run(tmp_path, clock, guest=guest)
    pressed = [t for k, t in log if k == key][-1]  # the last B is BEGIN, which reaches the world
    grabbed = next(t for name, t in guest.at if name.startswith(prefix))
    assert grabbed - pressed >= at_least


def test_the_curse_measure_route_reaches_the_party_menu_before_l():
    states = [state for _key, state, _kind in foundation.CURSE.measure_route]
    assert states[:2] == ["front_end", "title"]  # the copy-protection screen, then the party menu
    assert states[2] == "load_picker"
    # The accept route starts at that menu, and the interstitial waits for the same state.
    assert foundation.CURSE.route[0][0] == "L"
    assert foundation.CURSE.interstitials[0][2] == frozenset({"title"})


def test_darkness_mounts_disks_1_and_3_and_stages_disk_2_as_a_spare_for_the_df0_insert():
    darkness = foundation.DARKNESS
    assert darkness.mounted == ("disk1", "disk3") and darkness.spares == ("disk2",)
    assert darkness.options == ()
    assert set(darkness.disk_keys) == {"disk1", "disk2", "disk3"}
    assert darkness.disk_prompts == frozenset({"disk2_prompt"})
    assert "disk2_prompt" in darkness.strict and darkness.min_waits["disk2_prompt"] == 10.0


def test_darkness_inserts_disk_2_into_df0_at_the_prompt_after_the_slot_letter():
    insert = ((0, "disk2", "SPACE"), "loaded_menu", "insert")
    head = (("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
            ("B", "disk2_prompt", "key"), insert)
    tail = (("V", "sheet", "key"), ("E", "loaded_menu", "key"), ("S", "save_picker", "key"))
    assert foundation.DARKNESS.route[:8] == head + tail
    assert foundation.DARKNESS.measure_route[:5] == head


def test_darkness_has_no_disk_prompt_interstitial_and_pins_its_boot_span_as_a_guess():
    # With disk 3 mounted no prompt appeared. The 225 s span puts the first key near the title in
    # the one measured boot; that timing is a guess until a title guard recognises the screen.
    assert [row[0] for row in foundation.DARKNESS.interstitials] == ["yes_no", "continue"]
    assert foundation.DARKNESS.boot_span == 225.0
    first_four = (("P", "party_menu", "key"), ("L", "load_from", "key"),
                  ("P", "load_picker", "key"), ("B", "disk2_prompt", "key"))
    assert foundation.DARKNESS.measure_route[:4] == first_four
    assert foundation.DARKNESS.route[:4] == first_four
    # The load-from prompt offers POOLS, SECRET and EXIT; only POOLS (P) is ever chosen.
    assert "load_from" in foundation.DARKNESS.strict
    assert foundation.DARKNESS.min_waits["load_from"] == 20.0


def test_curse_leaves_the_intro_with_one_escape_and_only_while_waiting_for_the_title(
        tmp_path, clock):
    states = (*CURSE_STATES, "intro")
    guard = MapGuard(states=states, on={"title": _never, "intro": _on("title")})
    guest, result = _curse_run(tmp_path, clock, guard=guard)
    assert _keys(guest) == ["ESC"] and "title screen was not recognized" in result["error"]
    other = tmp_path / "other"
    other.mkdir()
    guard = MapGuard(states=states, on={"title": lambda p: True, "load_picker": _never,
                                        "intro": _on("01-load_picker")})
    guest, _ = _curse_run(other, clock, guard=guard)
    assert "ESC" not in _keys(guest)


class _Called:
    """A stand-in `run_recon` that records its keywords and reports a passing run."""

    def __init__(self):
        self.calls = []

    def __call__(self, manifest, **kw):
        self.calls.append(kw)
        return {"success": True, "error": "", "unguarded": [], "read": {"verdicts": []}}


def _measure_args(tmp_path, *extra):
    return ["measure", "--title", "pool", "--manifest", str(tmp_path / "prepare.json"),
            "--audio-proof", str(tmp_path / "mute.json"), "--attempt", "measure1", *extra]


def test_measure_passes_the_guard_file_it_is_given_and_none_without_one(tmp_path, monkeypatch):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    assert foundation.main(_measure_args(tmp_path)) == 0
    assert called.calls[-1]["guard"] is None and called.calls[-1]["measure"] is True
    assert foundation.main(_measure_args(tmp_path, "--guards", "g.json")) == 0
    assert called.calls[-1]["guard"] == ("guards", "g.json")


def test_measure_refuses_an_unreadable_guards_file_before_any_run_starts(tmp_path, monkeypatch,
                                                                         capsys):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    missing = tmp_path / "missing.json"
    assert foundation.main(_measure_args(tmp_path, "--guards", str(missing))) == 2
    assert called.calls == [] and "amigafoundation:" in capsys.readouterr().err
    unreadable = tmp_path / "bad.json"
    unreadable.write_text("not json")
    assert foundation.main(_measure_args(tmp_path, "--guards", str(unreadable))) == 2
    assert called.calls == []


def test_accept_still_passes_its_guard_and_identity_files(tmp_path, monkeypatch):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    args = _measure_args(tmp_path, "--guards", "g.json", "--identity", "i.json")
    args[0] = "accept"
    assert foundation.main(args) == 0
    assert called.calls[-1]["guard"] == ("guards", "g.json")
    assert called.calls[-1]["identity"] == ("guards", "i.json")


def test_darkness_prepare_copies_disk_2_as_a_working_copy_never_the_registered_image(
        tmp_path, monkeypatch):
    _darkness_registered()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    manifest = json.loads(foundation.prepare(foundation.DARKNESS, "disk2-run").read_text())
    entry = manifest["disks"]["disk2"]
    assert entry["sha256"] == foundation.DARKNESS_DISK2_SHA256
    assert pathlib.Path(entry["path"]).is_relative_to(tmp_path)
    assert manifest["sources"]["disk2"]["sha256"] == foundation.DARKNESS_DISK2_SHA256


def test_darkness_never_presses_the_continuation_key_when_the_df0_insert_fails(tmp_path, clock):
    class Refused(DarkGuest):
        def insert(self, holder, drive_number, remote, timeout=None, sha256=None):
            self.calls.append(("insert", drive_number, remote))
            exc = RuntimeError("drive 0 refused")
            exc.receipt = {"status": "refused"}
            raise exc

    guest, result = _dark_run(tmp_path, clock, guest=Refused(clock, save_key="disk3"))
    assert result["success"] is False and _keys(guest) == ["P", "L", "P", "B"]
    event = next(e for e in result["events"] if "insert" in e)
    assert event["drive"] == 0 and event["insert"] == "disk2"
    assert event["error"] == "drive 0 refused" and event["receipt"] == {"status": "refused"}


def test_darkness_insert_carries_the_disk_2_hash(tmp_path, clock):
    seen = []

    class Watching(DarkGuest):
        def insert(self, holder, drive_number, remote, timeout=None, sha256=None):
            seen.append((drive_number, remote.rsplit("-", 1)[1], sha256))
            return super().insert(holder, drive_number, remote, timeout, sha256)

    _dark_run(tmp_path, clock, guest=Watching(clock, save_key="disk3"))
    sha = hashlib.sha256((tmp_path / "disk2.adf").read_bytes()).hexdigest()
    assert seen == [(0, "disk2.adf", sha)]


@pytest.mark.parametrize("guard", [None, "lacking"])
def test_darkness_measure_refuses_a_df0_insert_without_a_guard_on_the_prompt(
        tmp_path, clock, guard):
    if guard:
        guard = MapGuard(states=tuple(s for s in MEASURE_STATES if s != "disk2_prompt"), on={})
    guest = DarkGuest(clock, save_key="disk3")
    with pytest.raises(drive.RouteError, match="disk2_prompt.*DF0 insert needs a guard"):
        _dark_run(tmp_path, clock, guest=guest, guard=guard, accept=False, measure=True)
    assert guest.calls == []


def test_darkness_measure_starts_when_the_guard_map_has_the_prompt(tmp_path, clock):
    guard = MapGuard(states=MEASURE_STATES)
    guest, result = _dark_run(tmp_path, clock, guard=guard, accept=False, measure=True)
    assert guest.starts and [d for d, _ in guest.inserted] == [0]


# The reload title: load the game-written slot G, write nothing, and judge the place on the screen.
RELOAD_KEYS = "P L P G SPACE V E B X RET".split()
G_PLACE = DARK_LATER
F_PLACE = DARK_START
G_KEY, F_KEY = drive.place_state(G_PLACE), drive.place_state(F_PLACE)
RELOAD_STATES = (*DARK_STATES, G_KEY, F_KEY)
G_LINE = f"slot G: reloaded at area 2 2,2 facing {G_PLACE['facing']}"
F_LINE = f"slot F: area 2 1,2 facing {F_PLACE['facing']} is not on the screen"


class ReloadGuest(TitleGuest):
    """The game shows `loads` after G is pressed at the load picker and writes only what `spoil` does."""

    def __init__(self, clock, *, loads=G_PLACE, spoil=None):
        super().__init__(clock, save_key="disk3", spoil=spoil)
        self.loads = loads

    def press(self, holder, key, timeout=None):
        super(TitleGuest, self).press(holder, key, timeout)
        if key == "G":
            self.place = dict(self.loads)
        elif key == "RET" and self.spoil:
            self.spoil(self)

    def write_file(self, path, raw):
        remote = next(r for r in self.mounted if r and r.endswith("-disk3.adf"))
        disk = AmigaDisk(self.remote[remote])
        disk.write_file(path, raw)
        self.remote[remote] = disk.to_bytes()


def _reload_title():
    return dataclasses.replace(foundation.DARKNESS_RELOAD, read_slot=_read_slot,
                               slot_letters=_letters, slot_files=_files)


def _reload_manifest(tmp_path):
    slots = [(letter, _slot(F_PLACE if letter != "G" else G_PLACE)) for letter in "ABCDEFG"]
    disks = {"disk1": _adf(tmp_path / "disk1.adf", "POD 1"),
             "disk2": _adf(tmp_path / "disk2.adf", "POD 2"),
             "disk3": _adf(tmp_path / "disk3.adf", "POD 3", slots)}
    data = {"disks": disks,
            "registered": {"accept_disk3": _adf(tmp_path / "accept3.adf", "POD 3", slots)},
            "loaded_letter": "G", "state_a": G_PLACE, "names_a": NAMES,
            "other_letter": "F", "other_place": F_PLACE}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


def _reload_guard(guest, *, g=None, f=None, states=RELOAD_STATES):
    """Each place key checks the fake's current place, unless `g` or `f` replaces its rule."""
    on = {G_KEY: g or (lambda _p: guest.place == G_PLACE),
          F_KEY: f or (lambda _p: guest.place == F_PLACE)}
    return MapGuard(states=states, on=on)


def _reload_run(tmp_path, clock, *, guest=None, guard=None, title=None, **kw):
    guest = guest or ReloadGuest(clock)
    kw.setdefault("reload", True)
    kw.setdefault("identity", _IdentityMap())
    result = drive.run_recon(
        _reload_manifest(tmp_path), guest=guest, guard=guard or _reload_guard(guest),
        holder="wish679-test", audio_proof=_audio_proof(tmp_path),
        title=title or _reload_title(), **kw)
    return guest, result


def test_reload_presses_the_route_writes_nothing_and_judges_the_place_on_the_screen(
        tmp_path, clock):
    guest, result = _reload_run(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]
    keys = _keys(guest)
    assert keys == RELOAD_KEYS
    assert not {"S", "F", "H", "N", "Y"} & set(keys)
    assert guest.inserted == [(0, "C:/Amiga/Disks/wish679-wish679-test-disk2.adf")]
    assert all(result["disks_unchanged"].values()) and len(result["disks_unchanged"]) == 3
    assert result["read"]["verdicts"] == [G_LINE, F_LINE]
    assert result["reload"]["shown"] is True and result["reload"]["other_shown"] is False
    assert all(result["kept_unchanged"].values()) and result["extra_saves"] == []
    assert result["read"]["loaded_letter"] == "G"


def test_reload_fails_when_the_screen_shows_the_other_slots_place(tmp_path, clock):
    guest = ReloadGuest(clock, loads=F_PLACE)
    _, result = _reload_run(tmp_path, clock, guest=guest)
    assert result["success"] is False
    assert result["reload"]["shown"] is False
    assert result["read"]["verdicts"][0] == (
        f"slot G: area 2 2,2 facing {G_PLACE['facing']} is not on the screen")


def test_reload_fails_when_the_place_guard_matches_both_places(tmp_path, clock):
    guest = ReloadGuest(clock)
    guard = _reload_guard(guest, f=lambda _p: True, g=lambda _p: True)
    _, result = _reload_run(tmp_path, clock, guest=guest, guard=guard)
    assert result["completed"] is True and result["reload"]["shown"] is True
    assert result["reload"]["other_shown"] is True and result["success"] is False
    assert result["read"]["verdicts"] == [
        G_LINE, f"slot F: area 2 1,2 facing {F_PLACE['facing']} is also on the screen"]


def test_reload_fails_when_the_place_guard_never_matches(tmp_path, clock):
    guest = ReloadGuest(clock)
    _, result = _reload_run(tmp_path, clock, guest=guest,
                            guard=_reload_guard(guest, g=lambda _p: False))
    assert result["success"] is False and "place screen was not recognized" in result[
        "error"].replace("place_x2_y2_f1", "place")
    assert result["reload"]["shown"] is False
    assert result["read"]["verdicts"][0].endswith("is not on the screen")


@pytest.mark.parametrize("spoil", [
    lambda guest: guest.write_file("/SAVE/savgamH.sav", _slot(G_PLACE)),
    lambda guest: guest.write_file("/SAVE/notes.dat", b"written by the game"),
], ids=["a slot H", "a file that is no slot"])
def test_reload_fails_when_the_game_writes_to_disk_3(tmp_path, clock, spoil):
    guest = ReloadGuest(clock, spoil=spoil)
    _, result = _reload_run(tmp_path, clock, guest=guest)
    assert result["completed"] is True and result["reload"]["shown"] is True
    assert result["disks_unchanged"]["disk3"] is False
    assert result["success"] is False


def test_reload_refuses_before_the_claim_when_a_guard_or_identity_rule_is_missing(
        tmp_path, clock):
    for missing in (G_KEY, F_KEY):
        guest = ReloadGuest(clock)
        states = tuple(s for s in RELOAD_STATES if s != missing)
        with pytest.raises(drive.RouteError, match="screen guard map lacks"):
            _reload_run(tmp_path, clock, guest=guest, guard=_reload_guard(guest, states=states))
        assert guest.calls == []

    class SheetOnly:
        def __contains__(self, state):
            return state == "sheet"

        def __call__(self, state, path):
            return True

    for identity in (None, SheetOnly()):
        guest = ReloadGuest(clock)
        with pytest.raises(drive.RouteError, match="identity map lacks"):
            _reload_run(tmp_path, clock, guest=guest, identity=identity)
        assert guest.calls == []


@pytest.mark.parametrize("title,mode", [
    ("reload", {"accept": True}), ("reload", {"measure": True}),
    ("darkness", {"reload": True}),
])
def test_a_title_with_no_save_letters_runs_only_as_a_reload(tmp_path, clock, title, mode):
    guest = ReloadGuest(clock)
    chosen = _reload_title() if title == "reload" else _dark_title()
    with pytest.raises(drive.RouteError, match="reload"):
        _reload_run(tmp_path, clock, guest=guest, title=chosen, **{"reload": False, **mode})
    assert guest.calls == []


def test_the_reload_description_is_pinned():
    reload = foundation.DARKNESS_RELOAD
    assert foundation.TITLES["darkness-reload"] is reload
    assert foundation.DARKNESS_RELOAD_LOADED == "G"
    assert reload.route == reload.measure_route == (
        ("P", "party_menu", "key"), ("L", "load_from", "key"), ("P", "load_picker", "key"),
        ("G", "disk2_prompt", "key"), foundation.DISK2_INSERT,
        ("V", "sheet", "key"), ("E", "loaded_menu", "key"),
        ("B", "journal", "key"), ("X", "journal_answer", "key"), ("RET", "world", "key"))
    assert reload.route[3][0] == foundation.DARKNESS_RELOAD_LOADED
    assert reload.control_letter is None and reload.after_letter is None
    assert reload.kept_letters == ("A", "B", "C", "D", "E", "F")
    assert reload.plain_keys == (("E", "loaded_menu"), ("B", "journal"))
    assert reload.strict == {step[1] for step in reload.route}
    assert not any(kind in ("write", "move") for _, _, kind in reload.route)
    assert drive.place_state(dict(area=2, x=2, y=2, facing=geo.EAST)) == "place_x2_y2_f1"
    assert foundation.DARKNESS.control_letter == "F"


# Preparing a reload from a game-written disk 3, on synthetic disks.
def _reload_registered(tmp_path, monkeypatch):
    """A registered disk 3 with slots A to E, and the pins and image finder that point at it."""
    slots = [(letter, _slot(DARK_START)) for letter in "ABCDE"]
    files = {"disk1": _adf(tmp_path / "r1.adf", "POD 1"), "disk2": _adf(tmp_path / "r2.adf", "POD 2"),
             "disk3": _adf(tmp_path / "r3.adf", "POD 3", slots)}
    images = {key: pathlib.Path(entry["path"]).read_bytes() for key, entry in files.items()}
    for key, entry in files.items():
        monkeypatch.setattr(foundation, f"DARKNESS_{key.upper()}_SHA256", entry["sha256"])
    monkeypatch.setattr(foundation, "_find_images",
                        lambda wanted: {key: ("registered", images[key]) for key in wanted})
    monkeypatch.setattr(foundation, "DARKNESS_RELOAD", _reload_title())
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return images


def _written_disk3(tmp_path, images, *, f=F_PLACE, g=G_PLACE, extra=(), names=NAMES,
                   name="written3.adf", dropped=None):
    disk = AmigaDisk(images["disk3"])
    if dropped:
        # No file can be deleted, so the disk is rebuilt without one registered slot.
        disk = AmigaDisk.blank("POD 3")
        disk.make_dir("/SAVE")
        for letter in "ABCDE":
            if letter != dropped:
                disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(DARK_START))
    for letter, place in (("F", f), ("G", g)):
        disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(place, names))
    for path, raw in extra:
        disk.write_file(path, raw)
    path = tmp_path / name
    disk.save(path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _accept_summary(tmp_path, sha, *, success=True, accept=True, fetched=None):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"success": success, "accept": accept,
                                "fetched": {"disk3": {"sha256": fetched or sha}}}))
    return path


def _prepare_reload(tmp_path, disk, sha, summary, run_id="reload-run", **kw):
    return foundation.prepare(foundation.TITLES["darkness-reload"], run_id, specimen=disk,
                              specimen_sha256=sha, accept_summary=summary, **kw)


def test_reload_prepare_writes_the_manifest_from_slots_g_and_f(tmp_path, monkeypatch):
    images = _reload_registered(tmp_path, monkeypatch)
    disk, sha = _written_disk3(tmp_path, images)
    summary = _accept_summary(tmp_path, sha)
    manifest = json.loads(_prepare_reload(tmp_path, disk, sha, summary).read_text())
    assert manifest["title"] == "darkness-reload" and manifest["loaded_letter"] == "G"
    assert manifest["state_a"] == G_PLACE and manifest["names_a"] == NAMES
    assert manifest["other_letter"] == "F" and manifest["other_place"] == F_PLACE
    assert manifest["registered"] == {"accept_disk3": {"path": str(disk), "sha256": sha}}
    assert set(manifest["disks"]) == {"disk1", "disk2", "disk3"}
    assert manifest["disks"]["disk3"]["sha256"] == sha
    assert manifest["disks"]["disk3"]["path"] != str(disk)
    assert set(manifest["slot_sha256"]) == {"F", "G"}
    assert manifest["accept_summary"]["sha256"] == hashlib.sha256(summary.read_bytes()).hexdigest()
    assert drive._title_inputs(manifest, _reload_title())[2] == "G"


@pytest.mark.parametrize("what,match", [
    ("hash", "disk 3 SHA-256 differs"),
    ("failed", "not a successful accept run"),
    ("not accept", "not a successful accept run"),
    ("other hash", "another disk"),
    ("extra file", "registered disk 3 plus slots F and G"),
    ("changed file", "registered disk 3 plus slots F and G"),
    ("missing file", "registered disk 3 plus slots F and G"),
    ("other party", "names another party"),
    ("one place", "at one place"),
])
def test_reload_prepare_refuses(tmp_path, monkeypatch, what, match):
    images = _reload_registered(tmp_path, monkeypatch)
    options = {"extra file": {"extra": [("/SAVE/notes.dat", b"x")]},
               "missing file": {"dropped": "A"},
               "other party": {"names": ["OTHER", "PARTY"]},
               "one place": {"g": F_PLACE}}.get(what, {})
    disk, sha = _written_disk3(tmp_path, images, **options)
    if what == "changed file":
        changed = AmigaDisk(disk.read_bytes())
        changed.write_file("/SAVE/savgamA.sav", b"another byte string")
        changed.save(disk)
        sha = hashlib.sha256(disk.read_bytes()).hexdigest()
    summary_args = {"failed": {"success": False}, "not accept": {"accept": False},
                    "other hash": {"fetched": "0" * 64}}.get(what, {})
    summary = _accept_summary(tmp_path, sha, **summary_args)
    with pytest.raises(drive.RouteError, match=match):
        _prepare_reload(tmp_path, disk, "1" * 64 if what == "hash" else sha, summary)
    assert not (tmp_path / ".cache" / "wish" / "acceptance" / "679" / "reload-run").exists()


def test_prepare_requires_the_reload_inputs_only_for_the_reload_title(tmp_path):
    with pytest.raises(drive.RouteError, match="needs the disk 3"):
        foundation.prepare(foundation.TITLES["darkness-reload"], "x", specimen=tmp_path / "a")
    with pytest.raises(drive.RouteError, match="takes no disk 3 hash"):
        foundation.prepare(foundation.DARKNESS, "x", specimen_sha256="0" * 64)
    with pytest.raises(drive.RouteError, match="takes no disk 3 hash"):
        foundation.prepare(foundation.POOL, "x", accept_summary=tmp_path / "s.json")


def test_reload_command_runs_the_reload_and_prints_its_verdicts(tmp_path, monkeypatch, capsys):
    called = _Called()
    monkeypatch.setattr(foundation, "run_recon", called)
    monkeypatch.setattr(foundation, "WinGuest", lambda: object())
    monkeypatch.setattr(foundation, "PixelGuards", lambda path: ("guards", str(path)))
    args = _measure_args(tmp_path, "--guards", "g.json", "--identity", "i.json")
    args[0], args[2] = "reload", "darkness-reload"
    args[args.index("--title") + 1] = "darkness-reload"
    assert foundation.main(args) == 0
    kw = called.calls[-1]
    assert kw["reload"] is True and "accept" not in kw and kw["title"] is foundation.DARKNESS_RELOAD
    assert kw["guard"] == ("guards", "g.json") and kw["identity"] == ("guards", "i.json")


def _reload_manifest_without(tmp_path, edit):
    path = _reload_manifest(tmp_path)
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize("edit,match", [
    (lambda d: d.pop("other_letter"), "manifest lacks 'other_letter'"),
    (lambda d: d.pop("other_place"), "manifest lacks 'other_place'"),
    (lambda d: d["state_a"].pop("x"), "manifest lacks 'x'"),
    (lambda d: d["other_place"].pop("facing"), "manifest lacks 'facing'"),
    (lambda d: d.update(other_place=7), "reload place is not a mapping"),
    (lambda d: d.update(other_letter="H"), "holds no slot H to compare"),
], ids=["other_letter", "other_place", "state_a x", "other_place facing", "not a mapping",
        "other slot absent"])
def test_reload_refuses_a_manifest_that_cannot_be_compared_before_the_claim(
        tmp_path, clock, edit, match):
    guest = ReloadGuest(clock)
    path = _reload_manifest_without(tmp_path, edit)
    with pytest.raises(drive.RouteError, match=match):
        drive.run_recon(path, guest=guest, guard=_reload_guard(guest), identity=_IdentityMap(),
                        holder="wish679-test", audio_proof=_audio_proof(tmp_path),
                        title=_reload_title(), reload=True)
    assert guest.calls == []


@pytest.mark.parametrize("disk", ["disk1", "disk2"])
def test_reload_fails_when_the_game_changes_disk_1_or_2(tmp_path, clock, disk):
    def spoil(guest):
        remote = next(r for r in guest.remote if r.endswith(f"-{disk}.adf"))
        raw = bytearray(guest.remote[remote])
        raw[-1] ^= 0xFF
        guest.remote[remote] = bytes(raw)
    guest = ReloadGuest(clock, spoil=spoil)
    _, result = _reload_run(tmp_path, clock, guest=guest)
    assert result["completed"] is True and result["reload"]["shown"] is True
    assert result["disks_unchanged"][disk] is False and result["success"] is False
