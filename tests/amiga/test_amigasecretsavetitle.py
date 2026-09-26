"""`run_recon` driven by a title description: a synthetic three-drive title on blank ADFs and a fake guest."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import signal

import pytest

from goldbox import geo
from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigasecretsavemeasure as measure
from tests.amiga.test_amigasecretsave import _audio_proof
from tests.amiga.test_amigasecretsaveaccept import (
    MapGuard,
    _IdentityMap,
    needs_posix_signals,
)
from tests.amiga.test_amigasecretsavemeasure import ScreenGuest
from tools.amiga import amigasecretsave as drive

clock = measure.clock  # the fixture that replaces the driver's time and sleep
START = {"area": 2, "x": 9, "y": 13, "facing": geo.NORTH}
NAMES = ["ALPHA", "BETA"]
STATES = ("party_menu", "load_picker", "loaded_menu", "disk_wait", "world", "camp",
          "camp_picker")


def _slot(place=START, names=NAMES):
    return json.dumps({"place": place, "names": names}).encode()


def _read_slot(disk, letter):
    try:
        raw = disk.read_file(f"/SAVE/savgam{letter}.sav")
    except Exception:
        return {"missing": True, "sha256": None}
    data = json.loads(raw)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "place": data["place"],
            "names": data["names"]}


def _letters(disk):
    return sorted(e.name[6].upper() for e in disk.entries(disk.lookup("/SAVE").block)
                  if e.name.lower().startswith("savgam"))


def _files(disk, letter):
    name = f"savgam{letter}.sav"
    return {name: disk.read_file(f"/SAVE/{name}")}


ROUTE = (
    ("P", "party_menu", "key"), ("L", "load_picker", "key"), ("A", "loaded_menu", "key"),
    ((1, "disk3", "SPACE"), "disk_wait", "insert"), ("C", "loaded_menu", "write"),
    ("NP2", "world", "turn"), ("NP8", "world", "move"), ("E", "camp", "key"),
    ("S", "camp_picker", "key"), ("D", "camp", "write"),
)


def make_title(**over):
    fields = dict(
        issue="679", mounted=("boot", None, "disk3"), spares=("spare",),
        options=("nr_floppies=3", "floppy2type=0"), save_disk="boot",
        read_slot=_read_slot, slot_letters=_letters, slot_files=_files,
        route=ROUTE, measure_route=ROUTE, boot_span=30.0,
        control_letter="C", after_letter="D", kept_letters=("B",), turn="about",
        strict=frozenset({"party_menu", "load_picker", "loaded_menu", "disk_wait",
                          "camp_picker"}),
        min_waits={"world": 5.0})
    fields.update(over)
    return drive.AmigaTitle(**fields)


def _adf(path, volume, slots=()):
    disk = AmigaDisk.blank(volume)
    disk.make_dir("/SAVE")
    for letter, raw in slots:
        disk.write_file(f"/SAVE/savgam{letter}.sav", raw)
    disk.save(path)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def manifest_for(tmp_path, *, expected_after=None, extra_slot=None, loaded="A",
                 save_key="boot"):
    slots = [("A", _slot()), ("B", b"kept slot")] + ([extra_slot] if extra_slot else [])
    disks = {"boot": _adf(tmp_path / "boot.adf", "BOOT", slots if save_key == "boot" else ()),
             "disk3": _adf(tmp_path / "disk3.adf", "THREE", slots if save_key == "disk3" else ()),
             "spare": _adf(tmp_path / "spare.adf", "SPARE")}
    registered = {"reg": _adf(tmp_path / "registered.adf", "REG")}
    data = {"disks": disks, "registered": registered, "loaded_letter": loaded,
            "state_a": START, "names_a": NAMES}
    if expected_after is not None:
        data["expected_after"] = expected_after
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(data))
    return path


class TitleGuest(ScreenGuest):
    """The game writes its two saves to the save disk's drive with the party where the keys took it."""

    def __init__(self, clock, *, save_key="boot", spoil=None, land=None):
        super().__init__(clock)
        self.save_key, self.spoil, self.land = save_key, spoil, land
        self.starts, self.mounted = [], []
        self.place = dict(START)
        self.inserted = []

    def start(self, holder, *drives, timeout=None, options=()):
        self.calls.append(("start", holder, *drives))
        self.starts.append((drives, tuple(options)))
        self.mounted = list(drives)
        return "ok pid=1"

    def insert(self, holder, drive_number, remote, timeout=None, sha256=None):
        self.calls.append(("insert", drive_number, remote))
        self.inserted.append((drive_number, remote))
        self.mounted[drive_number] = remote
        return "ok inserted"

    def _write(self, letter, place):
        remote = next(r for r in self.mounted if r and r.endswith(f"-{self.save_key}.adf"))
        disk = AmigaDisk(self.remote[remote])
        disk.write_file(f"/SAVE/savgam{letter}.sav", _slot(place))
        self.remote[remote] = disk.to_bytes()

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout)
        if key == "NP2":
            self.place["facing"] = geo.OPPOSITE[self.place["facing"]]
        elif key == "NP8":
            dx, dy = geo.STEP[self.place["facing"]]
            self.place["x"] += dx
            self.place["y"] += dy
        elif key == "C":
            self._write("C", self.place)
        elif key == "D":
            self._write("D", self.land or self.place)
            if self.spoil:
                self.spoil(self)


def _run(tmp_path, clock, *, title=None, guest=None, guard=None, manifest=None,
         identity=None, **kw):
    guest = guest or TitleGuest(clock)
    kw.setdefault("accept", True)
    result = drive.run_recon(
        manifest or manifest_for(tmp_path), guest=guest,
        guard=guard or MapGuard(states=("title", *STATES)),
        identity=identity or _IdentityMap(), holder="wish679-test",
        audio_proof=_audio_proof(tmp_path), title=title or make_title(), **kw)
    return guest, result


def _keys(guest):
    return [c[2] for c in guest.calls if c[0] == "press"]


def test_a_title_mounts_every_drive_and_its_options_in_order(monkeypatch):
    sent = []
    guest = drive.WinGuest()
    monkeypatch.setattr(guest, "_lane", lambda holder, command, timeout:
                        sent.append(command) or "ok")
    guest.start("h", "C:/A/d0.adf", None, "C:/A/d2.adf", timeout=60,
                options=("nr_floppies=3", "floppy2type=0"))
    words = sent[0].split()
    assert "-s floppy0=C:\\A\\d0.adf" in sent[0] and "-s floppy2=C:\\A\\d2.adf" in sent[0]
    assert words.index("nr_floppies=3") < words.index("floppy2type=0")
    assert words[-4:] == ["-s", "joyport1=none", "-s", "sound_output=interrupts"]


def test_an_empty_drive_is_ejected_rather_than_left_to_the_template(monkeypatch):
    sent = []
    guest = drive.WinGuest()
    monkeypatch.setattr(guest, "_lane", lambda holder, command, timeout:
                        sent.append(command) or "ok")
    guest.start("h", "C:/A/d0.adf", None, timeout=60)
    assert "-s floppy1= -s" in sent[0]


def test_two_drives_and_no_options_give_todays_start_line(monkeypatch):
    sent = []
    guest = drive.WinGuest()
    monkeypatch.setattr(guest, "_lane", lambda holder, command, timeout:
                        sent.append(command) or "ok")
    guest.start("h", "C:/A/df0.adf", "C:/A/df1.adf", timeout=60)
    assert sent[0] == (
        f"start -f {drive.BOOT_CONFIG} -s floppy0=C:\\A\\df0.adf -s floppy1=C:\\A\\df1.adf "
        f"-s joyport1=none -s sound_output=interrupts")


class _CopyingPopen:
    """A `winvm put` that succeeds."""

    returncode = 0

    def __init__(self, *a, **k):
        pass

    def communicate(self, timeout=None):
        return "", ""


def test_winguest_insert_hands_the_windows_path_holder_and_hash_to_the_pipe(monkeypatch):
    import automap.amiga as amiga

    seen = {}

    class Receipt:
        def as_dict(self):
            return {"status": "ok inserted drive=1"}

    class Pipe:
        def __init__(self, timeout=None, **kw):
            seen["timeout"] = timeout

        def insert_floppy(self, number, path, holder, sha256, staged=None):
            seen["call"] = (number, path, holder, sha256)
            seen["staged"] = staged
            return Receipt()

    monkeypatch.setattr(amiga, "WinuaePipe", Pipe)
    guest = drive.WinGuest()
    monkeypatch.setattr(drive.subprocess, "Popen", _CopyingPopen)
    guest.put(pathlib.Path("disk3.adf"), "C:/Amiga/Disks/wish679-h-disk3.adf", 30)
    receipt = guest.insert("h", 1, "C:/Amiga/Disks/wish679-h-disk3.adf", 30, "ab" * 32)
    assert seen["staged"] == {"C:\\Amiga\\Disks\\wish679-h-disk3.adf"}
    assert receipt == {"status": "ok inserted drive=1"}
    assert seen["call"] == (1, "C:\\Amiga\\Disks\\wish679-h-disk3.adf", "h", "ab" * 32)


def test_a_title_run_passes_and_starts_with_its_drives_and_options(tmp_path, clock):
    guest, result = _run(tmp_path, clock)
    assert result["error"] == "" and result["success"] is True, result["read"]
    (drives, options), = guest.starts
    assert [d and d.rsplit("-", 1)[1] for d in drives] == ["boot.adf", None, "disk3.adf"]
    assert options == ("nr_floppies=3", "floppy2type=0")
    assert "-".join(drives[0].split("-")[:1]) == "C:/Amiga/Disks/wish679"
    assert result["read"]["verdicts"] == [
        "slot C: did not move", "slot D: moved 1 square from area 2 9,13 facing 0 to "
        "area 2 9,14 facing 2"]


def test_spares_are_put_and_every_disk_is_fetched_by_name(tmp_path, clock):
    guest, result = _run(tmp_path, clock)
    put = {c[2].rsplit("-", 1)[1] for c in guest.calls if c[0] == "put"}
    got = {c[1].rsplit("-", 1)[1] for c in guest.calls if c[0] == "get"}
    assert put == got == {"boot.adf", "disk3.adf", "spare.adf"}
    assert sorted(result["fetched"]) == ["boot", "disk3", "spare"]
    assert (tmp_path / "recon1" / "fetched-spare.adf").is_file()
    assert result["disks_unchanged"] == {"boot": False, "disk3": True, "spare": True}


def test_the_saves_are_read_from_the_titles_save_disk(tmp_path, clock):
    seen = []

    def read_slot(disk, letter):
        seen.append(disk.volume_name)
        return _read_slot(disk, letter)

    manifest = manifest_for(tmp_path, save_key="disk3")
    title = make_title(save_disk="disk3", read_slot=read_slot)
    guest = TitleGuest(clock, save_key="disk3")
    _, result = _run(tmp_path, clock, title=title, guest=guest, manifest=manifest)
    assert set(seen) == {"THREE"} and "BOOT" not in seen
    assert result["error"] == "" and result["success"] is True
    assert result["disks_unchanged"] == {"boot": True, "disk3": False, "spare": True}


def test_an_insert_step_inserts_then_presses_its_key(tmp_path, clock):
    guest, result = _run(tmp_path, clock)
    names = [c[0] if c[0] == "insert" else (c[0], c[2]) for c in guest.calls
             if c[0] in ("insert", "press")]
    at = names.index("insert")
    assert names[at + 1] == ("press", "SPACE") and names[at - 1] == ("press", "A")
    assert guest.inserted == [(1, "C:/Amiga/Disks/wish679-wish679-test-disk3.adf")]
    event = next(e for e in result["events"] if "insert" in e)
    assert event["insert"] == "disk3" and event["receipt"] == "ok inserted"


def _waits(guest_clock, state, present_after):
    """A guard that recognises `state` only from its `present_after`-th look; `clock` is unused."""
    looks = []

    def on(path):
        looks.append(path.name)
        return len(looks) >= present_after

    return MapGuard(states=("title", *STATES, "disk_request"),
                    on={state: on, "disk_request": lambda path: True})


def test_an_interstitial_fires_only_while_waiting_for_its_states_and_at_most_its_limit(
        tmp_path, clock):
    rows = (("disk_request", ("keys", "ESC"), frozenset({"load_picker"}), 2),)
    guest, _ = _run(tmp_path, clock, title=make_title(interstitials=rows),
                    guard=_waits(clock, "load_picker", 6))
    assert _keys(guest).count("ESC") == 2  # limited to two though the wait lasted five looks


def test_an_interstitial_for_another_state_stays_silent(tmp_path, clock):
    rows = (("disk_request", ("keys", "ESC"), frozenset({"load_picker"}), 2),)
    guest, _ = _run(tmp_path, clock, title=make_title(interstitials=rows),
                    guard=_waits(clock, "party_menu", 6))
    assert "ESC" not in _keys(guest)


def test_the_about_face_walk():
    at = lambda x, y, facing: {"place": {"area": 2, "x": x, "y": y, "facing": facing}}  # noqa: E731
    control = at(9, 13, geo.NORTH)
    ok = drive.walk_verdict(START, control, at(9, 14, geo.SOUTH), 1, turn="about")
    assert ok["b_ok"] and ok["d_ok"] and ok["squares_moved"] == 1
    stood = drive.walk_verdict(START, control, at(9, 13, geo.SOUTH), 1, turn="about")
    assert not stood["d_ok"] and stood["verdicts"][1] == "slot D: did not move"
    ahead = drive.walk_verdict(START, control, at(9, 14, geo.NORTH), 1, turn="about")
    assert not ahead["d_ok"] and "expected 9,14" in ahead["verdicts"][1]
    # Without the turn the same save is a wrong facing, as it always was.
    plain = drive.walk_verdict(START, control, at(9, 14, geo.SOUTH), 1)
    assert not plain["d_ok"]


def test_the_verdict_lines_name_the_titles_letters():
    at = lambda x, y, facing: {"place": {"area": 2, "x": x, "y": y, "facing": facing}}  # noqa: E731
    walk = drive.walk_verdict(START, at(9, 13, geo.NORTH), at(9, 14, geo.SOUTH), 1,
                              control="I", after="J", turn="about")
    assert [v[:8] for v in walk["verdicts"]] == ["slot I: ", "slot J: "]
    stood = drive.walk_verdict(START, at(9, 13, geo.NORTH), at(9, 13, geo.NORTH), 1,
                               control="I", after="J")
    assert stood["verdicts"] == ["slot I: did not move", "slot J: did not move"]
    off = drive.walk_verdict(START, at(9, 12, geo.NORTH), at(9, 12, geo.NORTH), 1,
                             control="I", after="J")
    assert off["verdicts"][0] == "slot I: moved from 9,13 to 9,12, expected the prepared place"
    assert drive.walk_verdict(START, {"missing": True}, {"missing": True}, 1, control="I",
                              after="J")["verdicts"] == ["slot I: was not written",
                                                         "slot J: was not written"]


def test_a_changed_file_in_a_kept_slot_fails_the_run(tmp_path, clock):
    def spoil(guest):
        remote = next(r for r in guest.mounted if r.endswith("-boot.adf"))
        disk = AmigaDisk(guest.remote[remote])
        disk.write_file("/SAVE/savgamB.sav", b"the game rewrote it")
        guest.remote[remote] = disk.to_bytes()

    _, result = _run(tmp_path, clock, guest=TitleGuest(clock, spoil=spoil))
    assert result["kept_unchanged"]["B"] is False and result["success"] is False


def test_an_extra_save_letter_fails_the_run(tmp_path, clock):
    def spoil(guest):
        remote = next(r for r in guest.mounted if r.endswith("-boot.adf"))
        disk = AmigaDisk(guest.remote[remote])
        disk.write_file("/SAVE/savgamZ.sav", b"stray")
        guest.remote[remote] = disk.to_bytes()

    _, result = _run(tmp_path, clock, guest=TitleGuest(clock, spoil=spoil))
    assert result["extra_saves"] == ["Z"] and result["success"] is False


def test_an_after_slot_that_differs_from_expected_after_fails_the_run(tmp_path, clock):
    same = dict(START, y=14, facing=geo.SOUTH)
    _, good = _run(tmp_path, clock, manifest=manifest_for(tmp_path, expected_after=same))
    assert good["success"] is True
    assert good["read"]["verdicts"][-1] == "slot D matches the game's own save after the same walk"
    other = tmp_path / "other"
    other.mkdir()
    _, bad = _run(other, clock, manifest=manifest_for(other, expected_after=dict(same, y=15)))
    assert bad["success"] is False
    assert bad["read"]["verdicts"][-1] == "slot D differs from the game's own save after the same walk"


def test_a_walk_that_did_nothing_fails_the_run(tmp_path, clock):
    guest = TitleGuest(clock, land=dict(START))
    _, result = _run(tmp_path, clock, guest=guest)
    assert result["walk"]["d_ok"] is False and result["success"] is False


def test_write_keys_are_pressed_only_at_their_named_steps(tmp_path, clock):
    guest, _ = _run(tmp_path, clock)
    assert _keys(guest) == "P L A SPACE C NP2 NP8 E S D".split()


def test_the_journal_answer_presses_x_and_return_and_stops_after_three_rounds(tmp_path, clock):
    route = ROUTE[:2] + ((None, "loaded_menu", "answer"),) + ROUTE[4:]
    title = make_title(route=route, measure_route=route[:2])
    guard = MapGuard(states=("title", *STATES, "journal"), on={"journal": lambda path: True})
    guest, result = _run(tmp_path, clock, title=title, guard=guard)
    assert _keys(guest) == ["P", "L", "X", "RET", "X", "RET", "X", "RET"]
    assert _keys(guest).count("X") == 3 and "still on screen" in result["error"]


def test_measure_with_a_title_never_writes_or_answers(tmp_path, clock):
    guest, result = _run(tmp_path, clock, accept=False, measure=True,
                         guard=MapGuard(states=STATES))
    assert _keys(guest) == "P L A SPACE".split()  # stops at the first write step
    assert guest.inserted and result["success"] is True
    assert result["control_sha256"] is None and "C" not in _keys(guest)


def test_measure_boot_uses_the_titles_span(tmp_path, clock):
    guest, _ = _run(tmp_path, clock, accept=False, measure=True,
                    guard=MapGuard(states=STATES))
    boot = [s for s, _ in guest.at if s.startswith("00-boot")]
    assert len(boot) == 4  # every 10 s across the title's 30 s, not the Silver Blades 120 s


@pytest.mark.parametrize("bad", [
    {"route": (("B", "loaded_menu", "write"),)},                    # a write outside its letters
    {"route": (((1, "nowhere", "SPACE"), "disk_wait", "insert"),)},  # an unknown disk
    {"route": (("F99", "party_menu", "key"),)},                      # no key code
    {"save_disk": "missing"}, {"mounted": (None, "disk3")},
    {"kept_letters": ("C",)}, {"options": ("nr_floppies=3; rm",)},
    {"turn": "left"}, {"boot_span": 0},
    {"interstitials": (("x", ("insert", 1, "nowhere", "SPACE"), None, 1),)},
])
def test_an_inconsistent_description_is_refused(bad):
    with pytest.raises(drive.RouteError, match="title description"):
        make_title(**bad)


def test_a_description_that_does_not_fit_the_manifest_is_refused_before_a_lane_is_claimed(
        tmp_path, clock):
    manifest = manifest_for(tmp_path)
    data = json.loads(manifest.read_text())
    del data["disks"]["spare"]
    manifest.write_text(json.dumps(data))
    guest = TitleGuest(clock)
    with pytest.raises(drive.RouteError, match="lacks 'spare'"):
        _run(tmp_path, clock, guest=guest, manifest=manifest)
    assert guest.calls == []


@pytest.mark.parametrize("kwargs,match", [
    ({"loaded": "C"}, "would overwrite"),
    ({"extra_slot": ("D", b"already there")}, "slot D already exists"),
    ({"loaded": "Q"}, "no slot Q"),
])
def test_a_manifest_that_endangers_a_save_letter_is_refused_before_a_lane_is_claimed(
        tmp_path, clock, kwargs, match):
    guest = TitleGuest(clock)
    with pytest.raises(drive.RouteError, match=match):
        _run(tmp_path, clock, guest=guest, manifest=manifest_for(tmp_path, **kwargs))
    assert guest.calls == []


@pytest.mark.parametrize("modes", [{"accept": False}, {"accept": True, "measure": True}])
def test_a_title_run_is_accept_or_measure(tmp_path, clock, modes):
    guest = TitleGuest(clock)
    with pytest.raises(drive.RouteError, match="either accept or measure"):
        _run(tmp_path, clock, guest=guest, **modes)
    assert guest.calls == []


def test_a_missing_title_guard_is_refused_before_a_lane_is_claimed(tmp_path, clock):
    guest = TitleGuest(clock)
    with pytest.raises(drive.RouteError, match="loaded_menu"):
        _run(tmp_path, clock, guest=guest, guard=MapGuard(states=("title", "party_menu",
                                                                  "load_picker")))
    assert guest.calls == []


def test_the_silver_blades_defaults_are_the_ones_a_title_run_leaves_alone(tmp_path, clock):
    before = (drive.ACCEPT_ROUTE, drive.SILVER_BLADES_INTERSTITIALS, drive.ROUTE,
              drive.MENU_SAVE_LETTER, drive.CAMP_SAVE_LETTER, drive.MEASURE_TITLE_SPAN)
    _run(tmp_path, clock)
    assert before == (drive.ACCEPT_ROUTE, drive.SILVER_BLADES_INTERSTITIALS, drive.ROUTE,
                      drive.MENU_SAVE_LETTER, drive.CAMP_SAVE_LETTER,
                      drive.MEASURE_TITLE_SPAN)
    assert [row[0] for row in drive.SILVER_BLADES_INTERSTITIALS] == [
        "credits", "continue", "journal"]


def _swap(route, at, step):
    return route[:at] + (step,) + route[at + 1:]


INSERT_AT = 3
KEYED = ROUTE[INSERT_AT + 1]  # the control save: `C` at loaded_menu


@pytest.mark.parametrize("drive_number", [0, 2, 3, True])
def test_an_insert_step_may_change_only_drive_1(drive_number):
    route = _swap(ROUTE, INSERT_AT, ((drive_number, "disk3", "SPACE"), "disk_wait", "insert"))
    with pytest.raises(drive.RouteError, match="only DF1"):
        make_title(route=route, measure_route=ROUTE)
    with pytest.raises(drive.RouteError, match="only DF1"):
        make_title(route=ROUTE, measure_route=route)


@pytest.mark.parametrize("drive_number", [0, 2, 3])
def test_an_interstitial_insert_may_change_only_drive_1(drive_number):
    rows = (("disk_request", ("insert", drive_number, "disk3", "SPACE"), None, 1),)
    with pytest.raises(drive.RouteError, match="only DF1"):
        make_title(interstitials=rows)
    make_title(interstitials=(("disk_request", ("insert", 1, "disk3", "SPACE"), None, 1),))


@pytest.mark.parametrize("letter", ["C", "D", "B", "c"])
@pytest.mark.parametrize("kind", ["key", "move", "turn"])
def test_a_step_that_is_not_a_write_may_not_press_a_save_or_kept_letter(letter, kind):
    route = _swap(ROUTE, 0, (letter, "party_menu", kind))
    with pytest.raises(drive.RouteError, match="slot letter"):
        make_title(route=route, measure_route=ROUTE)
    # A measure run reaches the same key, so its route is checked as well.
    with pytest.raises(drive.RouteError, match="slot letter"):
        make_title(route=ROUTE, measure_route=route)


@pytest.mark.parametrize("action", [
    ("keys", "C"), ("keys", ("ESC", "D")), ("keys", "b"), ("insert", 1, "disk3", "C"),
])
def test_an_interstitial_may_not_press_a_save_or_kept_letter(action):
    with pytest.raises(drive.RouteError, match="slot letter"):
        make_title(interstitials=(("disk_request", action, None, 1),))


def test_an_interstitial_may_still_press_other_keys_and_answer():
    make_title(interstitials=(("a", ("keys", ("ESC", "RET")), None, 1),
                              ("b", ("answer",), None, 1)))


STRICT = frozenset({"party_menu", "load_picker", "loaded_menu", "disk_wait", "camp_picker"})


@pytest.mark.parametrize("missing", ["loaded_menu", "disk_wait", "camp_picker"])
def test_a_write_or_insert_after_a_state_that_is_not_strict_is_refused(missing):
    with pytest.raises(drive.RouteError, match="not a strict state"):
        make_title(strict=STRICT - {missing})


def test_a_title_with_no_strict_states_is_refused():
    with pytest.raises(drive.RouteError, match="not a strict state"):
        make_title(strict=frozenset())


def test_a_write_straight_after_the_title_needs_no_strict_state():
    route = (("C", "loaded_menu", "write"),) + ROUTE[5:]
    make_title(route=route, measure_route=route, strict=frozenset({"camp_picker"}))


def test_a_non_strict_state_between_the_keys_is_allowed_when_no_write_or_insert_follows(
        tmp_path, clock):
    # `world` is never strict, and the walk after it is not a write.
    guest, result = _run(tmp_path, clock, guard=MapGuard(
        states=("title", *STATES), on={"world": lambda path: False}))
    assert result["error"] == "" and result["unguarded"] == ["world"]
    assert result["success"] is False and result["completed"] is True
    assert _keys(guest) == "P L A SPACE C NP2 NP8 E S D".split()


def test_a_strict_state_that_never_matches_stops_the_run_before_the_next_key(tmp_path, clock):
    # `disk_wait` is not in Silver Blades' route states, so this fails only if the title's own
    # strict set is the one consulted.
    guest, result = _run(tmp_path, clock, guard=MapGuard(
        states=("title", *STATES), on={"disk_wait": lambda path: False}))
    assert "disk_wait screen was not recognized" in result["error"]
    assert _keys(guest) == "P L A SPACE".split()
    assert result["success"] is False


def test_an_unguarded_state_makes_the_run_a_measuring_one(tmp_path, clock):
    guard = MapGuard(states=tuple(s for s in ("title", *STATES) if s not in ("world", "camp")))
    _, result = _run(tmp_path, clock, guard=guard)
    assert result["error"] == "" and result["completed"] is True
    assert result["unguarded"] == ["world", "camp"] and result["success"] is False
    # Everything else about the run was as good as a passing one.
    assert result["walk"]["d_ok"] and result["menu_save_problems"] == []


class Hooked(TitleGuest):
    """A guest that runs `hooks[key](guest)` after that key is pressed, and can fail a fetch."""

    def __init__(self, clock, hooks=None, fail_get=(), **kw):
        super().__init__(clock, **kw)
        self.hooks, self.fail_get = dict(hooks or {}), tuple(fail_get)

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout)
        if key in self.hooks:
            self.hooks[key](self)

    def get(self, remote, local, timeout=None):
        if any(remote.endswith(f"-{k}.adf") for k in self.fail_get):
            self.calls.append(("get", remote, str(local)))
            raise OSError("no such file on the guest")
        super().get(remote, local, timeout)


def _remote(guest, key):
    return next(r for r in guest.remote if r.endswith(f"-{key}.adf"))


def _touch_remote(key):
    def hook(guest):
        remote = _remote(guest, key)
        disk = AmigaDisk(guest.remote[remote])
        disk.write_file("/SAVE/stray.txt", b"the game wrote here")
        guest.remote[remote] = disk.to_bytes()
    return hook


def test_a_registered_image_that_changes_fails_the_run(tmp_path, clock):
    hook = lambda guest: (tmp_path / "registered.adf").write_bytes(b"changed")  # noqa: E731
    _, result = _run(tmp_path, clock, guest=Hooked(clock, {"E": hook}))
    assert result["registered_unchanged"] == {"reg": False} and result["success"] is False


def test_a_working_copy_that_changes_fails_the_run(tmp_path, clock):
    hook = lambda guest: (tmp_path / "spare.adf").write_bytes(b"changed")  # noqa: E731
    _, result = _run(tmp_path, clock, guest=Hooked(clock, {"E": hook}))
    assert result["working_unchanged"]["spare"] is False and result["success"] is False


def test_a_disk_other_than_the_save_disk_that_changes_fails_the_run(tmp_path, clock):
    _, result = _run(tmp_path, clock, guest=Hooked(clock, {"NP8": _touch_remote("disk3")}))
    assert result["disks_unchanged"]["disk3"] is False and result["success"] is False


def test_a_save_disk_the_game_never_wrote_fails_even_when_the_saves_read_right(
        tmp_path, clock):
    """Readers that report both saves whatever the disk holds leave only the unchanged disk to fail."""
    def read_slot(disk, letter):
        place = {"C": START, "D": dict(START, y=14, facing=geo.SOUTH)}.get(letter)
        if place is None:
            return _read_slot(disk, letter)
        return {"sha256": "0" * 64, "place": place, "names": NAMES}

    guest = TitleGuest(clock)
    guest._write = lambda letter, place: None
    _, result = _run(tmp_path, clock, title=make_title(read_slot=read_slot), guest=guest)
    assert result["disks_unchanged"]["boot"] is True
    assert result["menu_save_problems"] == [] and result["walk"]["d_ok"] is True
    assert result["success"] is False


def test_a_disk_that_could_not_be_fetched_fails_a_measure_run(tmp_path, clock):
    _, result = _run(tmp_path, clock, accept=False, measure=True, guard=MapGuard(states=STATES),
                     guest=Hooked(clock, fail_get=("spare",)))
    assert sorted(result["fetched"]) == ["boot", "disk3"] and "fetch_spare_error" in result
    assert all(result["disks_unchanged"].values()) and result["route_changed"] is True
    assert result["success"] is False


def test_a_disk_that_could_not_be_fetched_fails_an_accept_run(tmp_path, clock):
    _, result = _run(tmp_path, clock, guest=Hooked(clock, fail_get=("spare",)))
    assert "fetch_spare_error" in result and result["success"] is False


def test_a_measure_run_fails_when_a_disk_changed(tmp_path, clock):
    _, result = _run(tmp_path, clock, accept=False, measure=True, guard=MapGuard(states=STATES),
                     guest=Hooked(clock, {"SPACE": _touch_remote("disk3")}))
    assert result["route_changed"] is True and result["error"] == ""
    assert result["disks_unchanged"]["disk3"] is False and result["success"] is False


@pytest.mark.parametrize("kwargs", [
    {"route": (("P", "party_menu"),)}, {"write_keys": ("C",)},
])
def test_a_title_run_refuses_a_route_or_write_keys_of_its_own(tmp_path, clock, kwargs):
    guest = TitleGuest(clock)
    with pytest.raises(drive.RouteError, match="brings its own route and write keys"):
        _run(tmp_path, clock, guest=guest, **kwargs)
    assert guest.calls == []


def test_the_title_limit_bounds_the_wait_for_the_title_screen(tmp_path, clock):
    never = MapGuard(states=("title", *STATES), on={"title": lambda path: False})
    _, accepted = _run(tmp_path, clock, title=make_title(title_limit=20.0), guard=never)
    assert "title screen was not recognized within 20s" in accepted["error"]
    other = tmp_path / "measure"
    other.mkdir()
    _, measured = _run(other, clock, accept=False, measure=True, guard=never,
                       title=make_title(title_limit=20.0),
                       manifest=manifest_for(other))
    assert "title screen was not recognized within 20s" in measured["error"]
    assert measured["success"] is False


def _sleeps_of(tmp_path, clock, title, **kw):
    clock.sleeps.clear()
    _run(tmp_path, clock, title=title, **kw)
    return set(clock.sleeps)


def test_the_titles_minimum_waits_are_used_and_the_callers_win(tmp_path, clock):
    title = make_title(min_waits={"world": 7.0})
    assert 7.0 in _sleeps_of(tmp_path, clock, title)
    other = tmp_path / "override"
    other.mkdir()
    sleeps = _sleeps_of(other, clock, title, min_waits={"world": 9.0},
                        manifest=manifest_for(other))
    assert 9.0 in sleeps and 7.0 not in sleeps


def test_an_issue_that_is_not_all_digits_is_refused():
    for issue in ("", "67x", "../679", "6 9"):
        with pytest.raises(drive.RouteError, match="is not a number"):
            make_title(issue=issue)


@pytest.mark.parametrize("bad", [
    {"spares": ("bad key",)}, {"spares": ("a/b",)}, {"spares": ("x" * 65,)},
    {"spares": ("boot",)},
])
def test_a_disk_key_must_be_distinct_and_lane_safe(bad):
    with pytest.raises(drive.RouteError, match="lane-safe"):
        make_title(**bad)


def test_the_identity_map_is_needed_only_when_the_route_uses_an_identity_state(
        tmp_path, clock):
    def renamed(step):
        key, state, kind = step
        return (key, "menu_two" if state == "loaded_menu" else state, kind)

    route = tuple(renamed(s) for s in ROUTE)
    title = make_title(route=route, measure_route=route, strict=frozenset(
        {"party_menu", "load_picker", "menu_two", "disk_wait", "camp_picker"}))
    guard = MapGuard(states=("title", *STATES, "menu_two"),
                     on={"menu_two": lambda path: True})
    guest = TitleGuest(clock)
    result = drive.run_recon(
        manifest_for(tmp_path), guest=guest, guard=guard, identity=None, title=title,
        holder="wish679-test", audio_proof=_audio_proof(tmp_path), accept=True)
    assert result["error"] == "" and guest.calls
    # The same run, whose route does reach `loaded_menu`, still needs the map.
    other = tmp_path / "needed"
    other.mkdir()
    with pytest.raises(drive.RouteError, match="identity map lacks"):
        drive.run_recon(
            manifest_for(other), guest=TitleGuest(clock), guard=MapGuard(
                states=("title", *STATES)), identity=None, title=make_title(),
            holder="wish679-test", audio_proof=_audio_proof(other), accept=True)


def test_a_deadline_that_a_minimum_wait_cannot_meet_still_stops_fetches_and_releases(
        tmp_path, clock):
    title = make_title(min_waits={"world": 60.0})
    guest, result = _run(tmp_path, clock, title=title, deadline_seconds=100)
    assert "deadline" in result["error"] and result["success"] is False
    names = [c[0] for c in guest.calls if c[0] in ("stop", "get", "release")]
    assert names == ["stop", "get", "get", "get", "release"]
    assert sorted(result["fetched"]) == ["boot", "disk3", "spare"]
    assert result["completed"] is False


@needs_posix_signals
def test_a_terminated_title_run_still_stops_fetches_and_releases(tmp_path, clock):
    def term(guest):
        os.kill(os.getpid(), signal.SIGTERM)

    guest = Hooked(clock, {"E": term})
    with drive.terminating():
        guest, result = _run(tmp_path, clock, guest=guest)
    assert result["lost"].startswith("Terminated") and result["completed"] is False
    assert result["success"] is False
    names = [c[0] for c in guest.calls if c[0] in ("stop", "get", "release")]
    assert names == ["stop", "get", "get", "get", "release"]
    summary = json.loads((tmp_path / "recon1" / "summary.json").read_text())
    assert summary["lost"] == result["lost"]


# A kept letter is never written, so the game's own key may be one when the description says where.
PLAIN = (("E", "camp"),)


def test_a_kept_letter_key_step_without_a_plain_keys_entry_is_refused():
    with pytest.raises(drive.RouteError, match="presses a save or kept slot letter"):
        make_title(kept_letters=("B", "E"))


def test_a_kept_letter_key_step_with_its_plain_keys_entry_is_accepted():
    title = make_title(kept_letters=("B", "E"), plain_keys=PLAIN)
    assert title.plain_keys == PLAIN


def test_a_plain_keys_entry_for_another_state_does_not_let_the_step_through():
    with pytest.raises(drive.RouteError, match="presses a save or kept slot letter"):
        make_title(kept_letters=("B", "E"), plain_keys=(("E", "world"),))


@pytest.mark.parametrize("letter,state", [("C", "loaded_menu"), ("D", "camp")])
def test_the_control_and_after_letters_are_refused_even_when_listed(letter, state):
    with pytest.raises(drive.RouteError, match="not a kept letter"):
        make_title(plain_keys=((letter, state),))
    # A step pressing one of them as a plain key stays refused with the entry present.
    route = _swap(ROUTE, 7, (letter, "camp", "key"))
    with pytest.raises(drive.RouteError, match="presses a save or kept slot letter"):
        make_title(route=route, measure_route=route, kept_letters=("B", "E"),
                   plain_keys=PLAIN)


def test_a_plain_keys_entry_whose_key_is_not_a_kept_letter_is_refused():
    with pytest.raises(drive.RouteError, match="not a kept letter"):
        make_title(plain_keys=(("S", "camp_picker"),))


def test_a_plain_keys_entry_no_step_uses_is_refused():
    with pytest.raises(drive.RouteError, match="pressed by no step in that state"):
        make_title(kept_letters=("B", "E"), plain_keys=(*PLAIN, ("E", "world")))


def test_a_repeated_plain_keys_entry_is_refused():
    with pytest.raises(drive.RouteError, match="repeat an entry"):
        make_title(kept_letters=("B", "E"), plain_keys=(*PLAIN, *PLAIN))


def test_a_run_with_a_plain_kept_e_still_fails_when_slot_e_changed(tmp_path, clock):
    title = make_title(kept_letters=("B", "E"), plain_keys=PLAIN)
    manifest = manifest_for(tmp_path, extra_slot=("E", b"the exit slot"))
    guest, good = _run(tmp_path, clock, title=title, manifest=manifest)
    assert good["success"] is True and "E" in _keys(guest)

    def spoil(guest):
        remote = next(r for r in guest.mounted if r.endswith("-boot.adf"))
        disk = AmigaDisk(guest.remote[remote])
        disk.write_file("/SAVE/savgamE.sav", b"the game rewrote it")
        guest.remote[remote] = disk.to_bytes()

    other = tmp_path / "other"
    other.mkdir()
    _, bad = _run(other, clock, title=title, guest=TitleGuest(clock, spoil=spoil),
                  manifest=manifest_for(other, extra_slot=("E", b"the exit slot")))
    assert bad["kept_unchanged"]["E"] is False and bad["success"] is False


def _with_kept_e(route, **over):
    return make_title(route=route, measure_route=route, kept_letters=("B", "E"),
                      strict=frozenset({*make_title().strict, "camp"}), **over)


def test_a_kept_letter_pressed_on_a_save_picker_is_refused_even_as_a_plain_key():
    route = ROUTE[:-1] + (("B", "camp", "key"),) + ROUTE[-1:]  # B right after camp_picker
    with pytest.raises(drive.RouteError, match="kept letter B as a plain key on 'camp_picker'"):
        _with_kept_e(route, plain_keys=(("E", "camp"), ("B", "camp")))


def test_a_plain_key_on_a_picker_is_refused_even_when_no_write_step_presses_there():
    route = _swap(ROUTE, 2, ("E", "loaded_menu", "key"))  # pressed on load_picker
    with pytest.raises(drive.RouteError, match="on 'load_picker', where a picker screen"):
        _with_kept_e(route, plain_keys=(("E", "loaded_menu"), ("E", "camp")))


def test_a_plain_key_on_the_screen_a_write_step_presses_on_is_refused():
    # C is pressed on `world` once the insert's screen is followed by a world step.
    route = _swap(ROUTE, INSERT_AT, ((1, "disk3", "SPACE"), "world", "insert"))
    with pytest.raises(drive.RouteError, match="on 'world', where a route step presses a save"):
        make_title(route=route, measure_route=route, kept_letters=("B", "E"),
                   strict=frozenset({*make_title().strict, "world"}), plain_keys=PLAIN)


def test_the_same_plain_key_on_an_ordinary_screen_is_accepted_in_either_case():
    assert _with_kept_e(ROUTE, plain_keys=PLAIN).plain_keys == PLAIN
    route = _swap(ROUTE, 7, ("e", "camp", "key"))
    assert _with_kept_e(route, plain_keys=PLAIN).plain_keys == PLAIN


@pytest.mark.parametrize("entry", [("E",), ("E", 1), "E camp", ["E", "camp"]])
def test_a_plain_keys_entry_that_is_not_a_pair_of_strings_is_refused(entry):
    with pytest.raises(drive.RouteError, match=r"must be \(key, state\) pairs"):
        make_title(kept_letters=("B", "E"), plain_keys=(entry,))


def test_a_first_step_plain_key_is_judged_on_the_title_screen():
    writes_on_title = (("C", "loaded_menu", "write"), ("S", "camp_picker", "key"),
                       ("D", "camp", "write"))
    first = (("E", "camp", "key"), ("N", "world", "key"))
    with pytest.raises(drive.RouteError, match="on 'title', where a route step presses a save"):
        make_title(route=writes_on_title, measure_route=first, kept_letters=("B", "E"),
                   plain_keys=PLAIN)
    # Nothing writes on the title screen, and the last step's picker state is not where E goes out.
    picker_last = (("E", "camp", "key"), ("S", "camp_picker", "key"))
    assert make_title(route=ROUTE, measure_route=picker_last, kept_letters=("B", "E"),
                      plain_keys=PLAIN).plain_keys == PLAIN


def test_a_picker_screen_is_recognised_whatever_its_capitals():
    route = (("P", "party_menu", "key"), ("S", "Camp_Picker", "key"), ("E", "camp", "key"))
    with pytest.raises(drive.RouteError, match="on 'Camp_Picker', where a picker screen"):
        make_title(route=route, measure_route=route, kept_letters=("B", "E"), plain_keys=PLAIN)


class _WorldIdentity:
    """An identity map with a rule for `world` as well as the two the driver requires."""

    def __init__(self, fail=()):
        self.fail = set(fail)

    def __contains__(self, state):
        return state in ("sheet", "loaded_menu", "world")

    def __call__(self, state, path):
        return state not in self.fail


def test_a_world_screen_showing_another_party_stops_the_run_with_a_readable_error(
        tmp_path, clock):
    _, result = _run(tmp_path, clock, identity=_WorldIdentity(fail={"world"}))
    assert result["success"] is False
    assert result["error"] == ("RouteError: world shows a party other than the prepared party")
    assert result["lost"] is None  # a refusal, not a run that was lost to a KeyError


def test_the_named_identity_messages_are_unchanged(tmp_path, clock):
    assert drive.IDENTITY_MESSAGES == {"sheet": "sheet shows another member",
                                       "loaded_menu": "loaded_menu shows another party"}
    _, result = _run(tmp_path, clock, identity=_IdentityMap(fail={"loaded_menu"}))
    assert result["error"] == "RouteError: loaded_menu shows another party"


DF0_ROUTE = (
    ("P", "party_menu", "key"), ("A", "disk_ask", "key"),
    ((0, "spare", "SPACE"), "loaded_menu", "insert"), ("C", "loaded_menu", "write"),
    ("NP2", "world", "turn"), ("NP8", "world", "move"), ("E", "camp", "key"),
    ("S", "camp_picker", "key"), ("D", "camp", "write"),
)
DF0_STRICT = frozenset({"party_menu", "disk_ask", "loaded_menu", "camp_picker"})


def _df0_title(route=DF0_ROUTE, **over):
    fields = dict(disk_prompts=frozenset({"disk_ask"}), strict=DF0_STRICT,
                  route=route, measure_route=DF0_ROUTE)
    fields.update(over)
    return make_title(**fields)


def test_a_df0_insert_after_a_strict_disk_prompt_is_accepted():
    _df0_title()


def test_a_df0_insert_is_refused_as_the_first_step():
    route = (((0, "spare", "SPACE"), "loaded_menu", "insert"), *DF0_ROUTE[3:])
    with pytest.raises(drive.RouteError, match="DF0 insert.*first"):
        _df0_title(route)


def test_a_df0_insert_after_a_state_that_is_not_a_disk_prompt_is_refused():
    with pytest.raises(drive.RouteError, match="DF0 insert.*disk prompt"):
        _df0_title(disk_prompts=frozenset())
    with pytest.raises(drive.RouteError, match="DF0 insert.*disk prompt"):
        _df0_title(disk_prompts=frozenset({"party_menu"}))


def test_a_df0_disk_prompt_must_be_strict():
    with pytest.raises(drive.RouteError, match="strict"):
        _df0_title(strict=DF0_STRICT - {"disk_ask"})


def test_a_df0_insert_of_the_disk_already_in_df0_is_refused():
    route = _swap(DF0_ROUTE, 2, ((0, "boot", "SPACE"), "loaded_menu", "insert"))
    with pytest.raises(drive.RouteError, match="already in DF0"):
        _df0_title(route)


@pytest.mark.parametrize("drive_number", [True, 2])
def test_a_df0_prompt_does_not_widen_the_other_drives(drive_number):
    route = _swap(DF0_ROUTE, 2, ((drive_number, "spare", "SPACE"), "loaded_menu", "insert"))
    with pytest.raises(drive.RouteError, match="only DF1"):
        _df0_title(route)


def test_an_interstitial_insert_into_df0_is_refused_even_with_disk_prompts():
    rows = (("disk_request", ("insert", 0, "spare", "SPACE"), None, 1),)
    with pytest.raises(drive.RouteError, match="only DF1"):
        _df0_title(interstitials=rows)


def test_a_df0_insert_run_stops_before_its_key_when_the_insert_fails(tmp_path, clock):
    class Refused(TitleGuest):
        def insert(self, holder, drive_number, remote, timeout=None, sha256=None):
            self.calls.append(("insert", drive_number, remote))
            exc = RuntimeError("drive 0 did not read it back")
            exc.receipt = {"status": "refused"}
            raise exc

    guest = Refused(clock)
    guard = MapGuard(states=("title", *STATES, "disk_ask"))
    _, result = _run(tmp_path, clock, guest=guest, guard=guard, title=_df0_title())
    assert result["success"] is False
    keys = [c[2] for c in guest.calls if c[0] == "press"]
    assert keys == ["P", "A"]
    event = next(e for e in result["events"] if "insert" in e)
    assert event["drive"] == 0 and event["insert"] == "spare"
    assert "did not read it back" in event["error"] and event["receipt"] == {"status": "refused"}
