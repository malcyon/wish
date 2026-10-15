"""The Curse ADD CHARACTER driver: the host copy, the guarded route and its fail-closed paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import signal
import threading

import pytest

from automap import gamedisks
from goldbox import amiga_adf
from tools.amiga import curseadd
from tools.amiga.winuaesession import RouteError
from tools.registry import specimens


def _record(name: str, control: int = 0, status: int = 0, kind: int = 0) -> bytes:
    raw = bytearray(curseadd.AMIGA_POR_RECORD_SIZE)
    raw[:len(name)] = name.encode("latin1")
    raw[0x85], raw[0x10E], raw[0xA1], raw[0x11D] = control, status, kind, 9
    return bytes(raw)


def _pool_disk(files: dict[str, bytes], drawer: str = "") -> amiga_adf.AmigaDisk:
    """A Pool save disk; REMOVE writes its files at the root, so that is the default."""
    disk = amiga_adf.AmigaDisk.blank("POOLSAVE")
    disk.make_dir("save")
    for name, data in files.items():
        disk.write_file(f"{drawer}/{name}" if drawer else name, data)
    return disk


def _curse_disk(files: tuple[str, ...] = ("savgamA.dat",)) -> amiga_adf.AmigaDisk:
    disk = amiga_adf.AmigaDisk.blank("CurseA")
    disk.make_dir("SAVE")
    for name in files:
        disk.write_file(f"SAVE/{name}", b"synthetic " + name.encode())
    return disk


def test_stem_is_the_name_pool_remove_writes():
    assert curseadd.cha_stem("Princess Fatima") == "PRINCESSFATIMA"
    assert curseadd.cha_stem("a.b*c,d?e/f:g;h|i") == "ABCDEFGHI"
    assert curseadd.cha_stem("BRUTUS") == "BRUTUS"


def test_copy_puts_cha_and_spc_unchanged_and_leaves_the_itm():
    cha, spc = _record("ROSALIND"), bytes(range(10))
    source = _pool_disk({"ROSALIND.cha": cha, "ROSALIND.spc": spc, "ROSALIND.itm": b"items"})
    before = source.to_bytes()
    target = _curse_disk()
    rows = curseadd.copy_characters(source, target, ["Rosalind"])
    assert target.read_file("SAVE/ROSALIND.cha") == cha
    assert target.read_file("SAVE/ROSALIND.spc") == spc
    with pytest.raises(amiga_adf.AmigaDiskError):
        target.lookup("SAVE/ROSALIND.itm")
    assert target.verify() == []
    assert source.to_bytes() == before
    assert rows[0]["stem"] == "ROSALIND"
    assert rows[0]["cha"]["sha256"] == hashlib.sha256(cha).hexdigest()
    assert rows[0]["spc"]["equal"] is True


def test_name_key_reads_pool_and_curse_spellings_alike():
    assert curseadd.name_key("LADY\xffKATHERINE") == "LADYKATHERINE"
    assert curseadd.name_key("Lady Katherine") == "LADYKATHERINE"
    assert curseadd.name_key("J.R. Smith") == curseadd.name_key("JRSMITH") == "JRSMITH"
    # The writer upper-cases a-z only; any other letter keeps its byte.
    assert curseadd.cha_stem("abc\xe9\xff") == "ABC\xe9\xff"


def test_copy_finds_a_multi_word_player_by_the_file_remove_wrote():
    stem = "LADY\xffKATHERINE"
    cha = _record(stem)
    target = _curse_disk()
    rows = curseadd.copy_characters(
        _pool_disk({f"{stem}.cha": cha, f"{stem}.spc": bytes(10)}), target, ["Lady Katherine"])
    assert rows[0]["stem"] == stem and rows[0]["key"] == "LADYKATHERINE"
    assert target.read_file(f"SAVE/{stem}.cha") == cha
    assert target.read_file(f"SAVE/{stem}.spc") == bytes(10)


def test_copy_finds_a_name_remove_cleaned():
    target = _curse_disk()
    rows = curseadd.copy_characters(_pool_disk({"JRSMITH.cha": _record("JRSMITH", 0xB2)}),
                                    target, ["J.R. Smith"])
    assert rows[0]["stem"] == "JRSMITH"
    assert target.read_file("SAVE/JRSMITH.cha")[0x85] == 0xB2


@pytest.mark.parametrize("drawer", [None, "", "/"])
def test_copy_finds_remove_s_lower_case_files_at_the_disk_root(drawer):
    """Amiga Pool's REMOVE wrote `/brutus.cha`, `.itm` and `.spc` at the save disk's root."""
    cha, spc = _record("BRUTUS", 0xB3, 1, 4), bytes(range(20))
    source = _pool_disk({"brutus.cha": cha, "brutus.itm": b"items", "brutus.spc": spc})
    target = _curse_disk()
    kwargs = {} if drawer is None else {"source_drawer": drawer}
    rows = curseadd.copy_characters(source, target, ["BRUTUS"], **kwargs)
    assert rows[0]["stem"] == "brutus" and rows[0]["key"] == "BRUTUS"
    assert rows[0]["cha"]["source"] == "/brutus.cha"
    assert target.read_file("SAVE/brutus.cha") == cha
    assert target.read_file("SAVE/brutus.spc") == spc
    names = [e.name for e in target.entries(target.lookup("SAVE").block)]
    assert "brutus.cha" in names and "brutus.spc" in names
    assert not any(n.lower().endswith(".itm") for n in names)


def test_copy_still_reads_a_named_drawer():
    target = _curse_disk()
    source = _pool_disk({"ROSALIND.cha": _record("ROSALIND")}, drawer="save")
    rows = curseadd.copy_characters(source, target, ["ROSALIND"], source_drawer="save")
    assert rows[0]["cha"]["source"] == "save/ROSALIND.cha"
    with pytest.raises(RouteError, match="0 .cha files"):
        curseadd.copy_characters(source, _curse_disk(), ["ROSALIND"])


def test_copy_records_a_character_with_no_effects_file():
    target = _curse_disk()
    rows = curseadd.copy_characters(_pool_disk({"GEN.cha": _record("GEN", 0xB2)}), target, ["GEN"])
    assert rows[0]["spc"] is None
    assert target.read_file("SAVE/GEN.cha")[0x85] == 0xB2


@pytest.mark.parametrize("case", ["listed_cha", "listed_sav", "wrong_size", "other_name",
                                  "missing", "duplicate_stem", "two_files", "none"])
def test_copy_stops_before_writing(case):
    files = {"ROSALIND.cha": _record("ROSALIND")}
    names, present = ["ROSALIND"], ("savgamA.dat",)
    if case == "listed_cha":
        present += ("OTHER.cha",)
    elif case == "listed_sav":
        present += ("CHRDATA1.sav",)
    elif case == "wrong_size":
        files["ROSALIND.cha"] = b"short"
    elif case == "other_name":
        files["ROSALIND.cha"] = _record("SOMEBODY")
    elif case == "missing":
        names = ["NOBODY"]
    elif case == "duplicate_stem":
        names = ["ROSALIND", "rosalind"]
    elif case == "two_files":
        files["ROSA.LIND.cha"] = _record("ROSALIND")
    elif case == "none":
        names = []
    target = _curse_disk(present)
    before = target.to_bytes()
    with pytest.raises(RouteError):
        curseadd.copy_characters(_pool_disk(files), target, names)
    if case not in ("wrong_size", "other_name", "two_files"):
        assert target.to_bytes() == before


def test_guard_rules_add_the_add_screens_to_the_curse_map():
    rules = curseadd.guard_rules()
    for state in ("add_from", "add_picker", "saving", "loaded_menu", "title", "sheet"):
        assert state in rules
    assert rules["add_picker"] == curseadd.ADD_GUARDS["add_picker"]
    assert set(curseadd.KNOWN) <= set(rules)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.5)


class FakeGuest:
    """Shows each scripted screen for one grab and records every key; the last screen stays."""

    def __init__(self, script, clock):
        self.script, self.clock = list(script), clock
        self.current = None
        self.keys: list[str] = []
        #: The screen the last grab showed when each key went out.
        self.pressed_on: list[str | None] = []

    def grab(self, label, raw, crop, timeout):
        self.current = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        self.clock.now += 1
        return True

    def press(self, holder, key, timeout):
        self.keys.append(key)
        self.pressed_on.append(self.current)


class FakeGuards:
    def __init__(self, guest):
        self.guest = guest

    def __contains__(self, state):
        return state in curseadd.KNOWN

    def __call__(self, state, crop):
        return state == self.guest.current


#: Keys that would act on the party or leave the game if they reached these screens.
FORBIDDEN = ({("loaded_menu", key) for key in "BCDEHMRT"} | {("sheet", key) for key in "DT"}
             | {("title", key) for key in "CEDM"} | {("add_from", "C"), ("add_from", "H")})


def _keys_allowed(screens, guest):
    pressed = [event for event in screens.events if "key" in event]
    assert [event["key"] for event in pressed] == guest.keys
    for event in pressed:
        assert event["key"] in curseadd.ALLOWED_KEYS[event["from"]], event
        assert (event["from"], event["key"]) not in FORBIDDEN, event
    assert set(guest.keys) <= set().union(*curseadd.ALLOWED_KEYS.values())
    for key, shown, event in zip(guest.keys, guest.pressed_on, pressed):
        if (event["from"], key) == ("add_picker", "E"):
            assert shown == "add_picker", "E went out without the ADD list on the last grab"


def _screens(tmp_path, script, budget=10_000):
    clock = Clock()
    guest = FakeGuest(script, clock)
    screens = curseadd.Screens(guest, "holder", tmp_path / "shots", FakeGuards(guest),
                               budget, clock=clock, sleep=clock.sleep)
    return screens, guest


def test_wait_stops_on_another_known_screen(tmp_path):
    screens, _ = _screens(tmp_path, ["sheet"])
    with pytest.raises(RouteError, match="saw"):
        screens.wait(("loaded_menu",), 60)


def test_wait_polls_past_the_screen_the_key_went_out_on(tmp_path):
    screens, _ = _screens(tmp_path, ["save_picker", "saving", None, "loaded_menu"])
    assert screens.wait(("loaded_menu",), 60, past=("save_picker", "saving")) == "loaded_menu"


def test_wait_times_out_on_an_unknown_screen(tmp_path):
    screens, _ = _screens(tmp_path, [None])
    with pytest.raises(RouteError, match="did not show"):
        screens.wait(("loaded_menu",), 30)


def test_boot_presses_escape_once_per_screen_until_the_party_menu(tmp_path):
    screens, guest = _screens(tmp_path, [None, "intro", "intro", "front_end", "title"])
    screens.to_party_menu(300)
    assert guest.keys == ["ESC", "ESC"]
    _keys_allowed(screens, guest)


def test_boot_stops_after_the_escape_cap(tmp_path):
    screens, guest = _screens(tmp_path, ["front_end"])
    with pytest.raises(RouteError, match="ESCs"):
        screens.to_party_menu(3000)
    assert guest.keys == ["ESC"] * curseadd.BOOT_ESCAPES
    _keys_allowed(screens, guest)


@pytest.mark.parametrize("on, key", [("loaded_menu", "D"), ("loaded_menu", "E"),
                                     ("sheet", "D"), ("title", "Q"), ("save_picker", "K"),
                                     ("nowhere", "A")])
def test_a_key_outside_the_allowlist_is_never_sent(tmp_path, on, key):
    screens, guest = _screens(tmp_path, [None])
    with pytest.raises(RouteError, match="not a key"):
        screens.press(key, on)
    assert guest.keys == [] and screens.events == []


def _manifest(tmp_path, stems, names=("GALAIN", "HOLLAND")):
    disk = _curse_disk()
    for stem in stems:
        disk.write_file(f"SAVE/{stem}.cha", _record(stem, 0xB2 if stem == "GEN" else 0))
    save = tmp_path / "save.adf"
    disk.save(save)
    return {"title": "curse", "disks": {"save": {"path": str(save)}},
            "add": {"load": "A", "save": "D", "load_names": list(names),
                    "copies": [{"stem": stem, "key": curseadd.name_key(stem),
                                "cha": {"target": f"SAVE/{stem}.cha"}} for stem in stems]}}


def _live(*names):
    return [{"name": n, "control": 0xB2 if n == "GEN" else 0, "status": 0, "type": 0}
            for n in names]


#: Boot, load, one add, the picker shown twice before E, view and save.
ROUTE_ONE = [None, "intro", "front_end", "title", "load_picker", None, "loaded_menu",
             "add_from", "add_picker", "add_picker", "add_picker", "loaded_menu", "sheet",
             "loaded_menu", "save_picker", "saving", "loaded_menu", "loaded_menu"]


def test_drive_adds_views_and_saves_one_character(tmp_path):
    screens, guest = _screens(tmp_path, ROUTE_ONE)
    manifest = _manifest(tmp_path, ["ROSALIND"])
    found = curseadd.drive(screens, manifest, "holder",
                           lambda holder: _live("GALAIN", "HOLLAND", "ROSALIND"))
    assert guest.keys == ["ESC", "ESC", "L", "A", "A", "P", "A", "E", "V", "E", "S", "D"]
    assert found["live_fields"]["ROSALIND"]["control"] == {"cha": 0, "live": 0, "equal": True}
    _keys_allowed(screens, guest)


def test_drive_compares_multi_word_names_by_their_cleaned_form(tmp_path):
    screens, guest = _screens(tmp_path, ROUTE_ONE)
    manifest = _manifest(tmp_path, ["LADY\xffKATHERINE"], names=("SIR\xffBOB",))
    found = curseadd.drive(screens, manifest, "holder",
                           lambda holder: _live("SIR BOB", "LADY KATHERINE"))
    assert found["live_fields"]["LADY KATHERINE"]["type"]["equal"] is True
    assert guest.keys[-2:] == ["S", "D"]
    _keys_allowed(screens, guest)


def test_drive_adds_two_and_takes_the_picker_closing_itself(tmp_path):
    script = [None, "title", "load_picker", "loaded_menu", "add_from", "add_picker",
              "add_picker", "loaded_menu", "sheet", "loaded_menu", "sheet", "loaded_menu",
              "save_picker", "loaded_menu", "loaded_menu"]
    screens, guest = _screens(tmp_path, script)
    manifest = _manifest(tmp_path, ["ROSALIND", "GEN"])
    found = curseadd.drive(screens, manifest, "holder",
                           lambda holder: _live("GALAIN", "HOLLAND", "GEN", "ROSALIND"))
    assert guest.keys == ["L", "A", "A", "P", "A", "NP1", "A", "V", "E", "NP7", "V", "E",
                          "S", "D"]
    assert found["live_fields"]["GEN"]["control"]["live"] == 0xB2
    _keys_allowed(screens, guest)


def test_drive_does_not_press_exit_on_a_picker_that_closed_late(tmp_path):
    script = [None, "title", "load_picker", "loaded_menu", "add_from", "add_picker",
              "add_picker", "loaded_menu", "sheet", "loaded_menu", "save_picker",
              "loaded_menu", "loaded_menu"]
    screens, guest = _screens(tmp_path, script)
    curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND"]), "holder",
                   lambda holder: _live("GALAIN", "HOLLAND", "ROSALIND"))
    assert guest.keys == ["L", "A", "A", "P", "A", "V", "E", "S", "D"]
    _keys_allowed(screens, guest)


@pytest.mark.parametrize("problem", ["raises", "hangs"])
def test_drive_stops_before_saving_when_the_party_does_not_read(tmp_path, monkeypatch, problem):
    screens, guest = _screens(tmp_path, ROUTE_ONE)
    monkeypatch.setattr(curseadd, "READ_LIMIT", 0.2)

    never = threading.Event()

    def reader(holder):
        if problem == "raises":
            raise ValueError("the party list does not read")
        never.wait()

    try:
        with pytest.raises(RouteError, match="party"):
            curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND"]), "holder", reader)
    finally:
        never.set()
    assert "S" not in guest.keys
    _keys_allowed(screens, guest)


def test_the_party_read_bound_needs_no_unix_signal(tmp_path, monkeypatch):
    """Windows has no SIGALRM or interval timer; the bound must not reach for either."""
    for name in ("SIGALRM", "setitimer", "ITIMER_REAL", "alarm"):
        monkeypatch.delattr(signal, name, raising=False)
    screens, guest = _screens(tmp_path, ROUTE_ONE)
    curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND"]), "holder",
                   lambda holder: _live("GALAIN", "HOLLAND", "ROSALIND"))
    assert guest.keys[-2:] == ["S", "D"]
    assert curseadd.bounded(lambda holder: holder * 2, "ab", 5) == "abab"


def test_drive_stops_when_the_picker_closes_early(tmp_path):
    script = [None, "title", "load_picker", "loaded_menu", "add_from", "add_picker",
              "loaded_menu"]
    screens, guest = _screens(tmp_path, script)
    with pytest.raises(RouteError, match="closed after 1 of 2"):
        curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND", "GEN"]), "holder",
                       lambda holder: [])
    assert "S" not in guest.keys
    _keys_allowed(screens, guest)


def test_drive_stops_before_saving_when_the_live_party_differs(tmp_path):
    screens, guest = _screens(tmp_path, ROUTE_ONE)
    with pytest.raises(RouteError, match="party after ADD"):
        curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND"]), "holder",
                       lambda h: _live("GALAIN", "OTHER"))
    assert "S" not in guest.keys
    _keys_allowed(screens, guest)


def _staged(tmp_path, stems=("ROSALIND",)):
    manifest = _manifest(tmp_path, list(stems))
    diskb = tmp_path / "diskb.adf"
    diskb.write_bytes(b"synthetic disk b")
    source = tmp_path / "pool.adf"
    _pool_disk({}).save(source)
    for key, path in (("save", pathlib.Path(manifest["disks"]["save"]["path"])), ("diskb", diskb)):
        manifest["disks"][key] = {"path": str(path),
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest["registered"] = {}
    manifest["add"]["source"] = {"path": str(source),
                                 "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    path = tmp_path / "prepare.json"
    path.write_text(json.dumps(manifest))
    return path


class LaneGuest:
    def __init__(self):
        self.calls = []

    def _run(self, *args, timeout):
        self.calls.append(args)
        return 'text {"vm": "WIN11-DEV"}'

    @staticmethod
    def silence(proof):
        return True


def _args(tmp_path, manifest):
    return argparse.Namespace(manifest=manifest, holder="holder", out=tmp_path / "run",
                              budget=600, wait_lane=0)


@pytest.mark.parametrize("problem", ["out_exists", "not_staged", "hash", "slot_taken",
                                     "bad_letter", "same_letter", "key_letter", "no_copies"])
def test_run_stops_before_the_guest(tmp_path, monkeypatch, problem):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(curseadd, "slot_letters", lambda disk: ["A", "B", "C"])
    if problem == "out_exists":
        (tmp_path / "run").mkdir()
    elif problem == "not_staged":
        value = json.loads(manifest.read_text())
        del value["add"]
        manifest.write_text(json.dumps(value))
    elif problem == "hash":
        (tmp_path / "diskb.adf").write_bytes(b"changed")
    elif problem == "slot_taken":
        monkeypatch.setattr(curseadd, "slot_letters", lambda disk: ["A", "D"])
    else:
        value = json.loads(manifest.read_text())
        if problem == "no_copies":
            value["add"]["copies"] = []
        else:
            value["add"]["save"] = {"bad_letter": "K", "same_letter": "A",
                                    "key_letter": "ESC"}[problem]
        manifest.write_text(json.dumps(value))
    guest = LaneGuest()
    with pytest.raises(RouteError):
        curseadd.run(_args(tmp_path, manifest), guest=guest, guards=object(),
                     boot=pytest.fail, halt=pytest.fail)
    assert guest.calls == []


def test_run_halts_and_fails_when_the_route_stops(tmp_path, monkeypatch):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(curseadd, "slot_letters", lambda disk: ["A"])
    halted = []

    def drive(screens, value, holder, reader):
        raise RouteError("expected add_picker, saw ['sheet']")

    monkeypatch.setattr(curseadd, "drive", drive)
    with pytest.raises(RouteError, match="saw"):
        curseadd.run(_args(tmp_path, manifest), guest=LaneGuest(), guards=object(),
                     boot=lambda *a, **k: {"claim": "ok"},
                     halt=lambda *a, **k: halted.append(k) or {"fetched": {}})
    receipt = json.loads((tmp_path / "run" / "receipt.json").read_text())
    assert halted and receipt["success"] is False
    assert "read_back" not in receipt
    assert receipt["source_hashes"] == "unchanged"


def test_run_does_not_halt_a_lane_it_never_booted(tmp_path, monkeypatch):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(curseadd, "slot_letters", lambda disk: ["A"])

    def boot(*args, **kwargs):
        raise RouteError("no lane within 0s")

    with pytest.raises(RouteError, match="no lane"):
        curseadd.run(_args(tmp_path, manifest), guest=LaneGuest(), guards=object(),
                     boot=boot, halt=pytest.fail)


@pytest.mark.parametrize("problems", [[], ["ROSALIND control"]])
def test_run_succeeds_only_on_a_clean_read_back(tmp_path, monkeypatch, problems):
    manifest = _staged(tmp_path)
    monkeypatch.setattr(curseadd, "slot_letters", lambda disk: ["A"])
    monkeypatch.setattr(curseadd, "drive", lambda *a: {"live": []})
    fetched = tmp_path / "fetched-save.adf"
    fetched.write_bytes(b"fetched")
    monkeypatch.setattr(curseadd, "read_back", lambda path, value: {"path": str(path)})
    monkeypatch.setattr(curseadd, "verdict", lambda found, value: list(problems))
    run = lambda: curseadd.run(  # noqa: E731
        _args(tmp_path, manifest), guest=LaneGuest(), guards=object(),
        boot=lambda *a, **k: {"claim": "ok"},
        halt=lambda *a, **k: {"fetched": {"save": {"path": str(fetched)}}})
    if problems:
        with pytest.raises(RouteError, match="control"):
            run()
    else:
        assert run()["read_back"] == {"path": str(fetched)}


def test_verdict_names_a_changed_byte_and_a_missing_member():
    manifest = {"add": {"load_names": ["GALAIN"],
                        "copies": [{"stem": "GEN"}, {"stem": "ROSALIND"}]}}
    found = {"verify": [], "kept": ["GALAIN"], "names": ["GALAIN", "GEN"], "members": {
        "GEN": {"seated": 1, "fields": {
            "control": {"cha": 0xB2, "curse": 0, "equal": False},
            "status": {"cha": 0, "curse": 0, "equal": True},
            "type": {"cha": 0, "curse": 0, "equal": True}}},
        "ROSALIND": {"seated": 0}}}
    problems = curseadd.verdict(found, manifest)
    assert any("GEN control" in p for p in problems)
    assert any("ROSALIND" in p for p in problems)


def test_verdict_needs_every_staged_character_read_back():
    manifest = {"add": {"load_names": ["GALAIN"], "copies": [{"stem": "ROSALIND"}]}}
    found = {"verify": [], "kept": ["GALAIN"], "names": ["GALAIN"], "members": {}}
    assert any("ROSALIND" in p for p in curseadd.verdict(found, manifest))
    manifest["add"]["copies"] = []
    assert curseadd.verdict(found, manifest) != []


def test_stage_that_stops_leaves_no_folder(tmp_path, monkeypatch):
    save, diskb = tmp_path / "save.adf", tmp_path / "diskb.adf"
    _curse_disk(("savgamA.dat", "OTHER.cha")).save(save)
    diskb.write_bytes(b"synthetic disk b")
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps({"title": "curse", "registered": {}, "disks": {
        "save": {"path": str(save), "sha256": digest(save)},
        "diskb": {"path": str(diskb), "sha256": digest(diskb)}}}))
    source = tmp_path / "pool.adf"
    _pool_disk({"ROSALIND.cha": _record("ROSALIND")}).save(source)
    monkeypatch.setattr(curseadd, "slot_letters", lambda disk: ["A"])
    monkeypatch.setattr(curseadd, "_slot_members", lambda disk, letter: [])
    with pytest.raises(RouteError, match="already lists"):
        curseadd.stage(prep, source, ["ROSALIND"], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def _registered_inputs():
    specimen = specimens.tree_root().joinpath(*route_curse_specimen())
    found = []
    for root in gamedisks.candidates("amiga"):
        if root.exists():
            found += sorted(root.rglob("CurseOfTheAzureBondsSaveDisk].adf"))
    if not specimen.is_file() or not found:
        pytest.skip("the Curse specimen or the Curse save disk is not on this machine")
    return specimen, found[0]


def route_curse_specimen():
    return curseadd.route_curse.CURSE_SPECIMEN


def test_stage_puts_a_registered_pool_character_beside_curse_slot_a(tmp_path):
    specimen, source = _registered_inputs()
    save, diskb = tmp_path / "prep-save.adf", tmp_path / "prep-diskb.adf"
    save.write_bytes(specimen.read_bytes())
    diskb.write_bytes(b"synthetic disk b")
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps({
        "title": "curse",
        "disks": {"save": {"path": str(save), "sha256": digest(save)},
                  "diskb": {"path": str(diskb), "sha256": digest(diskb)}},
        "registered": {"specimen": {"path": str(specimen), "sha256": digest(specimen)}}}))
    source_hash = digest(source)
    path = curseadd.stage(prep, source, ["ROSALIND", "GENHEERIS"], tmp_path / "out",
                          source_drawer="save")
    staged = json.loads(path.read_text())
    assert staged["add"]["load_names"] == ["GALAIN", "HOLLAND", "IILANDA", "SUNDRA"]
    assert [row["stem"] for row in staged["add"]["copies"]] == ["ROSALIND", "GENHEERIS"]
    disk = amiga_adf.AmigaDisk.open(staged["disks"]["save"]["path"])
    assert disk.read_file("SAVE/GENHEERIS.cha")[0x85] == 0xB2
    assert staged["add"]["copies"][1]["spc"] is None
    assert disk.verify() == []
    assert digest(source) == source_hash and digest(save) == staged["prepared_from"]["save_sha256"]
    with pytest.raises(RouteError, match="already exists"):
        curseadd.stage(prep, source, ["ROSALIND"], tmp_path / "out", source_drawer="save")
    with pytest.raises(RouteError, match="player members"):
        curseadd.stage(prep, source, ["ROSALIND", "CONJURER", "ADDERLY"], tmp_path / "out2",
                       source_drawer="save",
                       load="A")


class FramedGuest(FakeGuest):
    """Shows the unknown screen (the credits) with a crop that `frame(now)` names, then the title."""

    def __init__(self, clock, frame, title_at=None, fails=lambda n: False):
        super().__init__([None], clock)
        self.frame, self.title_at, self.fails, self.grabs = frame, title_at, fails, 0

    def grab(self, label, raw, crop, timeout):
        self.clock.now += 1
        self.grabs += 1
        if self.fails(self.grabs):
            return False
        shown = self.title_at is not None and self.clock.now >= self.title_at
        self.current = "title" if shown else None
        crop.write_bytes(f"frame {self.frame(self.clock.now)}".encode())
        return True


def _framed(tmp_path, frame, title_at=None, fails=lambda n: False):
    clock = Clock()
    guest = FramedGuest(clock, frame, title_at, fails)
    return curseadd.Screens(guest, "holder", tmp_path / "shots", FakeGuards(guest), 10_000,
                            clock=clock, sleep=clock.sleep), clock


def test_a_slow_boot_that_keeps_drawing_reaches_the_party_menu(tmp_path):
    """A loaded host pages through the credits for 400 s, which the old 300 s wait cut off."""
    screens, clock = _framed(tmp_path, lambda now: int(now // 20), title_at=400)
    screens.to_party_menu()
    assert clock.now >= 400
    assert screens.events[-1]["screen"] == "title"


def test_a_frozen_boot_frame_stops_the_wait_after_the_idle_span(tmp_path):
    screens, clock = _framed(tmp_path, lambda now: 0)
    with pytest.raises(RouteError, match="unchanged for 150s"):
        screens.to_party_menu()
    assert curseadd.BOOT_IDLE <= clock.now < curseadd.BOOT_IDLE + 10


def test_flaky_grabs_between_frozen_frames_do_not_reset_the_idle_span(tmp_path):
    """A failed grab is no new frame, so alternating failures cannot keep a frozen boot alive."""
    screens, clock = _framed(tmp_path, lambda now: 0, fails=lambda n: n % 2 == 0)
    with pytest.raises(RouteError, match="unchanged for 150s"):
        screens.to_party_menu()
    assert clock.now < curseadd.BOOT_IDLE + 20


def test_a_boot_that_never_stops_changing_stops_at_the_ceiling(tmp_path):
    screens, clock = _framed(tmp_path, lambda now: int(now))
    with pytest.raises(RouteError, match="did not show within 900s"):
        screens.to_party_menu()
    assert curseadd.BOOT_CEILING <= clock.now < curseadd.BOOT_CEILING + 10


def test_a_party_read_that_answers_at_70_seconds_is_within_the_limit(tmp_path):
    """The read runs on a thread, so the bound is its argument: it must allow a 70 s answer."""
    screens, _ = _screens(tmp_path, [None])
    assert screens.left(curseadd.READ_LIMIT) >= 70
    assert curseadd.bounded(lambda holder: _live("GALAIN"), "h",
                            screens.left(curseadd.READ_LIMIT)) == _live("GALAIN")


def test_the_live_read_shares_its_pipe_call_list_with_the_receipt(monkeypatch):
    from automap import amiga, amigaparty

    class Pipe:
        def __init__(self, holder):
            self.call_seconds = []

    class Member:
        name, raw = "GALAIN", bytes(0x200)

    made = []
    monkeypatch.setattr(amiga, "WinuaePipe", lambda holder: made.append(Pipe(holder)) or made[0])
    monkeypatch.setattr(amiga, "AmigaTarget",
                        lambda pipe, machine: type("T", (), {"locate": lambda self: None})())
    monkeypatch.setattr(amigaparty, "read_party", lambda target: [Member()])
    live = curseadd.read_live("holder")
    assert made[0].call_seconds is curseadd.PIPE_CALLS and live[0]["name"] == "GALAIN"


def test_drive_puts_the_pipe_call_durations_in_the_receipt(tmp_path):
    screens, _ = _screens(tmp_path, ROUTE_ONE)
    manifest = _manifest(tmp_path, ["ROSALIND"])

    def reader(holder):
        curseadd.PIPE_CALLS.extend([0.5, 29.0])
        return _live("GALAIN", "HOLLAND", "ROSALIND")

    found = curseadd.drive(screens, manifest, "holder", reader)
    assert found["pipe_call_seconds"] == [0.5, 29.0]


def test_a_party_read_that_hangs_still_reports_the_calls_it_made(tmp_path, monkeypatch):
    screens, _ = _screens(tmp_path, ROUTE_ONE)
    monkeypatch.setattr(curseadd, "READ_LIMIT", 0.2)
    never = threading.Event()

    def reader(holder):
        curseadd.PIPE_CALLS.append(0.7)
        never.wait()

    try:
        with pytest.raises(RouteError, match=r"no answer in .*pipe calls took \[0\.7\] s"):
            curseadd.drive(screens, _manifest(tmp_path, ["ROSALIND"]), "holder", reader)
    finally:
        never.set()
