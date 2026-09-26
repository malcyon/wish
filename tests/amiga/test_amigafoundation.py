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


# Pools of Darkness: disk 3 goes into DF1 when the boot asks for it, then SPACE; I is the control save
# and J the after save, and E is the game's exit key though slot E is a kept slot.
DARK_START = {"area": 2, "x": 1, "y": 2, "facing": geo.EAST}
DARK_LATER = dict(DARK_START, x=2)
DARK_STATES = ("title", "journal", "play", "party_menu", "load_picker",
               "loaded_menu", "sheet", "save_picker", "world", "camp", "camp_save_picker")
DARK_FIRST_SCREEN = {}  # the title crop is recognised by its own name, and nothing precedes it
DARK_KEYS = ["P", "P", "L", "B", "V", "E", "S", "I", "B", "NP8", "E", "S", "J"]


class DarkGuest(TitleGuest):
    """The game writes slot I at its `I` and slot J at its `J`, with the party where the keys took it."""

    def press(self, holder, key, timeout=None):
        super(TitleGuest, self).press(holder, key, timeout)
        if key == "NP8":
            dx, dy = geo.STEP[self.place["facing"]]
            self.place["x"] += dx
            self.place["y"] += dy
        elif key == "I":
            self._write("I", self.place)
        elif key == "J":
            self._write("J", self.land or self.place)


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
    assert keys == DARK_KEYS and "Y" not in keys
    assert guest.inserted == [] and keys[0] == "P"  # nothing is inserted; PLAY is the first key
    (drives, options), = guest.starts
    assert [d and d.rsplit("-", 1)[1] for d in drives] == ["disk1.adf", "disk3.adf"]
    assert options == ()
    # E leaves the sheet once and never twice in a row at the party menu.
    assert keys[keys.index("L"):keys.index("S")].count("E") == 1
    assert result["read"]["verdicts"][0] == "slot I: did not move"
    assert result["read"]["verdicts"][1].startswith("slot J: moved 1 square")


@pytest.mark.parametrize("land", [dict(DARK_START), dict(DARK_START, x=2, area=1),
                                  dict(DARK_START, x=3)])
def test_darkness_fails_when_j_stays_or_is_on_another_map_or_two_squares_on(
        tmp_path, clock, land):
    guest = DarkGuest(clock, save_key="disk3", land=land)
    _, result = _dark_run(tmp_path, clock, guest=guest)
    assert result["success"] is False and result["walk"]["d_ok"] is False


def test_darkness_answers_the_journal_at_most_three_times(tmp_path, clock):
    guard = MapGuard(states=DARK_STATES, on={"title": lambda p: False,
                                             "journal": lambda p: True})
    guest, result = _dark_run(tmp_path, clock, guard=guard)
    keys = _keys(guest)
    assert keys.count("X") == 3 and keys.count("RET") == 3
    assert "still on screen after three answers" in result["error"]


def test_darkness_measure_stops_before_the_first_save(tmp_path, clock):
    guest, result = _dark_run(tmp_path, clock, accept=False, measure=True)
    assert _keys(guest) == "P P L B V E S".split()
    assert guest.inserted == [] and result["success"] is True
    assert result["control_sha256"] is None
    assert not {"I", "J", "Y"} & set(_keys(guest))


def test_darkness_names_where_e_is_the_exit_key_and_nowhere_else():
    darkness = foundation.DARKNESS
    assert darkness.plain_keys == (("E", "loaded_menu"), ("E", "camp"))
    assert darkness.kept_letters == ("A", "C", "D", "E")
    assert darkness.title_limit == 420.0 and darkness.boot_span == 225.0
    assert not any(step[2] == "insert" and step[0][0] != 1 for step in darkness.route)
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
    guest, _ = _dark_run(tmp_path, clock, guard=_dark_guard("yes_no", ["09-world"], world=1))
    assert _keys(guest).count("N") == 1 and "Y" not in _keys(guest)
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _dark_run(other, clock, guard=_dark_guard("yes_no", ["01-play"], play=1))
    assert "N" not in _keys(guest) and "Y" not in _keys(guest)


def test_darkness_presses_return_at_a_continue_page_three_times_at_most_and_only_for_the_world(
        tmp_path, clock):
    guest, _ = _dark_run(tmp_path, clock, guard=_dark_guard("continue", ["09-world"], world=1))
    assert _keys(guest).count("RET") == 3
    other = tmp_path / "other"
    other.mkdir()
    guest, _ = _dark_run(other, clock, guard=_dark_guard("continue", ["01-play"], play=1))
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
    ("darkness", "B", "09-world", 45.0),   # BEGIN loads the dungeon, so the wait is long
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


def test_darkness_keeps_disk_2_as_a_registered_spare_so_a_later_df0_insert_can_be_decided():
    assert foundation.DARKNESS.spares == ("disk2",)
    assert "disk2" in foundation.DARKNESS.disk_keys


def test_darkness_has_no_disk_prompt_interstitial_and_pins_its_boot_span_as_a_guess():
    # With disk 3 mounted no prompt appeared. The 225 s span puts the first key near the title in
    # the one measured boot; that timing is a guess until a title guard recognises the screen.
    assert [row[0] for row in foundation.DARKNESS.interstitials] == ["journal", "yes_no",
                                                                     "continue"]
    assert foundation.DARKNESS.boot_span == 225.0
    assert foundation.DARKNESS.measure_route[0] == ("P", "play", "key")
